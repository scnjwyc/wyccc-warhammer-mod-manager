from __future__ import annotations

import ctypes
import logging
import os
import threading
import urllib.parse
from collections import defaultdict, deque
from typing import Any, Callable, Protocol

from .launcher import is_game_running


logger = logging.getLogger(__name__)


class RuntimeAPI(Protocol):
    def set_game_running(self, running: bool, *, force: bool = False) -> None: ...


def localized_idle_url(url: str, language: str) -> str:
    normalized = str(language or "").strip()
    if not normalized:
        return url
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.casefold() == "file":
        fragment = [
            (key, value)
            for key, value in urllib.parse.parse_qsl(parsed.fragment, keep_blank_values=True)
            if key != "lang"
        ]
        fragment.append(("lang", normalized))
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", urllib.parse.urlencode(fragment))
        )
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key != "lang"
    ]
    query.append(("lang", normalized))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )


def descendant_process_ids(root_pid: int, parent_by_pid: dict[int, int]) -> list[int]:
    children: dict[int, list[int]] = defaultdict(list)
    for pid, parent_pid in parent_by_pid.items():
        children[parent_pid].append(pid)
    result: list[int] = []
    pending = deque([root_pid])
    seen = {root_pid}
    while pending:
        parent = pending.popleft()
        for child in children.get(parent, []):
            if child in seen:
                continue
            seen.add(child)
            result.append(child)
            pending.append(child)
    return result


def _windows_parent_processes() -> dict[int, int]:
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
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot in (None, 0, ctypes.c_void_p(-1).value):
        return {}
    result: dict[int, int] = {}
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return result
        while True:
            result[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def trim_process_tree_working_sets(root_pid: int | None = None) -> int:
    """Release idle resident pages for WMM and its WebView2 child processes."""
    if os.name != "nt":
        return 0
    from ctypes import wintypes

    root = int(root_pid or os.getpid())
    pids = [root, *descendant_process_ids(root, _windows_parent_processes())]
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    psapi.EmptyWorkingSet.argtypes = (wintypes.HANDLE,)
    psapi.EmptyWorkingSet.restype = wintypes.BOOL
    released = 0
    for pid in pids:
        handle = kernel32.OpenProcess(0x0100 | 0x0400, False, pid)
        if not handle:
            continue
        try:
            if psapi.EmptyWorkingSet(handle):
                released += 1
        finally:
            kernel32.CloseHandle(handle)
    return released


class RuntimeCoordinator:
    """Switch between the full UI and the low-consumption page on game transitions."""

    def __init__(
        self,
        window: Any,
        api: RuntimeAPI,
        app_url: str,
        idle_url: str,
        *,
        initial_running: bool = False,
        detector: Callable[[], bool] = is_game_running,
        trim_callback: Callable[[], int] = trim_process_tree_working_sets,
        active_interval: float = 1.0,
        idle_interval: float = 5.0,
        trim_delay: float = 1.5,
    ):
        self.window = window
        self.api = api
        self.app_url = app_url
        self.idle_url = idle_url
        self.detector = detector
        self.trim_callback = trim_callback
        self.active_interval = max(0.1, active_interval)
        self.idle_interval = max(0.5, idle_interval)
        self.trim_delay = max(0.0, trim_delay)
        self._running = bool(initial_running)
        self._manual_exit_for_current_session = False
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.api.set_game_running(self._running, force=True)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="wmm-runtime-coordinator",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None

    def exit_low_consumption_mode(self) -> bool:
        with self._state_lock:
            if not self._running:
                return False
            if self._manual_exit_for_current_session:
                return True
            self._manual_exit_for_current_session = True
        try:
            self.window.load_url(self.app_url)
        except Exception:
            with self._state_lock:
                self._manual_exit_for_current_session = False
            logger.exception("Unable to exit WMM low-consumption mode")
            return False
        return True

    def _run(self) -> None:
        if self._running:
            self._trim_after_idle_load()
        while True:
            with self._state_lock:
                interval = (
                    self.idle_interval
                    if self._running and not self._manual_exit_for_current_session
                    else self.active_interval
                )
            if self._stop.wait(interval):
                break
            try:
                running = bool(self.detector())
            except Exception:
                logger.exception("Game process detection failed")
                continue
            with self._state_lock:
                current_running = self._running
            if running == current_running:
                continue
            self._transition(running)

    def _transition(self, running: bool) -> None:
        with self._state_lock:
            manually_restored = self._manual_exit_for_current_session
            self._running = bool(running)
            if not self._running:
                self._manual_exit_for_current_session = False
        self.api.set_game_running(self._running, force=True)
        if not self._running and manually_restored:
            return
        target = (
            localized_idle_url(self.idle_url, self._interface_language())
            if self._running
            else self.app_url
        )
        try:
            self.window.load_url(target)
        except Exception:
            logger.exception("Unable to switch WMM runtime page")
            return
        if self._running:
            self._trim_after_idle_load()

    def _trim_after_idle_load(self) -> None:
        if self._stop.wait(self.trim_delay):
            return
        try:
            released = self.trim_callback()
            logger.info("Low-consumption mode trimmed %s process working sets", released)
        except Exception:
            logger.exception("Unable to trim low-consumption working sets")

    def _interface_language(self) -> str:
        getter = getattr(self.api, "interface_language", None)
        if not callable(getter):
            return ""
        try:
            value = getter()
        except Exception:
            return ""
        return value if isinstance(value, str) else ""
