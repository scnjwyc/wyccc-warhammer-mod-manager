from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.games import get_game_definition
from backend.models import ScanResult
from backend.share import export_share, parse_share
from backend.storage import StateRepository
from tests.helpers import make_asset, write_pack


class GameIsolationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.api = API(self.root / "state")
        self.addCleanup(self.api.close)
        detector = patch.object(self.api, "detect_game_running", return_value=False)
        self.detector = detector.start()
        self.addCleanup(detector.stop)

    def select_game(self, game_id="warhammer3", suffix=""):
        game = self.root / (game_id + suffix)
        (game / "data").mkdir(parents=True, exist_ok=True)
        (game / get_game_definition(game_id).executable_name).write_bytes(b"")
        workshop = self.root / (game_id + suffix + "_workshop")
        workshop.mkdir(exist_ok=True)
        response = self.api.call("save_settings", [{
            "selected_game": game_id, "game_path": str(game), "workshop_path": str(workshop),
            "live_mod_detection": False, "fetch_workshop_metadata": False,
        }])
        self.assertTrue(response["ok"], response)
        return game, workshop

    def test_old_scan_is_discarded_and_new_game_scan_is_queued(self):
        game_a, _ = self.select_game()
        first = make_asset(write_pack(game_a / "data" / "a.pack"), "old-game", "data")
        entered, release = threading.Event(), threading.Event()

        def scan(paths, *_):
            if paths.game_id == "warhammer3":
                entered.set()
                self.assertTrue(release.wait(5))
                return ScanResult(mods=[first])
            return ScanResult(mods=[make_asset(Path(paths.data_path) / "b.pack", "new-game", "data")])

        with patch.object(self.api.scanner, "scan", side_effect=scan), ThreadPoolExecutor(2) as pool:
            old = pool.submit(self.api.call, "scan_mods", [True])
            self.assertTrue(entered.wait(5))
            try:
                self.select_game("three_kingdoms")
                new = pool.submit(self.api.call, "scan_mods", [False])
            finally:
                release.set()
            self.assertTrue(old.result(5)["data"]["discarded"])
            result = new.result(5)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["game_id"], "three_kingdoms")
        self.assertEqual(list(self.api._assets), ["new-game"])
        self.assertFalse(self.api.state_repository.are_playsets_initialized("warhammer3"))

    def test_import_rejects_wrong_game_before_changing_playset_or_subscribing(self):
        game, _ = self.select_game("three_kingdoms")
        asset = make_asset(write_pack(game / "data" / "same.pack"), "same", "data")
        self.api._assets = {asset.id: asset}
        code = export_share([asset], "warhammer3")
        with patch("backend.api.subscribe_workshop_items") as subscribe:
            for method in ("preview_import_share", "import_share"):
                self.assertFalse(self.api.call(method, [code])["ok"])
            subscribe.assert_not_called()
        self.assertEqual(self.api.state_repository.get_enabled_order("three_kingdoms"), [])
        exported = self.api.call("export_share", [[asset.id]])["data"]["share_code"]
        self.assertEqual(parse_share(exported, "three_kingdoms")[0]["id"], asset.id)

    def test_data_sync_does_not_claim_another_game_or_installation(self):
        game_a, workshop_a = self.select_game()
        source_a = write_pack(workshop_a / "123" / "same.pack", entries=[("item", b"AAAA")])
        target_a = write_pack(game_a / "data" / "same.pack", entries=[("item", b"AAAA")])
        self.api._record_data_sync(make_asset(source_a, "a", "workshop", "123"), source_a, target_a)
        for game_id, suffix in (("three_kingdoms", ""), ("warhammer3", "_other")):
            with self.subTest(game_id=game_id):
                game_b, workshop_b = self.select_game(game_id, suffix)
                target_b = write_pack(game_b / "data" / "same.pack", entries=[("item", b"USER")])
                stat = target_a.stat()
                os.utime(target_b, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                original = target_b.read_bytes()
                source_b = write_pack(workshop_b / "456" / "same.pack", entries=[("item", b"NEW!")])
                asset = make_asset(source_b, "b", "workshop", "456")
                self.api._assets = {asset.id: asset}
                result = self.api.call("sync_workshop_to_data")
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["data"]["skipped_existing"], 1)
                self.assertEqual(target_b.read_bytes(), original)

    def test_mod_file_operations_are_rejected_before_any_side_effect_when_running(self):
        game, workshop = self.select_game()
        path = write_pack(workshop / "123" / "mod.pack")
        asset = make_asset(path, "mod", "workshop", "123")
        self.api._assets = {asset.id: asset}
        original = path.read_bytes()
        self.detector.return_value = True
        with patch.object(self.api, "_run_workshop_operation") as steam, \
                patch("backend.api.ensure_unit_data_patch") as generate, \
                patch("backend.api.launch_game") as launch:
            for method, args in (
                ("force_update_workshop_mod", ["mod"]), ("copy_mod_to_data", ["mod"]),
                ("sync_workshop_to_data", []), ("delete_mod_files", ["invalid-token"]),
                ("unsubscribe_workshop_mods", [["mod"]]), ("save_unit_data_edits", [{}]),
                ("launch_game", [["mod"]]),
            ):
                with self.subTest(method=method):
                    result = self.api.call(method, args)
                    self.assertFalse(result["ok"], result)
                    self.assertIn("游戏运行期间", result["error"]["message"])
            steam.assert_not_called()
            generate.assert_not_called()
            launch.assert_not_called()
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((game / "data" / "mod.pack").exists())

    def test_launch_and_copy_cannot_pass_the_running_check_together(self):
        game, workshop = self.select_game()
        asset = make_asset(write_pack(workshop / "123" / "mod.pack"), "mod", "workshop", "123")
        self.api._assets = {asset.id: asset}
        entered, release = threading.Event(), threading.Event()

        def launching(*_):
            entered.set()
            self.assertTrue(release.wait(5))
            self.detector.return_value = True
            return {"launched": True, "launch_plan": {"ordered_mod_ids": [asset.id]}}

        with patch.object(self.api, "_launch_game_when_patch_idle", side_effect=launching), ThreadPoolExecutor(2) as pool:
            launch = pool.submit(self.api.call, "launch_game", [[]])
            self.assertTrue(entered.wait(5))
            copy = pool.submit(self.api.call, "copy_mod_to_data", ["mod"])
            release.set()
            self.assertTrue(launch.result(5)["ok"])
            self.assertFalse(copy.result(5)["ok"])
        self.assertFalse((game / "data" / "mod.pack").exists())


class DataSyncMigrationTests(unittest.TestCase):
    def test_legacy_record_requires_exact_target_and_scoped_records_coexist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "state.db"
            target_a, target_b = str(root / "a" / "same.pack"), str(root / "b" / "same.pack")
            with sqlite3.connect(database) as connection:
                connection.execute("""CREATE TABLE data_sync_items (
                    pack_name TEXT PRIMARY KEY COLLATE NOCASE, workshop_id TEXT NOT NULL,
                    source_path TEXT NOT NULL, source_size INTEGER NOT NULL, source_mtime_ns INTEGER NOT NULL,
                    target_path TEXT NOT NULL, target_size INTEGER NOT NULL, target_mtime_ns INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL)""")
                connection.execute("INSERT INTO data_sync_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   ("same.pack", "123", "source", 4, 1, target_a, 4, 1, 1))
            connection.close()
            repo = StateRepository(database)
            self.assertIsNone(repo.get_data_sync_item("same.pack", game_id="three_kingdoms", target_path=target_b))
            self.assertEqual(repo.get_data_sync_item("same.pack", target_path=target_a)["workshop_id"], "123")
            for game_id, target, workshop in (("warhammer3", target_a, "123"), ("three_kingdoms", target_b, "456")):
                repo.save_data_sync_item("same.pack", workshop, "source", 4, 1, target, 4, 1, game_id=game_id)
            repo = StateRepository(database)
            repo.delete_data_sync_item("same.pack", game_id="warhammer3", target_path=target_a)
            self.assertEqual(repo.get_data_sync_item("SAME.pack", game_id="three_kingdoms", target_path=target_b)["workshop_id"], "456")
            self.assertIsNone(repo.get_data_sync_item("same.pack", target_path=target_a))
