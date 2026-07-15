from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.changelog import get_all_changelogs
from backend.constants import APP_NAME, APP_VERSION
from backend.update_service import is_newer_version
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

    def test_release_version_and_changelog_are_synchronized(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        frontend = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
        version_info = (root / "packaging" / "version_info.txt").read_text(encoding="utf-8")
        update_manifest = json.loads(
            (root / "packaging" / "update-manifest.json").read_text(encoding="utf-8")
        )
        changelog = get_all_changelogs()

        self.assertEqual(APP_VERSION, "0.5.0")
        self.assertEqual(project["project"]["version"], APP_VERSION)
        self.assertEqual(frontend["version"], APP_VERSION)
        self.assertIn("filevers=(0, 5, 0, 0)", version_info)
        self.assertIn("StringStruct('ProductVersion', '0.5.0')", version_info)
        self.assertEqual(update_manifest["schema_version"], 1)
        self.assertEqual(update_manifest["app"], APP_NAME)
        self.assertEqual(update_manifest["version"], APP_VERSION)
        self.assertFalse(is_newer_version(update_manifest["version"], APP_VERSION))
        manifest_release = changelog[0]
        self.assertEqual(manifest_release["version"], APP_VERSION)
        self.assertEqual(update_manifest["published_at"], manifest_release["date"])
        self.assertEqual(update_manifest["changelog"], manifest_release["entries"])
        self.assertTrue(update_manifest["download"]["url"].startswith("https://"))
        self.assertEqual(len(update_manifest["download"]["sha256"]), 64)
        self.assertGreater(update_manifest["download"]["size"], 0)
        self.assertEqual(
            [release["version"] for release in changelog[:4]],
            ["0.5.0", "0.3.0", "0.2.0", "0.1.0"],
        )
        self.assertIn("创意工坊", str(changelog[0]))
        self.assertIn("系统语言", str(changelog[0]))
        self.assertIn("时间比较方向", str(changelog[0]))
        self.assertIn("只检查已启用 MOD", str(changelog[0]))
        self.assertIn("正在使用缓存", str(changelog[0]))
        self.assertIn("RimCrow", str(changelog[0]))
        for donation_term in ("捐赠", "二维码", "收款码", "打赏"):
            self.assertNotIn(donation_term, str(changelog[0]))
        self.assertIn("Data", str(changelog[1]))
        self.assertIn("Gitee", str(changelog[2]))
        self.assertNotIn("Gitee", str(changelog[3]))

    def test_changelog_is_available_in_every_built_in_language(self) -> None:
        languages = ("zh-CN", "en-US", "ko-KR", "ru-RU", "ja-JP")
        localized = {language: get_all_changelogs(language) for language in languages}

        for releases in localized.values():
            self.assertEqual(
                [release["version"] for release in releases[:4]],
                ["0.5.0", "0.3.0", "0.2.0", "0.1.0"],
            )
        titles = {
            language: releases[0]["entries"][0]["title"]
            for language, releases in localized.items()
        }
        self.assertEqual(len(set(titles.values())), len(languages))
        self.assertIn("Built-in languages", str(localized["en-US"]))
        self.assertIn("내장 다국어", str(localized["ko-KR"]))
        self.assertIn("Встроенные языки", str(localized["ru-RU"]))
        self.assertIn("内蔵多言語", str(localized["ja-JP"]))
        self.assertIn("Warning detection and messaging fixes", str(localized["en-US"]))
        self.assertIn("경고 감지 및 안내 수정", str(localized["ko-KR"]))
        self.assertIn("Исправления проверки и сообщений", str(localized["ru-RU"]))
        self.assertIn("警告判定と案内の修正", str(localized["ja-JP"]))

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
