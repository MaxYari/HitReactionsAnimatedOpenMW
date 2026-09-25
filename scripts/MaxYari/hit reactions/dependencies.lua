-- The one place that says what this mod cannot run without.
--
-- Max Yari's Script Services provides the damage listener the hit reactions are
-- driven from. It is a hard requirement for the whole mod, not just for that
-- half: a partly-working install is harder to diagnose than one that says
-- plainly why nothing is happening.

local core = require('openmw.core')

local M = {}

M.MSS_CONTENT_FILE = 'MaxYariScriptServices.omwscripts'
M.NAME = 'Hit Reactions Animated'

-- Read by .github/workflows/nexus-release.yml to version the Nexus upload.
-- Bump it here and the next [nexus] commit publishes under the new number.
M.VERSION = "2.0"


--- Wrapped, because contentFiles is not reachable from every script context.
function M.hasMSS()
    local ok, has = pcall(function() return core.contentFiles.has(M.MSS_CONTENT_FILE) end)
    return ok and has == true
end

--- Call at the top of every script this mod registers. Returns false when the
--- script should do nothing at all.
function M.ready()
    return M.hasMSS()
end

function M.missingMessage()
    return M.NAME .. ': critical dependency missing. Install Max Yari\'s Script Services ('
        .. M.MSS_CONTENT_FILE .. '); nothing in this mod runs without it.'
end

return M
