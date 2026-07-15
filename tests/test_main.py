from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.constants import APP_NAME
from main import main as run_app
from main import resolve_runtime_data_dir, run_desktop
from scripts.build import DEFAULT_RELEASE_DIR, EXECUTABLE_NAME


class PackagedRuntimeTests(unittest.TestCase):
    def test_desktop_window_starts_maximized(self) -> None:
        fake_webview = SimpleNamespace(create_window=Mock(), start=Mock())
        with patch.dict(sys.modules, {"webview": fake_webview}):
            result = run_desktop(object(), "file:///index.html")

        self.assertEqual(result, 0)
        self.assertEqual(fake_webview.create_window.call_args.args[0], "Wyccc's Mod Manager")
        self.assertTrue(fake_webview.create_window.call_args.kwargs["maximized"])

    def test_windows_release_branding_and_default_output_directory(self) -> None:
        self.assertEqual(APP_NAME, "Wyccc's Mod Manager")
        self.assertEqual(EXECUTABLE_NAME, "Wyccc's Mod Manager")
        if os.name == "nt":
            self.assertEqual(
                DEFAULT_RELEASE_DIR,
                Path(r"G:\Wyccc's Mod Manager"),
            )

    def test_desktop_mode_requires_pywebview(self) -> None:
        with patch.dict(sys.modules, {"webview": None}):
            with self.assertRaisesRegex(RuntimeError, "desktop mode"):
                run_desktop(object(), "file:///index.html")

    def test_browser_mode_flag_is_not_supported(self) -> None:
        with (
            patch.object(sys, "argv", ["main.py", "--browser"]),
            patch.object(sys, "stderr", io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as raised:
                run_app()

        self.assertEqual(raised.exception.code, 2)

    def test_frozen_build_uses_portable_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "Wyccc's Mod Manager.exe"
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(executable)),
                patch.dict(os.environ, {}, clear=True),
            ):
                data_dir = resolve_runtime_data_dir()

            self.assertEqual(data_dir, (root / "data").resolve())
            self.assertTrue(data_dir.is_dir())

    def test_explicit_data_directory_wins_in_frozen_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "custom"
            with patch.object(sys, "frozen", True, create=True):
                self.assertEqual(resolve_runtime_data_dir(str(target)), target.resolve())


if __name__ == "__main__":
    unittest.main()
