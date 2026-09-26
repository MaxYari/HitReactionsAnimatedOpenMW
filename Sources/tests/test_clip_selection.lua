-- Which clips a given push would choose, end to end.
--     luajit Sources/tests/test_clip_selection.lua
-- Run from the mod root. Mirrors the scoring in brutalStaggers.lua.
--
-- Staggers and falls are drawn from separate pools now - a stagger clip ends on
-- its feet and a fall clip ends on the floor - so every scenario is shown twice.

local M = dofile('scripts/MaxYari/hit reactions/staggers/direction_math.lua')
local clips = dofile('scripts/MaxYari/hit reactions/staggers/clips.lua')

local AWAY, SLACK, DOWNWARD = 0.8, 35, -0.6
local FWD_X, FWD_Y, LEFT_X, LEFT_Y = 0, 1, -1, 0

local function pool(kind, bearing, vertical)
    local scored, best = {}, nil
    for _, clip in ipairs(clips.list) do
        if clip.kind == kind then
            local score = M.bearingGap(clip.bearing, bearing)
            if vertical <= DOWNWARD and clip.tags.down then score = score - 45 end
            scored[#scored + 1] = { g = clip.group, s = score }
            if best == nil or score < best then best = score end
        end
    end
    local out = {}
    for _, e in ipairs(scored) do
        if e.s <= best + SLACK then out[#out + 1] = e.g end
    end
    table.sort(out)
    return out
end

-- The union brutalStaggers.pickGroup builds: where the blow throws them, plus
-- straight away from the attacker, so back/forward stays reachable under a sweep.
local function united(kind, bearing, awayBearing, vertical)
    local out, seen = {}, {}
    for _, g in ipairs(pool(kind, bearing, vertical)) do
        if not seen[g] then seen[g] = true; out[#out + 1] = g end
    end
    if awayBearing ~= bearing then
        for _, g in ipairs(pool(kind, awayBearing, vertical)) do
            if not seen[g] then seen[g] = true; out[#out + 1] = g end
        end
    end
    table.sort(out)
    return out
end

local function scenario(name, offX, offY, swingX, swingY)
    local b = M.pushBearing(offX, offY, FWD_X, FWD_Y, LEFT_X, LEFT_Y, swingX, AWAY)
    local away = M.pushBearing(offX, offY, FWD_X, FWD_Y, LEFT_X, LEFT_Y, 0, AWAY)
    print(('\n%s\n  push bearing %+.0f (sweep-free %+.0f), vertical %+.1f'):format(
        name, b, away, swingY))
    for _, kind in ipairs({ 'stagger', 'death' }) do
        local swung = table.concat(pool(kind, b, swingY), ', ')
        local both = table.concat(united(kind, b, away, swingY), ', ')
        local label = kind == 'stagger' and 'stagger' or 'fall   '
        print(('  %s : %s'):format(label, both))
        if both ~= swung then
            print(('            (swing alone would give: %s)'):format(swung))
        end
    end
end

local counts, dremora = {}, {}
for _, clip in ipairs(clips.list) do
    counts[clip.kind] = (counts[clip.kind] or 0) + 1
    if clip.dremora then
        dremora[#dremora + 1] = clip.group
        -- A dremora clip is retimed onto the mesh's death span, which exists
        -- only for a death. One marked as a stagger would fire the dissolve
        -- mid-fight.
        assert(clip.kind == 'death',
            ('dremora clip %s must be a death, not a %s'):format(clip.group, clip.kind))
    end
end
print(('collection: %d stagger, %d fall'):format(counts.stagger or 0, counts.death or 0))
print(('dremora-only falls: %s'):format(#dremora > 0 and table.concat(dremora, ', ') or 'none'))
print('  (listed in the pools below, but only Dremora ever draw them)')
print('victim faces +Y throughout; offset is victim -> attacker')

scenario('chop from the front (straight down, no sweep)',        0,  100,  0,   -1)
scenario('thrust from the front',                                0,  100,  0,    0)
scenario('thrust from behind',                                   0, -100,  0,    0)
scenario('slash from the front, sweeping to attacker right',     0,  100,  1,    0)
scenario('slash from the front, sweeping to attacker left',      0,  100, -1,    0)
scenario("attacker on the victim's left, straight blow",      -100,    0,  0,    0)
scenario('upward swing from the front',                          0,  100,  0,    1)
