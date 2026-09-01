# Mii Channel Auto Setup Guide

## What this is

Unlike the Manual version, this world has a real client. It reads your actual
Mii database file (`RFL_DB.dat`) -- the same file the Wii Mii Channel itself
writes to -- and automatically sends location checks the moment it notices
you've done the corresponding thing. No clicking required.

## Required Software

- Archipelago (you already have this)
- Dolphin, with a Wii Mii Channel save, OR a real softmodded Wii with an
  accessible NAND/SD backup

## Installation

1. Drop `mii_channel_auto.apworld` into your Archipelago `custom_worlds` folder.
2. Restart the Archipelago Launcher.
3. Generate a YAML for "Mii Channel Auto" and include it in your multiworld.

## Joining a MultiWorld Game

1. From the Launcher, click "Mii Channel Client" (or run it from the command
   line with a `archipelago://` connect URL).
2. It auto-detects `RFL_DB.dat` in the default Dolphin user folder
   (`%APPDATA%\Dolphin Emulator\Wii\shared2\menu\FaceLib\RFL_DB.dat` on
   Windows, `~/.local/share/dolphin-emu/...` or `~/.dolphin-emu/...` on
   Linux, `~/Library/Application Support/Dolphin/...` on macOS).
3. If it can't find it (portable Dolphin install, real Wii SD card, custom
   path), set it manually with `/miipath C:\full\path\to\RFL_DB.dat`.
4. Play the Mii Channel normally -- create Miis, give them glasses, moles,
   facial hair, different face shapes, etc. Every few seconds the client
   re-reads the file and checks off anything newly true.

## The Goal

"Become a Mii Master": have at least as many Miis as your `miis_required`
option (default 10), covering all 8 face shapes, with at least one Mii
wearing glasses, one with a mole, and one with a mustache or beard.

## Restrictions are enforced, not just tracked

Eleven items (Face Shape Tool, Skin Tone Palette, Eye/Eyebrow/Nose/Mouth
Editor, Glasses Case, Mole Marker, Facial Hair Kit, and the two Hairstyle
Packs) gate the matching Mii feature. If you use a feature before receiving
its item, the client actively reverts it in `RFL_DB.dat` on its next poll (a
few seconds later) and logs a warning -- it isn't just an honor-system
checklist like the Manual version.

**Read this before relying on it:**
- The revert is a **targeted patch of just the 2-4 bytes** for that one
  feature -- it never touches the rest of the Mii or any other Mii.
- It does **not** recompute the file's trailing CRC16 checksum (the exact
  algorithm Nintendo uses isn't reliably documented, and writing a wrong one
  is worse than leaving it stale). In testing, Dolphin didn't seem to
  strictly validate this checksum, but this hasn't been checked against real
  Wii hardware.
- Because Dolphin can hold this file open while running, there's a small
  window where your edit and the client's revert can race. If a revert
  doesn't stick immediately, the next poll (~3s later) will catch it.
- **Back up `RFL_DB.dat` before playing a season with this on.** If anything
  looks wrong, restore the backup.

If you'd rather not have your save file edited at all, use the Manual world
instead, or ask for a build with this feature disabled.

## Game Troubleshooting

- Nothing is being checked: make sure the client found your `RFL_DB.dat`
  (check the log on connect) and that you've actually saved changes in the
  Mii Channel (Dolphin only writes the file back to disk when the channel
  saves, not on every edit).
- Wrong file found: use `/miipath` to point at the correct one directly.
