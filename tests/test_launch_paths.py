from __future__ import annotations

import subprocess
import os
import unittest
from unittest.mock import call, patch

from backend.launch_paths import LaunchPathAliases


class LaunchPathAliasTests(unittest.TestCase):
    def test_existing_subst_is_reused_across_instances_and_rebinding_is_detected(self) -> None:
        root = r"D:\游戏\Warhammer"
        with (
            patch("backend.launch_paths._existing_drive_aliases", return_value={os.path.normcase(root): "X:\\"}) as mappings,
            patch("backend.launch_paths._used_drive_letters", return_value={"C", "D", "X"}),
            patch("backend.launch_paths.subprocess.run") as run,
        ):
            aliases = LaunchPathAliases()
            for manager in (aliases, LaunchPathAliases(), LaunchPathAliases()):
                self.assertEqual(manager.prepare(root, "").map_path(root), "X:\\")
            run.assert_not_called()
            mappings.return_value = {}
            self.assertEqual(aliases.prepare(root, "").map_path(root), "Z:\\")
            self.assertEqual(run.call_count, 1)

    def test_ascii_game_and_workshop_paths_are_not_mapped(self) -> None:
        aliases = LaunchPathAliases()

        with patch("backend.launch_paths.subprocess.run") as run:
            mapping = aliases.prepare(
                r"C:\Games\Total War WARHAMMER III",
                r"D:\SteamLibrary\steamapps\workshop\content\1142710",
            )

        self.assertEqual(
            mapping.map_path(r"C:\Games\Total War WARHAMMER III\data"),
            r"C:\Games\Total War WARHAMMER III\data",
        )
        self.assertEqual(
            mapping.map_path(r"D:\SteamLibrary\steamapps\workshop\content\1142710\123"),
            r"D:\SteamLibrary\steamapps\workshop\content\1142710\123",
        )
        run.assert_not_called()

    def test_non_ascii_game_and_workshop_paths_use_free_ascii_drives(self) -> None:
        aliases = LaunchPathAliases()

        with (
            patch("backend.launch_paths._used_drive_letters", return_value={"C", "D"}),
            patch("backend.launch_paths.subprocess.run") as run,
        ):
            mapping = aliases.prepare(
                r"D:\游戏\Total War WARHAMMER III",
                r"E:\创意工坊\steamapps\workshop\content\1142710",
            )

        self.assertEqual(
            mapping.map_path(r"D:\游戏\Total War WARHAMMER III"),
            "Z:\\",
        )
        self.assertEqual(
            mapping.map_path(r"D:\游戏\Total War WARHAMMER III\data"),
            r"Z:\data",
        )
        self.assertEqual(
            mapping.map_path(r"E:\创意工坊\steamapps\workshop\content\1142710\123"),
            r"Y:\123",
        )
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    ["subst.exe", "Z:", r"D:\游戏\Total War WARHAMMER III"],
                    check=True,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ),
                call(
                    ["subst.exe", "Y:", r"E:\创意工坊\steamapps\workshop\content\1142710"],
                    check=True,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
