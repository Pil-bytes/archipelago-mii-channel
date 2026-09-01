from __future__ import annotations

from typing import Dict, NamedTuple

from BaseClasses import Item, ItemClassification

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
# page 1. Value is how many copies are placed in the pool; safely generous
# for eye/eyebrow/mouth since a page count higher than the real one is
# harmless (the trampoline never tests a bit past the real max), while a
# count that's too LOW would permanently strand pages nothing could ever
# unlock -- eye's page count (4) is the only one directly confirmed live,
# the rest use the same generous margin.
progressive_item_counts: Dict[str, int] = {
    "Progressive Eye Editor": 4,
    "Progressive Eyebrow Editor": 6,
    "Progressive Mouth Editor": 6,
    "Progressive Hairstyle: Classic": 3,
    "Progressive Hairstyle: Wild": 3,
}

filler_item_names = [
    "Mii Outfit: Hawaiian Shirt",
    "Sticker: Star",
    "Sticker: Heart",
    "Kazoo Cheek Sound",
    "Spare Mii Part",
]

item_table: Dict[str, ItemData] = {
    name: ItemData(ITEM_ID_BASE + i, ItemClassification.progression)
    for i, name in enumerate(gating_item_names)
}

_next_id = ITEM_ID_BASE + len(gating_item_names)

for name in progressive_item_counts:
    item_table[name] = ItemData(_next_id, ItemClassification.progression)
    _next_id += 1

for name in filler_item_names:
    item_table[name] = ItemData(_next_id, ItemClassification.filler)
    _next_id += 1

item_table["Golden Wii Remote"] = ItemData(_next_id, ItemClassification.useful)
_next_id += 1

item_table["Victory"] = ItemData(_next_id, ItemClassification.progression)
