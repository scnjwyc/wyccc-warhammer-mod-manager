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
from main import ensure_single_instance
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
        fake_window = Mock()
        fake_webview = SimpleNamespace(create_window=Mock(return_value=fake_window), start=Mock())
        with patch.dict(sys.modules, {"webview": fake_webview}):
            result = run_desktop(object(), "file:///index.html")

        self.assertEqual(result, 0)
        self.assertEqual(fake_webview.create_window.call_args.args[0], "Wyccc's Mod Manager")
        self.assertTrue(fake_webview.create_window.call_args.kwargs["maximized"])

    def test_game_running_starts_on_the_static_low_consumption_page(self) -> None:
        fake_window = Mock()
        fake_webview = SimpleNamespace(create_window=Mock(return_value=fake_window), start=Mock())
        api = Mock()
        with patch.dict(sys.modules, {"webview": fake_webview}):
            result = run_desktop(
                api,
                "file:///index.html",
                idle_url="file:///idle.html",
                initial_game_running=True,
            )

        self.assertEqual(result, 0)
        self.assertEqual(fake_webview.create_window.call_args.args[1], "file:///idle.html")
        api.set_game_running.assert_called_with(True, force=True)
        api.bind_low_consumption_exit.assert_called_once()
        self.assertTrue(callable(api.bind_low_consumption_exit.call_args.args[0]))

    def test_second_launch_signals_the_existing_window_without_showing_an_error(self) -> None:
        with (
            patch("main.os.name", "nt"),
            patch("main._create_instance_mutex", return_value=(123, True)),
            patch("main._close_handle") as close_handle,
            patch("main._signal_existing_instance", return_value=True) as signal,
        ):
            self.assertFalse(ensure_single_instance())

        close_handle.assert_called_once_with(123)
        signal.assert_called_once_with()

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
        frontend_store = (root / "frontend" / "src" / "store.js").read_text(encoding="utf-8")
        version_info = (root / "packaging" / "version_info.txt").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        readme_en = (root / "README.en.md").read_text(encoding="utf-8")
        update_manifest = json.loads(
            (root / "packaging" / "update-manifest.json").read_text(encoding="utf-8")
        )
        changelog = get_all_changelogs()

        self.assertEqual(APP_VERSION, "0.6.5")
        self.assertEqual(project["project"]["version"], APP_VERSION)
        self.assertEqual(frontend["version"], APP_VERSION)
        self.assertIn("appVersion: '0.6.5'", frontend_store)
        self.assertIn("filevers=(0, 6, 5, 0)", version_info)
        self.assertIn("StringStruct('ProductVersion', '0.6.5')", version_info)
        self.assertIn("`0.6.5`", readme)
        self.assertIn("`0.6.5`", readme_en)
        self.assertEqual(update_manifest["schema_version"], 1)
        self.assertEqual(update_manifest["app"], APP_NAME)
        self.assertEqual(update_manifest["version"], APP_VERSION)
        self.assertFalse(is_newer_version(update_manifest["version"], APP_VERSION))
        self.assertEqual(changelog[0]["version"], APP_VERSION)
        manifest_release = changelog[0]
        self.assertEqual(update_manifest["published_at"], manifest_release["date"])
        self.assertEqual(update_manifest["changelog"], manifest_release["entries"])
        self.assertTrue(update_manifest["download"]["url"].startswith("https://"))
        self.assertEqual(len(update_manifest["download"]["sha256"]), 64)
        self.assertGreater(update_manifest["download"]["size"], 0)
        self.assertEqual(
            [release["version"] for release in changelog[:6]],
            ["0.6.5", "0.6.0", "0.5.0", "0.3.0", "0.2.0", "0.1.0"],
        )
        previous_release = changelog[1]
        self.assertEqual(previous_release["version"], "0.6.0")
        self.assertIn("低消耗模式", str(previous_release))
        self.assertIn("即时 MOD 增删检测", str(previous_release))
        self.assertIn("官方 MOD 启动器", str(previous_release))
        self.assertIn("Windows 回收站", str(previous_release))
        for donation_term in ("捐赠", "二维码", "收款码", "打赏"):
            self.assertNotIn(donation_term, str(changelog[0]))
        self.assertIn("Data", str(changelog[3]))
        self.assertIn("Gitee", str(changelog[4]))
        self.assertNotIn("Gitee", str(changelog[5]))

    def test_changelog_is_available_in_every_built_in_language(self) -> None:
        languages = ("zh-CN", "en-US", "ko-KR", "ru-RU", "ja-JP")
        localized = {language: get_all_changelogs(language) for language in languages}

        for releases in localized.values():
            self.assertEqual(
                [release["version"] for release in releases[:6]],
                ["0.6.5", "0.6.0", "0.5.0", "0.3.0", "0.2.0", "0.1.0"],
            )
            self.assertEqual(len(releases[0]["entries"]), 3)
            self.assertEqual(len(releases[1]["entries"]), 4)
            self.assertIn("Dynamic Unit Size", str(releases[1]))
            self.assertIn("Dynamic No Friendly Fire", str(releases[1]))
            self.assertNotIn("wyccc_dynamic_unit_size.pack", str(releases[1]))
            self.assertNotIn("wyccc_dynamic_no_friendly_fire.pack", str(releases[1]))
        titles = {
            language: releases[0]["entries"][0]["title"]
            for language, releases in localized.items()
        }
        self.assertEqual(len(set(titles.values())), len(languages))
        self.assertIn("low-consumption mode", str(localized["en-US"]))
        self.assertIn("游戏数据修改", str(localized["zh-CN"]))
        self.assertIn("订阅", str(localized["zh-CN"]))
        self.assertIn("恢复缺失的工坊 MOD 文件", str(localized["zh-CN"]))
        self.assertIn("Game data modification", str(localized["en-US"]))
        self.assertIn("저소비 모드", str(localized["ko-KR"]))
        self.assertIn("режим низкого потребления", str(localized["ru-RU"]))
        self.assertIn("低消費モード", str(localized["ja-JP"]))
        expected_multiplier_ranges = {
            "zh-CN": "0.5–5 倍",
            "en-US": "0.5× to 5×",
            "ko-KR": "0.5~5배",
            "ru-RU": "от 0,5 до 5 раз",
            "ja-JP": "0.5～5 倍",
        }
        for language, expected_range in expected_multiplier_ranges.items():
            self.assertIn(expected_range, str(localized[language][1]), language)
        expected_patch_generation = {
            "zh-CN": "一键生成补丁",
            "en-US": "generate the patch",
            "ko-KR": "패치를 생성",
            "ru-RU": "создать патч",
            "ja-JP": "パッチを生成",
        }
        for language, expected_text in expected_patch_generation.items():
            self.assertIn(expected_text, str(localized[language][1]), language)
        expected_automatic_updates = {
            "zh-CN": "保存更改时也会自动更新",
            "en-US": "automatic updates when changes are saved",
            "ko-KR": "변경 사항을 저장하면 자동으로 업데이트",
            "ru-RU": "автоматически обновляется при сохранении изменений",
            "ja-JP": "変更を保存すると自動的に更新",
        }
        for language, expected_text in expected_automatic_updates.items():
            self.assertIn(expected_text, str(localized[language][1]), language)

    def test_060_changelog_is_concise_and_describes_user_benefits(self) -> None:
        languages = ("zh-CN", "en-US", "ko-KR", "ru-RU", "ja-JP")
        implementation_terms = (
            "webview2",
            "warhammer3.exe",
            "getqueryugcchildren",
            "steamworks",
            "modprofiles",
            ".twmods",
            "runtime db",
            "运行时 db",
            "런타임 db",
            "рабочая бд",
            "実行時 db",
            "backend",
            "бэкенд",
        )

        for language in languages:
            release = get_all_changelogs(language)[1]
            self.assertEqual([len(entry["changes"]) for entry in release["entries"]], [3, 3, 4, 4])
            visible_copy = " ".join(
                [entry["title"] for entry in release["entries"]]
                + [
                    change["text"]
                    for entry in release["entries"]
                    for change in entry["changes"]
                ]
            )
            folded = visible_copy.casefold()
            for term in implementation_terms:
                self.assertNotIn(term.casefold(), folded, f"{language}: {term}")
            for entry in release["entries"]:
                self.assertLessEqual(len(entry["title"]), 60, language)
                for change in entry["changes"]:
                    self.assertLessEqual(len(change["text"]), 180, language)

    def test_065_changelog_is_concise_and_contains_only_user_visible_changes(self) -> None:
        languages = ("zh-CN", "en-US", "ko-KR", "ru-RU", "ja-JP")
        implementation_terms = (
            "fingerprint",
            "sha-256",
            "http",
            "steamworks",
            "bonus_hit_points",
            "packentry",
            "zero-byte",
            "db.pack",
            "retry",
            "指纹",
            "哈希",
            "并发",
            "退避",
            "字段",
        )

        for language in languages:
            release = get_all_changelogs(language)[0]
            self.assertEqual(release["version"], "0.6.5")
            self.assertEqual([len(entry["changes"]) for entry in release["entries"]], [3, 2, 1])
            visible_copy = " ".join(
                [entry["title"] for entry in release["entries"]]
                + [
                    change["text"]
                    for entry in release["entries"]
                    for change in entry["changes"]
                ]
            )
            folded = visible_copy.casefold()
            for term in implementation_terms:
                self.assertNotIn(term.casefold(), folded, f"{language}: {term}")
            for entry in release["entries"]:
                self.assertLessEqual(len(entry["title"]), 60, language)
                for change in entry["changes"]:
                    self.assertLessEqual(len(change["text"]), 160, language)

        chinese = str(get_all_changelogs("zh-CN")[0])
        self.assertIn("自动校验", chinese)
        self.assertIn("1–5", chinese)
        self.assertIn("领主与英雄血量", chinese)
        self.assertIn("作者昵称", chinese)
        self.assertIn("浏览器", chinese)
        self.assertIn("Steam 客户端", chinese)
        self.assertIn("跳过开场动画", chinese)

    def test_agents_requires_concise_function_focused_changelogs(self) -> None:
        agents = (
            Path(__file__).resolve().parents[1] / "AGENTS.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "更新日志必须简洁明了，只介绍用户可见的功能与修复，不描述实现细节。",
            agents,
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
            backend = root / "backend"
            output = root / "release"
            (frontend / "dist").mkdir(parents=True)
            packaging.mkdir()
            backend.mkdir()
            (steam_runtime / "steamworks" / "dist" / "win64").mkdir(parents=True)
            (steam_runtime / "steamworks_dependencies" / "dist" / "win64").mkdir(
                parents=True
            )
            (frontend / "dist" / "index.html").write_text("fixture", encoding="utf-8")
            (packaging / "wmm.ico").write_bytes(b"icon")
            (packaging / "version_info.txt").write_text("fixture", encoding="utf-8")
            schema_path = backend / "wh3_db_schema.json"
            schema_path.write_text("{}", encoding="utf-8")
            (steam_runtime / "workshop_bridge.js").write_text("fixture", encoding="utf-8")
            native_binding = (
                steam_runtime
                / "steamworks"
                / "dist"
                / "win64"
                / "steamworksjs.win32-x64-msvc.node"
            )
            native_binding.write_bytes(b"fixture")
            dependency_runtime = steam_runtime / "steamworks_dependencies" / "dist" / "win64"
            (dependency_runtime / "steamworksjs.win32-x64-msvc.node").write_bytes(b"fixture")
            (dependency_runtime / "steam_api64.dll").write_bytes(b"fixture")
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
            separator = ";" if os.name == "nt" else ":"
            self.assertIn(f"{schema_path}{separator}backend", pyinstaller_command)


if __name__ == "__main__":
    unittest.main()
