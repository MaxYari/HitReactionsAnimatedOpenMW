-- Menu context: setting renderers can only be registered here. Draws the banner
-- at the top of the settings page.
local I = require('openmw.interfaces')
local ui = require('openmw.ui')
local util = require('openmw.util')

-- Content rectangle of the banner inside its 1024x512 texture, as printed by
-- tools/make_banner.py. The rest of the canvas is transparent padding, there
-- only because OpenMW wants power-of-two sides.
local BANNER_TEXTURE = ui.texture {
    path = 'textures/MaxYari/HitReactionsAnimated/banner.dds',
    offset = util.vector2(0, 0),
    size = util.vector2(1024, 307),
}
local BANNER_WIDTH = 480

I.Settings.registerRenderer('HitReactionsAnimatedBanner', function()
    return {
        type = ui.TYPE.Flex,
        -- the settings row puts renderers on the right; out-growing the row's
        -- spacer centres the banner instead
        external = { grow = 1000 },
        props = { horizontal = true, align = ui.ALIGNMENT.Center, arrange = ui.ALIGNMENT.Center },
        content = ui.content {
            {
                type = ui.TYPE.Image,
                props = {
                    resource = BANNER_TEXTURE,
                    size = util.vector2(BANNER_WIDTH, BANNER_WIDTH * 307 / 1024),
                },
            },
        },
    }
end)

return {}
