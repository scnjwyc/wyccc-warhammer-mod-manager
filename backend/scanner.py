from __future__ import annotations

import hashlib
import re
import struct
import time
from pathlib import Path
from typing import Iterable

from .app_settings import DEFAULT_LANGUAGE
from .constants import (
    CORE_VANILLA_PACKS,
    INTERNAL_FEATURE_PACK_NAMES,
    INTERNAL_FEATURE_WORKSHOP_IDS,
    PACK_TYPE_MOD,
    PACK_TYPE_MOVIE,
    PACK_TYPE_UNKNOWN,
    SOURCE_DATA,
    SOURCE_WORKSHOP,
    WH3_PACK_MAGIC,
)
from .models import GamePaths, ModAsset, ScanResult
from .steam_paths import candidate_steam_roots, game_last_updated_at
from .workshop import WorkshopMetadataService

_MANIFEST_FILE_RE = re.compile(r"^\s*([^\s]+)")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
_STEAM_KEYVALUES_TOKEN_RE = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')


def _parse_steam_keyvalues(text: str) -> dict[str, object]:
    """Parse the quoted-key subset used by Steam's appworkshop manifests."""
    tokens = [
        match.group(1).replace(r'\\"', '"').replace(r'\\\\', '\\')
        if match.group(1) is not None
        else match.group(2)
        for match in _STEAM_KEYVALUES_TOKEN_RE.finditer(text)
    ]

    def parse_object(index: int) -> tuple[dict[str, object], int]:
        values: dict[str, object] = {}
        while index < len(tokens):
            token = tokens[index]
            if token == "}":
                return values, index + 1
            if token == "{":
                index += 1
                continue
            key = token
            index += 1
            if index >= len(tokens):
                break
            if tokens[index] == "{":
                child, index = parse_object(index + 1)
                values[key] = child
            else:
                values[key] = tokens[index]
                index += 1
        return values, index

    return parse_object(0)[0]


def _read_subscription_file(subscription_path: Path, app_id: str) -> dict[str, int]:
    try:
        manifest = _parse_steam_keyvalues(
            subscription_path.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        return {}
    subscribed_files = manifest.get("subscribedfiles")
    if not isinstance(subscribed_files, dict):
        return {}
    if str(subscribed_files.get("appid") or "") != app_id:
        return {}

    subscription_times: dict[str, int] = {}
    for item in subscribed_files.values():
        if not isinstance(item, dict):
            continue
        try:
            workshop_id = str(item.get("publishedfileid") or "")
            subscribed_at = int(str(item.get("time_subscribed") or "0"))
        except (TypeError, ValueError):
            continue
        if workshop_id.isdigit() and subscribed_at > 0:
            subscription_times[workshop_id] = subscribed_at * 1000
    return subscription_times


def _steam_user_data_directories(steam_root: Path) -> list[Path]:
    userdata_root = steam_root / "userdata"
    try:
        directories = [path for path in userdata_root.iterdir() if path.is_dir() and path.name.isdigit()]
    except OSError:
        return []
    by_name = {directory.name: directory for directory in directories}

    active_ids: list[str] = []
    try:
        login_users = _parse_steam_keyvalues(
            (steam_root / "config" / "loginusers.vdf").read_text(
                encoding="utf-8",
                errors="replace",
            )
        ).get("users")
    except OSError:
        login_users = None
    if isinstance(login_users, dict):
        ranked_users: list[tuple[int, int, str]] = []
        for steam_id, details in login_users.items():
            if not str(steam_id).isdigit() or not isinstance(details, dict):
                continue
            try:
                account_id = str(int(str(steam_id)) & 0xFFFFFFFF)
                timestamp = int(str(details.get("Timestamp") or "0"))
            except (TypeError, ValueError):
                continue
            is_active = str(details.get("AutoLogin") or details.get("MostRecent") or "") == "1"
            ranked_users.append((int(is_active), timestamp, account_id))
        active_ids = [account_id for _, _, account_id in sorted(ranked_users, reverse=True)]

    ordered: list[Path] = []
    for account_id in active_ids:
        directory = by_name.pop(account_id, None)
        if directory is not None:
            ordered.append(directory)
    return ordered + sorted(by_name.values(), key=lambda path: path.name)


def _steam_subscription_times(paths: GamePaths) -> dict[str, int]:
    roots: list[Path] = []
    if paths.steam_root:
        roots.append(Path(paths.steam_root))
    roots.extend(candidate_steam_roots())

    seen_roots: set[str] = set()
    app_id = paths.game_definition.app_id
    for steam_root in roots:
        root_key = str(steam_root.resolve(strict=False)).casefold()
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        for user_data in _steam_user_data_directories(steam_root):
            subscription_times = _read_subscription_file(
                user_data / "ugc" / f"{app_id}_subscriptions.vdf",
                app_id,
            )
            if subscription_times:
                return subscription_times
    return {}


def read_pack_type(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            header = stream.read(8)
    except OSError:
        return PACK_TYPE_UNKNOWN
    if len(header) < 8 or header[:4] != WH3_PACK_MAGIC:
        return PACK_TYPE_UNKNOWN
    byte_mask = struct.unpack("<I", header[4:8])[0]
    return PACK_TYPE_MOVIE if byte_mask == 4 else PACK_TYPE_MOD


def read_pack_dependencies(path: Path) -> list[str]:
    """Read the NUL-separated dependency block from a PFH5 pack header."""
    try:
        with path.open("rb") as stream:
            header = stream.read(28)
            if len(header) < 28 or header[:4] != WH3_PACK_MAGIC:
                return []
            dependency_size = struct.unpack_from("<I", header, 12)[0]
            if dependency_size <= 0:
                return []
            remaining = max(0, path.stat().st_size - 28)
            if dependency_size > remaining or dependency_size > 16 * 1024 * 1024:
                return []
            dependency_block = stream.read(dependency_size)
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


def _path_fingerprint(path: Path) -> str:
    canonical = str(path.resolve(strict=False)).replace("\\", "/").casefold()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:18]


def _asset_id(source: str, path: Path, workshop_id: str = "") -> str:
    if workshop_id:
        return f"steam:{workshop_id}:{path.name.casefold()}"
    return f"local:{source}:{_path_fingerprint(path)}"


def _find_preview(directory: Path, pack_name: str, workshop: bool) -> str:
    stem = Path(pack_name).stem.casefold()
    try:
        files = [item for item in directory.iterdir() if item.is_file()]
    except OSError:
        return ""
    for item in files:
        if item.suffix.casefold() in _IMAGE_SUFFIXES and item.stem.casefold() == stem:
            return str(item.resolve(strict=False))
    if workshop:
        for item in files:
            if item.suffix.casefold() in _IMAGE_SUFFIXES:
                return str(item.resolve(strict=False))
    return ""


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

        vanilla = self._read_vanilla_manifest(data_path, result.warnings)
        if paths.data_path:
            self._scan_pack_directory(
                data_path,
                SOURCE_DATA,
                assets,
                result,
                excluded_names=vanilla,
            )
        workshop_ids: list[str] = []
        workshop_root: Path | None = None
        if paths.workshop_path:
            workshop_root = Path(paths.workshop_path)
            if workshop_root.is_dir():
                result.scanned_roots.append(str(workshop_root))
                for child in sorted(workshop_root.iterdir(), key=lambda item: item.name.casefold()):
                    if not child.is_dir() or not child.name.isdigit():
                        continue
                    if child.name in INTERNAL_FEATURE_WORKSHOP_IDS:
                        continue
                    workshop_ids.append(child.name)
                    self._scan_workshop_item(child, child.name, assets, result)
            elif str(workshop_root):
                result.warnings.append(f"Workshop 目录不存在：{workshop_root}")

        subscription_times = _steam_subscription_times(paths)

        metadata: dict[str, dict] = {}
        if workshop_ids:
            interface_language = str(settings.get("language") or DEFAULT_LANGUAGE)
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
                asset.subscribed_at = subscription_times.get(asset.workshop_id, 0)
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
                    asset.updated_at = remote_updated
            if asset.pack_type == PACK_TYPE_UNKNOWN:
                result.warnings.append(f"无法识别 PFH5 Pack 头：{asset.path}")

        self._merge_data_workshop_duplicates(assets)
        self._mark_missing_dependencies(assets, vanilla)

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
        """Collapse an exact Data/Workshop pack-name collision into the Data asset."""
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
        excluded = {
            *(name.casefold() for name in excluded_names),
            *INTERNAL_FEATURE_PACK_NAMES,
        }
        if not directory.is_dir():
            return
        result.scanned_roots.append(str(directory.resolve(strict=False)))
        try:
            pack_paths = sorted(
                (
                    item
                    for item in directory.iterdir()
                    if item.is_file()
                    and item.suffix.casefold() == ".pack"
                    and item.name.casefold() not in excluded
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError as exc:
            result.warnings.append(f"无法扫描目录 {directory}：{exc}")
            return
        for pack_path in pack_paths:
            asset = self._make_asset(pack_path, source)
            assets[asset.id] = asset

    def _scan_workshop_item(
        self,
        directory: Path,
        workshop_id: str,
        assets: dict[str, ModAsset],
        result: ScanResult,
    ) -> None:
        try:
            pack_paths = sorted(
                (
                    item
                    for item in directory.iterdir()
                    if item.is_file() and item.suffix.casefold() == ".pack"
                    and item.name.casefold() not in INTERNAL_FEATURE_PACK_NAMES
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError as exc:
            result.warnings.append(f"无法扫描工坊项目 {workshop_id}：{exc}")
            return
        if not pack_paths:
            return
        for pack_path in pack_paths:
            asset = self._make_asset(pack_path, SOURCE_WORKSHOP, workshop_id)
            assets[asset.id] = asset

    @staticmethod
    def _make_asset(pack_path: Path, source: str, workshop_id: str = "") -> ModAsset:
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
            preview_path=_find_preview(directory, pack_path.name, source == SOURCE_WORKSHOP),
            workshop_url=(
                f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
                if workshop_id
                else ""
            ),
            pack_type=read_pack_type(pack_path),
            updated_at=updated_at,
            created_at=created_at,
            is_symlink=is_symlink,
            sources=[source],
            dependency_packs=read_pack_dependencies(pack_path),
        )
