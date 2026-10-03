from __future__ import annotations

import tempfile
import time
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from tests.helpers import write_pack


class WorkshopRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        game = root / "game"
        data = game / "data"
        data.mkdir(parents=True)
        (game / "Warhammer3.exe").write_bytes(b"")
        workshop = root / "workshop"
        for workshop_id in ("111", "222"):
            write_pack(workshop / workshop_id / f"{workshop_id}.pack", 3)
        self.api = API(root / "state")
        self.addCleanup(self.api.close)
        self.api.settings_service.save({"game_path": str(game), "workshop_path": str(workshop),
            "fetch_workshop_metadata": False, "live_mod_detection": False, "language": "zh-CN"})
        self.api._scan_mods(False)

    def test_startup_refresh_reuses_fresh_cache_and_queries_only_the_missing_item(self):
        now = int(time.time() * 1000)
        self.api.workshop_service.store.save({"schema_version": 7, "authors": {}, "items": {"111": {
            "title": "Cached MOD", "fetched_at": now, "updated_at": 100,
            "dependencies_fetched_at": now, "dependencies_language": "schinese",
            "localized": {"schinese": {"source": "steamworks", "failed": True, "last_error_at": 0,
                "title": "", "description": "", "fetched_at": now, "source_updated_at": 100}},
        }}})
        with patch.object(self.api.workshop_service, "refresh") as remote:
            result = self.api.call("refresh_workshop_metadata", [None, "warhammer3", True])
        self.assertTrue(result["ok"], result)
        remote.assert_called_once_with(["222"], "zh-CN", app_id=1142710, steamworks_first=True)

    def test_refresh_targets_only_the_new_item_and_returns_the_complete_local_list(self):
        def refresh(ids, language, *, app_id, steamworks_first):
            self.assertEqual(ids, ["222"])
            self.assertEqual(language, "zh-CN")
            self.assertEqual(app_id, 1142710)
            self.assertTrue(steamworks_first)
            self.api.workshop_service.store.save({"items": {"222": {"title": "New MOD title"}}, "authors": {}})
        with patch.object(self.api.workshop_service, "refresh", side_effect=refresh) as remote:
            result = self.api.call("refresh_workshop_metadata", [["222", "222", "999"], "warhammer3"])
        self.assertTrue(result["ok"], result)
        remote.assert_called_once()
        self.assertEqual({mod["workshop_id"] for mod in result["data"]["mods"]}, {"111", "222"})
        self.assertEqual(next(mod for mod in result["data"]["mods"] if mod["workshop_id"] == "222")["display_name"],
            "New MOD title")

    def test_slow_metadata_does_not_block_a_local_scan(self):
        entered, release = threading.Event(), threading.Event()
        def refresh(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
        with patch.object(self.api.workshop_service, "refresh", side_effect=refresh), ThreadPoolExecutor(2) as pool:
            request = pool.submit(self.api.call, "refresh_workshop_metadata", [["222"], "warhammer3"])
            try:
                self.assertTrue(entered.wait(1), request.result() if request.done() else "refresh did not start")
                local = pool.submit(self.api._scan_mods, False).result(timeout=1)
                self.assertEqual(len(local["mods"]), 2)
            finally:
                release.set()
            self.assertTrue(request.result()["ok"])

    def test_changed_game_discards_the_old_metadata_result(self):
        def refresh(*args, **kwargs):
            with self.api._context_lock:
                self.api._game_context_revision += 1
        with patch.object(self.api.workshop_service, "refresh", side_effect=refresh):
            result = self.api.call("refresh_workshop_metadata", [["222"], "warhammer3"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["data"]["discarded"])


if __name__ == "__main__":
    unittest.main()
