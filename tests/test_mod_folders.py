from __future__ import annotations

import tempfile
import unittest
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

    def test_playsets_and_games_are_isolated_and_deleting_playset_cascades(self):
        first = self.repository.create_mod_folder("default", "UI", ["a"])
        other = self.repository.create_playset("Other", ["a"])["id"]
        self.assertEqual(self.folders(other), [])
        second = self.repository.create_mod_folder(other, "UI", ["b"])
        for game, playset, target in [
            ("warhammer3", other, first),
            ("three_kingdoms", "default:three_kingdoms", first),
            ("three_kingdoms", other, second),
        ]:
            with self.subTest(game=game, playset=playset), self.assertRaises(ValueError):
                self.repository.assign_mod_folder(playset, ["a"], target, game)
        self.repository.delete_playset(other)
        with self.repository._connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mod_folders").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mod_folder_items").fetchone()[0], 1)


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


if __name__ == "__main__":
    unittest.main()
