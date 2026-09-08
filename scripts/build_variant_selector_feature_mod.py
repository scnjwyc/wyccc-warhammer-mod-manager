"""Build the Workshop feature marker; does not package or deploy the manager."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.constants import VARIANT_SELECTOR_FEATURE_PACK_NAME  # noqa: E402
from backend.start_options import PackEntry, write_pfh5_pack  # noqa: E402


def build() -> Path:
    directory = ROOT / "mods" / "wyccc_variant_selector_patch"
    payload = (directory / "feature.json").read_bytes()
    metadata = json.loads(payload)
    if metadata["pack_name"] != VARIANT_SELECTOR_FEATURE_PACK_NAME:
        raise ValueError("Feature metadata and manager Pack name disagree")
    return write_pfh5_pack(
        directory / VARIANT_SELECTOR_FEATURE_PACK_NAME,
        [PackEntry("wyccc\\features\\variant_selector_patch.json", payload)],
    )


if __name__ == "__main__":
    print(build())
