from __future__ import annotations

import ctypes
import os
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .steamworks_bridge import runtime_root


_STEAM_FRIENDS_LOCK = threading.Lock()
_UNKNOWN_PERSONA_NAMES = {"", "[unknown]"}


class SteamFriendsError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SteamPersonaResult:
    names: dict[str, str]
    unresolved: tuple[str, ...]


@contextmanager
def _temporary_app_environment(app_id: int) -> Iterator[None]:
    keys = ("SteamAppId", "SteamGameId")
    previous = {key: os.environ.get(key) for key in keys}
    value = str(int(app_id))
    os.environ["SteamAppId"] = value
    os.environ["SteamGameId"] = value
    try:
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _library_path(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else runtime_root()
    candidates = (
        base / "steam_runtime" / "steamworks" / "dist" / "win64" / "steam_api64.dll",
        base / "steamworks" / "dist" / "win64" / "steam_api64.dll",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SteamFriendsError(
        "steam_unavailable",
        f"Steam API library is missing: {candidates[0]}",
    )


def _load_library(root: Path | None = None) -> Any:
    if os.name != "nt":
        raise SteamFriendsError("steam_unavailable", "Steam Friends requires Windows")
    library_path = _library_path(root)
    directory_handle = None
    try:
        if hasattr(os, "add_dll_directory"):
            directory_handle = os.add_dll_directory(str(library_path.parent))
        return ctypes.CDLL(str(library_path))
    except OSError as exc:
        raise SteamFriendsError(
            "steam_unavailable",
            f"Steam API library could not be loaded: {exc}",
        ) from exc
    finally:
        if directory_handle is not None:
            directory_handle.close()


def _configure_signatures(dll: Any) -> None:
    try:
        dll.SteamAPI_InitSafe.argtypes = []
        dll.SteamAPI_InitSafe.restype = ctypes.c_bool
        dll.SteamAPI_Shutdown.argtypes = []
        dll.SteamAPI_Shutdown.restype = None
        dll.SteamAPI_RunCallbacks.argtypes = []
        dll.SteamAPI_RunCallbacks.restype = None
        dll.SteamAPI_SteamFriends_v017.argtypes = []
        dll.SteamAPI_SteamFriends_v017.restype = ctypes.c_void_p
        dll.SteamAPI_ISteamFriends_RequestUserInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_bool,
        ]
        dll.SteamAPI_ISteamFriends_RequestUserInformation.restype = ctypes.c_bool
        dll.SteamAPI_ISteamFriends_GetFriendPersonaName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
        ]
        dll.SteamAPI_ISteamFriends_GetFriendPersonaName.restype = ctypes.c_char_p
    except AttributeError as exc:
        raise SteamFriendsError(
            "steam_unavailable",
            f"Steam Friends exports are unavailable: {exc}",
        ) from exc


def _normalized_steam_ids(steam_ids: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in steam_ids:
        candidate = str(value).strip()
        if not candidate.isdigit():
            continue
        numeric = int(candidate)
        if numeric <= 0 or numeric > 2**64 - 1:
            continue
        canonical = str(numeric)
        if canonical not in normalized:
            normalized.append(canonical)
    return tuple(normalized)


def _persona_name(raw_value: Any) -> str:
    if raw_value is None:
        return ""
    if isinstance(raw_value, bytes):
        value = raw_value.decode("utf-8", errors="replace").strip()
    else:
        value = str(raw_value).strip()
    return "" if value.casefold() in _UNKNOWN_PERSONA_NAMES else value


def _poll_persona_names(
    dll: Any,
    friends: Any,
    steam_ids: tuple[str, ...],
    timeout_seconds: float,
    poll_interval: float,
) -> SteamPersonaResult:
    pending = list(steam_ids)
    names: dict[str, str] = {}
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    interval = max(0.01, float(poll_interval))
    while pending:
        dll.SteamAPI_RunCallbacks()
        for steam_id in tuple(pending):
            name = _persona_name(
                dll.SteamAPI_ISteamFriends_GetFriendPersonaName(
                    friends,
                    int(steam_id),
                )
            )
            if name:
                names[steam_id] = name
                pending.remove(steam_id)
        if not pending:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    return SteamPersonaResult(names, tuple(pending))


def query_steam_persona_names(
    steam_ids: Iterable[str],
    app_id: int = 1_142_710,
    root: Path | None = None,
    timeout_seconds: float = 5.0,
    poll_interval: float = 0.05,
) -> SteamPersonaResult:
    normalized_ids = _normalized_steam_ids(steam_ids)
    if not normalized_ids:
        return SteamPersonaResult({}, ())

    with _STEAM_FRIENDS_LOCK, _temporary_app_environment(app_id):
        try:
            dll = _load_library(root)
            _configure_signatures(dll)
            if not dll.SteamAPI_InitSafe():
                raise SteamFriendsError(
                    "steam_unavailable",
                    "Steam API initialization failed",
                )
        except SteamFriendsError:
            raise
        except Exception as exc:
            raise SteamFriendsError(
                "steam_unavailable",
                f"Steam API initialization failed: {exc}",
            ) from exc

        try:
            friends = dll.SteamAPI_SteamFriends_v017()
            if not friends:
                raise SteamFriendsError(
                    "steam_unavailable",
                    "Steam Friends interface is unavailable",
                )
            for steam_id in normalized_ids:
                dll.SteamAPI_ISteamFriends_RequestUserInformation(
                    friends,
                    int(steam_id),
                    True,
                )
            return _poll_persona_names(
                dll,
                friends,
                normalized_ids,
                timeout_seconds,
                poll_interval,
            )
        except SteamFriendsError:
            raise
        except Exception as exc:
            raise SteamFriendsError(
                "unexpected",
                f"Steam Friends query failed: {exc}",
            ) from exc
        finally:
            try:
                dll.SteamAPI_Shutdown()
            except Exception:
                pass
