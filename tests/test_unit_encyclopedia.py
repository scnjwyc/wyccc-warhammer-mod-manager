from __future__ import annotations

import base64
import lzma
import struct
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.api import API
from backend.encyclopedia_assets import EncyclopediaAssets
from backend.encyclopedia_localization import collect_catalogue_loc, parse_catalogue_loc
from backend.game_data import DbSource, GameDataEntry, TABLE_SCHEMAS
from backend.models import GamePaths
from backend.unit_encyclopedia import build_catalogue, load_catalogue
from tests.helpers import make_asset, write_pack
from tests.test_unit_data import _table_payload


def table(name, rows, internal="data__"):
    return GameDataEntry(f"db/{name}/{internal}", _table_payload(name, max(TABLE_SCHEMAS[name]), rows))


def base_source():
    return DbSource("db.pack", (
        table("main_units_tables", [{"unit": "custom_unit", "land_unit": "custom_land", "num_men": 120,
                                    "caste": "melee_infantry", "in_encyclopedia": True,
                                    "recruitment_cost": 375, "ui_unit_group_land": "infantry_sword"}]),
        table("land_units_tables", [{"key": "custom_land", "bonus_hit_points": 61, "melee_attack": 32,
                                    "man_entity": "man", "primary_melee_weapon": "sword",
                                    "attribute_group": "attrs", "shield": "shield"}]),
        table("battle_entities_tables", [{"key": "man", "hit_points": 8, "run_speed": 3, "mass": 100}]),
        table("melee_weapons_tables", [{"key": "sword", "damage": 21, "ap_damage": 7}]),
        table("unit_shield_types_tables", [{"key": "shield", "missile_block_chance": 35}]),
        table("ui_unit_groupings_tables", [{"key": "infantry_sword", "parent_group": "infantry", "icon": "infantry_sword"}]),
        table("unit_variants_tables", [{"unit": "custom_land", "unit_card": "real_card"}]),
        table("factions_tables", [{"key": "faction", "subculture": "sub"}]),
        table("cultures_subcultures_tables", [{"subculture": "sub", "culture": "race"}]),
        table("units_custom_battle_permissions_tables", [{"unit": "custom_unit", "faction": "faction"}]),
        table("unit_attributes_to_groups_junctions_tables", [{"attribute": "hide_forest", "attribute_group": "attrs"}]),
    ), role="vanilla")


def png(color):
    output = BytesIO()
    Image.new("RGBA", (10, 15), color).save(output, format="PNG")
    return output.getvalue()


def loc_payload(rows):
    output = b"\xff\xfeLOC\0" + struct.pack("<ii", 1, len(rows))
    for key, text in rows:
        for value in (key, text):
            output += struct.pack("<H", len(value)) + value.encode("utf-16le")
        output += b"\0"
    return output


class CatalogueTests(unittest.TestCase):
    def test_catalogue_reads_lzma_compressed_mod_localisation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = "land_units_onscreen_name_custom_unit"
            payload = loc_payload([(name, "Compressed unit name")])
            filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 8 * 1024 * 1024,
                        "lc": 3, "lp": 0, "pb": 2}]
            compressed = (struct.pack("<I", len(payload)) + b"\x5d"
                          + struct.pack("<I", 8 * 1024 * 1024)
                          + lzma.compress(payload, format=lzma.FORMAT_RAW, filters=filters))
            pack = write_pack(root / "compressed.pack", entries=[
                ("text\\compressed.loc", compressed),
            ])
            content = bytearray(pack.read_bytes())
            content[32] = 1  # PFH5 first index entry's compression flag.
            pack.write_bytes(content)

            self.assertEqual(
                collect_catalogue_loc(root, [pack], "cn")[name],
                "Compressed unit name",
            )

    def test_culture_crest_follows_related_factions_flags_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = "ui/flags/custom_banner/mon_64.png"
            pack = write_pack(Path(tmp) / "ui.pack", entries=[(path, png("red"))])
            source = DbSource("custom flags", (table("factions_tables", [
                {"key": "faction", "subculture": "sub", "flags_path": "ui\\flags\\custom_banner"},
            ]),))
            result = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([pack]))
            self.assertEqual(result["races"][0]["key"], "race")
            self.assertEqual(result["races"][0]["crest"], path)

    def test_culture_crest_prefers_multiplayer_representative_and_accepts_larger_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            selected = "ui/flags/representative/mon_256.png"
            other = "ui/flags/other/mon_64.png"
            pack = write_pack(Path(tmp) / "ui.pack", entries=[(selected, png("blue")), (other, png("red"))])
            source = DbSource("factions", (table("factions_tables", [
                {"key": "aa_other", "subculture": "sub", "flags_path": "ui/flags/other"},
                {"key": "race_mp", "subculture": "sub", "flags_path": "ui/flags/representative"},
            ]),))
            result = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([pack]))
            self.assertEqual(result["races"][0]["crest"], selected)

    def test_chaos_dwarf_crest_uses_released_flag_instead_of_culture_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            culture = "wh3_dlc23_chd_chaos_dwarfs"
            selected = "ui/flags/wh3_dlc23_chd_legion_of_azgorh/mon_64.png"
            pack = write_pack(Path(tmp) / "ui.pack", entries=[
                (selected, png("red")), (f"ui/flags/{culture}/mon_64.png", png("white")),
            ])
            source = DbSource("culture flags", (
                table("cultures_subcultures_tables", [{"subculture": "sub", "culture": culture}]),
                table("factions_tables", [{"key": culture, "subculture": "sub",
                                          "flags_path": "ui/flags/wh3_dlc23_chd_legion_of_azgorh"}]),
            ))
            result = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([pack]))
            self.assertEqual(result["races"][0]["crest"], selected)

    def test_mod_flag_override_and_generic_group_icons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flag = "ui/flags/modded_banner/mon_64.png"
            army, generic = "ui/skins/default/icon_army.png", "ui/skins/default/icon_factions.png"
            vanilla = write_pack(root / "ui.pack", entries=[(flag, png("blue")), (army, png("yellow")), (generic, png("white"))])
            mod = write_pack(root / "mod.pack", entries=[(flag, png("red"))])
            assets = EncyclopediaAssets([mod, vanilla])
            for culture, expected in (("race", flag), ("wh2_main_rogue", army), ("unassigned", generic)):
                with self.subTest(culture=culture):
                    source = DbSource("mod", (
                        table("cultures_subcultures_tables", [{"subculture": "sub", "culture": culture}]),
                        table("factions_tables", [{"key": "faction", "subculture": "sub", "flags_path": "ui/flags/modded_banner"}]),
                    ))
                    result = build_catalogue([source, base_source()], {}, {}, assets)
                    self.assertEqual(result["races"][0]["crest"], expected)
            image_data = assets.read([flag])[flag]
            picture = Image.open(BytesIO(base64.b64decode(image_data.split(",", 1)[1])))
            self.assertEqual(picture.getpixel((0, 0)), (255, 0, 0, 255))

    def test_versionless_mod_ability_tables_keep_legacy_and_current_abilities(self):
        junction = "land_units_to_unit_abilites_junctions_tables"
        legacy_rows = [{"land_unit": "custom_land", "ability": key} for key in ("legacy_a", "legacy_b")]
        legacy_payload = _table_payload(junction, 0, legacy_rows)[8:]
        guid = "12345678-abcd-1234-abcd-123456789012"
        guid_header = b"\xfd\xfe\xfc\xff" + struct.pack("<H", len(guid)) + guid.encode("utf-16le")
        for header in (b"", guid_header):
            with self.subTest(guid=bool(header)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                current_tables = [
                    table("unit_abilities_tables", [{"key": key} for key in ("legacy_a", "legacy_b", "current")]),
                    table(junction, [{"land_unit": "custom_land", "ability": "current", "culture": "race"}]),
                ]
                write_pack(root / "db.pack", entries=[(e.name, e.payload) for e in (*base_source().entries, *current_tables)])
                legacy_pack = write_pack(root / "legacy.pack", entries=[
                    (f"db/{junction}/legacy", header + legacy_payload),
                ])
                result, _ = load_catalogue(root, {"legacy": make_asset(legacy_pack, "legacy", "data")},
                                           ["legacy"], {}, "en-US")
                self.assertEqual(result["races"][0]["count"], 1)
                self.assertEqual({f["key"] for f in result["units"][0]["features"]},
                                 {"hide_forest", "legacy_a", "legacy_b", "current"})

    def test_empty_versionless_ability_table_does_not_abort_catalogue(self):
        source = DbSource("empty.pack", (GameDataEntry(
            "db/land_units_to_unit_abilites_junctions_tables/empty", b"\x01" + struct.pack("<i", 0),
        ),))
        result = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([]))
        self.assertEqual(result["units"][0]["key"], "custom_unit")
        self.assertEqual(result["races"][0]["count"], 1)

    def test_character_cards_use_permission_portraits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = "ui/portraits/portholes/no_culture/character.png"
            card = path.replace("/portholes/", "/units/")
            pack = write_pack(Path(tmp) / "ui.pack", entries=[(path, png("red")), (card, png("blue"))])
            source = DbSource("portrait mod", (table("units_custom_battle_permissions_tables", [
                {"unit": "custom_unit", "faction": "faction", "general_portrait": path}], "!portrait"),))
            unit = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([pack]))["units"][0]
            self.assertEqual(unit["icon"], card)
            self.assertEqual(unit["portrait"], path)

    def test_mounted_character_reuses_the_exact_shared_card_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            portrait = "ui/portraits/portholes/no_culture/general.png"
            card = portrait.replace("/portholes/", "/units/")
            pack = write_pack(Path(tmp) / "ui.pack", entries=[(portrait, png("red")), (card, png("blue")),
                                                                 ("ui/units/icons/placeholder.png", png("white"))])
            source = DbSource("mounted", (
                table("main_units_tables", [{"unit": "mounted", "land_unit": "mounted_land", "in_encyclopedia": True}]),
                table("land_units_tables", [{"key": "mounted_land", "man_entity": "man"}]),
                table("unit_variants_tables", [{"unit": "mounted_land", "unit_card": "real_card"}]),
                table("units_custom_battle_permissions_tables", [{"unit": "custom_unit", "faction": "faction",
                                                                  "general_portrait": portrait}]),
            ))
            units = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([pack]))["units"]
            self.assertEqual(next(u for u in units if u["key"] == "mounted")["icon"], card)

    def test_original_placeholder_is_skipped_in_favour_of_a_character_portrait(self):
        with tempfile.TemporaryDirectory() as tmp:
            portrait = "ui/portraits/portholes/no_culture/character.png"
            pack = write_pack(Path(tmp) / "ui.pack", entries=[(portrait, png("red")),
                                                                 ("ui/units/icons/placeholder.png", png("white"))])
            source = DbSource("character", (
                table("unit_variants_tables", [{"unit": "custom_land", "unit_card": "placeholder"}]),
                table("units_custom_battle_permissions_tables", [{"unit": "custom_unit", "faction": "faction",
                                                                  "general_portrait": portrait}]),
            ))
            unit = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([pack]))["units"][0]
            self.assertEqual(unit["icon"], portrait)

    def test_variant_mapping_stats_permissions_and_original_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = write_pack(Path(tmp) / "ui.pack", entries=[("ui/units/icons/real_card.png", png("red"))])
            result = build_catalogue([base_source()], {}, {
                "land_units_onscreen_name_custom_land": "剑士", "cultures_name_race": "帝国",
                "ui_unit_groupings_onscreen_infantry_sword": "持剑步兵",
                "unit_attributes_bullet_text_hide_forest": "于森林中隐蔽\n可隐藏",
            }, EncyclopediaAssets([pack]))
            unit = result["units"][0]
            self.assertEqual((unit["name"], unit["races"], unit["group"]), ("剑士", ["race"], "infantry"))
            self.assertEqual((unit["health"], unit["speed"], unit["weapon_strength"], unit["shield"]), (8280, 30, 28, 35))
            self.assertEqual(unit["icon"], "ui/units/icons/real_card.png")
            self.assertEqual(unit["features"][0]["name"], "于森林中隐蔽")
            self.assertEqual(result["races"][0]["count"], 1)

    def test_internal_db_priority_and_order_ties_match_editor(self):
        a = DbSource("A", (table("melee_weapons_tables", [{"key": "sword", "damage": 40, "ap_damage": 3}], "same"),))
        b = DbSource("B", (table("melee_weapons_tables", [{"key": "sword", "damage": 80, "ap_damage": 7}], "same"),))
        low_name = DbSource("C", (table("melee_weapons_tables", [{"key": "sword", "damage": 99}], "!priority"),))
        def damage(sources):
            return build_catalogue([*sources, base_source()], {}, {}, EncyclopediaAssets([]))["units"][0]["weapon_strength"]
        self.assertEqual(damage([a, b]), 43)
        self.assertEqual(damage([b, a]), 87)
        self.assertEqual(damage([a, b, low_name]), 99)

    def test_saved_edits_applied_and_disabled_units_excluded(self):
        result = build_catalogue([base_source()], {"custom_unit": {"hit_points": 100, "model_count": 10,
                                "armour": 70, "melee_damage": 50}}, {}, EncyclopediaAssets([]))
        unit = result["units"][0]
        self.assertEqual((unit["health"], unit["armour_value"], unit["weapon_strength"]), (1080, 70, 57))
        self.assertTrue(unit["edited"])
        hidden = build_catalogue([base_source()], {"custom_unit": {"enabled": False}}, {}, EncyclopediaAssets([]))
        self.assertEqual(hidden["units"], [])
        self.assertEqual(hidden["races"], [])

    def test_mount_speed_and_health_use_moving_entity(self):
        override = DbSource("mounted", (
            table("land_units_tables", [{"key": "custom_land", "bonus_hit_points": 80,
                                        "man_entity": "crew", "mount": "horse", "num_mounts": 60}], "!mount"),
            table("mounts_tables", [{"key": "horse", "entity": "horse_entity"}]),
            table("battle_entities_tables", [{"key": "horse_entity", "run_speed": 7, "hit_points": 10}]),
        ))
        unit = build_catalogue([override, base_source()], {}, {}, EncyclopediaAssets([]))["units"][0]
        self.assertEqual((unit["speed"], unit["health"]), (70, 5400))

    def test_hidden_abilities_and_other_culture_abilities_excluded(self):
        source = DbSource("skills", (
            table("unit_abilities_tables", [{"key": "visible"}, {"key": "hidden", "is_hidden_in_ui": True},
                                           {"key": "locked", "requires_effect_enabling": True}, {"key": "foreign"}]),
            table("land_units_to_unit_abilites_junctions_tables", [
                {"land_unit": "custom_land", "ability": key, "culture": "other" if key == "foreign" else ""}
                for key in ("visible", "hidden", "locked", "foreign")]),
        ))
        unit = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([]))["units"][0]
        self.assertEqual([f["key"] for f in unit["features"]], ["hide_forest", "visible"])

    def test_reads_only_enabled_mod_data_and_art_plus_automatic_movie(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pack(root / "db.pack", entries=[(e.name, e.payload) for e in base_source().entries])
            active = write_pack(root / "active.pack", entries=[("ui/units/icons/real_card.png", png("green"))])
            inactive = write_pack(root / "inactive_ui.pack", entries=[("ui/units/icons/real_card.png", png("red"))])
            movie = table("melee_weapons_tables", [{"key": "sword", "damage": 222}], "!movie")
            write_pack(root / "movie.pack", byte_mask=4, entries=[(movie.name, movie.payload)])
            mods = {"a": make_asset(active, "a", "data"), "b": make_asset(inactive, "b", "data")}
            result, assets = load_catalogue(root, mods, ["a"], {}, "zh-CN")
            self.assertEqual(result["units"][0]["weapon_strength"], 222)
            self.assertNotIn("inactive_ui.pack", result["source_pack_names"])
            data = assets.read(["ui/units/icons/real_card.png"])["ui/units/icons/real_card.png"]
            with Image.open(BytesIO(base64.b64decode(data.split(",", 1)[1]))) as pic:
                self.assertEqual(pic.getpixel((0, 0)), (0, 128, 0, 255))

    def test_missing_land_rows_do_not_crash_catalogue(self):
        source = DbSource("broken", (table("main_units_tables", [{"unit": "missing", "land_unit": "not_there"}]),))
        result = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([]))
        self.assertEqual(len(result["units"]), 1)
        self.assertEqual(result["stats"]["skipped_missing_land"], 1)


class CatalogueAssetTests(unittest.TestCase):
    def test_empty_attribute_strings_use_original_ui_translation(self):
        loc = parse_catalogue_loc(loc_payload([
            ("unit_attributes_bullet_text_guerrilla_deploy", ""),
            ("unit_attributes_imued_effect_text_guerrilla_deploy", ""),
            ("ui_text_replacements_localised_text_guerrilla_deployment", "先锋部署||可以在部署区域外部署"),
        ]))
        source = DbSource("attribute", (table("unit_attributes_to_groups_junctions_tables", [
            {"attribute": "guerrilla_deploy", "attribute_group": "attrs"},
        ]),))
        unit = build_catalogue([source, base_source()], {}, loc, EncyclopediaAssets([]))["units"][0]
        feature = next(f for f in unit["features"] if f["key"] == "guerrilla_deploy")
        self.assertEqual(feature["name"], "先锋部署")
        self.assertIn("可以在部署区域外部署", feature["description"])

    def test_ranged_details_follow_effective_projectile_for_infantry_and_engines(self):
        for use_engine in (False, True):
            with self.subTest(engine=use_engine):
                land = {"key": "custom_land", "reload": 25}
                land.update({"engine": "engine"} if use_engine else {"primary_missile_weapon": "weapon"})
                source = DbSource("ranged", (
                    table("land_units_tables", [land]),
                    table("missile_weapons_tables", [{"key": "weapon", "default_projectile": "shot"}]),
                    table("battlefield_engines_tables", [{"key": "engine", "missile_weapon": "weapon"}]),
                    table("projectiles_tables", [{"key": "shot", "base_reload_time": 9.5, "projectile_number": 6,
                                                  "effective_range": 170}]),
                ))
                result = build_catalogue([source, base_source()], {}, {}, EncyclopediaAssets([]))
                self.assertEqual(result["units"][0]["firing_interval"], 9.5)
                self.assertEqual(result["units"][0]["projectile_count"], 6)
        melee = build_catalogue([base_source()], {}, {}, EncyclopediaAssets([]))["units"][0]
        self.assertIsNone(melee["firing_interval"])
        self.assertIsNone(melee["projectile_count"])

    def test_pack_order_case_normalization_and_bounded_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = write_pack(Path(tmp) / "a.pack", entries=[("UI\\Units\\Icons\\card.png", png("red"))])
            b = write_pack(Path(tmp) / "b.pack", entries=[("ui/units/icons/card.png", png("blue"))])
            assets = EncyclopediaAssets([a, b])
            self.assertEqual(assets.resolve("ui/units/icons/card.png"), "ui/units/icons/card.png")
            data = assets.read(["ui/units/icons/card.png"])["ui/units/icons/card.png"]
            self.assertEqual(Image.open(BytesIO(base64.b64decode(data.split(",")[1]))).getpixel((0, 0)), (255, 0, 0, 255))
            self.assertEqual(assets.read(["../../settings.json"]), {"../../settings.json": ""})
            with self.assertRaises(ValueError):
                assets.read(["a"] * 97)

    def test_changed_pack_invalidates_images_until_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ui.pack"
            write_pack(path, entries=[("ui/a.png", png("red"))])
            first = EncyclopediaAssets([path])
            first_image = first.read(["ui/a.png"])["ui/a.png"]
            write_pack(path, entries=[("ui/a.png", png("blue")), ("ui/extra.png", png("green"))])
            self.assertEqual(first.read(["ui/a.png"])["ui/a.png"], "")
            self.assertNotEqual(EncyclopediaAssets([path]).read(["ui/a.png"])["ui/a.png"], first_image)

    def test_localisation_fallback_and_mod_internal_priority(self):
        key = "land_units_onscreen_name_custom_land"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pack(root / "local_en.pack", entries=[("text/base.loc", loc_payload([(key, "English")]))])
            write_pack(root / "local_cn.pack", entries=[("text/base.loc", loc_payload([(key, "中文")]))])
            a = write_pack(root / "a.pack", entries=[("text/z.loc", loc_payload([(key, "A")]))])
            b = write_pack(root / "b.pack", entries=[("text/!b.loc", loc_payload([(key, "[[col:red]]B[[/col]]||line")]))])
            self.assertEqual(collect_catalogue_loc(root, [], "ja-JP")[key], "English")
            self.assertEqual(collect_catalogue_loc(root, [], "zh-CN")[key], "中文")
            self.assertEqual(collect_catalogue_loc(root, [a, b], "zh-CN")[key], "B\nline")
            with self.assertRaises(ValueError):
                parse_catalogue_loc(loc_payload([(key, "text")])[:-1])


class CatalogueApiTests(unittest.TestCase):
    def test_editor_snapshot_invalidates_when_inputs_change(self):
        from backend.start_options import collect_game_data_source_snapshot
        for change in ("edits", "pack", "movie", "order", "language", "context", "expired"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                db = root / "db.pack"
                write_pack(db, entries=[(e.name, e.payload) for e in base_source().entries])
                a = write_pack(root / "a.pack", entries=[])
                b = write_pack(root / "b.pack", entries=[])
                api = API(tmp)
                api._assets = {"a": make_asset(a, "a", "data"), "b": make_asset(b, "b", "data")}
                edits = {}
                with patch.object(api.settings_service, "resolve_game_paths", return_value=GamePaths(data_path=tmp)), \
                     patch.object(api, "_unit_data_source_ids", return_value=["a", "b"]) as order, \
                     patch.object(api, "interface_language", return_value="zh-CN") as language, \
                     patch("backend.api.load_unit_data_edits", side_effect=lambda *args: dict(edits)):
                    catalogue = api._get_unit_encyclopedia()
                    token = catalogue["token"]
                    if change == "edits":
                        edits["custom_unit"] = {"melee_attack": 78}
                    elif change == "pack":
                        write_pack(a, entries=[(e.name, e.payload) for e in [table("land_units_tables", [{"key": "custom_land", "melee_attack": 80}])]])
                    elif change == "movie":
                        write_pack(root / "new_movie.pack", byte_mask=4, entries=[])
                    elif change == "order":
                        order.return_value = ["b", "a"]
                    elif change == "language":
                        language.return_value = "en-US"
                    elif change == "context":
                        api._game_context_revision += 1
                    else:
                        token = "expired"
                    with patch("backend.api.collect_game_data_source_snapshot", wraps=collect_game_data_source_snapshot) as read:
                        response = api._get_unit_data_list(token, "custom_unit")
                        read.assert_called_once()
                        if change == "edits":
                            self.assertEqual(response["units"][0]["melee_attack"], 78)
                        if change == "pack":
                            self.assertEqual(response["units"][0]["melee_attack"], 80)

    def test_editor_reuses_catalogue_snapshot_and_preserves_other_saved_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pack(root / "db.pack", entries=[(e.name, e.payload) for e in base_source().entries])
            api = API(tmp)
            with patch.object(api.settings_service, "resolve_game_paths", return_value=GamePaths(data_path=tmp)), \
                 patch("backend.api.load_unit_data_edits", return_value={"unlisted": {"melee_attack": 99}}):
                catalogue = api.call("get_unit_encyclopedia")["data"]
                self.assertNotIn("_editor_data", catalogue)
                with patch("backend.api.collect_game_data_source_snapshot", side_effect=AssertionError("Repeated DB scan")):
                    response = api.call("get_unit_data_list", [catalogue["token"], "custom_unit"])
                    self.assertTrue(response["ok"], response)
                    self.assertEqual([u["key"] for u in response["data"]["units"]], ["custom_unit"])
                    self.assertEqual(response["data"]["saved_edits"], {"unlisted": {"melee_attack": 99}})
                    self.assertTrue(response["data"]["partial"])
                    self.assertTrue(api.call("get_unit_data_list", [catalogue["token"]])["ok"])

    def test_read_only_rpc_and_session_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = API(tmp)
            with patch.object(api.settings_service, "resolve_game_paths", return_value=GamePaths(data_path=tmp)), \
                 patch("backend.api.load_catalogue", return_value=({"units": []}, EncyclopediaAssets([]))):
                response = api.call("get_unit_encyclopedia")
                self.assertTrue(response["ok"], response)
                token = response["data"]["token"]
                images = api.call("get_unit_encyclopedia_images", [token, ["ui/a.png"]])
                self.assertEqual(images["data"], {"ui/a.png": ""})
                self.assertFalse(api.call("get_unit_encyclopedia_images", ["missing", []])["ok"])
                self.assertFalse((Path(tmp) / "runtime" / "unit_data_edits.json").exists())

    def test_wrong_game_and_context_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = API(tmp)
            with patch.object(api.settings_service, "resolve_game_paths", return_value=GamePaths(game_id="three_kingdoms", data_path=tmp)):
                self.assertFalse(api.call("get_unit_encyclopedia")["ok"])
            def changed(*args):
                api._game_context_revision += 1
                return {}, EncyclopediaAssets([])
            with patch.object(api.settings_service, "resolve_game_paths", return_value=GamePaths(data_path=tmp)), \
                 patch("backend.api.load_catalogue", side_effect=changed):
                self.assertFalse(api.call("get_unit_encyclopedia")["ok"])
                self.assertEqual(api._encyclopedia_views, {})
