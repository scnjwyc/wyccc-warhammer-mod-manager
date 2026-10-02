"""Migrate MOD database entries to the definitions used by the installed game."""

from __future__ import annotations

import math
import struct
import uuid
from pathlib import Path

from .pack_reader import read_pack_index, read_pack_layout
from .pack_rewrite import pack_digest, replace_pack_entries
from .start_options import _decompress_payload, _has_compression_frame

GUID_MARKER = b"\xfd\xfe\xfc\xff"
VERSION_MARKER = b"\xfc\xfd\xfe\xff"
_NUMBERS = {"I16": "h", "I32": "i", "I64": "q", "F32": "f", "F64": "d", "ColourRGB": "I"}


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.cursor = data, 0

    def read(self, size: int) -> bytes:
        if size < 0 or self.cursor + size > len(self.data):
            raise ValueError("schemaUpdate.decodeFailed")
        value = self.data[self.cursor : self.cursor + size]
        self.cursor += size
        return value

    def number(self, fmt: str):
        return struct.unpack("<" + fmt, self.read(struct.calcsize("<" + fmt)))[0]


def table_header(data: bytes) -> tuple[int, bytes, int, int, int]:
    reader = _Reader(data)
    version, guid = 0, b""
    seen = set()
    while data[reader.cursor : reader.cursor + 4] in {GUID_MARKER, VERSION_MARKER}:
        marker = reader.read(4)
        if marker in seen:
            raise ValueError("schemaUpdate.decodeFailed")
        seen.add(marker)
        if marker == GUID_MARKER:
            length = reader.number("H")
            guid = marker + struct.pack("<H", length) + reader.read(length * 2)
        else:
            version = reader.number("i")
    mysterious = reader.number("B")
    if mysterious not in {0, 1}:
        raise ValueError("schemaUpdate.decodeFailed")
    count = reader.number("I")
    return version, guid, mysterious, count, reader.cursor


def _read_value(reader: _Reader, field_type):
    if isinstance(field_type, dict):
        kind = field_type["kind"]
        if kind not in {"SequenceU16", "SequenceU32"}:
            raise ValueError("schemaUpdate.unsupportedType")
        count = reader.number("H" if kind == "SequenceU16" else "I")
        return _read_rows(reader, field_type["definition"]["fields"], count)
    if field_type == "Boolean":
        value = reader.number("B")
        if value not in {0, 1}:
            raise ValueError("schemaUpdate.decodeFailed")
        return bool(value)
    if field_type in _NUMBERS:
        return reader.number(_NUMBERS[field_type])
    if field_type.startswith("OptionalI"):
        if reader.number("B") not in {0, 1}:
            raise ValueError("schemaUpdate.decodeFailed")
        return _read_value(reader, field_type.removeprefix("Optional"))
    if field_type in {"OptionalStringU8", "OptionalStringU16"}:
        present = reader.number("B")
        if present not in {0, 1}:
            raise ValueError("schemaUpdate.decodeFailed")
        return _read_value(reader, field_type.removeprefix("Optional")) if present else ""
    if field_type in {"StringU8", "StringU16"}:
        length = reader.number("H")
        raw = reader.read(length * (2 if field_type == "StringU16" else 1))
        return raw.decode("utf-16le" if field_type == "StringU16" else "utf-8", errors="surrogateescape")
    raise ValueError("schemaUpdate.unsupportedType")


def _read_rows(reader: _Reader, fields: list[dict], count: int) -> list:
    # Every supported field consumes at least one byte; this also bounds loops
    # for corrupt row counts and refuses zero-width schemas with nonempty data.
    if count and (not fields or count * len(fields) > len(reader.data) - reader.cursor):
        raise ValueError("schemaUpdate.decodeFailed")
    rows = []
    for _ in range(count):
        row = []
        for field in fields:
            start = reader.cursor
            value = _read_value(reader, field["type"])
            row.append((value, reader.data[start : reader.cursor]))
        rows.append(row)
    return rows


def decode_table(data: bytes, definitions: list[dict]) -> tuple[dict, list, tuple]:
    header = table_header(data)
    version, _, _, count, start = header
    candidates = (
        [d for d in definitions if d["version"] == version]
        if version > 0
        else [d for d in definitions if d["version"] <= 0]
    )
    if not candidates:
        raise ValueError("schemaUpdate.unknownVersion")
    for definition in candidates:
        reader = _Reader(data)
        reader.cursor = start
        try:
            rows = _read_rows(reader, definition["fields"], count)
            if reader.cursor == len(data):
                return definition, rows, header
        except (ValueError, UnicodeError, struct.error):
            continue
    raise ValueError("schemaUpdate.decodeFailed")


def _encode_value(value, field_type) -> bytes:
    if isinstance(field_type, dict):
        kind = field_type["kind"]
        return struct.pack("<H" if kind == "SequenceU16" else "<I", len(value)) + b"".join(
            b"".join(
                _encode_value(item[0], field["type"])
                for item, field in zip(row, field_type["definition"]["fields"])
            )
            for row in value
        )
    if field_type == "Boolean":
        return bytes([bool(value)])
    if field_type in _NUMBERS:
        return struct.pack("<" + _NUMBERS[field_type], value)
    if field_type.startswith("OptionalI"):
        return b"\1" + _encode_value(value, field_type.removeprefix("Optional"))
    if field_type in {"OptionalStringU8", "OptionalStringU16"}:
        return (b"\1" + _encode_value(value, field_type.removeprefix("Optional"))) if value else b"\0"
    if field_type in {"StringU8", "StringU16"}:
        raw = value.encode("utf-16le" if field_type == "StringU16" else "utf-8", errors="surrogateescape")
        return struct.pack("<H", len(raw) // (2 if field_type == "StringU16" else 1)) + raw
    raise ValueError("schemaUpdate.unsupportedType")


def _convert(value, old_type, new_type):
    if isinstance(old_type, dict) or isinstance(new_type, dict):
        raise ValueError("schemaUpdate.semanticChange")
    old_kind = old_type.removeprefix("Optional")
    kind = new_type.removeprefix("Optional")
    if kind == "Boolean":
        if isinstance(value, str):
            if value.lower() not in {"true", "false", "1", "0"}:
                raise ValueError("invalid boolean")
            return value.lower() in {"true", "1"}
        return value >= 1
    if kind in {"StringU8", "StringU16"}:
        if old_kind == "ColourRGB":
            return f"{value:06X}"
        return str(value).lower() if isinstance(value, bool) else str(value)
    if kind == "ColourRGB":
        return (
            (0xFFFFFF if value else 0)
            if isinstance(value, bool)
            else (int(value, 16) if isinstance(value, str) else int(value))
        )
    if kind.startswith("I"):
        if isinstance(value, str) and value != value.strip():
            raise ValueError("invalid integer")
        return int(value)
    if kind.startswith("F"):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("invalid float")
        return result
    raise ValueError("schemaUpdate.unsupportedType")


def _default(field: dict):
    kind = field["type"]
    if isinstance(kind, dict):
        return []
    base = kind.removeprefix("Optional")
    fallback = "" if base.startswith("String") else False if base == "Boolean" else 0
    default = field.get("default")
    if default is None:
        return fallback
    try:
        value = _convert(default, "StringU8", kind)
        _encode_value(value, kind)
        return value
    except (ValueError, OverflowError, struct.error):
        return fallback


def migrate_table(data: bytes, definitions: list[dict], target: dict) -> tuple[bytes, dict]:
    version = table_header(data)[0]
    if version > target["version"] and version > 0:
        return data, {"from_version": version, "to_version": target["version"], "rows": 0, "reset_values": 0}
    source, rows, header = decode_table(data, definitions)
    stats = {
        "from_version": source["version"],
        "to_version": target["version"],
        "rows": len(rows),
        "reset_values": 0,
    }
    if source == target or source["version"] > target["version"]:
        return data, stats
    old_fields, new_fields = source["fields"], target["fields"]
    if len({f["name"] for f in old_fields}) != len(old_fields) or len({f["name"] for f in new_fields}) != len(
        new_fields
    ):
        raise ValueError("schemaUpdate.semanticChange")
    positions = {f["name"]: i for i, f in enumerate(old_fields)}
    for field in new_fields:
        if field["name"] in positions:
            old = old_fields[positions[field["name"]]]
            if any(old.get(k) != field.get(k) for k in ("enum", "bitwise", "colour")):
                raise ValueError("schemaUpdate.semanticChange")
            if isinstance(old["type"], dict) or isinstance(field["type"], dict):
                if old["type"] != field["type"]:
                    raise ValueError("schemaUpdate.semanticChange")
    output = bytearray()
    for row in rows:
        for field in new_fields:
            position = positions.get(field["name"])
            if position is None:
                output.extend(_encode_value(_default(field), field["type"]))
                continue
            old = old_fields[position]
            value, raw = row[position]
            if old["type"] == field["type"]:
                output.extend(raw)
                continue
            try:
                output.extend(_encode_value(_convert(value, old["type"], field["type"]), field["type"]))
            except (ValueError, OverflowError, struct.error, UnicodeError):
                stats["reset_values"] += 1
                output.extend(_encode_value(_default(field), field["type"]))
    _, guid, mysterious, count, _ = header
    if not guid:
        value = str(uuid.uuid4()).encode("utf-16le")
        guid = GUID_MARKER + struct.pack("<H", len(value) // 2) + value
    encoded = guid + (VERSION_MARKER + struct.pack("<i", target["version"]) if target["version"] > 0 else b"")
    encoded += struct.pack("<BI", mysterious, count) + output
    decode_table(encoded, [target])  # Full-consumption verification before any Pack write.
    return encoded, stats


def db_table_name(name: str) -> str:
    parts = name.replace("\\", "/").split("/")
    return parts[1] if len(parts) >= 3 and parts[0].casefold() == "db" else ""


def _entry_payload(stream, entry) -> bytes:
    stream.seek(entry.offset)
    raw = stream.read(entry.size)
    if len(raw) != entry.size:
        raise ValueError("schemaUpdate.invalidPack")
    return _decompress_payload(raw, entry.name) if entry.compressed or _has_compression_frame(raw) else raw


def installed_definitions(data_dir: Path, names: set[str], schemas: dict) -> dict:
    if not data_dir.is_dir():
        raise ValueError("schemaUpdate.gameDataMissing")
    targets = {}
    found_vanilla = False
    for path in sorted(data_dir.glob("*.pack")):
        layout = read_pack_layout(path)
        if layout is None or layout.type_and_flags & 0xF > 2:
            continue
        found_vanilla = True
        with path.open("rb") as stream:
            for entry in read_pack_index(path):
                name = db_table_name(entry.name)
                if name not in names or name not in schemas:
                    continue
                if entry.compressed:
                    data = _entry_payload(stream, entry)
                else:
                    stream.seek(entry.offset)
                    data = stream.read(min(entry.size, 1024))
                    if _has_compression_frame(data):
                        data = _entry_payload(stream, entry)
                version = table_header(data)[0]
                if version > 0 and name in targets and version <= targets[name]["version"]:
                    continue
                if version > 0:
                    candidates = [d for d in schemas[name] if d["version"] == version]
                    if not candidates:
                        raise ValueError("schemaUpdate.unknownGameVersion")
                    definition = candidates[0]
                else:
                    definition = decode_table(_entry_payload(stream, entry), schemas[name])[0]
                if name not in targets or definition["version"] > targets[name]["version"]:
                    targets[name] = definition
    if not found_vanilla:
        raise ValueError("schemaUpdate.gameDataMissing")
    return targets


def update_mod_schema(path: Path, schemas: dict, targets: dict, backup_dir: Path) -> dict:
    if read_pack_layout(path) is None:
        raise ValueError("schemaUpdate.invalidPack")
    digest = pack_digest(path)
    replacements, tables, skipped = {}, [], []
    with path.open("rb") as stream:
        for entry in read_pack_index(path):
            name = db_table_name(entry.name)
            if not name:
                continue
            if name not in schemas or name not in targets:
                skipped.append(
                    {
                        "path": entry.name,
                        "reason": "schemaUpdate.unknownTable"
                        if name not in schemas
                        else "schemaUpdate.noGameTable",
                    }
                )
                continue
            try:
                payload = _entry_payload(stream, entry)
                updated, stats = migrate_table(payload, schemas[name], targets[name])
            except (ValueError, struct.error, UnicodeError) as exc:
                raise ValueError(f"{entry.name}: {exc}") from exc
            if updated != payload:
                replacements[entry.name] = updated
                tables.append({"path": entry.name, **stats})
    result = {"status": "updated" if replacements else "unchanged", "tables": tables, "skipped": skipped}
    if skipped:
        result["status"] = "partial"
    if replacements:
        result["backup_path"] = str(replace_pack_entries(path, replacements, backup_dir, digest))
    return result
