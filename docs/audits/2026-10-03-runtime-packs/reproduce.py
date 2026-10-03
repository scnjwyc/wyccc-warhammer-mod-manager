"""Isolated audit of generated Packs; never launches a game or writes live Data."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import lzma
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.api import API
from backend.constants import INTERNAL_RUNTIME_PACK_NAMES
from backend.game_data import CURRENT_TABLE_VERSIONS, parse_db_table
from backend.scanner import read_pack_type
import backend.start_options as start_options
from backend.start_options import GAME_DATA_PATCH_NAME, UNIT_DATA_PATCH_NAME, PackEntry, read_pack_entries, write_pfh5_pack
from backend.unit_data_state import save_unit_data_edits
from tests.test_game_data import _kv_rules_payload, _table_payload


def fixture(root: Path) -> tuple[API, Path]:
    game = root / "game"
    data = game / "data"
    data.mkdir(parents=True)
    (game / "Warhammer3.exe").write_bytes(b"")
    (data / "manifest.txt").write_text("db.pack\t0\n", encoding="utf-8")
    entries = [
        PackEntry("db\\main_units_tables\\data__", _table_payload("main_units_tables",
            CURRENT_TABLE_VERSIONS["main_units_tables"], [{"unit": "wyccc_audit_unit",
                "land_unit": "wyccc_audit_land", "num_men": 100, "campaign_cap": -1,
                "caste": "melee_infantry", "in_encyclopedia": True}])),
        PackEntry("db\\land_units_tables\\data__", _table_payload("land_units_tables",
            CURRENT_TABLE_VERSIONS["land_units_tables"], [{"key": "wyccc_audit_land",
                "category": "infantry", "class": "inf_melee", "rank_depth": 5}])),
        PackEntry("db\\_kv_rules_tables\\data__", _kv_rules_payload([
            ("unit_max_drag_width", 150.0)])),
    ]
    write_pfh5_pack(data / "db.pack", entries, pack_header_mask=0)
    api = API(root / "state")
    api.settings_service.save({"game_path": str(game), "workshop_path": "",
        "fetch_workshop_metadata": False, "live_mod_detection": False,
        "unit_model_multiplier": 2, "disable_unit_friendly_fire": False,
        "disable_spell_friendly_fire": False, "custom_battle_all_units_as_lords": False,
        "skip_intro_movies": False, "enable_script_logging": False,
        "dynamic_ror_compatibility_patch_enabled": False,
        "variant_selector_compatibility_patch_enabled": False})
    return api, data


def launch_fixture(api: API, ids: list[str]) -> tuple[dict, int]:
    scan = api._scan_mods(False)
    with (patch.object(api, "detect_game_running", return_value=False),
        patch.object(api, "_resolve_game_data_subscription_state", return_value={"3765783838": True}),
        patch.object(api, "set_game_running"),
        patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}) as launch):
        result = api.call("launch_game", [ids, scan["order_token"]])
    return result, launch.call_count


def unit_count(path: Path) -> int:
    for entry in read_pack_entries(path, "db\\main_units_tables\\"):
        rows = parse_db_table("main_units_tables", entry.payload).rows
        for row in rows:
            if row.values["unit"] == "wyccc_audit_unit":
                return int(row.values["num_men"])
    raise AssertionError("audit unit missing")


def older_decoder():
    source = subprocess.check_output(["git", "show", "8b5c910:backend/start_options.py"],
        encoding="utf-8")
    node = next(node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_decompress_payload")
    namespace = dict(vars(start_options))
    exec(compile(ast.Module(body=[node], type_ignores=[]), "1.1.5/start_options.py", "exec"), namespace)
    return namespace["_decompress_payload"]


def legacy_lzma(root: Path) -> dict:
    api, data = fixture(root)
    try:
        payload = _table_payload("main_units_tables", CURRENT_TABLE_VERSIONS["main_units_tables"],
            [{"unit": "wyccc_audit_unit", "land_unit": "wyccc_audit_land", "num_men": 80,
                "campaign_cap": -1, "caste": "melee_infantry"}])
        filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 1024 * 1024, "lc": 3, "lp": 0, "pb": 2}]
        compressed = struct.pack("<IBI", len(payload), 93, 1024 * 1024) + lzma.compress(
            payload, format=lzma.FORMAT_RAW, filters=filters)
        path = write_pfh5_pack(data / "old_lzma_mod.pack", [
            PackEntry("db\\main_units_tables\\!audit", compressed)])
        content = bytearray(path.read_bytes())
        content[32] = 1  # first PFH5 index entry's compression flag
        path.write_bytes(content)
        scan = api._scan_mods(False)
        mod_id = next(mod["id"] for mod in scan["mods"] if mod["pack_name"] == path.name)
        with patch("backend.start_options._decompress_payload", older_decoder()):
            before, before_launches = launch_fixture(api, [mod_id])
        after, after_launches = launch_fixture(api, [mod_id])
        assert not before["ok"] and before_launches == 0, before
        assert after["ok"] and after_launches == 1, after
        count = unit_count(data / GAME_DATA_PATCH_NAME)
        assert count == 160, count
        return {"legacy_version": "1.1.5", "legacy_started_processes": before_launches,
            "legacy_error": before.get("error"), "current_started_mock_processes": after_launches,
            "current_unit_count": count, "current_safety_passed": True}
    finally:
        api.close()


def renamed_copy(root: Path) -> dict:
    api, data = fixture(root)
    try:
        first, _ = launch_fixture(api, [])
        assert first["ok"], first
        original = data / GAME_DATA_PATCH_NAME
        assert unit_count(original) == 200
        duplicate = data / "!!!!wyccc_game_data_patch (1).pack"
        shutil.copy2(original, duplicate)
        scan = api._scan_mods(False)
        copied = next(mod for mod in scan["mods"] if mod["pack_name"] == duplicate.name)
        second, _ = launch_fixture(api, [copied["id"]])
        assert second["ok"], second
        names = second["data"]["launch_plan"]["pack_names"]
        count = unit_count(original)
        assert count == 200 and duplicate.name not in names and original.name in names
        api.settings_service.save({"unit_model_multiplier": 1})
        disabled, _ = launch_fixture(api, [copied["id"]])
        assert disabled["ok"], disabled
        still_loaded = duplicate.name in disabled["data"]["launch_plan"]["pack_names"]
        assert not original.exists() and duplicate.exists() and not still_loaded
        return {"copied_file_hidden": copied["hidden"], "base_count": 100,
            "first_2x_count": 200, "count_after_renamed_copy_enabled": count,
            "loaded_pack_names": names,
            "canonical_removed_when_disabled": not original.exists(),
            "renamed_copy_still_loaded_when_disabled": still_loaded,
            "safety_passed": copied["hidden"] and count == 200 and not still_loaded}
    finally:
        api.close()


def atomic_and_fixed_names(root: Path) -> dict:
    stage_api = API.__new__(API)
    data = root / "data"
    data.mkdir(parents=True)
    generated = root / "runtime"
    for name in INTERNAL_RUNTIME_PACK_NAMES:
        source = write_pfh5_pack(generated / name, [PackEntry("audit/test", b"first")])
        stage_api._stage_runtime_pack_in_data(str(source), data, name)
        write_pfh5_pack(source, [PackEntry("audit/test", b"second")])
        stage_api._stage_runtime_pack_in_data(str(source), data, name)
    target = generated / GAME_DATA_PATCH_NAME
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    with patch("backend.start_options.os.replace", side_effect=OSError("audit interrupted write")):
        try:
            write_pfh5_pack(target, [PackEntry("audit/test", b"partial replacement")])
        except OSError:
            pass
        else:
            raise AssertionError("injected interruption did not fire")
    after = hashlib.sha256(target.read_bytes()).hexdigest()
    count = len(list(data.glob("*.pack")))
    types = sorted({read_pack_type(path) for path in data.glob("*.pack")})
    temporary = list(generated.glob("*.tmp")) + list(data.glob("*.tmp"))
    assert before == after and count == 5 and types == ["mod"] and not temporary
    for name in INTERNAL_RUNTIME_PACK_NAMES:
        stage_api._stage_runtime_pack_in_data("", data, name)
    cleaned = not list(data.glob("*.pack"))
    assert cleaned
    return {"pack_families": count, "generated_types": types, "interrupted_output_preserved": before == after,
        "leftover_temporary_files": len(temporary), "disabled_canonical_files_cleaned": cleaned,
        "safety_passed": True}


def symlink_cleanup(root: Path) -> dict:
    data = root / "data"
    data.mkdir(parents=True)
    outside = (root / "user-file-outside-data.txt").resolve()
    outside.write_text("audit original", encoding="utf-8")
    target = data / GAME_DATA_PATCH_NAME
    try:
        target.symlink_to(outside)
    except OSError as exc:
        return {"skipped": True, "reason": f"symlink creation unavailable: WinError {exc.winerror}"}
    API._stage_runtime_pack_in_data(None, "", data, GAME_DATA_PATCH_NAME)
    deleted = not outside.exists()
    link_remains = target.is_symlink()
    assert not deleted and not link_remains
    return {"outside_data_file_deleted": deleted, "dangling_symlink_remains": link_remains,
        "safety_passed": not deleted and not link_remains}


def unsupported_schema(root: Path) -> dict:
    api, data = fixture(root)
    try:
        source = write_pfh5_pack(data / "unknown-schema.pack", [PackEntry(
            "db\\main_units_tables\\audit", b"\xfc\xfd\xfe\xff" + struct.pack("<iBi", 999, 1, 0))])
        scan = api._scan_mods(False)
        mod_id = next(mod["id"] for mod in scan["mods"] if mod["pack_name"] == source.name)
        result, calls = launch_fixture(api, [mod_id])
        assert not result["ok"] and calls == 0, result
        return {"started_processes": calls, "error": result.get("error"), "safety_passed": True}
    finally:
        api.close()


def unit_source_changes_during_build(root: Path) -> dict:
    api, data = fixture(root)
    try:
        api.settings_service.save({"unit_model_multiplier": 1})
        source = data / "updating-mod.pack"

        def replace_source(entity: str, health: int):
            write_pfh5_pack(source, [
                PackEntry("db\\land_units_tables\\!audit", _table_payload("land_units_tables",
                    CURRENT_TABLE_VERSIONS["land_units_tables"], [{"key": "wyccc_audit_land",
                        "man_entity": entity, "bonus_hit_points": health, "melee_attack": 10,
                        "category": "infantry", "class": "inf_melee", "rank_depth": 5}])),
                PackEntry("db\\battle_entities_tables\\!audit", _table_payload("battle_entities_tables",
                    CURRENT_TABLE_VERSIONS["battle_entities_tables"], [{"key": entity, "hit_points": 100}])),
            ])

        replace_source("wyccc_audit_entity_old", 1111)
        save_unit_data_edits(api.data_dir / "runtime", {"wyccc_audit_unit": {"melee_attack": 50}})
        scan = api._scan_mods(False)
        mod_id = next(mod["id"] for mod in scan["mods"] if mod["pack_name"] == source.name)
        builder = start_options.build_unit_data_patch

        builder_calls = 0

        def build_then_update(*args, **kwargs):
            nonlocal builder_calls
            built = builder(*args, **kwargs)
            builder_calls += 1
            if builder_calls == 1:
                replace_source("wyccc_audit_entity_new", 2222)
            return built

        with patch("backend.unit_data_state.build_unit_data_patch", side_effect=build_then_update):
            result, launches = launch_fixture(api, [mod_id])
        assert result["ok"] and launches == 1, result
        output = read_pack_entries(data / UNIT_DATA_PATCH_NAME)
        land = next(parse_db_table("land_units_tables", entry.payload).rows[0].values
            for entry in output if entry.name.startswith("db\\land_units_tables\\"))
        source_entities = {row.values["key"]
            for entry in read_pack_entries(source, "db\\battle_entities_tables\\")
            for row in parse_db_table("battle_entities_tables", entry.payload).rows}
        patch_entities = {row.values["key"]
            for entry in output if entry.name.startswith("db\\battle_entities_tables\\")
            for row in parse_db_table("battle_entities_tables", entry.payload).rows}
        unresolved = land["man_entity"] not in source_entities | patch_entities
        stale_health = land["bonus_hit_points"] != 2222
        assert not unresolved and not stale_health and land["melee_attack"] == 50
        return {"started_mock_processes": launches, "builder_calls": builder_calls,
            "requested_melee_attack": land["melee_attack"],
            "generated_bonus_health": land["bonus_hit_points"], "current_source_bonus_health": 2222,
            "generated_entity_reference": land["man_entity"],
            "current_source_entity_keys": sorted(source_entities), "patch_entity_keys": sorted(patch_entities),
            "unresolved_entity_reference": unresolved, "safety_passed": not unresolved and not stale_health}
    finally:
        api.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # Expected guarded failures are captured in the result instead of duplicating tracebacks.
    api_logger = logging.getLogger("backend.api")
    api_logger.addHandler(logging.NullHandler())
    api_logger.propagate = False
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert-safe", action="store_true")
    args = parser.parse_args()
    checks = [("legacy_lzma", legacy_lzma), ("renamed_copy", renamed_copy),
        ("atomic_and_fixed_names", atomic_and_fixed_names), ("symlink_cleanup", symlink_cleanup),
        ("unsupported_schema", unsupported_schema),
        ("unit_source_changes_during_build", unit_source_changes_during_build)]
    results = {}
    with tempfile.TemporaryDirectory(prefix="runtime-pack-audit-", dir="build") as temporary:
        with patch("backend.api.is_game_running", return_value=False):
            for name, check in checks:
                results[name] = check(Path(temporary) / name)
    output = Path(__file__).with_name("reproduction.json")
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    unsafe = [name for name, result in results.items() if result.get("safety_passed") is False]
    print("Unsafe checks:", ", ".join(unsafe) or "none")
    return 1 if args.assert_safe and unsafe else 0


if __name__ == "__main__":
    raise SystemExit(main())
