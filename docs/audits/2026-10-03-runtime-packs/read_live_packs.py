"""Read live Packs and rebuild into an isolated repo directory for comparison."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.constants import INTERNAL_FEATURE_PACK_NAMES
from backend.game_data import _collect_effective_rows, _table_row_key, parse_db_table
from backend.game_data_patch_state import ensure_game_data_patch
from backend.models import ModAsset
from backend.scanner import read_pack_type
from backend.schema_update import decode_table, installed_definitions
from backend.start_options import GAME_DATA_PATCH_NAME, collect_game_data_source_snapshot, read_pack_entries
from backend.table_schema import load_latest_schema


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, default=Path("G:/Wyccc's Mod Manager/data"))
    args = parser.parse_args()
    settings = json.loads((args.state_dir / "settings.json").read_text(encoding="utf-8"))
    data = Path(settings["game_installations"]["warhammer3"]["game_path"]) / "data"
    inventory = []
    for path in sorted(data.glob("*wyccc*.pack")):
        if path.name.casefold() not in INTERNAL_FEATURE_PACK_NAMES:
            continue
        inventory.append({"name": path.name, "type": read_pack_type(path), "size": path.stat().st_size,
            "sha256": sha256(path), "entries": [entry.name for entry in read_pack_entries(path)]})
    original = data / GAME_DATA_PATCH_NAME
    original_hash = sha256(original)
    manifest = json.loads((args.state_dir / "runtime" / "!!!!wyccc_game_data_patch.json").read_text(encoding="utf-8"))
    inputs = manifest["inputs"]
    assets, ids = {}, []
    for index, record in enumerate(inputs["sources"]):
        if record.get("role") != "explicit":
            continue
        path = Path(record["file"]["path"])
        mod_id = f"audit:{index}"
        assets[mod_id] = ModAsset(id=mod_id, pack_name=path.name, display_name=path.stem,
            path=str(path), directory=str(path.parent), source=record["source"],
            workshop_id=record.get("workshop_id", ""))
        ids.append(mod_id)
    with tempfile.TemporaryDirectory(prefix="runtime-pack-readback-", dir="build") as temporary:
        output = Path(temporary)
        result = ensure_game_data_patch(output, data, assets, ids, inputs["playset_id"],
            inputs["settings"], inputs["subscription_state"])
        rebuilt = Path(result["path"])
        entries = read_pack_entries(rebuilt)
        tables = {entry.name.split("\\")[1] for entry in entries}
        snapshot = collect_game_data_source_snapshot(data, assets, ids)
        effective = _collect_effective_rows(snapshot.sources, tables)
        schemas, _ = load_latest_schema("warhammer3", output / "schemas", prefer_bundled=True)
        installed = installed_definitions(data, tables, schemas)
        permitted_fields = {"main_units_tables": {"num_men", "campaign_cap"},
            "land_units_tables": {"num_mounts", "num_engines", "rank_depth", "bonus_hit_points"},
            "projectiles_tables": {"can_damage_allies"},
            "projectiles_explosions_tables": {"affects_allies"},
            "battle_vortexs_tables": {"affects_allies"}}
        records, unrelated_changes, missing_originals, keys = [], [], [], set()
        for entry in entries:
            table = entry.name.split("\\")[1]
            parsed = parse_db_table(table, entry.payload)
            definition, full_rows, _ = decode_table(entry.payload, schemas[table])
            assert len(parsed.rows) == len(full_rows)
            records.append({"table": table, "version": parsed.version, "rows": len(parsed.rows),
                "installed_version": installed[table]["version"],
                "rpfm_schema_version": definition["version"]})
            if table == "_kv_rules_tables":
                continue  # this table deliberately emits only the affected rules
            for row in parsed.rows:
                key = _table_row_key(table, row)
                assert (table, key) not in keys, "duplicate generated primary key"
                keys.add((table, key))
                candidate = effective[table].get(key)
                if candidate is None:
                    missing_originals.append((table, key))
                    continue
                for field, span in row.fields.items():
                    if field in permitted_fields.get(table, set()):
                        continue
                    previous = candidate.row.fields[field]
                    if row.raw[span.start:span.end] != candidate.row.raw[previous.start:previous.end]:
                        unrelated_changes.append((table, key, field))
        results = {"inventory": inventory, "source_mods": len(ids), "generated_tables": records,
            "rebuilt_sha256": sha256(rebuilt), "live_data_sha256": original_hash,
            "live_runtime_sha256": sha256(args.state_dir / "runtime" / GAME_DATA_PATCH_NAME),
            "manifest_sha256": manifest["output"]["sha256"],
            "rebuilt_matches_live_data": sha256(rebuilt) == original_hash,
            "unrelated_field_changes": len(unrelated_changes), "missing_original_rows": len(missing_originals),
            "live_data_unchanged_during_audit": sha256(original) == original_hash}
        assert not unrelated_changes and not missing_originals
        assert results["live_data_unchanged_during_audit"]
    Path(__file__).with_name("live-readback.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in results.items() if key != "inventory"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
