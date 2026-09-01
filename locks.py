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

Default revert values for size/position/rotation fields use the documented
WiiBrew defaults where known (a plain 0 would look like an extreme slider
position rather than "centered"); colors and types default to 0.
"""
from __future__ import annotations

from typing import Dict

from .mii_reader import Mii

# item_name -> {field_name: revert_value}
ITEM_FIELD_LOCKS: Dict[str, Dict[str, int]] = {
    "Face Shape Tool": {
        "face_shape": 0,
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
        "eye_rotation": 0,
        "eye_vert_pos": 12,
        "eye_size": 4,
        "eye_horiz_spacing": 2,
    },
    "Progressive Eyebrow Editor": {
        "eyebrow_type": 6,
    },
    "Eyebrow Color": {
        "eyebrow_color": 0,
    },
    "Eyebrow Movement": {
        "eyebrow_rotation": 0,
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


def find_violations(mii: Mii, unlocked_items: set) -> Dict[str, int]:
    """Return {field_name: value_to_revert_to} for every locked feature this
    Mii is using. `unlocked_items` must already include a progressive item's
    name if at least one copy of it has been received (coarse "any progress"
    check -- see module docstring)."""
    violations: Dict[str, int] = {}

    for item_name, fields in ITEM_FIELD_LOCKS.items():
        if item_name in unlocked_items:
            continue
        for field_name, default_value in fields.items():
            current = getattr(mii, field_name)
            current = int(current) if isinstance(current, bool) else current
            if current != default_value:
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

    if HAIR_COLOR_ITEM not in unlocked_items and mii.hair_color != 0:
        violations["hair_color"] = 0

    return violations
