from __future__ import annotations

import struct
from pathlib import Path

from backend.models import ModAsset


def write_pack(
    path: Path,
    byte_mask: int = 0,
    dependencies: list[str] | None = None,
    entries: list[tuple[str, bytes]] | None = None,
    magic: bytes = b"PFH5",
    fake_workshop_preamble: bool = False,
) -> Path:
    """Create a small PFH2-PFH6 fixture with optional uncompressed entries."""
    if magic not in {b"PFH2", b"PFH3", b"PFH4", b"PFH5", b"PFH6"}:
        raise ValueError(f"unsupported fixture Pack magic: {magic!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    dependency_block = b"".join(
        value.encode("utf-8") + b"\0" for value in (dependencies or [])
    )
    entry_values = list(entries or [])
    timestamp_size = 8 if magic in {b"PFH2", b"PFH3"} else 4
    has_index_timestamps = bool(byte_mask & 0x40)
    compression_flag = b"\0" if magic in {b"PFH5", b"PFH6"} else b""
    index = b"".join(
        struct.pack("<i", len(payload))
        + (b"\0" * timestamp_size if has_index_timestamps else b"")
        + compression_flag
        + name.encode("utf-8")
        + b"\0"
        for name, payload in entry_values
    )
    payloads = b"".join(payload for _, payload in entry_values)
    header_timestamp = b"\0" * timestamp_size
    extra_header = b"\0" * (280 if magic == b"PFH6" else (20 if byte_mask & 0x100 else 0))
    preamble = b"MFH\0\0\0\0\0" if fake_workshop_preamble else b""
    path.write_bytes(
        preamble
        + magic
        + struct.pack("<I", byte_mask)
        + struct.pack("<I", len(dependencies or []))
        + struct.pack("<I", len(dependency_block))
        + struct.pack("<I", len(entry_values))
        + struct.pack("<I", len(index))
        + header_timestamp
        + extra_header
        + dependency_block
        + index
        + payloads
    )
    return path


def make_asset(
    path: Path,
    mod_id: str,
    source: str,
    workshop_id: str = "",
) -> ModAsset:
    return ModAsset(
        id=mod_id,
        pack_name=path.name,
        display_name=path.stem,
        path=str(path.resolve(strict=False)),
        directory=str(path.parent.resolve(strict=False)),
        source=source,
        workshop_id=workshop_id,
        pack_type="mod",
    )
