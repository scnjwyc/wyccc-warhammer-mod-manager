from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .games import DEFAULT_GAME_ID, GameDefinition, get_game_definition


@dataclass(frozen=True)
class GamePaths:
    game_id: str = DEFAULT_GAME_ID
    game_path: str = ""
    data_path: str = ""
    workshop_path: str = ""
    steam_root: str = ""
    steam_library: str = ""
    detected_by: str = ""

    @property
    def game_definition(self) -> GameDefinition:
        return get_game_definition(self.game_id)

    @property
    def executable_path(self) -> str:
        if not self.game_path:
            return ""
        return str(Path(self.game_path) / self.game_definition.executable_name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModAsset:
    id: str
    pack_name: str
    display_name: str
    path: str
    directory: str
    source: str
    workshop_id: str = ""
    author: str = ""
    creator_id: str = ""
    description: str = ""
    preview_path: str = ""
    preview_url: str = ""
    workshop_url: str = ""
    pack_type: str = "unknown"
    updated_at: int = 0
    created_at: int = 0
    subscribed_at: int = 0
    is_symlink: bool = False
    alias: str = ""
    notes: str = ""
    mod_type: str = "unknown"
    mod_types: list[str] = field(default_factory=list)
    hidden: bool = False
    sources: list[str] = field(default_factory=list)
    alternate_ids: list[str] = field(default_factory=list)
    alternate_paths: list[str] = field(default_factory=list)
    cross_source_duplicate: bool = False
    dependency_packs: list[str] = field(default_factory=list)
    required_workshop_items: list[dict[str, str]] = field(default_factory=list)
    missing_dependencies: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    ignored_warning_codes: list[str] = field(default_factory=list)

    @property
    def effective_name(self) -> str:
        return self.alias.strip() or self.display_name.strip() or Path(self.pack_name).stem

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        selected_types = list(dict.fromkeys(self.mod_types or [self.mod_type or "unknown"]))
        if len(selected_types) > 1 and "unknown" in selected_types:
            selected_types.remove("unknown")
        if not selected_types:
            selected_types = ["unknown"]
        payload["mod_types"] = selected_types
        payload["mod_type"] = selected_types[0]
        payload["sources"] = list(self.sources or [self.source])
        ignored_warning_codes = list(dict.fromkeys(self.ignored_warning_codes))
        payload["ignored_warning_codes"] = ignored_warning_codes
        payload["warnings"] = [
            warning
            for warning in self.warnings
            if str(warning.get("code") or "") not in ignored_warning_codes
        ]
        payload["effective_name"] = self.effective_name
        return payload


@dataclass(frozen=True)
class LaunchPlan:
    ordered_mod_ids: list[str]
    working_directories: list[str]
    pack_names: list[str]
    content: str
    target_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordered_mod_ids": list(self.ordered_mod_ids),
            "working_directories": list(self.working_directories),
            "pack_names": list(self.pack_names),
            "content": self.content,
            "target_path": self.target_path,
        }


@dataclass
class ScanResult:
    mods: list[ModAsset] = field(default_factory=list)
    warnings: list[str | dict[str, Any]] = field(default_factory=list)
    scanned_roots: list[str] = field(default_factory=list)
    game_updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mods": [mod.to_dict() for mod in self.mods],
            "warnings": list(self.warnings),
            "scanned_roots": list(self.scanned_roots),
            "game_updated_at": self.game_updated_at,
        }
