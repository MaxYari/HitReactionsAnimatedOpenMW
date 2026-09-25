"""Retarget the endorphin BVH clips onto the ARP rig.

    blender -b Sources/Reatrget.blend --python Sources/blender/retarget_staggers.py \
        -- --prefix "[ARP]" [--only GROUP]

Leaves one "[Raw] <Group>" action per clip on the 'rig' object, with the pose
markers the exporter turns into text keys, and saves the .blend.

Why the rest pose is redefined: the endorphin skeleton's BVH rest pose (the one
the OFFSET lines describe, with every rotation zero) is a seated pose - the
spine and thighs both run along +X - while the ARP rig rests in a T-pose. ARP's
remapper binds source to target through their rest poses, so it has to be told
what the source's T-pose is. arp.copy_bone_rest aims each mapped source bone
along its target bone's rest direction, which is exactly that.
"""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import staggers_common as common  # noqa: E402
import bvh_rig_setup as rigsetup  # noqa: E402

TARGET_RIG = "rig"
MORROWIND_RIG = "Bip01"
# The bone mapping and the rest-pose construction both live in bvh_rig_setup,
# so the automatic pipeline and the by-hand ARP setup in Reatrget.blend cannot
# drift apart. BONE_MAP is what ARP drives; ORIENT_FROM is what each bone's rest
# orientation is measured against, and they are deliberately not the same table.
BONE_MAP = rigsetup.BONE_MAP

ROOT_SOURCE_BONE = "root"


def log(*parts):
    print("[brutal-staggers]", *parts, flush=True)


def select_pose_bone(pose_bone, state=True):
    """Blender 5.1 moved the selection flag onto the pose bone; 4.x has it on Bone."""
    if hasattr(pose_bone, "select"):
        pose_bone.select = state
    else:
        pose_bone.bone.select = state


def activate(obj, mode="OBJECT"):
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode=mode)


def import_bvh(path):
    before = set(bpy.data.objects.keys())
    bpy.ops.import_anim.bvh(
        filepath=path, global_scale=1.0, rotate_mode="NATIVE",
        axis_forward="-Z", axis_up="Y",
        update_scene_fps=False, update_scene_duration=False, use_fps_scale=False,
    )
    new = set(bpy.data.objects.keys()) - before
    if len(new) != 1:
        raise RuntimeError(f"BVH import produced {len(new)} objects: {new}")
    return bpy.data.objects[new.pop()]


def fill_bones_map(scn):
    """Replace whatever build_bones_list guessed with our own mapping."""
    scn.bones_map_v2.clear()
    for source_bone, target_bone in BONE_MAP.items():
        item = scn.bones_map_v2.add()
        item.name = target_bone          # implicit "name" is the TARGET bone
        item.source_bone = source_bone
        item.set_as_root = (source_bone == ROOT_SOURCE_BONE)
        item.location = (source_bone == ROOT_SOURCE_BONE)
        item.ik = False


def character_yaw(armature, left_bone, right_bone):
    """Which way the character faces, in degrees around +Z, from its hip axis.

    Measured the same way on both rigs so the two are comparable: the vector
    from the right hip to the left hip, flattened, turned a quarter turn.
    """
    import math
    from mathutils import Vector

    evaluated = armature.evaluated_get(bpy.context.evaluated_depsgraph_get())
    left = evaluated.matrix_world @ evaluated.pose.bones[left_bone].head
    right = evaluated.matrix_world @ evaluated.pose.bones[right_bone].head
    across = left - right
    across.z = 0.0
    if across.length < 1e-6:
        return None
    forward = across.normalized().cross(Vector((0.0, 0.0, 1.0)))
    return math.degrees(math.atan2(forward.y, forward.x))


RETARGET_OPTIONS = dict(
    interpolation_type="LINEAR", handle_type="DEFAULT", fake_user_action=True,
)


def run_retarget(rig, start, end, root_motion):
    activate(rig)
    bpy.ops.arp.retarget(
        "EXEC_DEFAULT", frame_start=start, frame_end=end,
        # Move the pelvis position onto c_traj, which is the bone the exporter's
        # Root Motion option copies onto the Bip01 root node. All three axes, and
        # loc_z_offset off so c_traj carries the pelvis height outright rather
        # than its change: that is what vanilla does. xbase_anim.kf keys Bip01 at
        # z 76.4 standing and 6.7 once the body is down, and leaves Bip01 Pelvis
        # at zero throughout. Rotation stays on the pelvis - the root node's
        # rotation is not accumulated by the engine, so putting it there would
        # buy nothing and only muddy what Bip01 means.
        extract_root_motion=root_motion,
        loc_x=True, loc_y=True, loc_z=True, loc_z_offset=False,
        rotation=False, forward_axis="Z",
        **RETARGET_OPTIONS)
    return rig.animation_data.action


def probe_output_yaw(source, rig, start):
    """Retarget two frames just to see which way the result comes out facing.

    The correction has to be measured on the output, not on the source. Rotating
    the source rig by some angle does move the result by exactly that angle -
    verified - but the angle the result starts at is not the angle the source
    starts at: the rest-pose snapshot normalises the source's own orientation
    away, so there is no way to predict the output's facing without producing
    some of it. Two frames is enough and costs a few seconds.
    """
    bip = bpy.data.objects[MORROWIND_RIG]
    rig.animation_data_create()
    rig.animation_data.action = None

    probe = run_retarget(rig, start, start + 1, root_motion=False)
    bpy.context.scene.frame_set(start)
    yaw = character_yaw(bip, "Bip01 Thigh.L", "Bip01 Thigh.R")

    rig.animation_data.action = None
    if probe is not None:
        probe.use_fake_user = False
        bpy.data.actions.remove(probe)
    return yaw


def turn_source(source, degrees):
    import math

    source.rotation_mode = "XYZ"
    source.rotation_euler[2] += math.radians(degrees)
    bpy.context.view_layer.update()


def target_rest_yaw():
    """Which way the Morrowind skeleton faces at rest, in WORLD space.

    Off the armature data and not off the posed rig, because clearing an action
    does not clear a pose - the bones keep the basis values the last bake left
    them with, and measuring those returned the pose we were trying to correct.

    But through matrix_world, because head_local is armature space and the probe
    it is compared against measures in world space. Those two differ by exactly
    the Bip01 object's authored 87.5 degree rotation, so leaving it out aimed
    every clip 87.5 degrees short: the body came out turned a quarter turn and
    the root motion with it, so a sideways stagger travelled forward or back.
    With the object transform included this is Morrowind's own neutral - vanilla
    walkforward moves the root along +Y, which is where this lands.
    """
    import math
    from mathutils import Vector

    obj = bpy.data.objects[MORROWIND_RIG]
    bones = obj.data.bones
    left = obj.matrix_world @ Vector(bones["Bip01 Thigh.L"].head_local)
    right = obj.matrix_world @ Vector(bones["Bip01 Thigh.R"].head_local)
    across = left - right
    across.z = 0.0
    forward = across.normalized().cross(Vector((0.0, 0.0, 1.0)))
    return math.degrees(math.atan2(forward.y, forward.x))


def redefine_source_rest_pose(source, rig, reference_frame):
    """Build the ARP-matching rest pose and hand it to ARP's remapper.

    The construction is bvh_rig_setup.build_rest_pose: aim every bone by
    joint-to-joint directions, impose twist only where children pin it, and
    measure the whole thing against a frame of the clip rather than the BVH's
    own rest pose. That last part matters because these clips carry a constant
    ~88 degree yaw between root and LowerSpineJoint which is a convention of the
    data, not animation - building from the BVH rest leaves it in, and it ends
    up dragging the legs round, because this ARP rig hangs them off c_spine_01.x
    rather than the pelvis.
    """
    action, previous = rigsetup.build_rest_pose(source, rig, reference_frame)

    # Put the clip back on the rig before entering redefine mode. ARP records
    # whatever action is assigned at that moment as the source action, so going
    # in with the rest action attached would leave it retargeting the rest pose.
    source.animation_data.action = previous

    activate(source, "POSE")
    bpy.ops.arp.redefine_rest_pose("EXEC_DEFAULT", preserve=True, rest_pose="REST")

    # ARP unlinks the action on entry, so the pose is read out of the action and
    # written onto the bones by hand.
    activate(source, "POSE")
    source.animation_data.action = action
    bpy.context.scene.frame_set(rigsetup.REST_FRAME)
    captured = {pb.name: pb.matrix_basis.copy() for pb in source.pose.bones}
    source.animation_data.action = None
    for name, basis in captured.items():
        source.pose.bones[name].matrix_basis = basis
    bpy.context.view_layer.update()

    activate(source, "POSE")
    bpy.ops.arp.save_pose_rest()
    bpy.ops.object.mode_set(mode="OBJECT")

    source.animation_data.action = previous
    action.use_fake_user = False
    bpy.data.actions.remove(action)


def add_markers(action, group, start, stagger_stop, stop, preserved=None):
    """Write the text keys, or put back the ones that were placed by hand.

    A retarget throws the old action away and makes a new one, so hand-placed
    keys have to be carried across explicitly or a rebuild silently replaces
    them with the automatic guess.
    """
    for marker in list(action.pose_markers):
        action.pose_markers.remove(marker)

    if preserved:
        first, last = (int(round(v)) for v in action.frame_range)
        for name, frame in preserved:
            marker = action.pose_markers.new(name)
            marker.frame = frame
            if not first <= frame <= last:
                log(f"{group}: WARNING kept marker {name!r} at {frame}, outside {first}..{last}")
        log(f"{group}: kept {len(preserved)} hand-placed marker(s)")
        return

    for frame, key in ((start, common.KEY_START),
                       (stagger_stop, common.KEY_STAGGER_STOP),
                       (stop, common.KEY_STOP)):
        marker = action.pose_markers.new(f"{group}: {key}")
        marker.frame = frame


def rest_reference_frame(preserved, start):
    """Which frame the rest pose is measured against.

    The bind is exact at this frame and drifts away from it, so it wants to be
    the frame the animation is actually entered on - the Start key - rather than
    wherever the trimmed clip happens to begin. On this clip that is frame 11
    against a trim start of 1, and referencing the trim start left a ~19 degree
    toes-down bias across the whole marked stagger.
    """
    if preserved:
        for name, frame in preserved:
            if name.split(":")[-1].strip().lower() == common.KEY_START.lower():
                return int(round(frame))
    return start


def retarget_clip(group, bvh_name, preserved=None, prefix="[Raw]"):
    scn = bpy.context.scene
    rig = bpy.data.objects[TARGET_RIG]
    path = common.bvh_path(bvh_name)

    start, stagger_stop, stop, _ = common.trim_points(path)
    # BVH frame 0 imports as Blender frame 1.
    start, stagger_stop, stop = start + 1, stagger_stop + 1, stop + 1
    log(f"{group}: frames {start}..{stop}, stagger ends {stagger_stop}")

    source = import_bvh(path)
    source.name = f"SRC_{group}"
    source.animation_data.action.name = f"SRC_{group}"
    scale = common.source_scale(path)
    source.scale = (scale, scale, scale)
    log(f"{group}: source scale {scale:.6f}")

    try:
        scn.frame_start, scn.frame_end = start, stop
        scn.target_rig = TARGET_RIG
        scn.source_rig = source.name       # also sets scn.source_action

        activate(source)
        bpy.ops.arp.build_bones_list()
        fill_bones_map(scn)

        rigsetup.force_fk_limbs(rig)
        reference = rest_reference_frame(preserved, start)
        log(f"{group}: rest pose referenced at frame {reference}")
        redefine_source_rest_pose(source, rig, reference)

        # OpenMW applies the actor's own facing to the skeleton's parent node, so
        # whatever orientation an animation carries reads as a turn away from
        # where the character is looking. These clips were simulated facing
        # roughly -Y while the Morrowind skeleton rests facing +X, which is what
        # put every character back-to-front in game.
        rig.animation_data_create()
        rig.animation_data.action = None
        wanted_yaw = None
        measured = probe_output_yaw(source, rig, start)
        if measured is not None:
            wanted_yaw = target_rest_yaw()
            correction = ((wanted_yaw - measured + 180.0) % 360.0) - 180.0
            log(f"{group}: output faced {measured:.1f} deg, turning source {correction:+.1f}")
            turn_source(source, correction)
            # The bind offsets are taken in the source's own space, so the
            # snapshot has to be retaken after turning it.
            rigsetup.force_fk_limbs(rig)
        reference = rest_reference_frame(preserved, start)
        log(f"{group}: rest pose referenced at frame {reference}")
        redefine_source_rest_pose(source, rig, reference)

        rig.animation_data.action = None
        run_retarget(rig, start, stop, root_motion=True)

        action = rig.animation_data.action
        if action is None:
            raise RuntimeError(f"{group}: retarget left no action on '{TARGET_RIG}'")
        action.name = f"{prefix} {group}"
        action.use_fake_user = True
        add_markers(action, group, start, stagger_stop, stop, preserved)

        bpy.context.scene.frame_set(start)
        final = character_yaw(bpy.data.objects[MORROWIND_RIG], "Bip01 Thigh.L", "Bip01 Thigh.R")
        if final is not None and wanted_yaw is not None:
            wanted_yaw = ((wanted_yaw + 180.0) % 360.0) - 180.0
            off = ((final - wanted_yaw + 180.0) % 360.0) - 180.0
            log(f"{group}: faces {final:.1f} deg, {off:+.1f} off the rig's rest"
                + ("  <-- CHECK" if abs(off) > 5.0 else ""))
        log(f"{group}: action '{action.name}' range {tuple(action.frame_range)}")
        return action
    finally:
        # The retarget names its output after the source action, so the source's
        # own action has to go or the next clip's lookup is ambiguous.
        data = source.data
        bpy.data.objects.remove(source, do_unlink=True)
        bpy.data.armatures.remove(data)
        for act in list(bpy.data.actions):
            if act.name.startswith(f"SRC_{group}") and act.users == 0:
                bpy.data.actions.remove(act)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    # The by-hand file keeps its retargets under a different tag, so a pass over
    # it cannot quietly replace the pipeline's own actions or vice versa.
    prefix = argv[argv.index("--prefix") + 1] if "--prefix" in argv else "[Raw]"

    scn = bpy.context.scene
    scn.render.fps = 60

    remark = "--remark" in argv

    for group, bvh_name in common.CLIPS:
        if only and group != only:
            continue

        # Markers placed by hand outlive the action they were placed on, unless
        # the run explicitly asks for them to be worked out again. Taken from
        # MANUAL_MARKERS in preference to whatever is in the .blend, so the
        # marking lives in the source and a lost .blend cannot silently revert
        # a clip to its computed guess.
        preserved = None
        if group in common.MANUAL_MARKERS and not remark:
            first, stagger_stop, stop = common.MANUAL_MARKERS[group]
            if stop is None:
                _, _, computed_end, _ = common.trim_points(
                    common.bvh_path(bvh_name))
                stop = computed_end + 1
            preserved = [(f"{group}: {common.KEY_START}", first),
                         (f"{group}: {common.KEY_STAGGER_STOP}", stagger_stop),
                         (f"{group}: {common.KEY_STOP}", stop)]
        elif group in common.MANUAL_MARKERS:
            log(f"{group}: --remark given, ignoring the hand-placed markers")

        for stale in (f"{prefix} {group}", f"SRC_{group}"):
            act = bpy.data.actions.get(stale)
            if act:
                act.use_fake_user = False
                bpy.data.actions.remove(act)
        retarget_clip(group, bvh_name, preserved, prefix)

    bpy.ops.wm.save_mainfile()
    log("saved", bpy.data.filepath)


# Guarded so these helpers can be imported without running the whole script.
if __name__ == "__main__":
    main()
