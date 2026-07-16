from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.file_operations import build_delete_preview, execute_delete_preview
from backend.models import GamePaths
from tests.helpers import make_asset, write_pack


class ModFileOperationTests(unittest.TestCase):
    def test_dual_source_preview_targets_only_data_and_revalidates_before_recycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "game" / "data"
            workshop = root / "workshop"
            data_pack = write_pack(data / "same.pack")
            workshop_pack = write_pack(workshop / "123" / "same.pack")
            asset = make_asset(data_pack, "local:data:same", "data", "123")
            asset.sources = ["data", "workshop"]
            asset.alternate_paths = [str(workshop_pack)]
            paths = GamePaths(data_path=str(data), workshop_path=str(workshop))

            preview = build_delete_preview([asset], paths)
            self.assertEqual(preview["data_count"], 1)
            self.assertEqual(preview["workshop_count"], 0)
            self.assertEqual(Path(preview["targets"][0]["path"]), data_pack.resolve())

            recycled: list[Path] = []
            result = execute_delete_preview(
                preview,
                paths,
                recycle=lambda path: recycled.append(path),
            )

        self.assertEqual(recycled, [data_pack.resolve()])
        self.assertEqual(result["deleted_count"], 1)

    def test_unsubscribe_deletes_exact_workshop_folder_and_rescans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            data = game / "data"
            workshop = root / "workshop"
            game.mkdir()
            data.mkdir()
            (game / "Warhammer3.exe").write_bytes(b"")
            pack = write_pack(workshop / "123" / "remove.pack")
            api = API(root / "state")
            api.settings_service.save(
                {"game_path": str(game), "workshop_path": str(workshop), "fetch_workshop_metadata": False}
            )
            asset = make_asset(pack, "steam:123:remove.pack", "workshop", "123")
            api._assets = {asset.id: asset}
            with (
                patch("backend.api.is_game_running", return_value=False),
                patch(
                    "backend.api.perform_workshop_operation",
                    return_value={"operation": "unsubscribe", "workshop_id": "123", "accepted": True},
                ),
                patch.object(api.workshop_service, "get_many", return_value={}),
                patch.object(api.workshop_service, "ensure_dependencies", return_value={}),
            ):
                response = api.call("unsubscribe_workshop_mods", [[asset.id]])

            self.assertTrue(response["ok"])
            self.assertFalse((workshop / "123").exists())
            self.assertEqual(response["data"]["scan"]["mods"], [])


if __name__ == "__main__":
    unittest.main()
