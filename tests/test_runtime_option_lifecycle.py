from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.constants import RUNTIME_OPTIONS_MARKER_ENTRY
from backend.start_options import (
    INTRO_MOVIES,
    PERMISSIONS_ENTRY,
    RUNTIME_PACK_NAME,
    PackEntry,
    read_pack_entries,
    write_pfh5_pack,
)
from tests.helpers import write_pack
from tests.test_start_options import _permission_row, _permission_table


class RuntimeOptionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        game = self.root / "game"
        self.data = game / "data"
        self.data.mkdir(parents=True)
        (game / "Warhammer3.exe").write_bytes(b"")
        (self.data / "manifest.txt").write_text("db.pack\t0\n", encoding="utf-8")
        write_pack(
            self.data / "db.pack",
            entries=[(
                "db\\units_custom_battle_permissions_tables\\vanilla",
                _permission_table([_permission_row("faction", "unit", 0)]),
            )],
        )
        self.api = API(self.root / "state")
        self.addCleanup(self.api.close)
        detector = patch.object(self.api, "detect_game_running", return_value=False)
        self.detector = detector.start()
        self.addCleanup(detector.stop)
        self.save({
            "game_path": str(game),
            "fetch_workshop_metadata": False,
            "live_mod_detection": False,
        })
        self.runtime_paths = (
            self.root / "state" / "runtime" / RUNTIME_PACK_NAME,
            self.data / RUNTIME_PACK_NAME,
        )

    def save(self, changes: dict) -> dict:
        response = self.api.call("save_settings", [changes])
        self.assertTrue(response["ok"], response)
        return response["data"]

    def launch(self) -> dict:
        scan = self.api.call("scan_mods", [False])
        self.assertTrue(scan["ok"], scan)
        with (
            patch("backend.api.query_workshop_subscription_status", return_value=[]),
            patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}),
            patch.object(self.api, "set_game_running"),
        ):
            response = self.api.call("launch_game", [[], scan["data"]["order_token"]])
        self.assertTrue(response["ok"], response)
        return response["data"]

    def test_disabling_lords_removes_permissions_at_save_and_preserves_other_options(self) -> None:
        self.save({
            "custom_battle_all_units_as_lords": True,
            "skip_intro_movies": True,
            "enable_script_logging": True,
        })
        self.launch()
        before = {
            entry.name: entry.payload
            for entry in read_pack_entries(self.runtime_paths[1])
        }
        self.assertIn(PERMISSIONS_ENTRY, before)

        saved = self.save({"custom_battle_all_units_as_lords": False})
        self.assertFalse(saved["settings"]["custom_battle_all_units_as_lords"])
        expected = {name: payload for name, payload in before.items() if name != PERMISSIONS_ENTRY}
        for path in self.runtime_paths:
            with self.subTest(path=path):
                actual = {entry.name: entry.payload for entry in read_pack_entries(path)}
                self.assertNotIn(PERMISSIONS_ENTRY, actual)
                self.assertEqual(actual, expected)

    def test_disabling_last_runtime_option_removes_both_packs_at_save(self) -> None:
        self.save({"custom_battle_all_units_as_lords": True})
        self.launch()
        self.assertTrue(all(path.is_file() for path in self.runtime_paths))

        self.save({"custom_battle_all_units_as_lords": False})
        for path in self.runtime_paths:
            with self.subTest(path=path):
                self.assertFalse(path.exists())

    def test_disabled_permissions_are_absent_after_relaunch(self) -> None:
        self.save({"custom_battle_all_units_as_lords": True, "skip_intro_movies": True})
        self.launch()
        self.save({"custom_battle_all_units_as_lords": False})
        launched = self.launch()

        self.assertEqual(launched["runtime_options"]["options"], ["skip_intro_movies"])
        for path in self.runtime_paths:
            with self.subTest(path=path):
                self.assertEqual(
                    {entry.name for entry in read_pack_entries(path)},
                    set(INTRO_MOVIES) | {RUNTIME_OPTIONS_MARKER_ENTRY},
                )

    def test_saving_with_game_running_defers_pack_changes_until_relaunch(self) -> None:
        self.save({"custom_battle_all_units_as_lords": True})
        self.launch()
        originals = {path: path.read_bytes() for path in self.runtime_paths}
        self.detector.return_value = True

        self.save({"custom_battle_all_units_as_lords": False})
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

        self.detector.return_value = False
        launched = self.launch()
        self.assertEqual(launched["runtime_options"]["options"], [])
        self.assertTrue(all(not path.exists() for path in self.runtime_paths))

    def test_saving_false_again_cleans_stale_packs_without_reading_source_db(self) -> None:
        for path in self.runtime_paths:
            write_pfh5_pack(path, [PackEntry(PERMISSIONS_ENTRY, b"stale permission table")])
        (self.data / "db.pack").unlink()
        with patch("backend.start_options._build_permission_table") as builder:
            self.save({"custom_battle_all_units_as_lords": False})
        builder.assert_not_called()
        self.assertTrue(all(not path.exists() for path in self.runtime_paths))

    def test_disabling_other_options_preserves_existing_permissions(self) -> None:
        self.save({
            "custom_battle_all_units_as_lords": True,
            "skip_intro_movies": True,
            "enable_script_logging": True,
        })
        self.launch()
        permission = next(
            entry.payload for entry in read_pack_entries(self.runtime_paths[1])
            if entry.name == PERMISSIONS_ENTRY
        )
        self.save({"skip_intro_movies": False, "enable_script_logging": False})
        for path in self.runtime_paths:
            with self.subTest(path=path):
                entries = {entry.name: entry.payload for entry in read_pack_entries(path)}
                self.assertEqual(set(entries), {PERMISSIONS_ENTRY, RUNTIME_OPTIONS_MARKER_ENTRY})
                self.assertEqual(entries[PERMISSIONS_ENTRY], permission)

    def test_removing_last_existing_override_does_not_leave_a_marker_only_pack(self) -> None:
        self.save({"custom_battle_all_units_as_lords": True})
        self.launch()
        self.save({"custom_battle_all_units_as_lords": False, "skip_intro_movies": True})
        self.assertTrue(all(not path.exists() for path in self.runtime_paths))

        self.launch()
        self.assertTrue(all(path.exists() for path in self.runtime_paths))

    def test_saving_for_another_game_preserves_warhammer_runtime_packs(self) -> None:
        self.save({"custom_battle_all_units_as_lords": True})
        self.launch()
        originals = {path: path.read_bytes() for path in self.runtime_paths}
        game = self.root / "three_kingdoms"
        (game / "data").mkdir(parents=True)
        (game / "Three_Kingdoms.exe").write_bytes(b"")
        other_pack = write_pfh5_pack(
            game / "data" / RUNTIME_PACK_NAME,
            [PackEntry("other_game_resource", b"keep")],
        )
        originals[other_pack] = other_pack.read_bytes()

        self.save({
            "selected_game": "three_kingdoms",
            "game_path": str(game),
            "custom_battle_all_units_as_lords": False,
        })
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
