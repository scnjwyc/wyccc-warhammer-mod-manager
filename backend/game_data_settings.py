from __future__ import annotations

import math
from typing import Any

from .constants import UNIT_MODEL_MULTIPLIER_MAX, UNIT_MODEL_MULTIPLIER_MIN


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


def normalize_single_entity_unit_mode(value: Any) -> str:
    """Normalize the one-model regular monster adjustment rule."""
    return (
        SINGLE_ENTITY_UNIT_MODE_HEALTH
        if str(value or "").strip().casefold() == SINGLE_ENTITY_UNIT_MODE_HEALTH
        else SINGLE_ENTITY_UNIT_MODE_SCALE
    )
