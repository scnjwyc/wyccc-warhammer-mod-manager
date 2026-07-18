from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.api import API
from backend.mod_watcher import DebouncedCallback, ModChangeMonitor, ModEventHandler
from backend.start_options import GAME_DATA_PATCH_NAME, RUNTIME_PACK_NAME
from tests.helpers import write_pack


class FakeObserver:
    def __init__(self) -> None:
        self.scheduled: list[tuple[object, str, bool]] = []
        self.started = False
        self.stopped = False

    def schedule(self, handler: object, path: str, recursive: bool = False) -> object:
        self.scheduled.append((handler, path, recursive))
        return object()

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float | None = None) -> None:
        return None


class ModWatcherTests(unittest.TestCase):
    def test_filters_for_pack_files_and_workshop_item_directories(self) -> None:
        changes: list[str] = []
        data_handler = ModEventHandler(lambda: changes.append("data"), workshop=False)
        workshop_handler = ModEventHandler(lambda: changes.append("workshop"), workshop=True)

        data_handler.on_any_event(
            SimpleNamespace(event_type="created", src_path=r"C:\game\data\new.pack", is_directory=False)
        )
        data_handler.on_any_event(
            SimpleNamespace(event_type="created", src_path=r"C:\game\data\preview.png", is_directory=False)
        )
        data_handler.on_any_event(
            SimpleNamespace(
                event_type="created",
                src_path=rf"C:\game\data\{GAME_DATA_PATCH_NAME}",
                is_directory=False,
            )
        )
        data_handler.on_any_event(
            SimpleNamespace(
                event_type="modified",
                src_path=rf"C:\game\data\{RUNTIME_PACK_NAME}",
                is_directory=False,
            )
        )
        workshop_handler.on_any_event(
            SimpleNamespace(event_type="deleted", src_path=r"C:\workshop\123456", is_directory=True)
        )
        workshop_handler.on_any_event(
            SimpleNamespace(event_type="modified", src_path=r"C:\workshop\123456\preview.jpg", is_directory=False)
        )

        self.assertEqual(changes, ["data", "workshop"])

    def test_debouncer_coalesces_event_bursts(self) -> None:
        calls: list[float] = []
        callback = DebouncedCallback(lambda: calls.append(time.monotonic()), 0.03)
        try:
            callback.trigger()
            callback.trigger()
            callback.trigger()
            time.sleep(0.08)
        finally:
            callback.close()

        self.assertEqual(len(calls), 1)

    def test_monitor_uses_non_recursive_data_and_recursive_workshop_watches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "game" / "data"
            workshop = root / "workshop" / "1142710"
            data.mkdir(parents=True)
            workshop.mkdir(parents=True)
            observers: list[FakeObserver] = []

            def factory() -> FakeObserver:
                observer = FakeObserver()
                observers.append(observer)
                return observer

            monitor = ModChangeMonitor(lambda: None, observer_factory=factory)
            self.assertTrue(monitor.start(str(data), str(workshop)))
            self.assertTrue(monitor.active)
            self.assertEqual(
                [(Path(path), recursive) for _handler, path, recursive in observers[0].scheduled],
                [(data, False), (workshop, True)],
            )

            self.assertTrue(monitor.start(str(data), str(workshop)))
            self.assertEqual(len(observers), 1)
            monitor.stop()
            self.assertTrue(observers[0].stopped)
            self.assertFalse(monitor.active)

    def test_real_observer_reports_a_new_data_pack_without_directory_polling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "game" / "data"
            data.mkdir(parents=True)
            changed = threading.Event()
            monitor = ModChangeMonitor(changed.set, debounce_seconds=0.05)
            if not monitor.available:
                self.skipTest("watchdog is not installed")
            try:
                self.assertTrue(monitor.start(str(data), ""))
                (data / "new_mod.pack").write_bytes(b"PFH5")
                self.assertTrue(changed.wait(3), "native filesystem event was not delivered")
            finally:
                monitor.stop()

    def test_change_arriving_during_scan_remains_pending_for_a_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            data = game / "data"
            game.mkdir()
            (game / "Warhammer3.exe").write_bytes(b"MZ")
            write_pack(data / "example.pack")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            api = API(root / "state")
            api.settings_service.save(
                {
                    "game_path": str(game),
                    "workshop_path": str(root / "workshop"),
                    "live_mod_detection": False,
                }
            )
            api._record_mod_change()
            original_scan = api.scanner.scan

            def scan_with_concurrent_change(*args: object, **kwargs: object):
                result = original_scan(*args, **kwargs)
                api._record_mod_change()
                return result

            with patch.object(api.scanner, "scan", side_effect=scan_with_concurrent_change):
                scanned = api.call("scan_mods", [False])

            self.assertTrue(scanned["ok"])
            self.assertEqual(scanned["data"]["mod_revision"], 1)
            self.assertEqual(api._mod_revision_value(), 2)


if __name__ == "__main__":
    unittest.main()
