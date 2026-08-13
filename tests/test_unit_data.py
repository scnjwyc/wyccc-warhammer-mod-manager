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
    _collect_permission_rows,
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


def _guid_prefix(guid: str) -> bytes:
    return b"".join(
        (
            b"\xfd\xfe\xfc\xff",
            struct.pack("<H", len(guid)),
            guid.encode("utf-16le"),
        )
    )


def _guid_table_payload(
    table_name: str,
    version: int,
    rows: list[dict[str, Any]],
    guid: str,
) -> bytes:
    return _guid_prefix(guid) + _table_payload(table_name, version, rows)


def _string_u8(value: str) -> bytes:
    raw = value.encode("ascii")
    return struct.pack("<H", len(raw)) + raw


def _custom_battle_row(faction: str, unit: str) -> bytes:
    return b"".join(
        (
            _string_u8(faction),
            b"\0",  # general_unit
            _string_u8(unit),
            b"\1\1",  # siege_unit_attacker / siege_unit_defender
            b"\0\0\0",  # general portrait, uniform, set-piece character
            b"\0",  # campaign_exclusive
            b"\0",  # armory_item_set
            b"\0",  # supports_upgrades
        )
    )


def _custom_battle_payload(rows: list[bytes], guid: str) -> bytes:
    return b"".join(
        (
            _guid_prefix(guid),
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", 11),
            b"\1",
            struct.pack("<i", len(rows)),
            *rows,
        )
    )


def _allied_recruitment_payload(units: list[str], guid: str) -> bytes:
    return b"".join(
        (
            _guid_prefix(guid),
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", 0),
            b"\1",
            struct.pack("<i", len(units)),
            *(_string_u8(unit) for unit in units),
        )
    )


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
                            "morale": 55,
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
                            "mount": "mount_chariot",
                            "articulated_record": "art_chariot",
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
                            "engine": "engine_ballista",
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
                "db\\mounts_tables\\data__",
                _table_payload(
                    "mounts_tables",
                    10,
                    [
                        {
                            "key": "mount_chariot",
                            "animation": "animation_chariot",
                            "entity": "mount_chariot_entity",
                            "audio_armour_type": "body",
                            "variant": "variant_chariot",
                            "voiceover": "vo_default",
                        },
                    ],
                ),
            ),
            GameDataEntry(
                "db\\battlefield_engines_tables\\data__",
                _table_payload(
                    "battlefield_engines_tables",
                    23,
                    [
                        {
                            "key": "engine_ballista",
                            "battle_entity": "engine_ballista_entity",
                        },
                    ],
                ),
            ),
            GameDataEntry(
                "db\\land_unit_articulated_vehicles_tables\\data__",
                _table_payload(
                    "land_unit_articulated_vehicles_tables",
                    6,
                    [
                        {
                            "key": "art_chariot",
                            "articulated_entity": "art_chariot_entity",
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
                        {"key": "man_swordsmen", "hit_points": 60, "run_speed": 2.8, "size": "small", "mass": 100.0},
                        {"key": "man_chariot_crew", "hit_points": 55, "run_speed": 0.0, "size": "small", "mass": 100.0},
                        {"key": "mount_chariot_entity", "hit_points": 55, "run_speed": 6.4, "size": "large", "mass": 1000.0},
                        {"key": "art_chariot_entity", "hit_points": 55, "run_speed": 6.4, "size": "large", "mass": 1000.0},
                        {"key": "man_ballista_crew", "hit_points": 50, "run_speed": 3.0, "size": "small", "mass": 100.0},
                        {"key": "engine_ballista_entity", "hit_points": 100, "run_speed": 2.0, "size": "large", "mass": 2000.0},
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
                "db\\building_units_allowed_tables\\data__",
                _table_payload(
                    "building_units_allowed_tables",
                    4,
                    [
                        {
                            "building": "building_barracks",
                            "unit": "inf_swordsmen",
                            "XP": 0,
                            "key": 101,
                            "conditions": 0,
                            "faction": None,
                            "enabled": True,
                        },
                        {
                            "building": "building_stables",
                            "unit": "veh_chariot",
                            "XP": 0,
                            "key": 102,
                            "conditions": 0,
                            "faction": None,
                            "enabled": True,
                        },
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


def _engine_artillery_source() -> DbSource:
    """A Warhammer war machine whose missile weapon lives on its engine row.

    Real artillery leaves ``land_units.primary_missile_weapon`` empty and
    carries the weapon on ``battlefield_engines.missile_weapon`` instead, so
    any resolution that only follows ``primary_missile_weapon`` sees no
    projectile and reports zero ranged/explosion damage.
    """
    return DbSource(
        "artillery.pack",
        (
            GameDataEntry(
                "db\\main_units_tables\\data__",
                _table_payload(
                    "main_units_tables",
                    7,
                    [
                        {
                            "unit": "art_great_cannon",
                            "caste": "warmachine",
                            "land_unit": "land_art_great_cannon",
                            "num_men": 24,
                        }
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
                            "key": "land_art_great_cannon",
                            "man_entity": "man_artillery_crew",
                            "engine": "engine_great_cannon",
                            "primary_ammo": 8,
                            "reload": 10,
                            "accuracy": 30,
                            "num_engines": 4,
                            "rank_depth": 1,
                            "category": "artillery",
                            "spacing": "artillery",
                        }
                    ],
                ),
            ),
            GameDataEntry(
                "db\\battlefield_engines_tables\\data__",
                _table_payload(
                    "battlefield_engines_tables",
                    23,
                    [
                        {
                            "key": "engine_great_cannon",
                            "engine_type": "artillery",
                            "gun_animation_table": "anim",
                            "model": "model",
                            "battle_entity": "engine_great_cannon_entity",
                            "missile_weapon": "weap_great_cannon",
                            "riders_shoot_behaviour": "none",
                            "scale": 1.0,
                        }
                    ],
                ),
            ),
            GameDataEntry(
                "db\\battle_entities_tables\\data__",
                _table_payload(
                    "battle_entities_tables",
                    39,
                    [
                        {
                            "key": "man_artillery_crew",
                            "hit_points": 50,
                            "run_speed": 3.0,
                        },
                        {
                            "key": "engine_great_cannon_entity",
                            "hit_points": 120,
                            "run_speed": 2.0,
                        },
                    ],
                ),
            ),
            GameDataEntry(
                "db\\missile_weapons_tables\\data__",
                _table_payload(
                    "missile_weapons_tables",
                    11,
                    [
                        {
                            "key": "weap_great_cannon",
                            "precursor": False,
                            "default_projectile": "proj_great_cannon",
                            "audio_type": None,
                            "use_secondary_ammo_pool": False,
                        }
                    ],
                ),
            ),
            GameDataEntry(
                "db\\projectiles_tables\\data__",
                _table_payload(
                    "projectiles_tables",
                    53,
                    [
                        {
                            "key": "proj_great_cannon",
                            "category": "artillery",
                            "shot_type": "cannon",
                            "explosion_type": "expl_great_cannon",
                            "effective_range": 500,
                            "damage": 100,
                            "ap_damage": 250,
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
                            "key": "expl_great_cannon",
                            "detonator_type": "contact",
                            "detonation_type": "standard",
                            "detonation_damage": 30,
                            "detonation_damage_ap": 70,
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
        self.assertEqual(swordsmen["morale"], 55)
        self.assertEqual(swordsmen["hit_points"], 8)
        self.assertEqual(swordsmen["total_hp"], 8 * 90)
        self.assertEqual(swordsmen["charge_bonus"], 15)
        self.assertEqual(swordsmen["melee_attack"], 28)
        self.assertEqual(swordsmen["melee_defence"], 32)
        self.assertEqual(swordsmen["melee_damage"], 25)
        self.assertEqual(swordsmen["melee_ap_damage"], 8)
        self.assertEqual(swordsmen["melee_bonus_v_infantry"], 0)
        self.assertEqual(swordsmen["melee_bonus_v_large"], 0)
        self.assertEqual(swordsmen["armour_value"], 10)
        self.assertEqual(swordsmen["armour_options"], [10, 20, 100])
        self.assertEqual(swordsmen["original_values"]["campaign_cap"], 4)
        self.assertEqual(swordsmen["original_values"]["melee_damage"], 25)
        self.assertEqual(swordsmen["original_values"]["melee_bonus_v_large"], 0)
        self.assertEqual(swordsmen["original_values"]["model_count"], 90)

    def test_chariot_and_war_machine_use_real_entity_counts(self) -> None:
        snapshot = build_unit_table_snapshot([_fixture_source()], {})
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(rows["veh_chariot"]["model_count"], 12)
        self.assertEqual(rows["art_ballista"]["model_count"], 4)

    def test_warhammer_physical_values_resolve_from_unit_entities(self) -> None:
        snapshot = build_unit_table_snapshot([_fixture_source()], {})
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(rows["inf_swordsmen"]["body_size"], "small")
        self.assertEqual(rows["inf_swordsmen"]["mass"], 100.0)
        self.assertEqual(rows["veh_chariot"]["body_size"], "large")
        self.assertEqual(rows["veh_chariot"]["mass"], 1000.0)
        # War machines must resolve land_units.engine rather than the crew.
        self.assertEqual(rows["art_ballista"]["body_size"], "large")
        self.assertEqual(rows["art_ballista"]["mass"], 2000.0)
        self.assertFalse(rows["art_ballista"]["body_size_locked"])
        self.assertFalse(rows["art_ballista"]["mass_locked"])

    def test_engine_artillery_reads_missile_and_explosion_damage(self) -> None:
        snapshot = build_unit_table_snapshot([_engine_artillery_source()], {})
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertIn("art_great_cannon", rows)
        cannon = rows["art_great_cannon"]
        self.assertEqual(cannon["missile_damage"], 100)
        self.assertEqual(cannon["missile_ap_damage"], 250)
        self.assertEqual(cannon["explosion_damage"], 30)
        self.assertEqual(cannon["explosion_ap_damage"], 70)
        self.assertEqual(cannon["range"], 500)
        self.assertEqual(cannon["ammo"], 8)

    def test_warhammer_body_size_and_mass_edits_overlay_snapshot_values(self) -> None:
        snapshot = build_unit_table_snapshot(
            [_fixture_source()],
            {"inf_swordsmen": {"body_size": "large", "mass": 250.5}},
        )
        row = next(item for item in snapshot["units"] if item["key"] == "inf_swordsmen")
        self.assertEqual(row["body_size"], "large")
        self.assertEqual(row["mass"], 250.5)
        self.assertEqual(row["original_values"]["body_size"], "small")
        self.assertEqual(row["original_values"]["mass"], 100.0)

    def test_legacy_warhammer_movement_edit_is_ignored_in_snapshot(self) -> None:
        snapshot = build_unit_table_snapshot(
            [_fixture_source()],
            {"inf_swordsmen": {"movement_speed": 33.3}},
        )
        row = next(item for item in snapshot["units"] if item["key"] == "inf_swordsmen")
        self.assertEqual(row["edited"], {})
        self.assertEqual(snapshot["stats"]["edited_unit_count"], 0)

    def test_display_uses_base_values_without_game_data_multipliers(self) -> None:
        snapshot = build_unit_table_snapshot(
            [_fixture_source()],
            {},
        )
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(rows["inf_swordsmen"]["model_count"], 90)
        self.assertEqual(rows["inf_swordsmen"]["hit_points"], 8)
        self.assertEqual(rows["inf_swordsmen"]["total_hp"], 720)
        self.assertEqual(rows["veh_chariot"]["model_count"], 12)

    def test_single_entity_model_count_remains_editable(self) -> None:
        source = DbSource(
            "single_entity.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\single_entity_data",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [
                            {
                                "unit": "single_monster",
                                "caste": "monster",
                                "land_unit": "land_single_monster",
                                "num_men": 1,
                            }
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\land_units_tables\\single_entity_data",
                    _table_payload(
                        "land_units_tables",
                        54,
                        [
                            {
                                "key": "land_single_monster",
                                "rank_depth": 1,
                            }
                        ],
                    ),
                ),
            ),
        )

        snapshot = build_unit_table_snapshot(
            [source],
            {"single_monster": {"model_count": 3}},
        )
        row = snapshot["units"][0]

        self.assertFalse(row["model_count_locked"])
        self.assertEqual(row["model_count"], 3)

        patch = build_unit_data_entries(
            [source],
            {"unit_model_multiplier": 1},
            {"single_monster": {"model_count": 3}},
        )
        main = _rows_by_key(patch, "main_units_tables")
        self.assertEqual(main["single_monster"]["num_men"], 3)


class UnitDataPatchTests(unittest.TestCase):
    def test_disabled_unit_rebuilds_only_affected_permission_files_with_original_headers(self) -> None:
        target = "inf_swordsmen"
        building_guid = "11111111-1111-1111-1111-111111111111"
        grouping_guid = "22222222-2222-2222-2222-222222222222"
        source = DbSource(
            "mod.pack",
            (
                GameDataEntry(
                    "db\\building_units_allowed_tables\\mod_buildings",
                    _guid_table_payload(
                        "building_units_allowed_tables",
                        4,
                        [
                            {
                                "building": "mod_barracks",
                                "unit": target,
                                "XP": 0,
                                "key": 1,
                                "conditions": 0,
                                "faction": None,
                                "enabled": True,
                            },
                            {
                                "building": "mod_barracks",
                                "unit": "kept_unit",
                                "XP": 0,
                                "key": 2,
                                "conditions": 0,
                                "faction": None,
                                "enabled": True,
                            },
                        ],
                        building_guid,
                    ),
                ),
                GameDataEntry(
                    "db\\building_units_allowed_tables\\unrelated_buildings",
                    _guid_table_payload(
                        "building_units_allowed_tables",
                        4,
                        [
                            {
                                "building": "other_barracks",
                                "unit": "other_unit",
                                "XP": 0,
                                "key": 3,
                                "conditions": 0,
                                "faction": None,
                                "enabled": True,
                            }
                        ],
                        "33333333-3333-3333-3333-333333333333",
                    ),
                ),
                GameDataEntry(
                    "db\\units_to_groupings_military_permissions_tables\\mod_groups",
                    _guid_prefix(grouping_guid)
                    + _versionless_payload(
                        [
                            _grouping_row(target, "mod_group"),
                            _grouping_row("kept_unit", "mod_group"),
                        ]
                    ),
                ),
                GameDataEntry(
                    "db\\units_to_groupings_military_permissions_tables\\unrelated_groups",
                    _guid_prefix("44444444-4444-4444-4444-444444444444")
                    + _versionless_payload([_grouping_row("other_unit", "other_group")]),
                ),
            ),
        )

        result = build_unit_data_entries([source], {}, {target: {"enabled": False}})
        entries = {entry.name: entry.payload for entry in result.entries}

        building_name = "db\\building_units_allowed_tables\\mod_buildings"
        grouping_name = "db\\units_to_groupings_military_permissions_tables\\mod_groups"
        self.assertEqual(
            {
                name
                for name in entries
                if name.startswith("db\\building_units_allowed_tables\\")
                or name.startswith("db\\units_to_groupings_military_permissions_tables\\")
            },
            {building_name, grouping_name},
        )
        self.assertTrue(entries[building_name].startswith(_guid_prefix(building_guid)))
        self.assertTrue(entries[grouping_name].startswith(_guid_prefix(grouping_guid)))
        self.assertNotIn(target.encode("ascii"), entries[building_name])
        self.assertNotIn(target.encode("ascii"), entries[grouping_name])
        self.assertIn(b"kept_unit", entries[building_name])
        self.assertIn(b"kept_unit", entries[grouping_name])

    def test_disabled_unit_is_removed_from_custom_battle_permissions(self) -> None:
        target = "inf_swordsmen"
        guid = "55555555-5555-5555-5555-555555555555"
        source = DbSource(
            "mod.pack",
            (
                GameDataEntry(
                    "db\\units_custom_battle_permissions_tables\\mod_battle",
                    _custom_battle_payload(
                        [
                            _custom_battle_row("wh_main_emp_empire", target),
                            _custom_battle_row("wh_main_emp_empire", "kept_unit"),
                        ],
                        guid,
                    ),
                ),
            ),
        )

        result = build_unit_data_entries([source], {}, {target: {"enabled": False}})
        entries = {entry.name: entry.payload for entry in result.entries}
        payload = entries["db\\units_custom_battle_permissions_tables\\mod_battle"]

        self.assertTrue(payload.startswith(_guid_prefix(guid)))
        self.assertNotIn(target.encode("ascii"), payload)
        self.assertIn(b"kept_unit", payload)

    def test_disabled_unit_is_removed_from_allied_recruitment_permissions(self) -> None:
        target = "inf_swordsmen"
        guid = "66666666-6666-6666-6666-666666666666"
        source = DbSource(
            "mod.pack",
            (
                GameDataEntry(
                    "db\\allied_recruitment_unit_permissions_tables\\mod_allies",
                    _allied_recruitment_payload([target, "kept_unit"], guid),
                ),
            ),
        )

        result = build_unit_data_entries([source], {}, {target: {"enabled": False}})
        entries = {entry.name: entry.payload for entry in result.entries}
        payload = entries["db\\allied_recruitment_unit_permissions_tables\\mod_allies"]

        self.assertTrue(payload.startswith(_guid_prefix(guid)))
        self.assertNotIn(target.encode("ascii"), payload)
        self.assertIn(b"kept_unit", payload)

    def test_applies_edits_across_joined_tables(self) -> None:
        source = _fixture_source()
        edits = {
            "inf_swordsmen": {
                "campaign_cap": 9,
                "recruitment_cost": 600,
                "upkeep_cost": 200,
                "model_count": 120,
                "morale": 70,
                "armour": 100,
                "hit_points": 80,
                "charge_bonus": 30,
                "missile_resistance": 25,
                "melee_damage": 40,
                "melee_ap_damage": 12,
                "melee_bonus_v_infantry": 6,
                "melee_bonus_v_large": 18,
            }
        }
        result = build_unit_data_entries([source], {"unit_model_multiplier": 1}, edits)
        main = _rows_by_key(result, "main_units_tables")
        self.assertEqual(main["inf_swordsmen"]["num_men"], 120)
        self.assertEqual(main["inf_swordsmen"]["campaign_cap"], 9)
        land = _rows_by_key(result, "land_units_tables")
        self.assertEqual(land["land_inf_swordsmen"]["morale"], 70)
        self.assertEqual(land["land_inf_swordsmen"]["charge_bonus"], 30)
        self.assertEqual(land["land_inf_swordsmen"]["damage_mod_missile"], 25)
        self.assertEqual(land["land_inf_swordsmen"]["armour"], "wh2_main_body_100")
        self.assertEqual(land["land_inf_swordsmen"]["bonus_hit_points"], 80)
        entities = _rows_by_key(result, "battle_entities_tables")
        self.assertNotIn("man_swordsmen", entities)
        melee = _rows_by_key(result, "melee_weapons_tables")
        self.assertEqual(melee["weap_sword"]["damage"], 40)
        self.assertEqual(melee["weap_sword"]["ap_damage"], 12)
        self.assertEqual(melee["weap_sword"]["bonus_v_infantry"], 6)
        self.assertEqual(melee["weap_sword"]["bonus_v_large"], 18)

    def test_engine_artillery_missile_and_explosion_edits_are_written(self) -> None:
        source = _engine_artillery_source()
        result = build_unit_data_entries(
            [source],
            {},
            {
                "art_great_cannon": {
                    "missile_damage": 120,
                    "explosion_damage": 45,
                    "explosion_ap_damage": 95,
                }
            },
        )
        projectiles = _rows_by_key(result, "projectiles_tables")
        self.assertEqual(projectiles["proj_great_cannon"]["damage"], 120)
        self.assertEqual(projectiles["proj_great_cannon"]["ap_damage"], 250)
        self.assertEqual(projectiles["proj_great_cannon"]["effective_range"], 500)
        explosions = _rows_by_key(result, "projectiles_explosions_tables")
        self.assertEqual(explosions["expl_great_cannon"]["detonation_damage"], 45)
        self.assertEqual(explosions["expl_great_cannon"]["detonation_damage_ap"], 95)
        # The land row keeps its engine reference untouched: artillery carries
        # the weapon through battlefield_engines.missile_weapon, and the engine
        # still points at the same projectile keys, now overlaid with edits.
        self.assertEqual(_rows_by_key(result, "land_units_tables"), {})

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
        self.assertEqual(exclusive, {})
        buildings = _rows_by_key(result, "building_units_allowed_tables")
        self.assertNotIn("inf_swordsmen", buildings)
        self.assertTrue(buildings["veh_chariot"]["enabled"])

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

    def test_body_size_and_mass_edit_clone_entity_without_changing_speed(self) -> None:
        source = _fixture_source()
        result = build_unit_data_entries(
            [source],
            {},
            {"inf_swordsmen": {"body_size": "large", "mass": 250.5}},
        )
        land = _rows_by_key(result, "land_units_tables")
        entities = _rows_by_key(result, "battle_entities_tables")
        clone_keys = [key for key in entities if key.startswith("wyccc_wh3_battle_entity_")]
        self.assertEqual(len(clone_keys), 1)
        self.assertEqual(land["land_inf_swordsmen"]["man_entity"], clone_keys[0])
        self.assertEqual(entities[clone_keys[0]]["size"], "large")
        self.assertAlmostEqual(entities[clone_keys[0]]["mass"], 250.5, places=5)
        self.assertAlmostEqual(entities[clone_keys[0]]["run_speed"], 2.8, places=5)
        self.assertEqual(entities["man_swordsmen"]["size"], "small")
        self.assertAlmostEqual(entities["man_swordsmen"]["mass"], 100.0, places=5)
        self.assertAlmostEqual(entities["man_swordsmen"]["run_speed"], 2.8, places=5)

    def test_war_machine_physical_edit_clones_engine_not_crew_entity(self) -> None:
        result = build_unit_data_entries(
            [_fixture_source()],
            {},
            {"art_ballista": {"body_size": "medium", "mass": 1500.0}},
        )
        land = _rows_by_key(result, "land_units_tables")
        engines = _rows_by_key(result, "battlefield_engines_tables")
        entities = _rows_by_key(result, "battle_entities_tables")
        entity_clone_keys = [
            key for key in entities if key.startswith("wyccc_wh3_battle_entity_")
        ]
        engine_clone_keys = [
            key
            for key in engines
            if key.startswith("wyccc_wh3_battlefield_engines_")
        ]
        self.assertEqual(len(entity_clone_keys), 1)
        self.assertEqual(len(engine_clone_keys), 1)
        self.assertEqual(land["land_art_ballista"]["engine"], engine_clone_keys[0])
        self.assertEqual(
            engines[engine_clone_keys[0]]["battle_entity"], entity_clone_keys[0]
        )
        self.assertEqual(land["land_art_ballista"]["man_entity"], "man_ballista_crew")
        self.assertEqual(entities[entity_clone_keys[0]]["size"], "medium")
        self.assertAlmostEqual(entities[entity_clone_keys[0]]["mass"], 1500.0, places=5)
        self.assertAlmostEqual(entities[entity_clone_keys[0]]["run_speed"], 2.0, places=5)
        self.assertEqual(entities["engine_ballista_entity"]["size"], "large")
        self.assertAlmostEqual(entities["man_ballista_crew"]["run_speed"], 3.0, places=5)

    def test_chariot_physical_edit_clones_mount_and_articulated_entities(self) -> None:
        result = build_unit_data_entries(
            [_fixture_source()],
            {},
            {"veh_chariot": {"body_size": "medium", "mass": 750.0}},
        )
        land = _rows_by_key(result, "land_units_tables")
        mounts = _rows_by_key(result, "mounts_tables")
        articulated = _rows_by_key(result, "land_unit_articulated_vehicles_tables")
        entities = _rows_by_key(result, "battle_entities_tables")
        entity_clone_keys = [
            key for key in entities if key.startswith("wyccc_wh3_battle_entity_")
        ]
        self.assertEqual(len(entity_clone_keys), 2)
        self.assertEqual(land["land_veh_chariot"]["man_entity"], "man_chariot_crew")
        self.assertAlmostEqual(entities["man_chariot_crew"]["run_speed"], 0.0, places=5)
        mount_clone_key = land["land_veh_chariot"]["mount"]
        articulated_clone_key = land["land_veh_chariot"]["articulated_record"]
        self.assertTrue(mount_clone_key.startswith("wyccc_wh3_mounts_"))
        self.assertTrue(articulated_clone_key.startswith("wyccc_wh3_land_unit_articulated_vehicles_"))
        self.assertIn(mount_clone_key, mounts)
        self.assertIn(articulated_clone_key, articulated)
        self.assertIn(mounts[mount_clone_key]["entity"], entity_clone_keys)
        self.assertIn(articulated[articulated_clone_key]["articulated_entity"], entity_clone_keys)
        for entity_key in entity_clone_keys:
            self.assertEqual(entities[entity_key]["size"], "medium")
            self.assertAlmostEqual(entities[entity_key]["mass"], 750.0, places=5)
            self.assertAlmostEqual(entities[entity_key]["run_speed"], 6.4, places=5)

    def test_legacy_warhammer_movement_edit_produces_no_entries(self) -> None:
        result = build_unit_data_entries(
            [_fixture_source()],
            {},
            {"inf_swordsmen": {"movement_speed": 35.0}},
        )
        self.assertEqual(result.entries, ())
        self.assertEqual(result.stats["edited_unit_count"], 0)


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

    def test_sanitize_edits_normalizes_body_size_to_supported_dropdown_values(self) -> None:
        cleaned = _sanitize_edits(
            {
                "unit_a": {"body_size": "VERY_LARGE", "mass": 100.0},
                "unit_b": {"body_size": "colossal"},
            }
        )
        self.assertEqual(cleaned, {"unit_a": {"body_size": "large", "mass": 100.0}})

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

    def test_same_mod_loc_names_follow_enabled_mod_order(self) -> None:
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

        with tempfile.TemporaryDirectory(prefix="wmm_mod_loc_order_") as raw:
            data = Path(raw)
            common_key = "land_units_onscreen_name_sfo_new_unit"
            sfo = data / "sfo.pack"
            translation = data / "sfo_zh.pack"
            write_pfh5_pack(
                sfo,
                [
                    PackEntry(
                        "text\\localisation__.loc",
                        loc_payload([(common_key, "SFO New Unit")]),
                    )
                ],
            )
            write_pfh5_pack(
                translation,
                [
                    PackEntry(
                        "text\\localisation__.loc",
                        loc_payload([(common_key, "SFO 新单位")]),
                    )
                ],
            )

            names, _cultures = collect_unit_name_map(
                data,
                [translation, sfo],
                "zh-CN",
            )
            self.assertEqual(names["sfo_new_unit"], "SFO 新单位")

            reversed_names, _ = collect_unit_name_map(
                data,
                [sfo, translation],
                "zh-CN",
            )
            self.assertEqual(reversed_names["sfo_new_unit"], "SFO New Unit")

    def test_mod_loc_internal_name_takes_priority_before_enabled_order(self) -> None:
        import tempfile

        from backend.start_options import PackEntry, write_pfh5_pack

        def loc_payload(key: str, text: str) -> bytes:
            key_bytes = key.encode("utf-16le")
            text_bytes = text.encode("utf-16le")
            return b"".join(
                (
                    b"\xff\xfeLOC\x00",
                    struct.pack("<i", 1),
                    struct.pack("<i", 1),
                    struct.pack("<H", len(key)),
                    key_bytes,
                    struct.pack("<H", len(text)),
                    text_bytes,
                    b"\0",
                )
            )

        with tempfile.TemporaryDirectory(prefix="wmm_mod_loc_name_") as raw:
            data = Path(raw)
            common_key = "land_units_onscreen_name_shared_unit"
            base = data / "base.pack"
            priority = data / "priority.pack"
            write_pfh5_pack(
                base,
                [PackEntry("text\\z_base.loc", loc_payload(common_key, "Base Name"))],
            )
            write_pfh5_pack(
                priority,
                [
                    PackEntry(
                        "text\\!priority.loc",
                        loc_payload(common_key, "Priority Name"),
                    )
                ],
            )

            for ordered_packs in ([base, priority], [priority, base]):
                with self.subTest(ordered_packs=[path.name for path in ordered_packs]):
                    names, _cultures = collect_unit_name_map(
                        data,
                        ordered_packs,
                        "en-US",
                    )
                    self.assertEqual(names["shared_unit"], "Priority Name")

    def test_permission_table_internal_name_takes_priority_before_enabled_order(self) -> None:
        def source(pack_name: str, internal_name: str, exclusive: bool) -> DbSource:
            return DbSource(
                pack_name,
                (
                    GameDataEntry(
                        "db\\units_to_exclusive_faction_permissions_tables\\"
                        + internal_name,
                        _versionless_payload(
                            [_exclusive_row("shared_unit", "shared_faction", exclusive)]
                        ),
                    ),
                ),
            )

        lower_name = source("lower.pack", "z_permissions", False)
        higher_name = source("higher.pack", "!permissions", True)

        for ordered_sources in ([lower_name, higher_name], [higher_name, lower_name]):
            with self.subTest(ordered_sources=[item.name for item in ordered_sources]):
                rows = _collect_permission_rows(
                    ordered_sources,
                    "units_to_exclusive_faction_permissions_tables",
                )
                self.assertTrue(
                    rows[("shared_unit", "shared_faction")].row.values["exclusive"]
                )

    def test_source_chain_shows_original_then_overrides(self) -> None:
        original = _fixture_source()
        override = DbSource(
            "sfo.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\!sfo_data",
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
        )
        rows = {row["key"]: row for row in snapshot["units"]}
        self.assertEqual(rows["inf_swordsmen"]["mod_name"], "原版")
        self.assertEqual(
            rows["inf_swordsmen"]["source_chain"],
            ["原版", "sfo.pack"],
        )

    def test_mod_table_outranks_vanilla_regardless_of_internal_name(self) -> None:
        base = _fixture_source()
        vanilla = DbSource(base.name, base.entries, role="vanilla")
        sfo = DbSource(
            "sfo.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\zzz_sfo_data",
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

        snapshot = build_unit_table_snapshot([sfo, vanilla], {})
        row = next(item for item in snapshot["units"] if item["key"] == "inf_swordsmen")

        self.assertEqual(row["model_count"], 120)
        self.assertEqual(row["source_chain"], ["原版", "sfo.pack"])

    def test_permission_mod_row_outranks_vanilla_regardless_of_internal_name(self) -> None:
        vanilla = DbSource(
            "db.pack",
            (
                GameDataEntry(
                    "db\\units_to_exclusive_faction_permissions_tables\\!vanilla",
                    _versionless_payload(
                        [_exclusive_row("shared_unit", "shared_faction", False)]
                    ),
                ),
            ),
            role="vanilla",
        )
        mod = DbSource(
            "sfo.pack",
            (
                GameDataEntry(
                    "db\\units_to_exclusive_faction_permissions_tables\\zzz_sfo",
                    _versionless_payload(
                        [_exclusive_row("shared_unit", "shared_faction", True)]
                    ),
                ),
            ),
        )

        rows = _collect_permission_rows(
            [mod, vanilla],
            "units_to_exclusive_faction_permissions_tables",
        )

        self.assertTrue(
            rows[("shared_unit", "shared_faction")].row.values["exclusive"]
        )

    def test_source_chain_follows_internal_db_priority_before_source_order(self) -> None:
        original = _fixture_source()

        def override_source(name: str, internal_name: str, num_men: int) -> DbSource:
            return DbSource(
                name,
                (
                    GameDataEntry(
                        "db\\main_units_tables\\" + internal_name,
                        _table_payload(
                            "main_units_tables",
                            7,
                            [
                                {
                                    "unit": "inf_swordsmen",
                                    "caste": "melee_infantry",
                                    "land_unit": "land_inf_swordsmen",
                                    "num_men": num_men,
                                }
                            ],
                        ),
                    ),
                ),
            )

        lowest = override_source("compatibility.pack", "z_compatibility", 60)
        highest = override_source("overhaul.pack", "!overhaul", 120)
        snapshot = build_unit_table_snapshot([lowest, highest, original], {})
        row = next(item for item in snapshot["units"] if item["key"] == "inf_swordsmen")

        self.assertEqual(row["model_count"], 120)
        self.assertEqual(len(row["source_chain"]), 3)
        self.assertEqual(row["source_chain"][0], "compatibility.pack")
        self.assertEqual(row["source_chain"][-1], "overhaul.pack")
        self.assertEqual(row["mod_name"], "compatibility.pack")

    def test_race_resolves_through_faction_and_subculture(self) -> None:
        snapshot = build_unit_table_snapshot(
            [_fixture_source()],
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
