"""Locked zones of the Mii editor under a grey veil with one dark padlock
(user requests 2026-09-15: "une zone grisee, et le cadenas au dessus ... il
faut mettre le cadenas qu'une fois", "le cadenas fonce partout", and hovered
items must not draw over it).

No pane is created. Each editor tab is a window; only the current tab's
window is visible, the others are hidden (flag bit 0 clear, moved off
screen). For each locked zone on screen (a grid page, a colour palette, a
movement button block) the overlay borrows a simple icon picture from one of
the HIDDEN windows -- a movement icon: I4 texture, coloured by its vertex
colours, alpha = intensity, so the padlock is dark -- moves it to the end of
the visible window's child list (drawn after everything in the window,
hovered grid cells included), stretches it over the zone's bounding box and
points it at our texture: a translucent veil with an opaque padlock and a
clear keyhole, I4 64x64 in MEM1. Texture coordinates beyond 0..1 keep the
padlock square in the middle; the texture is clamped, so its veil border
fills the rest. Nothing of the visible tab is touched, and the icon goes back
to its own window with its own values as soon as the zone unlocks or leaves
the screen.

The lists are edited in an order that keeps every forward walk valid at each
step (the game walks them while we write): unlink = prev.next first, then
next.prev; link = the node's own links first, then tail.next, then
sentinel.prev.

nw4r lyt objects, as measured live in the channel (2026-09-15):
  pane      +0x00 vtable (0x8025c17c window, 0x8025c058 picture,
            0x8025bfa8 null), +0x04 list node {next, prev} (nodes point at
            node addresses), +0x0C parent, +0x10 child count, +0x14 children
            sentinel node, +0x28 material, +0x2C translate, +0x44 scale,
            +0x4C size, +0xB4 name, +0xCD alpha, +0xCF flags (bit 0 visible)
  picture   +0xD4 vertex colours x4, +0xE5 tex coord count, +0xE8 tex coords
            (4 x VEC2: TL, TR, BL, BR)
  material  +0x50 GX data counts (top nibble = texture maps), +0x58 GX data,
            which starts with the GXTexObj: +0x00 filter/wrap bits (low
            nibble = wrap S/T, 0 = clamp), +0x08 fmt<<20 | (h-1)<<10 | (w-1),
            +0x0C image physical address >> 5, +0x14 format again
"""
import struct
from typing import Dict, List, Optional, Tuple

INTERVAL_SECONDS = 0.5

LOCK_BASE = 0x803C1600          # client lock bytes, bit n = page n unlocked
LOCK_COUNT = 0x18
TEX_ADDR = 0x803C9E00           # 0x800 bytes, next to the Gecko blocks
TEX_BYTES = 0x800
OLD_TEX_ADDRS = (0x803C9E00, 0x803CA600)   # anything pointing here is ours
# Veils currently lent out, read by the Gecko block "Editor veils stay on
# top" (Tools/ghidra_scripts/BuildVeilOnTop.java): whenever the game brings a
# hovered element to the front of a list, it moves the veils of that same
# list back to the end in the same frame. 8 pane pointers, 0 = empty.
VEIL_TABLE_ADDR = 0x803CB100
VEIL_SLOTS = 8
# Groups of the locked zones on screen, read by the Gecko block "Locked
# zones: no hover" (BuildLockedNoHover.java): a button inside one of them
# never enters its hovered state -- no zoom, no bring-to-front, no click.
LOCKED_GROUP_TABLE_ADDR = 0x803CB120
WINDOW_VT = 0x8025C17C
PICTURE_VT = 0x8025C058
BOX_VTS = (WINDOW_VT, PICTURE_VT)
MEM2_LO, MEM2_HI = 0x90000000, 0x94000000
SCAN_CHUNK = 0x100000
SCAN_CHUNKS_PER_TICK = 16
ANCHOR_WINDOW = "windowMouth"   # any editor window; its parent is the root

VEIL = 5                        # 0-15: alpha of the veil
PADLOCK_RGBA = bytes.fromhex("303030ff")
MARGIN = 6.0                    # layout units around the zone's contents
PADLOCK_MAX = 96.0
PADLOCK_SHARE = 0.62            # of the zone's smaller side

# window -> (zone group, lock byte, bit). Grid pages are frm*PrNull_NN with
# NN = page; single-page locks use bit 0 (the client writes 0x01 / 0x00).
ZONES: Dict[str, List[Tuple[str, int, int]]] = {
    "windowEye": [("frmEyePrNull_%02d" % i, 0x00, i) for i in range(4)]
    + [("cpEyePrNull_00", 0x0B, 0), ("editEFrmPrN_00", 0x0C, 0)],
    "windowEyeB": [("frmEyeBPrNull_%02d" % i, 0x01, i) for i in range(2)]
    + [("cpEyeBPrNull_00", 0x0D, 0), ("editEBFrmPrN_00", 0x0E, 0)],
    "windowHair": [("frmHairPrNull_%02d" % i, 0x02, i) for i in range(6)]
    + [("cpHairPrNull_00", 0x0F, 0)],
    "windowNose": [("frmNosePrNull_00", 0x03, 0), ("editNsFrmPrN_00", 0x10, 0)],
    "windowMouth": [("frmMoutPrNull_%02d" % i, 0x04, i) for i in range(2)]
    + [("cpMosePrNull_00", 0x11, 0), ("editMFrmPrN_00", 0x12, 0)],
    "windowFace": [("frmFacePrNull_00", 0x05, 0), ("frmFacePrNull_01", 0x05, 0),
                   ("cpFacePrNull_00", 0x06, 0)],
    # glasses / mustache / beard / mole share one window
    "windowEtc": [("frmEtcPrNull_00", 0x07, 0), ("frmEtcPrNull_01", 0x08, 0),
                  ("frmEtcPrNull_02", 0x09, 0), ("frmEtcPrNull_03", 0x0A, 0),
                  ("cpEtcPrNull_00", 0x13, 0), ("cpEtcPrNull_01", 0x15, 0),
                  ("editEtFrmPrN_00", 0x14, 0), ("editEtFrmPrN_01", 0x16, 0),
                  ("editEtFrmPrN_02", 0x17, 0)],
}


def _alpha(x: int, y: int) -> int:
    """Padlock texel at (x, y): 15 padlock, 0 keyhole, VEIL elsewhere."""
    if (x - 32) ** 2 + (y - 42) ** 2 <= 16 or (31 <= x <= 33 and 42 <= y <= 52):
        return 0
    if 10 <= x <= 54 and 31 <= y <= 59:
        cx, cy = min(max(x, 13), 51), min(max(y, 34), 56)
        return 15 if (x - cx) ** 2 + (y - cy) ** 2 <= 9 else VEIL
    if 15 <= y < 31:
        dx = abs(x - 32)
        if y >= 29:
            return 15 if 10 <= dx <= 15 else VEIL
        d = (dx * dx + (y - 29) ** 2) ** 0.5
        return 15 if 9.5 <= d <= 15.5 else VEIL
    return VEIL


def padlock_texture() -> bytes:
    """I4 64x64, texels laid out in GX's 8x8 blocks."""
    nib = []
    for by in range(0, 64, 8):
        for bx in range(0, 64, 8):
            for y in range(by, by + 8):
                for x in range(bx, bx + 8):
                    nib.append(_alpha(x, y))
    return bytes((nib[j] << 4) | nib[j + 1] for j in range(0, 4096, 2))


def _u32(dme, addr: int) -> int:
    return struct.unpack(">I", dme.read_bytes(addr, 4))[0]


def _w32(dme, addr: int, value: int) -> None:
    dme.write_bytes(addr, struct.pack(">I", value & 0xFFFFFFFF))


def _name(raw: bytes) -> str:
    return raw[0xB4:0xC4].split(b"\0")[0].decode("latin-1")


def _children(dme, pane: int):
    sentinel = pane + 0x14
    node = _u32(dme, sentinel)
    for _ in range(256):
        if node in (sentinel, 0):
            return
        yield node - 4
        node = _u32(dme, node)


def _unlink(dme, pane: int, owner: int) -> None:
    nxt, prv = struct.unpack(">2I", dme.read_bytes(pane + 4, 8))
    _w32(dme, prv, nxt)                 # prev.next: forward walks skip it now
    _w32(dme, nxt + 4, prv)             # next.prev
    _w32(dme, owner + 0x10, _u32(dme, owner + 0x10) - 1)


def _link_after(dme, pane: int, owner: int, after: int) -> None:
    node = pane + 4
    nxt = _u32(dme, after)
    _w32(dme, node, nxt)
    _w32(dme, node + 4, after)
    _w32(dme, pane + 0x0C, owner)
    _w32(dme, after, node)              # forward walks include it from here
    _w32(dme, nxt + 4, node)
    _w32(dme, owner + 0x10, _u32(dme, owner + 0x10) + 1)


def _abs_pos(dme, pane: int, window: int) -> Tuple[float, float]:
    """Position of a pane's origin in window space (translations only)."""
    x = y = 0.0
    for _ in range(16):
        if pane in (0, window):
            break
        tx, ty = struct.unpack(">2f", dme.read_bytes(pane + 0x2C, 8))
        x, y = x + tx, y + ty
        pane = _u32(dme, pane + 0x0C)
    return x, y


def _texobj(dme, raw: bytes) -> int:
    """GXTexObj of a picture with a texture and tex coords, else 0."""
    if struct.unpack_from(">I", raw, 0)[0] != PICTURE_VT or raw[0xE5] < 1:
        return 0
    material = struct.unpack_from(">I", raw, 0x28)[0]
    if not material or not (_u32(dme, material + 0x50) >> 28) & 0xF:
        return 0
    return _u32(dme, material + 0x58)


def _is_ours(dme, texobj: int) -> bool:
    low = _u32(dme, texobj + 0x0C) & 0x01FFFFFF
    return low in {(a & 0x01FFFFFF) >> 5 for a in OLD_TEX_ADDRS}


class _Zone:
    def __init__(self, window: int, group: int, lock_byte: int, bit: int, box):
        self.window = window
        self.group = group
        self.lock_byte = lock_byte
        self.bit = bit
        self.box = box                # (x0, y0, x1, y1) in window space
        self.donor: Optional["_Donor"] = None


class _Donor:
    def __init__(self, pane: int, window: int, texobj: int, coords: int):
        self.pane = pane
        self.window = window          # the hidden window it belongs to
        self.texobj = texobj
        self.coords = coords
        self.parent = 0               # where it came from, while lent
        self.prev_node = 0
        self.saved: List[Tuple[int, bytes]] = []
        self.slot = -1                # its entry in the veil table, while lent


class ZoneLockOverlay:
    """Call tick() every INTERVAL_SECONDS with whether the editor is open."""

    def __init__(self, logger=None):
        self.logger = logger
        self.texture = padlock_texture()
        self.reset()

    def reset(self) -> None:
        """Forget the layout (it is gone or about to be): nothing is written back."""
        self.anchor: Optional[int] = None
        self.windows: List[Tuple[int, List[_Zone]]] = []
        self.donors: List[_Donor] = []
        self.group_table = b""        # last locked group table written
        self.scan_at = MEM2_LO
        self.ticks = 0

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger.debug(msg)

    # --- finding the layout -------------------------------------------------

    def _scan_step(self, dme) -> None:
        key = ANCHOR_WINDOW.encode() + b"\0"
        for _ in range(SCAN_CHUNKS_PER_TICK):
            base = self.scan_at
            self.scan_at = base + SCAN_CHUNK if base + SCAN_CHUNK < MEM2_HI else MEM2_LO
            try:
                chunk = dme.read_bytes(base, SCAN_CHUNK + 0x20)
            except Exception:
                continue
            i = chunk.find(key)
            while i != -1 and i < SCAN_CHUNK:
                pane = base + i - 0xB4
                if i >= 0xB4 and _u32(dme, pane) == WINDOW_VT:
                    self._build(dme, pane)
                    return
                i = chunk.find(key, i + 1)

    def _build(self, dme, anchor: int) -> None:
        dme.write_bytes(VEIL_TABLE_ADDR, bytes(4 * VEIL_SLOTS))   # nothing lent yet
        dme.write_bytes(LOCKED_GROUP_TABLE_ADDR, bytes(4 * VEIL_SLOTS))
        self.group_table = bytes(4 * VEIL_SLOTS)
        root = _u32(dme, anchor + 0x0C)
        windows, donors, missing, stale = [], [], [], 0
        for window in _children(dme, root):
            zones_def = ZONES.get(_name(dme.read_bytes(window, 0xD0)))
            if not zones_def:
                continue
            panes: Dict[int, Tuple[bytes, float, float]] = {}   # pane -> (raw, x, y)
            by_name: Dict[str, int] = {}
            ours = set()

            def visit(p, ox, oy, depth):
                nonlocal stale
                raw = dme.read_bytes(p, 0xEC)
                tx, ty = struct.unpack_from(">2f", raw, 0x2C)
                x, y = (0.0, 0.0) if depth == 0 else (ox + tx, oy + ty)
                panes[p] = (raw, x, y)
                by_name.setdefault(_name(raw), p)
                t = _texobj(dme, raw)
                if t and _is_ours(dme, t):
                    # left over by an earlier run: some materials ignore the
                    # pane alpha, a 0x0 quad draws nothing whatever the material
                    dme.write_bytes(p + 0x4C, struct.pack(">2f", 0.0, 0.0))
                    dme.write_bytes(p + 0xCD, b"\x00")
                    ours.add(p)
                    stale += 1
                # movement button icons only: other icons (the hair tab's)
                # get a widescreen x scale of 0.75 from the game, even lent out
                elif (t and "FrmIcon_" in _name(raw)
                        and (_u32(dme, t + 0x08) >> 20) & 0xF == 0 and _u32(dme, t) & 0xF == 0):
                    donors.append(_Donor(p, window, t, struct.unpack_from(">I", raw, 0xE8)[0]))
                if depth < 6:
                    for c in _children(dme, p):
                        visit(c, x, y, depth + 1)

            visit(window, 0.0, 0.0, 0)

            zones = []
            for group_name, lock_byte, bit in zones_def:
                group = by_name.get(group_name)
                box = self._box(dme, group, panes, ours) if group else None
                if box:
                    zones.append(_Zone(window, group, lock_byte, bit, box))
                else:
                    missing.append(group_name)
            windows.append((window, zones))
        self.anchor, self.windows, self.donors = anchor, windows, donors
        self._log(f"Editor zone padlocks: {sum(len(z) for _, z in windows)} zones, "
                  f"{len(donors)} icons to lend"
                  + (f", none for {', '.join(missing)}" if missing else "")
                  + (f", {stale} stale veil(s) hidden" if stale else ""))

    @staticmethod
    def _box(dme, group: int, panes, ours) -> Optional[Tuple[float, float, float, float]]:
        boxes = []
        stack = list(_children(dme, group))
        while stack:
            p = stack.pop()
            stack.extend(_children(dme, p))
            if p not in panes or p in ours:
                continue
            raw, x, y = panes[p]
            if struct.unpack_from(">I", raw, 0)[0] not in BOX_VTS:
                continue
            sx, sy, w, h = struct.unpack_from(">4f", raw, 0x44)
            boxes.append((x - w * sx / 2, y - h * sy / 2, x + w * sx / 2, y + h * sy / 2))
        if not boxes:
            return None
        # relative to the group: grid pages other than the shown one wait
        # 500 units below and slide in, so the window position is read live
        gx, gy = panes[group][1], panes[group][2]
        return (min(b[0] for b in boxes) - MARGIN - gx, min(b[1] for b in boxes) - MARGIN - gy,
                max(b[2] for b in boxes) + MARGIN - gx, max(b[3] for b in boxes) + MARGIN - gy)

    # --- lending icons ------------------------------------------------------

    def _shown(self, dme, zone: _Zone) -> bool:
        p = zone.group
        for _ in range(16):
            if not dme.read_bytes(p + 0xCF, 1)[0] & 1:
                return False
            if p == zone.window:
                return True
            p = _u32(dme, p + 0x0C)
        return False

    @staticmethod
    def _centre(dme, zone: _Zone) -> bytes:
        """Veil translation in window space, from the group's live position."""
        gx, gy = _abs_pos(dme, zone.group, zone.window)
        x0, y0, x1, y1 = zone.box
        return struct.pack(">2f", gx + (x0 + x1) / 2, gy + (y0 + y1) / 2)

    def _lend(self, dme, zone: _Zone) -> bool:
        donor = next((d for d in self.donors
                      if d.window != zone.window and d.parent == 0), None)
        used = {d.slot for d in self.donors}
        slot = next((i for i in range(VEIL_SLOTS) if i not in used), None)
        if donor is None or slot is None:
            return False
        x0, y0, x1, y1 = zone.box
        width, height = x1 - x0, y1 - y0
        padlock = min(PADLOCK_MAX, PADLOCK_SHARE * min(width, height))
        u, v = width / (2 * padlock), height / (2 * padlock)
        p, t = donor.pane, donor.texobj
        filt, size_bits, maddr = _u32(dme, t), _u32(dme, t + 0x08), _u32(dme, t + 0x0C)
        writes = [
            (p + 0x2C, self._centre(dme, zone)),
            (p + 0x44, struct.pack(">2f", 1.0, 1.0)),
            (p + 0x4C, struct.pack(">2f", width, height)),
            (p + 0xCD, b"\xff"),
            (p + 0xD4, PADLOCK_RGBA * 4),
            (t + 0x00, struct.pack(">I", filt & ~0xF)),
            (t + 0x08, struct.pack(">I", (size_bits & 0xFF000000) | (63 << 10) | 63)),
            (t + 0x0C, struct.pack(">I", (maddr & ~0x01FFFFFF) | (TEX_ADDR & 0x01FFFFFF) >> 5)),
            (donor.coords, struct.pack(">8f", 0.5 - u, 0.5 - v, 0.5 + u, 0.5 - v,
                                       0.5 - u, 0.5 + v, 0.5 + u, 0.5 + v)),
        ]
        donor.saved = [(addr, dme.read_bytes(addr, len(data))) for addr, data in writes]
        donor.parent = _u32(dme, p + 0x0C)
        donor.prev_node = _u32(dme, p + 0x08)
        # values first, while the icon is still in its hidden window
        for addr, data in writes:
            dme.write_bytes(addr, data)
        _unlink(dme, p, donor.parent)
        _link_after(dme, p, zone.window, _u32(dme, zone.window + 0x18))
        donor.slot = slot
        _w32(dme, VEIL_TABLE_ADDR + 4 * slot, p)   # the game keeps it last from now on
        zone.donor = donor
        donor.writes = writes
        return True

    def _give_back(self, dme, zone: _Zone) -> None:
        donor = zone.donor
        p = donor.pane
        if donor.slot >= 0:                          # out of the game's hands first
            _w32(dme, VEIL_TABLE_ADDR + 4 * donor.slot, 0)
            donor.slot = -1
        _unlink(dme, p, zone.window)
        after = donor.prev_node
        if after != donor.parent + 0x14 and _u32(dme, after - 4 + 0x0C) != donor.parent:
            after = _u32(dme, donor.parent + 0x18)      # old neighbour moved: go last
        _link_after(dme, p, donor.parent, after)
        for addr, data in donor.saved:
            dme.write_bytes(addr, data)
        donor.parent = 0
        zone.donor = None

    def tick(self, dme, editor_open: bool) -> None:
        if not editor_open:
            if self.anchor is not None or self.scan_at != MEM2_LO:
                # the panes are freed: the game must not move them any more
                dme.write_bytes(VEIL_TABLE_ADDR, bytes(4 * VEIL_SLOTS))
                dme.write_bytes(LOCKED_GROUP_TABLE_ADDR, bytes(4 * VEIL_SLOTS))
                self.reset()
            return
        if self.anchor is None:
            self._scan_step(dme)
            if self.anchor is None:
                return
        raw = dme.read_bytes(self.anchor, 0xD0)
        if struct.unpack_from(">I", raw, 0)[0] != WINDOW_VT or _name(raw) != ANCHOR_WINDOW:
            self.reset()
            return

        if self.ticks % 10 == 0 and dme.read_bytes(TEX_ADDR, TEX_BYTES) != self.texture:
            dme.write_bytes(TEX_ADDR, self.texture)
        self.ticks += 1

        locks = dme.read_bytes(LOCK_BASE, LOCK_COUNT)
        wanted = []
        for window, zones in self.windows:
            window_shown = bool(dme.read_bytes(window + 0xCF, 1)[0] & 1)
            for zone in zones:
                locked = not (locks[zone.lock_byte] >> zone.bit) & 1
                want = locked and window_shown and self._shown(dme, zone)
                if not want and zone.donor:
                    self._give_back(dme, zone)       # free icons before lending any
                elif want:
                    wanted.append(zone)
        for zone in wanted:
            if zone.donor:
                zone.donor.writes[0] = (zone.donor.pane + 0x2C, self._centre(dme, zone))
                for addr, data in zone.donor.writes:
                    dme.write_bytes(addr, data)
            else:
                self._lend(dme, zone)

        table = b"".join(struct.pack(">I", z.group) for z in wanted[:VEIL_SLOTS])
        table = table.ljust(4 * VEIL_SLOTS, b"\0")
        if table != self.group_table:
            dme.write_bytes(LOCKED_GROUP_TABLE_ADDR, table)
            self.group_table = table

