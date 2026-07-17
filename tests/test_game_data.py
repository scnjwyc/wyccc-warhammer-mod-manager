from __future__ import annotations

import struct
import unittest
from typing import Any

from backend.game_data import (
    TABLE_SCHEMAS,
    DbSource,
    GameDataEntry,
    build_game_data_entries,
    parse_db_table,
)


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


def _rows_for(result: Any, table_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prefix = f"db\\{table_name}\\"
    for entry in result.entries:
        if entry.name.startswith(prefix):
            rows.extend(row.values for row in parse_db_table(table_name, entry.payload).rows)
    return rows


class GameDataPatchTests(unittest.TestCase):
    def test_tsv_sidecar_entries_are_ignored(self) -> None:
        source = DbSource(
            "example_mod.pack",
            (
                GameDataEntry(
                    "db\\battle_vortexs_tables\\!custom_vortex",
                    _table_payload(
                        "battle_vortexs_tables",
                        19,
                        [{"vortex_key": "custom_vortex", "affects_allies": True, "is_spell": True}],
                    ),
                ),
                GameDataEntry(
                    "db\\battle_vortexs_tables\\!custom_vortex.tsv",
                    b"vortex_key\tchange_max_angle\tcontact_effect\ncustom_vortex\t0\t\n",
                ),
                GameDataEntry(
                    "db\\projectiles_tables\\!custom_projectile",
                    _table_payload(
                        "projectiles_tables",
                        53,
                        [
                            {
                                "key": "custom_projectile",
                                "can_damage_allies": True,
                                "is_spell": True,
                                "explosion_type": "custom_explosion",
                                "spawned_vortex": "custom_vortex",
                            }
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\projectiles_explosions_tables\\!custom_explosion",
                    _table_payload(
                        "projectiles_explosions_tables",
                        19,
                        [{"key": "custom_explosion", "affects_allies": True, "is_spell": True}],
                    ),
                ),
            ),
        )

        result = build_game_data_entries(
            [source],
            {
                "unit_model_multiplier": 1.0,
                "disable_unit_friendly_fire": False,
                "disable_spell_friendly_fire": True,
            },
        )

        vortexes = {row["vortex_key"]: row for row in _rows_for(result, "battle_vortexs_tables")}
        self.assertFalse(vortexes["custom_vortex"]["affects_allies"])

    def test_unit_multiplier_matches_reference_flow_and_preserves_effective_rows(self) -> None:
        base = DbSource(
            "db.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\data__",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [
                            {"unit": "unit_infantry", "caste": "infantry", "land_unit": "land_infantry", "num_men": 100},
                            {"unit": "unit_lord", "caste": "lord", "land_unit": "land_lord", "num_men": 1},
                            {"unit": "unit_hero", "caste": "hero", "land_unit": "land_hero", "num_men": 1},
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\land_units_tables\\data__",
                    _table_payload(
                        "land_units_tables",
                        54,
                        [
                            {"key": "land_infantry", "num_mounts": 2, "num_engines": 1, "bonus_hit_points": 100},
                            {"key": "land_lord", "num_mounts": 1, "num_engines": 0, "bonus_hit_points": 1000},
                            {"key": "land_hero", "num_mounts": 1, "num_engines": 0, "bonus_hit_points": 800},
                        ],
                    ),
                ),
            ),
        )
        mod = DbSource(
            "example_mod.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\z_low_priority",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [{"unit": "unit_infantry", "caste": "infantry", "land_unit": "land_infantry", "num_men": 90}],
                    ),
                ),
                GameDataEntry(
                    "db\\main_units_tables\\!high_priority",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [
                            {"unit": "unit_infantry", "caste": "infantry", "land_unit": "land_infantry", "num_men": 80},
                            {"unit": "unit_artillery", "caste": "infantry", "land_unit": "land_artillery", "num_men": 4},
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\land_units_tables\\!high_priority",
                    _table_payload(
                        "land_units_tables",
                        54,
                        [
                            {"key": "land_infantry", "num_mounts": 3, "num_engines": 0},
                            {"key": "land_artillery", "num_mounts": 0, "num_engines": 2},
                        ],
                    ),
                ),
            ),
        )

        result = build_game_data_entries(
            [mod, base],
            {
                "unit_model_multiplier": 2,
                "scale_lord_hero_health": False,
                "disable_unit_friendly_fire": False,
                "disable_spell_friendly_fire": False,
            },
        )

        main_rows = {row["unit"]: row for row in _rows_for(result, "main_units_tables")}
        self.assertEqual(main_rows["unit_infantry"]["num_men"], 160)
        self.assertEqual(main_rows["unit_artillery"]["num_men"], 8)
        self.assertEqual(main_rows["unit_lord"]["num_men"], 1)
        self.assertEqual(main_rows["unit_hero"]["num_men"], 1)
        self.assertEqual(len(main_rows), 4)

        land_rows = {row["key"]: row for row in _rows_for(result, "land_units_tables")}
        self.assertEqual(land_rows["land_infantry"]["num_mounts"], 6)
        self.assertEqual(land_rows["land_infantry"]["num_engines"], 0)
        self.assertEqual(land_rows["land_artillery"]["num_mounts"], 0)
        self.assertEqual(land_rows["land_artillery"]["num_engines"], 4)
        self.assertEqual(land_rows["land_lord"]["num_mounts"], 1)
        self.assertEqual(land_rows["land_lord"]["bonus_hit_points"], 1000)
        self.assertEqual(land_rows["land_hero"]["bonus_hit_points"], 800)
        self.assertEqual(result.stats["unit_rows_scaled"], 2)
        self.assertEqual(result.stats["land_rows_scaled"], 2)
        self.assertEqual(result.stats["lord_hero_health_rows_scaled"], 0)

    def test_lord_and_hero_health_scaling_is_opt_in_and_keeps_model_counts(self) -> None:
        source = DbSource(
            "db.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\data__",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [
                            {"unit": "unit_infantry", "caste": "infantry", "land_unit": "land_infantry", "num_men": 10},
                            {"unit": "unit_lord", "caste": "lord", "land_unit": "land_lord", "num_men": 1},
                            {"unit": "unit_hero", "caste": "hero", "land_unit": "land_hero", "num_men": 1},
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\land_units_tables\\data__",
                    _table_payload(
                        "land_units_tables",
                        54,
                        [
                            {"key": "land_infantry", "bonus_hit_points": 100},
                            {"key": "land_lord", "bonus_hit_points": 1000},
                            {"key": "land_hero", "bonus_hit_points": 800},
                        ],
                    ),
                ),
            ),
        )

        result = build_game_data_entries(
            [source],
            {
                "unit_model_multiplier": 3,
                "scale_lord_hero_health": True,
            },
        )

        main_rows = {row["unit"]: row for row in _rows_for(result, "main_units_tables")}
        self.assertEqual(main_rows["unit_infantry"]["num_men"], 30)
        self.assertEqual(main_rows["unit_lord"]["num_men"], 1)
        self.assertEqual(main_rows["unit_hero"]["num_men"], 1)
        land_rows = {row["key"]: row for row in _rows_for(result, "land_units_tables")}
        self.assertEqual(land_rows["land_infantry"]["bonus_hit_points"], 100)
        self.assertEqual(land_rows["land_lord"]["bonus_hit_points"], 3000)
        self.assertEqual(land_rows["land_hero"]["bonus_hit_points"], 2400)
        self.assertEqual(result.stats["lord_hero_health_rows_scaled"], 2)

    def test_unit_multiplier_is_clamped_to_supported_range(self) -> None:
        source = DbSource(
            "db.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\data__",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [
                            {
                                "unit": "unit_infantry",
                                "caste": "infantry",
                                "land_unit": "land_infantry",
                                "num_men": 10,
                            }
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\land_units_tables\\data__",
                    _table_payload(
                        "land_units_tables",
                        54,
                        [{"key": "land_infantry", "num_mounts": 2, "num_engines": 0}],
                    ),
                ),
            ),
        )

        for supplied, expected, expected_models in ((0.1, 1, 10), (2.5, 3, 30), (50, 5, 50)):
            with self.subTest(supplied=supplied):
                result = build_game_data_entries(
                    [source],
                    {
                        "unit_model_multiplier": supplied,
                        "disable_unit_friendly_fire": False,
                        "disable_spell_friendly_fire": False,
                    },
                )

                self.assertEqual(result.stats["unit_model_multiplier"], expected)
                main_rows = _rows_for(result, "main_units_tables")
                if expected == 1:
                    self.assertEqual(main_rows, [])
                else:
                    self.assertEqual(main_rows[0]["num_men"], expected_models)

    def test_friendly_fire_switches_separate_unit_and_spell_damage_carriers(self) -> None:
        source = DbSource(
            "db.pack",
            (
                GameDataEntry(
                    "db\\projectiles_tables\\data__",
                    _table_payload(
                        "projectiles_tables",
                        53,
                        [
                            {"key": "normal_shot", "can_damage_allies": True, "is_spell": False, "explosion_type": "normal_blast", "spawned_vortex": "normal_vortex"},
                            {"key": "spell_shot", "can_damage_allies": True, "is_spell": True, "explosion_type": "spell_blast", "spawned_vortex": "spell_vortex"},
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\projectiles_explosions_tables\\data__",
                    _table_payload(
                        "projectiles_explosions_tables",
                        19,
                        [
                            {"key": "normal_blast", "affects_allies": True, "is_spell": False},
                            {"key": "spell_blast", "affects_allies": True, "is_spell": True},
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\battle_vortexs_tables\\data__",
                    _table_payload(
                        "battle_vortexs_tables",
                        19,
                        [
                            {"vortex_key": "normal_vortex", "affects_allies": True, "is_spell": False},
                            {"vortex_key": "spell_vortex", "affects_allies": True, "is_spell": True},
                        ],
                    ),
                ),
                GameDataEntry("db\\special_ability_phases_tables\\data__", b"must stay untouched"),
            ),
        )

        for unit_off, spell_off, normal_expected, spell_expected in (
            (True, False, False, True),
            (False, True, True, False),
            (True, True, False, False),
        ):
            with self.subTest(unit_off=unit_off, spell_off=spell_off):
                result = build_game_data_entries(
                    [source],
                    {
                        "unit_model_multiplier": 1.0,
                        "disable_unit_friendly_fire": unit_off,
                        "disable_spell_friendly_fire": spell_off,
                    },
                )
                projectiles = {row["key"]: row for row in _rows_for(result, "projectiles_tables")}
                explosions = {row["key"]: row for row in _rows_for(result, "projectiles_explosions_tables")}
                vortexes = {row["vortex_key"]: row for row in _rows_for(result, "battle_vortexs_tables")}

                self.assertEqual(projectiles["normal_shot"]["can_damage_allies"], normal_expected)
                self.assertEqual(projectiles["spell_shot"]["can_damage_allies"], spell_expected)
                self.assertEqual(explosions["normal_blast"]["affects_allies"], normal_expected)
                self.assertEqual(explosions["spell_blast"]["affects_allies"], spell_expected)
                self.assertEqual(vortexes["normal_vortex"]["affects_allies"], normal_expected)
                self.assertEqual(vortexes["spell_vortex"]["affects_allies"], spell_expected)
                self.assertFalse(any("special_ability_phases" in entry.name for entry in result.entries))


if __name__ == "__main__":
    unittest.main()
