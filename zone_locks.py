"""Locked parts of the Mii editor under a grey veil with a dark padlock
(user requests 2026-09-15/16: "une zone grisee, et le cadenas au dessus",
"le cadenas fonce partout", hovered items must not draw over it, the veil
shrinks as things unlock, one padlock per separate locked group, and no dark
seam where two veils meet).

What is veiled is computed cell by cell:
  * page grids (eye, eyebrow, hair, mouth types): the whole page while its bit
    is clear in the lock byte;
  * counted grids and colour palettes (nose, glasses, moustache, beard, mole,
    every colour): only the cells still out of reach -- the lock byte says how
    many non-default values are allowed and they open in value order, which is
    not always the display order (DISPLAY_ORDER);
  * movement blocks: all their buttons while the byte is 0.
The veiled cells are cut into rectangles: runs of neighbouring cells in a
row, stacked when rows line up. Rectangles that touch form one group, which
gets one padlock; where two rectangles of a group meet they stop at the
middle of the gap instead of overlapping (an overlap doubles the veil).

No pane is created. Each editor tab is a window; only the current tab's is
visible. The overlay borrows a simple icon picture from one of the HIDDEN
windows -- a movement icon: I4 texture, coloured by its vertex colours, alpha
= intensity, so the padlock is dark -- moves it to the end of the visible
window's child list (drawn after everything, hovered cells included),
stretches it over a rectangle and points it at our texture: a translucent
veil with an opaque padlock and a clear keyhole, I4 64x64 in MEM1. Texture
coordinates beyond 0..1 keep the padlock square in the middle; the texture is
clamped, so its veil border fills the rest. A rectangle without the padlock
samples a corner of the texture. Nothing of the visible tab is touched, and
the icon goes back to its own window with its own values as soon as the zone
unlocks or leaves the screen.

Lent icons are also written to LENT_STATE_PATH, so a client restarted while
the editor is open gives them back instead of leaving buttons without icons.

Two tables are published for the Gecko blocks:
  0x803CB100  veils lent out (8) -- "Editor veils stay on top" moves them back
              to the end of a list the game just reordered for a hover;
  0x803CB120  veiled panes (48) -- "Locked zones: no hover" makes a button
              inside one of them take the game's own no-hover branch, so a
              locked cell has no zoom, no bring-to-front and no click.

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
import json
import os
import re
import struct
import tempfile
from typing import Dict, List, Optional, Sequence, Tuple

INTERVAL_SECONDS = 0.5

LOCK_BASE = 0x803C1600          # client lock bytes (page bitmask, or a count)
LOCK_COUNT = 0x19
TEX_ADDR = 0x803C9E00           # 0x800 bytes, next to the Gecko blocks
TEX_BYTES = 0x800
OLD_TEX_ADDRS = (0x803C9E00, 0x803CA600)   # anything pointing here is ours
VEIL_TABLE_ADDR = 0x803CB100
VEIL_SLOTS = 8
MAX_VEILS_PER_ZONE = 4          # more rectangles than this: one box for the zone
LOCKED_TABLE_ADDR = 0x803CB120
LOCKED_SLOTS = 48
WINDOW_VT = 0x8025C17C
PICTURE_VT = 0x8025C058
BOX_VTS = (WINDOW_VT, PICTURE_VT)
MEM2_LO, MEM2_HI = 0x90000000, 0x94000000
SCAN_CHUNK = 0x100000
SCAN_CHUNKS_PER_TICK = 16
ANCHOR_WINDOW = "windowMouth"   # any editor window; its parent is the root
LENT_STATE_PATH = os.path.join(tempfile.gettempdir(), "mii_channel_lent_icons.json")

VEIL = 5                        # 0-15: alpha of the veil
PADLOCK_RGBA = bytes.fromhex("303030ff")
MARGIN = 6.0                    # layout units around a group of veiled cells
TOUCH = 12.0                    # cells closer than this are neighbours
PADLOCK_MAX = 96.0
PADLOCK_SHARE = 0.62            # of the rectangle's smaller side

PAGE, COUNT, FLAG = "page", "count", "flag"

Rect = Tuple[float, float, float, float]

# window -> (group pane, lock byte, mode, extra). extra is the page number for
# PAGE, the field's default value for COUNT (always selectable, so it is taken
# out of the rank the count is compared against, exactly like locks.py), and
# None for FLAG.
ZONES: Dict[str, List[Tuple[str, int, str, Optional[int]]]] = {
    "windowEye": [("frmEyePrNull_%02d" % i, 0x00, PAGE, i) for i in range(4)]
    + [("cpEyePrNull_00", 0x0B, COUNT, 0), ("editEFrmPrN_00", 0x0C, FLAG, None)],
    "windowEyeB": [("frmEyeBPrNull_%02d" % i, 0x01, PAGE, i) for i in range(2)]
    + [("cpEyeBPrNull_00", 0x0D, COUNT, 1), ("editEBFrmPrN_00", 0x0E, FLAG, None)],
    "windowHair": [("frmHairPrNull_%02d" % i, 0x02, PAGE, i) for i in range(6)]
    + [("cpHairPrNull_00", 0x0F, COUNT, 1)],
    "windowNose": [("frmNosePrNull_00", 0x03, COUNT, 1), ("editNsFrmPrN_00", 0x10, FLAG, None)],
    "windowMouth": [("frmMoutPrNull_%02d" % i, 0x04, PAGE, i) for i in range(2)]
    + [("cpMosePrNull_00", 0x11, COUNT, 0), ("editMFrmPrN_00", 0x12, FLAG, None)],
    # face shape (_00, 8 cells) and the makeup marks (_01, 12 cells) are two
    # items with two counted bytes since trampoline V15
    "windowFace": [("frmFacePrNull_00", 0x05, COUNT, 0), ("frmFacePrNull_01", 0x18, COUNT, 0),
                   ("cpFacePrNull_00", 0x06, COUNT, 0)],
    # glasses / moustache / mole / beard share one window. Measured live:
    # _00 glasses (cells 00-11), _01 moustache (12-15), _02 the mole's two
    # cells (24-25), _03 beard (16-19). The 8 swatch palette is the facial
    # hair one, the 6 swatch one the glasses'. The cell numbers run on across
    # the grids of this window, hence _cells counting from each grid's first.
    "windowEtc": [("frmEtcPrNull_00", 0x07, COUNT, 0), ("frmEtcPrNull_01", 0x08, COUNT, 0),
                  ("frmEtcPrNull_02", 0x0A, COUNT, 0), ("frmEtcPrNull_03", 0x09, COUNT, 0),
                  ("cpEtcPrNull_00", 0x15, COUNT, 0), ("cpEtcPrNull_01", 0x13, COUNT, 0),
                  ("editEtFrmPrN_00", 0x14, FLAG, None), ("editEtFrmPrN_01", 0x16, FLAG, None),
                  ("editEtFrmPrN_02", 0x17, FLAG, None)],
}

# The editor does not always show a category in value order: the game keeps
# a value -> display position table per paginated category (main.dol
# 0x802070d0 hair, 0x80207118 eye, 0x80207148 eyebrow, 0x80207160 nose,
# 0x80207170 mouth). Only counted grids need it here -- a page is veiled
# whole, and the other categories are in value order (measured live: the
# nose's 12 cells read 1, 10, 2, 3, 6, 0, 5, 4, 8, 9, 7, 11).
DISPLAY_ORDER: Dict[str, Sequence[int]] = {
    "frmNosePrNull_00": (5, 0, 2, 3, 7, 6, 4, 10, 8, 9, 1, 11),
}

_INDEX = re.compile("_([0-9]+)$")


def _alpha(x: int, y: int) -> int:
    """Padlock texel at (x, y): 15 padlock, 0 keyhole, VEIL elsewhere.

    The drawing below spans rows 15-59; it is read 5 rows lower so the
    padlock sits in rows 10-54, centred on the texture (user 2026-09-16:
    the padlock looked too low)."""
    y += 5
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


def veil_rects(boxes: Sequence[Rect]) -> List[Tuple[Rect, Rect, bool]]:
    """Rectangles covering exactly `boxes` (cell boxes): each as (veil
    rectangle with its margins, the cells it covers, whether it carries its
    group's padlock). The padlock is centred on the cells, not on the margins,
    which differ from side to side where rectangles meet.

    Runs of neighbouring cells in a row, runs stacked when they line up;
    rectangles that touch form a group with one padlock (on its biggest
    rectangle); a side that meets a rectangle of the same group stops at the
    middle of the gap, the others get MARGIN."""
    rows: Dict[int, List[Rect]] = {}
    for box in boxes:
        rows.setdefault(int(round((box[1] + box[3]) / 2)), []).append(box)
    runs: List[Rect] = []
    for _row, cells in sorted(rows.items(), reverse=True):
        cells.sort()
        run = list(cells[0])
        for c in cells[1:]:
            if c[0] - run[2] <= TOUCH:
                run = [run[0], min(run[1], c[1]), c[2], max(run[3], c[3])]
            else:
                runs.append(tuple(run))
                run = list(c)
        runs.append(tuple(run))

    rects: List[List[float]] = []
    for r in runs:
        for s in rects:
            if abs(s[0] - r[0]) < TOUCH and abs(s[2] - r[2]) < TOUCH and \
                    min(abs(s[1] - r[3]), abs(r[1] - s[3])) <= TOUCH:
                # rows of slightly different widths (buttons) still stack
                s[0], s[2] = min(s[0], r[0]), max(s[2], r[2])
                s[1], s[3] = min(s[1], r[1]), max(s[3], r[3])
                break
        else:
            rects.append(list(r))

    def gap_x(a, b):
        return max(a[0], b[0]) - min(a[2], b[2])

    def gap_y(a, b):
        return max(a[1], b[1]) - min(a[3], b[3])

    def touching(a, b):
        return ((-TOUCH <= gap_x(a, b) <= TOUCH and gap_y(a, b) < 0) or (-TOUCH <= gap_y(a, b) <= TOUCH and gap_x(a, b) < 0))

    group = list(range(len(rects)))

    def find(i):
        while group[i] != i:
            group[i] = group[group[i]]
            i = group[i]
        return i

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if touching(rects[i], rects[j]):
                group[find(i)] = find(j)

    out: List[Tuple[Rect, Rect, bool]] = []
    best: Dict[int, int] = {}
    for i, r in enumerate(rects):
        g = find(i)
        area = (r[2] - r[0]) * (r[3] - r[1])
        if g not in best or area > (rects[best[g]][2] - rects[best[g]][0]) * (rects[best[g]][3] - rects[best[g]][1]):
            best[g] = i
    for i, r in enumerate(rects):
        left = right = bottom = top = MARGIN
        for j, s in enumerate(rects):
            if j == i or find(j) != find(i):
                continue
            # neighbours meet in the middle of the gap -- or of the overlap
            # when the cells overlap a little: never both margins
            left_of = (s[0] + s[2]) < (r[0] + r[2])
            below = (s[1] + s[3]) < (r[1] + r[3])
            if gap_y(r, s) < 0 and left_of and -TOUCH <= r[0] - s[2] <= TOUCH:
                left = (r[0] - s[2]) / 2
            if gap_y(r, s) < 0 and not left_of and -TOUCH <= s[0] - r[2] <= TOUCH:
                right = (s[0] - r[2]) / 2
            if gap_x(r, s) < 0 and below and -TOUCH <= r[1] - s[3] <= TOUCH:
                bottom = (r[1] - s[3]) / 2
            if gap_x(r, s) < 0 and not below and -TOUCH <= s[1] - r[3] <= TOUCH:
                top = (s[1] - r[3]) / 2
        out.append(((r[0] - left, r[1] - bottom, r[2] + right, r[3] + top), tuple(r), best[find(i)] == i))
    out.sort(key=lambda item: not item[2])
    return out


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


def _subtree(dme, pane: int, ox: float, oy: float, depth: int = 0):
    """[(addr, raw, x, y)] in draw order, positions relative to `pane`."""
    raw = dme.read_bytes(pane, 0xEC)
    tx, ty = struct.unpack_from(">2f", raw, 0x2C)
    x, y = (ox, oy) if depth == 0 else (ox + tx, oy + ty)
    items = [(pane, raw, x, y)]
    if depth < 6:
        for c in _children(dme, pane):
            items.extend(_subtree(dme, c, x, y, depth + 1))
    return items


def _box_of(dme, pane: int, ox: float, oy: float, skip) -> Optional[Rect]:
    boxes = []
    for p, raw, x, y in _subtree(dme, pane, ox, oy):
        if struct.unpack_from(">I", raw, 0)[0] not in BOX_VTS or p in skip:
            continue
        sx, sy, w, h = struct.unpack_from(">4f", raw, 0x44)
        boxes.append((x - w * sx / 2, y - h * sy / 2, x + w * sx / 2, y + h * sy / 2))
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


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
    def __init__(self, window: int, group: int, lock: int, mode: str, extra: Optional[int],
                 cells: Sequence[Tuple[int, int, Rect]], group_name: str = ""):
        self.window = window
        self.group = group
        self.lock = lock
        self.mode = mode
        self.extra = extra
        self.cells = cells            # [(display index, pane, box relative to the group)]
        # display index -> value; an empty table means the two orders match
        self.value_of = {display: value for value, display in enumerate(DISPLAY_ORDER.get(group_name, ()))}
        self.donors: List["_Donor"] = []   # one per veil rectangle

    def locked_cells(self, byte: int):
        """The cells still out of reach, with the lock byte as it stands."""
        if self.mode == PAGE:
            return self.cells if not (byte >> (self.extra or 0)) & 1 else []
        if self.mode == FLAG:
            return self.cells if byte == 0 else []
        default = self.extra or 0
        out = []
        for display, pane, box in self.cells:
            value = self.value_of.get(display, display)
            if value == default:
                continue
            rank = value if value < default else value - 1
            if rank >= byte:
                out.append((display, pane, box))
        return out


class _Donor:
    def __init__(self, pane: int, window: int, texobj: int, coords: int):
        self.pane = pane
        self.window = window          # the hidden window it belongs to
        self.texobj = texobj
        self.coords = coords
        self.parent = 0               # where it came from, while lent
        self.prev_node = 0
        self.slot = -1
        self.lent_to = 0              # the window it is lent to
        self.saved: List[Tuple[int, bytes]] = []


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
        self.locked_table = b""
        self.scan_at = MEM2_LO
        self.ticks = 0

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger.debug(msg)

    # --- remembering what is lent, across client restarts --------------------

    def _save_state(self) -> None:
        state = {"anchor": self.anchor or 0, "icons": [
            {"pane": d.pane, "parent": d.parent, "prev": d.prev_node, "lent_to": d.lent_to,
             "saved": [[addr, data.hex()] for addr, data in d.saved]}
            for d in self.donors if d.parent]}
        try:
            with open(LENT_STATE_PATH, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
        except OSError:
            pass

    def _give_back_leftovers(self, dme, anchor: int) -> int:
        """Icons an earlier client run lent in this very editor session."""
        try:
            with open(LENT_STATE_PATH, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            return 0
        if state.get("anchor") != anchor:
            return 0                  # another editor session: those panes are gone
        restored = 0
        for icon in state.get("icons", []):
            pane, parent, prev, holder = icon["pane"], icon["parent"], icon["prev"], icon["lent_to"]
            try:
                if _u32(dme, pane + 0x0C) != holder:
                    continue
                _unlink(dme, pane, holder)
                after = prev
                if after != parent + 0x14 and _u32(dme, after - 4 + 0x0C) != parent:
                    after = _u32(dme, parent + 0x18)
                _link_after(dme, pane, parent, after)
                for addr, data in icon["saved"]:
                    dme.write_bytes(addr, bytes.fromhex(data))
                restored += 1
            except Exception:
                continue
        return restored

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
        dme.write_bytes(VEIL_TABLE_ADDR, bytes(4 * VEIL_SLOTS))     # nothing lent yet
        dme.write_bytes(LOCKED_TABLE_ADDR, bytes(4 * LOCKED_SLOTS))
        self.locked_table = bytes(4 * LOCKED_SLOTS)
        restored = self._give_back_leftovers(dme, anchor)
        root = _u32(dme, anchor + 0x0C)
        windows, donors, missing, stale = [], [], [], 0
        for window in _children(dme, root):
            zones_def = ZONES.get(_name(dme.read_bytes(window, 0xD0)))
            if not zones_def:
                continue
            by_name: Dict[str, int] = {}
            ours = set()
            for p, raw, _x, _y in _subtree(dme, window, 0.0, 0.0):
                by_name.setdefault(_name(raw), p)
                t = _texobj(dme, raw)
                if t and _is_ours(dme, t):
                    # left over and not in the saved state: some materials
                    # ignore the pane alpha, a 0x0 quad draws nothing at all
                    dme.write_bytes(p + 0x4C, struct.pack(">2f", 0.0, 0.0))
                    dme.write_bytes(p + 0xCD, b"\x00")
                    ours.add(p)
                    stale += 1
                elif (t and "FrmIcon_" in _name(raw)
                        and (_u32(dme, t + 0x08) >> 20) & 0xF == 0 and _u32(dme, t) & 0xF == 0):
                    # movement button icons only: other icons (the hair tab's)
                    # get a widescreen x scale of 0.75 from the game, even lent out
                    donors.append(_Donor(p, window, t, struct.unpack_from(">I", raw, 0xE8)[0]))

            zones = []
            for group_name, lock, mode, extra in zones_def:
                group = by_name.get(group_name)
                cells = self._cells(dme, group, ours) if group else []
                if cells:
                    zones.append(_Zone(window, group, lock, mode, extra, cells, group_name))
                else:
                    missing.append(group_name)
            windows.append((window, zones))
        self.anchor, self.windows, self.donors = anchor, windows, donors
        self._save_state()
        self._log(f"Editor zone padlocks: {sum(len(z) for _, z in windows)} zones, "
                  f"{len(donors)} icons to lend"
                  + (f", {restored} icon(s) given back from a previous run" if restored else "")
                  + (f", none for {', '.join(missing)}" if missing else "")
                  + (f", {stale} stale veil(s) hidden" if stale else ""))

    @staticmethod
    def _cells(dme, group: int, ours):
        """[(display position, pane, box)] for the group's cells, boxes
        relative to it. A cell is a direct child whose name ends in a number
        (colour swatches colorP*_NN, grid cells frame*Null_NN, movement
        buttons edit*Null_NN); its position counts from the group's first."""
        cells = []
        for child in _children(dme, group):
            raw = dme.read_bytes(child, 0xEC)
            match = _INDEX.search(_name(raw))
            tx, ty = struct.unpack_from(">2f", raw, 0x2C)
            box = _box_of(dme, child, tx, ty, ours)
            if match and box:
                cells.append((int(match.group(1)), child, box))
        cells.sort()
        # the accessories window numbers its cells across all its grids
        # (moustache 12-15, beard 16-19...): positions count from each
        # grid's first cell (user 2026-09-16: an open moustache was veiled)
        first = cells[0][0] if cells else 0
        return [(index - first, child, box) for index, child, box in cells]

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
    def _veil_writes(dme, zone: _Zone, donor: _Donor, rect: Rect, core: Rect, padlock_on: bool):
        gx, gy = _abs_pos(dme, zone.group, zone.window)
        x0, y0, x1, y1 = rect[0] + gx, rect[1] + gy, rect[2] + gx, rect[3] + gy
        width, height = x1 - x0, y1 - y0
        if padlock_on:
            padlock = min(PADLOCK_MAX, PADLOCK_SHARE * min(width, height))
            # texture centre on the centre of the veiled cells; v runs downwards
            cx, cy = (core[0] + core[2]) / 2 + gx, (core[1] + core[3]) / 2 + gy
            u_left, u_right = 0.5 + (x0 - cx) / padlock, 0.5 + (x1 - cx) / padlock
            v_top, v_bottom = 0.5 - (y1 - cy) / padlock, 0.5 - (y0 - cy) / padlock
            coords = (u_left, v_top, u_right, v_top, u_left, v_bottom, u_right, v_bottom)
        else:
            # a corner of the texture, veil only
            coords = (0.02, 0.02, 0.10, 0.02, 0.02, 0.10, 0.10, 0.10)
        p, t = donor.pane, donor.texobj
        filt, size_bits, maddr = _u32(dme, t), _u32(dme, t + 0x08), _u32(dme, t + 0x0C)
        return [
            (p + 0x2C, struct.pack(">2f", (x0 + x1) / 2, (y0 + y1) / 2)),
            (p + 0x44, struct.pack(">2f", 1.0, 1.0)),
            (p + 0x4C, struct.pack(">2f", width, height)),
            (p + 0xCD, b"\xff"),
            (p + 0xD4, PADLOCK_RGBA * 4),
            (t + 0x00, struct.pack(">I", filt & ~0xF)),
            (t + 0x08, struct.pack(">I", (size_bits & 0xFF000000) | (63 << 10) | 63)),
            (t + 0x0C, struct.pack(">I", (maddr & ~0x01FFFFFF) | (TEX_ADDR & 0x01FFFFFF) >> 5)),
            (donor.coords, struct.pack(">8f", *coords)),
        ]

    def _lend(self, dme, zone: _Zone) -> Optional[_Donor]:
        donor = next((d for d in self.donors
                      if d.window != zone.window and d.parent == 0), None)
        used = {d.slot for d in self.donors}
        slot = next((i for i in range(VEIL_SLOTS) if i not in used), None)
        if donor is None or slot is None:
            return None
        p = donor.pane
        donor.saved = [(addr, dme.read_bytes(addr, size)) for addr, size in (
            (p + 0x2C, 8), (p + 0x44, 8), (p + 0x4C, 8), (p + 0xCD, 1), (p + 0xD4, 16),
            (donor.texobj + 0x00, 4), (donor.texobj + 0x08, 4), (donor.texobj + 0x0C, 4),
            (donor.coords, 32))]
        donor.parent = _u32(dme, p + 0x0C)
        donor.prev_node = _u32(dme, p + 0x08)
        donor.lent_to = zone.window
        self._save_state()            # before moving it: a crash now still gives it back
        _unlink(dme, p, donor.parent)
        _link_after(dme, p, zone.window, _u32(dme, zone.window + 0x18))
        donor.slot = slot
        _w32(dme, VEIL_TABLE_ADDR + 4 * slot, p)   # the game keeps it last from now on
        zone.donors.append(donor)
        return donor

    def _give_back(self, dme, zone: _Zone, donor: _Donor) -> None:
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
        donor.lent_to = 0
        if donor in zone.donors:
            zone.donors.remove(donor)
        self._save_state()

    def tick(self, dme, editor_open: bool) -> None:
        if not editor_open:
            if self.anchor is not None or self.scan_at != MEM2_LO:
                # the panes are freed: the game must not touch them any more
                dme.write_bytes(VEIL_TABLE_ADDR, bytes(4 * VEIL_SLOTS))
                dme.write_bytes(LOCKED_TABLE_ADDR, bytes(4 * LOCKED_SLOTS))
                self.reset()
                self._save_state()
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
                cells = zone.locked_cells(locks[zone.lock]) if window_shown else []
                rects = []
                if cells and self._shown(dme, zone):
                    boxes = [c[2] for c in cells]
                    if len(cells) == len(zone.cells):
                        # the whole zone is locked: one rectangle, whatever the
                        # buttons' shapes (user 2026-09-16: two overlapping
                        # veils on the mole's movement block)
                        boxes = [(min(b[0] for b in boxes), min(b[1] for b in boxes),
                                  max(b[2] for b in boxes), max(b[3] for b in boxes))]
                    rects = veil_rects(boxes)
                    if len(rects) > MAX_VEILS_PER_ZONE:
                        box = (min(r[0][0] for r in rects), min(r[0][1] for r in rects),
                               max(r[0][2] for r in rects), max(r[0][3] for r in rects))
                        core = (min(r[1][0] for r in rects), min(r[1][1] for r in rects),
                                max(r[1][2] for r in rects), max(r[1][3] for r in rects))
                        rects = [(box, core, True)]
                # free what this zone no longer needs before anything is lent
                while len(zone.donors) > len(rects):
                    self._give_back(dme, zone, zone.donors[-1])
                if rects:
                    wanted.append((zone, cells, rects))

        locked_panes = []
        for zone, cells, rects in wanted:
            for i, (rect, core, padlock_on) in enumerate(rects):
                donor = zone.donors[i] if i < len(zone.donors) else self._lend(dme, zone)
                if donor is None:
                    break
                for addr, data in self._veil_writes(dme, zone, donor, rect, core, padlock_on):
                    dme.write_bytes(addr, data)
            # a whole veiled group can be named once; single cells one by one
            if len(cells) == len(zone.cells):
                locked_panes.append(zone.group)
            else:
                locked_panes.extend(c[1] for c in cells)

        table = b"".join(struct.pack(">I", p) for p in locked_panes[:LOCKED_SLOTS])
        table = table.ljust(4 * LOCKED_SLOTS, b"\0")
        if table != self.locked_table:
            dme.write_bytes(LOCKED_TABLE_ADDR, table)
            self.locked_table = table
