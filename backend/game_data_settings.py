from __future__ import annotations

import math
from typing import Any

from .constants import (
    UNIT_MODEL_MULTIPLIER_MAX,
    UNIT_MODEL_MULTIPLIER_MIN,
    UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MAX,
    UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MIN,
    UNIT_RECRUITMENT_CAPACITY_UNLIMITED,
)


SINGLE_ENTITY_UNIT_MODE_SCALE = "scale"
SINGLE_ENTITY_UNIT_MODE_HEALTH = "health"


def normalize_unit_scale_multiplier(value: Any) -> int:
    """Normalize persisted and RPC unit-scale values to a supported integer."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 1.0
    if not math.isfinite(numeric):
        numeric = 1.0
    clamped = max(
        UNIT_MODEL_MULTIPLIER_MIN,
        min(UNIT_MODEL_MULTIPLIER_MAX, numeric),
    )
    return int(math.floor(clamped + 0.5))


def normalize_unit_recruitment_capacity_multiplier(value: Any) -> int:
    """Normalize the 1-5 multiplier plus the persisted unlimited sentinel."""
    if isinstance(value, str) and value.strip().casefold() in {"unlimited", "infinite", "∞"}:
        return UNIT_RECRUITMENT_CAPACITY_UNLIMITED
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 1.0
    if not math.isfinite(numeric) or numeric < 0:
        numeric = 1.0
    if math.isclose(numeric, 0.0, rel_tol=0.0, abs_tol=1e-9):
        return UNIT_RECRUITMENT_CAPACITY_UNLIMITED
    clamped = max(
        UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MIN,
        min(UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MAX, numeric),
    )
    return int(math.floor(clamped + 0.5))


def normalize_single_entity_unit_mode(value: Any) -> str:
    """Normalize the one-model regular monster adjustment rule."""
    return (
        SINGLE_ENTITY_UNIT_MODE_HEALTH
        if str(value or "").strip().casefold() == SINGLE_ENTITY_UNIT_MODE_HEALTH
        else SINGLE_ENTITY_UNIT_MODE_SCALE
    )
