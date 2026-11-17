from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from .games import DEFAULT_GAME_ID, get_game_definition
from .models import ModAsset
from .share_adapters import (
    OfficialModLookupKeyAdapter,
    ShareCodeAdapter,
    ShareCodeContext,
    ShareCodeParseResult,
    ShareMod,
    Wh3LegacyShareCodeAdapter,
    WmmShareCodeAdapter,
    normalize_share_text,
)
from .share_adapters.wh3_legacy import LEGACY_PROJECT_METADATA

DEFAULT_EXPORT_FORMAT_ID = "wmm-v2"
MAX_SHARE_CODE_CHARS = 5 * 1024 * 1024
_OVERSIZED = "分享码文本过长，请只粘贴分享码内容"
_EMPTY = "请粘贴分享码后再导入"
_UNRECOGNIZED = "未识别到可导入的 MOD"


class ShareCodeService:
    """Selects an adapter, enforces shared limits, and returns format-neutral results."""

    def __init__(self, adapters: Sequence[ShareCodeAdapter]) -> None:
        if not adapters:
            raise ValueError("至少需要注册一个分享码适配器")
        self._adapters = tuple(adapters)
        self._by_format_id = {adapter.format_id: adapter for adapter in self._adapters}
        if len(self._by_format_id) != len(self._adapters):
            raise ValueError("分享码适配器格式标识重复")

    @property
    def format_ids(self) -> tuple[str, ...]:
        return tuple(adapter.format_id for adapter in self._adapters)

    def deserialize(self, value: str, context: ShareCodeContext) -> ShareCodeParseResult:
        text = normalize_share_text(value).strip()
        if not text:
            raise ValueError(_EMPTY)
        if len(text) > MAX_SHARE_CODE_CHARS:
            raise ValueError(_OVERSIZED)
        for adapter in self._adapters:
            if adapter.can_handle(text):
                result = adapter.deserialize(text, context)
                if result.format_id:
                    return result
                return replace(result, format_id=adapter.format_id)
        raise ValueError(_UNRECOGNIZED)

    def serialize(
        self,
        mods: Sequence[ShareMod],
        context: ShareCodeContext,
        format_id: str = DEFAULT_EXPORT_FORMAT_ID,
    ) -> str:
        adapter = self._by_format_id.get(format_id)
        if adapter is None:
            raise ValueError(f"不支持的分享码格式：{format_id}")
        if not adapter.can_serialize:
            raise ValueError(f"分享码格式 {format_id} 不支持导出")
        return adapter.serialize(mods, context)

    def references(self, value: str, context: ShareCodeContext) -> list[dict[str, Any]]:
        """Compatibility bridge: deserialize straight into the legacy reference dicts."""
        return share_references(self.deserialize(value, context))


def default_share_code_service() -> ShareCodeService:
    """Registration order decides recognition; legacy text is the last-resort fallback."""
    return ShareCodeService(
        [WmmShareCodeAdapter(), OfficialModLookupKeyAdapter(), Wh3LegacyShareCodeAdapter()]
    )


def share_context(game_id: str = DEFAULT_GAME_ID, app_id: str | None = None) -> ShareCodeContext:
    """Build a context without silently rewriting an unknown game ID to Warhammer III."""
    raw_game_id = str(game_id or "").strip()
    definition = get_game_definition(raw_game_id)
    known = definition.id == raw_game_id
    return ShareCodeContext(
        game_id=definition.id if known else raw_game_id,
        app_id=str(app_id or (definition.app_id if known else "")),
    )


def share_mods_from_assets(mods: Sequence[ModAsset]) -> list[ShareMod]:
    return [
        ShareMod(
            workshop_id=str(mod.workshop_id or "").strip() or None,
            pack_name=mod.pack_name,
            source=str(mod.source or "").strip() or None,
            mod_id=mod.id,
            position=position,
        )
        for position, mod in enumerate(mods)
    ]


def share_references(result: ShareCodeParseResult) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for mod in result.mods:
        reference: dict[str, Any] = {
            "workshop_id": mod.workshop_id or "",
            "pack_name": mod.pack_name,
            "source": mod.source or "",
            "position": mod.position,
        }
        if mod.mod_id:
            reference["id"] = mod.mod_id
        if mod.metadata.get(LEGACY_PROJECT_METADATA):
            reference[LEGACY_PROJECT_METADATA] = True
        references.append(reference)
    return references
