from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


class AtomicJsonStore:
    """Small versioned JSON store for settings and rebuildable caches."""

    def __init__(self, path: Path, default_factory: Callable[[], dict[str, Any]]):
        self.path = Path(path)
        self.default_factory = default_factory
        self._lock = threading.RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return deepcopy(self.default_factory())
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON root must be an object")
                return payload
            except (OSError, ValueError, json.JSONDecodeError):
                timestamp = int(time.time())
                corrupt_path = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}")
                try:
                    self.path.replace(corrupt_path)
                except OSError:
                    pass
                return deepcopy(self.default_factory())

    def save(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            with temp_path.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            payload.update(changes)
            self.save(payload)
            return payload
