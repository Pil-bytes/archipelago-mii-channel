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
from typing import Dict, List

from .mii_reader import Mii

# Grouping of Mii dataclass fields into the ~9 checkable categories (mirrors
# the face parts editable in-game), plus a separate "Body" group for
# height/weight. A category "matches" a target only when every one of its
# fields matches exactly -- no partial credit within a category.
CATEGORY_FIELDS: Dict[str, List[str]] = {
    "Face Shape": ["face_shape", "skin_color", "facial_feature"],
    "Eyes": ["eye_type", "eye_rotation", "eye_vert_pos", "eye_color", "eye_size", "eye_horiz_spacing"],
    "Eyebrows": ["eyebrow_type", "eyebrow_rotation", "eyebrow_color", "eyebrow_size", "eyebrow_vert_pos", "eyebrow_horiz_spacing"],
    "Nose": ["nose_type", "nose_size", "nose_vert_pos"],
    "Mouth": ["mouth_type", "mouth_color", "mouth_size", "mouth_vert_pos"],
    "Glasses": ["glasses_type", "glasses_color", "glasses_size", "glasses_vert_pos"],
    "Mole": ["mole_enabled", "mole_size", "mole_vert_pos", "mole_horiz_pos"],
    "Facial Hair": ["mustache_type", "beard_type", "facial_hair_color", "mustache_size", "mustache_vert_pos"],
    "Hairstyle": ["hair_type", "hair_color", "hair_part_reversed"],
}
CATEGORY_NAMES: List[str] = list(CATEGORY_FIELDS.keys())
BODY_FIELDS: List[str] = ["height", "weight"]

ALL_TARGET_FIELDS: List[str] = [f for fields in CATEGORY_FIELDS.values() for f in fields] + BODY_FIELDS

# Inclusive max value for each field when generating a target. These are the
# real in-game option counts (the number of choices in each editor page/
# slider), which are in several cases *tighter* than the raw bitfield width
# in mii_reader.FIELD_SPECS (e.g. eye_type's field is 6 bits wide / 0-63, but
# only values 0-47 are real selectable eyes -- see EYE_PAGE_COUNT in
# client.py). Believed-correct standard Mii Channel option counts; if a
# generated target ever looks impossible to reproduce in the in-game editor,
# this table is the first place to check and correct.
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
    "mouth_color": 3,
    "mouth_size": 8,
    "mouth_vert_pos": 18,
    "glasses_type": 9,
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
        recipe = {field: rng.randint(0, FIELD_MAX[field]) for field in ALL_TARGET_FIELDS}
        if not recipe["mole_enabled"]:
            recipe.update(_MOLE_DEFAULTS)
        targets.append(recipe)
    return targets


def category_matches(mii: Mii, target: Dict[str, int], category: str) -> bool:
    return all(int(getattr(mii, field)) == target[field] for field in CATEGORY_FIELDS[category])


def body_matches(mii: Mii, target: Dict[str, int]) -> bool:
    return all(int(getattr(mii, field)) == target[field] for field in BODY_FIELDS)


def any_mii_matches_category(miis: List[Mii], target: Dict[str, int], category: str) -> bool:
    return any(category_matches(mii, target, category) for mii in miis)


def any_mii_matches_body(miis: List[Mii], target: Dict[str, int]) -> bool:
    return any(body_matches(mii, target) for mii in miis)


def mii_matches_target_fully(mii: Mii, target: Dict[str, int]) -> bool:
    """True only if this single Mii matches EVERY category and the body
    fields simultaneously -- a genuine perfect copy of the target, as
    opposed to the per-category checks (which give credit for matching one
    category at a time, possibly on different Miis). Used for the
    "Perfect Copy" check -- see checks.py."""
    return all(int(getattr(mii, field)) == target[field] for field in ALL_TARGET_FIELDS)


def any_mii_matches_target_fully(miis: List[Mii], target: Dict[str, int]) -> bool:
    return any(mii_matches_target_fully(mii, target) for mii in miis)


TARGET_PREVIEW_NAME_PREFIX = "Target"


def target_preview_name(target_index: int) -> str:
    """Name a claimed target-preview Mii gets renamed to (see client.py's
    `/claim` command and mii_reader.claim_target_preview) -- 1-indexed to
    match target_location_name's display numbering."""
    return f"{TARGET_PREVIEW_NAME_PREFIX} {target_index + 1}"
