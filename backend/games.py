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
    save_directory_name: str
    data_relative_path: str = "data"
    mod_format: str = "pack"
    launch_executable_name: str = ""
    uses_mod_list: bool = True
    supports_save_games: bool = True
    mod_list_encoding: str = "utf-8"
    supports_game_data_modification: bool = False
    supports_unit_data_modification: bool = False
    supports_official_profile_import: bool = False


WARHAMMER3_GAME = GameDefinition(
    id="warhammer3",
    title="Total War: WARHAMMER III",
    app_id="1142710",
    install_dir="Total War WARHAMMER III",
    executable_name="Warhammer3.exe",
    process_name="Warhammer3.exe",
    save_directory_name="Warhammer3",
    supports_game_data_modification=True,
    supports_unit_data_modification=True,
    supports_official_profile_import=True,
)
WARHAMMER2_GAME = GameDefinition(
    id="warhammer2",
    title="Total War: WARHAMMER II",
    app_id="594570",
    install_dir="Total War WARHAMMER II",
    executable_name="Warhammer2.exe",
    process_name="Warhammer2.exe",
    save_directory_name="Warhammer2",
)
WARHAMMER_GAME = GameDefinition(
    id="warhammer",
    title="Total War: WARHAMMER",
    app_id="364360",
    install_dir="Total War WARHAMMER",
    executable_name="Warhammer.exe",
    process_name="Warhammer.exe",
    save_directory_name="Warhammer",
)
THREE_KINGDOMS_GAME = GameDefinition(
    id="three_kingdoms",
    title="Total War: THREE KINGDOMS",
    app_id="779340",
    install_dir="Total War THREE KINGDOMS",
    executable_name="Three_Kingdoms.exe",
    process_name="Three_Kingdoms.exe",
    save_directory_name="ThreeKingdoms",
    supports_unit_data_modification=True,
)
PHARAOH_DYNASTIES_GAME = GameDefinition(
    id="pharaoh_dynasties",
    title="Total War: PHARAOH DYNASTIES",
    app_id="2951630",
    install_dir="Total War PHARAOH DYNASTIES",
    executable_name="Pharaoh.exe",
    process_name="Pharaoh.exe",
    save_directory_name="PharaohDynasties",
)
PHARAOH_GAME = GameDefinition(
    id="pharaoh",
    title="Total War: PHARAOH",
    app_id="1937780",
    install_dir="Total War PHARAOH",
    executable_name="Pharaoh.exe",
    process_name="Pharaoh.exe",
    save_directory_name="Pharaoh",
)
TROY_GAME = GameDefinition(
    id="troy",
    title="A Total War Saga: TROY",
    app_id="1099410",
    install_dir="Total War Saga TROY",
    executable_name="Troy.exe",
    process_name="Troy.exe",
    save_directory_name="Troy",
)
THRONES_OF_BRITANNIA_GAME = GameDefinition(
    id="thrones_of_britannia",
    title="A Total War Saga: THRONES OF BRITANNIA",
    app_id="712100",
    install_dir="Total War Saga Thrones of Britannia",
    executable_name="Thrones.exe",
    process_name="Thrones.exe",
    save_directory_name="ThronesofBritannia",
)
ATTILA_GAME = GameDefinition(
    id="attila",
    title="Total War: ATTILA",
    app_id="325610",
    install_dir="Total War Attila",
    executable_name="Attila.exe",
    process_name="Attila.exe",
    save_directory_name="Attila",
)
ROME2_GAME = GameDefinition(
    id="rome2",
    title="Total War: ROME II - Emperor Edition",
    app_id="214950",
    install_dir="Total War Rome II",
    executable_name="Rome2.exe",
    process_name="Rome2.exe",
    save_directory_name="Rome2",
)
SHOGUN2_GAME = GameDefinition(
    id="shogun2",
    title="Total War: SHOGUN 2",
    app_id="34330",
    install_dir="Total War SHOGUN 2",
    executable_name="Shogun2.exe",
    process_name="Shogun2.exe",
    save_directory_name="Shogun2",
    mod_list_encoding="utf-16le",
)
ROME_REMASTERED_GAME = GameDefinition(
    id="rome_remastered",
    title="Total War: ROME REMASTERED",
    app_id="885970",
    install_dir="Total War ROME REMASTERED",
    executable_name="Total War ROME REMASTERED.exe",
    process_name="Total War ROME REMASTERED.exe",
    save_directory_name="",
    data_relative_path="Contents/Resources/Data/data",
    mod_format="feral_directory",
    launch_executable_name="launcher/launcher.exe",
    uses_mod_list=False,
    supports_save_games=False,
)
DEFAULT_GAME_ID = WARHAMMER3_GAME.id

_GAME_DEFINITIONS = MappingProxyType(
    {
        WARHAMMER3_GAME.id: WARHAMMER3_GAME,
        WARHAMMER2_GAME.id: WARHAMMER2_GAME,
        WARHAMMER_GAME.id: WARHAMMER_GAME,
        THREE_KINGDOMS_GAME.id: THREE_KINGDOMS_GAME,
        PHARAOH_DYNASTIES_GAME.id: PHARAOH_DYNASTIES_GAME,
        PHARAOH_GAME.id: PHARAOH_GAME,
        TROY_GAME.id: TROY_GAME,
        THRONES_OF_BRITANNIA_GAME.id: THRONES_OF_BRITANNIA_GAME,
        ATTILA_GAME.id: ATTILA_GAME,
        ROME2_GAME.id: ROME2_GAME,
        SHOGUN2_GAME.id: SHOGUN2_GAME,
        ROME_REMASTERED_GAME.id: ROME_REMASTERED_GAME,
    }
)


def get_game_definition(game_id: str | None) -> GameDefinition:
    """Resolve a persisted ID safely, falling back to the default game."""
    return _GAME_DEFINITIONS.get(str(game_id or "").strip(), WARHAMMER3_GAME)


def game_definitions() -> tuple[GameDefinition, ...]:
    """Return supported games in stable UI order."""
    return tuple(_GAME_DEFINITIONS.values())
