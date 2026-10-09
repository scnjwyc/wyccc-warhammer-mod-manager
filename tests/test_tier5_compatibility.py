import struct
from pathlib import Path

import pytest

from backend.constants import TIER5_COMPATIBILITY_PATCH_NAME, TIER5_FEATURE_PACK_NAME
from backend.game_data import DbSource, GameDataEntry, _collect_effective_rows, parse_db_table
from backend.scanner import ModScanner, _is_launcher_runtime_pack
from backend.start_options import read_pack_entries
from backend.tier5_compatibility import build_tier5_compatibility_entries
from backend.tier5_feature import tier5_feature_status
from backend.tier5_patch_state import ensure_tier5_compatibility_patch
from tests.helpers import make_asset, write_pack
from tests.test_dynamic_ror_compatibility import _table_payload


def entry(table, rows, internal="!beauty", version=None):
    versions = {"building_levels_tables": 3, "building_chains_tables": 10,
                "building_culture_variants_tables": 5, "building_upgrades_junction_tables": 0,
                "campaign_settlement_display_building_ids_tables": 3,
                "campaign_settlement_display_building_model_ids_tables": 0,
                "campaign_settlement_display_buildings_tables": 8}
    return GameDataEntry(f"db\\{table}\\{internal}", _table_payload(table, versions[table] if version is None else version, rows))


def city(chain="unknown_city", *, internal="!beauty", max_tier=3, model="custom_art", config_key=10):
    return [
        entry("building_chains_tables", [{"key": chain, "building_superchain": "settlements"}], internal),
        entry("building_levels_tables", [{"level_name": f"{chain}{t:02d}", "chain": chain, "level": t,
              "create_cost": 777, "health_override": 123.5, "can_convert": True} for t in range(max_tier + 1)], internal),
        entry("campaign_settlement_display_building_ids_tables", [{"key": f"{chain}{t:02d}",
              "building_level_key": f"{chain}{t:02d}", "building_model_id": model} for t in range(max_tier + 1)], internal),
        entry("campaign_settlement_display_building_model_ids_tables", [{"id": model}], internal),
        entry("campaign_settlement_display_buildings_tables", [{"key": config_key, "model_id": model,
              "building_bmd": "custom.bmd", "port_bmd": "custom_port.bmd"}], internal),
        entry("building_culture_variants_tables", [{"building": f"{chain}03", "culture": "culture",
              "faction": "faction", "description": "original_description", "icon": "original_icon"}], internal),
        entry("building_upgrades_junction_tables", [{"from": f"{chain}00", "to": f"{chain}01"}], internal),
    ]


def decoded(result):
    rows = {}
    for item in result.entries:
        table = item.name.split("\\")[1]
        rows.setdefault(table, []).extend(r.values for r in parse_db_table(table, item.payload).rows)
    return rows


def test_unknown_mod_names_get_zero_padded_tiers_and_complete_references():
    result = build_tier5_compatibility_entries([DbSource("never seen before", city())])
    rows = decoded(result)
    assert [r["level_name"] for r in rows["building_levels_tables"]] == ["unknown_city04", "unknown_city05"]
    assert all(r["create_cost"] == 777 and r["health_override"] == 123.5 and r["can_convert"] for r in rows["building_levels_tables"])
    assert {r["building_model_id"] for r in rows["campaign_settlement_display_building_ids_tables"]} == {"custom_art"}
    assert all(r["icon"] == "original_icon" for r in rows["building_culture_variants_tables"])
    assert {tuple(r[k] for k in ("from", "to")) for r in rows["building_upgrades_junction_tables"]} == {
        (f"unknown_city{t:02d}", f"unknown_city{t+1:02d}") for t in range(1, 5)
    }
    assert result.stats["patched_chain_count"] == 1


def test_major_city_is_not_extended():
    result = build_tier5_compatibility_entries([DbSource("major", city(max_tier=5))])
    assert not result.entries


def versionless_levels(rows, *, with_guid=True):
    # RPFM omits the version marker for v0 (e.g. Chasslo_Landmarks_IEE).
    payload = _table_payload("building_levels_tables", 0, rows)[8:]
    if with_guid:
        guid = "82c190ab-27e2-4782-b97b-34e0d385709a"
        payload = b"\xfd\xfe\xfc\xff" + struct.pack("<H", len(guid)) + guid.encode("utf-16le") + payload
    return GameDataEntry("db\\building_levels_tables\\le_iee", payload)


@pytest.mark.parametrize("with_guid", [False, True])
def test_versionless_landmarks_do_not_block_tier5_or_change_landmark_data(with_guid):
    levels = versionless_levels([
        {"level_name": "landmark_a", "chain": "landmark", "level": 0, "create_cost": 8800,
         "primary_slot_building_building_level_requirement": 3, "additional_loot_value": 321},
        {"level_name": "landmark_b", "chain": "landmark", "level": 1, "create_cost": 4700,
         "resource_cost": "landmark_cost", "additional_loot_value": 654},
    ], with_guid=with_guid)
    sources = [DbSource("Chasslo_Landmarks_IEE.pack", [levels]), DbSource("beauty", city())]
    result = build_tier5_compatibility_entries(sources)
    assert result == build_tier5_compatibility_entries(sources[1:])
    parsed = parse_db_table("building_levels_tables", levels.payload)
    assert parsed.version == 0 and len(parsed.rows) == 2
    assert [r.values["create_cost"] for r in parsed.rows] == [8800, 4700]
    assert [r.values["additional_loot_value"] for r in parsed.rows] == [321, 654]
    assert parsed.rows[1].values["resource_cost"] == "landmark_cost"
    effective = _collect_effective_rows([DbSource("generated", result.entries), *sources],
                                        {"building_levels_tables"})["building_levels_tables"]
    for original in parsed.rows:
        candidate = effective[original.values["level_name"]]
        assert candidate.version == 0 and candidate.row.raw == original.raw
    assert effective["unknown_city04"].version == effective["unknown_city05"].version == 3


@pytest.mark.parametrize("version", [0, 2, 3])
def test_explicit_building_level_versions_keep_their_own_layout(version):
    original = entry("building_levels_tables", [{
        "level_name": "explicit_level", "chain": "explicit_chain", "additional_loot_value": 123,
        "resource_transaction_on_complete": "completed", "split_chain_sort_order": 7,
        "override_startpos_settlement_display_building": True,
    }], version=version)
    parsed = parse_db_table("building_levels_tables", original.payload)
    assert parsed.version == version
    assert parsed.rows[0].values["additional_loot_value"] == 123
    if version >= 2:
        assert parsed.rows[0].values["resource_transaction_on_complete"] == "completed"
        assert parsed.rows[0].values["split_chain_sort_order"] == 7
    if version == 3:
        assert parsed.rows[0].values["override_startpos_settlement_display_building"]


@pytest.mark.parametrize("damage", ["truncated", "trailing", "wrong_version", "unknown_version"])
def test_invalid_building_levels_still_abort_tier5(damage):
    payload = versionless_levels([{"level_name": "landmark", "chain": "landmark"}], with_guid=False).payload
    if damage == "truncated":
        payload = payload[:-1]
    elif damage == "trailing":
        payload += b"\0"
    else:
        payload = b"\xfc\xfd\xfe\xff" + struct.pack("<i", 3 if damage == "wrong_version" else 999) + payload
    with pytest.raises(ValueError, match="building_levels_tables"):
        build_tier5_compatibility_entries([
            DbSource("invalid", [GameDataEntry("db\\building_levels_tables\\invalid", payload)]),
            DbSource("beauty", city()),
        ])


def test_display_chain_without_native_ui_fits_the_startup_array():
    vanilla = city("vanilla_minor", model="vanilla_art", internal="data__")
    vanilla[5] = entry("building_culture_variants_tables", [
        {"building": f"vanilla_minor{tier:02d}", "culture": "native_culture",
         "description": "native_description", "icon": "settlement_icon"}
        for tier in range(4)
    ], "data__")
    beauty = [e for e in city() if "building_culture_variants_tables" not in e.name]
    sources = [DbSource("beauty without UI", beauty), DbSource("vanilla", vanilla, role="vanilla")]
    result = build_tier5_compatibility_entries(sources)
    effective = _collect_effective_rows([DbSource("generated", result.entries), *sources], {
        "building_levels_tables", "building_culture_variants_tables",
    })
    levels = effective["building_levels_tables"]
    variants = effective["building_culture_variants_tables"]
    # WH3's initializer allocates from UI-row count, then uses building indices.
    assert len(variants) >= len(levels), (len(variants), len(levels))
    output = decoded(result)["building_culture_variants_tables"]
    assert {r["building"] for r in output} == {f"unknown_city{tier:02d}" for tier in range(6)}
    assert all(r["icon"] == "settlement_icon" and r["culture"] == "native_culture" for r in output)


def test_subculture_ui_variants_survive_and_extend_independently():
    original = city()
    original[5] = entry("building_culture_variants_tables", [
        {"building": "unknown_city03", "culture": "shared_culture", "subculture": subculture,
         "description": "original_description", "icon": subculture + "_icon"}
        for subculture in ("culture_a", "culture_b")
    ])
    rows = decoded(build_tier5_compatibility_entries([DbSource("two subcultures", original)]))
    higher = [r for r in rows["building_culture_variants_tables"] if r["building"] in ("unknown_city04", "unknown_city05")]
    assert {(r["building"], r["subculture"]) for r in higher} == {
        (f"unknown_city{tier:02d}", subculture) for tier in (4, 5) for subculture in ("culture_a", "culture_b")
    }
    assert all(r["icon"] == r["subculture"] + "_icon" for r in higher)


def test_no_ui_template_skips_the_chain_instead_of_adding_unsafe_levels():
    original = [e for e in city() if "building_culture_variants_tables" not in e.name]
    result = build_tier5_compatibility_entries([DbSource("no usable UI", original)])
    assert not result.entries
    assert result.stats["invalid_chain_count"] == 1


def test_missing_dummy_ruin_gets_level_zero_mapping_and_upgrade():
    entries = city()
    levels = [{"level_name": f"unknown_city{t:02d}", "chain": "unknown_city", "level": t} for t in (1, 2, 3)]
    entries[1] = entry("building_levels_tables", levels)
    entries[2] = entry("campaign_settlement_display_building_ids_tables", [
        {"key": f"unknown_city{t:02d}", "building_level_key": f"unknown_city{t:02d}", "building_model_id": "custom_art"} for t in (1, 2, 3)
    ])
    rows = decoded(build_tier5_compatibility_entries([DbSource("missing ruin", entries)]))
    ruin = next(r for r in rows["building_levels_tables"] if r["level"] == 0)
    assert ruin["create_cost"] == 0 and not ruin["can_be_damaged"]
    assert any(r["building_level_key"] == ruin["level_name"] for r in rows["campaign_settlement_display_building_ids_tables"])
    assert any(r["from"] == ruin["level_name"] and r["to"] == "unknown_city01" for r in rows["building_upgrades_junction_tables"])


def test_existing_higher_tier_art_survives_and_complete_output_is_idempotent():
    original = city()
    high = [entry("building_levels_tables", [{"level_name": "native04", "chain": "unknown_city", "level": 4}]),
            entry("campaign_settlement_display_building_ids_tables", [{"key": "native04", "building_level_key": "native04", "building_model_id": "tier4_art"}]),
            entry("campaign_settlement_display_building_model_ids_tables", [{"id": "tier4_art"}]),
            entry("campaign_settlement_display_buildings_tables", [{"key": 11, "model_id": "tier4_art", "building_bmd": "four.bmd"}])]
    sources = [DbSource("native tier4", high), DbSource("beauty", original)]
    result = build_tier5_compatibility_entries(sources)
    assert all(r["building_level_key"] != "native04" for r in decoded(result)["campaign_settlement_display_building_ids_tables"])
    again = build_tier5_compatibility_entries([DbSource("generated", result.entries), *sources])
    assert not again.entries


def test_same_path_overlay_recovers_low_tiers_and_keeps_colliding_unrelated_model():
    low = city()
    overlay = [entry("building_levels_tables", [{"level_name": "other03", "chain": "other", "level": 3}]),
               entry("campaign_settlement_display_building_ids_tables", []),
               entry("campaign_settlement_display_building_model_ids_tables", [{"id": "unrelated"}]),
               entry("campaign_settlement_display_buildings_tables", [{"key": 10, "model_id": "unrelated", "building_bmd": "other.bmd"}])]
    result = build_tier5_compatibility_entries([DbSource("overlay", overlay), DbSource("updated beauty", low)])
    rows = decoded(result)
    assert {r["level"] for r in rows["building_levels_tables"] if r["chain"] == "unknown_city"} == set(range(6))
    config = next(r for r in rows["campaign_settlement_display_buildings_tables"] if r["model_id"] == "custom_art")
    assert config["key"] != 10 and config["building_bmd"] == "custom.bmd"
    assert all(r["model_id"] != "unrelated" for r in rows["campaign_settlement_display_buildings_tables"])


def test_original_minor_economics_stay_intact_when_visual_mapping_changes():
    vanilla = city("minor", model="vanilla_art", config_key=1, internal="data__")
    base = [entry("building_levels_tables", [{"level_name": f"minor{t:02d}", "chain": "minor", "level": t, "create_cost": 9000+t} for t in (4, 5)], "!!tier5")]
    beauty = [entry("campaign_settlement_display_building_ids_tables", [{"key": "minor03", "building_level_key": "minor03", "building_model_id": "custom_art"}]),
              entry("campaign_settlement_display_building_model_ids_tables", [{"id": "custom_art"}]),
              entry("campaign_settlement_display_buildings_tables", [{"key": 2, "model_id": "custom_art", "building_bmd": "custom.bmd"}])]
    rows = decoded(build_tier5_compatibility_entries([DbSource("beauty", beauty), DbSource("tier5", base), DbSource("vanilla", vanilla, role="vanilla")]))
    assert "building_levels_tables" not in rows
    assert {r["building_model_id"] for r in rows["campaign_settlement_display_building_ids_tables"]} == {"custom_art"}


def test_feature_marker_is_installed_not_enabled_and_base_must_be_enabled(tmp_path):
    marker = make_asset(write_pack(tmp_path / TIER5_FEATURE_PACK_NAME), "marker", "local")
    base = make_asset(write_pack(tmp_path / "!!!!!MinorTierFiveFourAll.pack"), "base", "local")
    assets = {"marker": marker, "base": base}
    assert tier5_feature_status(assets, ["base"])["available"]
    assert not tier5_feature_status(assets, ["marker"])["available"]
    Path(marker.path).unlink()
    assert not tier5_feature_status(assets, ["base"])["available"]


def test_marker_pack_is_hidden_but_ordinary_beautification_mod_is_visible(tmp_path):
    marker = make_asset(write_pack(tmp_path / TIER5_FEATURE_PACK_NAME), "marker", "local")
    ordinary = make_asset(write_pack(tmp_path / "city_beautification.pack"), "ordinary", "local")
    ModScanner._apply_internal_pack_metadata({"marker": marker, "ordinary": ordinary}, "zh-CN")
    assert marker.hidden and not ordinary.hidden
    root = Path(__file__).resolve().parents[1]
    entries = read_pack_entries(root / "mods/wyccc_tier5_patch" / TIER5_FEATURE_PACK_NAME)
    assert len(entries) == 1 and entries[0].name == "wyccc\\features\\tier5_patch.json"
    generated = build_tier5_compatibility_entries([DbSource("beauty", city())])
    assert _is_launcher_runtime_pack(e.name for e in generated.entries)
    assert not _is_launcher_runtime_pack(["db\\building_levels_tables\\ordinary_beauty"])


@pytest.mark.parametrize("loss", ["setting", "marker", "base"])
def test_cache_reuses_then_removes_patch_when_gate_is_lost(tmp_path, loss):
    data = tmp_path / "data"
    write_pack(data / "db.pack")
    marker = make_asset(write_pack(tmp_path / TIER5_FEATURE_PACK_NAME), "marker", "local")
    base = make_asset(write_pack(tmp_path / "!!!!!MinorTierFiveFourAll.pack"), "base", "local")
    beauty = make_asset(write_pack(tmp_path / "beauty.pack", entries=[(e.name, e.payload) for e in city()]), "beauty", "local")
    assets = {"marker": marker, "base": base, "beauty": beauty}
    settings = {"tier5_compatibility_patch_enabled": True}
    args = [tmp_path / "runtime", data, assets, ["base", "beauty"], "playset", settings]
    first = ensure_tier5_compatibility_patch(*args)
    assert first["status"] == "generated"
    assert ensure_tier5_compatibility_patch(*args)["status"] == "reused"
    if loss == "setting":
        settings["tier5_compatibility_patch_enabled"] = False
    elif loss == "marker":
        Path(marker.path).unlink()
    else:
        args[3] = ["beauty"]
    result = ensure_tier5_compatibility_patch(*args)
    assert result["status"] == "zero_modification" and not result["path"]
    assert not (tmp_path / "runtime" / TIER5_COMPATIBILITY_PATCH_NAME).exists()


def test_rpc_cannot_enable_without_dependencies(tmp_path):
    from backend.api import API
    api = API(tmp_path / "state")
    result = api.call("save_compatibility_patch_settings", [{"tier5_compatibility_patch_enabled": True}])
    assert result["ok"]
    assert not result["data"]["settings"]["tier5_compatibility_patch_enabled"]


def test_ui_fix_rebuilds_pre_fix_version_two_cache(tmp_path, monkeypatch):
    from backend import tier5_patch_state
    current_version = tier5_patch_state.TIER5_COMPATIBILITY_BUILDER_VERSION
    data = tmp_path / "data"
    write_pack(data / "db.pack")
    marker = make_asset(write_pack(tmp_path / TIER5_FEATURE_PACK_NAME), "marker", "local")
    base = make_asset(write_pack(tmp_path / "!!!!!MinorTierFiveFourAll.pack"), "base", "local")
    beauty = make_asset(write_pack(tmp_path / "beauty.pack", entries=[(e.name, e.payload) for e in city()]), "beauty", "local")
    args = [tmp_path / "runtime", data, {"marker": marker, "base": base, "beauty": beauty},
            ["base", "beauty"], "playset", {"tier5_compatibility_patch_enabled": True}]
    monkeypatch.setattr(tier5_patch_state, "TIER5_COMPATIBILITY_BUILDER_VERSION", 2)
    before = ensure_tier5_compatibility_patch(*args)
    assert ensure_tier5_compatibility_patch(*args)["status"] == "reused"
    monkeypatch.setattr(tier5_patch_state, "TIER5_COMPATIBILITY_BUILDER_VERSION", current_version)
    fixed = ensure_tier5_compatibility_patch(*args)
    assert fixed["status"] == "generated"
    assert fixed["fingerprint"] != before["fingerprint"]


def test_mod_update_and_output_corruption_force_cache_rebuild(tmp_path):
    data = tmp_path / "data"
    write_pack(data / "db.pack")
    marker = make_asset(write_pack(tmp_path / TIER5_FEATURE_PACK_NAME), "marker", "local")
    base = make_asset(write_pack(tmp_path / "!!!!!MinorTierFiveFourAll.pack"), "base", "local")
    beauty_path = write_pack(tmp_path / "beauty.pack", entries=[(e.name, e.payload) for e in city()])
    beauty = make_asset(beauty_path, "beauty", "local")
    assets = {"marker": marker, "base": base, "beauty": beauty}
    args = [tmp_path / "runtime", data, assets, ["base", "beauty"], "playset", {"tier5_compatibility_patch_enabled": True}]
    before = ensure_tier5_compatibility_patch(*args)
    write_pack(beauty_path, entries=[(e.name, e.payload) for e in city(model="updated_art")])
    updated = ensure_tier5_compatibility_patch(*args)
    assert updated["status"] == "generated" and updated["fingerprint"] != before["fingerprint"]
    mappings = [e for e in read_pack_entries(Path(updated["path"])) if 'display_building_ids_tables' in e.name]
    assert all(r.values["building_model_id"] == "updated_art" for r in parse_db_table("campaign_settlement_display_building_ids_tables", mappings[0].payload).rows)
    Path(updated["path"]).write_bytes(b"broken")
    assert ensure_tier5_compatibility_patch(*args)["status"] == "generated"


def test_offline_launch_plan_generates_hidden_patch_then_cleans_it(tmp_path, monkeypatch):
    from backend import api as api_module
    from tests.test_storage_and_api import ApiContractTests
    api, _ = ApiContractTests._prepare_launch_api(tmp_path)
    data = tmp_path / "Total War WARHAMMER III/data"
    write_pack(data / TIER5_FEATURE_PACK_NAME)
    write_pack(data / "!!!!!MinorTierFiveFourAll.pack")
    write_pack(data / "beauty.pack", entries=[(e.name, e.payload) for e in city()])
    scan = api.call("scan_mods", [False])
    assert scan["ok"]
    marker = next(m for m in scan["data"]["mods"] if m["pack_name"] == TIER5_FEATURE_PACK_NAME)
    assert marker["hidden"]
    ids = [m["id"] for m in scan["data"]["mods"] if m["pack_name"] != TIER5_FEATURE_PACK_NAME]
    saved = api.call("save_load_order", [ids, scan["data"]["order_token"]])
    assert saved["ok"]
    pref = api.call("save_compatibility_patch_settings", [{"tier5_compatibility_patch_enabled": True}])
    assert pref["ok"] and pref["data"]["settings"]["tier5_compatibility_patch_enabled"]
    # Exercise the real staging/order pipeline with the process launch replaced.
    monkeypatch.setattr(api_module, "launch_game", lambda *args, **kwargs: {"pid": 123})
    monkeypatch.setattr(api_module, "is_game_running", lambda *args, **kwargs: False)
    monkeypatch.setattr(api_module, "query_workshop_subscription_status", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "set_game_running", lambda *args, **kwargs: None)
    launch = api.call("launch_game", [ids, saved["data"]["order_token"]])
    assert launch["ok"], launch
    assert launch["data"]["launch_plan"]["ordered_mod_ids"] == ["runtime:tier5-compatibility", *ids]
    assert (data / TIER5_COMPATIBILITY_PATCH_NAME).is_file()
    assert marker["id"] not in launch["data"]["launch_plan"]["ordered_mod_ids"]
    (data / TIER5_FEATURE_PACK_NAME).unlink()
    rescanned = api.call("scan_mods", [False])
    launch = api.call("launch_game", [ids, rescanned["data"]["order_token"]])
    assert launch["ok"], launch
    assert launch["data"]["launch_plan"]["ordered_mod_ids"] == ids
    assert not (data / TIER5_COMPATIBILITY_PATCH_NAME).exists()
    assert not (api.data_dir / "runtime" / TIER5_COMPATIBILITY_PATCH_NAME).exists()
