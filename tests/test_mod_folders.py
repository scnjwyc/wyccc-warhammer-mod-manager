from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from backend.api import API
from backend.storage import StateRepository
from tests.helpers import make_asset, write_pack


class ModFolderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "state.db"
        self.repository = StateRepository(self.database)

    def folders(self, playset="default", game="warhammer3"):
        return self.repository.list_mod_folders(playset, game)

    def test_membership_and_independent_collapse_survive_restart_without_changing_load_order(self):
        self.repository.update_current_playset(["b", "a"])
        folder = self.repository.create_mod_folder("default", "  UI  ", ["a", "a", "missing"])
        self.repository.set_mod_folder_collapsed("default", folder, "active", True)
        self.repository.rename_mod_folder("default", folder, "界面")
        restored = StateRepository(self.database)
        self.assertEqual(restored.list_mod_folders("default"), [{
            "id": folder, "name": "界面", "mod_ids": ["a", "missing"],
            "collapsed_active": True, "collapsed_inactive": False,
        }])
        self.assertEqual(restored.get_enabled_order(), ["b", "a"])

    def test_move_remove_and_delete_only_change_folder_membership(self):
        self.repository.update_current_playset(["a", "b"])
        first = self.repository.create_mod_folder("default", "One", ["a", "b"])
        second = self.repository.create_mod_folder("default", "Two", ["c"])
        self.repository.assign_mod_folder("default", ["a", "c"], first)
        self.assertEqual(self.folders()[0]["mod_ids"], ["a", "b", "c"])
        self.assertEqual(self.folders()[1]["mod_ids"], [])
        self.repository.assign_mod_folder("default", ["b"], "")
        self.repository.delete_mod_folder("default", first)
        self.assertEqual(self.folders()[0]["id"], second)
        self.assertEqual(self.folders()[0]["mod_ids"], [])
        self.assertEqual(self.repository.get_enabled_order(), ["a", "b"])

    def test_invalid_names_duplicate_names_and_bad_targets_leave_membership_intact(self):
        folder = self.repository.create_mod_folder("default", "Straße", ["a"])
        for name in [" ", "x" * 81, "STRASSE"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.repository.create_mod_folder("default", name, ["a"])
        with self.assertRaises(ValueError):
            self.repository.assign_mod_folder("default", ["a"], "missing")
        with self.assertRaises(ValueError):
            self.repository.set_mod_folder_collapsed("default", folder, "invalid", True)
        self.assertEqual(self.folders()[0]["mod_ids"], ["a"])

    def test_playsets_share_folders_while_games_are_isolated_and_playset_deletion_keeps_them(self):
        first = self.repository.create_mod_folder("default", "UI", ["a"])
        other = self.repository.create_playset("Other", ["a"])["id"]
        self.assertEqual(self.folders(other), self.folders())
        second = self.repository.create_mod_folder(other, "Other UI", ["b"])
        self.repository.assign_mod_folder(other, ["a"], second)
        for game, playset, target in [
            ("three_kingdoms", "default:three_kingdoms", first),
            ("three_kingdoms", other, second),
        ]:
            with self.subTest(game=game, playset=playset), self.assertRaises(ValueError):
                self.repository.assign_mod_folder(playset, ["a"], target, game)
        self.repository.delete_playset(other)
        with self.repository._connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mod_folders").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mod_folder_items").fetchone()[0], 2)
        self.assertEqual(self.folders()[1]["mod_ids"], ["a", "b"])

    def test_panel_layout_survives_restart_and_playset_switch_without_changing_mod_order(self):
        first = self.repository.create_mod_folder("default", "One", ["a"])
        second = self.repository.create_mod_folder("default", "Two", ["b"])
        self.repository.update_current_playset(["a", "b", "c"])
        layout = [f"folder:{second}", "mod:c", f"folder:{first}"]
        self.repository.reorder_mod_folder_groups("default", "active", layout)
        other = self.repository.create_playset("Other", ["c", "b"])["id"]
        restored = StateRepository(self.database)
        self.assertEqual(restored.get_mod_folder_layouts(), {"active": layout, "inactive": []})
        self.assertEqual(restored.list_mod_folders(other), restored.list_mod_folders("default"))
        restored.switch_playset("default")
        self.assertEqual(restored.get_enabled_order(), ["a", "b", "c"])
        self.assertEqual(restored.get_mod_folder_layouts("three_kingdoms"), {"active": [], "inactive": []})
        restored.delete_mod_folder("default", first)
        self.assertEqual(restored.get_mod_folder_layouts()["active"], [f"folder:{second}", "mod:c"])

    def test_invalid_layout_does_not_replace_saved_positions(self):
        folder = self.repository.create_mod_folder("default", "One", ["a"])
        layout = [f"folder:{folder}"]
        self.repository.reorder_mod_folder_groups("default", "inactive", layout)
        for name, keys in [("invalid", layout), ("inactive", ["folder:missing"]),
                           ("inactive", ["bad"]), ("inactive", [1]), ("inactive", layout * 2)]:
            with self.subTest(name=name, keys=keys), self.assertRaises(ValueError):
                self.repository.reorder_mod_folder_groups("default", name, keys)
        self.assertEqual(self.repository.get_mod_folder_layouts()["inactive"], layout)

    def make_legacy_folders(self):
        other = self.repository.create_playset("Old playset", ["a"])["id"]
        with self.repository._connect() as connection:
            connection.execute("DROP TABLE mod_folder_items")
            connection.execute("DROP TABLE mod_folders")
            connection.execute("""CREATE TABLE mod_folders (
                id TEXT PRIMARY KEY, playset_id TEXT NOT NULL REFERENCES playsets(id) ON DELETE CASCADE,
                name TEXT NOT NULL, collapsed_active INTEGER NOT NULL DEFAULT 0,
                collapsed_inactive INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
                UNIQUE(playset_id, id))""")
            connection.execute("""CREATE TABLE mod_folder_items (
                playset_id TEXT NOT NULL, mod_id TEXT NOT NULL, folder_id TEXT NOT NULL,
                PRIMARY KEY(playset_id, mod_id),
                FOREIGN KEY(playset_id, folder_id) REFERENCES mod_folders(playset_id, id) ON DELETE CASCADE)""")
            connection.executemany("INSERT INTO mod_folders VALUES(?, ?, ?, ?, ?, ?)", [
                ("first", "default", "UI", 0, 0, 1),
                ("current", other, "ui", 1, 0, 2),
                ("battle", "default", "Battle", 0, 1, 3),
                ("tk", "default:three_kingdoms", "UI", 0, 0, 4),
            ])
            connection.executemany("INSERT INTO mod_folder_items VALUES(?, ?, ?)", [
                ("default", "b", "first"), ("default", "a", "battle"),
                ("default", "c", "battle"), (other, "a", "current"),
                ("default:three_kingdoms", "a", "tk"),
            ])
        return other

    def test_legacy_playset_folders_migrate_once_with_membership_and_game_isolation(self):
        other = self.make_legacy_folders()
        restored = StateRepository(self.database)
        folders = restored.list_mod_folders("default")
        self.assertEqual(folders, restored.list_mod_folders(other))
        self.assertEqual(folders[0]["id"], "current")
        self.assertTrue(folders[0]["collapsed_active"])
        self.assertEqual(folders[0]["mod_ids"], ["a", "b"])
        self.assertEqual(folders[1]["mod_ids"], ["c"])
        self.assertEqual(restored.list_mod_folders("default:three_kingdoms", "three_kingdoms")[0]["id"], "tk")
        with restored._connect() as connection:
            backup = json.loads(connection.execute(
                "SELECT value FROM system_info WHERE key = 'mod_folders_legacy_v11'"
            ).fetchone()["value"])
            self.assertEqual(len(backup["folders"]), 4)
            self.assertEqual(len(backup["items"]), 5)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(StateRepository(self.database).list_mod_folders("default"), folders)

    def test_legacy_migration_failure_rolls_back_original_folder_tables(self):
        self.make_legacy_folders()

        class FailingConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, *args):
                if sql.startswith("INSERT INTO mod_folders VALUES"):
                    raise RuntimeError("simulated write failure")
                return self.connection.execute(sql, *args)

        with self.repository._connect() as connection:
            with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
                StateRepository._ensure_shared_mod_folders(FailingConnection(connection))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mod_folders").fetchone()[0], 4)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mod_folder_items").fetchone()[0], 5)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(mod_folders)")}
            self.assertIn("playset_id", columns)
            self.assertNotIn("game_id", columns)


class ModFolderApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.api = API(self.root / "state")
        self.addCleanup(self.api.close)
        asset = make_asset(write_pack(self.root / "a.pack"), "canonical", "data")
        self.api._assets = {asset.id: asset}
        self.api._asset_aliases = {"old-source": asset.id}

    def call(self, method, *args):
        result = self.api.call(method, list(args))
        self.assertTrue(result["ok"], result)
        return result["data"]

    def test_rpc_creation_aliases_reassignment_and_removal_are_persisted(self):
        self.api.state_repository.update_current_playset(["canonical"])
        first = self.call("create_mod_folder", "One", ["old-source"])["mod_folders"][0]
        self.assertEqual(first["mod_ids"], ["canonical"])
        second = self.call("create_mod_folder", "Two", ["canonical"])["mod_folders"][1]
        folders = self.api._current_playset_payload()["mod_folders"]
        self.assertEqual(folders[0]["mod_ids"], [])
        self.assertEqual(folders[1]["mod_ids"], ["canonical"])
        self.call("set_mod_folder_collapsed", second["id"], "inactive", True)
        self.call("rename_mod_folder", second["id"], "New name")
        self.call("assign_mod_folder", ["old-source"], "")
        self.assertTrue(all(not folder["mod_ids"] for folder in self.api._current_playset_payload()["mod_folders"]))
        self.call("delete_mod_folder", first["id"])
        self.assertEqual(self.api.state_repository.get_enabled_order(), ["canonical"])

    def test_wrong_context_and_invalid_destination_do_not_mutate_existing_folders(self):
        self.call("create_mod_folder", "UI", ["canonical"])
        for args in [
            [["canonical"], "missing"],
            [["canonical"], "", "three_kingdoms", "default"],
            [["canonical"], "", "warhammer3", "other-playset"],
        ]:
            with self.subTest(args=args):
                self.assertFalse(self.api.call("assign_mod_folder", args)["ok"])
                self.assertEqual(self.api._current_playset_payload()["mod_folders"][0]["mod_ids"], ["canonical"])

    def test_switching_to_an_existing_playset_retains_folders_and_membership(self):
        other = self.api.state_repository.create_playset("Other", ["canonical"])["id"]
        self.call("switch_playset", "default")
        created = self.call("create_mod_folder", "UI", ["canonical"])["mod_folders"]
        switched = self.call("switch_playset", other)
        self.assertEqual(switched["mod_folders"], created)
        self.assertEqual(switched["ordered_mod_ids"], ["canonical"])
        self.assertEqual(self.call("switch_playset", "default")["mod_folders"], created)

    def test_rpc_layout_is_returned_after_switch_and_wrong_context_cannot_replace_it(self):
        folder = self.call("create_mod_folder", "UI", ["canonical"])["mod_folders"][0]
        layout = ["mod:loose", f"folder:{folder['id']}"]
        result = self.call("reorder_mod_folder_groups", "active", layout, "warhammer3", "default")
        self.assertEqual(result["mod_folder_layouts"], {"active": layout, "inactive": []})
        created = self.call("create_playset", "Other", ["canonical"])
        other = created["current_playset"]["id"]
        self.assertEqual(created["mod_folder_layouts"]["active"], layout)
        self.assertFalse(self.api.call("reorder_mod_folder_groups", [
            "active", [], "warhammer3", "default",
        ])["ok"])
        self.assertEqual(self.call("switch_playset", other)["mod_folder_layouts"]["active"], layout)


if __name__ == "__main__":
    unittest.main()
