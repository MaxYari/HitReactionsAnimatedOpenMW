"""Check an exported clip is turned the right way in game.

    python3 Sources/check_facing.py

Compares where each exported clip's root motion actually travels against where
the source BVH says it should, both expressed in the frame vanilla itself
defines. Read that frame off vanilla's movement animations:

    walkforward  +90      walkback  -90      walkleft  180      walkright  0

so a clip whose character is pushed to their left should land near 180, one
pushed right near 0, and so on.

Two separate things can be wrong and they fail differently:

  travel   where the root motion carries the character. Accumulated by the
           engine in the ACTOR's frame, so this is the direction a player sees
           them thrown. Compared against the source clip.

  body     which way the skeleton is turned, from the composed
           Bip01 x Bip01 Pelvis yaw. Independent of travel - Bip01's own
           rotation turns its children, not its translation - so a clip can
           slide the right way while facing a quarter turn off.

The body reference is empirical: BODY_REFERENCE is the value measured on a build
confirmed correct in game, not vanilla's own. Comparing against vanilla's ~0
does not work, and the reason is worth knowing - the composed yaw mixes each
rig's bone rest orientations, so it is only comparable between builds of THIS
rig. An earlier version of this script compared to vanilla, passed a build whose
root motion was a quarter turn out, then failed the build that was finally
right.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import staggers_common as common  # noqa: E402

MOD = common.mod_root()
sys.path.insert(0, os.path.join(os.path.dirname(MOD),
                                "ReAnimation v2 Rogue - OpenMW-52596-2-7-1771797842",
                                "Sources", "Tools", "FBACompat"))
from nifkf import KF  # noqa: E402

# Where a clip's own forward ends up, in the frame the exported Bip01 translation
# lives in - so subtracting it from an exported bearing gives the direction the
# character travels in their own terms, ready to compare against what Blender
# measured before the export.
#
# The same +Y as export_exp.ACTION_FORWARD, and for the same reason: the rig
# rests on the x=0 plane, so forward is +Y, and the export does not turn it.
#
# This used to say 79.1, fitted against the source BVHs. That was the same
# comparison export_exp was making, not an independent one, and both carried the
# BVHs' own 11 degree bias; mirroring a clip is what exposed it. See the note on
# ACTION_FORWARD in export_exp.py.
MORROWIND_FORWARD = 90.0

# Wide on purpose. This catches a clip turned a quarter or a half turn, which is
# the failure that has actually happened here; it cannot resolve anything finer.
# A bearing is a straight line between two points and says nothing about the path
# between them, so a clip that curves reads as off by a good margin either way.
TOLERANCE = 45.0

# The body check compares the clips against EACH OTHER rather than against a
# constant, because there is no constant to compare to. An earlier version had
# one, measured off a build confirmed correct in game - but it was measured at
# that clip's Start key, and a hand-marked Start lands wherever the marker was
# put. Sampled there the composed yaw is the character mid-turn: over the half
# second after Start, StaggerStumbleRight2 swings from -56 to +167 degrees. It
# was measuring the animation.
#
# At t=0, the first frame in the file, every clip is standing in the same place,
# so they should agree with one another whatever that shared value turns out to
# be. A clip with a constant rotation baked in - the failure this is here to
# catch - sits apart from the rest.
BODY_TOLERANCE = 10.0


def compass(bearing):
    angle = (bearing + 360) % 360
    if angle < 45 or angle >= 315:
        return "right"
    if angle < 135:
        return "forward"
    if angle < 225:
        return "left"
    return "back"


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def euler_q(x, y, z):
    cx, sx = math.cos(x / 2), math.sin(x / 2)
    cy, sy = math.cos(y / 2), math.sin(y / 2)
    cz, sz = math.cos(z / 2), math.sin(z / 2)
    return (cx * cy * cz + sx * sy * sz, sx * cy * cz - cx * sy * sz,
            cx * sy * cz + sx * cy * sz, cx * cy * sz - sx * sy * cz)


def node_rotation(kf, bone, time):
    data = kf.data(bone)
    if data.rot_type == 4 and data.xyz:
        parts = []
        for group in data.xyz:
            keys = group['keys']
            value = min(keys, key=lambda k: abs(k[0] - time))[1] if keys else 0.0
            parts.append(value[0] if isinstance(value, tuple) else value)
        return euler_q(*parts)
    if data.quat_keys:
        return min(data.quat_keys, key=lambda k: abs(k[0] - time))[1]
    return None


def body_yaw(path, group):
    """Composed Bip01 x Bip01 Pelvis yaw at the first frame in the file."""
    kf = KF.load(path)
    root = node_rotation(kf, "Bip01", 0.0)
    pelvis = node_rotation(kf, "Bip01 Pelvis", 0.0)
    if root is None or pelvis is None:
        return None
    w, x, y, z = qmul(root, pelvis)
    return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def exported_bearing(path, group):
    kf = KF.load(path)
    keys = dict((k, t) for t, k in kf.groups()[group])
    track = kf.data("Bip01").trans['keys']
    if len(track) < 2:
        return None

    def at(time):
        return min(track, key=lambda k: abs(k[0] - time))[1]

    start = at(keys['start'])
    end = at(keys.get('stop', keys['start']))
    dx, dy = end[0] - start[0], end[1] - start[1]
    if math.hypot(dx, dy) < 1.0:
        return None
    return math.degrees(math.atan2(dy, dx))


def main():
    print("root motion: where each exported clip travels, against what the build measured\n"
          "off its action in Blender - so this is checking the export, not the retarget")
    print(f"this rig's forward measures {MORROWIND_FORWARD:+.1f} in that frame "
          f"(vanilla's own movement animations put it at +90)\n")
    print(f"{'clip':24s} {'travel want':>12s} {'got':>12s} {'off':>7s} {'body t=0':>9s}")

    # What shipped, and what each clip's source was. The group name alone does
    # not say - "deathdown" comes from Knock Down Left.bvh - so the build writes
    # the pairing out. Falling back to CLIPS covers the older pipeline, whose
    # group names and clip names were the same thing.
    # What shipped, and the bearing the build measured for each clip off its
    # action in Blender. Comparing against that rather than against a source BVH
    # is what lets this check every clip: a mirrored copy has no BVH at all, and
    # a clip marked over a different window than the recording travels somewhere
    # the recording never does.
    shipped = common.read_manifest()
    if shipped is None:
        raise SystemExit("no Sources/shipped_clips.json - run export_exp.py first")

    worst, bad, bodies, offsets = 0.0, [], [], []
    for entry in shipped:
        group = entry["group"]
        path = os.path.join(MOD, "Animations", "xbase_anim", f"x{group}.kf")
        if not os.path.exists(path):
            continue

        relative = entry.get("bearing")
        got = exported_bearing(path, group.lower())
        if relative is None or got is None:
            print(f"{group:24s} {'-':>18s} {'-':>18s}   no travel to measure")
            continue

        want = MORROWIND_FORWARD + relative
        off = ((got - want + 180) % 360) - 180
        worst = max(worst, abs(off))
        offsets.append((group, off))
        flag = ""
        if abs(off) > TOLERANCE:
            flag = "  <-- TURNED"
            bad.append(group)
        body = body_yaw(path, group.lower())
        bodies.append((group, body))
        body_txt = f"{body:+7.1f}" if body is not None else "none"

        print(f"{group:24s} {want:+11.1f} {got:+11.1f} {off:+7.1f} {body_txt:>8s}{flag}")

    print(f"\nworst travel offset: {worst:.1f} degrees")
    if bad:
        print(f"{len(bad)} clip(s) travel the wrong way, rebuild: {', '.join(bad)}")
    else:
        print("travel: every clip goes the way its source does")

    # A whole build turned the same way is the failure the constant above is
    # there to catch, and it would show up as every clip drifting together
    # rather than as any one of them standing out.
    if offsets:
        drift = sorted(o for _, o in offsets)[len(offsets) // 2]
        if abs(drift) > TOLERANCE / 2:
            print(f"travel: the whole set sits {drift:+.1f} degrees off, which looks "
                  "like a turned build rather than a bad clip - recheck the retarget")

    measured = sorted(b for _, b in bodies if b is not None)
    if not measured:
        print("body: nothing to measure")
        return
    middle = measured[len(measured) // 2]
    odd = [g for g, b in bodies
           if b is None or abs(((b - middle + 180) % 360) - 180) > BODY_TOLERANCE]
    print(f"body at t=0: {len(measured)} clip(s) around {middle:+.1f} degrees, "
          f"spread {measured[-1] - measured[0]:.1f}")
    if odd:
        print(f"{len(odd)} clip(s) start turned away from the rest, worth a look: "
              + ", ".join(odd))
    else:
        print("body: every clip starts turned the same way")


if __name__ == "__main__":
    main()
