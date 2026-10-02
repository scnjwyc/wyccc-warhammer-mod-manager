"""Replace selected Pack entries while preserving the original container metadata."""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import tempfile
import uuid
from pathlib import Path
from typing import Mapping

from .pack_reader import read_pack_index, read_pack_layout


def pack_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replace_pack_entries(
    path: Path,
    replacements: Mapping[str, bytes],
    backup_dir: Path,
    expected_digest: str,
) -> Path:
    """Stage and verify a complete Pack, back up the original, then atomically replace it.

    Untouched entries keep their raw bytes, compression flags and timestamps. Updated
    entries are stored uncompressed; header, dependencies and trailing data stay intact.
    """
    layout = read_pack_layout(path)
    if layout is None:
        raise ValueError("schemaUpdate.invalidPack")
    entries = read_pack_index(path)
    if len({entry.name for entry in entries}) != len(entries):
        raise ValueError("schemaUpdate.duplicateEntries")
    if not replacements or set(replacements) - {entry.name for entry in entries}:
        raise ValueError("schemaUpdate.invalidPack")
    timestamp_size = (8 if layout.magic in {b"PFH2", b"PFH3"} else 4) if layout.type_and_flags & 0x40 else 0
    flag_size = int(layout.magic in {b"PFH5", b"PFH6"})
    index_start = layout.header_size + layout.dependency_size
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    backup = backup_dir / f"{uuid.uuid4().hex}_{path.name}.bak"
    try:
        with os.fdopen(handle, "wb") as target, path.open("rb") as source:
            prefix = source.read(index_start)
            raw_index = bytearray(source.read(layout.file_index_size))
            cursor = 0
            for entry in entries:
                if entry.name in replacements:
                    struct.pack_into("<I", raw_index, cursor, len(replacements[entry.name]))
                    if flag_size:
                        raw_index[cursor + 4 + timestamp_size] = 0
                cursor = raw_index.index(0, cursor + 4 + timestamp_size + flag_size) + 1
            target.write(prefix)
            target.write(raw_index)
            for entry in entries:
                if entry.name in replacements:
                    target.write(replacements[entry.name])
                else:
                    source.seek(entry.offset)
                    remaining = entry.size
                    while remaining:
                        block = source.read(min(remaining, 1024 * 1024))
                        if not block:
                            raise ValueError("schemaUpdate.invalidPack")
                        target.write(block)
                        remaining -= len(block)
            source.seek(entries[-1].offset + entries[-1].size if entries else index_start + len(raw_index))
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        staged = read_pack_index(temporary)
        if [item.name for item in staged] != [item.name for item in entries]:
            raise ValueError("schemaUpdate.invalidPack")
        with temporary.open("rb") as stream:
            for entry in staged:
                if entry.name in replacements:
                    stream.seek(entry.offset)
                    if stream.read(entry.size) != replacements[entry.name] or entry.compressed:
                        raise ValueError("schemaUpdate.invalidPack")
        if pack_digest(path) != expected_digest:
            raise ValueError("schemaUpdate.fileChanged")
        backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, backup)
        except OSError:
            backup.unlink(missing_ok=True)
            raise
        if pack_digest(backup) != expected_digest or pack_digest(path) != expected_digest:
            backup.unlink(missing_ok=True)
            raise ValueError("schemaUpdate.fileChanged")
        shutil.copymode(path, temporary)
        os.replace(temporary, path)
        return backup
    finally:
        temporary.unlink(missing_ok=True)
