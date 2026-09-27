from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

_PACK_MAGICS = {b"PFH2", b"PFH3", b"PFH4", b"PFH5", b"PFH6"}
_PACK_TYPE_MASK = 0x0F
_PACK_FLAG_INDEX_TIMESTAMPS = 0x40
_PACK_FLAG_ENCRYPTED_INDEX = 0x80
_PACK_FLAG_EXTENDED_HEADER = 0x100
_MAX_PACK_INDEX_SIZE = 64 * 1024 * 1024


@dataclass(frozen=True)
class PackLayout:
    magic: bytes
    type_and_flags: int
    dependency_count: int
    dependency_size: int
    file_count: int
    file_index_size: int
    header_size: int


def read_pack_layout(path: Path) -> PackLayout | None:
    """Read the common PFH2-PFH6 index layout without loading Pack payloads."""
    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            prefix = stream.read(12)
            magic_offset = 8 if prefix[:3] == b"MFH" and prefix[8:12] in _PACK_MAGICS else 0
            magic = prefix[magic_offset:magic_offset + 4]
            if magic not in _PACK_MAGICS:
                return None
            stream.seek(magic_offset + 4)
            type_and_flags_data = stream.read(4)
            index_fields = stream.read(16)
            if len(type_and_flags_data) != 4 or len(index_fields) != 16:
                return None
            type_and_flags = struct.unpack("<I", type_and_flags_data)[0]
            dependency_count, dependency_size, file_count, file_index_size = struct.unpack(
                "<4I", index_fields
            )
            timestamp_size = 8 if magic in {b"PFH2", b"PFH3"} else 4
            if len(stream.read(timestamp_size)) != timestamp_size:
                return None
    except OSError:
        return None

    extra_header_size = 280 if magic == b"PFH6" else (
        20 if type_and_flags & _PACK_FLAG_EXTENDED_HEADER else 0
    )
    header_size = magic_offset + 4 + 4 + 16 + timestamp_size + extra_header_size
    if (
        dependency_size > _MAX_PACK_INDEX_SIZE
        or file_index_size > _MAX_PACK_INDEX_SIZE
        or header_size + dependency_size + file_index_size > file_size
    ):
        return None
    return PackLayout(
        magic=magic,
        type_and_flags=type_and_flags,
        dependency_count=dependency_count,
        dependency_size=dependency_size,
        file_count=file_count,
        file_index_size=file_index_size,
        header_size=header_size,
    )


@dataclass(frozen=True)
class PackIndexEntry:
    name: str
    offset: int
    size: int
    compressed: bool


def read_pack_index(path: Path) -> list[PackIndexEntry]:
    layout = read_pack_layout(path)
    if layout is None:
        with path.open("rb") as stream:
            prefix = stream.read(12)
        if prefix[:4] not in _PACK_MAGICS and not (prefix[:3] == b"MFH" and prefix[8:12] in _PACK_MAGICS):
            return []
        raise ValueError(f"Pack 索引无效：{path.name}")
    if layout.type_and_flags & _PACK_FLAG_ENCRYPTED_INDEX:
        raise ValueError(f"不支持加密 Pack 索引：{path.name}")
    index_offset = layout.header_size + layout.dependency_size
    with path.open("rb") as stream:
        stream.seek(index_offset)
        index = stream.read(layout.file_index_size)
    if len(index) != layout.file_index_size:
        raise ValueError(f"Pack 索引不完整：{path.name}")
    timestamp_size = (
        8 if layout.magic in {b"PFH2", b"PFH3"} else 4
    ) if layout.type_and_flags & _PACK_FLAG_INDEX_TIMESTAMPS else 0
    compression_flag_size = 1 if layout.magic in {b"PFH5", b"PFH6"} else 0
    fixed_entry_size = 4 + timestamp_size + compression_flag_size
    cursor = 0
    data_offset = index_offset + len(index)
    file_size = path.stat().st_size
    entries: list[PackIndexEntry] = []
    for _ in range(layout.file_count):
        if cursor + fixed_entry_size > len(index):
            raise ValueError(f"Pack 文件索引损坏：{path.name}")
        size = struct.unpack_from("<I", index, cursor)[0]
        compressed = bool(compression_flag_size and index[cursor + 4 + timestamp_size])
        cursor += fixed_entry_size
        terminator = index.find(b"\0", cursor)
        if terminator < 0 or terminator == cursor or data_offset + size > file_size:
            raise ValueError(f"Pack 文件索引损坏：{path.name}")
        name = index[cursor:terminator].decode("utf-8", errors="replace")
        entries.append(PackIndexEntry(name, data_offset, size, compressed))
        data_offset += size
        cursor = terminator + 1
    if cursor != len(index):
        raise ValueError(f"Pack 文件索引损坏：{path.name}")
    return entries
