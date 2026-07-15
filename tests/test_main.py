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
from scripts import build as build_script
from scripts.build import (
    DEFAULT_RELEASE_DIR,
    EXECUTABLE_NAME,
    PYINSTALLER_BUNDLE_NAME,
    package_desktop,
)


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
        self.assertEqual(PYINSTALLER_BUNDLE_NAME, "WycccModManager")
        self.assertNotIn("'", PYINSTALLER_BUNDLE_NAME)
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

    def test_packaging_uses_a_spec_safe_name_then_restores_the_public_exe_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frontend = root / "frontend"
            packaging = root / "packaging"
            steam_runtime = root / "steam_runtime"
            output = root / "release"
            (frontend / "dist").mkdir(parents=True)
            packaging.mkdir()
            (steam_runtime / "steamworks" / "dist" / "win64").mkdir(parents=True)
            (frontend / "dist" / "index.html").write_text("fixture", encoding="utf-8")
            (packaging / "wmm.ico").write_bytes(b"icon")
            (packaging / "version_info.txt").write_text("fixture", encoding="utf-8")
            (steam_runtime / "workshop_bridge.js").write_text("fixture", encoding="utf-8")
            native_binding = (
                steam_runtime
                / "steamworks"
                / "dist"
                / "win64"
                / "steamworksjs.win32-x64-msvc.node"
            )
            native_binding.write_bytes(b"fixture")
            node = root / "node.exe"
            node.write_bytes(b"fixture")
            commands: list[list[str]] = []

            def fake_run(command: list[str], *, cwd: Path = root) -> None:
                commands.append(command)
                internal_name = command[command.index("--name") + 1]
                dist_path = Path(command[command.index("--distpath") + 1])
                dist_path.mkdir(parents=True, exist_ok=True)
                (dist_path / f"{internal_name}.exe").write_bytes(b"packaged")

            with (
                patch.multiple(
                    build_script,
                    ROOT=root,
                    FRONTEND=frontend,
                    PACKAGING=packaging,
                    STEAM_RUNTIME=steam_runtime,
                ),
                patch.object(build_script, "find_node_for_packaging", return_value=node),
                patch.object(build_script, "run", side_effect=fake_run),
            ):
                executable = package_desktop(output)

            self.assertEqual(
                executable,
                (output / "Wyccc's Mod Manager.exe").resolve(strict=False),
            )
            self.assertEqual(executable.read_bytes(), b"packaged")
            self.assertFalse((output / "WycccModManager.exe").exists())
            pyinstaller_command = commands[-1]
            self.assertEqual(
                pyinstaller_command[pyinstaller_command.index("--name") + 1],
                "WycccModManager",
            )


if __name__ == "__main__":
    unittest.main()
