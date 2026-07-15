from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.constants import PACK_TYPE_MOD, PACK_TYPE_MOVIE
from backend.models import GamePaths
from backend.scanner import ModScanner, read_pack_dependencies, read_pack_type
from tests.helpers import write_pack


class OfflineWorkshopMetadata:
    def __init__(self) -> None:
        self.requested_ids: list[str] = []
        self.requested_language = ""

    def get_many(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict]:
        self.requested_ids = list(workshop_ids)
        self.requested_language = interface_language
        return {}

    def refresh(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict]:
        raise AssertionError(f"network refresh must stay disabled: {workshop_ids}")


class CachedWorkshopMetadata(OfflineWorkshopMetadata):
    def get_many(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict]:
        self.requested_ids = list(workshop_ids)
        self.requested_language = interface_language
        return {
            workshop_id: {
                "creator_id": "76561198000000000",
                "created_at": 1_690_000_000_000,
                "updated_at": 1_700_000_000_000,
            }
            for workshop_id in workshop_ids
        }


class TitledWorkshopMetadata(OfflineWorkshopMetadata):
    def get_many(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict]:
        self.requested_ids = list(workshop_ids)
        self.requested_language = interface_language
        titles = {
            "101": "A display title",
            "102": "Z display title",
        }
        return {
            workshop_id: {"title": titles[workshop_id]}
            for workshop_id in workshop_ids
        }


class DependencyWorkshopMetadata(OfflineWorkshopMetadata):
    def get_many(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict]:
        return {
            "101": {
                "required_workshop_items": [
                    {"workshop_id": "102", "title": "Installed requirement"},
                    {"workshop_id": "999", "title": "Missing requirement"},
                ]
            },
            "102": {"required_workshop_items": []},
        }


class ScannerTests(unittest.TestCase):
    def test_reads_pfh5_mod_and_movie_pack_types(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normal = write_pack(root / "normal.pack", byte_mask=0)
            movie = write_pack(root / "movie.pack", byte_mask=4)
            invalid = root / "invalid.pack"
            invalid.write_bytes(b"not-a-pfh-pack")

            self.assertEqual(read_pack_type(normal), PACK_TYPE_MOD)
            self.assertEqual(read_pack_type(movie), PACK_TYPE_MOVIE)
            self.assertEqual(read_pack_type(invalid), "unknown")

    def test_scans_sources_excludes_manifest_and_keeps_all_workshop_packs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            modding = data / "modding"
            merged = game / "merged"
            workshop = root / "steamapps" / "workshop" / "content" / "1142710"
            workshop_item = workshop / "1234567890"

            write_pack(data / "data.pack")
            write_pack(data / "vanilla_extra.pack")
            write_pack(data / "local_mod.pack")
            write_pack(data / "movie_mod.pack", byte_mask=4)
            write_pack(modding / "development.pack")
            write_pack(merged / "merged_output.pack")
            write_pack(workshop_item / "first_workshop.pack")
            write_pack(workshop_item / "second_workshop.pack", byte_mask=4)
            (workshop_item / "preview.jpg").write_bytes(b"image fixture")
            (data / "manifest.txt").write_text(
                "data.pack\t0\nvanilla_extra.pack\t0\n",
                encoding="utf-8",
            )

            metadata = OfflineWorkshopMetadata()
            scanner = ModScanner(metadata)
            result = scanner.scan(
                GamePaths(
                    game_path=str(game),
                    data_path=str(data),
                    workshop_path=str(workshop),
                ),
                {
                    "scan_data": False,
                    "scan_modding": True,
                    "scan_workshop": False,
                    "scan_merged": True,
                    "fetch_workshop_metadata": False,
                    "language": "ru-RU",
                },
            )

            by_name = {mod.pack_name: mod for mod in result.mods}
            self.assertEqual(
                set(by_name),
                {
                    "local_mod.pack",
                    "movie_mod.pack",
                    "first_workshop.pack",
                    "second_workshop.pack",
                },
            )
            self.assertNotIn("data.pack", by_name)
            self.assertNotIn("vanilla_extra.pack", by_name)
            self.assertNotIn("development.pack", by_name)
            self.assertNotIn("merged_output.pack", by_name)
            self.assertEqual(by_name["local_mod.pack"].pack_type, PACK_TYPE_MOD)
            self.assertEqual(by_name["movie_mod.pack"].pack_type, PACK_TYPE_MOVIE)

            workshop_assets = [mod for mod in result.mods if mod.workshop_id]
            self.assertEqual(len(workshop_assets), 2)
            self.assertEqual({mod.workshop_id for mod in workshop_assets}, {"1234567890"})
            self.assertEqual(len({mod.id for mod in workshop_assets}), 2)
            self.assertTrue(all(mod.preview_path for mod in workshop_assets))
            self.assertEqual(metadata.requested_ids, ["1234567890"])
            self.assertEqual(metadata.requested_language, "ru-RU")

            for asset in result.to_dict()["mods"]:
                self.assertNotIn("supported_languages", asset)
                self.assertNotIn("file_stats", asset)
                self.assertNotIn("dependencies", asset)

    def test_reads_pack_and_workshop_dependencies_and_marks_only_missing_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "game" / "data"
            workshop = root / "workshop" / "1142710"
            (data / "manifest.txt").parent.mkdir(parents=True)
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "base.pack")
            dependent = write_pack(
                data / "dependent.pack",
                dependencies=["data.pack", "base.pack", "missing.pack"],
            )
            write_pack(workshop / "101" / "first.pack")
            write_pack(workshop / "102" / "requirement.pack")

            result = ModScanner(DependencyWorkshopMetadata()).scan(
                GamePaths(data_path=str(data), workshop_path=str(workshop)),
                {"language": "zh-CN", "check_outdated_mods": False},
            )
            dependency_names = read_pack_dependencies(dependent)

        self.assertEqual(
            dependency_names,
            ["data.pack", "base.pack", "missing.pack"],
        )
        by_name = {mod.pack_name: mod for mod in result.mods}
        self.assertEqual(
            by_name["dependent.pack"].missing_dependencies,
            [{"kind": "pack", "id": "missing.pack", "name": "missing.pack"}],
        )
        self.assertEqual(
            by_name["first.pack"].missing_dependencies,
            [{"kind": "workshop", "id": "999", "name": "Missing requirement"}],
        )
        self.assertEqual(by_name["requirement.pack"].missing_dependencies, [])
        self.assertEqual(by_name["dependent.pack"].warnings[0]["severity"], "error")

    def test_workshop_metadata_overrides_created_time_and_exposes_author_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workshop = root / "workshop" / "1142710"
            write_pack(workshop / "123" / "example.pack")

            result = ModScanner(CachedWorkshopMetadata()).scan(
                GamePaths(workshop_path=str(workshop)),
                {
                    "scan_data": False,
                    "scan_modding": False,
                    "scan_workshop": True,
                    "scan_merged": False,
                    "fetch_workshop_metadata": False,
                },
            )

            self.assertEqual(len(result.mods), 1)
            self.assertEqual(result.mods[0].creator_id, "76561198000000000")
            self.assertEqual(result.mods[0].created_at, 1_690_000_000_000)
            self.assertEqual(result.mods[0].updated_at, 1_700_000_000_000)

    def test_mod_library_is_sorted_by_pack_file_name_not_display_title(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workshop = root / "workshop" / "1142710"
            write_pack(workshop / "101" / "zeta.pack")
            write_pack(workshop / "102" / "Alpha.pack")

            result = ModScanner(TitledWorkshopMetadata()).scan(
                GamePaths(workshop_path=str(workshop)),
                {
                    "scan_data": False,
                    "scan_modding": False,
                    "scan_workshop": True,
                    "scan_merged": False,
                    "fetch_workshop_metadata": False,
                },
            )

        self.assertEqual(
            [mod.pack_name for mod in result.mods],
            ["Alpha.pack", "zeta.pack"],
        )
        self.assertEqual(
            [mod.display_name for mod in result.mods],
            ["Z display title", "A display title"],
        )

    def test_exact_data_workshop_duplicate_is_merged_with_both_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            workshop = root / "workshop" / "1142710"
            data_pack = write_pack(data / "same_name.pack")
            workshop_pack = write_pack(workshop / "123" / "same_name.pack")
            (workshop_pack.parent / "preview.jpg").write_bytes(b"preview fixture")

            result = ModScanner(OfflineWorkshopMetadata()).scan(
                GamePaths(
                    game_path=str(game),
                    data_path=str(data),
                    workshop_path=str(workshop),
                ),
                {
                    "scan_data": True,
                    "scan_modding": False,
                    "scan_workshop": True,
                    "scan_merged": False,
                    "fetch_workshop_metadata": True,
                },
                refresh_workshop=False,
            )

            matches = [mod for mod in result.mods if mod.pack_name == "same_name.pack"]
            self.assertEqual(len(matches), 1)
            merged = matches[0]
            self.assertEqual(merged.source, "data")
            self.assertEqual(merged.sources, ["data", "workshop"])
            self.assertTrue(merged.cross_source_duplicate)
            self.assertEqual(merged.path, str(data_pack.resolve()))
            self.assertEqual(merged.workshop_id, "123")
            self.assertEqual(merged.preview_path, str((workshop_pack.parent / "preview.jpg").resolve()))
            self.assertIn("steam:123:same_name.pack", merged.alternate_ids)
            self.assertIn(str(workshop_pack.resolve()), merged.alternate_paths)

    def test_outdated_check_uses_the_requested_game_older_than_mod_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "game" / "data"
            mod_path = write_pack(data / "newer_mod.pack")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            mod_time = mod_path.stat().st_mtime_ns // 1_000_000

            with patch("backend.scanner.game_last_updated_at", return_value=mod_time - 1):
                checked = ModScanner(OfflineWorkshopMetadata()).scan(
                    GamePaths(game_path=str(data.parent), data_path=str(data)),
                    {
                        "scan_data": True,
                        "scan_modding": False,
                        "scan_workshop": False,
                        "scan_merged": False,
                        "check_outdated_mods": True,
                    },
                )
            self.assertEqual(checked.game_updated_at, mod_time - 1)
            self.assertEqual(checked.mods[0].warnings[0]["code"], "mod_newer_than_game")

            unchecked = ModScanner(OfflineWorkshopMetadata()).scan(
                GamePaths(game_path=str(data.parent), data_path=str(data)),
                {
                    "scan_data": True,
                    "scan_modding": False,
                    "scan_workshop": False,
                    "scan_merged": False,
                    "check_outdated_mods": False,
                },
            )
            self.assertEqual(unchecked.mods[0].warnings, [])


if __name__ == "__main__":
    unittest.main()
