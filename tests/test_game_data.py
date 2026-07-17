from __future__ import annotations

import struct
import unittest
from typing import Any

from backend.game_data import (
    TABLE_SCHEMAS,
    DbSource,
    GameDataEntry,
    _collect_effective_rows,
    _compare_internal_names,
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


def _kv_rules_payload(rows: list[tuple[str, float]]) -> bytes:
    encoded_rows = [
        struct.pack("<H", len(key.encode("ascii")))
        + key.encode("ascii")
        + struct.pack("<f", value)
        for key, value in rows
    ]
    return b"".join(
        (
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", 0),
            b"\1",
            struct.pack("<i", len(encoded_rows)),
            *encoded_rows,
        )
    )


def _decode_kv_rules(payload: bytes) -> dict[str, float]:
    cursor = 0
    if payload[cursor : cursor + 4] == b"\xfc\xfd\xfe\xff":
        cursor += 8
    assert payload[cursor : cursor + 1] == b"\1"
    row_count = struct.unpack_from("<i", payload, cursor + 1)[0]
    cursor += 5
    rows: dict[str, float] = {}
    for _ in range(row_count):
        length = struct.unpack_from("<H", payload, cursor)[0]
        cursor += 2
        key = payload[cursor : cursor + length].decode("ascii")
        cursor += length
        rows[key] = struct.unpack_from("<f", payload, cursor)[0]
        cursor += 4
    assert cursor == len(payload)
    return rows


class GameDataPatchTests(unittest.TestCase):
    def test_battle_entities_schema_covers_all_supported_wh3_versions(self) -> None:
        self.assertEqual(
            set(TABLE_SCHEMAS["battle_entities_tables"]),
            {31, 32, 33, 34, 38, 39},
        )

    def test_generated_tables_outrank_high_priority_mod_table_names(self) -> None:
        source_internal_name = "!!!!!!!overhaul"
        source = DbSource(
            "high_priority_mod.pack",
            (
                GameDataEntry(
                    f"db\\main_units_tables\\{source_internal_name}",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [
                            {
                                "unit": "unit_infantry",
                                "caste": "melee_infantry",
                                "land_unit": "land_infantry",
                                "num_men": 10,
                            }
                        ],
                    ),
                ),
                GameDataEntry(
                    f"db\\land_units_tables\\{source_internal_name}",
                    _table_payload(
                        "land_units_tables",
                        54,
                        [
                            {
                                "key": "land_infantry",
                                "num_mounts": 2,
                                "num_engines": 0,
                            }
                        ],
                    ),
                ),
            ),
        )

        result = build_game_data_entries(
            [source],
            {
                "unit_model_multiplier": 3,
                "scale_lord_hero_health": False,
            },
        )
        generated = DbSource("generated.pack", result.entries)
        effective = _collect_effective_rows(
            [generated, source],
            {"main_units_tables", "land_units_tables"},
        )

        self.assertEqual(
            effective["main_units_tables"]["unit_infantry"].row.values["num_men"],
            30,
        )
        self.assertEqual(
            effective["land_units_tables"]["land_infantry"].row.values["num_mounts"],
            6,
        )
        for entry in result.entries:
            internal_name = entry.name.rsplit("\\", 1)[-1]
            self.assertLess(
                _compare_internal_names(internal_name, source_internal_name),
                0,
            )
        self.assertEqual(result.stats["source_table_priority_markers"], 7)
        self.assertEqual(result.stats["patch_table_priority_markers"], 8)

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
                            {
                                "key": "land_infantry",
                                "man_entity": "entity_infantry",
                                "bonus_hit_points": 100,
                            },
                            {
                                "key": "land_lord",
                                "man_entity": "entity_lord",
                                "bonus_hit_points": 1000,
                            },
                            {
                                "key": "land_hero",
                                "man_entity": "entity_hero",
                                "bonus_hit_points": 800,
                            },
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\battle_entities_tables\\data__",
                    _table_payload(
                        "battle_entities_tables",
                        39,
                        [
                            {"key": "entity_infantry", "hit_points": 8},
                            {"key": "entity_lord", "hit_points": 3500},
                            {"key": "entity_hero", "hit_points": 3868},
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
        self.assertEqual(
            3500 + land_rows["land_lord"]["bonus_hit_points"],
            (3500 + 1000) * 3,
        )
        self.assertEqual(
            3868 + land_rows["land_hero"]["bonus_hit_points"],
            (3868 + 800) * 3,
        )
        self.assertFalse(
            any("battle_entities_tables" in entry.name for entry in result.entries)
        )
        self.assertEqual(result.stats["lord_hero_health_rows_scaled"], 2)

    def test_single_entity_health_mode_scales_only_regular_monsters(self) -> None:
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
                            },
                            {
                                "unit": "unit_star_dragon",
                                "caste": "monster",
                                "land_unit": "land_star_dragon",
                                "num_men": 1,
                                "is_monstrous": True,
                            },
                            {
                                "unit": "unit_shared_land_non_monster",
                                "caste": "infantry",
                                "land_unit": "land_star_dragon",
                                "num_men": 10,
                            },
                            {
                                "unit": "unit_monster_engine",
                                "caste": "monster",
                                "land_unit": "land_monster_engine",
                                "num_men": 1,
                                "is_monstrous": True,
                            },
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\land_units_tables\\data__",
                    _table_payload(
                        "land_units_tables",
                        54,
                        [
                            {
                                "key": "land_infantry",
                                "man_entity": "entity_infantry",
                                "num_mounts": 0,
                                "num_engines": 0,
                            },
                            {
                                "key": "land_star_dragon",
                                "man_entity": "entity_star_dragon",
                                "bonus_hit_points": 400,
                                "num_mounts": 0,
                                "num_engines": 0,
                            },
                            {
                                "key": "land_monster_engine",
                                "man_entity": "entity_monster_engine",
                                "bonus_hit_points": 500,
                                "engine": "monster_engine",
                                "num_mounts": 0,
                                "num_engines": 1,
                            },
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\battle_entities_tables\\data__",
                    _table_payload(
                        "battle_entities_tables",
                        39,
                        [
                            {"key": "entity_infantry", "hit_points": 10},
                            {"key": "entity_star_dragon", "hit_points": 2000},
                            {"key": "entity_monster_engine", "hit_points": 1000},
                        ],
                    ),
                ),
            ),
        )

        result = build_game_data_entries(
            [source],
            {
                "unit_model_multiplier": 3,
                "single_entity_unit_mode": "health",
                "scale_lord_hero_health": False,
            },
        )

        main_rows = {row["unit"]: row for row in _rows_for(result, "main_units_tables")}
        self.assertEqual(main_rows["unit_infantry"]["num_men"], 30)
        self.assertEqual(main_rows["unit_star_dragon"]["num_men"], 1)
        self.assertEqual(main_rows["unit_shared_land_non_monster"]["num_men"], 30)
        self.assertEqual(main_rows["unit_monster_engine"]["num_men"], 3)

        land_rows = {row["key"]: row for row in _rows_for(result, "land_units_tables")}
        self.assertEqual(
            2000 + land_rows["land_star_dragon"]["bonus_hit_points"],
            (2000 + 400) * 3,
        )
        self.assertEqual(land_rows["land_monster_engine"]["num_engines"], 3)
        self.assertEqual(land_rows["land_monster_engine"]["bonus_hit_points"], 500)
        self.assertEqual(result.stats["single_entity_health_rows_scaled"], 1)
        self.assertEqual(result.stats["unit_rows_scaled"], 3)
        self.assertEqual(result.stats["land_rows_scaled"], 1)

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
                kv_entries = [
                    entry
                    for entry in result.entries
                    if entry.name.startswith("db\\_kv_rules_tables\\")
                ]
                self.assertEqual(len(kv_entries), 1 if unit_off else 0)
                self.assertFalse(any("special_ability_phases" in entry.name for entry in result.entries))

    def test_non_spell_friendly_fire_adds_reference_kv_rules(self) -> None:
        source_internal_name = "!!!!!!!existing_rules"
        source = DbSource(
            "high_priority_rules.pack",
            (
                GameDataEntry(
                    f"db\\_kv_rules_tables\\{source_internal_name}",
                    _kv_rules_payload([("unrelated_rule", 5.0)]),
                ),
                GameDataEntry(
                    "db\\projectiles_tables\\data__",
                    _table_payload(
                        "projectiles_tables",
                        53,
                        [
                            {
                                "key": "already_safe_projectile",
                                "can_damage_allies": False,
                                "is_spell": False,
                            }
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\projectiles_explosions_tables\\data__",
                    _table_payload(
                        "projectiles_explosions_tables",
                        19,
                        [
                            {
                                "key": "already_safe_explosion",
                                "affects_allies": False,
                                "is_spell": False,
                            }
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\battle_vortexs_tables\\data__",
                    _table_payload(
                        "battle_vortexs_tables",
                        19,
                        [
                            {
                                "vortex_key": "already_safe_vortex",
                                "affects_allies": False,
                                "is_spell": False,
                            }
                        ],
                    ),
                ),
            ),
        )

        result = build_game_data_entries(
            [source],
            {
                "unit_model_multiplier": 1,
                "disable_unit_friendly_fire": True,
                "disable_spell_friendly_fire": False,
            },
        )

        entries = [
            entry
            for entry in result.entries
            if entry.name.startswith("db\\_kv_rules_tables\\")
        ]
        self.assertEqual(len(entries), 1)
        rules = _decode_kv_rules(entries[0].payload)
        self.assertEqual(set(rules), {
            "projectile_friendly_fire_man_height_coefficient",
            "projectile_friendly_fire_man_radius_coefficient",
            "projectile_friendly_fire_ignore_allies_height_coefficient",
            "projectile_friendly_fire_ignore_allies_radius_coefficient",
        })
        self.assertAlmostEqual(rules["projectile_friendly_fire_man_height_coefficient"], 0.6)
        self.assertAlmostEqual(rules["projectile_friendly_fire_man_radius_coefficient"], 1.2)
        self.assertAlmostEqual(
            rules["projectile_friendly_fire_ignore_allies_height_coefficient"],
            0.6,
        )
        self.assertAlmostEqual(
            rules["projectile_friendly_fire_ignore_allies_radius_coefficient"],
            1.2,
        )
        generated_name = entries[0].name.rsplit("\\", 1)[-1]
        self.assertLess(_compare_internal_names(generated_name, source_internal_name), 0)
        self.assertEqual(result.stats["unit_friendly_fire_kv_rules_changed"], 4)


if __name__ == "__main__":
    unittest.main()
