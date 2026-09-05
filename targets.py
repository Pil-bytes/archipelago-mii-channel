"""
Target Mii "recipes" for the recreate-the-target goal.

The world generates a fixed number of random target Miis deterministically
from the AP seed (see generate_targets, called once from World.generate_early
and sent to the client via slot_data -- never regenerated, so it stays stable
across reconnects). The client then checks, per target and per face-part
category, whether any of the player's real Miis matches that category's
fields exactly.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from .mii_reader import Mii

# Grouping of Mii dataclass fields into checkable categories. Each one
# matches only when EVERY field in it matches exactly -- no partial credit
# inside a group -- so the groups are deliberately cut the same way the
# UNLOCK ITEMS are (see locks.ITEM_FIELD_LOCKS): a part's type, its colour
# and its movement (size/rotation/position) are separate checks because they
# are separate items.
#
# Grouping them per face part instead (one "Eyes" check covering type +
# colour + movement) is what the mod did first, and it played badly: the
# check stayed unreachable until all three items had arrived, so a player
# holding the eye editor but not Eye Movement could see the right eyes on
# screen and still get no credit, with nothing telling them which sub-part
# was wrong. One check per item keeps every owned item immediately useful
# and makes the remaining work legible.
CATEGORY_FIELDS: Dict[str, List[str]] = {
    "Face Shape": ["face_shape"],
    "Makeup": ["facial_feature"],
    "Skin Tone": ["skin_color"],
    "Eye Type": ["eye_type"],
    "Eye Color": ["eye_color"],
    "Eye Movement": ["eye_rotation", "eye_vert_pos", "eye_size", "eye_horiz_spacing"],
    "Eyebrow Type": ["eyebrow_type"],
    "Eyebrow Color": ["eyebrow_color"],
    "Eyebrow Movement": ["eyebrow_rotation", "eyebrow_size", "eyebrow_vert_pos", "eyebrow_horiz_spacing"],
    "Nose Type": ["nose_type"],
    "Nose Movement": ["nose_size", "nose_vert_pos"],
    "Mouth Type": ["mouth_type"],
    "Mouth Color": ["mouth_color"],
    "Mouth Movement": ["mouth_size", "mouth_vert_pos"],
    "Glasses Type": ["glasses_type"],
    "Glasses Color": ["glasses_color"],
    "Glasses Movement": ["glasses_size", "glasses_vert_pos"],
    "Mole": ["mole_enabled"],
    "Mole Movement": ["mole_size", "mole_vert_pos", "mole_horiz_pos"],
    "Facial Hair Type": ["mustache_type", "beard_type"],
    "Facial Hair Color": ["facial_hair_color"],
    "Facial Hair Movement": ["mustache_size", "mustache_vert_pos"],
    "Hairstyle": ["hair_type", "hair_part_reversed"],
    "Hair Color": ["hair_color"],
    "Favorite Color": ["favorite_color"],
}
CATEGORY_NAMES: List[str] = list(CATEGORY_FIELDS.keys())
BODY_FIELDS: List[str] = ["height", "weight"]

ALL_TARGET_FIELDS: List[str] = [f for fields in CATEGORY_FIELDS.values() for f in fields] + BODY_FIELDS

# Inclusive max value for each field when generating a target. These are the
# real in-game option counts (the number of choices in each editor page/
# slider), which are in several cases *tighter* than the raw bitfield width
# in mii_reader.FIELD_SPECS (e.g. eye_type's field is 6 bits wide / 0-63, but
# only values 0-47 are real selectable eyes -- see EYE_PAGE_COUNT in
# client.py).
#
# VERIFIED AGAINST THE GAME (2026-09-05), no longer guesses: one Mii per
# field was written at its claimed maximum and the game was asked to display
# them. It silently refuses to load an entry holding a value it considers
# out of range, so anything that failed to appear had a ceiling that was too
# high -- and a value the game rejects is also one the player could never
# pick in the editor, i.e. a target impossible to complete. Exactly two were
# wrong: mouth_color (3 -> 2) and glasses_type (9 -> 8). Every other entry
# below was confirmed correct at its stated maximum.
#
# Re-run that sweep (scratchpad max_test.py) rather than reasoning from
# menus if this table is ever extended.
FIELD_MAX: Dict[str, int] = {
    "face_shape": 7,
    "skin_color": 5,
    "facial_feature": 11,
    "hair_type": 71,
    "hair_color": 7,
    "hair_part_reversed": 1,
    "eyebrow_type": 23,
    "eyebrow_rotation": 11,
    "eyebrow_color": 7,
    "eyebrow_size": 8,
    "eyebrow_vert_pos": 18,
    "eyebrow_horiz_spacing": 12,
    "eye_type": 47,
    "eye_rotation": 7,
    "eye_vert_pos": 18,
    "eye_color": 5,
    "eye_size": 7,
    "eye_horiz_spacing": 12,
    "nose_type": 11,
    "nose_size": 8,
    "nose_vert_pos": 18,
    "mouth_type": 23,
    "mouth_color": 2,  # 2-bit field, but the game refuses 3
    "mouth_size": 8,
    "mouth_vert_pos": 18,
    "glasses_type": 8,  # 9 choices counting "none"
    "glasses_color": 5,
    "glasses_size": 7,
    "glasses_vert_pos": 20,
    "mustache_type": 3,
    "beard_type": 3,
    "facial_hair_color": 7,
    "mustache_size": 8,
    "mustache_vert_pos": 16,
    "mole_enabled": 1,
    "mole_size": 8,
    "mole_vert_pos": 30,
    "mole_horiz_pos": 16,
    "height": 127,
    "weight": 127,
    # Standard Wii Mii favorite-color palette: Red, Orange, Yellow, Light
    # Green, Green, Blue, Light Blue, Pink, Purple, Brown, White, Black --
    # 12 colors, 0-11. Believed-correct like every other entry in this
    # table; check here first if a generated target's color ever looks
    # impossible to pick in the editor.
    "favorite_color": 11,
}

# Inclusive MINIMUM for the few fields that don't start at 0. Generation
# assumed 0 was legal everywhere, which is true of every field except one:
# verified the same way as FIELD_MAX (2026-09-05), by writing one Mii per
# field at 0 and at 1 and seeing which the game refused. Only
# eyebrow_vert_pos failed, and a follow-up sweep put its floor at 3 --
# values 0, 1 and 2 are all rejected. Two of five generated targets were
# unusable because of this.
FIELD_MIN: Dict[str, int] = {
    "eyebrow_vert_pos": 3,
}

# Neutral values used to clamp mole sub-fields when a generated target has
# mole_enabled=0, matching the in-game editor's own default slider positions
# for a mole that isn't placed (same values locks.py reverts to).
_MOLE_DEFAULTS = {"mole_size": 4, "mole_vert_pos": 20, "mole_horiz_pos": 2}


def generate_targets(rng: random.Random, count: int) -> List[Dict[str, int]]:
    """Deterministically generate `count` target Mii recipes using `rng`
    (pass the World's own self.random for AP-seed determinism). Each recipe
    is {field_name: value} covering every field in ALL_TARGET_FIELDS. Must
    only be called once per world generation -- the result is sent to the
    client via slot_data and has to stay frozen for the whole seed."""
    targets: List[Dict[str, int]] = []
    for _ in range(count):
        recipe = {
            field: rng.randint(FIELD_MIN.get(field, 0), FIELD_MAX[field])
            for field in ALL_TARGET_FIELDS
        }
        if not recipe["mole_enabled"]:
            recipe.update(_MOLE_DEFAULTS)
        targets.append(recipe)
    return targets


# Height/weight sliders are fiddly to place exactly in the real in-game
# editor (fine-grained, no numeric readout) -- unlike every other field,
# body matching allows a small tolerance instead of requiring an exact hit.
BODY_TOLERANCE = 5


def category_matches(mii: Mii, target: Dict[str, int], category: str) -> bool:
    return all(int(getattr(mii, field)) == target[field] for field in CATEGORY_FIELDS[category])


def body_matches(mii: Mii, target: Dict[str, int]) -> bool:
    return all(abs(int(getattr(mii, field)) - target[field]) <= BODY_TOLERANCE for field in BODY_FIELDS)


def any_mii_matches_category(miis: List[Mii], target: Dict[str, int], category: str) -> bool:
    return any(category_matches(mii, target, category) for mii in miis)


def any_mii_matches_body(miis: List[Mii], target: Dict[str, int]) -> bool:
    return any(body_matches(mii, target) for mii in miis)


def mii_matches_target_fully(mii: Mii, target: Dict[str, int]) -> bool:
    """True only if this single Mii matches EVERY category (exactly) and
    the body fields (within BODY_TOLERANCE) simultaneously -- a genuine
    perfect copy of the target, as opposed to the per-category checks
    (which give credit for matching one category at a time, possibly on
    different Miis). Used for the "Perfect Copy" check -- see checks.py."""
    return (
        all(category_matches(mii, target, category) for category in CATEGORY_FIELDS)
        and body_matches(mii, target)
    )


def any_mii_matches_target_fully(miis: List[Mii], target: Dict[str, int]) -> bool:
    return any(mii_matches_target_fully(mii, target) for mii in miis)


def find_mii_matching_target_fully(miis: List[Mii], target: Dict[str, int]) -> Optional[Mii]:
    """Same match as any_mii_matches_target_fully, but returns the actual
    Mii (the first one found) instead of just True/False -- used to know
    *which* Mii to reward (rename + favorite) when a target is completed."""
    for mii in miis:
        if mii_matches_target_fully(mii, target):
            return mii
    return None


def match_score(mii: Mii, target: Dict[str, int]) -> int:
    """How many of a target's checkable categories this Mii satisfies
    (body counting as one), i.e. how much credit it would earn."""
    score = sum(1 for category in CATEGORY_FIELDS if category_matches(mii, target, category))
    return score + (1 if body_matches(mii, target) else 0)


def assign_miis_to_targets(miis: List[Mii], targets: List[Dict[str, int]]) -> Dict[int, Mii]:
    """Decide which single Mii is "working on" each target.

    Without this, one Mii credits the same category on every target at once
    -- e.g. a freshly created Mii has no mole, so it silently completed
    "Mole Match" on all five targets simultaneously, which made the goal
    trivial and confusing to watch (seen live 2026-09-04).

    Each Mii is therefore assigned to at most one target and each target to
    at most one Mii, greedily by best score: the strongest pairings are
    locked in first, so a genuine near-copy always wins its target over a
    Mii that merely shares a default with it. Ties break on target order
    then slot, so the assignment is stable between polls rather than
    flip-flopping while the player edits.

    Returns {target_index: mii} for the targets that have a Mii working on
    them at all (score 0 pairings are left unassigned)."""
    scored = [
        (match_score(mii, target), target_index, mii.slot, mii)
        for target_index, target in enumerate(targets)
        for mii in miis
    ]
    scored.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))

    assignment: Dict[int, Mii] = {}
    taken_slots: set = set()
    for score, target_index, slot, mii in scored:
        if score <= 0 or target_index in assignment or slot in taken_slots:
            continue
        assignment[target_index] = mii
        taken_slots.add(slot)
    return assignment


TARGET_PREVIEW_NAME_PREFIX = "Target"


def target_preview_name(target_index: int) -> str:
    """Name of the synthetic preview Mii written into RFL_DB.dat so this
    target is visible in the Plaza (see mii_reader.write_synthetic_miis) --
    1-indexed to match target_location_name's display numbering."""
    return f"{TARGET_PREVIEW_NAME_PREFIX} {target_index + 1}"
