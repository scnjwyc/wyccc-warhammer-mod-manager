from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.api import API
from backend.launcher import launch_game
from backend.save_games import SaveGameService


class SaveGameTests(unittest.TestCase):
    def test_extracts_ordered_mod_pack_names_and_filters_vanilla_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            save_dir = Path(temporary)
            save = save_dir / "campaign.save"
            save.write_bytes(
                b"header\0data.pack\0first.pack\0FIRST.PACK\0folder\\second.pack\0tail"
            )
            service = SaveGameService(save_dir)

            result = service.pack_names("CAMPAIGN.SAVE", {"data.pack"})

        self.assertEqual(result["save"]["name"], "campaign.save")
        self.assertEqual(result["pack_names"], ["first.pack", "second.pack"])

    def test_extracts_length_prefixed_mod_pack_names_without_nul_terminators(self) -> None:
        def length_prefixed(name: bytes) -> bytes:
            return len(name).to_bytes(4, "little") + name

        with tempfile.TemporaryDirectory() as temporary:
            save_dir = Path(temporary)
            save = save_dir / "campaign.save"
            save.write_bytes(
                b"header\0ignored.pack\x1a\0\0\0"
                + length_prefixed(b"data.pack")
                + b"\x1a\0\0\0"
                + length_prefixed(b"first.pack")
                + b"\x1a\0\0\0"
                + length_prefixed(b"SECOND.PACK")
                + b"\x1a\0\0\0"
                + length_prefixed(b"first.pack")
            )
            service = SaveGameService(save_dir)

            result = service.pack_names("campaign.save", {"data.pack"})

        self.assertEqual(result["pack_names"], ["first.pack", "SECOND.PACK"])

    def test_lists_only_save_files_newest_first_and_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            save_dir = Path(temporary)
            older = save_dir / "older.save"
            newer = save_dir / "newer.save"
            older.write_bytes(b"old")
            newer.write_bytes(b"new")
            (save_dir / "notes.txt").write_text("ignore", encoding="utf-8")
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))
            service = SaveGameService(save_dir)

            self.assertEqual([item["name"] for item in service.list()], ["newer.save", "older.save"])
            self.assertEqual(service.latest()["name"], "newer.save")
            self.assertEqual(service.require("OLDER.SAVE")["name"], "older.save")
            with self.assertRaisesRegex(ValueError, "无效"):
                service.require("../older.save")

    def test_launcher_passes_campaign_load_command_before_mod_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "game"
            game.mkdir()
            executable = game / "Warhammer3.exe"
            executable.write_bytes(b"")
            mod_list = game / "used_mods.txt"
            mod_list.write_text("", encoding="utf-8")
            with (
                patch("backend.launcher.is_game_running", return_value=False),
                patch(
                    "backend.launcher.subprocess.Popen",
                    return_value=SimpleNamespace(pid=42),
                ) as popen,
            ):
                result = launch_game(str(game), str(mod_list), "campaign 1.save")

        self.assertEqual(
            popen.call_args.args[0],
            [
                str(executable),
                "game_startup_mode",
                "campaign_load",
                "campaign 1.save",
                ";",
                "used_mods.txt;",
            ],
        )
        self.assertIn('"campaign 1.save"', result["argument"])

    def test_continue_rpc_uses_the_newest_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_dir = root / "saves"
            save_dir.mkdir()
            save = save_dir / "latest.save"
            save.write_bytes(b"save")
            api = API(root / "state")
            api.save_games = SaveGameService(save_dir)
            with patch.object(
                api,
                "_launch_game",
                return_value={"save": {"name": "latest.save"}},
            ) as launch:
                response = api.call("continue_game", [["a"], "token"])
                listed = api.call("list_save_games")

        self.assertTrue(response["ok"])
        launch.assert_called_once_with(["a"], "token", "latest.save")
        self.assertEqual(listed["data"]["items"][0]["name"], "latest.save")

    def test_save_mod_rpc_returns_save_metadata_and_pack_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_dir = root / "saves"
            save_dir.mkdir()
            (save_dir / "campaign.save").write_bytes(b"\0data.pack\0example.pack\0")
            api = API(root / "state")
            api.save_games = SaveGameService(save_dir)
            with patch.object(api, "_vanilla_pack_names", return_value={"data.pack"}):
                response = api.call("get_save_mods", ["campaign.save"])

        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["save"]["name"], "campaign.save")
        self.assertEqual(response["data"]["pack_names"], ["example.pack"])


if __name__ == "__main__":
    unittest.main()
