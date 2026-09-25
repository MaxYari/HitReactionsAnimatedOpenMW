"""Append a two-step balance recovery to the current stagger action on the ARP rig.

Run from Blender's Text Editor with the ARP rig active (or the only ARP rig in
the scene) and the stagger clip assigned as its action. Only that action is
used, and it has to be an "[ARP] ..." action carrying its own two markers,
"Stagger...: Start" and "Stagger...: Stop" (see ACTION_PREFIX and the marker
patterns below); anything else stops with an error before touching the file.
Headless, with any setting below overridden by name:

    blender -b Sources/Reatrget.blend --python Sources/blender/stagger_recovery.py -- stance=L unclamped=0.5

A stagger is marked to stop while the character is off balance, usually on one
foot. Blending straight from there into idle reads as the body being hauled
upright on a string. This replaces everything after the end marker with a
recovery the body could actually perform:

1. Catch step. The free foot lands ahead of where the body will be at
   touchdown, by the distance the body still needs to stop - its capture
   offset, from a linear inverted pendulum - so the step brakes the fall
   (CATCH_AHEAD). The stance foot stays where it is, unless the body has
   already fallen past its reach, in which case it drags along after the body,
   skimming just off the floor (DRAG_STANCE_FOOT).
2. Closing step. The old stance foot, now the back one, steps up towards the
   new one, which stays planted, while the whole body eases back into the pose
   at the start marker. That pose is rebuilt at the new position and, by
   default, keeps the facing the stagger left the character with (KEEP_TURN).

The final pose is the start pose moved rigidly along the floor (a turn about
the vertical and a slide), anchored so its foot lands exactly where the catch
step put the free foot. The closing step then only has to bring the back foot
into the same stance the character started in.

The body moves on curves through key poses - the end pose, part way back at
each landing, the start pose - shaped like Blender's unclamped Auto handles, so
it carries the clip's momentum and flows through each pose instead of stopping
at it. UNCLAMPED scales that down if a clip overshoots. Feet ease to rest
wherever they land.

How the legs are keyed. The motion is solved on the FK controls, analytically,
so it is exact and continuous with the clip at the end marker. With
LEG_CONTROLS = "IK" (the default) the recovery's legs are then snapped onto
ARP's IK controls the way ARP's own IK-to-FK snap does it - c_foot_ik, c_toes_ik
and c_leg_pole keyed on every frame, ik_fk_switch blending from FK at the end
marker to IK over IK_BLEND_TIME - so the planted feet can be dragged about by
hand afterwards and stay planted. The FK keys stay underneath, so both modes
show the same motion. ARP's own snap operators cannot be used for this: they
need a 3D viewport for their update hack.

Output is a copy of the action named "<action> Recovery", assigned to the rig:
the clip up to the end marker, then the recovery, with the end marker moved to
the end of it. Keys and markers past the old end marker - the fall - are not
carried over. The source action is left as it was, apart from getting a fake
user so it is not lost on save once nothing uses it. Running again with the
recovery action assigned rebuilds it from its source, so settings can be
tweaked and re-run freely.

The start marker is the pose the recovery returns to; the stop marker is where
the stagger ends, off balance, and where the recovery takes over.
"""

import fnmatch
import math
import re
import sys

import bpy
from bpy_extras import anim_utils
from mathutils import Matrix, Quaternion, Vector

# --- Settings ---------------------------------------------------------------

# Speed of the catch step, from the end marker until the free foot lands: below
# 1 is faster, above 1 slower.
CATCH_TIME_SCALE = 0.5
# The same for everything after the catch lands: the pause, the closing step
# and the settle. The body's straightening follows both, since its key poses
# sit on the landings.
AFTER_CATCH_TIME_SCALE = 0.5

# How fast the feet can move in a step, as an average speed in Blender units per
# second, for both steps. A step never goes quicker than its length divided by
# this, whatever the time scales above ask for, so a long step takes longer
# instead of snapping across. Raise it for quicker feet, lower it for calmer ones.
STEP_SPEED = 3.0

# How far ahead of the body the catch foot lands, to brake the fall. The unit is
# how far the body would still travel before stopping over a foot planted under
# it at touchdown (its capture offset), so a fast fall gets a long step and a
# slow one a short step. 1 lands right where the body would come to rest; above
# 1 lands further ahead and brakes harder; below 1 lands short, leaving more for
# the closing step. Limited by CATCH_REACH_LEGS.
CATCH_AHEAD = 0.5

# The foot the character stands on at the end marker: "L", "R", or "AUTO" for
# whichever is lower and slower.
STANCE_FOOT = "L"

# How much of the facing the stagger ended on to keep. 1 keeps all of it, 0
# turns the character back to the facing it had at the start marker. Turning
# back runs through the whole recovery with everything else, starting while the
# body is still falling. The cap is off by default: a clip that spins the
# character keeps its spin.
KEEP_TURN = 0.3
MAX_TURN_DEG = 180.0

# "IK" keys the recovery's legs on ARP's IK controls as well, for hand editing;
# "FK" leaves them on the FK controls only.
LEG_CONTROLS = "IK"
# How long ik_fk_switch takes to go from FK to IK after the end marker. The two
# chains put knee and ankle in the same place, but ARP's IK leg cannot hold the
# small thigh twist the retarget has, so an instant switch pops the thigh's roll.
IK_BLEND_TIME = 0.2

# Step durations in seconds, before the time scales and STEP_SPEED at the top:
# base plus per Blender unit the foot travels.
STEP_TIME_BASE = 0.3
STEP_TIME_PER_UNIT = 0.35
STEP_TIME_MIN = 0.25
STEP_TIME_MAX = 0.50
# Both feet down between the two steps, and the settle after the second.
DOUBLE_SUPPORT_TIME = 0.10
SETTLE_TIME = 0.30

# How high the swinging ankle lifts mid-step, in Blender units.
STEP_HEIGHT_BASE = 0.05
STEP_HEIGHT_PER_UNIT = 0.08
STEP_HEIGHT_MAX = 0.12

# Furthest the catch foot may land ahead of the centre of mass at touchdown, in
# leg lengths (hip joint to ankle joint) - the leg's reach from the body, which
# is what limits a catch step; the stance foot behind drags up as needed.
CATCH_REACH_LEGS = 0.9
# Longest catch step measured from the stance foot instead, in leg lengths. Only
# used with DRAG_STANCE_FOOT off, when the stance foot cannot follow.
MAX_STEP_LEGS = 1.0
# Closest the catch step may land to the stance foot, and the closest a swinging
# ankle may pass the planted one, both in hip widths. Which side it lands on is
# left to the fall: a stumble that has spun the body often ends with the legs
# crossed, and the way out of that is a crossover step.
MIN_FOOT_GAP_HIPS = 1.0
SWING_CLEARANCE_HIPS = 1.1

# During the catch step, let the stance foot slide along after the body when
# the body has already fallen further than that leg reaches - the trailing foot
# drags, as it does in a real stumble - lifted DRAG_LIFT (Blender units) off the
# floor as soon as it starts to slide, so it skims rather than scrapes. Off, the
# stance foot stays put and the pelvis is held back within its reach instead,
# which can pull the body against its fall.
DRAG_STANCE_FOOT = True
DRAG_LIFT = 0.03

# How far the pelvis sinks below its straight path when the catch step lands.
CATCH_DIP = 0.02

# Leg extension limits the pelvis is held to, as a fraction of leg length.
MAX_LEG_EXTENSION = 0.985
MIN_LEG_EXTENSION = 0.55

# The body's curves - pelvis, spine, arms, head, the legs' reference pose - pass
# through key poses the way Blender's unclamped Auto handles do: they leave the
# end marker with the clip's own velocity and keep their speed through each key
# instead of stopping at it, so the recovery flows, and they may swing a little
# past a pose on the way. 1 is fully unclamped; lower it if a clip overshoots
# wildly; 0 behaves like Auto Clamped. Feet are clamped wherever they touch down
# regardless - a planted foot has to arrive at rest.
UNCLAMPED = 1.0
# Whatever velocity UNCLAMPED does not carry is still matched at the end marker,
# so nothing hitches there, and bled away over this long. Feet and toes also
# carry their end-marker motion for about this long.
MOMENTUM_TIME = 0.12

# The key poses: how far from the end pose to the start pose the body has come
# when the catch step lands and when the closing step lands.
RECOVERED_AT_CATCH = 0.4
RECOVERED_AT_CLOSING = 0.85

# Caps on carried velocity, in Blender units per second.
MAX_PELVIS_SPEED = 5.0
MAX_FOOT_SPEED = 3.0

# Smoothing of the pelvis corrections that keep the planted feet in reach.
PELVIS_SMOOTHING_FRAMES = 1.5

# Hip joint to ankle joint of a real adult, in metres. Only used to express
# gravity in Blender units for the capture point, so roughly right is enough.
REAL_LEG_LENGTH_M = 0.87

# Only actions whose names start with this are worked on, and only with their
# own markers matching these patterns (* matches anything, case is ignored).
ACTION_PREFIX = "[ARP]"
START_MARKER = "Stagger*: Start"
STOP_MARKER = "Stagger*: Stop"

# The generated action is named "<source action><suffix>".
OUTPUT_SUFFIX = " Recovery"
# Stretch the scene's end frame to cover the recovery.
SET_SCENE_RANGE = True

# --- Rig --------------------------------------------------------------------

TRAJ = "c_traj"
SIDES = {"L": ".l", "R": ".r"}
UP = Vector((0.0, 0.0, 1.0))
# The ARP rig faces -Y in armature space.
REST_FORWARD = Vector((0.0, -1.0, 0.0))

WATCHED = [TRAJ, "c_spine_02.x", "c_spine_03.x", "c_spine_04.x", "c_head.x"]
for _suffix in SIDES.values():
    WATCHED += [name + _suffix for name in (
        "c_thigh_fk", "c_leg_fk", "c_foot_fk", "c_toes_fk",
        "c_arm_fk", "c_forearm_fk", "c_hand_fk")]

# Segment mass fractions (Dempster, via Winter), and the head's centre of mass
# above the c_head.x pivot, in Blender units.
MASS_HEAD, MASS_TRUNK = 0.081, 0.497
MASS_UPPER_ARM, MASS_FOREARM, MASS_HAND = 0.028, 0.016, 0.006
MASS_THIGH, MASS_SHANK, MASS_FOOT = 0.100, 0.0465, 0.0145
HEAD_CENTRE = 0.06

CHANNEL_SIZE = {"location": 3, "rotation_quaternion": 4, "scale": 3}
CHANNEL_DEFAULT = {"location": (0, 0, 0), "rotation_quaternion": (1, 0, 0, 0), "scale": (1, 1, 1)}
SWITCH = "ik_fk_switch"


def log(*parts):
    print("[recovery]", *parts, flush=True)


# --- Maths ------------------------------------------------------------------

def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def smoother(s):
    """Smootherstep: zero velocity and acceleration at both ends."""
    s = clamp(s, 0.0, 1.0)
    return s * s * s * (s * (6 * s - 15) + 10)


def hermite(p0, m0, p1, m1, s):
    s2, s3 = s * s, s * s * s
    return (p0 * (2 * s3 - 3 * s2 + 1) + m0 * (s3 - 2 * s2 + s)
            + p1 * (-2 * s3 + 3 * s2) + m1 * (s3 - s2))


def coast_blend(x0, v0, x1, t, span, tau):
    """Ease from x0 to x1 over span frames, leaving x0 at velocity v0 per frame.

    The eased part starts at rest, so the clip's own velocity is added as a
    coast that decays over tau frames and fades out with the blend. The result
    matches the clip's position and velocity at t=0 and lands on x1 at rest.
    """
    u = smoother(t / span)
    coast = v0 * (tau * (1.0 - math.exp(-t / tau))) if tau > 0 else v0 * 0.0
    return x0 + (x1 - x0) * u + coast * (1.0 - u)


def flat(v):
    return Vector((v.x, v.y, 0.0))


def perpendicular(v, axis):
    return v - axis * v.dot(axis)


def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def signed_angle(a, b, axis):
    return math.atan2(axis.dot(a.cross(b)), a.dot(b))


def key_curve(times, values, start_velocity, unclamped, bleed_time):
    """A cubic through values at times, shaped like Blender's Auto handles.

    Inner tangents are Catmull-Rom, which is what unclamped Auto handles give,
    scaled by `unclamped`. The curve lands on the last value at rest and leaves
    the first with start_velocity * unclamped; the rest of start_velocity is
    added as a coast that has died away by the second key, so the curve always
    matches the clip's velocity where it joins it. Values may be floats or
    Vectors (a quaternion as a 4-vector, normalised by the caller).
    """
    tangents = [start_velocity * unclamped]
    for i in range(1, len(times) - 1):
        tangents.append((values[i + 1] - values[i - 1]) * (unclamped / (times[i + 1] - times[i - 1])))
    tangents.append(values[0] * 0.0)
    rest = start_velocity * (1.0 - unclamped)
    bleed_until = times[1] - times[0]

    def at(t):
        if t >= times[-1]:
            value = values[-1] * 1.0
        else:
            i = max(k for k in range(len(times) - 1) if times[k] <= t)
            span = times[i + 1] - times[i]
            value = hermite(values[i], tangents[i] * span, values[i + 1], tangents[i + 1] * span,
                            (t - times[i]) / span)
        if bleed_time > 0 and t < bleed_until:
            fade = 1.0 - smoother(t / bleed_until)
            value = value + rest * (bleed_time * (1.0 - math.exp(-t / bleed_time)) * fade)
        return value

    return at


def coast(x0, v0, t, tau):
    """Where x0 drifts to by t, leaving at v0 per frame and slowing over tau frames."""
    return x0 + v0 * (tau * (1.0 - math.exp(-t / tau))) if tau > 0 else x0 * 1.0


def bump(s, peak):
    """0 at s=0 and s=1, 1 at s=peak, flat at both ends."""
    if s <= 0.0 or s >= 1.0:
        return 0.0
    k = math.log(0.5) / math.log(clamp(peak, 0.05, 0.95))
    return math.sin(math.pi * s ** k) ** 2


def about(point, rotation):
    """A rotation matrix applied about a point rather than the origin."""
    return Matrix.Translation(point) @ rotation @ Matrix.Translation(-point)


def same_hemisphere(q, reference):
    return -q if q.dot(reference) < 0 else q


def gaussian_smooth(values, sigma):
    if sigma <= 0:
        return list(values)
    radius = int(3 * sigma) + 1
    kernel = [math.exp(-0.5 * (i / sigma) ** 2) for i in range(-radius, radius + 1)]
    last = len(values) - 1
    out = []
    for i in range(len(values)):
        total, weight = values[0] * 0.0, 0.0
        for offset, k in zip(range(-radius, radius + 1), kernel):
            total += values[clamp(i + offset, 0, last)] * k
            weight += k
        out.append(total / weight)
    return out


# --- Blender helpers ----------------------------------------------------------

def apply_overrides():
    """NAME=value after "--" on the command line overrides a setting above."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    for arg in argv:
        if "=" not in arg:
            continue
        name, value = arg.split("=", 1)
        name = {"STANCE": "STANCE_FOOT", "LEGS": "LEG_CONTROLS"}.get(name.upper(), name.upper())
        current = globals().get(name)
        if current is None or not name.isupper():
            log(f"unknown setting {name}, ignored")
            continue
        if isinstance(current, bool):
            globals()[name] = value.lower() in ("1", "true", "yes", "on")
        elif isinstance(current, str):
            globals()[name] = value.upper() if name in ("STANCE_FOOT", "LEG_CONTROLS") else value
        else:
            globals()[name] = type(current)(value)
        log(f"{name} = {globals()[name]!r}")


def find_rig():
    active = bpy.context.view_layer.objects.active
    if active and active.type == "ARMATURE" and TRAJ in active.data.bones:
        return active
    rigs = [o for o in bpy.context.scene.objects
            if o.type == "ARMATURE" and TRAJ in o.data.bones and "c_thigh_fk.l" in o.data.bones]
    if len(rigs) != 1:
        raise RuntimeError(f"make the ARP rig the active object (found {len(rigs)} candidates)")
    return rigs[0]


def assign(rig, action):
    ad = rig.animation_data
    ad.action = action
    if action is not None and ad.action_slot is None and len(action.slots):
        ad.action_slot = action.slots[0]


def read_channels(channelbag):
    """{bone: {property: [fcurve or None per component]}} for pose bone transforms."""
    bones = {}
    pattern = re.compile(r'pose\.bones\["(.+)"\]\.(location|rotation_quaternion|rotation_euler|scale)$')
    for fcurve in channelbag.fcurves:
        match = pattern.match(fcurve.data_path)
        if not match:
            continue
        name, prop = match.groups()
        if prop == "rotation_euler":
            raise RuntimeError(f"{name} is keyed in Euler; this expects quaternion keys")
        slots = bones.setdefault(name, {}).setdefault(prop, [None] * CHANNEL_SIZE[prop])
        slots[fcurve.array_index] = fcurve
    return bones


def local_at(channels, frame):
    """A bone's keyed local transform at a frame, as {property: Vector}."""
    values = {}
    for prop, fcurves in channels.items():
        values[prop] = Vector([fc.evaluate(frame) if fc else CHANNEL_DEFAULT[prop][i]
                               for i, fc in enumerate(fcurves)])
    return values


def find_markers(action):
    """The action's own start and stop markers, as (start name, frame, stop name, frame)."""
    def only(pattern):
        found = [m for m in action.pose_markers if fnmatch.fnmatchcase(m.name.lower(), pattern.lower())]
        if len(found) != 1:
            names = ", ".join(repr(m.name) for m in action.pose_markers) or "none"
            raise RuntimeError(f"'{action.name}' needs exactly one marker named like '{pattern}', "
                               f"found {len(found)} (its markers: {names})")
        return found[0]

    start, stop = only(START_MARKER), only(STOP_MARKER)
    if stop.frame < start.frame + 3:
        raise RuntimeError(f"'{action.name}': '{stop.name}' ({stop.frame}) has to come at least three "
                           f"frames after '{start.name}' ({start.frame})")
    return start.name, start.frame, stop.name, stop.frame


def set_pose_matrix(rig, pose_bone, matrix, rotation_only=False):
    """Give a bone this armature-space matrix, through its own local channels."""
    local = rig.convert_space(pose_bone=pose_bone, matrix=matrix,
                              from_space="POSE", to_space="LOCAL")
    loc, rot, scale = local.decompose()
    pose_bone.rotation_quaternion = rot
    if not rotation_only:
        pose_bone.location = loc
        pose_bone.scale = scale


def snap_matrix(rig, pose_bone, matrix):
    """Give a bone this final matrix, allowing for the Child Of ARP parents it by.

    ARP sets each Child Of's inverse to its target's rest matrix, so the target's
    matrix_channel (pose relative to rest) is the whole parent transform. Same
    as ARP's own snap_bone_matrix.
    """
    if pose_bone.parent is None:
        for c in pose_bone.constraints:
            if (c.type == "CHILD_OF" and not c.mute and c.influence > 0.5
                    and c.target == rig and c.subtarget):
                matrix = rig.pose.bones[c.subtarget].matrix_channel.inverted() @ matrix
                break
    pose_bone.matrix = matrix


def rest_relative(pose_bone):
    """A bone's rotation relative to its rest, in armature space."""
    return pose_bone.matrix.to_quaternion() @ pose_bone.bone.matrix_local.to_quaternion().inverted()


def sample(scene, rig, frame):
    scene.frame_set(frame)
    return {name: rig.pose.bones[name].matrix.copy() for name in WATCHED}


def write_keys(action, rig, keys):
    """keys: {(data_path, index): [(frame, value), ...]}, linear; replaces keys on those frames."""
    bag = anim_utils.action_get_channelbag_for_slot(action, rig.animation_data.action_slot)
    for (data_path, index), points in keys.items():
        fcurve = bag.fcurves.find(data_path, index=index)
        if fcurve is None:
            group = re.match(r'pose\.bones\["(.+?)"\]', data_path)
            fcurve = action.fcurve_ensure_for_datablock(
                rig, data_path, index=index, group_name=group.group(1) if group else "")
        for frame, value in points:
            key = fcurve.keyframe_points.insert(frame, value, options={"FAST"})
            key.interpolation = "LINEAR"
        fcurve.update()


# --- Body measurements ----------------------------------------------------------

def centre_of_mass(m):
    at = {name: mat.translation for name, mat in m.items()}
    hips = (at["c_thigh_fk.l"] + at["c_thigh_fk.r"]) / 2
    head = at["c_head.x"] + m["c_head.x"].col[1].xyz.normalized() * HEAD_CENTRE
    trunk = (hips + at["c_spine_02.x"] + at["c_spine_03.x"] + at["c_spine_04.x"]) / 4
    parts = [(MASS_HEAD, head), (MASS_TRUNK, trunk)]
    for s in SIDES.values():
        parts += [
            (MASS_UPPER_ARM, (at["c_arm_fk" + s] + at["c_forearm_fk" + s]) / 2),
            (MASS_FOREARM, (at["c_forearm_fk" + s] + at["c_hand_fk" + s]) / 2),
            (MASS_HAND, at["c_hand_fk" + s]),
            (MASS_THIGH, (at["c_thigh_fk" + s] + at["c_leg_fk" + s]) / 2),
            (MASS_SHANK, (at["c_leg_fk" + s] + at["c_foot_fk" + s]) / 2),
            (MASS_FOOT, (at["c_foot_fk" + s] + at["c_toes_fk" + s]) / 2),
        ]
    total = sum(w for w, _ in parts)
    return sum((p * w for w, p in parts), Vector()) / total


def facing(m, rest_forward, hip_width):
    """Which way the body faces, in radians about +Z, from pelvis, chest and hips.

    Each estimate is flattened onto the floor, so one that is tilted steeply
    (a pelvis rolled onto its side) counts for less.
    """
    total = Vector()
    for name, weight in ((TRAJ, 1.0), ("c_spine_03.x", 0.5)):
        forward = m[name].to_quaternion() @ rest_forward[name]
        total += flat(forward) * weight
    across = flat(m["c_thigh_fk.l"].translation - m["c_thigh_fk.r"].translation)
    total += across.cross(UP) / hip_width
    return math.atan2(total.y, total.x)


def contact(m, side):
    """Middle of the foot on the floor: halfway from ankle to toe joint, flattened."""
    s = SIDES[side]
    return flat((m["c_foot_fk" + s].translation + m["c_toes_fk" + s].translation) / 2)


# --- Leg solve --------------------------------------------------------------

def solve_leg(rig, side, target, hinge_local):
    """Bend the knee, then swing the thigh, so the ankle reaches target.

    The knee turns about its anatomical hinge (the thigh-space axis the rest pose
    bends about), by exactly the angle that gives the hip-to-ankle distance
    needed, choosing the solution that does not bend it backwards. The thigh then
    takes the shortest rotation that points the leg at the target, which keeps
    whatever knee direction the reference pose had.
    """
    s = SIDES[side]
    bones = rig.pose.bones
    thigh, leg = bones["c_thigh_fk" + s], bones["c_leg_fk" + s]
    hip, knee, ankle = thigh.head.copy(), leg.head.copy(), bones["c_foot_fk" + s].head.copy()

    axis = (thigh.matrix.to_quaternion() @ hinge_local).normalized()
    u, v = knee - hip, ankle - knee
    v_perp = perpendicular(v, axis)
    c = u + axis * v.dot(axis)
    w = axis.cross(v_perp)
    a, b = 2 * c.dot(v_perp), 2 * c.dot(w)
    k = (target - hip).length_squared - c.length_squared - v_perp.length_squared
    r = math.hypot(a, b)

    alpha = 0.0
    if r > 1e-9:
        phi = math.atan2(b, a)
        spread = math.acos(clamp(k / r, -1.0, 1.0))
        bend = signed_angle(perpendicular(u, axis), v_perp, axis)
        options = [wrap_angle(phi + spread), wrap_angle(phi - spread)]
        forward = [x for x in options if bend + x >= -1e-3]
        alpha = min(forward or options, key=abs)

    bend_rotation = Matrix.Rotation(alpha, 4, axis)
    leg_matrix = about(knee, bend_rotation) @ leg.matrix
    bent_ankle = knee + bend_rotation.to_3x3() @ v
    swing = (bent_ankle - hip).rotation_difference(target - hip)
    thigh_matrix = about(hip, swing.to_matrix().to_4x4()) @ thigh.matrix

    # Both are converted against the pose evaluated before either changed, which
    # is the parent space each matrix above was built in.
    set_pose_matrix(rig, leg, leg_matrix, rotation_only=True)
    set_pose_matrix(rig, thigh, thigh_matrix, rotation_only=True)


def set_foot(rig, side, rotation):
    foot = rig.pose.bones["c_foot_fk" + SIDES[side]]
    matrix = Matrix.LocRotScale(foot.head, rotation, foot.matrix.to_scale())
    set_pose_matrix(rig, foot, matrix, rotation_only=True)


def slide_to_reach(foot, direction, hip, reach):
    """How far a foot must slide along a floor direction to come within reach of hip."""
    w = hip - foot
    if w.length <= reach:
        return 0.0
    b = w.dot(direction)
    disc = b * b - w.length_squared + reach * reach
    return max(0.0, b - math.sqrt(disc)) if disc >= 0 else max(0.0, b)


def pelvis_correction(hips, targets, limits):
    """Pelvis offset that keeps each weighted foot target within leg reach."""
    delta = Vector()
    for _ in range(8):
        for side, (target, weight) in targets.items():
            if weight <= 0:
                continue
            lo, hi = limits[side]
            to_foot = target - (hips[side] + delta)
            d = to_foot.length
            if d > hi:
                delta += to_foot.normalized() * (d - hi) * weight
            elif d < lo and d > 1e-6:
                delta -= to_foot.normalized() * (lo - d) * weight
    return delta


# --- FK to IK ---------------------------------------------------------------

def knee_forward_rest(rest, s):
    """Which way the knee points at rest, square to the hip-ankle line."""
    hip = rest["c_thigh_fk" + s].head_local
    knee = rest["c_leg_fk" + s].head_local
    ankle = rest["c_foot_fk" + s].head_local
    return perpendicular(knee - hip, (ankle - hip).normalized()).normalized()


def knee_error(bones, s, knee_forward, leg_length):
    """How far round the leg the IK knee sits from the FK knee, in radians.

    Measured on the knees themselves about the hip-ankle line, as ARP's own
    compensate_ik_pole_position does. A nearly straight leg has no knee
    direction to measure, so there it hands over to comparing the thighs' twist.
    """
    hip, ankle = bones["c_thigh_fk" + s].head, bones["c_foot_fk" + s].head
    axis = (ankle - hip).normalized()
    middle = (hip + ankle) / 2
    want = perpendicular(bones["c_leg_fk" + s].head - middle, axis)
    have = perpendicular(bones["leg_ik" + s].head - middle, axis)
    by_knee = signed_angle(want, have, axis) if want.length > 1e-7 and have.length > 1e-7 else 0.0

    twist_want = perpendicular(rest_relative(bones["c_thigh_fk" + s]) @ knee_forward, axis)
    twist_have = perpendicular(rest_relative(bones["thigh_ik" + s]) @ knee_forward, axis)
    by_twist = signed_angle(twist_want, twist_have, axis) if twist_want.length > 1e-7 else 0.0

    bent = smoother((want.length / leg_length - 0.02) / 0.04)
    return by_knee * bent + by_twist * (1.0 - bent)


def legs_to_ik(scene, rig, action, frames, switch_frame, blend_frames):
    """Snap the IK leg controls onto the FK legs on every frame, and key them.

    Mirrors ARP's ik_to_fk_leg: c_foot_ik takes the FK foot's matrix, c_toes_ik
    the FK toes', and c_leg_pole sits in the knee's direction at ARP's pole
    distance. The pole is then turned about the leg until the IK thigh's twist
    matches the FK thigh's, which ARP does by trial as well. The knee direction
    comes from the thigh's own frame rather than from the bend, so a nearly
    straight leg still gets a steady pole.
    """
    bones = rig.pose.bones
    rest = rig.data.bones
    keys = {}

    def record(bone, prop, frame, value):
        for i, v in enumerate(value):
            keys.setdefault((f'pose.bones["{bone}"].{prop}', i), []).append((frame, v))

    forward = {side: knee_forward_rest(rest, s) for side, s in SIDES.items()}
    lengths = {side: rest["c_thigh_fk" + s].length
               + (rest["c_foot_fk" + s].head_local - rest["c_leg_fk" + s].head_local).length
               for side, s in SIDES.items()}
    pole_distance = {}
    for side, s in SIDES.items():
        ref = rest.get("foot_ref" + s)
        pole_distance[side] = ref.get("ik_pole_distance", 1.0) if ref else 1.0

    for frame in frames:
        scene.frame_set(frame)
        for s in SIDES.values():
            snap_matrix(rig, bones["c_foot_ik" + s], bones["c_foot_fk" + s].matrix.copy())
            bones["c_foot_ik" + s][SWITCH] = 0.0
        bpy.context.view_layer.update()

        for side, s in SIDES.items():
            bones["c_toes_ik" + s].matrix = bones["c_toes_fk" + s].matrix.copy()
            hip = bones["c_thigh_fk" + s].head
            knee = bones["c_leg_fk" + s].head
            axis = (bones["c_foot_fk" + s].head - hip).normalized()
            direction = perpendicular(rest_relative(bones["c_thigh_fk" + s]) @ forward[side], axis)
            pole_pos = knee + direction.normalized() * (knee - hip).length * pole_distance[side]
            pole = bones["c_leg_pole" + s]
            rotation, scale = pole.rotation_quaternion.copy(), pole.scale.copy()
            snap_matrix(rig, pole, Matrix.Translation(pole_pos))
            pole.rotation_quaternion, pole.scale = rotation, scale
        bpy.context.view_layer.update()

        for side, s in SIDES.items():
            pole = bones["c_leg_pole" + s]
            error = knee_error(bones, s, forward[side], lengths[side])
            turn = -1.0
            for _ in range(8):
                if abs(error) < 1e-4:
                    break
                hip = bones["c_thigh_fk" + s].head.copy()
                axis = (bones["c_foot_fk" + s].head - hip).normalized()
                pole_pos = about(hip, Matrix.Rotation(turn * error, 4, axis)) @ pole.head
                rotation, scale = pole.rotation_quaternion.copy(), pole.scale.copy()
                snap_matrix(rig, pole, Matrix.Translation(pole_pos))
                pole.rotation_quaternion, pole.scale = rotation, scale
                bpy.context.view_layer.update()
                new_error = knee_error(bones, s, forward[side], lengths[side])
                if abs(new_error) > abs(error):
                    turn = -turn
                error = new_error

        for s in SIDES.values():
            foot_ik = bones["c_foot_ik" + s]
            record(foot_ik.name, "location", frame, foot_ik.location)
            record(foot_ik.name, "rotation_quaternion", frame, foot_ik.rotation_quaternion)
            record(foot_ik.name, "scale", frame, foot_ik.scale)
            record(bones["c_toes_ik" + s].name, "rotation_quaternion", frame,
                   bones["c_toes_ik" + s].rotation_quaternion)
            record(bones["c_toes_ik" + s].name, "scale", frame, bones["c_toes_ik" + s].scale)
            record(bones["c_leg_pole" + s].name, "location", frame, bones["c_leg_pole" + s].location)
            switch_path = f'pose.bones["{foot_ik.name}"]["{SWITCH}"]'
            into = (frame - switch_frame) / blend_frames if blend_frames > 0 else 1.0
            keys.setdefault((switch_path, 0), []).append((frame, 1.0 - smoother(into)))

    # Quaternion keys stay in one hemisphere so the interpolation between them
    # never takes the long way round.
    for s in SIDES.values():
        for bone in ("c_foot_ik" + s, "c_toes_ik" + s):
            path = f'pose.bones["{bone}"].rotation_quaternion'
            columns = [keys[(path, i)] for i in range(4)]
            previous = None
            for n in range(len(columns[0])):
                q = Vector([columns[i][n][1] for i in range(4)])
                if previous is not None and q.dot(previous) < 0:
                    q = -q
                    for i in range(4):
                        columns[i][n] = (columns[i][n][0], q[i])
                previous = q

    write_keys(action, rig, keys)


def check_legs(scene, rig, frames):
    """Largest gap between the deforming knees and feet and the solved FK legs."""
    bones = rig.pose.bones
    worst_pos, worst_rot = 0.0, 0.0
    for frame in frames:
        scene.frame_set(frame)
        for s in SIDES.values():
            for deform, control in (("leg", "c_leg_fk"), ("foot", "c_foot_fk")):
                worst_pos = max(worst_pos, (bones[deform + s].head - bones[control + s].head).length)
            want = rest_relative(bones["c_foot_fk" + s])
            have = rest_relative(bones["foot" + s])
            angle = want.rotation_difference(have).angle
            worst_rot = max(worst_rot, math.degrees(min(angle, 2 * math.pi - angle)))
    return worst_pos, worst_rot


# --- Main -------------------------------------------------------------------

def main():
    apply_overrides()
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    rig = find_rig()
    if rig.mode == "EDIT":
        raise RuntimeError("leave Edit Mode first")
    if rig.data.pose_position != "POSE":
        raise RuntimeError("the rig is in Rest Position; switch it to Pose Position")
    if LEG_CONTROLS not in ("IK", "FK"):
        raise RuntimeError(f"LEG_CONTROLS must be IK or FK, not {LEG_CONTROLS!r}")
    ad = rig.animation_data
    if ad is None or ad.action is None:
        raise RuntimeError(f"'{rig.name}' has no action assigned")

    current = ad.action
    source = current
    if "recovery_source" in current:
        source = bpy.data.actions.get(current["recovery_source"])
        if source is None:
            raise RuntimeError(f"'{current.name}' was generated from '{current['recovery_source']}', "
                               f"which is gone; assign the original clip and run again")
    if source is not current:
        log(f"'{current.name}' was generated from '{source.name}'; rebuilding from that")
    if not source.name.startswith(ACTION_PREFIX):
        raise RuntimeError(f"'{source.name}' is not an {ACTION_PREFIX} action; assign one to the rig")
    start_name, start_f, end_name, end_f = find_markers(source)
    log(f"action '{source.name}': '{start_name}' {start_f}, '{end_name}' {end_f}")

    assign(rig, source)
    if not source.use_fake_user:
        # The rig is about to be switched to the recovery, which would leave the
        # source with no users - and Blender drops those on save.
        source.use_fake_user = True
        log(f"gave '{source.name}' a fake user so it survives the switch")
    channels = read_channels(anim_utils.action_get_channelbag_for_slot(source, ad.action_slot))
    if TRAJ not in channels:
        raise RuntimeError(f"'{source.name}' does not key {TRAJ}; is this a retargeted clip?")

    # For the IK hand-off the whole clip up to the end marker must be FK, which
    # is what the switch key at the end marker will say.
    for s in SIDES.values():
        rig.pose.bones["c_foot_ik" + s][SWITCH] = 1.0

    # Rest measurements.
    rest = rig.data.bones
    leg_length = {}
    hinge_local = {}
    for side, s in SIDES.items():
        hip = rest["c_thigh_fk" + s].head_local
        knee = rest["c_leg_fk" + s].head_local
        ankle = rest["c_foot_fk" + s].head_local
        leg_length[side] = (knee - hip).length + (ankle - knee).length
        bend_axis = (knee - hip).cross(ankle - knee)
        if bend_axis.length < 1e-7:
            raise RuntimeError(f"the {side} leg is dead straight at rest; no knee direction to go on")
        hinge_local[side] = rest["c_thigh_fk" + s].matrix_local.to_3x3().inverted() @ bend_axis.normalized()
    leg = (leg_length["L"] + leg_length["R"]) / 2
    hip_width = (rest["c_thigh_fk.l"].head_local - rest["c_thigh_fk.r"].head_local).length
    rest_forward = {name: rest[name].matrix_local.to_3x3().inverted() @ REST_FORWARD
                    for name in (TRAJ, "c_spine_03.x")}

    # Posed measurements, with the source action playing.
    at_start = sample(scene, rig, start_f)
    before2 = sample(scene, rig, end_f - 2)
    before1 = sample(scene, rig, end_f - 1)
    at_end = sample(scene, rig, end_f)

    def ankle(m, side):
        return m["c_foot_fk" + SIDES[side]].translation.copy()

    def toe_tip(m, side):
        s = SIDES[side]
        return m["c_toes_fk" + s] @ Vector((0, rest["c_toes_fk" + s].length, 0))

    stance = STANCE_FOOT.upper()
    if stance == "AUTO":
        # The foot carrying the weight is the one nearest the floor and moving
        # least; a stumbling clip often has neither flat, so height alone is a
        # coin toss. A tenth of a second of travel counts as much as height.
        def loaded(side):
            lowest = min(ankle(at_end, side).z, toe_tip(at_end, side).z)
            speed = flat(ankle(at_end, side) - ankle(before1, side)).length * fps
            return lowest + speed * 0.1
        stance = "L" if loaded("L") <= loaded("R") else "R"
        log(f"stance foot (auto, lowest and slowest): {stance}")
    elif stance not in SIDES:
        raise RuntimeError(f"STANCE_FOOT must be L, R or AUTO, not {STANCE_FOOT!r}")
    free = "R" if stance == "L" else "L"

    # Where the fall is heading: the capture point of a linear inverted pendulum.
    com_end = centre_of_mass(at_end)
    com_velocity = (com_end - centre_of_mass(before2)) * (fps / 2)
    floor_z = min(toe_tip(at_start, side).z for side in SIDES)
    height = max(com_end.z - floor_z, 0.2 * leg)
    gravity = 9.81 / (REAL_LEG_LENGTH_M / leg)
    omega = math.sqrt(gravity / height)
    capture = flat(com_end) + flat(com_velocity) / omega

    # Facing, relative to the start: what the stagger ended on, and how much of it is kept.
    end_turn = wrap_angle(facing(at_end, rest_forward, hip_width) - facing(at_start, rest_forward, hip_width))
    turn = clamp(end_turn * KEEP_TURN, -math.radians(MAX_TURN_DEG), math.radians(MAX_TURN_DEG))
    turn_matrix = Matrix.Rotation(turn, 4, "Z")

    # Catch step: land the free foot ahead of where the body will be at
    # touchdown, far enough to brake it - CATCH_AHEAD times its capture offset
    # there - and within the leg's reach. Where the body will be depends on how
    # long the step takes, which depends on how far it goes, so settle both.
    planted = contact(at_end, stance)
    across_start = flat(at_start["c_thigh_fk.l"].translation - at_start["c_thigh_fk.r"].translation)
    left_final = (turn_matrix.to_3x3() @ across_start).normalized()

    def step_seconds(distance):
        return clamp(STEP_TIME_BASE + STEP_TIME_PER_UNIT * distance, STEP_TIME_MIN, STEP_TIME_MAX)

    def step_frames(distance, scale=1.0):
        """A step's frames: the timing model, scaled, but no quicker than STEP_SPEED allows."""
        return max(2, round(max(step_seconds(distance) * scale, distance / STEP_SPEED) * fps))

    speed = flat(com_velocity).length
    heading = flat(com_velocity).normalized() if speed > 1e-6 else Vector()
    ahead = min(CATCH_AHEAD * speed / omega, CATCH_REACH_LEGS * leg)
    free_contact = contact(at_end, free)
    land1 = step_frames(0.5 * leg, CATCH_TIME_SCALE)
    for _ in range(4):
        touchdown = flat(com_end) + flat(com_velocity) * (land1 / fps)
        landing = touchdown + heading * ahead
        if not DRAG_STANCE_FOOT and (landing - planted).length > MAX_STEP_LEGS * leg:
            landing = planted + (landing - planted).normalized() * MAX_STEP_LEGS * leg
        gap = landing - planted
        if gap.length < MIN_FOOT_GAP_HIPS * hip_width:
            # Barely off balance: step out to a stance, towards where the free foot already is.
            if gap.length < 1e-6:
                gap = free_contact - planted
            if gap.length < 1e-6:
                gap = left_final if free == "L" else -left_final
            landing = planted + gap.normalized() * MIN_FOOT_GAP_HIPS * hip_width
        land1 = step_frames((landing - free_contact).length, CATCH_TIME_SCALE)

    # The final pose: the start pose turned and slid so its free foot is on the landing.
    shift = flat(landing - turn_matrix.to_3x3() @ contact(at_start, free))
    final = Matrix.Translation(shift) @ turn_matrix

    foot_end = {side: at_end["c_foot_fk" + SIDES[side]] for side in SIDES}
    foot_spin = {}
    for side in SIDES:
        q0 = foot_end[side].to_quaternion()
        foot_spin[side] = Vector(q0) - Vector(same_hemisphere(before1["c_foot_fk" + SIDES[side]].to_quaternion(), q0))
    # Where each foot lands, in the final pose.
    foot_land = {side: final @ at_start["c_foot_fk" + SIDES[side]] for side in SIDES}
    free_velocity = ankle(at_end, free) - ankle(before1, free)
    if free_velocity.length > MAX_FOOT_SPEED / fps:
        free_velocity = free_velocity.normalized() * MAX_FOOT_SPEED / fps

    # Timing, in frames after the end marker.
    dist1 = flat(foot_land[free].translation - foot_end[free].translation).length
    dist2 = flat(foot_land[stance].translation - foot_end[stance].translation).length
    later = AFTER_CATCH_TIME_SCALE
    lift2 = land1 + max(0, round(DOUBLE_SUPPORT_TIME * later * fps))
    land2 = lift2 + step_frames(dist2, later)
    total = land2 + max(1, round(SETTLE_TIME * later * fps))
    tau = MOMENTUM_TIME * fps

    log(f"stance {stance}, free {free}; centre of mass moving "
        f"{flat(com_velocity).length:.2f} u/s, capture point "
        f"{(capture - planted).length:.3f} from the stance foot")
    log(f"catch step {dist1:.3f} long, {land1 / fps:.2f}s at {dist1 * fps / land1:.2f} u/s "
        f"(lands +{land1}); pause {(lift2 - land1) / fps:.2f}s; closing step {dist2:.3f} long, "
        f"{(land2 - lift2) / fps:.2f}s at {dist2 * fps / (land2 - lift2):.2f} u/s (+{lift2}..+{land2}); "
        f"settle {(total - land2) / fps:.2f}s (+{total})")
    log(f"facing {math.degrees(end_turn):+.1f} deg at the end marker, keeping {math.degrees(turn):+.1f}")

    # Pelvis path: carry on from the end marker, over the feet at the catch, then home.
    pelvis_end = at_end[TRAJ].translation.copy()
    pelvis_velocity = pelvis_end - before1[TRAJ].translation
    if pelvis_velocity.length > MAX_PELVIS_SPEED / fps:
        pelvis_velocity = pelvis_velocity.normalized() * MAX_PELVIS_SPEED / fps
    pelvis_final_matrix = final @ at_start[TRAJ]
    pelvis_final = pelvis_final_matrix.translation.copy()
    # At touchdown the body is where its momentum has carried it, and the pelvis
    # sits off the centre of mass by a lean part way from the end pose's to the
    # final pose's.
    com_final = final @ centre_of_mass(at_start)
    lean = flat(pelvis_end - com_end).lerp(flat(pelvis_final - com_final), RECOVERED_AT_CATCH)
    catch_xy = touchdown + lean
    pelvis_catch = Vector((catch_xy.x, catch_xy.y, (pelvis_end.z + pelvis_final.z) / 2 - CATCH_DIP))
    pelvis_path = key_curve([0, land1, total], [pelvis_end, pelvis_catch, pelvis_final],
                            pelvis_velocity, UNCLAMPED, tau)

    # Everything else passes through the same key poses: the end pose, part way
    # back at each landing, the start pose once settled.
    key_times = [0, land1, land2, total]

    def recovery_curve(x_end, x_prev, x_start):
        values = [x_end, x_end.lerp(x_start, RECOVERED_AT_CATCH),
                  x_end.lerp(x_start, RECOVERED_AT_CLOSING), x_start]
        return key_curve(key_times, values, x_end - x_prev, UNCLAMPED, tau)

    q_end = Vector(at_end[TRAJ].to_quaternion())
    q_prev = Vector(same_hemisphere(before1[TRAJ].to_quaternion(), Quaternion(q_end)))
    q_final = Vector(same_hemisphere(pelvis_final_matrix.to_quaternion(), Quaternion(q_end)))
    pelvis_turn = recovery_curve(q_end, q_prev, q_final)
    traj_scale = at_start[TRAJ].to_scale()

    def pelvis_rotation(t):
        return Quaternion(pelvis_turn(t)).normalized()

    toes = {"c_toes_fk" + SIDES[free]: free, "c_toes_fk" + SIDES[stance]: stance}

    def toe_curve(side, x0, v0, x1):
        """Toes bend with their own foot's step, and are still while it is planted."""
        def at(t):
            if side == free:
                return coast_blend(x0, v0, x1, t, land1, tau) if t < land1 else x1
            if t <= lift2:
                return coast(x0, v0, t, tau)
            if t < land2:
                return coast_blend(coast(x0, v0, lift2, tau), v0 * 0.0, x1, t - lift2, land2 - lift2, tau)
            return x1
        return at

    # Every other keyed bone's local channels, as {bone: {property: curve}}.
    local_plan = {}
    for name, chans in channels.items():
        if name == TRAJ:
            continue
        end_v, prev_v, start_v = local_at(chans, end_f), local_at(chans, end_f - 1), local_at(chans, start_f)
        if "rotation_quaternion" in end_v:
            q = end_v["rotation_quaternion"]
            for other in (prev_v, start_v):
                if other["rotation_quaternion"].dot(q) < 0:
                    other["rotation_quaternion"] = -other["rotation_quaternion"]
        local_plan[name] = {
            prop: (toe_curve(toes[name], end_v[prop], end_v[prop] - prev_v[prop], start_v[prop])
                   if name in toes else recovery_curve(end_v[prop], prev_v[prop], start_v[prop]))
            for prop in end_v}

    # How far the stance foot has dragged by each frame, filled in by pass 1.
    drag_direction = flat(pelvis_catch - foot_end[stance].translation)
    drag_direction = drag_direction.normalized() if drag_direction.length > 1e-6 else Vector()
    drag = {}

    def stance_ankle(t):
        """The stance foot's ankle as it drags, up to its lift-off.

        It rises DRAG_LIFT off the floor over the first moment of sliding, so a
        foot that never has to slide never leaves the floor.
        """
        slid = drag.get(min(t, lift2), 0.0)
        lift = DRAG_LIFT * smoother(slid / (2.0 * DRAG_LIFT)) if DRAG_LIFT > 0 else 0.0
        return foot_end[stance].translation + drag_direction * slid + UP * lift

    def stance_rotation(t):
        """The stance foot keeps rolling the way it was at the end marker, and settles."""
        q0 = foot_end[stance].to_quaternion()
        return Quaternion(coast(Vector(q0), foot_spin[stance], min(t, lift2), tau)).normalized()

    def swing_foot(side, t, frames, p0, v0, q0, spin, other_ankle, distance):
        """A step from p0 (moving at v0 per frame) to the foot's final place.

        Leaves with the foot's own velocity and spin and lands at rest. The lift
        and the detour round the planted foot both start and end flat, so there
        is no kick at lift-off or stamp at landing.
        """
        s = t / frames
        m1 = foot_land[side]
        p1 = m1.translation
        p = coast_blend(p0, v0, p1, t, frames, tau)
        p.z = max(p.z, min(p0.z, p1.z))
        lift = min(STEP_HEIGHT_MAX, STEP_HEIGHT_BASE + STEP_HEIGHT_PER_UNIT * distance)
        p.z += lift * math.sin(math.pi * s) ** 2

        a, b, q = flat(p0), flat(p1), flat(other_ankle)
        line = b - a
        peak = clamp((q - a).dot(line) / line.length_squared, 0.05, 0.95) if line.length_squared > 1e-9 else 0.5
        away = a + line * peak - q
        clearance = SWING_CLEARANCE_HIPS * hip_width
        if away.length < clearance:
            direction = away.normalized() if away.length > 1e-5 else (
                left_final if side == "L" else -left_final)
            p += direction * (clearance - away.length) * bump(s, peak)

        q1 = same_hemisphere(m1.to_quaternion(), q0)
        rotation = Quaternion(coast_blend(Vector(q0), spin, Vector(q1), t, frames, tau)).normalized()
        # A swinging foot only holds the pelvis back once it is nearly down.
        return p, rotation, smoother((s - 0.5) / 0.5)

    def foot_target(side, t):
        """(ankle position, foot rotation, how much its reach should hold the pelvis)."""
        if side == free:
            if t < land1:
                return swing_foot(side, t, land1, foot_end[free].translation, free_velocity,
                                  foot_end[free].to_quaternion(), foot_spin[free],
                                  stance_ankle(t), dist1)
            m = foot_land[side]
        elif t <= lift2:
            return stance_ankle(t), stance_rotation(t), 1.0
        elif t < land2:
            pulled = stance_ankle(lift2) - stance_ankle(lift2 - 1)
            return swing_foot(side, t - lift2, land2 - lift2, stance_ankle(lift2), pulled,
                              stance_rotation(lift2), Vector((0.0, 0.0, 0.0, 0.0)),
                              foot_land[free].translation, dist2)
        else:
            m = foot_land[side]
        return m.translation.copy(), m.to_quaternion(), 1.0

    # Reach limits, loose enough for the end pose and the start pose themselves.
    def extension(m, side):
        s = SIDES[side]
        return (m["c_foot_fk" + s].translation - m["c_thigh_fk" + s].translation).length

    base_limits = {}
    end_excess = {}
    for side in SIDES:
        lo = min(MIN_LEG_EXTENSION * leg_length[side], extension(at_start, side))
        hi = max(MAX_LEG_EXTENSION * leg_length[side], extension(at_start, side))
        base_limits[side] = (lo, hi)
        d = extension(at_end, side)
        end_excess[side] = (max(0.0, lo - d), max(0.0, d - hi))

    def limits_at(t):
        fade = 1.0 - smoother(t / land1)
        return {side: (base_limits[side][0] - end_excess[side][0] * fade,
                       base_limits[side][1] + end_excess[side][1] * fade) for side in SIDES}

    bones = rig.pose.bones

    def pose_reference(t, pelvis_offset):
        for name, plan in local_plan.items():
            pb = bones[name]
            for prop, curve in plan.items():
                value = curve(t)
                if prop == "rotation_quaternion":
                    pb.rotation_quaternion = Quaternion(value).normalized()
                else:
                    setattr(pb, prop, value)
        pelvis = Matrix.LocRotScale(pelvis_path(t), pelvis_rotation(t), traj_scale)
        set_pose_matrix(rig, bones[TRAJ], Matrix.Translation(pelvis_offset) @ pelvis)

    use_nla = ad.use_nla
    assign(rig, None)
    ad.use_nla = False
    frames = range(1, total + 1)
    recorded = {}
    try:
        # Pass 1: how far the pelvis has to give to keep the feet in reach, and
        # how far the stance foot has to drag where the pelvis should not give.
        hips_seen = {}
        corrections = [Vector()]
        dragged = [0.0]
        for t in frames:
            pose_reference(t, Vector())
            bpy.context.view_layer.update()
            hips_seen[t] = {side: bones["c_thigh_fk" + s].head.copy() for side, s in SIDES.items()}
            targets = {}
            for side in SIDES:
                position, _, weight = foot_target(side, t)
                targets[side] = (position, weight)
            limits = limits_at(t)
            dragging = DRAG_STANCE_FOOT and t <= lift2 and drag_direction.length > 0
            if dragging:
                limits[stance] = (limits[stance][0], math.inf)
            correction = pelvis_correction(hips_seen[t], targets, limits)
            corrections.append(correction)
            needed = dragged[-1]
            if dragging:
                needed = max(needed, slide_to_reach(foot_end[stance].translation, drag_direction,
                                                    hips_seen[t][stance] + correction,
                                                    limits_at(t)[stance][1]))
            dragged.append(needed)
        smoothed = gaussian_smooth(corrections, PELVIS_SMOOTHING_FRAMES)
        smoothed[0] = Vector()
        # Smoothed so the foot eases into its slide, but never short of what reach needs.
        smooth_drag = gaussian_smooth(dragged, PELVIS_SMOOTHING_FRAMES)
        drag.update((t, max(a, b)) for t, (a, b) in enumerate(zip(smooth_drag, dragged)))
        drag[0] = 0.0
        if drag[lift2] > 1e-4:
            log(f"stance foot drags {drag[lift2]:.3f}, {DRAG_LIFT:g} off the floor, before it lifts")

        # Pass 2: pose, correct the pelvis for whatever smoothing took off the
        # reach limit, plant the feet, record.
        for t in frames:
            targets = {side: foot_target(side, t) for side in SIDES}
            hips = {side: hips_seen[t][side] + smoothed[t] for side in SIDES}
            reach_only = {side: (0.0, hi) for side, (_, hi) in limits_at(t).items()}
            residual = pelvis_correction(
                hips, {side: (p, w) for side, (p, _, w) in targets.items()}, reach_only)
            pose_reference(t, smoothed[t] + residual)
            bpy.context.view_layer.update()
            for side, s in SIDES.items():
                # A foot in the air that the hip has outrun is carried along by the
                # leg rather than left behind at the end of a locked-straight knee.
                position, rotation, weight = targets[side]
                hip = bones["c_thigh_fk" + s].head
                reach = limits_at(t)[side][1]
                if weight < 1.0 and (position - hip).length > reach:
                    position = hip + (position - hip).normalized() * reach
                    targets[side] = (position, rotation, weight)
                solve_leg(rig, side, position, hinge_local[side])
            bpy.context.view_layer.update()
            for side in SIDES:
                set_foot(rig, side, targets[side][1])
            if t == land1 and speed > 1e-6:
                body = flat(centre_of_mass({n: bones[n].matrix for n in WATCHED}))
                log(f"catch foot lands {(landing - body).dot(heading):+.3f} ahead of the centre of mass "
                    f"(aimed for {ahead:+.3f}: {CATCH_AHEAD:g} x a capture offset of {speed / omega:.3f}"
                    + (f", cut to the leg's reach" if CATCH_AHEAD * speed / omega > ahead else "") + ")")
            recorded[t] = {name: (bones[name].location.copy(),
                                  bones[name].rotation_quaternion.copy(),
                                  bones[name].scale.copy()) for name in channels}
    finally:
        ad.use_nla = use_nla
        assign(rig, source)

    # Output action: the source up to the end marker, then the recovery.
    name = source.name + OUTPUT_SUFFIX
    out = source.copy()
    old = bpy.data.actions.get(name)
    if old is not None:
        old.user_remap(out)
        bpy.data.actions.remove(old)
    out.name = name
    out.use_fake_user = True
    assign(rig, out)
    bag = anim_utils.action_get_channelbag_for_slot(out, ad.action_slot)
    for fcurve in bag.fcurves:
        points = fcurve.keyframe_points
        for i in range(len(points) - 1, -1, -1):
            if points[i].co.x > end_f + 1e-3:
                points.remove(points[i], fast=True)
        fcurve.update()

    keys = {}
    for bone_name, chans in channels.items():
        previous = local_at(chans, end_f).get("rotation_quaternion")
        for t in frames:
            loc, rot, scale = recorded[t][bone_name]
            if previous is not None:
                rot = same_hemisphere(rot, Quaternion(previous))
                previous = Vector(rot)
            values = {"location": loc, "rotation_quaternion": rot, "scale": scale}
            for prop, fcurves in chans.items():
                for index, source_curve in enumerate(fcurves):
                    if source_curve is not None:
                        keys.setdefault((source_curve.data_path, index), []).append(
                            (end_f + t, values[prop][index]))
    write_keys(out, rig, keys)

    new_end = end_f + total
    recovery_frames = range(end_f + 1, new_end + 1)
    if LEG_CONTROLS == "IK":
        legs_to_ik(scene, rig, out, range(end_f, new_end + 1), end_f, round(IK_BLEND_TIME * fps))
        worst_pos, worst_rot = check_legs(scene, rig, recovery_frames)
        log(f"legs keyed on IK; deforming legs within {worst_pos * 1000:.2f} mm "
            f"and {worst_rot:.2f} deg of the solve")
        if worst_pos > 0.005 or worst_rot > 2.0:
            log("WARNING: the IK legs drift from the solve; set LEG_CONTROLS = 'FK' to key FK only")

    for marker in list(out.pose_markers):
        if marker.frame > end_f or marker.name == end_name:
            out.pose_markers.remove(marker)
    if not any(m.name == start_name for m in out.pose_markers):
        out.pose_markers.new(start_name).frame = start_f
    out.pose_markers.new(end_name).frame = new_end
    if out.use_frame_range:
        out.frame_end = new_end

    out["recovery_source"] = source.name
    out["recovery_end_frame"] = end_f
    out["recovery_stance"] = stance
    out["recovery_turn_deg"] = round(math.degrees(turn), 2)
    out["recovery_catch_lands"] = end_f + land1
    out["recovery_closing_lands"] = end_f + land2

    if SET_SCENE_RANGE and scene.frame_end < new_end:
        scene.frame_end = new_end
    scene.frame_set(end_f)
    log(f"wrote '{out.name}': recovery {end_f}..{new_end} "
        f"({total / fps:.2f}s), stagger now {start_f}..{new_end} ({(new_end - start_f) / fps:.2f}s)")


# Guarded so the helpers can be imported without running the whole script.
if __name__ == "__main__":
    main()
