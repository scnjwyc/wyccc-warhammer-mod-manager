from __future__ import annotations

import ctypes
import logging
import os
import re
import webbrowser
from dataclasses import dataclass


logger = logging.getLogger(__name__)

WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/en-us/microsoft-edge/webview2"
_VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")


@dataclass(frozen=True)
class WebView2RuntimeStatus:
    available: bool
    version: str = ""


def _read_runtime_versions() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    subkey = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, subkey, getattr(winreg, "KEY_WOW64_32KEY", 0)),
        (winreg.HKEY_LOCAL_MACHINE, subkey, 0),
        (winreg.HKEY_CURRENT_USER, subkey, 0),
    )
    versions: list[str] = []
    for hive, path, view_flag in locations:
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view_flag) as key:
                value, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        version = str(value or "").strip()
        if _VERSION_RE.fullmatch(version) and any(int(part) for part in version.split(".")):
            versions.append(version)
    return versions


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def get_webview2_runtime_status() -> WebView2RuntimeStatus:
    versions = _read_runtime_versions()
    if versions:
        return WebView2RuntimeStatus(True, max(versions, key=_version_key))
    if os.name != "nt":
        return WebView2RuntimeStatus(True, "not-applicable")
    return WebView2RuntimeStatus(False, "")


def _show_missing_runtime_prompt() -> None:
    if os.name != "nt":
        return
    try:
        message = (
            "启动 Wyccc's Mod Manager 需要安装 Microsoft Edge WebView2 Runtime。\n\n"
            "是否现在打开 Microsoft 官方下载页？\n"
            f"{WEBVIEW2_DOWNLOAD_URL}"
        )
        result = ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "Wyccc's Mod Manager",
            0x00000004 | 0x00000010 | 0x00040000,
        )
        if result == 6:
            webbrowser.open(WEBVIEW2_DOWNLOAD_URL)
    except Exception:
        logger.exception("Unable to show the WebView2 Runtime download prompt")


def show_startup_error(message: str) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            str(message),
            "Wyccc's Mod Manager",
            0x00000010 | 0x00040000,
        )
    except Exception:
        logger.exception("Unable to show the desktop startup error")


def ensure_webview2_runtime() -> bool:
    status = get_webview2_runtime_status()
    if status.available:
        logger.info("WebView2 Runtime available: %s", status.version)
        return True
    logger.error("WebView2 Runtime is missing")
    _show_missing_runtime_prompt()
    return False
