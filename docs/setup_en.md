# Mii Channel Auto Setup Guide (v0.3)

## What this is

An Archipelago world for the Wii **Mii Channel**, played in Dolphin. The
seed generates a few **target Miis**; you get checks by recreating them in
the Mii editor, category by category (face shape, eyes, eyebrows, nose,
mouth, glasses, mole, facial hair, hair, colours, body...). The editor's
tools are locked until you receive the matching items, and the lock is real:
Gecko code injected into the channel reverts a locked choice as you make it.

The client reads your Mii database (`RFL_DB.dat`) and sends checks by itself
as soon as a saved Mii matches. No clicking required.

## Required Software

- Archipelago 0.6.7+
- Dolphin with the Wii Mii Channel (`HACA`) installed in its NAND
- A **dedicated Dolphin user folder** is strongly recommended (the client
  writes the target Miis into that save; keep your real Miis elsewhere)

## Installation

1. Drop `mii_channel_auto.apworld` into Archipelago's `custom_worlds` folder
   and restart the Launcher.
2. Copy `gecko/HACA01.ini` from this repository into your Dolphin user
   folder's `GameSettings\` directory.
3. In Dolphin: *Config > General > Enable Cheats*. Then right-click the Mii
   Channel > Properties > Gecko Codes and check that the four "Mii Channel"
   / "Mii Editor" codes are ticked. Gecko codes load when the game boots, so
   restart the channel after changing them.
4. Generate a YAML for "Mii Channel Auto" and include it in your multiworld.

## Joining a MultiWorld Game

1. From the Launcher, start "Mii Channel Client" and connect.
2. The client finds `RFL_DB.dat` in the Dolphin user folder (use
   `/miipath C:\full\path\to\RFL_DB.dat` if it can't).
3. It writes the targets into the **Mii Parade**, then starts Dolphin on the
   Mii Channel by itself. Leave the client running while you play.

## How to play

- **See a target**: Parade button (top right of the Plaza). The targets are
  called "Target 1", "Target 2"...
- **Know what is left**: click the Wii Friend envelope, then grab one of your
  Miis (A+B) and drop it on the envelope. The list shows that Mii's target
  and every category:
  - grey-red: not unlocked yet
  - white: unlocked, you can do it now
  - blue: this check has been hinted
  - violet: what unlocks it has been hinted
  - green: check sent, still true on this Mii
  - orange: check sent, but no longer true on this Mii
- **Details / hints**: click a row. Locked rows say which item is missing
  (and where it is, if hinted) and offer a **Hint** button that sends
  `!hint <item>` for you. Sent rows show what the check gave and to whom.
- **Edit an existing Mii**: click Edit Mii, then grab the Mii and drop it on
  the Edit Mii button.
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

## Client commands

- `/targets` lists the targets and your progress; `/targets 3` prints target
  3's exact values.
- `/features` lists the client's switchable features and `/feature <name>
  on|off` toggles one (saved in the Dolphin user folder) -- useful to isolate
  a problem.
- `/miipath <path>` sets the save file manually.

## Troubleshooting

- **Nothing is checked**: the Mii Channel only writes `RFL_DB.dat` when it
  saves -- leave the editor with "Save and quit".
- **Envelope list empty or rows do nothing**: the Gecko codes aren't loaded.
  Check they are enabled and restart the channel. If you add codes of your
  own, keep the total small: Dolphin silently drops Gecko codes past ~3 KB.
- **Locks don't react after restarting Dolphin**: the client reconnects to
  the new Dolphin by itself within a few seconds; if not, restart the client.
- **Back up `RFL_DB.dat`** before a long session. The client edits it (target
  Miis in the Parade, reverting locked features) with correct checksums, but a
  backup costs nothing.
