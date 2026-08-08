from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.game_data import (
    DbSource,
    GameDataEntry,
    THREE_KINGDOMS_TABLE_SCHEMAS,
    _entry_table_name,
    parse_db_table,
)
from backend.unit_data import build_unit_data_entries, build_unit_table_snapshot
from backend.unit_data_state import ensure_unit_data_patch, save_unit_data_edits


THREE_KINGDOMS = "three_kingdoms"


def _encode_value(field_type: str, value: Any) -> bytes:
    if field_type == "Boolean":
        return bytes([1 if value else 0])
    if field_type == "I32":
        return struct.pack("<i", int(value or 0))
    if field_type == "I64":
        return struct.pack("<q", int(value or 0))
    if field_type == "F32":
        return struct.pack("<f", float(value or 0))
    if field_type == "StringU8":
        raw = str(value or "").encode("ascii")
        return struct.pack("<H", len(raw)) + raw
    if field_type == "OptionalStringU8":
        if value in {None, ""}:
            return b"\0"
        raw = str(value).encode("ascii")
        return b"\1" + struct.pack("<H", len(raw)) + raw
    raise AssertionError(f"unsupported fixture type: {field_type}")


def _table_payload(table_name: str, version: int, rows: list[dict[str, Any]]) -> bytes:
    schema = THREE_KINGDOMS_TABLE_SCHEMAS[table_name][version]
    encoded_rows = [
        b"".join(_encode_value(field_type, row.get(name)) for name, field_type in schema)
        for row in rows
    ]
    return b"".join(
        (
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", version),
            b"\1",
            struct.pack("<i", len(encoded_rows)),
            *encoded_rows,
        )
    )


def _versionless_payload(rows: list[bytes]) -> bytes:
    return b"".join((b"\1", struct.pack("<i", len(rows)), *rows))


def _grouping_row(unit: str, group: str) -> bytes:
    return b"".join(
        struct.pack("<H", len(value)) + value.encode("ascii")
        for value in (unit, group)
    )


def _exclusive_row(unit: str, faction: str, allowed: bool) -> bytes:
    return b"".join(
        struct.pack("<H", len(value)) + value.encode("ascii")
        for value in (unit, faction)
    ) + bytes([1 if allowed else 0])


def _entry(table_name: str, payload: bytes) -> GameDataEntry:
    return GameDataEntry(f"db\\{table_name}\\data__", payload)


def _source() -> DbSource:
    return DbSource(
        "three_kingdoms_db.pack",
        (
            _entry(
                "main_units_tables",
                _table_payload(
                    "main_units_tables",
                    42,
                    [
                        {
                            "unit": "3k_archers",
                            "caste": "missile_infantry",
                            "land_unit": "3k_land_archers",
                            "campaign_cap": 4,
                            "recruitment_cost": 500,
                            "upkeep_cost": 125,
                        },
                        {
                            "unit": "3k_archers_unedited",
                            "caste": "missile_infantry",
                            "land_unit": "3k_land_archers_unedited",
                        },
                        {
                            "unit": "3k_trebuchet",
                            "caste": "warmachine",
                            "land_unit": "3k_land_trebuchet",
                        },
                        {
                            "unit": "3k_hero",
                            "caste": "hero",
                            "land_unit": "3k_land_hero",
                        },
                    ],
                ),
            ),
            _entry(
                "land_units_tables",
                _table_payload(
                    "land_units_tables",
                    49,
                    [
                        {
                            "key": "3k_land_archers",
                            "armour": "3k_armour_20",
                            "morale": 60,
                            "charge_bonus": 10,
                            "melee_attack": 20,
                            "melee_defence": 15,
                            "primary_ammo": 20,
                            "accuracy": 35,
                            "shield": "3k_shield_shared",
                            "melee_attack_interval_reduction_percentage": 5,
                            "reload_time_reduction_percentage": 10,
                            "primary_melee_weapon": "3k_melee_shared",
                            "primary_missile_weapon": "3k_missile_shared",
                        },
                        {
                            "key": "3k_land_archers_unedited",
                            "armour": "3k_armour_20",
                            "shield": "3k_shield_shared",
                            "primary_melee_weapon": "3k_melee_shared",
                            "primary_missile_weapon": "3k_missile_shared",
                        },
                        {
                            "key": "3k_land_trebuchet",
                            "armour": "3k_armour_20",
                            "primary_melee_weapon": "3k_melee_shared",
                        },
                        {
                            "key": "3k_land_hero",
                            "armour": "3k_armour_20",
                            "primary_melee_weapon": "3k_melee_shared",
                        },
                    ],
                ),
            ),
            _entry(
                "land_units_templates_tables",
                _table_payload(
                    "land_units_templates_tables",
                    3,
                    [
                        {
                            "land_unit": "3k_land_archers",
                            "composed_entity": "3k_archer_foot",
                            "num_composed_entities": 144,
                            "hp_pool": 86_400,
                        },
                        {
                            "land_unit": "3k_land_archers",
                            "composed_entity": "3k_archer_standard",
                            "num_composed_entities": 16,
                            "hp_pool": 9_600,
                        },
                        {
                            "land_unit": "3k_land_archers_unedited",
                            "composed_entity": "3k_archer_foot",
                            "num_composed_entities": 144,
                            "hp_pool": 86_400,
                        },
                        {
                            "land_unit": "3k_land_archers_unedited",
                            "composed_entity": "3k_archer_standard",
                            "num_composed_entities": 16,
                            "hp_pool": 9_600,
                        },
                        {
                            "land_unit": "3k_land_trebuchet",
                            "composed_entity": "3k_trebuchet_engine",
                            "num_composed_entities": 4,
                            "hp_pool": 12_000,
                        },
                        {
                            "land_unit": "3k_land_trebuchet",
                            "composed_entity": "3k_trebuchet_crew",
                            "num_composed_entities": 40,
                            "hp_pool": 12_000,
                        },
                        {
                            "land_unit": "3k_land_hero",
                            "composed_entity": "3k_hero_man",
                            "num_composed_entities": 1,
                            "hp_pool": 24_000,
                        },
                    ],
                ),
            ),
            _entry(
                "composed_entities_tables",
                _table_payload(
                    "composed_entities_tables",
                    5,
                    [
                        {
                            "key": "3k_archer_foot",
                            "num_men": 1,
                            "man": "3k_archer_man",
                        },
                        {
                            "key": "3k_archer_standard",
                            "num_men": 1,
                            "man": "3k_archer_man",
                        },
                        {"key": "3k_trebuchet_engine", "num_engines": 1},
                        {"key": "3k_trebuchet_crew", "num_men": 1},
                        {"key": "3k_hero_man", "num_men": 1},
                    ],
                ),
            ),
            _entry(
                "battle_entities_tables",
                _table_payload(
                    "battle_entities_tables",
                    32,
                    [{"key": "3k_archer_entity", "run_speed": 35.0}],
                ),
            ),
            _entry(
                "mens_tables",
                _table_payload(
                    "mens_tables",
                    1,
                    [{"key": "3k_archer_man", "battle_entity": "3k_archer_entity"}],
                ),
            ),
            _entry(
                "unit_shield_types_tables",
                _table_payload(
                    "unit_shield_types_tables",
                    6,
                    [{"key": "3k_shield_shared", "missile_block_chance": 30}],
                ),
            ),
            _entry(
                "melee_weapons_tables",
                _table_payload(
                    "melee_weapons_tables",
                    21,
                    [
                        {
                            "key": "3k_melee_shared",
                            "damage": 25,
                            "ap_damage": 8,
                            "bonus_v_cavalry": 3,
                            "bonus_v_infantry": 4,
                            "melee_attack_interval": 2.5,
                        }
                    ],
                ),
            ),
            _entry(
                "missile_weapons_tables",
                _table_payload(
                    "missile_weapons_tables",
                    11,
                    [
                        {
                            "key": "3k_missile_shared",
                            "default_projectile": "3k_projectile_shared",
                        }
                    ],
                ),
            ),
            _entry(
                "projectiles_tables",
                _table_payload(
                    "projectiles_tables",
                    46,
                    [
                        {
                            "key": "3k_projectile_shared",
                            "explosion_type": "3k_explosion_shared",
                            "effective_range": 200,
                            "damage": 5,
                            "ap_damage": 2,
                            "bonus_v_cavalry": 1,
                            "bonus_v_infantry": 2,
                            "base_reload_time": 7.0,
                        }
                    ],
                ),
            ),
            _entry(
                "projectiles_explosions_tables",
                _table_payload(
                    "projectiles_explosions_tables",
                    20,
                    [
                        {
                            "key": "3k_explosion_shared",
                            "detonation_damage": 40.0,
                            "detonation_damage_ap": 10.0,
                        }
                    ],
                ),
            ),
            _entry(
                "unit_armour_types_tables",
                _table_payload(
                    "unit_armour_types_tables",
                    6,
                    [
                        {"key": "3k_armour_20", "armour_value": 20, "audio_type": "metal"},
                        {"key": "3k_armour_100", "armour_value": 100, "audio_type": "metal"},
                    ],
                ),
            ),
            _entry(
                "units_to_groupings_military_permissions_tables",
                _versionless_payload(
                    [
                        _grouping_row("3k_archers", "3k_group"),
                        _grouping_row("3k_archers_unedited", "3k_group"),
                    ]
                ),
            ),
            _entry(
                "units_to_exclusive_faction_permissions_tables",
                _versionless_payload([_exclusive_row("3k_hero", "3k_faction", True)]),
            ),
        ),
    )


def _rows(result: Any, table_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in result.entries:
        resolved = _entry_table_name(entry.name)
        if resolved is None or resolved[0] != table_name:
            continue
        rows.extend(
            row.values
            for row in parse_db_table(table_name, entry.payload, game_id=THREE_KINGDOMS).rows
        )
    return rows


class ThreeKingdomsUnitDataSnapshotTests(unittest.TestCase):
    def test_composed_templates_drive_counts_health_and_locks(self) -> None:
        snapshot = build_unit_table_snapshot([_source()], {}, game_id=THREE_KINGDOMS)
        units = {unit["key"]: unit for unit in snapshot["units"]}

        archers = units["3k_archers"]
        self.assertEqual(archers["model_count"], 160)
        self.assertEqual(archers["hit_points"], 600)
        self.assertEqual(archers["total_hp"], 96_000)
        self.assertEqual(archers["morale"], 60)
        self.assertEqual(archers["missile_block_chance"], 30)
        self.assertEqual(archers["movement_speed"], 35.0)
        self.assertFalse(archers["movement_speed_locked"])
        self.assertEqual(archers["melee_attack_speed"], 2.5)
        self.assertEqual(archers["ranged_attack_speed"], 10)
        self.assertEqual(archers["melee_bonus_v_cavalry"], 3)
        self.assertEqual(archers["melee_bonus_v_infantry"], 4)
        self.assertEqual(archers["missile_bonus_v_cavalry"], 1)
        self.assertEqual(archers["missile_bonus_v_infantry"], 2)
        self.assertFalse(archers["enabled_locked"])

        trebuchet = units["3k_trebuchet"]
        self.assertEqual(trebuchet["model_count"], 4)
        self.assertTrue(trebuchet["hit_points_locked"])
        self.assertEqual(trebuchet["total_hp"], 24_000)
        self.assertTrue(trebuchet["enabled_locked"])

        self.assertTrue(units["3k_hero"]["model_count_locked"])

    def test_melee_attack_speed_is_rounded_to_one_decimal(self) -> None:
        snapshot = build_unit_table_snapshot(
            [_source()],
            {"3k_archers": {"melee_attack_speed": 2.56}},
            game_id=THREE_KINGDOMS,
        )
        row = next(unit for unit in snapshot["units"] if unit["key"] == "3k_archers")
        self.assertEqual(row["melee_attack_speed"], 2.6)

        result = build_unit_data_entries(
            [_source()],
            {},
            {"3k_archers": {"melee_attack_speed": 25.06}},
            game_id=THREE_KINGDOMS,
        )
        melee = {
            row["key"]: row for row in _rows(result, "melee_weapons_tables")
        }
        edited_key = next(key for key in melee if key != "3k_melee_shared")
        self.assertAlmostEqual(melee[edited_key]["melee_attack_interval"], 25.1, places=5)


class ThreeKingdomsUnitDataPatchTests(unittest.TestCase):
    def test_ignores_legacy_resistance_edits(self) -> None:
        result = build_unit_data_entries(
            [_source()],
            {},
            {"3k_archers": {"fire_resistance": 50, "missile_resistance": 25}},
            game_id=THREE_KINGDOMS,
        )

        self.assertEqual(result.entries, ())
        self.assertEqual(result.stats["edited_unit_count"], 0)

    def test_edits_clone_shared_weapons_and_patch_composed_templates(self) -> None:
        result = build_unit_data_entries(
            [_source()],
            {},
            {
                "3k_archers": {
                    "campaign_cap": 9,
                    "recruitment_cost": 600,
                    "upkeep_cost": 200,
                    "model_count": 80,
                    "hit_points": 700,
                    "morale": 70,
                    "armour": 100,
                    "charge_bonus": 30,
                    "missile_block_chance": 45,
                    "movement_speed": 40,
                    "melee_attack_speed": 25,
                    "melee_damage": 40,
                    "melee_ap_damage": 12,
                    "melee_bonus_v_cavalry": 9,
                    "melee_bonus_v_infantry": 10,
                    "missile_damage": 20,
                    "missile_ap_damage": 9,
                    "missile_bonus_v_cavalry": 6,
                    "missile_bonus_v_infantry": 7,
                    "range": 300,
                    "ranged_attack_speed": 30,
                    "explosion_damage": 70,
                    "explosion_ap_damage": 25,
                    "enabled": False,
                }
            },
            game_id=THREE_KINGDOMS,
        )

        main = {row["unit"]: row for row in _rows(result, "main_units_tables")}
        self.assertEqual(main["3k_archers"]["campaign_cap"], 9)
        self.assertEqual(main["3k_archers"]["recruitment_cost"], 600)
        self.assertEqual(main["3k_archers"]["upkeep_cost"], 200)
        self.assertNotEqual(main["3k_archers"]["land_unit"], "3k_land_archers")

        land = {row["key"]: row for row in _rows(result, "land_units_tables")}
        edited_land = land[main["3k_archers"]["land_unit"]]
        self.assertEqual(edited_land["armour"], "3k_armour_100")
        self.assertEqual(edited_land["morale"], 70)
        self.assertEqual(edited_land["charge_bonus"], 30)
        self.assertEqual(edited_land["melee_attack_interval_reduction_percentage"], 5)
        self.assertEqual(edited_land["reload_time_reduction_percentage"], 30)
        self.assertNotEqual(edited_land["shield"], "3k_shield_shared")
        self.assertNotEqual(edited_land["primary_melee_weapon"], "3k_melee_shared")
        self.assertNotEqual(edited_land["primary_missile_weapon"], "3k_missile_shared")
        self.assertEqual(
            land["3k_land_archers_unedited"]["primary_melee_weapon"],
            "3k_melee_shared",
        )
        self.assertEqual(
            land["3k_land_archers_unedited"]["primary_missile_weapon"],
            "3k_missile_shared",
        )

        edited_templates = [
            row
            for row in _rows(result, "land_units_templates_tables")
            if row["land_unit"] == edited_land["key"]
        ]
        self.assertEqual(len(edited_templates), 2)
        foot, standard = edited_templates
        self.assertEqual(foot["num_composed_entities"] + standard["num_composed_entities"], 80)
        self.assertEqual(foot["hp_pool"], foot["num_composed_entities"] * 700)
        self.assertEqual(standard["hp_pool"], standard["num_composed_entities"] * 700)

        shields = {row["key"]: row for row in _rows(result, "unit_shield_types_tables")}
        self.assertEqual(shields["3k_shield_shared"]["missile_block_chance"], 30)
        self.assertEqual(shields[edited_land["shield"]]["missile_block_chance"], 45)

        composed = {row["key"]: row for row in _rows(result, "composed_entities_tables")}
        men = {row["key"]: row for row in _rows(result, "mens_tables")}
        entities = {row["key"]: row for row in _rows(result, "battle_entities_tables")}
        foot_composed = composed[foot["composed_entity"]]
        foot_man = men[foot_composed["man"]]
        self.assertAlmostEqual(entities[foot_man["battle_entity"]]["run_speed"], 40.0)
        self.assertAlmostEqual(entities["3k_archer_entity"]["run_speed"], 35.0)

        melee = {row["key"]: row for row in _rows(result, "melee_weapons_tables")}
        self.assertEqual(melee["3k_melee_shared"]["damage"], 25)
        melee_clone = melee[edited_land["primary_melee_weapon"]]
        self.assertAlmostEqual(melee["3k_melee_shared"]["melee_attack_interval"], 2.5)
        self.assertAlmostEqual(melee_clone["melee_attack_interval"], 25.0)
        self.assertEqual(melee_clone["damage"], 40)
        self.assertEqual(melee_clone["ap_damage"], 12)
        self.assertEqual(melee_clone["bonus_v_cavalry"], 9)
        self.assertEqual(melee_clone["bonus_v_infantry"], 10)

        missiles = {row["key"]: row for row in _rows(result, "missile_weapons_tables")}
        missile_clone = missiles[edited_land["primary_missile_weapon"]]
        projectiles = {row["key"]: row for row in _rows(result, "projectiles_tables")}
        projectile_clone = projectiles[missile_clone["default_projectile"]]
        self.assertEqual(projectile_clone["damage"], 20)
        self.assertEqual(projectile_clone["ap_damage"], 9)
        self.assertEqual(projectile_clone["effective_range"], 300)
        self.assertEqual(projectile_clone["bonus_v_cavalry"], 6)
        self.assertEqual(projectile_clone["bonus_v_infantry"], 7)

        explosions = {
            row["key"]: row for row in _rows(result, "projectiles_explosions_tables")
        }
        explosion_clone = explosions[projectile_clone["explosion_type"]]
        self.assertAlmostEqual(explosion_clone["detonation_damage"], 70.0)
        self.assertAlmostEqual(explosion_clone["detonation_damage_ap"], 25.0)

        permissions = _rows(result, "units_to_groupings_military_permissions_tables")
        self.assertNotIn("3k_archers", {row["unit"] for row in permissions})
        self.assertIn("3k_archers_unedited", {row["unit"] for row in permissions})

    def test_runtime_patch_reads_three_kingdoms_pack_and_writes_a_pack(self) -> None:
        from backend.start_options import PackEntry, UNIT_DATA_PATCH_NAME, write_pfh5_pack

        with tempfile.TemporaryDirectory(prefix="wmm_three_kingdoms_unit_data_") as raw:
            root = Path(raw)
            data = root / "data"
            runtime = root / "runtime"
            data.mkdir()
            runtime.mkdir()
            source = _source()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry(entry.name, entry.payload) for entry in source.entries],
            )
            save_unit_data_edits(runtime, {"3k_archers": {"campaign_cap": 9}})

            result = ensure_unit_data_patch(
                runtime,
                data,
                {},
                [],
                "default:three_kingdoms",
                {},
                game_id=THREE_KINGDOMS,
            )

            self.assertEqual(result["status"], "generated")
            self.assertTrue((runtime / UNIT_DATA_PATCH_NAME).is_file())
            self.assertGreater(result["entry_count"], 0)


if __name__ == "__main__":
    unittest.main()
