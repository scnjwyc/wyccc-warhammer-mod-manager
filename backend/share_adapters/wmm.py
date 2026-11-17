from __future__ import annotations

import base64
import json
import zlib
from typing import Any, Sequence

from ..games import DEFAULT_GAME_ID, game_definitions
from .base import ShareCodeContext, ShareCodeParseResult, ShareMod

PREFIX = "WMM1"
LEGACY_PREFIXES = ("WWM1", "WWMM1")
_ALL_PREFIXES = (PREFIX, *LEGACY_PREFIXES)
_KNOWN_GAME_IDS = frozenset(game.id for game in game_definitions())


def _optional_text(value: Any) -> str | None:
    text = str(value if value is not None else "").strip()
    return text or None


class WmmShareCodeAdapter:
    """Built-in WMM1 share code: compressed JSON payload with CRC32 and Base64."""

    format_id = "wmm-v2"
    can_serialize = True

    def can_handle(self, value: str) -> bool:
        text = value.strip()
        return any(text.startswith(f"{prefix}-") for prefix in _ALL_PREFIXES)

    def deserialize(self, value: str, context: ShareCodeContext) -> ShareCodeParseResult:
        text = value.strip()
        matched_prefix = next(
            (prefix for prefix in _ALL_PREFIXES if text.startswith(f"{prefix}-")),
            "",
        )
        if not matched_prefix:
            raise ValueError("分享码格式错误")
        parts = text.split("-", 2)
        if len(parts) != 3:
            raise ValueError("分享码格式错误")
        _, checksum_text, encoded = parts
        padding = "=" * (-len(encoded) % 4)
        try:
            compressed = base64.urlsafe_b64decode(encoded + padding)
            expected = int(checksum_text, 16)
            if zlib.crc32(compressed) & 0xFFFFFFFF != expected:
                raise ValueError("分享码校验失败")
            payload = json.loads(zlib.decompress(compressed).decode("utf-8"))
        except (ValueError, TypeError, json.JSONDecodeError, zlib.error) as exc:
            raise ValueError(f"无法解析分享码：{exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("分享码内容无效")
        version = payload.get("schema_version")
        shared_game = payload.get("game")
        if version == 1 and shared_game == "wh3":
            shared_game = DEFAULT_GAME_ID
        elif (
            version != 2
            or not isinstance(shared_game, str)
            or shared_game not in _KNOWN_GAME_IDS
        ):
            raise ValueError("不支持的分享码版本或游戏")
        if shared_game != context.game_id:
            raise ValueError("分享码所属游戏与当前游戏不一致，请切换到对应游戏后导入")
        entries = payload.get("mods", [])
        if not isinstance(entries, list):
            raise ValueError("分享码内容无效")
        mods = [
            ShareMod(
                workshop_id=_optional_text(item.get("workshop_id")),
                pack_name=str(item.get("pack_name") or ""),
                source=_optional_text(item.get("source")),
                mod_id=_optional_text(item.get("id")),
                position=position,
            )
            for position, item in enumerate(
                entry for entry in entries if isinstance(entry, dict)
            )
        ]
        return ShareCodeParseResult(format_id=self.format_id, mods=mods, warnings=[])

    def serialize(self, mods: Sequence[ShareMod], context: ShareCodeContext) -> str:
        if context.game_id not in _KNOWN_GAME_IDS:
            raise ValueError("不支持的分享码版本或游戏")
        payload = {
            "schema_version": 2,
            "game": context.game_id,
            "mods": [
                {
                    "id": mod.mod_id or "",
                    "workshop_id": mod.workshop_id or "",
                    "pack_name": mod.pack_name,
                    "source": mod.source or "",
                }
                for mod in mods
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressed = zlib.compress(raw, level=9)
        checksum = zlib.crc32(compressed) & 0xFFFFFFFF
        encoded = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        return f"{PREFIX}-{checksum:08X}-{encoded}"
