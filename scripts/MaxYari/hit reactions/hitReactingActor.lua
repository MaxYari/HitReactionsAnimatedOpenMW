local self = require('openmw.self')
local animation = require('openmw.animation')
local core = require('openmw.core')
local nearby = require('openmw.nearby')
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

--- Is this actor in a fight?
--
-- Plenty of mods move health around outside combat - regeneration, disease,
-- cooking, a scripted drain - and a flinch on every one of those reads as a
-- twitchy character rather than a hurt one.
--
-- Nothing is polled for this. MSS already holds combat targets: OpenMW's own
-- music script reports every actor's AI targets, and MSS keeps them, so this is
-- a table lookup - and it only runs when damage has actually landed.
--
-- The player is the odd one out. It has no AI targets of its own, so it is in
-- combat when something else is fighting IT, which is the same thing the music
-- script means by combat. MSS holds the other actors' targets on the player's
-- side, under a different call - but keyed by actor, so answering takes a walk
-- of everything nearby. That answer is held for COMBAT_MAX_AGE rather than
-- walked again per blow. Whether a fight is on does not change blow to blow,
-- and the only cost of a stale one is a flinch on the first hit of a fight that
-- began within the last second.
--
-- If MSS cannot answer - an older build, or the music script missing so nothing
-- ever fills the table - the answer is yes. Failing open costs a few flinches
-- out of combat; failing closed would silently stop them everywhere.
local COMBAT_MAX_AGE = 1.0
local combatAnswer, combatAskedAt = false, nil

local function playerInCombat()
    local me = self.object.id
    for _, actor in ipairs(nearby.actors) do
        local targets = I.MSS.getCombatTargetsOther(actor.id)
        if targets then
            for i = 1, #targets do
                if targets[i].id == me then return true end
            end
        end
    end
    return false
end

local function inCombat()
    if not isPlayer then
        if not I.MSS.getCombatTargets then return true end
        return I.MSS.getCombatTargets() ~= nil
    end
    if not I.MSS.getCombatTargetsOther then return true end

    local now = core.getSimulationTime()
    if combatAskedAt == nil or now - combatAskedAt >= COMBAT_MAX_AGE then
        combatAskedAt = now
        combatAnswer = playerInCombat()
    end
    return combatAnswer
end

-- Every health decrease of this actor, from Max Yari's Script Services (MSS).
local function onDamage(e)
    -- Health falling only because max health was lowered is not damage.
    if e.health >= math.min(e.previousHealth, e.baseHealth) then return end
    if core.getSimulationTime() - startTime < IGNORE_AFTER_START or not animation.hasGroup(self, "hitreact1") then return end

    if isPlayer and settings:get("NoPlayerFlinches") == true then return end

    -- Zero means off, and off means not reaching for a clip at all.
    local intensity = util.clamp(settings:get("Intensity") or 1, 0, 1)
    if intensity <= 0 then return end
    if settings:get("CombatOnly") ~= false and not inCombat() then return end

    if not hitReactAnim or not hitReactAnim:isPlaying() then
        hitReactAnim = AnimManager.Animation:play(
            hitAnimGroups[math.random(1, hitAnimCount)],
            {
                startKey = "start",
                stopKey = "stop",
                -- Intensity 1 plays the whole reaction, lower values start further into it.
                startPoint = 1 - intensity,
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
