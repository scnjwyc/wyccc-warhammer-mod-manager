from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path, PurePosixPath
from typing import Iterable

from .app_settings import DEFAULT_LANGUAGE
from .constants import (
    CORE_VANILLA_PACKS,
    INTERNAL_FEATURE_PACK_NAMES,
    INTERNAL_FEATURE_WORKSHOP_IDS,
    internal_pack_display_name,
    PACK_TYPE_MOD,
    PACK_TYPE_MOVIE,
    PACK_TYPE_UNKNOWN,
    RUNTIME_OPTIONS_MARKER_ENTRY,
    SOURCE_DATA,
    SOURCE_LOCAL,
    SOURCE_WORKSHOP,
)
from .models import GamePaths, ModAsset, ScanResult
from .pack_reader import read_pack_layout, read_pack_index
from .steam_paths import active_steam_account_id, game_last_updated_at, parse_vdf, workshop_steam_root
from .steamworks_bridge import SteamworksBridgeError, get_subscribed_workshop_items
from .workshop import WorkshopMetadataService

_MANIFEST_FILE_RE = re.compile(r"^\s*([^\s]+)")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
logger = logging.getLogger(__name__)
_PACK_TYPE_MASK = 0x0F
_LAUNCHER_RUNTIME_DB_ENTRY_RE = re.compile(
    r"^db\\[^\\]+\\!+wyccc_(?:game_data|unit_data|dynamic_ror_compatibility)_v\d{4}$",
    re.IGNORECASE,
)
_LAUNCHER_RUNTIME_ENTRY_NAMES = frozenset(
    {
        "script\\campaign\\mod\\wyccc_variant_selector_patch.lua",
        "db\\units_custom_battle_permissions_tables\\!!!!wyccc_runtime",
        RUNTIME_OPTIONS_MARKER_ENTRY,
    }
)


def _is_launcher_runtime_pack_entry(name: str) -> bool:
    normalized = str(name).replace("/", "\\").casefold()
    return (
        normalized in _LAUNCHER_RUNTIME_ENTRY_NAMES
        or bool(_LAUNCHER_RUNTIME_DB_ENTRY_RE.fullmatch(normalized))
    )


def _is_launcher_runtime_pack(entry_names: Iterable[str]) -> bool:
    # Logging and intro overrides are shared by ordinary MODs. Only Wyccc's
    # dedicated markers can identify a generated Pack after it is renamed.
    return any(_is_launcher_runtime_pack_entry(name) for name in entry_names)


def _read_subscription_file(subscription_path: Path, app_id: str) -> dict[str, int] | None:
    try:
        manifest = parse_vdf(
            subscription_path.read_text(encoding="utf-8-sig", errors="replace")
        )
    except (OSError, ValueError):
        return None
    subscribed_files = manifest.get("subscribedfiles")
    if not isinstance(subscribed_files, dict):
        return None
    if str(subscribed_files.get("appid") or "") != app_id:
        return None

    subscription_times: dict[str, int] = {}
    for item in subscribed_files.values():
        if not isinstance(item, dict):
            continue
        workshop_id = str(item.get("publishedfileid") or "")
        if not workshop_id.isdigit():
            return None
        try:
            subscribed_at = int(str(item.get("time_subscribed") or "0"))
        except (TypeError, ValueError):
            subscribed_at = 0
        subscription_times[workshop_id] = max(0, subscribed_at) * 1000
    return subscription_times


def _steam_user_data_directories(steam_root: Path) -> list[Path]:
    """Select one account; never fall through to another account's subscription file."""
    userdata_root = steam_root / "userdata"
    active_id = active_steam_account_id(steam_root)
    if active_id:
        return [userdata_root / active_id]
    try:
        login_users = parse_vdf(
            (steam_root / "config" / "loginusers.vdf").read_text(
                encoding="utf-8-sig",
                errors="replace",
            )
        ).get("users")
    except (OSError, ValueError):
        login_users = None
    if isinstance(login_users, dict):
        ranked_users: list[tuple[int, int, int, str]] = []
        for steam_id, details in login_users.items():
            if not str(steam_id).isdigit() or not isinstance(details, dict):
                continue
            try:
                account_id = str(int(str(steam_id)) & 0xFFFFFFFF)
                timestamp = int(str(details.get("Timestamp") or "0"))
            except (TypeError, ValueError):
                continue
            most_recent = str(details.get("MostRecent") or "") == "1"
            auto_login = str(details.get("AutoLogin") or "") == "1"
            ranked_users.append((int(most_recent), int(auto_login), timestamp, account_id))
        if ranked_users:
            return [userdata_root / max(ranked_users)[3]]
    return []


def _steam_subscription_times(paths: GamePaths) -> dict[str, int] | None:
    steam_root = workshop_steam_root(paths)
    if steam_root is None:
        # A manually managed directory outside Steam has no account subscription scope.
        return None
    app_id = paths.game_definition.app_id
    for user_data in _steam_user_data_directories(steam_root):
        subscription_times = _read_subscription_file(
            user_data / "ugc" / f"{app_id}_subscriptions.vdf", app_id,
        )
        if subscription_times is not None:
            return subscription_times
    return {workshop_id: 0 for workshop_id in get_subscribed_workshop_items(app_id=int(app_id))}


def read_pack_type(path: Path) -> str:
    layout = read_pack_layout(path)
    if layout is None:
        return PACK_TYPE_UNKNOWN
    pack_type = layout.type_and_flags & _PACK_TYPE_MASK
    return PACK_TYPE_MOVIE if pack_type == 4 else PACK_TYPE_MOD


def read_pack_dependencies(path: Path) -> list[str]:
    """Read the NUL-separated dependency block from a PFH2-PFH6 Pack header."""
    layout = read_pack_layout(path)
    if layout is None or layout.dependency_size <= 0:
        return []
    try:
        with path.open("rb") as stream:
            stream.seek(layout.header_size)
            dependency_block = stream.read(layout.dependency_size)
            if len(dependency_block) != layout.dependency_size:
                return []
    except OSError:
        return []

    dependencies: list[str] = []
    seen: set[str] = set()
    for value in dependency_block.split(b"\0"):
        dependency = value.decode("utf-8", errors="replace").strip()
        if not dependency:
            continue
        pack_name = Path(dependency.replace("\\", "/")).name
        key = pack_name.casefold()
        if not pack_name or key in seen:
            continue
        seen.add(key)
        dependencies.append(pack_name)
    return dependencies


def read_pack_entry_names(path: Path) -> list[str]:
    """Read PFH2-PFH6 entry names without loading or decompressing payloads."""
    try:
        return [entry.name for entry in read_pack_index(path)]
    except (OSError, ValueError):
        return []


def read_unit_data_tables(path: Path) -> list[str]:
    """Return unit DB table families present in a Pack."""
    return _unit_data_tables_from_entries(read_pack_entry_names(path))


def _unit_data_tables_from_entries(entries: list[str]) -> list[str]:
    tables = {
        table_name
        for entry_name in entries
        for table_name in ("main_units_tables", "land_units_tables")
        if entry_name.replace("/", "\\").casefold().startswith(
            f"db\\{table_name}\\"
        )
    }
    return sorted(tables)


def _path_fingerprint(path: Path) -> str:
    canonical = str(path.resolve(strict=False)).replace("\\", "/").casefold()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:18]


def _asset_id(source: str, path: Path, workshop_id: str = "") -> str:
    if workshop_id:
        return f"steam:{workshop_id}:{path.name.casefold()}"
    return f"local:{source}:{_path_fingerprint(path)}"


def _preview_index(files: Iterable[Path]) -> tuple[dict[str, str], str]:
    images = sorted(
        (item for item in files if item.suffix.casefold() in _IMAGE_SUFFIXES),
        key=lambda item: (_IMAGE_SUFFIXES.index(item.suffix.casefold()), item.name.casefold()),
    )
    by_stem: dict[str, str] = {}
    fallback = ""
    for item in images:
        path = str(item.resolve(strict=False))
        by_stem.setdefault(item.stem.casefold(), path)
        fallback = fallback or path
    return by_stem, fallback


def _find_preview(
    directory: Path, pack_name: str, workshop: bool,
    index: tuple[dict[str, str], str] | None = None,
) -> str:
    if index is None:
        try:
            index = _preview_index(item for item in directory.iterdir() if item.is_file())
        except OSError:
            return ""
    by_stem, fallback = index
    return by_stem.get(Path(pack_name).stem.casefold(), fallback if workshop else "")


def _valid_feral_manifest_entry(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    filename = str(item.get("filename") or "").strip().replace("\\", "/")
    relative = PurePosixPath(filename)
    checksum = item.get("checksum")
    return (
        bool(filename)
        and not relative.is_absolute()
        and bool(relative.parts)
        and relative.parts[0].casefold() == "data"
        and all(part not in {"", ".", ".."} for part in relative.parts)
        and isinstance(checksum, int)
        and not isinstance(checksum, bool)
        and 0 <= checksum <= 0xFFFFFFFF
    )


class ModScanner:
    def __init__(self, workshop_metadata: WorkshopMetadataService):
        self.workshop_metadata = workshop_metadata

    def scan(
        self,
        paths: GamePaths,
        settings: dict,
        refresh_workshop: bool = False,
    ) -> ScanResult:
        result = ScanResult()
        assets: dict[str, ModAsset] = {}
        data_path = Path(paths.data_path) if paths.data_path else Path()
        directory_mods = paths.game_definition.mod_format == "feral_directory"

        vanilla = (
            set()
            if directory_mods
            else self._read_vanilla_manifest(data_path, result.warnings)
        )
        if paths.data_path and not directory_mods:
            self._scan_pack_directory(
                data_path,
                SOURCE_DATA,
                assets,
                result,
                excluded_names={
                    name
                    for name in vanilla
                    if name.casefold() not in INTERNAL_FEATURE_PACK_NAMES
                },
            )
        workshop_ids: list[str] = []
        workshop_root: Path | None = None
        subscription_times: dict[str, int] | None = None
        if paths.workshop_path:
            workshop_root = Path(paths.workshop_path)
            if workshop_root.is_dir():
                try:
                    subscription_times = _steam_subscription_times(paths)
                except SteamworksBridgeError as exc:
                    logger.warning("Current Steam Workshop subscriptions are unavailable: %s", exc)
                    subscription_times = {}
                    result.warnings.append({
                        "code": "workshop_subscriptions_unavailable",
                        "severity": "warning",
                        "message": "无法读取当前 Steam 账号的订阅清单，已跳过工坊 MOD；请启动 Steam 后刷新",
                    })
                result.scanned_roots.append(str(workshop_root))
                for child in sorted(workshop_root.iterdir(), key=lambda item: item.name.casefold()):
                    if not child.is_dir() or not child.name.isdigit():
                        continue
                    if subscription_times is not None and child.name not in subscription_times:
                        continue
                    workshop_ids.append(child.name)
                    if directory_mods:
                        self._scan_feral_directory_mod(
                            child,
                            SOURCE_WORKSHOP,
                            assets,
                            result,
                            workshop_id=child.name,
                        )
                    else:
                        self._scan_workshop_item(child, child.name, assets, result)
            elif str(workshop_root):
                result.warnings.append(f"Workshop 目录不存在：{workshop_root}")

        if directory_mods:
            self._scan_feral_local_mods(assets, result)

        interface_language = str(settings.get("language") or DEFAULT_LANGUAGE)
        metadata: dict[str, dict] = {}
        if workshop_ids:
            app_id = int(paths.game_definition.app_id)
            metadata = self.workshop_metadata.get_many(
                workshop_ids,
                interface_language,
                app_id=app_id,
            )
            if refresh_workshop:
                try:
                    metadata.update(
                        self.workshop_metadata.refresh(
                            workshop_ids,
                            interface_language,
                            app_id=app_id,
                        )
                    )
                    refresh_warning = str(
                        getattr(self.workshop_metadata, "last_refresh_warning", "") or ""
                    )
                    if refresh_warning:
                        result.warnings.append(
                            {
                                "code": "workshop_dependency_refresh",
                                "severity": "warning",
                                "message": refresh_warning,
                                "ignorable": True,
                            }
                        )
                except Exception as exc:
                    result.warnings.append(f"工坊在线信息刷新失败：{exc}")

        for asset in assets.values():
            if asset.workshop_id:
                asset.subscribed_at = (subscription_times or {}).get(asset.workshop_id, 0)
                workshop_data = metadata.get(asset.workshop_id, {})
                asset.display_name = str(workshop_data.get("title") or asset.display_name)
                asset.description = str(workshop_data.get("description") or "")
                asset.author = str(workshop_data.get("author") or asset.author)
                asset.creator_id = str(workshop_data.get("creator_id") or "")
                asset.preview_url = str(workshop_data.get("preview_url") or "")
                raw_required_items = workshop_data.get("required_workshop_items") or []
                asset.required_workshop_items = [
                    {
                        "workshop_id": str(item.get("workshop_id") or ""),
                        "title": str(item.get("title") or ""),
                    }
                    for item in raw_required_items
                    if isinstance(item, dict) and str(item.get("workshop_id") or "").isdigit()
                ]
                remote_created = int(workshop_data.get("created_at") or 0)
                if remote_created:
                    asset.created_at = remote_created
                remote_updated = int(workshop_data.get("updated_at") or 0)
                if remote_updated:
                    asset.workshop_updated_at = remote_updated
                    asset.updated_at = remote_updated
            if not directory_mods and asset.pack_type == PACK_TYPE_UNKNOWN:
                result.warnings.append(f"无法识别 PFH5 Pack 头：{asset.path}")

        self._merge_data_workshop_duplicates(assets)
        if not directory_mods:
            self._mark_missing_dependencies(assets, vanilla)

        for asset in assets.values():
            if (
                asset.workshop_updated_at > 0
                and asset.file_updated_at > 0
                and asset.file_updated_at < asset.workshop_updated_at
            ):
                asset.warnings.append(
                    {
                        "code": "workshop_update_available",
                        "severity": "warning",
                        "message": "Steam 创意工坊信息显示该 MOD 有新更新，请在工坊中确认并更新",
                        "file_updated_at": asset.file_updated_at,
                        "workshop_updated_at": asset.workshop_updated_at,
                    }
                )

        if settings.get("check_outdated_mods"):
            result.game_updated_at = game_last_updated_at(paths)
            if result.game_updated_at <= 0:
                result.warnings.append("无法确定游戏本体最后更新时间，已跳过过期 MOD 检查")
            else:
                for asset in assets.values():
                    if 0 < asset.updated_at < result.game_updated_at:
                        asset.warnings.append(
                            {
                                "code": "outdated_mod",
                                "severity": "warning",
                                "message": "该 MOD 在游戏本体更新后尚未更新，不代表该 MOD 无法使用",
                                "game_updated_at": result.game_updated_at,
                                "mod_updated_at": asset.updated_at,
                            }
                        )

        self._apply_internal_pack_metadata(assets, interface_language)
        result.mods = sorted(
            assets.values(),
            key=lambda mod: (mod.pack_name.casefold(), mod.pack_name, mod.id),
        )
        return result

    @staticmethod
    def _is_metadata_stale(item: dict | None) -> bool:
        if not item:
            return True
        if "created_at" not in item:
            return True
        fetched_at = int(item.get("fetched_at") or 0)
        return fetched_at <= 0 or int(time.time() * 1000) - fetched_at > 24 * 60 * 60 * 1000

    @staticmethod
    def _merge_data_workshop_duplicates(assets: dict[str, ModAsset]) -> None:
        """Merge only an unambiguous one-to-one Data/Workshop pair."""
        by_pack_name: dict[str, list[ModAsset]] = {}
        for asset in assets.values():
            by_pack_name.setdefault(asset.pack_name.casefold(), []).append(asset)

        for matches in by_pack_name.values():
            data_assets = sorted(
                (asset for asset in matches if asset.source == SOURCE_DATA),
                key=lambda asset: asset.id,
            )
            workshop_assets = sorted(
                (asset for asset in matches if asset.source == SOURCE_WORKSHOP),
                key=lambda asset: (asset.workshop_id, asset.id),
            )
            if len(workshop_assets) > 1 or len(data_assets) > 1:
                for asset in matches:
                    asset.warnings.append({
                        "code": "duplicate_pack_name",
                        "severity": "warning",
                        "message": "存在多个同名 Pack，已保留为独立项目；请只启用一个来源",
                    })
                continue
            if not data_assets or not workshop_assets:
                continue

            primary = data_assets[0]
            workshop = workshop_assets[0]
            primary.sources = [SOURCE_DATA, SOURCE_WORKSHOP]
            primary.cross_source_duplicate = True
            primary.alternate_ids = list(
                dict.fromkeys(
                    [
                        *primary.alternate_ids,
                        *(asset.id for asset in workshop_assets),
                        *(alias for asset in workshop_assets for alias in asset.alternate_ids),
                    ]
                )
            )
            primary.alternate_paths = list(
                dict.fromkeys(
                    [
                        *primary.alternate_paths,
                        *(asset.path for asset in workshop_assets),
                        *(path for asset in workshop_assets for path in asset.alternate_paths),
                    ]
                )
            )
            primary.workshop_id = workshop.workshop_id
            primary.workshop_url = workshop.workshop_url
            primary.creator_id = workshop.creator_id
            primary.author = workshop.author
            primary.description = workshop.description
            primary.preview_url = workshop.preview_url
            primary.preview_path = primary.preview_path or workshop.preview_path
            primary.display_name = workshop.display_name or primary.display_name
            primary.created_at = workshop.created_at or primary.created_at
            primary.updated_at = max(primary.updated_at, workshop.updated_at)
            primary.workshop_updated_at = max(
                primary.workshop_updated_at,
                workshop.workshop_updated_at,
            )
            primary.subscribed_at = workshop.subscribed_at or primary.subscribed_at
            primary.dependency_packs = list(
                dict.fromkeys([*primary.dependency_packs, *workshop.dependency_packs])
            )
            primary.required_workshop_items = [
                *{
                    str(item.get("workshop_id") or ""): item
                    for item in [
                        *primary.required_workshop_items,
                        *workshop.required_workshop_items,
                    ]
                    if str(item.get("workshop_id") or "")
                }.values()
            ]

            for duplicate in workshop_assets:
                assets.pop(duplicate.id, None)

    @staticmethod
    def _mark_missing_dependencies(
        assets: dict[str, ModAsset],
        vanilla_pack_names: set[str],
    ) -> None:
        installed_pack_names = {asset.pack_name.casefold() for asset in assets.values()}
        installed_workshop_ids = {
            asset.workshop_id for asset in assets.values() if asset.workshop_id
        }
        available_pack_names = installed_pack_names | {
            name.casefold() for name in vanilla_pack_names
        }

        for asset in assets.values():
            missing: list[dict[str, str]] = []
            for dependency in asset.dependency_packs:
                dependency_name = Path(dependency.replace("\\", "/")).name
                if (
                    dependency_name.casefold() == asset.pack_name.casefold()
                    or dependency_name.casefold() in available_pack_names
                ):
                    continue
                missing.append(
                    {
                        "kind": "pack",
                        "id": dependency_name,
                        "name": dependency_name,
                    }
                )

            for required in asset.required_workshop_items:
                workshop_id = str(required.get("workshop_id") or "")
                if not workshop_id or workshop_id == asset.workshop_id:
                    continue
                if workshop_id in installed_workshop_ids:
                    continue
                title = str(required.get("title") or "").strip()
                missing.append(
                    {
                        "kind": "workshop",
                        "id": workshop_id,
                        "name": title or f"Workshop #{workshop_id}",
                    }
                )

            unique_missing = {
                (item["kind"], item["id"]): item
                for item in missing
            }
            asset.missing_dependencies = list(unique_missing.values())

    @staticmethod
    def refresh_missing_dependency_warnings(
        assets: Iterable[ModAsset],
        enabled_mod_ids: Iterable[str],
    ) -> None:
        scanned_assets = list(assets)
        enabled = {str(mod_id) for mod_id in enabled_mod_ids}
        installed_pack_names = {asset.pack_name.casefold() for asset in scanned_assets}
        enabled_pack_names = {
            asset.pack_name.casefold()
            for asset in scanned_assets
            if asset.id in enabled
        }
        installed_workshop_ids = {
            asset.workshop_id for asset in scanned_assets if asset.workshop_id
        }
        enabled_workshop_ids = {
            asset.workshop_id
            for asset in scanned_assets
            if asset.id in enabled and asset.workshop_id
        }

        for asset in scanned_assets:
            asset.warnings = [
                warning
                for warning in asset.warnings
                if str(warning.get("code") or "") != "missing_dependency"
            ]
            dependencies = list(asset.missing_dependencies)
            recorded_dependencies = {
                (str(item.get("kind") or ""), str(item.get("id") or ""))
                for item in dependencies
            }

            for dependency in asset.dependency_packs:
                dependency_name = Path(dependency.replace("\\", "/")).name
                dependency_key = dependency_name.casefold()
                if (
                    not dependency_name
                    or dependency_key == asset.pack_name.casefold()
                    or dependency_key not in installed_pack_names
                    or dependency_key in enabled_pack_names
                    or ("pack", dependency_name) in recorded_dependencies
                ):
                    continue
                dependencies.append(
                    {
                        "kind": "pack",
                        "id": dependency_name,
                        "name": dependency_name,
                        "availability": "disabled",
                    }
                )
                recorded_dependencies.add(("pack", dependency_name))

            for required in asset.required_workshop_items:
                workshop_id = str(required.get("workshop_id") or "")
                if (
                    not workshop_id
                    or workshop_id == asset.workshop_id
                    or workshop_id not in installed_workshop_ids
                    or workshop_id in enabled_workshop_ids
                    or ("workshop", workshop_id) in recorded_dependencies
                ):
                    continue
                dependencies.append(
                    {
                        "kind": "workshop",
                        "id": workshop_id,
                        "name": str(required.get("title") or "").strip()
                        or f"Workshop #{workshop_id}",
                        "availability": "disabled",
                    }
                )
                recorded_dependencies.add(("workshop", workshop_id))

            if asset.id not in enabled or not dependencies:
                continue
            dependency_names = "、".join(
                item["name"] for item in dependencies
            )
            asset.warnings.append(
                {
                    "code": "missing_dependency",
                    "severity": "error",
                    "message": f"缺少依赖：{dependency_names}",
                    "dependencies": dependencies,
                }
            )

    @staticmethod
    def _read_vanilla_manifest(data_path: Path, warnings: list[str]) -> set[str]:
        vanilla = set(CORE_VANILLA_PACKS)
        manifest_path = data_path / "manifest.txt"
        if not manifest_path.is_file():
            if str(data_path):
                warnings.append("未找到 data/manifest.txt，原版 Pack 排除使用最小内置清单")
            return vanilla
        try:
            for line in manifest_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                match = _MANIFEST_FILE_RE.match(line)
                if match:
                    name = Path(match.group(1).replace("\\", "/")).name.casefold()
                    if name.endswith(".pack"):
                        vanilla.add(name)
        except OSError as exc:
            warnings.append(f"读取 manifest.txt 失败：{exc}")
        return vanilla

    def _scan_pack_directory(
        self,
        directory: Path,
        source: str,
        assets: dict[str, ModAsset],
        result: ScanResult,
        excluded_names: Iterable[str] = (),
    ) -> None:
        excluded = {name.casefold() for name in excluded_names}
        if not directory.is_dir():
            return
        result.scanned_roots.append(str(directory.resolve(strict=False)))
        try:
            files = [item for item in directory.iterdir() if item.is_file()]
            previews = _preview_index(files)
            pack_paths = sorted(
                (
                    item
                    for item in files
                    if item.suffix.casefold() == ".pack"
                    and item.name.casefold() not in excluded
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError as exc:
            result.warnings.append(f"无法扫描目录 {directory}：{exc}")
            return
        for pack_path in pack_paths:
            asset = self._make_asset(pack_path, source, preview_index=previews)
            assets[asset.id] = asset

    def _scan_workshop_item(
        self,
        directory: Path,
        workshop_id: str,
        assets: dict[str, ModAsset],
        result: ScanResult,
    ) -> None:
        try:
            files = [item for item in directory.iterdir() if item.is_file()]
            previews = _preview_index(files)
            pack_paths = sorted(
                (
                    item
                    for item in files
                    if item.suffix.casefold() == ".pack"
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError as exc:
            result.warnings.append(f"无法扫描工坊项目 {workshop_id}：{exc}")
            return
        if not pack_paths:
            return
        for pack_path in pack_paths:
            asset = self._make_asset(pack_path, SOURCE_WORKSHOP, workshop_id, preview_index=previews)
            assets[asset.id] = asset

    @staticmethod
    def _apply_internal_pack_metadata(
        assets: dict[str, ModAsset],
        language: str,
    ) -> None:
        for asset in assets.values():
            pack_key = asset.pack_name.casefold()
            if (
                pack_key in INTERNAL_FEATURE_PACK_NAMES
                or asset.workshop_id in INTERNAL_FEATURE_WORKSHOP_IDS
                or asset.is_launcher_runtime_pack
            ):
                asset.hidden = True
            alias = internal_pack_display_name(asset.pack_name, language)
            if alias:
                asset.display_name = alias

    def _scan_feral_local_mods(
        self,
        assets: dict[str, ModAsset],
        result: ScanResult,
    ) -> None:
        local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if not local_app_data:
            return
        mods_root = (
            Path(local_app_data)
            / "Feral Interactive"
            / "Total War ROME REMASTERED"
            / "Mods"
        )
        for folder_name in ("Local Mods", "My Mods"):
            root = mods_root / folder_name
            if not root.is_dir():
                continue
            result.scanned_roots.append(str(root.resolve(strict=False)))
            try:
                children = sorted(root.iterdir(), key=lambda item: item.name.casefold())
            except OSError as exc:
                result.warnings.append(f"无法扫描 Rome Remastered 本地 MOD 目录 {root}：{exc}")
                continue
            for child in children:
                if child.is_dir():
                    self._scan_feral_directory_mod(child, SOURCE_LOCAL, assets, result)

    @staticmethod
    def _scan_feral_directory_mod(
        directory: Path,
        source: str,
        assets: dict[str, ModAsset],
        result: ScanResult,
        workshop_id: str = "",
    ) -> None:
        modinfo_path = directory / "modinfo.json"
        filelist_path = directory / "filelist.json"
        data_path = directory / "data"
        try:
            modinfo = json.loads(modinfo_path.read_text(encoding="utf-8-sig"))
            filelist = json.loads(filelist_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            result.warnings.append(
                f"已跳过无效的 Rome Remastered MOD {directory.name}：{exc}"
            )
            return
        valid_manifest = isinstance(filelist, list) and all(
            _valid_feral_manifest_entry(item) for item in filelist
        )
        if not isinstance(modinfo, dict) or not valid_manifest or not data_path.is_dir():
            result.warnings.append(
                f"已跳过无效的 Rome Remastered MOD {directory.name}：缺少有效的 modinfo.json、filelist.json 或 data 目录"
            )
            return

        preview_path = ""
        preview_name = str(modinfo.get("Preview Image") or "").strip()
        if preview_name:
            candidate = (directory / preview_name).resolve(strict=False)
            try:
                candidate.relative_to(directory.resolve(strict=False))
            except ValueError:
                candidate = Path()
            if candidate.is_file() and candidate.suffix.casefold() in _IMAGE_SUFFIXES:
                preview_path = str(candidate)
        if not preview_path:
            preview_path = _find_preview(directory, directory.name, bool(workshop_id))

        try:
            stat = directory.stat()
            updated_at = int(max(modinfo_path.stat().st_mtime, filelist_path.stat().st_mtime) * 1000)
            created_at = int(stat.st_ctime * 1000)
        except OSError:
            updated_at = 0
            created_at = 0
        asset = ModAsset(
            id=_asset_id(source, directory, workshop_id),
            pack_name=directory.name,
            display_name=str(modinfo.get("Mod Name") or directory.name).strip() or directory.name,
            path=str(directory.resolve(strict=False)),
            directory=str(directory.parent.resolve(strict=False)),
            source=source,
            workshop_id=workshop_id,
            description=str(modinfo.get("Description") or ""),
            preview_path=preview_path,
            workshop_url=(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
                if workshop_id
                else ""
            ),
            pack_type=PACK_TYPE_MOD,
            updated_at=updated_at,
            file_updated_at=updated_at,
            created_at=created_at,
            is_symlink=directory.is_symlink(),
            sources=[source],
        )
        assets[asset.id] = asset

    @staticmethod
    def _make_asset(
        pack_path: Path, source: str, workshop_id: str = "",
        *, preview_index: tuple[dict[str, str], str] | None = None,
    ) -> ModAsset:
        entry_names = read_pack_entry_names(pack_path)
        try:
            stat = pack_path.lstat()
            updated_at = int(stat.st_mtime * 1000)
            created_at = int(stat.st_ctime * 1000)
            is_symlink = pack_path.is_symlink()
        except OSError:
            updated_at = 0
            created_at = 0
            is_symlink = False
        directory = pack_path.parent
        return ModAsset(
            id=_asset_id(source, pack_path, workshop_id),
            pack_name=pack_path.name,
            display_name=pack_path.stem,
            path=str(pack_path.resolve(strict=False)),
            directory=str(directory.resolve(strict=False)),
            source=source,
            workshop_id=workshop_id,
            preview_path=_find_preview(directory, pack_path.name, source == SOURCE_WORKSHOP, preview_index),
            workshop_url=(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
                if workshop_id
                else ""
            ),
            pack_type=read_pack_type(pack_path),
            unit_data_tables=_unit_data_tables_from_entries(entry_names),
            provides_variant_selector=any(
                name.replace("/", "\\").casefold()
                == "script\\campaign\\mod\\marthvariantselector.lua"
                for name in entry_names
            ),
            is_launcher_runtime_pack=_is_launcher_runtime_pack(entry_names),
            updated_at=updated_at,
            file_updated_at=updated_at,
            created_at=created_at,
            is_symlink=is_symlink,
            sources=[source],
            dependency_packs=read_pack_dependencies(pack_path),
        )
