from __future__ import annotations

from typing import Any

from .api import API


class DesktopBridge:
    """Keep pywebview's recursive discovery outside the application's services."""

    def __init__(self, api: API):
        self._api = api

    def call(
        self,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._api.call(method, args, kwargs)
