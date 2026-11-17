"""Share-code adapters: one module per format, no cross-adapter imports."""

from .base import (
    ShareCodeAdapter,
    ShareCodeContext,
    ShareCodeParseResult,
    ShareMod,
    normalize_share_text,
)
from .official import OFFICIAL_FORMAT_ID, OfficialModLookupKeyAdapter
from .wh3_legacy import Wh3LegacyShareCodeAdapter
from .wmm import PREFIX, LEGACY_PREFIXES, WmmShareCodeAdapter

__all__ = [
    "LEGACY_PREFIXES",
    "OFFICIAL_FORMAT_ID",
    "PREFIX",
    "OfficialModLookupKeyAdapter",
    "ShareCodeAdapter",
    "ShareCodeContext",
    "ShareCodeParseResult",
    "ShareMod",
    "Wh3LegacyShareCodeAdapter",
    "WmmShareCodeAdapter",
    "normalize_share_text",
]
