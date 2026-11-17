from __future__ import annotations

from typing import Sequence

from ..games import DEFAULT_GAME_ID
from .base import ShareCodeContext, ShareCodeParseResult, ShareMod, normalize_share_text

LEGACY_PROJECT_METADATA = "legacy_workshop_project"
_REQUIRES_WARHAMMER3 = "旧版分享码仅支持战锤3，请切换游戏或使用包含游戏信息的新版分享码"


class Wh3LegacyShareCodeAdapter:
    """WH3-Mod-Manager legacy project text: ``workshop_id[;load_order]|...``."""

    format_id = "wh3-legacy"
    can_serialize = True

    def can_handle(self, value: str) -> bool:
        # Fallback format: any non-empty text no earlier adapter claimed.
        return bool(normalize_share_text(value).strip())

    def deserialize(self, value: str, context: ShareCodeContext) -> ShareCodeParseResult:
        segments = [
            segment
            for segment in normalize_share_text(value).splitlines()
            if segment.strip() and not segment.strip().startswith(("#", "//"))
        ]
        mods: list[ShareMod] = []
        for index, token in enumerate(
            part.strip() for line in segments for part in line.split("|")
        ):
            if not token:
                continue
            workshop_id, _, load_order = token.partition(";")
            workshop_id = workshop_id.strip()
            # Only numeric Workshop IDs are legacy project entries; anything else
            # (comments, pasted prose, official launcher lines) is not a MOD.
            if not workshop_id.isdigit():
                continue
            mods.append(
                ShareMod(
                    workshop_id=workshop_id,
                    position=int(load_order) if load_order.strip().isdigit() else index,
                    metadata={LEGACY_PROJECT_METADATA: "1"},
                )
            )
        if not mods:
            raise ValueError("未识别到可导入的 MOD")
        if context.game_id != DEFAULT_GAME_ID:
            raise ValueError(_REQUIRES_WARHAMMER3)
        mods.sort(key=lambda mod: mod.position)
        return ShareCodeParseResult(format_id=self.format_id, mods=mods, warnings=[])

    def serialize(self, mods: Sequence[ShareMod], context: ShareCodeContext) -> str:
        if context.game_id != DEFAULT_GAME_ID:
            raise ValueError(_REQUIRES_WARHAMMER3)
        if not mods:
            raise ValueError("旧版分享码不能包含空 MOD 列表")
        tokens: list[str] = []
        for mod in sorted(mods, key=lambda item: item.position):
            workshop_id = str(mod.workshop_id or "").strip()
            if not workshop_id.isdigit():
                raise ValueError("旧版分享码需要数字 Workshop ID，本地 MOD 无法导出")
            tokens.append(f"{workshop_id};{mod.position}")
        return "|".join(tokens)
