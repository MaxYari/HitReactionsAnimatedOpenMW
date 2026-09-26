-- End to end: weapon group + attack type + where the attacker stands
--             -> swing vector -> bearing -> the clip that gets played
--             -> which way that clip actually carries the character.
--
--     luajit Sources/tests/test_attack_directions.lua
--
-- Run from the mod root. Needs no Blender and no OpenMW: it reads the real
-- attack_directions.yaml through the real reader, and the real clips.lua, and
-- mirrors the scoring in brutalStaggers.lua.
--
-- Conventions, which are the thing most likely to be wrong and are therefore
-- what this asserts:
--
--   swing.x    the ATTACKER's frame. +1 the blade travels to their right, so a
--              slash that goes LEFT TO RIGHT is +1.
--   bearing    the VICTIM's frame. 0 straight ahead, +90 their left, 180 behind,
--              -90 their right. Both the push and every clip use this.
--
-- The two hinge on each other: an attacker facing their victim has their right
-- on the victim's left, so a left-to-right slash throws the victim to the
-- victim's LEFT, a positive bearing.

package.loaded['openmw.vfs'] = {
    fileExists = function(p) local f = io.open(p) if f then f:close() return true end return false end,
    open = function(p)
        local f = assert(io.open(p))
        return { lines = function() return f:lines() end, close = function() f:close() end }
    end,
}

local M = dofile('scripts/MaxYari/hit reactions/staggers/direction_math.lua')
local clips = dofile('scripts/MaxYari/hit reactions/staggers/clips.lua')
local cfg = dofile('scripts/MaxYari/hit reactions/staggers/direction_config.lua')
local dirs = cfg.read()

local AWAY, SLACK, DOWNWARD = 0.8, 35, -0.6
local FWD_X, FWD_Y, LEFT_X, LEFT_Y = 0, 1, -1, 0

local passed, failed = 0, 0
local function check(ok, what)
    if ok then passed = passed + 1 else failed = failed + 1 print('  FAIL: ' .. what) end
end

local function side(bearing)
    if bearing == nil then return 'nowhere' end
    if math.abs(bearing) < 25 then return 'forward' end
    if math.abs(bearing) > 155 then return 'back' end
    return bearing > 0 and 'their left' or 'their right'
end

local function swingOf(group, typeName)
    local g = dirs[group]
    if g and g[typeName] then return g[typeName] end
    return dirs['default'] and dirs['default'][typeName] or { x = 0, y = 0 }
end

-- The union brutalStaggers.pickGroup builds.
local function pool(kind, bearing, awayBearing, vertical)
    local function one(b)
        local scored, best = {}, nil
        for _, c in ipairs(clips.list) do
            if c.kind == kind then
                local s = b and M.bearingGap(c.bearing, b) or 0
                if vertical <= DOWNWARD and c.tags.down then s = s - 45 end
                scored[#scored + 1] = { g = c.group, s = s }
                if best == nil or s < best then best = s end
            end
        end
        local out = {}
        for _, e in ipairs(scored) do if e.s <= best + SLACK then out[#out + 1] = e.g end end
        return out
    end
    local out, seen = {}, {}
    for _, g in ipairs(one(bearing)) do if not seen[g] then seen[g] = true; out[#out+1] = g end end
    if awayBearing and awayBearing ~= bearing then
        for _, g in ipairs(one(awayBearing)) do if not seen[g] then seen[g] = true; out[#out+1] = g end end
    end
    table.sort(out)
    return out
end

local function clipBearing(group)
    for _, c in ipairs(clips.list) do if c.group == group then return c.bearing end end
end

local function clipTags(group)
    for _, c in ipairs(clips.list) do if c.group == group then return c.tags end end
    return {}
end

-- Where the attacker stands, as victim -> attacker.
local WHERE = {
    { 'in front',        0,  100 },
    { 'behind',          0, -100 },
    { 'on their left', -100,   0 },
    { 'on their right', 100,   0 },
}

print('=== 1. the yaml says what it is meant to say =====================')
-- One-handed slashes left to right; every other weapon right to left.
check(swingOf('weapononehand', 'slash').x > 0, 'weapononehand slash should be left-to-right (+x)')
for _, g in ipairs({ 'weapontwohand', 'weapontwowide', 'handtohand', 'default' }) do
    check(swingOf(g, 'slash').x < 0, g .. ' slash should be right-to-left (-x)')
end
-- Chop comes down, thrust has no sweep at all.
for _, g in ipairs({ 'weapononehand', 'weapontwohand', 'weapontwowide', 'handtohand', 'default' }) do
    check(swingOf(g, 'chop').y < 0, g .. ' chop should come down (-y)')
    local t = swingOf(g, 'thrust')
    check(t.x == 0 and t.y == 0, g .. ' thrust should have no sweep')
end
-- Every alternating group is the opposite of the parent it stands in for.
local PAIRS = {
    { 'weapononehand', 'weapononehand1' },
    { 'weapontwohand', 'weapontwohandalt' },
    { 'weapontwohandktn', 'weapontwohandktnalt' },
    { 'weapontwowide', 'weapontwowidealt' },
    { 'handtohand', 'handtohandalt' },
}
for _, p in ipairs(PAIRS) do
    local a, b = swingOf(p[1], 'slash'), swingOf(p[2], 'slash')
    check(a.x * b.x < 0, p[2] .. ' slash should reverse ' .. p[1])
    local ca, cb = swingOf(p[1], 'chop'), swingOf(p[2], 'chop')
    check(ca.y * cb.y < 0, p[2] .. ' chop should reverse ' .. p[1])
end
-- Substitutes stand in for the parent, so they swing the same way.
for _, p in ipairs({ { 'weapontwohand', 'weapontwohandsub' },
                     { 'weapontwowide', 'weapontwowidesub' },
                     { 'weapontwohand', 'weapontwohandktn' } }) do
    check(swingOf(p[1], 'slash').x * swingOf(p[2], 'slash').x > 0,
          p[2] .. ' should swing the same way as ' .. p[1])
end

-- A weapon mod's override group must be listed, or the lookup prefers the parent
-- it overrides and hands back the wrong directions. Katars are the case that
-- caught it: hand-to-hand animations on a weapononehand parent.
local function listed(group)
    return dirs[group] ~= nil
end
for _, g in ipairs({ 'katar', 'kataralt' }) do
    check(listed(g), g .. ' must be listed, or it inherits weapononehand and swings backwards')
end
check(swingOf('katar', 'slash').x * swingOf('handtohand', 'slash').x > 0,
      'katar slashes the same way as hand-to-hand, whose animations it uses')
check(swingOf('katar', 'chop').y * swingOf('handtohand', 'chop').y > 0,
      'katar chops the same way as hand-to-hand')
check(swingOf('katar', 'slash').x * swingOf('weapononehand', 'slash').x < 0,
      'and therefore the opposite way to weapononehand, the group it overrides')
check(swingOf('katar', 'slash').x * swingOf('kataralt', 'slash').x < 0,
      'kataralt is the mirrored pair, so it reverses katar')
check(swingOf('katar', 'chop').y * swingOf('kataralt', 'chop').y < 0,
      'kataralt chops the other way too')

print('=== 2. a blow pushes away from whoever swung =====================')
-- Thrust has no sweep, so the bearing is purely "away from the attacker".
local EXPECT_AWAY = { ['in front'] = 'back', ['behind'] = 'forward',
                      ['on their left'] = 'their right', ['on their right'] = 'their left' }
for _, w in ipairs(WHERE) do
    local b = M.pushBearing(w[2], w[3], FWD_X, FWD_Y, LEFT_X, LEFT_Y, 0, AWAY)
    check(side(b) == EXPECT_AWAY[w[1]],
          ('thrust from %s should throw them %s, got %s (%+.0f)'):format(
              w[1], EXPECT_AWAY[w[1]], side(b), b))
end

print('=== 3. a slash throws them the way the blade travels =============')
-- Attacker in front: their right is the victim's left.
local oneH = M.pushBearing(0, 100, FWD_X, FWD_Y, LEFT_X, LEFT_Y, swingOf('weapononehand', 'slash').x, AWAY)
local twoH = M.pushBearing(0, 100, FWD_X, FWD_Y, LEFT_X, LEFT_Y, swingOf('weapontwohand', 'slash').x, AWAY)
check(oneH > 0, ('one-handed slash from the front should throw them LEFT, got %+.0f'):format(oneH))
check(twoH < 0, ('two-handed slash from the front should throw them RIGHT, got %+.0f'):format(twoH))
check(math.abs(oneH + twoH) < 1e-6, 'the two slashes should mirror each other exactly')

print('=== 4. the clip that gets played goes that way ===================')
-- The real test: not what the bearing says, but which way the character is
-- actually carried once a clip has been chosen.
for _, kind in ipairs({ 'stagger', 'death' }) do
    for _, g in ipairs({ 'weapononehand', 'weapontwohand' }) do
        for _, w in ipairs(WHERE) do
            for _, t in ipairs({ 'chop', 'slash', 'thrust' }) do
                local sw = swingOf(g, t)
                local b = M.pushBearing(w[2], w[3], FWD_X, FWD_Y, LEFT_X, LEFT_Y, sw.x, AWAY)
                local away = M.pushBearing(w[2], w[3], FWD_X, FWD_Y, LEFT_X, LEFT_Y, 0, AWAY)
                local chosen = pool(kind, b, away, sw.y)
                check(#chosen > 0, ('%s/%s/%s/%s picked nothing'):format(kind, g, t, w[1]))

                -- Every clip offered has to earn its place in ONE of the two
                -- pools - the swung bearing or the sweep-free one. The slack
                -- window is measured per bearing, against the best clip for
                -- THAT bearing: a clip can sit far from where the sweep points
                -- and still be the closest thing to a straight shove, which is
                -- the whole reason the second pool exists. Comparing against
                -- the better of the two bests instead would fail such a clip
                -- for doing exactly its job.
                local function bestFor(bearing)
                    local best = nil
                    for _, c in ipairs(clips.list) do
                        if c.kind == kind then
                            local gap = M.bearingGap(c.bearing, bearing)
                            if sw.y <= DOWNWARD and c.tags.down then gap = gap - 45 end
                            if best == nil or gap < best then best = gap end
                        end
                    end
                    return best
                end
                local bestSwung, bestAway = bestFor(b), bestFor(away)
                for _, name in ipairs(chosen) do
                    local function gapFor(bearing)
                        local gap = M.bearingGap(clipBearing(name), bearing)
                        if sw.y <= DOWNWARD and clipTags(name).down then gap = gap - 45 end
                        return gap
                    end
                    local earned = gapFor(b) <= bestSwung + SLACK + 1e-9
                                or gapFor(away) <= bestAway + SLACK + 1e-9
                    check(earned,
                          ('%s/%s/%s/%s offered %s: %.0f off best %.0f (swung), '
                           .. '%.0f off best %.0f (away)'):format(
                              kind, g, t, w[1], name,
                              gapFor(b), bestSwung, gapFor(away), bestAway))
                end
            end
        end
    end
end

print('=== 5. what it looks like ========================================')
print(('%-14s %-7s %-16s %8s  %-12s %s'):format(
    'weapon', 'attack', 'attacker', 'bearing', 'thrown', 'stagger clips (travel)'))
for _, g in ipairs({ 'weapononehand', 'weapontwohand' }) do
    for _, t in ipairs({ 'chop', 'slash', 'thrust' }) do
        for _, w in ipairs(WHERE) do
            local sw = swingOf(g, t)
            local b = M.pushBearing(w[2], w[3], FWD_X, FWD_Y, LEFT_X, LEFT_Y, sw.x, AWAY)
            local away = M.pushBearing(w[2], w[3], FWD_X, FWD_Y, LEFT_X, LEFT_Y, 0, AWAY)
            local chosen = pool('stagger', b, away, sw.y)
            local shown = {}
            for _, n in ipairs(chosen) do
                shown[#shown + 1] = ('%s->%s'):format(n:gsub('^stagger', ''), side(clipBearing(n)))
            end
            print(('%-14s %-7s %-16s %+8.0f  %-12s %s'):format(
                g, t, w[1], b, side(b), table.concat(shown, ', ')))
        end
    end
end

print()
print(('%d passed, %d failed'):format(passed, failed))
os.exit(failed == 0 and 0 or 1)
