from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any, Callable, Iterable

from .constants import SOURCE_DATA, SOURCE_WORKSHOP
from .models import GamePaths, ModAsset


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path))).resolve(strict=False)


def _validated_pack_path(path: str | Path, source: str, paths: GamePaths) -> Path:
    candidate = _absolute(path)
    if candidate.suffix.casefold() != ".pack":
        raise ValueError(f"只允许删除 Pack 文件：{candidate}")
    if source == SOURCE_DATA:
        if not paths.data_path:
            raise ValueError("游戏 Data 目录无效")
        root = _absolute(paths.data_path)
        if candidate.parent != root:
            raise ValueError(f"Pack 不在游戏 Data 根目录：{candidate}")
        return candidate
    if source == SOURCE_WORKSHOP:
        if not paths.workshop_path:
            raise ValueError("Workshop 目录无效")
        root = _absolute(paths.workshop_path)
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Pack 不在 Workshop 目录：{candidate}") from exc
        if len(relative.parts) != 2 or not relative.parts[0].isdigit():
            raise ValueError(f"Pack 不在有效的 Workshop 项目目录：{candidate}")
        return candidate
    raise ValueError(f"不支持删除来源：{source}")


def workshop_item_directory(workshop_root: str | Path, workshop_id: str) -> Path:
    normalized_id = str(workshop_id or "").strip()
    if not normalized_id.isdigit():
        raise ValueError("Workshop ID 无效")
    root = _absolute(workshop_root)
    candidate = _absolute(root / normalized_id)
    if candidate.parent != root or candidate.name != normalized_id:
        raise ValueError("Workshop 项目目录无效")
    return candidate


def _source_path(asset: ModAsset, source: str, paths: GamePaths) -> Path:
    for raw_path in (asset.path, *asset.alternate_paths):
        try:
            candidate = _validated_pack_path(raw_path, source, paths)
        except ValueError:
            continue
        if candidate.is_file() or candidate.is_symlink():
            return candidate
    raise ValueError(f"找不到 {asset.pack_name} 的 {source.upper()} 文件")


def build_delete_preview(assets: Iterable[ModAsset], paths: GamePaths) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in assets:
        sources = set(asset.sources or [asset.source])
        source = SOURCE_DATA if SOURCE_DATA in sources else SOURCE_WORKSHOP
        path = _source_path(asset, source, paths)
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        try:
            stat = path.lstat()
        except OSError as exc:
            raise ValueError(f"无法读取待删除文件：{path}：{exc}") from exc
        targets.append(
            {
                "mod_id": asset.id,
                "pack_name": asset.pack_name,
                "source": source,
                "path": str(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    if not targets:
        raise ValueError("没有可删除的 MOD 文件")
    return {
        "targets": targets,
        "data_count": sum(item["source"] == SOURCE_DATA for item in targets),
        "workshop_count": sum(item["source"] == SOURCE_WORKSHOP for item in targets),
    }


def execute_delete_preview(
    preview: dict[str, Any],
    paths: GamePaths,
    *,
    recycle: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    recycle_file = recycle or send_to_recycle_bin
    deleted: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for item in preview.get("targets", []):
        try:
            path = _validated_pack_path(item["path"], str(item["source"]), paths)
            stat = path.lstat()
            if stat.st_size != int(item["size"]) or stat.st_mtime_ns != int(item["mtime_ns"]):
                raise ValueError("文件在确认后发生变化")
            recycle_file(path)
            deleted.append(dict(item))
        except (OSError, ValueError) as exc:
            failures.append({"path": str(item.get("path") or ""), "error": str(exc)})
    return {
        "deleted": deleted,
        "failures": failures,
        "deleted_count": len(deleted),
        "failed_count": len(failures),
    }


def send_to_recycle_bin(path: Path) -> None:
    if os.name != "nt":
        raise OSError("回收站删除仅支持 Windows")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", ctypes.c_int),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    source = ctypes.create_unicode_buffer(f"{path}\0\0")
    operation = SHFILEOPSTRUCTW()
    operation.wFunc = 3
    operation.pFrom = ctypes.cast(source, ctypes.c_wchar_p)
    operation.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400
    result = int(ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation)))
    if result or operation.fAnyOperationsAborted:
        raise OSError(result or 1, f"无法将文件移入回收站：{path}")
