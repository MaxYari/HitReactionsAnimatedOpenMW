-- The no-repeat rule, and what it falls back to when it runs out of clips.
--     luajit Sources/tests/test_no_repeat.lua
-- Run from the mod root. Mirrors pickGroup's tail in brutalStaggers.lua.

local passed, failed = 0, 0
local function check(ok, what)
    if ok then passed = passed + 1 else failed = failed + 1; print('  FAIL: ' .. what) end
end

local lastGroup = nil
local function withoutLast(pool)
    if lastGroup == nil then return pool end
    local out = {}
    for i = 1, #pool do
        if pool[i] ~= lastGroup then out[#out + 1] = pool[i] end
    end
    return out
end

-- pool = the side the distance roll took, spare = the side it did not.
local function pick(pool, spare)
    local fresh = withoutLast(pool)
    if #fresh == 0 and spare ~= nil then fresh = withoutLast(spare) end
    if #fresh == 0 then return nil end
    return fresh[math.random(#fresh)]
end

print('a clip never repeats while another is available')
lastGroup = nil
local pool = { 'a', 'b', 'c' }
for i = 1, 300 do
    local got = pick(pool, nil)
    check(got ~= nil and got ~= lastGroup, 'repeated ' .. tostring(got) .. ' on draw ' .. i)
    lastGroup = got
end

print('\none clip left and it is the last one played')
lastGroup = 'only'
check(pick({ 'only' }, nil) == nil, 'single-clip pool should give up rather than repeat')
check(pick({ 'only' }, {}) == nil, 'empty spare is no help')

print('\nfar pool exhausted falls back to near, not to vanilla')
lastGroup = 'longside'
local got = pick({ 'longside' }, { 'shortside1', 'shortside2' })
check(got == 'shortside1' or got == 'shortside2',
      'should take a short clip, got ' .. tostring(got))

print('\nboth distances exhausted gives up')
lastGroup = 'x'
check(pick({ 'x' }, { 'x' }) == nil, 'nothing but the last clip anywhere -> vanilla')

print('\nthe spare is only reached when the chosen side is empty')
lastGroup = 'far1'
local seen = {}
for _ = 1, 300 do seen[pick({ 'far1', 'far2' }, { 'near1' })] = true end
check(seen['far2'] and not seen['near1'],
      'should stay on the far side while it still has an option')

print(('\n%d passed, %d failed'):format(passed, failed))
os.exit(failed == 0 and 0 or 1)
