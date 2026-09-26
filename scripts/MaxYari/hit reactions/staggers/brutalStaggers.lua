-- Brutal Staggers: replaces the engine's stagger, knockdown, knockout and death
-- animations with endorphin-simulated falls, picked at random per event.
--
-- How the override works
-- ---------------------
-- Hit reactions and deaths are played by the engine, not by Lua, so there is no
-- event that says "a stagger started" - but every engine-initiated animation is
-- routed through I.AnimationController.playBlendedAnimation once Lua animations
-- are enabled on the actor, which is what the handler below hooks.
--
-- The vanilla animation is NOT suppressed (options.skip). The engine's hit and
-- death state machines wait on it: CharacterController asks whether mCurrentHit
-- is still playing to know when the character recovers, so skipping it ends the
-- stagger on the same frame it began. Instead it is made invisible with
-- blendMask = 0 - the state still exists, still advances, still fires its text
-- keys, and still drives the state machine, it just moves no bones - and our
-- clip is played on top at a higher priority.
--
-- Each clip is one span, "start" to "stop", cut by hand for the one job it does.
-- Which job that is, is written into the clip itself: the group a Stagger* clip
-- ships under makes it a hit reaction, a Death* one makes it a knockdown,
-- knockout or death. See Sources/export_exp.py.

local self = require('openmw.self')
local animation = require('openmw.animation')
local core = require('openmw.core')
local storage = require('openmw.storage')
local types = require('openmw.types')
local util = require('openmw.util')
local I = require('openmw.interfaces')

local mp = 'scripts/MaxYari/hit reactions/staggers/'
local deps = require('scripts/MaxYari/hit reactions/dependencies')

-- Max Yari's Script Services is required by the mod as a whole; see
-- dependencies.lua. The player's copy of hitReactingActor.lua is what tells the
-- player about it, so this half just stands down quietly.
if not deps.ready() then return end

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

-- Below the gates on purpose, so an actor this script has decided not to touch
-- pays for nothing but the dependency check.
local clips = require(mp .. 'clips')
local directionConfig = require(mp .. 'direction_config')
local directionMath = require(mp .. 'direction_math')


local settings = storage.globalSection('SettingsBrutalStaggers')

local BONE_GROUP = animation.BONE_GROUP

-- Priorities are per bone group, and deliberately uneven.
--
-- Uneven because Animation::play() ERASES every state whose four-group priority
-- is exactly equal to the one being played. A uniform table would match the
-- hidden vanilla animation's own uniform priority and destroy it, and with it
-- the timing the engine is waiting on.
--
-- High because of what else is running. The engine plays a hit at priority 6
-- but a drawn weapon holds 7 on the torso and both arms, which is why vanilla
-- hit reactions are a lower-body twitch whenever a weapon is out. Clearing
-- Weapon (7), Block (8), Knockdown (9) and Torch (10) is what makes these
-- animations play on the whole body.
local function priority(lower, upper)
    return {
        [BONE_GROUP.LowerBody] = lower,
        [BONE_GROUP.Torso] = upper,
        [BONE_GROUP.LeftArm] = upper,
        [BONE_GROUP.RightArm] = upper,
    }
end

local STAGGER_PRIORITY = priority(10, 11)
local FALL_PRIORITY = priority(11, 12)

-- Which vanilla group gets replaced by what.
--   setting  - the checkbox that turns this category off
--   kind     - which half of the clip collection to draw from. A stagger clip
--              ends on its feet and a fall clip ends on the floor, so the two
--              are not interchangeable in either direction.
local KIND_STAGGER, KIND_DEATH = 'stagger', 'death'

local STAGGER = { setting = 'Staggers', kind = KIND_STAGGER, priority = STAGGER_PRIORITY }
local DEATH = { setting = 'Deaths', kind = KIND_DEATH, priority = FALL_PRIORITY }

-- knockdown and knockout are deliberately absent. The collection holds staggers
-- and deaths and nothing else: a knockdown ends with the character getting back
-- up, and the closest thing here is a death clip, which ends with them lying
-- still. Playing one meant they dropped, held the pose, then snapped upright the
-- moment the engine took the body back.
--
-- deathknockdown and deathknockout are a different matter - those ARE deaths,
-- ones that began as a knockdown - so they are replaced like any other.
--
-- The swim variants are left alone as well: these clips fall to a floor.
local CATEGORIES = {
    hit1 = STAGGER, hit2 = STAGGER, hit3 = STAGGER, hit4 = STAGGER, hit5 = STAGGER,
    death1 = DEATH, death2 = DEATH, death3 = DEATH, death4 = DEATH, death5 = DEATH,
    deathknockdown = DEATH, deathknockout = DEATH,
}

-- The clip currently playing over a vanilla group, so it can be cancelled and so
-- the same one is not drawn twice in a row.
local current = nil
local currentParent = nil
local lastGroup = nil

--- Which way the blow threw them ------------------------------------------------
-- I.Combat hands the victim the whole attack: who swung, what kind of swing, and
-- whether it landed. Its handlers run before the engine applies the stagger, so
-- by the time the hit animation is played this is already waiting.
--
-- Only kept for a moment. A hit reaction follows its blow within a frame or two,
-- and anything older belongs to a different blow - or to one that staggered
-- nobody.
local ATTACK_MEMORY = 0.5

-- How much of the push is "away from whoever swung" rather than the sweep of the
-- swing itself. Every blow drives the target back some; a wide slash also throws
-- them sideways. 1.0 would mean direction is decided purely by where the
-- attacker stands and the swing vector would do nothing.
local AWAY_WEIGHT = 0.8

-- Below this the blow is treated as coming straight down, and clips tagged
-- "down" are preferred over matching the compass direction.
local DOWNWARD = -0.6

-- Clips whose bearing is within this of the best one are all fair game, so a
-- direction with several candidates still varies.
local BEARING_SLACK = 35

-- Vanilla hit1..hit5 run 1.000 to 1.133 seconds, and the engine holds a
-- character for exactly as long as the one it drew plays. That is the stun, it
-- is the truth, and there is nothing about it to configure.
--
-- A clip cut longer than STAGGER_MAX is played faster to bring it down to
-- STAGGER_TARGET - just under vanilla's shortest, so it fits whichever hit group
-- the engine happened to draw. The speed-up is capped: past a point a stagger
-- stops reading as weight being thrown about and starts reading as a twitch.
-- Whatever is still too long after the cap is cut off at the end when the
-- engine's animation finishes, which is what the recovery blend is there for.
local STAGGER_MAX = 1.10
local STAGGER_TARGET = 1.05
local MAX_SPEEDUP = 1.15

-- Only the player's copy reports a malformed line: every actor in the cell
-- reads this file, and one complaint per NPC is not a useful error message.
local attackDirections = directionConfig.read(types.Player.objectIsInstance(self))
local lastAttack = nil

--- Long falls for heavy blows -----------------------------------------------
-- A tap should not throw someone across the room; a blow that takes half their
-- health should. So the chance of drawing from the clips that travel a long way
-- rises with what the strike actually cost this target, as a FRACTION of their
-- maximum health - which scales with how hard the hit was for them rather than
-- with a raw damage number that means different things to a rat and a golden
-- saint.
--
-- Between the two points it interpolates; outside them it flattens.
local FAR_LOW_DAMAGE, FAR_LOW_CHANCE = 0.10, 10
local FAR_HIGH_DAMAGE, FAR_HIGH_CHANCE = 0.50, 75

-- Damage is remembered no longer than an attack is: a reaction follows its blow
-- within a frame or two.
local DAMAGE_MEMORY = 0.5
local lastDamage = nil

--- Which clips throw the character sideways, by group. A sideways stagger is a
--- bigger departure from what the engine would have done than being shoved
--- straight back, so it gets its own, lower chance of being used at all.
local SIDEWAYS = {}
for i = 1, #clips.list do
    local clip = clips.list[i]
    SIDEWAYS[clip.group] = (clip.tags.left or clip.tags.right) and true or false
end

--- Which clips travel a long way, by group.
-- clips.lua carries a `far` field. Reading it off the group name when the field
-- is absent keeps this working against a clips.lua generated before the field
-- existed; the exporter derives it from the same name, the same way.
local FAR = {}
for i = 1, #clips.list do
    local clip = clips.list[i]
    local far = clip.far
    if far == nil then
        far = clip.group:find('far') ~= nil or clip.group:find('long') ~= nil
    end
    FAR[clip.group] = far and true or false
end

--- Max Yari's Script Services reports every health change on this actor. Its
--- listener has to be registered once the actor is active, by which point every
--- script on it has loaded and I.MSS exists.
local function onDamage(e)
    local maximum = e.baseHealth
    if maximum == nil or maximum <= 0 then return end
    local took = (e.previousHealth or 0) - (e.health or 0)
    -- Health falling only because max health was lowered is not damage.
    if took <= 0 then return end
    lastDamage = { at = core.getSimulationTime(), fraction = took / maximum }
end

--- The fraction of maximum health the blow just took, or nil if we have no
--- reading fresh enough to belong to this reaction.
local function damageFraction()
    if lastDamage == nil then return nil end
    if core.getSimulationTime() - lastDamage.at > DAMAGE_MEMORY then return nil end
    return lastDamage.fraction
end

--- Percent chance that this blow should draw from the far clips.
local function farChance(fraction)
    if fraction == nil then return nil end
    if fraction <= FAR_LOW_DAMAGE then return FAR_LOW_CHANCE end
    if fraction >= FAR_HIGH_DAMAGE then return FAR_HIGH_CHANCE end
    local t = (fraction - FAR_LOW_DAMAGE) / (FAR_HIGH_DAMAGE - FAR_LOW_DAMAGE)
    return FAR_LOW_CHANCE + t * (FAR_HIGH_CHANCE - FAR_LOW_CHANCE)
end

--- A clip's own travel bearing, for the diagnostic log.
local function clipBearing(groupname)
    for i = 1, #clips.list do
        if clips.list[i].group == groupname then return clips.list[i].bearing end
    end
    return nil
end

-- A hit with no attack type is a shot or a spell. There is no sweep to look up,
-- but the character should still be thrown away from whoever did it, and [0, 0]
-- says exactly that.
local NO_SWEEP = { x = 0, y = 0 }

--- The swing vector for a group, falling back to the attack type's default.
local function swingVector(groupname, typeName)
    typeName = typeName or 'shoot'
    local group = groupname and attackDirections[groupname]
    if group and group[typeName] then return group[typeName] end
    local fallback = attackDirections['default']
    if fallback and fallback[typeName] then return fallback[typeName] end
    return NO_SWEEP
end

local ATTACK_TYPE_NAMES = nil
local function attackTypeName(value)
    if ATTACK_TYPE_NAMES == nil then
        ATTACK_TYPE_NAMES = {}
        for name, number in pairs(I.Combat.ATTACK_TYPES) do
            ATTACK_TYPE_NAMES[number] = string.lower(name)
        end
    end
    return ATTACK_TYPE_NAMES[value]
end

--- The group actually driving the attacker's arm.
---
--- Harder than it looks, because when ReAnimation overrides an attack BOTH
--- groups are live on the actor: it hides the parent with blendMask 0 and plays
--- the override on top, exactly the way this mod hides a vanilla hit reaction.
--- getActiveGroup ranks by PRIORITY, which a hidden animation keeps - so asking
--- one bone group can hand back the invisible parent instead of the animation
--- on screen.
---
--- ReAnimation's uniquifyPriority() drops the hidden parent's LeftArm and
--- LowerBody priority by one so the engine cannot evict it, which is useful
--- here: on those two the override strictly outranks its parent. Torso and
--- RightArm are left equal, and an equal tie is broken by the engine on group
--- name, which is a thin thing to depend on.
---
--- So: ask every bone group, then prefer an override over its parent by name.
--- ReAnimation names an override by extending the parent - weapontwohand ->
--- weapontwohandalt, weapononehand -> weapononehand1 - so of two candidates
--- where one starts with the other, the longer is the override.
local BONE_GROUPS_TO_ASK = {
    BONE_GROUP.LeftArm, BONE_GROUP.LowerBody, BONE_GROUP.RightArm, BONE_GROUP.Torso,
}

local function attackerGroup(attacker)
    local order, seen = {}, {}
    for i = 1, #BONE_GROUPS_TO_ASK do
        local ok, group = pcall(animation.getActiveGroup, attacker, BONE_GROUPS_TO_ASK[i])
        if ok and group and group ~= '' then
            group = string.lower(group)
            if not seen[group] then
                seen[group] = true
                order[#order + 1] = group
            end
        end
    end
    if #order == 0 then return nil end

    -- An attack group we have a vector for beats whatever else is on a limb - a
    -- torch, a shield, a movement animation on the legs.
    local pool = {}
    for i = 1, #order do
        if attackDirections[order[i]] then pool[#pool + 1] = order[i] end
    end
    if #pool == 0 then pool = order end

    local best = pool[1]
    for i = 2, #pool do
        local other = pool[i]
        if #other > #best and other:sub(1, #best) == best then best = other end
    end
    return best, order
end

--- Off by default. On, every hit prints what was read and what was made of it,
--- which is the only way to tell a wrong swing vector from a wrong group from a
--- wrong clip without guessing.
local function logging()
    return settings:get('LogAttackDirection') == true
end

local function log(...)
    print('[Hit Reactions Animated] ' .. table.concat({ ... }, ' '))
end

I.Combat.addOnHitHandler(function(attack)
    if not attack or not attack.successful then return end

    local info = { at = core.getSimulationTime(), vertical = 0 }
    local attacker = attack.attacker

    if attacker then
        local group, allGroups = attackerGroup(attacker)
        local typeName = attackTypeName(attack.type)
        local swing = swingVector(group, typeName)
        if logging() then
            log('hit: type', tostring(typeName),
                '| group', tostring(group),
                '| all bone groups', table.concat(allGroups or {}, '/'),
                '| swing', ('[%g, %g]'):format(swing.x, swing.y),
                '| listed', tostring(group ~= nil and attackDirections[group] ~= nil))
        end
        local ok, offset = pcall(function() return attacker.position - self.position end)
        if ok and offset and swing then
            -- Vectors rather than special cases: "away from the attacker" is
            -- just a direction, so a blow from behind throws them forwards
            -- without any branch saying so.
            local forward = self.rotation:apply(util.vector3(0, 1, 0))
            local left = self.rotation:apply(util.vector3(-1, 0, 0))
            info.bearing = directionMath.pushBearing(
                offset.x, offset.y, forward.x, forward.y, left.x, left.y,
                swing.x, AWAY_WEIGHT)
            -- The same blow with the sweep taken out: straight away from
            -- whoever swung. Every blow drives someone that way whatever the
            -- weapon was doing sideways, so the clips that go there stay in the
            -- running for every attack type rather than only for the ones with
            -- no sweep to speak of - a thrust or a shot.
            info.awayBearing = directionMath.pushBearing(
                offset.x, offset.y, forward.x, forward.y, left.x, left.y,
                0, AWAY_WEIGHT)
            info.vertical = swing.y
            if logging() then
                log(('  bearing %s (sweep-free %s), vertical %g -- negative bearing '
                     .. 'is the victim\'s RIGHT'):format(
                    info.bearing and ('%+.0f'):format(info.bearing) or 'nil',
                    info.awayBearing and ('%+.0f'):format(info.awayBearing) or 'nil',
                    info.vertical or 0))
            end
        end
    end

    lastAttack = info
end)

--- Where this blow should throw them, in the same terms the clips are measured
--- in: degrees off their own forward, 0 ahead, +90 to their left.
--- Returns the swung bearing, the sweep-free one, and the vertical.
local function wantedBearing()
    local attack = lastAttack
    if not attack then return nil, nil, 0 end
    if core.getSimulationTime() - attack.at > ATTACK_MEMORY then return nil, nil, 0 end
    return attack.bearing, attack.awayBearing, attack.vertical or 0
end

--- Seconds between two of a group's text keys, or nil if the group is not
--- loaded on this actor. Each clip is one span, start to stop.
local function keySpan(groupname, startKey, stopKey)
    local from = animation.getTextKeyTime(self, groupname .. ': ' .. startKey)
    local to = animation.getTextKeyTime(self, groupname .. ': ' .. stopKey)
    if from and to and to > from then return to - from end
    return nil
end

--- Every clip of the right kind this actor could play, scored against where the
--- blow should throw them. hasGroup is what keeps beast skeletons, which these
--- clips are not shipped for, on their vanilla animations.
local function candidates(kind, bearing, vertical)
    local found, best = {}, nil
    local list = clips.list

    for i = 1, #list do
        local clip = list[i]
        if clip.kind == kind and animation.hasGroup(self, clip.group) then
            local score
            if bearing == nil or clip.bearing == nil then
                score = 0
            else
                score = directionMath.bearingGap(clip.bearing, bearing)
                -- A blow that comes straight down throws them down more than it
                -- throws them anywhere, so prefer the clips that land that way.
                if vertical <= DOWNWARD and clip.tags.down then
                    score = score - 45
                end
            end
            found[#found + 1] = { group = clip.group, score = score }
            if best == nil or score < best then best = score end
        end
    end

    if best == nil then return {} end

    local pool = {}
    for i = 1, #found do
        if found[i].score <= best + BEARING_SLACK then
            pool[#pool + 1] = found[i].group
        end
    end
    return pool
end

--- How likely a drawn clip is to be used rather than the engine's own.
--- The fallbacks match the registered defaults, for the frames before the
--- settings group exists on a new game.
local function chanceFor(kind, groupname)
    if kind == KIND_DEATH then
        return settings:get('CustomDeathChance') or 90
    end
    -- A far clip is never traded back for a vanilla twitch. It was drawn because
    -- the blow was heavy enough to earn it - that is what the damage roll is for
    -- - and declining it afterwards would undo the one thing it was picked for.
    if FAR[groupname] then
        return 100
    end
    if SIDEWAYS[groupname] then
        return settings:get('SidewaysStaggerChance') or 50
    end
    return settings:get('CustomStaggerChance') or 75
end

--- Everything in a pool except the clip that just played on this actor.
local function withoutLast(pool)
    if lastGroup == nil then return pool end
    local out = {}
    for i = 1, #pool do
        if pool[i] ~= lastGroup then out[#out + 1] = pool[i] end
    end
    return out
end

--- A clip for this blow, never the one that just played.
--- Direction is a preference: an actor with any clip of the right kind gets one,
--- even when nothing points the way the blow does. The kind is not a preference.
--- Returning nil means the engine plays its own animation, which is the right
--- answer when the collection has nothing of that kind to offer.
---
--- Two pools, unioned. The first is where the blow actually throws them, sweep
--- and all. The second is straight away from the attacker, which is where every
--- blow pushes to some degree - so being driven back (or forward, when the blow
--- came from behind) stays possible under a wide slash and not only under a
--- thrust. Without it a sweep worth more than AWAY_WEIGHT swings the bearing far
--- enough sideways that the straight-back clips can drop out of the slack
--- window, and a collection this small then never reaches them.
local function pickGroup(kind, bearing, awayBearing, vertical)
    local pool = candidates(kind, bearing, vertical)

    if awayBearing ~= nil and awayBearing ~= bearing then
        local seen = {}
        for i = 1, #pool do seen[pool[i]] = true end
        local away = candidates(kind, awayBearing, vertical)
        for i = 1, #away do
            if not seen[away[i]] then
                seen[away[i]] = true
                pool[#pool + 1] = away[i]
            end
        end
    end

    if #pool == 0 then pool = candidates(kind, nil, 0) end
    if #pool == 0 then return nil end

    -- Narrow to near or far, if the pool offers both. `spare` is whichever side
    -- was not taken, kept so a distance can be given up when it turns out to
    -- hold nothing but the clip that just played.
    local spare = nil
    if settings:get('FarByDamage') ~= false then
        local chance = farChance(damageFraction())
        if chance ~= nil then
            local far, near = {}, {}
            for i = 1, #pool do
                if FAR[pool[i]] then far[#far + 1] = pool[i] else near[#near + 1] = pool[i] end
            end
            -- Only a real choice when both sides have something; otherwise the
            -- direction match matters more than the distance.
            if #far > 0 and #near > 0 then
                local wantFar = math.random(100) <= chance
                pool, spare = wantFar and far or near, wantFar and near or far
                if logging() then
                    log(('  distance: %.0f%% damage -> %.0f%% far, drew %s')
                        :format((damageFraction() or 0) * 100, chance, wantFar and 'far' or 'near'))
                end
            end
        end
    end

    -- Never the same clip twice running. Seeing one animation play out and then
    -- immediately repeat reads worse than a slightly less apt clip does, so the
    -- one that just played is simply removed rather than rerolled around.
    --
    -- Where that empties the pool - one long sideways clip, say, and it is the
    -- one we just used - give up the distance before the direction and take a
    -- short clip going the same way. Give up entirely rather than reach for a
    -- clip pointing somewhere the blow did not: the engine's own reaction is a
    -- better answer than a stagger in the wrong direction.
    local fresh = withoutLast(pool)
    if #fresh == 0 and spare ~= nil then
        fresh = withoutLast(spare)
        if #fresh > 0 and logging() then
            log('  only clip at that distance was the last one played, took the other')
        end
    end
    if #fresh == 0 then
        if logging() then
            log('  nothing left that is not ' .. tostring(lastGroup) .. ', engine keeps it')
        end
        return nil
    end
    return fresh[math.random(#fresh)]
end

local function stopCurrent()
    if current then
        animation.cancel(self, current)
        current = nil
        currentParent = nil
    end
end

I.AnimationController.addPlayBlendedAnimationHandler(function(parent, options)
    local category = CATEGORIES[parent]
    if not category then return end

    if settings:get(category.setting) == false then return end

    local fall = category.kind == KIND_DEATH

    -- Draw the clip FIRST, then roll for whether to use it.
    --
    -- That order is what lets the chance depend on what was drawn. Being thrown
    -- sideways is a bigger departure from what the engine would have done than
    -- being shoved straight back, so it is worth having less often, and rolling
    -- before the draw could only ever apply one number to every stagger alike.
    -- Losing the roll means simply not touching the animation, so the engine
    -- plays its own - which is the point: vanilla reactions stay in the mix.
    local bearing, awayBearing, vertical = nil, nil, 0
    if settings:get('DirectionAware') ~= false then
        bearing, awayBearing, vertical = wantedBearing()
    end
    local groupname = pickGroup(category.kind, bearing, awayBearing, vertical)
    if not groupname then return end

    -- Rolled once per reaction, not once per blow. A blow landing while a clip
    -- of ours is still running is a CONTINUATION, and re-rolling it was what cut
    -- staggers short:
    --
    --   the engine gives every hit state the same priority table, so playing
    --   hit2 ERASES hit1 rather than layering over it. An erase fires
    --   animationEnded, the handler below sees the group it erased is the one
    --   our clip was riding, and cancels our clip. If the new blow had won its
    --   roll that is harmless - we had already swapped to a new clip and moved
    --   currentParent on. Losing it left currentParent pointing at the erased
    --   state, so the stagger was cancelled a fraction into itself and the
    --   character snapped to the vanilla twitch underneath.
    --
    -- Staying ours also matches the blend rules, which give clip-to-clip the
    -- same sharp entry as the first blow.
    local continuing = current ~= nil and CATEGORIES[currentParent] == category
    local chance = chanceFor(category.kind, groupname)
    if not continuing and chance < 100 and math.random(100) > chance then
        if logging() then
            log(('  %s -> %s declined on a %d%% roll, engine keeps it'):format(
                parent, groupname, chance))
        end
        return
    end

    if logging() then
        log(('  %s -> %s (clip bearing %s, %s at %d%%)'):format(parent, groupname,
            tostring(clipBearing(groupname)),
            fall and 'death' or (SIDEWAYS[groupname] and 'sideways' or 'forward/back'),
            chance))
    end

    local ours = keySpan(groupname, clips.START_KEY, clips.STOP_KEY)
    if not ours then return end

    -- Anything left over from a previous hit has to go before the new clip
    -- starts: playing a group that is already active only updates its priority,
    -- it does not restart it.
    stopCurrent()

    local theirs = keySpan(parent, options.startKey or 'start', options.stopKey or 'stop')
    local clipSpeed = 1

    if fall then
        -- A death's timing is left alone entirely. When the engine's animation
        -- ends, addAnimationEndedHandler below lets go of the clip instead of
        -- cancelling it, so the fall plays out in full and holds wherever it
        -- landed. Stretching the engine's animation to match would buy nothing,
        -- and would hold the actor in a dying state longer than it was meant to
        -- be.
    elseif ours > STAGGER_MAX then
        -- Only ever faster, never slower. A clip shorter than the stun just ends
        -- early and leaves the character standing for the tail, which reads
        -- fine; stretching one out to fill the time reads as slow motion.
        clipSpeed = math.min(ours / STAGGER_TARGET, MAX_SPEEDUP)
    end
    -- Which bones our clip is allowed to move.
    --
    -- Leaving the arms out hands them to whatever else is playing. During combat
    -- that is the weapon animation at priority Weapon, so the character keeps
    -- their guard while the rest of them is thrown about. The arms still travel
    -- with the chest, because they hang off it; only their own pose stays put.
    --
    -- Staggers only. A character being killed should let go, not hold form.
    local mask = animation.BLEND_MASK.All
    if not fall and settings:get('KeepWeaponArms') ~= false then
        mask = animation.BLEND_MASK.LowerBody + animation.BLEND_MASK.Torso
    end

    -- And the engine's own animation gets the bones we left alone, rather than
    -- being hidden outright.
    --
    -- It used to get blendMask 0 - invisible everywhere - which is why the arms
    -- had nothing of their own to fall back on. The bone groups are bit flags
    -- and All is every bit, so All minus ours is exactly the complement: with
    -- the arms held back, the engine's hit reaction drives the arms and our clip
    -- drives everything else. Its state still exists and still advances either
    -- way, which is what the hit state machine is waiting on.
    --
    -- Worth knowing what this does and does not change. With a weapon drawn it
    -- changes nothing: the weapon animation sits at priority Weapon (7) and a
    -- hit reaction at Hit (6), so the guard still wins the arms - which is
    -- vanilla's own behaviour, and the reason vanilla hit reactions are a
    -- lower-body twitch whenever a weapon is out. With nothing drawn there is no
    -- Weapon-priority animation, so the arms now play the real hit reaction
    -- instead of carrying on with the idle or running arm swing.
    options.blendMask = animation.BLEND_MASK.All - mask

    if logging() then
        local plays = ours / clipSpeed
        local cut = (not fall) and theirs and (plays - theirs) or 0
        log(('play: %s over %s | clip %.2fs | engine %s | speed x%.2f -> %.2fs%s%s'):format(
            groupname, parent, ours,
            theirs and ('%.2fs'):format(theirs) or 'unknown',
            clipSpeed, plays,
            continuing and ' | CONTINUING a reaction already ours' or '',
            cut > 0.005 and (' | CUT SHORT by %.2fs'):format(cut) or ''))
        log(('  bones: ours %d, engine %d'):format(mask, options.blendMask))
    end

    -- Straight to the engine binding, not through the interface: going back
    -- through playBlendedAnimation would re-enter this handler.
    animation.playBlended(self, groupname, {
        startKey = clips.START_KEY,
        stopKey = clips.STOP_KEY,
        priority = category.priority,
        blendMask = mask,
        -- A fall keeps its last frame, so the body stays where it landed
        -- instead of snapping back to the vanilla pose underneath.
        autoDisable = not fall,
        -- Both animations run 0..1 over their own span, so the engine's
        -- fraction carries straight across. It matters for corpses: a death
        -- restored from a save is played from startPoint 1, and starting ours
        -- at 0 instead would make every body re-enact its death on cell load.
        startPoint = options.startPoint or 0,
        speed = clipSpeed,
        loops = 0,
    })

    current = groupname
    currentParent = parent
    lastGroup = groupname
end)

I.AnimationController.addAnimationEndedHandler(function(groupname)
    -- Our own clip reaching its stop key. autoDisable takes the state away; all
    -- that is left to do is stop claiming it is still running, so a later blow
    -- is treated as a fresh reaction and rolls for itself again.
    if groupname == current and groupname ~= currentParent then
        if logging() then log('clip', groupname, 'finished') end
        current = nil
        return
    end

    if groupname ~= currentParent then return end
    if CATEGORIES[groupname] == DEATH then
        -- A corpse stays down. Forget the clip rather than cancelling it.
        --
        -- Worth logging, because the engine hangs something on this moment: a
        -- summoned creature is only dissolved once its own death animation has
        -- stopped playing (CharacterController::kill sets
        -- setDeathAnimationFinished, summoning.cpp then purges the effect). If
        -- this line never appears for a summon that failed to dissolve, the
        -- engine's death animation is what is stuck, not our clip.
        if logging() then
            log('engine death group', groupname, 'ended; ours keeps its last frame')
        end
        current = nil
        currentParent = nil
        return
    end
    if logging() and current then
        log('cut:', current, 'cancelled because', groupname, 'ended')
    end
    stopCurrent()
end)

-- The damage listener is the only thing here that needs the actor to be active
-- first: I.MSS does not exist until every script on the actor has loaded.
local damageRegistered = false

return {
    engineHandlers = {
        onActive = function()
            if damageRegistered then return end
            damageRegistered = true
            pcall(function() I.MSS.addDamageListener(onDamage) end)
        end,
    },
}
