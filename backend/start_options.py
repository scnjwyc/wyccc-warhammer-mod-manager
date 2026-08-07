from __future__ import annotations

import hashlib
import math
import os
import struct
import tempfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .constants import (
    GAME_DATA_FEATURE_WORKSHOP_ITEMS,
    PACK_TYPE_MOVIE,
    SOURCE_DATA,
    SOURCE_WORKSHOP,
)
from .game_data import (
    TABLE_PREFIXES,
    DbSource,
    GameDataEntry,
    build_game_data_entries,
)
from .dynamic_ror_compatibility import build_dynamic_ror_compatibility_entries
from .game_data_settings import (
    normalize_category_unit_mode,
    normalize_single_entity_unit_mode,
    normalize_unit_recruitment_capacity_multiplier,
    normalize_unit_scale_multiplier,
)
from .models import ModAsset
from .scanner import read_pack_type
from .unit_data import build_unit_data_entries


RUNTIME_PACK_NAME = "!!!!wyccc_runtime_options.pack"
GAME_DATA_PATCH_NAME = "!!!!wyccc_game_data_patch.pack"
UNIT_DATA_PATCH_NAME = "!!!!wyccc_unit_data_patch.pack"
DYNAMIC_ROR_COMPATIBILITY_PATCH_NAME = "!!!!wyccc_dynamic_ror_compatibility.pack"
PERMISSIONS_PREFIX = "db\\units_custom_battle_permissions_tables\\"
PERMISSIONS_ENTRY = f"{PERMISSIONS_PREFIX}!!!!wyccc_runtime"
PERMISSIONS_VERSION = 11
PERMISSIONS_GUID = "129d32d8-3563-4d4f-8e19-a815e834e456"

INTRO_MOVIES = (
    *(
        f"movies\\epilepsy_warning\\epilepsy_warning_{language}.ca_vp8"
        for language in (
            "br",
            "cn",
            "cz",
            "de",
            "en",
            "es",
            "fr",
            "it",
            "kr",
            "pl",
            "ru",
            "tr",
            "zh",
        )
    ),
    "movies\\gam_int.ca_vp8",
    *(f"movies\\startup_movie_{index:02d}.ca_vp8" for index in range(1, 9)),
)


@dataclass(frozen=True)
class PackEntry:
    name: str
    payload: bytes


@dataclass(frozen=True)
class GameDataSourceSpec:
    """One Pack whose DB records can affect the generated overlay."""

    path: Path
    asset: ModAsset | None
    role: str


@dataclass(frozen=True)
class GameDataSourceSnapshotEntry:
    spec: GameDataSourceSpec
    source: DbSource
    size: int
    mtime_ns: int
    content_sha256: str

    def input_record(self) -> dict[str, Any]:
        asset = self.spec.asset
        return {
            "role": self.spec.role,
            "pack_name": self.spec.path.name,
            "source": str(asset.source) if asset is not None else self.spec.role,
            "workshop_id": str(asset.workshop_id) if asset is not None else "",
            "file": {
                "path": str(self.spec.path),
                "size": self.size,
                "mtime_ns": self.mtime_ns,
                "target_db_sha256": self.content_sha256,
            },
        }


@dataclass(frozen=True)
class GameDataSourceSnapshot:
    entries: tuple[GameDataSourceSnapshotEntry, ...]

    @property
    def sources(self) -> tuple[DbSource, ...]:
        return tuple(entry.source for entry in self.entries)

    def input_records(self, role: str) -> list[dict[str, Any]]:
        return [
            entry.input_record()
            for entry in self.entries
            if entry.spec.role == role
        ]

    def first_input_record(self, role: str) -> dict[str, Any]:
        return next(
            (
                entry.input_record()
                for entry in self.entries
                if entry.spec.role == role
            ),
            {"missing": True},
        )

    def diagnostics(self) -> dict[str, Any]:
        explicit = self.input_records("explicit")
        movies = self.input_records("auto_movie")
        return {
            "source_count": len(self.entries),
            "explicit_pack_names": [item["pack_name"] for item in explicit],
            "auto_movie_pack_names": [item["pack_name"] for item in movies],
            "source_pack_names": [
                entry.spec.path.name
                for entry in self.entries
                if entry.spec.role != "vanilla"
            ],
        }


def _has_compression_frame(raw: bytes) -> bool:
    """Recognize CA payloads that have a compression frame despite a bad index flag."""
    compression_magic = {b"\x28\xb5\x2f\xfd", b"\x04\x22\x4d\x18"}
    return any(raw[offset : offset + 4] in compression_magic for offset in (0, 4))


def _decompress_payload(raw: bytes, name: str) -> bytes:
    offsets: list[int] = []

    def add_offset(value: int) -> None:
        if 0 <= value < len(raw) and value not in offsets:
            offsets.append(value)

    add_offset(4)
    add_offset(0)
    for index in range(0, min(32, max(0, len(raw) - 4)) + 1):
        if raw[index : index + 4] in {b"\x28\xb5\x2f\xfd", b"\x04\x22\x4d\x18"}:
            add_offset(index)
    for value in (8, 12, 16):
        add_offset(value)

    last_error: Exception | None = None
    try:
        import zstandard

        decompressor = zstandard.ZstdDecompressor()
        for offset in offsets:
            try:
                # CA stores the decompressed byte count immediately before a
                # Zstandard frame.  The frame itself intentionally omits the
                # content-size field, so python-zstandard needs that value as
                # max_output_size (vanilla db.pack uses this layout).
                declared_size = 0
                if offset >= 4:
                    declared_size = struct.unpack_from("<I", raw, offset - 4)[0]
                if 0 < declared_size <= 512 * 1024 * 1024:
                    return decompressor.decompress(
                        raw[offset:],
                        max_output_size=declared_size,
                    )
                return decompressor.decompress(raw[offset:])
            except zstandard.ZstdError as exc:
                last_error = exc
    except ImportError as exc:
        last_error = exc

    try:
        import lz4.frame

        for offset in offsets:
            try:
                return lz4.frame.decompress(raw[offset:])
            except (RuntimeError, ValueError) as exc:
                last_error = exc
    except ImportError as exc:
        last_error = exc

    for offset in offsets:
        for window_bits in (-zlib.MAX_WBITS, zlib.MAX_WBITS):
            try:
                return zlib.decompress(raw[offset:], window_bits)
            except zlib.error as exc:
                last_error = exc
    raise ValueError(f"无法解压 Pack 条目 {name}：{last_error or '未知压缩格式'}")


def read_pack_entries(
    path: Path,
    prefix: str | Iterable[str] = "",
) -> list[PackEntry]:
    prefixes = (
        ((prefix,) if prefix else ())
        if isinstance(prefix, str)
        else tuple(str(item) for item in prefix if str(item))
    )
    try:
        with path.open("rb") as stream:
            header = stream.read(28)
            if len(header) != 28 or header[:4] != b"PFH5":
                return []
            _, _, dependency_size, file_count, index_size, _ = struct.unpack_from("<6i", header, 4)
            if dependency_size < 0 or file_count < 0 or index_size < 0:
                raise ValueError(f"Pack 索引无效：{path.name}")
            stream.seek(28 + dependency_size)
            index = stream.read(index_size)
            if len(index) != index_size:
                raise ValueError(f"Pack 索引不完整：{path.name}")
            data_offset = 28 + dependency_size + index_size
            cursor = 0
            current_offset = data_offset
            selected: list[tuple[str, int, int, bool]] = []
            for _ in range(file_count):
                if cursor + 5 > len(index):
                    raise ValueError(f"Pack 文件索引损坏：{path.name}")
                file_size = struct.unpack_from("<i", index, cursor)[0]
                compressed = index[cursor + 4] == 1
                cursor += 5
                terminator = index.find(b"\0", cursor)
                if file_size < 0 or terminator < 0:
                    raise ValueError(f"Pack 文件索引损坏：{path.name}")
                name = index[cursor:terminator].decode("utf-8", errors="replace")
                if not prefixes or any(
                    name.casefold().startswith(item.casefold()) for item in prefixes
                ):
                    selected.append((name, current_offset, file_size, compressed))
                current_offset += file_size
                cursor = terminator + 1

            entries: list[PackEntry] = []
            for name, offset, file_size, compressed in selected:
                stream.seek(offset)
                payload = stream.read(file_size)
                if len(payload) != file_size:
                    raise ValueError(f"Pack 内文件不完整：{name}")
                # A few third-party Packs contain a valid Zstandard/LZ4 frame
                # but mark the index entry as uncompressed.  Accept only an
                # unmistakable frame at the payload start (or after CA's size
                # prefix), so ordinary uncompressed entries are untouched.
                needs_decompression = compressed or _has_compression_frame(payload)
                entries.append(
                    PackEntry(
                        name,
                        _decompress_payload(payload, name)
                        if needs_decompression
                        else payload,
                    )
                )
            return entries
    except OSError as exc:
        raise ValueError(f"无法读取 Pack：{path}") from exc


def _skip_string_u8(payload: bytes, cursor: int) -> int:
    if cursor + 2 > len(payload):
        raise ValueError("权限表字符串长度越界")
    length = struct.unpack_from("<H", payload, cursor)[0]
    cursor += 2 + length
    if cursor > len(payload):
        raise ValueError("权限表字符串内容越界")
    return cursor


def _skip_optional_string_u8(payload: bytes, cursor: int) -> int:
    if cursor >= len(payload):
        raise ValueError("权限表可选字符串越界")
    exists = payload[cursor]
    cursor += 1
    if exists == 1:
        return _skip_string_u8(payload, cursor)
    if exists != 0:
        raise ValueError("权限表可选字符串标记无效")
    return cursor


def _permission_rows(payload: bytes) -> list[bytes]:
    cursor = 0
    version: int | None = None
    while cursor + 4 <= len(payload):
        marker = payload[cursor : cursor + 4]
        if marker == b"\xfd\xfe\xfc\xff":
            cursor += 4
            if cursor + 2 > len(payload):
                raise ValueError("权限表 GUID 头不完整")
            length = struct.unpack_from("<H", payload, cursor)[0]
            cursor += 2 + length * 2
        elif marker == b"\xfc\xfd\xfe\xff":
            cursor += 4
            if cursor + 4 > len(payload):
                raise ValueError("权限表版本头不完整")
            version = struct.unpack_from("<i", payload, cursor)[0]
            cursor += 4
        else:
            break
    if version != PERMISSIONS_VERSION:
        return []
    if cursor + 5 > len(payload):
        raise ValueError("权限表行头不完整")
    cursor += 1  # table marker
    row_count = struct.unpack_from("<i", payload, cursor)[0]
    cursor += 4
    if row_count < 0:
        raise ValueError("权限表行数无效")

    rows: list[bytes] = []
    for _ in range(row_count):
        row_start = cursor
        cursor = _skip_string_u8(payload, cursor)  # faction
        general_offset = cursor
        cursor += 1  # general_unit
        cursor = _skip_string_u8(payload, cursor)  # unit
        cursor += 2  # siege_unit_attacker / siege_unit_defender
        cursor = _skip_optional_string_u8(payload, cursor)  # general_portrait
        cursor = _skip_optional_string_u8(payload, cursor)  # general_uniform
        cursor = _skip_optional_string_u8(payload, cursor)  # set_piece_character
        cursor += 1  # campaign_exclusive
        cursor = _skip_optional_string_u8(payload, cursor)  # armory_item_set
        cursor += 1  # supports_upgrades
        if cursor > len(payload):
            raise ValueError("权限表行内容越界")
        original = payload[row_start:cursor]
        relative_general = general_offset - row_start
        general_value = original[relative_general]
        if general_value not in {0, 1}:
            raise ValueError("权限表 general_unit 字段无效")
        modified = bytearray(original)
        modified[relative_general] = 1
        rows.append(bytes(modified))
        if general_value == 1:
            duplicate = bytearray(original)
            duplicate[relative_general] = 0
            rows.append(bytes(duplicate))
    return rows


def _build_permission_table(pack_paths: Iterable[Path]) -> bytes:
    rows: list[bytes] = []
    for pack_path in pack_paths:
        for entry in read_pack_entries(pack_path, PERMISSIONS_PREFIX):
            rows.extend(_permission_rows(entry.payload))
    if not rows:
        raise ValueError("未能读取自定义战斗权限表，无法启用“所有单位视为领主”")
    guid = PERMISSIONS_GUID.encode("utf-16le")
    return b"".join(
        (
            b"\xfd\xfe\xfc\xff",
            struct.pack("<H", len(PERMISSIONS_GUID)),
            guid,
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", PERMISSIONS_VERSION),
            b"\x01",
            struct.pack("<i", len(rows)),
            b"".join(rows),
        )
    )


def write_pfh5_pack(
    path: Path,
    entries: Iterable[PackEntry],
    *,
    pack_header_mask: int = 3,
) -> Path:
    normalized = list(entries)
    if not normalized:
        raise ValueError("运行时 Pack 没有可写入内容")
    index_parts: list[bytes] = []
    for entry in normalized:
        name = entry.name.encode("utf-8")
        index_parts.append(struct.pack("<iB", len(entry.payload), 0) + name + b"\0")
    index = b"".join(index_parts)
    content = b"".join(
        (
            b"PFH5",
            struct.pack(
                "<6i",
                int(pack_header_mask),
                0,
                0,
                len(normalized),
                len(index),
                0x7FFFFFFF,
            ),
            index,
            *(entry.payload for entry in normalized),
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _effective_game_data_settings(
    settings: dict[str, Any],
    subscribed_workshop_ids: Iterable[str],
) -> dict[str, int | bool | str]:
    subscribed_ids = {
        str(workshop_id).strip()
        for workshop_id in subscribed_workshop_ids
        if str(workshop_id).strip()
    }
    unit_size_available = (
        GAME_DATA_FEATURE_WORKSHOP_ITEMS["unit_size"]["workshop_id"] in subscribed_ids
    )
    friendly_fire_available = (
        GAME_DATA_FEATURE_WORKSHOP_ITEMS["friendly_fire"]["workshop_id"] in subscribed_ids
    )
    unit_cap_available = (
        GAME_DATA_FEATURE_WORKSHOP_ITEMS["unit_cap"]["workshop_id"] in subscribed_ids
    )
    unit_multiplier = normalize_unit_scale_multiplier(
        settings.get("unit_model_multiplier", 1)
    )
    unit_recruitment_capacity_multiplier = (
        normalize_unit_recruitment_capacity_multiplier(
            settings.get("unit_recruitment_capacity_multiplier", 1)
        )
    )
    return {
        "unit_model_multiplier": unit_multiplier if unit_size_available else 1,
        "unit_recruitment_capacity_multiplier": (
            unit_recruitment_capacity_multiplier if unit_cap_available else 1
        ),
        "single_entity_unit_mode": (
            normalize_single_entity_unit_mode(
                settings.get("single_entity_unit_mode", "scale")
            )
            if unit_size_available
            else "scale"
        ),
        "artillery_unit_mode": (
            normalize_category_unit_mode(
                settings.get("artillery_unit_mode", "full")
            )
            if unit_size_available
            else "full"
        ),
        "war_machine_unit_mode": (
            normalize_category_unit_mode(
                settings.get("war_machine_unit_mode", "full")
            )
            if unit_size_available
            else "full"
        ),
        "scale_lord_hero_health": (
            bool(settings.get("scale_lord_hero_health")) if unit_size_available else False
        ),
        "disable_unit_friendly_fire": (
            bool(settings.get("disable_unit_friendly_fire")) if friendly_fire_available else False
        ),
        "disable_spell_friendly_fire": (
            bool(settings.get("disable_spell_friendly_fire")) if friendly_fire_available else False
        ),
    }


def _game_data_enabled(settings: dict[str, int | bool | str]) -> bool:
    return (
        not math.isclose(
            float(settings["unit_model_multiplier"]),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or int(settings["unit_recruitment_capacity_multiplier"]) != 1
        or bool(settings["disable_unit_friendly_fire"])
        or bool(settings["disable_spell_friendly_fire"])
    )


def _enabled_game_data_options(settings: dict[str, int | bool | str]) -> list[str]:
    options: list[str] = []
    if not math.isclose(
        float(settings["unit_model_multiplier"]),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        options.append("unit_model_multiplier")
        if settings["single_entity_unit_mode"] == "health":
            options.append("single_entity_unit_mode")
        if settings["artillery_unit_mode"] != "full":
            options.append("artillery_unit_mode")
        if settings["war_machine_unit_mode"] != "full":
            options.append("war_machine_unit_mode")
        if settings["scale_lord_hero_health"]:
            options.append("scale_lord_hero_health")
    if int(settings["unit_recruitment_capacity_multiplier"]) != 1:
        options.append("unit_recruitment_capacity_multiplier")
    if settings["disable_unit_friendly_fire"]:
        options.append("disable_unit_friendly_fire")
    if settings["disable_spell_friendly_fire"]:
        options.append("disable_spell_friendly_fire")
    return options


def _changed_game_data_rows(stats: dict[str, int | float]) -> int:
    return sum(
        int(stats.get(key, 0))
        for key in (
            "unit_rows_scaled",
            "unit_recruitment_capacity_rows_changed",
            "land_rows_scaled",
            "lord_hero_health_rows_scaled",
            "single_entity_health_rows_scaled",
            "artillery_health_rows_scaled",
            "war_machine_health_rows_scaled",
            "unit_friendly_fire_rows_changed",
            "unit_friendly_fire_kv_rules_changed",
            "unit_max_drag_width_changed",
            "spell_friendly_fire_rows_changed",
        )
    )


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _movie_pack_paths(directory: Path) -> list[Path]:
    """Find Packs that the game can load automatically from one search root."""
    if not directory.is_dir():
        return []
    try:
        pack_paths = sorted(
            (
                item.resolve(strict=False)
                for item in directory.iterdir()
                if item.is_file() and item.suffix.casefold() == ".pack"
            ),
            key=lambda item: (item.name.casefold(), item.name),
        )
    except OSError as exc:
        raise ValueError(f"无法扫描自动加载 Movie Pack 目录 {directory}：{exc}") from exc
    return [path for path in pack_paths if read_pack_type(path) == PACK_TYPE_MOVIE]


def resolve_game_data_source_specs(
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    unit_data_patch_path: str | Path | None = None,
) -> tuple[GameDataSourceSpec, ...]:
    """Resolve every Pack that can affect a game-data patch for this launch.

    A Movie Pack in Data is always discovered by the game.  A Movie Pack next
    to an explicitly enabled external Pack is also reachable because that
    directory is added to the launch file as a working directory.  They must
    therefore participate in both effective-row selection and the cache key.
    """
    data_root = Path(data_path).resolve(strict=False)
    active_assets = [
        assets[mod_id]
        for mod_id in active_ids
        if mod_id in assets and Path(assets[mod_id].path).is_file()
    ]
    asset_by_path = {
        _path_key(Path(asset.path)): asset
        for asset in assets.values()
        if Path(asset.path).is_file()
    }

    active_paths: list[Path] = []
    working_directories: list[Path] = []
    seen_paths: set[str] = set()
    seen_directories: set[str] = set()
    data_root_key = _path_key(data_root)
    for asset in active_assets:
        path = Path(asset.path).resolve(strict=False)
        path_key = _path_key(path)
        if path_key not in seen_paths:
            seen_paths.add(path_key)
            active_paths.append(path)
        directory = Path(asset.directory).resolve(strict=False)
        directory_key = _path_key(directory)
        if directory_key != data_root_key and directory_key not in seen_directories:
            seen_directories.add(directory_key)
            working_directories.append(directory)

    movie_paths: list[Path] = []
    seen_movie_paths: set[str] = set()
    for directory in (data_root, *working_directories):
        for path in _movie_pack_paths(directory):
            path_key = _path_key(path)
            if path_key not in seen_movie_paths:
                seen_movie_paths.add(path_key)
                movie_paths.append(path)

    specs: list[GameDataSourceSpec] = []
    if unit_data_patch_path:
        resolved_patch = Path(unit_data_patch_path).resolve(strict=False)
        if resolved_patch.is_file():
            specs.append(
                GameDataSourceSpec(
                    path=resolved_patch,
                    asset=None,
                    role="unit_data_patch",
                )
            )
    specs.extend(
        GameDataSourceSpec(
            path=path,
            asset=asset_by_path.get(_path_key(path)),
            role="auto_movie",
        )
        for path in movie_paths
    )
    specs.extend(
        GameDataSourceSpec(
            path=path,
            asset=asset_by_path.get(_path_key(path)),
            role="explicit",
        )
        for path in active_paths
        if _path_key(path) not in seen_movie_paths
    )
    specs.append(
        GameDataSourceSpec(
            path=(data_root / "db.pack").resolve(strict=False),
            asset=None,
            role="vanilla",
        )
    )
    return tuple(specs)


def _read_game_data_source_snapshot_entry(
    spec: GameDataSourceSpec,
) -> GameDataSourceSnapshotEntry:
    path = spec.path
    source_name = _game_data_source_name(path, spec.asset, spec.role)
    try:
        before = path.stat()
        if not path.is_file():
            raise OSError("不是普通文件")
    except OSError as exc:
        raise ValueError(f"游戏数据来源 {source_name} 不存在或无法读取：{exc}") from exc

    try:
        raw_entries = read_pack_entries(path, TABLE_PREFIXES)
    except ValueError as exc:
        raise ValueError(f"游戏数据来源 {source_name} 读取失败：{exc}") from exc

    try:
        after = path.stat()
    except OSError as exc:
        raise ValueError(f"游戏数据来源 {source_name} 在读取后不可用：{exc}") from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ValueError(
            f"游戏数据来源 {source_name} 在读取期间发生变化，请等待 Steam 更新完成后重试"
        )

    digest = hashlib.sha256()
    digest.update(b"wyccc-game-data-source-v1\0")
    entries: list[GameDataEntry] = []
    for entry in raw_entries:
        name = entry.name.replace("/", "\\").encode("utf-8")
        digest.update(len(name).to_bytes(4, "little"))
        digest.update(name)
        digest.update(len(entry.payload).to_bytes(8, "little"))
        digest.update(entry.payload)
        entries.append(GameDataEntry(entry.name, entry.payload))
    return GameDataSourceSnapshotEntry(
        spec=spec,
        source=DbSource(source_name, tuple(entries)),
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        content_sha256=digest.hexdigest(),
    )


def collect_game_data_source_snapshot(
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    unit_data_patch_path: str | Path | None = None,
) -> GameDataSourceSnapshot:
    specs = resolve_game_data_source_specs(
        data_path,
        assets,
        active_ids,
        unit_data_patch_path=unit_data_patch_path,
    )
    workers = min(8, max(1, len(specs)))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            entries = list(pool.map(_read_game_data_source_snapshot_entry, specs))
        return GameDataSourceSnapshot(tuple(entries))
    return GameDataSourceSnapshot(
        tuple(_read_game_data_source_snapshot_entry(spec) for spec in specs)
    )


def _collect_game_data_sources(
    data_path: str,
    assets: dict[str, ModAsset],
    active_ids: list[str],
) -> tuple[DbSource, ...]:
    return collect_game_data_source_snapshot(data_path, assets, active_ids).sources


def _game_data_source_name(
    path: Path,
    asset: ModAsset | None,
    role: str = "explicit",
) -> str:
    if role == "unit_data_patch":
        return "单位数据修改补丁"
    if role == "auto_movie":
        if asset is None:
            return f'自动加载 Movie Pack "{path.name}"'
        return f'自动加载 Movie MOD "{asset.effective_name}" [pack: {path.name}]'
    if asset is None:
        if path.name.casefold() == "db.pack":
            return "原版数据库 db.pack"
        return f'Pack "{path.name}"'

    source_name = {
        SOURCE_WORKSHOP: "Workshop",
        SOURCE_DATA: "Data",
    }.get(str(asset.source or "").casefold(), str(asset.source or "unknown") or "unknown")
    mod_name = str(asset.effective_name or "").strip() or path.stem
    return f'MOD "{mod_name}" [pack: {path.name}, source: {source_name}]'


def build_game_data_patch(
    output_dir: Path,
    data_path: str,
    assets: dict[str, ModAsset],
    active_ids: list[str],
    settings: dict[str, Any],
    subscribed_workshop_ids: Iterable[str] = (),
    *,
    source_snapshot: GameDataSourceSnapshot | None = None,
    unit_data_patch_path: str | Path | None = None,
) -> dict[str, Any]:
    effective_settings = _effective_game_data_settings(settings, subscribed_workshop_ids)
    output_path = Path(output_dir) / GAME_DATA_PATCH_NAME
    if not _game_data_enabled(effective_settings):
        output_path.unlink(missing_ok=True)
        return {
            "path": "",
            "options": [],
            "entry_count": 0,
            "game_data": {},
        }

    snapshot = source_snapshot or collect_game_data_source_snapshot(
        data_path,
        assets,
        active_ids,
        unit_data_patch_path=unit_data_patch_path,
    )
    sources = snapshot.sources
    diagnostics = snapshot.diagnostics()
    game_data = build_game_data_entries(sources, effective_settings)
    entries = [PackEntry(entry.name, entry.payload) for entry in game_data.entries]
    diagnostics["output_table_names"] = [entry.name for entry in entries]
    if not entries or _changed_game_data_rows(game_data.stats) == 0:
        output_path.unlink(missing_ok=True)
        return {
            "path": "",
            "options": _enabled_game_data_options(effective_settings),
            "entry_count": 0,
            "game_data": game_data.stats,
            "source_diagnostics": diagnostics,
        }
    write_pfh5_pack(output_path, entries)
    return {
        "path": str(output_path.resolve(strict=False)),
        "options": _enabled_game_data_options(effective_settings),
        "entry_count": len(entries),
        "game_data": game_data.stats,
        "source_diagnostics": diagnostics,
    }


def build_unit_data_patch(
    output_dir: Path,
    data_path: str,
    assets: dict[str, ModAsset],
    active_ids: list[str],
    settings: dict[str, Any],
    edits: dict[str, dict[str, Any]],
    *,
    source_snapshot: GameDataSourceSnapshot | None = None,
) -> dict[str, Any]:
    """Write the hidden unit-data patch pack when per-unit edits exist."""
    output_path = Path(output_dir) / UNIT_DATA_PATCH_NAME
    if not edits:
        output_path.unlink(missing_ok=True)
        return {
            "path": "",
            "entry_count": 0,
            "stats": {"edited_unit_count": 0, "disabled_unit_count": 0, "entry_count": 0},
        }
    snapshot = source_snapshot or collect_game_data_source_snapshot(
        data_path,
        assets,
        active_ids,
    )
    built = build_unit_data_entries(snapshot.sources, settings, edits)
    entries = [PackEntry(entry.name, entry.payload) for entry in built.entries]
    if not entries:
        output_path.unlink(missing_ok=True)
        return {
            "path": "",
            "entry_count": 0,
            "stats": dict(built.stats),
        }
    write_pfh5_pack(output_path, entries)
    return {
        "path": str(output_path.resolve(strict=False)),
        "entry_count": len(entries),
        "stats": dict(built.stats),
    }


def build_dynamic_ror_compatibility_patch(
    output_dir: Path,
    data_path: str,
    assets: dict[str, ModAsset],
    active_ids: list[str],
    enabled: bool,
    *,
    source_snapshot: GameDataSourceSnapshot | None = None,
) -> dict[str, Any]:
    """Write the launch-time compatibility Pack for Nanu's Dynamic RoRs."""
    output_path = Path(output_dir) / DYNAMIC_ROR_COMPATIBILITY_PATCH_NAME
    if not enabled:
        output_path.unlink(missing_ok=True)
        return {
            "path": "",
            "entry_count": 0,
            "stats": {
                "dynamic_ror_detected": 0,
                "eligible_mod_unit_count": 0,
                "patched_unit_count": 0,
            },
        }
    snapshot = source_snapshot or collect_game_data_source_snapshot(
        data_path,
        assets,
        active_ids,
    )
    built = build_dynamic_ror_compatibility_entries(snapshot.sources)
    entries = [PackEntry(entry.name, entry.payload) for entry in built.entries]
    if not entries or int(built.stats.get("patched_unit_count", 0)) == 0:
        output_path.unlink(missing_ok=True)
        return {
            "path": "",
            "entry_count": 0,
            "stats": dict(built.stats),
            "source_diagnostics": snapshot.diagnostics(),
        }
    write_pfh5_pack(output_path, entries)
    diagnostics = snapshot.diagnostics()
    diagnostics["output_entry_names"] = [entry.name for entry in entries]
    return {
        "path": str(output_path.resolve(strict=False)),
        "entry_count": len(entries),
        "stats": dict(built.stats),
        "source_diagnostics": diagnostics,
    }


def build_runtime_options_pack(
    output_dir: Path,
    data_path: str,
    assets: dict[str, ModAsset],
    active_ids: list[str],
    settings: dict[str, Any],
) -> dict[str, Any]:
    entries: list[PackEntry] = []
    enabled_options: list[str] = []
    if settings.get("custom_battle_all_units_as_lords"):
        source_specs = resolve_game_data_source_specs(data_path, assets, active_ids)
        unique_paths = list(
            dict.fromkeys(
                spec.path.resolve(strict=False)
                for spec in source_specs
                if spec.path.is_file()
            )
        )
        entries.append(PackEntry(PERMISSIONS_ENTRY, _build_permission_table(unique_paths)))
        enabled_options.append("custom_battle_all_units_as_lords")
    if settings.get("enable_script_logging"):
        entries.append(PackEntry("script\\enable_console_logging", b"\0"))
        enabled_options.append("enable_script_logging")
    if settings.get("skip_intro_movies"):
        entries.extend(PackEntry(name, b"") for name in INTRO_MOVIES)
        enabled_options.append("skip_intro_movies")

    output_path = Path(output_dir) / RUNTIME_PACK_NAME
    if not entries:
        output_path.unlink(missing_ok=True)
        return {
            "path": "",
            "options": [],
            "entry_count": 0,
            "game_data": {},
        }
    write_pfh5_pack(output_path, entries)
    return {
        "path": str(output_path.resolve(strict=False)),
        "options": enabled_options,
        "entry_count": len(entries),
        "game_data": {},
    }
