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

from typing import Dict, List, Optional, Tuple

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
HAIR_PACK_PAGES = 3          # each pack is three editor pages = three copies
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
    if item_name in _PAGE_ITEM.values():
        # One copy per editor page (eye 4, eyebrow 2, mouth 2), exactly what
        # items.py puts in the pool. Counting their values instead asked for
        # 4 copies of the eyebrow/mouth editors when only 2 exist.
        field = next(f for f, i in _PAGE_ITEM.items() if i == item_name)
        return max(EDITOR_PAGE[field]) + 1

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


def palette_allowed_count(item_name: str, field_name: str, copies_owned: int) -> int:
    """How many non-default values of `field_name` are selectable with
    `copies_owned` copies of `item_name`.

    The real-time layer in the game needs this as a number: it compares the
    rank of the picked value (its position with the default taken out)
    against it, so both layers open exactly the same values at the same
    time. It used to receive 1 as soon as a single copy had arrived, which
    opened the whole palette in the editor and let the save-file layer take
    the colour back afterwards."""
    from .targets import FIELD_MAX

    total = item_copies(item_name)
    unlockable = FIELD_MAX.get(field_name, 1)
    if copies_owned >= total:
        return unlockable
    return _palette_allowed_count(
        unlockable, copies_owned, total, PALETTE_FIRST_STEP.get(item_name, 1)
    )


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

            if field_name in EDITOR_PAGE:
                # Page-gated grid: copy n opens page n-1, as in the editor.
                req = _editor_requirement(field_name, current)
                if req is not None and owned < req[1]:
                    violations[field_name] = default_value
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

    # Hair packs split by editor PAGE (pages 0-2 Classic, 3-5 Wild; copy n of
    # a pack opens its page n-1), the same rule as the in-editor ASM lock. The
    # old split by type id (0-35 / 36-71) disagreed with the editor.
    hair_req = _editor_requirement("hair_type", int(mii.hair_type))
    if hair_req is not None:
        pack, pack_needed = hair_req
        pack_owned = counts.get(pack, HAIR_PACK_PAGES if pack in unlocked_items else 0)
        if pack_owned < pack_needed:
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


_FIELD_ITEM: Dict[str, str] = {
    field: item for item, fields in ITEM_FIELD_LOCKS.items() for field in fields
}

# Editor page of every type id (display index // 12), read from the game's
# own page tables (main.dol 0x80207118 eye, 0x80207148 eyebrow, 0x802070d0
# hair, 0x80207170 mouth). The ASM layer unlocks PAGES in order -- copy n of a
# progressive item opens page n-1 -- and the mapping from type id to page is
# not linear, so the file layer's value-order check alone under-reports.
EDITOR_PAGE: Dict[str, List[int]] = {
    "eye_type": [0, 0, 0, 3, 0, 2, 2, 3, 0, 1, 3, 1, 1, 2, 3, 0, 0, 0, 2, 1, 0, 1, 3, 1,
                 2, 1, 0, 0, 2, 3, 2, 2, 1, 1, 1, 1, 2, 2, 3, 0, 1, 2, 3, 3, 3, 3, 2, 3],
    "eyebrow_type": [0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1],
    "mouth_type": [0, 0, 1, 1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 0, 0],
    "hair_type": [4, 3, 5, 4, 3, 3, 4, 3, 3, 5, 4, 4, 3, 3, 4, 5, 5, 4, 5, 3, 4, 4, 4, 2,
                  5, 3, 3, 3, 5, 5, 2, 0, 1, 0, 2, 4, 2, 1, 2, 0, 0, 2, 2, 2, 0, 0, 5, 1,
                  1, 0, 1, 0, 1, 5, 2, 1, 0, 2, 1, 0, 1, 5, 1, 4, 1, 2, 1, 2, 0, 3, 0, 5],
}
_PAGE_ITEM = {"eye_type": "Progressive Eye Editor", "eyebrow_type": "Progressive Eyebrow Editor",
              "mouth_type": "Progressive Mouth Editor"}


def _editor_requirement(field_name: str, value: int) -> Optional[Tuple[str, int]]:
    """(item, copies) the in-editor ASM layer needs to let `value` be picked.
    Hair pages 0-2 belong to the Classic pack, 3-5 to Wild -- by PAGE, which
    for some types disagrees with the file layer's split by type id
    (HAIRSTYLE_CLASSIC_MAX); both are reported, the player needs both."""
    pages = EDITOR_PAGE.get(field_name)
    if pages is None or not 0 <= value < len(pages):
        return None
    page = pages[value]
    if field_name == "hair_type":
        if value == HAIRSTYLE_DEFAULT_TYPE:
            return None
        return (HAIRSTYLE_CLASSIC_ITEM if page < 3 else HAIRSTYLE_WILD_ITEM), page % 3 + 1
    if value == ITEM_FIELD_LOCKS[_PAGE_ITEM[field_name]][field_name]:
        return None   # the default is always available
    return _PAGE_ITEM[field_name], page + 1


def _gating_item(field_name: str, value: int) -> Optional[str]:
    """The item that decides whether `field_name` may hold `value`."""
    if field_name == "hair_type":
        if value == HAIRSTYLE_DEFAULT_TYPE:
            return None
        req = _editor_requirement("hair_type", value)
        return req[0] if req else None
    if field_name == "hair_color":
        return HAIR_COLOR_ITEM
    if field_name == "hair_part_reversed":
        return HAIRSTYLE_CLASSIC_ITEM if value else None
    return _FIELD_ITEM.get(field_name)


# Value of every target field on a Mii made from scratch. Generation avoids
# these (a target category equal to them would be a free check).
FIELD_DEFAULTS: Dict[str, int] = {
    field: value for fields in ITEM_FIELD_LOCKS.values() for field, value in fields.items()
}
FIELD_DEFAULTS.update({
    "hair_type": HAIRSTYLE_DEFAULT_TYPE, "hair_color": HAIR_COLOR_DEFAULT,
    "hair_part_reversed": 0, "favorite_color": 0, "height": 64, "weight": 64,
})

# Fields the editor only lets you change (and only shows) once something is
# on the face: glasses size/colour need glasses, a mole must be placed to be
# moved, moustache size/position and facial hair colour need facial hair.
# Seen live 2026-09-11: "Glasses Movement" was reported doable on a Mii
# without glasses, and the size buttons did nothing.
CARRIER_FIELDS: Dict[str, Tuple[str, int]] = {
    "glasses_color": ("Glasses Case", 1), "glasses_size": ("Glasses Case", 1),
    "glasses_vert_pos": ("Glasses Case", 1),
    "mole_size": ("Mole Marker", 1), "mole_vert_pos": ("Mole Marker", 1),
    "mole_horiz_pos": ("Mole Marker", 1),
    "facial_hair_color": ("Facial Hair Kit", 1), "mustache_size": ("Facial Hair Kit", 1),
    "mustache_vert_pos": ("Facial Hair Kit", 1),
}


def _copies_for(item: str, field_name: str, value: int, default: int) -> int:
    """Fewest copies of `item` that let `field_name` hold `value` -- the
    same arithmetic find_violations uses, run forwards."""
    from .targets import FIELD_MAX, FIELD_MIN

    if value == default:
        return 0
    total = item_copies(item)
    field_max = FIELD_MAX.get(field_name, default)
    field_min = FIELD_MIN.get(field_name, 0)
    for n in range(1, total + 1):
        if item in SPREAD_ITEMS:
            if abs(value - default) <= _allowed_spread(field_min, field_max, default, n):
                return n
        elif _palette_allows(value, default, field_max, n, total, PALETTE_FIRST_STEP.get(item, 1)):
            return n
    return total


def field_needs(field_name: str, value: int) -> Dict[str, int]:
    """{item: copies} needed to give `field_name` the value `value`."""
    needs: Dict[str, int] = {}

    def need(item: str, n: int) -> None:
        if n > 0:
            needs[item] = max(needs.get(item, 0), n)

    if field_name in EDITOR_PAGE:              # eye/eyebrow/mouth/hair grids: by page
        req = _editor_requirement(field_name, value)
        if req is not None:
            need(*req)
    elif field_name == "hair_color":
        need(HAIR_COLOR_ITEM, _copies_for(HAIR_COLOR_ITEM, field_name, value, HAIR_COLOR_DEFAULT))
    elif field_name == "hair_part_reversed":
        if value:
            need(HAIRSTYLE_CLASSIC_ITEM, 1)
    elif field_name in _FIELD_ITEM:
        item = _FIELD_ITEM[field_name]
        need(item, _copies_for(item, field_name, value, ITEM_FIELD_LOCKS[item][field_name]))

    if field_name in CARRIER_FIELDS:
        need(*CARRIER_FIELDS[field_name])
    return needs


def category_needs(target: Dict[str, int], fields: List[str]) -> Dict[str, int]:
    """{item: copies} needed to match `target` on all of `fields` at once."""
    needs: Dict[str, int] = {}
    hair_pack = "hair_type" in fields and bool(field_needs("hair_type", int(target["hair_type"])))
    for field_name in fields:
        if field_name == "hair_part_reversed" and hair_pack:
            continue    # any hair pack allows flipping the part; the hairstyle already needs one
        for item, n in field_needs(field_name, int(target[field_name])).items():
            needs[item] = max(needs.get(item, 0), n)
    return needs


def requirements_for(
    mii: Mii,
    wanted: Dict[str, int],
    unlocked_items: set,
    item_counts: Dict[str, int],
) -> List[Tuple[str, int, int]]:
    """[(item, copies owned, copies needed)] still missing before `wanted`
    (field -> value) can be put on a Mii. Same computation as the world's
    access rules, so the envelope's colours agree with the generator."""
    return [
        (item, item_counts.get(item, 0), n)
        for item, n in category_needs(wanted, list(wanted)).items()
        if item_counts.get(item, 0) < n
    ]
