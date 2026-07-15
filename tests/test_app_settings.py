from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app_settings import SettingsService, default_settings


class SettingsMigrationTests(unittest.TestCase):
    def test_new_installs_enable_background_workshop_refresh(self) -> None:
        self.assertTrue(default_settings()["fetch_workshop_metadata"])
        self.assertEqual(default_settings()["schema_version"], 7)
        self.assertEqual(default_settings()["language"], "zh-CN")
        for removed_key in (
            "rpfm_path",
            "scan_data",
            "scan_modding",
            "scan_workshop",
            "scan_merged",
        ):
            self.assertNotIn(removed_key, default_settings())
        self.assertFalse(default_settings()["check_outdated_mods"])
        self.assertFalse(default_settings()["ai_enabled"])
        self.assertFalse(default_settings()["custom_battle_all_units_as_lords"])
        self.assertFalse(default_settings()["enable_script_logging"])
        self.assertFalse(default_settings()["skip_intro_movies"])
        self.assertTrue(default_settings()["check_updates_automatically"])
        self.assertEqual(default_settings()["update_manifest_url"], "")
        self.assertEqual(default_settings()["last_update_check_at"], 0)
        self.assertEqual(default_settings()["last_seen_app_version"], "0.2.0")

    def test_schema_one_settings_migrate_to_background_refresh_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            settings_path = data_dir / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "fetch_workshop_metadata": False,
                    }
                ),
                encoding="utf-8",
            )
            service = SettingsService(data_dir)

            migrated = service.get()
            self.assertEqual(migrated["schema_version"], 7)
            self.assertTrue(migrated["fetch_workshop_metadata"])

            service.save({"fetch_workshop_metadata": False})
            self.assertFalse(service.get()["fetch_workshop_metadata"])

    def test_schema_two_settings_add_language_without_resetting_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "fetch_workshop_metadata": False,
                        "scan_merged": False,
                    }
                ),
                encoding="utf-8",
            )

            migrated = SettingsService(data_dir).get()

            self.assertEqual(migrated["schema_version"], 7)
            self.assertEqual(migrated["language"], "zh-CN")
            self.assertFalse(migrated["fetch_workshop_metadata"])
            self.assertNotIn("scan_merged", migrated)

    def test_language_setting_accepts_supported_codes_and_rejects_unknown_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))

            self.assertEqual(service.save({"language": "ja-JP"})["language"], "ja-JP")
            self.assertEqual(service.save({"language": "unsupported"})["language"], "zh-CN")

    def test_removed_rpfm_and_scan_settings_are_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary) / "state")
            executable = Path(temporary) / "tools" / "rpfm.exe"

            saved = service.save(
                {
                    "rpfm_path": str(executable),
                    "scan_modding": True,
                    "scan_merged": True,
                }
            )

            self.assertNotIn("rpfm_path", saved)
            self.assertNotIn("scan_modding", saved)
            self.assertNotIn("scan_merged", saved)

    def test_ai_key_is_masked_publicly_and_blank_saves_preserve_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))
            service.save(
                {
                    "ai_enabled": True,
                    "ai_api_key": "secret-key",
                    "ai_model": "test-model",
                }
            )

            public = service.get_public()
            self.assertEqual(public["ai_api_key"], "")
            self.assertTrue(public["ai_api_key_configured"])

            service.save({"ai_api_key": "", "ai_temperature": 9})
            self.assertEqual(service.get()["ai_api_key"], "secret-key")
            self.assertEqual(service.get()["ai_temperature"], 2.0)

            service.save({"clear_ai_api_key": True, "ai_api_key": ""})
            self.assertEqual(service.get()["ai_api_key"], "")

    def test_schema_six_settings_gain_update_preferences_without_resetting_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "schema_version": 6,
                        "language": "ja-JP",
                        "fetch_workshop_metadata": False,
                    }
                ),
                encoding="utf-8",
            )

            migrated = SettingsService(data_dir).get()

            self.assertEqual(migrated["schema_version"], 7)
            self.assertEqual(migrated["language"], "ja-JP")
            self.assertFalse(migrated["fetch_workshop_metadata"])
            self.assertTrue(migrated["check_updates_automatically"])
            self.assertEqual(migrated["last_seen_app_version"], "0.2.0")


if __name__ == "__main__":
    unittest.main()
