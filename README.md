# Mii Channel Auto — an Archipelago world for the Wii Mii Channel

Recreate target Miis in the **Wii Mii Channel** (played in [Dolphin](https://dolphin-emu.org/))
while the editor's tools are unlocked by items from the rest of the
[Archipelago](https://archipelago.gg/) multiworld.

Every seed generates a few **target Miis**. They wait for you in the Mii Parade,
and each part you match — face shape, eyes, eyebrows, nose, mouth, glasses,
mole, facial hair, hairstyle, colours, height and weight — is a check. Matching a
whole target is a "Perfect Copy"; completing every target wins the game.

## Features

- **Real in-game locks.** Locked tools stay locked *inside* the editor: grey
  veils and padlocks cover what you don't have yet, and a locked choice is
  refused as you make it. Unlocks are progressive (one editor page, one pack
  of colours at a time).
- **In-game checklist.** Drop a Mii on the Wii Friend envelope to list what it
  still has to match, coloured by logic, sent and hinted state. Click a row for
  details, where the missing items are, and a **Hint** button.
- **Checks sent automatically** by the client as you save your Miis.
- **Traps**: Quit Without Saving, Tool Jam, Lockdown, Blindfold, Paint Spill,
  Growth Spurt, Shuffle, Mutation and Default — each with its own weight.
- **DeathLink**: leaving a Mii without saving sends a death; receiving one
  throws you out of the editor.
- **Quality of life**: a much bigger head when you select a Mii, finished
  Miis protected (their favourite star is earned, and they can't be edited or
  erased), Plaza/Parade transfers blocked.

## Your Miis are safe

The client never plays in your Mii Channel. It installs **Mii Channel
Archipelago** in your Dolphin: a copy of the Mii Channel with a Mii save of its
own (`RFL_AP.dat`). Your Miis, your Mii Channel and your other games are never
touched, and each Archipelago game keeps its own save.

## Requirements

- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases) 0.6.7 or newer
- Dolphin (a recent build) with the **Mii Channel** installed:
  *Tools > Perform Online System Update*, or install the Mii Channel WAD.
  (Windows is the tested platform.)

## Quick start

1. Download `mii_channel_auto.apworld` from the
   [latest release](https://github.com/Pil-bytes/archipelago-mii-channel/releases/latest)
   and drop it into Archipelago's `custom_worlds` folder.
2. Download `Mii Channel Auto.yaml` from the release, fill it in (every
   option is explained) and add it to your multiworld.
3. In the Archipelago Launcher, open **Mii Channel Client** and connect.
   The first time it asks where `Dolphin.exe` is, installs Mii Channel
   Archipelago and starts Dolphin on it.

The full guide — how to play, colours, traps, DeathLink, client commands,
troubleshooting — is in [docs/setup_en.md](docs/setup_en.md).

## Credits

- World, client and game patches: **Pil_Bandit**
- The Mii Channel is © Nintendo. This project contains no Nintendo code or
  data: it patches the copy of the channel already installed in your Dolphin.
