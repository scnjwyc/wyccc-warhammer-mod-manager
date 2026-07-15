from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from pathlib import Path

from backend import APP_NAME
from backend.api import API
from backend.app_settings import default_data_dir


_instance_mutex: int | None = None


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def ensure_single_instance() -> bool:
    """Prevent two packaged managers from racing on the same load-order files."""
    if os.name != "nt":
        return True
    global _instance_mutex
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\WycccModManager")
    if not handle:
        return True
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        ctypes.windll.user32.MessageBoxW(
            None,
            "Wyccc's Mod Manager 已经在运行。",
            "WMM",
            0x40,
        )
        return False
    _instance_mutex = int(handle)
    return True


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


def run_desktop(api: API, ui_url: str) -> int:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("pywebview is required for desktop mode.") from exc

    webview.create_window(
        APP_NAME,
        ui_url,
        js_api=api,
        width=1440,
        height=900,
        min_size=(1080, 680),
        maximized=True,
        background_color="#0b0909",
    )
    webview.start(debug=False)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--dev-url", default="", help="Use a running Vite development server")
    parser.add_argument("--data-dir", default="", help="Override the application data directory")
    args = parser.parse_args()

    if not ensure_single_instance():
        return 0
    data_dir = resolve_runtime_data_dir(args.data_dir)
    configure_logging(data_dir)
    api = API(data_dir)
    static_root = project_root() / "frontend" / "dist"
    if args.dev_url:
        ui_url = args.dev_url
    else:
        index_path = static_root / "index.html"
        if not index_path.is_file():
            print("frontend/dist 不存在；请先运行 frontend/pnpm build，或使用 --dev-url。")
            return 2
        ui_url = index_path.as_uri()
    return run_desktop(api, ui_url)


if __name__ == "__main__":
    raise SystemExit(main())
