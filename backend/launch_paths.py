from __future__ import annotations

import ctypes
import os
import string
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path


def _needs_ascii_alias(path: Path) -> bool:
    return any(ord(character) > 127 for character in str(path))


def _used_drive_letters() -> set[str]:
    if os.name != "nt":
        return set()
    bitmask = int(ctypes.windll.kernel32.GetLogicalDrives())
    return {
        letter
        for index, letter in enumerate(string.ascii_uppercase)
        if bitmask & (1 << index)
    }


@dataclass(frozen=True)
class LaunchPathMap:
    aliases: tuple[tuple[Path, str], ...] = ()

    def map_path(self, path: str | Path) -> str:
        physical_path = Path(path).resolve(strict=False)
        for root, alias in self.aliases:
            try:
                relative_path = physical_path.relative_to(root)
            except ValueError:
                continue
            return str(Path(alias) / relative_path)
        return str(physical_path)


class LaunchPathAliases:
    """Expose non-ASCII game roots through session-local ASCII drive aliases."""

    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}
        self._lock = threading.Lock()

    def prepare(self, game_path: str, workshop_path: str) -> LaunchPathMap:
        roots = [
            Path(path).resolve(strict=False)
            for path in (game_path, workshop_path)
            if str(path or "").strip()
        ]
        aliases = [
            (root, self._alias_for(root))
            for root in roots
            if _needs_ascii_alias(root)
        ]
        aliases.sort(key=lambda item: len(str(item[0])), reverse=True)
        return LaunchPathMap(tuple(aliases))

    def _alias_for(self, root: Path) -> str:
        key = os.path.normcase(str(root))
        with self._lock:
            existing = self._aliases.get(key)
            if existing:
                return existing
            reserved_letters = _used_drive_letters() | {
                value[0].upper() for value in self._aliases.values()
            }
            alias = self._create_alias(root, reserved_letters)
            self._aliases[key] = alias
            return alias

    @staticmethod
    def _create_alias(root: Path, used_letters: set[str]) -> str:
        if os.name != "nt":
            raise ValueError("当前系统无法为非 ASCII 游戏路径创建临时驱动器映射")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for letter in reversed(string.ascii_uppercase):
            if letter in used_letters:
                continue
            drive = f"{letter}:"
            try:
                subprocess.run(
                    ["subst.exe", drive, str(root)],
                    check=True,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    creationflags=creationflags,
                )
            except (OSError, subprocess.SubprocessError):
                used_letters.add(letter)
                continue
            return f"{drive}\\"
        raise ValueError("没有可用的驱动器号，无法启动位于非 ASCII 路径的游戏")
