# Retargeting endorphin BVH onto the Morrowind rig

Written for whoever next touches this pipeline, including me. Everything here
was arrived at by measuring, and each rule says what breaks without it, because
most of these failures look like something else.

The short version: **the Blender viewport is not the reference. Vanilla is.**
Nearly every wrong turn below came from validating against the rig's own rest
pose instead of against what `xbase_anim.kf` actually does.

---

## The pipeline

What ships comes out of `Sources/Reatrget.blend`: every BVH is retargeted onto
the ARP rig there as an `[ARP] <name>` action, the ones worth keeping are trimmed
and marked by hand and renamed to `[ARP][Exp] <name>`, and the export picks up
exactly those.

```
blender -b Sources/Reatrget.blend --python Sources/blender/bvh_rig_setup.py    # once
blender -b Sources/Reatrget.blend --python Sources/blender/retarget_staggers.py --prefix "[ARP]"
# ... trim and mark by hand, rename to [ARP][Exp] ...
blender -b Sources/Reatrget.blend --python Sources/blender/export_exp.py
```

`bvh_rig_setup.py` prepares the source rig; for the by-hand ARP route, run
`Sources/blender/apply_bvh_rest_pose.py` from the Text Editor while ARP is in Redefine
Rest Pose mode, and press Apply.

The export writes into the three `Animations/xbase_anim*` folders and generates
`scripts/MaxYari/hit reactions/staggers/clips.lua`. It also **deletes** anything in
those folders it did not just write: they hold nothing but generated output, and
OpenMW loads every `.kf` under them, so a file left from a build with different
group names is not inert.

`--only GROUP` restricts the retarget and the export to one clip.


### The two authoring tools

| | |
|---|---|
| `Sources/blender/mark_arp_actions.py` | Gives every `[ARP]` action a `Start`/`Stop` marker pair to move, named so no two clips claim the same animation group. Run it after a retarget, before marking by hand. |
| `Sources/blender/stagger_recovery.py` | Replaces the fall at the end of a stagger with a two-step balance recovery, solved on the FK controls and snapped onto ARP's IK. This is what made the three staggers that ship; read its docstring before using it. |

`stagger_recovery.py` runs from Blender's Text Editor with the clip assigned, or
headless with settings overridden by name:

```
blender -b Sources/Reatrget.blend --python Sources/blender/stagger_recovery.py -- stance=L unclamped=0.5
```

It writes a copy called `<action> Recovery` and leaves the source alone, so it
can be re-run with different settings freely.

### Checking the result

| | |
|---|---|
| `Sources/blender/check_facing.py` | Is the clip turned in game? Run after every build. |
| `Sources/blender/check_markers.py` | Shipped clip lengths against vanilla's 1.00-1.13s |

---

## Rest pose: the part that decides everything

ARP binds source to target through their rest poses. The BVH skeleton has no
usable one - with every rotation zero it sits in a seated, twisted shape, spine
and thighs along +X but shoulders separated along Y - so one has to be built.

**Aim each bone by joint-to-joint directions, not by bone axes.** An ARP bone's
axis is not always the direction to the next joint. `c_foot_fk.l` is a 0.049
horizontal stub while the real ankle-to-toe span drops 33.7 degrees, so aiming
the BVH ankle at that stub pitched every foot ~34 degrees down. Joint positions
are unambiguous on both rigs; bone stubs are not.

**Impose twist only where children pin it.** A bone's orientation is direction
plus roll, and the two skeletons do not agree on roll. Copying ARP's orientation
outright onto the BVH knee is a 3 degree aim and a **78 degree twist**; onto the
right shoulder, 10 degrees of aim and **90 of twist**. Roll moves no joints, so
the rest pose still measures as a clean T-pose - but the bind offset comes out as
the identity, the BVH's roll convention reaches the controllers unfiltered, and
you get a torso turned a quarter turn with the shoulders cranked round to keep
the arms forward. Only the pelvis (spine + both hips) and the chest (neck + both
clavicles) have two or more mapped children, so only those two get a fitted
twist. Everything else is aimed and otherwise left alone.

**Measure it against a frame of the clip, not the BVH rest pose.** These clips
carry a constant ~88 degree yaw between `root` and `LowerSpineJoint`, present on
every frame, so it is a convention of the data and not animation. Building from
the BVH rest leaves it in. It lands on the legs, because this ARP rig hangs them
off `c_spine_01.x` rather than the pelvis:

```
c_thigh_fk.l <- c_thigh_b.l <- spine_01.x <- c_spine_01.x <- c_root_master.x
```

so the lower spine's 88 degrees drags the hips round and they end up one behind
the other. Referencing the clip's Start marker absorbs it.

---

## The neck

`Bip01 Neck` is driven by **`c_spine_04.x`**, not by `c_neck.x`, which is a 4mm
stub. Check by walking the parent chain of `Bip01 Neck_qr_offset`, the bone
`Bip01 Neck` copies its transform from. Mapping the neck to the stub leaves
`Bip01 Neck` with two keyframes and zero rotation while `c_head.x` still gets
the source's full head orientation, so the head alone accounts for the whole
neck-plus-head bend and reaches impossible angles.

Measured before: `Bip01 Neck` 0.0 degrees over 2 keys, `Bip01 Head` 63.1 over
88. After: neck 36-112 degrees, head 24-108. Vanilla moves the neck 71.

---

## Orientation

**Never flatten the Bip01 object transform.** It is authored at
`loc (0, 0, 0.76722) rot z 1.5266` - vanilla's own Bip01 node, 76.37 units up
and turned 87.5 degrees. A `.kf` stores each node's *local* transform, so
flattening the object moves that 87.5 degrees onto `Bip01 Pelvis` and leaves
`Bip01` with no rotation track at all. In game the node then keeps
`base_anim.nif`'s own rotation, which the pelvis keys no longer cancel.

**Aim at the rig's rest measured in WORLD space.** `head_local` is armature
space; the probe it is compared against measures in world space. Those differ by
exactly that 87.5 degrees, and leaving it out aims every clip a quarter turn
short - the body comes out turned and the root motion with it, so a sideways
stagger travels forward or back.

No constant is needed. With the object transform intact and both sides measured
the same way, the rig's rest *is* Morrowind's neutral.

**Verify against vanilla's root motion, which defines the frame:**

```
walkforward  +90     walkback  -90     walkleft  180     walkright  0
```

`check_facing.py` reports two separate things, because two separate things can
be wrong:

* **travel** - where the root motion carries the character, compared against the
  source clip. This is what the engine accumulates as movement, in the actor's
  frame, so it is the direction a player sees them thrown.
* **body** - which way the skeleton is turned, from the composed
  `Bip01 x Bip01 Pelvis` yaw. Independent of travel, because Bip01's rotation
  turns its children and not its own translation, so a clip can slide the right
  way while facing a quarter turn off. That is exactly what the missing Bip01
  rotation track did.

The body reference is **empirical** - the value measured on a build confirmed
correct in game, not vanilla's. Comparing to vanilla does not work here: the
composed yaw mixes in each rig's bone rest orientations, so it is only
comparable between builds of this same rig. An earlier version of the script
compared against vanilla, passed a build whose root motion was a quarter turn
out, and then failed the build that was finally right. If the rig is ever
rebuilt, re-measure `BODY_REFERENCE` from a clip verified in game.

---

## The rig object's own origin must be at z = 0

The exporter gives the Morrowind `Bip01` node **c_traj's world location**, and
Morrowind reads that node as the pelvis - vanilla keys it at z 76.369 standing,
6.7 once a body is down. c_traj already sits at pelvis height inside the rig, so
whatever the rig OBJECT is offset by is added on top of that and every character
floats by exactly that much.

`Reatrget.blend` had `rig` at z 0.76722, the same height the `Bip01` armature is
authored at. It looks like alignment and is not: it put the ARP rig's feet 0.767
above the floor and the exported clips 1.1 metres up. The earlier, now deleted
BrutalStaggers.blend, whose clips were confirmed correct in game, had it at
zero - which is how this was found.

Nothing inside an action is wrong when this happens, which is what makes it
worth knowing - no marker, no key and no hand adjustment needs redoing. Move the
object and re-export:

```
blender -b Sources/Reatrget.blend --python Sources/blender/ground_rig.py
```

`export_exp.py` also grounds the rig in memory before exporting, so a nudged rig
cannot quietly produce floating clips again.

How to spot it: read the exported `Bip01` z and compare against 76.369. Doubled
height, or anything near it, is this.

---

## Scale, root motion, IK/FK, rotation modes

**Scale by leg length**, hip joint to ankle joint, read off the BVH hierarchy's
OFFSET lines rather than off the first frame - the second batch of clips opens
with the knees slightly bent and scaling to that pelvis height made those
characters 10% too big. ARP's own auto-scale comes out 2.9x too large, because
it compares whole-armature bounding boxes and skips every target bone whose head
is below z=0, which on this rig is both legs.

The two skeletons are not proportioned alike - leg to spine is 1.27 on the BVH
rig against 1.63 on the ARP rig - so matching the legs leaves the BVH spine
about 29% long and its head ~12cm high. That is proportion, not error.

**Root motion goes to `c_traj`, all three axes, with `loc_z_offset` off** so it
carries the pelvis height outright rather than its change. That is what vanilla
does: `xbase_anim.kf` keys `Bip01` at z 76.4 standing and 6.7 once the body is
down, and leaves `Bip01 Pelvis` at zero throughout. Rotation stays on the pelvis.

**Force FK before retargeting.** ARP sets the IK/FK switches itself, but from
inside a bare `try: ... except: pass` around `bpy.ops.arp.reset_pose()`
(`auto_rig_remap.py:3374-3379`). When that operator fails - as it does without a
UI - the switch is skipped silently, the limb stays on IK, and the FK controller
being driven moves nothing: `c_foot_fk` gets zero animated channels and the foot
sits at its rest angle for the whole clip.

**Never change a pose bone's `rotation_mode`.** The BVH importer sets an Euler
order per bone to match the file's channel order, and the motion is Euler curves.
Switching a bone to quaternion makes the engine read `rotation_quaternion`
instead, every Euler curve stops being applied, and the clip only moves by its
root location track - which looks like the rig sliding about in its rest pose.

---

## Clip naming: the names are written from the viewer's side

A clip's name describes what someone watching sees - a player looking at the
enemy they just hit - while every number in the pipeline is in the character's
own frame. So the two sides swap between them:

| name | the character goes |
|---|---|
| **Left** | to their own **right** |
| **Right** | to their own **left** |
| **Back** | back (away from the viewer; no swap) |
| **Forward** | forward (towards the viewer; no swap) |

Measured across all 27 clips, and `NAME_DIRECTIONS` in `export_exp.py` applies
exactly that swap, which is what lets the name be cross-checked against the
measurement rather than appearing to contradict it.

Tag from measured travel where there is a choice; `down` stays a name tag,
because a downward blow is not a direction of travel at all.

One exception, and it is about hard edges rather than about trusting names. The
four quarters meet at 45, 135, 225 and 315 degrees, and a clip travelling near
one of those lines is a coin toss between two buckets that says nothing about the
clip. So when the name claims a quarter and the measurement lands within
`NAME_MARGIN` (20 degrees) of it, the name breaks the tie - it is a statement of
intent, and the measurement is not precise enough to overrule it that close in.
`StaggerStumbleBack` is the case: it measures +129, six degrees off the back
quarter, and is named Back for the obvious reason. Further out than the margin
and the motion wins, because then the two genuinely disagree and the export says
so.

---

## Markers: the clip's whole identity

A finished clip is an action called `[ARP][Exp] <name>` in `Reatrget.blend` with
exactly two pose markers, and those markers say everything the game needs:

```
DeathBack: Start            DeathBack: Stop
StaggerStumbleLeft2: Start  StaggerStumbleLeft2: Stop
```

* the text before `": "` becomes the **animation group**, lowercased by OpenMW;
* its first word is the **kind** - `Stagger*` replaces `hit1`-`hit5`, `Death*`
  replaces `knockdown`, `knockout` and the death groups;
* the two frames are the whole span. One animation per file.

So a clip is repurposed by renaming its markers and nothing else.
`[ARP][Exp] BSKnockDownLeft` ships as a death because its markers say
`DeathDown`; the action name is only a reminder of which BVH it came from.

The rest of the name is free, as long as no two clips claim the same group -
`export_exp.py` refuses a collision rather than letting one .kf overwrite
another. Keep it clear of the 100-odd groups already in the .blend.

Mark a stagger as a short chunk and let the blend rules carry the recovery.
Vanilla `hit1`-`hit5` run 1.00 to 1.13s, so aim at **0.72 to 1.33s**:

```
blender -b Sources/Reatrget.blend --python Sources/blender/check_markers.py
```

The marked length is a stun length too, because the engine holds the character
until the animation it is hiding stops - though the Lua floors it at vanilla, so
marking short changes how a stagger looks and not how combat plays.

A fall is not banded. The engine's knockdown and death animations are stretched
to whatever the clip needs, and a body takes as long as it takes to land.

The older pipeline cut two animations out of one recording, `Start` to
`Stagger Stop` for the stagger and `Start` to `Stop` for the fall, with the cut
guessed from pelvis height. `staggers_common.py` still carries that machinery
for the bulk retarget. Nothing shipped uses it: a clip cut by hand for one job
beats a clip cut by arithmetic for two.

---

## Blend rules: per-kf files are incoming only

The rules that govern a transition belong to the animation being blended **into**,
not the one being left - `Animation::resetActiveGroups` passes
`animsrc->mAnimBlendRules` of the source becoming active. So a per-kf `.yaml` can
only shape transitions into its own clips. A `from: "stagger*" to: "*"` rule
there never fires, because idle and movement live in `xbase_anim.kf`.

Reaching the transition *out* of a stagger needs the global config, which is why
`Animations/animation-config.yaml` exists here - stock content plus one block,
`from: "stagger*"`. Staggers only: a fall holds its last frame and has no
recovery to blend, and `death*` would also have caught the engine's own
`death1`-`death5`, `deathknockdown` and `deathknockout`. Nothing in vanilla is
called `stagger*`, which is what makes that half safe to wildcard.
OpenMW's own copy tells mods not to do this, and the warning is fair: anything
else shipping that path conflicts, and the copy goes stale when the defaults
change. Deleting it reverts to the generic `sineOut 0.25`.
