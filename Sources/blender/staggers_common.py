"""Shared data for the Brutal Staggers build: the clip list and the BVH trimming.

Every clip in Sources/*.bvh is an endorphin simulation that starts standing and
ends on the floor, so each one carries two usable animations: the part before the
character commits to falling (a stagger) and the whole thing (a knockdown or a
death). Both ship in one .kf, separated by text keys - see MARKERS below.
"""

import json
import math
import os

# group name -> BVH file. The group name is what OpenMW sees, lowercased, as the
# part of a text key before ": ". Keep them distinct from every vanilla group.
CLIPS = [
    # First batch: knockbacks and staggers.
    ("BSKnockBack",          "Knock Back.bvh"),
    ("BSKnockBackHigh",      "Knock Back High.bvh"),
    ("BSKnockBackHighFace",  "Knock Back High Face.bvh"),
    ("BSKnockDownLeft",      "Knock Down Left.bvh"),
    ("BSKnockDownLeft2",     "Knock Down Left 2.bvh"),
    ("BSKnockForward",       "Knock Forward.bvh"),
    ("BSStaggerBack",        "Stagger Back.bvh"),
    ("BSStaggerLeft",        "Stagger left.bvh"),
    ("BSStaggerLongLeft",    "Stagger longer left.bvh"),
    ("BSStaggerRight",       "Stagger right.bvh"),
    # Second batch. Named deaths and stumbles, but every one of them still ends
    # on the floor, so they carry a stagger and a fall just like the first.
    ("BSDeathBack",          "2_Death_Back.bvh"),
    ("BSDeathBackFar",       "2_Death_Back_Far.bvh"),
    ("BSDeathBackFar2",      "2_Death_Back_Far2.bvh"),
    ("BSDeathBackFarFlip",   "2_Death_Back_Far_Flip.bvh"),
    ("BSDeathDown",          "2_Death_Down.bvh"),
    ("BSDeathDownLeft",      "2_Death_Down_Left.bvh"),
    ("BSDeathDownRight",     "2_Death_Down_Right.bvh"),
    ("BSDeathDownRight2",    "2_Death_Down_Right2.bvh"),
    ("BSDeathForwardFar",    "2_Death_Forward_Far.bvh"),
    ("BSDeathForwardMed",    "2_Death_Forward_Med.bvh"),
    ("BSDeathLeftFar",       "2_Death_Left_Far.bvh"),
    ("BSDeathRightFar",      "2_Death_Right_Far.bvh"),
    ("BSStumbleBack",        "2_Stumble_Back.bvh"),
    ("BSStumbleLeft",        "2_Stumble_Left.bvh"),
    ("BSStumbleLeft2",       "2_Stumble_Left2.bvh"),
    ("BSStumbleRight",       "2_Stumble_Right.bvh"),
    ("BSStumbleRight2",      "2_Stumble_Right2.bvh"),
]

# Text keys written into every clip. "stagger stop" is an early stop key: playing
# the group with stopKey="stagger stop" gives the stagger, with "stop" the fall.
# OpenMW's reset() truncates the stop-key comparison to the expected length, and
# "<g>: stag" never equals "<g>: stop", so the two keys cannot be confused.
# Markers placed by hand, in Blender frames: (start, stagger stop, stop). A stop of
# None means "use the trim end", for a clip where only the stagger was marked.
#
# Kept here rather than only in the .blend so the marking survives a rebuild and
# is visible in the source. The build uses these in preference to both the
# computed trim and whatever is currently in the action.
MANUAL_MARKERS = {
    # stagger stop moved from 41 to 60 so both marked clips run the same
    # 0.82s, rather than one being half the length of the other.
    "BSStumbleRight2": (11, 60, 146),
    "BSStumbleLeft2": (11, 60, None),
}

KEY_START = "Start"
KEY_STAGGER_STOP = "Stagger Stop"
KEY_STOP = "Stop"


# Hip joint to ankle joint on the Morrowind skeleton, in Blender units: the
# lengths of Bip01 Thigh.L and Bip01 Calf.L added together, measured off the rig
# off the Morrowind rig.
MORROWIND_HIP_TO_ANKLE = 0.6986


def bvh_rest_offsets(path):
    """{joint name: (x, y, z)} from the BVH hierarchy's OFFSET lines.

    A joint's offset is its position in its parent's frame with every rotation
    zero, so its length is the parent bone's length whatever pose the clip is in.
    """
    offsets = {}
    name = None
    for line in open(path):
        parts = line.split()
        if not parts:
            continue
        if parts[0] in ("ROOT", "JOINT"):
            name = parts[1]
        elif parts[0] == "OFFSET" and name is not None:
            offsets[name] = tuple(float(v) for v in parts[1:4])
            name = None
        elif parts[0] == "MOTION":
            break
    return offsets


def source_scale(path):
    """Uniform scale for the BVH rig so its root motion lands in Morrowind units.

    Only rotations and the root's translation come across in a retarget, and the
    pose is the target rig's own, so the one thing the source's size has to get
    right is the translation. Matching leg length does that.

    Measured off the skeleton rather than off the first frame: the second batch
    of clips opens with the knees slightly bent, so its frame-zero pelvis sits at
    34.9 where the first batch's stands at 38.5, and scaling to that would have
    made those characters 10% too big. Bone lengths do not care about the pose.

    It also beats ARP's auto-scale, which compares whole-armature bounding boxes
    and skips every target bone whose head is below z=0 - both legs, on this rig -
    and so came out 2.9x too large here.
    """
    offsets = bvh_rest_offsets(path)
    thigh = math.dist((0, 0, 0), offsets["LeftKneeJoint"])
    shin = math.dist((0, 0, 0), offsets["LeftAnkleJoint"])
    return MORROWIND_HIP_TO_ANKLE / (thigh + shin)


def read_bvh_motion(path):
    """Return (frame_count, frame_time, rows) for a BVH file."""
    lines = open(path).read().splitlines()
    i = next(n for n, l in enumerate(lines) if l.strip() == "MOTION")
    count = int(lines[i + 1].split(":")[1])
    frame_time = float(lines[i + 2].split(":")[1])
    rows = [list(map(float, l.split())) for l in lines[i + 3:i + 3 + count] if l.strip()]
    return count, frame_time, rows


def trim_points(path):
    """Where to start, where the stagger ends, and where to stop, in BVH frames.

    The clips are raw simulation output: several open with the character standing
    still, and all of them end with the body settled on the floor for seconds. Both
    ends are cut by motion energy - the per-frame sum of root travel and joint
    rotation change, smoothed over a quarter second.

    The stagger cut is the last frame the pelvis is still at three quarters of its
    standing height, i.e. the last moment the character is plausibly on their feet.
    'Stagger longer left' dips and recovers before falling for good, which is why
    this is the LAST such frame rather than the first drop.
    """
    count, frame_time, rows = read_bvh_motion(path)

    energy = [0.0]
    for i in range(1, count):
        travel = math.dist(rows[i][0:3], rows[i - 1][0:3])
        rotation = sum(abs(a - b) for a, b in zip(rows[i][3:], rows[i - 1][3:]))
        energy.append(travel * 3 + rotation)

    window = 15
    smooth = [sum(energy[max(0, i - window):i + 1]) / min(window, i + 1) for i in range(count)]

    start = next((i for i, v in enumerate(smooth) if v > 10), 0)
    start = max(0, start - 10)
    end = max((i for i, v in enumerate(smooth) if v > 8), default=count - 1)
    end = min(count - 1, end + 20)

    heights = [r[1] for r in rows]
    standing = heights[0]
    upright = [i for i, h in enumerate(heights) if h >= 0.75 * standing and i <= end]
    stagger_stop = upright[-1] if upright else start + 12
    stagger_stop = max(start + 12, min(stagger_stop, end - 2))

    return start, stagger_stop, end, frame_time


def travel_bearing(path, frm, to):
    """Where the character goes between two frames, in degrees off its own forward.

    0 is forward, +90 the character's left, 180 back. The BVH skeleton separates
    its hips along +-X with the left hip at +X, and up is +Y, so forward is +Z.
    """
    _, _, rows = read_bvh_motion(path)
    frm = max(0, min(frm, len(rows) - 1))
    to = max(0, min(to, len(rows) - 1))
    dx = rows[to][0] - rows[frm][0]
    dz = rows[to][2] - rows[frm][2]
    if math.hypot(dx, dz) < 1e-6:
        return None
    return math.degrees(math.atan2(dx, dz))


def clip_bearing(group, path):
    """Which way a clip carries the character, in degrees off its own forward.

    0 is forward, +90 the character's left, 180 back, -90 right. Measured over
    the whole clip, which is steadier than the stagger window alone - a short
    stagger can be dominated by the first stumble rather than where the blow
    actually threw them.
    """
    start, _, end, _ = trim_points(path)
    return travel_bearing(path, start, end)


def clip_directions(group, path=None):
    """Direction tags for a clip: where it actually travels, plus "down" by name.

    Measured rather than read off the name, because a name and this tag are in
    different frames. The names are written from the VIEWER's side - a player
    watching the character they hit - so every clip called Left travels to the
    character's own right and every Right to their own left, checked across all
    27. Back and Forward need no swap.

    "down" stays a name tag: it marks a downward blow, which is not a direction
    of travel at all, and every one of these clips ends on the floor anyway.
    """
    tags = []
    if "Down" in group:
        tags.append("down")

    if path is not None:
        start, _, end, _ = trim_points(path)
        bearing = travel_bearing(path, start, end)
        if bearing is not None:
            angle = (bearing + 360) % 360
            if angle < 45 or angle >= 315:
                tags.append("forward")
            elif angle < 135:
                tags.append("left")
            elif angle < 225:
                tags.append("back")
            else:
                tags.append("right")

    return tags or ["any"]


def blender_dir():
    """Where the build scripts live: Sources/blender."""
    return os.path.dirname(os.path.abspath(__file__))


def sources_dir():
    """The Sources root. Everything under it is build material, not shipped."""
    return os.path.dirname(blender_dir())


def bvh_dir():
    """The endorphin recordings every clip is retargeted from."""
    return os.path.join(sources_dir(), "bvh")


def bvh_path(name):
    return os.path.join(bvh_dir(), name)


def mod_root():
    """The mod folder itself - what OpenMW's data= line points at."""
    return os.path.dirname(sources_dir())


def script_dir():
    """Where the mod's stagger Lua lives, and where clips.lua is generated."""
    return os.path.join(mod_root(), "scripts", "MaxYari", "hit reactions", "staggers")


# What the last export actually shipped, written by export_exp.py.
#
# A shipped clip's group name says nothing about where it came from - "deathdown"
# gives no hint that its source is Knock Down Left.bvh - and the connection lives
# only in the .blend, in which action was retargeted from which BVH. This is that
# connection, written out so the checks that compare an exported .kf against its
# source can stay plain python instead of needing Blender.
MANIFEST = "shipped_clips.json"


def manifest_path():
    return os.path.join(sources_dir(), MANIFEST)


def read_manifest():
    """The last build's clip list, or None if nothing has been exported yet."""
    path = manifest_path()
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return json.load(handle)


def write_manifest(entries):
    with open(manifest_path(), "w") as handle:
        json.dump(entries, handle, indent=2)
        handle.write("\n")
