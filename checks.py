"""
Definitions of every auto-detected location for the Mii Channel world.

Two tiers of checks:
  - MILESTONE_CHECKS: a small handful of simple (name, predicate) checks,
    same style as before -- predicate(miis, miis_required) -> bool, based on
    a parsed list of mii_reader.Mii records read straight from RFL_DB.dat.
  - Per-target checks: one per (target Mii, category) pair, up to
    MAX_TARGETS targets x TARGET_CHECK_CATEGORIES categories. These can't be
    static predicates like the milestones -- each target's actual field
    values are random-per-seed (see targets.py, sent to the client via
    slot_data), so the client evaluates these itself using
    targets.any_mii_matches_category / any_mii_matches_body. This module
    only defines their location *names* (target_location_name), used both
    to build the static id table below and by the client/world to look a
    specific check's id up.

The location name/id table has to cover the full MAX_TARGETS range (not
just whatever a given seed's target_count option happens to be) so ids stay
stable across every possible option value -- the world only actually creates
the locations for its own target_count in create_regions.
"""
from __future__ import annotations

from typing import Callable, List

from .mii_reader import Mii
from .options import TargetCount
from .targets import CATEGORY_NAMES

VICTORY_NAME = "Become a Mii Master"

Predicate = Callable[[List[Mii], int], bool]


def _count_at_least(n: int) -> Predicate:
    return lambda miis, required: len(miis) >= n


def _all_face_shapes(miis: List[Mii], required: int) -> bool:
    return {m.face_shape for m in miis} >= set(range(8))


MILESTONE_CHECKS: List[tuple] = [
    ("Create Your First Mii", _count_at_least(1)),
    ("Create 5 Miis", _count_at_least(5)),
    ("Create 10 Miis", _count_at_least(10)),
    ("Create 20 Miis", _count_at_least(20)),
    ("Use Every Face Shape", _all_face_shapes),
]

# One extra check per target for matching height+weight simultaneously,
# alongside the 9 face-part categories, plus a final "Perfect Copy" check
# that only fires when a single Mii matches every category AND body field
# at once (a genuine complete recreation) -- see
# targets.mii_matches_target_fully. The per-category checks above it still
# award partial progress for matching one category at a time, possibly on
# different Miis; "Perfect Copy" is the strict, all-at-once completion
# signal the user asked for on top of that.
TARGET_CHECK_CATEGORIES: List[str] = CATEGORY_NAMES + ["Body"]
PERFECT_COPY_CATEGORY: str = "Perfect Copy"
TARGET_CHECK_CATEGORIES_ALL: List[str] = TARGET_CHECK_CATEGORIES + [PERFECT_COPY_CATEGORY]

MAX_TARGETS: int = TargetCount.range_end


def target_location_name(target_index: int, category: str) -> str:
    return f"Target {target_index + 1}: {category} Match"


ALL_TARGET_LOCATION_NAMES: List[str] = [
    target_location_name(i, category)
    for i in range(MAX_TARGETS)
    for category in TARGET_CHECK_CATEGORIES_ALL
]

CHECK_NAMES: List[str] = (
    [name for name, _ in MILESTONE_CHECKS] + ALL_TARGET_LOCATION_NAMES + [VICTORY_NAME]
)
