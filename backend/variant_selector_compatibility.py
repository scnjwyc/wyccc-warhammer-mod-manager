"""Resolve character art sets and generate registrations through Variant Selector's API."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Sequence

from .game_data import (
    VARIANT_SELECTOR_TABLE_ORDER,
    DbSource,
    GameDataBuildResult,
    GameDataEntry,
    _collect_effective_rows,
)

VARIANT_SELECTOR_SCRIPT_NAME = "script\\campaign\\mod\\wyccc_variant_selector_patch.lua"
VARIANT_SELECTOR_FRAMEWORK_SCRIPT = "script\\campaign\\mod\\marthvariantselector.lua"
VARIANT_SELECTOR_SOURCE_PREFIXES = (
    *(f"db\\{name}\\" for name in VARIANT_SELECTOR_TABLE_ORDER),
    VARIANT_SELECTOR_FRAMEWORK_SCRIPT,
)

# These rows describe quick/quest-battle forms, often changing a hero into a
# general. Do not offer them as campaign appearances. Avoid matching words
# such as "questing" in an ordinary character's key.
_BATTLE_ONLY = re.compile(r"(?:^|_)(?:qb\d*|quick_battle|quest_battle)(?:_|$)", re.I)


def _clean_key(value: Any) -> str:
    return str(value or "").strip()


def _lua_string(value: str) -> str:
    escaped = []
    for char in value:
        if char in ('\\', '"'):
            escaped.append("\\" + char)
        elif ord(char) < 32 or ord(char) == 127:
            escaped.append(f"\\{ord(char):03d}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


_LUA_RUNTIME = r'''
local SAVE_KEY = "wyccc_variant_selector_patch_art_sets_v1"
local selected = {}
local owned = {}

local function live_character(cqi)
    cqi = tonumber(cqi)
    if not cqi then return nil end
    local character = cm:get_character_by_cqi(cqi)
    if character and not character:is_null_interface() then return character end
end

local function managed_variants(character)
    if not character or type(marthvs) ~= "table" then return nil end
    local subtype = character:character_subtype_key()
    local expected = AUTO_VARIANTS[subtype]
    local variants = marthvs:get_subtype_variants(subtype)
    -- Relinquish ownership if another adaptation replaces or edits our list.
    if not owned[subtype] or variants ~= owned[subtype] or #variants ~= #expected then
        return nil
    end
    for index, art_set in ipairs(expected) do
        if variants[index] ~= art_set then return nil end
    end
    return variants
end

local function apply(character, variants, index)
    local cqi = character:command_queue_index()
    marthvs:set_character_variant_index(cqi, index)
    cm:add_unit_model_overrides("character_cqi:" .. tostring(cqi), variants[index])
end

local function reapply_selected()
    local applied = 0
    -- Only explicitly selected appearances are restored. Unselected characters
    -- keep the appearance assigned by the game, including random variants.
    for cqi, record in pairs(selected) do
        local character = live_character(cqi)
        local variants = managed_variants(character)
        if variants and type(record) == "table"
            and record.subtype == character:character_subtype_key()
        then
            local found = false
            for index, art_set in ipairs(variants) do
                if art_set == record.art_set then
                    apply(character, variants, index)
                    applied = applied + 1
                    found = true
                    break
                end
            end
            if not found then
                -- A removed appearance has no safe numeric-index fallback.
                selected[cqi] = nil
                marthvs:set_character_variant_index(tonumber(cqi), nil)
            end
        end
    end
    return applied
end

cm:add_saving_game_callback(function(context)
    for cqi, record in pairs(selected) do
        local character = live_character(cqi)
        if not character or type(record) ~= "table"
            or record.subtype ~= character:character_subtype_key()
            or not managed_variants(character)
        then
            selected[cqi] = nil
        end
    end
    cm:save_named_value(SAVE_KEY, selected, context)
end)

cm:add_loading_game_callback(function(context)
    local saved = cm:load_named_value(SAVE_KEY, {}, context)
    selected = type(saved) == "table" and saved or {}
end)

cm:add_first_tick_callback(function()
    local function initialize(attempt)
        if type(marthvs) ~= "table"
            or type(marthvs.get_subtype_variants) ~= "function"
            or type(marthvs.set_subtype_variants) ~= "function"
            or type(marthvs.set_character_variant_index) ~= "function"
        then
            if attempt < 5 then
                cm:callback(function() initialize(attempt + 1) end, 1)
            end
            return
        end
        local added = 0
        for subtype, variants in pairs(AUTO_VARIANTS) do
            -- Even an empty manual list is intentional and must be preserved.
            if marthvs:get_subtype_variants(subtype) == nil then
                local copy = {}
                for index, art_set in ipairs(variants) do copy[index] = art_set end
                marthvs:set_subtype_variants(subtype, copy)
                owned[subtype] = copy
                added = added + 1
            end
        end
        out("[wyccc_variant_selector_patch] registered " .. tostring(added) .. " subtypes")
        core:add_listener(
            "wyccc_variant_selector_patch_changed",
            "UITrigger",
            function(context)
                return string.match(context:trigger(), "^marthvs_variant_index:(%d+)$") ~= nil
            end,
            function(context)
                local character = live_character(context:faction_cqi())
                local variants = managed_variants(character)
                local index = tonumber(string.match(context:trigger(), "^marthvs_variant_index:(%d+)$"))
                if not variants or not index or not variants[index] then return end
                -- UITrigger runs on all peers. No game state is changed by a
                -- local UI click listener, and all peers save the same art ID.
                selected[tostring(character:command_queue_index())] = {
                    subtype = character:character_subtype_key(),
                    art_set = variants[index],
                }
                apply(character, variants, index)
            end,
            true
        )
        core:add_listener(
            "wyccc_variant_selector_patch_pending_battle",
            "PendingBattle", true,
            function()
                -- Includes embedded heroes, which do not have their own
                -- attacker/defender entry in the pending battle cache.
                if reapply_selected() > 0 then cm:update_pending_battle() end
            end,
            true
        )
        reapply_selected()
    end
    -- The framework merges marthvs/mod registrations during script loading.
    -- Defer until all campaign scripts/first-tick registrations have run.
    cm:callback(function() initialize(0) end, 0.1)
end)
'''


def _build_lua_script(variants_by_subtype: dict[str, list[str]]) -> bytes:
    lines = [
        "-- Generated by Wyccc's Mod Manager: Dynamic Variant Selector Patch.",
        "local AUTO_VARIANTS = {",
    ]
    for subtype in sorted(variants_by_subtype):
        variants = ", ".join(_lua_string(key) for key in variants_by_subtype[subtype])
        lines.append(f"    [{_lua_string(subtype)}] = {{{variants}}},")
    lines.append("}")
    return ("\n".join(lines) + "\n" + _LUA_RUNTIME).encode("utf-8")


def build_variant_selector_compatibility_entries(
    sources: Sequence[DbSource],
) -> GameDataBuildResult:
    """Generate candidates from effective DB rows, including singleton lists.

    The runtime decides which subtypes are still unregistered after all manual
    adaptations load. Counts here describe candidates, not runtime registrations.
    """
    effective = _collect_effective_rows(sources, set(VARIANT_SELECTOR_TABLE_ORDER))
    art_sets, arts, uniforms, variants = (
        effective[name] for name in VARIANT_SELECTOR_TABLE_ORDER
    )
    stats = {
        "art_set_rows": len(art_sets),
        "valid_art_set_rows": 0,
        "invalid_art_set_rows": 0,
        "battle_only_art_set_rows": 0,
        "candidate_subtype_count": 0,
        "candidate_art_set_count": 0,
    }
    arts_by_set: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in arts.values():
        arts_by_set[_clean_key(candidate.row.values.get("art_set_id"))].append(
            candidate.row.values
        )

    by_subtype: dict[str, list[str]] = defaultdict(list)
    for candidate in art_sets.values():
        values = candidate.row.values
        art_set_id = _clean_key(values.get("art_set_id"))
        subtype = _clean_key(values.get("agent_subtype"))
        if any(_BATTLE_ONLY.search(_clean_key(values.get(key))) for key in (
            "art_set_id", "agent_subtype", "faction",
        )):
            stats["battle_only_art_set_rows"] += 1
            continue
        valid = False
        for art in arts_by_set.get(art_set_id, ()):
            uniform = uniforms.get(_clean_key(art.get("uniform")))
            if uniform is None:
                continue
            filename = _clean_key(uniform.row.values.get("filename"))
            if filename and filename in variants:
                valid = True
                break
        if not art_set_id or not subtype or not valid:
            stats["invalid_art_set_rows"] += 1
            continue
        stats["valid_art_set_rows"] += 1
        by_subtype[subtype].append(art_set_id)

    for subtype in by_subtype:
        by_subtype[subtype] = sorted(set(by_subtype[subtype]))
    stats["candidate_subtype_count"] = len(by_subtype)
    stats["candidate_art_set_count"] = sum(map(len, by_subtype.values()))
    entries = (
        (GameDataEntry(VARIANT_SELECTOR_SCRIPT_NAME, _build_lua_script(by_subtype)),)
        if by_subtype else ()
    )
    return GameDataBuildResult(entries, stats)
