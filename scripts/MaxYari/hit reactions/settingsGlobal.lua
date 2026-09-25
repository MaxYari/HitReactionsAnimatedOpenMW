local I = require('openmw.interfaces')
local deps = require('scripts/MaxYari/hit reactions/dependencies')

-- Nothing to configure if the mod is standing down; see dependencies.lua.
if not deps.ready() then return end

I.Settings.registerGroup {
    key = 'SettingsHitReactionsAnimated',
    page = 'HitReactionsAnimatedPage',
    l10n = 'HitReactionsAnimated',
    name = 'General',
    permanentStorage = true,
    settings = {
        {
            key = 'Intensity',
            renderer = 'number',
            default = 1,
            argument = { min = 0.05, max = 1 },
            name = 'Intensity',
            description = 'How much of the hit animation plays on each hit. 1.0 plays the full animation, 0.1 starts it almost at its end.',
        },
    },
}
