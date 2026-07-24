from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


_PACK_NAME_RE = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]{1,260}\.pack$', re.IGNORECASE)
_PACK_SUFFIX = b".pack"
_MAX_PACK_TOKEN_BYTES = 1024
_LENGTH_PREFIX_BYTES = 4
_SAVE_PROFILE_DIRECTORIES = {
    "warhammer3": "Warhammer3",
    "three_kingdoms": "ThreeKingdoms",
}


def _has_legacy_pack_terminator(content: bytes, token_end: int) -> bool:
    return token_end < len(content) and content[token_end] == 0


def _has_matching_length_prefix(content: bytes, token_start: int, token_end: int) -> bool:
    if token_start < _LENGTH_PREFIX_BYTES:
        return False
    length_prefix = content[token_start - _LENGTH_PREFIX_BYTES:token_start]
    return int.from_bytes(length_prefix, "little") == token_end - token_start


def default_save_directory(game_id: str | None = None) -> Path:
    override = (
        os.environ.get("WYCCC_MM_SAVE_DIR", "").strip()
        or os.environ.get("WYCCC_WM_SAVE_DIR", "").strip()
        or os.environ.get("WYCCC_WMM_SAVE_DIR", "").strip()
    )
    if override:
        return Path(override).expanduser().resolve(strict=False)
    app_data = os.environ.get("APPDATA", "").strip()
    root = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
    profile_directory = _SAVE_PROFILE_DIRECTORIES.get(
        str(game_id or "").strip(),
        _SAVE_PROFILE_DIRECTORIES["warhammer3"],
    )
    return root / "The Creative Assembly" / profile_directory / "save_games"


class SaveGameService:
    def __init__(
        self,
        save_directory: Path | None = None,
        game_id: str | None = None,
    ):
        self.game_id = str(game_id or "warhammer3").strip()
        self.save_directory = Path(
            save_directory
            if save_directory is not None
            else default_save_directory(self.game_id)
        )

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

    def pack_names(
        self,
        save_name: str,
        excluded_pack_names: set[str] | None = None,
    ) -> dict[str, Any]:
        save = self.require(save_name)
        save_path = Path(save["path"])
        try:
            content = save_path.read_bytes()
        except OSError as exc:
            raise ValueError(f"无法读取存档：{exc}") from exc

        excluded = {str(name).casefold() for name in (excluded_pack_names or set())}
        lowered = content.lower()
        pack_names: list[str] = []
        seen: set[str] = set()
        cursor = 0
        while True:
            marker = lowered.find(_PACK_SUFFIX, cursor)
            if marker < 0:
                break
            token_end = marker + len(b".pack")
            token_start = content.rfind(
                b"\0",
                max(0, marker - _MAX_PACK_TOKEN_BYTES),
                marker,
            ) + 1
            raw_token = content[token_start:token_end]
            cursor = token_end + 1
            if not (
                _has_legacy_pack_terminator(content, token_end)
                or _has_matching_length_prefix(content, token_start, token_end)
            ):
                continue
            token = raw_token.decode("utf-8", errors="replace").strip()
            pack_name = Path(token.replace("\\", "/")).name
            key = pack_name.casefold()
            if not _PACK_NAME_RE.fullmatch(pack_name) or key in excluded or key in seen:
                continue
            seen.add(key)
            pack_names.append(pack_name)
        return {"save": save, "pack_names": pack_names}
