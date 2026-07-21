from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app_settings import SettingsService, default_settings, detect_system_language
from backend.models import GamePaths


class SettingsMigrationTests(unittest.TestCase):
    def test_schema_eleven_migrates_legacy_paths_only_to_warhammer_three(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "schema_version": 11,
                        "game_path": "D:/Steam/steamapps/common/Total War WARHAMMER III",
                        "workshop_path": "D:/Steam/steamapps/workshop/content/1142710",
                        "update_manifest_url": "https://obsolete.example/manifest.json",
                    }
                ),
                encoding="utf-8",
            )

            migrated = SettingsService(data_dir).get()

        self.assertEqual(migrated["schema_version"], 16)
        self.assertEqual(migrated["selected_game"], "warhammer3")
        self.assertTrue(
            migrated["game_installations"]["warhammer3"]["game_path"].endswith(
                "Total War WARHAMMER III"
            )
        )
        self.assertEqual(
            migrated["game_installations"]["three_kingdoms"],
            {"game_path": "", "workshop_path": ""},
        )
        self.assertNotIn("game_path", migrated)
        self.assertNotIn("workshop_path", migrated)
        self.assertNotIn("update_manifest_url", migrated)

    def test_game_switch_preserves_each_game_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))
            saved = service.save(
                {
                    "selected_game": "three_kingdoms",
                    "game_installations": {
                        "warhammer3": {
                            "game_path": "D:/Steam/steamapps/common/Total War WARHAMMER III",
                            "workshop_path": "D:/Steam/steamapps/workshop/content/1142710",
                        },
                        "three_kingdoms": {
                            "game_path": "E:/Steam/steamapps/common/Total War THREE KINGDOMS",
                            "workshop_path": "E:/Steam/steamapps/workshop/content/779340",
                        },
                    },
                }
            )

        self.assertEqual(saved["selected_game"], "three_kingdoms")
        self.assertTrue(
            saved["game_installations"]["warhammer3"]["game_path"].endswith(
                "Total War WARHAMMER III"
            )
        )
        self.assertTrue(
            saved["game_installations"]["three_kingdoms"]["game_path"].endswith(
                "Total War THREE KINGDOMS"
            )
        )

    def test_three_kingdoms_detection_keeps_a_previously_manual_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manual_game = root / "Custom Three Kingdoms"
            manual_workshop = root / "Custom Workshop"
            service = SettingsService(root / "state")
            service.save(
                {
                    "selected_game": "three_kingdoms",
                    "game_installations": {
                        "three_kingdoms": {
                            "game_path": str(manual_game),
                            "workshop_path": str(manual_workshop),
                        }
                    },
                }
            )

            with patch(
                "backend.app_settings.discover_game_paths",
                return_value=GamePaths(game_id="three_kingdoms"),
            ):
                result = service.detect_and_save("three_kingdoms")

        self.assertFalse(result["found"])
        self.assertEqual(Path(result["paths"]["game_path"]), manual_game.resolve())
        self.assertEqual(Path(result["paths"]["workshop_path"]), manual_workshop.resolve())

    def test_new_installs_enable_background_workshop_refresh(self) -> None:
        self.assertTrue(default_settings()["fetch_workshop_metadata"])
        self.assertTrue(default_settings()["live_mod_detection"])
        self.assertTrue(default_settings()["keyboard_shortcuts_enabled"])
        self.assertEqual(default_settings()["schema_version"], 16)
        self.assertEqual(
            default_settings()["workshop_page_open_counts"],
            {"browser": 0, "client": 0},
        )
        self.assertEqual(default_settings()["language"], "en-US")
        for removed_key in (
            "rpfm_path",
            "scan_data",
            "scan_modding",
            "scan_workshop",
            "scan_merged",
        ):
            self.assertNotIn(removed_key, default_settings())
        self.assertFalse(default_settings()["check_outdated_mods"])
        self.assertFalse(default_settings()["search_highlight_mode"])
        self.assertFalse(default_settings()["ai_enabled"])
        self.assertFalse(default_settings()["custom_battle_all_units_as_lords"])
        self.assertFalse(default_settings()["enable_script_logging"])
        self.assertFalse(default_settings()["skip_intro_movies"])
        self.assertEqual(default_settings()["unit_model_multiplier"], 1)
        self.assertEqual(default_settings()["unit_recruitment_capacity_multiplier"], 1)
        self.assertEqual(default_settings()["single_entity_unit_mode"], "scale")
        self.assertFalse(default_settings()["scale_lord_hero_health"])
        self.assertFalse(default_settings()["disable_unit_friendly_fire"])
        self.assertFalse(default_settings()["disable_spell_friendly_fire"])
        self.assertTrue(default_settings()["check_updates_automatically"])
        self.assertNotIn("update_manifest_url", default_settings())
        self.assertEqual(default_settings()["last_update_check_at"], 0)
        self.assertEqual(default_settings()["last_seen_app_version"], "0.9.0")

    def test_workshop_page_open_preference_counts_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))
            saved = service.save(
                {"workshop_page_open_counts": {"browser": "9", "client": -2}}
            )

        self.assertEqual(saved["workshop_page_open_counts"], {"browser": 9, "client": 0})

    def test_search_highlight_mode_is_persisted_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))

            self.assertTrue(service.save({"search_highlight_mode": 1})["search_highlight_mode"])
            self.assertTrue(service.get()["search_highlight_mode"])
            self.assertFalse(service.save({"search_highlight_mode": ""})["search_highlight_mode"])

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
            self.assertEqual(migrated["schema_version"], 16)
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

            self.assertEqual(migrated["schema_version"], 16)
            self.assertEqual(migrated["language"], "zh-CN")
            self.assertFalse(migrated["fetch_workshop_metadata"])
            self.assertNotIn("scan_merged", migrated)

    def test_language_setting_accepts_supported_codes_and_rejects_unknown_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))

            self.assertEqual(service.save({"language": "ja-JP"})["language"], "ja-JP")
            self.assertEqual(service.save({"language": "es-ES"})["language"], "es-ES")
            self.assertEqual(service.save({"language": "unsupported"})["language"], "en-US")

    def test_first_launch_detects_and_persists_supported_system_languages(self) -> None:
        cases = {
            "zh-CN": "zh-CN",
            "zh-Hant-TW": "zh-CN",
            "en-GB": "en-US",
            "ko_KR": "ko-KR",
            "ru-RU.UTF-8": "ru-RU",
            "ja-JP": "ja-JP",
            "es-MX": "es-ES",
        }
        for system_locale, expected in cases.items():
            with self.subTest(system_locale=system_locale), tempfile.TemporaryDirectory() as temporary:
                data_dir = Path(temporary)
                with patch(
                    "backend.app_settings._system_locale_name",
                    return_value=system_locale,
                ):
                    first = SettingsService(data_dir).get()
                self.assertEqual(first["language"], expected)
                self.assertEqual(
                    json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))["language"],
                    expected,
                )

                with patch(
                    "backend.app_settings._system_locale_name",
                    return_value="zh-CN" if expected != "zh-CN" else "en-US",
                ):
                    reopened = SettingsService(data_dir).get()
                self.assertEqual(reopened["language"], expected)

    def test_system_language_detection_falls_back_to_english(self) -> None:
        cases = (
            {"return_value": "fr-FR"},
            {"side_effect": OSError("locale unavailable")},
        )
        for mocked_detection in cases:
            with self.subTest(mocked_detection=mocked_detection), tempfile.TemporaryDirectory() as temporary:
                with patch(
                    "backend.app_settings._system_locale_name",
                    **mocked_detection,
                ):
                    self.assertEqual(detect_system_language(), "en-US")
                    settings = SettingsService(Path(temporary)).get()
                self.assertEqual(settings["language"], "en-US")

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

            self.assertEqual(migrated["schema_version"], 16)
            self.assertEqual(migrated["language"], "ja-JP")
            self.assertFalse(migrated["fetch_workshop_metadata"])
            self.assertTrue(migrated["check_updates_automatically"])
        self.assertEqual(migrated["last_seen_app_version"], "0.9.0")

    def test_schema_eight_settings_enable_live_mod_detection_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "schema_version": 8,
                        "language": "zh-CN",
                        "live_mod_detection": False,
                    }
                ),
                encoding="utf-8",
            )

            migrated = SettingsService(data_dir).get()

            self.assertEqual(migrated["schema_version"], 16)
            self.assertFalse(migrated["live_mod_detection"])

            fresh_legacy = data_dir / "fresh-legacy"
            (fresh_legacy / "settings.json").parent.mkdir(parents=True)
            (fresh_legacy / "settings.json").write_text(
                json.dumps({"schema_version": 8, "language": "zh-CN"}),
                encoding="utf-8",
            )
            self.assertTrue(SettingsService(fresh_legacy).get()["live_mod_detection"])

    def test_keyboard_shortcut_preference_is_persisted_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))

            self.assertTrue(service.get()["keyboard_shortcuts_enabled"])
            self.assertFalse(
                service.save({"keyboard_shortcuts_enabled": ""})[
                    "keyboard_shortcuts_enabled"
                ]
            )
            self.assertFalse(service.get()["keyboard_shortcuts_enabled"])
            self.assertTrue(
                service.save({"keyboard_shortcuts_enabled": 1})[
                    "keyboard_shortcuts_enabled"
                ]
            )

    def test_keyboard_shortcut_bindings_are_persisted_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))
            self.assertEqual(service.get()["keyboard_shortcuts"]["open-workshop"], "Shift+W")
            saved = service.save(
                {
                    "keyboard_shortcuts": {
                        "open-workshop": " alt + shift + k ",
                        "open-rpfm": "Shift",
                        "unknown": "Ctrl+X",
                    }
                }
            )
            self.assertEqual(saved["keyboard_shortcuts"]["open-workshop"], "Alt+Shift+K")
            self.assertEqual(saved["keyboard_shortcuts"]["open-rpfm"], "Shift+R")
            self.assertNotIn("unknown", saved["keyboard_shortcuts"])

    def test_game_data_settings_are_clamped_normalized_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))

            saved = service.save(
                {
                    "unit_model_multiplier": "75.5",
                    "unit_recruitment_capacity_multiplier": "75.5",
                    "single_entity_unit_mode": "health",
                    "scale_lord_hero_health": 1,
                    "disable_unit_friendly_fire": 1,
                    "disable_spell_friendly_fire": "",
                }
            )

            self.assertEqual(saved["unit_model_multiplier"], 5)
            self.assertEqual(saved["unit_recruitment_capacity_multiplier"], 5)
            self.assertEqual(saved["single_entity_unit_mode"], "health")
            self.assertTrue(saved["scale_lord_hero_health"])
            self.assertTrue(saved["disable_unit_friendly_fire"])
            self.assertFalse(saved["disable_spell_friendly_fire"])
            reopened = SettingsService(Path(temporary)).get()
            self.assertEqual(reopened["unit_model_multiplier"], 5)
            self.assertEqual(reopened["unit_recruitment_capacity_multiplier"], 5)
            self.assertEqual(reopened["single_entity_unit_mode"], "health")
            self.assertTrue(reopened["scale_lord_hero_health"])

            self.assertEqual(
                service.save({"single_entity_unit_mode": "unexpected"})[
                    "single_entity_unit_mode"
                ],
                "scale",
            )
            self.assertTrue(reopened["disable_unit_friendly_fire"])

            self.assertEqual(
                service.save({"unit_model_multiplier": "0.1"})["unit_model_multiplier"],
                1,
            )

            self.assertEqual(
                service.save({"unit_model_multiplier": "invalid"})["unit_model_multiplier"],
                1,
            )
            self.assertEqual(
                service.save({"unit_model_multiplier": 2.5})["unit_model_multiplier"],
                3,
            )
            self.assertEqual(
                service.save({"unit_recruitment_capacity_multiplier": 0})[
                    "unit_recruitment_capacity_multiplier"
                ],
                0,
            )
            self.assertEqual(
                service.save({"unit_recruitment_capacity_multiplier": "invalid"})[
                    "unit_recruitment_capacity_multiplier"
                ],
                1,
            )

    def test_normalize_changes_previews_values_without_persisting_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = SettingsService(Path(temporary))
            normalize_changes = getattr(service, "normalize_changes", None)

            self.assertTrue(callable(normalize_changes))
            if not callable(normalize_changes):
                return
            normalized = normalize_changes({"unit_model_multiplier": "2.5"})

            self.assertEqual(normalized["unit_model_multiplier"], 3)
            self.assertEqual(service.get()["unit_model_multiplier"], 1)


if __name__ == "__main__":
    unittest.main()
