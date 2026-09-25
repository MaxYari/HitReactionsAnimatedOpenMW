"""Set up the BVH rig in Reatrget.blend for a hand-driven ARP retarget.

    blender -b Sources/Reatrget.blend --python Sources/bvh_rig_setup.py

Does three things and saves:

1. Scales the BVH rig so its leg length matches the Morrowind skeleton's.
2. Turns it so the clip's first frame faces the way the ARP rig rests.
3. Writes a "[Rest] ARP Match" action holding a single-frame pose that puts the
   BVH skeleton in the ARP rig's rest pose - which is what ARP's Redefine Rest
   Pose needs, and what the BVH hierarchy does not come with.

Only rotations are set, plus the root's location. Bones are never moved to make
the proportions agree: the ARP rig's legs are proportionally longer than the
BVH rig's, so with the pelvises aligned and the legs matched the BVH spine
overshoots the ARP one. That is expected and does not affect a retarget, which
transfers orientations.
"""

import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import staggers_common as common  # noqa: E402

ARP_RIG = "rig"
REST_ACTION = "[Rest] ARP Match"
REST_FRAME = 0

# Which ARP bone each BVH joint should borrow its rest orientation from. The
# four joints ARP has no controller for - the forearm twists, the mid feet -
# take the orientation of the segment they sit in, so they come out straight
# rather than keeping their BVH rest angle.
ORIENT_FROM = {
    "root": "c_root_master.x",
    "LowerSpineJoint": "c_spine_01.x",
    "MiddleSpineJoint": "c_spine_02.x",
    "UpperSpineJoint": "c_spine_03.x",
    # Bip01 Neck is driven by c_spine_04.x on this rig, not by c_neck.x, which
    # is a 4mm stub. Check by walking the parent chain of Bip01 Neck_qr_offset.
    "LowerNeckJoint": "c_spine_04.x",
    "UpperNeckJoint": "c_head.x",
}
for side, suffix in (("Left", ".l"), ("Right", ".r")):
    ORIENT_FROM.update({
        f"{side}ClavicleJoint": f"c_shoulder{suffix}",
        f"{side}ShoulderJoint": f"c_arm_fk{suffix}",
        f"{side}ElbowJoint": f"c_forearm_fk{suffix}",
        f"{side}ForearmTwistJoint": f"c_forearm_fk{suffix}",
        f"{side}WristJoint": f"c_hand_fk{suffix}",
        f"{side}FingersJoint": f"c_middle1{suffix}",
        f"{side}HipJoint": f"c_thigh_fk{suffix}",
        f"{side}KneeJoint": f"c_leg_fk{suffix}",
        f"{side}AnkleJoint": f"c_foot_fk{suffix}",
        f"{side}MidFootJoint": f"c_toes_fk{suffix}",
        f"{side}ToesJoint": f"c_toes_fk{suffix}",
    })

# What to drive with what, for ARP's bones list. Only the joints that have a
# real counterpart; the twists, mid feet and finger stubs are left unmapped so
# they inherit their parent rather than fighting it.
BONE_MAP = {
    "root": "c_root_master.x",
    "LowerSpineJoint": "c_spine_01.x",
    "MiddleSpineJoint": "c_spine_02.x",
    "UpperSpineJoint": "c_spine_03.x",
    "LowerNeckJoint": "c_spine_04.x",
    "UpperNeckJoint": "c_head.x",
}
for side, suffix in (("Left", ".l"), ("Right", ".r")):
    BONE_MAP.update({
        f"{side}ClavicleJoint": f"c_shoulder{suffix}",
        f"{side}ShoulderJoint": f"c_arm_fk{suffix}",
        f"{side}ElbowJoint": f"c_forearm_fk{suffix}",
        f"{side}WristJoint": f"c_hand_fk{suffix}",
        f"{side}HipJoint": f"c_thigh_fk{suffix}",
        f"{side}KneeJoint": f"c_leg_fk{suffix}",
        f"{side}AnkleJoint": f"c_foot_fk{suffix}",
        f"{side}ToesJoint": f"c_toes_fk{suffix}",
    })

ROOT_BONE = "root"


def log(*parts):
    print("[bvh-setup]", *parts, flush=True)


def rotation_channel(pose_bone):
    """The rotation property this bone actually animates through.

    Which one is live depends on the bone's rotation_mode, and the mode is NOT
    ours to change: the BVH importer sets an Euler order per bone to match the
    file's channel order, and the motion action is Euler curves. Switching a
    bone to quaternion makes the engine read rotation_quaternion instead, so
    every Euler curve in the clip stops being applied and the bone freezes at
    whatever the quaternion basis happens to hold - the clip then only moves by
    its root location track, which looks like the rig sliding about in its rest
    pose. Key the channel the bone already uses.
    """
    mode = pose_bone.rotation_mode
    if mode == "QUATERNION":
        return "rotation_quaternion"
    if mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def repair_rotation_modes(bvh):
    """Put back rotation modes a previous run of this script may have changed.

    Read from a throwaway re-import of the clip rather than assumed, so this is
    right for any BVH and not just the one that got broken.
    """
    source = common.bvh_path(f"{bvh.name}.bvh")
    if not os.path.exists(source):
        log(f"no {os.path.basename(source)} to read rotation modes from; leaving them alone")
        return

    before = set(bpy.data.objects.keys())
    bpy.ops.import_anim.bvh(filepath=source, global_scale=1.0, rotate_mode="NATIVE",
                            axis_forward="-Z", axis_up="Y", update_scene_fps=False,
                            update_scene_duration=False, use_fps_scale=False)
    fresh_name = (set(bpy.data.objects.keys()) - before).pop()
    fresh = bpy.data.objects[fresh_name]

    changed = 0
    for pose_bone in fresh.pose.bones:
        target = bvh.pose.bones.get(pose_bone.name)
        if target is not None and target.rotation_mode != pose_bone.rotation_mode:
            target.rotation_mode = pose_bone.rotation_mode
            changed += 1

    data = fresh.data
    action = fresh.animation_data.action if fresh.animation_data else None
    bpy.data.objects.remove(fresh, do_unlink=True)
    bpy.data.armatures.remove(data)
    if action is not None and action.users == 0:
        bpy.data.actions.remove(action)

    bpy.context.view_layer.objects.active = bvh

    modes = {pb.rotation_mode for pb in bvh.pose.bones}
    if changed:
        log(f"restored the rotation mode on {changed} bone(s) -> {sorted(modes)}")
    else:
        log(f"rotation modes already correct ({sorted(modes)})")


def find_bvh_rig():
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and "LowerSpineJoint" in obj.data.bones:
            return obj
    raise SystemExit("no BVH armature in this file (looked for a LowerSpineJoint bone)")


def activate(obj, mode="OBJECT"):
    # Guarded: removing a temporary object leaves the view layer with no active
    # object, and mode_set's poll() fails outright in that state.
    if bpy.context.view_layer.objects.active is not None:
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode=mode)


def hip_yaw(obj, left, right, posed=True):
    """Which way a rig faces, in degrees about +Z, from its hip axis."""
    if posed:
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        l = ev.matrix_world @ ev.pose.bones[left].head
        r = ev.matrix_world @ ev.pose.bones[right].head
    else:
        l = obj.matrix_world @ Vector(obj.data.bones[left].head_local)
        r = obj.matrix_world @ Vector(obj.data.bones[right].head_local)
    across = l - r
    across.z = 0.0
    forward = across.normalized().cross(Vector((0.0, 0.0, 1.0)))
    return math.degrees(math.atan2(forward.y, forward.x))


def bone_length(obj, a, b):
    """Distance between two rest bone heads, in world units."""
    pa = obj.matrix_world @ Vector(obj.data.bones[a].head_local)
    pb = obj.matrix_world @ Vector(obj.data.bones[b].head_local)
    return (pa - pb).length


def report_scale_options(bvh, rig):
    """Print what each candidate scale would give, then return the leg-based one."""
    unscaled = bvh.matrix_world.copy()
    bvh.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()

    thigh = bone_length(bvh, "LeftHipJoint", "LeftKneeJoint")
    shin = bone_length(bvh, "LeftKneeJoint", "LeftAnkleJoint")
    bvh_leg = thigh + shin
    bvh_spine = sum(bone_length(bvh, a, b) for a, b in (
        ("root", "LowerSpineJoint"), ("LowerSpineJoint", "MiddleSpineJoint"),
        ("MiddleSpineJoint", "UpperSpineJoint"), ("UpperSpineJoint", "LowerNeckJoint"),
        ("LowerNeckJoint", "UpperNeckJoint")))

    arp_leg = (bone_length(rig, "c_thigh_fk.l", "c_leg_fk.l")
               + bone_length(rig, "c_leg_fk.l", "c_foot_fk.l"))
    arp_spine = sum(bone_length(rig, a, b) for a, b in (
        ("c_root_master.x", "c_spine_01.x"), ("c_spine_01.x", "c_spine_02.x"),
        ("c_spine_02.x", "c_spine_03.x"), ("c_spine_03.x", "c_spine_04.x"),
        ("c_spine_04.x", "c_head.x")))

    by_leg = arp_leg / bvh_leg
    by_spine = arp_spine / bvh_spine
    log(f"BVH leg {bvh_leg:.3f}, spine {bvh_spine:.3f}  ->  leg/spine {bvh_leg / bvh_spine:.3f}")
    log(f"ARP leg {arp_leg:.3f}, spine {arp_spine:.3f}  ->  leg/spine {arp_leg / arp_spine:.3f}")
    log(f"scale to match legs  : {by_leg:.6f}  (spine then overshoots by "
        f"{(by_leg * bvh_spine / arp_spine - 1) * 100:+.1f}%)")
    log(f"scale to match spine : {by_spine:.6f}  (legs then fall short by "
        f"{(by_spine * bvh_leg / arp_leg - 1) * 100:+.1f}%)")

    bvh.matrix_world = unscaled
    bpy.context.view_layer.update()
    return by_leg, by_spine


def best_fit_rotation(source_dirs, target_dirs):
    """Kabsch: the rotation that best carries source_dirs onto target_dirs."""
    import numpy as np

    a = np.array([[v.x, v.y, v.z] for v in source_dirs])
    b = np.array([[v.x, v.y, v.z] for v in target_dirs])
    u, _, vt = np.linalg.svd(a.T @ b)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    return Matrix(((r[0][0], r[0][1], r[0][2]),
                   (r[1][0], r[1][1], r[1][2]),
                   (r[2][0], r[2][1], r[2][2]))).to_quaternion()


def build_rest_pose(bvh, rig, reference_frame=None):
    """Pose the BVH skeleton into the ARP rig's rest pose and key it.

    Each bone is aimed along its ARP counterpart, and given only the axial twist
    that its own children's positions actually pin down.

    The tempting shortcut - hand every bone its ARP counterpart's orientation
    outright - is wrong, and quietly so. A bone's orientation is its direction
    plus its roll, and the two skeletons do not agree on roll: copying ARP's
    orientation onto the BVH knee is a 3 degree aim and a 78 degree twist, and
    onto the right shoulder a 10 degree aim and a 90 degree twist. Roll moves no
    joints, so the rest pose still measures as a clean T-pose - but the bind
    offset then comes out as the identity, the BVH's own roll convention reaches
    the ARP controllers unfiltered, and the result is a torso twisted a quarter
    turn, shoulders cranked round to keep the arms forward, and hips that sit
    one behind the other instead of side by side.

    So the twist is only imposed where it is observable. A bone with two or more
    mapped children - the pelvis, which carries the spine and both hips, and the
    chest, which carries the neck and both clavicles - has its twist fixed by
    where those children have to land, and a best-fit rotation over their
    directions recovers it. A bone with one child has no observable twist: its
    axial rotation is a free degree of freedom that the clip itself drives, so
    it is aimed and otherwise left as it was. The bind offset then carries the
    convention difference, which is exactly its job.
    """
    action = bpy.data.actions.get(REST_ACTION)
    if action:
        action.use_fake_user = False
        bpy.data.actions.remove(action)
    action = bpy.data.actions.new(REST_ACTION)
    action.use_fake_user = True

    previous = bvh.animation_data.action if bvh.animation_data else None
    bvh.animation_data_create()

    # Start from a standing frame of the clip, not from the BVH's own rest pose.
    #
    # This is the whole ball game. The clip holds a constant ~88 degree twist
    # between root and LowerSpineJoint - present on every frame, so it is a
    # convention of the data and not animation - while the BVH's own rest pose
    # has those two square. Building the rest pose from the rest pose therefore
    # produces a bind that removes nothing, and the 88 degrees goes straight
    # through to the target. It lands on the legs in particular, because this
    # ARP rig hangs them off c_spine_01.x rather than the pelvis, which is what
    # put the hips one behind the other.
    #
    # Measuring the corrections against a frame the clip actually uses absorbs
    # any such constant offset exactly, whichever bone carries it.
    reference = None
    if previous is not None:
        bvh.animation_data.action = previous
        reference = int(round(previous.frame_range[0])) if reference_frame is None else reference_frame
        bpy.context.scene.frame_set(reference)
        bpy.context.view_layer.update()
        start_pose = {pb.name: pb.matrix_basis.copy() for pb in bvh.pose.bones}
    else:
        start_pose = None

    bvh.animation_data.action = action

    activate(bvh, "POSE")
    for pose_bone in bvh.pose.bones:
        if start_pose is not None:
            pose_bone.matrix_basis = start_pose[pose_bone.name]
        else:
            pose_bone.matrix_basis.identity()
    bpy.context.view_layer.update()
    log(f"rest pose measured from {'clip frame ' + str(reference) if reference is not None else 'the BVH rest pose'}")

    def arp_head(name):
        return rig.matrix_world @ Vector(rig.data.bones[name].head_local)

    def arp_tail(name):
        return rig.matrix_world @ Vector(rig.data.bones[name].tail_local)

    ordered = sorted(bvh.pose.bones, key=lambda pb: len(pb.parent_recursive))
    twisted, aimed = [], []

    for pose_bone in ordered:
        target_name = ORIENT_FROM.get(pose_bone.name)
        if target_name is None or target_name not in rig.data.bones:
            continue

        here = bvh.matrix_world @ pose_bone.head
        source_dirs, target_dirs = [], []

        # Aim by joint-to-joint directions: where this bone's children sit,
        # against where their ARP counterparts sit.
        #
        # Not by the bones' own axes. An ARP bone's axis is not always the
        # direction to the next joint - c_foot_fk.l is a short horizontal stub
        # while the real ankle-to-toe span drops 33.7 degrees - so aiming the
        # BVH ankle at that stub pitched every foot down by exactly that much.
        # Joint positions are unambiguous on both rigs; bone stubs are not.
        for child in pose_bone.children:
            child_target = ORIENT_FROM.get(child.name)
            if child_target is None or child_target not in rig.data.bones:
                continue
            to_child = (bvh.matrix_world @ child.head) - here
            to_target = arp_head(child_target) - arp_head(target_name)
            # A child sharing its parent's ARP bone gives a zero-length target.
            if to_child.length > 1e-6 and to_target.length > 1e-4:
                source_dirs.append(to_child.normalized())
                target_dirs.append(to_target.normalized())

        if not source_dirs:
            # A leaf, or a chain end whose child maps onto the same ARP bone:
            # nothing else to go on, so use the bone's own axis.
            source_dirs.append(((bvh.matrix_world @ pose_bone.tail) - here).normalized())
            target_dirs.append((arp_tail(target_name) - arp_head(target_name)).normalized())

        spread = 0.0
        if len(source_dirs) >= 2:
            spread = max(target_dirs[0].cross(d).length for d in target_dirs[1:])

        if spread > 0.1:
            # Two or more directions that genuinely span: the twist is pinned.
            rotation = best_fit_rotation(source_dirs, target_dirs)
            twisted.append(pose_bone.name)
        else:
            # One usable direction: aim it and add no twist of our own.
            rotation = source_dirs[0].rotation_difference(target_dirs[0])
            aimed.append(pose_bone.name)

        world = (bvh.matrix_world @ pose_bone.matrix).to_quaternion()
        local = bvh.matrix_world.to_quaternion().inverted() @ (rotation @ world)
        location, _, scale = pose_bone.matrix.decompose()
        pose_bone.matrix = Matrix.LocRotScale(location, local, scale)
        bpy.context.view_layer.update()

    if ROOT_BONE in bvh.pose.bones:
        bvh.pose.bones[ROOT_BONE].location = (0.0, 0.0, 0.0)
        bpy.context.view_layer.update()

    for pose_bone in bvh.pose.bones:
        pose_bone.keyframe_insert(rotation_channel(pose_bone), frame=REST_FRAME)
        if pose_bone.name == ROOT_BONE:
            pose_bone.keyframe_insert("location", frame=REST_FRAME)

    bpy.ops.object.mode_set(mode="OBJECT")
    log(f"twist fitted from children on {len(twisted)} bone(s): {', '.join(twisted)}")
    log(f"aimed without adding twist: {len(aimed)} bone(s)")
    return action, previous


def report_fit(bvh, rig):
    """How far each BVH joint lands from its ARP counterpart, once posed."""
    ev = bvh.evaluated_get(bpy.context.evaluated_depsgraph_get())
    log("joint positions after the rest pose (mismatch is proportion, not error):")
    for bvh_bone in ("LeftHipJoint", "LeftKneeJoint", "LeftAnkleJoint",
                     "LowerSpineJoint", "UpperSpineJoint", "UpperNeckJoint",
                     "LeftShoulderJoint", "LeftWristJoint"):
        target = ORIENT_FROM.get(bvh_bone)
        if not target or target not in rig.data.bones:
            continue
        got = ev.matrix_world @ ev.pose.bones[bvh_bone].head
        want = rig.matrix_world @ Vector(rig.data.bones[target].head_local)
        log(f"    {bvh_bone:20s} off by {(got - want).length * 100:5.1f} cm  "
            f"(z {got.z:+.3f} vs {want.z:+.3f})")


def force_fk_limbs(rig):
    """Put every limb whose FK controller we drive into FK mode.

    ARP sets these itself, but from inside a bare `try: ... except: pass` around
    `bpy.ops.arp.reset_pose()` (auto_rig_remap.py:3374-3379). When that operator
    fails the switch is skipped silently, the limb stays on IK, and the FK
    controller we are driving moves nothing - the foot then sits at its rest
    angle for the whole clip while the source foot moves.
    """
    switched = []
    for target in set(BONE_MAP.values()):
        if not (target.startswith("c_foot_fk") or target.startswith("c_hand_fk")):
            continue
        ik_bone = rig.pose.bones.get(target.replace("fk", "ik"))
        if ik_bone is not None and "ik_fk_switch" in ik_bone.keys():
            if ik_bone["ik_fk_switch"] != 1.0:
                ik_bone["ik_fk_switch"] = 1.0
                switched.append(ik_bone.name)
    log(f"limbs set to FK: {', '.join(switched) if switched else 'already FK'}")


def write_bone_map(bvh, rig, reset=False):
    """Fill in ARP's bones list, keeping any pairing already set by hand.

    Only the list ARP drives. Which ARP bone a BVH bone is measured AGAINST when
    the rest pose is built is ORIENT_FROM, and that is deliberately separate:
    the root is driven through c_traj by preference, but its geometry has to be
    read against c_root_master.x, the bone that actually sits at the pelvis.
    Reading it against c_traj, down at floor level, would point every direction
    out of the pelvis somewhere quite different.
    """
    scn = bpy.context.scene
    existing = {}
    if not reset:
        for item in scn.bones_map_v2:
            if item.source_bone and item.name and item.name != "None":
                existing[item.source_bone] = (item.name, item.set_as_root, item.location)

    scn.source_rig = bvh.name
    scn.target_rig = rig.name
    scn.bones_map_v2.clear()
    kept = []
    for source_bone, target_bone in BONE_MAP.items():
        item = scn.bones_map_v2.add()
        item.source_bone = source_bone
        if source_bone in existing:
            item.name, item.set_as_root, item.location = existing[source_bone]
            if item.name != target_bone:
                kept.append(f"{source_bone} -> {item.name}")
        else:
            item.name = target_bone
            item.set_as_root = (source_bone == ROOT_BONE)
            item.location = (source_bone == ROOT_BONE)
    log(f"bones list: {len(scn.bones_map_v2)} pairs"
        + (f", kept your pairing for {', '.join(kept)}" if kept else ""))


def main():
    bvh = find_bvh_rig()
    rig = bpy.data.objects[ARP_RIG]
    log(f"BVH rig {bvh.name!r}, ARP rig {rig.name!r}")

    repair_rotation_modes(bvh)

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    choice = argv[argv.index("--scale") + 1] if "--scale" in argv else "legs"

    by_leg, by_spine = report_scale_options(bvh, rig)
    if choice == "legs":
        scale = by_leg
    elif choice == "spine":
        scale = by_spine
    else:
        scale = float(choice)
    bvh.scale = (scale, scale, scale)

    # The BVH root bone sits at the armature's own origin, so putting the object
    # on the ARP pelvis is what makes the two pelvises coincide. The ARP rig is
    # not at the world origin in this file - it stands on the floor - so this
    # has to be read off the rig rather than assumed.
    bvh.location = rig.matrix_world @ Vector(rig.data.bones["c_root_master.x"].head_local)
    bpy.context.view_layer.update()
    log(f"applied scale {scale:.6f} ({choice}), pelvis placed on the ARP pelvis at "
        f"{tuple(round(v, 3) for v in bvh.location)}")

    # Face the way the ARP rig rests, judged on the clip's first frame.
    motion = bvh.animation_data.action if bvh.animation_data else None
    if motion is not None:
        bpy.context.scene.frame_set(int(round(motion.frame_range[0])))
        have = hip_yaw(bvh, "LeftHipJoint", "RightHipJoint")
        want = hip_yaw(rig, "c_thigh_fk.l", "c_thigh_fk.r", posed=False)
        delta = ((want - have + 180.0) % 360.0) - 180.0
        # Turned through the matrix rather than through rotation_euler, so the
        # object's own rotation_mode is left alone whatever it happens to be.
        # Pivoted on the rig's location so the placement above survives.
        pivot = bvh.matrix_world.translation.copy()
        turn = (Matrix.Translation(pivot)
                @ Matrix.Rotation(math.radians(delta), 4, "Z")
                @ Matrix.Translation(-pivot))
        bvh.matrix_world = turn @ bvh.matrix_world
        bpy.context.view_layer.update()
        log(f"first frame faced {have:+.1f} deg, ARP rests at {want:+.1f}, turned {delta:+.1f}")

    frame_arg = argv[argv.index("--frame") + 1] if "--frame" in argv else None
    action, previous = build_rest_pose(bvh, rig, int(frame_arg) if frame_arg else None)
    report_fit(bvh, rig)

    write_bone_map(bvh, rig, reset="--reset-map" in argv)
    force_fk_limbs(rig)

    # Hand the rig back with the motion action on it, the way it was found.
    if previous is not None:
        bvh.animation_data.action = previous
        bpy.context.scene.frame_set(int(round(previous.frame_range[0])))
    log(f"rest pose stored in action {action.name!r} at frame {REST_FRAME}")

    bpy.ops.wm.save_mainfile()
    log("saved", bpy.data.filepath)


# Guarded so these helpers can be imported without running the whole script.
if __name__ == "__main__":
    main()
