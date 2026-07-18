from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class GameDefinition:
    """Immutable platform details and feature capabilities for one supported game."""

    id: str
    title: str
    app_id: str
    install_dir: str
    executable_name: str
    process_name: str
    supports_game_data_modification: bool = False
    supports_official_profile_import: bool = False


WARHAMMER3_GAME = GameDefinition(
    id="warhammer3",
    title="Total War: WARHAMMER III",
    app_id="1142710",
    install_dir="Total War WARHAMMER III",
    executable_name="Warhammer3.exe",
    process_name="Warhammer3.exe",
    supports_game_data_modification=True,
    supports_official_profile_import=True,
)
THREE_KINGDOMS_GAME = GameDefinition(
    id="three_kingdoms",
    title="Total War: THREE KINGDOMS",
    app_id="779340",
    install_dir="Total War THREE KINGDOMS",
    executable_name="Three_Kingdoms.exe",
    process_name="Three_Kingdoms.exe",
)
DEFAULT_GAME_ID = WARHAMMER3_GAME.id

_GAME_DEFINITIONS = MappingProxyType(
    {
        WARHAMMER3_GAME.id: WARHAMMER3_GAME,
        THREE_KINGDOMS_GAME.id: THREE_KINGDOMS_GAME,
    }
)


def get_game_definition(game_id: str | None) -> GameDefinition:
    """Resolve a persisted ID safely, falling back to the default game."""
    return _GAME_DEFINITIONS.get(str(game_id or "").strip(), WARHAMMER3_GAME)


def game_definitions() -> tuple[GameDefinition, ...]:
    """Return supported games in stable UI order."""
    return tuple(_GAME_DEFINITIONS.values())
