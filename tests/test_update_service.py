from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app_settings import SettingsService
from backend.constants import GITEE_UPDATE_MANIFEST_URL, GITHUB_UPDATE_MANIFEST_URL
from backend.update_service import UpdateService, is_newer_version


class UpdateServiceTests(unittest.TestCase):
    @staticmethod
    def _manifest(version: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "app": "Wyccc's Mod Manager",
            "version": version,
            "published_at": "2026-07-15",
            "download": {
                "url": "https://downloads.example.test/WycccModManager.exe",
                "sha256": "1" * 64,
                "size": 1234,
            },
            "changelog": ["测试更新"],
        }

    def test_semantic_version_comparison_handles_stable_and_prerelease_versions(self) -> None:
        self.assertTrue(is_newer_version("0.1.1", "0.1.0"))
        self.assertTrue(is_newer_version("v1.0.0", "0.9.9"))
        self.assertTrue(is_newer_version("1.0.0", "1.0.0-rc.2"))
        self.assertFalse(is_newer_version("1.0.0-rc.1", "1.0.0"))
        self.assertFalse(is_newer_version("0.1", "0.1.0"))

    def test_local_manifest_check_download_hash_and_ignore_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "Wyccc's Mod Manager.exe"
            executable.write_bytes(b"MZ" + b"release-fixture" * 20)
            data = executable.read_bytes()
            manifest = root / "update-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "app": "Wyccc's Mod Manager",
                        "version": "0.8.7",
                        "published_at": "2026-07-15",
                        "download": {
                            "url": executable.name,
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "size": len(data),
                        },
                        "changelog": [
                            {
                                "title": "自动更新",
                                "changes": [{"type": "feature", "text": "新增安全更新。"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            settings = SettingsService(root / "state")
            service = UpdateService(root / "state", settings)
            service.preferred_repository_sources = lambda _language: (("fixture", manifest.as_uri()),)

            checked = service.check(manual=False)
            self.assertTrue(checked["has_update"])
            self.assertEqual(checked["status"], "remote")
            self.assertEqual(checked["entries"][0]["changes"][0]["type"], "feature")
            self.assertGreater(settings.get()["last_update_check_at"], 0)

            downloaded = service.download("0.8.7")
            self.assertEqual(downloaded["status"], "ready")
            self.assertTrue(Path(downloaded["local_path"]).is_file())
            self.assertEqual(Path(downloaded["local_path"]).read_bytes(), data)

            service.ignore("0.8.7")
            ignored = service.check(manual=False)
            self.assertFalse(ignored["has_update"])
            self.assertTrue(ignored["ignored"])
            manual = service.check(manual=True)
            self.assertTrue(manual["has_update"])

    def test_download_rejects_a_hash_mismatch_and_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "bad.exe"
            executable.write_bytes(b"MZbad-update")
            manifest = root / "update-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.8.7",
                        "download_url": executable.name,
                        "sha256": "0" * 64,
                        "size": executable.stat().st_size,
                    }
                ),
                encoding="utf-8",
            )
            settings = SettingsService(root / "state")
            service = UpdateService(root / "state", settings)
            service.preferred_repository_sources = lambda _language: (("fixture", manifest.as_uri()),)
            service.check()

            with self.assertRaisesRegex(ValueError, "SHA-256"):
                service.download()

            self.assertFalse(any((root / "state" / "updates").glob("*.part")))

    def test_automatic_check_respects_toggle_and_daily_interval(self) -> None:
        settings = {
            "check_updates_automatically": True,
            "last_update_check_at": 100,
        }
        self.assertFalse(UpdateService.should_check_automatically(settings, now=200))
        self.assertTrue(UpdateService.should_check_automatically(settings, now=100 + 86400))
        settings["check_updates_automatically"] = False
        self.assertFalse(UpdateService.should_check_automatically(settings, now=999999))

    def test_chinese_checks_gitee_then_github_and_prefers_gitee_on_a_tie(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = SettingsService(Path(temporary))
            settings.save({"language": "zh-CN"})
            service = UpdateService(Path(temporary), settings)
            calls: list[str] = []

            def read_manifest(url: str) -> tuple[dict[str, object], str]:
                calls.append(url)
                return self._manifest("0.5.0"), url

            with patch.object(service, "_read_json", side_effect=read_manifest):
                checked = service.check(manual=True)

            self.assertEqual(calls, [GITEE_UPDATE_MANIFEST_URL, GITHUB_UPDATE_MANIFEST_URL])
            self.assertEqual(checked["source"], "gitee")
            self.assertEqual(checked["sources_checked"], ["gitee", "github"])
            self.assertFalse(checked["has_update"])

    def test_non_chinese_checks_github_first_but_uses_a_newer_gitee_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = SettingsService(Path(temporary))
            settings.save({"language": "en-US"})
            service = UpdateService(Path(temporary), settings)
            calls: list[str] = []

            def read_manifest(url: str) -> tuple[dict[str, object], str]:
                calls.append(url)
                version = "0.5.0" if url == GITHUB_UPDATE_MANIFEST_URL else "0.8.7"
                return self._manifest(version), url

            with patch.object(service, "_read_json", side_effect=read_manifest):
                checked = service.check(manual=True)

            self.assertEqual(calls, [GITHUB_UPDATE_MANIFEST_URL, GITEE_UPDATE_MANIFEST_URL])
            self.assertEqual(checked["source"], "gitee")
            self.assertEqual(checked["version"], "0.8.7")
            self.assertTrue(checked["has_update"])

    def test_repository_check_falls_back_when_the_preferred_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = SettingsService(Path(temporary))
            settings.save({"language": "zh-CN"})
            service = UpdateService(Path(temporary), settings)

            def read_manifest(url: str) -> tuple[dict[str, object], str]:
                if url == GITEE_UPDATE_MANIFEST_URL:
                    raise OSError("Gitee unavailable")
                return self._manifest("0.8.7"), url

            with patch.object(service, "_read_json", side_effect=read_manifest):
                checked = service.check(manual=True)

            self.assertEqual(checked["source"], "github")
            self.assertEqual(checked["sources_checked"], ["gitee", "github"])
            self.assertTrue(checked["has_update"])

    def test_check_rejects_custom_channel_overrides_and_uses_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = SettingsService(Path(temporary))
            settings.save({"language": "zh-CN"})
            service = UpdateService(Path(temporary), settings)

            with patch.object(
                service,
                "_read_json",
                side_effect=lambda url: (self._manifest("0.5.0"), url),
            ):
                checked = service.check(manual=True)

            self.assertEqual(checked["source"], "gitee")
            self.assertNotIn("update_manifest_url", settings.get())
            with patch.object(
                service,
                "_read_json",
                side_effect=lambda url: (self._manifest("0.5.0"), url),
            ):
                with self.assertRaises(TypeError):
                    service.check(manual=True, manifest_url="https://custom.example.test/update.json")

    def test_installer_script_waits_replaces_restarts_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = SettingsService(root / "state")
            service = UpdateService(root / "state", settings)

            script = service._write_installer_script(
                root / "Wyccc's Mod Manager.exe",
                root / "state" / "updates" / "WycccModManager-0.4.0.exe",
            )
            content = script.read_text(encoding="utf-8-sig")

            self.assertIn("Get-Process -Id $parentPid", content)
            self.assertIn("Move-Item -LiteralPath $current -Destination $backup", content)
            self.assertIn("Copy-Item -LiteralPath $downloaded -Destination $current", content)
            self.assertIn("$started = Start-Process @startParameters", content)
            self.assertIn("Move-Item -LiteralPath $backup -Destination $current", content)
            self.assertIn("[string]::IsNullOrWhiteSpace($arguments)", content)
            self.assertEqual(content.count("$env:PYINSTALLER_RESET_ENVIRONMENT = '1'"), 2)
            self.assertIn(
                "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'\n"
                "        $started = Start-Process @startParameters",
                content,
            )
            self.assertIn(
                "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'\n"
                "        Start-Process @restartParameters",
                content,
            )
            powershell = shutil.which("powershell.exe") or shutil.which("powershell")
            if os.name == "nt" and powershell:
                environment = os.environ.copy()
                environment["WMM_SCRIPT_TO_PARSE"] = str(script)
                parsed = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        (
                            "$tokens=$null; $errors=$null; "
                            "[System.Management.Automation.Language.Parser]::ParseFile("
                            "$env:WMM_SCRIPT_TO_PARSE,[ref]$tokens,[ref]$errors) | Out-Null; "
                            "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }"
                        ),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    check=False,
                    env=environment,
                )
                self.assertEqual(parsed.returncode, 0, parsed.stderr)

    def test_install_rollback_error_is_reported_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = UpdateService(root / "state", SettingsService(root / "state"))
            service.update_dir.mkdir(parents=True)
            (service.update_dir / "install-error.log").write_text(
                "2026-07-15T00:00:00Z 新版本启动后立即退出",
                encoding="utf-8",
            )

            self.assertIn("新版本启动后立即退出", service.consume_install_error())
            self.assertEqual(service.consume_install_error(), "")


if __name__ == "__main__":
    unittest.main()
