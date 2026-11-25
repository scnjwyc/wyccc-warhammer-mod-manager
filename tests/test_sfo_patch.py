import struct
from pathlib import Path

from backend.api import API
from backend.schema_update import VERSION_MARKER, _default, _encode_value
from backend.scanner import read_pack_dependencies
from backend.sfo_patch import SFO_PACK, _effective_rows, _read_tables, _schemas
from backend.start_options import PackEntry, write_pfh5_pack
from tests.helpers import make_asset


def table(name, filename, **values):
    name += "_tables"
    definition = _schemas()[name][0]
    version = definition["version"]
    header = VERSION_MARKER + struct.pack("<i", version) if version > 0 else b""
    payload = header + struct.pack("<BI", 1, 1) + b"".join(
        _encode_value(values[field["name"]] if field["name"] in values else _default(field), field["type"])
        for field in definition["fields"]
    )
    return PackEntry(f"db\\{name}\\{filename}", payload)


def test_create_sfo_patch_uses_original_damage_and_persists_workshop_alias(tmp_path, monkeypatch):
    game = tmp_path / "game"
    data = game / "data"
    workshop = tmp_path / "workshop"
    vanilla = write_pfh5_pack(data / "db.pack", [
        table("battle_entities", "data__", key="man", hit_points=30),
        table("melee_weapons", "data__", key="sword", damage=20, ap_damage=10),
        table("unit_armour_types", "data__", key="armour", armour_value=40),
        table("missile_weapons", "data__", key="bow", default_projectile="arrow"),
        table("missile_weapons_to_projectiles", "data__", missile_weapon="bow", projectile="fire_arrow"),
        table("projectiles", "data__", key="arrow", damage=15, ap_damage=5, effective_range=123),
        table("projectiles", "alternate", key="fire_arrow", damage=0, ap_damage=5, explosion_type="blast"),
        table("projectiles_explosions", "data__", key="blast", detonation_damage=2.5, detonation_damage_ap=5.0),
        table("land_units", "data__", key="unrelated", primary_missile_weapon="bow"),
        table("special_ability_phases", "data__", id="shared_phase", damage_amount=20, hp_change_frequency=2.0),
        table("special_ability_phases", "healing", id="healing_phase", heal_amount=0.5),
        table("special_ability_phase_stat_effects", "data__", phase="shared_phase", stat="test_stat", value=5.0),
        table("special_ability_to_special_ability_phase_junctions", "data__",
              special_ability="vanilla_spell", phase="shared_phase", target_enemies=True),
        table("unit_special_abilities", "data__", key="vanilla_spell", activated_projectile="fire_arrow"),
    ])
    original = write_pfh5_pack(workshop / "123" / "!archers.pack", [
        table("main_units", "mod", unit="archers", land_unit="archers", num_men=100, caste="infantry", tier=2),
        table("land_units", "mod", key="archers", man_entity="man", armour="armour", bonus_hit_points=70,
              primary_melee_weapon="sword", primary_missile_weapon="bow", category="inf_ranged"),
        table("unit_special_abilities", "mod", key="fire_spell", activated_projectile="fire_arrow", vortex="vortex",
              bombardment="bombard", recharge_time=60.0),
        table("special_ability_to_special_ability_phase_junctions", "mod",
              special_ability="fire_spell", phase="shared_phase", target_enemies=True),
        table("special_ability_to_special_ability_phase_junctions", "heal",
              special_ability="fire_spell", phase="healing_phase", order=1, target_friends=True),
        table("battle_vortexs", "mod", vortex_key="vortex", damage=20, damage_ap=10, duration=4.0,
              subsequent_vortex="second_vortex"),
        table("battle_vortexs", "second", vortex_key="second_vortex", damage=10, contact_effect="shared_phase"),
        table("projectile_bombardments", "mod", bombardment_key="bombard", projectile_type="fire_arrow",
              num_projectiles=8),
    ])
    sfo = write_pfh5_pack(workshop / "2792731173" / SFO_PACK, [
        table("battle_entities", "sfo", key="man", hit_points=0),
        table("projectiles", "sfo", key="arrow", damage=999, ap_damage=999),
    ])
    (game / "Warhammer3.exe").touch()
    api = API(tmp_path / "state")
    api.settings_service.save({
        "game_path": str(game), "workshop_path": str(workshop), "fetch_workshop_metadata": False,
    })
    mod = make_asset(original, "steam:123:!archers.pack", "workshop", "123")
    mod.alias = "Existing alias"
    sfo_mod = make_asset(sfo, f"steam:2792731173:{SFO_PACK}", "workshop", "2792731173")
    api._assets = {asset.id: asset for asset in (mod, sfo_mod)}
    monkeypatch.setattr(api, "detect_game_running", lambda: False)
    monkeypatch.setattr(api.workshop_service, "get_many",
                        lambda *args, **kwargs: {"123": {"title": "Workshop Archers"}})
    monkeypatch.setattr(api.workshop_service, "ensure_dependencies", lambda *args, **kwargs: {})

    result = api.call("create_sfo_patch", [mod.id])
    assert result["ok"], result
    report = result["data"]
    target = data / "!!archers_sfo.pack"
    assert Path(report["path"]) == target
    assert read_pack_dependencies(target) == [original.name, sfo.name]
    assert report["units"][0]["stats"]["hp"] == (100, 160)
    scanned = next(row for row in report["scan"]["mods"] if row["id"] == report["mod_id"])
    assert scanned["alias"] == "Workshop Archers SFO补丁"
    assert report["mod_id"] not in report["scan"]["enabled_order"]

    patch = _effective_rows(_read_tables(target))
    assert set(patch["land_units"]) == {"archers"}
    land = patch["land_units"]["archers"]
    assert land["bonus_hit_points"] == 160
    bow = patch["missile_weapons"][land["primary_missile_weapon"]]
    arrow = patch["projectiles"][bow["default_projectile"]]
    assert (arrow["damage"], arrow["ap_damage"], arrow["effective_range"]) == (18, 6, 123)
    assert "bow" not in patch["missile_weapons"] and "arrow" not in patch["projectiles"]
    alternate = next(iter(patch["missile_weapons_to_projectiles"].values()))
    fire_arrow = patch["projectiles"][alternate["projectile"]]
    assert (fire_arrow["damage"], fire_arrow["ap_damage"]) == (0, 6)
    blast = patch["projectiles_explosions"][fire_arrow["explosion_type"]]
    assert (blast["detonation_damage"], blast["detonation_damage_ap"]) == (3.0, 6.0)

    assert set(patch["unit_special_abilities"]) == {"fire_spell"}
    skill = patch["unit_special_abilities"]["fire_spell"]
    assert skill["recharge_time"] == 60.0
    assert skill["activated_projectile"] != alternate["projectile"]
    skill_arrow = patch["projectiles"][skill["activated_projectile"]]
    assert (skill_arrow["damage"], skill_arrow["ap_damage"]) == (0, 7)
    skill_blast = patch["projectiles_explosions"][skill_arrow["explosion_type"]]
    assert (skill_blast["detonation_damage"], skill_blast["detonation_damage_ap"]) == (3.25, 6.5)
    bombardment = patch["projectile_bombardments"][skill["bombardment"]]
    assert (bombardment["projectile_type"], bombardment["num_projectiles"]) == (skill["activated_projectile"], 8)
    vortex = patch["battle_vortexs"][skill["vortex"]]
    assert (vortex["damage"], vortex["damage_ap"], vortex["duration"]) == (26, 13, 4.0)
    second = patch["battle_vortexs"][vortex["subsequent_vortex"]]
    assert (second["damage"], second["damage_ap"]) == (13, 0)
    new_phase = second["contact_effect"]
    assert set(patch["special_ability_phases"]) == {new_phase}
    phase = patch["special_ability_phases"][new_phase]
    assert (phase["damage_amount"], phase["hp_change_frequency"]) == (26, 2.0)
    assert patch["special_ability_phase_stat_effects"][new_phase, "test_stat"]["value"] == 5.0
    assert len(patch["special_ability_to_special_ability_phase_junctions"]) == 1
    assert next(iter(patch["special_ability_to_special_ability_phase_junctions"].values()))["phase"] == new_phase
    assert report["skills"][0]["key"] == "fire_spell"

    previous = target.read_bytes()
    api._assets[mod.id] = mod
    duplicate = api.call("create_sfo_patch", [mod.id])
    assert not duplicate["ok"] and duplicate["error"]["message"].startswith("sfoPatch.exists|")
    assert target.read_bytes() == previous
    assert _effective_rows(_read_tables(vanilla))["projectiles"]["arrow"]["damage"] == 15
