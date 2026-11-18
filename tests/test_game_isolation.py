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
from backend.constants import (
    GAME_DATA_FEATURE_WORKSHOP_ITEMS,
    INTERNAL_FEATURE_PACK_NAMES,
    INTERNAL_FEATURE_WORKSHOP_IDS,
    RUNTIME_OPTIONS_MARKER_ENTRY,
)
from backend.games import get_game_definition
from backend.models import ScanResult
from backend.share import export_share, parse_share
from backend.start_options import UNIT_DATA_PATCH_NAME
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
        asset = make_asset(write_pack(game / "data" / "same.pack"), "same", "workshop", "123")
        self.api._assets = {asset.id: asset}
        code = export_share([asset], "warhammer3")
        with patch("backend.api.subscribe_workshop_items") as subscribe:
            for method in ("preview_import_share", "import_share"):
                self.assertFalse(self.api.call(method, [code])["ok"])
            subscribe.assert_not_called()
        self.assertEqual(self.api.state_repository.get_enabled_order("three_kingdoms"), [])
        exported = self.api.call("export_share", [[asset.id]])["data"]["share_code"]
        self.assertEqual(parse_share(exported, "three_kingdoms")[0]["pack_name"], asset.pack_name)

    def test_share_import_does_not_apply_to_a_playset_switched_during_subscription(self):
        game, _ = self.select_game()
        self.api.state_repository.update_current_playset(["original-order"])
        another_playset = self.api.state_repository.create_playset("Other", ["other-order"])
        self.api.state_repository.switch_playset("default")
        asset = make_asset(write_pack(game / "downloaded.pack"), "example", "workshop", "123")

        def subscribe(workshop_ids, *, app_id):
            self.api.state_repository.switch_playset(another_playset["id"])
            return {"subscribed": workshop_ids}

        with patch("backend.api.subscribe_workshop_items", side_effect=subscribe) as subscribe_mock:
            imported = self.api.call("import_share", [export_share([asset])])

        self.assertTrue(imported["data"]["discarded"])
        self.assertEqual(self.api.state_repository.get_enabled_order(), ["other-order"])
        subscribe_mock.assert_called_once_with(["123"], app_id=1_142_710)

    def test_three_kingdoms_mod_with_warhammer_feature_name_is_visible_and_enableable(self):
        game, _ = self.select_game("three_kingdoms")
        pack_name = GAME_DATA_FEATURE_WORKSHOP_ITEMS["unit_size"]["pack_name"]
        write_pack(game / "data" / pack_name)

        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        mod = scanned["data"]["mods"][0]
        self.assertFalse(mod["hidden"])
        self.assertEqual(self.api._canonicalize_mod_ids([mod["id"]]), [mod["id"]])

    def test_three_kingdoms_can_unhide_mod_with_generated_pack_entry(self):
        game, _ = self.select_game("three_kingdoms")
        write_pack(
            game / "data" / "ordinary.pack",
            entries=[(RUNTIME_OPTIONS_MARKER_ENTRY, b"{}")],
        )
        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        mod = scanned["data"]["mods"][0]

        self.assertFalse(mod["hidden"])
        hidden = self.api.call("set_mod_hidden", [mod["id"], True])
        self.assertTrue(hidden["ok"], hidden)
        self.assertTrue(hidden["data"]["hidden"])
        self.assertTrue(self.api.call("scan_mods", [False])["data"]["mods"][0]["hidden"])
        unhidden = self.api.call("set_mod_hidden", [mod["id"], False])
        self.assertTrue(unhidden["ok"], unhidden)
        self.assertFalse(unhidden["data"]["hidden"])
        rescanned = self.api.call("scan_mods", [False])
        self.assertFalse(rescanned["data"]["mods"][0]["hidden"])
        self.assertEqual(self.api._canonicalize_mod_ids([mod["id"]]), [mod["id"]])

    def test_three_kingdoms_keeps_all_warhammer_pack_names_in_playsets_and_load_order(self):
        game, _ = self.select_game("three_kingdoms")
        for pack_name in INTERNAL_FEATURE_PACK_NAMES:
            write_pack(game / "data" / pack_name)
        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        mods = scanned["data"]["mods"]
        ids = [mod["id"] for mod in mods]
        self.assertEqual(len(mods), len(INTERNAL_FEATURE_PACK_NAMES))
        self.assertTrue(all(not mod["hidden"] for mod in mods))
        self.assertTrue(all(mod["display_name"] == Path(mod["pack_name"]).stem for mod in mods))

        default_id = scanned["data"]["current_playset"]["id"]
        created = self.api.call("create_playset", ["Three Kingdoms", ids])
        self.assertTrue(created["ok"], created)
        self.assertEqual(created["data"]["ordered_mod_ids"], ids)
        self.assertEqual(created["data"]["current_playset"]["hidden_mod_ids"], [])
        other_id = created["data"]["current_playset"]["id"]
        saved = self.api.call("save_load_order", [ids, scanned["data"]["order_token"]])
        self.assertTrue(saved["ok"], saved)
        self.assertEqual(saved["data"]["plan"]["ordered_mod_ids"], ids)
        self.assertEqual(self.api._unit_data_source_ids(), ids)
        rescanned = self.api.call("scan_mods", [False])
        self.assertEqual(rescanned["data"]["enabled_order"], ids)
        for playset_id in (default_id, other_id):
            switched = self.api.call("switch_playset", [playset_id])
            self.assertTrue(switched["ok"], switched)
            self.assertEqual(switched["data"]["current_playset"]["hidden_mod_ids"], [])
            self.assertTrue(all(not asset.hidden for asset in self.api._assets.values()))

    def test_three_kingdoms_ignores_warhammer_published_and_pending_workshop_ids(self):
        game, _ = self.select_game("three_kingdoms")
        path = write_pack(game / "data" / "ordinary.pack")
        for workshop_id in INTERNAL_FEATURE_WORKSHOP_IDS:
            with self.subTest(workshop_id=workshop_id):
                scanned = self.api.call("scan_mods", [False])
                self.assertTrue(scanned["ok"], scanned)
                mod_id = scanned["data"]["mods"][0]["id"]
                self.api.state_repository.set_published_workshop_id(mod_id, workshop_id)
                rescanned = self.api.call("scan_mods", [False])
                mod = rescanned["data"]["mods"][0]
                self.assertEqual(mod["path"], str(path.resolve()))
                self.assertFalse(mod["hidden"])
                self.assertEqual(self.api._canonicalize_mod_ids([mod_id]), [mod_id])
                pending_id = f"steam:{workshop_id}:missing.pack"
                self.assertEqual(self.api._canonicalize_mod_ids([pending_id]), [pending_id])

    def test_three_kingdoms_unhide_clears_old_hidden_flags_on_merged_workshop_copy(self):
        game, workshop = self.select_game("three_kingdoms")
        write_pack(game / "data" / "ordinary.pack")
        write_pack(workshop / "123" / "ordinary.pack")
        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        mod = scanned["data"]["mods"][0]
        self.assertTrue(mod["alternate_ids"])
        playset_id = scanned["data"]["current_playset"]["id"]
        for old_id in [mod["id"], *mod["alternate_ids"]]:
            self.api.state_repository.set_playset_mod_hidden(playset_id, old_id, True, "three_kingdoms")
        self.assertTrue(self.api.call("scan_mods", [False])["data"]["mods"][0]["hidden"])

        unhidden = self.api.call("set_mod_hidden", [mod["id"], False])
        self.assertTrue(unhidden["ok"], unhidden)
        self.assertFalse(unhidden["data"]["hidden"])
        rescanned = self.api.call("scan_mods", [False])
        self.assertFalse(rescanned["data"]["mods"][0]["hidden"])
        self.assertEqual(self.api.state_repository.get_playset_hidden_mod_ids(playset_id, "three_kingdoms"), set())

    def test_three_kingdoms_diagnostics_accepts_a_warhammer_runtime_pack_name(self):
        game, _ = self.select_game("three_kingdoms")
        write_pack(game / "data" / "!!!!wyccc_runtime_options.pack", byte_mask=3)
        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        mod_id = scanned["data"]["mods"][0]["id"]

        with patch("backend.diagnostics_api.GameProbe.run", return_value={"verdict": "ok"}) as probe:
            started = self.api.call("start_mod_diagnostics", [[mod_id], "bisect"])
            self.assertTrue(started["ok"], started)
            self.api.diagnostics.session._thread.join(5)
            self.assertEqual(self.api.diagnostics.session.status()["status"], "no_repro")
            self.assertTrue(probe.called)

    def test_three_kingdoms_legacy_launch_list_keeps_warhammer_runtime_pack_names(self):
        game, _ = self.select_game("three_kingdoms")
        names = ["!!!!wyccc_runtime_options.pack", "ordinary.pack"]
        self.api.diagnostics.launches.save({"version": 1, "games": {"three_kingdoms": {
            "game_path": str(game.resolve()), "started_at": 123,
            "packs": [{"pack_name": name} for name in names],
        }}})

        history = self.api.call("get_last_launch_mods")
        self.assertTrue(history["ok"], history)
        self.assertEqual([mod["pack_name"] for mod in history["data"]["mods"]], names)

    def test_three_kingdoms_launch_loads_a_visible_generated_unit_patch_once(self):
        game, _ = self.select_game("three_kingdoms")
        source = write_pack(
            self.root / "generated" / UNIT_DATA_PATCH_NAME,
            entries=[("db\\land_units_tables\\!!!!wyccc_unit_data_v0035", b"generated")],
        )
        target = game / "data" / UNIT_DATA_PATCH_NAME
        target.write_bytes(source.read_bytes())
        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        mod = scanned["data"]["mods"][0]
        self.assertFalse(mod["hidden"])
        result = {"status": "generated", "path": str(source), "fingerprint": "unit", "entry_count": 1}

        with patch("backend.api.ensure_unit_data_patch", return_value=result), \
                patch("backend.api.launch_game", return_value={"pid": 7}), \
                patch.object(self.api, "set_game_running"):
            launched = self.api.call("launch_game", [[mod["id"]], scanned["data"]["order_token"]])
        self.assertTrue(launched["ok"], launched)
        self.assertEqual(launched["data"]["launch_plan"]["pack_names"], [UNIT_DATA_PATCH_NAME])
        self.assertEqual(self.api._unit_data_source_ids(), [])

    def test_three_kingdoms_launch_preserves_a_manually_enabled_unit_patch_without_new_edits(self):
        game, _ = self.select_game("three_kingdoms")
        target = write_pack(
            game / "data" / UNIT_DATA_PATCH_NAME,
            entries=[("db\\land_units_tables\\saved_units", b"saved edits")],
        )
        original = target.read_bytes()
        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        mod_id = scanned["data"]["mods"][0]["id"]
        result = {"status": "zero_modification", "path": "", "fingerprint": "", "entry_count": 0}

        with patch("backend.api.ensure_unit_data_patch", return_value=result), \
                patch("backend.api.launch_game", return_value={"pid": 7}), \
                patch.object(self.api, "set_game_running"):
            launched = self.api.call("launch_game", [[mod_id], scanned["data"]["order_token"]])
        self.assertTrue(launched["ok"], launched)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(launched["data"]["launch_plan"]["pack_names"], [UNIT_DATA_PATCH_NAME])
        self.assertEqual(self.api._unit_data_source_ids(), [mod_id])

    def test_three_kingdoms_schema_update_does_not_reject_a_warhammer_runtime_pack_name(self):
        game, _ = self.select_game("three_kingdoms")
        write_pack(game / "data" / "!!!!wyccc_runtime_options.pack", byte_mask=3)
        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        mod_id = scanned["data"]["mods"][0]["id"]

        updated = self.api.call("update_mod_table_schemas", [[mod_id], "three_kingdoms"])
        self.assertTrue(updated["ok"], updated)
        self.assertEqual(updated["data"]["failed_count"], 0)
        self.assertEqual(updated["data"]["unchanged_count"], 1)

    def test_three_kingdoms_launch_does_not_delete_an_ordinary_inactive_mod_named_like_the_unit_patch(self):
        game, _ = self.select_game("three_kingdoms")
        target = write_pack(
            game / "data" / UNIT_DATA_PATCH_NAME,
            entries=[("db\\land_units_tables\\ordinary_units", b"user data")],
        )
        original = target.read_bytes()
        scanned = self.api.call("scan_mods", [False])
        self.assertTrue(scanned["ok"], scanned)
        result = {"status": "zero_modification", "path": "", "fingerprint": "", "entry_count": 0}

        with patch("backend.api.ensure_unit_data_patch", return_value=result), \
                patch("backend.api.launch_game", return_value={"pid": 7}), \
                patch.object(self.api, "set_game_running"):
            launched = self.api.call("launch_game", [[], scanned["data"]["order_token"]])
        self.assertTrue(launched["ok"], launched)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), original)

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
