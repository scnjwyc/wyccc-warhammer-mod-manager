from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterator

from .games import GameDefinition, WARHAMMER3_GAME, get_game_definition
from .models import GamePaths

_TOKEN_RE = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')


def _unescape_vdf(value: str) -> str:
    return value.replace(r"\\", "\\").replace(r'\"', '"')


def tokenize_vdf(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        if match.group(2):
            tokens.append(match.group(2))
        else:
            tokens.append(_unescape_vdf(match.group(1) or ""))
    return tokens


def parse_vdf(text: str) -> dict[str, Any]:
    tokens = tokenize_vdf(text)
    index = 0

    def parse_object(stop_at_brace: bool = False) -> dict[str, Any]:
        nonlocal index
        result: dict[str, Any] = {}
        while index < len(tokens):
            token = tokens[index]
            if token == "}":
                if not stop_at_brace:
                    raise ValueError("Unexpected closing brace")
                index += 1
                return result
            if token == "{":
                raise ValueError("Unexpected opening brace")
            key = token
            index += 1
            if index >= len(tokens):
                result[key] = ""
                break
            value_token = tokens[index]
            index += 1
            if value_token == "{":
                result[key] = parse_object(True)
            elif value_token == "}":
                raise ValueError("Missing value before closing brace")
            else:
                result[key] = value_token
        if stop_at_brace:
            raise ValueError("Unclosed VDF object")
        return result

    return parse_object(False)


def _registry_steam_roots() -> Iterator[Path]:
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return
    candidates = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]
    for hive, key_name, value_name in candidates:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                if value:
                    yield Path(str(value)).expanduser()
        except OSError:
            continue


def candidate_steam_roots() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("STEAM_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(_registry_steam_roots() or [])
    if os.name == "nt":
        program_files = os.environ.get("PROGRAMFILES(X86)") or os.environ.get("PROGRAMFILES")
        if program_files:
            candidates.append(Path(program_files) / "Steam")
    else:
        candidates.extend(
            [
                Path.home() / ".steam" / "steam",
                Path.home() / ".local" / "share" / "Steam",
            ]
        )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.expanduser().resolve(strict=False)).casefold()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(candidate)
    return unique


def _library_roots(steam_root: Path) -> list[Path]:
    roots = [steam_root]
    vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
    if not vdf_path.is_file():
        return roots
    try:
        parsed = parse_vdf(vdf_path.read_text(encoding="utf-8-sig", errors="replace"))
        folders = parsed.get("libraryfolders", parsed.get("LibraryFolders", {}))
        if isinstance(folders, dict):
            for key, value in folders.items():
                if not str(key).isdigit():
                    continue
                path_value = value.get("path") if isinstance(value, dict) else value
                if path_value:
                    roots.append(Path(str(path_value)))
    except (OSError, ValueError):
        pass
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        normalized = str(root.resolve(strict=False)).casefold()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(root)
    return unique


def _read_install_dir(manifest_path: Path, default_install_dir: str) -> str:
    try:
        parsed = parse_vdf(manifest_path.read_text(encoding="utf-8-sig", errors="replace"))
        state = parsed.get("AppState", parsed.get("appstate", {}))
        if isinstance(state, dict):
            value = state.get("installdir", state.get("InstallDir", ""))
            if value:
                return str(value)
    except (OSError, ValueError):
        pass
    return default_install_dir


def _case_insensitive_value(mapping: dict[str, Any], key: str, default: Any = "") -> Any:
    wanted = key.casefold()
    for current_key, value in mapping.items():
        if str(current_key).casefold() == wanted:
            return value
    return default


def read_app_manifest_last_updated(manifest_path: Path) -> int:
    """Read Steam's LastUpdated value and return milliseconds since epoch."""
    try:
        parsed = parse_vdf(manifest_path.read_text(encoding="utf-8-sig", errors="replace"))
        state = _case_insensitive_value(parsed, "AppState", {})
        if not isinstance(state, dict):
            return 0
        seconds = int(_case_insensitive_value(state, "LastUpdated", 0) or 0)
        return seconds * 1000 if seconds > 0 else 0
    except (OSError, TypeError, ValueError):
        return 0


def game_last_updated_at(paths: GamePaths) -> int:
    """Resolve the game's last Steam update, with local core files as a fallback."""
    definition = paths.game_definition
    candidates: list[Path] = []
    if paths.steam_library:
        candidates.append(
            Path(paths.steam_library) / "steamapps" / f"appmanifest_{definition.app_id}.acf"
        )
    if paths.game_path:
        game_root = Path(paths.game_path)
        candidates.append(game_root.parent.parent / f"appmanifest_{definition.app_id}.acf")
    seen: set[str] = set()
    for manifest in candidates:
        key = str(manifest.resolve(strict=False)).casefold()
        if key in seen:
            continue
        seen.add(key)
        updated_at = read_app_manifest_last_updated(manifest)
        if updated_at:
            return updated_at

    local_times: list[int] = []
    if paths.game_path:
        game_root = Path(paths.game_path)
        for candidate in (
            Path(paths.executable_path),
            game_root / "data" / "data.pack",
            game_root / "data" / "db.pack",
            game_root / "data" / "data_script.pack",
        ):
            try:
                local_times.append(candidate.stat().st_mtime_ns // 1_000_000)
            except OSError:
                continue
    return max(local_times, default=0)


def discover_game_paths(game_id: str = "") -> GamePaths:
    definition = get_game_definition(game_id)
    return _discover_game_paths(definition)


def _discover_game_paths(definition: GameDefinition) -> GamePaths:
    for steam_root in candidate_steam_roots():
        for library_root in _library_roots(steam_root):
            steamapps = library_root / "steamapps"
            manifest = steamapps / f"appmanifest_{definition.app_id}.acf"
            if not manifest.is_file():
                continue
            install_dir = _read_install_dir(manifest, definition.install_dir)
            game_path = steamapps / "common" / install_dir
            executable = game_path / definition.executable_name
            data_path = game_path / "data"
            if not executable.is_file() or not data_path.is_dir():
                continue
            workshop_path = steamapps / "workshop" / "content" / definition.app_id
            return GamePaths(
                game_id=definition.id,
                game_path=str(game_path.resolve()),
                data_path=str(data_path.resolve()),
                workshop_path=str(workshop_path.resolve(strict=False)),
                steam_root=str(steam_root.resolve(strict=False)),
                steam_library=str(library_root.resolve(strict=False)),
                detected_by="steam-vdf",
            )
    return GamePaths(game_id=definition.id)


def discover_wh3_paths() -> GamePaths:
    """Compatibility wrapper for callers which still explicitly request WH3."""
    return _discover_game_paths(WARHAMMER3_GAME)
