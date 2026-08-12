from __future__ import annotations

import hashlib
import math
import re
import struct
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cmp_to_key, lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from .game_data import (
    GameDataBuildResult,
    GameDataEntry,
    ParsedDbRow,
    _clamped_i32,
    _collect_effective_rows,
    _compare_candidate_priority,
    _compare_internal_names,
    _generated_internal_name,
    _patch_i32,
    _round_half_up_i32,
    is_three_kingdoms_game,
    parse_db_table,
    patch_db_row_value,
)


# Display fields that the unit-data editor can write.  The values are the
# JSON keys used by both the frontend table and the persisted edit store.
EDITABLE_FIELDS = frozenset(
    {
        "enabled",
        "campaign_cap",
        "recruitment_cost",
        "upkeep_cost",
        "model_count",
        "morale",
        "armour",
        "hit_points",
        "charge_bonus",
        "melee_attack",
        "melee_defence",
        "ammo",
        "reload",
        "accuracy",
        "missile_resistance",
        "fire_resistance",
        "magic_resistance",
        "physical_resistance",
        "ward_save",
        "missile_block_chance",
        "movement_speed",
        "body_size",
        "mass",
        "melee_attack_speed",
        "ranged_attack_speed",
        "melee_damage",
        "melee_ap_damage",
        "melee_bonus_v_cavalry",
        "melee_bonus_v_infantry",
        "melee_bonus_v_large",
        "missile_damage",
        "missile_ap_damage",
        "missile_bonus_v_cavalry",
        "missile_bonus_v_infantry",
        "range",
        "explosion_damage",
        "explosion_ap_damage",
    }
)

_ARMOUR_SUFFIX_RE = re.compile(r"^(?P<prefix>.*)_(?P<value>\d+)$")
_BODY_SIZE_VALUES = frozenset({"small", "medium", "large"})
_BODY_SIZE_ALIASES = {
    "very_small": "small",
    "very_large": "large",
}


@dataclass(frozen=True)
class _PermissionRow:
    row: ParsedDbRow
    version: int
    internal_name: str
    source_rank: int
    entry_rank: int
    row_rank: int
    key: tuple[str, ...]
    unit_key: str


@dataclass(frozen=True)
class _LocValue:
    text: str
    internal_name: str
    entry_rank: int


def _sanitize_edits(raw_edits: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Normalize the persisted/UI edit map into ``{unit_key: {field: value}}``."""
    if not isinstance(raw_edits, Mapping):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for unit_key, fields in raw_edits.items():
        if not isinstance(fields, Mapping):
            continue
        cleaned: dict[str, Any] = {}
        for raw_field, value in fields.items():
            field = str(raw_field)
            if field not in EDITABLE_FIELDS or value is None or value == "":
                continue
            if field == "body_size":
                normalized_size = _normalize_body_size(value)
                if not normalized_size:
                    continue
                cleaned[field] = normalized_size
                continue
            cleaned[field] = value
        if cleaned:
            normalized[str(unit_key)] = cleaned
    return normalized


def _normalize_body_size(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    normalized = _BODY_SIZE_ALIASES.get(normalized, normalized)
    return normalized if normalized in _BODY_SIZE_VALUES else ""


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _clamp_int(value: Any, minimum: int | None = None) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    if not math.isfinite(numeric):
        numeric = 0.0
    rounded = int(math.floor(numeric + 0.5))
    if minimum is not None:
        rounded = max(rounded, minimum)
    return _clamped_i32(rounded)


# ---------------------------------------------------------------------------
# Localisation name resolution
# ---------------------------------------------------------------------------

_LOC_MAGIC = b"LOC\x00"

# Vanilla localisation packs chosen by the launcher interface language.  Each
# tuple is ordered from least to most preferred; English is the universal
# fallback because WH3 ships no Japanese pack and the chosen language may be
# missing entirely.
LANGUAGE_LOC_PACKS: dict[str, tuple[str, ...]] = {
    "zh-CN": ("local_en.pack", "local_zh.pack", "local_cn.pack"),
    "en-US": ("local_en.pack",),
    "ko-KR": ("local_en.pack", "local_kr.pack"),
    "ru-RU": ("local_en.pack", "local_ru.pack"),
    "ja-JP": ("local_en.pack",),
    "es-ES": ("local_en.pack", "local_sp.pack"),
}


def _language_loc_packs(language: str) -> tuple[str, ...]:
    normalized = str(language or "").strip()
    for code, packs in LANGUAGE_LOC_PACKS.items():
        if normalized.casefold() == code.casefold():
            return packs
    return LANGUAGE_LOC_PACKS["en-US"]


def _parse_loc_payload(
    payload: bytes,
) -> tuple[dict[str, str], dict[str, str]]:
    """Parse a WH3 loc payload into ``(unit_names, culture_names)``."""
    if (
        len(payload) < 14
        or payload[:2] != b"\xff\xfe"
        or payload[2:6] != _LOC_MAGIC
    ):
        return {}, {}
    row_count = struct.unpack_from("<i", payload, 10)[0]
    if row_count < 0 or row_count > 2_000_000:
        return {}, {}
    cursor = 14
    unit_names: dict[str, str] = {}
    culture_names: dict[str, str] = {}
    _UNIT_PREFIX = "land_units_onscreen_name_"
    _CULTURE_PREFIX = "cultures_name_"
    for _ in range(row_count):
        if cursor + 2 > len(payload):
            break
        key_length = struct.unpack_from("<H", payload, cursor)[0]
        cursor += 2
        if key_length > 1024 or cursor + key_length * 2 > len(payload):
            break
        key = payload[cursor : cursor + key_length * 2].decode(
            "utf-16le", errors="replace"
        )
        cursor += key_length * 2
        if cursor + 2 > len(payload):
            break
        text_length = struct.unpack_from("<H", payload, cursor)[0]
        cursor += 2
        if text_length > 8192 or cursor + text_length * 2 > len(payload):
            break
        text = payload[cursor : cursor + text_length * 2].decode(
            "utf-16le", errors="replace"
        )
        cursor += text_length * 2
        if cursor >= len(payload):
            break
        cursor += 1  # per-row language byte
        if key.startswith(_UNIT_PREFIX):
            unit_names[key[len(_UNIT_PREFIX) :]] = text
        elif key.startswith(_CULTURE_PREFIX):
            culture_names[key[len(_CULTURE_PREFIX) :]] = text
    return unit_names, culture_names


@lru_cache(maxsize=12)
def _load_loc_file(
    path_text: str,
    _mtime_ns: int,
) -> tuple[dict[str, _LocValue], dict[str, _LocValue]]:
    try:
        path = Path(path_text)
        if not path.is_file():
            return {}, {}
        from .start_options import read_pack_entries

        merged_units: dict[str, _LocValue] = {}
        merged_cultures: dict[str, _LocValue] = {}
        for entry_rank, entry in enumerate(read_pack_entries(path, "text\\")):
            if entry.name.casefold().endswith(".loc"):
                normalized_name = entry.name.replace("/", "\\")
                internal_name = normalized_name.split("\\", 1)[-1]
                units, cultures = _parse_loc_payload(entry.payload)
                for target, values in (
                    (merged_units, units),
                    (merged_cultures, cultures),
                ):
                    for key, text in values.items():
                        candidate = _LocValue(text, internal_name, entry_rank)
                        existing = target.get(key)
                        if existing is None or _has_loc_priority(
                            candidate,
                            0,
                            existing,
                            0,
                        ):
                            target[key] = candidate
        return merged_units, merged_cultures
    except (OSError, ValueError):
        return {}, {}


def _has_loc_priority(
    candidate: _LocValue,
    candidate_source_rank: int,
    existing: _LocValue,
    existing_source_rank: int,
) -> bool:
    file_order = _compare_internal_names(
        candidate.internal_name,
        existing.internal_name,
    )
    if file_order:
        return file_order < 0
    if candidate_source_rank != existing_source_rank:
        return candidate_source_rank < existing_source_rank
    return candidate.entry_rank < existing.entry_rank


def _file_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _heuristic_unit_name(unit_key: str) -> str:
    """Derive a readable name from a unit key when no loc entry exists."""
    cleaned = re.sub(r"^(wh\d+|wh)_(main|dlc\d+|pro\d+|twa\d+|cp\d+)_", "", unit_key)
    cleaned = re.sub(r"^[a-z]{3}_", "", cleaned)
    cleaned = re.sub(r"_\d+$", "", cleaned)
    cleaned = cleaned.replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else unit_key


def _display_source_name(source: Any) -> str:
    """Shorten a DbSource name like ``MOD "SFO" [pack: ...]`` to the mod name."""
    name = str(getattr(source, "name", "") or "")
    if name.startswith('MOD "'):
        end = name.find('"', 5)
        if end > 0:
            return name[5:end]
    if name.startswith("原版数据库") or "db.pack" in name:
        return "原版"
    return name


def collect_unit_name_map(
    data_path: str | Path,
    mod_loc_files: Sequence[Path],
    language: str = "",
) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(unit_names, culture_names)`` using the vanilla loc pack for
    the launcher language (English fallback) plus enabled mod loc files; mod
    files override vanilla.  Among MODs, the internal LOC name has priority;
    enabled-mod order only breaks ties between identical internal names."""
    data_root = Path(data_path).resolve(strict=False)
    unit_names: dict[str, str] = {}
    culture_names: dict[str, str] = {}
    for pack_name in _language_loc_packs(language):
        path = (data_root / pack_name).resolve(strict=False)
        units, cultures = _load_loc_file(str(path), _file_mtime_ns(path))
        unit_names.update({key: value.text for key, value in units.items()})
        culture_names.update({key: value.text for key, value in cultures.items()})
    # Keep vanilla language packs as the fallback, then merge MOD loc files
    # separately.  A MOD must override vanilla, but among MODs the enabled
    # internal LOC name is authoritative.  Enabled load order is consulted
    # only when two packs provide the key through the same internal LOC name.
    mod_unit_names: dict[str, tuple[_LocValue, int]] = {}
    mod_culture_names: dict[str, tuple[_LocValue, int]] = {}
    resolved_mods = [Path(path).resolve(strict=False) for path in mod_loc_files]
    if len(resolved_mods) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(resolved_mods))) as pool:
            loaded = list(
                pool.map(
                    lambda path: (
                        path,
                        _load_loc_file(str(path), _file_mtime_ns(path)),
                    ),
                    resolved_mods,
                )
            )
    else:
        loaded = [
            (path, _load_loc_file(str(path), _file_mtime_ns(path)))
            for path in resolved_mods
        ]

    for source_rank, (_path, (units, cultures)) in enumerate(loaded):
        for target, values in (
            (mod_unit_names, units),
            (mod_culture_names, cultures),
        ):
            for key, candidate in values.items():
                existing = target.get(key)
                if existing is None or _has_loc_priority(
                    candidate,
                    source_rank,
                    existing[0],
                    existing[1],
                ):
                    target[key] = (candidate, source_rank)
    unit_names.update({key: value.text for key, (value, _rank) in mod_unit_names.items()})
    culture_names.update(
        {key: value.text for key, (value, _rank) in mod_culture_names.items()}
    )
    return unit_names, culture_names


# ---------------------------------------------------------------------------
# Recruitment permission rows
# ---------------------------------------------------------------------------

_PERMISSION_TABLES = (
    "building_units_allowed_tables",
    "units_to_groupings_military_permissions_tables",
    "units_to_exclusive_faction_permissions_tables",
)

_WARHAMMER_ADDITIONAL_PERMISSION_TABLES = (
    "allied_recruitment_unit_permissions_tables",
    "units_custom_battle_permissions_tables",
)

_PERMISSION_KEY_FIELDS = {
    "building_units_allowed_tables": ("key",),
    "units_to_groupings_military_permissions_tables": ("unit", "military_group"),
    "units_to_exclusive_faction_permissions_tables": ("unit", "faction"),
    "allied_recruitment_unit_permissions_tables": ("unit",),
    "units_custom_battle_permissions_tables": ("unit", "faction", "general_unit"),
}

_THREE_KINGDOMS_PERMISSION_KEY_FIELDS = {
    "building_units_allowed_tables": ("key",),
    "units_to_groupings_military_permissions_tables": ("unit", "military_group"),
    "units_to_exclusive_faction_permissions_tables": ("key", "faction"),
}


def _permission_row_key(
    table_name: str,
    values: Mapping[str, Any],
    game_id: str | None = None,
) -> tuple[str, ...]:
    key_fields = (
        _THREE_KINGDOMS_PERMISSION_KEY_FIELDS
        if is_three_kingdoms_game(game_id)
        else _PERMISSION_KEY_FIELDS
    )
    return tuple(
        "" if values.get(field) is None else str(values.get(field) or "")
        for field in key_fields[table_name]
    )


def _permission_unit_key(
    table_name: str,
    values: Mapping[str, Any],
    game_id: str | None = None,
) -> str:
    if table_name == "building_units_allowed_tables":
        return str(values.get("unit") or "")
    key_fields = (
        _THREE_KINGDOMS_PERMISSION_KEY_FIELDS
        if is_three_kingdoms_game(game_id)
        else _PERMISSION_KEY_FIELDS
    )
    return str(values.get(key_fields[table_name][0]) or "")


def _permission_tables_for_game(game_id: str | None = None) -> tuple[str, ...]:
    if is_three_kingdoms_game(game_id):
        return _PERMISSION_TABLES
    return (*_PERMISSION_TABLES, *_WARHAMMER_ADDITIONAL_PERMISSION_TABLES)


def _collect_permission_rows(
    sources: Sequence[Any],
    table_name: str,
    game_id: str | None = None,
) -> dict[tuple[str, ...], _PermissionRow]:
    """Collect permission rows using internal DB name, then source order."""
    from .game_data import _entry_table_name

    effective: dict[tuple[str, ...], _PermissionRow] = {}
    for source_rank, source in enumerate(sources):
        for entry_rank, entry in enumerate(source.entries):
            resolved = _entry_table_name(entry.name)
            if not resolved or resolved[0] != table_name:
                continue
            parsed = parse_db_table(table_name, entry.payload, game_id)
            for row_rank, row in enumerate(parsed.rows):
                values = row.values
                # ``building_units_allowed`` uses a numeric row key as its
                # primary key, while every other supported permission table
                # stores the unit reference in its first permission key.
                unit_key = _permission_unit_key(table_name, values, game_id)
                if not unit_key:
                    raise ValueError(
                        f"{source.name} 中的 {entry.name} 存在空 unit 主键"
                    )
                key = _permission_row_key(table_name, values, game_id)
                candidate = _PermissionRow(
                    row,
                    parsed.version,
                    resolved[1],
                    source_rank,
                    entry_rank,
                    row_rank,
                    key,
                    unit_key,
                )
                existing = effective.get(key)
                if existing is None or _has_permission_priority(candidate, existing):
                    effective[key] = candidate
    return effective


def _has_permission_priority(candidate: _PermissionRow, existing: _PermissionRow) -> bool:
    file_order = _compare_internal_names(
        candidate.internal_name, existing.internal_name
    )
    if file_order:
        return file_order < 0
    if candidate.source_rank != existing.source_rank:
        return candidate.source_rank < existing.source_rank
    return (candidate.entry_rank, candidate.row_rank) < (
        existing.entry_rank,
        existing.row_rank,
    )


# ---------------------------------------------------------------------------
# Unit snapshot
# ---------------------------------------------------------------------------

UNIT_TABLES = (
    "main_units_tables",
    "land_units_tables",
    "mounts_tables",
    "battlefield_engines_tables",
    "land_unit_articulated_vehicles_tables",
    "battle_entities_tables",
    "melee_weapons_tables",
    "missile_weapons_tables",
    "projectiles_tables",
    "projectiles_explosions_tables",
    "unit_armour_types_tables",
    *_PERMISSION_TABLES,
)

# Tables joined per unit for the editor table; recruitment permission tables
# are collected separately with their own multi-row merge, and the shared
# battle_entities table is deliberately excluded (model HP lives on land_units).
UNIT_JOIN_TABLES = tuple(
    table
    for table in UNIT_TABLES
    if table not in _PERMISSION_TABLES and table != "battle_entities_tables"
)

THREE_KINGDOMS_UNIT_TABLES = (
    "main_units_tables",
    "land_units_tables",
    "land_units_templates_tables",
    "composed_entities_tables",
    "battle_entities_tables",
    "mens_tables",
    "mounts_tables",
    "animals_tables",
    "battlefield_engines_tables",
    "melee_weapons_tables",
    "missile_weapons_tables",
    "projectiles_tables",
    "projectiles_explosions_tables",
    "unit_armour_types_tables",
    "unit_shield_types_tables",
    *_PERMISSION_TABLES,
)
THREE_KINGDOMS_UNIT_JOIN_TABLES = tuple(
    table for table in THREE_KINGDOMS_UNIT_TABLES if table not in _PERMISSION_TABLES
)

# Tables joined only for the editor table (race resolution), not for patching.
RACE_TABLES = ("factions_tables", "cultures_subcultures_tables")


def _unit_join_tables(game_id: str | None) -> tuple[str, ...]:
    return THREE_KINGDOMS_UNIT_JOIN_TABLES if is_three_kingdoms_game(game_id) else UNIT_JOIN_TABLES


_THREE_KINGDOMS_HIDDEN_FIELDS = frozenset(
    {
        "body_size",
        "mass",
        "missile_resistance",
        "fire_resistance",
        "magic_resistance",
        "physical_resistance",
        "ward_save",
    }
)
_WARHAMMER_HIDDEN_FIELDS = frozenset({"movement_speed"})


def _edits_for_game(
    raw_edits: Mapping[str, Any] | None,
    game_id: str | None,
) -> dict[str, dict[str, Any]]:
    """Return only the editor fields supported by the selected game."""
    hidden_fields = (
        _THREE_KINGDOMS_HIDDEN_FIELDS
        if is_three_kingdoms_game(game_id)
        else _WARHAMMER_HIDDEN_FIELDS
    )
    return {
        unit_key: {
            field: value
            for field, value in fields.items()
            if field not in hidden_fields
        }
        for unit_key, fields in _sanitize_edits(raw_edits).items()
        if any(field not in hidden_fields for field in fields)
    }

_THREE_KINGDOMS_ENTITY_REFERENCE_TABLES = {
    "man": ("mens_tables", "battle_entity"),
    "mount": ("mounts_tables", "entity"),
    "animal": ("animals_tables", "entity"),
    "engine": ("battlefield_engines_tables", "battle_entity"),
}


def _base_visible_count(
    main_values: Mapping[str, Any],
    land_values: Mapping[str, Any],
) -> tuple[int, str]:
    """Return the real visible entity count and the DB field that carries it.

    Infantry/cavalry/monsters use ``num_men``; chariots and mounted units are
    counted by ``num_mounts``; war machines and artillery by ``num_engines``.
    """
    num_engines = int(land_values.get("num_engines") or 0)
    num_mounts = int(land_values.get("num_mounts") or 0)
    if num_engines > 0:
        return num_engines, "num_engines"
    if num_mounts > 0:
        return num_mounts, "num_mounts"
    return int(main_values.get("num_men") or 0), "num_men"


def _three_kingdoms_components(
    effective: Mapping[str, Mapping[str, Any]],
    land_unit: str,
) -> list[tuple[str, Any, Mapping[str, Any]]]:
    """Resolve the composed-entity rows that make up one Three Kingdoms unit."""
    components: list[tuple[str, Any, Mapping[str, Any]]] = []
    composed_entities = effective["composed_entities_tables"]
    for key, template in effective["land_units_templates_tables"].items():
        values = template.row.values
        if str(values.get("land_unit") or "") != land_unit:
            continue
        composed = composed_entities.get(str(values.get("composed_entity") or ""))
        if composed is not None:
            components.append((key, template, composed.row.values))
    return components


def _three_kingdoms_unit_shape(
    effective: Mapping[str, Mapping[str, Any]],
    main_values: Mapping[str, Any],
    land_unit: str,
) -> dict[str, Any]:
    """Return editor-safe model and health facts for one Three Kingdoms unit."""
    components = _three_kingdoms_components(effective, land_unit)
    engine_components = [
        item for item in components if int(item[2].get("num_engines") or 0) > 0
    ]
    mount_components = [
        item for item in components if int(item[2].get("num_mounts") or 0) > 0
    ]
    animal_components = [
        item for item in components if int(item[2].get("num_animals") or 0) > 0
    ]
    man_components = [
        item for item in components if int(item[2].get("num_men") or 0) > 0
    ]
    visible_components = (
        engine_components or mount_components or animal_components or man_components
    )
    model_count = sum(
        int(template.row.values.get("num_composed_entities") or 0)
        for _key, template, _composed in visible_components
    )
    total_hp = sum(
        int(template.row.values.get("hp_pool") or 0)
        for _key, template, _composed in components
    )
    hp_per_model: int | None = None
    ratios: list[float] = []
    for _key, template, _composed in components:
        values = template.row.values
        count = int(values.get("num_composed_entities") or 0)
        if count <= 0:
            ratios = []
            break
        ratios.append(float(values.get("hp_pool") or 0) / count)
    if ratios and all(math.isclose(value, ratios[0], abs_tol=1e-6) for value in ratios):
        rounded = _round_half_up_i32(ratios[0], minimum=0)
        if math.isclose(ratios[0], rounded, abs_tol=1e-6):
            hp_per_model = rounded
    return {
        "components": components,
        "visible_component_keys": {key for key, _template, _composed in visible_components},
        "model_count": model_count,
        "model_count_locked": (
            str(main_values.get("caste") or "").casefold() in {"lord", "hero"}
            or model_count <= 0
        ),
        "hit_points": hp_per_model if hp_per_model is not None else 0,
        "hit_points_locked": hp_per_model is None,
        "total_hp": total_hp,
    }


def _three_kingdoms_movement_components(
    effective: Mapping[str, Mapping[str, Any]],
    shape: Mapping[str, Any],
) -> list[tuple[str, str, Any, str, Any, Any]] | None:
    """Resolve the visible Three Kingdoms components to their battle entities.

    A unit's speed is owned by its battle entity rather than its land-unit
    record.  Return ``None`` when one visible component cannot be traced
    safely; callers then lock the single aggregate speed control.
    """
    resolved: list[tuple[str, str, Any, str, Any, Any]] = []
    visible_keys = set(shape["visible_component_keys"])
    for template_key, _template, composed_values in shape["components"]:
        if template_key not in visible_keys:
            continue
        if int(composed_values.get("num_engines") or 0) > 0:
            role = "engine"
        elif int(composed_values.get("num_mounts") or 0) > 0:
            role = "mount"
        elif int(composed_values.get("num_animals") or 0) > 0:
            role = "animal"
        elif int(composed_values.get("num_men") or 0) > 0:
            role = "man"
        else:
            return None
        reference_table, entity_field = _THREE_KINGDOMS_ENTITY_REFERENCE_TABLES[role]
        reference_key = str(composed_values.get(role) or "")
        reference = effective[reference_table].get(reference_key)
        if reference is None:
            return None
        entity_key = str(reference.row.values.get(entity_field) or "")
        entity = effective["battle_entities_tables"].get(entity_key)
        if entity is None:
            return None
        composed_key = str(composed_values.get("key") or "")
        if not composed_key:
            return None
        resolved.append(
            (
                template_key,
                role,
                effective["composed_entities_tables"][composed_key],
                reference_table,
                reference,
                entity,
            )
        )
    return resolved or None


def _three_kingdoms_movement_shape(
    effective: Mapping[str, Mapping[str, Any]],
    shape: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a safe, unit-level run-speed value for Three Kingdoms."""
    components = _three_kingdoms_movement_components(effective, shape)
    if components is None:
        return {"components": (), "movement_speed": 0.0, "movement_speed_locked": True}
    speeds = [
        float(entity.row.values.get("run_speed") or 0.0)
        for *_rest, entity in components
    ]
    if not speeds or not all(math.isclose(value, speeds[0], abs_tol=1e-6) for value in speeds):
        return {
            "components": components,
            "movement_speed": 0.0,
            "movement_speed_locked": True,
        }
    return {
        "components": components,
        "movement_speed": speeds[0],
        "movement_speed_locked": False,
    }


def _warhammer_entity_shape(
    effective: Mapping[str, Mapping[str, Any]],
    land_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve all WH3 battle entities that represent a unit's physical body.

    ``land_units`` stores references to component records rather than always
    pointing directly at ``battle_entities``: mounts use ``mounts.entity``,
    engines use ``battlefield_engines.battle_entity``, and articulated
    vehicles use ``land_unit_articulated_vehicles.articulated_entity``.  A
    plain unit with none of those components uses its ``man_entity``.  The
    same component chain is used for display and cloning, so size/mass edits
    are isolated to one unit instead of changing an entity shared by MODs.
    """
    components: list[dict[str, Any]] = []

    def add_direct(role: str, land_field: str) -> None:
        entity_key = str(land_values.get(land_field) or "")
        if not entity_key:
            return
        entity = effective.get("battle_entities_tables", {}).get(entity_key)
        if entity is None:
            return
        components.append(
            {
                "role": role,
                "land_field": land_field,
                "reference_table": None,
                "reference": None,
                "entity_field": None,
                "entity": entity,
                "entity_key": entity_key,
            }
        )

    def add_reference(
        role: str,
        land_field: str,
        table_name: str,
        entity_field: str,
    ) -> None:
        reference_key = str(land_values.get(land_field) or "")
        if not reference_key:
            return
        reference = effective.get(table_name, {}).get(reference_key)
        if reference is None:
            # A few older or third-party DBs use the battle-entity key
            # directly in land_units.  Preserve that layout as a fallback
            # when the intermediate reference table is absent.
            add_direct(role, land_field)
            return
        entity_key = str(reference.row.values.get(entity_field) or "")
        entity = effective.get("battle_entities_tables", {}).get(entity_key)
        if entity is None:
            add_direct(role, land_field)
            return
        components.append(
            {
                "role": role,
                "land_field": land_field,
                "reference_table": table_name,
                "reference": reference,
                "entity_field": entity_field,
                "entity": entity,
                "entity_key": entity_key,
            }
        )

    # A composite unit may use all of these.  Do not use man_entity as a
    # substitute when a component exists: crew entities commonly have zero
    # movement speed and are not the entity moving the chariot.
    add_reference("mount", "mount", "mounts_tables", "entity")
    add_reference(
        "engine",
        "engine",
        "battlefield_engines_tables",
        "battle_entity",
    )
    add_reference(
        "articulated",
        "articulated_record",
        "land_unit_articulated_vehicles_tables",
        "articulated_entity",
    )
    if not components:
        add_direct("man", "man_entity")

    if not components:
        return {
            "components": (),
            "body_size": "",
            "body_size_locked": True,
            "mass": 0.0,
            "mass_locked": True,
        }
    body_sizes = [
        _normalize_body_size(component["entity"].row.values.get("size"))
        for component in components
    ]
    masses = [
        _clamp_float(component["entity"].row.values.get("mass"), minimum=0)
        for component in components
    ]
    body_size_consistent = bool(body_sizes) and all(
        value and value == body_sizes[0] for value in body_sizes
    )
    mass_consistent = bool(masses) and all(
        math.isclose(value, masses[0], abs_tol=1e-6) for value in masses
    )
    return {
        "components": tuple(components),
        "body_size": body_sizes[0] if body_size_consistent else "",
        "body_size_locked": not body_size_consistent,
        "mass": masses[0] if mass_consistent else 0.0,
        "mass_locked": not mass_consistent,
    }


def _armour_info(
    armour_key: Any,
    armour_rows: Mapping[str, Any],
) -> dict[str, Any]:
    key = str(armour_key or "")
    row = armour_rows.get(key)
    row_values = row.row.values if row is not None else {}
    value = int(row_values.get("armour_value") or 0) if row is not None else 0
    audio_type = row_values.get("audio_type") if row is not None else None
    options = sorted(
        {
            int(candidate.row.values.get("armour_value") or 0)
            for candidate in armour_rows.values()
            if candidate.row.values.get("audio_type") == audio_type
        }
    )
    return {
        "key": key,
        "value": value,
        "audio_type": audio_type,
        "options": options,
    }


def _armour_key_for_value(
    current_key: str,
    value: Any,
    armour_rows: Mapping[str, Any],
) -> str:
    numeric = _clamp_int(value, minimum=0)
    match = _ARMOUR_SUFFIX_RE.match(current_key)
    if match:
        rebuilt = f"{match.group('prefix')}_{numeric}"
        if rebuilt in armour_rows:
            return rebuilt
    current = armour_rows.get(current_key)
    audio_type = (
        current.row.values.get("audio_type") if current is not None else None
    )
    for key, candidate in armour_rows.items():
        if (
            candidate.row.values.get("audio_type") == audio_type
            and int(candidate.row.values.get("armour_value") or 0) == numeric
        ):
            return key
    if match:
        return f"{match.group('prefix')}_{numeric}"
    return current_key


def _unit_missile_weapon(
    effective: Mapping[str, Mapping[str, Any]],
    land_values: Mapping[str, Any],
) -> Any:
    """Resolve the missile weapon row for a land unit.

    Most ranged units reference it through land_units.primary_missile_weapon,
    but artillery/warmachines leave that field empty and carry the weapon on
    their engine row instead (battlefield_engines.missile_weapon).
    """
    key = str(land_values.get("primary_missile_weapon") or "")
    if not key:
        engine_key = str(land_values.get("engine") or "")
        if engine_key:
            engine = effective.get("battlefield_engines_tables", {}).get(engine_key)
            if engine is not None:
                key = str(engine.row.values.get("missile_weapon") or "")
    if not key:
        return None
    return effective.get("missile_weapons_tables", {}).get(key)


def _unit_edits_for(
    edits: Mapping[str, Mapping[str, Any]],
    unit_key: str,
    game_id: str | None = None,
) -> dict[str, Any]:
    entry = edits.get(unit_key)
    if not isinstance(entry, Mapping):
        return {}
    fields = dict(entry)
    if is_three_kingdoms_game(game_id):
        fields = {
            field: value
            for field, value in fields.items()
            if field not in _THREE_KINGDOMS_HIDDEN_FIELDS
        }
    else:
        fields = {
            field: value
            for field, value in fields.items()
            if field not in _WARHAMMER_HIDDEN_FIELDS
        }
    return fields


def _ordered_source_ranks(candidates: Sequence[Any]) -> list[int]:
    """Return contributing sources from lowest to highest effective DB priority."""
    best_by_source: dict[int, Any] = {}
    for candidate in candidates:
        existing = best_by_source.get(candidate.source_rank)
        if existing is None or _compare_candidate_priority(candidate, existing) < 0:
            best_by_source[candidate.source_rank] = candidate
    ordered = sorted(
        best_by_source.items(),
        key=cmp_to_key(
            lambda first, second: _compare_candidate_priority(first[1], second[1])
        ),
        reverse=True,
    )
    return [source_rank for source_rank, _candidate in ordered]


def build_unit_table_snapshot(
    sources: Sequence[Any],
    edits: Mapping[str, Mapping[str, Any]],
    name_map: Mapping[str, str] | None = None,
    culture_map: Mapping[str, str] | None = None,
    source_names: Sequence[str] | None = None,
    game_id: str | None = None,
) -> dict[str, Any]:
    """Project base DB values plus unit edits, without game-data multipliers."""
    all_candidates: dict[str, dict[str, list[Any]]] = {}
    unit_tables = set(_unit_join_tables(game_id)) | set(RACE_TABLES)
    if not is_three_kingdoms_game(game_id):
        # WH3 physical size and mass are owned by a shared battle entity.
        # Keep that table out of the flattened editor row, but collect its
        # effective rows so edited entities can be cloned safely.
        unit_tables.add("battle_entities_tables")
    effective = _collect_effective_rows(
        sources,
        unit_tables,
        game_id=game_id,
        skip_main_unit_compatibility_placeholders=True,
        all_candidates=all_candidates,
    )
    armour_rows = effective["unit_armour_types_tables"]
    names = dict(name_map or {})
    cultures = dict(culture_map or {})
    resolved_source_names = (
        list(source_names)
        if source_names is not None
        else [_display_source_name(source) for source in sources]
    )

    faction_cultures: dict[str, str] = {}
    for candidate in effective["factions_tables"].values():
        faction_cultures[candidate.row.values["key"]] = str(
            candidate.row.values.get("subculture") or ""
        )
    military_group_subcultures: dict[str, set[str]] = {}
    for candidate in effective["factions_tables"].values():
        values = candidate.row.values
        group = str(values.get("military_group") or "")
        if group:
            military_group_subcultures.setdefault(group, set()).add(
                str(values.get("subculture") or "")
            )
    subculture_cultures: dict[str, str] = {}
    for candidate in effective["cultures_subcultures_tables"].values():
        subculture_cultures[candidate.row.values["subculture"]] = str(
            candidate.row.values.get("culture") or ""
        )
    exclusive_factions: dict[str, str] = {}
    for permission in _collect_permission_rows(
        sources, "units_to_exclusive_faction_permissions_tables", game_id
    ).values():
        exclusive_factions.setdefault(permission.key[0], permission.key[1])
    unit_military_groups: dict[str, set[str]] = {}
    for permission in _collect_permission_rows(
        sources, "units_to_groupings_military_permissions_tables", game_id
    ).values():
        unit_military_groups.setdefault(permission.key[0], set()).add(
            permission.key[1]
        )
    sorted_cultures = tuple(sorted(cultures))

    def resolve_race(unit_key: str) -> tuple[str, str]:
        faction = exclusive_factions.get(unit_key)
        if faction:
            subculture = faction_cultures.get(faction)
            if subculture:
                culture = subculture_cultures.get(subculture)
                if culture:
                    return culture, cultures.get(culture, culture)
        prefix = "_".join(str(unit_key).split("_")[:3])
        if len(prefix) > 3:
            for culture in sorted_cultures:
                if culture.startswith(prefix + "_"):
                    return culture, cultures.get(culture, culture)
        culture_votes: dict[str, int] = {}
        for group in unit_military_groups.get(unit_key, ()):
            for subculture in military_group_subcultures.get(group, ()):
                culture = subculture_cultures.get(subculture)
                if culture and culture in cultures:
                    culture_votes[culture] = culture_votes.get(culture, 0) + 1
        if culture_votes:
            best = min(
                culture_votes,
                key=lambda culture: (-culture_votes[culture], culture),
            )
            return best, cultures.get(best, best)
        return "", ""

    visible_edits = _edits_for_game(edits, game_id)
    rows: list[dict[str, Any]] = []
    missing_land: list[str] = []
    for unit_key, candidate in effective["main_units_tables"].items():
        main_values = candidate.row.values
        land_unit = str(main_values.get("land_unit") or "")
        land_candidate = effective["land_units_tables"].get(land_unit)
        land_values = land_candidate.row.values if land_candidate is not None else {}
        if land_candidate is None:
            missing_land.append(f"{unit_key} -> {land_unit or '<empty>'}")
            continue

        if is_three_kingdoms_game(game_id):
            three_kingdoms_shape = _three_kingdoms_unit_shape(
                effective,
                main_values,
                land_unit,
            )
            bonus_hit_points = int(three_kingdoms_shape["hit_points"])
            model_count = int(three_kingdoms_shape["model_count"])
            model_count_locked = bool(three_kingdoms_shape["model_count_locked"])
            hit_points_locked = bool(three_kingdoms_shape["hit_points_locked"])
            total_hp = int(three_kingdoms_shape["total_hp"])
            movement_shape = _three_kingdoms_movement_shape(
                effective,
                three_kingdoms_shape,
            )
            movement_speed = float(movement_shape["movement_speed"])
            movement_speed_locked = bool(movement_shape["movement_speed_locked"])
            shield = effective["unit_shield_types_tables"].get(
                str(land_values.get("shield") or "")
            )
            missile_block_chance = _clamp_int(
                shield.row.values.get("missile_block_chance") if shield else 0,
                minimum=0,
            )
            missile_block_chance_locked = shield is None
            # Three Kingdoms stores the base attack interval on the linked
            # melee weapon, not in the unit's percentage modifier column.
            melee_attack_speed_locked = True
            ranged_attack_speed_locked = (
                "reload_time_reduction_percentage" not in land_candidate.row.fields
            )
        else:
            # Model HP is owned by the unit itself (land_units.bonus_hit_points).
            # battle_entities.hit_points is shared across many units and is
            # deliberately excluded from both the value and the edit path.
            bonus_hit_points = int(land_values.get("bonus_hit_points") or 0)
            model_count, _count_field = _base_visible_count(main_values, land_values)
            model_count_locked = False
            hit_points_locked = False
            total_hp = _clamped_i32(bonus_hit_points * model_count)
            physical_shape = _warhammer_entity_shape(effective, land_values)
            movement_speed = 0.0
            movement_speed_locked = True
            body_size = str(physical_shape["body_size"])
            body_size_locked = bool(physical_shape["body_size_locked"])
            mass = float(physical_shape["mass"])
            mass_locked = bool(physical_shape["mass_locked"])
            missile_block_chance = 0
            missile_block_chance_locked = True
            melee_attack_speed_locked = True
            ranged_attack_speed_locked = True
        melee = effective["melee_weapons_tables"].get(
            str(land_values.get("primary_melee_weapon") or "")
        )
        melee_values = melee.row.values if melee is not None else {}
        if is_three_kingdoms_game(game_id):
            melee_attack_speed_locked = (
                melee is None or "melee_attack_interval" not in melee.row.fields
            )
        missile_weapon = _unit_missile_weapon(effective, land_values)
        projectile = None
        projectile_values: dict[str, Any] = {}
        explosion_values: dict[str, Any] = {}
        if missile_weapon is not None:
            projectile = effective["projectiles_tables"].get(
                str(missile_weapon.row.values.get("default_projectile") or "")
            )
            if projectile is not None:
                projectile_values = projectile.row.values
                explosion = effective["projectiles_explosions_tables"].get(
                    str(projectile_values.get("explosion_type") or "")
                )
                if explosion is not None:
                    explosion_values = explosion.row.values

        armour = _armour_info(land_values.get("armour"), armour_rows)
        if is_three_kingdoms_game(game_id):
            body_size = ""
            body_size_locked = True
            mass = 0.0
            mass_locked = True
        unit_edits = _unit_edits_for(visible_edits, unit_key, game_id)
        original_model_count = model_count

        original_values = {
            "enabled": True,
            "campaign_cap": _clamp_int(main_values.get("campaign_cap")),
            "recruitment_cost": _clamp_int(main_values.get("recruitment_cost")),
            "upkeep_cost": _clamp_int(main_values.get("upkeep_cost")),
            "model_count": original_model_count,
            "morale": _clamp_int(land_values.get("morale"), minimum=0),
            "armour": armour["value"],
            "hit_points": _clamp_int(bonus_hit_points, minimum=0),
            "charge_bonus": _clamp_int(land_values.get("charge_bonus")),
            "melee_attack": _clamp_int(land_values.get("melee_attack")),
            "melee_defence": _clamp_int(land_values.get("melee_defence")),
            "ammo": _clamp_int(land_values.get("primary_ammo"), minimum=0),
            "missile_resistance": _clamp_int(land_values.get("damage_mod_missile")),
            "fire_resistance": _clamp_int(land_values.get("damage_mod_flame")),
            "magic_resistance": _clamp_int(land_values.get("damage_mod_magic")),
            "physical_resistance": _clamp_int(land_values.get("damage_mod_physical")),
            "ward_save": _clamp_int(land_values.get("damage_mod_all")),
            "missile_block_chance": missile_block_chance,
            "movement_speed": movement_speed,
            "body_size": body_size,
            "mass": mass,
            "melee_attack_speed": (
                _round_float(
                    melee_values.get("melee_attack_interval"),
                    digits=1,
                    minimum=0,
                )
                if is_three_kingdoms_game(game_id)
                else 0
            ),
            "ranged_attack_speed": _clamp_int(
                land_values.get("reload_time_reduction_percentage"),
                minimum=0,
            ),
            "melee_damage": _clamp_int(melee_values.get("damage")),
            "melee_ap_damage": _clamp_int(melee_values.get("ap_damage")),
            "melee_bonus_v_cavalry": _clamp_int(melee_values.get("bonus_v_cavalry")),
            "melee_bonus_v_infantry": _clamp_int(melee_values.get("bonus_v_infantry")),
            "melee_bonus_v_large": _clamp_int(melee_values.get("bonus_v_large")),
            "missile_damage": _clamp_int(projectile_values.get("damage")),
            "missile_ap_damage": _clamp_int(projectile_values.get("ap_damage")),
            "missile_bonus_v_cavalry": _clamp_int(
                projectile_values.get("bonus_v_cavalry")
            ),
            "missile_bonus_v_infantry": _clamp_int(
                projectile_values.get("bonus_v_infantry")
            ),
            "explosion_damage": _clamp_int(
                explosion_values.get("detonation_damage")
            ),
            "explosion_ap_damage": _clamp_int(
                explosion_values.get("detonation_damage_ap")
            ),
            "range": _clamp_int(projectile_values.get("effective_range")),
            "reload": _clamp_int(
                (
                    projectile_values.get("base_reload_time")
                    if is_three_kingdoms_game(game_id)
                    else land_values.get("reload")
                ),
                minimum=0,
            ),
            "accuracy": _clamp_int(land_values.get("accuracy"), minimum=0),
        }

        def merged(field: str, current: Any, minimum: int | None = None) -> int:
            if field in unit_edits:
                return _clamp_int(unit_edits[field], minimum)
            return _clamp_int(current, minimum)

        def merged_float(
            field: str,
            current: Any,
            minimum: float | None = None,
            digits: int | None = None,
        ) -> float:
            value = (
                _clamp_float(unit_edits[field], minimum)
                if field in unit_edits
                else _clamp_float(current, minimum)
            )
            return round(value, digits) if digits is not None else value

        if "model_count" in unit_edits and not model_count_locked:
            wanted = _clamp_int(unit_edits["model_count"], minimum=1)
            model_count = wanted

        edited_enabled = unit_edits.get("enabled")
        enabled = (
            _coerce_bool(edited_enabled)
            if edited_enabled is not None
            else True
        )

        effective_hit_points = (
            merged("hit_points", bonus_hit_points, minimum=0)
            if not hit_points_locked
            else bonus_hit_points
        )
        if not hit_points_locked:
            total_hp = _clamped_i32(effective_hit_points * model_count)
        land_name = str(land_values.get("key") or "")
        chain_candidates = all_candidates.get("main_units_tables", {}).get(
            unit_key, ()
        )
        chain_ranks = _ordered_source_ranks(chain_candidates)
        # Present the actual DB overlay order: original/lowest priority first,
        # then each progressively higher-priority source.
        source_chain = [
            resolved_source_names[rank]
            if rank < len(resolved_source_names)
            else ""
            for rank in chain_ranks
        ]
        original_mod_name = (
            source_chain[0]
            if source_chain
            else (
                resolved_source_names[candidate.source_rank]
                if candidate.source_rank < len(resolved_source_names)
                else ""
            )
        )
        race_key, race_name = resolve_race(unit_key)
        rows.append(
            {
                "key": unit_key,
                "mod_name": original_mod_name,
                "source_chain": source_chain,
                "race": race_name,
                "race_key": race_key,
                "name": names.get(land_name) or _heuristic_unit_name(unit_key),
                "land_unit": land_unit,
                "caste": str(main_values.get("caste") or ""),
                "enabled": enabled,
                "enabled_locked": (
                    is_three_kingdoms_game(game_id)
                    and unit_key not in unit_military_groups
                    and unit_key not in exclusive_factions
                ),
                "campaign_cap": merged("campaign_cap", main_values.get("campaign_cap")),
                "recruitment_cost": merged(
                    "recruitment_cost", main_values.get("recruitment_cost")
                ),
                "upkeep_cost": merged("upkeep_cost", main_values.get("upkeep_cost")),
                "model_count": model_count,
                "model_count_locked": model_count_locked,
                "morale": merged("morale", land_values.get("morale"), minimum=0),
                "armour": armour,
                "armour_value": (
                    _clamp_int(unit_edits["armour"], minimum=0)
                    if "armour" in unit_edits
                    else armour["value"]
                ),
                "armour_options": armour["options"],
                "hit_points": effective_hit_points,
                "hit_points_locked": hit_points_locked,
                "total_hp": total_hp,
                "charge_bonus": merged("charge_bonus", land_values.get("charge_bonus")),
                "melee_attack": merged("melee_attack", land_values.get("melee_attack")),
                "melee_defence": merged(
                    "melee_defence", land_values.get("melee_defence")
                ),
                "ammo": merged("ammo", land_values.get("primary_ammo"), minimum=0),
                "reload": merged(
                    "reload",
                    (
                        projectile_values.get("base_reload_time")
                        if is_three_kingdoms_game(game_id)
                        else land_values.get("reload")
                    ),
                    minimum=0,
                ),
                "accuracy": merged("accuracy", land_values.get("accuracy"), minimum=0),
                "missile_resistance": merged(
                    "missile_resistance", land_values.get("damage_mod_missile")
                ),
                "fire_resistance": merged(
                    "fire_resistance", land_values.get("damage_mod_flame")
                ),
                "magic_resistance": merged(
                    "magic_resistance", land_values.get("damage_mod_magic")
                ),
                "physical_resistance": merged(
                    "physical_resistance", land_values.get("damage_mod_physical")
                ),
                "ward_save": merged(
                    "ward_save", land_values.get("damage_mod_all")
                ),
                "missile_block_chance": merged(
                    "missile_block_chance",
                    missile_block_chance,
                    minimum=0,
                ),
                "missile_block_chance_locked": missile_block_chance_locked,
                "movement_speed": (
                    _clamp_float(unit_edits["movement_speed"], minimum=0.01)
                    if "movement_speed" in unit_edits and not movement_speed_locked
                    else movement_speed
                ),
                "movement_speed_locked": movement_speed_locked,
                "body_size": (
                    _normalize_body_size(unit_edits["body_size"])
                    if "body_size" in unit_edits and not body_size_locked
                    else body_size
                ),
                "body_size_locked": body_size_locked,
                "mass": (
                    _clamp_float(unit_edits["mass"], minimum=0)
                    if "mass" in unit_edits and not mass_locked
                    else mass
                ),
                "mass_locked": mass_locked,
                "melee_attack_speed": (
                    merged_float(
                        "melee_attack_speed",
                        melee_values.get("melee_attack_interval"),
                        minimum=0.01,
                        digits=1,
                    )
                    if is_three_kingdoms_game(game_id)
                    else 0
                ),
                "melee_attack_speed_locked": melee_attack_speed_locked,
                "ranged_attack_speed": merged(
                    "ranged_attack_speed",
                    land_values.get("reload_time_reduction_percentage"),
                    minimum=0,
                ),
                "ranged_attack_speed_locked": ranged_attack_speed_locked,
                "melee_damage": merged("melee_damage", melee_values.get("damage")),
                "melee_ap_damage": merged(
                    "melee_ap_damage", melee_values.get("ap_damage")
                ),
                "melee_bonus_v_cavalry": merged(
                    "melee_bonus_v_cavalry", melee_values.get("bonus_v_cavalry")
                ),
                "melee_bonus_v_infantry": merged(
                    "melee_bonus_v_infantry", melee_values.get("bonus_v_infantry")
                ),
                "melee_bonus_v_large": merged(
                    "melee_bonus_v_large", melee_values.get("bonus_v_large")
                ),
                "missile_damage": merged(
                    "missile_damage", projectile_values.get("damage")
                ),
                "missile_ap_damage": merged(
                    "missile_ap_damage", projectile_values.get("ap_damage")
                ),
                "missile_bonus_v_cavalry": merged(
                    "missile_bonus_v_cavalry",
                    projectile_values.get("bonus_v_cavalry"),
                ),
                "missile_bonus_v_infantry": merged(
                    "missile_bonus_v_infantry",
                    projectile_values.get("bonus_v_infantry"),
                ),
                "range": merged("range", projectile_values.get("effective_range")),
                "explosion_damage": merged(
                    "explosion_damage", explosion_values.get("detonation_damage")
                ),
                "explosion_ap_damage": merged(
                    "explosion_ap_damage", explosion_values.get("detonation_damage_ap")
                ),
                "original_values": original_values,
                "edited": unit_edits,
            }
        )
    rows.sort(key=lambda row: (str(row["mod_name"]).casefold(), str(row["key"]).casefold()))
    return {
        "units": rows,
        "stats": {
            "unit_count": len(rows),
            "skipped_missing_land": len(missing_land),
            "edited_unit_count": len(
                {key for key, fields in visible_edits.items() if fields}
            ),
        },
    }


# ---------------------------------------------------------------------------
# Patch generation
# ---------------------------------------------------------------------------


def _write_i32(row: ParsedDbRow, field: str, value: Any) -> ParsedDbRow:
    return _patch_i32(row, field, _clamp_int(value))


def _write_f32(row: ParsedDbRow, field: str, value: Any) -> ParsedDbRow:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    if not math.isfinite(numeric):
        numeric = 0.0
    return patch_db_row_value(row, field, numeric)


def _clamp_float(value: Any, minimum: float | None = None) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    if not math.isfinite(numeric):
        numeric = 0.0
    if minimum is not None:
        numeric = max(numeric, minimum)
    return numeric


def _round_float(
    value: Any,
    *,
    digits: int,
    minimum: float | None = None,
) -> float:
    """Clamp a floating-point DB value and expose it at a fixed precision."""
    return round(_clamp_float(value, minimum), digits)


def _unit_clone_key(
    kind: str,
    unit_key: str,
    source_key: str,
    namespace: str = "3k",
) -> str:
    """Produce a stable ASCII key for an isolated unit DB clone."""
    digest = hashlib.sha1(
        f"{kind}\0{unit_key}\0{source_key}".encode("utf-8")
    ).hexdigest()[:14]
    return f"wyccc_{namespace}_{kind}_{digest}"


def _scaled_component_counts(
    components: Sequence[tuple[str, Any, Mapping[str, Any]]],
    visible_component_keys: set[str],
    wanted: int,
) -> dict[str, int]:
    """Scale visible composition rows while keeping their total exact."""
    selected = [item for item in components if item[0] in visible_component_keys]
    original = sum(
        int(template.row.values.get("num_composed_entities") or 0)
        for _key, template, _composed in selected
    )
    if original <= 0:
        return {}
    raw_counts = [
        int(template.row.values.get("num_composed_entities") or 0) * wanted / original
        for _key, template, _composed in selected
    ]
    counts = [math.floor(value) for value in raw_counts]
    remaining = wanted - sum(counts)
    order = sorted(
        range(len(selected)),
        key=lambda index: (
            -(raw_counts[index] - counts[index]),
            selected[index][0].casefold(),
        ),
    )
    for index in order[:remaining]:
        counts[index] += 1
    return {selected[index][0]: counts[index] for index in range(len(selected))}


def _prepare_three_kingdoms_speed_clone(
    effective: Mapping[str, Mapping[str, Any]],
    unit_key: str,
    land_key: str,
    land: Any,
    added: dict[str, dict[str, tuple[int, ParsedDbRow]]],
) -> dict[str, Any]:
    """Create a private land-unit/template branch for a speed edit.

    Movement speed belongs to battle entities.  Cloning from main_units through
    land_units_templates makes the new battle-entity chain reachable only by
    the edited unit, without leaving an extra composition row on the original
    land-unit record.
    """
    clone_land_key = _unit_clone_key("land", unit_key, land_key)
    clone_land = patch_db_row_value(land.row, "key", clone_land_key)
    template_keys: dict[str, str] = {}
    for template_key, template in effective["land_units_templates_tables"].items():
        if str(template.row.values.get("land_unit") or "") != land_key:
            continue
        composed_key = str(template.row.values.get("composed_entity") or "")
        clone_template_key = f"{clone_land_key}\x1f{composed_key}"
        clone_template = patch_db_row_value(
            template.row,
            "land_unit",
            clone_land_key,
        )
        added["land_units_templates_tables"][clone_template_key] = (
            template.version,
            clone_template,
        )
        template_keys[template_key] = clone_template_key
    return {
        "land_key": clone_land_key,
        "land_row": clone_land,
        "template_keys": template_keys,
    }


def _clone_three_kingdoms_movement_components(
    unit_key: str,
    movement_shape: Mapping[str, Any],
    speed_clone: Mapping[str, Any],
    added: dict[str, dict[str, tuple[int, ParsedDbRow]]],
    value: Any,
) -> None:
    """Point private composition rows to battle entities with a new run speed."""
    speed = _clamp_float(value, minimum=0.01)
    entity_clones: dict[str, str] = {}
    reference_clones: dict[tuple[str, str], str] = {}
    composed_clones: dict[str, str] = {}
    template_keys = speed_clone["template_keys"]
    for template_key, role, composed, reference_table, reference, entity in movement_shape[
        "components"
    ]:
        output_template_key = template_keys.get(template_key)
        if not output_template_key:
            continue
        entity_key = str(entity.row.values.get("key") or "")
        entity_clone_key = entity_clones.get(entity_key)
        if entity_clone_key is None:
            entity_clone_key = _unit_clone_key("battle_entity", unit_key, entity_key)
            entity_clone = patch_db_row_value(entity.row, "key", entity_clone_key)
            entity_clone = _write_f32(entity_clone, "run_speed", speed)
            added["battle_entities_tables"][entity_clone_key] = (
                entity.version,
                entity_clone,
            )
            entity_clones[entity_key] = entity_clone_key

        reference_key = str(reference.row.values.get("key") or "")
        reference_cache_key = (reference_table, reference_key)
        reference_clone_key = reference_clones.get(reference_cache_key)
        if reference_clone_key is None:
            reference_clone_key = _unit_clone_key(
                reference_table.removesuffix("_tables"),
                unit_key,
                reference_key,
            )
            reference_clone = patch_db_row_value(
                reference.row,
                "key",
                reference_clone_key,
            )
            entity_field = _THREE_KINGDOMS_ENTITY_REFERENCE_TABLES[role][1]
            reference_clone = patch_db_row_value(
                reference_clone,
                entity_field,
                entity_clone_key,
            )
            added[reference_table][reference_clone_key] = (
                reference.version,
                reference_clone,
            )
            reference_clones[reference_cache_key] = reference_clone_key

        composed_key = str(composed.row.values.get("key") or "")
        composed_clone_key = composed_clones.get(composed_key)
        if composed_clone_key is None:
            composed_clone_key = _unit_clone_key("composed", unit_key, composed_key)
            composed_clone = patch_db_row_value(composed.row, "key", composed_clone_key)
            composed_clone = patch_db_row_value(
                composed_clone,
                role,
                reference_clone_key,
            )
            added["composed_entities_tables"][composed_clone_key] = (
                composed.version,
                composed_clone,
            )
            composed_clones[composed_key] = composed_clone_key

        template_version, template = added["land_units_templates_tables"][
            output_template_key
        ]
        template = patch_db_row_value(template, "composed_entity", composed_clone_key)
        added["land_units_templates_tables"][output_template_key] = (
            template_version,
            template,
        )


def _build_three_kingdoms_patched_rows(
    effective: Mapping[str, Mapping[str, Any]],
    edits: Mapping[str, Mapping[str, Any]],
) -> tuple[
    dict[str, dict[str, ParsedDbRow]],
    dict[str, dict[str, tuple[int, ParsedDbRow]]],
]:
    """Patch Three Kingdoms rows, cloning shared weapons before changing them."""
    patched: dict[str, dict[str, ParsedDbRow]] = {
        table: {key: candidate.row for key, candidate in rows.items()}
        for table, rows in effective.items()
    }
    added: dict[str, dict[str, tuple[int, ParsedDbRow]]] = {
        table: {}
        for table in (
            "land_units_tables",
            "land_units_templates_tables",
            "composed_entities_tables",
            "battle_entities_tables",
            "mens_tables",
            "mounts_tables",
            "animals_tables",
            "battlefield_engines_tables",
            "unit_shield_types_tables",
            "melee_weapons_tables",
            "missile_weapons_tables",
            "projectiles_tables",
            "projectiles_explosions_tables",
        )
    }
    for unit_key, fields in edits.items():
        main = effective["main_units_tables"].get(unit_key)
        if main is None:
            continue
        main_row = main.row
        main_values = main_row.values
        land_key = str(main_values.get("land_unit") or "")
        land = effective["land_units_tables"].get(land_key)
        if land is None:
            continue
        land_row = land.row
        land_values = land_row.values
        shape = _three_kingdoms_unit_shape(effective, main_values, land_key)
        movement_shape: dict[str, Any] | None = None
        speed_clone: dict[str, Any] | None = None
        if "movement_speed" in fields:
            movement_shape = _three_kingdoms_movement_shape(effective, shape)
            if not movement_shape["movement_speed_locked"]:
                speed_clone = _prepare_three_kingdoms_speed_clone(
                    effective,
                    unit_key,
                    land_key,
                    land,
                    added,
                )
                main_row = patch_db_row_value(
                    main_row,
                    "land_unit",
                    speed_clone["land_key"],
                )
                land_row = speed_clone["land_row"]

        def template_row(template_key: str, template: Any) -> ParsedDbRow:
            if speed_clone is None:
                return patched["land_units_templates_tables"].get(
                    template_key,
                    template.row,
                )
            output_key = speed_clone["template_keys"].get(template_key)
            if output_key is None:
                return template.row
            return added["land_units_templates_tables"][output_key][1]

        def save_template_row(
            template_key: str,
            row: ParsedDbRow,
        ) -> None:
            if speed_clone is None:
                patched["land_units_templates_tables"][template_key] = row
                return
            output_key = speed_clone["template_keys"].get(template_key)
            if output_key is None:
                return
            version, _previous = added["land_units_templates_tables"][output_key]
            added["land_units_templates_tables"][output_key] = (version, row)

        for main_field in ("campaign_cap", "recruitment_cost", "upkeep_cost"):
            if main_field in fields:
                main_row = _write_i32(main_row, main_field, fields[main_field])

        if "model_count" in fields and not shape["model_count_locked"]:
            wanted_count = _clamp_int(fields["model_count"], minimum=1)
            counts = _scaled_component_counts(
                shape["components"],
                shape["visible_component_keys"],
                wanted_count,
            )
            original_visible_count = max(int(shape["model_count"]), 1)
            for template_key, template, _composed in shape["components"]:
                if template_key not in counts:
                    counts[template_key] = _round_half_up_i32(
                        int(template.row.values.get("num_composed_entities") or 0)
                        * wanted_count
                        / original_visible_count,
                    )
            for template_key, wanted in counts.items():
                template = effective["land_units_templates_tables"][template_key]
                save_template_row(
                    template_key,
                    _write_i32(
                        template_row(template_key, template),
                        "num_composed_entities",
                        wanted,
                    ),
                )

        if "hit_points" in fields and not shape["hit_points_locked"]:
            wanted_hp = _clamp_int(fields["hit_points"], minimum=0)
            for template_key, template, _composed in shape["components"]:
                current = template_row(template_key, template)
                count = int(current.values.get("num_composed_entities") or 0)
                save_template_row(
                    template_key,
                    _write_i32(
                        current,
                        "hp_pool",
                        wanted_hp * count,
                    ),
                )

        if "armour" in fields:
            new_key = _armour_key_for_value(
                str(land_values.get("armour") or ""),
                fields["armour"],
                effective["unit_armour_types_tables"],
            )
            land_row = patch_db_row_value(land_row, "armour", new_key)
        for land_field, edit_field in (
            ("morale", "morale"),
            ("charge_bonus", "charge_bonus"),
            ("melee_attack", "melee_attack"),
            ("melee_defence", "melee_defence"),
            ("primary_ammo", "ammo"),
            ("accuracy", "accuracy"),
            ("damage_mod_missile", "missile_resistance"),
            ("damage_mod_flame", "fire_resistance"),
            ("damage_mod_magic", "magic_resistance"),
            ("damage_mod_physical", "physical_resistance"),
            ("damage_mod_all", "ward_save"),
            ("reload_time_reduction_percentage", "ranged_attack_speed"),
        ):
            if edit_field in fields:
                land_row = _write_i32(land_row, land_field, fields[edit_field])

        shield = effective["unit_shield_types_tables"].get(
            str(land_values.get("shield") or "")
        )
        if shield is not None and "missile_block_chance" in fields:
            source_key = str(shield.row.values.get("key") or "")
            clone_key = _unit_clone_key("shield", unit_key, source_key)
            clone = patch_db_row_value(shield.row, "key", clone_key)
            clone = _write_i32(clone, "missile_block_chance", fields["missile_block_chance"])
            added["unit_shield_types_tables"][clone_key] = (shield.version, clone)
            land_row = patch_db_row_value(land_row, "shield", clone_key)

        melee = effective["melee_weapons_tables"].get(
            str(land_values.get("primary_melee_weapon") or "")
        )
        if melee is not None and {
            "melee_attack_speed",
            "melee_damage",
            "melee_ap_damage",
            "melee_bonus_v_cavalry",
            "melee_bonus_v_infantry",
            "melee_bonus_v_large",
        } & set(fields):
            source_key = str(melee.row.values.get("key") or "")
            clone_key = _unit_clone_key("melee", unit_key, source_key)
            clone = patch_db_row_value(melee.row, "key", clone_key)
            if "melee_attack_speed" in fields:
                clone = _write_f32(
                    clone,
                    "melee_attack_interval",
                    _round_float(
                        fields["melee_attack_speed"],
                        digits=1,
                        minimum=0.01,
                    ),
                )
            if "melee_damage" in fields:
                clone = _write_i32(clone, "damage", fields["melee_damage"])
            if "melee_ap_damage" in fields:
                clone = _write_i32(clone, "ap_damage", fields["melee_ap_damage"])
            if "melee_bonus_v_cavalry" in fields:
                clone = _write_i32(
                    clone,
                    "bonus_v_cavalry",
                    fields["melee_bonus_v_cavalry"],
                )
            if "melee_bonus_v_infantry" in fields:
                clone = _write_i32(
                    clone,
                    "bonus_v_infantry",
                    fields["melee_bonus_v_infantry"],
                )
            if "melee_bonus_v_large" in fields:
                clone = _write_i32(
                    clone,
                    "bonus_v_large",
                    fields["melee_bonus_v_large"],
                )
            added["melee_weapons_tables"][clone_key] = (melee.version, clone)
            land_row = patch_db_row_value(land_row, "primary_melee_weapon", clone_key)

        projectile_fields = {
            "missile_damage",
            "missile_ap_damage",
            "range",
            "reload",
            "missile_bonus_v_cavalry",
            "missile_bonus_v_infantry",
            "explosion_damage",
            "explosion_ap_damage",
        }
        missile_weapon = _unit_missile_weapon(effective, land_values)
        if missile_weapon is not None and projectile_fields & set(fields):
            projectile = effective["projectiles_tables"].get(
                str(missile_weapon.row.values.get("default_projectile") or "")
            )
            if projectile is not None:
                projectile_key = str(projectile.row.values.get("key") or "")
                projectile_clone_key = _unit_clone_key("projectile", unit_key, projectile_key)
                projectile_clone = patch_db_row_value(
                    projectile.row,
                    "key",
                    projectile_clone_key,
                )
                for projectile_field, edit_field in (
                    ("damage", "missile_damage"),
                    ("ap_damage", "missile_ap_damage"),
                    ("effective_range", "range"),
                    ("bonus_v_cavalry", "missile_bonus_v_cavalry"),
                    ("bonus_v_infantry", "missile_bonus_v_infantry"),
                ):
                    if edit_field in fields:
                        projectile_clone = _write_i32(
                            projectile_clone,
                            projectile_field,
                            fields[edit_field],
                        )
                if "reload" in fields:
                    projectile_clone = _write_f32(
                        projectile_clone,
                        "base_reload_time",
                        fields["reload"],
                    )
                explosion = effective["projectiles_explosions_tables"].get(
                    str(projectile.row.values.get("explosion_type") or "")
                )
                if explosion is not None and {
                    "explosion_damage",
                    "explosion_ap_damage",
                } & set(fields):
                    explosion_key = str(explosion.row.values.get("key") or "")
                    explosion_clone_key = _unit_clone_key(
                        "explosion",
                        unit_key,
                        explosion_key,
                    )
                    explosion_clone = patch_db_row_value(
                        explosion.row,
                        "key",
                        explosion_clone_key,
                    )
                    if "explosion_damage" in fields:
                        explosion_clone = _write_f32(
                            explosion_clone,
                            "detonation_damage",
                            fields["explosion_damage"],
                        )
                    if "explosion_ap_damage" in fields:
                        explosion_clone = _write_f32(
                            explosion_clone,
                            "detonation_damage_ap",
                            fields["explosion_ap_damage"],
                        )
                    added["projectiles_explosions_tables"][explosion_clone_key] = (
                        explosion.version,
                        explosion_clone,
                    )
                    projectile_clone = patch_db_row_value(
                        projectile_clone,
                        "explosion_type",
                        explosion_clone_key,
                    )
                added["projectiles_tables"][projectile_clone_key] = (
                    projectile.version,
                    projectile_clone,
                )
                missile_key = str(missile_weapon.row.values.get("key") or "")
                missile_clone_key = _unit_clone_key("missile", unit_key, missile_key)
                missile_clone = patch_db_row_value(missile_weapon.row, "key", missile_clone_key)
                missile_clone = patch_db_row_value(
                    missile_clone,
                    "default_projectile",
                    projectile_clone_key,
                )
                added["missile_weapons_tables"][missile_clone_key] = (
                    missile_weapon.version,
                    missile_clone,
                )
                land_row = patch_db_row_value(
                    land_row,
                    "primary_missile_weapon",
                    missile_clone_key,
                )

        if speed_clone is not None:
            _clone_three_kingdoms_movement_components(
                unit_key,
                movement_shape or {},
                speed_clone,
                added,
                fields["movement_speed"],
            )
            added["land_units_tables"][speed_clone["land_key"]] = (
                land.version,
                land_row,
            )
        else:
            patched["land_units_tables"][land_key] = land_row
        patched["main_units_tables"][unit_key] = main_row
    return patched, added


def _build_patched_rows(
    effective: Mapping[str, Mapping[str, ParsedDbRow]],
    edits: Mapping[str, Mapping[str, Any]],
) -> tuple[
    dict[str, dict[str, ParsedDbRow]],
    dict[str, dict[str, tuple[int, ParsedDbRow]]],
]:
    """Apply per-unit edits to the effective rows of every writable table."""
    patched: dict[str, dict[str, ParsedDbRow]] = {
        table: {key: candidate.row for key, candidate in rows.items()}
        for table, rows in effective.items()
    }
    added: dict[str, dict[str, tuple[int, ParsedDbRow]]] = {
        table_name: {}
        for table_name in (
            "mounts_tables",
            "battlefield_engines_tables",
            "land_unit_articulated_vehicles_tables",
            "battle_entities_tables",
        )
    }
    for unit_key, fields in edits.items():
        main = effective["main_units_tables"].get(unit_key)
        if main is None:
            continue
        main_row = main.row
        main_values = main_row.values
        land = effective["land_units_tables"].get(
            str(main_values.get("land_unit") or "")
        )
        if land is None:
            continue
        land_row = land.row
        land_values = land_row.values

        if "campaign_cap" in fields:
            main_row = _write_i32(main_row, "campaign_cap", fields["campaign_cap"])
        if "recruitment_cost" in fields:
            main_row = _write_i32(main_row, "recruitment_cost", fields["recruitment_cost"])
        if "upkeep_cost" in fields:
            main_row = _write_i32(main_row, "upkeep_cost", fields["upkeep_cost"])

        if "model_count" in fields:
            wanted = _clamp_int(fields["model_count"], minimum=1)
            _count_field = _base_visible_count(main_values, land_values)[1]
            original_visible, _ = _base_visible_count(main_values, land_values)
            original_men = int(main_values.get("num_men") or 0)
            if _count_field == "num_engines":
                land_row = _write_i32(land_row, "num_engines", wanted)
                if original_visible > 0 and original_men > 0:
                    main_row = _write_i32(
                        main_row,
                        "num_men",
                        max(
                            wanted,
                            _round_half_up_i32(
                                original_men * wanted / original_visible
                            ),
                        ),
                    )
            elif _count_field == "num_mounts":
                land_row = _write_i32(land_row, "num_mounts", wanted)
                if original_visible > 0 and original_men > 0:
                    main_row = _write_i32(
                        main_row,
                        "num_men",
                        max(
                            wanted,
                            _round_half_up_i32(
                                original_men * wanted / original_visible
                            ),
                        ),
                    )
            else:
                main_row = _write_i32(main_row, "num_men", wanted)

        if "armour" in fields:
            new_key = _armour_key_for_value(
                str(land_values.get("armour") or ""),
                fields["armour"],
                effective["unit_armour_types_tables"],
            )
            land_row = patch_db_row_value(land_row, "armour", new_key)

        for land_field, edit_field in (
            ("morale", "morale"),
            ("charge_bonus", "charge_bonus"),
            ("melee_attack", "melee_attack"),
            ("melee_defence", "melee_defence"),
            ("bonus_hit_points", "hit_points"),
            ("primary_ammo", "ammo"),
            ("reload", "reload"),
            ("accuracy", "accuracy"),
            ("damage_mod_missile", "missile_resistance"),
            ("damage_mod_flame", "fire_resistance"),
            ("damage_mod_magic", "magic_resistance"),
            ("damage_mod_physical", "physical_resistance"),
            ("damage_mod_all", "ward_save"),
        ):
            if edit_field in fields:
                land_row = _write_i32(land_row, land_field, fields[edit_field])

        requested_physical_fields = {
            field for field in ("body_size", "mass") if field in fields
        }
        if requested_physical_fields:
            physical_shape = _warhammer_entity_shape(effective, land_values)
            writable_physical_fields = {
                field
                for field in requested_physical_fields
                if not bool(physical_shape[f"{field}_locked"])
            }
            if writable_physical_fields:
                entity_clones: dict[str, str] = {}
                reference_clones: dict[tuple[str, str], str] = {}
                for component in physical_shape["components"]:
                    entity = component["entity"]
                    source_entity_key = str(entity.row.values.get("key") or "")
                    clone_key = entity_clones.get(source_entity_key)
                    if clone_key is None:
                        clone_key = _unit_clone_key(
                            "battle_entity",
                            unit_key,
                            source_entity_key,
                            namespace="wh3",
                        )
                        clone = patch_db_row_value(entity.row, "key", clone_key)
                        if "body_size" in writable_physical_fields:
                            clone = patch_db_row_value(
                                clone,
                                "size",
                                _normalize_body_size(fields["body_size"]),
                            )
                        if "mass" in writable_physical_fields:
                            clone = _write_f32(
                                clone,
                                "mass",
                                _clamp_float(fields["mass"], minimum=0),
                            )
                        added["battle_entities_tables"][clone_key] = (
                            entity.version,
                            clone,
                        )
                        entity_clones[source_entity_key] = clone_key

                    reference = component["reference"]
                    reference_table = component["reference_table"]
                    if reference is None or reference_table is None:
                        land_row = patch_db_row_value(
                            land_row,
                            component["land_field"],
                            clone_key,
                        )
                        continue
                    source_reference_key = str(
                        reference.row.values.get("key") or ""
                    )
                    reference_cache_key = (reference_table, source_reference_key)
                    reference_clone_key = reference_clones.get(reference_cache_key)
                    if reference_clone_key is None:
                        reference_clone_key = _unit_clone_key(
                            reference_table.removesuffix("_tables"),
                            unit_key,
                            source_reference_key,
                            namespace="wh3",
                        )
                        reference_clone = patch_db_row_value(
                            reference.row,
                            "key",
                            reference_clone_key,
                        )
                        reference_clone = patch_db_row_value(
                            reference_clone,
                            component["entity_field"],
                            clone_key,
                        )
                        added[reference_table][reference_clone_key] = (
                            reference.version,
                            reference_clone,
                        )
                        reference_clones[reference_cache_key] = reference_clone_key
                    land_row = patch_db_row_value(
                        land_row,
                        component["land_field"],
                        reference_clone_key,
                    )
        patched["land_units_tables"][land.row.values["key"]] = land_row
        patched["main_units_tables"][unit_key] = main_row

        melee = effective["melee_weapons_tables"].get(
            str(land_values.get("primary_melee_weapon") or "")
        )
        if melee is not None:
            melee_row = melee.row
            if "melee_damage" in fields:
                melee_row = _write_i32(melee_row, "damage", fields["melee_damage"])
            if "melee_ap_damage" in fields:
                melee_row = _write_i32(melee_row, "ap_damage", fields["melee_ap_damage"])
            if "melee_bonus_v_infantry" in fields:
                melee_row = _write_i32(
                    melee_row,
                    "bonus_v_infantry",
                    fields["melee_bonus_v_infantry"],
                )
            if "melee_bonus_v_large" in fields:
                melee_row = _write_i32(
                    melee_row,
                    "bonus_v_large",
                    fields["melee_bonus_v_large"],
                )
            patched["melee_weapons_tables"][melee.row.values["key"]] = melee_row

        missile_weapon = _unit_missile_weapon(effective, land_values)
        projectile = None
        if missile_weapon is not None:
            projectile = effective["projectiles_tables"].get(
                str(missile_weapon.row.values.get("default_projectile") or "")
            )
        if projectile is not None:
            projectile_row = projectile.row
            if "missile_damage" in fields:
                projectile_row = _write_i32(
                    projectile_row, "damage", fields["missile_damage"]
                )
            if "missile_ap_damage" in fields:
                projectile_row = _write_i32(
                    projectile_row, "ap_damage", fields["missile_ap_damage"]
                )
            if "range" in fields:
                projectile_row = _write_i32(
                    projectile_row, "effective_range", fields["range"]
                )
            patched["projectiles_tables"][projectile.row.values["key"]] = projectile_row
            explosion = effective["projectiles_explosions_tables"].get(
                str(projectile.row.values.get("explosion_type") or "")
            )
            if explosion is not None:
                explosion_row = explosion.row
                if "explosion_damage" in fields:
                    explosion_row = _write_f32(
                        explosion_row,
                        "detonation_damage",
                        fields["explosion_damage"],
                    )
                if "explosion_ap_damage" in fields:
                    explosion_row = _write_f32(
                        explosion_row,
                        "detonation_damage_ap",
                        fields["explosion_ap_damage"],
                    )
                patched["projectiles_explosions_tables"][
                    explosion.row.values["key"]
                ] = explosion_row
    return patched, added


def _serialize_table_entries(
    table_name: str,
    rows: Mapping[str, tuple[int, ParsedDbRow]],
    candidates: Mapping[str, Any],
) -> list[GameDataEntry]:
    """Serialize an overlay table with a priority-marked internal file name."""
    grouped: dict[int, list[tuple[str, ParsedDbRow]]] = {}
    for key, (version, row) in rows.items():
        grouped.setdefault(version, []).append((key, row))
    entries: list[GameDataEntry] = []
    for version in sorted(grouped):
        ordered = [row for _key, row in sorted(grouped[version], key=lambda item: item[0].casefold())]
        payload = b"".join(
            (
                b"\xfc\xfd\xfe\xff",
                struct.pack("<i", version),
                b"\1",
                struct.pack("<i", len(ordered)),
                *(row.raw for row in ordered),
            )
        )
        entries.append(
            GameDataEntry(
                f"db\\{table_name}\\"
                + _generated_internal_name(
                    candidates,
                    version,
                    label="wyccc_unit_data",
                ),
                payload,
            )
        )
    return entries


def _changed_table_rows(
    effective: Mapping[str, Mapping[str, Any]],
    patched: Mapping[str, Mapping[str, ParsedDbRow]],
    table_name: str,
    added_rows: Mapping[str, tuple[int, ParsedDbRow]] | None = None,
) -> dict[str, tuple[int, ParsedDbRow]] | None:
    """Return the full overlay rows for a table when any row changed."""
    candidates = effective[table_name]
    additions = dict(added_rows or {})
    if not additions and not any(
        patched[table_name].get(key).raw != candidate.row.raw
        for key, candidate in candidates.items()
    ):
        return None
    rows = {
        key: (candidate.version, patched[table_name].get(key, candidate.row))
        for key, candidate in candidates.items()
    }
    rows.update(additions)
    return rows


def _permission_replacement_entries(
    sources: Sequence[Any],
    table_name: str,
    disabled_units: set[str],
    game_id: str | None = None,
) -> list[GameDataEntry]:
    """Clone only affected source DB files, removing disabled-unit rows.

    A same-name DB entry replaces its source file.  Rebuilding that entry must
    therefore retain its GUID/version prefix and its own remaining rows; a
    table-wide merged payload is neither a byte-compatible replacement nor a
    lightweight patch.
    """
    from .game_data import _entry_table_name

    # A generated pack can contain one entry per internal path.  The existing
    # source resolver treats the earliest source/entry as the effective one
    # when those paths are identical, so mirror that choice here.
    selected: dict[str, tuple[str, int, int, Any, Any]] = {}
    for source_rank, source in enumerate(sources):
        for entry_rank, entry in enumerate(source.entries):
            resolved = _entry_table_name(entry.name)
            if not resolved or resolved[0] != table_name:
                continue
            internal_name = resolved[1]
            key = internal_name.casefold()
            if key in selected:
                continue
            try:
                parsed = parse_db_table(table_name, entry.payload, game_id)
            except ValueError as exc:
                raise ValueError(
                    f"读取 {source.name} 中的 {entry.name} 失败：{exc}"
                ) from exc
            selected[key] = (internal_name, source_rank, entry_rank, entry, parsed)

    replacements: list[GameDataEntry] = []
    ordered = sorted(
        selected.values(),
        key=cmp_to_key(
            lambda first, second: _compare_internal_names(first[0], second[0])
        ),
    )
    for _internal_name, _source_rank, _entry_rank, entry, parsed in ordered:
        kept_rows = [
            row
            for row in parsed.rows
            if _permission_unit_key(table_name, row.values, game_id) not in disabled_units
        ]
        if len(kept_rows) == len(parsed.rows):
            continue

        row_bytes = sum(len(row.raw) for row in parsed.rows)
        count_offset = len(entry.payload) - row_bytes - 4
        if count_offset < 1:
            raise ValueError(f"{entry.name} 的权限表行计数位置无效")
        payload = b"".join(
            (
                entry.payload[:count_offset],
                struct.pack("<i", len(kept_rows)),
                *(row.raw for row in kept_rows),
            )
        )
        replacements.append(GameDataEntry(entry.name, payload))
    return replacements


def build_unit_data_entries(
    sources: Sequence[Any],
    settings: Mapping[str, Any],
    edits: Mapping[str, Mapping[str, Any]],
    game_id: str | None = None,
) -> GameDataBuildResult:
    """Build the unit-data patch entries from effective rows plus edits."""
    normalized_edits = _edits_for_game(edits, game_id)
    if not normalized_edits:
        return GameDataBuildResult((), {"edited_unit_count": 0, "entry_count": 0})

    unit_tables = set(_unit_join_tables(game_id))
    if not is_three_kingdoms_game(game_id):
        unit_tables.add("battle_entities_tables")
    effective = _collect_effective_rows(
        sources,
        unit_tables,
        game_id=game_id,
        skip_main_unit_compatibility_placeholders=True,
    )
    if is_three_kingdoms_game(game_id):
        patched, added_rows = _build_three_kingdoms_patched_rows(
            effective,
            normalized_edits,
        )
        output_tables = (
            "main_units_tables",
            "land_units_tables",
            "land_units_templates_tables",
            "composed_entities_tables",
            "battle_entities_tables",
            "mens_tables",
            "mounts_tables",
            "animals_tables",
            "battlefield_engines_tables",
            "unit_shield_types_tables",
            "melee_weapons_tables",
            "missile_weapons_tables",
            "projectiles_tables",
            "projectiles_explosions_tables",
        )
    else:
        patched, added_rows = _build_patched_rows(effective, normalized_edits)
        output_tables = (
            "main_units_tables",
            "land_units_tables",
            "mounts_tables",
            "battlefield_engines_tables",
            "land_unit_articulated_vehicles_tables",
            "battle_entities_tables",
            "melee_weapons_tables",
            "projectiles_tables",
            "projectiles_explosions_tables",
        )
    entries: list[GameDataEntry] = []

    for table_name in output_tables:
        full_rows = _changed_table_rows(
            effective,
            patched,
            table_name,
            added_rows.get(table_name),
        )
        if full_rows is not None:
            entries.extend(
                _serialize_table_entries(
                    table_name,
                    full_rows,
                    effective[table_name],
                )
            )

    # Recruitment gating: clone only source permission files that contain a
    # disabled unit, preserving each file's GUID/version prefix and every
    # unrelated row.  ``building_units_allowed.enabled`` is not a reliable
    # disable switch, so the row itself must be removed.
    disabled_units = {
        unit_key
        for unit_key, fields in normalized_edits.items()
        if fields.get("enabled") is not None and not _coerce_bool(fields["enabled"])
    }
    if disabled_units:
        for table_name in _permission_tables_for_game(game_id):
            entries.extend(
                _permission_replacement_entries(
                    sources,
                    table_name,
                    disabled_units,
                    game_id,
                )
            )

    return GameDataBuildResult(
        tuple(entries),
        {
            "edited_unit_count": len(normalized_edits),
            "disabled_unit_count": len(disabled_units),
            "entry_count": len(entries),
        },
    )
