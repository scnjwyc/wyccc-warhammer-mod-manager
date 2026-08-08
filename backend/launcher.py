from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

from .constants import WH3_EXECUTABLE, WH3_PROCESS_NAME


def _windows_process_entries() -> list[tuple[int, str]]:
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot in (None, 0, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    entries: list[tuple[int, str]] = []
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return entries
        while True:
            entries.append((int(entry.th32ProcessID), str(entry.szExeFile)))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return entries


def _windows_executable_path(process_id: int) -> str:
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, int(process_id))
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def _windows_process_has_visible_window(process_id: int) -> bool:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = False
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit_window(window: int, _parameter: int) -> bool:
        nonlocal found
        if not user32.IsWindowVisible(window) or user32.GetWindowTextLengthW(window) <= 0:
            return True
        owner_process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner_process_id))
        if int(owner_process_id.value) != int(process_id):
            return True
        found = True
        return False

    user32.EnumWindows(visit_window, 0)
    return found


def _normalized_executable_path(path: str | Path) -> str:
    value = os.fspath(path).strip().strip('"')
    return os.path.normcase(os.path.abspath(value)) if value else ""


def _matching_game_process_ids(
    expected_executable: str | Path = "",
    *,
    process_name: str = WH3_PROCESS_NAME,
) -> list[int]:
    expected_process_name = str(process_name or WH3_PROCESS_NAME).casefold()
    if os.name == "nt":
        try:
            matches = [
                process_id
                for process_id, process_name in _windows_process_entries()
                if process_name.casefold() == expected_process_name
            ]
            if not matches:
                return []
            configured_path = _normalized_executable_path(expected_executable)
            if not configured_path:
                return matches
            verified_matches: list[int] = []
            for process_id in matches:
                process_path = _windows_executable_path(process_id)
                if process_path:
                    if _normalized_executable_path(process_path) == configured_path:
                        verified_matches.append(process_id)
                    continue
                if _windows_process_has_visible_window(process_id):
                    verified_matches.append(process_id)
            return verified_matches
        except OSError:
            return []
    try:
        completed = subprocess.run(
            ["pgrep", "-f", str(process_name or WH3_PROCESS_NAME)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if completed.returncode != 0:
            return []
        return [
            int(value)
            for value in completed.stdout.splitlines()
            if value.strip().isdigit()
        ]
    except (OSError, subprocess.SubprocessError):
        return []


def is_game_running(
    expected_executable: str | Path = "",
    *,
    process_name: str = WH3_PROCESS_NAME,
) -> bool:
    return bool(
        _matching_game_process_ids(
            expected_executable,
            process_name=process_name,
        )
    )


def _windows_terminate_process(process_id: int) -> None:
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(0x0001 | 0x00100000, False, int(process_id))
    if not handle:
        raise OSError(ctypes.get_last_error(), f"Unable to open game process {process_id}")
    try:
        if not kernel32.TerminateProcess(handle, 1):
            raise OSError(
                ctypes.get_last_error(),
                f"Unable to terminate game process {process_id}",
            )
        wait_result = kernel32.WaitForSingleObject(handle, 5_000)
        if wait_result == 0x00000102:
            raise OSError(f"Timed out waiting for game process {process_id} to exit")
        if wait_result == 0xFFFFFFFF:
            raise OSError(ctypes.get_last_error(), "WaitForSingleObject failed")
    finally:
        kernel32.CloseHandle(handle)


def terminate_game(
    expected_executable: str | Path = "",
    *,
    process_name: str = WH3_PROCESS_NAME,
) -> dict[str, list[int]]:
    """Force-stop only the game process matched by the active game configuration."""
    process_ids = _matching_game_process_ids(
        expected_executable,
        process_name=process_name,
    )
    if os.name == "nt":
        for process_id in process_ids:
            _windows_terminate_process(process_id)
    else:
        for process_id in process_ids:
            os.kill(process_id, 15)
    return {"process_ids": process_ids}


def launch_game(
    game_path: str,
    mod_list_path: str,
    save_name: str = "",
    *,
    executable_name: str = WH3_EXECUTABLE,
    process_name: str = WH3_PROCESS_NAME,
    app_id: str = "",
    launch_executable_name: str = "",
    uses_mod_list: bool = True,
) -> dict[str, int | str | list[str]]:
    game_root = Path(game_path)
    executable = game_root / str(executable_name or WH3_EXECUTABLE)
    if not executable.is_file():
        raise ValueError(f"找不到游戏可执行文件：{executable}")
    launch_executable = (
        game_root / Path(launch_executable_name)
        if launch_executable_name
        else executable
    )
    if not launch_executable.is_file():
        raise ValueError(f"找不到游戏启动器：{launch_executable}")
    if uses_mod_list and not Path(mod_list_path).is_file():
        raise ValueError(f"找不到启动清单：{mod_list_path}")
    if is_game_running(executable, process_name=process_name):
        raise ValueError(f"{executable.name} 已经在运行")

    normalized_save_name = str(save_name or "").strip()
    if normalized_save_name and (
        Path(normalized_save_name).name != normalized_save_name
        or '"' in normalized_save_name
    ):
        raise ValueError("存档名称无效")
    arguments: list[str] = []
    if normalized_save_name:
        arguments.extend(
            ["game_startup_mode", "campaign_load", normalized_save_name, ";"]
        )
    if uses_mod_list:
        arguments.append(f"{Path(mod_list_path).name};")
    argument = " ".join(
        f'"{value}"' if " " in value else value for value in arguments
    )
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    environment = os.environ.copy()
    normalized_app_id = str(app_id or "").strip()
    if normalized_app_id.isdigit():
        environment["SteamAppId"] = normalized_app_id
        environment["SteamGameId"] = normalized_app_id
    process = subprocess.Popen(
        [str(launch_executable), *arguments],
        cwd=str(game_root),
        close_fds=True,
        creationflags=creationflags,
        env=environment,
    )
    return {
        "pid": process.pid,
        "argument": argument,
        "arguments": arguments,
        "executable": str(launch_executable),
    }
