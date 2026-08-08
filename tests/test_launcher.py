from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.launcher import is_game_running, launch_game, terminate_game


class LauncherProcessTests(unittest.TestCase):
    def test_windows_detection_uses_a_supplied_process_name(self) -> None:
        with (
            patch("backend.launcher.os.name", "nt"),
            patch(
                "backend.launcher._windows_process_entries",
                return_value=[(42, "Three_Kingdoms.exe")],
            ),
            patch(
                "backend.launcher._windows_executable_path",
                return_value=r"C:\\Games\\Three Kingdoms\\Three_Kingdoms.exe",
            ),
        ):
            self.assertTrue(
                is_game_running(
                    r"C:\\Games\\Three Kingdoms\\Three_Kingdoms.exe",
                    process_name="Three_Kingdoms.exe",
                )
            )

    def test_windows_detection_matches_the_configured_game_executable(self) -> None:
        with (
            patch("backend.launcher.os.name", "nt"),
            patch(
                "backend.launcher._windows_process_entries",
                return_value=[(1, "steam.exe"), (42, "WARHAMMER3.EXE")],
            ) as snapshot,
            patch(
                "backend.launcher._windows_executable_path",
                return_value=r"C:\Games\Warhammer III\Warhammer3.exe",
            ) as executable_path,
            patch("backend.launcher.subprocess.run") as run,
        ):
            self.assertTrue(
                is_game_running(r"C:\Games\Warhammer III\Warhammer3.exe")
            )

        snapshot.assert_called_once_with()
        executable_path.assert_called_once_with(42)
        run.assert_not_called()

    def test_same_named_process_from_another_directory_is_not_the_game(self) -> None:
        with (
            patch("backend.launcher.os.name", "nt"),
            patch(
                "backend.launcher._windows_process_entries",
                return_value=[(42, "Warhammer3.exe")],
            ),
            patch(
                "backend.launcher._windows_executable_path",
                return_value=r"C:\Tools\Warhammer3.exe",
            ),
            patch("backend.launcher._windows_process_has_visible_window") as visible,
        ):
            self.assertFalse(
                is_game_running(r"C:\Games\Warhammer III\Warhammer3.exe")
            )

        visible.assert_not_called()

    def test_unreadable_process_path_uses_a_visible_window_as_the_safe_fallback(self) -> None:
        with (
            patch("backend.launcher.os.name", "nt"),
            patch(
                "backend.launcher._windows_process_entries",
                return_value=[(42, "Warhammer3.exe")],
            ),
            patch("backend.launcher._windows_executable_path", return_value=""),
            patch(
                "backend.launcher._windows_process_has_visible_window",
                side_effect=[False, True],
            ),
        ):
            self.assertFalse(is_game_running(r"C:\Games\Warhammer III\Warhammer3.exe"))
            self.assertTrue(is_game_running(r"C:\Games\Warhammer III\Warhammer3.exe"))

    def test_windows_detection_fails_closed_when_snapshot_is_unavailable(self) -> None:
        with (
            patch("backend.launcher.os.name", "nt"),
            patch("backend.launcher._windows_process_entries", side_effect=OSError("denied")),
        ):
            self.assertFalse(is_game_running())

    def test_windows_termination_only_targets_the_configured_game_executable(self) -> None:
        with (
            patch("backend.launcher.os.name", "nt"),
            patch(
                "backend.launcher._windows_process_entries",
                return_value=[(41, "Warhammer3.exe"), (42, "Warhammer3.exe")],
            ),
            patch(
                "backend.launcher._windows_executable_path",
                side_effect=[r"C:\\Tools\\Warhammer3.exe", r"C:\\Games\\Warhammer III\\Warhammer3.exe"],
            ),
            patch("backend.launcher._windows_terminate_process") as terminate,
        ):
            result = terminate_game(r"C:\Games\Warhammer III\Warhammer3.exe")

        self.assertEqual(result, {"process_ids": [42]})
        terminate.assert_called_once_with(42)

    def test_launch_reports_the_selected_game_executable_when_it_is_already_running(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Three Kingdoms"
            game.mkdir()
            (game / "Three_Kingdoms.exe").write_bytes(b"")
            mod_list = root / "user.script.txt"
            mod_list.write_text("", encoding="utf-8")
            with patch("backend.launcher.is_game_running", return_value=True):
                with self.assertRaisesRegex(ValueError, "Three_Kingdoms\\.exe 已经在运行"):
                    launch_game(
                        str(game),
                        str(mod_list),
                        executable_name="Three_Kingdoms.exe",
                        process_name="Three_Kingdoms.exe",
                    )

    def test_launch_passes_the_selected_steam_app_id_to_the_game(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War Rome II"
            game.mkdir()
            (game / "Rome2.exe").write_bytes(b"")
            mod_list = game / "used_mods.txt"
            mod_list.write_text('mod "example.pack";\n', encoding="utf-8")

            with (
                patch("backend.launcher.is_game_running", return_value=False),
                patch("backend.launcher.subprocess.Popen") as popen,
            ):
                popen.return_value.pid = 42
                result = launch_game(
                    str(game),
                    str(mod_list),
                    executable_name="Rome2.exe",
                    process_name="Rome2.exe",
                    app_id="214950",
                )

        environment = popen.call_args.kwargs["env"]
        self.assertEqual(environment["SteamAppId"], "214950")
        self.assertEqual(environment["SteamGameId"], "214950")
        self.assertEqual(result["pid"], 42)

    def test_launches_rome_remastered_official_manager_without_pack_list_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "Total War ROME REMASTERED"
            launcher = game / "launcher" / "launcher.exe"
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b"")
            (game / "Total War ROME REMASTERED.exe").write_bytes(b"")

            with (
                patch("backend.launcher.is_game_running", return_value=False),
                patch("backend.launcher.subprocess.Popen") as popen,
            ):
                popen.return_value.pid = 84
                result = launch_game(
                    str(game),
                    "",
                    executable_name="Total War ROME REMASTERED.exe",
                    process_name="Total War ROME REMASTERED.exe",
                    app_id="885970",
                    launch_executable_name="launcher/launcher.exe",
                    uses_mod_list=False,
                )

        self.assertEqual(popen.call_args.args[0], [str(launcher)])
        self.assertEqual(result["arguments"], [])
        self.assertEqual(result["executable"], str(launcher))


if __name__ == "__main__":
    unittest.main()
