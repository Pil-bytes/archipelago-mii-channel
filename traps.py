"""Trap effects for the Mii Channel client (2026-09-15, reworked 2026-09-16).

The world puts trap items in the pool (items.TRAP_ITEMS, weighted by the
options). The client turns each one it receives into an effect here:

  Quit Without Saving -- the editor closes and the edit is lost (ASM, waits
                         for the editor to be open)
  Tool Jam            -- one unlocked tool locks again for TOOL_JAM_SECONDS
  Paint Spill         -- a random colour lands on one of the player's Miis
  Growth Spurt        -- one of the player's Miis gets a random height/weight
  Shuffle             -- every value of one unfinished Mii is re-rolled among
                         the values the player can reach
  Mutation            -- ONE value of any Mii (finished ones too) changes to
                         another reachable value; a finished Mii loses its
                         favourite star
  Default             -- one unfinished Mii is reset to a Mii made from scratch
  Blindfold           -- the Mii being edited is hidden for BLINDFOLD_SECONDS
                         (waits for the editor)
  Lockdown            -- every tool locks for LOCKDOWN_SECONDS (waits for the
                         editor)

"Finished" = favourite: the star is only ever given by the client to a Mii
that matches its target (the game's star buttons are blocked).

Choosing WHAT a trap does is pure (this module, testable offline); the
client applies the result to RFL_DB.dat / RAM. Targets in the Parade are
never touched: only Plaza Miis are candidates.

A trap must fire once per item, not once per connection: the client replays
every received item after a restart, so the number of traps already applied
is kept in the server's data storage (TRAPS_DONE_KEY).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .locks import FIELD_DEFAULTS, field_needs
from .targets import ALL_TARGET_FIELDS, FIELD_MAX, FIELD_MIN

TOOL_JAM_SECONDS = 60.0
BLINDFOLD_SECONDS = 30.0
LOCKDOWN_SECONDS = 25.0


def traps_done_key(team: int, slot: int) -> str:
    return f"mii_channel_traps_done_{team}_{slot}"


# Colour fields a Paint Spill may hit, with their inclusive maximum
# (targets.FIELD_MAX) -- duplicated so this module stays import-light.
COLOUR_FIELDS: Dict[str, int] = {
    "hair_color": 7, "eye_color": 5, "eyebrow_color": 7, "mouth_color": 2,
    "glasses_color": 5, "facial_hair_color": 7, "favorite_color": 11,
}
BODY_MAX = 127

# Tool Jam: which in-editor lock (the labels of the client's ASM lock-byte
# loop) can be jammed, and the item(s) that must already be unlocked for it
# to count as "a tool you have". The client forces that lock byte to 0 until
# the jam expires.
JAM_TARGETS: Dict[str, Tuple[str, ...]] = {
    "eye": ("Progressive Eye Editor",),
    "eyebrow": ("Progressive Eyebrow Editor",),
    "hair": ("Progressive Hairstyle: Classic", "Progressive Hairstyle: Wild"),
    "nose": ("Nose Editor",),
    "mouth": ("Progressive Mouth Editor",),
    "face shape": ("Face Shape Tool", "Makeup Kit"),
    "skin tone": ("Skin Tone Palette",),
    "glasses": ("Glasses Case",),
    "mole": ("Mole Marker",),
    "eye color": ("Eye Color",),
    "eye movement": ("Eye Movement",),
    "eyebrow color": ("Eyebrow Color",),
    "eyebrow movement": ("Eyebrow Movement",),
    "hair color": ("Hair Color",),
    "nose movement": ("Nose Movement",),
    "mouth color": ("Mouth Color",),
    "mouth movement": ("Mouth Movement",),
    "glasses color": ("Glasses Color",),
    "glasses movement": ("Glasses Movement",),
    "facial hair color": ("Facial Hair Color",),
    "facial hair movement": ("Facial Hair Movement",),
    "mole movement": ("Mole Movement",),
}
# The facial hair kit drives two lock bytes; jamming it jams both.
JAM_SIBLINGS: Dict[str, Tuple[str, ...]] = {"mustache": ("mustache", "beard")}
JAM_TARGETS["mustache"] = ("Facial Hair Kit",)
GROWTH_MIN_CHANGE = 20   # far enough to break a body match (tolerance 5)
BODY_TRAP_FIELDS = ("height", "weight")


def paint_spill(rng: random.Random, mii) -> Tuple[str, int]:
    """(field, new value) for a Paint Spill on `mii` -- always a real change."""
    name = rng.choice(sorted(COLOUR_FIELDS))
    current = int(getattr(mii, name))
    choices = [v for v in range(COLOUR_FIELDS[name] + 1) if v != current]
    return name, rng.choice(choices)


def growth_spurt(rng: random.Random, mii) -> Dict[str, int]:
    """New height and weight for `mii`, each at least GROWTH_MIN_CHANGE away."""
    out = {}
    for name in ("height", "weight"):
        current = int(getattr(mii, name))
        choices = [v for v in range(BODY_MAX + 1) if abs(v - current) >= GROWTH_MIN_CHANGE]
        out[name] = rng.choice(choices)
    return out


def pick_victim(rng: random.Random, miis: List, protected_names=(),
                spare_finished: bool = False) -> Optional[object]:
    """A Plaza Mii to hit, never one whose name is protected (the targets);
    with spare_finished, never a finished (favourite) Mii either."""
    pool = [m for m in miis if m.name not in protected_names
            and not (spare_finished and m.is_favorite)]
    return rng.choice(pool) if pool else None


def reachable_values(field_name: str, counts: Dict[str, int]) -> List[int]:
    """Every value of `field_name` the player can pick with the items in
    `counts` (item -> copies received) -- the rule the world and the
    envelope use (locks.field_needs), so a trap never leaves a Mii in a state
    the player could not rebuild. The default is always in: a blank Mii has
    it (field_needs still asks for the carrier item, e.g. glasses colour)."""
    default = FIELD_DEFAULTS.get(field_name, FIELD_MIN.get(field_name, 0))
    return [v for v in range(FIELD_MIN.get(field_name, 0), FIELD_MAX[field_name] + 1)
            if v == default
            or all(counts.get(item, 0) >= n for item, n in field_needs(field_name, v).items())]


def shuffle(rng: random.Random, counts: Dict[str, int]) -> Dict[str, int]:
    """A new reachable value for every target field."""
    return {name: rng.choice(reachable_values(name, counts)) for name in ALL_TARGET_FIELDS}


def mutation(rng: random.Random, mii, counts: Dict[str, int]) -> Optional[Tuple[str, int]]:
    """(field, new value): one field of `mii` moved to another reachable
    value, or None when nothing can change."""
    options = []
    for name in ALL_TARGET_FIELDS:
        current = int(getattr(mii, name))
        values = [v for v in reachable_values(name, counts) if v != current
                  and (name not in BODY_TRAP_FIELDS or abs(v - current) >= GROWTH_MIN_CHANGE)]
        if values:
            options.append((name, values))
    if not options:
        return None
    name, values = rng.choice(options)
    return name, rng.choice(values)


def defaults(mii) -> Dict[str, int]:
    """The target fields of `mii` that differ from a Mii made from scratch."""
    out = {}
    for name in ALL_TARGET_FIELDS:
        value = FIELD_DEFAULTS.get(name, FIELD_MIN.get(name, 0))
        if int(getattr(mii, name)) != value:
            out[name] = value
    return out


@dataclass
class TrapState:
    """What the client has to do about traps right now."""
    done: Optional[int] = None                 # traps applied so far (server storage); None = unknown yet
    seen: int = 0                              # trap items received this session, in order
    pending: List[str] = field(default_factory=list)
    jammed: Dict[str, float] = field(default_factory=dict)    # lock label -> until (monotonic)
    quit_pending: bool = False
    blindfold_pending: bool = False            # starts when the editor opens
    blindfold_until: float = 0.0
    lockdown_pending: bool = False             # starts when the editor opens
    lockdown_until: float = 0.0

    def receive(self, trap_name: str) -> None:
        """Called for every trap item in items_received order."""
        self.seen += 1
        if self.done is not None and self.seen <= self.done:
            return                                  # already applied in an earlier session
        self.pending.append(trap_name)

    def set_done(self, done: int) -> None:
        """The server said how many traps were already applied: drop the
        replays that were queued before we knew."""
        self.done = done
        if self.seen > 0:
            replayed = max(0, min(done, self.seen) - (self.seen - len(self.pending)))
            del self.pending[:replayed]

    def jam(self, label: str, now: Optional[float] = None) -> None:
        until = (now or time.monotonic()) + TOOL_JAM_SECONDS
        for name in JAM_SIBLINGS.get(label, (label,)):
            self.jammed[name] = until

    def is_jammed(self, label: str, now: Optional[float] = None) -> bool:
        now = now or time.monotonic()
        if now < self.lockdown_until:
            return True                             # Lockdown: every tool
        until = self.jammed.get(label)
        if until is None:
            return False
        if now >= until:
            del self.jammed[label]
            return False
        return True

    def editor_opened(self, now: Optional[float] = None) -> List[str]:
        """Start the traps that wait for the editor; returns their names."""
        now = now or time.monotonic()
        started = []
        if self.blindfold_pending:
            self.blindfold_pending = False
            self.blindfold_until = max(self.blindfold_until, now) + BLINDFOLD_SECONDS
            started.append("Blindfold Trap")
        if self.lockdown_pending:
            self.lockdown_pending = False
            self.lockdown_until = max(self.lockdown_until, now) + LOCKDOWN_SECONDS
            started.append("Lockdown Trap")
        return started

    def blindfold_active(self, now: Optional[float] = None) -> bool:
        return (now or time.monotonic()) < self.blindfold_until
