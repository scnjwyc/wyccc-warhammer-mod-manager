from __future__ import annotations

import hashlib
import json
import math
import struct
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .game_data import (
    DbSource,
    GameDataBuildResult,
    GameDataEntry,
    ParsedDbRow,
    _collect_effective_rows,
    _is_single_entity_unit,
    patch_db_row_value,
)


UNIT_EFFECT_TABLE = "unit_purchasable_effect_sets_tables"
UNIT_MISSILE_TABLE = "unit_missile_weapon_junctions_tables"
EFFECT_MISSILE_TABLE = "effect_bonus_value_missile_weapon_junctions_tables"
MAIN_UNIT_TABLE = "main_units_tables"
LAND_UNIT_TABLE = "land_units_tables"
MISSILE_WEAPON_TABLE = "missile_weapons_tables"
PROJECTILE_TABLE = "projectiles_tables"
EXPLOSION_TABLE = "projectiles_explosions_tables"

_DYNAMIC_EFFECT_MARKER = "dynamic_ror"
_SCRIPTED_AMMO_MARKER = "scripted_ammo_type_"
_DYNAMIC_ROR_MIN_TEMPLATE_UNITS = 64
_AMMO_SUFFIXES = frozenset(
    {
        "arcane_fire",
        "flaming",
        "magic",
        "anti_infantry",
        "anti_infantry_arcane_fire",
        "anti_infantry_flaming",
        "anti_infantry_magic",
        "anti_large",
        "anti_large_arcane_fire",
        "anti_large_flaming",
        "anti_large_magic",
    }
)


def _dynamic_ammo_suffix(effect_key: str) -> str:
    marker_index = effect_key.casefold().find(_SCRIPTED_AMMO_MARKER)
    if marker_index < 0:
        return ""
    return effect_key[marker_index + len(_SCRIPTED_AMMO_MARKER) :].casefold()


def _serialize_rows(
    table_name: str,
    versioned_rows: Sequence[tuple[int, ParsedDbRow]],
) -> list[GameDataEntry]:
    grouped: dict[int, list[ParsedDbRow]] = defaultdict(list)
    for version, row in versioned_rows:
        grouped[int(version)].append(row)
    entries: list[GameDataEntry] = []
    for version in sorted(grouped):
        rows = grouped[version]
        payload = b"".join(
            (
                b"\xfc\xfd\xfe\xff",
                struct.pack("<i", version),
                b"\1",
                struct.pack("<i", len(rows)),
                *(row.raw for row in rows),
            )
        )
        entries.append(
            GameDataEntry(
                (
                    f"db\\{table_name}\\"
                    f"!!!!wyccc_dynamic_ror_compatibility_v{version:04d}"
                ),
                payload,
            )
        )
    return entries


def _stable_key(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"wyccc_dr_{prefix}_{digest}"


def _allocate_junction_id(unit_key: str, suffix: str, used: set[int]) -> int:
    digest = hashlib.sha1(f"{unit_key}\0{suffix}".encode("utf-8")).digest()
    candidate = 1_500_000_000 + int.from_bytes(digest[:4], "little") % 600_000_000
    while candidate in used:
        candidate += 1
        if candidate > 2_100_000_000:
            candidate = 1_500_000_000
    used.add(candidate)
    return candidate


def _candidate_values(candidate: Any | None) -> Mapping[str, Any]:
    return candidate.row.values if candidate is not None else {}


def _is_ranged(land_values: Mapping[str, Any]) -> bool:
    return bool(str(land_values.get("primary_missile_weapon") or "").strip())


def _template_score(
    target_main: Mapping[str, Any],
    target_land: Mapping[str, Any],
    template_main: Mapping[str, Any],
    template_land: Mapping[str, Any],
) -> tuple[float, str]:
    score = 0.0
    comparisons = (
        ("caste", target_main, template_main, 50.0),
        ("category", target_land, template_land, 40.0),
        ("class", target_land, template_land, 25.0),
        ("audio_voiceover_culture", target_main, template_main, 12.0),
    )
    for field, target, template, penalty in comparisons:
        left = str(target.get(field) or "").casefold()
        right = str(template.get(field) or "").casefold()
        if left and right and left != right:
            score += penalty
        elif bool(left) != bool(right):
            score += penalty * 0.5

    boolean_comparisons = (
        (_is_ranged(target_land), _is_ranged(template_land), 90.0),
        (
            _is_single_entity_unit(target_main, target_land),
            _is_single_entity_unit(template_main, template_land),
            70.0,
        ),
        (bool(target_land.get("engine")), bool(template_land.get("engine")), 45.0),
        (bool(target_land.get("mount")), bool(template_land.get("mount")), 20.0),
        (bool(target_land.get("shield")), bool(template_land.get("shield")), 8.0),
    )
    for left, right, penalty in boolean_comparisons:
        if left != right:
            score += penalty

    target_cost = max(1, int(target_main.get("multiplayer_cost") or 1))
    template_cost = max(1, int(template_main.get("multiplayer_cost") or 1))
    score += min(30.0, abs(math.log(target_cost / template_cost)) * 12.0)
    return score, str(template_main.get("unit") or "")


def _unit_keywords(
    unit_key: str,
    main_values: Mapping[str, Any],
    land_values: Mapping[str, Any],
) -> list[str]:
    keywords: set[str] = set()
    caste = str(main_values.get("caste") or "").casefold()
    category = str(land_values.get("category") or "").casefold()
    unit_class = str(land_values.get("class") or "").casefold()
    combined = "_".join((unit_key.casefold(), caste, category, unit_class))

    if _is_single_entity_unit(main_values, land_values):
        keywords.add("single_entity")
    if category == "artillery" or caste == "artillery":
        keywords.add("artillery")
    if category in {"war_machine", "warmachine"} or caste in {
        "war_machine",
        "warmachine",
    }:
        keywords.add("warmachine")
    if "monster" in combined:
        keywords.add("monster")
    if "cavalry" in combined:
        keywords.add("cavalry")
    if "chariot" in combined:
        keywords.add("chariot")
    if _is_ranged(land_values):
        keywords.add("ranged")
        if any(marker in combined for marker in ("gun", "rifle", "pistol", "handgun")):
            keywords.add("powder_unit")
        if "crossbow" in combined:
            keywords.add("crossbow")
        elif any(marker in combined for marker in ("bow", "archer")):
            keywords.add("archer")
    if str(land_values.get("shield") or "").strip():
        keywords.add("shield_unit")
    if any(marker in combined for marker in ("halberd", "spear", "anti_large")):
        keywords.add("anti_large")
    return sorted(keywords)


def _lua_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _compatibility_script(unit_keywords: Mapping[str, Sequence[str]]) -> GameDataEntry:
    lines = [
        'local mod_name = "wyccc_generated_dynamic_ror_compatibility"',
        "local Unit_Keywords = {",
    ]
    for unit_key in sorted(unit_keywords, key=str.casefold):
        encoded_keywords = ", ".join(
            _lua_string(keyword) for keyword in unit_keywords[unit_key]
        )
        lines.append(f"    [{_lua_string(unit_key)}] = {{{encoded_keywords}}},")
    lines.extend(
        (
            "}",
            "",
            "if type(Dynamic_RoR_ModList) ~= 'table' or "
            "type(Dynamic_RoR_Modded_Unit_Keywords) ~= 'table' then",
            "    return",
            "end",
            "",
            "Dynamic_RoR_ModList[mod_name] = false",
            "core:add_listener(",
            "    'DynamicRoR_RegisterMod_' .. mod_name,",
            "    'DynamicRoR_RegisterMods',",
            "    true,",
            "    function()",
            "        local ok, error_message = pcall(function()",
            "            for unit_key, keywords in pairs(Unit_Keywords) do",
            "                local target = Dynamic_RoR_Modded_Unit_Keywords[unit_key]",
            "                if type(target) ~= 'table' then",
            "                    target = {}",
            "                    Dynamic_RoR_Modded_Unit_Keywords[unit_key] = target",
            "                end",
            "                for _, keyword in ipairs(keywords) do",
            "                    local exists = false",
            "                    for _, current in ipairs(target) do",
            "                        if current == keyword then exists = true break end",
            "                    end",
            "                    if not exists then table.insert(target, keyword) end",
            "                end",
            "            end",
            "        end)",
            "        if not ok and out then",
            "            out('[Wyccc Dynamic RoR Compatibility] ' .. tostring(error_message))",
            "        end",
            "        core:trigger_custom_event('DynamicRoRModReady', {mod_name = mod_name})",
            "    end,",
            "    true",
            ")",
            "",
        )
    )
    return GameDataEntry(
        "script\\campaign\\mod\\wyccc_dynamic_ror_compatibility.lua",
        "\n".join(lines).encode("utf-8"),
    )


def _apply_ammo_traits(row: ParsedDbRow, suffix: str) -> ParsedDbRow:
    result = row
    if suffix.startswith("anti_infantry"):
        result = patch_db_row_value(
            result,
            "bonus_v_infantry",
            int(result.values.get("bonus_v_infantry") or 0) + 10,
        )
    if suffix.startswith("anti_large"):
        result = patch_db_row_value(
            result,
            "bonus_v_large",
            int(result.values.get("bonus_v_large") or 0) + 15,
        )
    if "magic" in suffix or "arcane_fire" in suffix:
        result = patch_db_row_value(result, "is_magical", True)
    if "flaming" in suffix or "arcane_fire" in suffix:
        result = patch_db_row_value(result, "ignition_amount", 100.0)
    return result


def build_dynamic_ror_compatibility_entries(
    sources: Sequence[DbSource],
) -> GameDataBuildResult:
    """Generate Dynamic RoR DB and Lua rows for new units in enabled mods."""
    stats: dict[str, int | float] = {
        "dynamic_ror_detected": 0,
        "template_unit_count": 0,
        "eligible_mod_unit_count": 0,
        "patched_unit_count": 0,
        "effect_row_count": 0,
        "ammo_variant_count": 0,
        "missile_junction_count": 0,
    }
    if len(sources) < 2:
        return GameDataBuildResult((), stats)

    needed_tables = {
        MAIN_UNIT_TABLE,
        LAND_UNIT_TABLE,
        UNIT_EFFECT_TABLE,
        UNIT_MISSILE_TABLE,
        EFFECT_MISSILE_TABLE,
        MISSILE_WEAPON_TABLE,
        PROJECTILE_TABLE,
        EXPLOSION_TABLE,
    }
    all_candidates: dict[str, dict[str, list[Any]]] = {}
    effective = _collect_effective_rows(
        sources,
        needed_tables,
        skip_main_unit_compatibility_placeholders=True,
        all_candidates=all_candidates,
    )

    dynamic_rows_by_source: dict[int, list[Any]] = defaultdict(list)
    dynamic_units_by_source: dict[int, set[str]] = defaultdict(set)
    already_compatible: set[str] = set()
    for candidates in all_candidates.get(UNIT_EFFECT_TABLE, {}).values():
        for candidate in candidates:
            values = candidate.row.values
            effect_key = str(values.get("purchasable_effect") or "")
            if _DYNAMIC_EFFECT_MARKER not in effect_key.casefold():
                continue
            unit_key = str(values.get("unit") or "")
            if not unit_key:
                continue
            dynamic_rows_by_source[candidate.source_rank].append(candidate)
            dynamic_units_by_source[candidate.source_rank].add(unit_key)
            already_compatible.add(unit_key)

    if not dynamic_units_by_source:
        return GameDataBuildResult((), stats)
    nanu_source_rank, template_units = max(
        dynamic_units_by_source.items(),
        key=lambda item: (len(item[1]), -item[0]),
    )
    if len(template_units) < _DYNAMIC_ROR_MIN_TEMPLATE_UNITS:
        return GameDataBuildResult((), stats)
    stats["dynamic_ror_detected"] = 1
    stats["template_unit_count"] = len(template_units)

    main_rows = effective[MAIN_UNIT_TABLE]
    land_rows = effective[LAND_UNIT_TABLE]
    vanilla_main = _collect_effective_rows(
        (sources[-1],),
        {MAIN_UNIT_TABLE},
        skip_main_unit_compatibility_placeholders=True,
    )[MAIN_UNIT_TABLE]
    usable_templates = [
        unit_key
        for unit_key in template_units
        if unit_key in main_rows
        and str(main_rows[unit_key].row.values.get("land_unit") or "") in land_rows
    ]
    if not usable_templates:
        return GameDataBuildResult((), stats)

    mod_units: list[str] = []
    vanilla_rank = len(sources) - 1
    for unit_key, candidate in main_rows.items():
        values = candidate.row.values
        land_key = str(values.get("land_unit") or "")
        caste = str(values.get("caste") or "").casefold()
        if (
            candidate.source_rank >= vanilla_rank
            or unit_key in vanilla_main
            or unit_key in already_compatible
            or land_key not in land_rows
            or bool(values.get("is_naval"))
            or caste in {"lord", "hero"}
            or "renown" in unit_key.casefold()
            or "ror" in unit_key.casefold()
        ):
            continue
        mod_units.append(unit_key)
    stats["eligible_mod_unit_count"] = len(mod_units)
    if not mod_units:
        return GameDataBuildResult((), stats)

    # Every effect row owned by a Dynamic RoR unit is a template, not only the
    # rows whose key contains the marker.  Ammo variants such as
    # ``scripted_ammo_type_flaming`` are attached to the same unit but carry a
    # different effect key, so they must be collected here too.
    template_effects: dict[str, list[Any]] = defaultdict(list)
    for candidate in all_candidates.get(UNIT_EFFECT_TABLE, {}).values():
        for row_candidate in candidate:
            if row_candidate.source_rank != nanu_source_rank:
                continue
            unit_key = str(row_candidate.row.values.get("unit") or "")
            if unit_key in template_units:
                template_effects[unit_key].append(row_candidate)

    effect_mapping_scaffolds: dict[str, list[Any]] = defaultdict(list)
    for candidate in effective[EFFECT_MISSILE_TABLE].values():
        effect_key = str(candidate.row.values.get("effect") or "")
        if effect_key:
            effect_mapping_scaffolds[effect_key].append(candidate)
    unit_missile_scaffold = next(iter(effective[UNIT_MISSILE_TABLE].values()), None)

    used_junction_ids = {
        int(candidate.row.values.get("id") or 0)
        for candidate in effective[UNIT_MISSILE_TABLE].values()
        if 0 < int(candidate.row.values.get("id") or 0) <= 2_147_483_647
    }
    used_junction_ids.update(
        int(candidate.row.values.get("missile_weapon_junction") or 0)
        for candidate in effective[EFFECT_MISSILE_TABLE].values()
        if 0 < int(candidate.row.values.get("missile_weapon_junction") or 0) <= 2_147_483_647
    )

    generated: dict[str, list[tuple[int, ParsedDbRow]]] = defaultdict(list)
    generated_weapon_variants: dict[tuple[str, str], str] = {}
    unit_keywords: dict[str, list[str]] = {}

    for unit_key in sorted(mod_units, key=str.casefold):
        main_values = main_rows[unit_key].row.values
        land_key = str(main_values.get("land_unit") or "")
        land_values = land_rows[land_key].row.values
        template_key = min(
            usable_templates,
            key=lambda key: _template_score(
                main_values,
                land_values,
                main_rows[key].row.values,
                land_rows[str(main_rows[key].row.values.get("land_unit") or "")].row.values,
            ),
        )
        rows_added = 0
        for candidate in template_effects[template_key]:
            effect_key = str(candidate.row.values.get("purchasable_effect") or "")
            suffix = _dynamic_ammo_suffix(effect_key)
            if suffix and (
                suffix not in _AMMO_SUFFIXES
                or unit_missile_scaffold is None
                or f"nanu_ammo_type_{suffix}" not in effect_mapping_scaffolds
                or not _is_ranged(land_values)
            ):
                continue
            row = patch_db_row_value(candidate.row, "unit", unit_key)
            generated[UNIT_EFFECT_TABLE].append((candidate.version, row))
            rows_added += 1

        if rows_added == 0:
            continue
        stats["patched_unit_count"] = int(stats["patched_unit_count"]) + 1
        stats["effect_row_count"] = int(stats["effect_row_count"]) + rows_added
        unit_keywords[unit_key] = _unit_keywords(unit_key, main_values, land_values)

        base_weapon_key = str(land_values.get("primary_missile_weapon") or "")
        base_weapon = effective[MISSILE_WEAPON_TABLE].get(base_weapon_key)
        if base_weapon is None or unit_missile_scaffold is None:
            continue
        base_projectile_key = str(base_weapon.row.values.get("default_projectile") or "")
        base_projectile = effective[PROJECTILE_TABLE].get(base_projectile_key)
        if base_projectile is None:
            continue

        generated_effects = [
            str(row.values.get("purchasable_effect") or "")
            for _version, row in generated[UNIT_EFFECT_TABLE][-rows_added:]
        ]
        for effect_key in generated_effects:
            suffix = _dynamic_ammo_suffix(effect_key)
            if not suffix:
                continue
            cache_key = (base_weapon_key, suffix)
            variant_weapon_key = generated_weapon_variants.get(cache_key)
            if variant_weapon_key is None:
                variant_weapon_key = _stable_key("mw", base_weapon_key, suffix)
                variant_projectile_key = _stable_key("pr", base_projectile_key, suffix)
                projectile_row = patch_db_row_value(
                    _apply_ammo_traits(base_projectile.row, suffix),
                    "key",
                    variant_projectile_key,
                )
                explosion_key = str(projectile_row.values.get("explosion_type") or "")
                base_explosion = effective[EXPLOSION_TABLE].get(explosion_key)
                if base_explosion is not None and (
                    "magic" in suffix or "flaming" in suffix or "arcane_fire" in suffix
                ):
                    variant_explosion_key = _stable_key("ex", explosion_key, suffix)
                    explosion_row = patch_db_row_value(
                        _apply_ammo_traits(base_explosion.row, suffix),
                        "key",
                        variant_explosion_key,
                    )
                    generated[EXPLOSION_TABLE].append(
                        (base_explosion.version, explosion_row)
                    )
                    projectile_row = patch_db_row_value(
                        projectile_row,
                        "explosion_type",
                        variant_explosion_key,
                    )
                weapon_row = patch_db_row_value(
                    patch_db_row_value(base_weapon.row, "key", variant_weapon_key),
                    "default_projectile",
                    variant_projectile_key,
                )
                generated[MISSILE_WEAPON_TABLE].append((base_weapon.version, weapon_row))
                generated[PROJECTILE_TABLE].append((base_projectile.version, projectile_row))
                generated_weapon_variants[cache_key] = variant_weapon_key
                stats["ammo_variant_count"] = int(stats["ammo_variant_count"]) + 1

            junction_id = _allocate_junction_id(unit_key, suffix, used_junction_ids)
            junction_row = patch_db_row_value(
                patch_db_row_value(
                    patch_db_row_value(unit_missile_scaffold.row, "unit", unit_key),
                    "missile_weapon",
                    variant_weapon_key,
                ),
                "id",
                junction_id,
            )
            generated[UNIT_MISSILE_TABLE].append(
                (unit_missile_scaffold.version, junction_row)
            )
            for scaffold in effect_mapping_scaffolds[f"nanu_ammo_type_{suffix}"]:
                mapping_row = patch_db_row_value(
                    scaffold.row,
                    "missile_weapon_junction",
                    junction_id,
                )
                generated[EFFECT_MISSILE_TABLE].append((scaffold.version, mapping_row))
            stats["missile_junction_count"] = int(stats["missile_junction_count"]) + 1

    if not unit_keywords:
        return GameDataBuildResult((), stats)
    entries: list[GameDataEntry] = []
    for table_name in (
        UNIT_EFFECT_TABLE,
        MISSILE_WEAPON_TABLE,
        PROJECTILE_TABLE,
        EXPLOSION_TABLE,
        UNIT_MISSILE_TABLE,
        EFFECT_MISSILE_TABLE,
    ):
        entries.extend(_serialize_rows(table_name, generated.get(table_name, ())))
    entries.append(_compatibility_script(unit_keywords))
    return GameDataBuildResult(tuple(entries), stats)
