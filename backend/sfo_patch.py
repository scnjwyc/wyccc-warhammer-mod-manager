"""Build an isolated WH3 unit balance overlay from the installed Pack data."""

from __future__ import annotations

import hashlib
import re
import struct
from collections import defaultdict
from dataclasses import dataclass
from functools import cmp_to_key, lru_cache
from math import floor
from pathlib import Path

from .game_data import _compare_internal_names
from .schema_update import VERSION_MARKER, _encode_value, db_table_name, decode_table
from .pack_reader import read_pack_layout
from .start_options import PackEntry, read_pack_entries
from .table_schema import load_latest_schema

SFO_PACK = "sfo_grimhammer_3_main.pack"
LAND = "land_units"
MAIN = "main_units"
ENTITY = "battle_entities"
MOUNT = "mounts"
ENGINE = "battlefield_engines"
EXTRA = "land_units_to_extra_engines"
ARMOUR = "unit_armour_types"
MELEE = "melee_weapons"
MISSILE = "missile_weapons"
AMMO = "missile_weapons_to_projectiles"
CONDITIONAL = "unit_missile_weapon_junctions"
ENTITY_STATS = "battle_entity_stats"
ENGINE_ANIMATION = "unit_component_animation_table_junctions"
PROJECTILE = "projectiles"
EXPLOSION = "projectiles_explosions"
SHRAPNEL = "projectile_shrapnels"
PROJECTILE_EFFECT = "effect_bonus_value_projectile_junctions"
ABILITY = "unit_special_abilities"
PHASE = "special_ability_phases"
ABILITY_PHASE = "special_ability_to_special_ability_phase_junctions"
VORTEX = "battle_vortexs"
BOMBARDMENT = "projectile_bombardments"
SPREADING = "special_ability_spreadings"
UNIT_SET_PHASE = "unit_set_special_ability_phase_junctions"
UNIT_SET_EFFECT = "effect_bonus_value_unit_set_special_ability_phase_junctions"
PHASE_ATTACHMENTS = {
    "special_ability_phase_attribute_effects": ("phase", ("attribute", "phase")),
    "special_ability_phase_stat_effects": ("phase", ("phase", "stat")),
    "special_ability_contact_phase_groups": ("contact_phase_id", ("contact_phase_id", "contact_phase_group_id")),
    "special_ability_phases_to_additional_ui_effects_junctions": (
        "special_ability_phase", ("effect", "special_ability_phase"),
    ),
    "effect_bonus_value_special_ability_phase_record_junctions": (
        "special_ability_phase", ("bonus_value_id", "effect", "special_ability_phase"),
    ),
}
KEYS = {
    **dict.fromkeys(
        (LAND, ENTITY, MOUNT, ENGINE, ARMOUR, MELEE, MISSILE, PROJECTILE, EXPLOSION, SHRAPNEL, ENTITY_STATS), ("key",),
    ),
    MAIN: ("unit",),
    EXTRA: ("land_unit", "attach_articulation", "battle_engine"),
    AMMO: ("missile_weapon", "projectile"),
    CONDITIONAL: ("id",),
    ENGINE_ANIMATION: ("id",),
    PROJECTILE_EFFECT: ("effect", "bonus_value", "projectile"),
    ABILITY: ("key",),
    PHASE: ("id",),
    ABILITY_PHASE: ("order", "special_ability", "target_self", "target_friends", "target_enemies"),
    VORTEX: ("vortex_key",),
    BOMBARDMENT: ("bombardment_key",),
    SPREADING: ("key",),
    UNIT_SET_PHASE: ("key",),
    UNIT_SET_EFFECT: ("bonus_value_id", "effect", "unit_set_special_ability_phase_junction"),
    **{table: fields for table, (_, fields) in PHASE_ATTACHMENTS.items()},
}
SKILL_FACTOR = 1.30
SKILL_LINKS = {
    ABILITY: {"activated_projectile": PROJECTILE, "bombardment": BOMBARDMENT, "vortex": VORTEX},
    PHASE: {"imbue_contact": PHASE, "spreading": SPREADING},
    SPREADING: {"phase": PHASE},
    PROJECTILE: {
        "explosion_type": EXPLOSION, "overhead_stat_effect": PHASE, "contact_stat_effect": PHASE,
        "spawned_vortex": VORTEX,
    },
    EXPLOSION: {"shrapnel": SHRAPNEL, "contact_phase_effect": PHASE},
    SHRAPNEL: {"projectile": PROJECTILE},
    VORTEX: {"contact_effect": PHASE, "subsequent_vortex": VORTEX},
    BOMBARDMENT: {"projectile_type": PROJECTILE},
}
SKILL_DAMAGE = {
    PHASE: ("damage_amount",),
    VORTEX: ("damage", "damage_ap"),
    PROJECTILE: ("damage", "ap_damage"),
    EXPLOSION: ("detonation_damage", "detonation_damage_ap"),
}
PREFIXES = tuple(f"db\\{table}_tables\\" for table in KEYS)
FALLBACK = {
    # Health factor, health rounding step, melee factor.
    "infantry": (1.70, 5, 1.15),
    "ranged_infantry": (1.60, 5, 1.15),
    "cavalry": (1.95, 5, 1.25),
    "ranged_cavalry": (1.80, 5, None),
    "monstrous_infantry": (1.65, 25, 1.125),
    "monstrous_cavalry": (2.10, 50, 1.125),
    "monster": (1.25, 250, 1.05),
    "hero": (1.28, 250, 1.05),
    "lord": (1.25, 250, 1.05),
    "mounted_hero": (1.23, 250, 1.05),
    "mounted_lord": (1.20, 250, 1.05),
    "complex": (None, 5, None),
}


@dataclass(frozen=True)
class Row:
    version: int
    cells: dict
    source: str

    def __getitem__(self, field):
        return self.cells[field][0]

    def get(self, field, default=None):
        return self.cells.get(field, (default,))[0]


@lru_cache(maxsize=1)
def _schemas():
    return load_latest_schema("warhammer3", Path(), prefer_bundled=True)[0]


def _read_tables(path):
    if read_pack_layout(path) is None:
        raise ValueError(f"sfoPatch.readFailed|{path.name}")
    result = []
    for entry in read_pack_entries(path, PREFIXES):
        name = entry.name.replace("/", "\\").casefold()
        table = db_table_name(name).removesuffix("_tables")
        try:
            definition, data, _ = decode_table(entry.payload, _schemas()[table + "_tables"])
        except ValueError as exc:
            raise ValueError(f"sfoPatch.readFailed|{path.name}/{name}") from exc
        fields = [field["name"] for field in definition["fields"]]
        rows = [Row(definition["version"], dict(zip(fields, row)), path.name) for row in data]
        result.append((table, name.rsplit("\\", 1)[-1], rows))
    return result


def _effective_rows(*layers):
    result = {table: {} for table in KEYS}
    seen = set()
    # The final layer is vanilla. Within the MOD layer, DB file names
    # determine priority, with Pack order breaking ties across identical paths.
    order = cmp_to_key(_compare_internal_names)
    for files in (sorted((file for layer in layers[:-1] for file in layer), key=lambda f: order(f[1])),
                  sorted(layers[-1], key=lambda f: order(f[1]))):
        for table, name, rows in files:
            if (table, name) in seen:
                continue
            seen.add((table, name))
            for row in rows:
                key = tuple(row[field] for field in KEYS[table])
                result[table].setdefault(key[0] if len(key) == 1 else key, row)
    return result


def _group(rows, field):
    result = defaultdict(list)
    for row in rows.values():
        result[row[field]].append(row)
    return result


def _round(value, step=1):
    return floor(value / step + 0.5) * step


def _damage_split(base, ap, factor, step=1):
    total = base + ap
    if total == 0:
        return base, ap
    scaled = _round(total * factor, step)
    scaled_ap = _round(scaled * ap / total, step)
    if step > 1 and ((base > 0 and scaled_ap == scaled) or (ap > 0 and scaled_ap == 0)):
        return _damage_split(base, ap, factor)
    return scaled - scaled_ap, scaled_ap


def _culture(*keys):
    for key in keys:
        match = re.match(r"wh\d*_[a-z0-9]+_([a-z]{3})_", key or "")
        if match:
            return match[1]
    return ""


@dataclass(frozen=True)
class Profile:
    main: Row
    land: Row
    engines: tuple
    man_hp: int
    mount_hp: int
    engine_hps: tuple
    topology: tuple
    kind: str
    culture: str
    armour: Row | None
    weapon: Row | None

    @property
    def men(self):
        return self.main["num_men"]

    @property
    def crew_hp(self):
        return self.man_hp + self.land["bonus_hit_points"]

    @property
    def hp_per_model(self):
        return self.crew_hp + self.mount_hp


def _profile(db, main, land, extra, *, structure=None):
    key = land["key"]
    man = db[ENTITY][land["man_entity"]]
    mount = db[MOUNT].get(land["mount"])
    engine_slots = []
    if land["engine"]:
        engine_slots.append((land["engine"], max(1, land["num_engines"])))
    engine_slots.extend((row["battle_engine"], 1) for row in extra.get(key, ()))
    engines = tuple(db[ENGINE][name] for name, _ in engine_slots)
    mount_hp = db[ENTITY][mount["entity"]]["hit_points"] if mount else 0
    if land["mount"] and mount is None:
        raise KeyError(land["mount"])
    engine_hps = tuple(db[ENTITY][engine["battle_entity"]]["hit_points"] for engine in engines)
    men, mounts = main["num_men"], land["num_mounts"]
    if men <= 0:
        raise ValueError("sfoPatch.formation")
    caste, category = main["caste"], land["category"]
    ranged = bool(land["primary_missile_weapon"]) or category == "inf_ranged"
    monstrous = (
        caste == "monster" or category == "war_beast"
        or "monster" in land["spacing"] or "monstrous" in land["spacing"]
    )
    if structure is not None:
        kind = structure.kind
    elif (
        engines or category in {"artillery", "war_machine"} or land["class"] == "chariot"
        or caste in {"artillery", "warmachine", "war_machine"} or (mount and mounts != men)
    ):
        kind = "complex"
    elif caste in {"hero", "lord"}:
        kind = f"mounted_{caste}" if mount else caste
    elif monstrous and men == 1:
        kind = "monster"
    elif mount or category == "cavalry":
        kind = "monstrous_cavalry" if monstrous else "ranged_cavalry" if ranged else "cavalry"
    elif monstrous:
        kind = "monstrous_infantry"
    else:
        kind = "ranged_infantry" if ranged else "infantry"
    topology = (men, mounts, bool(mount), tuple(
        (engine["engine_type"], count) for engine, (_, count) in zip(engines, engine_slots)
    ), bool(land["engine"]))
    return Profile(main, land, engines, man["hit_points"], mount_hp, engine_hps,
                   topology, kind, _culture(main["unit"], key, land["man_entity"]),
                   db[ARMOUR][land["armour"]], db[MELEE][land["primary_melee_weapon"]])


def _references(vanilla, sfo):
    original_extra, sfo_extra = (_group(db[EXTRA], "land_unit") for db in (vanilla, sfo))
    result = defaultdict(list)
    for key, main in vanilla[MAIN].items():
        current = sfo[MAIN].get(key)
        if not current or current["land_unit"] not in sfo[LAND] or main["land_unit"] not in vanilla[LAND]:
            continue
        try:
            before = _profile(vanilla, main, vanilla[LAND][main["land_unit"]], original_extra)
            after = _profile(sfo, current, sfo[LAND][current["land_unit"]], sfo_extra)
        except (KeyError, ValueError):
            continue
        if before.topology == after.topology and before.hp_per_model > 0 and after.hp_per_model > 0:
            result[_reference_group(before)].append((before, after))
    return result


def _reference_group(unit):
    # A reference must preserve its own formation in SFO. The target can
    # have a different number of models in the same formation type.
    _, mounts, has_mount, engines, primary = unit.topology
    return unit.kind, bool(mounts), has_mount, tuple(kind for kind, _ in engines), primary


def _reference(unit, candidates):
    same_unit = next((pair for pair in candidates if pair[0].main["unit"] == unit.main["unit"]), None)
    if same_unit:
        return same_unit
    plausible = []
    for before, after in candidates:
        same_weapon = bool(unit.weapon and before.weapon
                           and unit.weapon["melee_weapon_type"] == before.weapon["melee_weapon_type"])
        same_culture = bool(unit.culture and unit.culture == before.culture)
        tier_gap = abs(unit.main.get("tier", 0) - before.main.get("tier", 0))
        strength = abs(before.hp_per_model - unit.hp_per_model) / max(1, unit.hp_per_model)
        if unit.kind == "complex":
            if unit.land["category"] != before.land["category"]:
                continue
        elif not ((same_culture or (not unit.culture and unit.kind == "ranged_cavalry" and same_weapon))
                  and strength <= 0.35 and tier_gap <= 1):
            continue
        rank = (not same_culture, unit.land["class"] != before.land["class"],
                unit.topology != before.topology, tier_gap, not same_weapon, strength, before.main["unit"])
        plausible.append((rank, before, after))
    best = min(plausible, default=None, key=lambda item: item[0])
    return best[1:] if best else (None, None)


class Overlay:
    def __init__(self, tag, tables):
        self.tag = tag
        self.tables = tables
        self.edits = {}

    def put(self, table, row, **changes):
        key = tuple(changes.get(field, row[field]) for field in KEYS[table])
        self.edits[table, key] = (row, changes)

    def clone_key(self, table, original, scope=""):
        digest = hashlib.sha256(f"{scope}\0{original}".encode("utf-8")).hexdigest()[:20]
        new = f"wyccc_sfo_{self.tag}_{digest}"
        if new in self.tables[table]:
            raise ValueError(f"sfoPatch.keyCollision|{new}")
        return new

    def clone(self, table, row, scope="", **changes):
        field, = KEYS[table]
        new = self.clone_key(table, row[field], scope)
        self.put(table, row, **{field: new}, **changes)
        return new

    def copy_engine_animation(self, row, engine):
        seed = hashlib.sha256(f"{engine}/{row['id']}".encode("utf-8")).digest()
        new_id = int.from_bytes(seed[:4], "little") & 0x7fffffff
        if new_id in self.tables[ENGINE_ANIMATION] or (ENGINE_ANIMATION, (new_id,)) in self.edits:
            raise ValueError(f"sfoPatch.keyCollision|{new_id}")
        self.put(ENGINE_ANIMATION, row, id=new_id, engine=engine)

    def entries(self, priority):
        grouped = defaultdict(list)
        for (table, _), (row, changes) in sorted(self.edits.items()):
            grouped[table, row.version].append((row, changes))
        result = []
        for (table, version), rows in sorted(grouped.items()):
            definitions = _schemas()[table + "_tables"]
            definition = next(d for d in definitions if d["version"] == version)
            fields = definition["fields"]
            marker = VERSION_MARKER + struct.pack("<i", version) if version > 0 else b""
            payload = marker + struct.pack("<BI", 1, len(rows)) + b"".join(
                _encode_value(changes[field["name"]], field["type"]) if field["name"] in changes
                else row.cells[field["name"]][1]
                for row, changes in rows for field in fields
            )
            decode_table(payload, [definition])
            name = f"db\\{table}_tables\\{'!' * priority}wyccc_sfo_{self.tag}_v{version:04d}"
            result.append(PackEntry(name, payload))
        return result


def _missile_overlay(base, overlay, report):
    ammo = _group(base[AMMO], "missile_weapon")
    effects = _group(base[PROJECTILE_EFFECT], "projectile")
    projectiles = {}

    def projectile(key):
        if key in projectiles:
            return projectiles[key]
        row = base[PROJECTILE][key]
        original = (row["damage"], row["ap_damage"])
        direct = _damage_split(*original, 1.20)
        changes = dict(zip(("damage", "ap_damage"), direct))
        # Reserve the key before following shrapnel so circular links are safe.
        new = projectiles[key] = overlay.clone(PROJECTILE, row, **changes)
        stats = {"key": key, "direct": (original, direct)}
        if row["explosion_type"]:
            explosion = base[EXPLOSION][row["explosion_type"]]
            fields = ("detonation_damage", "detonation_damage_ap")
            old = tuple(explosion[field] for field in fields)
            scaled = tuple(value * 1.20 for value in old)
            explosive = dict(zip(fields, scaled))
            if shrapnel_key := explosion.get("shrapnel"):
                shrapnel = base[SHRAPNEL][shrapnel_key]
                explosive["shrapnel"] = overlay.clone(SHRAPNEL, shrapnel, projectile=projectile(shrapnel["projectile"]))
            changes["explosion_type"] = overlay.clone(EXPLOSION, explosion, **explosive)
            overlay.put(PROJECTILE, row, key=new, **changes)
            stats["explosion"] = (old, scaled)
        for effect in effects.get(key, ()):
            overlay.put(PROJECTILE_EFFECT, effect, projectile=new)
        report.append(stats)
        return new

    @lru_cache(maxsize=None)
    def missile(key):
        row = base[MISSILE][key]
        default = projectile(row["default_projectile"]) if row["default_projectile"] else ""
        new = overlay.clone(MISSILE, row, default_projectile=default)
        for alternate in ammo.get(key, ()):
            overlay.put(AMMO, alternate, missile_weapon=new, projectile=projectile(alternate["projectile"]))
        return new

    return missile


def _balance_unit(unit, env, ref, base, overlay, conditional, engine_users, animations, aliases):
    land = unit.land
    name = land["key"]
    before, after = ref
    health_factor, step, melee_factor = FALLBACK[unit.kind]
    character = unit.main["caste"] in {"hero", "lord"}
    attack = land["melee_attack"] + ((1 if character else 2) if not before else
                                    after.land["melee_attack"] - before.land["melee_attack"])
    defence = land["melee_defence"] + (after.land["melee_defence"] - before.land["melee_defence"] if before else 0)
    changes = {
        "melee_attack": max(0, attack if before else _round(attack, 5)),
        "melee_defence": max(0, defence if before else _round(defence, 5)),
    }
    report = {"unit": name, "reference": before.main["unit"] if before else "",
              "issues": [], "stats": {}, "projectiles": [], "shared_engines": []}
    stats = report["stats"]
    stats.update({f: (land[f], changes[f]) for f in ("melee_attack", "melee_defence")})
    if unit.armour:
        original = value = unit.armour["armour_value"]
        if before and before.armour and after.armour:
            value = max(0, original + after.armour["armour_value"] - before.armour["armour_value"])
        if not env.armour or value != env.armour["armour_value"]:
            changes["armour"] = overlay.clone(ARMOUR, unit.armour, name, armour_value=value)
        stats["armour"] = (original, value)
    if before and before.weapon and after.weapon and unit.weapon and (
        before.weapon["melee_weapon_type"] == unit.weapon["melee_weapon_type"]
        or before.main["unit"] == unit.main["unit"]
    ):
        old_total = before.weapon["damage"] + before.weapon["ap_damage"]
        if old_total > 0:
            melee_factor = (after.weapon["damage"] + after.weapon["ap_damage"]) / old_total
    if unit.weapon and melee_factor is not None:
        original = (unit.weapon["damage"], unit.weapon["ap_damage"])
        damage = _damage_split(*original, melee_factor, 5 if min(original) >= 5 and sum(original) >= 20 else 1)
        changes["primary_melee_weapon"] = overlay.clone(
            MELEE, unit.weapon, name, damage=damage[0], ap_damage=damage[1],
        )
        stats["melee"] = (original, damage)
    elif unit.weapon:
        report["issues"].append("meleeReference")
    report["melee_factor"] = melee_factor

    engine_targets = unit.engine_hps
    if unit.kind == "complex":
        crew, mount_hp = unit.crew_hp, unit.mount_hp
        if before:
            def part_hp(value, old, new):
                return max(0, _round(value * new / old if old else value + new - old))

            crew = part_hp(unit.crew_hp, before.crew_hp, after.crew_hp)
            mount_hp = part_hp(unit.mount_hp, before.mount_hp, after.mount_hp)
            engine_targets = tuple(part_hp(value, old, new) for value, old, new in
                                   zip(unit.engine_hps, before.engine_hps, after.engine_hps))
        else:
            report["issues"].append("healthReference")
        if land["mount"] and mount_hp != env.mount_hp:
            mount = base[MOUNT][land["mount"]]
            entity = overlay.clone(ENTITY, base[ENTITY][mount["entity"]], name + "/mount", hit_points=mount_hp)
            changes["mount"] = overlay.clone(MOUNT, mount, name, entity=entity)
        changes["bonus_hit_points"] = crew - env.man_hp
        stats["crew_hp"] = (unit.crew_hp, crew)
        if land["mount"]:
            stats["mount_hp"] = (unit.mount_hp, mount_hp)
    else:
        if before:
            health_factor = after.hp_per_model / before.hp_per_model
        hp = max(step, _round(unit.hp_per_model * health_factor, step))
        changes["bonus_hit_points"] = hp - env.man_hp - env.mount_hp
        stats["hp"] = (unit.hp_per_model, hp)
    report["health_factor"] = health_factor

    missile = _missile_overlay(base, overlay, report["projectiles"])
    if land["primary_missile_weapon"]:
        changes["primary_missile_weapon"] = missile(land["primary_missile_weapon"])
    for main in aliases:
        for junction in conditional.get(main["unit"], ()):
            edits = {}
            if junction["missile_weapon"]:
                edits["missile_weapon"] = missile(junction["missile_weapon"])
            if stats_key := junction.get("battle_entity_stats_override"):
                stats_row = base[ENTITY_STATS][stats_key]
                if weapon := stats_row["primary_missile_weapon"]:
                    edits["battle_entity_stats_override"] = overlay.clone(
                        ENTITY_STATS, stats_row, primary_missile_weapon=missile(weapon),
                    )
            if edits:
                overlay.put(CONDITIONAL, junction, **edits)
    engines = []
    for index, (engine, old_hp, env_hp, target_hp) in enumerate(
        zip(unit.engines, unit.engine_hps, env.engine_hps, engine_targets)
    ):
        key = engine["key"]
        engine_missile = engine["missile_weapon"]
        direct = index == 0 and land["engine"]
        if not direct and engine_users[key] - {name}:
            if engine_missile or target_hp != env_hp:
                report["shared_engines"].append((key, target_hp != env_hp))
            engines.append((old_hp, env_hp))
            continue
        edits = {}
        if engine_missile:
            edits["missile_weapon"] = missile(engine_missile)
        if target_hp != env_hp:
            entity = base[ENTITY][engine["battle_entity"]]
            edits["battle_entity"] = overlay.clone(ENTITY, entity, name + "/engine", hit_points=target_hp)
        if edits:
            if direct:
                changes["engine"] = overlay.clone(ENGINE, engine, name, **edits)
                for animation in animations.get(key, ()):
                    overlay.copy_engine_animation(animation, changes["engine"])
            else:
                # All key fields of the extra-engine junction are immutable.
                # Updating its exclusive engine avoids adding a second socket.
                overlay.put(ENGINE, engine, **edits)
        engines.append((old_hp, target_hp))
    if engines:
        stats["engine_hp"] = engines
    overlay.put(LAND, land, **changes)
    return report


def _patch_shared_engines(output, reports, engine_users, base):
    completed = {report["unit"] for report in reports if not report.get("skipped")}
    shared = {}
    for report in reports:
        for key, keep_hp in report.pop("shared_engines", ()):
            if key not in shared:
                engine = base[ENGINE][key]
                projectiles = []
                missile_key = engine["missile_weapon"]
                if engine_users[key] <= completed and missile_key:
                    overlay = Overlay(output.tag, output.tables)
                    try:
                        new_missile = _missile_overlay(base, overlay, projectiles)(missile_key)
                    except KeyError:
                        projectiles.clear()
                    else:
                        overlay.put(ENGINE, engine, missile_weapon=new_missile)
                        output.edits.update(overlay.edits)
                shared[key] = projectiles
            projectiles = shared[key]
            known = {row["key"] for row in report["projectiles"]}
            report["projectiles"].extend(row for row in projectiles if row["key"] not in known)
            if (keep_hp or not projectiles) and "sharedEngine" not in report["issues"]:
                report["issues"].append("sharedEngine")


def _skill_damage(table, row):
    fields = SKILL_DAMAGE.get(table, ())
    old = tuple(row[field] for field in fields)
    if not any(value > 0 for value in old):
        return {}
    if table == EXPLOSION:
        new = tuple(value * SKILL_FACTOR for value in old)
    elif table == PHASE:
        new = (_round(old[0] * SKILL_FACTOR),)
    else:
        new = _damage_split(*old, SKILL_FACTOR)
    return {field: (before, after) for field, before, after in zip(fields, old, new) if before != after}


def _skill_graph(base, root, junctions):
    """Clone only records on a path to damage, including cycles through contact effects."""
    graph = {}
    damage = {}
    parents = defaultdict(set)
    missing = set()
    pending = [root, *((PHASE, row["phase"]) for row in junctions if row["phase"])]
    for node in pending:
        if node in graph or node in missing:
            continue
        table, key = node
        row = base[table].get(key)
        if row is None:
            missing.add(node)
            continue
        branches = {
            field: (target, row[field])
            for field, target in SKILL_LINKS[table].items()
            if row.get(field)
        }
        graph[node] = branches
        if edits := _skill_damage(table, row):
            damage[node] = edits
        for child in branches.values():
            parents[child].add(node)
            pending.append(child)

    affected = set(damage)
    pending = list(damage)
    for child in pending:
        unseen = parents[child] - affected
        affected.update(unseen)
        pending.extend(unseen)
    return graph, damage, affected, missing


def _patch_skill_damage(base, authored, output, source_name):
    # An inherited vanilla spell keeps its existing balance. A selected Pack
    # owns an ability when it defines its battle record or replaces its phases.
    phases = _group(base[ABILITY_PHASE], "special_ability")
    targets = {key for key, row in base[ABILITY].items() if row.source == source_name}
    targets.update(
        row["special_ability"] for row in base[ABILITY_PHASE].values()
        if row.source == source_name or row["phase"] in authored[PHASE]
    )
    attachments = {
        table: (field, _group(base[table], field))
        for table, (field, _) in PHASE_ATTACHMENTS.items()
    }
    sets = _group(base[UNIT_SET_PHASE], "special_ability_phase")
    set_effects = _group(base[UNIT_SET_EFFECT], "unit_set_special_ability_phase_junction")
    projectile_effects = _group(base[PROJECTILE_EFFECT], "projectile")
    reports = []
    for key in sorted(targets):
        root = (ABILITY, key)
        junctions = phases[key]
        graph, damage, affected, missing = _skill_graph(base, root, junctions)
        if missing and root in missing:
            affected.clear()
            damage.clear()
        if not damage and not missing:
            continue
        aliases = {
            (table, node_key): output.clone_key(table, node_key, "skill")
            for table, node_key in affected if table != ABILITY
        }
        for node in sorted(affected):
            table, node_key = node
            row = base[table][node_key]
            edits = {field: target for field, (_, target) in damage.get(node, {}).items()}
            edits.update({field: aliases[child] for field, child in graph[node].items() if child in aliases})
            if node in aliases:
                edits[KEYS[table][0]] = new = aliases[node]
                if table == PHASE:
                    for attachment, (field, grouped) in attachments.items():
                        for link in grouped[node_key]:
                            output.put(attachment, link, **{field: new})
                    for link in sets[node_key]:
                        set_key = output.clone(UNIT_SET_PHASE, link, "skill", special_ability_phase=new)
                        for effect in set_effects[link["key"]]:
                            output.put(UNIT_SET_EFFECT, effect, unit_set_special_ability_phase_junction=set_key)
                elif table == PROJECTILE:
                    for effect in projectile_effects[node_key]:
                        output.put(PROJECTILE_EFFECT, effect, projectile=new)
            output.put(table, row, **edits)
        if root not in missing:
            for link in junctions:
                if new := aliases.get((PHASE, link["phase"])):
                    output.put(ABILITY_PHASE, link, phase=new)
        reports.append({
            "key": key,
            "damage": [
                {"key": node_key, "table": table, "stats": edits}
                for (table, node_key), edits in sorted(damage.items())
            ],
            "missing": [node_key for _, node_key in sorted(missing)],
        })
    return reports


def build_sfo_patch(source: Path, vanilla_path: Path, sfo_path: Path, dependencies=()):
    """Return DB-only Pack entries and a per-unit before/after report."""
    vanilla_files, sfo_files, source_files = map(_read_tables, (vanilla_path, sfo_path, source))
    dependency_files = tuple(map(_read_tables, dependencies))
    vanilla = _effective_rows(vanilla_files)
    sfo = _effective_rows(sfo_files, vanilla_files)
    authored = _effective_rows(source_files)
    base = _effective_rows(source_files, *dependency_files, vanilla_files)
    env = _effective_rows(source_files, *dependency_files, sfo_files, vanilla_files)
    targets = {key for key, row in base[LAND].items() if key in authored[LAND] and row.source == source.name}
    main_units = _group(base[MAIN], "land_unit")
    extras, env_extras = (_group(db[EXTRA], "land_unit") for db in (base, env))
    conditional = _group(base[CONDITIONAL], "unit")
    animations = _group(base[ENGINE_ANIMATION], "engine")
    engine_users = defaultdict(set)
    for row in env[LAND].values():
        engine_users[row["engine"]].add(row["key"])
    for row in env[EXTRA].values():
        engine_users[row["battle_engine"]].add(row["land_unit"])
    refs = _references(vanilla, sfo)
    tag = hashlib.sha256(source.name.casefold().encode("utf-8")).hexdigest()[:12]
    output = Overlay(tag, env)
    reports = []
    for key in sorted(targets):
        aliases = main_units.get(key, ())
        land = base[LAND][key]
        if not aliases:
            reports.append({"unit": key, "issues": ["formation"], "skipped": True})
            continue
        # Prefer the selected Pack's main unit when other units reuse its land key.
        main = min(aliases, key=lambda row: (row.source != source.name, row["unit"] != key, row["unit"]))
        if any(row["num_men"] != main["num_men"] for row in aliases):
            reports.append({"unit": key, "issues": ["formation"], "skipped": True})
            continue
        overlay = Overlay(tag, env)
        try:
            unit = _profile(base, main, land, extras)
            effective = _profile(env, main, land, env_extras, structure=unit)
            if unit.topology != effective.topology:
                reports.append({"unit": key, "issues": ["formation"], "skipped": True})
                continue
            reference = _reference(unit, refs[_reference_group(unit)])
            report = _balance_unit(unit, effective, reference, base, overlay, conditional, engine_users, animations, aliases)
            for alias in aliases:
                loaded = env[MAIN].get(alias["unit"])
                if not loaded or (loaded["land_unit"], loaded["num_men"]) != (key, unit.men):
                    overlay.put(MAIN, alias)
        except KeyError as exc:
            report = {"unit": key, "issues": ["missingRecord"], "detail": str(exc.args[0]), "skipped": True}
        except ValueError as exc:
            if str(exc) != "sfoPatch.formation":
                raise
            report = {"unit": key, "issues": ["formation"], "skipped": True}
        else:
            for (table, row_key), value in overlay.edits.items():
                if table == ENGINE_ANIMATION and (earlier := output.edits.get((table, row_key))) and earlier != value:
                    raise ValueError(f"sfoPatch.keyCollision|{row_key[0]}")
            output.edits.update(overlay.edits)
        reports.append(report)
    _patch_shared_engines(output, reports, engine_users, base)
    skills = _patch_skill_damage(base, authored, output, source.name)
    priority = 1 + max(
        (len(name) - len(name.lstrip("!")) for layer in (source_files, sfo_files, *dependency_files)
         for _, name, _ in layer),
        default=0,
    )
    return output.entries(priority), reports, skills
