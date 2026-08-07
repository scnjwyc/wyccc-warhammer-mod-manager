from __future__ import annotations

import math
import re
import struct
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from .game_data import (
    GameDataBuildResult,
    GameDataEntry,
    ParsedDbRow,
    _clamped_i32,
    _collect_effective_rows,
    _compare_internal_names,
    _generated_internal_name,
    _leading_priority_markers,
    _patch_i32,
    _resolve_unit_scale_policy,
    _round_half_up_i32,
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
        "armour",
        "hit_points",
        "charge_bonus",
        "melee_attack",
        "melee_defence",
        "ammo",
        "reload",
        "accuracy",
        "fire_resistance",
        "magic_resistance",
        "physical_resistance",
        "ward_save",
        "melee_damage",
        "melee_ap_damage",
        "missile_damage",
        "missile_ap_damage",
        "range",
        "explosion_damage",
        "explosion_ap_damage",
    }
)

_ARMOUR_SUFFIX_RE = re.compile(r"^(?P<prefix>.*)_(?P<value>\d+)$")


@dataclass(frozen=True)
class _PermissionRow:
    row: ParsedDbRow
    internal_name: str
    source_rank: int
    entry_rank: int
    row_rank: int
    key: tuple[str, ...]


def _sanitize_edits(raw_edits: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Normalize the persisted/UI edit map into ``{unit_key: {field: value}}``."""
    if not isinstance(raw_edits, Mapping):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for unit_key, fields in raw_edits.items():
        if not isinstance(fields, Mapping):
            continue
        cleaned = {
            str(field): value
            for field, value in fields.items()
            if field in EDITABLE_FIELDS and value is not None and value != ""
        }
        if cleaned:
            normalized[str(unit_key)] = cleaned
    return normalized


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
) -> tuple[dict[str, str], dict[str, str]]:
    try:
        path = Path(path_text)
        if not path.is_file():
            return {}, {}
        from .start_options import read_pack_entries

        merged_units: dict[str, str] = {}
        merged_cultures: dict[str, str] = {}
        for entry in read_pack_entries(path, "text\\"):
            if entry.name.casefold().endswith(".loc"):
                units, cultures = _parse_loc_payload(entry.payload)
                merged_units.update(units)
                merged_cultures.update(cultures)
        return merged_units, merged_cultures
    except (OSError, ValueError):
        return {}, {}


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
    files override vanilla, and later mods in the given order win."""
    data_root = Path(data_path).resolve(strict=False)
    unit_names: dict[str, str] = {}
    culture_names: dict[str, str] = {}
    for pack_name in _language_loc_packs(language):
        path = (data_root / pack_name).resolve(strict=False)
        units, cultures = _load_loc_file(str(path), _file_mtime_ns(path))
        unit_names.update(units)
        culture_names.update(cultures)
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
        for path, (units, cultures) in loaded:
            unit_names.update(units)
            culture_names.update(cultures)
    else:
        for path in resolved_mods:
            units, cultures = _load_loc_file(str(path), _file_mtime_ns(path))
            unit_names.update(units)
            culture_names.update(cultures)
    return unit_names, culture_names


# ---------------------------------------------------------------------------
# Recruitment permission rows
# ---------------------------------------------------------------------------

_PERMISSION_TABLES = (
    "units_to_groupings_military_permissions_tables",
    "units_to_exclusive_faction_permissions_tables",
)

_PERMISSION_KEY_FIELDS = {
    "units_to_groupings_military_permissions_tables": ("unit", "military_group"),
    "units_to_exclusive_faction_permissions_tables": ("unit", "faction"),
}


def _permission_row_key(table_name: str, values: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        "" if values.get(field) is None else str(values.get(field) or "")
        for field in _PERMISSION_KEY_FIELDS[table_name]
    )


def _collect_permission_rows(
    sources: Sequence[Any],
    table_name: str,
) -> dict[tuple[str, ...], _PermissionRow]:
    """Collect all permission rows, deduplicating identical key rows by load
    order (first source wins, matching the game-data overlay priority)."""
    from .game_data import _entry_table_name

    effective: dict[tuple[str, ...], _PermissionRow] = {}
    for source_rank, source in enumerate(sources):
        for entry_rank, entry in enumerate(source.entries):
            resolved = _entry_table_name(entry.name)
            if not resolved or resolved[0] != table_name:
                continue
            parsed = parse_db_table(table_name, entry.payload)
            for row_rank, row in enumerate(parsed.rows):
                values = row.values
                unit_key = str(values.get("unit") or "")
                if not unit_key:
                    raise ValueError(
                        f"{source.name} 中的 {entry.name} 存在空 unit 主键"
                    )
                key = _permission_row_key(table_name, values)
                candidate = _PermissionRow(
                    row,
                    resolved[1],
                    source_rank,
                    entry_rank,
                    row_rank,
                    key,
                )
                existing = effective.get(key)
                if existing is None or _has_permission_priority(candidate, existing):
                    effective[key] = candidate
    return effective


def _has_permission_priority(candidate: _PermissionRow, existing: _PermissionRow) -> bool:
    if candidate.source_rank != existing.source_rank:
        return candidate.source_rank < existing.source_rank
    file_order = _compare_internal_names(
        candidate.internal_name, existing.internal_name
    )
    if file_order:
        return file_order < 0
    return (candidate.entry_rank, candidate.row_rank) < (
        existing.entry_rank,
        existing.row_rank,
    )


def _generated_permission_name(
    rows: Sequence[_PermissionRow],
    table_name: str,
) -> str:
    priority_markers = (
        max(
            (_leading_priority_markers(row.internal_name) for row in rows),
            default=0,
        )
        + 1
    )
    internal_name = f"{'!' * priority_markers}wyccc_unit_data_{table_name}"
    blockers = sorted(
        {row.internal_name for row in rows},
        key=str.casefold,
    )
    if any(_compare_internal_names(internal_name, blocker) >= 0 for blocker in blockers):
        raise ValueError(
            "无法生成优先级高于启用 MOD 的招募权限表："
            + ", ".join(sorted(blockers)[:3])
        )
    return internal_name


# ---------------------------------------------------------------------------
# Unit snapshot
# ---------------------------------------------------------------------------

UNIT_TABLES = (
    "main_units_tables",
    "land_units_tables",
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

# Tables joined only for the editor table (race resolution), not for patching.
RACE_TABLES = ("factions_tables", "cultures_subcultures_tables")


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


def _effective_model_count(
    main_values: Mapping[str, Any],
    land_values: Mapping[str, Any],
    policy: Any,
) -> int:
    base_count, _field = _base_visible_count(main_values, land_values)
    if (
        policy.kind == "character"
        or math.isclose(policy.size_multiplier, 1.0, rel_tol=0.0, abs_tol=1e-9)
    ):
        return base_count
    return _round_half_up_i32(base_count * policy.size_multiplier, minimum=1)


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


def _unit_edits_for(edits: Mapping[str, Mapping[str, Any]], unit_key: str) -> dict[str, Any]:
    entry = edits.get(unit_key)
    return dict(entry) if isinstance(entry, Mapping) else {}


def build_unit_table_snapshot(
    sources: Sequence[Any],
    settings: Mapping[str, Any],
    edits: Mapping[str, Mapping[str, Any]],
    name_map: Mapping[str, str] | None = None,
    culture_map: Mapping[str, str] | None = None,
    source_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Project every effective unit into the editor table rows."""
    multiplier = _clamp_int(settings.get("unit_model_multiplier", 1), minimum=1)
    single_entity_health_mode = (
        str(settings.get("single_entity_unit_mode") or "scale").strip().casefold()
        == "health"
    )
    artillery_mode = str(settings.get("artillery_unit_mode") or "full").strip().casefold()
    war_machine_mode = (
        str(settings.get("war_machine_unit_mode") or "full").strip().casefold()
    )
    scale_lord_hero_health = _coerce_bool(settings.get("scale_lord_hero_health"))

    all_candidates: dict[str, dict[str, list[Any]]] = {}
    effective = _collect_effective_rows(
        sources,
        set(UNIT_JOIN_TABLES) | set(RACE_TABLES),
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
        sources, "units_to_exclusive_faction_permissions_tables"
    ).values():
        exclusive_factions.setdefault(permission.key[0], permission.key[1])
    unit_military_groups: dict[str, set[str]] = {}
    for permission in _collect_permission_rows(
        sources, "units_to_groupings_military_permissions_tables"
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

        # Model HP is owned by the unit itself (land_units.bonus_hit_points).
        # battle_entities.hit_points is shared across many units and is
        # deliberately excluded from both the value and the edit path.
        bonus_hit_points = int(land_values.get("bonus_hit_points") or 0)

        policy = _resolve_unit_scale_policy(
            main_values,
            land_values,
            multiplier,
            single_entity_health_mode,
            artillery_mode,
            war_machine_mode,
            scale_lord_hero_health,
        )
        model_count = _effective_model_count(main_values, land_values, policy)
        model_count_locked = (
            policy.kind == "character"
            or (
                policy.size_multiplier == 1.0
                and _base_visible_count(main_values, land_values)[0] == 1
            )
        )

        melee = effective["melee_weapons_tables"].get(
            str(land_values.get("primary_melee_weapon") or "")
        )
        melee_values = melee.row.values if melee is not None else {}
        missile_weapon = effective["missile_weapons_tables"].get(
            str(land_values.get("primary_missile_weapon") or "")
        )
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
        unit_edits = _unit_edits_for(edits, unit_key)
        original_model_count = model_count

        original_values = {
            "enabled": True,
            "campaign_cap": _clamp_int(main_values.get("campaign_cap")),
            "recruitment_cost": _clamp_int(main_values.get("recruitment_cost")),
            "upkeep_cost": _clamp_int(main_values.get("upkeep_cost")),
            "model_count": original_model_count,
            "armour": armour["value"],
            "hit_points": _clamp_int(bonus_hit_points, minimum=0),
            "charge_bonus": _clamp_int(land_values.get("charge_bonus")),
            "melee_attack": _clamp_int(land_values.get("melee_attack")),
            "melee_defence": _clamp_int(land_values.get("melee_defence")),
            "ammo": _clamp_int(land_values.get("primary_ammo"), minimum=0),
            "fire_resistance": _clamp_int(land_values.get("damage_mod_flame")),
            "magic_resistance": _clamp_int(land_values.get("damage_mod_magic")),
            "physical_resistance": _clamp_int(land_values.get("damage_mod_physical")),
            "ward_save": _clamp_int(land_values.get("damage_mod_all")),
            "melee_damage": _clamp_int(melee_values.get("damage")),
            "melee_ap_damage": _clamp_int(melee_values.get("ap_damage")),
            "missile_damage": _clamp_int(projectile_values.get("damage")),
            "missile_ap_damage": _clamp_int(projectile_values.get("ap_damage")),
            "explosion_damage": _clamp_int(
                explosion_values.get("detonation_damage")
            ),
            "explosion_ap_damage": _clamp_int(
                explosion_values.get("detonation_damage_ap")
            ),
            "range": _clamp_int(projectile_values.get("effective_range")),
            "reload": _clamp_int(land_values.get("reload"), minimum=0),
            "accuracy": _clamp_int(land_values.get("accuracy"), minimum=0),
        }

        def merged(field: str, current: Any, minimum: int | None = None) -> int:
            if field in unit_edits:
                return _clamp_int(unit_edits[field], minimum)
            return _clamp_int(current, minimum)

        if "model_count" in unit_edits and not model_count_locked:
            wanted = _clamp_int(unit_edits["model_count"], minimum=1)
            model_count = wanted

        edited_enabled = unit_edits.get("enabled")
        enabled = (
            _coerce_bool(edited_enabled)
            if edited_enabled is not None
            else True
        )

        effective_hit_points = merged("hit_points", bonus_hit_points, minimum=0)
        land_name = str(land_values.get("key") or "")
        chain_candidates = all_candidates.get("main_units_tables", {}).get(
            unit_key, ()
        )
        chain_ranks = sorted(
            {entry.source_rank for entry in chain_candidates},
        )
        # Lowest-priority source is the original definition; the chain is
        # presented original -> latest modifier.
        source_chain = [
            resolved_source_names[rank]
            if rank < len(resolved_source_names)
            else ""
            for rank in reversed(chain_ranks)
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
                "campaign_cap": merged("campaign_cap", main_values.get("campaign_cap")),
                "recruitment_cost": merged(
                    "recruitment_cost", main_values.get("recruitment_cost")
                ),
                "upkeep_cost": merged("upkeep_cost", main_values.get("upkeep_cost")),
                "model_count": model_count,
                "model_count_locked": model_count_locked,
                "armour": armour,
                "armour_value": (
                    _clamp_int(unit_edits["armour"], minimum=0)
                    if "armour" in unit_edits
                    else armour["value"]
                ),
                "armour_options": armour["options"],
                "hit_points": effective_hit_points,
                "total_hp": _clamped_i32(effective_hit_points * model_count),
                "charge_bonus": merged("charge_bonus", land_values.get("charge_bonus")),
                "melee_attack": merged("melee_attack", land_values.get("melee_attack")),
                "melee_defence": merged(
                    "melee_defence", land_values.get("melee_defence")
                ),
                "ammo": merged("ammo", land_values.get("primary_ammo"), minimum=0),
                "reload": merged("reload", land_values.get("reload"), minimum=0),
                "accuracy": merged("accuracy", land_values.get("accuracy"), minimum=0),
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
                "melee_damage": merged("melee_damage", melee_values.get("damage")),
                "melee_ap_damage": merged(
                    "melee_ap_damage", melee_values.get("ap_damage")
                ),
                "missile_damage": merged(
                    "missile_damage", projectile_values.get("damage")
                ),
                "missile_ap_damage": merged(
                    "missile_ap_damage", projectile_values.get("ap_damage")
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
                {key for key, fields in edits.items() if fields}
            ),
        },
    }


# ---------------------------------------------------------------------------
# Patch generation
# ---------------------------------------------------------------------------


def _write_i32(row: ParsedDbRow, field: str, value: Any) -> ParsedDbRow:
    return _patch_i32(row, field, _clamp_int(value))


def _build_patched_rows(
    effective: Mapping[str, Mapping[str, ParsedDbRow]],
    edits: Mapping[str, Mapping[str, Any]],
    settings: Mapping[str, Any],
) -> dict[str, dict[str, ParsedDbRow]]:
    """Apply per-unit edits to the effective rows of every writable table."""
    patched: dict[str, dict[str, ParsedDbRow]] = {
        table: {key: candidate.row for key, candidate in rows.items()}
        for table, rows in effective.items()
    }
    for unit_key, fields in edits.items():
        multiplier = _clamp_int(settings.get("unit_model_multiplier", 1), minimum=1)
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

        policy = _resolve_unit_scale_policy(
            main_values,
            land_values,
            multiplier,
            (
                str(settings.get("single_entity_unit_mode") or "scale")
                .strip()
                .casefold()
                == "health"
            ),
            str(settings.get("artillery_unit_mode") or "full").strip().casefold(),
            str(settings.get("war_machine_unit_mode") or "full").strip().casefold(),
            _coerce_bool(settings.get("scale_lord_hero_health")),
        )
        model_count_locked = (
            policy.kind == "character"
            or (
                policy.size_multiplier == 1.0
                and _base_visible_count(main_values, land_values)[0] == 1
            )
        )

        if "campaign_cap" in fields:
            main_row = _write_i32(main_row, "campaign_cap", fields["campaign_cap"])
        if "recruitment_cost" in fields:
            main_row = _write_i32(main_row, "recruitment_cost", fields["recruitment_cost"])
        if "upkeep_cost" in fields:
            main_row = _write_i32(main_row, "upkeep_cost", fields["upkeep_cost"])

        if "model_count" in fields and not model_count_locked:
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
            ("charge_bonus", "charge_bonus"),
            ("melee_attack", "melee_attack"),
            ("melee_defence", "melee_defence"),
            ("bonus_hit_points", "hit_points"),
            ("primary_ammo", "ammo"),
            ("reload", "reload"),
            ("accuracy", "accuracy"),
            ("damage_mod_flame", "fire_resistance"),
            ("damage_mod_magic", "magic_resistance"),
            ("damage_mod_physical", "physical_resistance"),
            ("damage_mod_all", "ward_save"),
        ):
            if edit_field in fields:
                land_row = _write_i32(land_row, land_field, fields[edit_field])
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
            patched["melee_weapons_tables"][melee.row.values["key"]] = melee_row

        missile_weapon = effective["missile_weapons_tables"].get(
            str(land_values.get("primary_missile_weapon") or "")
        )
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
                    explosion_row = _write_i32(
                        explosion_row,
                        "detonation_damage",
                        fields["explosion_damage"],
                    )
                if "explosion_ap_damage" in fields:
                    explosion_row = _write_i32(
                        explosion_row,
                        "detonation_damage_ap",
                        fields["explosion_ap_damage"],
                    )
                patched["projectiles_explosions_tables"][
                    explosion.row.values["key"]
                ] = explosion_row
    return patched


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
) -> dict[str, tuple[int, ParsedDbRow]] | None:
    """Return the full overlay rows for a table when any row changed."""
    candidates = effective[table_name]
    if not any(
        patched[table_name].get(key).raw != candidate.row.raw
        for key, candidate in candidates.items()
    ):
        return None
    return {
        key: (candidate.version, patched[table_name].get(key, candidate.row))
        for key, candidate in candidates.items()
    }


def _serialize_versionless_table(
    table_name: str,
    rows: Sequence[_PermissionRow],
) -> GameDataEntry:
    payload = b"".join(
        (
            b"\1",
            struct.pack("<i", len(rows)),
            *(row.row.raw for row in rows),
        )
    )
    return GameDataEntry(
        f"db\\{table_name}\\" + _generated_permission_name(rows, table_name),
        payload,
    )


def build_unit_data_entries(
    sources: Sequence[Any],
    settings: Mapping[str, Any],
    edits: Mapping[str, Mapping[str, Any]],
) -> GameDataBuildResult:
    """Build the unit-data patch entries from effective rows plus edits."""
    normalized_edits = _sanitize_edits(edits)
    if not normalized_edits:
        return GameDataBuildResult((), {"edited_unit_count": 0, "entry_count": 0})

    effective = _collect_effective_rows(
        sources,
        set(UNIT_JOIN_TABLES),
        skip_main_unit_compatibility_placeholders=True,
    )
    patched = _build_patched_rows(effective, normalized_edits, settings)
    entries: list[GameDataEntry] = []

    for table_name in (
        "main_units_tables",
        "land_units_tables",
        "melee_weapons_tables",
        "projectiles_tables",
        "projectiles_explosions_tables",
    ):
        full_rows = _changed_table_rows(effective, patched, table_name)
        if full_rows is not None:
            entries.extend(
                _serialize_table_entries(
                    table_name,
                    full_rows,
                    effective[table_name],
                )
            )

    # Recruitment gating: emit the full effective permission rows minus the
    # units the player disabled.  The vanilla tables are versionless, so these
    # overlays are serialized without a version header as well.
    disabled_units = {
        unit_key
        for unit_key, fields in normalized_edits.items()
        if fields.get("enabled") is not None and not _coerce_bool(fields["enabled"])
    }
    if disabled_units:
        for table_name in _PERMISSION_TABLES:
            rows = _collect_permission_rows(sources, table_name)
            kept = [
                permission
                for permission in rows.values()
                if permission.key[0] not in disabled_units
            ]
            if not kept:
                continue
            entries.append(_serialize_versionless_table(table_name, kept))

    return GameDataBuildResult(
        tuple(entries),
        {
            "edited_unit_count": len(normalized_edits),
            "disabled_unit_count": len(disabled_units),
            "entry_count": len(entries),
        },
    )
