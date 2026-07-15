from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.constants import SOURCE_WORKSHOP
from backend.models import ModAsset
from backend.share import export_share, parse_pending_workshop_mod_id
from backend.storage import StateRepository
from tests.helpers import make_asset, write_pack


class StorageContractTests(unittest.TestCase):
    def test_schema_one_database_migrates_user_intent_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE system_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE user_mod_data (
                        mod_id TEXT PRIMARY KEY,
                        alias TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        updated_at INTEGER NOT NULL
                    );
                    INSERT INTO system_info(key, value) VALUES('schema_version', '1');
                    INSERT INTO user_mod_data(mod_id, alias, notes, updated_at)
                    VALUES('legacy', '旧别名', '旧备注', 1);
                    """
                )

            repository = StateRepository(database)

            self.assertEqual(
                repository.list_user_mod_data()["legacy"],
                {
                    "alias": "旧别名",
                    "notes": "旧备注",
                    "mod_type": "unknown",
                    "mod_types": ["unknown"],
                    "published_workshop_id": "",
                    "hidden": False,
                    "ignored_warning_codes": [],
                },
            )
            with closing(sqlite3.connect(database)) as connection:
                schema_version = connection.execute(
                    "SELECT value FROM system_info WHERE key = 'schema_version'"
                ).fetchone()[0]
            self.assertEqual(schema_version, "7")

    def test_legacy_presets_migrate_to_playsets_and_current_order_becomes_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE system_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE presets (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE TABLE preset_items (
                        preset_id TEXT NOT NULL REFERENCES presets(id) ON DELETE CASCADE,
                        mod_id TEXT NOT NULL,
                        position INTEGER NOT NULL,
                        PRIMARY KEY (preset_id, mod_id)
                    );
                    INSERT INTO system_info(key, value) VALUES('schema_version', '5');
                    INSERT INTO app_state(key, value)
                    VALUES('enabled_order', '["current-a", "current-b"]');
                    INSERT INTO presets(id, name, created_at, updated_at)
                    VALUES('legacy-preset', '旧预设', 1, 2);
                    INSERT INTO preset_items(preset_id, mod_id, position)
                    VALUES('legacy-preset', 'legacy-b', 0), ('legacy-preset', 'legacy-a', 1);
                    """
                )

            repository = StateRepository(database)

            self.assertEqual(repository.get_current_playset()["name"], "默认")
            self.assertEqual(repository.get_current_playset()["mod_ids"], ["current-a", "current-b"])
            migrated = next(item for item in repository.list_playsets() if item["name"] == "旧预设")
            self.assertEqual(migrated["mod_ids"], ["legacy-b", "legacy-a"])
            repository.switch_playset(migrated["id"])
            self.assertEqual(repository.get_enabled_order(), ["legacy-b", "legacy-a"])
            self.assertEqual(
                [item["name"] for item in StateRepository(database).list_playsets()],
                ["默认", "旧预设"],
            )

    def test_sqlite_schema_and_user_intent_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.db"
            repository = StateRepository(database)

            repository.set_enabled_order(["a", "a", "", "b"])
            self.assertEqual(repository.get_enabled_order(), ["a", "b"])
            repository.set_active_order_filename("my_mods.txt")
            self.assertEqual(repository.get_active_order_filename(), "my_mods.txt")
            with self.assertRaisesRegex(ValueError, "不支持"):
                repository.set_active_order_filename("other.txt")
            self.assertEqual(
                repository.save_user_mod_data("a", "  别名  ", "  备注  "),
                {"alias": "别名", "notes": "备注"},
            )
            self.assertEqual(
                repository.list_user_mod_data()["a"],
                {
                    "alias": "别名",
                    "notes": "备注",
                    "mod_type": "unknown",
                    "mod_types": ["unknown"],
                    "published_workshop_id": "",
                    "hidden": False,
                    "ignored_warning_codes": [],
                },
            )

            type_names = [item["name"] for item in repository.list_mod_types()]
            self.assertEqual(type_names[:7], ["语言包", "UI", "单位", "功能", "大修", "美化", "未知"])
            custom_type = repository.create_mod_type("音效")
            repository.set_mod_types("a", [custom_type["id"], "ui", custom_type["id"]])
            repository.set_mod_hidden("a", True)
            updated_type = repository.update_mod_type(custom_type["id"], "音乐")
            self.assertEqual(updated_type["name"], "音乐")
            self.assertEqual(repository.list_user_mod_data()["a"]["mod_type"], custom_type["id"])
            self.assertEqual(
                repository.list_user_mod_data()["a"]["mod_types"],
                [custom_type["id"], "ui"],
            )
            self.assertTrue(repository.list_user_mod_data()["a"]["hidden"])
            self.assertEqual(
                repository.set_mod_warning_ignored("a", "missing_dependency", True),
                ["missing_dependency"],
            )
            self.assertEqual(
                repository.set_mod_warning_ignored("a", "mod_newer_than_game", True),
                ["outdated_mod", "missing_dependency"],
            )
            self.assertEqual(
                repository.list_user_mod_data()["a"]["ignored_warning_codes"],
                ["outdated_mod", "missing_dependency"],
            )
            self.assertEqual(
                repository.set_mod_warning_ignored("a", "missing_dependency", False),
                ["outdated_mod"],
            )
            with self.assertRaisesRegex(ValueError, "不支持忽略"):
                repository.set_mod_warning_ignored("a", "unknown_warning", True)
            with self.assertRaisesRegex(ValueError, "默认类型无法"):
                repository.delete_mod_type("ui")
            repository.delete_mod_type(custom_type["id"])
            self.assertEqual(repository.list_user_mod_data()["a"]["mod_types"], ["ui"])
            self.assertEqual(repository.set_mod_types("a", []), ["unknown"])
            self.assertEqual(repository.set_published_workshop_id("a", "123456"), "123456")
            self.assertEqual(
                repository.list_user_mod_data()["a"]["published_workshop_id"],
                "123456",
            )
            sync_record = repository.save_data_sync_item(
                "example.pack",
                "123",
                "workshop/example.pack",
                10,
                20,
                "data/example.pack",
                10,
                20,
            )
            self.assertEqual(sync_record["workshop_id"], "123")
            self.assertEqual(repository.get_data_sync_item("EXAMPLE.PACK")["source_size"], 10)

            default_playset = repository.get_current_playset()
            self.assertEqual(default_playset["id"], "default")
            self.assertEqual(default_playset["name"], "默认")
            self.assertTrue(default_playset["is_default"])
            self.assertEqual(default_playset["mod_ids"], ["a", "b"])

            playset = repository.create_playset("常用", ["c", "!base", "a", "c"])
            self.assertEqual(playset["mod_ids"], ["c", "!base", "a"])
            self.assertEqual(repository.get_current_playset_id(), playset["id"])
            self.assertEqual(
                next(item for item in StateRepository(database).list_playsets() if item["id"] == playset["id"])[
                    "mod_ids"
                ],
                ["c", "!base", "a"],
            )
            repository.rename_playset(playset["id"], "常用更新")
            updated = repository.update_current_playset(["a"])
            self.assertEqual(updated["mod_ids"], ["a"])
            backup = repository.add_backup("backup.txt", ["a"])
            self.assertEqual(repository.list_backups()[0]["id"], backup["id"])
            with self.assertRaisesRegex(ValueError, "默认播放集无法删除"):
                repository.delete_playset("default")
            repository.delete_playset(playset["id"])
            self.assertEqual(repository.get_current_playset_id(), "default")
            self.assertEqual([item["name"] for item in repository.list_playsets()], ["默认"])

            with closing(sqlite3.connect(database)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertEqual(
                tables,
                {
                    "system_info",
                    "app_state",
                    "user_mod_data",
                    "custom_mod_types",
                    "presets",
                    "preset_items",
                    "playsets",
                    "playset_items",
                    "load_order_backups",
                    "data_sync_items",
                },
            )


class ApiContractTests(unittest.TestCase):
    def test_first_scan_restores_installed_used_mods_without_subscribing_missing_mods(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            data.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            write_pack(data / "first.pack")
            write_pack(data / "second.pack")
            (game / "used_mods.txt").write_text(
                'mod "second.pack";\nmod "not-installed.pack";\nmod "first.pack";\n',
                encoding="utf-8",
            )

            api = API(root / "state")
            saved = api.call(
                "save_settings",
                [{
                    "game_path": str(game),
                    "workshop_path": "",
                    "fetch_workshop_metadata": False,
                }],
            )
            self.assertTrue(saved["ok"])

            with (
                patch(
                    "backend.api.query_workshop_subscription_status",
                    side_effect=AssertionError("first-start restore must not query subscriptions"),
                ) as query_status,
                patch(
                    "backend.api.subscribe_workshop_items",
                    side_effect=AssertionError("first-start restore must not subscribe to missing mods"),
                ) as subscribe,
            ):
                first_scan = api.call("scan_mods", [False])
                self.assertTrue(first_scan["ok"])
                pack_to_id = {
                    item["pack_name"]: item["id"]
                    for item in first_scan["data"]["mods"]
                }
                expected = [pack_to_id["second.pack"], pack_to_id["first.pack"]]
                self.assertEqual(first_scan["data"]["enabled_order"], expected)
                self.assertEqual(first_scan["data"]["missing_enabled_ids"], [])
                self.assertEqual(
                    first_scan["data"]["current_playset"]["mod_ids"],
                    expected,
                )

                (game / "used_mods.txt").write_text(
                    'mod "first.pack";\nmod "second.pack";\n',
                    encoding="utf-8",
                )
                second_scan = api.call("scan_mods", [False])
                self.assertEqual(second_scan["data"]["enabled_order"], expected)
                query_status.assert_not_called()
                subscribe.assert_not_called()

    def test_workshop_publish_copy_suggests_english_when_description_has_no_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = make_asset(
                write_pack(root / "123" / "localized.pack"),
                "localized-id",
                SOURCE_WORKSHOP,
                "123",
            )
            api = API(root / "state")
            api._assets = {asset.id: asset}
            with patch.object(
                api.workshop_service,
                "refresh_localized",
                return_value={
                    "123": {
                        "title": "中文标题",
                        "description": "English description",
                        "title_language": "schinese",
                        "description_language": "english",
                    }
                },
            ) as refresh:
                result = api.call("get_workshop_publish_copy", [asset.id, "zh-CN"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["suggested_language"], "en-US")
        self.assertEqual(result["data"]["effective_language"], "en-US")
        self.assertEqual(result["data"]["steam_language"], "schinese")
        refresh.assert_called_once_with(["123"], "zh-CN")

    def test_share_import_warns_subscribes_and_resolves_downloaded_workshop_mods(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exported_asset = make_asset(
                write_pack(root / "exported" / "123" / "shared.pack"),
                "exported-id",
                SOURCE_WORKSHOP,
                "123",
            )
            share_code = export_share([exported_asset])
            api = API(root / "state")

            with patch(
                "backend.api.query_workshop_subscription_status",
                return_value=[
                    {
                        "workshop_id": "123",
                        "title": "Shared Workshop Mod",
                        "subscribed": False,
                    }
                ],
            ) as query_status:
                preview = api.call("preview_import_share", [share_code])

            self.assertTrue(preview["ok"])
            self.assertEqual(preview["data"]["unsubscribed"][0]["workshop_id"], "123")
            query_status.assert_called_once_with(["123"], "schinese", app_id="1142710")

            with patch(
                "backend.api.subscribe_workshop_items",
                return_value={
                    "operation": "subscribe_many",
                    "subscribed": ["123"],
                    "already_subscribed": [],
                },
            ) as subscribe:
                accepted = api.call("subscribe_workshop_items", [["123"]])
            self.assertTrue(accepted["ok"])
            subscribe.assert_called_once_with(["123"], app_id="1142710")

            imported = api.call("import_share", [share_code])
            self.assertTrue(imported["ok"])
            pending_id = imported["data"]["missing_mod_ids"][0]
            self.assertEqual(parse_pending_workshop_mod_id(pending_id), ("123", "shared.pack"))
            self.assertEqual(
                api.state_repository.get_current_playset()["mod_ids"],
                [pending_id],
            )

            downloaded_asset = make_asset(
                write_pack(root / "installed" / "123" / "shared.pack"),
                "installed-id",
                SOURCE_WORKSHOP,
                "123",
            )
            api._assets = {downloaded_asset.id: downloaded_asset}
            resolved = api._current_playset_payload()
            self.assertEqual(resolved["ordered_mod_ids"], ["installed-id"])
            self.assertEqual(resolved["missing_mod_ids"], [])
            self.assertEqual(
                api.state_repository.get_current_playset()["mod_ids"],
                ["installed-id"],
            )

    def test_switching_playset_persists_its_order_through_the_next_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            data.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            for pack_name in ("!base.pack", "alpha.pack", "zeta.pack"):
                write_pack(data / pack_name)

            api = API(root / "state")
            self.assertTrue(
                api.call(
                    "save_settings",
                    [{
                        "game_path": str(game),
                        "workshop_path": "",
                        "scan_data": True,
                        "scan_modding": False,
                        "scan_workshop": False,
                        "scan_merged": False,
                        "fetch_workshop_metadata": False,
                    }],
                )["ok"]
            )
            first_scan = api.call("scan_mods", [False])
            self.assertTrue(first_scan["ok"])
            mod_ids = {item["pack_name"]: item["id"] for item in first_scan["data"]["mods"]}
            playset_order = [
                mod_ids["zeta.pack"],
                mod_ids["!base.pack"],
                mod_ids["alpha.pack"],
            ]
            created = api.call("create_playset", ["保留顺序", playset_order])
            self.assertTrue(created["ok"])
            playset_id = created["data"]["current_playset"]["id"]

            switched_default = api.call("switch_playset", ["default"])
            self.assertTrue(switched_default["ok"])
            api.call("update_playset", ["default", list(reversed(playset_order))])
            switched = api.call("switch_playset", [playset_id])
            self.assertTrue(switched["ok"])
            self.assertEqual(switched["data"]["ordered_mod_ids"], playset_order)
            self.assertEqual(api.state_repository.get_enabled_order(), playset_order)

            rescanned = api.call("scan_mods", [False])
            self.assertTrue(rescanned["ok"])
            self.assertEqual(rescanned["data"]["enabled_order"], playset_order)
            self.assertEqual(rescanned["data"]["current_playset"]["id"], playset_id)

    def test_public_rpc_supports_core_workflow_without_network_or_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_dir = root / "state"
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            game.mkdir()
            data.mkdir()
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            write_pack(data / "example_mod.pack")

            api = API(state_dir)
            excluded_entries = {
                "groups",
                "dependency_graph",
                "rules",
                "texture_optimization",
                "file_content_search",
                "mod_settings",
                "log_analysis",
            }
            self.assertTrue(excluded_entries.isdisjoint(api.rpc_methods))
            self.assertEqual(
                api.call("rules"),
                {
                    "ok": False,
                    "error": {"code": "METHOD_NOT_ALLOWED", "message": "该操作未开放"},
                },
            )

            with (
                patch("backend.api.is_game_running", return_value=False),
                patch(
                    "backend.api.launch_game",
                    side_effect=AssertionError("game launch is forbidden in tests"),
                ),
                patch(
                    "urllib.request.urlopen",
                    side_effect=AssertionError("network access is forbidden in tests"),
                ),
            ):
                settings = api.call(
                    "save_settings",
                    [
                        {
                            "game_path": str(game),
                            "workshop_path": "",
                            "scan_data": True,
                            "scan_modding": False,
                            "scan_workshop": False,
                            "scan_merged": False,
                            "fetch_workshop_metadata": False,
                        }
                    ],
                )
                self.assertTrue(settings["ok"])

                bootstrap = api.call("get_bootstrap")
                self.assertTrue(bootstrap["ok"])
                self.assertNotIn("feature_scope", bootstrap["data"])
                self.assertTrue(bootstrap["data"]["path_health"]["game_ready"])
                self.assertEqual(
                    [item["name"] for item in bootstrap["data"]["mod_types"][:7]],
                    ["语言包", "UI", "单位", "功能", "大修", "美化", "未知"],
                )

                scan = api.call("scan_mods", [False])
                self.assertTrue(scan["ok"])
                self.assertEqual(len(scan["data"]["mods"]), 1)
                mod = scan["data"]["mods"][0]
                self.assertEqual(mod["pack_name"], "example_mod.pack")
                self.assertNotIn("supported_languages", mod)
                self.assertNotIn("file_stats", mod)
                self.assertNotIn("dependencies", mod)
                self.assertEqual(mod["mod_type"], "unknown")
                self.assertEqual(mod["mod_types"], ["unknown"])
                self.assertFalse(mod["hidden"])
                self.assertEqual(mod["ignored_warning_codes"], [])

                saved_user_data = api.call(
                    "save_mod_user_data",
                    [mod["id"], "示例别名", "示例备注"],
                )
                self.assertTrue(saved_user_data["ok"])
                self.assertEqual(saved_user_data["data"]["alias"], "示例别名")

                custom_type = api.call("create_mod_type", ["音效"])
                self.assertTrue(custom_type["ok"])
                custom_type_id = custom_type["data"]["item"]["id"]
                typed = api.call("set_mod_types", [mod["id"], [custom_type_id, "ui"]])
                self.assertEqual(typed["data"]["mod_type"], custom_type_id)
                self.assertEqual(typed["data"]["mod_types"], [custom_type_id, "ui"])
                hidden = api.call("set_mod_hidden", [mod["id"], True])
                self.assertTrue(hidden["data"]["hidden"])

                playset = api.call("create_playset", ["测试播放集", [mod["id"]]])
                self.assertTrue(playset["ok"])
                self.assertEqual(playset["data"]["current_playset"]["mod_ids"], [mod["id"]])

                exported = api.call("export_share", [[mod["id"]]])
                self.assertTrue(exported["ok"])
                current_playset_id = playset["data"]["current_playset"]["id"]
                cleared = api.call("update_playset", [current_playset_id, []])
                self.assertTrue(cleared["ok"])
                imported = api.call("import_share", [exported["data"]["share_code"]])
                self.assertEqual(imported["data"]["ordered_mod_ids"], [mod["id"]])
                self.assertEqual(imported["data"]["current_playset"]["id"], current_playset_id)
                self.assertEqual(
                    api.state_repository.get_current_playset()["mod_ids"],
                    [mod["id"]],
                )

                preview = api.call("preview_load_order", [[mod["id"]]])
                self.assertTrue(preview["ok"])
                self.assertEqual(preview["data"]["pack_names"], ["example_mod.pack"])
                saved_order = api.call(
                    "save_load_order",
                    [[mod["id"]], scan["data"]["order_token"]],
                )
                self.assertTrue(saved_order["ok"])
                self.assertTrue((game / "used_mods.txt").is_file())

                shared_token = saved_order["data"]["order_token"]
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(
                        executor.map(
                            lambda order: api.call(
                                "save_load_order",
                                [order, shared_token],
                            ),
                            ([mod["id"]], []),
                        )
                    )
                self.assertEqual(sum(result["ok"] for result in results), 1)
                rejected = next(result for result in results if not result["ok"])
                self.assertIn("其他程序修改", rejected["error"]["message"])

    def test_local_mod_can_create_and_update_a_workshop_item_without_real_steam_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            data.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            write_pack(data / "my_own_mod.pack")
            preview = root / "preview.jpg"
            preview.write_bytes(b"preview fixture")

            api = API(root / "state")
            saved = api.call(
                "save_settings",
                [
                    {
                        "game_path": str(game),
                        "workshop_path": "",
                        "scan_data": True,
                        "scan_modding": False,
                        "scan_workshop": False,
                        "scan_merged": False,
                        "fetch_workshop_metadata": False,
                    }
                ],
            )
            self.assertTrue(saved["ok"])
            scan = api.call("scan_mods", [False])
            mod = scan["data"]["mods"][0]
            bridge_calls: list[dict[str, object]] = []

            def fake_publish(**kwargs: object) -> dict[str, object]:
                content_path = Path(str(kwargs["content_path"]))
                self.assertTrue((content_path / "my_own_mod.pack").is_file())
                bridge_calls.append(dict(kwargs))
                return {
                    "operation": "upload" if not kwargs["workshop_id"] else "update",
                    "workshop_id": "456789",
                    "created": not bool(kwargs["workshop_id"]),
                    "owner_id": "76561198000000000",
                    "owner_name": "Wyccc",
                    "needs_to_accept_agreement": False,
                }

            payload = {
                "mode": "upload",
                "title": "My Own Mod",
                "description": "Description",
                "change_note": "",
                "language": "zh-CN",
                "preview_path": str(preview),
                "category": "units",
                "visibility": 0,
            }
            with patch("backend.api.publish_workshop_item", side_effect=fake_publish):
                uploaded = api.call("publish_workshop_item", [mod["id"], payload])
                updated = api.call(
                    "publish_workshop_item",
                    [mod["id"], {**payload, "mode": "update", "change_note": "Version 2"}],
                )

            self.assertTrue(uploaded["ok"])
            self.assertTrue(updated["ok"])
            self.assertEqual(uploaded["data"]["mod"]["workshop_id"], "456789")
            self.assertEqual(uploaded["data"]["mod"]["author"], "Wyccc")
            self.assertEqual(bridge_calls[0]["workshop_id"], "")
            self.assertEqual(bridge_calls[1]["workshop_id"], "456789")
            self.assertEqual(bridge_calls[0]["tags"], ["mod", "units"])
            self.assertEqual(bridge_calls[0]["language"], "schinese")
            self.assertEqual(bridge_calls[1]["language"], "schinese")
            self.assertEqual(
                api.state_repository.list_user_mod_data()[mod["id"]]["published_workshop_id"],
                "456789",
            )

    def test_context_menu_file_and_steam_operations_use_the_selected_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            workshop = root / "workshop" / "1142710" / "123"
            data.mkdir(parents=True)
            workshop.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            source_pack = workshop / "context_menu.pack"
            write_pack(source_pack)
            api = API(root / "state")
            saved = api.call(
                "save_settings",
                [
                    {
                        "game_path": str(game),
                        "workshop_path": str(workshop.parent),
                        "scan_data": True,
                        "scan_modding": False,
                        "scan_workshop": True,
                        "scan_merged": False,
                        "fetch_workshop_metadata": False,
                    }
                ],
            )
            self.assertTrue(saved["ok"])

            with (
                patch.object(api.workshop_service, "get_many", return_value={}),
                patch.object(api.workshop_service, "ensure_dependencies", return_value={}),
            ):
                scan = api.call("scan_mods", [False])
            self.assertTrue(scan["ok"])
            mod = scan["data"]["mods"][0]
            self.assertEqual(mod["source"], "workshop")

            copied = api.call("copy_mod_to_data", [mod["id"]])
            self.assertTrue(copied["ok"])
            self.assertTrue(copied["data"]["copied"])
            self.assertTrue((data / "context_menu.pack").is_file())

            with (
                patch.object(api.workshop_service, "get_many", return_value={}),
                patch.object(api.workshop_service, "ensure_dependencies", return_value={}),
            ):
                merged_scan = api.call("scan_mods", [False])
            merged = merged_scan["data"]["mods"][0]
            self.assertTrue(merged["cross_source_duplicate"])
            self.assertEqual(merged["sources"], ["data", "workshop"])

            with patch.object(api, "_reveal_file") as reveal_file:
                opened_folder = api.call("open_mod_folder", [merged["id"]])
            self.assertTrue(opened_folder["ok"])
            reveal_file.assert_called_once_with(Path(merged["path"]))

            with patch.object(api, "_reveal_file") as reveal_file:
                opened_workshop_folder = api.call("open_workshop_folder", [merged["id"]])
            self.assertTrue(opened_workshop_folder["ok"])
            self.assertEqual(
                Path(opened_workshop_folder["data"]["path"]),
                source_pack.resolve(strict=False),
            )
            reveal_file.assert_called_once_with(source_pack.resolve(strict=False))

            with patch.object(api, "_open_path") as open_path:
                opened = api.call("open_mod_in_rpfm", [merged["id"]])
            self.assertTrue(opened["ok"])
            self.assertEqual(opened["data"]["path"], merged["path"])
            open_path.assert_called_once_with(Path(merged["path"]))

            with patch(
                "backend.api.perform_workshop_operation",
                return_value={"operation": "force_update", "workshop_id": "123", "accepted": True},
            ) as steam_operation:
                updated = api.call("force_update_workshop_mod", [merged["id"]])
                unsubscribed = api.call("unsubscribe_workshop_mod", [merged["id"]])
            self.assertTrue(updated["ok"])
            self.assertTrue(unsubscribed["ok"])
            self.assertEqual(
                [call.args[:2] for call in steam_operation.call_args_list],
                [("force_update", "123"), ("unsubscribe", "123")],
            )

    def test_warning_ignore_rpc_filters_and_restores_supported_mod_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            asset = ModAsset(
                id="local:data:warning",
                pack_name="warning.pack",
                display_name="Warning Mod",
                path=str(Path(temporary) / "warning.pack"),
                directory=temporary,
                source="data",
                warnings=[
                    {
                        "code": "outdated_mod",
                        "severity": "warning",
                        "message": "MOD 过期",
                    },
                    {
                        "code": "missing_dependency",
                        "severity": "error",
                        "message": "缺少依赖",
                    },
                ],
            )
            api._assets = {asset.id: asset}

            ignored = api.call(
                "set_mod_warning_ignored",
                [asset.id, "missing_dependency", True],
            )
            self.assertTrue(ignored["ok"])
            self.assertEqual(ignored["data"]["ignored_warning_codes"], ["missing_dependency"])
            self.assertEqual(
                [warning["code"] for warning in ignored["data"]["warnings"]],
                ["outdated_mod"],
            )
            self.assertEqual(len(asset.warnings), 2)

            restored = api.call(
                "set_mod_warning_ignored",
                [asset.id, "missing_dependency", False],
            )
            self.assertEqual(
                [warning["code"] for warning in restored["data"]["warnings"]],
                ["outdated_mod", "missing_dependency"],
            )
            self.assertEqual(
                api.state_repository.list_user_mod_data()[asset.id]["ignored_warning_codes"],
                [],
            )

            unsupported = api.call(
                "set_mod_warning_ignored",
                [asset.id, "pack_parse_error", True],
            )
            self.assertFalse(unsupported["ok"])
            self.assertIn("不支持忽略", unsupported["error"]["message"])

    def test_missing_dependency_warnings_follow_the_current_enabled_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            first = ModAsset(
                id="local:data:first",
                pack_name="first.pack",
                display_name="First",
                path=str(Path(temporary) / "first.pack"),
                directory=temporary,
                source="data",
                missing_dependencies=[
                    {"kind": "pack", "id": "first-base.pack", "name": "first-base.pack"}
                ],
            )
            second = ModAsset(
                id="local:data:second",
                pack_name="second.pack",
                display_name="Second",
                path=str(Path(temporary) / "second.pack"),
                directory=temporary,
                source="data",
                missing_dependencies=[
                    {"kind": "pack", "id": "second-base.pack", "name": "second-base.pack"}
                ],
            )
            api._assets = {first.id: first, second.id: second}

            enabled_first = api.call("update_playset", ["default", [first.id]])
            self.assertTrue(enabled_first["ok"])
            self.assertEqual([warning["code"] for warning in first.warnings], ["missing_dependency"])
            self.assertEqual(second.warnings, [])

            enabled_second = api.call("update_playset", ["default", [second.id]])
            self.assertTrue(enabled_second["ok"])
            self.assertEqual(first.warnings, [])
            self.assertEqual([warning["code"] for warning in second.warnings], ["missing_dependency"])

            disabled_all = api.call("update_playset", ["default", []])
            self.assertTrue(disabled_all["ok"])
            self.assertEqual(first.warnings, [])
            self.assertEqual(second.warnings, [])

    def test_windows_file_reveal_uses_explorer_select_with_the_path_quoted_after_comma(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pack_path = Path(temporary) / "Data Mod.pack"
            pack_path.write_bytes(b"pack")
            resolved = pack_path.resolve(strict=False)

            with (
                patch("backend.api.os.name", "nt"),
                patch("backend.api.subprocess.Popen") as popen,
            ):
                API._reveal_file(pack_path)

            popen.assert_called_once_with(f'explorer.exe /select,"{resolved}"')

    def test_bulk_data_sync_skips_existing_local_packs_and_only_updates_managed_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            workshop_root = root / "workshop" / "1142710"
            own_data = write_pack(data / "own_upload.pack")
            own_data.write_bytes(own_data.read_bytes() + b"local-owner-copy")
            write_pack(data / "data.pack")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            (game / "Warhammer3.exe").write_bytes(b"")
            write_pack(workshop_root / "101" / "own_upload.pack")
            workshop_managed = write_pack(workshop_root / "102" / "managed.pack")

            api = API(root / "state")
            saved = api.call(
                "save_settings",
                [{
                    "game_path": str(game),
                    "workshop_path": str(workshop_root),
                    "scan_data": True,
                    "scan_modding": False,
                    "scan_workshop": True,
                    "scan_merged": False,
                    "fetch_workshop_metadata": False,
                }],
            )
            self.assertTrue(saved["ok"])
            with (
                patch.object(api.workshop_service, "get_many", return_value={}),
                patch.object(api.workshop_service, "ensure_dependencies", return_value={}),
            ):
                self.assertTrue(api.call("scan_mods", [False])["ok"])

            first = api.call("sync_workshop_to_data")
            self.assertTrue(first["ok"])
            self.assertEqual(first["data"]["copied"], 1)
            self.assertEqual(first["data"]["skipped_existing"], 1)
            self.assertEqual(own_data.read_bytes()[-16:], b"local-owner-copy")
            managed_target = data / "managed.pack"
            self.assertTrue(managed_target.is_file())

            workshop_managed.write_bytes(workshop_managed.read_bytes() + b"workshop-update")
            second = api.call("sync_workshop_to_data")
            self.assertEqual(second["data"]["updated"], 1)
            self.assertTrue(managed_target.read_bytes().endswith(b"workshop-update"))

            managed_target.write_bytes(managed_target.read_bytes() + b"local-edit")
            workshop_managed.write_bytes(workshop_managed.read_bytes() + b"second-update")
            third = api.call("sync_workshop_to_data")
            self.assertEqual(third["data"]["skipped_modified"], 1)
            self.assertTrue(managed_target.read_bytes().endswith(b"local-edit"))


if __name__ == "__main__":
    unittest.main()
