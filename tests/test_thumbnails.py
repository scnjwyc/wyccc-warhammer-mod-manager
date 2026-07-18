from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.api import API
from tests.helpers import write_pack


class ThumbnailTests(unittest.TestCase):
    def test_palette_thumbnail_with_byte_transparency_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            (game / "data").mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            workshop = root / "workshop" / "1142710"
            item = workshop / "123"
            write_pack(item / "example.pack")
            palette = Image.new("P", (8, 8))
            palette.putpalette(
                [0, 0, 0, 155, 48, 48, 48, 155, 48] + [0] * (768 - 9)
            )
            palette.putdata(([0, 1, 2] * 22)[:64])
            palette.info["transparency"] = bytes((0, 128, 255))
            palette.save(item / "preview.png")

            api = API(root / "state")
            api.settings_service.save(
                {
                    "game_path": str(game),
                    "workshop_path": str(workshop),
                    "scan_data": False,
                    "scan_modding": False,
                    "scan_workshop": True,
                    "scan_merged": False,
                    "fetch_workshop_metadata": False,
                }
            )
            with patch.object(api.workshop_service, "ensure_dependencies", return_value={}):
                scan = api.call("scan_mods", [False])
            mod_id = scan["data"]["mods"][0]["id"]

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                thumbnails = api.call("get_mod_thumbnails", [[mod_id]])

            self.assertTrue(thumbnails["ok"])
            self.assertFalse(
                [
                    warning
                    for warning in caught
                    if "Palette images with Transparency expressed in bytes"
                    in str(warning.message)
                ]
            )

    def test_batch_thumbnail_rpc_returns_small_image_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            (game / "data").mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            workshop = root / "workshop" / "1142710"
            item = workshop / "123"
            write_pack(item / "example.pack")
            Image.new("RGB", (8, 8), (155, 48, 48)).save(item / "preview.png")

            api = API(root / "state")
            api.settings_service.save(
                {
                    "game_path": str(game),
                    "workshop_path": str(workshop),
                    "scan_data": False,
                    "scan_modding": False,
                    "scan_workshop": True,
                    "scan_merged": False,
                    "fetch_workshop_metadata": False,
                }
            )
            with patch.object(api.workshop_service, "ensure_dependencies", return_value={}):
                scan = api.call("scan_mods", [False])
            self.assertTrue(scan["ok"])
            mod_id = scan["data"]["mods"][0]["id"]

            thumbnails = api.call("get_mod_thumbnails", [[mod_id]])
            self.assertTrue(thumbnails["ok"])
            self.assertTrue(thumbnails["data"]["items"][mod_id].startswith("data:image/jpeg;base64,"))


if __name__ == "__main__":
    unittest.main()
