local I = require('openmw.interfaces')
local deps = require('scripts/MaxYari/hit reactions/dependencies')

-- Nothing to configure if the mod is standing down; see dependencies.lua.
if not deps.ready() then return end

-- Banner across the top of the page. Its renderer lives in menu.lua, the only
-- context allowed to register one; nothing is stored, the group exists purely
-- to give the image a row to sit in.
I.Settings.registerGroup {
    key = 'SettingsHitReactionsAnimatedBanner',
    page = 'HitReactionsAnimatedPage',
    l10n = 'HitReactionsAnimated',
    name = '',
    order = 0,
    permanentStorage = false,
    settings = {
        { key = 'Banner', renderer = 'HitReactionsAnimatedBanner', default = '', name = '' },
    },
}

I.Settings.registerGroup {
    -- The storage key stays as it was so tuned values survive the rename; it is
    -- internal and never shown.
    key = 'SettingsHitReactionsAnimated',
    page = 'HitReactionsAnimatedPage',
    l10n = 'HitReactionsAnimated',
    name = 'Hit flinches',
    order = 1,
    description = 'Small, purely visual flinches in response to being damaged, played in '
        .. 'addition to whatever the character is doing at the time.',
    permanentStorage = true,
    settings = {
        {
            key = 'Intensity',
            renderer = 'number',
            default = 1,
            argument = { min = 0, max = 1 },
            name = 'Hit flinch intensity',
            description = 'How much of the flinch plays on each weapon, fist or projectile '
                .. 'hit. 1.0 plays the full animation, 0.1 starts it almost at its end, 0 '
                .. 'turns these flinches off.',
        },
        {
            key = 'IndirectIntensity',
            renderer = 'number',
            default = 0.33,
            argument = { min = 0, max = 1 },
            name = 'Indirect damage flinch intensity',
            description = 'The same, for damage that did not come from a hit: spells, '
                .. 'poison, falls and anything else that drains health. 0 turns these '
                .. 'flinches off.',
        },
        {
            key = 'IndirectFrequency',
            renderer = 'number',
            default = 2,
            argument = { min = 0 },
            name = 'Indirect damage flinch frequency',
            description = 'At most this many flinches a second from indirect damage, so a '
                .. 'spell that burns for a while does not flinch on every tick. Flinches '
                .. 'from hits are not limited.',
        },
        {
            key = 'NoPlayerFlinches',
            renderer = 'checkbox',
            default = false,
            name = 'No flinches on the player',
            description = 'Turn flinches off for the player only. NPCs and creatures keep '
                .. 'theirs.',
        },
        {
            key = 'CombatOnly',
            renderer = 'checkbox',
            default = true,
            name = 'Limit flinching only to combat state',
            description = 'Some mods do stuff to player and enemy hp outside of combat, '
                .. 'resulting in flinches. Keeping this ON should probably help with that.',
        },
    },
}
