# Hit Reactions Animated - development notes

How the mod is built and why it works the way it does. None of this is needed to
play it; the user-facing page is [README.md](../README.md).

The retargeting reference lives separately in
[Sources/RETARGETING.md](../Sources/RETARGETING.md) - read that before touching
the animation pipeline.

## Layout

```
HitReactionsAnimated.omwscripts     the manifest, both halves
Animations/xbase_anim/              flinch + stagger clips, third person
Animations/xbase_anim_female/       stagger clips, female skeleton
Animations/xbase_animkna/           stagger clips, beast skeleton (see rough edges)
scripts/MaxYari/hit reactions/      the flinch half
scripts/MaxYari/hit reactions/staggers/   the stagger half
Sources/                            nothing below here ships
  Reatrget.blend                    the ARP retarget workspace
  bvh/                              the 27 endorphin recordings
  blender/                          the build and check scripts
  tests/                            pure-Lua tests, no Blender or OpenMW needed
  reference/                        OpenMW API dumps
  RETARGETING.md                    the retargeting reference
  shipped_clips.json                what the last export shipped
```

The flinch half keeps the script paths it was published under, so existing saves
still resolve it. The stagger half moved in underneath it.

## Are staggers per-weapon?

No. Morrowind has one set of hit reactions for everything: `hit1` through
`hit5`, on the base skeleton, picked at random by
`CharacterController::chooseRandomGroup("hit")`. Nothing about the attacker's
weapon, the defender's weapon or the damage type reaches that choice. Attacks
are per-weapon; reactions are not. That is why this mod overrides one flat set
of groups and not a per-weapon matrix.

Worth knowing: `chooseRandomGroup` counts upwards until the group is missing, so
the engine will happily roll `hit6`, `hit7` and so on if a mod defines them. Ten
extra hit reactions could therefore be added with no Lua at all. This mod uses
Lua instead so the clip can be picked to match the blow, so deaths get the same
treatment, and so the stun length stays vanilla's.

## Picking a clip for the blow

`I.Combat.addOnHitHandler` hands the victim the whole attack - who swung, what
kind of swing, and whether it landed - and its handlers run before the engine
applies the stagger, so the information is waiting by the time the hit animation
is played.

From that, the push is built as a vector rather than as a set of cases:

```
push = (away from the attacker) * 0.8  +  (the attacker's right) * swing.x
```

which is read back in the victim's own frame as a bearing - 0 straight ahead,
+90 to their left, 180 behind. Every clip carries its **measured** travel
bearing, so the one chosen is simply the nearest, with everything inside 35
degrees of the best staying in the running so a direction with several
candidates still varies.

Doing it with vectors is what makes a blow from behind throw the character
forwards with no special case: "away from the attacker" is a direction like any
other. It also means the attacker standing off to one side shifts the result
smoothly rather than snapping between buckets.

The push is worked out twice: once with the sweep, once without it. Both pools
of clips are used. Every blow drives someone away from whoever swung, whatever
the weapon was doing sideways, so the clips that go that way - straight back, or
forward when the blow came from behind - stay in the running for **every** attack
type and not just for the ones with no sweep to speak of. Without the second
pool a sweep worth more than the 0.8 away-weight swings the bearing far enough
that the straight-back clips can fall outside the 35-degree slack window.

### Never the same clip twice running

A clip that just played is removed from the pool rather than rerolled around, so
a repeat is impossible while anything else fits. Seeing one animation play out
and immediately repeat reads worse than a slightly less apt clip does.

When that empties the pool - one long sideways clip, say, and it is the one just
used - the **distance** is given up before the direction, and a short clip going
the same way is taken instead. If there is nothing left either way the mod stands
down and the engine plays its own reaction: a vanilla twitch is a better answer
than a stagger pointing somewhere the blow did not.

With the current collection the far sub-pool is a single clip for every sideways
blow, so that is where the fallback actually happens. No pool is down to one clip
overall, so the give-up-entirely branch never fires today.

```
luajit Sources/tests/test_no_repeat.lua
```

### Saying how a weapon swings

`scripts/MaxYari/hit reactions/staggers/attack_directions.yaml` gives each attack a
swing vector in the **attacker's** frame - `x` sideways, negative their left;
`y` vertical, positive up:

A slash that travels **left to right** is `[1, 0]`; **right to left** is
`[-1, 0]`.

```yaml
weapononehand:                     # the odd one out: slash goes left to right
  chop: [0, -1]
  slash: [1, 0]
  thrust: [0, 0]

weapontwohand:                     # everything else slashes right to left
  chop: [0, -1]
  slash: [-1, 0]
  thrust: [0, 0]
```

`[0, 0]` means no sweep - a thrust or a shot. The character is still thrown,
just straight away from whoever hit them, so forward needs no vector of its own.

Keys are animation group names as OpenMW reports them. Anything unlisted falls
back to `default` for its attack type, so the file only needs the attacks that
differ.

The group is read with `animation.getActiveGroup` on the attacker at the moment
of the hit, which is the group actually driving their arm.

#### Why the alternating swings do not reach this

ReAnimation's alternating attacks are **first person only**. Every one of its
`addAttackVariants` calls passes `ARMATURE_TYPE.FirstPerson`, and it ships only
an `Animations/xbase_anim.1st` folder - there is no third-person animation in it.

This mod is third person, so the group driving an attacker's arm as the victim
sees it is always the vanilla one: `weapononehand`, `weapontwohand`,
`weapontwowide` or `handtohand`. The `alt`, `sub` and `ktn` entries in the file
cannot currently be reached, and are kept only so they are already right if
third-person variants ever ship.

The consequence is worth understanding rather than working around: in third
person a two-handed slash has exactly one animation, it sweeps one way, and so
it throws the target the same way every time. That is faithful to what actually
played. In first person you see your own arms alternate and the target will not
follow them - the victim's script cannot see your first-person armature, and
`openmw.animation` has no first-person accessor to offer it one.

`y` is used for the vertical: a blow at or below -0.6 is treated as coming
straight down and prefers clips tagged `down` over matching the compass.

### Checking it

```
luajit Sources/tests/test_direction_math.lua     # the vector maths, 17 cases
luajit Sources/tests/test_clip_selection.lua     # which clips a given push chooses
```

Neither needs Blender or OpenMW. The first caught a sign error that had the
attacker's right vector pointing left, which mirrors every sweep - a mistake
that looks plausible enough in game to miss.

## Marking clips

A clip ships if, and only if, it is an action named `[ARP][Exp] <something>` in
`Sources/Reatrget.blend` with two pose markers on it. The markers are the whole
configuration:

```
StaggerStumbleLeft2: Start        StaggerStumbleLeft2: Stop
DeathBack: Start                  DeathBack: Stop
```

* the text before `": "` is the **animation group** OpenMW will see;
* its first word is the **kind** - `Stagger*` for a hit reaction, `Death*` for a
  death;
* the two frames are the span, and there is one span per clip.

Repurposing a clip is renaming its markers. `[ARP][Exp] BSKnockDownLeft` ships as
a death called `deathdown` for that reason alone; the action name only records
which recording it came from. Two clips may not claim the same group -
`export_exp.py` stops rather than letting one .kf overwrite another.

Direction is not configured here, it is measured. The names are written from the
**viewer's** side - a player looking at the enemy they just hit - while every
number in the pipeline is in the character's own frame, so the two sides swap
between them: a clip called `Left` carries the body to the viewer's left, which
is the character's own right. `Back` and `Forward` need no swap. The build reads
the name as well and says so if the two disagree; across the shipped clips they
agree on every one.

### How long a stagger should be

**Vanilla is the truth.** `hit1`-`hit5` run 1.000, 1.133, 1.000, 1.000 and 1.000
seconds, and the engine holds a character for exactly as long as the one it drew
plays - so those *are* the stun lengths. The mod does not touch them, which means
combat timing is vanilla's, with nothing to configure.

Cut a stagger to **1.00-1.10s** and it plays as it is. Longer than 1.10s and it
is played faster to land on **1.05s**, just under vanilla's shortest so it fits
whichever hit group the engine drew. That speed-up is capped at **1.15x**: past
there a stagger stops reading as weight being thrown about and starts reading as
a twitch. Anything still too long is cut off at the end, and the recovery blend
covers it.

```
blender -b Sources/Reatrget.blend --python Sources/blender/check_markers.py
```

reports each clip as cut, what it will actually play at, and which ones need
their Stop marker moved earlier.

A death is not banded. Nothing is stretched and nothing is cut - the clip plays
out in full and holds where it landed, because a body takes as long as it takes.

## How the override works

Hit reactions and deaths are played by the engine, not by Lua, so there is no
"a stagger started" event to listen for. But every engine-initiated animation
goes through `CharacterController::playBlendedAnimation`, which hands off to
`I.AnimationController.playBlendedAnimation` once Lua animations are enabled on
the actor (`character.cpp:2609`). That is the hook.

The vanilla animation is **not** suppressed with `options.skip`. The engine's
own state machines wait on it - `character.cpp:410` asks whether `mCurrentHit`
is still playing to decide when the character recovers - so skipping it ends the
stagger on the frame it began. Instead it is made invisible with
`blendMask = 0`: the state still exists, still advances, still fires its text
keys and still drives the state machine, it just moves no bones. Our clip plays
on top at a higher priority.

Two consequences worth understanding:

**Priorities are uneven on purpose.** `Animation::play` erases any state whose
four-bone-group priority is exactly equal to the one being played. A uniform
priority table would match the hidden vanilla animation's own uniform table and
destroy it, taking the engine's timing with it. Staggers use
`{10, 11, 11, 11}`, falls use `{11, 12, 12, 12}`.

They are also high because of what else is running. The engine plays a hit
reaction at priority 6, but a drawn weapon holds 7 on the torso and both arms -
which is why vanilla hit reactions are a lower-body twitch whenever a weapon is
out. Clearing Weapon (7), Block (8), Knockdown (9) and Torch (10) is what makes
these play on the whole body.

**Two different answers to "who owns the timing".**

* **Stagger:** the engine does. `hit1`-`hit5` are the stun, so they are left
  exactly as they are and the clip is sped up to fit inside. Combat timing stays
  vanilla's to the frame.
* **Death:** nobody. Death timing does not matter. When the engine's animation
  ends the mod lets go of the clip rather than cancelling it, so the fall plays
  out in full and holds where it landed. Nothing is stretched.

## Retargeting

**`Sources/RETARGETING.md` is the reference** - how the rest pose is built, why
each rule is there, and what breaks without it. Read it before changing anything
in the pipeline; most of these failures present as something else entirely.

## Retargeting by hand

`Sources/Reatrget.blend` is the by-hand ARP setup. The BVH skeleton has no rest
pose worth binding to - with every rotation zero it sits in a seated, twisted
shape, spine and thighs along +X but shoulders separated along Y - so ARP has
nothing to match against. Two scripts fix that:

```
blender -b Sources/Reatrget.blend --python Sources/blender/bvh_rig_setup.py
```

scales the BVH rig, turns it to face the way the ARP rig rests, rebuilds ARP's
bones list with the mapping that actually drives the Morrowind bones, and stores
an ARP-matching rest pose in a `[Rest] ARP Match` action. Every mapped bone ends
up within 0.000 degrees of its ARP counterpart's rest orientation.

Then, from Blender's Text Editor, `Sources/blender/apply_bvh_rest_pose.py` puts that
pose onto the rig at any time - including while ARP is in Redefine Rest Pose
mode, where the action list is no help because ARP unlinks the action on entry.
Run it, then press Apply.

The scale is chosen to match **leg length**, which is what puts the feet on the
floor and makes travel distances right. The two skeletons are not proportioned
alike - leg to spine is 1.27 on the BVH rig against 1.63 on the ARP rig - so
matching the legs leaves the BVH spine about 29% long and its head roughly 12cm
above the ARP head. That is proportion, not error: a retarget transfers
orientations, and every bone's orientation matches exactly. Pass
`--scale spine` to trade it the other way, or `--scale 0.0185` for a number.

Only rotations are set, plus the root's location.

## Rebuilding the animations

Needs Blender 5.1 with Auto-Rig Pro, the
[Blender Morrowind Plugin](https://github.com/Greatness7/io_scene_mw) and
Bizarre Morrowind Anim Utils.

What ships comes out of `Sources/Reatrget.blend`, where the clips are trimmed
and marked by hand:

```
BL=/path/to/blender

# retarget every BVH onto the ARP rig as an "[ARP] ..." action
$BL -b Sources/Reatrget.blend --python Sources/blender/retarget_staggers.py --prefix "[ARP]"

# ... trim, mark and rename the keepers to "[ARP][Exp] ..." in Blender ...

# export those, and only those
$BL -b Sources/Reatrget.blend --python Sources/blender/export_exp.py
$BL -b Sources/Reatrget.blend --python Sources/blender/check_markers.py
```

The export **deletes** anything in the three `Animations/xbase_anim*` folders it
did not just write. They hold nothing but generated output, and OpenMW loads
every `.kf` under them, so a file left behind from a build with different group
names is an animation source the game reads and the mod no longer knows about.

`Sources/blender/staggers_common.py` holds the clip list and the trimming;
`retarget_staggers.py` holds the endorphin-to-ARP bone map.
`scripts/MaxYari/hit reactions/staggers/clips.lua` is generated by the export.

### Two things the pipeline gets right that are easy to get wrong

**The source rig's scale.** Only rotations and the root's translation survive a
retarget, and the pose is the target rig's own, so the one thing the source's
size has to get right is the translation. It is scaled by leg length - hip joint
to ankle joint - read off the BVH hierarchy's OFFSET lines rather than off the
first frame, because the second batch of clips opens with the knees slightly
bent and scaling to that pelvis height would have made those characters 10% too
big. ARP's own auto-scale came out 2.9x too large, because it compares
whole-armature bounding boxes and skips every target bone whose head is below
z=0 - which on this rig is both legs.

**Where root motion lives.** Morrowind carries the entire pelvis position,
height included, on the `Bip01` root node, and leaves `Bip01 Pelvis` at zero:
vanilla `xbase_anim.kf` keys `Bip01` at z 76.369 standing and 6.7 once a body is
down. The retarget therefore extracts all three axes onto `c_traj`, with ARP's
"keep initial Z offset" *off* so the height is absolute rather than relative.
The exported clips match that convention to three decimal places.

**The source rest pose.** The endorphin skeleton's BVH rest pose - the one the
OFFSET lines describe - is a seated, twisted shape: spine and thighs both along
+X, but shoulders separated along Y. The ARP rig rests in a T-pose. The
reconciliation gives each mapped source bone its target bone's rest orientation
outright, which makes the bind offset the identity.

ARP's own `arp.copy_bone_rest` aims a Damped Track at the target's direction
instead. That fixes where a bone points but leaves its roll to whatever the
source happened to have - and for the pelvis, whose target direction is straight
up, it leaves the yaw entirely unconstrained. That is what put every character
back-to-front in game.

**Which way the character faces.** OpenMW applies the actor's own facing to the
skeleton's parent node, so any orientation baked into an animation reads as a
turn away from where the character is looking. These clips were simulated facing
roughly -Y while the Morrowind skeleton rests facing +X. The retarget therefore
runs a two-frame probe first, measures which way the output actually comes out
facing, and turns the source to compensate - measured on the output rather than
on the source, because the rest-pose snapshot normalises the source's own
orientation away. Every clip is checked afterwards and logs how far off it
landed; all 27 currently land within 0.1 degrees.

**Which bone is the neck.** On this rig `Bip01 Neck` is driven by
`c_spine_04.x`, not by `c_neck.x` - `c_neck.x` is a 4mm stub. Check by walking
the parent chain of `Bip01 Neck_qr_offset`, the bone `Bip01 Neck` copies its
transform from. Mapping the neck to the stub leaves `Bip01 Neck` with two
keyframes and zero rotation while `c_head.x` still receives the source's full
head orientation, so the head alone has to account for the whole neck-plus-head
bend and ends up at impossible angles.

**Nothing is scaled.** The scale above is applied to the BVH rig inside Blender
and never reaches the game: a retarget transfers rotations, which are
scale-invariant, and the pose is built from the Morrowind rig's own bone
lengths. The exported files carry no scale animation - the largest deviation
from 1.0 on any bone on any key, across all 27 clips, is 0.000006.

