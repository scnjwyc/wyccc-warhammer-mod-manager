from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.load_order import LoadOrderService
from backend.models import ScanResult
from backend.scanner import ModScanner
from tests.helpers import make_asset, write_pack


class ScanConflictAndPreviewTests(unittest.TestCase):
    def test_ambiguous_workshop_files_retain_identity_and_cannot_both_be_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = {
                "local": make_asset(write_pack(root / "data" / "same.pack"), "local", "data"),
                "one": make_asset(write_pack(root / "111" / "same.pack"), "one", "workshop", "111"),
                "two": make_asset(write_pack(root / "222" / "same.pack"), "two", "workshop", "222"),
            }
            ModScanner._merge_data_workshop_duplicates(assets)
            self.assertEqual(len(assets), 3)
            self.assertEqual(assets["local"].workshop_id, "")
            self.assertEqual(assets["one"].workshop_id, "111")
            self.assertEqual(assets["two"].workshop_id, "222")
            for asset in assets.values():
                self.assertFalse(asset.alternate_ids)
                self.assertIn("duplicate_pack_name", [w["code"] for w in asset.warnings])
            with self.assertRaisesRegex(ValueError, "同名 Pack"):
                LoadOrderService(root / "backups").build_plan(str(root), str(root / "data"), assets, ["one", "two"])

    def test_cover_discovery_enumerates_directory_once_and_refreshes_each_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number in range(100):
                write_pack(root / f"mod{number}.pack")
            cover = root / "MOD0.PNG"
            cover.write_bytes(b"image-fixture")
            scanner = ModScanner(Mock())
            original = Path.iterdir
            visits = []

            def enumerate_files(path):
                visits.append(path)
                return original(path)

            for workshop in (False, True):
                with self.subTest(workshop=workshop), patch.object(Path, "iterdir", enumerate_files):
                    visits.clear()
                    assets = {}
                    if workshop:
                        scanner._scan_workshop_item(root, "123", assets, ScanResult())
                    else:
                        scanner._scan_pack_directory(root, "data", assets, ScanResult())
                    self.assertEqual(visits, [root])
                    self.assertEqual(len(assets), 100)
                    by_name = {a.pack_name: a for a in assets.values()}
                    self.assertEqual(by_name["mod0.pack"].preview_path, str(cover.resolve()))
                    self.assertEqual(by_name["mod1.pack"].preview_path, str(cover.resolve()) if workshop else "")
            new_cover = root / "mod1.webp"
            new_cover.write_bytes(b"updated-fixture")
            assets = {}
            scanner._scan_pack_directory(root, "data", assets, ScanResult())
            self.assertEqual(next(a for a in assets.values() if a.pack_name == "mod1.pack").preview_path, str(new_cover.resolve()))
