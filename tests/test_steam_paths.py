from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.models import GamePaths
from backend.steam_paths import discover_game_paths, discover_wh3_paths, game_last_updated_at, parse_vdf


class SteamVdfTests(unittest.TestCase):
    def test_discovers_three_kingdoms_from_secondary_steam_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steam_root = root / "Steam"
            library_root = root / "Library One"
            steamapps = library_root / "steamapps"
            install_name = "Total War THREE KINGDOMS Test"
            game_path = steamapps / "common" / install_name
            workshop_path = steamapps / "workshop" / "content" / "779340"

            (steam_root / "steamapps").mkdir(parents=True)
            game_path.mkdir(parents=True)
            (game_path / "data").mkdir()
            (game_path / "Three_Kingdoms.exe").write_bytes(b"")
            workshop_path.mkdir(parents=True)

            escaped_library = str(library_root).replace("\\", "\\\\")
            (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
                (
                    '"libraryfolders"\n{\n'
                    f'  "1" {{ "path" "{escaped_library}" '
                    '"apps" { "779340" "1" } }\n'
                    '}\n'
                ),
                encoding="utf-8",
            )
            (steamapps / "appmanifest_779340.acf").write_text(
                (
                    '"AppState"\n{\n'
                    '  "appid" "779340"\n'
                    f'  "installdir" "{install_name}"\n'
                    '}\n'
                ),
                encoding="utf-8",
            )

            with patch(
                "backend.steam_paths.candidate_steam_roots",
                return_value=[steam_root],
            ):
                discovered = discover_game_paths("three_kingdoms")

        self.assertEqual(discovered.game_id, "three_kingdoms")
        self.assertEqual(Path(discovered.game_path), game_path.resolve())
        self.assertEqual(Path(discovered.executable_path).name, "Three_Kingdoms.exe")
        self.assertEqual(Path(discovered.workshop_path), workshop_path.resolve())

    def test_parse_modern_libraryfolders_vdf(self) -> None:
        parsed = parse_vdf(
            r'''
            "libraryfolders"
            {
                "0"
                {
                    "path" "C:\\Program Files (x86)\\Steam"
                    "apps" { "1142710" "90123" }
                }
                "1"
                {
                    "path" "D:\\SteamLibrary"
                    "apps" { "294100" "456" }
                }
            }
            '''
        )

        folders = parsed["libraryfolders"]
        self.assertEqual(folders["0"]["path"], r"C:\Program Files (x86)\Steam")
        self.assertEqual(folders["0"]["apps"]["1142710"], "90123")
        self.assertEqual(folders["1"]["path"], r"D:\SteamLibrary")

    def test_parse_vdf_rejects_unclosed_object(self) -> None:
        with self.assertRaises(ValueError):
            parse_vdf('"libraryfolders" { "0" { "path" "D:\\\\Steam" }')

    def test_discovers_wh3_from_secondary_steam_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            steam_root = root / "Steam"
            library_root = root / "Library One"
            steamapps = library_root / "steamapps"
            install_name = "Total War WARHAMMER III Test"
            game_path = steamapps / "common" / install_name
            workshop_path = steamapps / "workshop" / "content" / "1142710"

            (steam_root / "steamapps").mkdir(parents=True)
            game_path.mkdir(parents=True)
            (game_path / "data").mkdir()
            (game_path / "Warhammer3.exe").write_bytes(b"")
            workshop_path.mkdir(parents=True)

            escaped_library = str(library_root).replace("\\", "\\\\")
            (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
                (
                    '"libraryfolders"\n{\n'
                    f'  "1" {{ "path" "{escaped_library}" '
                    '"apps" { "1142710" "1" } }\n'
                    '}\n'
                ),
                encoding="utf-8",
            )
            (steamapps / "appmanifest_1142710.acf").write_text(
                (
                    '"AppState"\n{\n'
                    '  "appid" "1142710"\n'
                    f'  "installdir" "{install_name}"\n'
                    '}\n'
                ),
                encoding="utf-8",
            )

            with patch(
                "backend.steam_paths.candidate_steam_roots",
                return_value=[steam_root],
            ):
                discovered = discover_wh3_paths()

            self.assertEqual(Path(discovered.game_path), game_path.resolve())
            self.assertEqual(Path(discovered.data_path), (game_path / "data").resolve())
            self.assertEqual(Path(discovered.workshop_path), workshop_path.resolve())
            self.assertEqual(Path(discovered.steam_library), library_root.resolve())
            self.assertEqual(discovered.detected_by, "steam-vdf")

    def test_game_last_updated_prefers_steam_manifest_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            steamapps = library / "steamapps"
            game = steamapps / "common" / "Total War WARHAMMER III"
            game.mkdir(parents=True)
            (steamapps / "appmanifest_1142710.acf").write_text(
                '"AppState" { "LastUpdated" "1700000000" }',
                encoding="utf-8",
            )

            updated_at = game_last_updated_at(
                GamePaths(game_path=str(game), steam_library=str(library))
            )

            self.assertEqual(updated_at, 1_700_000_000_000)


if __name__ == "__main__":
    unittest.main()
