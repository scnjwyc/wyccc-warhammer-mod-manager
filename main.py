from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import threading
from pathlib import Path

from backend import APP_NAME
from backend.api import API
from backend.app_settings import default_data_dir
from backend.launcher import is_game_running
from backend.runtime import RuntimeCoordinator, localized_idle_url
from backend.webview_runtime import ensure_webview2_runtime, show_startup_error


_instance_mutex: int | None = None
_instance_activation_event: int | None = None
_MUTEX_NAME = "Local\\WycccModManager"
_ACTIVATION_EVENT_NAME = "Local\\WycccModManagerActivate"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _create_instance_mutex() -> tuple[int | None, bool]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return None, False
    return int(handle), kernel32.GetLastError() == 183


def _create_activation_event() -> int | None:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateEventW.restype = ctypes.c_void_p
    handle = kernel32.CreateEventW(None, False, False, _ACTIVATION_EVENT_NAME)
    return int(handle) if handle else None


def _close_handle(handle: int | None) -> None:
    if os.name == "nt" and handle:
        ctypes.windll.kernel32.CloseHandle(handle)


def _signal_existing_instance() -> bool:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenEventW.restype = ctypes.c_void_p
    handle = kernel32.OpenEventW(0x0002, False, _ACTIVATION_EVENT_NAME)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


def ensure_single_instance() -> bool:
    """Keep one manager instance and activate it when a second launch is attempted."""
    if os.name != "nt":
        return True
    global _instance_mutex, _instance_activation_event
    handle, already_exists = _create_instance_mutex()
    if already_exists:
        _close_handle(handle)
        _signal_existing_instance()
        return False
    _instance_mutex = handle
    _instance_activation_event = _create_activation_event()
    return True


def _activate_window(window: object) -> None:
    for method_name in ("restore", "show"):
        method = getattr(window, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                logging.getLogger(__name__).exception("Unable to %s WMM window", method_name)
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, APP_NAME)
    if hwnd:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)


def _activation_loop(window: object, stop_event: threading.Event) -> None:
    if os.name != "nt" or not _instance_activation_event:
        return
    kernel32 = ctypes.windll.kernel32
    while not stop_event.is_set():
        if kernel32.WaitForSingleObject(_instance_activation_event, 500) == 0:
            _activate_window(window)


def close_instance_handles() -> None:
    global _instance_mutex, _instance_activation_event
    _close_handle(_instance_activation_event)
    _close_handle(_instance_mutex)
    _instance_activation_event = None
    _instance_mutex = None


def resolve_runtime_data_dir(override: str = "") -> Path:
    if override:
        return Path(override).expanduser().resolve(strict=False)
    has_data_override = any(
        os.environ.get(name)
        for name in (
            "WYCCC_MM_DATA_DIR",
            "WYCCC_WM_DATA_DIR",
            "WYCCC_WMM_DATA_DIR",
        )
    )
    if getattr(sys, "frozen", False) and not has_data_override:
        portable = Path(sys.executable).resolve().parent / "data"
        try:
            portable.mkdir(parents=True, exist_ok=True)
            return portable
        except OSError:
            pass
    return default_data_dir()


def configure_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    ]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )


def run_desktop(
    api: API,
    ui_url: str,
    *,
    idle_url: str = "",
    initial_game_running: bool = False,
) -> int:
    if not ensure_webview2_runtime():
        return 3
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("pywebview is required for desktop mode.") from exc

    low_consumption_url = idle_url or ui_url
    language_getter = getattr(api, "interface_language", None)
    language = language_getter() if callable(language_getter) else ""
    if not isinstance(language, str):
        language = ""
    initial_url = (
        localized_idle_url(low_consumption_url, language)
        if initial_game_running
        else ui_url
    )
    try:
        window = webview.create_window(
            APP_NAME,
            initial_url,
            js_api=api,
            width=1440,
            height=900,
            min_size=(1080, 680),
            maximized=True,
            background_color="#0b0909",
        )
    except Exception as exc:
        logging.getLogger(__name__).exception("Unable to create the desktop window")
        show_startup_error(f"Unable to create the application window:\n{exc}")
        close_instance_handles()
        return 4
    bind_window = getattr(api, "bind_window", None)
    if callable(bind_window):
        bind_window(window)
    set_game_running = getattr(api, "set_game_running", None)
    if callable(set_game_running):
        set_game_running(initial_game_running, force=True)
    coordinator = RuntimeCoordinator(
        window,
        api,
        ui_url,
        low_consumption_url,
        initial_running=initial_game_running,
        detector=(
            api.detect_game_running
            if callable(getattr(api, "detect_game_running", None))
            else is_game_running
        ),
    )
    bind_low_consumption_exit = getattr(api, "bind_low_consumption_exit", None)
    if callable(bind_low_consumption_exit):
        bind_low_consumption_exit(coordinator.exit_low_consumption_mode)
    activation_stop = threading.Event()

    def on_ready() -> None:
        threading.Thread(
            target=_activation_loop,
            args=(window, activation_stop),
            name="wmm-instance-activation",
            daemon=True,
        ).start()
        coordinator.start()

    try:
        webview.start(on_ready, debug=False)
    except Exception as exc:
        logging.getLogger(__name__).exception("Desktop runtime stopped during startup")
        show_startup_error(f"Unable to start the application window:\n{exc}")
        return 4
    finally:
        activation_stop.set()
        coordinator.stop()
        close_api = getattr(api, "close", None)
        if callable(close_api):
            close_api()
        close_instance_handles()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--dev-url", default="", help="Use a running Vite development server")
    parser.add_argument("--data-dir", default="", help="Override the application data directory")
    parser.add_argument(
        "--steam-friends-worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.steam_friends_worker:
        from backend.steam_friends import run_steam_friends_worker

        return run_steam_friends_worker()
    if not ensure_single_instance():
        return 0
    data_dir = resolve_runtime_data_dir(args.data_dir)
    configure_logging(data_dir)
    api = API(data_dir)
    static_root = project_root() / "frontend" / "dist"
    if args.dev_url:
        ui_url = args.dev_url
        idle_url = f"{args.dev_url.rstrip('/')}/idle.html"
    else:
        index_path = static_root / "index.html"
        idle_path = static_root / "idle.html"
        if not index_path.is_file() or not idle_path.is_file():
            print("frontend/dist 不存在；请先运行 frontend/pnpm build，或使用 --dev-url。")
            return 2
        ui_url = index_path.as_uri()
        idle_url = idle_path.as_uri()
    return run_desktop(
        api,
        ui_url,
        idle_url=idle_url,
        initial_game_running=api.detect_game_running(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
