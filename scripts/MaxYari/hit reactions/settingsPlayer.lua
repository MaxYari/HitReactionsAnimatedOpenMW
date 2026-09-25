local I = require('openmw.interfaces')
local deps = require('scripts/MaxYari/hit reactions/dependencies')

-- Nothing to configure if the mod is standing down; see dependencies.lua.
if not deps.ready() then return end

I.Settings.registerPage {
    key = 'HitReactionsAnimatedPage',
    l10n = 'HitReactionsAnimated',
    name = 'Hit Reactions Animated',
    description = 'Animated hit reactions, staggers, knockdowns and deaths for NPCs and the '
        .. 'player. Requires Max Yari\'s Script Services.',
}
