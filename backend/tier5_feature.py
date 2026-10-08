"""The marker is installed, while the five-tier base MOD must be enabled."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from .constants import TIER5_BASE_WORKSHOP_ID, TIER5_FEATURE_PACK_NAME
from .models import ModAsset


def tier5_feature_status(assets: Mapping[str, ModAsset], active_ids: Sequence[str]) -> dict:
    subscribed = any(
        asset.pack_name.casefold() == TIER5_FEATURE_PACK_NAME.casefold()
        and Path(asset.path).is_file() for asset in assets.values()
    )
    base_enabled = any(
        (asset := assets.get(mod_id)) is not None and Path(asset.path).is_file()
        and (asset.workshop_id == TIER5_BASE_WORKSHOP_ID
             or asset.pack_name.casefold().lstrip("!") == "minortierfivefourall.pack")
        for mod_id in active_ids
    )
    return {"subscribed": subscribed, "base_enabled": base_enabled,
            "available": subscribed and base_enabled}
