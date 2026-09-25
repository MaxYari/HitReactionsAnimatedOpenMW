"""Shared pieces of the .nif/.kf export, used by whichever exporter is running.

Pulled out of the earlier, since deleted export_staggers.py: the live exporter
needed its addon plumbing and had been importing a script whose .blend no longer
existed, which is a confusing thing to leave in place.
"""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import staggers_common as common  # noqa: E402

ADDON = "BizarreMorrowindAnimatonUtilities"

# xbase_anim is the third-person skeleton every non-beast NPC and the player use
# in third person; the other two are the female and beast variants of it. OpenMW
# picks up every .kf under animations/<skeleton name>/.
ANIM_FOLDERS = ["xbase_anim", "xbase_anim_female", "xbase_animkna"]

# Error tolerances for the headless key reduction, in the units of each channel.
# A quaternion component of 2e-4 is about a hundredth of a degree; 1e-4 Blender
# units is a hundredth of a Morrowind unit.
TOLERANCES = {"rotation_quaternion": 2e-4, "rotation_euler": 2e-4,
              "location": 1e-4, "scale": 1e-4}
DEFAULT_TOLERANCE = 1e-4


def log(*parts):
    print("[hit-reactions]", *parts, flush=True)


def mod_root():
    return common.mod_root()


def simplify(points, tolerance):
    """Ramer-Douglas-Peucker over (frame, value), iteratively to avoid recursion depth."""
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        x0, y0 = points[lo]
        x1, y1 = points[hi]
        span = x1 - x0
        worst, worst_i = 0.0, -1
        for i in range(lo + 1, hi):
            x, y = points[i]
            straight = y0 + (y1 - y0) * ((x - x0) / span) if span else y0
            error = abs(y - straight)
            if error > worst:
                worst, worst_i = error, i
        if worst > tolerance:
            keep[worst_i] = True
            stack.append((lo, worst_i))
            stack.append((worst_i, hi))
    return keep


def decimate_action(action):
    """Drop keys the curve does not need.

    Stands in for bpy.ops.graph.decimate, which the addon runs through a Graph
    Editor and skips when there is no UI - which is always, in background mode.
    Without this every channel keeps one key per frame, including the scale and
    translation tracks that never move at all.
    """
    from BizarreMorrowindAnimatonUtilities import exporter

    before = after = 0
    for container in exporter.iter_fcurve_containers(action):
        for fcurve in container:
            keys = fcurve.keyframe_points
            before += len(keys)
            if len(keys) < 3:
                after += len(keys)
                continue
            channel = fcurve.data_path.rsplit(".", 1)[-1]
            tolerance = TOLERANCES.get(channel, DEFAULT_TOLERANCE)
            points = [(k.co[0], k.co[1]) for k in keys]
            keep = simplify(points, tolerance)
            for i in range(len(keys) - 1, -1, -1):
                if not keep[i]:
                    keys.remove(keys[i], fast=True)
            fcurve.update()
            after += sum(keep)
    return before, after


def install_headless_decimation():
    """Make the addon's prune step decimate without a Graph Editor."""
    from BizarreMorrowindAnimatonUtilities import exporter

    original = exporter.prune_baked_action

    def prune(context, temp_action, allowed_bones, report=None, reference_name=None):
        dropped = exporter.filter_action_bones(temp_action, allowed_bones)
        if dropped:
            log(f"  dropped {len(dropped)} bone(s) outside '{reference_name}'")
        before, after = decimate_action(temp_action)
        log(f"  keys {before} -> {after}")
        exporter._negate_camera_after_prune(context, temp_action, report)

    exporter.prune_baked_action = prune
    return original


def configure(prefs, out_folder):
    prefs.export_folder = out_folder
    prefs.export_as = "3RD_PERSON"
    prefs.enable_root_motion_arp = True
    prefs.negate_camera_motion = False
    prefs.retained_extra_bones = ""
    log(f"export folder {prefs.export_folder!r}, 3rd person, root motion on")
