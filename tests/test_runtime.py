from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from backend.api import API
from backend.models import GamePaths
from backend.runtime import RuntimeCoordinator, descendant_process_ids, localized_idle_url


class RuntimeCoordinatorTests(unittest.TestCase):
    def test_idle_url_uses_the_selected_interface_language(self) -> None:
        self.assertEqual(
            localized_idle_url("file:///idle.html", "ja-JP"),
            "file:///idle.html#lang=ja-JP",
        )
        self.assertEqual(
            localized_idle_url("https://localhost/idle.html?lang=en-US&x=1", "ru-RU"),
            "https://localhost/idle.html?x=1&lang=ru-RU",
        )

    def test_descendant_process_ids_walks_the_complete_process_tree(self) -> None:
        self.assertEqual(
            descendant_process_ids(10, {11: 10, 12: 11, 13: 10, 99: 98}),
            [11, 13, 12],
        )

    def test_transitions_load_idle_and_app_pages_and_toggle_runtime_services(self) -> None:
        window = Mock()
        api = Mock()
        trim = Mock(return_value=3)
        coordinator = RuntimeCoordinator(
            window,
            api,
            "file:///index.html",
            "file:///idle.html",
            trim_callback=trim,
            trim_delay=0,
        )

        coordinator._transition(True)
        coordinator._transition(False)

        self.assertEqual(
            window.load_url.call_args_list,
            [
                unittest.mock.call("file:///idle.html"),
                unittest.mock.call("file:///index.html"),
            ],
        )
        self.assertEqual(
            api.set_game_running.call_args_list,
            [
                unittest.mock.call(True, force=True),
                unittest.mock.call(False, force=True),
            ],
        )
        trim.assert_called_once_with()

    def test_manual_exit_restores_the_app_until_the_current_game_session_ends(self) -> None:
        window = Mock()
        api = Mock()
        coordinator = RuntimeCoordinator(
            window,
            api,
            "file:///index.html",
            "file:///idle.html",
            initial_running=True,
            trim_delay=0,
        )

        self.assertTrue(coordinator.exit_low_consumption_mode())
        coordinator._transition(False)
        coordinator._transition(True)

        self.assertEqual(
            window.load_url.call_args_list,
            [
                unittest.mock.call("file:///index.html"),
                unittest.mock.call("file:///idle.html"),
            ],
        )
        self.assertEqual(
            api.set_game_running.call_args_list,
            [
                unittest.mock.call(False, force=True),
                unittest.mock.call(True, force=True),
            ],
        )

    def test_low_consumption_exit_rpc_calls_the_bound_runtime_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary))
            restore = Mock(return_value=True)
            api.bind_low_consumption_exit(restore)

            result = api.call("exit_low_consumption_mode")

        self.assertEqual(result, {"ok": True, "data": {"restored": True}})
        restore.assert_called_once_with()

    def test_low_consumption_runtime_stops_live_directory_monitoring(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary))
            paths = GamePaths(data_path=str(Path(temporary) / "data"), workshop_path=str(Path(temporary) / "workshop"))
            with (
                patch.object(api.settings_service, "resolve_game_paths", return_value=paths),
                patch.object(api.mod_monitor, "start", return_value=True) as start,
                patch.object(api.mod_monitor, "stop") as stop,
            ):
                api.set_game_running(False, force=True)
                api.set_game_running(True, force=True)

        start.assert_called_once_with(paths.data_path, paths.workshop_path)
        stop.assert_called_once_with()

    def test_api_detection_validates_against_the_cached_configured_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary))
            first = GamePaths(game_path=r"C:\Games\WH3")
            second = GamePaths(game_path=r"D:\Steam\WH3")
            with (
                patch.object(
                    api.settings_service,
                    "resolve_game_paths",
                    side_effect=[first, second],
                ) as resolve_paths,
                patch("backend.api.is_game_running", return_value=False) as detect,
            ):
                self.assertFalse(api.detect_game_running())
                self.assertFalse(api.detect_game_running())
                api._invalidate_game_executable_cache()
                self.assertFalse(api.detect_game_running())

        self.assertEqual(resolve_paths.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in detect.call_args_list],
            [
                str(Path(first.game_path) / "Warhammer3.exe"),
                str(Path(first.game_path) / "Warhammer3.exe"),
                str(Path(second.game_path) / "Warhammer3.exe"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
