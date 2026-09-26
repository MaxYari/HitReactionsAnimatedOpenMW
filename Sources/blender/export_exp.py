"""Export the hand-finished [ARP][Exp] clips out of Sources/Reatrget.blend.

    blender -b Sources/Reatrget.blend --python Sources/export_exp.py -- [--only GROUP]

These are the clips that have been through the whole pipeline: retargeted with
the corrected setup (see RETARGETING.md), then trimmed and marked by hand in
Blender. Everything about a clip that the game needs is read out of the action
rather than configured here:

  * the ANIMATION GROUP is the text before ": " in its pose markers, so
    "DeathBack: Start" and "DeathBack: Stop" make a group called "deathback";
  * the KIND is the first word of that group - a Stagger* clip replaces a hit
    reaction, a Death* clip replaces a knockdown, knockout or death. This is why
    a clip can be renamed from knockdown to death by editing its markers alone:
    "[ARP][Exp] BSKnockDownLeft" is marked "DeathDown" and ships as a death;
  * the DIRECTION comes from the source BVH, measured, as it always has.

The clips are single-purpose now. The old build put two animations in every file
- "start" to "stagger stop" for the stagger, "start" to "stop" for the fall - so
one clip had to serve both. A hand-marked clip is cut for the job it does, so
there is one span per file and the second stop key is gone.

The blend is never saved: this renames actions and nudges markers to get them
past the exporter, and all of that is meant to die with the process.
"""

import math
import os
import re
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import staggers_common as common  # noqa: E402
import export_common as build  # noqa: E402

EXP_PREFIX = "[ARP][Exp] "
TARGET_RIG = "rig"

# The suffix on an action whose markers cover only part of the source clip. Not
# part of the clip's identity - "BSStumbleLeft2 Recovery" is still the
# BSStumbleLeft2 BVH, and that is where its direction is measured from.
VARIANT_SUFFIXES = (" Recovery",)

# A clip whose fall carries the character a long way. Written down only in the
# name - "Far", or "Long" for the stagger that travels - and used by the Lua to
# save the long ones for the blows that earn them.
FAR_WORDS = ("far", "long")


def is_far(group):
    low = group.lower()
    return any(word in low for word in FAR_WORDS)


KIND_STAGGER = "stagger"
KIND_DEATH = "death"
KIND_PREFIXES = {"Stagger": KIND_STAGGER, "Death": KIND_DEATH}

# Where the character's own forward points, measured in the frame c_traj's
# location keys live in. Subtracting it from a travel angle read off an action
# gives the bearing in the character's frame, which is what everything else uses.
#
# Exactly +Y, and the reason to trust that is geometric rather than fitted.
#
# Every midline bone on this rig rests on x=0 (mirror_staggers.py checks it), so
# the character's sagittal plane IS the world x=0 plane and their forward must lie
# in it - +Y or -Y. A back stagger reads as back only with +Y, so +Y it is.
#
# Fitting it against the source BVHs instead gives 79.06, and that is what this
# used to say. The mirror is what caught it: reflecting a clip across x=0 maps a
# world angle t to 180 - t, so a source and its mirror must have bearings summing
# to 180 - 2*ACTION_FORWARD, which is zero only at 90. At 79 every mirrored pair
# came out 22 degrees short of opposite. The BVH route carries an 11 degree bias
# of its own - check_facing.MORROWIND_FORWARD is the same 79 because it is the
# same comparison, exported-against-BVH, not an independent measurement.
#
# Measuring here rather than from the BVH is also what lets a clip exist without
# one: a second cut of a recording, a hand-built variant, a mirrored copy.
ACTION_FORWARD = 90.0


def action_fcurves(action):
    """Every F-curve in an action, across Blender 5.1's slotted layout."""
    legacy = getattr(action, "fcurves", None)
    if legacy is not None and len(legacy):
        for fcurve in legacy:
            yield fcurve
        return
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                for fcurve in bag.fcurves:
                    yield fcurve


def traj_xy(action, frame):
    """c_traj's horizontal position at a frame, read off the keys themselves.

    No scene state to set up and nothing to put back afterwards, which matters
    in a script that must not modify the .blend it is reading.
    """
    out = [0.0, 0.0]
    for fcurve in action_fcurves(action):
        if ("c_traj" in fcurve.data_path and fcurve.data_path.endswith(".location")
                and fcurve.array_index in (0, 1)):
            out[fcurve.array_index] = fcurve.evaluate(frame)
    return out


def action_bearing(action, start, stop):
    """Where the clip carries the character, in degrees off their own forward.

    A straight line from start to finish. It says nothing about the path between,
    so a clip that curves reads as somewhere between its two halves - which is
    the right answer when the question is which blow the clip suits.
    """
    x0, y0 = traj_xy(action, start)
    x1, y1 = traj_xy(action, stop)
    if math.hypot(x1 - x0, y1 - y0) < 1e-4:
        return None
    world = math.degrees(math.atan2(y1 - y0, x1 - x0))
    return ((world - ACTION_FORWARD + 180) % 360) - 180


# What a word in a clip's name says about where the clip carries the character,
# translated into the frame everything else uses: the CHARACTER's own.
#
# The names are written from the point of view of someone watching the
# character - a player looking at the enemy they just hit. So "Left" means the
# body goes to the viewer's left, which is the character's own right, and the
# two sides swap on the way in here. Back and Forward need no swap: away from
# the viewer is also the character's back.
#
# This is why a name can be checked against the measurement instead of
# appearing to contradict it; see direction_tags().
NAME_DIRECTIONS = {
    "Back": "back",
    "Forward": "forward",
    "Left": "right",
    "Right": "left",
}


def log(*parts):
    print("[hit-reactions]", *parts, flush=True)


def exp_actions():
    return sorted((a for a in bpy.data.actions if a.name.startswith(EXP_PREFIX)),
                  key=lambda a: a.name)


def clip_key(action):
    """The CLIPS entry an action came from, so its source BVH can be found."""
    key = action.name[len(EXP_PREFIX):]
    for suffix in VARIANT_SUFFIXES:
        if key.endswith(suffix):
            key = key[:-len(suffix)]
    return key.strip()


def read_markers(action):
    """(group, {event: frame}) from the action's pose markers.

    io_scene_mw turns each marker into a text key verbatim, and OpenMW splits a
    text key at ": " into the group and the event. Two markers, one group.
    """
    groups, events = set(), {}
    for marker in action.pose_markers:
        if ":" not in marker.name:
            raise SystemExit(f"{action.name}: marker {marker.name!r} has no '<Group>: <Event>' form")
        group, event = marker.name.split(":", 1)
        groups.add(group.strip())
        events[event.strip().lower()] = marker.frame

    if len(groups) != 1:
        raise SystemExit(f"{action.name}: markers name {len(groups)} groups ({sorted(groups)}), "
                         "and one .kf group cannot be split across two names")
    missing = {"start", "stop"} - set(events)
    if missing:
        raise SystemExit(f"{action.name}: no {sorted(missing)} marker")
    return groups.pop(), events


def clip_kind(group):
    for prefix, kind in KIND_PREFIXES.items():
        if group.startswith(prefix):
            return kind
    raise SystemExit(f"group {group!r} starts with neither " +
                     " nor ".join(sorted(KIND_PREFIXES)) +
                     ", so there is no telling whether it is a stagger or a fall")


def name_directions(key):
    """Direction tags read off the clip's name, as directions of travel."""
    tags = []
    for word in re.findall(r"[A-Z][a-z]*|\d+", key):
        if word == "Down":
            tags.append("down")
        elif word in NAME_DIRECTIONS:
            tags.append(NAME_DIRECTIONS[word])
    return tags


# Each quarter of the character's own frame, as (from, to) in degrees off their
# forward. Measured bearings are bucketed into these.
QUARTERS = {
    "forward": (-45.0, 45.0),
    "left": (45.0, 135.0),
    "back": (135.0, 225.0),
    "right": (225.0, 315.0),
}
COMPASS = set(QUARTERS)

# How far outside its quarter a bearing may sit and still be called by name.
#
# The quarters have hard edges, and a clip travelling near one is a coin toss
# between two buckets that says nothing about the clip. StaggerStumbleBack is the
# case in point: it measures 129, six degrees off the back quarter, and is named
# Back for the obvious reason. Where the name says a direction and the motion is
# this close to agreeing, the name breaks the tie - it is a statement of intent
# and the measurement is not precise enough to overrule it. Further out than
# this and the motion wins, because then they genuinely disagree.
NAME_MARGIN = 20.0


def compass_of(bearing):
    """Which quarter a bearing falls in, in the character's own frame."""
    if bearing is None:
        return None
    angle = (bearing + 360) % 360
    if angle < 45 or angle >= 315:
        return "forward"
    if angle < 135:
        return "left"
    if angle < 225:
        return "back"
    return "right"


def quarter_gap(bearing, quarter):
    """How many degrees a bearing sits outside a quarter. 0 when inside it."""
    low, high = QUARTERS[quarter]
    angle = (bearing + 360) % 360
    # Compare in the quarter's own winding, so "back" straddling 180 is one range.
    for candidate in (angle, angle + 360, angle - 360):
        if low <= candidate <= high:
            return 0.0
    return min(abs(((bearing - edge + 180) % 360) - 180) for edge in (low, high))


def direction_tags(name, bearing):
    """Every direction a clip answers for, from its motion and from its name.

    The motion is the honest source for which quarter a clip belongs to, with one
    exception: a bearing sitting just outside a quarter the name explicitly claims
    is taken as belonging to it. See NAME_MARGIN.

    "down" only ever comes from the name. A downward blow drives someone into the
    floor, which is not a compass direction and does not show up in where they
    travel at all.
    """
    measured = compass_of(bearing)
    named = name_directions(name)
    named_compass = [t for t in named if t in COMPASS]
    chosen = measured

    if measured and named_compass and measured not in named_compass:
        near = min(named_compass, key=lambda q: quarter_gap(bearing, q))
        gap = quarter_gap(bearing, near)
        if gap <= NAME_MARGIN:
            chosen = near
            log(f"  {name}: {bearing:+.0f} is {gap:.0f} deg outside '{near}', which the name "
                f"claims - taking the name over '{measured}'")
        else:
            log(f"  ! {name}: name says {sorted(named_compass)}, motion says {measured} "
                f"({bearing:+.0f}, {gap:.0f} deg outside the nearest named quarter) "
                "- using the motion")

    tags = [t for t in named if t not in COMPASS]
    if chosen:
        tags.append(chosen)
    return tags or ["any"]


def clamp_markers(action):
    """Pull every marker inside the range the bake will actually cover.

    The exporter bakes over the action's curve range, so a marker past the last
    keyframe would put a text key beyond the end of the animation and leave the
    engine waiting on a stop that never arrives. Two of these are marked a frame
    or so long, which is the kind of thing that happens when a stop is placed on
    the last pose rather than the last key.
    """
    first, last = action.curve_frame_range
    moved = []
    for marker in action.pose_markers:
        clamped = min(max(marker.frame, int(first)), int(last))
        if clamped != marker.frame:
            moved.append((marker.name, marker.frame, clamped))
            marker.frame = clamped
    return moved


def ground_rig(rig):
    """Put the ARP rig's origin on the world floor, in memory, before exporting.

    The addon gives the exported Bip01 node c_traj's WORLD location, and Morrowind
    reads that node as the pelvis - vanilla keys it at z 76.369 standing. c_traj
    sits at the pelvis height within the rig, so the rig's own origin has to be at
    zero or the two heights add up and every character floats by however far the
    object was moved.

    Reatrget.blend had the rig at z 0.76722, matching the Bip01 armature, which is
    authored at pelvis height. That looks like alignment and is not: it put the
    ARP rig's feet 0.767 above the floor, and the exported clips 1.1 metres up.
    The earlier, now deleted BrutalStaggers.blend, whose clips were confirmed
    correct in game, had it at zero - which is how this was found.

    Done here as well as in the .blend so the export cannot silently produce
    floating clips again if the rig is ever nudged.
    """
    offset = rig.matrix_world.translation.copy()
    if offset.length < 1e-6:
        return
    rig.location -= offset
    bpy.context.view_layer.update()
    log(f"grounded '{rig.name}': moved by {tuple(round(-v, 5) for v in offset)}")


def export_one(rig, action, group):
    """Run the addon over one action, under a name it will accept.

    The exporter takes the file name from the action's name with the [tags]
    stripped, and refuses anything without a [Raw] tag, so the action is renamed
    for the length of the export. Naming it after the group is what keeps
    xDeathBack.kf and the "deathback" group inside it obviously the same thing.
    """
    original_name = action.name
    original_frames = [(m, m.frame) for m in action.pose_markers]

    rig.animation_data_create()
    rig.animation_data.action = action

    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="OBJECT")
    for other in list(bpy.context.selected_objects):
        other.select_set(False)
    rig.select_set(True)

    try:
        moved = clamp_markers(action)
        for name, was, now in moved:
            log(f"  marker {name!r} {was} -> {now} (past the last keyframe)")
        action.name = f"[Raw] {group}"
        log(f"{group}: exporting from {original_name!r}, "
            f"frames {action.curve_frame_range[0]:.0f}-{action.curve_frame_range[1]:.0f}")
        result = bpy.ops.export.animation()
        if "FINISHED" not in result:
            raise SystemExit(f"{group}: export returned {result}")
    finally:
        action.name = original_name
        for marker, frame in original_frames:
            marker.frame = frame


BLEND_RULE_TEMPLATE = """# Blend rules for the Brutal Staggers clip "{group}".
#
# Transitions INTO this clip, and nothing else. The rules that govern a
# transition belong to the animation being blended into rather than the one
# being left (Animation::resetActiveGroups passes animsrc->mAnimBlendRules of
# the source becoming ACTIVE), so a per-kf file reaches its own entries only.
# Recovery out of a stagger is in Animations/animation-config.yaml instead.
#
# Per-animation rules are appended after the global ruleset and the bottom-most
# match wins, so this outranks the global config.

blending_rules:
  # Short, so a hit reads as an impact instead of a lean into one. Every source
  # is the same 0.08: a second blow landing mid-clip should hit as hard as the
  # first, which means it gets the same entry timing rather than a softer one.
  - from: "*"
    to: "{group}"
    easing: "sineOut"
    duration: 0.08
"""


def write_blend_rules(folder, clips):
    for clip in clips:
        path = os.path.join(folder, f"x{clip['group']}.yaml")
        with open(path, "w") as handle:
            handle.write(BLEND_RULE_TEMPLATE.format(group=clip["group"].lower()))


def write_clip_list(clips):
    """The clip table the Lua side plays from, generated so the two cannot drift."""
    path = os.path.join(common.script_dir(), "clips.lua")
    lines = [
        "-- Generated by Sources/export_exp.py. Do not edit by hand.",
        "--",
        "-- One entry per exported clip, lowercased the way OpenMW reports text keys.",
        "--",
        "-- kind is what the clip replaces, and comes from the first word of the group",
        "-- name in its markers: a 'stagger' answers hit1..hit5, a 'death' answers the",
        "-- death groups. A clip is one or the other, never both - each is cut by hand",
        "-- for the job it does. knockdown and knockout are left to the engine.",
        "--",
        "-- bearing is where the clip carries the character, in degrees off their own",
        "-- forward: 0 ahead, +90 their left, 180 back, -90 their right. MEASURED from",
        "-- the source. The names are written from the VIEWER's side - a player",
        "-- looking at the enemy they hit - so a clip called Left carries the body to",
        "-- the viewer's left, which is the character's own right. Back and Forward",
        "-- need no swap.",
        "--",
        "-- tags bucket the same thing, plus \"down\" for a clip that answers a downward",
        "-- blow - which is not a compass direction and so is readable only in the name.",
        "--",
        "-- far is true for a clip that throws the character a long way, read off the",
        "-- name (Far, or Long). The Lua can save those for the blows that earn them.",
        "return {",
        f"    START_KEY = {common.KEY_START.lower()!r},",
        f"    STOP_KEY = {common.KEY_STOP.lower()!r},",
        "    list = {",
    ]
    for clip in clips:
        tags = ", ".join(f"{tag} = true" for tag in clip["tags"])
        bearing = clip["bearing"]
        bearing_txt = f"{bearing:.1f}" if bearing is not None else "nil"
        lines.append(f"        {{ group = {clip['group'].lower()!r}, kind = {clip['kind']!r}, "
                     f"far = {str(clip['far']).lower()}, "
                     f"bearing = {bearing_txt}, tags = {{ {tags} }} }},")
    lines += ["    },", "}", ""]
    with open(path, "w") as handle:
        handle.write("\n".join(lines))
    log(f"wrote {path}")


def write_manifest(clips):
    """Record what was shipped, so the plain-python checks can find the sources."""
    common.write_manifest([{
        "group": clip["group"],
        "kind": clip["kind"],
        "action": clip["action"].name,
        "clip": clip["key"],
        "bearing": clip["bearing"],
        "far": clip["far"],
        "frames": clip["frames"],
        "tags": clip["tags"],
        "seconds": round(clip["seconds"], 3),
    } for clip in clips])
    log(f"wrote {common.manifest_path()}")


# Shipped by the hit-reaction half of the mod, not by this build. They live in
# the same folder and must survive a prune - deleting them would take the
# flinch animation out of the mod every time the staggers were rebuilt.
FOREIGN = {"HitReact.nif", "xHitReact.nif", "xHitReact.kf", "xHitReact.yaml"}

# Built from exported clips by Sources/blender/retime_kf.py rather than by the
# exporter, so nothing here knows how to rebuild them and a prune must not take
# them out. Each is a death retimed onto the Dremora mesh's own dissolve span,
# 666.667, so that mesh animates itself while the clip plays; see retime_kf.py
# and the `dremora` flag in clips.lua. Regenerate one with:
#
#   python3 Sources/blender/retime_kf.py \
#       Animations/xbase_anim/xDeathBackFar.kf \
#       Animations/xbase_anim/xDeathDremora1.kf 666.334 DeathBackFar DeathDremora1
#
# where the delta is 666.667 minus that clip's own ": Start" time, and copy
# x<source>.nif and x<source>.yaml alongside under the new name. No <group>.nif
# is needed: the skeleton nif carries no text keys and still points at the
# source mesh, which ships anyway.
RETIMED = {name
           for i in range(1, 6)
           for name in (f"xDeathDremora{i}.nif",
                        f"xDeathDremora{i}.kf",
                        f"xDeathDremora{i}.yaml")}


def prune(folder, clips):
    """Drop files from an earlier build.

    These folders hold generated output, and OpenMW loads every .kf under them -
    so a clip left behind from a build with different group names is not inert,
    it is an animation source the game reads and the mod no longer knows about.
    """
    keep = set(FOREIGN) | set(RETIMED)
    for clip in clips:
        keep.update((f"{clip['group']}.nif", f"x{clip['group']}.nif",
                     f"x{clip['group']}.kf", f"x{clip['group']}.yaml"))
    for name in sorted(os.listdir(folder)):
        if name not in keep:
            os.remove(os.path.join(folder, name))
            log(f"  removed stale {os.path.basename(folder)}/{name}")


def mirror_to_other_skeletons(primary, clips):
    """Copy the exported files into the female and beast animation folders.

    The female skeleton is the same as the male one, so the clips are correct
    there. The beast skeleton is digitigrade and these are not retargeted to it -
    the clips are copied so beast NPCs get something rather than falling back to
    a vanilla animation mid-override, and they will look off until someone runs
    the addon's Transfer to Beasts on them.
    """
    import shutil

    for folder in build.ANIM_FOLDERS[1:]:
        destination = os.path.join(common.mod_root(), "Animations", folder)
        os.makedirs(destination, exist_ok=True)
        for clip in clips:
            for name in (f"{clip['group']}.nif", f"x{clip['group']}.nif",
                         f"x{clip['group']}.kf", f"x{clip['group']}.yaml"):
                source = os.path.join(primary, name)
                if os.path.exists(source):
                    shutil.copy2(source, os.path.join(destination, name))
        prune(destination, clips)
        log(f"mirrored into Animations/{folder}")


def collect():
    """Everything the build needs to know about each [Exp] action, validated.

    Nothing here consults the source BVH. Direction is measured off the action's
    own root motion, so a clip needs no entry in any table to ship - which is
    what lets a mirrored copy, or a second cut of one recording, just work.
    """
    clips, seen = [], {}
    for action in exp_actions():
        group, events = read_markers(action)
        if group in seen:
            raise SystemExit(f"{action.name} and {seen[group]} both mark a group called "
                             f"{group!r}; one would overwrite the other's .kf")
        seen[group] = action.name

        start, stop = int(events["start"]), int(events["stop"])
        bearing = action_bearing(action, start, stop)
        if bearing is None:
            log(f"  ! {group}: c_traj does not move between its markers, so it has no "
                "direction and will be offered for any blow")
        clips.append({
            "action": action,
            "key": clip_key(action),
            "group": group,
            "kind": clip_kind(group),
            "far": is_far(group),
            "bearing": bearing,
            "tags": direction_tags(group, bearing),
            "frames": [start, stop],
            "seconds": (events["stop"] - events["start"]) / bpy.context.scene.render.fps,
        })
    return clips


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    only = argv[argv.index("--only") + 1] if "--only" in argv else None

    addon = bpy.context.preferences.addons.get(build.ADDON)
    if addon is None:
        raise SystemExit(f"addon '{build.ADDON}' is not enabled")
    if not hasattr(bpy.ops.export_scene, "mw"):
        raise SystemExit("io_scene_mw (the Blender Morrowind Plugin) is not enabled")

    clips = collect()
    if not clips:
        raise SystemExit(f"no '{EXP_PREFIX}' actions in this .blend")
    for clip in clips:
        log(f"{clip['group']:22s} {clip['kind']:8s} {clip['seconds']:5.2f}s  "
            f"bearing {'    n/a' if clip['bearing'] is None else format(clip['bearing'], '6.1f')}  "
            f"{'FAR ' if clip['far'] else '    '}"
            f"tags {clip['tags']}")

    primary = os.path.join(common.mod_root(), "Animations", build.ANIM_FOLDERS[0])
    os.makedirs(primary, exist_ok=True)
    build.configure(addon.preferences, primary + os.sep)
    build.install_headless_decimation()

    rig = bpy.data.objects[TARGET_RIG]
    ground_rig(rig)
    for clip in clips:
        if only and clip["group"] != only:
            continue
        export_one(rig, clip["action"], clip["group"])

    if only:
        return

    write_blend_rules(primary, clips)
    prune(primary, clips)
    for clip in clips:
        for name in (f"{clip['group']}.nif", f"x{clip['group']}.kf"):
            path = os.path.join(primary, name)
            size = os.path.getsize(path) if os.path.exists(path) else None
            log(f"  {name}: {size if size is not None else 'MISSING'}")

    write_clip_list(clips)
    write_manifest(clips)
    mirror_to_other_skeletons(primary, clips)


if __name__ == "__main__":
    main()
