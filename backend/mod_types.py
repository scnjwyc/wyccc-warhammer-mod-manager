from __future__ import annotations

from typing import Final, Iterable


DEFAULT_MOD_TYPE_ID: Final = "unknown"

DEFAULT_MOD_TYPES: Final = (
    {"id": "language", "name": "语言包", "built_in": True},
    {"id": "ui", "name": "UI", "built_in": True},
    {"id": "unit", "name": "单位", "built_in": True},
    {"id": "feature", "name": "功能", "built_in": True},
    {"id": "overhaul", "name": "大修", "built_in": True},
    {"id": "visual", "name": "美化", "built_in": True},
    {"id": DEFAULT_MOD_TYPE_ID, "name": "未知", "built_in": True},
)

DEFAULT_MOD_TYPE_IDS: Final = frozenset(item["id"] for item in DEFAULT_MOD_TYPES)
DEFAULT_MOD_TYPE_NAMES: Final = frozenset(item["name"].casefold() for item in DEFAULT_MOD_TYPES)

# Workshop exposes a smaller, fixed set of category tags than the launcher's
# MOD type list. Keep this mapping in the backend as the source of truth for
# requests that do not include an explicit category (for example, older
# clients opening the update dialog).
WORKSHOP_CATEGORY_BY_MOD_TYPE: Final = {
    "graphical": "graphical",
    "visual": "graphical",
    "campaign": "campaign",
    "unit": "units",
    "units": "units",
    "battle": "battle",
    "ui": "ui",
    "map": "maps",
    "maps": "maps",
    "overhaul": "overhaul",
    "compilation": "compilation",
    "cheat": "cheat",
}


def workshop_category_for_mod_types(type_ids: Iterable[object] | None) -> str:
    """Return the Workshop category represented by the first known MOD type."""

    for raw_type in type_ids or ():
        category = WORKSHOP_CATEGORY_BY_MOD_TYPE.get(str(raw_type or "").strip().casefold())
        if category:
            return category
    return "graphical"


def default_mod_types() -> list[dict[str, object]]:
    return [dict(item) for item in DEFAULT_MOD_TYPES]
