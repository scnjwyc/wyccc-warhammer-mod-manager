from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.constants import GAME_DATA_FEATURE_WORKSHOP_ITEMS, SOURCE_WORKSHOP
from backend.launch_paths import LaunchPathMap
from backend.models import GamePaths, ModAsset
from backend.scanner import _asset_id
from backend.share import export_share, parse_pending_workshop_mod_id
from backend.start_options import GAME_DATA_PATCH_NAME, RUNTIME_PACK_NAME
from backend.steamworks_bridge import SteamworksBridgeError
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
            self.assertEqual(schema_version, "8")

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

    def test_playsets_migrate_into_warhammer_and_are_scoped_by_game(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "state.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE system_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE playsets (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE TABLE playset_items (
                        playset_id TEXT NOT NULL REFERENCES playsets(id) ON DELETE CASCADE,
                        mod_id TEXT NOT NULL,
                        position INTEGER NOT NULL,
                        PRIMARY KEY (playset_id, mod_id)
                    );
                    INSERT INTO system_info(key, value) VALUES('schema_version', '7');
                    INSERT INTO app_state(key, value) VALUES
                        ('current_playset_id', 'favorite'),
                        ('playsets_initialized', '1'),
                        ('enabled_order', '["legacy-a", "legacy-b"]');
                    INSERT INTO playsets(id, name, created_at, updated_at) VALUES
                        ('default', '默认', 1, 2),
                        ('favorite', '常用', 3, 4);
                    INSERT INTO playset_items(playset_id, mod_id, position) VALUES
                        ('default', 'legacy-a', 0),
                        ('default', 'legacy-b', 1),
                        ('favorite', 'favorite-b', 0),
                        ('favorite', 'favorite-a', 1);
                    """
                )

            repository = StateRepository(database)

            warhammer = repository.list_playsets("warhammer3")
            three_kingdoms = repository.list_playsets("three_kingdoms")
            self.assertEqual([item["name"] for item in warhammer], ["默认", "常用"])
            self.assertTrue(all(item["game_id"] == "warhammer3" for item in warhammer))
            self.assertEqual(warhammer[1]["mod_ids"], ["favorite-b", "favorite-a"])
            self.assertEqual(len(three_kingdoms), 1)
            self.assertTrue(three_kingdoms[0]["is_default"])
            self.assertEqual(three_kingdoms[0]["mod_ids"], [])
            self.assertEqual(repository.get_current_playset("warhammer3")["id"], "favorite")
            self.assertEqual(
                repository.get_current_playset("three_kingdoms")["id"],
                "default:three_kingdoms",
            )

            created = repository.create_playset("常用", ["three-a"], "three_kingdoms")
            self.assertEqual(created["game_id"], "three_kingdoms")
            self.assertEqual(created["name"], "常用")
            self.assertEqual(created["mod_ids"], ["three-a"])
            with self.assertRaisesRegex(ValueError, "不属于当前游戏"):
                repository.switch_playset("favorite", "three_kingdoms")

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
    def test_saving_search_highlight_mode_keeps_scanned_assets_available_to_ai(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = make_asset(
                write_pack(root / "data" / "example.pack"),
                "data:example.pack",
                "data",
            )
            api = API(root / "state")
            api._assets = {asset.id: asset}

            saved = api.call("set_search_highlight_mode", [True])
            with patch(
                "backend.api.generate_mod_user_data",
                return_value={"alias": "AI alias", "notes": "AI notes"},
            ):
                generated = api.call("generate_mod_user_data", [asset.id])

        self.assertTrue(saved["ok"])
        self.assertTrue(saved["data"]["settings"]["search_highlight_mode"])
        self.assertTrue(generated["ok"])
        self.assertEqual(generated["data"]["alias"], "AI alias")

    @staticmethod
    def _prepare_launch_api(root: Path) -> tuple[API, dict]:
        game = root / "Total War WARHAMMER III"
        data = game / "data"
        data.mkdir(parents=True)
        (game / "Warhammer3.exe").write_bytes(b"")
        (data / "manifest.txt").write_text("data.pack\t0\ndb.pack\t0\n", encoding="utf-8")
        write_pack(data / "data.pack")
        write_pack(data / "db.pack")
        api = API(root / "state")
        api.call(
            "save_settings",
            [{"game_path": str(game), "workshop_path": "", "fetch_workshop_metadata": False}],
        )
        return api, api.call("scan_mods", [False])

    @staticmethod
    def _prepare_three_kingdoms_api(root: Path) -> tuple[API, dict]:
        game = root / "Total War THREE KINGDOMS"
        data = game / "data"
        workshop = root / "steamapps" / "workshop" / "content" / "779340"
        data.mkdir(parents=True)
        workshop.mkdir(parents=True)
        (game / "Three_Kingdoms.exe").write_bytes(b"")
        (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
        write_pack(data / "data.pack")
        api = API(root / "state")
        saved = api.call(
            "save_settings",
            [{
                "selected_game": "three_kingdoms",
                "game_installations": {
                    "three_kingdoms": {
                        "game_path": str(game),
                        "workshop_path": str(workshop),
                    },
                },
                "fetch_workshop_metadata": False,
            }],
        )
        if not saved["ok"]:
            raise AssertionError(saved)
        return api, api.call("scan_mods", [False])

    @staticmethod
    def _feature_statuses(subscribed: bool = True) -> list[dict[str, object]]:
        return [
            {
                "workshop_id": item["workshop_id"],
                "title": item["title"],
                "subscribed": subscribed,
            }
            for item in GAME_DATA_FEATURE_WORKSHOP_ITEMS.values()
        ]

    @staticmethod
    def _game_data_patch_result(root: Path, status: str = "generated") -> dict[str, object]:
        path = ""
        entry_count = 0
        if status in {"generated", "reused"}:
            patch_path = root / "state" / "runtime" / "!!!!wyccc_game_data_patch.pack"
            write_pack(patch_path)
            path = str(patch_path)
            entry_count = 1
        return {
            "status": status,
            "path": path,
            "fingerprint": "a" * 64,
            "changed_inputs": ["settings"] if status == "generated" else [],
            "entry_count": entry_count,
            "options": ["unit_model_multiplier"] if entry_count else [],
            "game_data": {"unit_rows_scaled": entry_count},
        }

    def test_playsets_follow_the_selected_game(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, warhammer_scan = self._prepare_launch_api(root)
            self.assertTrue(warhammer_scan["ok"])
            warhammer_created = api.call("create_playset", ["常用", []])
            self.assertTrue(warhammer_created["ok"])
            warhammer_playset_id = warhammer_created["data"]["current_playset"]["id"]

            three_kingdoms_game = root / "Total War THREE KINGDOMS"
            three_kingdoms_data = three_kingdoms_game / "data"
            three_kingdoms_workshop = root / "steamapps" / "workshop" / "content" / "779340"
            three_kingdoms_data.mkdir(parents=True)
            three_kingdoms_workshop.mkdir(parents=True)
            (three_kingdoms_game / "Three_Kingdoms.exe").write_bytes(b"")
            (three_kingdoms_data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(three_kingdoms_data / "data.pack")

            switched_to_three_kingdoms = api.call(
                "save_settings",
                [{
                    "selected_game": "three_kingdoms",
                    "game_installations": {
                        "warhammer3": {
                            "game_path": str(root / "Total War WARHAMMER III"),
                            "workshop_path": "",
                        },
                        "three_kingdoms": {
                            "game_path": str(three_kingdoms_game),
                            "workshop_path": str(three_kingdoms_workshop),
                        },
                    },
                    "fetch_workshop_metadata": False,
                }],
            )
            self.assertTrue(switched_to_three_kingdoms["ok"])

            bootstrap = api.call("get_bootstrap")
            self.assertTrue(bootstrap["ok"])
            self.assertEqual([item["name"] for item in bootstrap["data"]["playsets"]], ["默认"])

            blocked = api.call("switch_playset", [warhammer_playset_id])
            self.assertFalse(blocked["ok"])
            self.assertIn("不属于当前游戏", blocked["error"]["message"])

            three_kingdoms_created = api.call("create_playset", ["常用", []])
            self.assertTrue(three_kingdoms_created["ok"])
            self.assertEqual(three_kingdoms_created["data"]["current_playset"]["name"], "常用")

            switched_to_warhammer = api.call(
                "save_settings",
                [{
                    "selected_game": "warhammer3",
                    "game_installations": {
                        "warhammer3": {
                            "game_path": str(root / "Total War WARHAMMER III"),
                            "workshop_path": "",
                        },
                        "three_kingdoms": {
                            "game_path": str(three_kingdoms_game),
                            "workshop_path": str(three_kingdoms_workshop),
                        },
                    },
                    "fetch_workshop_metadata": False,
                }],
            )
            self.assertTrue(switched_to_warhammer["ok"])

            restored = api.call("get_bootstrap")
            self.assertTrue(restored["ok"])
            self.assertEqual(
                [item["name"] for item in restored["data"]["playsets"]],
                ["默认", "常用"],
            )
            self.assertEqual(restored["data"]["current_playset"]["id"], warhammer_playset_id)
            self.assertEqual(restored["data"]["current_playset"]["mod_ids"], [])

    def test_force_update_requires_the_workshop_download_to_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            asset = ModAsset(
                id="steam:123:missing.pack",
                pack_name="missing.pack",
                display_name="Missing Workshop MOD",
                path=str(Path(temporary) / "missing.pack"),
                directory=temporary,
                source=SOURCE_WORKSHOP,
                workshop_id="123",
            )
            api._assets = {asset.id: asset}

            with patch(
                "backend.api.perform_workshop_operation",
                return_value={
                    "operation": "force_update",
                    "workshop_id": "123",
                    "accepted": True,
                    "completed": False,
                },
            ):
                result = api.call("force_update_workshop_mod", [asset.id])

        self.assertFalse(result["ok"])
        self.assertIn("未完成", result["error"]["message"])

    def test_game_data_feature_status_uses_fixed_workshop_subscriptions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            items = GAME_DATA_FEATURE_WORKSHOP_ITEMS
            with patch(
                "backend.api.query_workshop_subscription_status",
                return_value=[
                    {
                        "workshop_id": items["unit_size"]["workshop_id"],
                        "title": "动态单位规模 - Dynamic Unit Size",
                        "subscribed": True,
                    },
                    {
                        "workshop_id": items["friendly_fire"]["workshop_id"],
                        "title": "动态禁用友伤 - Dynamic No Friendly Fire",
                        "subscribed": False,
                    },
                ],
            ) as query:
                result = api.call("get_game_data_feature_status")

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["data"]["items"],
            {
                "unit_size": {
                    **items["unit_size"],
                    "title": "动态单位规模 - Dynamic Unit Size",
                    "subscribed": True,
                },
                "friendly_fire": {
                    **items["friendly_fire"],
                    "title": "动态禁用友伤 - Dynamic No Friendly Fire",
                    "subscribed": False,
                },
                "unit_cap": {
                    **items["unit_cap"],
                    "subscribed": False,
                },
            },
        )
        self.assertEqual(result["data"]["warning"], "")
        self.assertTrue(result["data"]["known"])
        self.assertEqual(result["data"]["source"], "live")
        query.assert_called_once_with(
            [
                items["unit_size"]["workshop_id"],
                items["friendly_fire"]["workshop_id"],
                items["unit_cap"]["workshop_id"],
            ],
            "schinese",
            app_id=1_142_710,
        )

    def test_three_kingdoms_routes_steam_and_launch_without_wh3_runtime_packs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, scan = self._prepare_three_kingdoms_api(root)
            self.assertTrue(scan["ok"])
            with (
                patch(
                    "backend.api.subscribe_workshop_items",
                    return_value={"subscribed": ["123"]},
                ) as subscribe,
                patch("backend.api.launch_game", return_value={"pid": 7, "argument": ""}) as launch,
                patch.object(api, "set_game_running"),
            ):
                subscribed = api.call("subscribe_workshop_items", [["123"]])
                launched = api.call("launch_game", [[], scan["data"]["order_token"]])

        self.assertTrue(subscribed["ok"])
        self.assertEqual(subscribe.call_args.kwargs["app_id"], 779340)
        self.assertTrue(launched["ok"])
        self.assertEqual(launch.call_args.kwargs["executable_name"], "Three_Kingdoms.exe")
        self.assertEqual(launch.call_args.kwargs["process_name"], "Three_Kingdoms.exe")
        self.assertEqual(launched["data"]["game_data_patch"]["status"], "unsupported")

    def test_launch_uses_ascii_aliases_when_game_and_workshop_paths_are_non_ascii(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "中文 Steam 库"
            api, _ = self._prepare_three_kingdoms_api(root)
            game = root / "Total War THREE KINGDOMS"
            workshop = root / "steamapps" / "workshop" / "content" / "779340"
            workshop_pack = write_pack(workshop / "123" / "workshop.pack")
            scan = api.call("scan_mods", [False])
            workshop_id = next(
                mod["id"]
                for mod in scan["data"]["mods"]
                if mod["path"] == str(workshop_pack.resolve())
            )
            mapping = LaunchPathMap(
                (
                    (game.resolve(), "Z:\\"),
                    (workshop.resolve(), "Y:\\"),
                )
            )

            def write_without_accessing_the_alias(
                plan, *_args, **_kwargs
            ):
                return plan, "", "alias-token"

            with (
                patch.object(api.launch_path_aliases, "prepare", return_value=mapping),
                patch.object(
                    api.load_order,
                    "write_plan",
                    side_effect=write_without_accessing_the_alias,
                ),
                patch(
                    "backend.api.launch_game",
                    return_value={"pid": 7, "argument": ""},
                ) as launch,
                patch.object(api, "set_game_running"),
            ):
                launched = api.call(
                    "launch_game",
                    [[workshop_id], scan["data"]["order_token"]],
                )

        self.assertTrue(launched["ok"])
        self.assertEqual(launch.call_args.args[0], "Z:\\")
        self.assertEqual(launch.call_args.args[1], r"Z:\used_mods.txt")
        self.assertIn(
            'add_working_directory "Y:\\123";',
            launched["data"]["launch_plan"]["content"],
        )
        self.assertFalse(
            any(
                ord(character) > 127
                for character in launched["data"]["launch_plan"]["content"]
            )
        )

    def test_detect_paths_selects_requested_game_and_returns_its_health(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War THREE KINGDOMS"
            data = game / "data"
            workshop = root / "workshop" / "content" / "779340"
            data.mkdir(parents=True)
            workshop.mkdir(parents=True)
            (game / "Three_Kingdoms.exe").write_bytes(b"")
            paths = GamePaths(
                game_id="three_kingdoms",
                game_path=str(game),
                data_path=str(data),
                workshop_path=str(workshop),
            )
            api = API(root / "state")
            with (
                patch.object(
                    api.settings_service,
                    "detect_and_save",
                    return_value={"found": True, "paths": paths.to_dict()},
                ) as detect,
                patch.object(
                    api.settings_service,
                    "get_public",
                    return_value={"selected_game": "three_kingdoms"},
                ),
                patch.object(api, "detect_game_running", return_value=False),
                patch.object(api, "_sync_runtime_services"),
            ):
                result = api.call("detect_paths", ["three_kingdoms"])

        self.assertTrue(result["ok"])
        detect.assert_called_once_with("three_kingdoms")
        self.assertTrue(result["data"]["path_health"]["game_ready"])

    def test_cover_file_picker_is_not_exposed_by_the_directory_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            result = api.call("select_directory", ["preview"])

        self.assertFalse(result["ok"])
        self.assertIn("不支持", result["error"]["message"])

    def test_workshop_update_eligibility_requires_matching_creator_and_allows_workshop_only_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack = write_pack(root / "123" / "workshop_only.pack")
            pack.with_suffix(".png").write_bytes(b"cover fixture")
            workshop_only = ModAsset(
                id="steam:123:workshop_only.pack",
                pack_name="workshop_only.pack",
                display_name="Workshop-only MOD",
                path=str(pack),
                directory=str(pack.parent),
                source=SOURCE_WORKSHOP,
                sources=[SOURCE_WORKSHOP],
                workshop_id="123",
                creator_id="765",
            )
            api = API(root / "state")
            api._assets = {workshop_only.id: workshop_only}
            with patch(
                "backend.api.get_current_user",
                return_value={"steam_id": "765", "name": "Owner"},
            ):
                eligible = api.call("get_workshop_update_eligibility", [[workshop_only.id]])
            with patch(
                "backend.api.get_current_user",
                return_value={"steam_id": "999", "name": "Other"},
            ):
                ineligible = api.call("get_workshop_update_eligibility", [[workshop_only.id]])
            with patch(
                "backend.api.get_current_user",
                side_effect=SteamworksBridgeError("Steam offline"),
            ):
                unavailable = api.call("get_workshop_update_eligibility", [[workshop_only.id]])

            payload = {
                "mode": "update",
                "title": "Workshop-only MOD",
                "description": "",
                "change_note": "",
                "language": "en-US",
                "category": "units",
                "visibility": 0,
            }
            with patch(
                "backend.api.publish_workshop_item",
                return_value={
                    "workshop_id": "123",
                    "owner_id": "765",
                    "owner_name": "Owner",
                },
            ) as publish:
                updated = api.call("publish_workshop_item", [workshop_only.id, payload])
                uploaded = api.call(
                    "publish_workshop_item",
                    [workshop_only.id, {**payload, "mode": "upload"}],
                )

        self.assertTrue(eligible["ok"])
        self.assertEqual(eligible["data"]["eligible_mod_ids"], [workshop_only.id])
        self.assertEqual(ineligible["data"]["eligible_mod_ids"], [])
        self.assertEqual(unavailable["data"]["eligible_mod_ids"], [])
        self.assertTrue(updated["ok"])
        self.assertEqual(publish.call_args_list[0].kwargs["workshop_id"], "123")
        self.assertFalse(uploaded["ok"])

    def test_game_data_feature_status_retains_known_cache_after_refresh_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            with patch(
                "backend.api.query_workshop_subscription_status",
                side_effect=[
                    self._feature_statuses(subscribed=True),
                    SteamworksBridgeError("Steam offline"),
                ],
            ):
                live = api.call("get_game_data_feature_status")
                cached = api.call("get_game_data_feature_status")

        self.assertTrue(live["data"]["known"])
        self.assertEqual(live["data"]["source"], "live")
        self.assertTrue(cached["data"]["known"])
        self.assertEqual(cached["data"]["source"], "memory")
        self.assertIn("Steam offline", cached["data"]["warning"])
        self.assertTrue(
            all(item["subscribed"] for item in cached["data"]["items"].values())
        )

    def test_launch_refreshes_subscriptions_and_ensures_patch_before_starting_game(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, scan = self._prepare_launch_api(root)
            api.call("save_game_data_settings", [{"unit_model_multiplier": 2.0}])
            patch_result = self._game_data_patch_result(root)
            with (
                patch(
                    "backend.api.query_workshop_subscription_status",
                    return_value=self._feature_statuses(),
                ) as query,
                patch(
                    "backend.api.ensure_game_data_patch",
                    return_value=patch_result,
                ) as ensure,
                patch(
                    "backend.api.build_runtime_options_pack",
                    return_value={"path": "", "options": [], "entry_count": 0, "game_data": {}},
                ),
                patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}) as launch,
                patch.object(api, "set_game_running"),
            ):
                launched = api.call("launch_game", [[], scan["data"]["order_token"]])

        self.assertTrue(launched["ok"])
        self.assertEqual(launched["data"]["game_data_patch"]["status"], "generated")
        self.assertIn("!!!!wyccc_game_data_patch.pack", launched["data"]["launch_plan"]["content"])
        self.assertEqual(ensure.call_args.kwargs["playset_id"], "default")
        self.assertEqual(ensure.call_args.kwargs["active_ids"], [])
        self.assertTrue(all(ensure.call_args.kwargs["subscription_state"].values()))
        query.assert_called_once()
        launch.assert_called_once()

    def test_launch_stages_runtime_packs_in_data_when_portable_path_is_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "中文目录" / "管理器"
            root.mkdir(parents=True)
            api, scan = self._prepare_launch_api(root)
            patch_result = self._game_data_patch_result(root)
            runtime_source = root / "state" / "runtime" / RUNTIME_PACK_NAME
            write_pack(runtime_source)
            runtime_result = {
                "path": str(runtime_source),
                "options": ["skip_intro_movies"],
                "entry_count": 1,
                "game_data": {},
            }
            with (
                patch(
                    "backend.api.query_workshop_subscription_status",
                    return_value=self._feature_statuses(),
                ),
                patch("backend.api.ensure_game_data_patch", return_value=patch_result),
                patch(
                    "backend.api.build_runtime_options_pack",
                    return_value=runtime_result,
                ),
                patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}),
                patch.object(api, "set_game_running"),
            ):
                launched = api.call("launch_game", [[], scan["data"]["order_token"]])

            data_path = root / "Total War WARHAMMER III" / "data"
            content = launched["data"]["launch_plan"]["content"]
            patch_target = data_path / GAME_DATA_PATCH_NAME
            runtime_target = data_path / RUNTIME_PACK_NAME
            patch_target_bytes = patch_target.read_bytes() if patch_target.is_file() else b""
            runtime_target_bytes = runtime_target.read_bytes() if runtime_target.is_file() else b""
            patch_source_bytes = Path(patch_result["path"]).read_bytes()
            runtime_source_bytes = runtime_source.read_bytes()

        self.assertTrue(launched["ok"])
        self.assertEqual(launched["data"]["launch_plan"]["working_directories"], [])
        self.assertNotIn("add_working_directory", content)
        self.assertIn(f'mod "{GAME_DATA_PATCH_NAME}";', content)
        self.assertIn(f'mod "{RUNTIME_PACK_NAME}";', content)
        self.assertEqual(patch_target_bytes, patch_source_bytes)
        self.assertEqual(runtime_target_bytes, runtime_source_bytes)

    def test_launch_removes_stale_runtime_packs_from_data_when_options_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, scan = self._prepare_launch_api(root)
            data_path = root / "Total War WARHAMMER III" / "data"
            stale_paths = [
                write_pack(data_path / GAME_DATA_PATCH_NAME),
                write_pack(data_path / RUNTIME_PACK_NAME),
            ]
            patch_result = self._game_data_patch_result(root, "zero_modification")
            with (
                patch(
                    "backend.api.query_workshop_subscription_status",
                    return_value=self._feature_statuses(),
                ),
                patch("backend.api.ensure_game_data_patch", return_value=patch_result),
                patch(
                    "backend.api.build_runtime_options_pack",
                    return_value={
                        "path": "",
                        "options": [],
                        "entry_count": 0,
                        "game_data": {},
                    },
                ),
                patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}),
                patch.object(api, "set_game_running"),
            ):
                launched = api.call("launch_game", [[], scan["data"]["order_token"]])
            stale_exists_after_launch = [path.exists() for path in stale_paths]

        self.assertTrue(launched["ok"])
        self.assertEqual(stale_exists_after_launch, [False, False])

    def test_launch_logs_generated_reused_and_zero_modification_outcomes(self) -> None:
        for status in ("generated", "reused", "zero_modification"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                api, scan = self._prepare_launch_api(root)
                patch_result = self._game_data_patch_result(root, status)
                with (
                    self.assertLogs("backend.api", level="INFO") as logs,
                    patch(
                        "backend.api.query_workshop_subscription_status",
                        return_value=self._feature_statuses(),
                    ),
                    patch("backend.api.ensure_game_data_patch", return_value=patch_result),
                    patch(
                        "backend.api.build_runtime_options_pack",
                        return_value={"path": "", "options": [], "entry_count": 0, "game_data": {}},
                    ),
                    patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}),
                    patch.object(api, "set_game_running"),
                ):
                    launched = api.call("launch_game", [[], scan["data"]["order_token"]])

                self.assertTrue(launched["ok"])
                self.assertIn(f"status={status}", "\n".join(logs.output))

    def test_launch_aborts_and_logs_generation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, scan = self._prepare_launch_api(root)
            with (
                self.assertLogs("backend.api", level="ERROR") as logs,
                patch(
                    "backend.api.query_workshop_subscription_status",
                    return_value=self._feature_statuses(),
                ),
                patch(
                    "backend.api.ensure_game_data_patch",
                    side_effect=ValueError("缺少 main_units_tables"),
                ),
                patch("backend.api.launch_game") as launch,
            ):
                result = api.call("launch_game", [[], scan["data"]["order_token"]])

        self.assertFalse(result["ok"])
        self.assertIn("main_units_tables", result["error"]["message"])
        self.assertIn("status=generation_failed", "\n".join(logs.output))
        launch.assert_not_called()

    def test_unknown_subscription_with_requested_settings_aborts_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, scan = self._prepare_launch_api(root)
            api.call("save_game_data_settings", [{"unit_model_multiplier": 2.0}])
            with (
                self.assertLogs("backend.api", level="ERROR") as logs,
                patch(
                    "backend.api.query_workshop_subscription_status",
                    side_effect=SteamworksBridgeError("Steam offline"),
                ),
                patch("backend.api.load_manifest_subscription_state", return_value=None),
                patch("backend.api.ensure_game_data_patch") as ensure,
                patch("backend.api.launch_game") as launch,
            ):
                result = api.call("launch_game", [[], scan["data"]["order_token"]])

        self.assertFalse(result["ok"])
        self.assertIn("订阅状态", result["error"]["message"])
        self.assertIn("status=subscription_error", "\n".join(logs.output))
        ensure.assert_not_called()
        launch.assert_not_called()

    def test_subscription_error_uses_manifest_state_and_continues_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, scan = self._prepare_launch_api(root)
            api.call("save_game_data_settings", [{"unit_model_multiplier": 2.0}])
            unit_id = GAME_DATA_FEATURE_WORKSHOP_ITEMS["unit_size"]["workshop_id"]
            patch_result = self._game_data_patch_result(root, "zero_modification")
            with (
                self.assertLogs("backend.api", level="WARNING") as logs,
                patch(
                    "backend.api.query_workshop_subscription_status",
                    side_effect=SteamworksBridgeError("Steam offline"),
                ),
                patch(
                    "backend.api.load_manifest_subscription_state",
                    return_value={unit_id: True},
                ),
                patch(
                    "backend.api.ensure_game_data_patch",
                    return_value=patch_result,
                ) as ensure,
                patch(
                    "backend.api.build_runtime_options_pack",
                    return_value={"path": "", "options": [], "entry_count": 0, "game_data": {}},
                ),
                patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}),
                patch.object(api, "set_game_running"),
            ):
                result = api.call("launch_game", [[], scan["data"]["order_token"]])

        self.assertTrue(result["ok"])
        self.assertEqual(ensure.call_args.kwargs["subscription_state"], {unit_id: True})
        self.assertIn("status=subscription_error", "\n".join(logs.output))
        self.assertIn("source=manifest", "\n".join(logs.output))

    def test_subscription_error_with_disabled_settings_continues_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, scan = self._prepare_launch_api(root)
            patch_result = self._game_data_patch_result(root, "zero_modification")
            with (
                self.assertLogs("backend.api", level="WARNING") as logs,
                patch(
                    "backend.api.query_workshop_subscription_status",
                    side_effect=SteamworksBridgeError("Steam offline"),
                ),
                patch("backend.api.load_manifest_subscription_state", return_value=None),
                patch(
                    "backend.api.ensure_game_data_patch",
                    return_value=patch_result,
                ) as ensure,
                patch(
                    "backend.api.build_runtime_options_pack",
                    return_value={"path": "", "options": [], "entry_count": 0, "game_data": {}},
                ),
                patch("backend.api.launch_game", return_value={"pid": 123, "argument": ""}),
                patch.object(api, "set_game_running"),
            ):
                result = api.call("launch_game", [[], scan["data"]["order_token"]])

        self.assertTrue(result["ok"])
        self.assertEqual(ensure.call_args.kwargs["subscription_state"], {})
        self.assertIn("status=subscription_error", "\n".join(logs.output))

    def test_manual_game_data_patch_rpc_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            result = api.call("generate_game_data_patch", [{}, []])

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_launch_is_rejected_while_game_data_patch_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, scan = self._prepare_launch_api(root)
            api._game_data_patch_lock.acquire()
            try:
                launched = api.call("launch_game", [[], scan["data"]["order_token"]])
            finally:
                api._game_data_patch_lock.release()

        self.assertFalse(launched["ok"])
        self.assertIn("补丁", launched["error"]["message"])

    def test_scan_discards_internal_feature_mods_from_a_stale_playset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            data.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            unit_item = GAME_DATA_FEATURE_WORKSHOP_ITEMS["unit_size"]
            fire_item = GAME_DATA_FEATURE_WORKSHOP_ITEMS["friendly_fire"]
            unit_pack = write_pack(data / unit_item["pack_name"])
            write_pack(data / "visible.pack")

            api = API(root / "state")
            api.call(
                "save_settings",
                [{"game_path": str(game), "workshop_path": "", "fetch_workshop_metadata": False}],
            )
            initial = api.call("scan_mods", [False])
            self.assertTrue(initial["ok"])
            stale_local_id = _asset_id("data", unit_pack)
            stale_workshop_id = (
                f"steam:{fire_item['workshop_id']}:{fire_item['pack_name']}"
            )
            api.state_repository.set_published_workshop_id(
                stale_local_id,
                unit_item["workshop_id"],
            )
            api.state_repository.update_current_playset(
                [stale_local_id, stale_workshop_id]
            )

            rescanned = api.call("scan_mods", [False])

        self.assertTrue(rescanned["ok"])
        self.assertEqual(
            [item["pack_name"] for item in rescanned["data"]["mods"]],
            ["visible.pack"],
        )
        self.assertEqual(rescanned["data"]["enabled_order"], [])
        self.assertEqual(rescanned["data"]["missing_enabled_ids"], [])
        self.assertEqual(
            rescanned["data"]["current_playset"]["mod_ids"],
            [],
        )

    def test_game_data_settings_rpc_only_updates_supported_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            original_language = api.settings_service.get()["language"]

            result = api.call(
                "save_game_data_settings",
                [{
                    "unit_model_multiplier": 2.5,
                    "single_entity_unit_mode": "health",
                    "scale_lord_hero_health": True,
                    "disable_unit_friendly_fire": True,
                    "disable_spell_friendly_fire": True,
                    "language": "ja-JP",
                }],
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["settings"]["unit_model_multiplier"], 3)
            self.assertEqual(
                result["data"]["settings"]["single_entity_unit_mode"],
                "health",
            )
            self.assertTrue(result["data"]["settings"]["scale_lord_hero_health"])
            self.assertTrue(result["data"]["settings"]["disable_unit_friendly_fire"])
            self.assertTrue(result["data"]["settings"]["disable_spell_friendly_fire"])
            self.assertEqual(result["data"]["settings"]["language"], original_language)

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
        refresh.assert_called_once_with(["123"], "zh-CN", app_id=1_142_710)

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
            query_status.assert_called_once_with(["123"], "schinese", app_id=1_142_710)

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
            subscribe.assert_called_once_with(["123"], app_id=1_142_710)

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

    def test_collection_import_subscribes_missing_items_and_preserves_collection_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = API(root / "state")
            installed = make_asset(
                write_pack(root / "workshop" / "123" / "one.pack"),
                "installed-id",
                SOURCE_WORKSHOP,
                "123",
            )
            api._assets = {installed.id: installed}
            collection = {
                "collection_id": "900",
                "title": "My collection",
                "references": [
                    {"workshop_id": "123", "legacy_workshop_project": True},
                    {"workshop_id": "456", "legacy_workshop_project": True},
                ],
            }
            with (
                patch("backend.api.fetch_workshop_collection", return_value=collection),
                patch(
                    "backend.api.query_workshop_subscription_status",
                    return_value=[
                        {"workshop_id": "123", "title": "Installed", "subscribed": True},
                        {"workshop_id": "456", "title": "Missing", "subscribed": False},
                    ],
                ),
                patch(
                    "backend.api.subscribe_workshop_items",
                    return_value={
                        "subscribed": [],
                        "already_subscribed": [],
                        "failed": [{"workshop_id": "456", "error": "access denied"}],
                    },
                ) as subscribe,
            ):
                imported = api.call(
                    "import_workshop_collection",
                    ["https://steamcommunity.com/sharedfiles/filedetails/?id=900"],
                )
                playset_order = api.state_repository.get_current_playset()["mod_ids"]

        self.assertTrue(imported["ok"])
        self.assertEqual(imported["data"]["collection"]["title"], "My collection")
        self.assertEqual(imported["data"]["ordered_mod_ids"], [installed.id])
        self.assertEqual(imported["data"]["pending_workshop_ids"], [])
        self.assertEqual(imported["data"]["subscription_failures"][0]["workshop_id"], "456")
        self.assertEqual(playset_order, [installed.id])
        subscribe.assert_called_once_with(["456"], app_id=1_142_710)

    def test_save_load_order_preserves_pending_workshop_items_for_download_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            workshop = root / "workshop" / "1142710"
            data.mkdir(parents=True)
            workshop.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            write_pack(data / "installed.pack")

            api = API(root / "state")
            saved_settings = api.call(
                "save_settings",
                [{
                    "game_path": str(game),
                    "workshop_path": str(workshop),
                    "scan_data": True,
                    "scan_modding": False,
                    "scan_workshop": True,
                    "scan_merged": False,
                    "fetch_workshop_metadata": False,
                }],
            )
            self.assertTrue(saved_settings["ok"])
            scan = api.call("scan_mods", [False])
            self.assertTrue(scan["ok"])
            installed_id = next(
                item["id"]
                for item in scan["data"]["mods"]
                if item["pack_name"] == "installed.pack"
            )
            pending_id = "pending:steam:456:downloaded.pack"
            current_playset_id = api.state_repository.get_current_playset_id()
            api.call("update_playset", [current_playset_id, [installed_id, pending_id]])

            saved_order = api.call(
                "save_load_order",
                [[installed_id], scan["data"]["order_token"]],
            )

            self.assertTrue(saved_order["ok"])
            self.assertEqual(
                api.state_repository.get_current_playset()["mod_ids"],
                [installed_id, pending_id],
            )

            write_pack(workshop / "456" / "downloaded.pack")
            downloaded_scan = api.call("scan_mods", [False])
            self.assertTrue(downloaded_scan["ok"])
            downloaded_id = next(
                item["id"]
                for item in downloaded_scan["data"]["mods"]
                if item["workshop_id"] == "456"
            )
            self.assertEqual(
                downloaded_scan["data"]["enabled_order"],
                [installed_id, downloaded_id],
            )
            self.assertEqual(
                api.state_repository.get_current_playset()["mod_ids"],
                [installed_id, downloaded_id],
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
            cover = data / "my_own_mod.png"
            cover.write_bytes(b"cover fixture")

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
                staged_cover = content_path / "my_own_mod.png"
                self.assertTrue(staged_cover.is_file())
                self.assertEqual(Path(str(kwargs["preview_path"])), staged_cover)
                self.assertEqual(staged_cover.read_bytes(), b"cover fixture")
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

    def test_workshop_publish_requires_a_same_name_png_cover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            data.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            write_pack(data / "my_own_mod.pack")
            unrelated_preview = root / "preview.jpg"
            unrelated_preview.write_bytes(b"unrelated preview")

            api = API(root / "state")
            self.assertTrue(
                api.call(
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
                )["ok"]
            )
            mod = api.call("scan_mods", [False])["data"]["mods"][0]

            rejected = api.call(
                "publish_workshop_item",
                [
                    mod["id"],
                    {
                        "mode": "upload",
                        "title": "My Own Mod",
                        "language": "en-US",
                        "preview_path": str(unrelated_preview),
                        "category": "units",
                        "visibility": 0,
                    },
                ],
            )

            self.assertFalse(rejected["ok"])

    def test_workshop_publish_rejects_an_oversized_same_name_png_cover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "Total War WARHAMMER III"
            data = game / "data"
            data.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            (data / "manifest.txt").write_text("data.pack\t0\n", encoding="utf-8")
            write_pack(data / "data.pack")
            write_pack(data / "my_own_mod.pack")
            (data / "my_own_mod.png").write_bytes(b"x" * (1_024 * 1_024 + 1))
            unrelated_preview = root / "preview.jpg"
            unrelated_preview.write_bytes(b"small unrelated preview")

            api = API(root / "state")
            self.assertTrue(
                api.call(
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
                )["ok"]
            )
            mod = api.call("scan_mods", [False])["data"]["mods"][0]

            rejected = api.call(
                "publish_workshop_item",
                [
                    mod["id"],
                    {
                        "mode": "upload",
                        "title": "My Own Mod",
                        "language": "en-US",
                        "preview_path": str(unrelated_preview),
                        "category": "units",
                        "visibility": 0,
                    },
                ],
            )

            self.assertFalse(rejected["ok"])

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
                return_value={
                    "operation": "force_update",
                    "workshop_id": "123",
                    "accepted": True,
                    "completed": True,
                },
            ) as steam_operation:
                updated = api.call("force_update_workshop_mod", [merged["id"]])
                unsubscribed = api.call("unsubscribe_workshop_mod", [merged["id"]])
            self.assertTrue(updated["ok"])
            self.assertTrue(unsubscribed["ok"])
            self.assertEqual(
                [call.args[:2] for call in steam_operation.call_args_list],
                [("force_update", "123"), ("unsubscribe", "123")],
            )

    def test_workshop_page_actions_use_browser_and_official_steam_client_uri(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            asset = ModAsset(
                id="steam:123:example.pack",
                pack_name="example.pack",
                display_name="Example",
                path=str(Path(temporary) / "example.pack"),
                directory=temporary,
                source=SOURCE_WORKSHOP,
                workshop_id="123",
            )
            api._assets = {asset.id: asset}

            with patch("backend.api.webbrowser.open", return_value=True) as browser:
                browser_result = api.call("open_workshop_page", [asset.id])
            with patch.object(api, "_open_uri") as open_uri:
                client_result = api.call("open_workshop_client", [asset.id])

        self.assertTrue(browser_result["ok"])
        browser.assert_called_once_with(
            "https://steamcommunity.com/sharedfiles/filedetails/?id=123"
        )
        self.assertTrue(client_result["ok"])
        open_uri.assert_called_once_with("steam://url/CommunityFilePage/123")

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
