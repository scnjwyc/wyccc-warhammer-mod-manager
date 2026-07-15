from __future__ import annotations

from typing import Final


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


def default_mod_types() -> list[dict[str, object]]:
    return [dict(item) for item in DEFAULT_MOD_TYPES]
