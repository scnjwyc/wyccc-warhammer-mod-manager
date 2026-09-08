-- Small campaign API simulation. No external game/framework source is copied.
local initial, reordered, removed = arg[1], arg[2], arg[3]
local save_key = "wyccc_variant_selector_patch_art_sets_v1"
local function copy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, item in pairs(value) do result[key] = copy(item) end
    return result
end

local function session(script, saved, without_api)
    local s = {
        registrations = {manual = {"manual_a", "manual_b"}, empty = {}},
        indices = {}, overrides = {}, saves = {}, loads = {}, ticks = {},
        callbacks = {}, listeners = {}, saved = copy(saved or {}), updates = 0,
    }
    local characters = {}
    for cqi, subtype in pairs({[1]="new", [2]="single", [3]="manual", [4]="empty", [5]="late", [7]="new"}) do
        local id, key = cqi, subtype
        characters[id] = {
            is_null_interface = function() return false end,
            command_queue_index = function() return id end,
            character_subtype_key = function() return key end,
        }
    end
    cm = {
        get_character_by_cqi = function(_, cqi) return characters[cqi] end,
        add_saving_game_callback = function(_, fn) table.insert(s.saves, fn) end,
        add_loading_game_callback = function(_, fn) table.insert(s.loads, fn) end,
        add_first_tick_callback = function(_, fn) table.insert(s.ticks, fn) end,
        callback = function(_, fn) table.insert(s.callbacks, fn) end,
        save_named_value = function(_, key, value) s.saved[key] = copy(value) end,
        load_named_value = function(_, key, default) return copy(s.saved[key] or default) end,
        add_unit_model_overrides = function(_, lookup, art)
            assert(type(art) == "string", "invalid model override")
            s.overrides[tonumber(string.match(lookup, "^character_cqi:(%d+)$"))] = art
        end,
        update_pending_battle = function() s.updates = s.updates + 1 end,
    }
    core = {
        add_listener = function(_, name, event, condition, callback)
            s.listeners[name] = {event=event, condition=condition, callback=callback}
        end,
    }
    marthvs = {
        get_subtype_variants = function(_, key) return s.registrations[key] end,
        set_subtype_variants = function(_, key, list) s.registrations[key] = list end,
        set_character_variant_index = function(_, cqi, index) s.indices[tostring(cqi)] = index end,
    }
    if without_api then marthvs = nil end
    out = function() end
    assert(loadfile(script))()
    for _, fn in ipairs(s.loads) do fn({}) end
    for _, fn in ipairs(s.ticks) do fn() end
    local manual = s.registrations.manual
    local empty = s.registrations.empty
    -- A separate adaptation registers during its own first tick.
    local late = {"late_manual"}
    s.registrations.late = late
    while #s.callbacks > 0 do table.remove(s.callbacks, 1)() end
    assert(s.registrations.manual == manual and s.registrations.empty == empty)
    assert(s.registrations.late == late)
    function s:emit(event, cqi, trigger)
        local context = {
            faction_cqi = function() return cqi end,
            trigger = function() return trigger end,
        }
        for _, listener in pairs(self.listeners) do
            if listener.event == event
                and (listener.condition == true or listener.condition(context))
            then listener.callback(context) end
        end
    end
    function s:save()
        for _, fn in ipairs(self.saves) do fn({}) end
        return copy(self.saved)
    end
    return s
end

local first = session(initial)
assert(#first.registrations.single == 1, "singleton selector missing")
assert(#first.registrations.new == 2)
assert(next(first.overrides) == nil, "unselected characters changed")
first:emit("UITrigger", 1, "marthvs_variant_index:2")
first:emit("UITrigger", 2, "marthvs_variant_index:1")
-- Existing manual/empty/late registrations are not owned by this patch.
first:emit("UITrigger", 3, "marthvs_variant_index:1")
first:emit("UITrigger", 4, "marthvs_variant_index:1")
first:emit("UITrigger", 5, "marthvs_variant_index:1")
first:emit("UITrigger", 999, "marthvs_variant_index:1")
first:emit("UITrigger", 1, "marthvs_variant_index:0")
first:emit("UITrigger", 1, "marthvs_variant_index:99")
first:emit("UITrigger", 1, "unrelated:1")
assert(first.overrides[1] == "z_art" and first.indices["1"] == 2)
assert(first.overrides[2] == "single_art" and first.indices["2"] == 1)
assert(first.overrides[3] == nil and first.overrides[4] == nil and first.overrides[5] == nil)
local saved = first:save()
assert(saved[save_key]["1"].art_set == "z_art")
assert(saved[save_key]["1"].subtype == "new")
assert(saved[save_key]["3"] == nil)
first.overrides = {}
first:emit("PendingBattle")
assert(first.overrides[1] == "z_art" and first.overrides[2] == "single_art")
assert(first.updates == 1, "pending battle not refreshed")

-- A second peer receiving the synchronized trigger saves identical choices.
local peer = session(initial)
peer:emit("UITrigger", 1, "marthvs_variant_index:2")
assert(peer:save()[save_key]["1"].art_set == saved[save_key]["1"].art_set)

-- Insertions may change the numeric index but must preserve the art-set ID.
local second = session(reordered, saved)
assert(second.overrides[1] == "z_art" and second.indices["1"] == 3)
assert(second.overrides[2] == "single_art")
assert(second.overrides[7] == nil, "unselected same-subtype character changed")
local third = session(removed, saved)
assert(third.overrides[1] == nil and third.indices["1"] == nil)
assert(third:save()[save_key]["1"] == nil, "removed appearance retained")

-- A manual adaptation taking over after initialization must remain in charge.
local takeover = session(initial, saved)
takeover.registrations.new = {"replacement"}
takeover.overrides = {}
takeover:emit("UITrigger", 1, "marthvs_variant_index:1")
takeover:emit("PendingBattle")
assert(takeover.overrides[1] == nil)
assert(takeover:save()[save_key]["1"] == nil)
-- This also applies to changes made in place to the registered table.
takeover.registrations.single[1] = "replacement_single"
takeover.overrides = {}
takeover:emit("UITrigger", 2, "marthvs_variant_index:1")
assert(takeover.overrides[2] == nil)

-- A failed framework load is harmless, including when the game later saves.
local absent = session(initial, saved, true)
assert(next(absent.listeners) == nil)
absent:save()
print("all runtime checks passed")
