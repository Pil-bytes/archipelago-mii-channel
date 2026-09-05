"""
Maps each lockable Mii feature to the item that unlocks it, and the "neutral"
value the client reverts a field to when it's used without that item.

Each category's "type" selector (which face/hairstyle/etc. is picked) is
gated separately from its color and its movement (size/rotation/position)
sub-fields -- three independent unlocks per category where all three exist
(some categories have no color, e.g. nose; some have no movement, e.g. face
shape). Multi-page categories (eye, eyebrow, mouth, hairstyle) gate their
type selector with a PROGRESSIVE item (see items.py's
progressive_item_counts) instead of a single all-or-nothing item -- each
copy received unlocks the next page in order. The real-time page precision
for progressive categories lives in the ASM trampoline
(client.py/poll_asm_lock_bitmask); this file's save-file correction layer
only checks "has at least one copy been received at all" for a progressive
item's type field (coarser than the ASM layer's exact per-page check, but
consistent with how this layer has always been a ~1s fallback, not the
precise enforcement).

Default revert values were originally guessed as "a plain 0" for colors and
most rotation/position fields, but several turned out wrong -- confirmed
live (2026-09-02) against a genuinely from-scratch Mii created in a fully-
unlocked session (so nothing could have silently reverted it first):
hair_color's real default is 1 (not 0), eyebrow_color's is 1 (not 0),
eyebrow_rotation's is 6 (not 0), and eye_rotation's is 4 (not 0). Every
other field's assumed default (types, sizes, remaining positions) matched
the real game exactly. If a future field ever looks wrong the same way
(an untouched, freshly-created Mii getting "Blocked" messages despite the
player never touching that category), this is the class of bug to
suspect -- re-verify against a real, from-scratch Mii in a session with
everything already unlocked, not by guessing.
"""
from __future__ import annotations

from typing import Dict, Optional

from .mii_reader import Mii

# item_name -> {field_name: revert_value}
ITEM_FIELD_LOCKS: Dict[str, Dict[str, int]] = {
    "Face Shape Tool": {
        "face_shape": 0,
    },
    # The editor puts face shape and the makeup/marks on two separate tabs
    # of the same screen, and they have different option counts (8 vs 12),
    # so they unlock independently rather than sharing one item's steps.
    "Makeup Kit": {
        "facial_feature": 0,
    },
    "Skin Tone Palette": {
        "skin_color": 0,
    },
    "Progressive Eye Editor": {
        "eye_type": 2,
    },
    "Eye Color": {
        "eye_color": 0,
    },
    "Eye Movement": {
        "eye_rotation": 4,
        "eye_vert_pos": 12,
        "eye_size": 4,
        "eye_horiz_spacing": 2,
    },
    "Progressive Eyebrow Editor": {
        "eyebrow_type": 6,
    },
    "Eyebrow Color": {
        "eyebrow_color": 1,
    },
    "Eyebrow Movement": {
        "eyebrow_rotation": 6,
        "eyebrow_size": 4,
        "eyebrow_vert_pos": 10,
        "eyebrow_horiz_spacing": 2,
    },
    "Nose Editor": {
        "nose_type": 1,
    },
    "Nose Movement": {
        "nose_size": 4,
        "nose_vert_pos": 9,
    },
    "Progressive Mouth Editor": {
        "mouth_type": 23,
    },
    "Mouth Color": {
        "mouth_color": 0,
    },
    "Mouth Movement": {
        "mouth_size": 4,
        "mouth_vert_pos": 13,
    },
    "Glasses Case": {
        "glasses_type": 0,
    },
    "Glasses Color": {
        "glasses_color": 0,
    },
    "Glasses Movement": {
        "glasses_size": 4,
        "glasses_vert_pos": 10,
    },
    "Mole Marker": {
        "mole_enabled": 0,
    },
    "Mole Movement": {
        "mole_size": 4,
        "mole_vert_pos": 20,
        "mole_horiz_pos": 2,
    },
    "Facial Hair Kit": {
        "mustache_type": 0,
        "beard_type": 0,
    },
    "Facial Hair Color": {
        "facial_hair_color": 0,
    },
    "Facial Hair Movement": {
        "mustache_size": 4,
        "mustache_vert_pos": 10,
    },
}

HAIRSTYLE_CLASSIC_ITEM = "Progressive Hairstyle: Classic"
HAIRSTYLE_WILD_ITEM = "Progressive Hairstyle: Wild"
HAIRSTYLE_CLASSIC_MAX = 35  # hair_type 0-35 = classic pack, 36-71 = wild pack
HAIRSTYLE_DEFAULT_TYPE = 33  # user-picked "basic Mii" default, not 0
HAIR_COLOR_ITEM = "Hair Color"
HAIR_COLOR_DEFAULT = 1  # real in-game default (confirmed live 2026-09-02), not 0

# hair_part_reversed isn't meaningful without some hairstyle unlocked at
# all -- locked until the player owns at least one hair pack (coarse "any
# progress" check, same as every other progressive type field in this
# file). hair_color is its own separate unlock (HAIR_COLOR_ITEM), not
# bundled with the hairstyle packs.
HAIR_DETAIL_FIELDS: Dict[str, int] = {
    "hair_part_reversed": 0,
}

GATING_ITEM_NAMES = (
    list(ITEM_FIELD_LOCKS.keys())
    + [HAIRSTYLE_CLASSIC_ITEM, HAIRSTYLE_WILD_ITEM, HAIR_COLOR_ITEM]
)

# How many copies of each non-type gating item exist. Every item here used
# to be all-or-nothing, which made a huge share of the multiworld's item
# pool filler: checks scale with target count while useful items didn't
# scale at all. Splitting each into copies adds real items WITHOUT adding
# checks -- the only way the ratio improves, since cutting checks finer
# would just grow both sides together.
#
# It also plays better than a binary flag: control widens gradually instead
# of flipping from "forbidden" to "anything goes".
GATING_ITEM_COPIES = 3

# Two ways a partial unlock can widen:
#   "palette" -- values unlock in order from 0 (colours, single-page type
#                grids): copy c allows 0 .. ceil((max+1) * c / copies) - 1.
#   "spread"  -- the value may drift further from its default (sizes,
#                rotations, positions): copy c allows a deviation of
#                ceil(span * c / copies), where span is the larger distance
#                from the default to either end of the range.
PALETTE_ITEMS = {
    "Face Shape Tool", "Makeup Kit", "Skin Tone Palette", "Nose Editor",
    "Glasses Case", "Mole Marker", "Facial Hair Kit",
    "Eye Color", "Eyebrow Color", "Mouth Color", "Glasses Color",
    "Facial Hair Color", HAIR_COLOR_ITEM,
}
SPREAD_ITEMS = {
    "Eye Movement", "Eyebrow Movement", "Nose Movement", "Mouth Movement",
    "Glasses Movement", "Facial Hair Movement", "Mole Movement",
}


# Palette items get one more copy than movement ones, and their first copy
# deliberately hands over a single new value before the rest come two at a
# time (the user's shape: default, then +1, +2, +2, +2 across an 8-colour
# palette). Confirmed live that a field's value ids follow the editor's own
# swatch order left-to-right, top-to-bottom -- id 0 is the first swatch, 7
# the last on hair -- so unlocking in id order reads as the palette simply
# opening up, rather than colours appearing at random positions.
PALETTE_ITEM_COPIES = 4

# How many values the FIRST copy of a palette item is worth. One by default
# (a gentle opening step), but a field with a lot of choices can afford to
# start wider: the nose has 12 shapes, and starting at +2 makes its steps
# land on an even +2/+3/+3/+3 instead of +1/+3/+3/+4.
PALETTE_FIRST_STEP: Dict[str, int] = {
    "Nose Editor": 2,   # 12 shapes -> +2, +3, +3, +3
    "Makeup Kit": 2,    # 12 marks, same shape as the nose
}


def item_copies(item_name: str) -> int:
    """How many copies of `item_name` exist in the pool.

    Capped by how much there actually is to unlock: a field with only two
    or three values can't be opened in four meaningful steps, and a copy
    that widens nothing is a dead item the player is annoyed to receive
    (Mole Marker gates a single on/off field -- its first copy used to
    unlock literally nothing)."""
    from .targets import FIELD_MAX

    if item_name in SPREAD_ITEMS:
        return GATING_ITEM_COPIES

    fields = ITEM_FIELD_LOCKS.get(item_name) or {"hair_color": HAIR_COLOR_DEFAULT}
    # Values other than the default -- the default is never taken away, so
    # it is not part of what the copies hand out.
    unlockable = max(FIELD_MAX.get(field, 1) for field in fields)
    return max(1, min(PALETTE_ITEM_COPIES, unlockable))


def _palette_allowed_count(
    unlockable: int, copies_owned: int, copies_total: int, first_step: int = 1
) -> int:
    """How many non-default values `copies_owned` copies open up.

    The first copy is worth one value and the rest share what's left. The
    division rounds DOWN on purpose: when the remainder can't be spread
    evenly the extra values land on the last copies, so the steps only ever
    grow. Rounding up instead front-loads them, which gave Face Shape a
    lumpy +1, +4, +3, +3 instead of +1, +3, +3, +4."""
    if copies_owned <= 0:
        return 0
    if copies_owned >= copies_total or copies_total == 1:
        return unlockable
    first = min(first_step, unlockable)
    return first + (unlockable - first) * (copies_owned - 1) // (copies_total - 1)


def _palette_allows(
    value: int, default: int, field_max: int, copies_owned: int,
    copies_total: int, first_step: int = 1,
) -> bool:
    """Is `value` selectable with `copies_owned` copies?

    The field's default is always available -- the player starts with it and
    taking it away would break Miis they never touched -- so it is excluded
    from the sequence being unlocked. Counting it in (the first version of
    this did) makes the steps uneven: on a field whose default sits in the
    middle of the range, one copy would hand over fewer genuinely new
    choices than the next. Here every copy is worth the same number of new
    values."""
    if value == default:
        return True
    if copies_owned <= 0:
        return False
    if copies_owned >= copies_total:
        return True

    unlockable = field_max  # every value except the default
    rank = value if value < default else value - 1
    return rank < _palette_allowed_count(unlockable, copies_owned, copies_total, first_step)


def _allowed_spread(field_min: int, field_max: int, default: int, copies_owned: int) -> int:
    """How far from `default` the field may move with `copies_owned` copies."""
    span = max(field_max - default, default - field_min)
    if copies_owned <= 0:
        return 0
    if copies_owned >= GATING_ITEM_COPIES:
        return span
    return -(-span * copies_owned // GATING_ITEM_COPIES)


def find_violations(
    mii: Mii,
    unlocked_items: set,
    item_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """Return {field_name: value_to_revert_to} for every locked feature this
    Mii is using.

    `item_counts` gives how many copies of each item have been received, so
    a partially-unlocked field can be clamped to the part of its range the
    player has actually earned rather than reverted outright. Without it,
    membership in `unlocked_items` is treated as a full unlock (which is
    what the coarser real-time ASM layer does -- see module docstring)."""
    from .targets import FIELD_MAX, FIELD_MIN

    counts = item_counts or {}
    violations: Dict[str, int] = {}

    for item_name, fields in ITEM_FIELD_LOCKS.items():
        total = item_copies(item_name)
        owned = counts.get(item_name, total if item_name in unlocked_items else 0)
        if owned >= total:
            continue

        for field_name, default_value in fields.items():
            current = getattr(mii, field_name)
            current = int(current) if isinstance(current, bool) else current
            if current == default_value:
                continue

            field_max = FIELD_MAX.get(field_name, default_value)
            field_min = FIELD_MIN.get(field_name, 0)

            if item_name in SPREAD_ITEMS:
                if abs(current - default_value) > _allowed_spread(
                    field_min, field_max, default_value, owned
                ):
                    violations[field_name] = default_value
            elif not _palette_allows(
                current, default_value, field_max, owned, total,
                PALETTE_FIRST_STEP.get(item_name, 1),
            ):
                violations[field_name] = default_value

    if mii.hair_type > HAIRSTYLE_CLASSIC_MAX:
        if HAIRSTYLE_WILD_ITEM not in unlocked_items:
            violations["hair_type"] = HAIRSTYLE_DEFAULT_TYPE
    elif mii.hair_type != HAIRSTYLE_DEFAULT_TYPE:
        if HAIRSTYLE_CLASSIC_ITEM not in unlocked_items:
            violations["hair_type"] = HAIRSTYLE_DEFAULT_TYPE

    if HAIRSTYLE_CLASSIC_ITEM not in unlocked_items and HAIRSTYLE_WILD_ITEM not in unlocked_items:
        for field_name, default_value in HAIR_DETAIL_FIELDS.items():
            current = getattr(mii, field_name)
            current = int(current) if isinstance(current, bool) else current
            if current != default_value:
                violations[field_name] = default_value

    hair_total = item_copies(HAIR_COLOR_ITEM)
    hair_color_owned = counts.get(
        HAIR_COLOR_ITEM, hair_total if HAIR_COLOR_ITEM in unlocked_items else 0
    )
    if not _palette_allows(
        mii.hair_color, HAIR_COLOR_DEFAULT, FIELD_MAX["hair_color"], hair_color_owned, hair_total
    ):
        violations["hair_color"] = HAIR_COLOR_DEFAULT

    return violations
