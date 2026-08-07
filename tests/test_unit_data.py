from __future__ import annotations

import struct
import unittest
from pathlib import Path
from typing import Any

from backend.game_data import (
    TABLE_SCHEMAS,
    DbSource,
    GameDataEntry,
    _entry_table_name,
    parse_db_table,
)
from backend.unit_data import (
    _armour_key_for_value,
    _base_visible_count,
    _language_loc_packs,
    _sanitize_edits,
    build_unit_data_entries,
    build_unit_table_snapshot,
    collect_unit_name_map,
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


def _versionless_payload(rows: list[bytes]) -> bytes:
    return b"".join((b"\1", struct.pack("<i", len(rows)), *rows))


def _grouping_row(unit: str, group: str) -> bytes:
    encoded = [
        struct.pack("<H", len(str(value).encode("ascii"))) + str(value).encode("ascii")
        for value in (unit, group)
    ]
    return b"".join(encoded)


def _exclusive_row(unit: str, faction: str, exclusive: bool) -> bytes:
    encoded = [
        struct.pack("<H", len(str(value).encode("ascii"))) + str(value).encode("ascii")
        for value in (unit, faction)
    ]
    return b"".join(encoded) + bytes([1 if exclusive else 0])


def _fixture_source() -> DbSource:
    return DbSource(
        "db.pack",
        (
            GameDataEntry(
                "db\\main_units_tables\\data__",
                _table_payload(
                    "main_units_tables",
                    7,
                    [
                        {
                            "unit": "inf_swordsmen",
                            "caste": "infantry",
                            "land_unit": "land_inf_swordsmen",
                            "num_men": 90,
                            "campaign_cap": 4,
                            "recruitment_cost": 400,
                            "upkeep_cost": 100,
                        },
                        {
                            "unit": "veh_chariot",
                            "caste": "chariot",
                            "land_unit": "land_veh_chariot",
                            "num_men": 24,
                            "campaign_cap": 2,
                            "recruitment_cost": 900,
                            "upkeep_cost": 250,
                        },
                        {
                            "unit": "art_ballista",
                            "caste": "warmachine",
                            "land_unit": "land_art_ballista",
                            "num_men": 8,
                            "campaign_cap": 3,
                            "recruitment_cost": 700,
                            "upkeep_cost": 180,
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
                            "key": "land_inf_swordsmen",
                            "man_entity": "man_swordsmen",
                            "armour": "wh2_main_body_10",
                            "charge_bonus": 15,
                            "melee_attack": 28,
                            "melee_defence": 32,
                            "primary_ammo": 0,
                            "reload": 10,
                            "accuracy": 40,
                            "bonus_hit_points": 8,
                            "primary_melee_weapon": "weap_sword",
                            "damage_mod_flame": 0,
                            "damage_mod_magic": 0,
                            "damage_mod_physical": 0,
                            "damage_mod_all": 0,
                            "num_mounts": 0,
                            "num_engines": 0,
                            "rank_depth": 3,
                            "category": "infantry",
                            "spacing": "infantry",
                        },
                        {
                            "key": "land_veh_chariot",
                            "man_entity": "man_chariot_crew",
                            "armour": "wh2_main_heavy_metal_60",
                            "charge_bonus": 40,
                            "melee_attack": 20,
                            "melee_defence": 25,
                            "primary_ammo": 0,
                            "reload": 10,
                            "accuracy": 30,
                            "bonus_hit_points": 5,
                            "primary_melee_weapon": "weap_sword",
                            "num_mounts": 12,
                            "num_engines": 0,
                            "rank_depth": 3,
                            "category": "chariot",
                            "spacing": "cavalry",
                        },
                        {
                            "key": "land_art_ballista",
                            "man_entity": "man_ballista_crew",
                            "armour": "wh2_main_body_20",
                            "charge_bonus": 0,
                            "melee_attack": 10,
                            "melee_defence": 15,
                            "primary_ammo": 0,
                            "reload": 10,
                            "accuracy": 30,
                            "bonus_hit_points": 5,
                            "primary_melee_weapon": "weap_sword",
                            "num_mounts": 0,
                            "num_engines": 4,
                            "rank_depth": 1,
                            "category": "artillery",
                            "spacing": "artillery",
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
                        {"key": "man_swordsmen", "hit_points": 60},
                        {"key": "man_chariot_crew", "hit_points": 55},
                        {"key": "man_ballista_crew", "hit_points": 50},
                    ],
                ),
            ),
            GameDataEntry(
                "db\\melee_weapons_tables\\data__",
                _table_payload(
                    "melee_weapons_tables",
                    25,
                    [{"key": "weap_sword", "damage": 25, "ap_damage": 8}],
                ),
            ),
            GameDataEntry(
                "db\\unit_armour_types_tables\\data__",
                _table_payload(
                    "unit_armour_types_tables",
                    6,
                    [
                        {"key": "wh2_main_body_10", "armour_value": 10, "audio_type": "body"},
                        {"key": "wh2_main_body_20", "armour_value": 20, "audio_type": "body"},
                        {"key": "wh2_main_body_100", "armour_value": 100, "audio_type": "body"},
                        {"key": "wh2_main_heavy_metal_60", "armour_value": 60, "audio_type": "heavy_metal"},
                        {"key": "wh2_main_heavy_metal_80", "armour_value": 80, "audio_type": "heavy_metal"},
                    ],
                ),
            ),
            GameDataEntry(
                "db\\units_to_groupings_military_permissions_tables\\data__",
                _versionless_payload(
                    [
                        _grouping_row("inf_swordsmen", "grp_empire"),
                        _grouping_row("inf_swordsmen", "grp_wissenland"),
                        _grouping_row("veh_chariot", "grp_empire"),
                    ]
                ),
            ),
            GameDataEntry(
                "db\\units_to_exclusive_faction_permissions_tables\\data__",
                _versionless_payload(
                    [_exclusive_row("veh_chariot", "wh_main_emp_reikland", True)]
                ),
            ),
            GameDataEntry(
                "db\\factions_tables\\data__",
                _table_payload(
                    "factions_tables",
                    6,
                    [
                        {
                            "key": "wh_main_emp_reikland",
                            "subculture": "sc_empire",
                            "military_group": "wh_main_emp",
                        }
                    ],
                ),
            ),
            GameDataEntry(
                "db\\cultures_subcultures_tables\\data__",
                _table_payload(
                    "cultures_subcultures_tables",
                    6,
                    [
                        {
                            "subculture": "sc_empire",
                            "culture": "wh_main_emp_empire",
                        }
                    ],
                ),
            ),
        ),
    )


def _rows_by_key(result: Any, table_name: str) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in result.entries:
        resolved = _entry_table_name(entry.name)
        if not resolved or resolved[0] != table_name:
            continue
        parsed = parse_db_table(table_name, entry.payload)
        for row in parsed.rows:
            key = str(row.values.get("unit") or row.values.get("key") or "")
            merged[key] = row.values
    return merged


class UnitDataSnapshotTests(unittest.TestCase):
    def test_projects_all_requested_fields(self) -> None:
        source = _fixture_source()
        snapshot = build_unit_table_snapshot(
            [source],
            {"unit_model_multiplier": 1},
            {},
        )
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(set(rows), {"inf_swordsmen", "veh_chariot", "art_ballista"})
        swordsmen = rows["inf_swordsmen"]
        self.assertEqual(swordsmen["caste"], "infantry")
        self.assertEqual(swordsmen["campaign_cap"], 4)
        self.assertEqual(swordsmen["recruitment_cost"], 400)
        self.assertEqual(swordsmen["upkeep_cost"], 100)
        self.assertEqual(swordsmen["model_count"], 90)
        self.assertEqual(swordsmen["hit_points"], 8)
        self.assertEqual(swordsmen["total_hp"], 8 * 90)
        self.assertEqual(swordsmen["charge_bonus"], 15)
        self.assertEqual(swordsmen["melee_attack"], 28)
        self.assertEqual(swordsmen["melee_defence"], 32)
        self.assertEqual(swordsmen["melee_damage"], 25)
        self.assertEqual(swordsmen["melee_ap_damage"], 8)
        self.assertEqual(swordsmen["armour_value"], 10)
        self.assertEqual(swordsmen["armour_options"], [10, 20, 100])
        self.assertEqual(swordsmen["original_values"]["campaign_cap"], 4)
        self.assertEqual(swordsmen["original_values"]["melee_damage"], 25)
        self.assertEqual(swordsmen["original_values"]["model_count"], 90)

    def test_chariot_and_war_machine_use_real_entity_counts(self) -> None:
        snapshot = build_unit_table_snapshot([_fixture_source()], {}, {})
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(rows["veh_chariot"]["model_count"], 12)
        self.assertEqual(rows["art_ballista"]["model_count"], 4)

    def test_model_count_reflects_unit_scale_multiplier(self) -> None:
        snapshot = build_unit_table_snapshot(
            [_fixture_source()],
            {"unit_model_multiplier": 2},
            {},
        )
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(rows["inf_swordsmen"]["model_count"], 180)
        self.assertEqual(rows["veh_chariot"]["model_count"], 24)


class UnitDataPatchTests(unittest.TestCase):
    def test_applies_edits_across_joined_tables(self) -> None:
        source = _fixture_source()
        edits = {
            "inf_swordsmen": {
                "campaign_cap": 9,
                "recruitment_cost": 600,
                "upkeep_cost": 200,
                "model_count": 120,
                "armour": 100,
                "hit_points": 80,
                "charge_bonus": 30,
                "melee_damage": 40,
                "melee_ap_damage": 12,
            }
        }
        result = build_unit_data_entries([source], {"unit_model_multiplier": 1}, edits)
        main = _rows_by_key(result, "main_units_tables")
        self.assertEqual(main["inf_swordsmen"]["num_men"], 120)
        self.assertEqual(main["inf_swordsmen"]["campaign_cap"], 9)
        land = _rows_by_key(result, "land_units_tables")
        self.assertEqual(land["land_inf_swordsmen"]["charge_bonus"], 30)
        self.assertEqual(land["land_inf_swordsmen"]["armour"], "wh2_main_body_100")
        self.assertEqual(land["land_inf_swordsmen"]["bonus_hit_points"], 80)
        entities = _rows_by_key(result, "battle_entities_tables")
        self.assertNotIn("man_swordsmen", entities)
        melee = _rows_by_key(result, "melee_weapons_tables")
        self.assertEqual(melee["weap_sword"]["damage"], 40)
        self.assertEqual(melee["weap_sword"]["ap_damage"], 12)

    def test_disabled_unit_is_removed_from_recruitment_tables(self) -> None:
        source = _fixture_source()
        result = build_unit_data_entries(
            [source],
            {},
            {"inf_swordsmen": {"enabled": False}},
        )
        groupings = _rows_by_key(result, "units_to_groupings_military_permissions_tables")
        self.assertNotIn("inf_swordsmen", groupings)
        self.assertIn("veh_chariot", groupings)
        exclusive = _rows_by_key(result, "units_to_exclusive_faction_permissions_tables")
        self.assertIn("veh_chariot", exclusive)

    def test_no_edits_produces_no_entries(self) -> None:
        result = build_unit_data_entries([_fixture_source()], {}, {})
        self.assertEqual(result.entries, ())

    def test_model_count_edit_writes_absolute_value(self) -> None:
        source = _fixture_source()
        result = build_unit_data_entries(
            [source],
            {"unit_model_multiplier": 2},
            {"inf_swordsmen": {"model_count": 100}},
        )
        main = _rows_by_key(result, "main_units_tables")
        # The unit patch stores the absolute value; the game-data patch scales
        # it by the multiplier on top.
        self.assertEqual(main["inf_swordsmen"]["num_men"], 100)


class UnitDataHelpersTests(unittest.TestCase):
    def test_sanitize_edits_filters_unknown_fields(self) -> None:
        cleaned = _sanitize_edits(
            {
                "unit_a": {"campaign_cap": 3, "not_a_field": 1, "enabled": False},
                "unit_b": {},
                "unit_c": "junk",
            }
        )
        self.assertEqual(cleaned, {"unit_a": {"campaign_cap": 3, "enabled": False}})

    def test_armour_key_rebuild_keeps_prefix_and_audio(self) -> None:
        from backend.game_data import _collect_effective_rows

        source = _fixture_source()
        effective = _collect_effective_rows(
            [source],
            {"unit_armour_types_tables"},
        )
        armour_rows = effective["unit_armour_types_tables"]
        self.assertEqual(
            _armour_key_for_value("wh2_main_heavy_metal_60", 80, armour_rows),
            "wh2_main_heavy_metal_80",
        )
        self.assertEqual(
            _armour_key_for_value("wh2_main_body_10", 100, armour_rows),
            "wh2_main_body_100",
        )

    def test_base_visible_count_prefers_engines_then_mounts(self) -> None:
        main = {"num_men": 8}
        self.assertEqual(
            _base_visible_count(main, {"num_engines": 4, "num_mounts": 0}),
            (4, "num_engines"),
        )
        self.assertEqual(
            _base_visible_count(main, {"num_engines": 0, "num_mounts": 12}),
            (12, "num_mounts"),
        )
        self.assertEqual(
            _base_visible_count(main, {"num_engines": 0, "num_mounts": 0}),
            (8, "num_men"),
        )

    def test_language_loc_pack_preference(self) -> None:
        self.assertEqual(
            _language_loc_packs("zh-CN"),
            ("local_en.pack", "local_zh.pack", "local_cn.pack"),
        )
        self.assertEqual(_language_loc_packs("en-US"), ("local_en.pack",))
        self.assertEqual(
            _language_loc_packs("ja-JP"),
            ("local_en.pack",),
        )
        self.assertEqual(
            _language_loc_packs("es-ES"),
            ("local_en.pack", "local_sp.pack"),
        )
        self.assertEqual(_language_loc_packs("xx-XX"), ("local_en.pack",))

    def test_name_map_prefers_launcher_language_pack_over_fallback(self) -> None:
        import tempfile

        from backend.start_options import PackEntry, write_pfh5_pack

        def loc_payload(rows: list[tuple[str, str]]) -> bytes:
            payload = b"\xff\xfeLOC\x00" + struct.pack("<i", 1) + struct.pack(
                "<i", len(rows)
            )
            for key, text in rows:
                key_bytes = key.encode("utf-16le")
                text_bytes = text.encode("utf-16le")
                payload += (
                    struct.pack("<H", len(key))
                    + key_bytes
                    + struct.pack("<H", len(text))
                    + text_bytes
                    + b"\0"
                )
            return payload

        with tempfile.TemporaryDirectory(prefix="wmm_loc_") as raw:
            data = Path(raw)
            common_key = "land_units_onscreen_name_land_test"
            en = data / "local_en.pack"
            cn = data / "local_cn.pack"
            write_pfh5_pack(
                en,
                [PackEntry("text\\localisation__.loc", loc_payload([(common_key, "English Name")]))],
            )
            write_pfh5_pack(
                cn,
                [PackEntry("text\\localisation__.loc", loc_payload([(common_key, "简体名称")]))],
            )
            names, _cultures = collect_unit_name_map(data, [], "zh-CN")
            self.assertEqual(names["land_test"], "简体名称")
            names_en, _ = collect_unit_name_map(data, [], "en-US")
            self.assertEqual(names_en["land_test"], "English Name")

    def test_source_chain_shows_original_then_overrides(self) -> None:
        original = _fixture_source()
        override = DbSource(
            "sfo.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\sfo_data",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [
                            {
                                "unit": "inf_swordsmen",
                                "caste": "melee_infantry",
                                "land_unit": "land_inf_swordsmen",
                                "num_men": 120,
                            }
                        ],
                    ),
                ),
            ),
        )
        snapshot = build_unit_table_snapshot(
            [override, original],
            {},
            {},
        )
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(rows["inf_swordsmen"]["mod_name"], "原版")
        self.assertEqual(
            rows["inf_swordsmen"]["source_chain"],
            ["原版", "sfo.pack"],
        )

    def test_race_resolves_through_faction_and_subculture(self) -> None:
        snapshot = build_unit_table_snapshot(
            [_fixture_source()],
            {},
            {},
            culture_map={"wh_main_emp_empire": "帝国"},
        )
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(rows["veh_chariot"]["race"], "帝国")
        self.assertEqual(
            rows["veh_chariot"]["race_key"],
            "wh_main_emp_empire",
        )


if __name__ == "__main__":
    unittest.main()
