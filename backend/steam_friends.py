from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
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
_WORKER_FLAG = "--steam-friends-worker"
_WORKER_RESULT_PREFIX = "WMM_STEAM_FRIENDS_RESULT="


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


def query_steam_persona_names_isolated(
    steam_ids: Iterable[str],
    app_id: int = 1_142_710,
    root: Path | None = None,
    timeout_seconds: float = 5.0,
    poll_interval: float = 0.05,
) -> SteamPersonaResult:
    normalized_ids = _normalized_steam_ids(steam_ids)
    if not normalized_ids:
        return SteamPersonaResult({}, ())

    if getattr(sys, "frozen", False):
        command = [sys.executable, _WORKER_FLAG]
    else:
        command = [
            sys.executable,
            str(runtime_root() / "main.py"),
            _WORKER_FLAG,
        ]
    request = {
        "steam_ids": list(normalized_ids),
        "app_id": int(app_id),
        "root": str(Path(root).resolve(strict=False)) if root is not None else "",
        "timeout_seconds": float(timeout_seconds),
        "poll_interval": float(poll_interval),
    }
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(5.0, float(timeout_seconds) + 5.0),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise SteamFriendsError(
            "steam_unavailable",
            f"Steam Friends worker could not run: {exc}",
        ) from exc

    result_line = next(
        (
            line[len(_WORKER_RESULT_PREFIX) :]
            for line in reversed(completed.stdout.splitlines())
            if line.startswith(_WORKER_RESULT_PREFIX)
        ),
        "",
    )
    if not result_line:
        detail = (completed.stderr or completed.stdout).strip()[-800:]
        suffix = f": {detail}" if detail else ""
        raise SteamFriendsError(
            "steam_unavailable",
            f"Steam Friends worker returned no result (exit {completed.returncode}){suffix}",
        )
    try:
        payload = json.loads(result_line)
    except json.JSONDecodeError as exc:
        raise SteamFriendsError(
            "steam_unavailable",
            "Steam Friends worker returned invalid JSON",
        ) from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        code = str(payload.get("code") or "steam_unavailable") if isinstance(payload, dict) else ""
        message = str(payload.get("error") or "") if isinstance(payload, dict) else ""
        raise SteamFriendsError(code or "steam_unavailable", message or "Steam Friends worker failed")

    names = payload.get("names")
    unresolved = payload.get("unresolved")
    if not isinstance(names, dict) or not isinstance(unresolved, list):
        raise SteamFriendsError(
            "steam_unavailable",
            "Steam Friends worker returned invalid data",
        )
    normalized_names = {
        str(steam_id): str(name)
        for steam_id, name in names.items()
        if str(steam_id).isdigit() and str(name).strip()
    }
    normalized_unresolved = tuple(
        str(steam_id) for steam_id in unresolved if str(steam_id).isdigit()
    )
    return SteamPersonaResult(normalized_names, normalized_unresolved)


def run_steam_friends_worker(
    input_stream: Any | None = None,
    output_stream: Any | None = None,
) -> int:
    source = input_stream if input_stream is not None else sys.stdin
    target = output_stream if output_stream is not None else sys.stdout
    try:
        source_buffer = getattr(source, "buffer", None) if input_stream is None else None
        request_text = (
            source_buffer.read().decode("utf-8")
            if source_buffer is not None
            else source.read()
        )
        request = json.loads(request_text)
        if not isinstance(request, dict) or not isinstance(request.get("steam_ids"), list):
            raise ValueError("Steam Friends worker request is invalid")
        root_value = str(request.get("root") or "").strip()
        result = query_steam_persona_names(
            request["steam_ids"],
            app_id=int(request.get("app_id") or 1_142_710),
            root=Path(root_value) if root_value else None,
            timeout_seconds=float(request.get("timeout_seconds") or 5.0),
            poll_interval=float(request.get("poll_interval") or 0.05),
        )
        payload = {
            "ok": True,
            "names": result.names,
            "unresolved": list(result.unresolved),
        }
    except SteamFriendsError as exc:
        payload = {"ok": False, "code": exc.code, "error": str(exc)}
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "ok": False,
            "code": "steam_unavailable",
            "error": str(exc) or "Steam Friends worker request is invalid",
        }
    result = (
        f"{_WORKER_RESULT_PREFIX}"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n"
    )
    target_buffer = getattr(target, "buffer", None) if output_stream is None else None
    if target_buffer is not None:
        target_buffer.write(result.encode("utf-8"))
        target_buffer.flush()
    else:
        target.write(result)
        target.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(
        run_steam_friends_worker()
        if _WORKER_FLAG in sys.argv[1:]
        else 2
    )
