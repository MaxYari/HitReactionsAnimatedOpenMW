local I = require('openmw.interfaces')

local deps = require('scripts/MaxYari/hit reactions/dependencies')

-- Nothing to configure if the mod is not going to run.
if not deps.ready() then return end

I.Settings.registerGroup {
    -- The storage key stays as it was so tuned values survive the move into
    -- Hit Reactions Animated; it is internal and never shown.
    key = 'SettingsBrutalStaggers',
    page = 'HitReactionsAnimatedPage',
    l10n = 'HitReactionsAnimated',
    name = 'Staggers and deaths',
    permanentStorage = true,
    settings = {
        {
            key = 'CustomStaggerChance',
            renderer = 'number',
            default = 75,
            argument = { min = 0, max = 100, integer = true },
            name = 'Custom staggers, forward and back (%)',
            description = 'How often a stagger that throws the character forwards or backwards '
                .. 'is used. The rest of the time the engine plays its own. Zero, along with '
                .. 'the sideways figure, turns custom staggers off.',
        },
        {
            key = 'SidewaysStaggerChance',
            renderer = 'number',
            default = 50,
            argument = { min = 0, max = 100, integer = true },
            name = 'Custom staggers, sideways (%)',
            description = 'The same, for one that throws them to a side. Lower by default '
                .. 'because it departs further from vanilla.',
        },
        {
            key = 'CustomDeathChance',
            renderer = 'number',
            default = 90,
            argument = { min = 0, max = 100, integer = true },
            name = 'Custom deaths (%)',
            description = 'How often a death is used. Zero turns custom deaths off.',
        },
        {
            key = 'DirectionAware',
            renderer = 'checkbox',
            default = true,
            name = 'Match the attack',
            description = 'Throw the character the way the blow actually pushes, from where the '
                .. 'attacker stands and how their weapon swings. Off picks at random.',
        },
        {
            key = 'FarByDamage',
            renderer = 'checkbox',
            default = true,
            name = 'Long falls for heavy blows',
            description = 'Throw the character further the harder they were hit, measured '
                .. 'against their own maximum health. A heavy blow lets a stagger reach for the '
                .. 'long clips, and makes a death use them outright.',
        },
        {
            key = 'KeepWeaponArms',
            renderer = 'checkbox',
            default = true,
            name = 'Keep the weapon arms steady',
            description = 'Stagger the body but leave the arms to their guard. Off animates the '
                .. 'whole body. Staggers only.',
        },
        {
            key = 'LogAttackDirection',
            renderer = 'checkbox',
            default = false,
            name = 'Log hits and staggers (diagnostic)',
            description = 'Write what each hit was read as, and how its clip fared, to '
                .. 'openmw.log. Several lines per hit.',
        },
    },
}
