from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from backend.api import API
from backend.constants import VARIANT_SELECTOR_FEATURE_PACK_NAME
from backend.game_data import DbSource, GameDataEntry, parse_db_table
from backend.models import GamePaths
from backend.scanner import ModScanner
from backend.start_options import (
    VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME,
    read_pack_entries,
)
from backend.variant_selector_compatibility import (
    VARIANT_SELECTOR_FRAMEWORK_SCRIPT,
    VARIANT_SELECTOR_SCRIPT_NAME,
    _build_lua_script,
    _lua_string,
    build_variant_selector_compatibility_entries,
)
from backend.variant_selector_patch_state import ensure_variant_selector_compatibility_patch
from tests.helpers import make_asset, write_pack
from tests.test_dynamic_ror_compatibility import _table_payload
from tests.test_scanner import OfflineWorkshopMetadata


def character_entries(
    appearances: dict[str, list[str]], *, internal_name: str = "data__",
) -> tuple[GameDataEntry, ...]:
    sets, arts, uniforms, variants = [], [], [], []
    for subtype, keys in appearances.items():
        for key in keys:
            sets.append({"art_set_id": key, "agent_subtype": subtype, "agent_type": "champion"})
            arts.append({"art_set_id": key, "uniform": key, "id": len(arts) + 1})
            uniforms.append({"uniform_name": key, "filename": key})
            variants.append({"variant_name": key, "variant_filename": key})
    return tuple(
        GameDataEntry(
            f"db\\{name}\\{internal_name}",
            _table_payload(name, version, rows),
        )
        for name, version, rows in (
            ("campaign_character_art_sets_tables", 7, sets),
            ("campaign_character_arts_tables", 0, arts),
            ("agent_uniforms_tables", 10, uniforms),
            ("variants_tables", 6, variants),
        )
    )


def pack_entries(entries):
    return [(entry.name, entry.payload) for entry in entries]


def test_includes_single_appearance_and_skips_battle_only_rows():
    built = build_variant_selector_compatibility_entries([
        DbSource("vanilla", character_entries({
            "single": ["single_art"],
            "multi": ["z_art", "a_art"],
            "hero": ["hero_art", "hero_qb_general"],
            "questing_knight": ["questing_knight_art"],
            "quick_battle_only": ["qb_art"],
        }), role="vanilla"),
    ])
    script = built.entries[0].payload.decode()
    assert built.entries[0].name == VARIANT_SELECTOR_SCRIPT_NAME
    assert '["single"] = {"single_art"}' in script
    assert '["multi"] = {"a_art", "z_art"}' in script
    assert '["hero"] = {"hero_art"}' in script
    assert '["questing_knight"] = {"questing_knight_art"}' in script
    assert "qb_art" not in script
    assert built.stats["candidate_subtype_count"] == 4
    assert built.stats["battle_only_art_set_rows"] == 2


@pytest.mark.parametrize("missing_table", [1, 2, 3])
def test_requires_complete_appearance_chain(missing_table):
    entries = character_entries({"hero": ["art"]})
    built = build_variant_selector_compatibility_entries([
        DbSource("broken", [e for i, e in enumerate(entries) if i != missing_table]),
    ])
    assert not built.entries
    assert built.stats["invalid_art_set_rows"] == 1


def test_all_arts_rows_are_considered_and_versionless_current_table_is_supported():
    entries = list(character_entries({"hero": ["art"]}))
    payload = _table_payload("campaign_character_arts_tables", 0, [
        {"art_set_id": "art", "id": 1, "uniform": "missing"},
        {"art_set_id": "art", "id": 0, "uniform": "art"},
    ])[8:]  # The installed WH3 table omits its version marker.
    assert parse_db_table("campaign_character_arts_tables", payload).version == 0
    entries[1] = GameDataEntry(entries[1].name, payload)
    result = build_variant_selector_compatibility_entries([DbSource("mod", entries)])
    assert result.stats["candidate_subtype_count"] == 1


def test_effective_db_names_then_pack_order_then_vanilla_fallback():
    base = character_entries({"original": ["art"]}, internal_name="!!!!vanilla")
    low = character_entries({"low": ["art"]}, internal_name="z_low")
    high = character_entries({"winner": ["art"]}, internal_name="!high")
    result = build_variant_selector_compatibility_entries([
        DbSource("low pack first", low),
        DbSource("high internal name", high),
        DbSource("base", base, role="vanilla"),
    ])
    script = result.entries[0].payload.decode()
    assert '["winner"] = {"art"}' in script
    assert '["original"]' not in script and '["low"]' not in script
    tie = character_entries({"first_pack": ["art"]}, internal_name="!high")
    result = build_variant_selector_compatibility_entries([
        DbSource("first", tie), DbSource("second", high), DbSource("base", base, role="vanilla"),
    ])
    assert '["first_pack"] = {"art"}' in result.entries[0].payload.decode()


def prepare_sources(root: Path):
    data = root / "data"
    write_pack(data / "db.pack", entries=pack_entries(character_entries({"base": ["base_art"]})))
    framework = write_pack(
        root / "mods" / "renamed_framework.pack", byte_mask=3,
        entries=[(VARIANT_SELECTOR_FRAMEWORK_SCRIPT, b"-- framework")],
    )
    characters = write_pack(
        root / "mods" / "characters.pack", byte_mask=3,
        entries=pack_entries(character_entries({"mod_hero": ["mod_art"]})),
    )
    assets = {
        "framework": make_asset(framework, "framework", "workshop"),
        "characters": make_asset(characters, "characters", "workshop"),
    }
    return data, assets


def ensure(root, data, assets, ids, *, subscribed=True, settings=None):
    return ensure_variant_selector_compatibility_patch(
        root / "runtime", data, assets, ids, "playset",
        settings if settings is not None else {
            "variant_selector_compatibility_patch_enabled": True,
        },
        subscribed=subscribed,
    )


def test_subscription_default_on_framework_gate_cache_and_stale_cleanup(tmp_path):
    data, assets = prepare_sources(tmp_path)
    ids = list(assets)
    disabled = ensure(tmp_path, data, assets, ids, subscribed=False)
    assert disabled["reason"] == "patch_not_subscribed"
    assert not disabled["path"]
    generated = ensure(tmp_path, data, assets, ids)
    assert generated["status"] == "generated"
    entries = read_pack_entries(Path(generated["path"]))
    assert [entry.name for entry in entries] == [VARIANT_SELECTOR_SCRIPT_NAME]
    assert b'["mod_hero"] = {"mod_art"}' in entries[0].payload
    assert ensure(tmp_path, data, assets, ids)["status"] == "reused"
    # Damaging only the generated cache must cause regeneration.
    Path(generated["path"]).write_bytes(b"bad cache")
    assert ensure(tmp_path, data, assets, ids)["status"] == "generated"
    no_framework = ensure(tmp_path, data, assets, ["characters"])
    assert not no_framework["path"]
    assert no_framework["reason"] == "variant_selector_not_enabled"
    assert not (tmp_path / "runtime" / VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME).exists()
    assert ensure(tmp_path, data, assets, ids)["path"]
    assert not ensure(tmp_path, data, assets, ids, subscribed=False)["path"]
    assert ensure(tmp_path, data, assets, ids)["path"]
    assert not ensure(tmp_path, data, assets, ids, settings={
        "variant_selector_compatibility_patch_enabled": False,
    })["path"]


def test_fingerprint_tracks_art_changes_mod_removal_and_auto_movie_sources(tmp_path):
    data, assets = prepare_sources(tmp_path)
    ids = list(assets)
    first = ensure(tmp_path, data, assets, ids)
    write_pack(
        Path(assets["characters"].path), byte_mask=3,
        entries=pack_entries(character_entries({"mod_hero": ["new_art"]})),
    )
    changed = ensure(tmp_path, data, assets, ids)
    assert changed["status"] == "generated"
    assert changed["fingerprint"] != first["fingerprint"]
    removed = ensure(tmp_path, data, assets, ["framework"])
    script = read_pack_entries(Path(removed["path"]))[0].payload
    assert b"new_art" not in script
    write_pack(
        data / "automatic.pack", byte_mask=4,
        entries=pack_entries(character_entries({"movie_hero": ["movie_art"]})),
    )
    automatic = ensure(tmp_path, data, assets, ["framework"])
    assert b'movie_art' in read_pack_entries(Path(automatic["path"]))[0].payload


def test_source_change_during_generation_retries(tmp_path, monkeypatch):
    from backend import variant_selector_patch_state as state

    data, assets = prepare_sources(tmp_path)
    original = state.build_variant_selector_compatibility_patch
    calls = []

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calls:
            write_pack(
                Path(assets["characters"].path), byte_mask=3,
                entries=pack_entries(character_entries({"updated": ["updated_art"]})),
            )
        calls.append(True)
        return result

    monkeypatch.setattr(state, "build_variant_selector_compatibility_patch", changing)
    result = ensure(tmp_path, data, assets, list(assets))
    assert len(calls) == 2
    assert b'updated_art' in read_pack_entries(Path(result["path"]))[0].payload


def test_marker_is_hidden_and_framework_detection_survives_renaming(tmp_path):
    data, assets = prepare_sources(tmp_path)
    workshop = tmp_path / "workshop"
    write_pack(workshop / "12345" / VARIANT_SELECTOR_FEATURE_PACK_NAME.upper())
    write_pack(data / VARIANT_SELECTOR_FEATURE_PACK_NAME)
    write_pack(data / VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME)
    paths = GamePaths(data_path=str(data), workshop_path=str(workshop))
    assert API._variant_selector_feature_status(paths)["subscribed"]
    scan = ModScanner(OfflineWorkshopMetadata()).scan(paths, {"fetch_workshop_metadata": False})
    assert [mod.pack_name for mod in scan.mods] == [
        VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME,
        VARIANT_SELECTOR_FEATURE_PACK_NAME,
    ]
    assert all(mod.hidden for mod in scan.mods)
    assert scan.mods[0].display_name == "Variant Selector Compatibility Patch"
    framework = ModScanner._make_asset(Path(assets["framework"].path), "workshop")
    assert framework.provides_variant_selector
    assert not API._variant_selector_feature_status(
        GamePaths(game_id="three_kingdoms", workshop_path=str(workshop)),
    )["subscribed"]


def test_marker_artifact_and_source_metadata_agree():
    directory = Path(__file__).resolve().parents[1] / "mods" / "wyccc_variant_selector_patch"
    metadata = json.loads((directory / "feature.json").read_text(encoding="utf-8"))
    entries = read_pack_entries(directory / VARIANT_SELECTOR_FEATURE_PACK_NAME)
    assert len(entries) == 1
    assert json.loads(entries[0].payload) == metadata
    assert metadata["title"] == "Dynamic Variant Selector Patch"


def test_workshop_cover_matches_project_standard():
    directory = Path(__file__).resolve().parents[1] / "mods" / "wyccc_variant_selector_patch"
    cover = directory / "cover.png"
    sibling = directory / "wyccc_variant_selector_patch.png"
    assert cover.is_file() and sibling.is_file()
    assert cover.read_bytes() == sibling.read_bytes()
    assert cover.stat().st_size <= 1_024 * 1_024
    with Image.open(cover) as image:
        assert image.format == "PNG"
        assert image.size == (500, 500)


def test_launch_includes_generated_patch_without_enabling_marker_then_removes_it(tmp_path, monkeypatch):
    from backend import api as api_module
    from tests.test_storage_and_api import ApiContractTests

    api, _ = ApiContractTests._prepare_launch_api(tmp_path)
    data = tmp_path / "Total War WARHAMMER III" / "data"
    workshop = tmp_path / "workshop"
    marker = write_pack(workshop / "12345" / VARIANT_SELECTOR_FEATURE_PACK_NAME)
    write_pack(
        workshop / "2888171970" / "renamed.pack", byte_mask=3,
        entries=[(VARIANT_SELECTOR_FRAMEWORK_SCRIPT, b"-- framework")],
    )
    write_pack(data / "db.pack", entries=pack_entries(character_entries({"base": ["base_art"]})))
    assert api.call("save_settings", [{"workshop_path": str(workshop)}])["ok"]
    assert api.call("save_compatibility_patch_settings", [{
        "variant_selector_compatibility_patch_enabled": True,
    }])["ok"]
    scan = api.call("scan_mods", [False])
    assert scan["ok"]
    assert scan["data"]["variant_selector_feature"]["subscribed"]
    ids = [
        mod["id"]
        for mod in scan["data"]["mods"]
        if mod["pack_name"].casefold() != VARIANT_SELECTOR_FEATURE_PACK_NAME.casefold()
    ]
    assert len(ids) == 1
    monkeypatch.setattr(api_module, "query_workshop_subscription_status", lambda *a, **k: [])
    monkeypatch.setattr(api_module, "launch_game", lambda *a, **k: {"pid": 123, "argument": ""})
    monkeypatch.setattr(api, "set_game_running", lambda *a, **k: None)
    launched = api.call("launch_game", [ids, scan["data"]["order_token"]])
    assert launched["ok"], launched
    launch_ids = launched["data"]["launch_plan"]["ordered_mod_ids"]
    assert launch_ids == ["runtime:variant-selector-compatibility", *ids]
    assert (data / VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME).is_file()
    marker.unlink()
    scan = api.call("scan_mods", [False])
    launched = api.call("launch_game", [ids, scan["data"]["order_token"]])
    assert launched["ok"], launched
    assert launched["data"]["launch_plan"]["ordered_mod_ids"] == ids
    assert not (data / VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME).exists()
    assert not (api.data_dir / "runtime" / VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME).exists()


def test_saving_nanu_preference_does_not_reset_variant_selector(tmp_path):
    api = API(tmp_path / "state")
    assert api.settings_service.get_public()["variant_selector_compatibility_patch_enabled"]
    result = api.call("save_compatibility_patch_settings", [{
        "variant_selector_compatibility_patch_enabled": "false",
    }])
    assert result["ok"]
    result = api.call("save_compatibility_patch_settings", [{
        "dynamic_ror_compatibility_patch_enabled": True,
    }])
    assert result["ok"]
    assert not result["data"]["settings"]["variant_selector_compatibility_patch_enabled"]
    assert result["data"]["settings"]["dynamic_ror_compatibility_patch_enabled"]
    assert api._is_internal_feature_mod_id(
        "steam:12345:WYCCC_VARIANT_SELECTOR_PATCH.PACK",
    )


def test_generated_lua_strings_roundtrip_control_characters_and_literal_escapes():
    lua = shutil.which("lua")
    if not lua:
        pytest.skip("Lua interpreter is needed for generated-string validation")
    value = 'art"\\u0022\\path\n\r\t\x00\x1b\x7f'
    script = f'local s = {_lua_string(value)}; for i=1,#s do io.write(string.format("%02x", s:byte(i))) end'
    result = subprocess.run([lua, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == value.encode().hex()


def test_runtime_with_lua_preserves_adaptations_and_restores_stable_art_ids(tmp_path):
    lua = shutil.which("lua")
    if not lua:
        pytest.skip("Lua interpreter is needed for the campaign runtime harness")
    common = {"single": ["single_art"], "manual": ["hidden_art"], "empty": ["empty_art"], "late": ["late_art"]}
    paths = []
    for name, variants in (
        ("initial", ["b_art", "z_art"]),
        ("reordered", ["a_art", "b_art", "z_art"]),
        ("removed", ["a_art", "b_art"]),
    ):
        path = tmp_path / f"{name}.lua"
        path.write_bytes(_build_lua_script({**common, "new": variants}))
        paths.append(str(path))
    harness = Path(__file__).parent / "fixtures" / "variant_selector_runtime_harness.lua"
    result = subprocess.run([lua, str(harness), *paths], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all runtime checks passed" in result.stdout
