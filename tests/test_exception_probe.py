from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.steamworks_bridge import SteamworksBridgeError
from backend.app_settings import SettingsService, default_settings
from backend.battle_probe import (
    BATTLE_PROBE_ENTRY_NAMES,
    MEMREADER_PLUS_WORKSHOP_ID,
    battle_probe_payloads,
)
from backend.constants import RUNTIME_OPTIONS_MARKER_ENTRY
from backend.models import ModAsset
from backend.start_options import (
    RUNTIME_PACK_NAME,
    build_runtime_options_pack,
    read_pack_entries,
)
from tests.helpers import write_pack


class ExceptionProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.game = self.root / "game"
        self.data = self.game / "data"
        self.data.mkdir(parents=True)
        (self.game / "Warhammer3.exe").write_bytes(b"")
        self.workshop = self.root / "workshop"
        self.plus = write_pack(
            self.workshop / MEMREADER_PLUS_WORKSHOP_ID / "memreader_plus.pack",
            byte_mask=3,
            entries=[("script\\_lib\\mod\\memreader_plus.lua", b"-- fixture")],
        )
        self.asset = ModAsset(
            id="plus", pack_name=self.plus.name, display_name="Memreader Plus",
            path=str(self.plus), directory=str(self.plus.parent), source="workshop",
            workshop_id=MEMREADER_PLUS_WORKSHOP_ID,
        )
        self.settings = {"enable_exception_probe": True, "selected_game": "warhammer3"}

    def build(self, assets=None, active_ids=None, settings=None) -> dict:
        return build_runtime_options_pack(
            self.root / "runtime", str(self.data),
            assets if assets is not None else {"plus": self.asset},
            active_ids if active_ids is not None else ["plus"],
            settings if settings is not None else self.settings,
        )

    def test_default_off_and_setting_persists_across_service_reload(self) -> None:
        self.assertFalse(default_settings()["enable_exception_probe"])
        service = SettingsService(self.root / "state")
        service.save({"enable_exception_probe": True})
        self.assertTrue(SettingsService(self.root / "state").get()["enable_exception_probe"])
        service.save({"enable_exception_probe": False})
        self.assertFalse(SettingsService(self.root / "state").get()["enable_exception_probe"])

    def test_enabled_subscribed_plus_packages_exact_probe_sources(self) -> None:
        built = self.build()
        self.assertIn("enable_exception_probe", built["options"])
        actual = {entry.name: entry.payload for entry in read_pack_entries(Path(built["path"]))}
        self.assertEqual(set(actual), {*BATTLE_PROBE_ENTRY_NAMES, RUNTIME_OPTIONS_MARKER_ENTRY})
        for name, payload in battle_probe_payloads():
            self.assertEqual(actual[name], payload)

    def test_missing_or_disabled_plus_does_not_generate_probe(self) -> None:
        for assets, active_ids in (({}, []), ({"plus": self.asset}, [])):
            with self.subTest(active_ids=active_ids, assets=list(assets)):
                self.assertEqual(self.build(assets, active_ids)["path"], "")
        self.asset.workshop_id = "2789863945"  # Original Memreader is insufficient.
        self.assertEqual(self.build()["path"], "")

    def test_local_pack_without_workshop_source_is_insufficient(self) -> None:
        self.asset.source = "data"
        self.assertEqual(self.build()["path"], "")

    def test_data_copy_with_downloaded_workshop_alias_is_supported(self) -> None:
        self.asset.path = str(write_pack(self.data / self.plus.name, byte_mask=3))
        self.asset.source = "data"
        self.asset.sources = ["data", "workshop"]
        self.asset.alternate_paths = [str(self.plus)]
        self.assertTrue(self.build()["exception_probe"]["enabled"])
        self.plus.unlink()
        self.assertEqual(self.build()["path"], "")

    def test_dependency_loss_rewrites_stale_probe_but_preserves_other_options(self) -> None:
        settings = {**self.settings, "enable_script_logging": True}
        first = self.build(settings=settings)
        self.assertTrue(first["exception_probe"]["enabled"])
        self.plus.unlink()
        second = self.build(settings=settings)
        self.assertFalse(second["exception_probe"]["enabled"])
        actual = {entry.name: entry.payload for entry in read_pack_entries(Path(second["path"]))}
        self.assertEqual(actual, {
            "script\\enable_console_logging": b"\0",
            RUNTIME_OPTIONS_MARKER_ENTRY: actual[RUNTIME_OPTIONS_MARKER_ENTRY],
        })

    def test_dependency_loss_removes_pack_when_probe_was_only_option(self) -> None:
        built = self.build()
        pack = Path(built["path"])
        self.assertTrue(pack.is_file())
        self.build(active_ids=[])
        self.assertFalse(pack.exists())

    def test_other_games_never_load_probe(self) -> None:
        for game in ("warhammer2", "three_kingdoms", "rome_remastered"):
            with self.subTest(game=game):
                self.assertEqual(self.build(settings={**self.settings, "selected_game": game})["path"], "")

    def test_save_disabling_probe_cleans_runtime_and_data_copies(self) -> None:
        api = API(self.root / "state")
        self.addCleanup(api.close)
        with patch.object(api, "detect_game_running", return_value=False):
            saved = api.call("save_settings", [{
                "game_path": str(self.game), "fetch_workshop_metadata": False,
                "live_mod_detection": False, "enable_exception_probe": True,
                "enable_script_logging": True,
            }])
            self.assertTrue(saved["ok"], saved)
            built = build_runtime_options_pack(
                api.data_dir / "runtime", str(self.data), {"plus": self.asset}, ["plus"],
                api.settings_service.get(),
            )
            staged = api._stage_runtime_pack_in_data(built["path"], self.data, RUNTIME_PACK_NAME)
            saved = api.call("save_settings", [{"enable_exception_probe": False}])
            self.assertTrue(saved["ok"], saved)
            for path in (Path(built["path"]), staged):
                actual = {entry.name for entry in read_pack_entries(path)}
                self.assertEqual(actual, {"script\\enable_console_logging", RUNTIME_OPTIONS_MARKER_ENTRY})

    def test_fake_launch_injects_probe_and_respects_changed_enabled_list(self) -> None:
        api = API(self.root / "state")
        self.addCleanup(api.close)
        with (
            patch.object(api, "detect_game_running", return_value=False),
            patch("backend.api.query_workshop_subscription_status", return_value=[{
                "workshop_id": MEMREADER_PLUS_WORKSHOP_ID, "subscribed": True,
            }]),
            patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}) as launch,
            patch.object(api, "set_game_running"),
        ):
            response = api.call("save_settings", [{
                "game_path": str(self.game), "workshop_path": str(self.workshop),
                "fetch_workshop_metadata": False, "live_mod_detection": False,
                "enable_exception_probe": True,
            }])
            self.assertTrue(response["ok"], response)
            scan = api.call("scan_mods", [False])
            self.assertTrue(scan["ok"], scan)
            plus_id = next(mod["id"] for mod in scan["data"]["mods"] if mod["pack_name"] == self.plus.name)
            for active in ([plus_id], []):
                with self.subTest(active=active):
                    response = api.call("launch_game", [active, scan["data"]["order_token"]])
                    self.assertTrue(response["ok"], response)
                    runtime = self.data / RUNTIME_PACK_NAME
                    if active:
                        self.assertTrue(runtime.is_file())
                        self.assertTrue(set(BATTLE_PROBE_ENTRY_NAMES).issubset({
                            entry.name for entry in read_pack_entries(runtime)
                        }))
                    else:
                        self.assertFalse(runtime.exists())
                    scan = api.call("scan_mods", [False])
            self.assertEqual(launch.call_count, 2)

    def test_fake_launch_without_verified_subscription_preserves_other_options(self) -> None:
        for status in (False, SteamworksBridgeError("Steam unavailable")):
            with self.subTest(status=str(status)):
                api = API(self.root / str(len(str(status))))
                self.addCleanup(api.close)
                def subscriptions(workshop_ids, *args, **kwargs):
                    if MEMREADER_PLUS_WORKSHOP_ID not in workshop_ids:
                        return []
                    if isinstance(status, Exception):
                        raise status
                    return [{"workshop_id": MEMREADER_PLUS_WORKSHOP_ID, "subscribed": status}]
                with (
                    patch.object(api, "detect_game_running", return_value=False),
                    patch("backend.api.query_workshop_subscription_status", side_effect=subscriptions),
                    patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}),
                    patch.object(api, "set_game_running"),
                ):
                    response = api.call("save_settings", [{
                        "game_path": str(self.game), "workshop_path": str(self.workshop),
                        "fetch_workshop_metadata": False, "live_mod_detection": False,
                        "enable_exception_probe": True, "enable_script_logging": True,
                    }])
                    self.assertTrue(response["ok"], response)
                    scan = api.call("scan_mods", [False])
                    plus_id = next(mod["id"] for mod in scan["data"]["mods"] if mod["pack_name"] == self.plus.name)
                    response = api.call("launch_game", [[plus_id], scan["data"]["order_token"]])
                    self.assertTrue(response["ok"], response)
                    actual = {entry.name for entry in read_pack_entries(self.data / RUNTIME_PACK_NAME)}
                    self.assertEqual(actual, {"script\\enable_console_logging", RUNTIME_OPTIONS_MARKER_ENTRY})
                    self.assertTrue(api.settings_service.get()["enable_exception_probe"])
