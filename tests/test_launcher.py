from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.launcher import is_game_running


class LauncherProcessTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
