from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .constants import (
    APP_SLUG,
    APP_VERSION,
    DEFAULT_UPDATE_MANIFEST_URL,
    LEGACY_APP_SLUGS,
    WH3_APP_ID,
)
from .json_store import AtomicJsonStore
from .models import GamePaths
from .steam_paths import discover_wh3_paths


DEFAULT_LANGUAGE = "zh-CN"
SUPPORTED_LANGUAGES = frozenset({"zh-CN", "en-US", "ko-KR", "ru-RU", "ja-JP"})


def default_data_dir() -> Path:
    override = (
        os.environ.get("WYCCC_MM_DATA_DIR", "").strip()
        or os.environ.get("WYCCC_WM_DATA_DIR", "").strip()
        or os.environ.get("WYCCC_WMM_DATA_DIR", "").strip()
    )
    if override:
        return Path(override).expanduser().resolve(strict=False)
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if root:
            config_root = Path(root)
            preferred = config_root / APP_SLUG
            if not preferred.exists():
                for legacy_slug in LEGACY_APP_SLUGS:
                    legacy = config_root / legacy_slug
                    if legacy.exists():
                        return legacy
            return preferred
    config_root = Path.home() / ".config"
    preferred = config_root / APP_SLUG
    if not preferred.exists():
        for legacy_slug in LEGACY_APP_SLUGS:
            legacy = config_root / legacy_slug
            if legacy.exists():
                return legacy
    return preferred


def default_settings() -> dict[str, Any]:
    return {
        "schema_version": 7,
        "language": DEFAULT_LANGUAGE,
        "game_path": "",
        "workshop_path": "",
        "fetch_workshop_metadata": True,
        "check_outdated_mods": False,
        "ai_enabled": False,
        "ai_base_url": "https://api.openai.com/v1",
        "ai_api_key": "",
        "ai_model": "",
        "ai_temperature": 0.3,
        "custom_battle_all_units_as_lords": False,
        "enable_script_logging": False,
        "skip_intro_movies": False,
        "check_updates_automatically": True,
        "update_manifest_url": DEFAULT_UPDATE_MANIFEST_URL,
        "last_update_check_at": 0,
        "ignored_update_version": "",
        "last_seen_app_version": APP_VERSION,
        "theme": "crimson",
    }


class SettingsService:
    ALLOWED_KEYS = set(default_settings()) - {"schema_version"}

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.store = AtomicJsonStore(self.data_dir / "settings.json", default_settings)

    def get(self) -> dict[str, Any]:
        stored = self.store.load()
        try:
            stored_version = int(stored.get("schema_version") or 0)
        except (TypeError, ValueError):
            stored_version = 0
        payload = default_settings()
        payload.update(stored)
        if stored_version < 2:
            payload["fetch_workshop_metadata"] = True
        payload["schema_version"] = 7
        normalized = self._normalize(payload)
        if stored_version < 7:
            self.store.save(normalized)
        return normalized

    def get_public(self) -> dict[str, Any]:
        """Return settings safe to expose through the desktop bridge."""
        payload = self.get()
        payload["ai_api_key_configured"] = bool(payload.get("ai_api_key"))
        payload["ai_api_key"] = ""
        return payload

    def save(self, changes: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, dict):
            raise ValueError("设置必须是对象")
        current = self.get()
        clear_ai_api_key = bool(changes.get("clear_ai_api_key"))
        for key, value in changes.items():
            if key not in self.ALLOWED_KEYS:
                continue
            if key == "ai_api_key" and not str(value or "").strip() and not clear_ai_api_key:
                continue
            current[key] = value
        if clear_ai_api_key:
            current["ai_api_key"] = ""
        normalized = self._normalize(current)
        self.store.save(normalized)
        return normalized

    def detect_and_save(self) -> dict[str, Any]:
        detected = discover_wh3_paths()
        if not detected.game_path:
            raise ValueError("未能从 Steam 库自动定位《全面战争：战锤 3》")
        settings = self.save(
            {
                "game_path": detected.game_path,
                "workshop_path": detected.workshop_path,
            }
        )
        return {"settings": settings, "paths": detected.to_dict()}

    def resolve_game_paths(self) -> GamePaths:
        settings = self.get()
        game_path_value = settings["game_path"]
        workshop_path_value = settings["workshop_path"]
        if not game_path_value:
            detected = discover_wh3_paths()
            if detected.game_path:
                self.save(
                    {
                        "game_path": detected.game_path,
                        "workshop_path": detected.workshop_path,
                    }
                )
                return detected
            return GamePaths()

        game_path = Path(game_path_value)
        data_path = game_path / "data"
        workshop_path = Path(workshop_path_value) if workshop_path_value else None
        if not workshop_path_value:
            inferred = game_path.parent.parent / "workshop" / "content" / WH3_APP_ID
            if inferred.exists():
                workshop_path = inferred
        return GamePaths(
            game_path=str(game_path.resolve(strict=False)),
            data_path=str(data_path.resolve(strict=False)),
            workshop_path=str(workshop_path.resolve(strict=False)) if workshop_path else "",
            detected_by="manual",
        )

    @staticmethod
    def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
        result = default_settings()
        result.update(
            {key: value for key, value in payload.items() if key in result}
        )
        for path_key in ("game_path", "workshop_path"):
            value = str(result.get(path_key) or "").strip().strip('"')
            if value:
                candidate = Path(value).expanduser()
                if path_key == "game_path" and candidate.name.casefold() == "warhammer3.exe":
                    candidate = candidate.parent
                result[path_key] = str(candidate.resolve(strict=False))
            else:
                result[path_key] = ""
        for key in (
            "fetch_workshop_metadata",
            "check_outdated_mods",
            "ai_enabled",
            "custom_battle_all_units_as_lords",
            "enable_script_logging",
            "skip_intro_movies",
            "check_updates_automatically",
        ):
            result[key] = bool(result.get(key, default_settings()[key]))
        result["ai_base_url"] = str(result.get("ai_base_url") or "").strip().rstrip("/")
        result["ai_api_key"] = str(result.get("ai_api_key") or "").strip()
        result["ai_model"] = str(result.get("ai_model") or "").strip()
        result["update_manifest_url"] = str(result.get("update_manifest_url") or "").strip()
        result["ignored_update_version"] = str(result.get("ignored_update_version") or "").strip()
        result["last_seen_app_version"] = str(result.get("last_seen_app_version") or APP_VERSION).strip()
        try:
            result["last_update_check_at"] = max(0, int(result.get("last_update_check_at") or 0))
        except (TypeError, ValueError):
            result["last_update_check_at"] = 0
        try:
            temperature = float(result.get("ai_temperature", 0.3))
        except (TypeError, ValueError):
            temperature = 0.3
        result["ai_temperature"] = max(0.0, min(2.0, temperature))
        result["theme"] = str(result.get("theme") or "crimson")
        language = str(result.get("language") or DEFAULT_LANGUAGE).strip()
        result["language"] = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        result["schema_version"] = 7
        return result
