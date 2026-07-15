from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def default_save_directory() -> Path:
    override = (
        os.environ.get("WYCCC_MM_SAVE_DIR", "").strip()
        or os.environ.get("WYCCC_WM_SAVE_DIR", "").strip()
        or os.environ.get("WYCCC_WMM_SAVE_DIR", "").strip()
    )
    if override:
        return Path(override).expanduser().resolve(strict=False)
    app_data = os.environ.get("APPDATA", "").strip()
    root = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
    return root / "The Creative Assembly" / "Warhammer3" / "save_games"


class SaveGameService:
    def __init__(self, save_directory: Path | None = None):
        self.save_directory = Path(save_directory or default_save_directory())

    def list(self) -> list[dict[str, Any]]:
        if not self.save_directory.is_dir():
            return []
        saves: list[dict[str, Any]] = []
        try:
            candidates = list(self.save_directory.iterdir())
        except OSError:
            return []
        for path in candidates:
            if not path.is_file() or path.suffix.casefold() != ".save":
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            saves.append(
                {
                    "name": path.name,
                    "path": str(path.resolve(strict=False)),
                    "modified_at": int(stat.st_mtime * 1000),
                    "size": stat.st_size,
                }
            )
        return sorted(
            saves,
            key=lambda item: (-int(item["modified_at"]), str(item["name"]).casefold()),
        )

    def require(self, save_name: str) -> dict[str, Any]:
        normalized = str(save_name or "").strip()
        if not normalized or Path(normalized).name != normalized:
            raise ValueError("存档名称无效")
        match = next(
            (item for item in self.list() if item["name"].casefold() == normalized.casefold()),
            None,
        )
        if match is None:
            raise ValueError(f"找不到存档：{normalized}")
        return match

    def latest(self) -> dict[str, Any]:
        saves = self.list()
        if not saves:
            raise ValueError("没有可用于继续游戏的战役存档")
        return saves[0]
