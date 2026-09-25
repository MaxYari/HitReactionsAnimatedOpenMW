"""Report every shipped clip's marked length against vanilla.

    blender -b Sources/Reatrget.blend --python Sources/check_markers.py

Reads the same [ARP][Exp] actions the export does, so what it measures is what
the game gets.

Vanilla hit1..hit5 run 1.00 to 1.13 seconds. A stagger's marked length is also
its stun length whenever it is longer than vanilla, because the engine holds the
character until the animation it is hiding finishes - so a clip well outside the
band changes combat, not just how it looks. A fall is not banded: the engine's
own knockdown and death animations are stretched to whatever the clip needs, and
a body takes as long as it takes to land.
"""

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_exp as build  # noqa: E402

# Measured from the game's own xbase_anim.kf: hit1 1.000, hit2 1.133, hit3 1.000,
# hit4 1.000, hit5 1.000. The engine holds a character for exactly as long as the
# hit animation it drew plays, so these are stun lengths.
VANILLA_LOW, VANILLA_HIGH = 1.000, 1.133

# What a stagger should be cut to, and what brutalStaggers.lua does about one
# that is not: anything over STAGGER_MAX is played faster to land on
# STAGGER_TARGET, just under vanilla's shortest hit.
TARGET_LOW = 1.00
STAGGER_MAX = 1.10
STAGGER_TARGET = 1.05

# brutalStaggers.lua plays a clip up to this much faster to fit it into the
# engine's window. Anything still over after that is cut off at the end, so the
# figure worth judging a marking by is the one AFTER the speed-up.
MAX_SPEEDUP = 1.15


def main():
    print(f"\nvanilla hit reactions run {VANILLA_LOW:.3f}s to {VANILLA_HIGH:.3f}s, and that is "
          f"the stun.\naim a stagger at {TARGET_LOW:.2f}-{STAGGER_MAX:.2f}s. Anything longer is "
          f"played up to {MAX_SPEEDUP:.2f}x faster to reach {STAGGER_TARGET:.2f}s;\nwhatever is "
          f"still over after that is cut off at the end in game.\n")
    print(f"{'group':24s} {'kind':>8s} {'as cut':>7s} {'played':>7s} {'speed':>6s}  verdict")

    clips = build.collect()
    short, over = [], []
    for clip in clips:
        seconds = clip["seconds"]
        if clip["kind"] != build.KIND_STAGGER:
            print(f"{clip['group']:24s} {clip['kind']:>8s} {seconds:6.2f}s "
                  f"{seconds:6.2f}s {1.0:5.2f}x  -      a fall runs as long as it runs")
            continue

        # The speed the mod would choose: only as fast as it needs to be, and
        # never past the cap.
        speed = min(seconds / STAGGER_TARGET, MAX_SPEEDUP) if seconds > STAGGER_MAX else 1.0
        played = seconds / speed
        if played < TARGET_LOW:
            verdict = f"SHORT  {played / TARGET_LOW - 1:+.0%} under {TARGET_LOW:.2f}s"
            short.append((clip["group"], played))
        elif played > STAGGER_MAX + 1e-9:
            worst = played / VANILLA_HIGH - 1
            verdict = (f"OVER   {played - STAGGER_MAX:+.2f}s past {STAGGER_MAX:.2f}s, "
                       f"{worst:+.0%} vs vanilla's longest; cut short in game")
            over.append((clip["group"], seconds, played))
        else:
            verdict = "ok"
        print(f"{clip['group']:24s} {clip['kind']:>8s} {seconds:6.2f}s "
              f"{played:6.2f}s {speed:5.2f}x  {verdict}")

    staggers = [c for c in clips if c["kind"] == build.KIND_STAGGER]
    falls = [c for c in clips if c["kind"] == build.KIND_DEATH]
    print(f"\n{len(staggers)} stagger, {len(falls)} fall")
    if short:
        print(f"{len(short)} under {TARGET_LOW:.2f}s: "
              + ", ".join(f"{g} {d:.2f}s" for g, d in sorted(short, key=lambda x: x[1])))
    if over:
        print(f"{len(over)} still over {STAGGER_MAX:.2f}s at {MAX_SPEEDUP:.2f}x - move their "
              "Stop marker earlier:")
        for group, cut, played in sorted(over, key=lambda x: -x[2]):
            print(f"   {group:24s} {cut:.2f}s cut, plays {played:.2f}s, "
                  f"needs a {cut / STAGGER_MAX:.2f}x speed-up to reach {STAGGER_MAX:.2f}s")
    if not staggers:
        print("no stagger clips at all - hit reactions will all fall through to vanilla")
    elif not (short or over):
        print("every stagger lands in the band once the speed-up is applied")


# Guarded so these helpers can be imported without running the whole script.
if __name__ == "__main__":
    main()
