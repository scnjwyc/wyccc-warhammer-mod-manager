from __future__ import annotations

APP_NAME = "Wyccc's Mod Manager"
APP_SLUG = "WycccModManager"
LEGACY_APP_SLUGS = (
    "WycccWarhammerManager",
    "WycccWarhammerModManager",
)
APP_VERSION = "0.1.0"

# Set this to the published HTTPS JSON manifest before making a public build.
# Users can override it in Settings, which also keeps development and private
# distribution channels possible without changing the updater implementation.
DEFAULT_UPDATE_MANIFEST_URL = ""

WH3_APP_ID = "1142710"
WH3_GAME_FOLDER = "Total War WARHAMMER III"
WH3_EXECUTABLE = "Warhammer3.exe"
WH3_PROCESS_NAME = "Warhammer3.exe"
WH3_PACK_MAGIC = b"PFH5"

CORE_VANILLA_PACKS = {
    "data.pack",
    "db.pack",
    "data_script.pack",
}

SOURCE_DATA = "data"
SOURCE_WORKSHOP = "workshop"

PACK_TYPE_MOD = "mod"
PACK_TYPE_MOVIE = "movie"
PACK_TYPE_UNKNOWN = "unknown"
