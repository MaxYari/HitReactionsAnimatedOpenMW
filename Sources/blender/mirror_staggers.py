"""Mirror clips left <-> right, and fix a marker group's name.

    blender -b Sources/Reatrget.blend --python Sources/blender/mirror_staggers.py \
        -- --mirror "[ARP][Exp] BSStaggerLongLeft Recovery" \
           --set-group "[ARP][Exp] BSDeathBackHighFace=DeathBackHighFace"

Mirroring is how a one-sided collection is made even: the endorphin recordings
lean heavily one way, and a character hit from the left should have as much to
draw on as one hit from the right.

The transform is the one from ReAnimation's mirror_action.py, which was
calibrated against bpy.ops.pose.paste(flipped=True) on this rig (156 of 156
mirror pairs agreeing on the quaternion rule). It works on the F-curves rather
than baking a key per frame, so keys, handles and interpolation survive.

It is only valid because THIS rig rests exactly symmetric about x=0 - every
limb pair at 0.00000, every centre bone at x=0 - which the script checks before
touching anything. Negating x then mirrors the pose anatomically AND mirrors
c_traj's travel across the character's own sagittal plane, so the clip goes the
other way as well as looking the other way.

Saves the .blend. Nothing else in the pipeline writes to it, so run it when the
file is closed in Blender.
"""

import re
import sys

import bpy

TARGET_RIG = "rig"
MIRRORED_ACTION = "{src} Mirrored"

# Props that live on one hand. Mirroring their motion is meaningless while they
# stay parented to that hand.
KEEP_AS_IS = {"Weapon Bone", "Shield Bone", "Left Hand Gripper"}

# index -> multiplier, per property. Anything unlisted is copied unchanged.
FLIP = {
    "location":            {0: -1.0},
    "rotation_quaternion": {2: -1.0, 3: -1.0},
    "rotation_euler":      {1: -1.0, 2: -1.0},   # XYZ order
    "rotation_axis_angle": {2: -1.0, 3: -1.0},
}
KEY_PROPS = ("interpolation", "easing", "type", "handle_left_type",
             "handle_right_type", "amplitude", "back", "period")

BONE = re.compile(r'^pose\.bones\["(.+?)"\]\.(.+)$')
# flip_name only sees a side marker at either end of the name. This rig also has
# it in the middle - "Bip01 Forearm.L_qr_offset" - and those bones drive the
# export skeleton, so they have to swap too.
INFIX = re.compile(r'\.(L|R|l|r)_')

SIDES = (("Left", "Right"), ("left", "right"), ("LEFT", "RIGHT"))

# A bone belonging to one side: ".l"/".r" at the end, or ".L_"/".R_" in the
# middle, which is how the bones that drive the export skeleton are named.
SIDED = re.compile(r'\.[lr]$|\.[LR]_')

# ARP marks a bone on the body's midline with a ".x" suffix - c_traj is the one
# exception. These are what define where the sagittal plane is, and they are the
# only bones whose x position decides whether a mirror is a mirror.
#
# Everything else off-centre is a prop or a helper: Weapon Bone and Shield Bone
# sit in a hand by design, and checking them would reject every rig there is.
MIDLINE = re.compile(r'\.x$')
MIDLINE_EXTRA = {"c_traj"}

# One limb pair on this rig is genuinely off - hand_rot_twist, by 1cm - and
# ReAnimation's own calibration of this transform found the same single
# exception. A lone outlier that small is a rig quirk, not a different
# convention, so it is reported and allowed.
PAIR_TOLERANCE = 0.02
PAIR_OUTLIERS_ALLOWED = 2


def log(*parts):
    print("[hit-reactions]", *parts, flush=True)


def check_symmetry(rig):
    """A mirror across x=0 is only meaningful if the rest pose is symmetric.

    Two separate things, and only one of them is fatal.

    The CENTRE bones - spine, pelvis, c_traj - must sit on x=0. They define where
    the sagittal plane is, and if the character rests off it then negating x
    rotates the whole body instead of mirroring it, swapping some forward for
    some back. That is fatal.

    The LIMB pairs should mirror each other. A pair that does not just makes that
    one bone's motion slightly wrong, so a small number of small outliers is
    reported and accepted.
    """
    pairs, outliers, worst = 0, [], 0.0
    for bone in rig.data.bones:
        if not bone.name.endswith(".l"):
            continue
        other = rig.data.bones.get(bone.name[:-2] + ".r")
        if other is None:
            continue
        pairs += 1
        a, b = bone.head_local, other.head_local
        error = max(abs(a.x + b.x), abs(a.y - b.y), abs(a.z - b.z))
        worst = max(worst, error)
        if error > 1e-4:
            outliers.append((error, bone.name))
    if pairs == 0:
        raise SystemExit("found no .l/.r bone pairs; is this the ARP rig?")

    midline = [b for b in rig.data.bones
               if MIDLINE.search(b.name) or b.name in MIDLINE_EXTRA]
    if not midline:
        raise SystemExit("found no midline bones (ARP names them '*.x'); is this the ARP rig?")
    off_centre = [(b.name, b.head_local.x) for b in midline if abs(b.head_local.x) > 1e-4]
    if off_centre:
        raise SystemExit(
            "these midline bones are not on x=0, so the character does not rest on the "
            "plane a mirror would reflect across - negating x would swap some forward "
            "for some back: "
            + ", ".join(f"{n} (x={x:+.5f})" for n, x in off_centre[:6]))

    if worst > PAIR_TOLERANCE or len(outliers) > PAIR_OUTLIERS_ALLOWED:
        raise SystemExit(f"{len(outliers)} of {pairs} limb pairs do not mirror, worst "
                         f"{worst:.5f} - too much to call this rig symmetric: "
                         + ", ".join(n for _, n in sorted(outliers, reverse=True)[:6]))

    log(f"rest pose symmetric: all {len(midline)} midline bones on x=0, "
        f"{pairs - len(outliers)} of {pairs} limb pairs exact")
    for error, name in sorted(outliers, reverse=True):
        log(f"  tolerated asymmetric pair: {name} off by {error:.5f}")


def flip_bone_name(name):
    flipped = bpy.utils.flip_name(name)
    if flipped != name:
        return flipped
    found = INFIX.search(name)
    if found:
        other = {"L": "R", "R": "L", "l": "r", "r": "l"}[found.group(1)]
        return name[:found.start()] + "." + other + "_" + name[found.end():]
    return name


def swap_sides(text):
    """Left <-> Right in a group name, so the name still describes the motion."""
    out, i = [], 0
    while i < len(text):
        for low, high in SIDES:
            for a, b in ((low, high), (high, low)):
                if text.startswith(a, i):
                    out.append(b)
                    i += len(a)
                    break
            else:
                continue
            break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def all_groups():
    """Every marker group name already in the file, lowercased."""
    taken = set()
    for action in bpy.data.actions:
        for marker in action.pose_markers:
            if ":" in marker.name:
                taken.add(marker.name.split(":", 1)[0].strip().lower())
    return taken


def mirrored_group(group, taken):
    swapped = swap_sides(group)
    if swapped == group:
        raise SystemExit(f"group {group!r} has no Left or Right in it, so a mirror of it "
                         "would need a name chosen by hand")
    name = swapped
    while name.lower() in taken:
        name += "M"
    return name


def containers(action):
    legacy = getattr(action, "fcurves", None)
    if legacy is not None and len(legacy):
        yield None, legacy
        return
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                yield bag.slot, bag.fcurves


def destination(action, slot):
    """An Action holds one layer, so reuse it and add a channelbag per slot."""
    if slot is None:
        return action.fcurves
    new_slot = action.slots.new(slot.target_id_type, slot.name_display)
    if action.layers:
        strip = action.layers[0].strips[0]
    else:
        strip = action.layers.new("Layer").strips.new(type="KEYFRAME")
    return strip.channelbag(new_slot, ensure=True).fcurves


def mirror(rig, source, taken):
    group, events = None, 0
    for marker in source.pose_markers:
        if ":" in marker.name:
            group = marker.name.split(":", 1)[0].strip()
            events += 1
    if group is None:
        raise SystemExit(f"{source.name!r} has no '<Group>: <Event>' markers to mirror")

    new_group = mirrored_group(group, taken)
    taken.add(new_group.lower())

    new = bpy.data.actions.new(MIRRORED_ACTION.format(src=source.name))
    # Nothing uses it until the export assigns it, and Blender drops unused
    # data-blocks when it saves.
    new.use_fake_user = True

    curves = 0
    for slot, fcurves in containers(source):
        out = destination(new, slot)
        for fcurve in fcurves:
            found = BONE.match(fcurve.data_path)
            if found:
                bone, prop = found.group(1), found.group(2)
                if bone in KEEP_AS_IS:
                    path, multiplier = fcurve.data_path, 1.0
                else:
                    flipped = flip_bone_name(bone)
                    if flipped not in rig.pose.bones:
                        flipped = bone
                    path = 'pose.bones["%s"].%s' % (flipped, prop)
                    multiplier = FLIP.get(prop, {}).get(fcurve.array_index, 1.0)
            else:
                path, multiplier = fcurve.data_path, 1.0

            try:
                new_curve = out.new(path, index=fcurve.array_index,
                                    action_group=(fcurve.group.name if fcurve.group else ""))
            except TypeError:
                new_curve = out.new(path, index=fcurve.array_index)
            new_curve.extrapolation = fcurve.extrapolation
            new_curve.keyframe_points.add(len(fcurve.keyframe_points))
            for a, b in zip(fcurve.keyframe_points, new_curve.keyframe_points):
                # Free the handles first: assigning an auto type afterwards makes
                # Blender recompute and discard the positions set here.
                b.handle_left_type = b.handle_right_type = "FREE"
                b.co = (a.co[0], a.co[1] * multiplier)
                b.handle_left = (a.handle_left[0], a.handle_left[1] * multiplier)
                b.handle_right = (a.handle_right[0], a.handle_right[1] * multiplier)
                for prop in KEY_PROPS:
                    setattr(b, prop, getattr(a, prop))
            for old_mod in fcurve.modifiers:
                new_mod = new_curve.modifiers.new(old_mod.type)
                for prop in old_mod.bl_rna.properties:
                    pid = prop.identifier
                    if prop.is_readonly or pid in {"rna_type", "type", "is_valid", "active"}:
                        continue
                    try:
                        setattr(new_mod, pid, getattr(old_mod, pid))
                    except Exception:
                        pass
            new_curve.update()
            curves += 1

    for marker in source.pose_markers:
        name = marker.name
        if ":" in name:
            name = new_group + ":" + name.split(":", 1)[1]
        copy = new.pose_markers.new(name)
        copy.frame = marker.frame

    log(f"  {source.name!r} -> {new.name!r}   group {group} -> {new_group}   "
        f"({curves} curves, {events} markers)")
    return new


def set_group(action_name, new):
    """Rename the marker group of ONE action.

    Per action, not per group name: two actions sharing a group is exactly the
    problem this gets used to fix, and a rename by group name would rename both
    of them and fix nothing.
    """
    action = bpy.data.actions.get(action_name)
    if action is None:
        raise SystemExit(f"no action named {action_name!r}")
    was, touched = set(), 0
    for marker in action.pose_markers:
        if ":" not in marker.name:
            continue
        group, event = marker.name.split(":", 1)
        was.add(group.strip())
        marker.name = new + ":" + event
        touched += 1
    if touched == 0:
        raise SystemExit(f"{action_name!r} has no '<Group>: <Event>' markers")
    log(f"  {action_name}: group {'/'.join(sorted(was))} -> {new} ({touched} markers)")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    to_mirror = [argv[i + 1] for i, a in enumerate(argv) if a == "--mirror"]
    regroup = [argv[i + 1] for i, a in enumerate(argv) if a == "--set-group"]
    if not to_mirror and not regroup:
        raise SystemExit("nothing to do: pass --mirror <action> and/or "
                         "--set-group '<action>=<NewGroup>'")

    rig = bpy.data.objects[TARGET_RIG]
    check_symmetry(rig)

    for pair in regroup:
        action_name, _, new = pair.partition("=")
        set_group(action_name.strip(), new.strip())

    taken = all_groups()
    for name in to_mirror:
        source = bpy.data.actions.get(name)
        if source is None:
            raise SystemExit(f"no action named {name!r}")
        mirror(rig, source, taken)

    before = {a.name for a in bpy.data.actions}
    bpy.ops.wm.save_mainfile()
    log(f"saved {bpy.data.filepath}")
    bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
    after = {a.name for a in bpy.data.actions}
    lost = sorted(before - after)
    if lost:
        raise SystemExit(f"{len(lost)} action(s) did not survive the save: {', '.join(lost)}")
    log(f"{len(after)} actions after the save, none lost")


if __name__ == "__main__":
    main()
