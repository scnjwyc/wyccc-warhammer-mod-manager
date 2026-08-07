from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.game_data import TABLE_SCHEMAS, DbSource, GameDataEntry, parse_db_table
from backend.dynamic_ror_compatibility import (
    build_dynamic_ror_compatibility_entries,
)
from backend.dynamic_ror_patch_state import (
    DYNAMIC_ROR_COMPATIBILITY_PATCH_NAME,
    build_dynamic_ror_compatibility_inputs,
    ensure_dynamic_ror_compatibility_patch,
    fingerprint_dynamic_ror_compatibility_inputs,
)
from backend.models import ModAsset
from backend.start_options import PackEntry, write_pfh5_pack


def _encode_value(field_type: str, value: Any) -> bytes:
    if field_type == "Boolean":
        return bytes([1 if value else 0])
    if field_type in {"I32", "ColourRGB"}:
        return struct.pack("<i", int(value or 0))
    if field_type == "I16":
        return struct.pack("<h", int(value or 0))
    if field_type == "I64":
        return struct.pack("<q", int(value or 0))
    if field_type == "F32":
        return struct.pack("<f", float(value or 0))
    if field_type == "F64":
        return struct.pack("<d", float(value or 0))
    if field_type == "StringU8":
        raw = str(value or "").encode("ascii")
        return struct.pack("<H", len(raw)) + raw
    if field_type == "OptionalStringU8":
        if value in {None, ""}:
            return b"\0"
        raw = str(value).encode("ascii")
        return b"\1" + struct.pack("<H", len(raw)) + raw
    if field_type == "StringU16":
        text = str(value or "")
        return struct.pack("<H", len(text)) + text.encode("utf-16le")
    raise AssertionError(f"unsupported fixture type: {field_type}")


def _table_payload(table_name: str, version: int, rows: list[dict[str, Any]]) -> bytes:
    schema = TABLE_SCHEMAS[table_name][version]
    encoded_rows = []
    for row in rows:
        encoded_rows.append(
            b"".join(_encode_value(field_type, row.get(name)) for name, field_type in schema)
        )
    return b"".join(
        (
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", version),
            b"\1",
            struct.pack("<i", len(encoded_rows)),
            *encoded_rows,
        )
    )


def _entry(table_name: str, rows: list[dict[str, Any]]) -> GameDataEntry:
    version = max(int(version) for version in TABLE_SCHEMAS[table_name])
    return GameDataEntry(
        f"db\\{table_name}\\data__",
        _table_payload(table_name, version, rows),
    )


def _melee_main(unit: str, land: str, *, caste: str = "infantry", cost: int = 500) -> dict[str, Any]:
    return {
        "unit": unit,
        "caste": caste,
        "land_unit": land,
        "num_men": 90,
        "multiplayer_cost": cost,
        "audio_voiceover_culture": "wh_main_emp",
    }


def _melee_land(land: str, *, category: str = "infantry", unit_class: str = "infantry") -> dict[str, Any]:
    return {
        "key": land,
        "category": category,
        "class": unit_class,
        "man_entity": "man_swordsmen",
        "armour": "wh2_main_body_10",
        "charge_bonus": 15,
        "num_mounts": 0,
        "num_engines": 0,
        "rank_depth": 3,
        "spacing": "infantry",
    }


def _ranged_main(unit: str, land: str) -> dict[str, Any]:
    return {**_melee_main(unit, land, cost=600), "num_men": 80}


def _ranged_land(land: str, weapon: str) -> dict[str, Any]:
    return {
        **_melee_land(land, category="infantry", unit_class="missile_infantry"),
        "primary_missile_weapon": weapon,
        "primary_ammo": 20,
    }


def _vanilla_source() -> DbSource:
    entries = [
        _entry(
            "main_units_tables",
            [
                _melee_main("wh_main_inf_swordsmen", "land_wh_main_inf_swordsmen"),
                _melee_main("wh_main_inf_archers", "land_wh_main_inf_archers", cost=400),
            ],
        ),
        _entry(
            "land_units_tables",
            [
                _melee_land("land_wh_main_inf_swordsmen"),
                _ranged_land("land_wh_main_inf_archers", "wh_main_missile_short_bow"),
            ],
        ),
        _entry(
            "missile_weapons_tables",
            [
                {
                    "key": "wh_main_missile_short_bow",
                    "default_projectile": "wh_main_projectile_arrow",
                }
            ],
        ),
        _entry(
            "projectiles_tables",
            [
                {
                    "key": "wh_main_projectile_arrow",
                    "category": "missile",
                    "damage": 5,
                    "ap_damage": 1,
                }
            ],
        ),
        _entry(
            "projectiles_explosions_tables",
            [{"key": "wh_main_explosion_arrow", "detonation_damage": 2}],
        ),
    ]
    return DbSource("db.pack", tuple(entries))


def _naru_source() -> DbSource:
    entries: list[GameDataEntry] = []
    main_rows: list[dict[str, Any]] = []
    land_rows: list[dict[str, Any]] = []
    effect_rows: list[dict[str, Any]] = []
    junction_rows: list[dict[str, Any]] = []
    for index in range(65):
        unit = f"naru_ror_inf_{index:03d}"
        land = f"land_naru_ror_inf_{index:03d}"
        main_rows.append(_melee_main(unit, land, cost=450 + index))
        land_rows.append(_melee_land(land))
        effect_rows.append(
            {
                "unit": unit,
                "purchasable_effect": f"wh_main_effect_dynamic_ror_inf_{index}",
                "is_exclusive": True,
            }
        )
        junction_rows.append(
            {
                "missile_weapon": "wh_main_missile_short_bow",
                "unit": unit,
                "id": 2_000_000_000 + index,
            }
        )
    # One ranged template carrying a scripted ammo effect.
    unit = "naru_ror_archers"
    land = "land_naru_ror_archers"
    main_rows.append(_ranged_main(unit, land))
    land_rows.append(_ranged_land(land, "wh_main_missile_short_bow"))
    effect_rows.append(
        {
            "unit": unit,
            "purchasable_effect": "wh_main_effect_dynamic_ror_archers",
            "is_exclusive": True,
        }
    )
    effect_rows.append(
        {
            "unit": unit,
            "purchasable_effect": "wh_main_effect_scripted_ammo_type_flaming",
            "is_exclusive": True,
        }
    )
    junction_rows.append(
        {
            "missile_weapon": "wh_main_missile_short_bow",
            "unit": unit,
            "id": 2_100_000_000,
        }
    )
    entries.extend(
        (
            _entry("main_units_tables", main_rows),
            _entry("land_units_tables", land_rows),
            _entry("unit_purchasable_effect_sets_tables", effect_rows),
            _entry("unit_missile_weapon_junctions_tables", junction_rows),
            _entry(
                "effect_bonus_value_missile_weapon_junctions_tables",
                [
                    {
                        "effect": "nanu_ammo_type_flaming",
                        "bonus_value_id": "wh_main_effect_scripted_ammo_type_flaming",
                        "missile_weapon_junction": 2_100_000_000,
                    }
                ],
            ),
        )
    )
    return DbSource("Nanu_s_Dynamic_RoRs.pack", tuple(entries))


def _mod_source() -> DbSource:
    entries = [
        _entry(
            "main_units_tables",
            [
                _melee_main("mod_inf_swordsmen", "land_mod_inf_swordsmen", cost=480),
                _ranged_main("mod_inf_archers", "land_mod_inf_archers"),
                _melee_main(
                    "mod_lord_generic",
                    "land_mod_lord_generic",
                    caste="lord",
                    cost=900,
                ),
            ],
        ),
        _entry(
            "land_units_tables",
            [
                _melee_land("land_mod_inf_swordsmen"),
                _ranged_land("land_mod_inf_archers", "wh_main_missile_short_bow"),
                _melee_land("land_mod_lord_generic", category="infantry", unit_class="infantry"),
            ],
        ),
    ]
    return DbSource("Mod_Units.pack", tuple(entries))


def _sources() -> tuple[DbSource, DbSource, DbSource]:
    return _naru_source(), _mod_source(), _vanilla_source()


def _rows_for(result: Any, table_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prefix = f"db\\{table_name}\\"
    for entry in result.entries:
        if entry.name.startswith(prefix):
            rows.extend(row.values for row in parse_db_table(table_name, entry.payload).rows)
    return rows


class DynamicRorCompatibilityGeneratorTests(unittest.TestCase):
    def test_missing_naru_mod_produces_no_patch(self) -> None:
        sources = (_mod_source(), _vanilla_source())
        result = build_dynamic_ror_compatibility_entries(sources)
        self.assertEqual(result.entries, ())
        self.assertEqual(result.stats["dynamic_ror_detected"], 0)

    def test_generates_effects_for_mod_units_only(self) -> None:
        result = build_dynamic_ror_compatibility_entries(_sources())
        self.assertEqual(result.stats["dynamic_ror_detected"], 1)
        self.assertGreaterEqual(result.stats["template_unit_count"], 64)
        self.assertEqual(result.stats["eligible_mod_unit_count"], 2)
        self.assertEqual(result.stats["patched_unit_count"], 2)

        effect_rows = _rows_for(result, "unit_purchasable_effect_sets_tables")
        patched_units = {row["unit"] for row in effect_rows}
        self.assertIn("mod_inf_swordsmen", patched_units)
        self.assertIn("mod_inf_archers", patched_units)
        self.assertNotIn("mod_lord_generic", patched_units)
        self.assertNotIn("wh_main_inf_swordsmen", patched_units)

    def test_ranged_unit_gets_ammo_variant_and_junction(self) -> None:
        result = build_dynamic_ror_compatibility_entries(_sources())
        self.assertGreaterEqual(result.stats["ammo_variant_count"], 1)
        self.assertGreaterEqual(result.stats["missile_junction_count"], 1)

        weapons = _rows_for(result, "missile_weapons_tables")
        self.assertEqual(len(weapons), 1)
        variant_weapon = weapons[0]
        variant_projectile_key = variant_weapon["default_projectile"]
        projectiles = _rows_for(result, "projectiles_tables")
        variant_projectiles = [
            row for row in projectiles if row["key"] == variant_projectile_key
        ]
        self.assertEqual(len(variant_projectiles), 1)
        self.assertEqual(variant_projectiles[0]["ignition_amount"], 100.0)
        self.assertFalse(variant_projectiles[0]["is_magical"])
        junctions = _rows_for(result, "unit_missile_weapon_junctions_tables")
        self.assertTrue(
            any(row["unit"] == "mod_inf_archers" for row in junctions),
            junctions,
        )
        mappings = _rows_for(result, "effect_bonus_value_missile_weapon_junctions_tables")
        self.assertTrue(mappings, mappings)

    def test_emits_lua_keyword_script(self) -> None:
        result = build_dynamic_ror_compatibility_entries(_sources())
        lua = [entry for entry in result.entries if entry.name.endswith(".lua")]
        self.assertEqual(len(lua), 1)
        payload = lua[0].payload.decode("utf-8")
        self.assertIn("Dynamic_RoR_Modded_Unit_Keywords", payload)
        self.assertIn("mod_inf_swordsmen", payload)
        self.assertIn("mod_inf_archers", payload)


class DynamicRorCompatibilityStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="wmm_dynamic_ror_")
        self.root = Path(self._temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _write_packs(self) -> None:
        write_pfh5_pack(
            self.data / "nanu_dynamic_rors.pack",
            [PackEntry(entry.name, entry.payload) for entry in _naru_source().entries],
        )
        write_pfh5_pack(
            self.data / "db.pack",
            [PackEntry(entry.name, entry.payload) for entry in _vanilla_source().entries],
        )
        write_pfh5_pack(
            self.data / "mod_units.pack",
            [PackEntry(entry.name, entry.payload) for entry in _mod_source().entries],
        )

    def _settings(self, enabled: bool) -> dict[str, Any]:
        return {"dynamic_ror_compatibility_patch_enabled": enabled}

    def test_disabled_removes_patch(self) -> None:
        self._write_packs()
        result = ensure_dynamic_ror_compatibility_patch(
            self.runtime,
            self.data,
            {},
            [],
            "default",
            self._settings(False),
        )
        self.assertEqual(result["status"], "zero_modification")
        self.assertFalse((self.runtime / DYNAMIC_ROR_COMPATIBILITY_PATCH_NAME).exists())

    def test_enabled_generates_and_reuses(self) -> None:
        self._write_packs()
        active_ids = ["nanu_dynamic_rors", "mod_units"]
        nanu_asset = ModAsset(
            id="nanu_dynamic_rors",
            pack_name="nanu_dynamic_rors.pack",
            display_name="Nanu Dynamic RoRs",
            path=str(self.data / "nanu_dynamic_rors.pack"),
            directory=str(self.data),
            source="data",
            sources=["data"],
        )
        asset = ModAsset(
            id="mod_units",
            pack_name="mod_units.pack",
            display_name="Mod Units",
            path=str(self.data / "mod_units.pack"),
            directory=str(self.data),
            source="data",
            sources=["data"],
        )
        assets = {"nanu_dynamic_rors": nanu_asset, "mod_units": asset}
        first = ensure_dynamic_ror_compatibility_patch(
            self.runtime,
            self.data,
            assets,
            active_ids,
            "default",
            self._settings(True),
        )
        self.assertEqual(first["status"], "generated")
        self.assertGreater(first["entry_count"], 0)
        self.assertGreaterEqual(first["stats"]["patched_unit_count"], 1)
        patch_path = self.runtime / DYNAMIC_ROR_COMPATIBILITY_PATCH_NAME
        self.assertTrue(patch_path.is_file())

        second = ensure_dynamic_ror_compatibility_patch(
            self.runtime,
            self.data,
            assets,
            active_ids,
            "default",
            self._settings(True),
        )
        self.assertEqual(second["status"], "reused")
        self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_inputs_fingerprint_changes_with_setting_and_sources(self) -> None:
        self._write_packs()
        base = build_dynamic_ror_compatibility_inputs(
            self.data,
            {},
            [],
            "default",
            self._settings(True),
        )
        changed_order = build_dynamic_ror_compatibility_inputs(
            self.data,
            {},
            ["mod_units"],
            "default",
            self._settings(True),
        )
        disabled = build_dynamic_ror_compatibility_inputs(
            self.data,
            {},
            [],
            "default",
            self._settings(False),
        )
        self.assertNotEqual(base["enabled"], disabled["enabled"])
        self.assertNotEqual(
            fingerprint_dynamic_ror_compatibility_inputs(base),
            fingerprint_dynamic_ror_compatibility_inputs(changed_order),
        )


if __name__ == "__main__":
    unittest.main()
