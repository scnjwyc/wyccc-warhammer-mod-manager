from __future__ import annotations

APP_NAME = "Wyccc's Mod Manager"
APP_SLUG = "WycccModManager"
LEGACY_APP_SLUGS = (
    "WycccWarhammerManager",
    "WycccWarhammerModManager",
)
APP_VERSION = "1.1.1"

IGNORABLE_MOD_WARNING_CODES = (
    "outdated_mod",
    "workshop_update_available",
    "missing_dependency",
)
LEGACY_MOD_WARNING_CODE_ALIASES = {
    "mod_newer_than_game": "outdated_mod",
}

# Built-in update manifests are checked together. Chinese users prefer Gitee
# when both repositories publish the same version; all other languages prefer
# GitHub.
GITHUB_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/scnjwyc/wyccc-warhammer-mod-manager/"
    "main/packaging/update-manifest.json"
)
GITEE_UPDATE_MANIFEST_URL = (
    "https://gitee.com/wyccc2018/wyccc-warhammer-mod-manager/"
    "raw/master/packaging/update-manifest.json"
)
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
    "unit_cap": {
        "workshop_id": "3766867060",
        "title": "动态单位容量 - Dynamic Unit Cap",
        "pack_name": "wyccc_dynamic_unit_cap.pack",
    },
}
UNIT_DATA_FEATURE_PACK_NAME = "wyccc_dynamic_units_modify.pack"
UNIT_DATA_FEATURE_TITLE = "Dynamic Units Modify"
VARIANT_SELECTOR_FEATURE_PACK_NAME = "wyccc_variant_selector_patch.pack"
VARIANT_SELECTOR_FEATURE_TITLE = "Dynamic Variant Selector Patch"
UNIT_MODEL_MULTIPLIER_MIN = 1
UNIT_MODEL_MULTIPLIER_MAX = 5
UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MIN = 1
UNIT_RECRUITMENT_CAPACITY_MULTIPLIER_MAX = 5
UNIT_RECRUITMENT_CAPACITY_UNLIMITED = 0
INTERNAL_FEATURE_WORKSHOP_IDS = frozenset(
    item["workshop_id"] for item in GAME_DATA_FEATURE_WORKSHOP_ITEMS.values()
)
INTERNAL_RUNTIME_PACK_NAMES = frozenset(
    {
        "!!!!wyccc_dynamic_ror_compatibility.pack",
        "!!!!wyccc_variant_selector_patch.pack",
        "!!!!wyccc_game_data_patch.pack",
        "!!!!wyccc_runtime_options.pack",
        "!!!!wyccc_unit_data_patch.pack",
    }
)
INTERNAL_FEATURE_PACK_NAMES = frozenset(
    item["pack_name"].casefold() for item in GAME_DATA_FEATURE_WORKSHOP_ITEMS.values()
) | INTERNAL_RUNTIME_PACK_NAMES | {
    UNIT_DATA_FEATURE_PACK_NAME.casefold(),
    VARIANT_SELECTOR_FEATURE_PACK_NAME.casefold(),
    "wyccc_nanu_rors_patch.pack",
}

# These Packs are managed by the launcher.  They remain visible in the data
# returned by a scan so the existing "show hidden MODs" control can reveal
# them, but their display name should describe the feature instead of exposing
# an implementation filename.
INTERNAL_PACK_DISPLAY_NAMES = {
    "wyccc_dynamic_unit_size.pack": {
        "zh-CN": "动态单位规模",
        "en-US": "Dynamic Unit Size",
        "ko-KR": "Dynamic Unit Size",
        "ru-RU": "Dynamic Unit Size",
        "ja-JP": "Dynamic Unit Size",
        "es-ES": "Dynamic Unit Size",
    },
    "wyccc_dynamic_no_friendly_fire.pack": {
        "zh-CN": "动态无友军伤害",
        "en-US": "Dynamic No Friendly Fire",
        "ko-KR": "Dynamic No Friendly Fire",
        "ru-RU": "Dynamic No Friendly Fire",
        "ja-JP": "Dynamic No Friendly Fire",
        "es-ES": "Dynamic No Friendly Fire",
    },
    "wyccc_dynamic_unit_cap.pack": {
        "zh-CN": "动态单位容量",
        "en-US": "Dynamic Unit Cap",
        "ko-KR": "Dynamic Unit Cap",
        "ru-RU": "Dynamic Unit Cap",
        "ja-JP": "Dynamic Unit Cap",
        "es-ES": "Dynamic Unit Cap",
    },
    "wyccc_dynamic_units_modify.pack": {
        "zh-CN": "单位数据修改",
        "en-US": "Unit Data Modification",
        "ko-KR": "유닛 데이터 수정",
        "ru-RU": "Изменение данных отрядов",
        "ja-JP": "ユニットデータ変更",
        "es-ES": "Modificación de datos de unidades",
    },
    "wyccc_variant_selector_patch.pack": {
        "zh-CN": "Dynamic Variant Selector Patch",
        "en-US": "Dynamic Variant Selector Patch",
        "ko-KR": "Dynamic Variant Selector Patch",
        "ru-RU": "Dynamic Variant Selector Patch",
        "ja-JP": "Dynamic Variant Selector Patch",
        "es-ES": "Dynamic Variant Selector Patch",
    },
    "wyccc_nanu_rors_patch.pack": {
        "zh-CN": "Nanu's Dynamic RORs Ultimate Compatibility Patch",
        "en-US": "Nanu's Dynamic RORs Ultimate Compatibility Patch",
        "ko-KR": "Nanu's Dynamic RORs Ultimate Compatibility Patch",
        "ru-RU": "Nanu's Dynamic RORs Ultimate Compatibility Patch",
        "ja-JP": "Nanu's Dynamic RORs Ultimate Compatibility Patch",
        "es-ES": "Nanu's Dynamic RORs Ultimate Compatibility Patch",
    },
    "!!!!wyccc_dynamic_ror_compatibility.pack": {
        "zh-CN": "Nanu's Dynamic RoRs 兼容补丁",
        "en-US": "Nanu's Dynamic RoRs Compatibility Patch",
        "ko-KR": "Nanu's Dynamic RoRs Compatibility Patch",
        "ru-RU": "Nanu's Dynamic RoRs Compatibility Patch",
        "ja-JP": "Nanu's Dynamic RoRs Compatibility Patch",
        "es-ES": "Nanu's Dynamic RoRs Compatibility Patch",
    },
    "!!!!wyccc_variant_selector_patch.pack": {
        "zh-CN": "Variant Selector 兼容补丁",
        "en-US": "Variant Selector Compatibility Patch",
        "ko-KR": "Variant Selector Compatibility Patch",
        "ru-RU": "Variant Selector Compatibility Patch",
        "ja-JP": "Variant Selector Compatibility Patch",
        "es-ES": "Variant Selector Compatibility Patch",
    },
    "!!!!wyccc_game_data_patch.pack": {
        "zh-CN": "游戏数据修改",
        "en-US": "Game Data Modification",
        "ko-KR": "게임 데이터 수정",
        "ru-RU": "Изменение игровых данных",
        "ja-JP": "ゲームデータ変更",
        "es-ES": "Modificación de datos del juego",
    },
    "!!!!wyccc_runtime_options.pack": {
        "zh-CN": "启动选项",
        "en-US": "Runtime Options",
        "ko-KR": "실행 옵션",
        "ru-RU": "Параметры запуска",
        "ja-JP": "起動オプション",
        "es-ES": "Opciones de ejecución",
    },
    "!!!!wyccc_unit_data_patch.pack": {
        "zh-CN": "单位数据修改",
        "en-US": "Unit Data Modification",
        "ko-KR": "유닛 데이터 수정",
        "ru-RU": "Изменение данных отрядов",
        "ja-JP": "ユニットデータ変更",
        "es-ES": "Modificación de datos de unidades",
    },
}


def internal_pack_display_name(pack_name: str, language: str = "en-US") -> str:
    aliases = INTERNAL_PACK_DISPLAY_NAMES.get(str(pack_name).casefold())
    if not aliases:
        return ""
    return str(aliases.get(language) or aliases.get("en-US") or "")

CORE_VANILLA_PACKS = {
    "data.pack",
    "db.pack",
    "database.pack",
    "data_script.pack",
}

# Campaign/boot Packs that saves record as loaded files, but that are not user
# MODs. Many are injected by the campaign loader and therefore omitted from
# data/manifest.txt. Names follow WH3-Mod-Manager's save-comparison ignore list.
SAVE_BOOT_PACK_NAMES = frozenset(
    {
        "wh3_main.pack",
        "wh3_main_chaos.pack",
        "wh3_main_combi.pack",
        "wh2_main.pack",
        "wh2_main_vortex.pack",
        "wh2_main_chaos.pack",
        "three_kingdoms.pack",
        "data_rome2.pack",
        "attilla.pack",
        "attila.pack",
        "jap_campaign.pack",
        "jap_loc.pack",
        "patch.pack",
        "main.pack",
        "patch_1.pack",
        "patch_2.pack",
        "charlemagne.pack",
        "gaul.pack",
        "blood_rome2.pack",
        "punic.pack",
        "!!!!out.pack",
    }
)

SOURCE_DATA = "data"
SOURCE_WORKSHOP = "workshop"
SOURCE_LOCAL = "local"

PACK_TYPE_MOD = "mod"
PACK_TYPE_MOVIE = "movie"
PACK_TYPE_UNKNOWN = "unknown"
