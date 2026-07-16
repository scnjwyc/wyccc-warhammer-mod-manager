from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .constants import UNIT_MODEL_MULTIPLIER_MAX, UNIT_MODEL_MULTIPLIER_MIN


SCHEMA_PATH = Path(__file__).with_name("wh3_db_schema.json")


def _load_schemas() -> dict[str, dict[int, tuple[tuple[str, str], ...]]]:
    try:
        raw = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取战锤 3 DB 架构：{SCHEMA_PATH}") from exc
    return {
        str(table_name): {
            int(version): tuple((str(name), str(field_type)) for name, field_type in fields)
            for version, fields in versions.items()
        }
        for table_name, versions in raw.items()
    }


# This is a focused subset of the locally verified WH3 schema.  Every known
# version of the five touched tables is retained so older enabled mods can be
# resolved without replacing their rows with vanilla data.
TABLE_SCHEMAS = _load_schemas()
TABLE_ORDER = (
    "main_units_tables",
    "land_units_tables",
    "projectiles_tables",
    "projectiles_explosions_tables",
    "battle_vortexs_tables",
)
TABLE_PREFIXES = tuple(f"db\\{table_name}\\" for table_name in TABLE_ORDER)
CURRENT_TABLE_VERSIONS = {
    "main_units_tables": 7,
    "land_units_tables": 54,
    "projectiles_tables": 53,
    "projectiles_explosions_tables": 19,
    "battle_vortexs_tables": 19,
}
TABLE_KEY_FIELDS = {
    "main_units_tables": "unit",
    "land_units_tables": "key",
    "projectiles_tables": "key",
    "projectiles_explosions_tables": "key",
    "battle_vortexs_tables": "vortex_key",
}


@dataclass(frozen=True)
class GameDataEntry:
    name: str
    payload: bytes


@dataclass(frozen=True)
class DbSource:
    name: str
    entries: Sequence[GameDataEntry]


@dataclass(frozen=True)
class FieldSpan:
    field_type: str
    start: int
    end: int
    value: Any


@dataclass(frozen=True)
class ParsedDbRow:
    raw: bytes
    fields: Mapping[str, FieldSpan]

    @property
    def values(self) -> dict[str, Any]:
        return {name: field.value for name, field in self.fields.items()}


@dataclass(frozen=True)
class ParsedDbTable:
    table_name: str
    version: int
    rows: tuple[ParsedDbRow, ...]


@dataclass(frozen=True)
class GameDataBuildResult:
    entries: tuple[GameDataEntry, ...]
    stats: dict[str, int | float]


@dataclass(frozen=True)
class _Candidate:
    row: ParsedDbRow
    version: int
    internal_name: str
    source_rank: int
    entry_rank: int
    row_rank: int


def _require(payload: bytes, cursor: int, size: int, context: str) -> None:
    if size < 0 or cursor < 0 or cursor + size > len(payload):
        raise ValueError(f"DB 表数据越界：{context}")


def _parse_field(payload: bytes, cursor: int, field_type: str, context: str) -> tuple[Any, int]:
    if field_type == "Boolean":
        _require(payload, cursor, 1, context)
        value = payload[cursor]
        if value not in {0, 1}:
            raise ValueError(f"DB 布尔字段无效：{context}")
        return bool(value), cursor + 1
    if field_type in {"I32", "ColourRGB"}:
        _require(payload, cursor, 4, context)
        return struct.unpack_from("<i", payload, cursor)[0], cursor + 4
    if field_type == "I16":
        _require(payload, cursor, 2, context)
        return struct.unpack_from("<h", payload, cursor)[0], cursor + 2
    if field_type == "I64":
        _require(payload, cursor, 8, context)
        return struct.unpack_from("<q", payload, cursor)[0], cursor + 8
    if field_type == "F32":
        _require(payload, cursor, 4, context)
        return struct.unpack_from("<f", payload, cursor)[0], cursor + 4
    if field_type == "F64":
        _require(payload, cursor, 8, context)
        return struct.unpack_from("<d", payload, cursor)[0], cursor + 8
    if field_type == "StringU8":
        _require(payload, cursor, 2, context)
        length = struct.unpack_from("<H", payload, cursor)[0]
        cursor += 2
        _require(payload, cursor, length, context)
        return payload[cursor : cursor + length].decode("ascii", errors="replace"), cursor + length
    if field_type == "OptionalStringU8":
        _require(payload, cursor, 1, context)
        exists = payload[cursor]
        cursor += 1
        if exists == 0:
            return None, cursor
        if exists != 1:
            raise ValueError(f"DB 可选字符串标记无效：{context}")
        return _parse_field(payload, cursor, "StringU8", context)
    if field_type == "StringU16":
        _require(payload, cursor, 2, context)
        length = struct.unpack_from("<H", payload, cursor)[0]
        cursor += 2
        byte_length = length * 2
        _require(payload, cursor, byte_length, context)
        return payload[cursor : cursor + byte_length].decode("utf-16le", errors="replace"), cursor + byte_length
    raise ValueError(f"不支持的 DB 字段类型：{field_type}（{context}）")


def parse_db_table(table_name: str, payload: bytes) -> ParsedDbTable:
    schemas = TABLE_SCHEMAS.get(table_name)
    if not schemas:
        raise ValueError(f"不支持的 DB 表：{table_name}")

    cursor = 0
    version: int | None = None
    while cursor + 4 <= len(payload):
        marker = payload[cursor : cursor + 4]
        if marker == b"\xfd\xfe\xfc\xff":
            cursor += 4
            _require(payload, cursor, 2, f"{table_name} GUID")
            length = struct.unpack_from("<H", payload, cursor)[0]
            cursor += 2
            _require(payload, cursor, length * 2, f"{table_name} GUID")
            cursor += length * 2
            continue
        if marker == b"\xfc\xfd\xfe\xff":
            cursor += 4
            _require(payload, cursor, 4, f"{table_name} version")
            version = struct.unpack_from("<i", payload, cursor)[0]
            cursor += 4
            continue
        break

    resolved_version = version if version is not None else CURRENT_TABLE_VERSIONS[table_name]
    schema = schemas.get(resolved_version)
    if not schema:
        supported = ", ".join(str(item) for item in sorted(schemas))
        raise ValueError(
            f"不支持 {table_name} 的 DB 版本 {resolved_version}；已支持版本：{supported}"
        )
    _require(payload, cursor, 5, f"{table_name} row header")
    cursor += 1  # table marker
    row_count = struct.unpack_from("<i", payload, cursor)[0]
    cursor += 4
    if row_count < 0:
        raise ValueError(f"DB 表行数无效：{table_name}")

    rows: list[ParsedDbRow] = []
    for row_index in range(row_count):
        row_start = cursor
        absolute_fields: dict[str, FieldSpan] = {}
        for field_name, field_type in schema:
            field_start = cursor
            value, cursor = _parse_field(
                payload,
                cursor,
                field_type,
                f"{table_name} v{resolved_version} row {row_index + 1} field {field_name}",
            )
            absolute_fields[field_name] = FieldSpan(field_type, field_start, cursor, value)
        row_raw = payload[row_start:cursor]
        relative_fields = {
            name: replace(field, start=field.start - row_start, end=field.end - row_start)
            for name, field in absolute_fields.items()
        }
        rows.append(ParsedDbRow(row_raw, relative_fields))

    if cursor != len(payload):
        raise ValueError(
            f"DB 表 {table_name} v{resolved_version} 解析后仍有 {len(payload) - cursor} 字节，架构可能已更新"
        )
    return ParsedDbTable(table_name, resolved_version, tuple(rows))


def _patch_i32(row: ParsedDbRow, field_name: str, value: int) -> ParsedDbRow:
    field = row.fields.get(field_name)
    if not field or field.field_type != "I32":
        return row
    raw = bytearray(row.raw)
    struct.pack_into("<i", raw, field.start, int(value))
    fields = dict(row.fields)
    fields[field_name] = replace(field, value=int(value))
    return ParsedDbRow(bytes(raw), fields)


def _patch_bool(row: ParsedDbRow, field_name: str, value: bool) -> ParsedDbRow:
    field = row.fields.get(field_name)
    if not field or field.field_type != "Boolean":
        return row
    raw = bytearray(row.raw)
    raw[field.start] = 1 if value else 0
    fields = dict(row.fields)
    fields[field_name] = replace(field, value=bool(value))
    return ParsedDbRow(bytes(raw), fields)


def _compare_internal_names(first: str, second: str) -> int:
    """Match the internal DB-file priority comparison used by WH3 Mod Manager."""
    first = first.casefold()
    second = second.casefold()
    for index in range(max(len(first), len(second))):
        if index == len(first):
            return 1
        if index == len(second):
            return -1
        difference = ord(first[index]) - ord(second[index])
        if difference:
            return -1 if difference < 0 else 1
    return 0


def _has_higher_priority(candidate: _Candidate, existing: _Candidate) -> bool:
    file_order = _compare_internal_names(candidate.internal_name, existing.internal_name)
    if file_order:
        return file_order < 0
    return (
        candidate.source_rank,
        candidate.entry_rank,
        candidate.row_rank,
    ) < (
        existing.source_rank,
        existing.entry_rank,
        existing.row_rank,
    )


def _entry_table_name(name: str) -> tuple[str, str] | None:
    normalized = name.replace("/", "\\")
    parts = normalized.split("\\", 2)
    if len(parts) != 3 or parts[0].casefold() != "db":
        return None
    if parts[2].casefold().endswith(".tsv"):
        return None
    matched = next((table for table in TABLE_ORDER if table.casefold() == parts[1].casefold()), None)
    if not matched:
        return None
    return matched, parts[2]


def _collect_effective_rows(
    sources: Sequence[DbSource],
    needed_tables: set[str],
) -> dict[str, dict[str, _Candidate]]:
    effective = {table_name: {} for table_name in needed_tables}
    for source_rank, source in enumerate(sources):
        for entry_rank, entry in enumerate(source.entries):
            resolved = _entry_table_name(entry.name)
            if not resolved or resolved[0] not in needed_tables:
                continue
            table_name, internal_name = resolved
            try:
                parsed = parse_db_table(table_name, entry.payload)
            except ValueError as exc:
                raise ValueError(f"读取 {source.name} 中的 {entry.name} 失败：{exc}") from exc
            key_field = TABLE_KEY_FIELDS[table_name]
            for row_rank, row in enumerate(parsed.rows):
                key = str(row.values.get(key_field) or "")
                if not key:
                    raise ValueError(f"{source.name} 中的 {entry.name} 存在空主键")
                candidate = _Candidate(
                    row,
                    parsed.version,
                    internal_name,
                    source_rank,
                    entry_rank,
                    row_rank,
                )
                existing = effective[table_name].get(key)
                if existing is None or _has_higher_priority(candidate, existing):
                    effective[table_name][key] = candidate
    return effective


def _scaled_i32(value: Any, multiplier: float, minimum: int | None = None) -> int:
    numeric = int(value or 0)
    scaled = numeric * multiplier
    if minimum is not None:
        scaled = max(scaled, minimum)
    return max(-(2**31), min(2**31 - 1, math.ceil(scaled)))


def _serialize_effective_table(
    table_name: str,
    candidates: Mapping[str, _Candidate],
    patched: Mapping[str, ParsedDbRow],
) -> list[GameDataEntry]:
    grouped: dict[int, list[tuple[str, ParsedDbRow]]] = {}
    for key, candidate in candidates.items():
        grouped.setdefault(candidate.version, []).append((key, patched.get(key, candidate.row)))

    entries: list[GameDataEntry] = []
    for version in sorted(grouped):
        rows = [row for _key, row in sorted(grouped[version], key=lambda item: item[0].casefold())]
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
                f"db\\{table_name}\\!!!!wyccc_game_data_v{version:04d}",
                payload,
            )
        )
    return entries


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _classifications_for_reference(
    key: str,
    spell_keys: set[str],
    unit_keys: set[str],
) -> set[bool]:
    result: set[bool] = set()
    if key in spell_keys:
        result.add(True)
    if key in unit_keys:
        result.add(False)
    return result


def build_game_data_entries(
    sources: Sequence[DbSource],
    settings: Mapping[str, Any],
) -> GameDataBuildResult:
    try:
        multiplier = float(settings.get("unit_model_multiplier", 1.0))
    except (TypeError, ValueError):
        multiplier = 1.0
    if not math.isfinite(multiplier):
        multiplier = 1.0
    multiplier = max(
        UNIT_MODEL_MULTIPLIER_MIN,
        min(UNIT_MODEL_MULTIPLIER_MAX, multiplier),
    )
    disable_unit = _coerce_bool(settings.get("disable_unit_friendly_fire", False))
    disable_spell = _coerce_bool(settings.get("disable_spell_friendly_fire", False))
    scale_units = not math.isclose(multiplier, 1.0, rel_tol=0.0, abs_tol=1e-9)

    stats: dict[str, int | float] = {
        "unit_model_multiplier": multiplier,
        "unit_rows_scaled": 0,
        "land_rows_scaled": 0,
        "unit_friendly_fire_rows_changed": 0,
        "spell_friendly_fire_rows_changed": 0,
    }
    needed_tables: set[str] = set()
    if scale_units:
        needed_tables.update({"main_units_tables", "land_units_tables"})
    if disable_unit or disable_spell:
        needed_tables.update(
            {
                "projectiles_tables",
                "projectiles_explosions_tables",
                "battle_vortexs_tables",
            }
        )
    if not needed_tables:
        return GameDataBuildResult((), stats)

    effective = _collect_effective_rows(sources, needed_tables)
    for table_name in needed_tables:
        if not effective[table_name]:
            raise ValueError(f"未能从当前游戏和启用 MOD 中读取 {table_name}")

    patched_by_table: dict[str, dict[str, ParsedDbRow]] = {
        table_name: {} for table_name in needed_tables
    }
    if scale_units:
        target_land_units: set[str] = set()
        for key, candidate in effective["main_units_tables"].items():
            values = candidate.row.values
            caste = str(values.get("caste") or "").casefold()
            row = candidate.row
            if caste not in {"lord", "hero"}:
                land_unit = str(values.get("land_unit") or "")
                if land_unit:
                    target_land_units.add(land_unit)
                new_count = _scaled_i32(values.get("num_men"), multiplier, minimum=1)
                row = _patch_i32(row, "num_men", new_count)
                if new_count != int(values.get("num_men") or 0):
                    stats["unit_rows_scaled"] = int(stats["unit_rows_scaled"]) + 1
            patched_by_table["main_units_tables"][key] = row

        for key, candidate in effective["land_units_tables"].items():
            row = candidate.row
            values = row.values
            if key in target_land_units:
                new_mounts = _scaled_i32(values.get("num_mounts"), multiplier)
                new_engines = _scaled_i32(values.get("num_engines"), multiplier)
                row = _patch_i32(row, "num_mounts", new_mounts)
                row = _patch_i32(row, "num_engines", new_engines)
                if (
                    new_mounts != int(values.get("num_mounts") or 0)
                    or new_engines != int(values.get("num_engines") or 0)
                ):
                    stats["land_rows_scaled"] = int(stats["land_rows_scaled"]) + 1
            patched_by_table["land_units_tables"][key] = row

    if disable_unit or disable_spell:
        spell_explosions: set[str] = set()
        unit_explosions: set[str] = set()
        spell_vortexes: set[str] = set()
        unit_vortexes: set[str] = set()
        for key, candidate in effective["projectiles_tables"].items():
            row = candidate.row
            values = row.values
            classification = bool(values["is_spell"]) if "is_spell" in values else None
            if classification is not None:
                explosion = str(values.get("explosion_type") or "")
                vortex = str(values.get("spawned_vortex") or "")
                if explosion:
                    (spell_explosions if classification else unit_explosions).add(explosion)
                if vortex:
                    (spell_vortexes if classification else unit_vortexes).add(vortex)
                should_disable = disable_spell if classification else disable_unit
                if should_disable and values.get("can_damage_allies") is True:
                    row = _patch_bool(row, "can_damage_allies", False)
                    stat_key = (
                        "spell_friendly_fire_rows_changed"
                        if classification
                        else "unit_friendly_fire_rows_changed"
                    )
                    stats[stat_key] = int(stats[stat_key]) + 1
            patched_by_table["projectiles_tables"][key] = row

        for table_name, reference_spell, reference_unit in (
            ("projectiles_explosions_tables", spell_explosions, unit_explosions),
            ("battle_vortexs_tables", spell_vortexes, unit_vortexes),
        ):
            for key, candidate in effective[table_name].items():
                row = candidate.row
                values = row.values
                if "is_spell" in values:
                    classifications = {bool(values["is_spell"])}
                else:
                    classifications = _classifications_for_reference(
                        key,
                        reference_spell,
                        reference_unit,
                    )
                should_disable = any(
                    (classification and disable_spell) or (not classification and disable_unit)
                    for classification in classifications
                )
                if should_disable and values.get("affects_allies") is True:
                    row = _patch_bool(row, "affects_allies", False)
                    for classification in classifications:
                        if (classification and disable_spell) or (not classification and disable_unit):
                            stat_key = (
                                "spell_friendly_fire_rows_changed"
                                if classification
                                else "unit_friendly_fire_rows_changed"
                            )
                            stats[stat_key] = int(stats[stat_key]) + 1
                patched_by_table[table_name][key] = row

    entries: list[GameDataEntry] = []
    for table_name in TABLE_ORDER:
        if table_name not in needed_tables:
            continue
        entries.extend(
            _serialize_effective_table(
                table_name,
                effective[table_name],
                patched_by_table[table_name],
            )
        )
    return GameDataBuildResult(tuple(entries), stats)
