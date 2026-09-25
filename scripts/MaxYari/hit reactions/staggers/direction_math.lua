-- Working out which way a blow throws someone.
--
-- Plain numbers in, plain number out, no engine types: this is the part worth
-- being sure about, and keeping it free of openmw lets it be tested directly.
-- See Sources/test_direction_math.lua.
--
-- Everything is in the horizontal plane. Bearings are in the same terms the
-- clips are measured in: degrees off the victim's own forward, 0 straight
-- ahead, +90 to their left, 180 behind, -90 to their right.

local M = {}

--- Which way the victim gets thrown.
--
-- @param offsetX,offsetY  from the victim to the attacker, world, unnormalised
-- @param forwardX,forwardY the victim's forward, world, unit
-- @param leftX,leftY       the victim's left, world, unit
-- @param swingX            sideways sweep of the swing, in the ATTACKER's frame:
--                          negative their left, positive their right
-- @param awayWeight        how much of the push is simply "away from whoever
--                          swung" rather than the sweep
-- @return bearing in degrees, or nil if the two are on top of each other
function M.pushBearing(offsetX, offsetY, forwardX, forwardY, leftX, leftY, swingX, awayWeight)
    local distance = math.sqrt(offsetX * offsetX + offsetY * offsetY)
    if distance < 1e-6 then return nil end

    -- From the attacker towards the victim: the direction a blow shoves them.
    local awayX, awayY = -offsetX / distance, -offsetY / distance

    -- The attacker's right, seen from above, is their forward turned a quarter
    -- turn clockwise: (fx, fy) -> (fy, -fx). Their forward is "towards the
    -- victim", close enough since they are swinging at them.
    --
    -- The other sign here gives their LEFT, and every sweep comes out mirrored:
    -- a slash that should throw the target one way throws it the other, and it
    -- looks plausible enough in game to miss.
    local rightX, rightY = awayY, -awayX

    local pushX = awayX * awayWeight + rightX * swingX
    local pushY = awayY * awayWeight + rightY * swingX
    local length = math.sqrt(pushX * pushX + pushY * pushY)
    if length < 1e-6 then return nil end
    pushX, pushY = pushX / length, pushY / length

    -- Flatten the victim's frame before measuring against it.
    --
    -- forward and left arrive as the victim's 3D axes with the z dropped, and a
    -- victim who is looking up or down has a SHORTER horizontal forward -
    -- cos(pitch) of one - while their left stays a full unit long. Dividing an
    -- unscaled sideways component by a shrunken ahead one stretches the angle:
    -- a blow that lands at 51 degrees off reads as 57 at 30 degrees of pitch and
    -- keeps growing from there. It shows up as the push direction drifting with
    -- where the victim happens to be looking, which is not a thing a sword cares
    -- about.
    --
    -- Only the player pitches far enough to notice, and only when the player is
    -- the one being hit. Normalising both axes makes the measurement depend on
    -- the victim's facing alone. Yaw keeps the two perpendicular, so this stays
    -- a proper frame.
    local forwardLength = math.sqrt(forwardX * forwardX + forwardY * forwardY)
    local leftLength = math.sqrt(leftX * leftX + leftY * leftY)
    if forwardLength < 1e-6 or leftLength < 1e-6 then return nil end
    forwardX, forwardY = forwardX / forwardLength, forwardY / forwardLength
    leftX, leftY = leftX / leftLength, leftY / leftLength

    local ahead = pushX * forwardX + pushY * forwardY
    local sideways = pushX * leftX + pushY * leftY
    return math.deg(math.atan2(sideways, ahead))
end

--- Shortest angle between two bearings, 0..180.
function M.bearingGap(a, b)
    return math.abs((a - b + 180) % 360 - 180)
end

return M
