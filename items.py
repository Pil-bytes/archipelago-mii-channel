from __future__ import annotations

from typing import Dict, NamedTuple

from BaseClasses import Item, ItemClassification

from .locks import item_copies

ITEM_ID_BASE = 90000000


class MiiChannelItem(Item):
    game = "Mii Channel Auto"


class ItemData(NamedTuple):
    code: int
    classification: ItemClassification


# Binary gating items: while you don't have one of these, the client
# actively reverts the matching Mii sub-field(s) back to a neutral value
# (see locks.py). Each category's "type" selector is either one of these
# (single-page categories, all-or-nothing) or a progressive line below
# (multi-page categories, unlocked one page at a time) -- color and
# movement (size/rotation/position) are always separate binary items,
# independent of whichever page(s) are unlocked for that category's type.
gating_item_names = [
    "Face Shape Tool",
    "Makeup Kit",
    "Skin Tone Palette",
    "Nose Editor",
    "Glasses Case",
    "Mole Marker",
    "Facial Hair Kit",
    "Eye Color",
    "Eye Movement",
    "Eyebrow Color",
    "Eyebrow Movement",
    "Hair Color",
    "Nose Movement",
    "Mouth Color",
    "Mouth Movement",
    "Glasses Color",
    "Glasses Movement",
    "Facial Hair Color",
    "Facial Hair Movement",
    "Mole Movement",
]

# Progressive gating items: every copy received (in any order, from
# anywhere in the multiworld) unlocks the NEXT page of that category's type
# grid, in order (0, then 1, then 2, ...) -- you can't unlock page 2 before
# page 1.
#
# Counts are the REAL page counts, read off the editor itself (2026-09-05):
# every grid holds 12 per page, and the screens show 1/4 for eyes (48
# types), 1/2 for eyebrows and mouths (24 each) and 1/6 for hair (72, split
# 3+3 between the Classic and Wild lines). Eyebrow and mouth used to carry 6
# copies each on the theory that an over-count was harmless -- it isn't: the
# extra 4 copies unlocked nothing and just read as fake progress.
progressive_item_counts: Dict[str, int] = {
    "Progressive Eye Editor": 4,
    "Progressive Eyebrow Editor": 2,
    "Progressive Mouth Editor": 2,
    "Progressive Hairstyle: Classic": 3,
    "Progressive Hairstyle: Wild": 3,
}

# Every item in gating_item_names now ships in GATING_ITEM_COPIES copies
# instead of one (see locks.py for what a partial unlock allows). This is
# the one lever that improves the useful-item-to-filler ratio: checks scale
# with target_count while the gating item list is fixed, so without it a
# multiworld gets flooded with this world's filler. Cutting checks finer
# would grow locations and items together and change nothing.
for name in gating_item_names:
    progressive_item_counts[name] = item_copies(name)

# A single, honestly-named filler. The flavour names this used to have
# ("Mii Outfit: Hawaiian Shirt", "Kazoo Cheek Sound", ...) read like they
# unlocked something, but nothing in the mod ever acted on them -- only the
# gating items in locks.py do anything. Calling it what it is stops the
# player (and anyone else in the multiworld) reading a received filler as
# progress.
filler_item_names = [
    "Nothing",
]

item_table: Dict[str, ItemData] = {
    name: ItemData(ITEM_ID_BASE + i, ItemClassification.progression)
    for i, name in enumerate(gating_item_names)
}

_next_id = ITEM_ID_BASE + len(gating_item_names)

# The gating items are already in item_table above; only the multi-page
# "Progressive ..." lines still need ids here.
for name in progressive_item_counts:
    if name in item_table:
        continue
    item_table[name] = ItemData(_next_id, ItemClassification.progression)
    _next_id += 1

for name in filler_item_names:
    item_table[name] = ItemData(_next_id, ItemClassification.filler)
    _next_id += 1

item_table["Golden Wii Remote"] = ItemData(_next_id, ItemClassification.useful)
_next_id += 1

item_table["Victory"] = ItemData(_next_id, ItemClassification.progression)
_next_id += 1

# Traps (2026-09-15). Their ids come after every existing item, so no id an
# older seed relies on moves. What each one does lives in traps.py; how
# many end up in the pool is the trap_percentage option plus one weight per
# trap (options.py).
TRAP_ITEMS = [
    "Quit Without Saving Trap",   # the editor closes and throws the edit away
    "Tool Jam Trap",              # an unlocked tool locks again for a while
    "Paint Spill Trap",           # a random colour on one of your Miis
    "Growth Spurt Trap",          # random height and weight on one of your Miis
    "Big Head Trap",              # every head balloons for a while
]
for name in TRAP_ITEMS:
    item_table[name] = ItemData(_next_id, ItemClassification.trap)
    _next_id += 1
