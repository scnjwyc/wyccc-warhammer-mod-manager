from __future__ import annotations

import base64
import os
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import ModAsset


RUNTIME_PACK_NAME = "!!!!wyccc_runtime_options.pack"
PERMISSIONS_PREFIX = "db\\units_custom_battle_permissions_tables\\"
PERMISSIONS_ENTRY = f"{PERMISSIONS_PREFIX}!!!!wyccc_runtime"
PERMISSIONS_VERSION = 11
PERMISSIONS_GUID = "129d32d8-3563-4d4f-8e19-a815e834e456"

INTRO_MOVIES = (
    "movies\\epilepsy_warning\\epilepsy_warning_en.ca_vp8",
    "movies\\gam_int.ca_vp8",
    "movies\\startup_movie_01.ca_vp8",
    "movies\\startup_movie_02.ca_vp8",
    "movies\\startup_movie_03.ca_vp8",
    "movies\\startup_movie_04.ca_vp8",
)

# Valid empty VP8 movie used by Warhammer Mod Manager for intro overrides.
EMPTY_MOVIE = base64.b64decode(
    "Q0FNVgEAKQBWUDgwgALgAVVVhUIBAAAAAQAAAEoCAAABAAAAIQIAAABQQgCdASqAAuABAEcIhYWI"
    "hYSIAgIABhYE9waBZJ9r25snOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsnOHsn"
    "OHsnOHsnOHsnN4D+/6tQgCkAAAAhAgAAAQ=="
)


@dataclass(frozen=True)
class PackEntry:
    name: str
    payload: bytes


def _decompress_payload(raw: bytes, name: str) -> bytes:
    offsets: list[int] = []

    def add_offset(value: int) -> None:
        if 0 <= value < len(raw) and value not in offsets:
            offsets.append(value)

    add_offset(4)
    add_offset(0)
    for index in range(0, min(32, max(0, len(raw) - 4)) + 1):
        if raw[index : index + 4] in {b"\x28\xb5\x2f\xfd", b"\x04\x22\x4d\x18"}:
            add_offset(index)
    for value in (8, 12, 16):
        add_offset(value)

    last_error: Exception | None = None
    try:
        import zstandard

        decompressor = zstandard.ZstdDecompressor()
        for offset in offsets:
            try:
                # CA stores the decompressed byte count immediately before a
                # Zstandard frame.  The frame itself intentionally omits the
                # content-size field, so python-zstandard needs that value as
                # max_output_size (vanilla db.pack uses this layout).
                declared_size = 0
                if offset >= 4:
                    declared_size = struct.unpack_from("<I", raw, offset - 4)[0]
                if 0 < declared_size <= 512 * 1024 * 1024:
                    return decompressor.decompress(
                        raw[offset:],
                        max_output_size=declared_size,
                    )
                return decompressor.decompress(raw[offset:])
            except zstandard.ZstdError as exc:
                last_error = exc
    except ImportError as exc:
        last_error = exc

    try:
        import lz4.frame

        for offset in offsets:
            try:
                return lz4.frame.decompress(raw[offset:])
            except (RuntimeError, ValueError) as exc:
                last_error = exc
    except ImportError as exc:
        last_error = exc

    for offset in offsets:
        for window_bits in (-zlib.MAX_WBITS, zlib.MAX_WBITS):
            try:
                return zlib.decompress(raw[offset:], window_bits)
            except zlib.error as exc:
                last_error = exc
    raise ValueError(f"无法解压权限表 {name}：{last_error or '未知压缩格式'}")


def read_pack_entries(path: Path, prefix: str = "") -> list[PackEntry]:
    try:
        with path.open("rb") as stream:
            header = stream.read(28)
            if len(header) != 28 or header[:4] != b"PFH5":
                return []
            _, _, dependency_size, file_count, index_size, _ = struct.unpack_from("<6i", header, 4)
            if dependency_size < 0 or file_count < 0 or index_size < 0:
                raise ValueError(f"Pack 索引无效：{path.name}")
            stream.seek(28 + dependency_size)
            index = stream.read(index_size)
            if len(index) != index_size:
                raise ValueError(f"Pack 索引不完整：{path.name}")
            data_offset = 28 + dependency_size + index_size
            cursor = 0
            current_offset = data_offset
            selected: list[tuple[str, int, int, bool]] = []
            for _ in range(file_count):
                if cursor + 5 > len(index):
                    raise ValueError(f"Pack 文件索引损坏：{path.name}")
                file_size = struct.unpack_from("<i", index, cursor)[0]
                compressed = index[cursor + 4] == 1
                cursor += 5
                terminator = index.find(b"\0", cursor)
                if file_size < 0 or terminator < 0:
                    raise ValueError(f"Pack 文件索引损坏：{path.name}")
                name = index[cursor:terminator].decode("utf-8", errors="replace")
                if not prefix or name.casefold().startswith(prefix.casefold()):
                    selected.append((name, current_offset, file_size, compressed))
                current_offset += file_size
                cursor = terminator + 1

            entries: list[PackEntry] = []
            for name, offset, file_size, compressed in selected:
                stream.seek(offset)
                payload = stream.read(file_size)
                if len(payload) != file_size:
                    raise ValueError(f"Pack 内文件不完整：{name}")
                entries.append(PackEntry(name, _decompress_payload(payload, name) if compressed else payload))
            return entries
    except OSError as exc:
        raise ValueError(f"无法读取 Pack：{path}") from exc


def _skip_string_u8(payload: bytes, cursor: int) -> int:
    if cursor + 2 > len(payload):
        raise ValueError("权限表字符串长度越界")
    length = struct.unpack_from("<H", payload, cursor)[0]
    cursor += 2 + length
    if cursor > len(payload):
        raise ValueError("权限表字符串内容越界")
    return cursor


def _skip_optional_string_u8(payload: bytes, cursor: int) -> int:
    if cursor >= len(payload):
        raise ValueError("权限表可选字符串越界")
    exists = payload[cursor]
    cursor += 1
    if exists == 1:
        return _skip_string_u8(payload, cursor)
    if exists != 0:
        raise ValueError("权限表可选字符串标记无效")
    return cursor


def _permission_rows(payload: bytes) -> list[bytes]:
    cursor = 0
    version: int | None = None
    while cursor + 4 <= len(payload):
        marker = payload[cursor : cursor + 4]
        if marker == b"\xfd\xfe\xfc\xff":
            cursor += 4
            if cursor + 2 > len(payload):
                raise ValueError("权限表 GUID 头不完整")
            length = struct.unpack_from("<H", payload, cursor)[0]
            cursor += 2 + length * 2
        elif marker == b"\xfc\xfd\xfe\xff":
            cursor += 4
            if cursor + 4 > len(payload):
                raise ValueError("权限表版本头不完整")
            version = struct.unpack_from("<i", payload, cursor)[0]
            cursor += 4
        else:
            break
    if version != PERMISSIONS_VERSION:
        return []
    if cursor + 5 > len(payload):
        raise ValueError("权限表行头不完整")
    cursor += 1  # table marker
    row_count = struct.unpack_from("<i", payload, cursor)[0]
    cursor += 4
    if row_count < 0:
        raise ValueError("权限表行数无效")

    rows: list[bytes] = []
    for _ in range(row_count):
        row_start = cursor
        cursor = _skip_string_u8(payload, cursor)  # faction
        general_offset = cursor
        cursor += 1  # general_unit
        cursor = _skip_string_u8(payload, cursor)  # unit
        cursor += 2  # siege_unit_attacker / siege_unit_defender
        cursor = _skip_optional_string_u8(payload, cursor)  # general_portrait
        cursor = _skip_optional_string_u8(payload, cursor)  # general_uniform
        cursor = _skip_optional_string_u8(payload, cursor)  # set_piece_character
        cursor += 1  # campaign_exclusive
        cursor = _skip_optional_string_u8(payload, cursor)  # armory_item_set
        cursor += 1  # supports_upgrades
        if cursor > len(payload):
            raise ValueError("权限表行内容越界")
        original = payload[row_start:cursor]
        relative_general = general_offset - row_start
        general_value = original[relative_general]
        if general_value not in {0, 1}:
            raise ValueError("权限表 general_unit 字段无效")
        modified = bytearray(original)
        modified[relative_general] = 1
        rows.append(bytes(modified))
        if general_value == 1:
            duplicate = bytearray(original)
            duplicate[relative_general] = 0
            rows.append(bytes(duplicate))
    return rows


def _build_permission_table(pack_paths: Iterable[Path]) -> bytes:
    rows: list[bytes] = []
    for pack_path in pack_paths:
        for entry in read_pack_entries(pack_path, PERMISSIONS_PREFIX):
            rows.extend(_permission_rows(entry.payload))
    if not rows:
        raise ValueError("未能读取自定义战斗权限表，无法启用“所有单位视为领主”")
    guid = PERMISSIONS_GUID.encode("utf-16le")
    return b"".join(
        (
            b"\xfd\xfe\xfc\xff",
            struct.pack("<H", len(PERMISSIONS_GUID)),
            guid,
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", PERMISSIONS_VERSION),
            b"\x01",
            struct.pack("<i", len(rows)),
            b"".join(rows),
        )
    )


def write_pfh5_pack(path: Path, entries: Iterable[PackEntry]) -> Path:
    normalized = list(entries)
    if not normalized:
        raise ValueError("运行时 Pack 没有可写入内容")
    index_parts: list[bytes] = []
    for entry in normalized:
        name = entry.name.encode("utf-8")
        index_parts.append(struct.pack("<iB", len(entry.payload), 0) + name + b"\0")
    index = b"".join(index_parts)
    content = b"".join(
        (
            b"PFH5",
            struct.pack("<6i", 3, 0, 0, len(normalized), len(index), 0x7FFFFFFF),
            index,
            *(entry.payload for entry in normalized),
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def build_runtime_options_pack(
    output_dir: Path,
    data_path: str,
    assets: dict[str, ModAsset],
    active_ids: list[str],
    settings: dict[str, Any],
) -> dict[str, Any]:
    entries: list[PackEntry] = []
    enabled_options: list[str] = []
    if settings.get("custom_battle_all_units_as_lords"):
        pack_paths: list[Path] = [Path(data_path) / "db.pack"]
        pack_paths.extend(
            Path(assets[mod_id].path)
            for mod_id in active_ids
            if mod_id in assets and Path(assets[mod_id].path).is_file()
        )
        unique_paths = list(dict.fromkeys(path.resolve(strict=False) for path in pack_paths if path.is_file()))
        entries.append(PackEntry(PERMISSIONS_ENTRY, _build_permission_table(unique_paths)))
        enabled_options.append("custom_battle_all_units_as_lords")
    if settings.get("enable_script_logging"):
        entries.append(PackEntry("script\\enable_console_logging", b"\0"))
        enabled_options.append("enable_script_logging")
    if settings.get("skip_intro_movies"):
        entries.extend(PackEntry(name, EMPTY_MOVIE) for name in INTRO_MOVIES)
        enabled_options.append("skip_intro_movies")

    output_path = Path(output_dir) / RUNTIME_PACK_NAME
    if not entries:
        output_path.unlink(missing_ok=True)
        return {"path": "", "options": [], "entry_count": 0}
    write_pfh5_pack(output_path, entries)
    return {
        "path": str(output_path.resolve(strict=False)),
        "options": enabled_options,
        "entry_count": len(entries),
    }
