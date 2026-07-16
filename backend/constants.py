from __future__ import annotations

APP_NAME = "Wyccc's Mod Manager"
APP_SLUG = "WycccModManager"
LEGACY_APP_SLUGS = (
    "WycccWarhammerManager",
    "WycccWarhammerModManager",
)
APP_VERSION = "0.6.0"

IGNORABLE_MOD_WARNING_CODES = (
    "outdated_mod",
    "missing_dependency",
)
LEGACY_MOD_WARNING_CODE_ALIASES = {
    "mod_newer_than_game": "outdated_mod",
}

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

GAME_DATA_FEATURE_WORKSHOP_ITEMS = {
    "unit_size": {
        "workshop_id": "3765783838",
        "title": "Dynamic Unit Size",
        "pack_name": "wyccc_dynamic_unit_size.pack",
    },
    "friendly_fire": {
        "workshop_id": "3765783977",
        "title": "Dynamic No Friendly Fire",
        "pack_name": "wyccc_dynamic_no_friendly_fire.pack",
    },
}
UNIT_MODEL_MULTIPLIER_MIN = 0.5
UNIT_MODEL_MULTIPLIER_MAX = 5.0
INTERNAL_FEATURE_WORKSHOP_IDS = frozenset(
    item["workshop_id"] for item in GAME_DATA_FEATURE_WORKSHOP_ITEMS.values()
)
INTERNAL_FEATURE_PACK_NAMES = frozenset(
    item["pack_name"].casefold() for item in GAME_DATA_FEATURE_WORKSHOP_ITEMS.values()
)

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
