-- Tests for scripts/MaxYari/hit reactions/staggers/direction_math.lua
--     luajit Sources/tests/test_direction_math.lua
-- Run from the mod root. No Blender, no OpenMW.

local M = dofile('scripts/MaxYari/hit reactions/staggers/direction_math.lua')

-- The victim always faces +Y here, so their left is -X and their right is +X.
local FWD_X, FWD_Y = 0, 1
local LEFT_X, LEFT_Y = -1, 0
local AWAY = 0.8

local function compass(b)
    if b == nil then return 'none' end
    local a = (b + 360) % 360
    if a < 45 or a >= 315 then return 'forward' end
    if a < 135 then return 'left' end
    if a < 225 then return 'back' end
    return 'right'
end

local passed, failed = 0, 0
local function check(name, offX, offY, swingX, expect)
    local b = M.pushBearing(offX, offY, FWD_X, FWD_Y, LEFT_X, LEFT_Y, swingX, AWAY)
    local got = compass(b)
    local ok = got == expect
    passed = passed + (ok and 1 or 0)
    failed = failed + (ok and 0 or 1)
    print(('  %-46s %7s  %-8s expected %-8s %s')
        :format(name, b and ('%.0f'):format(b) or 'nil', got, expect, ok and 'ok' or 'FAIL'))
end

print('victim faces +Y. offset is victim -> attacker.\n')

print('no sweep (a straight thrust): thrown directly away from the attacker')
check('attacker in front',                   0,  100, 0, 'back')
check('attacker behind',                     0, -100, 0, 'forward')
check("attacker on the victim's left",    -100,    0, 0, 'right')
check("attacker on the victim's right",    100,    0, 0, 'left')

print('\nslash sweeping to the attacker\'s right, attacker in front')
check('sweep right, attacker in front',      0,  100,  1, 'left')
check('sweep left,  attacker in front',      0,  100, -1, 'right')

print('\nsame slash from behind: sweep flips with the attacker')
check('sweep right, attacker behind',        0, -100,  1, 'right')
check('sweep left,  attacker behind',        0, -100, -1, 'left')

print('\ndiagonal, and a chop (no sweep) from a corner')
-- kept off the exact 45 degree diagonal, which lands on a compass boundary
check('attacker front-left, no sweep',     -40,  100, 0, 'back')
check('attacker front-right, no sweep',     40,  100, 0, 'back')
check('attacker hard front-left',        -100,   40, 0, 'right')
check('attacker hard front-right',        100,   40, 0, 'left')

print('\ndegenerate input')
check('attacker exactly on the victim',      0,    0, 0, 'none')
do
    local b = M.pushBearing(0, 100, FWD_X, FWD_Y, LEFT_X, LEFT_Y, -AWAY, AWAY)
    -- sweep exactly cancelling the away push would be a zero vector
    print(('  %-46s %7s  (cancelling push must not blow up)')
        :format('sweep cancels away push', b and ('%.0f'):format(b) or 'nil'))
end

print('\nlooking up or down must not change where a blow throws you')
-- The victim's forward arrives as their 3D axis with z dropped, so a pitched
-- victim has a horizontal forward only cos(pitch) long while their left stays a
-- full unit. Unnormalised, that stretches every angle - and the player pitches
-- constantly in first person.
do
    local flat = M.pushBearing(0, 100, FWD_X, FWD_Y, LEFT_X, LEFT_Y, -1, AWAY)
    for _, pitch in ipairs({ 0, 15, 30, 45, 60, 80, -30, -60 }) do
        local c = math.cos(math.rad(pitch))
        -- yaw 0, pitch p: forward -> (0, cos p, sin p), left -> (-1, 0, 0)
        local got = M.pushBearing(0, 100, 0, c, LEFT_X, LEFT_Y, -1, AWAY)
        local ok = got ~= nil and math.abs(M.bearingGap(got, flat)) < 0.001
        passed = passed + (ok and 1 or 0); failed = failed + (ok and 0 or 1)
        print(('  pitch %+3d deg -> %+7.1f (flat %+.1f)  %s'):format(
            pitch, got or 0/0, flat, ok and 'ok' or 'FAIL'))
    end
end

print('\nbearingGap wraps the short way')
local gaps = { {170, -170, 20}, {0, 360, 0}, {-90, 90, 180}, {10, 350, 20} }
for _, g in ipairs(gaps) do
    local got = M.bearingGap(g[1], g[2])
    local ok = math.abs(got - g[3]) < 0.001
    passed = passed + (ok and 1 or 0); failed = failed + (ok and 0 or 1)
    print(('  gap(%d, %d) = %.0f expected %d  %s'):format(g[1], g[2], got, g[3], ok and 'ok' or 'FAIL'))
end

print(('\n%d passed, %d failed'):format(passed, failed))
os.exit(failed == 0 and 0 or 1)
