from __future__ import annotations

import locale
import os
from pathlib import Path
from typing import Any

from .constants import (
    APP_SLUG,
    APP_VERSION,
    LEGACY_APP_SLUGS,
)
from .games import DEFAULT_GAME_ID, GameDefinition, game_definitions, get_game_definition
from .game_data_settings import (
    normalize_single_entity_unit_mode,
    normalize_unit_recruitment_capacity_multiplier,
    normalize_unit_scale_multiplier,
)
from .json_store import AtomicJsonStore
from .models import GamePaths
from .steam_paths import discover_game_paths


DEFAULT_LANGUAGE = "en-US"
LEGACY_DEFAULT_LANGUAGE = "zh-CN"
SUPPORTED_LANGUAGES = frozenset({"zh-CN", "en-US", "ko-KR", "ru-RU", "ja-JP", "es-ES"})
SYSTEM_LANGUAGE_MAP = {
    "zh": "zh-CN",
    "en": "en-US",
    "ko": "ko-KR",
    "ru": "ru-RU",
    "ja": "ja-JP",
    "es": "es-ES",
}
SETTINGS_SCHEMA_VERSION = 16

DEFAULT_KEYBOARD_SHORTCUTS = {
    "open-workshop": "Shift+W",
    "open-rpfm": "Shift+R",
    "toggle-active": "Shift+E",
    "launch-game": "Shift+Enter",
}
_SHORTCUT_MODIFIERS = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "meta": "Meta",
    "win": "Meta",
    "cmd": "Meta",
    "command": "Meta",
}
_SHORTCUT_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift", "Meta")
_SHORTCUT_KEY_ALIASES = {
    "esc": "Escape",
    "escape": "Escape",
    "return": "Enter",
    "enter": "Enter",
    "space": "Space",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
}


def _normalize_shortcut(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""
    modifiers: set[str] = set()
    base = ""
    for part in raw.split("+"):
        token = part.strip()
        if not token:
            return ""
        folded = token.casefold()
        modifier = _SHORTCUT_MODIFIERS.get(folded)
        if modifier:
            if modifier in modifiers:
                return ""
            modifiers.add(modifier)
            continue
        if base:
            return ""
        base = _SHORTCUT_KEY_ALIASES.get(folded, token.upper() if len(token) == 1 else token[:1].upper() + token[1:].lower())
    if not base:
        return ""
    ordered = [modifier for modifier in _SHORTCUT_MODIFIER_ORDER if modifier in modifiers]
    return "+".join([*ordered, base])


def _normalize_keyboard_shortcuts(value: Any) -> dict[str, str]:
    raw = value if isinstance(value, dict) else {}
    result = {}
    for action, default in DEFAULT_KEYBOARD_SHORTCUTS.items():
        candidate = _normalize_shortcut(raw.get(action))
        result[action] = candidate or default
    return result


def _normalize_workshop_page_open_counts(value: Any) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    normalized: dict[str, int] = {}
    for target in ("browser", "client"):
        try:
            normalized[target] = max(0, min(1_000_000, int(raw.get(target) or 0)))
        except (TypeError, ValueError):
            normalized[target] = 0
    return normalized


def _system_locale_name() -> str:
    """Return the Windows display locale, with a portable development fallback."""
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        language_id = int(kernel32.GetUserDefaultUILanguage())
        if language_id:
            buffer = ctypes.create_unicode_buffer(85)
            if int(kernel32.LCIDToLocaleName(language_id, buffer, len(buffer), 0)) > 0:
                return buffer.value

        buffer = ctypes.create_unicode_buffer(85)
        if int(kernel32.GetUserDefaultLocaleName(buffer, len(buffer))) > 0:
            return buffer.value

    language, _encoding = locale.getlocale()
    return str(language or "")


def detect_system_language() -> str:
    """Map the current system locale to a built-in interface language."""
    try:
        locale_name = _system_locale_name()
    except Exception:
        return DEFAULT_LANGUAGE
    normalized = str(locale_name or "").strip().replace("_", "-").split(".", 1)[0]
    language_family = normalized.split("-", 1)[0].split("@", 1)[0].casefold()
    return SYSTEM_LANGUAGE_MAP.get(language_family, DEFAULT_LANGUAGE)


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


def _default_game_installations() -> dict[str, dict[str, str]]:
    return {
        definition.id: {"game_path": "", "workshop_path": ""}
        for definition in game_definitions()
    }


def default_settings(language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "language": language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE,
        "selected_game": DEFAULT_GAME_ID,
        "game_installations": _default_game_installations(),
        "fetch_workshop_metadata": True,
        "live_mod_detection": True,
        "keyboard_shortcuts_enabled": True,
        "keyboard_shortcuts": dict(DEFAULT_KEYBOARD_SHORTCUTS),
        "check_outdated_mods": False,
        "search_highlight_mode": False,
        "active_search_highlight_mode": False,
        "inactive_search_highlight_mode": False,
        "show_hidden_mods": False,
        "ai_enabled": False,
        "ai_base_url": "https://api.openai.com/v1",
        "ai_api_key": "",
        "ai_model": "",
        "ai_temperature": 0.3,
        "custom_battle_all_units_as_lords": False,
        "enable_script_logging": False,
        "skip_intro_movies": False,
        "unit_model_multiplier": 1,
        "unit_recruitment_capacity_multiplier": 1,
        "single_entity_unit_mode": "scale",
        "scale_lord_hero_health": False,
        "disable_unit_friendly_fire": False,
        "disable_spell_friendly_fire": False,
        "check_updates_automatically": True,
        "workshop_page_open_counts": {"browser": 0, "client": 0},
        "last_update_check_at": 0,
        "ignored_update_version": "",
        "last_seen_app_version": APP_VERSION,
        "theme": "crimson",
    }


class SettingsService:
    ALLOWED_KEYS = set(default_settings()) - {"schema_version"}

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or default_data_dir())
        settings_path = self.data_dir / "settings.json"
        initial_language = (
            detect_system_language() if not settings_path.exists() else DEFAULT_LANGUAGE
        )
        self.store = AtomicJsonStore(
            settings_path,
            lambda: default_settings(initial_language),
        )

    def get(self) -> dict[str, Any]:
        is_first_launch = not self.store.path.exists()
        stored = self.store.load()
        language_was_missing = "language" not in stored
        search_highlight_modes_missing = any(
            key not in stored
            for key in ("active_search_highlight_mode", "inactive_search_highlight_mode")
        )
        try:
            stored_version = int(stored.get("schema_version") or 0)
        except (TypeError, ValueError):
            stored_version = 0
        payload = default_settings()
        payload.update(stored)
        if search_highlight_modes_missing:
            legacy_highlight_mode = bool(payload.get("search_highlight_mode"))
            for key in ("active_search_highlight_mode", "inactive_search_highlight_mode"):
                if key not in stored:
                    payload[key] = legacy_highlight_mode
        if stored_version < SETTINGS_SCHEMA_VERSION:
            payload["game_installations"] = self._migrate_legacy_game_installations(
                stored,
                payload.get("game_installations"),
            )
        if not is_first_launch and language_was_missing:
            payload["language"] = LEGACY_DEFAULT_LANGUAGE
        if stored_version < 2:
            payload["fetch_workshop_metadata"] = True
        payload["schema_version"] = SETTINGS_SCHEMA_VERSION
        normalized = self._normalize(payload)
        if (
            is_first_launch
            or stored_version < SETTINGS_SCHEMA_VERSION
            or language_was_missing
            or search_highlight_modes_missing
        ):
            self.store.save(normalized)
        return normalized

    def get_public(self) -> dict[str, Any]:
        """Return settings safe to expose through the desktop bridge."""
        payload = self.get()
        payload["ai_api_key_configured"] = bool(payload.get("ai_api_key"))
        payload["ai_api_key"] = ""
        return payload

    def normalize_changes(self, changes: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, dict):
            raise ValueError("设置必须是对象")
        current = self.get()
        clear_ai_api_key = bool(changes.get("clear_ai_api_key"))
        for key, value in changes.items():
            if key in {"game_path", "workshop_path"}:
                selected = get_game_definition(current.get("selected_game")).id
                installations = current.setdefault("game_installations", _default_game_installations())
                installation = installations.setdefault(
                    selected,
                    {"game_path": "", "workshop_path": ""},
                )
                installation[key] = value
                continue
            if key not in self.ALLOWED_KEYS:
                continue
            if key == "ai_api_key" and not str(value or "").strip() and not clear_ai_api_key:
                continue
            current[key] = value
        if clear_ai_api_key:
            current["ai_api_key"] = ""
        return self._normalize(current)

    def save(self, changes: dict[str, Any]) -> dict[str, Any]:
        normalized = self.normalize_changes(changes)
        self.store.save(normalized)
        return normalized

    def selected_game_definition(self) -> GameDefinition:
        return get_game_definition(self.get().get("selected_game"))

    def detect_and_save(self, game_id: str = "") -> dict[str, Any]:
        selected = get_game_definition(game_id or self.get().get("selected_game")).id
        settings = self.save({"selected_game": selected})
        detected = discover_game_paths(selected)
        if detected.game_path:
            installations = {
                key: dict(value)
                for key, value in settings["game_installations"].items()
                if isinstance(value, dict)
            }
            installations[selected] = {
                "game_path": detected.game_path,
                "workshop_path": detected.workshop_path,
            }
            settings = self.save(
                {
                    "selected_game": selected,
                    "game_installations": installations,
                }
            )
        resolved = detected if detected.game_path else self.resolve_game_paths()
        return {
            "found": bool(detected.game_path),
            "settings": settings,
            "paths": resolved.to_dict(),
        }

    def resolve_game_paths(self) -> GamePaths:
        settings = self.get()
        definition = get_game_definition(settings.get("selected_game"))
        raw_installations = settings.get("game_installations")
        installations = raw_installations if isinstance(raw_installations, dict) else {}
        installation = installations.get(definition.id)
        installation = installation if isinstance(installation, dict) else {}
        game_path_value = str(installation.get("game_path") or "")
        workshop_path_value = str(installation.get("workshop_path") or "")
        if not game_path_value:
            detected = discover_game_paths(definition.id)
            if detected.game_path:
                updated_installations = {
                    key: dict(value)
                    for key, value in installations.items()
                    if isinstance(value, dict)
                }
                updated_installations[definition.id] = {
                    "game_path": detected.game_path,
                    "workshop_path": detected.workshop_path,
                }
                self.save(
                    {
                        "selected_game": definition.id,
                        "game_installations": updated_installations,
                    }
                )
                return detected
            return GamePaths(game_id=definition.id)

        game_path = Path(game_path_value)
        data_path = game_path / "data"
        workshop_path = Path(workshop_path_value) if workshop_path_value else None
        if not workshop_path_value:
            inferred = game_path.parent.parent / "workshop" / "content" / definition.app_id
            if inferred.exists():
                workshop_path = inferred
        return GamePaths(
            game_id=definition.id,
            game_path=str(game_path.resolve(strict=False)),
            data_path=str(data_path.resolve(strict=False)),
            workshop_path=str(workshop_path.resolve(strict=False)) if workshop_path else "",
            detected_by="manual",
        )

    @staticmethod
    def _migrate_legacy_game_installations(
        stored: dict[str, Any],
        default_installations: Any,
    ) -> dict[str, dict[str, Any]]:
        result = _default_game_installations()
        if isinstance(default_installations, dict):
            for definition in game_definitions():
                candidate = default_installations.get(definition.id)
                if isinstance(candidate, dict):
                    result[definition.id].update(candidate)
        result[DEFAULT_GAME_ID].update(
            {
                "game_path": str(stored.get("game_path") or ""),
                "workshop_path": str(stored.get("workshop_path") or ""),
            }
        )
        return result

    @staticmethod
    def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
        result = default_settings()
        result.update(
            {key: value for key, value in payload.items() if key in result}
        )
        selected_game = get_game_definition(result.get("selected_game")).id
        raw_installations = result.get("game_installations")
        normalized_installations: dict[str, dict[str, str]] = {}
        for definition in game_definitions():
            raw_installation = (
                raw_installations.get(definition.id, {})
                if isinstance(raw_installations, dict)
                else {}
            )
            raw_installation = raw_installation if isinstance(raw_installation, dict) else {}
            normalized: dict[str, str] = {}
            for path_key in ("game_path", "workshop_path"):
                value = str(raw_installation.get(path_key) or "").strip().strip('"')
                if value:
                    candidate = Path(value).expanduser()
                    if (
                        path_key == "game_path"
                        and candidate.name.casefold() == definition.executable_name.casefold()
                    ):
                        candidate = candidate.parent
                    normalized[path_key] = str(candidate.resolve(strict=False))
                else:
                    normalized[path_key] = ""
            normalized_installations[definition.id] = normalized
        result["selected_game"] = selected_game
        result["game_installations"] = normalized_installations
        result["keyboard_shortcuts"] = _normalize_keyboard_shortcuts(result.get("keyboard_shortcuts"))
        result["workshop_page_open_counts"] = _normalize_workshop_page_open_counts(
            result.get("workshop_page_open_counts")
        )
        for key in (
            "fetch_workshop_metadata",
            "live_mod_detection",
            "keyboard_shortcuts_enabled",
            "check_outdated_mods",
            "search_highlight_mode",
            "active_search_highlight_mode",
            "inactive_search_highlight_mode",
            "show_hidden_mods",
            "ai_enabled",
            "custom_battle_all_units_as_lords",
            "enable_script_logging",
            "skip_intro_movies",
            "scale_lord_hero_health",
            "disable_unit_friendly_fire",
            "disable_spell_friendly_fire",
            "check_updates_automatically",
        ):
            result[key] = bool(result.get(key, default_settings()[key]))
        result["ai_base_url"] = str(result.get("ai_base_url") or "").strip().rstrip("/")
        result["ai_api_key"] = str(result.get("ai_api_key") or "").strip()
        result["ai_model"] = str(result.get("ai_model") or "").strip()
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
        result["unit_model_multiplier"] = normalize_unit_scale_multiplier(
            result.get("unit_model_multiplier", 1)
        )
        result["unit_recruitment_capacity_multiplier"] = (
            normalize_unit_recruitment_capacity_multiplier(
                result.get("unit_recruitment_capacity_multiplier", 1)
            )
        )
        result["single_entity_unit_mode"] = normalize_single_entity_unit_mode(
            result.get("single_entity_unit_mode", "scale")
        )
        result["theme"] = str(result.get("theme") or "crimson")
        language = str(result.get("language") or DEFAULT_LANGUAGE).strip()
        result["language"] = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        result["schema_version"] = SETTINGS_SCHEMA_VERSION
        return result
