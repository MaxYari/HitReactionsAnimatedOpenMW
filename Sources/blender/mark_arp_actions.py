"""Give each [ARP] clip two text-key markers, ready to be dragged into place.

    blender -b Sources/Reatrget.blend --python Sources/mark_arp_actions.py

One pair per action - "<Name>: Start" and "<Name>: Stop" - placed at the ends of
the action's own range. They are meant to be moved; the point is that the naming
is already settled so dragging is all that is left.

The group name has to be unique across the WHOLE file, not just among these
clips: OpenMW keys an animation group by the text before the colon, so two
actions sharing one would be two halves of the same group. Every group name
already present anywhere in the file is collected first, and the run aborts
rather than writing a name that clashes.

Only actions this pipeline made are touched. Anything else under [ARP] is left
exactly as it is.
"""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import staggers_common as common  # noqa: E402

PREFIX = "[ARP] "


def log(*parts):
    print("[brutal-staggers]", *parts, flush=True)


def marker_group(clip, bvh):
    """A name that says what the clip is and stays unique.

    Death or Stagger by what the source is called, then the clip's own stem.
    A leading word is dropped only when it repeats the kind, so Stagger* and
    Stumble* do not collapse onto each other - BSStaggerBack and BSStumbleBack
    would otherwise both become StaggerBack.
    """
    kind = "Death" if "Death" in bvh or "Death" in clip else "Stagger"
    stem = clip[2:] if clip.startswith("BS") else clip
    if stem.startswith(kind):
        stem = stem[len(kind):]
    return kind + stem


def groups_in_use(skip):
    """Every animation group name any action in the file already mentions."""
    seen = {}
    for action in bpy.data.actions:
        if action.name in skip:
            continue
        for marker in action.pose_markers:
            name = marker.name.split(":")[0].strip()
            if name:
                seen.setdefault(name.lower(), action.name)
    return seen


def main():
    ours = {f"{PREFIX}{clip}": (clip, bvh) for clip, bvh in common.CLIPS
            if bpy.data.actions.get(f"{PREFIX}{clip}")}
    if not ours:
        raise SystemExit(f"no {PREFIX} actions from the clip list in this file")

    taken = groups_in_use(skip=set(ours))
    planned, clash = {}, []
    for action_name, (clip, bvh) in ours.items():
        name = marker_group(clip, bvh)
        if name.lower() in taken:
            clash.append(f"{name} (already used by {taken[name.lower()]})")
        if name.lower() in planned:
            clash.append(f"{name} (twice: {planned[name.lower()]} and {action_name})")
        planned[name.lower()] = action_name

    if clash:
        raise SystemExit("group name collisions, nothing written:\n  " + "\n  ".join(clash))

    log(f"{len(taken)} group name(s) already in the file, none clash")

    for action_name, (clip, bvh) in sorted(ours.items()):
        action = bpy.data.actions[action_name]
        name = marker_group(clip, bvh)
        first, last = (int(round(v)) for v in action.frame_range)

        removed = len(action.pose_markers)
        for marker in list(action.pose_markers):
            action.pose_markers.remove(marker)
        for frame, key in ((first, "Start"), (last, "Stop")):
            action.pose_markers.new(f"{name}: {key}").frame = frame

        log(f"{action_name:32s} {name}: Start@{first}, Stop@{last}"
            + (f"  (replaced {removed})" if removed else ""))

    bpy.ops.wm.save_mainfile()
    log("saved", bpy.data.filepath)


if __name__ == "__main__":
    main()
