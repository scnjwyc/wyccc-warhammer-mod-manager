from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.api import API
from tests.helpers import write_pack


class ThumbnailTests(unittest.TestCase):
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
