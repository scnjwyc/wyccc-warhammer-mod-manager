from __future__ import annotations

APP_NAME = "Wyccc's Mod Manager"
APP_SLUG = "WycccModManager"
LEGACY_APP_SLUGS = (
    "WycccWarhammerManager",
    "WycccWarhammerModManager",
)
APP_VERSION = "0.1.0"

# Built-in update manifests are checked together. Chinese users prefer Gitee
# when both repositories publish the same version; all other languages prefer
# GitHub. A custom manifest in Settings overrides both built-in sources.
GITHUB_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/scnjwyc/wyccc-warhammer-mod-manager/"
    "main/packaging/update-manifest.json"
)
GITEE_UPDATE_MANIFEST_URL = (
    "https://gitee.com/wyccc2018/wyccc-warhammer-mod-manager/"
    "raw/master/packaging/update-manifest.json"
)
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
