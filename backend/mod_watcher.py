from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Protocol

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - exercised only by incomplete dev environments
    FileSystemEvent = object  # type: ignore[assignment,misc]
    FileSystemEventHandler = object  # type: ignore[assignment,misc]
    Observer = None  # type: ignore[assignment,misc]


logger = logging.getLogger(__name__)


class _ObserverLike(Protocol):
    def schedule(self, handler: object, path: str, recursive: bool = False) -> object: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...


class DebouncedCallback:
    """Coalesce a burst of filesystem events without polling the filesystem."""

    def __init__(self, callback: Callable[[], None], delay_seconds: float = 0.8):
        self.callback = callback
        self.delay_seconds = max(0.01, float(delay_seconds))
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._closed = False

    def trigger(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._timer is not None:
                self._timer.cancel()
            timer = threading.Timer(self.delay_seconds, self._fire)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def _fire(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._timer = None
        try:
            self.callback()
        except Exception:
            logger.exception("MOD filesystem change callback failed")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()


class ModEventHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None], *, workshop: bool):
        super().__init__()
        self.callback = callback
        self.workshop = workshop

    def on_any_event(self, event: FileSystemEvent) -> None:
        if str(getattr(event, "event_type", "")) in {"opened", "closed_no_write"}:
            return
        candidates = [
            str(getattr(event, "src_path", "") or ""),
            str(getattr(event, "dest_path", "") or ""),
        ]
        is_directory = bool(getattr(event, "is_directory", False))
        if any(self._is_relevant(path, is_directory) for path in candidates if path):
            self.callback()

    def _is_relevant(self, raw_path: str, is_directory: bool) -> bool:
        path = Path(raw_path)
        if not is_directory and path.suffix.casefold() == ".pack":
            return True
        if not self.workshop or not is_directory:
            return False
        return path.name.isdigit() or path.parent.name.isdigit()


class ModChangeMonitor:
    """Watch MOD roots through native OS notifications with debounced delivery."""

    def __init__(
        self,
        callback: Callable[[], None],
        *,
        observer_factory: Callable[[], _ObserverLike] | None = None,
        debounce_seconds: float = 0.8,
    ):
        self._callback = callback
        self._observer_factory = observer_factory or Observer
        self._debounce_seconds = debounce_seconds
        self._lock = threading.Lock()
        self._observer: _ObserverLike | None = None
        self._debouncer: DebouncedCallback | None = None
        self._signature: tuple[str, str] = ("", "")
        self._active = False

    @property
    def available(self) -> bool:
        return self._observer_factory is not None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self, data_path: str, workshop_path: str) -> bool:
        data_root = self._existing_directory(data_path)
        workshop_root = self._existing_directory(workshop_path)
        signature = (
            str(data_root.resolve(strict=False)) if data_root else "",
            str(workshop_root.resolve(strict=False)) if workshop_root else "",
        )
        with self._lock:
            if self._active and signature == self._signature:
                return True
        self.stop()
        if not self.available or not any(signature):
            return False

        observer = self._observer_factory()
        debouncer = DebouncedCallback(self._callback, self._debounce_seconds)
        try:
            if data_root:
                observer.schedule(
                    ModEventHandler(debouncer.trigger, workshop=False),
                    str(data_root),
                    recursive=False,
                )
            if workshop_root:
                observer.schedule(
                    ModEventHandler(debouncer.trigger, workshop=True),
                    str(workshop_root),
                    recursive=True,
                )
            observer.start()
        except Exception:
            debouncer.close()
            try:
                observer.stop()
                observer.join(timeout=1)
            except Exception:
                pass
            logger.exception("Unable to start MOD filesystem monitor")
            return False

        with self._lock:
            self._observer = observer
            self._debouncer = debouncer
            self._signature = signature
            self._active = True
        return True

    def stop(self) -> None:
        with self._lock:
            observer = self._observer
            debouncer = self._debouncer
            self._observer = None
            self._debouncer = None
            self._signature = ("", "")
            self._active = False
        if debouncer is not None:
            debouncer.close()
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=2)
            except Exception:
                logger.exception("Unable to stop MOD filesystem monitor")

    @staticmethod
    def _existing_directory(value: str) -> Path | None:
        if not str(value or "").strip():
            return None
        path = Path(value)
        return path if path.is_dir() else None
