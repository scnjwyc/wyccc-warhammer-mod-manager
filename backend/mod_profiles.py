from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .share_adapters import OFFICIAL_FORMAT_ID, ShareCodeContext
from .share_code import ShareCodeService, default_share_code_service, share_context


def default_mod_profile_directory() -> Path:
    app_data = os.environ.get("APPDATA", "").strip()
    root = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
    return root / "The Creative Assembly" / "Warhammer3" / "modprofiles"


def existing_profile_directory() -> Path:
    candidate = default_mod_profile_directory()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def parse_mod_profile(
    profile_path: str | Path,
    context: ShareCodeContext | None = None,
    service: ShareCodeService | None = None,
) -> dict[str, Any]:
    """Validate a .twmods file, then let the official share-code adapter parse its text.

    File-level checks (extension, existence, size, encoding) live here; every
    line-level rule stays in ``backend/share_adapters/official.py``.
    """
    path = Path(profile_path).expanduser()
    if path.suffix.casefold() != ".twmods" or not path.is_file():
        raise ValueError("请选择有效的官方启动器 .twmods 配置")
    try:
        stat = path.stat()
        if stat.st_size > 5 * 1024 * 1024:
            raise ValueError("官方启动器配置文件过大")
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ValueError(f"无法读取官方启动器配置：{exc}") from exc

    active_context = context or share_context()
    try:
        parsed = (service or default_share_code_service()).deserialize(
            content, active_context
        )
    except ValueError as exc:
        raise ValueError("配置中未识别到 Warhammer III 工坊 MOD") from exc
    if parsed.format_id != OFFICIAL_FORMAT_ID:
        raise ValueError("配置中未识别到 Warhammer III 工坊 MOD")

    references = [
        {"workshop_id": mod.workshop_id, "pack_name": mod.pack_name}
        for mod in parsed.mods
    ]
    return {
        "profile": {
            "name": path.stem,
            "path": str(path.resolve(strict=False)),
            "modified_at": int(stat.st_mtime * 1000),
            "size": stat.st_size,
        },
        "name": path.stem,
        "path": str(path.resolve(strict=False)),
        "references": references,
        "unrecognized_lines": list(parsed.warnings),
    }
