"""WH3 catalogue: effective DB rows, original art, and read-only unit panels."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .encyclopedia_assets import EncyclopediaAssets
from .encyclopedia_localization import collect_catalogue_loc
from .encyclopedia_schema import ENCYCLOPEDIA_SCHEMAS
from .game_data import TABLE_PREFIXES, _collect_effective_rows
from .start_options import collect_game_data_source_snapshot, resolve_game_data_source_specs
from .unit_data import (
    RACE_TABLES, UNIT_JOIN_TABLES, _collect_permission_rows, _warhammer_entity_shape,
    build_unit_table_snapshot, _unit_missile_weapon, _language_loc_packs,
)

CATALOGUE_PREFIXES = (*TABLE_PREFIXES, *(f"db/{name}/" for name in ENCYCLOPEDIA_SCHEMAS))
SKIN = "ui/skins/default/"
STAT_ICONS = {
    "model_count": "icon_entity_small", "armour_value": "icon_stat_armour",
    "morale": "icon_stat_morale", "speed": "icon_stat_speed",
    "melee_attack": "icon_stat_attack", "melee_defence": "icon_stat_defence",
    "weapon_strength": "icon_stat_damage", "charge_bonus": "icon_stat_charge_bonus",
    "ammo": "icon_stat_ammo", "range": "icon_stat_range",
    "missile_damage": "icon_stat_ranged_damage", "health": "icon_stat_health_noframe",
    "upkeep": "icon_income", "mass": "icon_stat_mass",
}


def _unit_image(assets: EncyclopediaAssets, kind: str, *keys: str) -> str:
    paths = []
    for key in dict.fromkeys(keys):
        if not key or "placeholder" in str(key).casefold():
            continue
        if str(key).lower().startswith("ui/") or str(key).lower().startswith("ui\\"):
            paths.append(key)
        else:
            name = key if Path(key).suffix else key + ".png"
            paths.append(f"ui/units/{kind}/{name}")
    return assets.resolve(*paths)


def _culture_crest(
    assets: EncyclopediaAssets, culture: str, factions: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    # Mixed rosters have no single faction identity; use the game's generic icons.
    if culture == "unassigned":
        return assets.resolve(f"{SKIN}icon_factions.png")
    if culture == "wh2_main_rogue":
        return assets.resolve(f"{SKIN}icon_army.png", f"{SKIN}icon_factions.png")
    representatives = (culture, f"{culture}_mp")
    candidates = sorted(factions.get(culture, ()), key=lambda row: (
        representatives.index(row["key"]) if row["key"] in representatives else 2,
        bool(row.get("is_rebel")), bool(row.get("is_quest_faction")), row["key"],
    ))
    for faction in candidates:
        # Many culture keys redirect to another folder (e.g. Cathay -> Northern
        # Provinces); synthesizing ui/flags/<culture> misses these or finds PH art.
        folder = str(faction.get("flags_path") or "").strip().replace("\\", "/").rstrip("/")
        if not folder or "placeholder" in folder.casefold():
            continue
        path = assets.resolve(*(f"{folder}/mon_{size}.png" for size in (64, 256, 24)),
                              f"{folder}/mon_icon.png")
        if path:
            return path
    return assets.resolve(f"{SKIN}icon_factions.png")


def build_catalogue(
    sources: Sequence[Any], edits: Mapping[str, Any], loc: Mapping[str, str], assets: EncyclopediaAssets,
) -> dict[str, Any]:
    names = {k.removeprefix("land_units_onscreen_name_"): v for k, v in loc.items()
             if k.startswith("land_units_onscreen_name_")}
    cultures = {k.removeprefix("cultures_name_"): v for k, v in loc.items() if k.startswith("cultures_name_")}
    snapshot = build_unit_table_snapshot(sources, edits, name_map=names, culture_map=cultures)
    effective = _collect_effective_rows(
        sources, set(UNIT_JOIN_TABLES) | set(RACE_TABLES) | set(ENCYCLOPEDIA_SCHEMAS) | {"battle_entities_tables"},
        skip_main_unit_compatibility_placeholders=True,
    )

    def values(table, key):
        candidate = effective.get(table, {}).get(key)
        return candidate.row.values if candidate else {}

    culture_factions = defaultdict(list)
    for candidate in effective["factions_tables"].values():
        faction = candidate.row.values
        culture = values("cultures_subcultures_tables", faction.get("subculture")).get("culture")
        if culture:
            culture_factions[culture].append(faction)

    variants = defaultdict(list)
    for candidate in effective["unit_variants_tables"].values():
        variants[candidate.row.values["unit"]].append(candidate.row.values)
    attributes = defaultdict(list)
    for candidate in effective["unit_attributes_to_groups_junctions_tables"].values():
        row = candidate.row.values
        attributes[row.get("attribute_group")].append(row["attribute"])
    abilities = defaultdict(list)
    for candidate in effective["land_units_to_unit_abilites_junctions_tables"].values():
        row = candidate.row.values
        ability = values("unit_abilities_tables", row["ability"])
        if ability and not ability.get("is_hidden_in_ui") and not ability.get("requires_effect_enabling"):
            abilities[row["land_unit"]].append((ability, row.get("culture")))

    # Explicit permissions give custom-key MOD units a home even without a CA prefix.
    permissions = defaultdict(set)
    character_portraits = defaultdict(list)
    for permission in _collect_permission_rows(sources, "units_custom_battle_permissions_tables").values():
        faction = values("factions_tables", permission.row.values.get("faction"))
        culture = values("cultures_subcultures_tables", faction.get("subculture")).get("culture")
        if culture:
            permissions[permission.unit_key].add(culture)
        portrait = str(permission.row.values.get("general_portrait") or "").replace("\\", "/")
        if portrait:
            character_portraits[permission.unit_key].append(portrait)

    recruitable = set(permissions)
    for table in ("units_to_groupings_military_permissions_tables", "units_to_exclusive_faction_permissions_tables",
                  "building_units_allowed_tables"):
        recruitable.update(p.unit_key for p in _collect_permission_rows(sources, table).values())

    portraits_by_card = defaultdict(set)
    for unit_key, paths in character_portraits.items():
        land_key = values("main_units_tables", unit_key).get("land_unit")
        for variant in variants[land_key]:
            card = str(variant.get("unit_card") or "")
            if card and "placeholder" not in card.casefold():
                portraits_by_card[card].update(paths)

    units = []
    races = {}
    for row in snapshot["units"]:
        main = values("main_units_tables", row["key"])
        land = values("land_units_tables", row["land_unit"])
        # Hidden campaign helpers, naval stubs and disabled editor rows are not recruitable entries.
        if not row["enabled"] or main.get("is_naval"):
            continue
        if main.get("in_encyclopedia") is False and row["key"] not in recruitable:
            continue
        race_keys = [row["race_key"]] if row["race_key"] else sorted(permissions[row["key"]])
        if not race_keys:
            race_keys = ["unassigned"]
        group_key = str(main.get("ui_unit_group_land") or "")
        grouping = values("ui_unit_groupings_tables", group_key)
        group = str(grouping.get("parent_group") or row["caste"] or "other")
        if row["caste"] in {"lord", "hero"}:
            group = row["caste"]
        variant_rows = sorted(variants[row["land_unit"]], key=lambda v: (bool(v.get("faction")), str(v.get("faction") or "")))
        card_keys = [v.get("unit_card") for v in variant_rows if v.get("unit_card")]
        icon = _unit_image(assets, "icons", *card_keys, row["land_unit"], row["key"])
        portrait = _unit_image(assets, "infopics", *card_keys, row["land_unit"], row["key"])
        # Characters use the battle-permission portrait, often with no unit-card texture at all.
        portrait_paths = sorted(set(character_portraits[row["key"]]).union(
            *(portraits_by_card[key] for key in card_keys),
        ))
        icon = icon or assets.resolve(*(p.replace("/portholes/", "/units/") for p in portrait_paths),
                                      *portrait_paths, f"ui/units/minspec_portholes/{row['land_unit']}.png")
        portrait = portrait or assets.resolve(*portrait_paths)
        shape = _warhammer_entity_shape(effective, land)
        entities = [c["entity"].row.values for c in shape["components"]]
        entity = entities[0] if entities else {}
        attr_keys = sorted(set(attributes[land.get("attribute_group")]))
        flying = "flying" in attr_keys or "always_flying" in attr_keys
        speed = entity.get("fly_speed") if flying and entity.get("fly_speed") else entity.get("run_speed")
        # The editor exposes bonus HP; the information panel includes the entity's base HP.
        health = round((row["hit_points"] + float(entity.get("hit_points") or 0)) * row["model_count"])
        features = []
        for key in attr_keys:
            ui_key = "guerrilla_deployment" if key == "guerrilla_deploy" else key
            text = (loc.get(f"unit_attributes_bullet_text_{key}")
                    or loc.get(f"ui_text_replacements_localised_text_{ui_key}", ""))
            label = loc.get(f"unit_attributes_imued_effect_text_{key}") or text.split("\n", 1)[0] or key
            features.append({"key": key, "name": label, "description": text,
                             "icon": assets.resolve(f"ui/battle ui/ability_icons/{key}.png")})
        seen = set()
        for ability, culture in abilities[row["land_unit"]]:
            key = ability["key"]
            if key in seen or (culture and culture not in race_keys):
                continue
            seen.add(key)
            icon_name = str(ability.get("icon_name") or key)
            features.append({"key": key, "name": loc.get(f"unit_abilities_onscreen_name_{key}", key),
                             "description": loc.get(f"unit_abilities_tooltip_text_{key}", ""),
                             "icon": assets.resolve(f"ui/battle ui/ability_icons/{icon_name.removesuffix('.png')}.png")})
        for key in race_keys:
            if key not in races:
                # The original prologue strip is stamped PLACEHOLDER; use the released Kislev artwork.
                art_key = "wh3_main_ksl_kislev" if key == "wh3_main_pro_ksl_kislev" else key
                races[key] = {
                    "key": key, "name": cultures.get(key, key), "count": 0,
                    "prologue": key == "wh3_main_pro_ksl_kislev",
                    "image": assets.resolve(f"ui/frontend ui/race_select_images/large/{art_key}.png",
                                            f"ui/frontend ui/race_strip_images/{art_key}_large.png"),
                    "crest": _culture_crest(assets, art_key, culture_factions),
                }
            races[key]["count"] += 1
        missile = _unit_missile_weapon(effective, land)
        projectile = values("projectiles_tables", missile.row.values.get("default_projectile")) if missile else {}
        units.append({
            **{key: row[key] for key in (
                "key", "name", "caste", "model_count", "recruitment_cost", "upkeep_cost", "armour_value",
                "morale", "melee_attack", "melee_defence", "charge_bonus", "ammo", "range",
                "melee_damage", "melee_ap_damage", "missile_damage", "missile_ap_damage", "mass",
                "missile_resistance", "physical_resistance", "magic_resistance", "fire_resistance", "ward_save",
                "source_chain", "melee_bonus_v_large", "melee_bonus_v_infantry",
            )},
            "races": race_keys, "group": group,
            "group_name": loc.get(f"ui_unit_groupings_onscreen_{group}", ""),
            "category": loc.get(f"ui_unit_groupings_onscreen_{group_key}", ""),
            "category_icon": assets.resolve(f"ui/common ui/unit_category_icons/{grouping.get('icon') or group_key}.png"),
            "description": loc.get(f"unit_description_short_texts_text_{land.get('short_description_text')}", ""),
            "icon": icon, "portrait": portrait or icon, "health": health,
            "speed": round(float(speed) * 10) if speed is not None else None,
            "weapon_strength": row["melee_damage"] + row["melee_ap_damage"],
            "missile_strength": row["missile_damage"] + row["missile_ap_damage"],
            "firing_interval": projectile.get("base_reload_time"),
            "projectile_count": projectile.get("projectile_number"),
            "shield": values("unit_shield_types_tables", land.get("shield")).get("missile_block_chance", 0),
            "features": features, "edited": bool(row["edited"]),
        })
    units.sort(key=lambda row: (row["recruitment_cost"], row["name"], row["key"]))
    return {
        # Kept on the backend for the editor; API strips it from the public catalogue.
        "_editor_data": snapshot,
        "races": sorted(races.values(), key=lambda r: (r["key"] == "unassigned", r["name"])),
        "units": units, "stats": snapshot["stats"],
        "art": {
            **{key: assets.resolve(f"{SKIN}{name}.png") for key, name in STAT_ICONS.items()},
            **{name: assets.resolve(f"{SKIN}{name}.png") for name in (
                "panel_back_tile", "parchment_texture", "parchment_divider", "parchment_header_max",
                "bar_back", "bar_frame", "separator_skull2", "unit_card_frame", "icon_entity_large",
            )},
        },
        "asset_warnings": assets.warnings,
    }


def load_catalogue(data_path, mods, active_ids, edits, language):
    root = Path(data_path)
    snapshot = collect_game_data_source_snapshot(root, mods, active_ids, prefixes=CATALOGUE_PREFIXES)
    mod_paths = [entry.spec.path for entry in snapshot.entries if entry.spec.role != "vanilla"]
    # Only known original UI packs are fallback layers. An inactive mod named *ui*.pack must not leak in.
    vanilla_ui = [root / name for name in ("ui.pack", "ui2.pack", "ui3.pack") if (root / name).is_file()]
    assets = EncyclopediaAssets([*mod_paths, *vanilla_ui])
    loc = collect_catalogue_loc(root, mod_paths, language)
    result = build_catalogue(snapshot.sources, edits, loc, assets)
    result["source_count"] = len(snapshot.entries)
    result["source_pack_names"] = [entry.spec.path.name for entry in snapshot.entries]
    return result, assets


def catalogue_fingerprint(data_path, mods, active_ids, language):
    """Check source identity without reading DB payloads, including automatic Movie Packs."""
    root = Path(data_path)
    specs = resolve_game_data_source_specs(root, mods, active_ids)
    paths = [(spec.role, spec.path) for spec in specs]
    paths.extend(("loc", root / name) for name in _language_loc_packs(language))
    files = []
    for role, path in paths:
        try:
            stat = path.stat()
            stamp = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            stamp = None
        files.append((role, str(path), stamp))
    return str(root), tuple(active_ids), language, tuple(files)
