from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.api import API
from backend.launcher import launch_game
from backend.save_games import SaveGameService, default_save_directory


class SaveGameTests(unittest.TestCase):
    def test_default_save_directory_is_scoped_to_the_selected_game(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_data = Path(temporary) / "AppData"
            three_kingdoms_directory = (
                app_data / "The Creative Assembly" / "ThreeKingdoms" / "save_games"
            )
            warhammer_directory = (
                app_data / "The Creative Assembly" / "Warhammer3" / "save_games"
            )
            with patch.dict(os.environ, {"APPDATA": str(app_data)}, clear=True):
                self.assertEqual(default_save_directory("three_kingdoms"), three_kingdoms_directory)
                self.assertEqual(default_save_directory("warhammer3"), warhammer_directory)
                self.assertEqual(default_save_directory("unknown"), warhammer_directory)
                self.assertEqual(
                    SaveGameService(game_id="three_kingdoms").save_directory,
                    three_kingdoms_directory,
                )

            custom_directory = Path(temporary) / "custom_saves"
            with patch.dict(
                os.environ,
                {"APPDATA": str(app_data), "WYCCC_MM_SAVE_DIR": str(custom_directory)},
                clear=True,
            ):
                self.assertEqual(
                    default_save_directory("three_kingdoms"),
                    custom_directory.resolve(strict=False),
                )

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

    def test_api_switches_all_save_operations_to_the_selected_game(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            warhammer_saves = root / "warhammer_saves"
            three_kingdoms_saves = root / "three_kingdoms_saves"
            warhammer_saves.mkdir()
            three_kingdoms_saves.mkdir()
            (warhammer_saves / "warhammer.save").write_bytes(b"warhammer")
            (three_kingdoms_saves / "three.save").write_bytes(
                b"\0data.pack\0three_mod.pack\0"
            )

            def resolve_save_directory(game_id=None):
                return three_kingdoms_saves if game_id == "three_kingdoms" else warhammer_saves

            with patch("backend.save_games.default_save_directory", side_effect=resolve_save_directory):
                api = API(root / "state")
                with patch.object(api, "_sync_runtime_services"):
                    switched = api.call("save_settings", [{"selected_game": "three_kingdoms"}])
                listed = api.call("list_save_games")
                with patch.object(api, "_vanilla_pack_names", return_value={"data.pack"}):
                    save_mods = api.call("get_save_mods", ["three.save"])
                with patch.object(api, "_launch_game", return_value={"save": {"name": "three.save"}}) as launch:
                    continued = api.call("continue_game", [["a"], "token"])
                with patch.object(api, "_sync_runtime_services"):
                    switched_back = api.call("save_settings", [{"selected_game": "warhammer3"}])
                listed_back = api.call("list_save_games")

        self.assertTrue(switched["ok"])
        self.assertEqual(listed["data"]["directory"], str(three_kingdoms_saves.resolve()))
        self.assertEqual(listed["data"]["items"][0]["name"], "three.save")
        self.assertTrue(save_mods["ok"])
        self.assertEqual(save_mods["data"]["pack_names"], ["three_mod.pack"])
        self.assertTrue(continued["ok"])
        launch.assert_called_once_with(["a"], "token", "three.save")
        self.assertTrue(switched_back["ok"])
        self.assertEqual(listed_back["data"]["directory"], str(warhammer_saves.resolve()))
        self.assertEqual(listed_back["data"]["items"][0]["name"], "warhammer.save")


if __name__ == "__main__":
    unittest.main()
