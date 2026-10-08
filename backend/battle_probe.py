from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from .constants import SOURCE_WORKSHOP
from .models import ModAsset


MEMREADER_PLUS_WORKSHOP_ID = "3811098873"
MEMREADER_PLUS_PACK_NAME = "memreader_plus.pack"
BATTLE_PROBE_ENTRY_NAMES = (
    "script\\battle\\mod\\!wyccc_battle_probe.lua",
    "script\\wyccc_battle_probe\\probe.lua",
)
BATTLE_PROBE_SOURCE_ROOT = Path(__file__).parent / "resources" / "battle_probe"


def memreader_plus_enabled(assets: Mapping[str, ModAsset], active_ids: Sequence[str]) -> bool:
    """Require an enabled Plus Pack and its downloaded Workshop source."""
    for mod_id in active_ids:
        asset = assets.get(mod_id)
        if asset is None or asset.workshop_id != MEMREADER_PLUS_WORKSHOP_ID:
            continue
        if asset.pack_name.casefold() != MEMREADER_PLUS_PACK_NAME:
            continue
        if SOURCE_WORKSHOP not in (asset.sources or [asset.source]):
            continue
        if not Path(asset.path).is_file():
            continue
        for source in (asset.path, *asset.alternate_paths):
            candidate = Path(source).resolve(strict=False)
            if MEMREADER_PLUS_WORKSHOP_ID in candidate.parts and candidate.is_file():
                return True
    return False


def battle_probe_payloads() -> list[tuple[str, bytes]]:
    return [
        (name, BATTLE_PROBE_SOURCE_ROOT.joinpath(*name.split("\\")).read_bytes())
        for name in BATTLE_PROBE_ENTRY_NAMES
    ]
