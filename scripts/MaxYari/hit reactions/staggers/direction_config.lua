-- Reads attack_directions.yaml.
--
-- A deliberately small reader for one shape of file, not a YAML library: a
-- two-level mapping whose leaves are two-number flow sequences.
--
--     groupname:
--       attacktype: [x, y]
--
-- Comments, blank lines and surrounding whitespace are allowed anywhere. Tabs
-- are not - YAML forbids them for indentation and silently mis-reading one
-- would be worse than saying so. Anything else is reported by line number and
-- skipped, so one bad line costs one entry rather than the whole file.

local vfs = require('openmw.vfs')

local PATH = 'scripts/MaxYari/hit reactions/staggers/attack_directions.yaml'

-- Reporting is off unless the caller asks for it, and only one script on one
-- actor does. This file is read by every NPC and every creature in the cell, so
-- anything printed here unconditionally is printed dozens of times a load.
local function warn(report, path, line, text)
    if not report then return end
    print(('[Hit Reactions Animated] %s line %d: %s'):format(path, line, text))
end

--- { [groupname] = { [attacktype] = {x = , y = } } }
local function read(report, path)
    path = path or PATH
    if not vfs.fileExists(path) then
        warn(report, path, 0, 'not found; every attack falls back to its type')
        return {}
    end

    local handle = vfs.open(path)
    local out, group, number = {}, nil, 0

    for line in handle:lines() do
        number = number + 1
        local text = line:gsub('#.*$', '')

        if text:find('\t') then
            warn(report, path, number, 'tab used for indentation, line skipped')
        elseif text:match('^%s*$') then
            -- blank
        elseif text:match('^%S') then
            -- "groupname:" at the left margin opens a block
            local name = text:match('^([%w_%.%-]+)%s*:%s*$')
            if name then
                group = name:lower()
                out[group] = out[group] or {}
            else
                group = nil
                warn(report, path, number, 'expected "groupname:", got ' .. text:gsub('%s+$', ''))
            end
        else
            -- "  attacktype: [x, y]" inside a block
            local key, x, y = text:match('^%s+([%w_%.%-]+)%s*:%s*%[%s*(-?[%d%.]+)%s*,%s*(-?[%d%.]+)%s*%]%s*$')
            if not key then
                warn(report, path, number, 'expected "name: [x, y]", got ' .. text:gsub('^%s+', ''):gsub('%s+$', ''))
            elseif not group then
                warn(report, path, number, 'indented entry before any group name')
            else
                out[group][key:lower()] = { x = tonumber(x), y = tonumber(y) }
            end
        end
    end
    handle:close()

    return out
end

return { read = read, PATH = PATH }
