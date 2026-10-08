-- Run from the repository root. No game process or native hooks are used.
local Probe = dofile(arg and arg[1] or "backend/resources/battle_probe/script/wyccc_battle_probe/probe.lua")
local unpack_values = unpack or table.unpack
local checks = 0
local function check(value, message)
    checks = checks + 1
    assert(value, message)
end
local now, chunks, context = 0, {}, {}
local writer = {stem = "wyccc_battle_probe_fixture"}
function writer:append(channel, text) chunks[#chunks + 1] = {channel = channel, text = text} end
local function text_log()
    local parts = {}
    for _, chunk in ipairs(chunks) do parts[#parts + 1] = chunk.text end
    return table.concat(parts)
end
local function list(items)
    return {count = function() return #items end, item = function(_, index) return items[index] end}
end
local Unit = {}
Unit.__index = Unit
function Unit:type() return self.key end
function Unit:name() return "fixture unit" end
function Unit:unique_ui_id() return self.uid end
function Unit:is_valid_target() self.getters = self.getters + 1; return true end
function Unit:unary_hitpoints() self.getters = self.getters + 1; return 0.75 end
function Unit:number_of_men_alive() self.getters = self.getters + 1; return 80 end
function Unit:is_routing() self.getters = self.getters + 1; return false end
function Unit:ammo_left() self.getters = self.getters + 1; return 12 end
function Unit:fatigue_state() self.getters = self.getters + 1; return "active" end
function Unit:set_stat_attribute(key, value)
    self.last_attribute = {key, value}
    if key == "fail" then error("original unit error") end
    return "unit-return", nil, value, nil
end
local Controller = {}
Controller.__index = Controller
function Controller:add_units(...) self.members = {...} end
function Controller:set_invincible(value) self.invincible = value; return nil, "controller-return", nil end
function Controller:clear_all() self.members = {} end
local Army = {}
Army.__index = Army
function Army:units() return list(self.items) end
function Army:create_unit_controller() return setmetatable({}, Controller), nil end
local u1 = setmetatable({uid = "u1", key = "wyccc_fixture_lord", getters = 0}, Unit)
local army = setmetatable({items = {u1}}, Army)
local Battle = {}
Battle.__index = Battle
function Battle:alliances() return list({{armies = function() return list({army}) end}}) end
function Battle:time_elapsed_ms() return self.sim end
function Battle:current_battle_speed() return self.speed end
function Battle:register_repeating_timer(name, interval) self.timer = {name, interval}; return "timer-return", nil end
function Battle:register_singleshot_timer(name, interval) self.single = {name, interval} end
function Battle:register_battle_phase_handler(name) self.handler = name end
local battle = setmetatable({sim = 1000, speed = 1}, Battle)
local Core = {}
Core.__index = Core
function Core:add_listener(name, event, condition, callback, persistent)
    self.event_listeners[event] = self.event_listeners[event] or {}
    self.event_listeners[event][#self.event_listeners[event] + 1] = {
        name = name, callback = callback, condition = condition, persistent = persistent}
    return "listener-return", nil
end
function Core:event_callback(event, event_context)
    for _, record in ipairs(self.event_listeners[event] or {}) do
        if record.condition == true or record.condition(event_context) then record.callback(event_context) end
    end
    return "dispatch-return", nil, 3, nil
end
function Core:remove_listener(name)
    for _, listeners in pairs(self.event_listeners) do
        for index = #listeners, 1, -1 do
            if listeners[index].name == name then table.remove(listeners, index) end
        end
    end
end
local core = setmetatable({event_listeners = {}}, Core)
local original_unit, original_army, original_timer = Unit.set_stat_attribute, Army.create_unit_controller, Battle.register_repeating_timer
local mr = {base = {kind = "base"}, plus_version = "0.6.0"}
local unit_hex = {[0] = "000000012cf64380", [0x36c8] = "000000012cf67a48", [0x3ac8] = "000000012cf67e48"}
local function pointer(kind, offset, uid) return {kind = kind, offset = offset or 0, uid = uid or "u1"} end
local sigs = {
    ["\17\89\238\2"] = "\72\139\78\8\72\129\193\200\54\0\0",
    ["\48\122\141\0"] = "\72\139\65\64\195",
    ["\80\81\4\3"] = "\72\141\143\200\58\0\0",
    ["\113\221\237\2"] = "\72\139\79\8\72\99\145\16\60\0\0",
    ["\44\151\241\2"] = "\72\139\78\8\139\145\160\62\0\0"
}
function mr.read(_, offset, size)
    if mr.mismatch then return string.rep("\0", size) end
    if offset == 0x80 then return "PE\0\0" end
    if offset == 0x88 then return "\56\83\188\106" end
    if offset == 0xd0 then return "\0\192\122\15" end
    return assert(sigs[offset], "unexpected profile read")
end
function mr.read_int32(ptr, offset)
    if ptr.kind == "base" and offset == 0x3c then return 0x80 end
    return 1
end
function mr.ud_topointer(unit) return pointer("interface", 0, unit.uid) end
function mr.read_pointer(ptr, offset)
    if ptr.kind == "interface" then return pointer("unit", 0, ptr.uid) end
    if offset == 0x3b08 then
        if mr.bad then return pointer("bad") end
        if mr.null then return pointer("null") end
        if mr.unreadable then error("failed to read memory") end
        return pointer("unit", 0x36c8, ptr.uid)
    end
    return pointer("vtable")
end
function mr.read_uint64(ptr) return pointer("uid", 0, ptr.uid) end
function mr.read_uint32(ptr, offset, typed)
    assert(offset == 0x3ea0 and typed == true, "unit UID must be read as an exact 32-bit typed value")
    return pointer("uid", 0, ptr.uid)
end
function mr.is_null(ptr) return ptr.kind == "null" end
function mr.add(ptr, offset) return pointer(ptr.kind, ptr.offset + offset, ptr.uid) end
function mr.eq(a, b) return a.kind == b.kind and a.offset == b.offset and a.uid == b.uid end
function mr.tostring(ptr)
    if ptr.kind == "unit" then
        if ptr.uid == "u2" then
            return assert(({[0] = "0000000300000000", [0x36c8] = "00000003000036c8", [0x3ac8] = "0000000300003ac8"})[ptr.offset])
        end
        return assert(unit_hex[ptr.offset])
    end
    if ptr.kind == "bad" then return "2bc52ea32cf67a48" end
    if ptr.kind == "null" then return "0000000000000000" end
    if ptr.kind == "interface" then return "0000000200000100" end
    if ptr.kind == "uid" then return ptr.uid == "u2" and "67" or "66" end
    return "0000000143ac75d8"
end
function mr.set_crash_context(key, value) context[key] = value end
function mr.ticks() return {value = now} end
function mr.elapsed_us(start) return (now - start.value) * 1000000 end
local probe = Probe.new({battle = battle, mr = mr, writer = writer,
    clock = function() return now end, wall = function() return "2026-10-06 21:07:34" end,
    phase_source = function() return "Deployed" end})
local prior_called = 0
core:add_listener("prior", "BattleTest", true, function() prior_called = prior_called + 1 end, true)
probe:start(core)
check(probe.native, "matching profile should enable guarded reads")
check(#probe.roster == 1 and probe.roster[1].status == "000000012cf67e48", "address registry must identify status object from actual crash")
check(text_log():match('"type":"wyccc_fixture_lord"'), "roster stores DB unit key")
check(context["wyccc probe"]:match("wyccc_battle_probe_fixture"), "crash context links to log stem")
check(rawget(core, "add_listener") ~= nil, "inherited core add_listener must be wrapped")
local condition = function() return true end
local returned = {n = 0}
local function result(...) returned = {n = select("#", ...), ...} end
local later_callback = function() return "ok", nil, 2, nil end
result(core:add_listener("later", "BattleTest", condition, later_callback, true))
check(returned.n == 2 and returned[1] == "listener-return", "registration return count preserved")
check(core.event_listeners.BattleTest[2].condition == condition, "original condition identity preserved")
result(core.event_listeners.BattleTest[2].callback({}))
check(returned.n == 4 and returned[3] == 2, "callback trailing nils preserved")
result(core:event_callback("BattleTest", {}))
check(returned.n == 4 and returned[1] == "dispatch-return" and prior_called == 1, "existing event dispatch semantics preserved")
result(u1:set_stat_attribute("stalk", true))
check(returned.n == 4 and returned[3] == true, "native-method return count preserved")
check(text_log():match('"method":"unit:set_stat_attribute"') and text_log():match('offline.lua:'), "mutation intent records actual caller")
local success, err = pcall(function() u1:set_stat_attribute("fail", true) end)
check(not success and tostring(err):match("original unit error"), "original method errors propagate")
local controller = army:create_unit_controller()
controller:add_units(u1)
result(controller:set_invincible(true))
check(returned.n == 3 and returned[2] == "controller-return" and controller.invincible, "controller returns and behavior preserved")
probe:flush()
check(text_log():match('"units":"#1/66"'), "controller membership is joined to unit registry")
function wyccc_probe_fixture_timer() return "global-timer", nil, 4, nil end
local global_original = wyccc_probe_fixture_timer
result(battle:register_repeating_timer("wyccc_probe_fixture_timer", 200))
check(returned.n == 2 and battle.timer[2] == 200, "timer registration preserved")
result(wyccc_probe_fixture_timer())
check(returned.n == 4 and returned[3] == 4, "named timer callback preserved")
probe:flush()
check(text_log():match('"name":"wyccc_probe_fixture_timer"'), "native named timer receives provenance")
now = 2
probe:tick()
probe:flush()
check(u1.getters > 0 and text_log():match('"hp":0.75'), "valid unit state collected")
check(probe.phase == "Deployed", "manager phase is observed without replacing native handler")
local alias = setmetatable({uid = "u1", key = u1.key, getters = 0}, Unit)
army.items = {alias}
probe:scan()
check(#probe.roster == 1 and probe.roster[1].unit == alias, "fresh userdata must reuse native registry slot")
check(probe:identity(setmetatable({uid = "u1"}, Unit)) == "#1/66", "event userdata resolves cached native identity")
army.items = {u1}
probe:scan()
u1.getters = 0
mr.bad = true
now = 4
probe:tick()
check(u1.getters == 0, "corrupt status pointer must skip all game state getters")
check(text_log():match('"kind":"ANOMALY"') and text_log():match("2bc52ea32cf67a48"), "actual freeze pointer pattern must be recorded")
mr.bad, mr.null = false, true
now = 6.5
probe:tick()
check(u1.getters == 0, "null status pointer must also skip game getters")
mr.null = false
mr.bad, mr.unreadable = false, true
now = 9
probe:tick()
probe:flush()
check(u1.getters == 0 and text_log():match('"native_error":"'), "failed guarded read also skips unsafe game getters")
mr.unreadable = false
local u2 = setmetatable({uid = "u2", key = "summoned_unit", getters = 0}, Unit)
army.items[#army.items + 1] = u2
now = 15
probe:tick()
check(#probe.roster == 2 and text_log():match('"type":"summoned_unit"'), "reinforcements enter registry")
army.items = {u2}
probe:scan()
check(not probe.units[u1].present and probe.units[u2].present, "removed units are no longer polled")
mr.mismatch = true
local valid, reason = probe:validate_profile()
check(not valid and reason == "PE build mismatch", "unknown build disables raw memory reads")
mr.mismatch = false
now = 20
for i = 1, 300 do probe:observe("RATE_TEST", {index = i}) end
check(probe.dropped == 180, "burst evidence is bounded with explicit dropped count")
local before = #chunks
probe:observe("RATE_TEST", {index = 1})
check(#chunks == before, "repeated site coalesced within interval")
now = 22
probe:tick()
probe:flush()
check(text_log():match('"dropped":180'), "heartbeat exposes evidence truncation")
check(probe.dropped_total == 180, "cumulative dropped count avoids double counting across heartbeats")
local failing = probe:callback(function() error("callback failed") end, "failing_callback", "BattleTest")
success, err = pcall(failing)
check(not success and tostring(err):match("callback failed"), "callback error is rethrown to its original dispatcher")
check(probe.active == "idle" and text_log():match('"kind":"CALLBACK_ERROR"'), "caught errors cannot leave stale active callback")
probe:stop()
check(Unit.set_stat_attribute == original_unit and Army.create_unit_controller == original_army, "shared methods restored on exit")
check(Battle.register_repeating_timer == original_timer and wyccc_probe_fixture_timer == global_original, "timer hooks restored")
check(rawget(core, "add_listener") == nil and rawget(core, "event_callback") == nil, "inherited slots restored without shadowing")
check(core.event_listeners.BattleTest[2].callback == later_callback, "callbacks registered during battle are also restored")
check(context["wyccc probe"] == nil and not probe.enabled, "battle state cleared")
local write_fail_probe = Probe.new({battle = battle, writer = {stem = "fail", append = function() error("disk full") end}})
write_fail_probe:install(core)
write_fail_probe:stop()
check(rawget(core, "add_listener") == nil, "disk failure cannot prevent cleanup")
check(Probe.json({text = '中\n文\t"\\'}):match("\\u000a"), "JSON control characters escaped")
-- Exercise the actual battle entry point with a single native phase handler.
local actual_writer = Probe.writer
Probe.writer = function() return writer end
core.load_global_script = function(_, path)
    check(path == "script/wyccc_battle_probe/probe", "actual loader requests its packaged module")
    return Probe
end
core.get_static_object = function() return {get_current_phase_name = function() return "Deployed" end} end
local destroyed
core.add_ui_destroyed_callback = function(_, fn) destroyed = fn end
_G.core, _G.memreader_plus = core, mr
_G.empire_battle = {new = function() return battle end}
local timer_active
_G.real_timer = {
    register_repeating = function(_, interval) timer_active = interval end,
    unregister = function() timer_active = nil end
}
_G.out = function() end
battle.handler = "original_manager_handler"
dofile(arg[2] or "backend/resources/battle_probe/script/battle/mod/!wyccc_battle_probe.lua")
check(timer_active == 500 and _G.wyccc_battle_probe, "actual loader installs the real-time probe")
check(battle.handler == "original_manager_handler", "actual loader preserves the manager's sole native phase handler")
_G.wyccc_battle_probe:tick()
check(_G.wyccc_battle_probe.phase == "Deployed", "actual loader obtains manager phase")
destroyed()
check(timer_active == nil and _G.wyccc_battle_probe == nil and Unit.set_stat_attribute == original_unit, "actual loader tears down timers and shared methods")
Probe.writer = actual_writer
core.load_global_script = function() error("Plus gate must run before loading the probe") end
_G.memreader_plus, _G.memreader = nil, mr
dofile(arg[2] or "backend/resources/battle_probe/script/battle/mod/!wyccc_battle_probe.lua")
check(timer_active == nil and _G.wyccc_battle_probe == nil, "original Memreader cannot activate the launcher probe")
_G.memreader_plus = {ticks = mr.ticks, elapsed_us = mr.elapsed_us}
dofile(arg[2] or "backend/resources/battle_probe/script/battle/mod/!wyccc_battle_probe.lua")
check(timer_active == nil and _G.wyccc_battle_probe == nil, "incomplete Plus API skips the launcher probe")
if arg[3] then
    local output = assert(io.open(arg[3], "w"))
    output:write(text_log())
    output:close()
end
print("BATTLE_PROBE_OFFLINE_PASS " .. checks)
