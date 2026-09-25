local self = require('openmw.self')
local animation = require('openmw.animation')
local core = require('openmw.core')
local types = require('openmw.types')
local util = require('openmw.util')
local I = require('openmw.interfaces')
local storage = require('openmw.storage')

local mp = "scripts/MaxYari/hit reactions/"

DebugLevel = 0

local isPlayer = types.Player.objectIsInstance(self)

-- Max Yari's Script Services (MSS) is a hard dependency for the whole mod, not
-- just for this half. Without it there is no damage listener to react to, and a
-- mod that half-runs is harder to diagnose than one that says why it did not.
-- The player's copy of this script is the one that says so, once.
local deps = require(mp .. "dependencies")
if not deps.ready() then
    if isPlayer then
        print("[" .. deps.NAME .. "] " .. deps.missingMessage())
        require('openmw.ui').showMessage(deps.missingMessage())
    end
    return
end

local recordBlackList = { ["ab01alsonar"] = true, ["ab01bird01"] = true } -- From where all birds going, don't need to process those, only wastes performance.
if recordBlackList[self.recordId] then return end

-- Creatures are in scope when they use the humanoid animation set. isBiped is
-- the engine's own answer to which ones those are; a quadruped has neither
-- these animation groups nor anything sensible to do with them. The hasGroup
-- checks further down are the real gate - this only avoids asking them of
-- things that can never qualify.
local function wrongShape()
    if not types.Creature.objectIsInstance(self) then return false end
    local ok, record = pcall(function() return types.Creature.record(self) end)
    return not (ok and record and record.isBiped)
end
if wrongShape() then return end

-- Required down here, past every gate, and not at the top of the file.
-- Requiring it registers an I.AnimationController.addTextKeyHandler with a nil
-- group filter at module scope, which then fires for every text key this actor
-- ever plays - every footstep, every attack key. On an actor we have already
-- decided to leave alone that is a handler running forever with nothing
-- subscribed to it. Lua only loads a module on first require, so moving the
-- require past the gates is all it takes to not pay for it.
local AnimManager = require(mp .. "anim_manager")


local hitAnimGroups = { "hitreact1", "hitreact2", "hitreact3", "hitreact4" }
local hitAnimCount = #hitAnimGroups
local hitReactAnim = nil
local settings = storage.globalSection('SettingsHitReactionsAnimated')

-- Some mods alter npc health during initialization: decreases this soon after registering are ignored.
local IGNORE_AFTER_START = 0.2
local startTime = nil

-- Every health decrease of this actor, from Max Yari's Script Services (MSS).
local function onDamage(e)
    -- Health falling only because max health was lowered is not damage.
    if e.health >= math.min(e.previousHealth, e.baseHealth) then return end
    if core.getSimulationTime() - startTime < IGNORE_AFTER_START or not animation.hasGroup(self, "hitreact1") then return end

    if not hitReactAnim or not hitReactAnim:isPlaying() then
        hitReactAnim = AnimManager.Animation:play(
            hitAnimGroups[math.random(1, hitAnimCount)],
            {
                startKey = "start",
                stopKey = "stop",
                -- Intensity 1 plays the whole reaction, lower values start further into it.
                startPoint = 1 - util.clamp(settings:get("Intensity") or 1, 0, 1),
                priority = animation.PRIORITY.Knockdown + 1,
                blendMask = animation.BLEND_MASK.Torso
            }
        )
    end
end

-- Registered in onActive, once all scripts on this actor (the player included) are loaded, so I.MSS exists.
local registered = false
local function register()
    if registered then return end
    registered = true
    startTime = core.getSimulationTime()
    I.MSS.addDamageListener(onDamage)
end

return {
    engineHandlers = {
        onActive = register,
    },
}
