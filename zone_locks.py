"""Locked zones of the Mii editor under a grey veil with one padlock
(user request 2026-09-15: "une zone grisee, et le cadenas au dessus ... la
zone peut reduire en fonction de ce qu'il reste reellement a debloquer et il
faut mettre le cadenas qu'une fois").

No pane is created. For each locked zone (a grid page, a colour palette, a
movement button block) one textured picture -- the host -- is stretched over
the zone's bounding box and given our own texture: I4 64x64 in MEM1, a
translucent veil with an opaque padlock and a clear keyhole. Texture
coordinates beyond 0..1 keep the padlock square in the middle; the texture is
clamped, so its veil border fills the rest.

The host has to be drawn after the zone's contents: the last textured picture
of the zone's own group, or, for palettes (their cells are windows, with no
usable picture), the first icon of the movement group, which the game draws
after the palette. Only values inside the editor's own objects are written
(no pointer changes hands, so freeing the layout is untouched), and they are
put back as soon as the zone unlocks. The editor layout is rebuilt each time
the editor opens, so everything is found again then.

nw4r lyt objects, as measured live in the channel (2026-09-15):
  pane      +0x00 vtable (0x8025c17c window, 0x8025c058 picture,
            0x8025bfa8 null), +0x0C parent, +0x14 children list sentinel,
            +0x28 material, +0x2C translate, +0x44 scale, +0x4C size,
            +0x84 global matrix (row 0 first), +0xB4 name, +0xCD alpha,
            +0xCF flags (bit 0 visible)
  picture   +0xD4 vertex colours x4, +0xE5 tex coord count, +0xE8 tex coords
            (4 x VEC2: TL, TR, BL, BR)
  material  +0x50 GX data counts (top nibble = texture maps), +0x58 GX data,
            which starts with the GXTexObj: +0x08 fmt<<20 | (h-1)<<10 | (w-1),
            +0x0C image physical address >> 5, +0x14 format again
The grid icons get their width corrected for widescreen by the game (global
matrix x scale 0.75 against their parent): the host's width is divided by
that ratio so the veil still covers the whole zone.
"""
import struct
from typing import Dict, List, Optional, Tuple

INTERVAL_SECONDS = 0.5

LOCK_BASE = 0x803C1600          # client lock bytes, bit n = page n unlocked
LOCK_COUNT = 0x18
TEX_ADDR = 0x803C9E00           # 0x800 bytes, next to the Gecko blocks
TEX_BYTES = 0x800
TEX_I4_64 = (63 << 10) | 63     # GXTexObj size bits: I4 (format 0), 64x64
WINDOW_VT = 0x8025C17C
PICTURE_VT = 0x8025C058
BOX_VTS = (WINDOW_VT, PICTURE_VT)
MEM2_LO, MEM2_HI = 0x90000000, 0x94000000
SCAN_CHUNK = 0x100000
SCAN_CHUNKS_PER_TICK = 16
ANCHOR_WINDOW = "windowMouth"   # any editor window; its parent is the root

VEIL = 5                        # 0-15: strength of the grey veil
PADLOCK_RGBA = bytes.fromhex("303030ff")
MARGIN = 6.0                    # layout units around the zone's contents
PADLOCK_MAX = 96.0
PADLOCK_SHARE = 0.62            # of the zone's smaller side

# window -> (zone group, lock byte, bit, host group or None). Grid pages are
# frm*PrNull_NN with NN = page; single-page locks use bit 0 (the client
# writes 0x01 / 0x00). A host group is only needed where the zone has no
# picture of its own (palettes).
ZONES: Dict[str, List[Tuple[str, int, int, Optional[str]]]] = {
    "windowEye": [("frmEyePrNull_%02d" % i, 0x00, i, None) for i in range(4)]
    + [("cpEyePrNull_00", 0x0B, 0, "editEFrmPrN_00"), ("editEFrmPrN_00", 0x0C, 0, None)],
    "windowEyeB": [("frmEyeBPrNull_%02d" % i, 0x01, i, None) for i in range(2)]
    + [("cpEyeBPrNull_00", 0x0D, 0, "editEBFrmPrN_00"), ("editEBFrmPrN_00", 0x0E, 0, None)],
    "windowHair": [("frmHairPrNull_%02d" % i, 0x02, i, None) for i in range(6)],
    "windowNose": [("frmNosePrNull_00", 0x03, 0, None), ("editNsFrmPrN_00", 0x10, 0, None)],
    "windowMouth": [("frmMoutPrNull_%02d" % i, 0x04, i, None) for i in range(2)]
    + [("cpMosePrNull_00", 0x11, 0, "editMFrmPrN_00"), ("editMFrmPrN_00", 0x12, 0, None)],
    "windowFace": [("frmFacePrNull_00", 0x05, 0, None), ("frmFacePrNull_01", 0x05, 0, None),
                   ("cpFacePrNull_00", 0x06, 0, "editFcFrmPrN_00")],
    # glasses / mustache / beard / mole share one window
    "windowEtc": [("frmEtcPrNull_00", 0x07, 0, None), ("frmEtcPrNull_01", 0x08, 0, None),
                  ("frmEtcPrNull_02", 0x09, 0, None), ("frmEtcPrNull_03", 0x0A, 0, None),
                  ("cpEtcPrNull_00", 0x13, 0, "editEtFrmPrN_00"),
                  ("cpEtcPrNull_01", 0x15, 0, "editEtFrmPrN_01"),
                  ("editEtFrmPrN_00", 0x14, 0, None), ("editEtFrmPrN_01", 0x16, 0, None),
                  ("editEtFrmPrN_02", 0x17, 0, None)],
}


def _texel(x: int, y: int) -> int:
    """Padlock intensity at (x, y): 15 padlock, 0 keyhole, VEIL elsewhere."""
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
                    nib.append(_texel(x, y))
    return bytes((nib[j] << 4) | nib[j + 1] for j in range(0, 4096, 2))


def _u32(dme, addr: int) -> int:
    return struct.unpack(">I", dme.read_bytes(addr, 4))[0]


def _f32(dme, addr: int) -> float:
    return struct.unpack(">f", dme.read_bytes(addr, 4))[0]


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


def _subtree(dme, group: int, gx: float, gy: float):
    """[(addr, raw, x, y)] in draw order, positions in window space."""
    items = []

    def visit(p, ox, oy, depth):
        raw = dme.read_bytes(p, 0xEC)
        tx, ty = struct.unpack_from(">2f", raw, 0x2C)
        x, y = (gx, gy) if depth == 0 else (ox + tx, oy + ty)
        items.append((p, raw, x, y))
        if depth < 6:
            for c in _children(dme, p):
                visit(c, x, y, depth + 1)

    visit(group, 0.0, 0.0, 0)
    return items


def _textured_picture(dme, raw: bytes) -> bool:
    if struct.unpack_from(">I", raw, 0)[0] != PICTURE_VT or raw[0xE5] < 1:
        return False
    material = struct.unpack_from(">I", raw, 0x28)[0]
    return bool(material) and bool((_u32(dme, material + 0x50) >> 28) & 0xF)


class _Zone:
    def __init__(self, lock_byte: int, bit: int, writes, saved):
        self.lock_byte = lock_byte
        self.bit = bit
        self.writes = writes          # [(addr, bytes)] that draw the veil
        self.saved = saved            # [(addr, bytes)] originals, None if unknown
        self.applied = saved is None


def _build_zone(dme, window: int, group: int, lock_byte: int, bit: int,
                host_group: Optional[int]) -> Optional[_Zone]:
    gx, gy = _abs_pos(dme, group, window)
    items = _subtree(dme, group, gx, gy)

    if host_group is None:
        hosts = [it for it in reversed(items) if _textured_picture(dme, it[1])]
    else:
        hx, hy = _abs_pos(dme, host_group, window)
        pictures = [it for it in _subtree(dme, host_group, hx, hy) if _textured_picture(dme, it[1])]
        hosts = [it for it in pictures if "Icon" in _name(it[1])] or pictures
    if not hosts:
        return None
    host, host_raw = hosts[0][0], hosts[0][1]
    parent = struct.unpack_from(">I", host_raw, 0x0C)[0]
    parent_x, parent_y = _abs_pos(dme, parent, window)

    material = struct.unpack_from(">I", host_raw, 0x28)[0]
    texobj = _u32(dme, material + 0x58)
    coords = struct.unpack_from(">I", host_raw, 0xE8)[0]
    size_bits, maddr = _u32(dme, texobj + 0x08), _u32(dme, texobj + 0x0C)
    ours = (maddr & 0x01FFFFFF) == (TEX_ADDR & 0x01FFFFFF) >> 5

    boxes = []
    for p, raw, x, y in items[1:]:
        if struct.unpack_from(">I", raw, 0)[0] not in BOX_VTS or (p == host and ours):
            continue
        sx, sy, w, h = struct.unpack_from(">4f", raw, 0x44)
        boxes.append((x - w * sx / 2, y - h * sy / 2, x + w * sx / 2, y + h * sy / 2))
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes) - MARGIN
    y0 = min(b[1] for b in boxes) - MARGIN
    x1 = max(b[2] for b in boxes) + MARGIN
    y1 = max(b[3] for b in boxes) + MARGIN
    width, height = x1 - x0, y1 - y0
    padlock = min(PADLOCK_MAX, PADLOCK_SHARE * min(width, height))
    u, v = width / (2 * padlock), height / (2 * padlock)

    # widescreen correction the game applies to some pictures (grid icons)
    ratio = 1.0
    parent_m00 = _f32(dme, parent + 0x84) if parent else 0.0
    if parent_m00:                  # scale is ours only as 1.0, so the ratio stays valid
        ratio = _f32(dme, host + 0x84) / parent_m00
        if not 0.3 <= ratio <= 3.0 or abs(ratio - 1.0) < 0.02:
            ratio = 1.0

    writes = [
        (host + 0x2C, struct.pack(">2f", (x0 + x1) / 2 - parent_x, (y0 + y1) / 2 - parent_y)),
        (host + 0x44, struct.pack(">2f", 1.0, 1.0)),
        (host + 0x4C, struct.pack(">2f", width / ratio, height)),
        (host + 0xCD, b"\xff"),
        (host + 0xD4, PADLOCK_RGBA * 4),
        (texobj + 0x08, struct.pack(">I", (size_bits & 0xFF000000) | TEX_I4_64)),
        (texobj + 0x0C, struct.pack(">I", (maddr & ~0x01FFFFFF) | (TEX_ADDR & 0x01FFFFFF) >> 5)),
        (texobj + 0x14, struct.pack(">I", 0)),
        (coords, struct.pack(">8f", 0.5 - u, 0.5 - v, 0.5 + u, 0.5 - v,
                             0.5 - u, 0.5 + v, 0.5 + u, 0.5 + v)),
    ]
    saved = None if ours else [(addr, dme.read_bytes(addr, len(data))) for addr, data in writes]
    return _Zone(lock_byte, bit, writes, saved)


class ZoneLockOverlay:
    """Call tick() every INTERVAL_SECONDS with whether the editor is open."""

    def __init__(self, logger=None):
        self.logger = logger
        self.texture = padlock_texture()
        self.reset()

    def reset(self) -> None:
        self.anchor: Optional[int] = None
        self.windows: List[Tuple[int, List[_Zone]]] = []
        self.scan_at = MEM2_LO
        self.ticks = 0

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger.debug(msg)

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
        root = _u32(dme, anchor + 0x0C)
        windows, count, missing = [], 0, []
        for window in _children(dme, root):
            zones_def = ZONES.get(_name(dme.read_bytes(window, 0xD0)))
            if not zones_def:
                continue
            by_name: Dict[str, int] = {}
            stack = [window]
            while stack:
                p = stack.pop()
                by_name.setdefault(_name(dme.read_bytes(p, 0xD0)), p)
                stack.extend(_children(dme, p))
            zones = []
            for group_name, lock_byte, bit, host_name in zones_def:
                group = by_name.get(group_name)
                host_group = by_name.get(host_name) if host_name else None
                zone = None
                if group and (host_name is None or host_group):
                    zone = _build_zone(dme, window, group, lock_byte, bit, host_group)
                if zone:
                    zones.append(zone)
                else:
                    missing.append(group_name)
            windows.append((window, zones))
            count += len(zones)
        self.anchor, self.windows = anchor, windows
        self._log(f"Editor zone padlocks: {count} zones ready"
                  + (f", none for {', '.join(missing)}" if missing else ""))

    def tick(self, dme, editor_open: bool) -> None:
        if not editor_open:
            if self.anchor is not None or self.scan_at != MEM2_LO:
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
        for window, zones in self.windows:
            visible = bool(dme.read_bytes(window + 0xCF, 1)[0] & 1)
            for zone in zones:
                locked = not (locks[zone.lock_byte] >> zone.bit) & 1
                if locked and (visible or not zone.applied):
                    for addr, data in zone.writes:
                        dme.write_bytes(addr, data)
                    zone.applied = True
                elif not locked and zone.applied:
                    if zone.saved:
                        for addr, data in zone.saved:
                            dme.write_bytes(addr, data)
                    zone.applied = False
