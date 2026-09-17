# Mii Channel Auto Setup Guide (v1.0.2)

## What this is

An Archipelago world for the Wii **Mii Channel**, played in Dolphin. The
seed generates a few **target Miis**; you get checks by recreating them in
the Mii editor, category by category (face shape, eyes, eyebrows, nose,
mouth, glasses, mole, facial hair, hair, colours, body...). The editor's
tools are locked until you receive the matching items, and the lock is real:
Gecko code injected into the channel reverts a locked choice as you make it.

The client reads the Mii database of Mii Channel Archipelago (`RFL_AP.dat`) and sends checks by itself
as soon as a saved Mii matches. No clicking required.

## Required Software

- Archipelago 0.6.7+
- Dolphin with the Wii Mii Channel (`HACA`) installed in its NAND
- A **dedicated Dolphin user folder** is strongly recommended (the client
  writes the target Miis into that save; keep your real Miis elsewhere)

## Your Miis are safe

The Mii save (`RFL_DB.dat`) is shared by the whole Wii, and this client
rewrites the save it plays with constantly. So you don't play in the real Mii
Channel: the client installs **Mii Channel Archipelago** in your Dolphin, a
copy of the Mii Channel whose Mii save is a separate file (`RFL_AP.dat`).
Your Miis, your Mii Channel and every other game are left untouched.

Each Archipelago game has its own Mii save. Connecting to a new game parks
the previous game's save in `<Archipelago>/mii_channel_auto/saves` and starts
with an empty Plaza; connecting to that older game again brings its Miis back.
Close Dolphin before switching games: while it runs, the game keeps its own
copy of the save, so the client waits for you to close it and reconnect.

## Installation

1. Install the Mii Channel in Dolphin once, if it isn't there yet:
   *Tools > Perform Online System Update*, or install the Mii Channel WAD.
2. Drop `mii_channel_auto.apworld` into Archipelago's `custom_worlds` folder
   and restart the Launcher.
3. Fill in `docs/Mii Channel Auto.yaml` (every option is explained in it) and
   include it in your multiworld.

That's all: the modified channel, its Gecko codes and Dolphin's "Enable
Cheats" setting are installed by the client.

## Joining a MultiWorld Game

1. From the Launcher, start "Mii Channel Client" and connect.
2. The first time, it asks where `Dolphin.exe` is, then installs Mii Channel
   Archipelago into your Dolphin (a few seconds).
3. It writes the targets into the **Mii Parade**, then starts Dolphin on Mii
   Channel Archipelago by itself. Leave the client running while you play.
   Dolphin's game list only shows game files, never installed channels (the
   real Mii Channel isn't there either): start it from the client, or from
   *Tools > Load Wii System Menu*, where it is called "Mii Channel AP --
   Nintendo / Pil_Bandit". Its title id is `0001000248415058` ("HAPX").

Settings live in Archipelago's `host.yaml`, under `mii_channel_auto_options`:
`dolphin_path` (Dolphin.exe) and `dolphin_user_folder` (your Dolphin user
folder, the one holding `Wii`, `Config` and `GameSettings`; empty: found from
Dolphin.exe, portable installs included).

## How to play

- **In-game help**: the Plaza's "?" button explains all of this while the
  client is running.
- **See a target**: Parade button (top right of the Plaza). The targets are
  called "Target 1", "Target 2"...
- **Know what is left**: click the Wii Friend envelope, then grab one of your
  Miis (A+B) and drop it on the envelope. The list shows that Mii's target
  and every category:
  - grey-red: not unlocked yet
  - white: unlocked, you can do it now
  - dark blue: this check has been hinted and you can do it now (listed first)
  - blue: this check has been hinted, still locked
  - yellow: every copy still missing to unlock it has been hinted
  - green: check sent, still true on this Mii
  - orange: check sent, but no longer true on this Mii
- **Details / hints**: click a row. Locked rows say which item is missing
  (and where it is, if hinted) and offer a **Hint** button that sends
  `!hint <item>` for you. Sent rows show what the check gave and to whom.
- **Edit an existing Mii**: click Edit Mii, then grab the Mii and drop it on
  the Edit Mii button.
- **Look at a Mii**: click one in the Plaza or the Parade. Its head grows
  much bigger than in the original game, with its name under the chin, and
  the camera frames the face. The zoom buttons do nothing while a Mii is
  selected: deselect it to change the zoom.
- **Finished Miis**: a Mii that matches its whole target gets the favourite
  star. The star buttons are reserved for this, and a starred Mii can't be
  dropped on Edit Mii or Erase any more -- your finished work is safe. Only a
  Mutation trap can take the star away.
- **Transfers** between the Plaza and the Mii Parade are blocked (the Parade
  holds the targets).
- Each Mii works on one target at a time: the client pairs every Mii with
  the target it resembles most.

## Checks and goal

- Milestones: create your first Mii, 5, 10 and 20 Miis, use every face shape.
- For each target: one check per category matched exactly, one for the body
  (height and weight within 5), and "Perfect Copy" for a single Mii matching
  everything at once.
- No check is free: a target never shares a category with a brand-new Mii,
  and every target wears glasses, a mole and a moustache.
- **Where to start**: nothing locks a target's Favorite Color and Body, nor
  the "Create N Miis" milestones -- the first items are always there. Every
  other check is in logic once you own the items it needs (the envelope list
  shows exactly which).
- **Goal** ("Become a Mii Master"): complete every check of every target.

## Traps

`trap_percentage` (default 20) turns that share of the filler items into
traps; each trap has its own weight option (0 disables it):

- **Quit Without Saving**: the editor closes and your edit is lost (waits
  for the editor). It does not send a DeathLink.
- **Tool Jam**: one tool you already unlocked locks again for 60 seconds.
- **Lockdown**: every editor tool locks for 25 seconds (waits for the editor).
- **Blindfold**: the Mii you edit is invisible for 30 seconds (waits for the
  editor).
- **Paint Spill**: a random colour (hair, eyes, eyebrows, mouth, glasses,
  facial hair or favourite colour) lands on one of your Miis.
- **Growth Spurt**: one of your Miis gets a random height and weight.
- **Shuffle**: every value of one of your unfinished Miis is re-rolled among
  the values you can already pick.
- **Mutation**: one value of one of your Miis changes, finished Miis
  included; a finished Mii loses its star until you fix it. The client does
  not say what changed: your checks do.
- **Default**: one of your unfinished Miis becomes a blank Mii again.

A finished Mii is one that matches its target: it wears the favourite star,
which only the client gives (the game's star buttons are blocked). Traps
never touch the targets, and each one plays once: restarting the client does
not replay traps you already received. A trap that changes a Mii shows at
once on the Mii walking in the Plaza. The values are fully random, so a
Shuffle or a Mutation can also match a category by luck and send its check.

## DeathLink

With `death_link` on, "Quit without saving" becomes "Send DeathLink" and
skips its confirmation: leaving a Mii without saving kills everyone linked.
A death received while you edit a Mii throws you out of the editor without
saving; outside the editor it does nothing.

## Client commands

- `/targets` lists the targets and your progress; `/targets 3` prints target
  3's exact values.

## Troubleshooting

- **Nothing is checked**: the game only writes `RFL_AP.dat` when it
  saves -- leave the editor with "Save and quit".
- **Envelope list empty, rows do nothing, "?" shows the game's controls**:
  the Gecko codes aren't loaded, or the client isn't running. Check the
  codes are enabled and restart the channel. If you add codes of your own,
  keep the total small: Dolphin silently drops Gecko codes past ~3 KB.
- **No grey veils or padlocks in the editor, but items are still locked**:
  the MMU must be on for this channel. The client switches it on for you
  (Properties of the game, or `GameSettings/HAPX01.ini`, `[Core] MMU = True`);
  if you removed that line, put it back, or tick Config > Advanced > Enable
  MMU, and restart the channel.
- **Locks don't react after restarting Dolphin**: the client reconnects to
  the new Dolphin by itself within a few seconds; if not, restart the client.
- **Head zoom, name position or padlocks look like the original game**: those
  values are written by the client -- make sure it is connected.
- **"The Mii Channel is not installed in this Dolphin"**: install it (see
  Installation), or set `dolphin_user_folder` in host.yaml if your Dolphin
  keeps its data elsewhere.
- **Back up `RFL_AP.dat`** (Wii/shared2/menu/FaceLib in your Dolphin folder)
  before a long session. The client
  edits it (target Miis in the Parade, reverting locked features, traps) with
  correct checksums, but a backup costs nothing.
