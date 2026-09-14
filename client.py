import asyncio
import subprocess
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple

import CommonClient
import Utils

from .checks import (
    MILESTONE_CHECKS,
    PERFECT_COPY_CATEGORY,
    TARGET_CHECK_CATEGORIES,
    TARGET_CHECK_CATEGORIES_ALL,
    VICTORY_NAME,
    target_location_name,
)
from .items import item_table, progressive_item_counts
from .locations import location_name_to_id
from .locks import find_violations, requirements_for
from .items import TRAP_ITEMS
from .traps import (JAM_TARGETS, TOOL_JAM_SECONDS, TrapState, growth_spurt, paint_spill,
                    pick_victim, traps_done_key)
from .help_text import SCREEN_TEXTS

# Per-screen texts (gecko dialog block, BuildWC24DialogTable). The table at
# TEXT_TABLE_ADDR is a u32 count followed by 12-byte entries: the message id
# as 8 ASCII bytes (7 digits + NUL) and a pointer to its UTF-16BE text in
# TEXT_BUFFER_BASE. The game keeps its own text for any id not listed.
TEXT_TABLE_ADDR = 0x803C5B00
TEXT_TABLE_MAX = 16
TEXT_BUFFER_BASE = 0x803C5C00
TEXT_BUFFER_BYTES = 0x300

# The same texts, written into the channel's message file (MESGbmg1 in MEM2).
# Messages whose room a longer text may take -- never shown offline.
BMG_DONOR_MESSAGES = ["0000060", "0000024", "0000083", "0000084", "0600003", "0600004",
                      "0600005", "0600200", "0600400", "0000087", "0000066", "0000067"]
# Left to the Gecko table: no donor is big enough for it.
BMG_SKIP_MESSAGES = {"0000023"}


def _screen_text_blobs() -> Tuple[bytes, bytes]:
    """(table bytes, buffers bytes) for SCREEN_TEXTS."""
    items = list(SCREEN_TEXTS.items())[:TEXT_TABLE_MAX]
    table = bytearray(len(items).to_bytes(4, "big"))
    buffers = bytearray()
    for i, (message_id, text) in enumerate(items):
        table += message_id.encode("ascii")[:7].ljust(8, b"\0")
        table += (TEXT_BUFFER_BASE + i * TEXT_BUFFER_BYTES).to_bytes(4, "big")
        encoded = text.encode("utf-16-be", "replace")[:TEXT_BUFFER_BYTES - 2]
        buffers += encoded + bytes(TEXT_BUFFER_BYTES - len(encoded))
    return bytes(table), bytes(buffers)
from .mii_reader import (
    MII_CHANNEL_TITLE_ID,
    Mii,
    dolphin_profile_dir,
    find_dolphin_exe,
    find_mii_entries_by_name,
    find_rfl_db,
    read_miis,
    read_wii_memory,
    remove_miis_by_name,
    write_mii_field,
    write_mii_creator,
    write_mii_creator_ram,
    write_mii_field_ram,
    write_parade_miis,
    write_synthetic_miis,
)
from .targets import (
    BODY_FIELDS,
    CATEGORY_FIELDS,
    assign_miis_to_targets,
    body_matches,
    category_matches,
    match_score,
    mii_matches_target_fully,
    target_preview_name,
)

POLL_INTERVAL_SECONDS = 1.0
# Badge written into the creator line when a Mii completes a target -- see
# _update_progress_names for the "T2 7/26" badge every other assigned Mii
# carries. Neither touches the name the player chose.
PERFECT_COPY_NAME_PREFIX = "Match "
# Don't refight the running game over the save file more often than this.
PREVIEW_WRITE_COOLDOWN_SECONDS = 30.0
# How long to leave the save file alone after starting Dolphin ourselves:
# it opens RFL_DB.dat exclusively while booting, and a poll landing in that
# window pops an error dialog in the game.
DOLPHIN_BOOT_QUIET_SECONDS = 20.0

# The injected patch on FUN_800639b4 makes the WC24 screen's five list rows
# read their text from this table instead of the Wii address book -- one
# 0x40-byte UTF-16BE slot per row. See BuildWC24Rows.java for the hook.
WC24_ROW_TABLE = 0x803C2000
WC24_ROW_STRIDE = 0x40
WC24_ROWS_PER_PAGE = 5
WC24_PAGE_COUNT = 6          # size of the row table: 30 slots = 6 pages of 5
WC24_ROW_COUNT = WC24_ROWS_PER_PAGE * WC24_PAGE_COUNT
# The screen's pager takes its page total from the Wii address book once, at
# boot (-1 with no Wii friends: the "1/0" header, next arrow dead). The row
# filler (BuildWC24RowsV2.java) rewrites the pager's maximum from this word
# on every fill and redraws the header and arrows, so the client only says
# how many pages it needs (value = pages - 1).
WC24_PAGE_MAX_ADDR = 0x803C1F04
# Per-row text colours (top, bottom RGBA), one 8-byte entry per row, indexed
# like the text table; the V3 filler copies them into each row's TextBox
# (+0xD8/+0xDC). (0, 0) = the game's own white.
WC24_COLOR_TABLE = 0x803C1F10
WC24_COLOR_DEFAULT = (0, 0)


def _ap_colour(rgb: int) -> Tuple[int, int]:
    """(top, bottom) RGBA for a text row: the colour, then 20% darker."""
    r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
    dark = (int(r * 0.8) << 16) | (int(g * 0.8) << 8) | int(b * 0.8)
    return (rgb << 8) | 0xFF, (dark << 8) | 0xFF


# Archipelago's text-client palette.
AP_PROGRESSION = _ap_colour(0xAF99EF)   # plum
AP_USEFUL = _ap_colour(0x6D8BE8)        # slate blue
AP_TRAP = _ap_colour(0xFA8072)          # salmon
AP_FILLER = _ap_colour(0x00EEEE)        # cyan
AP_PLAYER = _ap_colour(0xEE00EE)        # magenta (own player)
AP_RED = _ap_colour(0xEE0000)
WC24_COLOR_HEADER = AP_PLAYER
WC24_COLOR_LOST = AP_RED
WC24_COLOR_SEPARATOR = (0xBBBBBBFF, 0x999999FF)  # grey


def _item_colour(flags: int) -> Tuple[int, int]:
    """NetworkItem flags -> AP colour (progression beats useful beats trap)."""
    if flags & 0b001:
        return AP_PROGRESSION
    if flags & 0b010:
        return AP_USEFUL
    if flags & 0b100:
        return AP_TRAP
    return AP_FILLER
WC24_SEPARATOR = "-------"
# Shown when the header row of the envelope list is clicked (the dialog
# holds about 175 characters in all, the summary above it included).
WC24_COLOUR_LEGEND = ("Grey-red: locked  White: doable\n"
                      "Blue: hinted  Violet: unlock hinted\n"
                      "Green: sent  Orange: sent, lost")

# The user's colour scheme (2026-09-11).
COL_LOCKED = (0xC07878FF, 0x8C5050FF)    # grey-red: not unlocked yet
COL_IN_LOGIC = WC24_COLOR_DEFAULT        # white: doable now
COL_HINTED = (0x5AA0FFFF, 0x3C6FC8FF)    # blue: this check has been hinted
COL_WE_HINTED = (0xB478F0FF, 0x8250C3FF) # violet: what unlocks it has been hinted
COL_SENT = (0x55DD55FF, 0x22AA33FF)      # green: sent, still on the Mii
COL_LOST = (0xFFAA33FF, 0xDD7711FF)      # orange: sent, no longer on the Mii

# Row click -> our message in the game's dialog (BuildWC24Dialog.java).
WC24_MSG_TABLE = 0x803C2780
WC24_MSG_STRIDE = 0x180
WC24_MSG_BYTES = 0x160
WC24_BTN1_BYTES = 0x20
WC24_BTN2_ADDR = 0x803C1EC0
WC24_CLICK_INDEX_ADDR = 0x803C1F08
WC24_RESULT_ADDR = 0x803C1EF8
WC24_RESULT_COUNT_ADDR = 0x803C1EFC

# (row text, colour, dialog message, first-button label, item to hint)
Row = Tuple[str, Tuple[int, int], str, str, Optional[str]]

# The Mii the player has picked up (selected / carried in the Plaza and the
# Wii Friend view) is mirrored into a MEM2 object with this vtable, its Mii id
# at +0x52 -- found live 2026-09-11 by dropping lol then v13 on the envelope
# and watching one object switch between their ids. The 100 Plaza actors in
# MEM1 use the same class, so only MEM2 is searched.
SELECTED_MII_VTABLE = 0x80233D98
SELECTED_MII_ID_OFFSET = 0x52
SELECTED_MII_POLL_SECONDS = 0.2
MEM2_START, MEM2_SIZE = 0x90000000, 0x04000000
RAM_ENFORCE_INTERVAL_SECONDS = 0.4
ASM_LOCK_BITMASK_INTERVAL_SECONDS = 0.5

# Live addresses of each category's lock-bitmask byte, read by the injected
# Gecko-code trampoline (GameSettings\HACA01.ini, hooked at FUN_8003bd68 /
# 0x8003bda0). One byte per category, bit N = "grid page N is unlocked" (bit
# SET means the page's picks are allowed through; bit CLEAR means any pick
# on that page gets reverted to type 0 every frame, well before the player
# ever saves -- eye/eyebrow instead revert to type 47, an old diagnostic
# choice kept as-is since it's tested and working). See
# reference_mii_channel_re_facts memory for the full derivation -- this is a
# same-session, real-time enforcement layer on top of (not a replacement
# for) the save-file correction below.
#
# NOTE: renumbered three times as the trampoline grew (0x1100 -> 0x1200 ->
# 0x1400 -> now 0x1600) -- V8 (2026-09-06, force-default instead of
# clear-to-zero for locked color/movement fields) grew the trampoline body
# to 0x803C1000-0x803C161C, which would have silently overlapped the 0x1400
# scratch region itself (code writing into what's supposed to be data) had
# it not been caught before deploying -- exactly the class of bug that
# already crashed Dolphin once on this project at 0x803C1040. Any future
# trampoline change must re-check its generated "Total trampoline size"
# against wherever this region currently starts before extending either
# one.
EYE_LOCK_BITMASK_ADDR = 0x803C1600
EYE_PAGE_COUNT = 4  # eye_type 0-47, 12 per page (DAT_80207118 page table)

# Eyebrow category, same mechanism, same trampoline (chained after the eye
# block, no interference confirmed live). 24 eyebrow types at 12 per page =
# 2 pages, read off the editor itself (its grid header shows "1/2").
EYEBROW_LOCK_BITMASK_ADDR = 0x803C1601
EYEBROW_PAGE_COUNT = 2

# Hair category: hair_type is gated by TWO progressive lines (Progressive
# Hairstyle: Classic covers types 0-35 = pages 0-2, Wild covers 36-71 =
# pages 3-5, using the same 12-per-page convention confirmed universal
# across every paginated category in FUN_8003bda4's decompile -- 72 types /
# 12 = 6 pages, matching locks.py's HAIRSTYLE_CLASSIC_MAX=35 split exactly
# at the page-3 boundary). Revert-to-0 when locked. Each line unlocks its
# own 3 pages one at a time, in order (see poll_asm_lock_bitmask).
HAIR_LOCK_BITMASK_ADDR = 0x803C1602

# Nose category: single-page in-game (no DAT_xxx page table used by
# FUN_8003bda4's case 6 at all -- "FUN_8003df28, 1 slot, no loop"), so the
# trampoline treats this scratch byte as a plain locked(0)/unlocked(nonzero)
# flag rather than a per-page bitmask.
NOSE_LOCK_BITMASK_ADDR = 0x803C1603

# Mouth category: paginated like eye/eyebrow/hair (DAT_80207170 table, same
# /12 convention). Page count not pinned down exactly; matching eye/
# eyebrow's existing all-or-nothing usage (0xFF/0x00) sidesteps needing it.
MOUTH_LOCK_BITMASK_ADDR = 0x803C1604

# Face shape category (compound, single-page): case 2 in FUN_8003bda4 packs
# face_shape + skin_color + facial_feature into one r6+0 halfword, but
# "Face Shape Tool" only gates face_shape+facial_feature -- skin_color is
# gated separately by "Skin Tone Palette". Two independent scratch bytes,
# same locked(0)/unlocked(nonzero) convention as nose.
FACE_SHAPE_LOCK_BITMASK_ADDR = 0x803C1605
SKIN_TONE_LOCK_BITMASK_ADDR = 0x803C1606

# Category 8 (glasses/mustache/beard/mole): four independent single-page
# fields, no DAT_xxx table for any of them. Mustache and beard share the
# same r6+16 halfword (different bit ranges) but still get independent
# scratch bytes/lock checks.
GLASSES_LOCK_BITMASK_ADDR = 0x803C1607
MUSTACHE_LOCK_BITMASK_ADDR = 0x803C1608
BEARD_LOCK_BITMASK_ADDR = 0x803C1609
MOLE_LOCK_BITMASK_ADDR = 0x803C160A

# Color and movement (size/rotation/position) real-time locks, independent
# of whichever type pages are unlocked -- one scratch byte per lock item,
# same locked(0)/unlocked(nonzero) flag convention as the single-page type
# locks (nose etc.). Only categories that actually have a color and/or
# movement sub-field get one (nose/mole have no color; face shape and skin
# tone have neither).
EYE_COLOR_LOCK_BITMASK_ADDR = 0x803C160B
EYE_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C160C
EYEBROW_COLOR_LOCK_BITMASK_ADDR = 0x803C160D
EYEBROW_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C160E
HAIR_COLOR_LOCK_BITMASK_ADDR = 0x803C160F
NOSE_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1610
MOUTH_COLOR_LOCK_BITMASK_ADDR = 0x803C1611
MOUTH_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1612
GLASSES_COLOR_LOCK_BITMASK_ADDR = 0x803C1613
GLASSES_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1614
FACIAL_HAIR_COLOR_LOCK_BITMASK_ADDR = 0x803C1615
FACIAL_HAIR_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1616
MOLE_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1617

# Editor heartbeat, bumped once per call of the hooked category-apply
# function. A canary established that function fires ~120x/s while a Mii is
# open in the editor and exactly 0 times anywhere else, so "this word is
# still changing" is a reliable "the editor is open" signal -- and its
# rising edge is the moment to capture the values below.
EDITOR_HEARTBEAT_ADDR = 0x803C17F0

# Per-field restore values the V9 trampoline reads when a field is locked.
# Before V9 it wrote zeroes (which froze the game on save, since
# eyebrow_vert_pos rejects 0) and then guessed constants (which put the
# eyebrows in the wrong place and forced a locked colour to brown). The
# player's own value is the only correct answer.
RESTORE_VALUE_TABLE_ADDR = 0x803C1500
RESTORE_VALUE_FIELDS = (
    # (table offset, live-struct word offset, start_from_msb, width)
    ("eyebrow_type", 0x0, 0x8, 0, 5),
    ("eyebrow_rotation", 0x1, 0x8, 6, 4),
    ("eyebrow_color", 0x2, 0x8, 16, 3),
    ("eyebrow_size", 0x3, 0x8, 19, 4),
    ("eyebrow_vert_pos", 0x4, 0x8, 23, 5),
    ("eyebrow_horiz_spacing", 0x5, 0x8, 28, 4),
)

# Where the trampoline publishes the live Mii-edit struct pointer it derives
# itself, as *(int*)(*(int*)(r13-0x7064)+0xbc). This used to be a hardcoded
# 0x906919BC on the theory that Wii heap layout is deterministic; a probe
# read 0x906919d4 back out of it -- a pointer, not a packed field word --
# so the restore table was being filled from whatever sat at a stale
# address. Reading the pointer the game itself just computed cannot go
# stale.
EDIT_STRUCT_PTR_ADDR = 0x803C17F4

# Feature switches, for isolating a bug to one layer of the mod. Each can be
# flipped live with /feature <name> on|off (list them with /features); the
# choice is saved to FEATURES_FILE in the Dolphin profile folder so it
# survives a client restart. The Gecko side has its own switchboard:
# Tools/bench.py toggles each HACA01.ini block (needs a Dolphin restart).
FEATURE_DEFAULTS: Dict[str, bool] = {
    "previews": True,        # write the 'Target N' Miis into the Plaza
    "autolaunch": True,      # start Dolphin once connected
    "file_locks": True,      # revert locked features in RFL_DB.dat
    "favorite_guard": True,  # reserve the favorite star for perfect copies
    "badges": True,          # 'T2 7/25' creator line, file + RAM
    "wc24_rows": True,       # remaining-characteristics text on the WC24 screen
    "asm_locks": True,       # real-time locks; off = every lock byte 0xFF (trampoline inert)
    # Obsolete since V11 (the trampoline keeps the last good state itself)
    # and now DANGEROUS to leave on: it writes 6 bytes at 0x803C1500, and a
    # trampoline that ever grows past that address would have its own code
    # overwritten. Kept only so an old V9/V10 build can still be tested.
    "restore_values": False,
    # Keep the targets out of the Plaza: on start-up (Dolphin closed) write
    # them into the Mii Parade and delete the Plaza previews, so the Plaza
    # holds only the player's own Miis. Parade layout decoded from the
    # game's code and verified live 2026-09-11 (see mii_reader).
    "targets_in_parade": False,
}
FEATURE_HELP: Dict[str, str] = {
    "restore_values": "V9/V10 only. Writes at 0x803C1500 -- keep OFF with V11+.",
    "targets_in_parade": "takes effect at the next start with Dolphin closed.",
}
FEATURES_FILE = "mii_channel_features.json"

try:
    import dolphin_memory_engine as _dme
except ImportError:
    _dme = None

_ID_TO_ITEM_NAME: Dict[int, str] = {data.code: name for name, data in item_table.items()}


class MiiChannelCommandProcessor(CommonClient.ClientCommandProcessor):
    ctx: "MiiChannelContext"

    def _cmd_features(self) -> bool:
        """List the mod's feature switches (see /feature)."""
        for name, on in self.ctx.features.items():
            note = FEATURE_HELP.get(name, "")
            CommonClient.logger.info(f"  [{'on ' if on else 'OFF'}] {name}{'  -- ' + note if note else ''}")
        return True

    def _cmd_feature(self, name: str = "", state: str = "") -> bool:
        """Turn one layer of the mod on or off to isolate a bug, e.g.
        /feature wc24_rows off. Saved across client restarts; /features lists them."""
        if name not in self.ctx.features or state.lower() not in ("on", "off"):
            CommonClient.logger.info(f"Usage: /feature <{'|'.join(self.ctx.features)}> on|off")
            return True
        self.ctx.features[name] = state.lower() == "on"
        self.ctx._save_features()
        CommonClient.logger.info(f"{name} is now {state.upper()}")
        return True

    def _cmd_miipath(self, path: str = "") -> bool:
        """Manually set the path to your RFL_DB.dat (Wii Mii database) file."""
        if not path:
            CommonClient.logger.info(f"Current path: {self.ctx.mii_db_path or '(not set)'}")
            return True

        self.ctx.mii_db_path = path
        CommonClient.logger.info(f"Mii database path set to: {path}")
        return True

    def _cmd_targets(self, index: str = "") -> bool:
        """List your target Miis and how many categories you've matched so
        far. Pass a target number (e.g. /targets 3) to print that target's
        full field recipe. In game, the targets are in the Mii Parade and
        the Wii Friend envelope lists what a Mii still has to match."""
        if not self.ctx.target_miis:
            CommonClient.logger.info("No targets loaded yet -- connect to a server first.")
            return True

        if index:
            try:
                i = int(index) - 1
            except ValueError:
                CommonClient.logger.info("Usage: /targets [target number]")
                return True
            if not (0 <= i < len(self.ctx.target_miis)):
                CommonClient.logger.info(f"Target must be between 1 and {len(self.ctx.target_miis)}.")
                return True

            target = self.ctx.target_miis[i]
            CommonClient.logger.info(f"--- Target {i + 1} ---")
            for category in TARGET_CHECK_CATEGORIES:
                fields = BODY_FIELDS if category == "Body" else CATEGORY_FIELDS[category]
                done = target_location_name(i, category) in self.ctx.checked_names
                mark = "DONE" if done else "    "
                values = ", ".join(f"{f}={target[f]}" for f in fields)
                CommonClient.logger.info(f"[{mark}] {category}: {values}")
            perfect_done = target_location_name(i, PERFECT_COPY_CATEGORY) in self.ctx.checked_names
            CommonClient.logger.info(f"[{'DONE' if perfect_done else '    '}] {PERFECT_COPY_CATEGORY} "
                                      f"(one single Mii matching everything above at once)")
            return True

        CommonClient.logger.info(
            f"{len(self.ctx.target_miis)} target Mii(s), all visible in the Mii Parade. "
            f"Use /targets <n> to see one's exact recipe."
        )
        existing_names: Set[str] = set()
        if self.ctx.mii_db_path:
            try:
                existing_names = {m.name for m in read_miis(self.ctx.mii_db_path)}
            except OSError:
                pass
        for i in range(len(self.ctx.target_miis)):
            matched = sum(
                1 for category in TARGET_CHECK_CATEGORIES
                if target_location_name(i, category) in self.ctx.checked_names
            )
            perfect_done = target_location_name(i, PERFECT_COPY_CATEGORY) in self.ctx.checked_names
            preview = "" if target_preview_name(i) in existing_names else " [not in Plaza yet]"
            CommonClient.logger.info(
                f"Target {i + 1}: {matched}/{len(TARGET_CHECK_CATEGORIES)} categories matched"
                f"{' -- PERFECT COPY DONE' if perfect_done else ''}{preview}"
            )
        return True


class MiiChannelContext(CommonClient.CommonContext):
    tags: Set[str] = {"AP"}
    game: str = "Mii Channel Auto"
    command_processor = MiiChannelCommandProcessor
    items_handling: int = 0b111
    want_slot_data: bool = True

    mii_db_path: Optional[str]
    miis_required: int
    target_miis: List[Dict[str, int]]
    checked_names: Set[str]
    goaled: bool
    could_not_find_file_logged: bool
    unlocked_items: Set[str]
    progressive_counts: Dict[str, int]
    seen_item_indices: Set[int]
    last_preview_write: float
    dolphin_launched: bool
    pause_polling_until: float
    mii_signatures: Dict[int, tuple]
    mii_touched_at: Dict[int, float]
    dme_missing_warned: bool
    dme_hook_warned: bool
    asm_dme_missing_warned: bool
    asm_dme_hook_warned: bool

    def __init__(self, server_address: Optional[str], password: Optional[str]) -> None:
        super().__init__(server_address, password)
        self.mii_db_path = find_rfl_db()
        self.miis_required = 10
        self.target_miis = []
        self.checked_names = set()
        self.goaled = False
        self.last_preview_write = 0.0
        self.dolphin_launched = False
        self.mii_signatures = {}
        self.mii_touched_at = {}
        self.pause_polling_until = 0.0
        self.could_not_find_file_logged = False
        self.unlocked_items = set()
        self.progressive_counts = {}
        self.seen_item_indices = set()
        self.traps = TrapState()
        self.bmg_addr: Optional[int] = None
        self.bmg_checked_at = 0.0
        self.dme_missing_warned = False
        self.dme_hook_warned = False
        self.asm_dme_missing_warned = False
        self.asm_dme_hook_warned = False
        # Editor-open detection for the V9 restore table (see
        # _refresh_restore_values).
        self.last_editor_heartbeat: Optional[int] = None
        self.editor_was_open = False
        self.selected_obj_addr: Optional[int] = None
        self.selected_mii_id: Optional[bytes] = None
        self.last_selected_scan = 0.0
        self.cached_miis: List[Mii] = []
        self.cached_assignment: Dict[int, Mii] = {}
        self.row_hint_items: List[Optional[str]] = []
        self.last_msg_blob = b""
        self.last_result_count: Optional[int] = None
        self.dme_hooked_pid: Optional[int] = None
        self.dme_pid_checked_at = 0.0
        self.features: Dict[str, bool] = dict(FEATURE_DEFAULTS)
        self._load_features()

    def _features_path(self) -> Optional[str]:
        if not self.mii_db_path:
            return None
        import os
        return os.path.join(dolphin_profile_dir(self.mii_db_path), FEATURES_FILE)

    def _load_features(self) -> None:
        path = self._features_path()
        if not path:
            return
        import json, os
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError) as e:
            CommonClient.logger.warning(f"Ignoring unreadable {path}: {e!r}")
            return
        for name, value in saved.items():
            if name in self.features:
                self.features[name] = bool(value)
        changed = [f"{n}={'on' if v else 'off'}" for n, v in self.features.items() if v != FEATURE_DEFAULTS[n]]
        if changed:
            CommonClient.logger.info(f"Feature switches from {FEATURES_FILE}: {', '.join(changed)}")

    def _save_features(self) -> None:
        path = self._features_path()
        if not path:
            return
        import json
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.features, fh, indent=2)
        except OSError as e:
            CommonClient.logger.warning(f"Could not save {path}: {e!r}")

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)

        await self.get_username()
        await self.send_connect()

    async def disconnect(self, allow_autoreconnect: bool = False):
        self.checked_names = set()
        self.goaled = False
        self.last_preview_write = 0.0
        self.dolphin_launched = False
        await super().disconnect(allow_autoreconnect)

    def on_package(self, cmd: str, args: Any) -> None:
        if cmd == "Connected":
            slot_data: Dict[str, Any] = args.get("slot_data") or {}
            self.miis_required = slot_data.get("miis_required", 10)
            self.target_miis = slot_data.get("target_miis", [])

            CommonClient.logger.info(
                f"{len(self.target_miis)} target Mii(s) loaded. They appear in the Mii Parade as "
                f"'Target 1'...'Target {len(self.target_miis)}'; drop one of your Miis on the "
                f"Wii Friend envelope to see what it still has to match."
            )

            Utils.async_start(
                self.send_msgs([
                    {"cmd": "StatusUpdate", "status": CommonClient.ClientStatus.CLIENT_PLAYING}
                ])
            )

        super().on_package(cmd, args)

        if cmd == "Connected":
            # What every location of ours holds (create_as_hint 0: nothing is
            # announced or hinted -- the client only reveals it in-game once
            # the check has been sent, or once somebody hinted it), and a
            # subscription to this slot's hints.
            hints_key = f"_read_hints_{self.team}_{self.slot}"
            Utils.async_start(self.send_msgs([
                {"cmd": "LocationScouts", "locations": sorted(self.server_locations), "create_as_hint": 0},
                {"cmd": "Get", "keys": [hints_key, traps_done_key(self.team, self.slot)]},
                {"cmd": "SetNotify", "keys": [hints_key]},
            ]))

    def _dolphin_pid(self) -> Optional[int]:
        try:
            output = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        for line in output.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1 and parts[0].lower() == "dolphin.exe" and parts[1].isdigit():
                return int(parts[1])
        return None

    def _ensure_dme_hooked(self) -> bool:
        """Hook Dolphin's memory, and RE-hook when Dolphin was restarted.

        dolphin_memory_engine keeps reporting is_hooked() after the Dolphin
        it attached to is gone, and every write then fails ("Could not write
        memory") -- confirmed 2026-09-11: after a Dolphin restart the client
        silently stopped writing the lock bytes (everything read as locked)
        and the envelope screen's rows (blank). An older fix un-hooked on
        every failed write and thrashed; this un-hooks once per new process."""
        now = time.monotonic()
        if now - self.dme_pid_checked_at >= 3.0:
            self.dme_pid_checked_at = now
            pid = self._dolphin_pid()
            if pid != self.dme_hooked_pid:
                if self.dme_hooked_pid is not None:
                    try:
                        _dme.un_hook()
                    except Exception:
                        pass
                    if pid is not None:
                        CommonClient.logger.info("Dolphin was restarted -- reconnecting to its memory.")
                self.dme_hooked_pid = pid
                self.last_msg_blob = b""          # a new Dolphin has empty tables
                self.last_result_count = None
        if not _dme.is_hooked():
            try:
                _dme.hook()
            except Exception:
                pass
        return _dme.is_hooked()

    def _dolphin_is_running(self) -> bool:
        try:
            output = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/NH"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "Dolphin.exe" in output

    def _move_targets_to_parade(self, preview_names: Set[str]) -> None:
        """Targets go to the Mii Parade, the Plaza keeps only the player's
        Miis. Only safe while Dolphin is closed: the running game keeps its
        own copy of the Parade list and writes it back over ours."""
        if not self.target_miis or not self.mii_db_path:
            return
        if self._dolphin_is_running():
            CommonClient.logger.info(
                "Dolphin is already running, so the targets can't be moved to the Mii Parade "
                "now -- close Dolphin and restart the client to do it.")
            return
        try:
            written = write_parade_miis(
                self.mii_db_path,
                [(target_preview_name(i), target) for i, target in enumerate(self.target_miis)])
            removed = remove_miis_by_name(self.mii_db_path, preview_names)
        except (OSError, ValueError) as e:
            CommonClient.logger.warning(f"Could not move the targets to the Mii Parade: {e!r}")
            return
        CommonClient.logger.info(
            f"{len(written)} target Mii(s) are in the Mii Parade (Parade button, top right of the "
            f"Plaza); {removed} preview(s) removed from the Plaza.")

    def _launch_dolphin(self) -> None:
        """Boot Dolphin straight into the Mii Channel once we're connected.

        Deliberately runs AFTER the target previews have been written: the
        running game owns RFL_DB.dat and writes its boot-time list back over
        anything added later, so launching it ourselves is what guarantees
        the previews are on disk first (doing this by hand in the right
        order was a recurring source of half-loaded target lists)."""
        if not self.mii_db_path:
            return
        if self._dolphin_is_running():
            CommonClient.logger.info("Dolphin is already running -- leaving it alone.")
            return

        profile_dir = dolphin_profile_dir(self.mii_db_path)
        exe = find_dolphin_exe(profile_dir)
        if not exe:
            CommonClient.logger.info(
                "Could not find Dolphin.exe to start automatically -- launch it yourself "
                "(the target Miis are already written to your save)."
            )
            return

        try:
            subprocess.Popen([exe, "-u", profile_dir, "-n", MII_CHANNEL_TITLE_ID])
        except OSError as e:
            CommonClient.logger.warning(f"Could not start Dolphin: {e!r}")
            return

        # Back off from the save file while the game boots. Dolphin opens it
        # exclusively on startup, and a poll landing in that window makes the
        # game fail with "could not be opened -- use by another process",
        # which is a dialog the player has to answer rather than a silent
        # retry.
        self.pause_polling_until = time.monotonic() + DOLPHIN_BOOT_QUIET_SECONDS
        CommonClient.logger.info("Starting Dolphin on the Mii Channel...")


    def _update_todo_rows(self, miis: List[Mii], assignment: Dict[int, Mii]) -> None:
        """Fill the five rows of the in-game "Choose a Wii Friend to send this
        Mii to" screen with the categories still to match.

        That screen is the only list in the game able to show text, and an
        injected patch (HACA01.ini, see BuildWC24RowsV3.java) makes it read each
        row's text from WC24_ROW_TABLE and its colour from WC24_COLOR_TABLE
        instead of the address book. Category
        NAMES only, deliberately: the exact values are the player's job to
        find, and the names match the Archipelago check names one-for-one so a
        received item points straight at a row.

        Lists the target of the Mii the player picked up (the one carried onto
        the envelope), read from the game's selected-Mii object by
        poll_selected_mii. Before any Mii has been picked up it falls back to
        the most recently edited Mii, then the most advanced target."""
        if _dme is None:
            return

        by_id = {m.mii_id: m for m in miis if m.mii_id}
        picked = by_id.get(self.selected_mii_id) if self.selected_mii_id else None
        rows: List[Row]
        if picked is not None:
            owned = [t for t, m in assignment.items() if m.slot == picked.slot]
            if owned:
                rows = self._todo_rows_for(owned[0], picked)
            else:
                rows = [(f"{picked.name}: no target", WC24_COLOR_HEADER,
                         f"{picked.name}\nThis Mii is not working on any target.", "OK", None)]
        elif assignment:
            best = max(
                assignment.items(),
                key=lambda kv: (
                    self.mii_touched_at.get(kv[1].slot, 0.0),
                    match_score(kv[1], self.target_miis[kv[0]]),
                ),
            )
            rows = self._todo_rows_for(best[0], best[1])
        else:
            return
        # The filler indexes by page*5 + row, so the whole list is written;
        # the pager is told how many pages that makes.
        rows = rows[:WC24_ROW_COUNT]
        pages = max(1, -(-len(rows) // WC24_ROWS_PER_PAGE))

        try:
            if not self._ensure_dme_hooked():
                return
            colours = bytearray(8 * WC24_ROW_COUNT)
            messages = bytearray(WC24_MSG_STRIDE * WC24_ROW_COUNT)
            hint_items: List[Optional[str]] = []
            for row in range(WC24_ROW_COUNT):
                text, (top, bottom), message, button, hint_item = (
                    rows[row] if row < len(rows) else ("", WC24_COLOR_DEFAULT, "", "", None))
                encoded = text.encode("utf-16-be")[:WC24_ROW_STRIDE - 2]
                _dme.write_bytes(
                    WC24_ROW_TABLE + row * WC24_ROW_STRIDE,
                    encoded + bytes(WC24_ROW_STRIDE - len(encoded)),
                )
                colours[8 * row:8 * row + 8] = top.to_bytes(4, "big") + bottom.to_bytes(4, "big")
                base = row * WC24_MSG_STRIDE
                m = message.encode("utf-16-be", "replace")[:WC24_MSG_BYTES - 2]
                b = button.encode("utf-16-be", "replace")[:WC24_BTN1_BYTES - 2]
                messages[base:base + len(m)] = m
                messages[base + WC24_MSG_BYTES:base + WC24_MSG_BYTES + len(b)] = b
                hint_items.append(hint_item)
            _dme.write_bytes(WC24_COLOR_TABLE, bytes(colours))
            self.row_hint_items = hint_items
            # Also rewrite when RAM no longer holds our header message: the
            # game zeroes this area while it boots, after we may have hooked.
            if (bytes(messages) != self.last_msg_blob
                    or _dme.read_bytes(WC24_MSG_TABLE, 0x20) != bytes(messages[:0x20])):
                _dme.write_bytes(WC24_MSG_TABLE, bytes(messages))
                close = "Close".encode("utf-16-be")
                _dme.write_bytes(WC24_BTN2_ADDR, close + bytes(0x30 - len(close)))
                self.last_msg_blob = bytes(messages)
            _dme.write_bytes(WC24_PAGE_MAX_ADDR, (pages - 1).to_bytes(4, "big"))
        except Exception as e:
            CommonClient.logger.debug(f"Could not write the in-game to-do rows: {e!r}")

    def _todo_rows_for(self, target_index: int, mii: Mii) -> List[Row]:
        """Header, then three groups split by a separator row: still to do,
        already sent and still true on this Mii, sent but no longer true.
        Each row also carries the message shown when it is clicked."""
        target = self.target_miis[target_index]
        todo: List[str] = []
        sent: List[str] = []
        lost: List[str] = []
        for category in list(CATEGORY_FIELDS) + ["Body"]:
            matched = (body_matches(mii, target) if category == "Body"
                       else category_matches(mii, target, category))
            checked = target_location_name(target_index, category) in self.checked_names
            if matched:
                sent.append(category)
            elif checked:
                lost.append(category)
            else:
                todo.append(category)

        hints = self._hints()

        def loc(category: str) -> Optional[int]:
            return location_name_to_id.get(target_location_name(target_index, category))

        def location_hint(category: str) -> Optional[Dict[str, Any]]:
            lid = loc(category)
            return next((h for h in hints if h.get("finding_player") == self.slot
                         and h.get("location") == lid), None)

        def item_hints(item_name: str) -> List[Dict[str, Any]]:
            """Hints for copies of this item not received yet -- a found copy
            is already counted in `have` (progressive items have several)."""
            data = item_table.get(item_name)
            if data is None:
                return []
            return [h for h in hints if h.get("receiving_player") == self.slot
                    and h.get("item") == data.code and not h.get("found")]

        def needs(category: str) -> List[Tuple[str, int, int]]:
            if category == "Body":
                return []
            wanted = {f: int(target[f]) for f in CATEGORY_FIELDS[category] if f in target}
            return requirements_for(mii, wanted, self.unlocked_items, self.progressive_counts)

        def sent_message(category: str, still: bool) -> str:
            lines = [category, "Check sent:"]
            info = self.locations_info.get(loc(category))
            if info is not None:
                lines.append(f"{self._item_label(info.item, info.player)}")
                lines.append(f"for {self._player_label(info.player)}")
            lines.append("Still on this Mii." if still else "No longer on this Mii!")
            return "\n".join(lines)

        def todo_row(category: str) -> Row:
            missing = needs(category)
            lh = location_hint(category)
            lines = [category]
            to_hint: Optional[str] = None
            if missing:
                lines.append("Locked. Missing:")
                for item, have, need in missing[:3]:
                    lines.append(f"{item} {have}/{need}")
                    known = item_hints(item)
                    for h in known[:2]:
                        where = self._location_label(h.get("location"), h.get("finding_player"))
                        lines.append(f"  at {where} ({self._player_label(h.get('finding_player'))})")
                    if len(known) < need - have and to_hint is None:
                        to_hint = item
            else:
                lines.append("Unlocked: recreate it")
                lines.append("on this Mii.")
            if lh is not None:
                lines.append(f"Hinted: {self._item_label(lh.get('item'), lh.get('receiving_player'))}")
                lines.append(f"for {self._player_label(lh.get('receiving_player'))}")
            if lh is not None:
                colour = COL_HINTED
            elif missing:
                colour = COL_WE_HINTED if to_hint is None else COL_LOCKED
            else:
                colour = COL_IN_LOGIC
            return (category, colour, "\n".join(lines), "Hint" if to_hint else "OK", to_hint)

        header = (f"T{target_index + 1} is a perfect copy!" if not todo and not lost
                  else f"T{target_index + 1}: {len(todo)} left")
        summary = (f"Target {target_index + 1} - {mii.name}\n{len(todo)} to do, "
                   f"{len(sent)} sent, {len(lost)} lost\n"
                   f"{WC24_COLOUR_LEGEND}")
        separator: Row = (WC24_SEPARATOR, WC24_COLOR_SEPARATOR, "", "", None)
        rows: List[Row] = [(header, WC24_COLOR_HEADER, summary, "OK", None)]
        rows += [todo_row(c) for c in todo]
        if sent:
            rows += [separator] + [(c, COL_SENT, sent_message(c, True), "OK", None) for c in sent]
        if lost:
            rows += [separator] + [(c, COL_LOST, sent_message(c, False), "OK", None) for c in lost]
        return rows

    def _item_label(self, item_id: Any, player: Any) -> str:
        try:
            return str(self.item_names.lookup_in_slot(int(item_id), int(player)))
        except Exception:
            return f"item {item_id}"

    def _location_label(self, location_id: Any, player: Any) -> str:
        try:
            return str(self.location_names.lookup_in_slot(int(location_id), int(player)))
        except Exception:
            return f"location {location_id}"

    def _player_label(self, player: Any) -> str:
        try:
            return str(self.player_names[int(player)])
        except Exception:
            return f"player {player}"

    def _poll_dialog_result(self) -> None:
        """A button was pressed in a row's dialog: "Hint" -> !hint <item>."""
        try:
            count = int.from_bytes(_dme.read_bytes(WC24_RESULT_COUNT_ADDR, 4), "big")
            if self.last_result_count is None or count < self.last_result_count:
                self.last_result_count = count
                return
            if count == self.last_result_count:
                return
            self.last_result_count = count
            button = int.from_bytes(_dme.read_bytes(WC24_RESULT_ADDR, 4), "big")
            index = int.from_bytes(_dme.read_bytes(WC24_CLICK_INDEX_ADDR, 4), "big")
        except Exception:
            return
        item = self.row_hint_items[index] if 0 <= index < len(self.row_hint_items) else None
        if button == 1 and item:
            CommonClient.logger.info(f"Hint asked from the envelope screen: {item}")
            Utils.async_start(self.send_msgs([{"cmd": "Say", "text": f"!hint {item}"}]))

    def _hints(self) -> List[Dict[str, Any]]:
        """This slot's hints (data storage), as plain dicts."""
        raw = self.stored_data.get(f"_read_hints_{self.team}_{self.slot}") or []
        out: List[Dict[str, Any]] = []
        for h in raw:
            if isinstance(h, dict):
                out.append(h)
            else:
                out.append({k: getattr(h, k, None) for k in
                            ("receiving_player", "finding_player", "location", "item", "found", "item_flags")})
        return out

    def _hinted_flags(self, location_id: Optional[int]) -> Optional[int]:
        """Item flags of a hint pointing at one of OUR locations, if any."""
        if location_id is None:
            return None
        for h in self._hints():
            if h.get("finding_player") == self.slot and h.get("location") == location_id:
                return int(h.get("item_flags") or 0)
        return None

    async def _find_selected_mii_object(self) -> Optional[int]:
        """Scan MEM2 for the selected-Mii object: vtable SELECTED_MII_VTABLE
        and the id of a Mii we know. Yields between chunks -- a full pass is a
        few seconds of reads and must not stall the rest of the client."""
        known = {m.mii_id for m in self.cached_miis if m.mii_id}
        if not known:
            return None
        needle = SELECTED_MII_VTABLE.to_bytes(4, "big")
        step = 0x100000
        for off in range(0, MEM2_SIZE, step):
            try:
                chunk = _dme.read_bytes(MEM2_START + off, step)
            except Exception:
                return None
            i = chunk.find(needle)
            while i != -1:
                if i % 4 == 0:
                    addr = MEM2_START + off + i
                    try:
                        mii_id = _dme.read_bytes(addr + SELECTED_MII_ID_OFFSET, 8)
                    except Exception:
                        mii_id = b""
                    if mii_id in known:
                        return addr
                i = chunk.find(needle, i + 1)
            await asyncio.sleep(0)
        return None

    async def poll_selected_mii(self) -> None:
        """Keep the envelope rows on the Mii the player is holding."""
        if _dme is None:
            return
        while not self.exit_event.is_set():
            await asyncio.sleep(SELECTED_MII_POLL_SECONDS)
            if not self.features["wc24_rows"] or not self.cached_miis:
                continue
            if not self._ensure_dme_hooked():
                self.selected_obj_addr = None
                continue
            self._poll_dialog_result()
            if self.selected_obj_addr is None:
                now = time.monotonic()
                if now - self.last_selected_scan < 15.0:
                    continue
                self.last_selected_scan = now
                self.selected_obj_addr = await self._find_selected_mii_object()
                if self.selected_obj_addr is None:
                    continue
            try:
                head = _dme.read_bytes(self.selected_obj_addr, 4)
                mii_id = _dme.read_bytes(self.selected_obj_addr + SELECTED_MII_ID_OFFSET, 8)
            except Exception:
                self.selected_obj_addr = None
                continue
            if head != SELECTED_MII_VTABLE.to_bytes(4, "big"):
                self.selected_obj_addr = None       # object moved: find it again
                continue
            if mii_id != self.selected_mii_id and any(m.mii_id == mii_id for m in self.cached_miis):
                self.selected_mii_id = mii_id
                self._update_todo_rows(self.cached_miis, self.cached_assignment)

    def _update_progress_names(self, miis: List[Mii], assignment: Dict[int, Mii]) -> None:
        """Show each Mii's progress as its creator line -- "T2 7/26" meaning
        "working on Target 2, 7 of the 26 checkable categories already
        match".

        The Mii Channel prints the creator name directly under the Mii's own
        name in the Plaza bubble, so this reads as a progress badge without
        costing the player the name they chose (an earlier version wrote
        into the name itself and simply erased it). Both fields hold 10
        characters; "T20 26/26" is the worst case at 9.

        Miis with no target assigned are left alone, and a Mii that already
        completed its target keeps its "Match N" badge."""
        # Live on purpose (user's choice, 2026-09-14): an emulation freeze
        # was seen once right after saving a new Mii while this wrote
        # RFL_DB.dat and RAM (2026-09-11), but a crash costs nothing and the
        # live badge is much nicer. First suspect if freezes come back.
        slot_to_target = {mii.slot: target_index for target_index, mii in assignment.items()}
        total = len(TARGET_CHECK_CATEGORIES)

        for mii in miis:
            if mii.creator.startswith(PERFECT_COPY_NAME_PREFIX):
                continue

            target_index = slot_to_target.get(mii.slot)
            if target_index is None:
                continue

            score = match_score(mii, self.target_miis[target_index])
            wanted = f"T{target_index + 1} {score}/{total}"

            if wanted != mii.creator:
                try:
                    write_mii_creator(self.mii_db_path, mii.slot, wanted)
                except Exception as e:
                    CommonClient.logger.warning(f"Could not update {mii.name}'s progress badge: {e!r}")
                    continue
                self._update_creator_in_ram(mii.name, wanted)

    def _update_creator_in_ram(self, mii_name: str, text: str) -> None:
        """Mirror a creator-line change into the running game's copy so the
        bubble updates without leaving the channel. Silent on failure: the
        save already has it, so the worst case is the badge only appearing
        after re-entering the channel."""
        if _dme is None:
            return
        try:
            if not self._ensure_dme_hooked():
                return
            for entry_addr, _mii in find_mii_entries_by_name(read_wii_memory(_dme), mii_name):
                write_mii_creator_ram(_dme, entry_addr, text)
        except Exception as e:
            CommonClient.logger.debug(f"Could not mirror the progress badge into Dolphin: {e!r}")

    def _apply_traps(self, miis: List[Mii]) -> None:
        """Turn received trap items into effects, once each (traps.py).

        Nothing happens until the server said how many traps earlier
        sessions already applied -- otherwise every restart would replay
        them all."""
        import random as _random

        key = traps_done_key(self.team, self.slot)
        if self.traps.done is None:
            if key not in self.stored_data:
                return
            self.traps.set_done(int(self.stored_data.get(key) or 0))
        if not self.traps.pending:
            return

        rng = _random.Random()
        protected = {m.name for m in miis if m.name.startswith("Target ")}
        applied = 0
        while self.traps.pending:
            name = self.traps.pending.pop(0)
            applied += 1
            if name == "Tool Jam Trap":
                owned = [label for label, items in JAM_TARGETS.items()
                         if any(item in self.unlocked_items for item in items)]
                if not owned:
                    CommonClient.logger.info("Tool Jam Trap! ...but you have no tool to jam yet.")
                    continue
                label = rng.choice(owned)
                self.traps.jam(label)
                CommonClient.logger.info(
                    f"Tool Jam Trap! The {label} tool is locked for {int(TOOL_JAM_SECONDS)} seconds.")
            elif name in ("Paint Spill Trap", "Growth Spurt Trap"):
                victim = pick_victim(rng, miis, protected)
                if victim is None or not self.mii_db_path:
                    CommonClient.logger.info(f"{name}! ...but you have no Mii to hit.")
                    continue
                if name == "Paint Spill Trap":
                    field_name, value = paint_spill(rng, victim)
                    changes = {field_name: value}
                else:
                    changes = growth_spurt(rng, victim)
                for field_name, value in changes.items():
                    try:
                        write_mii_field(self.mii_db_path, victim.slot, field_name, value)
                    except Exception as e:
                        CommonClient.logger.warning(f"{name}: could not change {victim.name}: {e!r}")
                self._mirror_fields_in_ram(victim.name, changes)
                what = ", ".join(f"{field.replace(chr(95), chr(32))} {value}"
                                 for field, value in changes.items())
                CommonClient.logger.info(f"{name}! {victim.name} now has {what}.")
            else:
                CommonClient.logger.info(f"{name} received -- this client can't play it yet.")

        self.traps.done += applied
        Utils.async_start(self.send_msgs([{
            "cmd": "Set", "key": key, "default": 0, "want_reply": False,
            "operations": [{"operation": "replace", "value": self.traps.done}],
        }]))

    def _mirror_fields_in_ram(self, mii_name: str, changes: Dict[str, int]) -> None:
        """Same fields on the running game's copy of the Mii, so a trap shows
        without leaving the channel. Silent on failure: the save has it."""
        if _dme is None:
            return
        try:
            if not self._ensure_dme_hooked():
                return
            for entry_addr, _mii in find_mii_entries_by_name(read_wii_memory(_dme), mii_name):
                for field_name, value in changes.items():
                    write_mii_field_ram(_dme, entry_addr, field_name, value)
        except Exception as e:
            CommonClient.logger.debug(f"Could not mirror a trap into Dolphin: {e!r}")

    def _repoint_screen_messages(self) -> None:
        """Write SCREEN_TEXTS into the game's message file in RAM, once per
        boot: a text that fits replaces the message in place, a longer one
        goes into a donor message's room and the message is repointed."""
        import time as _time

        def u16(addr: int) -> int:
            return int.from_bytes(_dme.read_bytes(addr, 2), "big")

        def u32(addr: int) -> int:
            return int.from_bytes(_dme.read_bytes(addr, 4), "big")

        try:
            if self.bmg_addr is not None and _dme.read_bytes(self.bmg_addr, 8) != b"MESGbmg1":
                self.bmg_addr = None
            if self.bmg_addr is None:
                now = _time.monotonic()
                if now - self.bmg_checked_at < 5.0:
                    return
                self.bmg_checked_at = now
                for base in range(0x90000000, 0x94000000, 0x100000):
                    try:
                        found = _dme.read_bytes(base, 0x100000).find(b"MESGbmg1")
                    except Exception:
                        continue
                    if found != -1:
                        self.bmg_addr = base + found
                        break
                if self.bmg_addr is None:
                    return

            header = self.bmg_addr
            sections: Dict[bytes, int] = {}
            p = header + 0x20
            for _ in range(u32(header + 12)):
                sections[_dme.read_bytes(p, 4)] = p
                p += u32(p + 4)
            inf, dat, mid = sections[b"INF1"], sections[b"DAT1"], sections[b"MID1"]
            n, entry_size = u16(inf + 8), u16(inf + 10)
            mid_raw = _dme.read_bytes(mid + 0x10, u16(mid + 8) * 4)
            labels = ["%07d" % int.from_bytes(mid_raw[i:i + 4], "big") for i in range(0, len(mid_raw), 4)]
            index = {label: k for k, label in enumerate(labels[:n])}
            inf_raw = _dme.read_bytes(inf + 0x10, n * entry_size)
            offsets = [int.from_bytes(inf_raw[k * entry_size:k * entry_size + 4], "big") for k in range(n)]

            wanted = [(label, text.encode("utf-16-be", "replace") + b"\0\0")
                      for label, text in SCREEN_TEXTS.items()
                      if label in index and label not in BMG_SKIP_MESSAGES]
            # Already done on this boot (the client may have restarted)?
            for label, data in wanted:
                if _dme.read_bytes(dat + 8 + offsets[index[label]], len(data)) == data:
                    return

            ordered = sorted(set(offsets))

            def room(offset: int) -> int:
                later = [o for o in ordered if o > offset]
                return later[0] - offset if later else 0

            donors = [[offsets[index[d]], room(offsets[index[d]])]
                      for d in BMG_DONOR_MESSAGES if d in index]
            for label, data in wanted:
                k = index[label]
                if len(data) <= room(offsets[k]):
                    _dme.write_bytes(dat + 8 + offsets[k], data)
                    continue
                donor = next((d for d in donors if d[1] >= len(data)), None)
                if donor is None:
                    CommonClient.logger.debug(f"No room in the message file for {label}")
                    continue
                _dme.write_bytes(dat + 8 + donor[0], data)
                _dme.write_bytes(inf + 0x10 + k * entry_size, donor[0].to_bytes(4, "big"))
                used = len(data) + (len(data) & 1)
                donor[0] += used
                donor[1] -= used
        except Exception as e:
            CommonClient.logger.debug(f"Could not rewrite the screen messages: {e!r}")

    async def poll_mii_database(self) -> None:
        while not self.exit_event.is_set():
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            try:
                await self._poll_mii_database_once()
            except Exception as e:
                # This whole method runs as a long-lived background task --
                # an uncaught exception here would silently kill polling for
                # the rest of the session (this bit us once already: one bad
                # field write took down enforcement for every Mii after it).
                CommonClient.logger.warning(f"Mii Channel poll error (will retry): {e!r}")

    async def _poll_mii_database_once(self) -> None:
        if time.monotonic() < self.pause_polling_until:
            return

        if True:
            if not self.server or not self.slot:
                return

            if not self.mii_db_path:
                self.mii_db_path = find_rfl_db()
                if not self.mii_db_path:
                    if not self.could_not_find_file_logged:
                        CommonClient.logger.warning(
                            "Could not find RFL_DB.dat automatically. "
                            "Use /miipath <full path to RFL_DB.dat> to set it manually."
                        )
                        self.could_not_find_file_logged = True
                    return

            i: int
            network_item: Any
            for i, network_item in enumerate(self.items_received):
                if i in self.seen_item_indices:
                    continue
                self.seen_item_indices.add(i)
                name = _ID_TO_ITEM_NAME.get(network_item.item)
                if name in TRAP_ITEMS:
                    self.traps.receive(name)
                    continue
                if name:
                    self.unlocked_items.add(name)
                    if name in progressive_item_counts:
                        self.progressive_counts[name] = self.progressive_counts.get(name, 0) + 1

            try:
                all_miis: List[Mii] = read_miis(self.mii_db_path)
            except OSError as e:
                CommonClient.logger.debug(f"Could not read {self.mii_db_path}: {e!r}")
                return
            self._apply_traps(all_miis)

            # Target previews are synthetic Miis we write into RFL_DB.dat so
            # the player can see every target standing in the Plaza next to
            # their own Miis. They are permanent copies of a target's own
            # face, so they must never count toward milestones, matching, or
            # lock enforcement -- otherwise each one would trivially
            # "complete" its own target for free, and lock enforcement would
            # fight to revert its deliberately-target-matching fields.
            preview_names = {target_preview_name(i) for i in range(len(self.target_miis))}
            miis: List[Mii] = [m for m in all_miis if m.name not in preview_names]

            # Switched on mid-session (or previews came back): the move is only
            # safe while Dolphin is closed, so do it the moment it is.
            if (self.features["targets_in_parade"] and self.dolphin_launched
                    and preview_names & {m.name for m in all_miis}
                    and not self._dolphin_is_running()):
                self._move_targets_to_parade(preview_names)
                try:
                    all_miis = read_miis(self.mii_db_path)
                except OSError:
                    return
                miis = [m for m in all_miis if m.name not in preview_names]

            # (Re)write any preview that isn't in the file -- on first
            # connect, and again if the game ever purges them. This must NOT
            # wait for the player to own a Mii: write_synthetic_miis falls
            # back to its embedded template for an empty save, and a fresh
            # game with nothing in the Plaza is exactly when seeing the
            # targets matters most.
            # Rate-limited: while Dolphin is running it owns the file and
            # periodically writes its own in-memory list back, wiping
            # previews it didn't load at boot. Rewriting every tick would
            # just fight it (and churn slots); waiting instead lets the
            # previews land for good the next time the game starts.
            missing = preview_names - {m.name for m in all_miis}
            now = time.monotonic()
            if (missing and self.features["previews"] and not self.features["targets_in_parade"]
                    and now - self.last_preview_write >= PREVIEW_WRITE_COOLDOWN_SECONDS):
                self.last_preview_write = now
                try:
                    written = write_synthetic_miis(
                        self.mii_db_path,
                        [(target_preview_name(i), target) for i, target in enumerate(self.target_miis)],
                    )
                except OSError as e:
                    CommonClient.logger.debug(f"Could not write target previews: {e!r}")
                    written = []
                if written:
                    CommonClient.logger.info(
                        f"Wrote {len(written)} target Mii(s) into your Mii Plaza. "
                        f"They show up as 'Target 1'...'Target {len(written)}' -- "
                        f"recreate them to send checks."
                    )
                    try:
                        all_miis = read_miis(self.mii_db_path)
                        miis = [m for m in all_miis if m.name not in preview_names]
                    except OSError:
                        return

            # Start the game once per connection, after the previews above
            # have had their chance to land (a brand-new save has no Mii to
            # clone from yet, so this must not wait for them to succeed --
            # the player needs the game running to create that first Mii).
            if not self.dolphin_launched:
                # Before the game starts: it owns the file while running.
                # With Dolphin already up this can only be refused, so only say
                # so when there actually is something left to move.
                if self.features["targets_in_parade"] and (
                        not self._dolphin_is_running()
                        or preview_names & {m.name for m in all_miis}):
                    self._move_targets_to_parade(preview_names)
                self.dolphin_launched = True
                if self.features["autolaunch"]:
                    self._launch_dolphin()

            # Enforcement: revert any locked feature straight in RFL_DB.dat,
            # recomputing the file's CRC16 footer so it stays a fully valid
            # save (see mii_reader.crc16_ccitt -- verified against a real
            # Dolphin save). This is the reliable, guaranteed-to-land layer;
            # poll_ram_enforcement (below) additionally tries to catch it
            # live in Dolphin's RAM for a faster reaction when possible.
            #
            # IMPORTANT: this must run and land on disk BEFORE any match
            # checking below -- confirmed live (2026-09-02) that checking
            # matches against the same in-memory `miis` snapshot used here,
            # stale relative to the reverts just written, let a Mii using
            # entirely locked-and-not-yet-owned features get real, permanent
            # credit for a category/Perfect-Copy match for one tick, before
            # the next poll's fresh read caught up and reverted its fields
            # (and consequently its favorite star) back out from under it --
            # the check itself, already sent to the server, stayed granted.
            # `miis` is re-read from disk right after this loop specifically
            # to close that window.
            any_reverted = False
            for mii in (miis if self.features["file_locks"] else []):
                violations = find_violations(mii, self.unlocked_items, self.progressive_counts)
                for field_name, revert_value in violations.items():
                    try:
                        write_mii_field(self.mii_db_path, mii.slot, field_name, revert_value)
                        any_reverted = True
                        CommonClient.logger.info(
                            f"Blocked '{mii.name}' from using a locked feature ({field_name}) "
                            f"-- reverted in your save file."
                        )
                    except Exception as e:
                        # Catch everything (not just OSError): a single bad
                        # field must never silently kill the rest of this
                        # loop (or the whole poll task) for every other Mii
                        # and field still waiting to be reverted.
                        CommonClient.logger.warning(f"Could not revert {mii.name}/{field_name}: {e!r}")

            if any_reverted:
                try:
                    # Must re-apply the preview filter: previews are
                    # byte-perfect copies of their own target, so letting one
                    # back into `miis` here instantly "completes" that target
                    # for free -- confirmed live (2026-09-04), the previews
                    # got renamed to "Match N" and credited as if the player
                    # had recreated them.
                    miis = [m for m in read_miis(self.mii_db_path) if m.name not in preview_names]
                except OSError as e:
                    CommonClient.logger.debug(f"Could not re-read {self.mii_db_path} after enforcement: {e!r}")
                    return

            # is_favorite is a SYSTEM-controlled signal now (see Perfect
            # Copy reward below) -- it must not be player-toggleable, or
            # it stops meaning anything. Only slots that genuinely,
            # currently (post-enforcement) match some target in full are
            # allowed to stay favorited; anyone else's manual star gets
            # reverted straight back to unfavorited.
            # One Mii works on one target and vice versa (see
            # targets.assign_miis_to_targets) -- otherwise a single Mii
            # credits the same category on every target at once.
            now_touch = time.monotonic()
            for mii in miis:
                signature = tuple(
                    int(getattr(mii, field))
                    for fields in CATEGORY_FIELDS.values() for field in fields
                ) + (int(mii.height), int(mii.weight))
                if self.mii_signatures.get(mii.slot) != signature:
                    self.mii_signatures[mii.slot] = signature
                    self.mii_touched_at[mii.slot] = now_touch

            assignment = assign_miis_to_targets(miis, self.target_miis)

            favorited_slots_allowed: Set[int] = set()
            for target_index, target in enumerate(self.target_miis):
                assigned = assignment.get(target_index)
                if assigned is not None and mii_matches_target_fully(assigned, target):
                    favorited_slots_allowed.add(assigned.slot)

            for mii in (miis if self.features["favorite_guard"] else []):
                if mii.is_favorite and mii.slot not in favorited_slots_allowed:
                    try:
                        write_mii_field(self.mii_db_path, mii.slot, "is_favorite", 0)
                        CommonClient.logger.info(
                            f"'{mii.name}' isn't a completed Perfect Copy -- its favorite star "
                            f"is reserved for that, so it was reverted."
                        )
                    except Exception as e:
                        CommonClient.logger.warning(f"Could not revert {mii.name}'s favorite flag: {e!r}")

            newly_checked_ids: List[int] = []

            for name, predicate in MILESTONE_CHECKS:
                if name in self.checked_names:
                    continue

                if predicate(miis, self.miis_required):
                    self.checked_names.add(name)
                    newly_checked_ids.append(location_name_to_id[name])

            # Per-target-per-category checks: for each target Mii recipe
            # (frozen at generation, received via slot_data), one check per
            # face-part category (all sub-fields must match exactly on at
            # least one of the player's current Miis) plus one for
            # height+weight together. See targets.py for the match logic.
            # "Perfect Copy" is stricter: it only fires when a SINGLE Mii
            # matches every category and body field at once (a genuine
            # complete recreation), not accumulated one category at a time
            # possibly across different Miis.
            for target_index, target in enumerate(self.target_miis):
                assigned = assignment.get(target_index)
                if assigned is None:
                    continue

                for category in TARGET_CHECK_CATEGORIES:
                    name = target_location_name(target_index, category)
                    if name in self.checked_names:
                        continue

                    matched = (
                        body_matches(assigned, target)
                        if category == "Body"
                        else category_matches(assigned, target, category)
                    )
                    if matched:
                        self.checked_names.add(name)
                        newly_checked_ids.append(location_name_to_id[name])

                perfect_name = target_location_name(target_index, PERFECT_COPY_CATEGORY)
                if perfect_name not in self.checked_names:
                    winning_mii = assigned if mii_matches_target_fully(assigned, target) else None
                    if winning_mii is not None:
                        self.checked_names.add(perfect_name)
                        newly_checked_ids.append(location_name_to_id[perfect_name])
                        # Permanent, all-in-game visual reward -- no client
                        # needed to see it: mark the Mii with a star (see
                        # is_favorite enforcement below, which is what keeps
                        # this meaningful instead of player-toggleable) and
                        # rename it to show which target it completed, since
                        # the star alone doesn't carry a number.
                        badge = f"{PERFECT_COPY_NAME_PREFIX}{target_index + 1}"
                        try:
                            write_mii_creator(self.mii_db_path, winning_mii.slot, badge)
                            write_mii_field(self.mii_db_path, winning_mii.slot, "is_favorite", 1)
                            self._update_creator_in_ram(winning_mii.name, badge)
                            CommonClient.logger.info(
                                f"'{winning_mii.name}' is a perfect copy of Target {target_index + 1}! "
                                f"Badged '{badge}' and marked as a favorite."
                            )
                        except Exception as e:
                            CommonClient.logger.warning(f"Could not apply Perfect Copy reward: {e!r}")

            if self.features["badges"]:
                self._update_progress_names(miis, assignment)
            self.cached_miis = miis
            self.cached_assignment = assignment
            if self.features["wc24_rows"]:
                self._update_todo_rows(miis, assignment)

            # Victory once every check for every target has been completed
            # (every category, body, AND the strict Perfect Copy check).
            if VICTORY_NAME not in self.checked_names and self.target_miis:
                all_targets_recreated = all(
                    target_location_name(target_index, category) in self.checked_names
                    for target_index in range(len(self.target_miis))
                    for category in TARGET_CHECK_CATEGORIES_ALL
                )
                if all_targets_recreated:
                    self.checked_names.add(VICTORY_NAME)
                    newly_checked_ids.append(location_name_to_id[VICTORY_NAME])
                    self.goaled = True

            if newly_checked_ids:
                await self.check_locations(newly_checked_ids)

            if self.goaled:
                await self.send_msgs([
                    {"cmd": "StatusUpdate", "status": CommonClient.ClientStatus.CLIENT_GOAL}
                ])

    async def poll_ram_enforcement(self) -> None:
        """Continuously watch Dolphin's live RAM (not the save file) for any
        Mii using a locked feature, and revert it in-place the moment it's
        committed -- well before the game ever writes it to RFL_DB.dat.
        """
        if _dme is None:
            if not self.dme_missing_warned:
                CommonClient.logger.warning(
                    "dolphin_memory_engine not available -- live in-game blocking is "
                    "disabled, falling back to save-file warnings only."
                )
                self.dme_missing_warned = True
            return

        while not self.exit_event.is_set():
            await asyncio.sleep(RAM_ENFORCE_INTERVAL_SECONDS)

            if not self.server or not self.slot or not self.mii_db_path:
                continue

            if not self._ensure_dme_hooked():
                if True:
                    if not self.dme_hook_warned:
                        CommonClient.logger.warning(
                            "Couldn't hook into Dolphin's memory -- make sure Dolphin is "
                            "running with a title loaded. Retrying in the background."
                        )
                        self.dme_hook_warned = True
                    continue
                self.dme_hook_warned = False

            try:
                miis: List[Mii] = read_miis(self.mii_db_path)
            except OSError:
                continue

            preview_names = {target_preview_name(i) for i in range(len(self.target_miis))}
            names = {mii.name for mii in miis if mii.name and mii.name not in preview_names}
            if not names:
                continue

            try:
                chunks = read_wii_memory(_dme)
            except Exception:
                continue

            for name in names:
                try:
                    live_entries = find_mii_entries_by_name(chunks, name)
                except Exception:
                    continue

                for entry_addr, live_mii in live_entries:
                    violations = find_violations(live_mii, self.unlocked_items, self.progressive_counts)
                    for field_name, revert_value in violations.items():
                        try:
                            write_mii_field_ram(_dme, entry_addr, field_name, revert_value)
                            CommonClient.logger.info(
                                f"Blocked '{name}' from using a locked feature ({field_name}) "
                                f"-- reverted live in Dolphin's RAM."
                            )
                        except Exception as e:
                            CommonClient.logger.warning(f"RAM revert failed for {name}/{field_name}: {e!r}")

    def _refresh_restore_values(self) -> None:
        """Keep the V9 trampoline's restore table pointing at the right values.

        The trampoline can only put back a value someone hands it, and the
        right value is whatever the Mii had when the editor opened: the saved
        one for an existing Mii, the game's own starting values for a new one.
        Rather than work out which Mii is being edited -- the live edit struct
        carries no name or id -- take the snapshot on the tick the editor
        opens, when what's in the struct IS still the saved state. The
        heartbeat makes that tick observable.
        """
        try:
            heartbeat = int.from_bytes(_dme.read_bytes(EDITOR_HEARTBEAT_ADDR, 4), "big")
        except Exception:
            return

        editing = self.last_editor_heartbeat is not None and heartbeat != self.last_editor_heartbeat
        just_opened = editing and not self.editor_was_open
        self.last_editor_heartbeat = heartbeat
        self.editor_was_open = editing
        if not just_opened:
            return

        try:
            struct_addr = int.from_bytes(_dme.read_bytes(EDIT_STRUCT_PTR_ADDR, 4), "big")
            if not (0x80000000 <= struct_addr < 0x81800000
                    or 0x90000000 <= struct_addr < 0x94000000):
                CommonClient.logger.debug(
                    f"Editor opened but the struct pointer looks wrong ({struct_addr:#010x}) "
                    "-- leaving the restore table alone.")
                return

            words = {}
            for _name, _off, word_off, _start, _width in RESTORE_VALUE_FIELDS:
                if word_off not in words:
                    words[word_off] = int.from_bytes(
                        _dme.read_bytes(struct_addr + word_off, 4), "big")

            table = bytearray(len(RESTORE_VALUE_FIELDS))
            for _name, off, word_off, start, width in RESTORE_VALUE_FIELDS:
                # start counts from the MSB of the 32-bit word, matching
                # mii_reader.FIELD_SPECS and the trampoline's rlwimi masks.
                shift = 32 - start - width
                table[off] = (words[word_off] >> shift) & ((1 << width) - 1)

            _dme.write_bytes(RESTORE_VALUE_TABLE_ADDR, bytes(table))
            CommonClient.logger.debug(
                f"Editor opened -- captured restore values {list(table)}")
        except Exception as e:
            CommonClient.logger.debug(f"Restore-value snapshot failed (will retry): {e!r}")

    async def poll_asm_lock_bitmask(self) -> None:
        """Keep the injected ASM trampoline's eye-page lock bitmask in sync
        with which items the player actually owns. This drives real-time,
        same-frame enforcement (a locked page's pick reverts before the
        player can even leave the category screen), on top of -- not a
        replacement for -- the save-file correction in poll_mii_database.

        Requires the Gecko code in the dedicated profile's
        GameSettings\\HACA01.ini to be active (EnableCheats=True in
        Dolphin.ini) with the multi-category trampoline deployed. All 9
        face-part categories are covered: eye, eyebrow, hair, nose, mouth,
        face shape, skin tone, glasses, and facial hair (mustache+beard
        share one item), plus mole. See reference_mii_channel_re_facts
        memory for the full per-category field offsets/tables.
        """
        if _dme is None:
            if not self.asm_dme_missing_warned:
                CommonClient.logger.warning(
                    "dolphin_memory_engine not available -- real-time ASM-level "
                    "blocking is disabled, falling back to save-file correction only."
                )
                self.asm_dme_missing_warned = True
            return

        while not self.exit_event.is_set():
            await asyncio.sleep(ASM_LOCK_BITMASK_INTERVAL_SECONDS)

            if not self.server or not self.slot:
                continue

            if not self._ensure_dme_hooked():
                if True:
                    if not self.asm_dme_hook_warned:
                        CommonClient.logger.warning(
                            "Couldn't hook into Dolphin's memory for ASM-level "
                            "blocking -- make sure Dolphin is running with a title "
                            "loaded. Retrying in the background."
                        )
                        self.asm_dme_hook_warned = True
                    continue
                self.asm_dme_hook_warned = False

            if self.features["restore_values"]:
                self._refresh_restore_values()

            # All-or-nothing per category for now (matches the current item
            # model: one gating item per category, not per-page items) --
            # 0xFF sets every page of that category unlocked, 0x00 locks
            # them all (only the low 4-6 bits the trampoline actually checks
            # matter; the rest are simply never tested). Add one line per
            # category as more trampoline blocks are deployed (see
            # reference_mii_channel_re_facts memory for the per-category
            # field offsets/tables).
            # Eye/eyebrow/mouth type-unlock is now progressive: each copy of
            # "Progressive X Editor" received unlocks the NEXT page in order
            # (page 0 first, no skipping ahead) -- (1 << count) - 1 sets
            # exactly the low `count` bits, i.e. pages 0..count-1. A count
            # higher than the category's real page count is harmless (those
            # extra bits are never tested by the trampoline); capped to 8
            # bits regardless since the scratch byte is one byte wide.
            def _progressive_bitmask(item_name: str) -> int:
                count = self.progressive_counts.get(item_name, 0)
                return ((1 << min(count, 8)) - 1) & 0xFF

            eye_bitmask = _progressive_bitmask("Progressive Eye Editor")
            eyebrow_bitmask = _progressive_bitmask("Progressive Eyebrow Editor")
            mouth_bitmask = _progressive_bitmask("Progressive Mouth Editor")
            nose_bitmask = 0x01 if "Nose Editor" in self.unlocked_items else 0x00

            # Hairstyle packs are ALSO progressive within themselves (each
            # copy of "Progressive Hairstyle: Classic"/"Wild" unlocks the
            # next of its own 3 pages, in order) -- Classic occupies bits
            # 0-2 of the shared hair bitmask, Wild occupies bits 3-5.
            classic_count = self.progressive_counts.get("Progressive Hairstyle: Classic", 0)
            wild_count = self.progressive_counts.get("Progressive Hairstyle: Wild", 0)
            hair_bitmask = (
                (((1 << min(classic_count, 3)) - 1) & 0x07)
                | ((((1 << min(wild_count, 3)) - 1) & 0x07) << 3)
            )

            # One scratch byte still covers the whole r6+0 halfword, which
            # holds face shape AND the makeup marks, so it opens as soon as
            # either item has arrived; the save-file layer applies the real
            # per-item limits a moment later (same coarser-ASM tradeoff as
            # every other partial unlock here).
            face_shape_bitmask = (
                0x01
                if {"Face Shape Tool", "Makeup Kit"} & self.unlocked_items
                else 0x00
            )
            skin_tone_bitmask = 0x01 if "Skin Tone Palette" in self.unlocked_items else 0x00
            glasses_bitmask = 0x01 if "Glasses Case" in self.unlocked_items else 0x00
            mole_bitmask = 0x01 if "Mole Marker" in self.unlocked_items else 0x00
            # Mustache and beard are two separate trampoline blocks (they
            # occupy different bit ranges of the same live word) but share a
            # single gating item -- "Facial Hair Kit" -- matching
            # locks.py's ITEM_FIELD_LOCKS, which locks both together.
            facial_hair_bitmask = 0x01 if "Facial Hair Kit" in self.unlocked_items else 0x00

            def _b(item_name: str) -> int:
                return 0x01 if item_name in self.unlocked_items else 0x00

            # Archipelago texts on the game's screens ("?", mode banners...).
            # Rewritten whenever RAM lost them (the game clears this area
            # while it boots). Buffers first, table last: the table is what
            # makes the game use them.
            try:
                table, buffers = _screen_text_blobs()
                if (_dme.read_bytes(TEXT_TABLE_ADDR, len(table)) != table
                        or _dme.read_bytes(TEXT_BUFFER_BASE, 0x20) != buffers[:0x20]):
                    _dme.write_bytes(TEXT_BUFFER_BASE, buffers)
                    _dme.write_bytes(TEXT_TABLE_ADDR, table)
            except Exception as e:
                CommonClient.logger.debug(f"Could not write the screen texts: {e!r}")
            self._repoint_screen_messages()

            for addr, bitmask, label in (
                (EYE_LOCK_BITMASK_ADDR, eye_bitmask, "eye"),
                (EYEBROW_LOCK_BITMASK_ADDR, eyebrow_bitmask, "eyebrow"),
                (HAIR_LOCK_BITMASK_ADDR, hair_bitmask, "hair"),
                (NOSE_LOCK_BITMASK_ADDR, nose_bitmask, "nose"),
                (MOUTH_LOCK_BITMASK_ADDR, mouth_bitmask, "mouth"),
                (FACE_SHAPE_LOCK_BITMASK_ADDR, face_shape_bitmask, "face shape"),
                (SKIN_TONE_LOCK_BITMASK_ADDR, skin_tone_bitmask, "skin tone"),
                (GLASSES_LOCK_BITMASK_ADDR, glasses_bitmask, "glasses"),
                (MUSTACHE_LOCK_BITMASK_ADDR, facial_hair_bitmask, "mustache"),
                (BEARD_LOCK_BITMASK_ADDR, facial_hair_bitmask, "beard"),
                (MOLE_LOCK_BITMASK_ADDR, mole_bitmask, "mole"),
                (EYE_COLOR_LOCK_BITMASK_ADDR, _b("Eye Color"), "eye color"),
                (EYE_MOVEMENT_LOCK_BITMASK_ADDR, _b("Eye Movement"), "eye movement"),
                (EYEBROW_COLOR_LOCK_BITMASK_ADDR, _b("Eyebrow Color"), "eyebrow color"),
                # This one used to be pinned unlocked: the ASM layer zeroed a
                # locked field, and eyebrow_vert_pos rejects 0 (its range
                # starts at 3 -- FIELD_MIN, established live), so saving froze
                # the game. The V8b trampoline now writes the real defaults
                # for this category instead of zeroes, so the lock can be
                # enforced in real time like every other one.
                (EYEBROW_MOVEMENT_LOCK_BITMASK_ADDR, _b("Eyebrow Movement"), "eyebrow movement"),
                (HAIR_COLOR_LOCK_BITMASK_ADDR, _b("Hair Color"), "hair color"),
                (NOSE_MOVEMENT_LOCK_BITMASK_ADDR, _b("Nose Movement"), "nose movement"),
                (MOUTH_COLOR_LOCK_BITMASK_ADDR, _b("Mouth Color"), "mouth color"),
                (MOUTH_MOVEMENT_LOCK_BITMASK_ADDR, _b("Mouth Movement"), "mouth movement"),
                (GLASSES_COLOR_LOCK_BITMASK_ADDR, _b("Glasses Color"), "glasses color"),
                (GLASSES_MOVEMENT_LOCK_BITMASK_ADDR, _b("Glasses Movement"), "glasses movement"),
                (FACIAL_HAIR_COLOR_LOCK_BITMASK_ADDR, _b("Facial Hair Color"), "facial hair color"),
                (FACIAL_HAIR_MOVEMENT_LOCK_BITMASK_ADDR, _b("Facial Hair Movement"), "facial hair movement"),
                (MOLE_MOVEMENT_LOCK_BITMASK_ADDR, _b("Mole Movement"), "mole movement"),
            ):
                try:
                    # asm_locks off = every byte 0xFF, i.e. the trampoline
                    # still runs but never reverts anything. (Simply not
                    # writing would leave RAM at its boot value, 0 = all
                    # locked -- the opposite of switching the layer off.)
                    if self.traps.is_jammed(label):
                        bitmask = 0x00          # Tool Jam Trap: locked again for a while
                    _dme.write_bytes(addr, bytes([bitmask if self.features["asm_locks"] else 0xFF]))
                except Exception as e:
                    CommonClient.logger.debug(f"ASM lock-bitmask write failed for {label} (will retry): {e!r}")
                    # Tried calling _dme.un_hook() here to auto-recover from
                    # dolphin_memory_engine's is_hooked() staying True after
                    # the hooked Dolphin process is replaced by a new one --
                    # made things WORSE in practice (a live test showed it
                    # gets stuck in a permanent hook/un-hook thrash that
                    # never stabilizes, confirmed by the fact a real client
                    # process restart fixed it instantly when the un_hook
                    # loop alone couldn't). Reverted. The reliable fix
                    # remains: restart this client after every Dolphin
                    # restart (see reference_mii_channel_re_facts memory).


def main(*args) -> None:
    Utils.init_logging("MiiChannelClient", exception_logger="Client")

    parser = CommonClient.get_base_parser(description="Mii Channel Client")
    parser.add_argument("url", nargs="?", help="Archipelago Connection URL")
    parser.add_argument("--name", default=None, help="Archipelago Slot Name")

    parsed_args = parser.parse_args(args)

    if parsed_args.url:
        url = urllib.parse.urlparse(parsed_args.url)
        parsed_args.connect = url.netloc
        if url.username:
            parsed_args.name = urllib.parse.unquote(url.username)
        if url.password:
            parsed_args.password = urllib.parse.unquote(url.password)

    async def _main(args_) -> None:
        ctx = MiiChannelContext(args_.connect, args_.password)

        if args_.name:
            ctx.auth = args_.name

        ctx.server_task = asyncio.create_task(CommonClient.server_loop(ctx), name="server loop")
        ctx.poll_task = asyncio.create_task(ctx.poll_mii_database(), name="MiiChannelPoll")
        # poll_ram_enforcement (continuous live-RAM patch of the *committed*
        # post-save struct) stays disabled: patching that struct doesn't
        # affect the live preview or the eventual save (confirmed this
        # session -- see reference_mii_channel_re_facts memory), and poking
        # it while Dolphin is actively rendering that Mii risks desyncing
        # the running session. The file-based correction in
        # poll_mii_database remains the reliable layer for that struct.
        # ctx.ram_poll_task = asyncio.create_task(ctx.poll_ram_enforcement(), name="MiiChannelRAMEnforce")
        #
        # poll_asm_lock_bitmask IS enabled: this drives the injected Gecko-
        # code trampoline (GameSettings\HACA01.ini, hooked at FUN_8003bd68),
        # which reverts a locked eye page's pick in the game's *live-edit*
        # struct (r6+4) every frame -- confirmed this session to actually
        # feed the save, and to have an immediate visible in-game effect
        # (unlike the struct poll_ram_enforcement targets). Requires
        # EnableCheats=True in the dedicated profile's Dolphin.ini and the
        # eye trampoline to be the currently-deployed Gecko code; degrades
        # gracefully (falls back to save-file correction only) if Dolphin
        # or dolphin_memory_engine isn't available.
        ctx.asm_lock_task = asyncio.create_task(ctx.poll_asm_lock_bitmask(), name="MiiChannelASMLock")
        ctx.selected_task = asyncio.create_task(ctx.poll_selected_mii(), name="MiiChannelSelectedMii")

        if CommonClient.gui_enabled:
            ctx.run_gui()

        ctx.run_cli()

        await ctx.exit_event.wait()
        await ctx.shutdown()

    import colorama
    colorama.just_fix_windows_console()

    asyncio.run(_main(parsed_args))

    colorama.deinit()


if __name__ == "__main__":
    main(*sys.argv[1:])
