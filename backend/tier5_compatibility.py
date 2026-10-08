"""Fill settlement-display tiers from enabled Pack data, without MOD-name lists."""

from __future__ import annotations

import re
import struct
from collections import defaultdict
from dataclasses import replace
from typing import Sequence

from .game_data import (
    DbSource, GameDataBuildResult, GameDataEntry, _Candidate,
    _collect_effective_rows, _generated_internal_name, _has_higher_priority,
    _table_row_key, patch_db_row_value,
)
from .settlement_schema import SETTLEMENT_SCHEMAS

LEVELS = "building_levels_tables"
CHAINS = "building_chains_tables"
UI = "building_culture_variants_tables"
UPGRADES = "building_upgrades_junction_tables"
IDS = "campaign_settlement_display_building_ids_tables"
MODEL_IDS = "campaign_settlement_display_building_model_ids_tables"
MODELS = "campaign_settlement_display_buildings_tables"
TIER5_SOURCE_PREFIXES = (
    *(f"db\\{table}\\" for table in SETTLEMENT_SCHEMAS),
    "script\\campaign\\", "script\\_lib\\",
)


def _whole_file_sources(sources: Sequence[DbSource]) -> tuple[DbSource, ...]:
    # A higher-priority Pack replaces an identical internal file in full.
    owners = {}
    for rank in sorted(range(len(sources)), key=lambda i: sources[i].role == "vanilla"):
        for entry in sources[rank].entries:
            owners.setdefault(entry.name.replace("/", "\\").casefold(), rank)
    result = []
    for rank, source in enumerate(sources):
        entries = []
        for entry in source.entries:
            name = entry.name.replace("/", "\\").casefold()
            if owners[name] != rank:
                continue
            entries.append(entry)
        result.append(DbSource(source.name, tuple(entries), role=source.role))
    return tuple(result)


def _clone(candidate: _Candidate, **changes) -> _Candidate:
    row = candidate.row
    for field, value in changes.items():
        row = patch_db_row_value(row, field, value)
    return replace(candidate, row=row)


def _by_chain(levels):
    chains = defaultdict(dict)
    for candidate in levels.values():
        values = candidate.row.values
        chains[str(values["chain"])][int(values["level"])] = candidate
    return chains


def _links_by_building(rows):
    result = defaultdict(list)
    for candidate in rows.values():
        result[str(candidate.row.values.get("building_level_key") or "")].append(candidate)
    return result


def _ui_templates(chain, group, tables):
    by_building = defaultdict(list)
    for candidate in tables[UI].values():
        by_building[str(candidate.row.values["building"])].append(candidate)
    for tier in sorted(group, key=lambda tier: (abs(tier - 3), tier)):
        building = str(group[tier].row.values["level_name"])
        if by_building.get(building):
            return by_building[building]
    # Display-only chains can omit UI entirely. Reuse a valid settlement UI
    # template so WH3's initializer has a paired row for every display level.
    superchain = tables[CHAINS][chain].row.values.get("building_superchain")
    choices = []
    for building, variants in by_building.items():
        level = tables[LEVELS].get(building)
        if level is None:
            continue
        original_chain = tables[CHAINS].get(str(level.row.values["chain"]))
        same_superchain = original_chain is not None and original_chain.row.values.get("building_superchain") == superchain
        priority = (not same_superchain, not variants[0].source_is_vanilla,
                    abs(int(level.row.values["level"]) - 3), building)
        choices.append((priority, variants))
    return min(choices, key=lambda item: item[0])[1] if choices else []


def build_tier5_compatibility_entries(sources: Sequence[DbSource]) -> GameDataBuildResult:
    tables = set(SETTLEMENT_SCHEMAS)
    all_candidates = {}
    raw = _collect_effective_rows(sources, tables, all_candidates=all_candidates)
    effective = _collect_effective_rows(_whole_file_sources(sources), tables)
    vanilla = _collect_effective_rows([s for s in sources if s.role == "vanilla"], tables)
    vanilla_chains = _by_chain(vanilla[LEVELS])
    raw_chains = _by_chain(raw[LEVELS])
    raw_links = _links_by_building(raw[IDS])
    model_pool = {}
    for candidates in all_candidates[MODELS].values():
        for candidate in candidates:
            model_id = str(candidate.row.values["model_id"])
            if model_id not in model_pool or _has_higher_priority(candidate, model_pool[model_id]):
                model_pool[model_id] = candidate
    # A display-only minor chain has a native three-tier definition in at least
    # one MOD. Existing compatibility Packs may already add higher tiers.
    native_minor = set()
    for source in sources:
        if source.role == "vanilla":
            continue
        levels = _by_chain(_collect_effective_rows([source], {LEVELS})[LEVELS])
        native_minor.update(chain for chain, group in levels.items() if max(group) == 3)
    output = {table: {} for table in tables}
    stats = {"candidate_chain_count": 0, "patched_chain_count": 0,
             "added_level_count": 0, "display_rows_changed": 0, "restored_row_count": 0,
             "invalid_chain_count": 0, "ui_rows_added": 0}

    def changed(table, candidate):
        original = vanilla[table].get(_table_row_key(table, candidate.row))
        return not candidate.source_is_vanilla and (original is None or original.row.raw != candidate.row.raw)

    def emit(table, candidate):
        key = _table_row_key(table, candidate.row)
        previous = effective[table].get(key)
        if previous is None or previous.row.raw != candidate.row.raw:
            output[table][key] = candidate
            effective[table][key] = candidate

    def restore(table, key):
        if key not in effective[table] and key in raw[table]:
            emit(table, raw[table][key])
            stats["restored_row_count"] += 1

    def model_available(model_id):
        return model_id in raw[MODEL_IDS] and model_id in model_pool

    def ensure_model(model_id):
        restore(MODEL_IDS, model_id)
        if any(c.row.values["model_id"] == model_id for c in effective[MODELS].values()):
            return
        original = model_pool[model_id]
        candidate = original
        key = str(original.row.values["key"])
        if key in effective[MODELS]:
            # Keep an unrelated model that owns the same numeric key.
            key_value = max(int(k) for k in effective[MODELS]) + 1
            if key_value > 2**63 - 1:
                raise ValueError("城市模型配置主键超出 I64 范围")
            candidate = _clone(original, key=key_value)
        emit(MODELS, candidate)
        stats["restored_row_count"] += 1

    for chain, group in sorted(raw_chains.items()):
        if 3 not in group:
            continue
        native = group[3]
        building3 = str(native.row.values["level_name"])
        links3 = raw_links.get(building3, [])
        original_minor = chain in vanilla_chains and max(vanilla_chains[chain]) == 3
        alias_minor = chain not in vanilla_chains and chain in native_minor
        if not (original_minor or alias_minor) or not links3:
            continue
        links3 = [c for c in links3 if changed(IDS, c) or (
            (model := model_pool.get(str(c.row.values["building_model_id"]))) is not None
            and changed(MODELS, model)
        )]
        if not links3 or (native.source_is_vanilla and not original_minor):
            continue
        stats["candidate_chain_count"] += 1
        if chain not in raw[CHAINS] or any(not model_available(c.row.values["building_model_id"]) for c in links3):
            stats["invalid_chain_count"] += 1
            continue
        ui_templates = _ui_templates(chain, group, raw)
        if not ui_templates:
            stats["invalid_chain_count"] += 1
            continue
        count_before = sum(len(rows) for rows in output.values())
        restore(CHAINS, chain)
        # Recover native records hidden by a same-path whole-table overlay.
        for tier in (0, 1, 2, 3):
            if tier not in group:
                continue
            building = str(group[tier].row.values["level_name"])
            restore(LEVELS, building)
            for link in raw_links.get(building, []):
                model_id = str(link.row.values["building_model_id"])
                if model_available(model_id):
                    restore(IDS, _table_row_key(IDS, link.row))
                    ensure_model(model_id)
            for key, variant in raw[UI].items():
                if variant.row.values["building"] == building:
                    restore(UI, key)
        current_group = _by_chain(effective[LEVELS])[chain]
        if 0 not in current_group and alias_minor:
            # Some display-only chains omit ruins entirely. A level-zero dummy
            # fills that display state without adding a real settlement level.
            missing_ruins = [str(link.row.values.get("building_level_key") or "")
                             for link in raw[IDS].values()
                             if str(link.row.values.get("building_level_key") or "").startswith(chain)
                             and "ruin" in str(link.row.values.get("building_level_key") or "").casefold()]
            ruin_name = missing_ruins[0] if missing_ruins else f"{chain}_wyccc_ruin"
            changes = {"level_name": ruin_name, "level": 0, "create_time": 1, "create_cost": 0,
                       "can_convert": False, "can_be_damaged": False}
            ruin_level = _clone(native, **{k: v for k, v in changes.items() if k in native.row.fields})
            emit(LEVELS, ruin_level)
            current_group[0] = ruin_level
            stats["added_level_count"] += 1
        for tier in (4, 5):
            level = current_group.get(tier)
            if level is None:
                match = re.fullmatch(r"(.*?)(\d+)", building3)
                name = (match[1] + str(tier).zfill(len(match[2]))) if match else f"{building3}_wyccc_tier{tier}"
                if name in effective[LEVELS]:
                    name = f"{building3}_wyccc_tier{tier}"
                level = _clone(native, level_name=name, level=tier)
                emit(LEVELS, level)
                current_group[tier] = level
                stats["added_level_count"] += 1
            building = str(level.row.values["level_name"])
            existing = _links_by_building(effective[IDS]).get(building, [])
            # Preserve complete native tier4/5 artwork; generic Tier5 mappings
            # to unmodified vanilla models yield to the city's actual model.
            preserve = existing and all(
                model_available(str(link.row.values["building_model_id"]))
                and (not original_minor or changed(MODELS, model_pool[str(link.row.values["building_model_id"])]))
                for link in existing
            )
            if preserve:
                for link in existing:
                    ensure_model(str(link.row.values["building_model_id"]))
            else:
                for index, link in enumerate(links3):
                    model_id = str(link.row.values["building_model_id"])
                    ensure_model(model_id)
                    key = str(existing[index].row.values["key"]) if index < len(existing) else building
                    if len(links3) > 1 and index >= len(existing):
                        key += f"_wyccc_{index}"
                    new = _clone(link, key=key, building_level_key=building)
                    if key not in effective[IDS] or effective[IDS][key].row.raw != new.row.raw:
                        stats["display_rows_changed"] += 1
                    emit(IDS, new)
        variant_buildings = {v.row.values["building"] for v in effective[UI].values()}
        for level in current_group.values():
            building = str(level.row.values["level_name"])
            if building not in variant_buildings:
                for variant in ui_templates:
                    emit(UI, _clone(variant, building=building))
                    stats["ui_rows_added"] += 1
        # Supply an absent ruin mapping from this city's lowest native model.
        if 0 in current_group:
            ruin = str(current_group[0].row.values["level_name"])
            if not _links_by_building(effective[IDS]).get(ruin):
                template = next((links[0] for tier, candidate in sorted(current_group.items())
                                 if tier > 0 and (links := raw_links.get(str(candidate.row.values["level_name"])))), links3[0])
                model_id = str(template.row.values["building_model_id"])
                # Use the original generic ruin when the native MOD does so for
                # its other cities, as DEER does for the missing shrine record.
                same_source_ruins = [link for link in raw[IDS].values()
                                     if link.source_rank == template.source_rank
                                     and str(link.row.values.get("building_model_id")) == "wh_main_building_human_ruin"]
                if same_source_ruins and model_available("wh_main_building_human_ruin"):
                    model_id = "wh_main_building_human_ruin"
                ensure_model(model_id)
                emit(IDS, _clone(template, key=ruin, building_level_key=ruin, building_model_id=model_id))
        for lower, upper in zip(sorted(current_group), sorted(current_group)[1:]):
            if upper != lower + 1:
                continue
            start = str(current_group[lower].row.values["level_name"])
            end = str(current_group[upper].row.values["level_name"])
            key = start + "\x1f" + end
            if key not in effective[UPGRADES]:
                template = next(iter(raw[UPGRADES].values()), None)
                if template:
                    emit(UPGRADES, _clone(template, **{"from": start, "to": end}))
        if sum(len(rows) for rows in output.values()) > count_before:
            stats["patched_chain_count"] += 1
    entries = []
    for table, rows in sorted(output.items()):
        grouped = defaultdict(list)
        for key, candidate in sorted(rows.items()):
            grouped[candidate.version].append(candidate.row)
        for version, records in sorted(grouped.items()):
            name = _generated_internal_name(raw[table], version, label="wyccc_tier5") + "_display"
            payload = b"\xfc\xfd\xfe\xff" + struct.pack("<i", version) + b"\1" + struct.pack("<i", len(records))
            entries.append(GameDataEntry(f"db\\{table}\\{name}", payload + b"".join(r.raw for r in records)))
    stats["output_row_count"] = sum(len(rows) for rows in output.values())
    return GameDataBuildResult(tuple(entries), stats)
