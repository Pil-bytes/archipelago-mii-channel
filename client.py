import asyncio
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Set

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
from .locks import find_violations
from .mii_reader import (
    Mii,
    claim_target_preview,
    find_mii_entries_by_name,
    find_rfl_db,
    read_miis,
    read_wii_memory,
    write_mii_field,
    write_mii_field_ram,
)
from .targets import (
    ALL_TARGET_FIELDS,
    BODY_FIELDS,
    CATEGORY_FIELDS,
    any_mii_matches_body,
    any_mii_matches_category,
    any_mii_matches_target_fully,
    target_preview_name,
)

POLL_INTERVAL_SECONDS = 1.0
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
# NOTE: renumbered twice as the trampoline grew (0x1100 range -> 0x1200
# range -> now 0x1400 range) -- adding face-shape + category-8
# (glasses/mustache/beard/mole) pushed the trampoline body to
# 0x803C1000-0x803C1238, so the whole scratch region moved to 0x1400+ with
# generous headroom (not just re-checked to barely clear) rather than risk
# a third collision, the exact class of bug that crashed Dolphin once
# already this project at 0x803C1040. Any future category addition must
# still re-check the trampoline's current end address before extending this
# region further.
EYE_LOCK_BITMASK_ADDR = 0x803C1400
EYE_PAGE_COUNT = 4  # eye_type 0-47, 12 per page (DAT_80207118 page table)

# Eyebrow category, same mechanism, same trampoline (chained after the eye
# block, no interference confirmed live). Page count assumed 12/page like
# eyes (DAT_80207148 table, same divide-by-0xc pattern in the trampoline) --
# not independently re-verified, revisit if lock behavior looks off for a
# specific eyebrow_type range.
EYEBROW_LOCK_BITMASK_ADDR = 0x803C1401
EYEBROW_PAGE_COUNT = 4

# Hair category: hair_type is gated by TWO progressive lines (Progressive
# Hairstyle: Classic covers types 0-35 = pages 0-2, Wild covers 36-71 =
# pages 3-5, using the same 12-per-page convention confirmed universal
# across every paginated category in FUN_8003bda4's decompile -- 72 types /
# 12 = 6 pages, matching locks.py's HAIRSTYLE_CLASSIC_MAX=35 split exactly
# at the page-3 boundary). Revert-to-0 when locked. Each line unlocks its
# own 3 pages one at a time, in order (see poll_asm_lock_bitmask).
HAIR_LOCK_BITMASK_ADDR = 0x803C1402

# Nose category: single-page in-game (no DAT_xxx page table used by
# FUN_8003bda4's case 6 at all -- "FUN_8003df28, 1 slot, no loop"), so the
# trampoline treats this scratch byte as a plain locked(0)/unlocked(nonzero)
# flag rather than a per-page bitmask.
NOSE_LOCK_BITMASK_ADDR = 0x803C1403

# Mouth category: paginated like eye/eyebrow/hair (DAT_80207170 table, same
# /12 convention). Page count not pinned down exactly; matching eye/
# eyebrow's existing all-or-nothing usage (0xFF/0x00) sidesteps needing it.
MOUTH_LOCK_BITMASK_ADDR = 0x803C1404

# Face shape category (compound, single-page): case 2 in FUN_8003bda4 packs
# face_shape + skin_color + facial_feature into one r6+0 halfword, but
# "Face Shape Tool" only gates face_shape+facial_feature -- skin_color is
# gated separately by "Skin Tone Palette". Two independent scratch bytes,
# same locked(0)/unlocked(nonzero) convention as nose.
FACE_SHAPE_LOCK_BITMASK_ADDR = 0x803C1405
SKIN_TONE_LOCK_BITMASK_ADDR = 0x803C1406

# Category 8 (glasses/mustache/beard/mole): four independent single-page
# fields, no DAT_xxx table for any of them. Mustache and beard share the
# same r6+16 halfword (different bit ranges) but still get independent
# scratch bytes/lock checks.
GLASSES_LOCK_BITMASK_ADDR = 0x803C1407
MUSTACHE_LOCK_BITMASK_ADDR = 0x803C1408
BEARD_LOCK_BITMASK_ADDR = 0x803C1409
MOLE_LOCK_BITMASK_ADDR = 0x803C140A

# Color and movement (size/rotation/position) real-time locks, independent
# of whichever type pages are unlocked -- one scratch byte per lock item,
# same locked(0)/unlocked(nonzero) flag convention as the single-page type
# locks (nose etc.). Only categories that actually have a color and/or
# movement sub-field get one (nose/mole have no color; face shape and skin
# tone have neither).
EYE_COLOR_LOCK_BITMASK_ADDR = 0x803C140B
EYE_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C140C
EYEBROW_COLOR_LOCK_BITMASK_ADDR = 0x803C140D
EYEBROW_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C140E
HAIR_COLOR_LOCK_BITMASK_ADDR = 0x803C140F
NOSE_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1410
MOUTH_COLOR_LOCK_BITMASK_ADDR = 0x803C1411
MOUTH_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1412
GLASSES_COLOR_LOCK_BITMASK_ADDR = 0x803C1413
GLASSES_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1414
FACIAL_HAIR_COLOR_LOCK_BITMASK_ADDR = 0x803C1415
FACIAL_HAIR_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1416
MOLE_MOVEMENT_LOCK_BITMASK_ADDR = 0x803C1417

try:
    import dolphin_memory_engine as _dme
except ImportError:
    _dme = None

_ID_TO_ITEM_NAME: Dict[int, str] = {data.code: name for name, data in item_table.items()}


class MiiChannelCommandProcessor(CommonClient.ClientCommandProcessor):
    ctx: "MiiChannelContext"

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
        full field recipe -- there's no in-game panel showing these yet
        (planned for later), so this is the only way to see what to build
        in the editor until then."""
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
            f"{len(self.ctx.target_miis)} target Mii(s). Use /targets <n> to see one's recipe, "
            f"/claim <n> <your Mii's name> to turn one of your real Miis into a permanent preview."
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
            preview = " [preview claimed]" if target_preview_name(i) in existing_names else ""
            CommonClient.logger.info(
                f"Target {i + 1}: {matched}/{len(TARGET_CHECK_CATEGORIES)} categories matched"
                f"{' -- PERFECT COPY DONE' if perfect_done else ''}{preview}"
            )
        return True

    def _cmd_claim(self, index: str = "", mii_name: str = "") -> bool:
        """Permanently turn one of your real, already-created Miis into a
        preview of a target -- renames it and overwrites its face to match
        the target, so it shows up in-game (e.g. via Wii Friend) as a
        reference for what to build. THIS PERMANENTLY REPLACES that Mii's
        face (only its identity survives) -- pick a Mii you don't mind
        sacrificing, not one you're actively using for an attempt. Usage:
        /claim <target number> <exact name of your Mii>"""
        if not self.ctx.target_miis:
            CommonClient.logger.info("No targets loaded yet -- connect to a server first.")
            return True
        if not index or not mii_name:
            CommonClient.logger.info("Usage: /claim <target number> <exact name of your Mii>")
            return True
        try:
            i = int(index) - 1
        except ValueError:
            CommonClient.logger.info("Usage: /claim <target number> <exact name of your Mii>")
            return True
        if not (0 <= i < len(self.ctx.target_miis)):
            CommonClient.logger.info(f"Target must be between 1 and {len(self.ctx.target_miis)}.")
            return True
        if not self.ctx.mii_db_path:
            self.ctx.mii_db_path = find_rfl_db()
        if not self.ctx.mii_db_path:
            CommonClient.logger.info("Could not locate RFL_DB.dat.")
            return True

        new_name = target_preview_name(i)
        try:
            found = claim_target_preview(self.ctx.mii_db_path, mii_name, new_name, self.ctx.target_miis[i])
        except Exception as e:
            CommonClient.logger.warning(f"Could not claim '{mii_name}' as a preview: {e!r}")
            return True

        if not found:
            CommonClient.logger.info(f"No Mii named '{mii_name}' found -- check the exact spelling.")
            return True

        CommonClient.logger.info(
            f"'{mii_name}' is now permanently '{new_name}', matching Target {i + 1}'s face. "
            f"Restart Dolphin to see it in-game (e.g. via Wii Friend)."
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
        self.could_not_find_file_logged = False
        self.unlocked_items = set()
        self.progressive_counts = {}
        self.seen_item_indices = set()
        self.dme_missing_warned = False
        self.dme_hook_warned = False
        self.asm_dme_missing_warned = False
        self.asm_dme_hook_warned = False

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)

        await self.get_username()
        await self.send_connect()

    async def disconnect(self, allow_autoreconnect: bool = False):
        self.checked_names = set()
        self.goaled = False
        await super().disconnect(allow_autoreconnect)

    def on_package(self, cmd: str, args: Any) -> None:
        if cmd == "Connected":
            slot_data: Dict[str, Any] = args.get("slot_data") or {}
            self.miis_required = slot_data.get("miis_required", 10)
            self.target_miis = slot_data.get("target_miis", [])

            CommonClient.logger.info(
                f"{len(self.target_miis)} target Mii(s) loaded. Use /targets to see them, and "
                f"/claim <n> <your Mii's name> to turn a real Mii into an in-game preview of one."
            )

            Utils.async_start(
                self.send_msgs([
                    {"cmd": "StatusUpdate", "status": CommonClient.ClientStatus.CLIENT_PLAYING}
                ])
            )

        super().on_package(cmd, args)

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
                if name:
                    self.unlocked_items.add(name)
                    if name in progressive_item_counts:
                        self.progressive_counts[name] = self.progressive_counts.get(name, 0) + 1

            try:
                all_miis: List[Mii] = read_miis(self.mii_db_path)
            except OSError as e:
                CommonClient.logger.debug(f"Could not read {self.mii_db_path}: {e!r}")
                return

            # Target-preview placeholders (claimed via /claim) are permanent
            # copies of a target's own face -- they must never count toward
            # milestones, matching, or lock enforcement, or the moment one
            # is claimed it would trivially "complete" that exact target for
            # free (and lock enforcement would fight to revert its
            # deliberately-target-matching fields back to defaults).
            preview_names = {target_preview_name(i) for i in range(len(self.target_miis))}
            miis: List[Mii] = [m for m in all_miis if m.name not in preview_names]

            # Enforcement: revert any locked feature straight in RFL_DB.dat,
            # recomputing the file's CRC16 footer so it stays a fully valid
            # save (see mii_reader.crc16_ccitt -- verified against a real
            # Dolphin save). This is the reliable, guaranteed-to-land layer;
            # poll_ram_enforcement (below) additionally tries to catch it
            # live in Dolphin's RAM for a faster reaction when possible.
            for mii in miis:
                violations = find_violations(mii, self.unlocked_items)
                for field_name, revert_value in violations.items():
                    try:
                        write_mii_field(self.mii_db_path, mii.slot, field_name, revert_value)
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
                for category in TARGET_CHECK_CATEGORIES:
                    name = target_location_name(target_index, category)
                    if name in self.checked_names:
                        continue

                    matched = (
                        any_mii_matches_body(miis, target)
                        if category == "Body"
                        else any_mii_matches_category(miis, target, category)
                    )
                    if matched:
                        self.checked_names.add(name)
                        newly_checked_ids.append(location_name_to_id[name])

                perfect_name = target_location_name(target_index, PERFECT_COPY_CATEGORY)
                if perfect_name not in self.checked_names and any_mii_matches_target_fully(miis, target):
                    self.checked_names.add(perfect_name)
                    newly_checked_ids.append(location_name_to_id[perfect_name])

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

            if not _dme.is_hooked():
                try:
                    _dme.hook()
                except Exception:
                    pass
                if not _dme.is_hooked():
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
                    violations = find_violations(live_mii, self.unlocked_items)
                    for field_name, revert_value in violations.items():
                        try:
                            write_mii_field_ram(_dme, entry_addr, field_name, revert_value)
                            CommonClient.logger.info(
                                f"Blocked '{name}' from using a locked feature ({field_name}) "
                                f"-- reverted live in Dolphin's RAM."
                            )
                        except Exception as e:
                            CommonClient.logger.warning(f"RAM revert failed for {name}/{field_name}: {e!r}")

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

            if not _dme.is_hooked():
                try:
                    _dme.hook()
                except Exception:
                    pass
                if not _dme.is_hooked():
                    if not self.asm_dme_hook_warned:
                        CommonClient.logger.warning(
                            "Couldn't hook into Dolphin's memory for ASM-level "
                            "blocking -- make sure Dolphin is running with a title "
                            "loaded. Retrying in the background."
                        )
                        self.asm_dme_hook_warned = True
                    continue
                self.asm_dme_hook_warned = False

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

            face_shape_bitmask = 0x01 if "Face Shape Tool" in self.unlocked_items else 0x00
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
                    _dme.write_bytes(addr, bytes([bitmask]))
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
