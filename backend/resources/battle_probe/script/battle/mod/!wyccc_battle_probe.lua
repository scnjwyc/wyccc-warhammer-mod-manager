-- Loaded before ordinary battle MOD scripts. Logs live next to Warhammer3.exe.
if rawget(_G, "wyccc_battle_probe") then return end
local disabled = io.open("wyccc_battle_probe.disabled", "r")
if disabled then disabled:close(); return end
local mr = rawget(_G, "memreader_plus")
if type(mr) ~= "table" or type(mr.set_crash_context) ~= "function"
    or type(mr.ticks) ~= "function" or type(mr.elapsed_us) ~= "function" then
    out("[wyccc_battle_probe] skipped: Memreader Plus is not loaded")
    return
end
local ok, Probe = pcall(function() return core:load_global_script("script/wyccc_battle_probe/probe") end)
if not ok or type(Probe) ~= "table" then
    out("[wyccc_battle_probe] load failed: " .. tostring(Probe))
    return
end
local battle = empire_battle:new()
local clock_start = mr and mr.ticks and mr.ticks()
local suffix = tostring({}):gsub("[^%w]", ""):sub(-8)
local stem = "wyccc_battle_probe_" .. os.date("%d%m%y_%H%M%S") .. "_" .. suffix
local function clock()
    if mr and mr.ticks and mr.elapsed_us then
        -- Exact typed ticks avoid WH3's float timestamp rounding.
        return mr.elapsed_us(clock_start) / 1000000
    end
    return os.clock()
end
local probe = Probe.new({battle = battle, mr = mr, writer = Probe.writer(stem), clock = clock,
    phase_source = function()
        local manager = rawget(_G, "bm") or core:get_static_object("battle_manager")
        return manager and manager:get_current_phase_name()
    end,
    notify = function(message) out("[wyccc_battle_probe] " .. message) end})
_G.wyccc_battle_probe = probe
local started = probe:safe(function() probe:start(core) end)
if not started then
    probe:safe(function() probe:stop() end)
    _G.wyccc_battle_probe = nil
    return
end
out("[wyccc_battle_probe] active: " .. stem .. " native=" .. tostring(probe.native))

local TIMER = "wyccc_battle_probe_realtime"
core:add_listener(TIMER, "RealTimeTrigger", function(context) return context.string == TIMER end,
    function() probe:safe(function() probe:tick() end) end, true)
real_timer.register_repeating(TIMER, 500)

-- Poll the manager's phase; the native battle has just one phase handler.
-- Registering our own native handler would replace the manager's dispatcher.
core:add_ui_destroyed_callback(function()
    real_timer.unregister(TIMER)
    core:remove_listener(TIMER)
    probe:safe(function() probe:stop() end)
    _G.wyccc_battle_probe = nil
end)
