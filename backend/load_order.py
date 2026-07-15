from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from .constants import SOURCE_DATA
from .models import LaunchPlan, ModAsset

_MOD_LINE_RE = re.compile(r'^\s*mod\s+"([^"]+)"\s*;', re.IGNORECASE | re.MULTILINE)


def file_token(path: Path) -> str:
    if not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}:{digest.hexdigest()}"


def current_order_path(game_path: str, preferred_name: str = "") -> Path:
    primary = Path(game_path) / "used_mods.txt"
    fallback = Path(game_path) / "my_mods.txt"
    if preferred_name in {primary.name, fallback.name}:
        preferred = Path(game_path) / preferred_name
        if preferred.is_file():
            return preferred
    return primary if primary.is_file() or not fallback.is_file() else fallback


class LoadOrderService:
    def __init__(self, backup_dir: Path):
        self.backup_dir = Path(backup_dir)

    def import_disk_order(
        self,
        game_path: str,
        mods: list[ModAsset],
        preferred_name: str = "",
    ) -> list[str]:
        if not game_path:
            return []
        source_path = current_order_path(game_path, preferred_name)
        return self.import_order_file(source_path, mods)

    @staticmethod
    def import_order_file(source_path: Path, mods: list[ModAsset]) -> list[str]:
        if not source_path.is_file():
            return []
        try:
            content = source_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return []
        by_name: dict[str, list[ModAsset]] = {}
        for mod in mods:
            by_name.setdefault(mod.pack_name.casefold(), []).append(mod)
        result: list[str] = []
        for pack_name in _MOD_LINE_RE.findall(content):
            candidates = by_name.get(Path(pack_name).name.casefold(), [])
            if not candidates:
                continue
            selected = sorted(candidates, key=lambda item: (item.source != SOURCE_DATA, item.id))[0]
            if selected.id not in result:
                result.append(selected.id)
        return result

    def build_plan(
        self,
        game_path: str,
        data_path: str,
        assets: dict[str, ModAsset],
        ordered_mod_ids: list[str],
        target_name: str = "used_mods.txt",
    ) -> LaunchPlan:
        if not game_path:
            raise ValueError("尚未设置游戏目录")
        normalized_ids = list(dict.fromkeys(ordered_mod_ids))
        selected: list[ModAsset] = []
        missing_ids: list[str] = []
        for mod_id in normalized_ids:
            asset = assets.get(mod_id)
            if not asset or not Path(asset.path).is_file():
                missing_ids.append(mod_id)
                continue
            if '"' in asset.pack_name or '"' in asset.directory:
                raise ValueError(f"Pack 路径包含不支持的引号：{asset.path}")
            selected.append(asset)
        if missing_ids:
            raise ValueError(f"以下启用项已不存在：{', '.join(missing_ids[:5])}")

        data_root = Path(data_path).resolve(strict=False) if data_path else Path()
        working_directories: list[str] = []
        seen_directories: set[str] = set()
        for asset in selected:
            directory = Path(asset.directory).resolve(strict=False)
            is_data_root = bool(data_path) and (
                os.path.normcase(str(directory)) == os.path.normcase(str(data_root))
            )
            if asset.source == SOURCE_DATA and is_data_root:
                continue
            key = os.path.normcase(str(directory))
            if key not in seen_directories:
                seen_directories.add(key)
                working_directories.append(str(directory))

        lines = [f'add_working_directory "{directory}";' for directory in working_directories]
        lines.extend(f'mod "{asset.pack_name}";' for asset in selected)
        content = "\r\n".join(lines)
        if content:
            content += "\r\n"
        target_path = str((Path(game_path) / target_name).resolve(strict=False))
        return LaunchPlan(
            ordered_mod_ids=[asset.id for asset in selected],
            working_directories=working_directories,
            pack_names=[asset.pack_name for asset in selected],
            content=content,
            target_path=target_path,
        )

    def write_plan(
        self,
        plan: LaunchPlan,
        expected_token: str = "",
        comparison_path: Path | None = None,
    ) -> tuple[LaunchPlan, str, str]:
        primary = Path(plan.target_path)
        comparison_path = comparison_path or current_order_path(str(primary.parent))
        if expected_token and file_token(comparison_path) != expected_token:
            raise ValueError("加载清单已被其他程序修改，请重新扫描后再保存")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = ""
        if comparison_path.is_file():
            seconds = time.strftime("%Y%m%d-%H%M%S")
            stamp = f"{seconds}-{time.time_ns() % 1_000_000_000:09d}"
            backup = self.backup_dir / f"{comparison_path.stem}-{stamp}.txt"
            shutil.copy2(comparison_path, backup)
            backup_path = str(backup)

        try:
            written_path = self._atomic_write(primary, plan.content)
        except OSError:
            fallback = primary.with_name("my_mods.txt")
            written_path = self._atomic_write(fallback, plan.content)
            plan = LaunchPlan(
                ordered_mod_ids=plan.ordered_mod_ids,
                working_directories=plan.working_directories,
                pack_names=plan.pack_names,
                content=plan.content,
                target_path=str(fallback),
            )
        return plan, backup_path, file_token(written_path)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        unique = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}"
        temp = path.with_name(f".{path.name}.{unique}.tmp")
        data = content.encode("utf-8")
        try:
            with temp.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            if path.read_bytes() != data:
                raise OSError(f"写入后校验失败：{path}")
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return path
