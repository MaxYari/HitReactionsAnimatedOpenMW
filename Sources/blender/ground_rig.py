"""Put the ARP rig's origin back on the world floor and save.

    blender -b Sources/Reatrget.blend --python Sources/ground_rig.py

Why this matters is in export_exp.ground_rig(): the exporter hands the Morrowind
Bip01 node c_traj's WORLD location, and c_traj already sits at pelvis height
inside the rig, so anything the rig object itself is offset by is added on top.
At z 0.76722 - pelvis height, the same place the Bip01 armature is authored -
every exported character floated about 1.1 metres.

This moves the OBJECT and nothing else. No action is assigned, switched or
edited, so every clip, every hand adjustment and every marker is untouched; the
fix reaches all of them at once because none of them was ever wrong.

The action count is checked across the save, because Blender drops orphaned
data-blocks when it writes a file and this script is not worth losing work to.
"""

import sys

import bpy

TARGET_RIG = "rig"


def log(*parts):
    print("[brutal-staggers]", *parts, flush=True)


def main():
    rig = bpy.data.objects[TARGET_RIG]
    before = {a.name: len(a.pose_markers) for a in bpy.data.actions}

    offset = rig.matrix_world.translation.copy()
    log(f"'{rig.name}' world origin {tuple(round(v, 5) for v in offset)}")
    if offset.length < 1e-6:
        log("already on the floor, nothing to do")
        return

    rig.location -= offset
    bpy.context.view_layer.update()
    landed = rig.matrix_world.translation
    if landed.length > 1e-6:
        raise SystemExit(f"could not ground the rig; it is still at {tuple(landed)} - "
                         "check whether its parent or a constraint is holding it up")
    log(f"moved to {tuple(round(v, 5) for v in landed)}")

    unsaved = [a.name for a in bpy.data.actions if a.users == 0 and not a.use_fake_user]
    if unsaved:
        raise SystemExit(f"{len(unsaved)} action(s) have no user and would be dropped by the "
                         f"save: {', '.join(sorted(unsaved)[:5])}... "
                         "Give them a fake user in Blender first, or say so and this can do it.")

    bpy.ops.wm.save_mainfile()
    log(f"saved {bpy.data.filepath}")

    # The file on disk is the only thing that matters now, so re-read it rather
    # than trusting the session that just wrote it.
    bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
    after = {a.name: len(a.pose_markers) for a in bpy.data.actions}
    lost = sorted(set(before) - set(after))
    remarked = sorted(n for n in set(before) & set(after) if before[n] != after[n])
    if lost:
        raise SystemExit(f"{len(lost)} action(s) did not survive the save: {', '.join(lost)}")
    if remarked:
        raise SystemExit(f"marker counts changed on: {', '.join(remarked)}")
    log(f"{len(after)} actions and every marker intact, rig at "
        f"{tuple(round(v, 5) for v in bpy.data.objects[TARGET_RIG].matrix_world.translation)}")


if __name__ == "__main__":
    main()
