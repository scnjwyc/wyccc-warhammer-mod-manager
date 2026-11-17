from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Any

from .games import DEFAULT_GAME_ID, get_game_definition


_PROFILE_LINE_RE = re.compile(
    r"^mod_lookup_key://(?P<checksum>[0-9a-f]{32})@"
    r"(?:steam_workshop:(?P<app_id>\d+)/(?P<workshop_id>\d+)@(?P<updated_at>\d+)/"
    r"(?P<workshop_path>.+\.pack)|game_dir:(?P<local_path>.+\.pack))$",
    re.IGNORECASE,
)


def parse_mod_profile_text(content: str, game_id: str = DEFAULT_GAME_ID) -> dict[str, Any]:
    if len(content.encode("utf-8")) > 5 * 1024 * 1024:
        raise ValueError("share.tooLarge")
    references: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    has_header = False
    for raw_line in content.lstrip("\ufeff").splitlines():
        line = raw_line.strip()
        if line == "# TW Mod Profile":
            has_header = True
        if not line or line.startswith("#"):
            continue
        matched = _PROFILE_LINE_RE.fullmatch(line)
        if not matched:
            raise ValueError("share.invalidOfficial")
        workshop_id = matched.group("workshop_id") or ""
        if workshop_id and matched.group("app_id") != get_game_definition(game_id).app_id:
            raise ValueError("share.wrongGame")
        pack_path = urllib.parse.unquote(matched.group("workshop_path") or matched.group("local_path"))
        path = PurePosixPath(pack_path.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or ":" in pack_path:
            raise ValueError("share.invalidOfficial")
        reference = {"pack_name": path.name, "checksum": matched.group("checksum").lower()}
        if workshop_id:
            reference.update(workshop_id=workshop_id)
        else:
            source = "data" if path.parts[0].casefold() == "data" else "local"
            reference.update(source=source, relative_path=path.as_posix())
        key = (workshop_id, pack_path.casefold())
        if key not in seen:
            seen.add(key)
            references.append(reference)
    if not references and not has_header:
        raise ValueError("share.invalidOfficial")
    return {"references": references, "unrecognized_lines": []}


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

    parsed = parse_mod_profile_text(content)
    return {
        "profile": {
            "name": path.stem,
            "path": str(path.resolve(strict=False)),
            "modified_at": int(stat.st_mtime * 1000),
            "size": stat.st_size,
        },
        "name": path.stem,
        "path": str(path.resolve(strict=False)),
        **parsed,
    }
