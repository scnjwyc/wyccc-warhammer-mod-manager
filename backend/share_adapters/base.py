from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class ShareCodeContext:
    """Current game facts a share-code adapter may use for format validation."""

    game_id: str
    app_id: str


@dataclass(frozen=True)
class ShareMod:
    """Format-neutral MOD identity shared by every adapter."""

    workshop_id: str | None = None
    pack_name: str = ""
    source: str | None = None
    mod_id: str | None = None
    position: int = 0
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ShareCodeParseResult:
    format_id: str
    mods: list[ShareMod]
    warnings: list[str] = field(default_factory=list)


class ShareCodeAdapter(Protocol):
    """Fixed bidirectional contract implemented by one file per format."""

    format_id: str
    can_serialize: bool

    def can_handle(self, value: str) -> bool:
        """Return whether this adapter owns the input text; never raise user-input errors."""
        ...

    def deserialize(self, value: str, context: ShareCodeContext) -> ShareCodeParseResult:
        """Turn share-code text into format-neutral MOD entries."""
        ...

    def serialize(self, mods: Sequence[ShareMod], context: ShareCodeContext) -> str:
        """Turn format-neutral MOD entries into this adapter's share code."""
        ...


# Invisible junk clipboard pastes and UTF-8-BOM profile files carry around: a BOM
# ahead of a header comment must not turn that comment into an unknown MOD line.
_INVISIBLE_CHARS = "\ufeff\u200b\u2060"


def normalize_share_text(value: str) -> str:
    """Drop BOM/zero-width characters and normalize line endings for pasted text."""
    text = str(value or "")
    for char in _INVISIBLE_CHARS:
        text = text.replace(char, "")
    return text.replace("\r\n", "\n").replace("\r", "\n")
