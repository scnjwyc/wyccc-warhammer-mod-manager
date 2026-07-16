from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

from .constants import WH3_APP_ID


_PROFILE_LINE_RE = re.compile(
    r"^mod_lookup_key://.*?@steam_workshop:(?P<app_id>\d+)/"
    r"(?P<workshop_id>\d+)@[^/]+/(?P<pack_path>.+\.pack)\s*$",
    re.IGNORECASE,
)


def default_mod_profile_directory() -> Path:
    app_data = os.environ.get("APPDATA", "").strip()
    root = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
    return root / "The Creative Assembly" / "Warhammer3" / "modprofiles"


def existing_profile_directory() -> Path:
    candidate = default_mod_profile_directory()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def parse_mod_profile(profile_path: str | Path) -> dict[str, Any]:
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

    references: list[dict[str, str]] = []
    unrecognized_lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        matched = _PROFILE_LINE_RE.match(line)
        if not matched or matched.group("app_id") != WH3_APP_ID:
            unrecognized_lines.append(line)
            continue
        workshop_id = matched.group("workshop_id")
        decoded_path = urllib.parse.unquote(matched.group("pack_path"))
        pack_name = Path(decoded_path.replace("\\", "/")).name.strip()
        if not pack_name.casefold().endswith(".pack"):
            unrecognized_lines.append(line)
            continue
        key = (workshop_id, pack_name.casefold())
        if key in seen:
            continue
        seen.add(key)
        references.append({"workshop_id": workshop_id, "pack_name": pack_name})

    if not references:
        raise ValueError("配置中未识别到 Warhammer III 工坊 MOD")
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
        "unrecognized_lines": unrecognized_lines,
    }
