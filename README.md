![](https://i.imgur.com/CBAElYb.png)
![](https://i.imgur.com/YYFfIlT.png)

**v2 Introduces more stagger and death animations, fake ragdolls of a kind, its a lot and its very cool, you can see some of it in action in the video below**

<!-- nexus-raw: [youtube]GPr29jKNFYI[/youtube] -->

## 💃 GIFs GIFs GIFs

![](https://staticdelivery.nexusmods.com/mods/100/images/56594/56594-1747158023-1855299359.gif)![](https://staticdelivery.nexusmods.com/mods/100/images/56594/56594-1747158008-631610966.gif)

[![](img/kofi-left.webp)![](img/kofi-right.png)](https://ko-fi.com/maxyari)
[![](img/kofi-glow.png)](https://ko-fi.com/maxyari)

## 💃 Installation

* Install the dependency [Max Yari's Script Services (MSS)](https://www.nexusmods.com/morrowind/mods/60256) (Most of my lua mods require it now, should come BEFORE all my mods in the load order, you can just move it at the very top of your list, no harm in that).
* Install this mod **With a mod organiser**: Download this repository as an archive and drag and drop it into your mod organiser of choice (e.g [Mod Organizer 2](https://github.com/ModOrganizer2/modorganizer/releases) on Windows or [Nerevarine Organizer](https://github.com/grazelandsnomad/nerevarine_organizer/releases/tag/v0.70) on Linux). **Or**: [read this tutorial](https://modding-openmw.com/tips/installing-mods/) on how to install mods using the launcher or completely manually (it's also very easy).
* Enable the mod's .omwscript file in "Content Files" tab of the OpenMW launcher.

---

Thanks to folks in OpenMW discord for supporting my shenanigans and helping when OpenMW lua docs give up on being understandable.

Hit them hard!

<!-- nexus-skip-start -->

## What is in the pool

33 clips, simulated in endorphin and retargeted onto the Morrowind skeleton.
Each is cut for one job, and the two jobs do not share clips: a stagger ends with
the character still on their feet, a fall ends on the floor.

Directions are from the **viewer's** side, the way the clips are named - a player
looking at the character they hit.

* **11 staggers** - 2 back, 4 to the left (one of them a long one), 5 to the
  right (one long). Nothing forward yet.
* **22 falls** - 3 forward (2 long), 8 back (2 long), 6 left (1 long), 5 right
  (1 long).

Four of the staggers are mirrors of others, which is how both sides ended up
with the same repertoire including a long fall. Nothing travels forward yet.

<details><summary>Every clip</summary>

| group | | throws them | length | |
|---|---|---|---|---|
| `staggerback` | stagger | back | 1.77 s |  |
| `staggerstumblerightback` | stagger | back | 1.52 s |  |
| `staggerlongleft` | stagger | left | 1.32 s | **far** |
| `staggerstumblehopleft2` | stagger | left | 1.32 s |  |
| `staggerstumbleleft2` | stagger | left | 1.17 s |  |
| `staggerstumbleleft2m` | stagger | left | 1.18 s |  |
| `staggerlongright` | stagger | right | 1.32 s | **far** |
| `staggerstumbleback` | stagger | right | 1.08 s |  |
| `staggerstumblehopright2` | stagger | right | 1.32 s |  |
| `staggerstumbleright2` | stagger | right | 1.18 s |  |
| `staggerstumbleright2m` | stagger | right | 1.17 s |  |
| `deathback` | fall | back | 2.75 s |  |
| `deathback1` | fall | back | 2.68 s |  |
| `deathback2` | fall | back | 2.65 s |  |
| `deathbackfar` | fall | back | 2.85 s | **far** |
| `deathbackfarflip` | fall | back | 2.48 s | **far** |
| `deathbackhigh` | fall | back | 2.93 s |  |
| `deathbackhighface` | fall | back | 4.70 s |  |
| `deathstepback` | fall | back | 2.45 s |  |
| `deathforward` | fall | forward | 2.53 s |  |
| `deathforwardflipfar` | fall | forward | 3.25 s | **far** |
| `deathlongforward` | fall | forward | 4.50 s | **far** |
| `deathdownleft` | fall | left | 1.97 s |  |
| `deathdownleft1` | fall | left | 2.77 s |  |
| `deathdownleft2` | fall | left | 1.48 s |  |
| `deathleftfar` | fall | left | 1.43 s | **far** |
| `deathstepleft` | fall | left | 2.37 s |  |
| `deathwalkleft` | fall | left | 2.88 s |  |
| `deathdown` | fall | right | 2.92 s |  |
| `deathdownright` | fall | right | 1.33 s |  |
| `deathdownright2` | fall | right | 2.52 s |  |
| `deathright` | fall | right | 3.55 s |  |
| `deathrightfar` | fall | right | 2.83 s | **far** |

</details>

## Settings

In-game: Options -> Scripts -> Hit Reactions Animated. Two groups on one page.

**General** - the flinches:

* **Intensity** (1.0) - how much of the flinch plays per hit. 1.0 plays all of
  it, 0.1 starts it almost at its end.

**Staggers and deaths:**

* **Staggers** (on) - replace `hit1`-`hit5`.
* **Deaths** (on) - replace `death1`-`death5`, `deathknockdown`, `deathknockout`.
* **Custom staggers, forward and back** (75%) - how often a stagger that throws
  them forwards or backwards uses one of these clips.
* **Custom staggers, sideways** (50%) - the same, for one that throws them to a
  side. Lower because it departs further from what the engine would have done.
* **Custom deaths** (90%) - the same, for deaths.
* **Match the attack** (on) - pick a clip that goes the way the blow pushes.
* **Long falls for heavy blows** (on) - throw them further the harder they were
  hit, measured against their own maximum health.
* **Keep the weapon arms steady** (on) - stagger the body but leave the arms to
  their guard.
* **Log hits and staggers** (off) - diagnostic. Writes what each hit was read as,
  and how its clip fared, to `openmw.log`.

## How often a clip is used at all

The clip is **drawn first**, then rolled against a chance that depends on what
was drawn - which is the only order that lets the chance depend on the direction:

* a long fall - **always**
* a sideways stagger - 50%
* a forward or backward stagger - 75%
* a death - 90%

Lose the roll and the mod simply does not touch the animation, so the engine
plays its own and vanilla reactions stay in the mix.

A long fall is never declined. It was drawn because the blow was heavy enough to
earn it, and trading it for a vanilla twitch afterwards would undo the one thing
it was picked for.

The roll happens once per **reaction**, not once per blow: a hit landing while a
clip is still running continues it rather than re-rolling.

## Keeping the guard

*Keep the weapon arms steady* plays the clip on the lower body and torso only.
The character is thrown about while still holding their guard; the arms travel
with the chest, because they hang off it, but their own pose stays put.

The arms are not left empty. The engine's own hit reaction is given exactly the
bone groups our clip is not driving - the bone groups are bit flags, so this is
just `All` minus ours - instead of being hidden outright. What that means depends
on what is in hand:

* **Weapon drawn:** nothing changes. The weapon animation holds priority Weapon
  (7) on the arms and a hit reaction is Hit (6), so the guard still wins. That is
  vanilla's behaviour, and the reason vanilla hit reactions are a lower-body
  twitch whenever a weapon is out.
* **Nothing drawn:** there is no Weapon-priority animation, so the arms play the
  real vanilla flinch rather than carrying on with the idle or running arm swing.

It applies to staggers alone. A character being killed should let go, not hold
form, so a fall always takes the whole body and the engine's animation is hidden
completely.

## Known rough edges

* **Knockdowns and knockouts are left to the engine.** The collection has
  staggers and deaths in it and nothing else. A knockdown ends with the character
  getting back up, and the nearest thing here is a death clip, which ends with
  them lying still - so they dropped, held the pose, then snapped upright the
  moment the engine took the body back. `deathknockdown` and `deathknockout` are
  replaced, because those are deaths.
* **Nothing travels forward.** A blow from behind gets the nearest sideways
  clip instead. Mirroring cannot fix it - it swaps left for right and leaves
  forward and back alone - so that gap needs a clip of its own.
* **Beast races.** `Animations/xbase_animkna/` is a straight copy of the human
  clips. Khajiit and Argonians are digitigrade, so their legs will bend wrong.
  Delete that folder to leave beast races on vanilla animations, or retarget the
  clips properly with the addon's Transfer to Beasts.
* **First person** is untouched; the clips are only in the third-person
  skeleton's folders, and the override bails out when the group is not loaded.
* **Swimming** hit and death groups (`swimhit`, `swimdeath`, ...) are left
  alone. These clips fall to a floor.
* **The second batch opens slightly crouched.** `2_Death_*` and `2_Stumble_*`
  start with the pelvis at 68-70 Morrowind units where the first batch stands at
  76.7 and the vanilla idle sits at 76.369, so the character dips about 8 units
  as the clip blends in. That is the pose the simulation was actually in, not a
  retarget error - the scale is taken from leg length precisely so it is not
  silently flattened out. It reads as a small flinch; re-simulating those clips
  from a standing start is the fix if it bothers you.

## Gear coming off a corpse

This used to live here - the weapon thrown out of a dying character's hands,
the helmet knocked off, worn gear and inventory scattered with LuaPhysics. It
has moved to **Combat Juice**, where each of those has its own chance. Settings
tuned here do not carry over.

## Credits

Animations simulated in endorphin and retargeted onto the Morrowind skeleton.
Rig and export toolchain from [ReAnimation](https://www.nexusmods.com/morrowind/mods/52596)
and Bizarre Morrowind Anim Utils.

## Building from source

`docs/development.md` covers how the mod is put together, and
`Sources/RETARGETING.md` is the reference for the animation pipeline. Neither is
needed to play it.

```
luajit Sources/tests/test_direction_math.lua      # the vector maths
luajit Sources/tests/test_attack_directions.lua   # swing -> bearing -> clip, end to end
luajit Sources/tests/test_clip_selection.lua      # which clips a given push chooses
luajit Sources/tests/test_no_repeat.lua           # the no-repeat rule and its fallbacks
bash tools/build_nexus_zip.sh                     # pack what Nexus gets
```

<!-- nexus-skip-end -->
