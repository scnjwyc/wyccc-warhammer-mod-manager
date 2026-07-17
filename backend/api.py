from __future__ import annotations

import base64
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from PIL import Image, ImageOps

from .app_settings import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    SettingsService,
    default_data_dir,
)
from .ai_service import generate_mod_user_data
from .changelog import get_all_changelogs
from .constants import (
    APP_NAME,
    APP_VERSION,
    GAME_DATA_FEATURE_WORKSHOP_ITEMS,
    INTERNAL_FEATURE_WORKSHOP_IDS,
    SOURCE_DATA,
    SOURCE_WORKSHOP,
    WH3_APP_ID,
    WH3_EXECUTABLE,
)
from .file_operations import (
    build_delete_preview,
    execute_delete_preview,
    workshop_item_directory,
)
from .game_data_patch_state import (
    ensure_game_data_patch,
    game_data_settings_requested,
    load_manifest_subscription_state,
)
from .launcher import is_game_running, launch_game
from .load_order import LoadOrderService, current_order_path, file_token
from .models import ModAsset
from .mod_profiles import existing_profile_directory, parse_mod_profile
from .mod_watcher import ModChangeMonitor
from .scanner import ModScanner
from .save_games import SaveGameService
from .share import (
    export_share,
    parse_pending_workshop_mod_id,
    parse_share,
    resolve_share,
    resolve_share_with_pending,
)
from .storage import StateRepository
from .start_options import (
    GAME_DATA_PATCH_NAME,
    RUNTIME_PACK_NAME,
    build_runtime_options_pack,
)
from .steamworks_bridge import (
    SteamworksBridgeError,
    perform_workshop_operation,
    publish_workshop_item,
    query_workshop_subscription_status,
    subscribe_workshop_items,
)
from .update_service import UpdateService
from .workshop import (
    ENGLISH_STEAM_LANGUAGE,
    WorkshopMetadataService,
    interface_language_for_steam,
    steam_language_for_interface,
)


logger = logging.getLogger(__name__)
GAME_DATA_SETTING_KEYS = frozenset(
    {
        "unit_model_multiplier",
        "single_entity_unit_mode",
        "scale_lord_hero_health",
        "disable_unit_friendly_fire",
        "disable_spell_friendly_fire",
    }
)
MAX_WORKSHOP_COVER_BYTES = 1_024 * 1_024


def _require_workshop_cover(source_pack: Path) -> Path:
    cover_path = source_pack.with_suffix(".png")
    if not cover_path.is_file():
        raise ValueError(
            f"MOD 封面必须与 Pack 同目录且同名：{cover_path.name}"
        )
    try:
        cover_size = cover_path.stat().st_size
    except OSError as exc:
        raise ValueError(f"无法读取 MOD 封面：{cover_path}") from exc
    if cover_size > MAX_WORKSHOP_COVER_BYTES:
        raise ValueError("MOD 封面图不能超过 1 MB")
    return cover_path


def _stage_workshop_upload_file(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


class API:
    """Single explicit RPC facade exposed through pywebview."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.settings_service = SettingsService(self.data_dir)
        self.update_service = UpdateService(self.data_dir, self.settings_service)
        self.state_repository = StateRepository(self.data_dir / "state.db")
        self.workshop_service = WorkshopMetadataService(self.data_dir / "workshop_cache.json")
        self.scanner = ModScanner(self.workshop_service)
        self.load_order = LoadOrderService(self.data_dir / "backups")
        self.save_games = SaveGameService()
        self._assets: dict[str, ModAsset] = {}
        self._asset_aliases: dict[str, str] = {}
        self._thumbnail_cache: dict[str, tuple[str, str]] = {}
        self._scan_lock = threading.Lock()
        self._order_lock = threading.Lock()
        self._delete_preview_lock = threading.Lock()
        self._delete_previews: dict[str, tuple[float, dict[str, Any]]] = {}
        self._mod_revision_lock = threading.Lock()
        self._mod_revision = 0
        self._runtime_lock = threading.Lock()
        self._last_runtime_running: bool | None = None
        self._game_executable_lock = threading.Lock()
        self._game_executable_cache: str | None = None
        self._game_data_subscription_lock = threading.Lock()
        self._game_data_subscription_cache: dict[str, dict[str, Any]] = {}
        self._game_data_subscription_cache_known = False
        self._game_data_patch_lock = threading.Lock()
        self._internal_feature_mod_ids: set[str] = set()
        self.mod_monitor = ModChangeMonitor(self._record_mod_change)
        self._window: Any | None = None
        self._exit_low_consumption_callback: Callable[[], bool] | None = None
        self._last_order_token = "missing"
        self._rpc: dict[str, Callable[..., Any]] = {
            "get_bootstrap": self._get_bootstrap,
            "detect_paths": self._detect_paths,
            "save_settings": self._save_settings,
            "save_game_data_settings": self._save_game_data_settings,
            "get_game_data_feature_status": self._get_game_data_feature_status,
            "check_for_updates": self._check_for_updates,
            "download_update": self._download_update,
            "install_update": self._install_update,
            "ignore_update": self._ignore_update,
            "get_changelog": self._get_changelog,
            "acknowledge_changelog": self._acknowledge_changelog,
            "select_directory": self._select_directory,
            "select_mod_profile": self._select_mod_profile,
            "scan_mods": self._scan_mods,
            "save_mod_user_data": self._save_mod_user_data,
            "generate_mod_user_data": self._generate_mod_user_data,
            "list_mod_types": self._list_mod_types,
            "create_mod_type": self._create_mod_type,
            "update_mod_type": self._update_mod_type,
            "delete_mod_type": self._delete_mod_type,
            "set_mod_type": self._set_mod_type,
            "set_mod_types": self._set_mod_types,
            "set_mod_hidden": self._set_mod_hidden,
            "set_mod_warning_ignored": self._set_mod_warning_ignored,
            "preview_load_order": self._preview_load_order,
            "save_load_order": self._save_load_order,
            "launch_game": self._launch_game,
            "continue_game": self._continue_game,
            "list_save_games": self._list_save_games,
            "get_save_mods": self._get_save_mods,
            "get_runtime_status": self._get_runtime_status,
            "exit_low_consumption_mode": self._exit_low_consumption_mode,
            "exit_app": self._exit_app,
            "list_playsets": self._list_playsets,
            "create_playset": self._create_playset,
            "rename_playset": self._rename_playset,
            "update_playset": self._update_playset,
            "delete_playset": self._delete_playset,
            "switch_playset": self._switch_playset,
            "list_backups": self._list_backups,
            "export_share": self._export_share,
            "preview_import_share": self._preview_import_share,
            "import_share": self._import_share,
            "preview_mod_profile": self._preview_mod_profile,
            "import_mod_profile": self._import_mod_profile,
            "subscribe_workshop_items": self._subscribe_workshop_items,
            "get_mod_preview": self._get_mod_preview,
            "get_mod_thumbnails": self._get_mod_thumbnails,
            "open_mod_folder": self._open_mod_folder,
            "open_workshop_folder": self._open_workshop_folder,
            "open_game_folder": self._open_game_folder,
            "open_workshop_page": self._open_workshop_page,
            "open_workshop_client": self._open_workshop_client,
            "open_external_url": self._open_external_url,
            "preview_delete_mod_files": self._preview_delete_mod_files,
            "delete_mod_files": self._delete_mod_files,
            "unsubscribe_workshop_mod": self._unsubscribe_workshop_mod,
            "unsubscribe_workshop_mods": self._unsubscribe_workshop_mods,
            "force_update_workshop_mod": self._force_update_workshop_mod,
            "get_workshop_publish_copy": self._get_workshop_publish_copy,
            "publish_workshop_item": self._publish_workshop_item,
            "open_mod_in_rpfm": self._open_mod_in_rpfm,
            "copy_mod_to_data": self._copy_mod_to_data,
            "sync_workshop_to_data": self._sync_workshop_to_data,
        }

    @property
    def rpc_methods(self) -> frozenset[str]:
        return frozenset(self._rpc)

    def bind_window(self, window: Any) -> None:
        self._window = window

    def bind_low_consumption_exit(self, callback: Callable[[], bool]) -> None:
        self._exit_low_consumption_callback = callback

    def interface_language(self) -> str:
        return str(self.settings_service.get().get("language") or DEFAULT_LANGUAGE)

    def close(self) -> None:
        self.mod_monitor.stop()
        self._exit_low_consumption_callback = None

    def _exit_low_consumption_mode(self) -> dict[str, bool]:
        callback = self._exit_low_consumption_callback
        if callback is None:
            raise ValueError("低消耗模式控制器尚未就绪")
        return {"restored": bool(callback())}

    def _exit_app(self) -> dict[str, bool]:
        window = self._window
        if window is None:
            raise ValueError("应用窗口尚未就绪")

        def destroy() -> None:
            try:
                window.destroy()
            except Exception:
                traceback.print_exc()

        timer = threading.Timer(0.05, destroy)
        timer.daemon = True
        timer.start()
        return {"closing": True}

    def call(
        self,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The only method exposed through the desktop bridge."""
        handler = self._rpc.get(str(method))
        if handler is None:
            return {
                "ok": False,
                "error": {"code": "METHOD_NOT_ALLOWED", "message": "该操作未开放"},
            }
        try:
            data = handler(*(args or []), **(kwargs or {}))
            return {"ok": True, "data": data}
        except (ValueError, OSError) as exc:
            return {
                "ok": False,
                "error": {"code": exc.__class__.__name__.upper(), "message": str(exc)},
            }
        except Exception as exc:
            traceback.print_exc()
            return {
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"操作失败：{exc}",
                },
            }

    def _get_bootstrap(self) -> dict[str, Any]:
        settings = self.settings_service.get_public()
        paths = self.settings_service.resolve_game_paths()
        target = self._active_order_path(paths.game_path) if paths.game_path else Path()
        self._last_order_token = file_token(target) if paths.game_path else "missing"
        current_playset = self.state_repository.get_current_playset()
        private_settings = self.settings_service.get()
        running = self._current_runtime_running()
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "settings": settings,
            "paths": paths.to_dict(),
            "path_health": self._path_health(paths.game_path, paths.data_path, paths.workshop_path),
            "enabled_order": current_playset["mod_ids"],
            "playsets": self.state_repository.list_playsets(),
            "current_playset": current_playset,
            "backups": self.state_repository.list_backups(),
            "mod_types": self.state_repository.list_mod_types(),
            "order_token": self._last_order_token,
            "runtime": self._runtime_payload(running),
            "changelog": get_all_changelogs(str(settings.get("language") or DEFAULT_LANGUAGE)),
            "show_changelog": private_settings.get("last_seen_app_version") != APP_VERSION,
            "auto_update_due": self.update_service.should_check_automatically(private_settings),
            "update_install_error": self.update_service.consume_install_error(),
        }

    def _get_game_data_feature_status(self) -> dict[str, Any]:
        workshop_ids = [
            item["workshop_id"]
            for item in GAME_DATA_FEATURE_WORKSHOP_ITEMS.values()
        ]
        warning = ""
        live_success = False
        language = steam_language_for_interface(self.interface_language())
        try:
            statuses = query_workshop_subscription_status(
                workshop_ids,
                language,
                app_id=WH3_APP_ID,
            )
        except SteamworksBridgeError as exc:
            warning = f"无法刷新游戏数据功能的 Workshop 订阅状态：{exc}"
        else:
            live_success = True
            status_by_id = {
                str(item.get("workshop_id") or ""): item
                for item in statuses
                if isinstance(item, dict)
            }
            with self._game_data_subscription_lock:
                self._game_data_subscription_cache = {
                    item["workshop_id"]: {
                        "subscribed": bool(
                            status_by_id.get(item["workshop_id"], {}).get("subscribed")
                        ),
                        "title": str(
                            status_by_id.get(item["workshop_id"], {}).get("title") or item["title"]
                        ).strip(),
                    }
                    for item in GAME_DATA_FEATURE_WORKSHOP_ITEMS.values()
                }
                self._game_data_subscription_cache_known = True

        with self._game_data_subscription_lock:
            cached = {
                workshop_id: dict(status)
                for workshop_id, status in self._game_data_subscription_cache.items()
            }
            known = self._game_data_subscription_cache_known
        return {
            "items": {
                key: {
                    **item,
                    "title": str(
                        cached.get(item["workshop_id"], {}).get("title") or item["title"]
                    ),
                    "subscribed": bool(
                        cached.get(item["workshop_id"], {}).get("subscribed")
                    ),
                }
                for key, item in GAME_DATA_FEATURE_WORKSHOP_ITEMS.items()
            },
            "warning": warning,
            "known": known,
            "source": "live" if live_success else ("memory" if known else "unavailable"),
        }

    def _check_for_updates(
        self,
        manual: bool = True,
        manifest_url: str | None = None,
    ) -> dict[str, Any]:
        result = self.update_service.check(manual=bool(manual), manifest_url=manifest_url)
        language = str(self.settings_service.get().get("language") or DEFAULT_LANGUAGE)
        local_release = next(
            (
                release
                for release in get_all_changelogs(language)
                if release["version"] == result.get("version")
            ),
            None,
        )
        if local_release:
            result["entries"] = local_release["entries"]
        return result

    def _download_update(self, version: str = "") -> dict[str, Any]:
        return self.update_service.download(version)

    def _install_update(self, version: str = "") -> dict[str, Any]:
        return self.update_service.install_and_restart(version)

    def _ignore_update(self, version: str) -> dict[str, Any]:
        return self.update_service.ignore(version)

    def _get_changelog(self) -> dict[str, Any]:
        language = str(self.settings_service.get().get("language") or DEFAULT_LANGUAGE)
        return {"items": get_all_changelogs(language), "current_version": APP_VERSION}

    def _acknowledge_changelog(self) -> dict[str, str]:
        self.settings_service.save({"last_seen_app_version": APP_VERSION})
        return {"last_seen_app_version": APP_VERSION}

    def _detect_paths(self) -> dict[str, Any]:
        result = self.settings_service.detect_and_save()
        result["settings"] = self.settings_service.get_public()
        self._assets.clear()
        self._asset_aliases.clear()
        self._invalidate_game_executable_cache()
        self._sync_runtime_services(self.detect_game_running(), force=True)
        return result

    def _save_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.settings_service.save(changes)
        settings = self.settings_service.get_public()
        paths = self.settings_service.resolve_game_paths()
        self._assets.clear()
        self._asset_aliases.clear()
        self._invalidate_game_executable_cache()
        self._sync_runtime_services(self.detect_game_running(), force=True)
        return {
            "settings": settings,
            "paths": paths.to_dict(),
            "path_health": self._path_health(paths.game_path, paths.data_path, paths.workshop_path),
        }

    def _save_game_data_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        filtered = self._game_data_setting_changes(changes)
        self.settings_service.save(filtered)
        return {"settings": self.settings_service.get_public()}

    @staticmethod
    def _game_data_setting_changes(changes: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, dict):
            raise ValueError("游戏数据设置必须是对象")
        return {key: value for key, value in changes.items() if key in GAME_DATA_SETTING_KEYS}

    def _resolve_game_data_subscription_state(
        self,
        settings: dict[str, Any],
    ) -> dict[str, bool]:
        feature_status = self._get_game_data_feature_status()
        warning = str(feature_status.get("warning") or "")
        requested = game_data_settings_requested(settings)
        known = bool(feature_status.get("known"))
        if known:
            subscription_state = {
                str(item.get("workshop_id") or ""): bool(item.get("subscribed"))
                for item in feature_status.get("items", {}).values()
                if str(item.get("workshop_id") or "")
            }
            if warning:
                logger.warning(
                    "Game data patch status=subscription_error source=%s requested=%s detail=%s",
                    feature_status.get("source") or "memory",
                    str(requested).lower(),
                    warning,
                )
            return subscription_state

        manifest_state = load_manifest_subscription_state(self.data_dir / "runtime")
        if manifest_state is not None:
            logger.warning(
                "Game data patch status=subscription_error source=manifest requested=%s detail=%s",
                str(requested).lower(),
                warning or "subscription state unavailable",
            )
            return manifest_state
        if requested:
            logger.error(
                "Game data patch status=subscription_error source=unavailable requested=true detail=%s",
                warning or "subscription state unavailable",
            )
            raise ValueError("无法确认游戏数据功能的 Workshop 订阅状态，已取消启动")
        logger.warning(
            "Game data patch status=subscription_error source=unavailable requested=false action=zero_modification detail=%s",
            warning or "subscription state unavailable",
        )
        return {}

    @staticmethod
    def _select_directory(kind: str) -> dict[str, str]:
        if kind not in {"game", "workshop", "preview"}:
            raise ValueError("不支持的目录类型")
        try:
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if kind == "preview":
                selected = filedialog.askopenfilename(
                    title="选择 Workshop 预览图",
                    filetypes=(
                        ("图片文件", "*.png *.jpg *.jpeg"),
                        ("PNG", "*.png"),
                        ("JPEG", "*.jpg *.jpeg"),
                        ("所有文件", "*.*"),
                    ),
                )
            else:
                title = "选择 Warhammer III 游戏目录" if kind == "game" else "选择 Workshop 目录"
                selected = filedialog.askdirectory(title=title)
            root.destroy()
            return {"path": str(selected or "")}
        except Exception as exc:
            raise ValueError(f"无法打开目录选择器：{exc}") from exc

    @staticmethod
    def _select_mod_profile() -> dict[str, str]:
        try:
            import tkinter
            from tkinter import filedialog

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(
                title="选择官方 MOD 启动器配置",
                initialdir=str(existing_profile_directory()),
                filetypes=(
                    ("Total War MOD 配置", "*.twmods"),
                    ("所有文件", "*.*"),
                ),
            )
            root.destroy()
            return {"path": str(selected or "")}
        except Exception as exc:
            raise ValueError(f"无法打开官方配置选择器：{exc}") from exc

    def _scan_mods(self, refresh_workshop: bool = False) -> dict[str, Any]:
        if not self._scan_lock.acquire(blocking=False):
            raise ValueError("扫描正在进行中")
        try:
            scan_revision = self._mod_revision_value()
            settings = self.settings_service.get()
            paths = self.settings_service.resolve_game_paths()
            health = self._path_health(paths.game_path, paths.data_path, paths.workshop_path)
            if not health["game_ready"]:
                raise ValueError("游戏目录无效，请先在设置中自动检测或手动指定")
            scan_result = self.scanner.scan(paths, settings, bool(refresh_workshop))
            user_data = self.state_repository.list_user_mod_data()
            self._internal_feature_mod_ids = {
                mod_id
                for mod_id, custom in user_data.items()
                if str(custom.get("published_workshop_id") or "")
                in INTERNAL_FEATURE_WORKSHOP_IDS
            }
            for mod in scan_result.mods:
                custom = user_data.get(mod.id, {})
                if not custom:
                    custom = next(
                        (user_data[alias] for alias in mod.alternate_ids if alias in user_data),
                        {},
                    )
                mod.alias = str(custom.get("alias") or "")
                mod.notes = str(custom.get("notes") or "")
                raw_types = custom.get("mod_types")
                mod.mod_types = list(raw_types) if isinstance(raw_types, list) else [
                    str(custom.get("mod_type") or "unknown")
                ]
                mod.mod_type = mod.mod_types[0] if mod.mod_types else "unknown"
                if not mod.workshop_id and str(custom.get("published_workshop_id") or "").isdigit():
                    mod.workshop_id = str(custom["published_workshop_id"])
                    mod.workshop_url = (
                        "https://steamcommunity.com/sharedfiles/filedetails/"
                        f"?id={mod.workshop_id}"
                    )
                mod.hidden = bool(custom.get("hidden"))
                raw_ignored_warning_codes = custom.get("ignored_warning_codes")
                mod.ignored_warning_codes = (
                    list(raw_ignored_warning_codes)
                    if isinstance(raw_ignored_warning_codes, list)
                    else []
                )
            self._assets = {mod.id: mod for mod in scan_result.mods}
            self._asset_aliases = {
                alias: mod.id
                for mod in scan_result.mods
                for alias in mod.alternate_ids
            }
            self._thumbnail_cache = {
                mod_id: cached
                for mod_id, cached in self._thumbnail_cache.items()
                if mod_id in self._assets
            }

            current_playset = self.state_repository.get_current_playset()
            original_order = list(current_playset["mod_ids"])
            if not self.state_repository.are_playsets_initialized():
                original_order = self.load_order.import_disk_order(
                    paths.game_path,
                    scan_result.mods,
                    self.state_repository.get_active_order_filename(),
                )
                self.state_repository.update_current_playset(original_order)
                self.state_repository.mark_playsets_initialized()
            stored_order = self._canonicalize_mod_ids(original_order)
            if stored_order != original_order:
                self.state_repository.update_current_playset(stored_order)
            present_order = [mod_id for mod_id in stored_order if mod_id in self._assets]
            missing_order = [mod_id for mod_id in stored_order if mod_id not in self._assets]
            self._refresh_missing_dependency_warnings(present_order)
            target = self._active_order_path(paths.game_path)
            self._last_order_token = file_token(target)
            payload = scan_result.to_dict()
            payload.update(
                {
                    "enabled_order": present_order,
                    "missing_enabled_ids": missing_order,
                    "order_token": self._last_order_token,
                    "playsets": self.state_repository.list_playsets(),
                    "current_playset": self.state_repository.get_current_playset(),
                    # A filesystem event arriving during this scan must remain
                    # visible to the frontend so it schedules one follow-up scan.
                    "mod_revision": scan_revision,
                }
            )
            return payload
        finally:
            self._scan_lock.release()

    def _save_mod_user_data(self, mod_id: str, alias: str = "", notes: str = "") -> dict[str, Any]:
        asset = self._require_asset(mod_id)
        saved = self.state_repository.save_user_mod_data(asset.id, alias, notes)
        asset.alias = saved["alias"]
        asset.notes = saved["notes"]
        return asset.to_dict()

    def _generate_mod_user_data(self, mod_id: str) -> dict[str, Any]:
        asset = self._require_asset(mod_id)
        generated = generate_mod_user_data(asset, self.settings_service.get())
        return self._save_mod_user_data(asset.id, generated["alias"], generated["notes"])

    def _list_mod_types(self) -> list[dict[str, Any]]:
        return self.state_repository.list_mod_types()

    def _create_mod_type(self, name: str) -> dict[str, Any]:
        created = self.state_repository.create_mod_type(name)
        return {"item": created, "items": self.state_repository.list_mod_types()}

    def _update_mod_type(self, type_id: str, name: str) -> dict[str, Any]:
        updated = self.state_repository.update_mod_type(type_id, name)
        return {"item": updated, "items": self.state_repository.list_mod_types()}

    def _delete_mod_type(self, type_id: str) -> dict[str, Any]:
        self.state_repository.delete_mod_type(type_id)
        for asset in self._assets.values():
            asset.mod_types = [item for item in asset.mod_types if item != type_id] or ["unknown"]
            asset.mod_type = asset.mod_types[0]
        return {"items": self.state_repository.list_mod_types()}

    def _set_mod_type(self, mod_id: str, type_id: str) -> dict[str, Any]:
        asset = self._require_asset(mod_id)
        asset.mod_type = self.state_repository.set_mod_type(asset.id, type_id)
        asset.mod_types = [asset.mod_type]
        return asset.to_dict()

    def _set_mod_types(self, mod_id: str, type_ids: list[str]) -> dict[str, Any]:
        asset = self._require_asset(mod_id)
        asset.mod_types = self.state_repository.set_mod_types(asset.id, type_ids)
        asset.mod_type = asset.mod_types[0]
        return asset.to_dict()

    def _set_mod_hidden(self, mod_id: str, hidden: bool) -> dict[str, Any]:
        asset = self._require_asset(mod_id)
        asset.hidden = self.state_repository.set_mod_hidden(asset.id, hidden)
        return asset.to_dict()

    def _set_mod_warning_ignored(
        self,
        mod_id: str,
        warning_code: str,
        ignored: bool,
    ) -> dict[str, Any]:
        asset = self._require_asset(mod_id)
        asset.ignored_warning_codes = self.state_repository.set_mod_warning_ignored(
            asset.id,
            warning_code,
            bool(ignored),
        )
        return asset.to_dict()

    def _preview_load_order(self, ordered_mod_ids: list[str]) -> dict[str, Any]:
        paths = self.settings_service.resolve_game_paths()
        ordered_mod_ids = self._canonicalize_mod_ids(ordered_mod_ids)
        plan = self.load_order.build_plan(
            paths.game_path,
            paths.data_path,
            self._assets,
            ordered_mod_ids,
        )
        return plan.to_dict()

    def _save_load_order(
        self,
        ordered_mod_ids: list[str],
        expected_token: str = "",
    ) -> dict[str, Any]:
        with self._order_lock:
            return self._save_load_order_locked(ordered_mod_ids, expected_token)

    def _save_load_order_locked(
        self,
        ordered_mod_ids: list[str],
        expected_token: str = "",
    ) -> dict[str, Any]:
        paths = self.settings_service.resolve_game_paths()
        ordered_mod_ids = self._canonicalize_mod_ids(ordered_mod_ids)
        plan = self.load_order.build_plan(
            paths.game_path,
            paths.data_path,
            self._assets,
            ordered_mod_ids,
        )
        comparison_path = self._active_order_path(paths.game_path)
        previous_order = self.load_order.import_order_file(
            comparison_path,
            list(self._assets.values()),
        )
        written_plan, backup_path, token = self.load_order.write_plan(
            plan,
            expected_token or self._last_order_token,
            comparison_path,
        )
        self.state_repository.update_current_playset(written_plan.ordered_mod_ids)
        self._refresh_missing_dependency_warnings(written_plan.ordered_mod_ids)
        self.state_repository.set_active_order_filename(Path(written_plan.target_path).name)
        backup = None
        if backup_path:
            backup = self.state_repository.add_backup(
                backup_path,
                previous_order,
            )
        self._last_order_token = token
        return {
            "plan": written_plan.to_dict(),
            "backup": backup,
            "order_token": token,
        }

    def _launch_game(
        self,
        ordered_mod_ids: list[str],
        expected_token: str = "",
        save_name: str = "",
    ) -> dict[str, Any]:
        if not self._game_data_patch_lock.acquire(blocking=False):
            raise ValueError("游戏数据补丁正在生成，暂时无法启动游戏")
        try:
            return self._launch_game_when_patch_idle(
                ordered_mod_ids,
                expected_token,
                save_name,
            )
        finally:
            self._game_data_patch_lock.release()

    def _launch_game_when_patch_idle(
        self,
        ordered_mod_ids: list[str],
        expected_token: str,
        save_name: str,
    ) -> dict[str, Any]:
        with self._order_lock:
            selected_save = self.save_games.require(save_name) if save_name else None
            saved = self._save_load_order_locked(ordered_mod_ids, expected_token)
            paths = self.settings_service.resolve_game_paths()
            settings = self.settings_service.get()
            subscription_state = self._resolve_game_data_subscription_state(settings)
            try:
                game_data_patch = ensure_game_data_patch(
                    output_dir=self.data_dir / "runtime",
                    data_path=paths.data_path,
                    assets=self._assets,
                    active_ids=saved["plan"]["ordered_mod_ids"],
                    playset_id=self.state_repository.get_current_playset_id(),
                    settings=settings,
                    subscription_state=subscription_state,
                )
            except Exception:
                logger.exception("Game data patch status=generation_failed")
                raise
            logger.info(
                "Game data patch status=%s fingerprint=%s changed_inputs=%s entries=%s game_data=%s",
                game_data_patch["status"],
                str(game_data_patch.get("fingerprint") or "")[:12],
                ",".join(game_data_patch.get("changed_inputs", [])) or "none",
                game_data_patch.get("entry_count", 0),
                game_data_patch.get("game_data", {}),
            )
            runtime = build_runtime_options_pack(
                self.data_dir / "runtime",
                paths.data_path,
                self._assets,
                saved["plan"]["ordered_mod_ids"],
                settings,
            )
            launch_plan = saved["plan"]
            launch_path = saved["plan"]["target_path"]

            internal_assets: dict[str, ModAsset] = {}
            internal_ids: list[str] = []
            game_data_path = Path(str(game_data_patch.get("path") or ""))
            if game_data_patch.get("path") and game_data_path.is_file():
                game_data_id = "runtime:game-data-patch"
                internal_assets[game_data_id] = ModAsset(
                    id=game_data_id,
                    pack_name=GAME_DATA_PATCH_NAME,
                    display_name="Wyccc 游戏数据补丁",
                    path=str(game_data_path.resolve(strict=False)),
                    directory=str(game_data_path.parent.resolve(strict=False)),
                    source="runtime",
                    sources=["runtime"],
                )
                internal_ids.append(game_data_id)
            if runtime["path"]:
                runtime_path = Path(runtime["path"])
                runtime_id = "runtime:start-options"
                internal_assets[runtime_id] = ModAsset(
                    id=runtime_id,
                    pack_name=RUNTIME_PACK_NAME,
                    display_name="Wyccc 启动选项",
                    path=str(runtime_path),
                    directory=str(runtime_path.parent),
                    source="runtime",
                    sources=["runtime"],
                )
                internal_ids.append(runtime_id)

            if internal_ids:
                runtime_assets = {**self._assets, **internal_assets}
                runtime_plan = self.load_order.build_plan(
                    paths.game_path,
                    paths.data_path,
                    runtime_assets,
                    [*saved["plan"]["ordered_mod_ids"], *internal_ids],
                    target_name="wyccc_launch_mods.txt",
                )
                self.load_order._atomic_write(Path(runtime_plan.target_path), runtime_plan.content)
                launch_plan = runtime_plan.to_dict()
                launch_path = runtime_plan.target_path
            process = launch_game(
                paths.game_path,
                launch_path,
                str(selected_save["name"]) if selected_save else "",
            )
            self.set_game_running(True, force=True)
            return {
                **saved,
                "process": process,
                "game_data_patch": game_data_patch,
                "runtime_options": runtime,
                "launch_plan": launch_plan,
                "save": selected_save,
            }

    def _continue_game(
        self,
        ordered_mod_ids: list[str],
        expected_token: str = "",
    ) -> dict[str, Any]:
        latest = self.save_games.latest()
        return self._launch_game(
            ordered_mod_ids,
            expected_token,
            str(latest["name"]),
        )

    def _list_save_games(self) -> dict[str, Any]:
        return {
            "directory": str(self.save_games.save_directory.resolve(strict=False)),
            "items": self.save_games.list(),
        }

    def _vanilla_pack_names(self) -> set[str]:
        paths = self.settings_service.resolve_game_paths()
        warnings: list[str] = []
        data_path = Path(paths.data_path) if paths.data_path else Path()
        return self.scanner._read_vanilla_manifest(data_path, warnings)

    def _get_save_mods(self, save_name: str) -> dict[str, Any]:
        return self.save_games.pack_names(save_name, self._vanilla_pack_names())

    def _record_mod_change(self) -> None:
        with self._mod_revision_lock:
            self._mod_revision += 1

    def _mod_revision_value(self) -> int:
        with self._mod_revision_lock:
            return self._mod_revision

    def _sync_runtime_services(self, running: bool, *, force: bool = False) -> None:
        with self._runtime_lock:
            previous = self._last_runtime_running
            if not force and previous is running:
                return
            self._last_runtime_running = running
            if previous is None or previous is not running:
                logger.info(
                    "Warhammer III runtime state changed: running=%s executable=%s",
                    running,
                    self.game_executable_path(),
                )
            if running:
                self.mod_monitor.stop()
                return
            settings = self.settings_service.get()
            if not settings.get("live_mod_detection", True):
                self.mod_monitor.stop()
                return
            paths = self.settings_service.resolve_game_paths()
            self.mod_monitor.start(paths.data_path, paths.workshop_path)

    def set_game_running(self, running: bool, *, force: bool = False) -> None:
        self._sync_runtime_services(bool(running), force=force)

    def _invalidate_game_executable_cache(self) -> None:
        with self._game_executable_lock:
            self._game_executable_cache = None

    def game_executable_path(self) -> str:
        with self._game_executable_lock:
            cached = self._game_executable_cache
        if cached is not None:
            return cached
        paths = self.settings_service.resolve_game_paths()
        executable = str(Path(paths.game_path) / WH3_EXECUTABLE) if paths.game_path else ""
        with self._game_executable_lock:
            self._game_executable_cache = executable
        return executable

    def detect_game_running(self) -> bool:
        return is_game_running(self.game_executable_path())

    def _current_runtime_running(self) -> bool:
        with self._runtime_lock:
            cached = self._last_runtime_running
        if cached is not None:
            return cached
        running = self.detect_game_running()
        self._sync_runtime_services(running, force=True)
        return running

    def _runtime_payload(self, running: bool) -> dict[str, Any]:
        return {
            "running": running,
            "mod_revision": self._mod_revision_value(),
            "live_mod_detection_available": self.mod_monitor.available,
            "live_mod_detection_active": self.mod_monitor.active,
        }

    def _get_runtime_status(self) -> dict[str, Any]:
        running = self._current_runtime_running()
        return self._runtime_payload(running)

    def _list_playsets(self) -> list[dict[str, Any]]:
        return self.state_repository.list_playsets()

    def _current_playset_payload(self) -> dict[str, Any]:
        current = self.state_repository.get_current_playset()
        canonical_ids = self._canonicalize_mod_ids(current["mod_ids"])
        if canonical_ids != current["mod_ids"]:
            current = self.state_repository.update_current_playset(canonical_ids)
        present = [mod_id for mod_id in canonical_ids if mod_id in self._assets]
        missing = [mod_id for mod_id in canonical_ids if mod_id not in self._assets]
        self._refresh_missing_dependency_warnings(present)
        return {
            "playsets": self.state_repository.list_playsets(),
            "current_playset": current,
            "ordered_mod_ids": present,
            "missing_mod_ids": missing,
        }

    def _create_playset(self, name: str, mod_ids: list[str]) -> dict[str, Any]:
        self.state_repository.create_playset(
            name,
            self._canonicalize_mod_ids(mod_ids),
        )
        return self._current_playset_payload()

    def _rename_playset(self, playset_id: str, name: str) -> dict[str, Any]:
        playset = self.state_repository.rename_playset(playset_id, name)
        return {
            "playset": playset,
            "playsets": self.state_repository.list_playsets(),
            "current_playset": self.state_repository.get_current_playset(),
        }

    def _update_playset(self, playset_id: str, mod_ids: list[str]) -> dict[str, Any]:
        playset = self.state_repository.update_playset(
            playset_id,
            self._canonicalize_mod_ids(mod_ids),
        )
        self._refresh_missing_dependency_warnings(
            self.state_repository.get_current_playset()["mod_ids"]
        )
        return {
            "playset": playset,
            "playsets": self.state_repository.list_playsets(),
            "current_playset": self.state_repository.get_current_playset(),
        }

    def _delete_playset(self, playset_id: str) -> dict[str, Any]:
        self.state_repository.delete_playset(playset_id)
        return self._current_playset_payload()

    def _switch_playset(self, playset_id: str) -> dict[str, Any]:
        self.state_repository.switch_playset(playset_id)
        return self._current_playset_payload()

    def _list_backups(self) -> list[dict[str, Any]]:
        return self.state_repository.list_backups()

    def _export_share(self, ordered_mod_ids: list[str]) -> dict[str, str]:
        mods = [self._require_asset(mod_id) for mod_id in ordered_mod_ids]
        return {"share_code": export_share(mods)}

    def _preview_import_share(self, share_code: str) -> dict[str, Any]:
        references = parse_share(share_code)
        ordered_ids, missing = resolve_share(references, self._assets)
        references_by_workshop_id: dict[str, dict[str, Any]] = {}
        for reference in references:
            workshop_id = str(reference.get("workshop_id") or "").strip()
            if workshop_id.isdigit() and workshop_id not in references_by_workshop_id:
                references_by_workshop_id[workshop_id] = reference

        statuses: list[dict[str, Any]] = []
        if references_by_workshop_id:
            language = steam_language_for_interface(
                str(self.settings_service.get().get("language") or "")
            )
            try:
                statuses = query_workshop_subscription_status(
                    list(references_by_workshop_id),
                    language,
                    app_id=WH3_APP_ID,
                )
            except SteamworksBridgeError as exc:
                raise ValueError(f"无法检查分享码中的 Workshop 订阅状态：{exc}") from exc

        unsubscribed = []
        for item in statuses:
            if item.get("subscribed"):
                continue
            workshop_id = str(item.get("workshop_id") or "")
            reference = references_by_workshop_id.get(workshop_id, {})
            unsubscribed.append(
                {
                    "workshop_id": workshop_id,
                    "title": str(item.get("title") or "").strip(),
                    "pack_name": str(reference.get("pack_name") or "").strip(),
                }
            )
        return {
            "ordered_mod_ids": ordered_ids,
            "missing": missing,
            "unsubscribed": unsubscribed,
        }

    def _import_share(self, share_code: str) -> dict[str, Any]:
        references = parse_share(share_code)
        ordered_ids, missing = resolve_share_with_pending(references, self._assets)
        self.state_repository.update_current_playset(ordered_ids)
        pending_workshop_ids = list(
            dict.fromkeys(
                str(reference.get("workshop_id") or "")
                for reference in missing
                if str(reference.get("workshop_id") or "").isdigit()
            )
        )
        return {
            **self._current_playset_payload(),
            "missing": missing,
            "pending_workshop_ids": pending_workshop_ids,
        }

    def _preview_mod_profile(self, profile_path: str) -> dict[str, Any]:
        parsed = parse_mod_profile(profile_path)
        references = parsed["references"]
        ordered_ids, missing = resolve_share(references, self._assets)
        references_by_workshop_id = {
            str(reference["workshop_id"]): reference
            for reference in references
        }
        language = steam_language_for_interface(
            str(self.settings_service.get().get("language") or "")
        )
        try:
            statuses = query_workshop_subscription_status(
                list(references_by_workshop_id),
                language,
                app_id=WH3_APP_ID,
            )
        except SteamworksBridgeError as exc:
            raise ValueError(f"无法检查官方配置中的 Workshop 订阅状态：{exc}") from exc
        unsubscribed = []
        for item in statuses:
            if item.get("subscribed"):
                continue
            workshop_id = str(item.get("workshop_id") or "")
            reference = references_by_workshop_id.get(workshop_id, {})
            unsubscribed.append(
                {
                    "workshop_id": workshop_id,
                    "title": str(item.get("title") or "").strip(),
                    "pack_name": str(reference.get("pack_name") or "").strip(),
                }
            )
        return {
            "profile": parsed["profile"],
            "references": references,
            "ordered_mod_ids": ordered_ids,
            "missing": missing,
            "unsubscribed": unsubscribed,
            "unrecognized_lines": parsed["unrecognized_lines"],
        }

    def _import_mod_profile(self, profile_path: str, mode: str = "new") -> dict[str, Any]:
        if mode not in {"new", "replace"}:
            raise ValueError("官方配置导入模式无效")
        parsed = parse_mod_profile(profile_path)
        references = parsed["references"]
        ordered_ids, missing = resolve_share_with_pending(references, self._assets)
        if mode == "new":
            existing_names = {
                str(item.get("name") or "").casefold()
                for item in self.state_repository.list_playsets()
            }
            base_name = str(parsed["profile"]["name"] or "官方启动器配置").strip()
            name = base_name
            suffix = 2
            while name.casefold() in existing_names:
                name = f"{base_name} ({suffix})"
                suffix += 1
            self.state_repository.create_playset(name, ordered_ids)
        else:
            self.state_repository.update_current_playset(ordered_ids)
        pending_workshop_ids = list(
            dict.fromkeys(
                str(reference.get("workshop_id") or "")
                for reference in missing
                if str(reference.get("workshop_id") or "").isdigit()
            )
        )
        return {
            **self._current_playset_payload(),
            "profile": parsed["profile"],
            "missing": missing,
            "pending_workshop_ids": pending_workshop_ids,
        }

    @staticmethod
    def _subscribe_workshop_items(workshop_ids: list[str]) -> dict[str, Any]:
        if not isinstance(workshop_ids, list):
            raise ValueError("Workshop ID 列表无效")
        normalized = list(
            dict.fromkeys(str(value).strip() for value in workshop_ids if str(value).strip())
        )
        if not normalized or any(not value.isdigit() for value in normalized):
            raise ValueError("Workshop ID 列表无效")
        if len(normalized) > 200:
            raise ValueError("一次最多自动订阅 200 个 Workshop 项目")
        try:
            return subscribe_workshop_items(normalized, app_id=WH3_APP_ID)
        except SteamworksBridgeError as exc:
            raise ValueError(f"自动订阅 Workshop 项目失败：{exc}") from exc

    def _get_mod_preview(self, mod_id: str) -> dict[str, str]:
        asset = self._require_asset(mod_id)
        if asset.preview_path:
            preview = Path(asset.preview_path)
            if preview.is_file() and preview.stat().st_size <= 8 * 1024 * 1024:
                mime = mimetypes.guess_type(preview.name)[0] or "image/png"
                encoded = base64.b64encode(preview.read_bytes()).decode("ascii")
                return {"url": f"data:{mime};base64,{encoded}"}
        return {"url": asset.preview_url}

    def _get_mod_thumbnails(self, mod_ids: list[str]) -> dict[str, dict[str, str]]:
        if not isinstance(mod_ids, list):
            raise ValueError("mod_ids must be a list")
        if len(mod_ids) > 500:
            raise ValueError("Too many thumbnail requests")
        items: dict[str, str] = {}
        for requested_id in dict.fromkeys(str(item) for item in mod_ids):
            asset = self._require_asset(requested_id)
            items[asset.id] = self._thumbnail_for_asset(asset)
        return {"items": items}

    def _thumbnail_for_asset(self, asset: ModAsset) -> str:
        preview = Path(asset.preview_path) if asset.preview_path else Path()
        signature = f"url:{asset.preview_url}"
        if asset.preview_path and preview.is_file():
            try:
                stat = preview.stat()
                signature = f"file:{preview}:{stat.st_mtime_ns}:{stat.st_size}"
            except OSError:
                pass
        cached = self._thumbnail_cache.get(asset.id)
        if cached and cached[0] == signature:
            return cached[1]

        url = asset.preview_url
        if asset.preview_path and preview.is_file():
            try:
                with Image.open(preview) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    image = ImageOps.fit(
                        image,
                        (72, 72),
                        method=Image.Resampling.LANCZOS,
                        centering=(0.5, 0.5),
                    )
                    output = BytesIO()
                    image.save(output, format="JPEG", quality=78, optimize=True)
                encoded = base64.b64encode(output.getvalue()).decode("ascii")
                url = f"data:image/jpeg;base64,{encoded}"
            except (OSError, ValueError):
                url = asset.preview_url
        self._thumbnail_cache[asset.id] = (signature, url)
        return url

    def _open_mod_folder(self, mod_id: str) -> dict[str, bool]:
        asset = self._require_asset(mod_id)
        self._reveal_file(Path(asset.path))
        return {"opened": True}

    def _open_workshop_folder(self, mod_id: str) -> dict[str, Any]:
        asset = self._require_workshop_asset(mod_id)
        candidates: list[Path] = []
        paths = self.settings_service.resolve_game_paths()
        if paths.workshop_path:
            candidates.append(
                Path(paths.workshop_path) / asset.workshop_id / asset.pack_name
            )
        for alternate_path in asset.alternate_paths:
            pack_path = Path(alternate_path)
            if asset.workshop_id in pack_path.parts:
                candidates.append(pack_path)
        if asset.source == "workshop":
            candidates.append(Path(asset.path))

        seen: set[str] = set()
        for candidate in candidates:
            normalized = str(candidate.resolve(strict=False)).casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            if candidate.is_file():
                self._reveal_file(candidate)
                return {"opened": True, "path": str(candidate.resolve(strict=False))}
        raise ValueError("未找到该 MOD 的 Workshop 本地目录")

    def _open_game_folder(self) -> dict[str, bool]:
        paths = self.settings_service.resolve_game_paths()
        if not paths.game_path:
            raise ValueError("尚未设置游戏目录")
        self._open_path(Path(paths.game_path))
        return {"opened": True}

    def _open_workshop_page(self, mod_id: str) -> dict[str, bool]:
        asset = self._require_asset(mod_id)
        if not asset.workshop_id:
            raise ValueError("该 MOD 不是 Workshop 项目")
        webbrowser.open(
            f"https://steamcommunity.com/sharedfiles/filedetails/?id={asset.workshop_id}"
        )
        return {"opened": True}

    def _open_workshop_client(self, mod_id: str) -> dict[str, bool]:
        asset = self._require_asset(mod_id)
        if not asset.workshop_id:
            raise ValueError("该 MOD 不是 Workshop 项目")
        self._open_uri(f"steam://url/CommunityFilePage/{asset.workshop_id}")
        return {"opened": True}

    @staticmethod
    def _open_external_url(url: str) -> dict[str, Any]:
        normalized = str(url or "").strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("只允许打开有效的 HTTP 或 HTTPS 链接")
        return {"opened": bool(webbrowser.open(normalized)), "url": normalized}

    def _preview_delete_mod_files(self, mod_ids: list[str]) -> dict[str, Any]:
        if self.detect_game_running():
            raise ValueError("游戏运行期间不能删除 MOD 文件")
        if not isinstance(mod_ids, list):
            raise ValueError("MOD ID 列表无效")
        assets = [self._require_asset(mod_id) for mod_id in dict.fromkeys(map(str, mod_ids))]
        preview = build_delete_preview(assets, self.settings_service.resolve_game_paths())
        token = uuid.uuid4().hex
        with self._delete_preview_lock:
            now = time.monotonic()
            self._delete_previews = {
                key: value
                for key, value in self._delete_previews.items()
                if now - value[0] <= 300
            }
            self._delete_previews[token] = (now, preview)
        return {**preview, "token": token}

    def _delete_mod_files(self, preview_token: str) -> dict[str, Any]:
        if self.detect_game_running():
            raise ValueError("游戏运行期间不能删除 MOD 文件")
        token = str(preview_token or "").strip()
        with self._delete_preview_lock:
            stored = self._delete_previews.pop(token, None)
        if not stored or time.monotonic() - stored[0] > 300:
            raise ValueError("删除确认已失效，请重新预览")
        result = execute_delete_preview(
            stored[1],
            self.settings_service.resolve_game_paths(),
        )
        for item in result["deleted"]:
            if item.get("source") == SOURCE_DATA:
                self.state_repository.delete_data_sync_item(str(item.get("pack_name") or ""))
        result["scan"] = self._scan_mods(False)
        return result

    def _unsubscribe_workshop_mod(self, mod_id: str) -> dict[str, Any]:
        return self._unsubscribe_workshop_mods([mod_id])

    def _unsubscribe_workshop_mods(self, mod_ids: list[str]) -> dict[str, Any]:
        if self.detect_game_running():
            raise ValueError("游戏运行期间不能取消订阅或删除工坊文件")
        if not isinstance(mod_ids, list):
            raise ValueError("MOD ID 列表无效")
        assets = [self._require_workshop_asset(mod_id) for mod_id in dict.fromkeys(map(str, mod_ids))]
        by_workshop_id = {
            asset.workshop_id: asset
            for asset in assets
            if asset.workshop_id
        }
        paths = self.settings_service.resolve_game_paths()
        if not paths.workshop_path:
            raise ValueError("Workshop 目录无效")
        completed: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for workshop_id in by_workshop_id:
            try:
                steam_result = self._run_workshop_operation("unsubscribe", workshop_id)
                if not steam_result.get("accepted"):
                    raise ValueError("Steam 未接受取消订阅请求")
                item_directory = workshop_item_directory(paths.workshop_path, workshop_id)
                if item_directory.exists():
                    shutil.rmtree(item_directory)
                completed.append(
                    {
                        "workshop_id": workshop_id,
                        "directory": str(item_directory),
                        "steam": steam_result,
                    }
                )
            except (OSError, ValueError) as exc:
                failures.append({"workshop_id": workshop_id, "error": str(exc)})
        return {
            "completed": completed,
            "failures": failures,
            "completed_count": len(completed),
            "failed_count": len(failures),
            "scan": self._scan_mods(False),
        }

    def _force_update_workshop_mod(self, mod_id: str) -> dict[str, Any]:
        asset = self._require_workshop_asset(mod_id)
        result = self._run_workshop_operation("force_update", asset.workshop_id)
        if not result.get("accepted"):
            raise ValueError("Steam 未接受强制更新请求")
        if not result.get("completed"):
            raise ValueError("Steam Workshop MOD 下载未完成")
        return result

    def _get_workshop_publish_copy(
        self,
        mod_id: str,
        language: str,
    ) -> dict[str, Any]:
        asset = self._require_workshop_asset(mod_id)
        interface_language = str(language or "").strip()
        if interface_language not in SUPPORTED_LANGUAGES:
            raise ValueError("不支持的 Workshop 语言")
        item = self.workshop_service.refresh_localized(
            [asset.workshop_id],
            interface_language,
        ).get(asset.workshop_id)
        if not isinstance(item, dict):
            raise ValueError("未能读取该 Workshop 项目的标题和描述")
        description_language = str(item.get("description_language") or "")
        effective_language = interface_language_for_steam(
            description_language or str(item.get("title_language") or "")
        )
        suggested_language = (
            "en-US"
            if interface_language != "en-US"
            and description_language == ENGLISH_STEAM_LANGUAGE
            else interface_language
        )
        return {
            "workshop_id": asset.workshop_id,
            "language": interface_language,
            "steam_language": steam_language_for_interface(interface_language),
            "effective_language": effective_language,
            "suggested_language": suggested_language,
            "title_language": str(item.get("title_language") or ""),
            "description_language": description_language,
            "title": str(item.get("title") or ""),
            "description": str(item.get("description") or ""),
            "warning": self.workshop_service.last_refresh_warning,
        }

    def _publish_workshop_item(
        self,
        mod_id: str,
        publish_data: dict[str, Any],
    ) -> dict[str, Any]:
        asset = self._require_publishable_asset(mod_id)
        if not isinstance(publish_data, dict):
            raise ValueError("工坊发布参数无效")
        mode = str(publish_data.get("mode") or "").strip()
        if mode not in {"upload", "update"}:
            raise ValueError("工坊发布模式无效")
        if mode == "upload" and asset.workshop_id:
            raise ValueError("该 MOD 已关联 Workshop 项目，请使用更新功能")
        workshop_id = asset.workshop_id if mode == "update" else ""
        if mode == "update" and not workshop_id:
            raise ValueError("该 MOD 尚未关联 Workshop 项目")

        title = str(publish_data.get("title") or "").strip()
        description = str(publish_data.get("description") or "")
        change_note = str(publish_data.get("change_note") or "")
        interface_language = str(publish_data.get("language") or "").strip()
        if interface_language not in SUPPORTED_LANGUAGES:
            raise ValueError("不支持的 Workshop 发布语言")
        steam_language = steam_language_for_interface(interface_language)
        if not title:
            raise ValueError("Workshop 标题不能为空")
        if len(title) > 128:
            raise ValueError("Workshop 标题不能超过 128 个字符")
        if len(description) > 8_000 or len(change_note) > 8_000:
            raise ValueError("Workshop 描述或更新日志过长")

        category = str(publish_data.get("category") or "graphical").strip().casefold()
        allowed_categories = {
            "graphical", "campaign", "units", "battle", "ui",
            "maps", "overhaul", "compilation", "cheat",
        }
        if category not in allowed_categories:
            raise ValueError("Workshop 分类标签无效")
        visibility = int(publish_data.get("visibility", 0))
        if visibility not in {0, 1, 2, 3}:
            raise ValueError("Workshop 可见性无效")

        source_pack = Path(asset.path)
        if not source_pack.is_file() or source_pack.suffix.casefold() != ".pack":
            raise ValueError("待发布的 Pack 文件不存在")
        cover_path = _require_workshop_cover(source_pack)
        upload_root = self.data_dir / "workshop_uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="wmm-", dir=upload_root) as temporary:
                content_path = Path(temporary) / "content"
                content_path.mkdir()
                staged_pack = content_path / asset.pack_name
                staged_cover = content_path / cover_path.name
                _stage_workshop_upload_file(source_pack, staged_pack)
                _stage_workshop_upload_file(cover_path, staged_cover)
                result = publish_workshop_item(
                    content_path=content_path,
                    preview_path=staged_cover,
                    title=title,
                    description=description,
                    change_note=change_note,
                    tags=["mod", category],
                    visibility=visibility,
                    workshop_id=workshop_id,
                    language=steam_language,
                    app_id=WH3_APP_ID,
                )
        except SteamworksBridgeError as exc:
            raise ValueError(str(exc)) from exc

        published_id = str(result.get("workshop_id") or "")
        if not published_id.isdigit():
            raise ValueError("Steam 未返回有效的 Workshop ID")
        self.state_repository.set_published_workshop_id(asset.id, published_id)
        asset.workshop_id = published_id
        asset.workshop_url = (
            "https://steamcommunity.com/sharedfiles/filedetails/"
            f"?id={published_id}"
        )
        asset.creator_id = str(result.get("owner_id") or asset.creator_id)
        asset.author = str(result.get("owner_name") or asset.author)
        return {"result": result, "mod": asset.to_dict()}

    @staticmethod
    def _run_workshop_operation(operation: str, workshop_id: str) -> dict[str, Any]:
        try:
            return perform_workshop_operation(operation, workshop_id, app_id=WH3_APP_ID)
        except SteamworksBridgeError as exc:
            raise ValueError(str(exc)) from exc

    def _open_mod_in_rpfm(self, mod_id: str) -> dict[str, Any]:
        asset = self._require_asset(mod_id)
        pack_path = Path(asset.path)
        if not pack_path.is_file():
            raise ValueError(f"Pack 文件不存在：{pack_path}")
        self._open_path(pack_path)
        return {"opened": True, "path": str(pack_path.resolve(strict=False))}

    def _copy_mod_to_data(self, mod_id: str) -> dict[str, Any]:
        asset = self._require_asset(mod_id)
        source = Path(asset.path)
        if not source.is_file():
            raise ValueError(f"Pack 文件不存在：{source}")
        paths = self.settings_service.resolve_game_paths()
        data_path = Path(paths.data_path) if paths.data_path else Path()
        if not paths.data_path or not data_path.is_dir():
            raise ValueError("Warhammer III Data 目录无效")
        target = data_path / asset.pack_name
        if source.resolve(strict=False) == target.resolve(strict=False):
            return {"copied": False, "already_in_data": True, "target_path": str(target)}
        if target.exists():
            raise ValueError(f"Data 目录中已存在同名 Pack，未覆盖：{target.name}")
        self._atomic_copy(source, target)
        if asset.source == SOURCE_WORKSHOP:
            self._record_data_sync(asset, source, target)
        return {"copied": True, "already_in_data": False, "target_path": str(target)}

    def _sync_workshop_to_data(self) -> dict[str, Any]:
        paths = self.settings_service.resolve_game_paths()
        data_path = Path(paths.data_path) if paths.data_path else Path()
        workshop_root = Path(paths.workshop_path) if paths.workshop_path else Path()
        if not paths.data_path or not data_path.is_dir():
            raise ValueError("Warhammer III Data 目录无效")
        if not paths.workshop_path or not workshop_root.is_dir():
            raise ValueError("Steam Workshop 目录无效")
        if not self._assets:
            raise ValueError("请先扫描 MOD，再同步到 Data")

        candidates: dict[str, list[tuple[ModAsset, Path]]] = {}
        for asset in self._assets.values():
            source = self._workshop_source_path(asset, workshop_root)
            if source is None:
                continue
            candidates.setdefault(asset.pack_name.casefold(), []).append((asset, source))

        counts = {
            "total_workshop_files": sum(len(items) for items in candidates.values()),
            "copied": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped_existing": 0,
            "skipped_modified": 0,
            "skipped_conflict": 0,
        }
        details: list[dict[str, str]] = []
        for items in sorted(candidates.values(), key=lambda group: group[0][0].pack_name.casefold()):
            if len(items) != 1:
                counts["skipped_conflict"] += len(items)
                details.append({"pack_name": items[0][0].pack_name, "status": "conflict"})
                continue
            asset, source = items[0]
            target = data_path / asset.pack_name
            record = self.state_repository.get_data_sync_item(asset.pack_name)
            source_stat = source.stat()
            if target.exists() and record is None:
                counts["skipped_existing"] += 1
                details.append({"pack_name": asset.pack_name, "status": "existing_local"})
                continue
            if target.exists() and record is not None:
                target_stat = target.stat()
                target_matches_record = (
                    int(record.get("target_size") or -1) == target_stat.st_size
                    and int(record.get("target_mtime_ns") or -1) == target_stat.st_mtime_ns
                )
                if not target_matches_record:
                    counts["skipped_modified"] += 1
                    details.append({"pack_name": asset.pack_name, "status": "modified_local"})
                    continue
                source_unchanged = (
                    int(record.get("source_size") or -1) == source_stat.st_size
                    and int(record.get("source_mtime_ns") or -1) == source_stat.st_mtime_ns
                    and os.path.normcase(str(record.get("source_path") or ""))
                    == os.path.normcase(str(source.resolve(strict=False)))
                )
                if source_unchanged:
                    counts["unchanged"] += 1
                    details.append({"pack_name": asset.pack_name, "status": "unchanged"})
                    continue
                action = "updated"
            else:
                action = "copied"

            self._atomic_copy(source, target)
            self._record_data_sync(asset, source, target)
            counts[action] += 1
            details.append({"pack_name": asset.pack_name, "status": action})

        counts["skipped"] = (
            counts["skipped_existing"]
            + counts["skipped_modified"]
            + counts["skipped_conflict"]
        )
        return {**counts, "details": details}

    @staticmethod
    def _atomic_copy(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _workshop_source_path(asset: ModAsset, workshop_root: Path) -> Path | None:
        root = workshop_root.resolve(strict=False)
        for raw_path in (asset.path, *asset.alternate_paths):
            candidate = Path(raw_path)
            if not candidate.is_file():
                continue
            try:
                candidate.resolve(strict=False).relative_to(root)
            except ValueError:
                continue
            return candidate.resolve(strict=False)
        return None

    def _record_data_sync(self, asset: ModAsset, source: Path, target: Path) -> None:
        source_stat = source.stat()
        target_stat = target.stat()
        self.state_repository.save_data_sync_item(
            asset.pack_name,
            asset.workshop_id,
            str(source.resolve(strict=False)),
            source_stat.st_size,
            source_stat.st_mtime_ns,
            str(target.resolve(strict=False)),
            target_stat.st_size,
            target_stat.st_mtime_ns,
        )

    def _require_workshop_asset(self, mod_id: str) -> ModAsset:
        asset = self._require_asset(mod_id)
        if not asset.workshop_id:
            raise ValueError("该 MOD 不是 Workshop 项目")
        return asset

    def _require_publishable_asset(self, mod_id: str) -> ModAsset:
        asset = self._require_asset(mod_id)
        sources = set(asset.sources or [asset.source])
        if SOURCE_DATA not in sources:
            raise ValueError("只能上传 Data 目录中的自有 MOD")
        return asset

    def _require_asset(self, mod_id: str) -> ModAsset:
        canonical_id = self._asset_aliases.get(str(mod_id), str(mod_id))
        asset = self._assets.get(canonical_id)
        if not asset:
            raise ValueError("MOD 不存在或尚未扫描")
        return asset

    def _canonicalize_mod_ids(self, mod_ids: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw_id in mod_ids:
            normalized = str(raw_id)
            if self._is_internal_feature_mod_id(normalized):
                continue
            pending = parse_pending_workshop_mod_id(normalized)
            if pending:
                workshop_id, pack_name = pending
                candidates = sorted(
                    (
                        asset
                        for asset in self._assets.values()
                        if asset.workshop_id == workshop_id
                        and (not pack_name or asset.pack_name.casefold() == pack_name)
                    ),
                    key=lambda asset: (asset.pack_name.casefold(), asset.id),
                )
                canonical_ids = [asset.id for asset in candidates] or [normalized]
            else:
                canonical_ids = [self._asset_aliases.get(normalized, normalized)]
            for canonical in canonical_ids:
                if canonical in seen:
                    continue
                seen.add(canonical)
                result.append(canonical)
        return result

    def _is_internal_feature_mod_id(self, mod_id: str) -> bool:
        normalized = str(mod_id)
        if normalized in self._internal_feature_mod_ids:
            return True
        pending = parse_pending_workshop_mod_id(normalized)
        if pending and pending[0] in INTERNAL_FEATURE_WORKSHOP_IDS:
            return True
        return any(
            normalized.startswith(f"steam:{workshop_id}:")
            for workshop_id in INTERNAL_FEATURE_WORKSHOP_IDS
        )

    def _refresh_missing_dependency_warnings(self, enabled_mod_ids: list[str]) -> None:
        self.scanner.refresh_missing_dependency_warnings(
            self._assets.values(),
            self._canonicalize_mod_ids(enabled_mod_ids),
        )

    def _active_order_path(self, game_path: str) -> Path:
        return current_order_path(
            game_path,
            self.state_repository.get_active_order_filename(),
        )

    @staticmethod
    def _path_health(game_path: str, data_path: str, workshop_path: str) -> dict[str, Any]:
        game = Path(game_path) if game_path else Path()
        data = Path(data_path) if data_path else Path()
        workshop = Path(workshop_path) if workshop_path else Path()
        game_ready = bool(game_path) and (game / "Warhammer3.exe").is_file() and data.is_dir()
        return {
            "game_ready": game_ready,
            "game_path_exists": bool(game_path) and game.is_dir(),
            "executable_exists": bool(game_path) and (game / "Warhammer3.exe").is_file(),
            "data_path_exists": bool(data_path) and data.is_dir(),
            "workshop_path_exists": bool(workshop_path) and workshop.is_dir(),
        }

    @staticmethod
    def _open_path(path: Path) -> None:
        if not path.exists():
            raise ValueError(f"路径不存在：{path}")
        if os.name == "nt":
            os.startfile(str(path))
        elif os.name == "posix":
            command = ["open", str(path)] if os.uname().sysname == "Darwin" else ["xdg-open", str(path)]
            subprocess.Popen(command)
        else:
            raise ValueError("当前系统不支持打开路径")

    @staticmethod
    def _open_uri(uri: str) -> None:
        normalized = str(uri or "").strip()
        parsed = urlparse(normalized)
        if parsed.scheme.casefold() != "steam" or not parsed.netloc:
            raise ValueError("只允许打开有效的 Steam 链接")
        if os.name == "nt":
            os.startfile(normalized)
        elif os.name == "posix":
            command = ["open", normalized] if os.uname().sysname == "Darwin" else ["xdg-open", normalized]
            subprocess.Popen(command)
        else:
            raise ValueError("当前系统不支持打开 Steam 链接")

    @staticmethod
    def _reveal_file(path: Path) -> None:
        if not path.is_file():
            raise ValueError(f"文件不存在：{path}")
        resolved = path.resolve(strict=False)
        if os.name == "nt":
            # Explorer parses /select from the raw command line rather than via
            # the normal argv rules. Keeping the quotes after the comma avoids
            # falling back to the user's Documents folder for paths with spaces.
            subprocess.Popen(f'explorer.exe /select,"{resolved}"')
            return
        API._open_path(resolved.parent)
