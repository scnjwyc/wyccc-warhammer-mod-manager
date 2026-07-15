from __future__ import annotations

import struct
from pathlib import Path

from backend.models import ModAsset


def write_pack(
    path: Path,
    byte_mask: int = 0,
    dependencies: list[str] | None = None,
) -> Path:
    """Create the smallest header fixture needed by the PFH5 reader."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dependency_block = b"".join(
        value.encode("utf-8") + b"\0" for value in (dependencies or [])
    )
    path.write_bytes(
        b"PFH5"
        + struct.pack("<I", byte_mask)
        + struct.pack("<I", 0)
        + struct.pack("<I", len(dependency_block))
        + struct.pack("<I", 0)
        + struct.pack("<I", 0)
        + struct.pack("<I", 0)
        + dependency_block
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
