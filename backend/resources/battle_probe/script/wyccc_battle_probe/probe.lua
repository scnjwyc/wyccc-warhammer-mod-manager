-- Read-only battle evidence. Never call native hooks or write game memory.
local Probe = {}
Probe.__index = Probe
local unpack_values = unpack or table.unpack
local protected_call = pcall
local function pack(...) return {n = select("#", ...), ...} end

local function json(value)
    if value == nil then return "null" end
    if type(value) == "boolean" then return tostring(value) end
    if type(value) == "number" then
        return value == value and math.abs(value) ~= math.huge and tostring(value) or "null"
    end
    if type(value) == "table" then
        local fields = {}
        for key, item in pairs(value) do fields[#fields + 1] = json(tostring(key)) .. ":" .. json(item) end
        table.sort(fields)
        return "{" .. table.concat(fields, ",") .. "}"
    end
    return '"' .. tostring(value):gsub('[%z\1-\31\\"]', function(c)
        return string.format("\\u%04x", string.byte(c))
    end) .. '"'
end

local function method(object, name, ...)
    if not object then return nil end
    local ok, fn = protected_call(function() return object[name] end)
    if not ok or type(fn) ~= "function" then return nil end
    local success, value = protected_call(fn, object, ...)
    if success then return value end
end

local function source(fn)
    if debug and debug.getinfo then
        local ok, info = protected_call(debug.getinfo, fn, "S")
        if ok and info then return (info.short_src or info.source or "?") .. ":" .. tostring(info.linedefined) end
    end
    return "unknown"
end

local function caller()
    if debug and debug.getinfo then
        for level = 3, 12 do
            local info = debug.getinfo(level, "Sl")
            if not info then break end
            local path = info.short_src or "?"
            if info.what ~= "C" and not path:match("wyccc_battle_probe") then
                return path .. ":" .. tostring(info.currentline)
            end
        end
    end
    return "unknown"
end

function Probe.writer(stem, max_bytes)
    local writer = {stem = stem, part = 1, bytes = 0, max_bytes = max_bytes or 4 * 1024 * 1024}
    function writer:append(channel, lines)
        if channel == "trace" and self.bytes > 0 and self.bytes + #lines > self.max_bytes then
            self.part = self.part % 3 + 1
            self.bytes = 0
        end
        local path = self.stem .. (channel == "trace" and ("_trace" .. self.part) or "_roster") .. ".jsonl"
        local mode = channel == "trace" and self.bytes == 0 and "w" or "a"
        local file, err = io.open(path, mode)
        if not file then error("probe log open failed: " .. tostring(err)) end
        local written, write_error = file:write(lines)
        local flushed, flush_error = file:flush()
        file:close()
        if not written or not flushed then error(tostring(write_error or flush_error)) end
        if channel == "trace" then self.bytes = self.bytes + #lines end
    end
    return writer
end

function Probe.new(options)
    return setmetatable({battle = options.battle, mr = options.mr, writer = options.writer,
        clock = options.clock or os.clock, wall = options.wall or function() return os.date("%Y-%m-%d %H:%M:%S") end,
        notify = options.notify or function() end, phase_source = options.phase_source,
        units = setmetatable({}, {__mode = "k"}), by_identity = {}, by_native = {}, unit_tables = {}, roster = {},
        controllers = setmetatable({}, {__mode = "k"}),
        patches = {}, patched = setmetatable({}, {__mode = "k"}), seen = {}, buffer = {}, sequence = 0,
        pulse = 0, last_scan = -100, last_snapshot = -100, last_flush = -100,
        active = "idle", sim_ms = 0, phase = "loading", enabled = true, native = false,
        error_count = 0, dropped = 0, dropped_total = 0, coalesced_total = 0, rate_count = 0, rate_second = -1}, Probe)
end

function Probe:flush()
    if #self.buffer == 0 then return end
    local lines = table.concat(self.buffer)
    self.buffer = {}
    self.writer:append("trace", lines)
    self.last_flush = self.clock()
end

function Probe:record(kind, fields, immediate, roster)
    if not self.enabled then return end
    self.sequence = self.sequence + 1
    local row = {kind = kind, seq = self.sequence, wall = self.wall(), sim_ms = self.sim_ms}
    for key, value in pairs(fields or {}) do row[key] = value end
    local line = json(row) .. "\n"
    if roster then self.writer:append("roster", line)
    else self.buffer[#self.buffer + 1] = line end
    if immediate or #self.buffer >= 128 then self:flush() end
end

function Probe:safe(fn, ...)
    if not self.enabled then return end
    local ok, result = protected_call(fn, ...)
    if not ok then
        self.error_count = self.error_count + 1
        self.notify("probe error " .. tostring(self.error_count) .. ": " .. tostring(result))
        if self.error_count >= 3 then
            self.enabled = false
            self:restore()
            self.notify("probe disabled after three errors")
        end
    end
    return ok, result
end

function Probe:context()
    if self.mr and type(self.mr.set_crash_context) == "function" then
        -- Plus has only 12 context slots; use one slot and leave its own fields intact.
        protected_call(self.mr.set_crash_context, "wyccc probe",
            self.writer.stem .. " seq=" .. self.sequence .. " t=" .. self.sim_ms .. " " .. self.active:sub(1, 65))
    end
end

function Probe:observe(kind, fields, immediate)
    local now = self.clock()
    local second = math.floor(now)
    if second ~= self.rate_second then self.rate_second, self.rate_count = second, 0 end
    local fingerprint = kind .. "|" .. json(fields)
    if self.seen[fingerprint] and now - self.seen[fingerprint] < 1 then
        self.coalesced_total = self.coalesced_total + 1
        return false
    end
    if self.rate_count >= 120 then
        self.dropped, self.dropped_total = self.dropped + 1, self.dropped_total + 1
        return false
    end
    self.rate_count = self.rate_count + 1
    self.seen[fingerprint] = now
    self:record(kind, fields, immediate or now - self.last_flush >= 1)
    return true
end

function Probe:replace(object, key, replacement)
    local slots = self.patched[object]
    if not slots then slots = {}; self.patched[object] = slots end
    if slots[key] then return end
    local raw_original = rawget(object, key)
    local original = object[key]
    if type(original) ~= "function" then return end
    local wrapped = replacement(original)
    slots[key] = true
    self.patches[#self.patches + 1] = {object, key, raw_original, wrapped}
    rawset(object, key, wrapped)
end

function Probe:restore()
    for index = #self.patches, 1, -1 do
        local patch = self.patches[index]
        if rawget(patch[1], patch[2]) == patch[4] then rawset(patch[1], patch[2], patch[3]) end
    end
    self.patches = {}
end

function Probe:method_table(object)
    local mt = getmetatable(object)
    if type(mt) ~= "table" then return nil end
    local index = rawget(mt, "__index")
    return type(index) == "table" and index or mt
end

function Probe:validate_profile()
    local mr = self.mr
    if not mr or type(mr.read) ~= "function" or type(mr.ud_topointer) ~= "function"
        or type(mr.is_null) ~= "function" or type(mr.read_uint32) ~= "function" then
        return false, "Memreader Plus unavailable"
    end
    -- These offsets are RAW bytes, not float Lua numbers above 0x1000000.
    -- All five signatures were read from WH3 9.0.2.0 (PE timestamp 0x6abc5338).
    local signatures = {
        {"\17\89\238\2", "\72\139\78\8\72\129\193\200\54\0\0"},
        {"\48\122\141\0", "\72\139\65\64\195"},
        {"\80\81\4\3", "\72\141\143\200\58\0\0"},
        {"\113\221\237\2", "\72\139\79\8\72\99\145\16\60\0\0"},
        {"\44\151\241\2", "\72\139\78\8\139\145\160\62\0\0"}
    }
    local ok, reason = protected_call(function()
        local pe = mr.read_int32(mr.base, 0x3c)
        if pe < 0x40 or pe > 0x1000 or mr.read(mr.base, pe, 4) ~= "PE\0\0"
            or mr.read(mr.base, pe + 8, 4) ~= "\56\83\188\106"
            or mr.read(mr.base, pe + 80, 4) ~= "\0\192\122\15" then return "PE build mismatch" end
        for _, item in ipairs(signatures) do
            if mr.read(mr.base, item[1], #item[2]) ~= item[2] then return "signature mismatch" end
        end
        return "WH3 9.0.2.0"
    end)
    return ok and reason == "WH3 9.0.2.0", ok and reason or tostring(reason)
end

function Probe:native_identity(unit)
    if not self.native then return {} end
    local mr = self.mr
    local interface = mr.ud_topointer(unit)
    local pointer = mr.read_pointer(interface, 8)
    if mr.is_null(pointer) then return {interface = mr.tostring(interface), native_error = "null unit"} end
    return {interface = mr.tostring(interface), native = mr.tostring(pointer), pointer = pointer,
        attributes = mr.tostring(mr.add(pointer, 0x36c8)), status = mr.tostring(mr.add(pointer, 0x3ac8)),
        native_uid = mr.tostring(mr.read_uint32(pointer, 0x3ea0, true)), vtable = mr.tostring(mr.read_pointer(pointer)),
        db_record = mr.tostring(mr.read_pointer(pointer, 0x48))}
end

function Probe:register(unit, alliance, army_index, unit_index)
    if self.units[unit] then self.units[unit].present = true; return self.units[unit] end
    local native = {}
    local ok, result = protected_call(self.native_identity, self, unit)
    if ok then native = result else native.native_error = tostring(result) end
    local uid = tostring(method(unit, "unique_ui_id") or "?")
    -- Re-enumeration may return a new Lua userdata for the same native unit.
    -- Include its exact native UID so a reused heap address gets a new slot.
    local key = native.native and (native.native:lower() .. ":" .. tostring(native.native_uid))
        or (uid ~= "?" and "ui:" .. uid or nil)
    local existing = key and self.by_identity[key]
    if existing then
        existing.unit, existing.pointer, existing.present = unit, native.pointer or existing.pointer, true
        self.units[unit] = existing
        return existing
    end
    if #self.roster >= 2048 then
        if not self.roster_limit then
            self.roster_limit = true
            self:record("COVERAGE_LIMIT", {reason = "unit registry limit", limit = 2048}, true, true)
        end
        return nil
    end
    local row = {slot = #self.roster + 1, unit = unit, present = true, pointer = native.pointer,
        uid = native.native_uid or uid, type = method(unit, "type") or "?",
        name = method(unit, "name") or "?", alliance = alliance, army = army_index, unit_index = unit_index}
    self.units[unit] = row
    if key then self.by_identity[key] = row end
    if native.native then self.by_native[native.native:lower()] = row end
    local slots = self:method_table(unit)
    if slots then self.unit_tables[slots] = true end
    self.roster[#self.roster + 1] = row
    local fields = {slot = row.slot, uid = row.uid, ui_api_uid = uid, type = row.type, name = row.name,
        alliance = alliance, army = army_index, unit_index = unit_index}
    for key, value in pairs(native) do if key ~= "pointer" then fields[key] = value end end
    row.native, row.attributes, row.status = fields.native, fields.attributes, fields.status
    self:record("UNIT", fields, false, true)
    self:instrument_object(unit, "unit")
    return row
end

function Probe:identity(unit)
    local row = self.units[unit]
    if not row and self.native and self.unit_tables[self:method_table(unit)] then
        local ok, key = protected_call(function()
            local pointer = self.mr.read_pointer(self.mr.ud_topointer(unit), 8)
            return self.mr.tostring(pointer):lower() .. ":" .. self.mr.tostring(self.mr.read_uint32(pointer, 0x3ea0, true))
        end)
        row = ok and self.by_identity[key] or nil
        if row then self.units[unit] = row end
    end
    if row then return "#" .. row.slot .. "/" .. row.uid end
    return tostring(unit)
end

local UNIT_METHODS = {"set_stat_attribute", "reduce_hitpoints_unary", "heal_hitpoints_unary",
    "set_current_ammo_unary", "disable_special_ability", "change_behaviour_active"}
local CONTROLLER_METHODS = {"set_invincible", "set_invisible_to_all", "change_enabled",
    "morale_behavior_default", "morale_behavior_fearless", "morale_behavior_rout", "change_fatigue_amount",
    "perform_special_ability", "perform_special_ability_q", "perform_special_ability_ground",
    "reset_ability_cooldown", "reset_ability_number_of_uses", "kill", "take_control", "release_control",
    "change_behaviour_active", "teleport_to_location", "attack_unit", "attack_unit_q", "halt", "withdraw",
    "add_units", "add_group", "add_all_units", "clear_all"}

function Probe:instrument_object(object, kind)
    local slots = self:method_table(object)
    if not slots then return end
    local names = kind == "unit" and UNIT_METHODS or CONTROLLER_METHODS
    for _, name in ipairs(names) do
        self:replace(slots, name, function(original)
            return function(target, ...)
                self:safe(function(...)
                    local args, labels = pack(...), {}
                    for i = 1, math.min(args.n, 5) do
                        local value = args[i]
                        labels[i] = self.units[value] and self:identity(value) or tostring(value)
                    end
                    local controller = self.controllers[target]
                    if kind == "controller" then
                        controller = controller or {units = {}}
                        self.controllers[target] = controller
                        if name == "clear_all" then controller.units = {}
                        elseif name == "add_units" or name == "add_group" then
                            for i = 1, args.n do controller.units[self:identity(args[i])] = true end
                        elseif name == "add_all_units" and controller.army then
                            local units = method(controller.army, "units")
                            for i = 1, (method(units, "count") or 0) do
                                controller.units[self:identity(method(units, "item", i))] = true
                            end
                        end
                    end
                    local members = {}
                    if controller then for id in pairs(controller.units) do members[#members + 1] = id end; table.sort(members) end
                    self:observe("CALL", {method = kind .. ":" .. name, target = kind == "unit" and self:identity(target)
                        or tostring(target), units = table.concat(members, ","), args = table.concat(labels, ","), source = caller()},
                        kind == "unit" or name == "change_fatigue_amount" or name:match("^morale_behavior") ~= nil)
                end, ...)
                return original(target, ...)
            end
        end)
    end
end

function Probe:instrument_army(army)
    local slots = self:method_table(army)
    if not slots then return end
    self:replace(slots, "create_unit_controller", function(original)
        return function(target, ...)
            local results = pack(original(target, ...))
            self:safe(function()
                if results[1] then
                    self.controllers[results[1]] = {army = target, units = {}}
                    self:instrument_object(results[1], "controller")
                end
            end)
            return unpack_values(results, 1, results.n)
        end
    end)
end

function Probe:scan()
    for _, row in ipairs(self.roster) do row.present = false end
    local alliances = method(self.battle, "alliances")
    for alliance = 1, (method(alliances, "count") or 0) do
        local armies = method(method(alliances, "item", alliance), "armies")
        for army_index = 1, (method(armies, "count") or 0) do
            local army = method(armies, "item", army_index)
            self:instrument_army(army)
            local units = method(army, "units")
            for unit_index = 1, (method(units, "count") or 0) do
                local unit = method(units, "item", unit_index)
                if unit then self:register(unit, alliance, army_index, unit_index) end
            end
        end
    end
end

function Probe:snapshot(row)
    if not row.present then return end
    local fields = {slot = row.slot, uid = row.uid}
    if row.pointer then
        local ok, state = protected_call(function()
            local mr = self.mr
            local backref = mr.read_pointer(row.pointer, 0x3b08)
            local text = mr.tostring(backref)
            return {status_backref = text, backref_matches_attributes = mr.eq(backref, mr.add(row.pointer, 0x36c8)),
                fatigue_raw = mr.read_int32(row.pointer, 0x3c10), native_uid = mr.tostring(mr.read_uint32(row.pointer, 0x3ea0, true)),
                canonical = not mr.is_null(backref) and text:match("^0000[0-7]") ~= nil}
        end)
        if ok then
            for key, value in pairs(state) do fields[key] = value end
            if not state.canonical or not state.backref_matches_attributes then
                self:record("ANOMALY", {slot = row.slot, uid = row.uid, type = row.type,
                    native = row.native, status_backref = state.status_backref,
                    reason = state.canonical and "status backref differs from embedded attributes" or "null or noncanonical status pointer"}, true)
                -- A corrupt native object must not be dereferenced by extra game getters.
                self:record("STATE", fields)
                return
            end
        else
            fields.native_error = tostring(state)
            self:record("STATE", fields)
            return
        end
    end
    if method(row.unit, "is_valid_target") == false then fields.valid = false
    else
        fields.valid = true
        fields.hp = method(row.unit, "unary_hitpoints")
        fields.men = method(row.unit, "number_of_men_alive")
        fields.routing = method(row.unit, "is_routing")
        fields.ammo = method(row.unit, "ammo_left")
        fields.fatigue = method(row.unit, "fatigue_state")
    end
    self:record("STATE", fields)
end

function Probe:callback(fn, name, event)
    local location = source(fn)
    return function(...)
        if not self.enabled then return fn(...) end
        local previous, started, logged = self.active, self.clock(), false
        self:safe(function()
            self.active = name .. " " .. location
            logged = self:observe("CALLBACK_BEGIN", {name = name, event = event, source = location})
            self:context()
        end)
        -- Preserve original errors and every return value, including trailing nils.
        local results = pack(protected_call(fn, ...))
        self:safe(function()
            local elapsed = (self.clock() - started) * 1000
            if not results[1] then
                self:record("CALLBACK_ERROR", {name = name, source = location, error = tostring(results[2]), elapsed_ms = elapsed}, true)
            elseif logged or elapsed >= 100 then
                self:record("CALLBACK_END", {name = name, source = location, elapsed_ms = elapsed})
            end
            self.active = previous
            self:context()
        end)
        if not results[1] then error(results[2], 0) end
        return unpack_values(results, 2, results.n)
    end
end

function Probe:install(core)
    local wrapped = setmetatable({}, {__mode = "k"})
    local function wrap(fn, name, event)
        if type(fn) ~= "function" or tostring(name):match("^wyccc_battle_probe") or wrapped[fn] then return fn end
        local replacement = self:callback(fn, tostring(name), event)
        wrapped[replacement] = true
        return replacement
    end
    -- Include listeners registered before this battle MOD was loaded.
    for event, listeners in pairs(core.event_listeners or {}) do
        for _, listener in ipairs(listeners) do
            self:replace(listener, "callback", function(fn) return wrap(fn, listener.name, event) end)
        end
    end
    self:replace(core, "add_listener", function(original)
        return function(target, name, event, condition, fn, persistent, ...)
            local replacement = wrap(fn, name, event)
            local results = pack(original(target, name, event, condition, replacement, persistent, ...))
            self:safe(function()
                if replacement ~= fn then
                    for _, listener in ipairs((target.event_listeners or {})[event] or {}) do
                        if listener.callback == replacement and not self.patched[listener] then
                            self.patched[listener] = {callback = true}
                            self.patches[#self.patches + 1] = {listener, "callback", fn, replacement}
                        end
                    end
                end
            end)
            return unpack_values(results, 1, results.n)
        end
    end)
    local event_original = core.event_callback
    local event_wrapped = function(target, event, context, ...)
        self:safe(function()
            if type(event) == "string" and (event:match("^Battle") or event == "ShortcutTriggered" or event == "ComponentLClickUp") then
                local value = context and context.string
                local fields = {event = event, value = type(value) == "string" and value or nil}
                -- Resolve cached identities with guarded address reads, never state getters.
                local unit = method(context, "unit")
                local other = method(context, "target_unit") or method(context, "other_unit")
                if unit then fields.unit = self:identity(unit) end
                if other then fields.target = self:identity(other) end
                self:observe("EVENT", fields)
            end
        end)
        return event_original(target, event, context, ...)
    end
    self.patches[#self.patches + 1] = {core, "event_callback", rawget(core, "event_callback"), event_wrapped}
    rawset(core, "event_callback", event_wrapped)
    local slots = self:method_table(self.battle)
    if slots then
        for _, name in ipairs({"register_repeating_timer", "register_singleshot_timer", "register_battle_phase_handler"}) do
            self:replace(slots, name, function(original)
                return function(target, fn_name, ...)
                    if type(fn_name) == "string" and not fn_name:match("^wyccc_battle_probe") then
                        self:safe(function() self:replace(_G, fn_name, function(fn) return wrap(fn, fn_name, name) end) end)
                    end
                    return original(target, fn_name, ...)
                end
            end)
        end
    end
end

function Probe:tick()
    if not self.enabled then return end
    self.pulse = self.pulse + 1
    local now = self.clock()
    self.sim_ms = method(self.battle, "time_elapsed_ms") or self.sim_ms
    local speed = method(self.battle, "current_battle_speed")
    if self.phase_source then
        local ok, phase = protected_call(self.phase_source)
        if ok and phase and tostring(phase) ~= self.phase then
            self.phase = tostring(phase)
            self:record("PHASE", {phase = self.phase}, true)
        end
    end
    if now - self.last_scan >= 5 then self:scan(); self.last_scan = now end
    if self.coverage_patches ~= #self.patches or self.coverage_units ~= #self.roster then
        self.coverage_patches, self.coverage_units = #self.patches, #self.roster
        self:record("COVERAGE", {native = self.native, patches = #self.patches, units = #self.roster}, false, true)
    end
    if now - self.last_snapshot >= 2 then
        for _, row in ipairs(self.roster) do self:snapshot(row) end
        self.last_snapshot = now
    end
    self:record("HEARTBEAT", {pulse = self.pulse, phase = self.phase, speed = speed, active = self.active,
        units = #self.roster, native = self.native, dropped = self.dropped,
        dropped_total = self.dropped_total, coalesced_total = self.coalesced_total})
    self:context()
    if now - self.last_flush >= 1 then
        self:flush()
        self.seen = {}
        self.dropped = 0
    end
end

function Probe:start(core)
    local reason
    self.native, reason = self:validate_profile()
    self:record("START", {schema = 1, version = "1.1", profile = reason,
        plus_version = self.mr and self.mr.plus_version or "unavailable", stem = self.writer.stem}, true, true)
    self:install(core)
    self:scan()
    self.coverage_patches, self.coverage_units = #self.patches, #self.roster
    self:record("COVERAGE", {native = self.native, patches = #self.patches, units = #self.roster}, true, true)
    self:context()
end

function Probe:stop()
    self:restore()
    if self.enabled then
        local ok, err = protected_call(self.record, self, "STOP", {phase = self.phase}, true)
        if not ok then self.notify("final log write failed: " .. tostring(err)) end
    end
    self.enabled = false
    if self.mr and type(self.mr.set_crash_context) == "function" then
        protected_call(self.mr.set_crash_context, "wyccc probe", nil)
    end
end

-- Optional integration point for other MODs; evidence only, never gameplay changes.
function Probe:mark(name, fields)
    return self:safe(function() self:record("MARK", {name = tostring(name), source = caller(), detail = json(fields or {})}, true) end)
end

Probe.json = json
return Probe
