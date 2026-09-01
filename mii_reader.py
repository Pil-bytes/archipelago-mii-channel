"""
Parser for the Wii Mii Channel's Mii database file (RFL_DB.dat).

File layout (from WiiBrew "/shared2/menu/FaceLib/RFL_DB.dat" and "Mii data"):
  - 4 byte "RNOD" magic + 2 bytes at file start
  - Up to 100 fixed-size (0x4A / 74 byte) Mii records starting at file offset 0x04
  - A "Mii Parade" section and CRC16 footer follow, which we don't need.

Each Mii record's bitfields are packed big-endian, MSB-first within each group,
in the field order documented on WiiBrew. Verified empirically against a real
Dolphin RFL_DB.dat file (all extracted values fell inside their documented
valid ranges).
"""
from __future__ import annotations

import os
import glob
from dataclasses import dataclass, field
from typing import List, Optional

ENTRY_START = 0x04
ENTRY_SIZE = 0x4A
MAX_SLOTS = 100

# CRC16 footer: covers exactly the first CRC_OFFSET bytes of the file.
# Algorithm verified against a real Dolphin RFL_DB.dat: standard CRC-16/CCITT
# (poly 0x1021, init 0x0000, MSB-first, no bit reflection, no final XOR, no
# padding) over data[:CRC_OFFSET] reproduces the stored checksum exactly.
CRC_OFFSET = 0x1F1DE


def crc16_ccitt(data: bytes) -> int:
    crc = 0x0000
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _be16(b: bytes, off: int) -> int:
    return (b[off] << 8) | b[off + 1]


def _be32(b: bytes, off: int) -> int:
    return (b[off] << 24) | (b[off + 1] << 16) | (b[off + 2] << 8) | b[off + 3]


def _bits(val: int, total_bits: int, start_from_msb: int, width: int) -> int:
    shift = total_bits - start_from_msb - width
    mask = (1 << width) - 1
    return (val >> shift) & mask


def _pack_bits(word: int, total_bits: int, start_from_msb: int, width: int, value: int) -> int:
    """Return `word` with the given bit range replaced by `value`, other bits untouched."""
    shift = total_bits - start_from_msb - width
    mask = (1 << width) - 1
    return (word & ~(mask << shift)) | ((value & mask) << shift)


# (word_offset_within_entry, word_bits, start_bit_from_msb, width) for every field
# we may need to both read and lock/revert. word_offset/word_bits let read-modify-write
# share the exact same word other fields are packed into (e.g. face_shape/skin_color
# both live in the 2-byte word at entry offset 0x20).
FIELD_SPECS = {
    "face_shape": (0x20, 16, 0, 3),
    "skin_color": (0x20, 16, 3, 3),
    "facial_feature": (0x20, 16, 6, 4),
    "hair_type": (0x22, 16, 0, 7),
    "hair_color": (0x22, 16, 7, 3),
    "hair_part_reversed": (0x22, 16, 10, 1),
    "eyebrow_type": (0x24, 32, 0, 5),
    "eyebrow_rotation": (0x24, 32, 6, 4),
    "eyebrow_color": (0x24, 32, 16, 3),
    "eyebrow_size": (0x24, 32, 19, 4),
    "eyebrow_vert_pos": (0x24, 32, 23, 5),
    "eyebrow_horiz_spacing": (0x24, 32, 28, 4),
    "eye_type": (0x28, 32, 0, 6),
    "eye_rotation": (0x28, 32, 8, 3),
    "eye_vert_pos": (0x28, 32, 11, 5),
    "eye_color": (0x28, 32, 16, 3),
    "eye_size": (0x28, 32, 20, 3),
    "eye_horiz_spacing": (0x28, 32, 23, 4),
    "nose_type": (0x2C, 16, 0, 4),
    "nose_size": (0x2C, 16, 4, 4),
    "nose_vert_pos": (0x2C, 16, 8, 5),
    "mouth_type": (0x2E, 16, 0, 5),
    "mouth_color": (0x2E, 16, 5, 2),
    "mouth_size": (0x2E, 16, 7, 4),
    "mouth_vert_pos": (0x2E, 16, 11, 5),
    "glasses_type": (0x30, 16, 0, 4),
    "glasses_color": (0x30, 16, 4, 3),
    "glasses_size": (0x30, 16, 8, 3),
    "glasses_vert_pos": (0x30, 16, 11, 5),
    "mustache_type": (0x32, 16, 0, 2),
    "beard_type": (0x32, 16, 2, 2),
    "facial_hair_color": (0x32, 16, 4, 3),
    "mustache_size": (0x32, 16, 7, 4),
    "mustache_vert_pos": (0x32, 16, 11, 5),
    "mole_enabled": (0x34, 16, 0, 1),
    "mole_size": (0x34, 16, 1, 4),
    "mole_vert_pos": (0x34, 16, 5, 5),
    "mole_horiz_pos": (0x34, 16, 10, 5),
}

# The in-game live Mii-editor struct (what the actual running game reads
# for rendering/selection, distinct from this file's on-disk RFL_DB.dat
# layout above) packs the SAME per-field (start_from_msb, width) bit
# layout into each word -- confirmed independently twice this project, via
# a live memory diff for eye_type and via FUN_8004043c's clamp-function
# decompile for every other field -- but at DIFFERENT word offsets: eye and
# eyebrow are swapped relative to the file layout, and so are glasses and
# mustache/beard. Everything else keeps the same relative order, just
# shifted down by the file's 0x20 record-header size. Maps this file's
# FIELD_SPECS word_offset -> (live word offset, word width in bits).
LIVE_WORD_MAP = {
    0x20: (0x00, 16),  # face_shape / skin_color / facial_feature
    0x22: (0x02, 16),  # hair_type / hair_color / hair_part_reversed
    0x24: (0x08, 32),  # eyebrow_* -- swapped vs. file layout
    0x28: (0x04, 32),  # eye_* -- swapped vs. file layout
    0x2C: (0x0C, 16),  # nose_*
    0x2E: (0x0E, 16),  # mouth_*
    0x30: (0x12, 16),  # glasses_* -- swapped vs. file layout
    0x32: (0x10, 16),  # mustache_* / beard_* / facial_hair_color -- swapped vs. file layout
    0x34: (0x14, 16),  # mole_*
}

# Matches the per-slot stride FUN_80055d74 (the Wii-list-fill routine we
# hook for the Phase 2 "Wii Friend" target-Mii panel) copies its decoded
# local record into (see reference_mii_channel_re_facts memory) -- only
# bytes 0-0x16 (the face-part words above) are populated; the rest (name,
# birthday, etc in the real format) stays zero, which is fine since only
# the face bits feed the 96x96 icon render this feature relies on.
LIVE_RECORD_SIZE = 0x50


def pack_live_struct_record(fields: Dict[str, int]) -> bytes:
    """Pack a target Mii's face-part fields (dict of FIELD_SPECS-keyed
    values, e.g. one of targets.py's generated target dicts) into the live
    in-game Mii-editor struct's raw byte layout. Used by client.py to write
    target Miis into Dolphin RAM for the Phase 2 "Wii Friend" panel
    redirect -- see BuildPhase2Hooks.java / reference_mii_channel_re_facts
    memory for the ASM side that reads this buffer."""
    words: Dict[int, int] = {live_off: 0 for live_off, _ in LIVE_WORD_MAP.values()}
    for field_name, (file_word_offset, word_bits, start_from_msb, width) in FIELD_SPECS.items():
        if field_name not in fields:
            continue
        live_off, live_word_bits = LIVE_WORD_MAP[file_word_offset]
        words[live_off] = _pack_bits(words[live_off], live_word_bits, start_from_msb, width, fields[field_name])

    buf = bytearray(LIVE_RECORD_SIZE)
    for live_off, word_bits in LIVE_WORD_MAP.values():
        word = words[live_off]
        if word_bits == 16:
            buf[live_off] = (word >> 8) & 0xFF
            buf[live_off + 1] = word & 0xFF
        else:
            buf[live_off] = (word >> 24) & 0xFF
            buf[live_off + 1] = (word >> 16) & 0xFF
            buf[live_off + 2] = (word >> 8) & 0xFF
            buf[live_off + 3] = word & 0xFF
    return bytes(buf)


def _read_name(b: bytes, off: int, max_chars: int) -> str:
    chars = []
    for i in range(max_chars):
        code = _be16(b, off + i * 2)
        if code == 0:
            break
        chars.append(chr(code))
    return "".join(chars)


@dataclass
class Mii:
    slot: int
    name: str
    creator: str
    gender: int
    is_favorite: bool
    birth_month: int
    birth_day: int
    favorite_color: int
    height: int
    weight: int
    face_shape: int
    skin_color: int
    facial_feature: int
    mingle_off: bool
    hair_type: int
    hair_color: int
    hair_part_reversed: bool
    eyebrow_type: int
    eyebrow_rotation: int
    eyebrow_color: int
    eyebrow_size: int
    eyebrow_vert_pos: int
    eyebrow_horiz_spacing: int
    eye_type: int
    eye_rotation: int
    eye_vert_pos: int
    eye_color: int
    eye_size: int
    eye_horiz_spacing: int
    nose_type: int
    nose_size: int
    nose_vert_pos: int
    mouth_type: int
    mouth_color: int
    mouth_size: int
    mouth_vert_pos: int
    glasses_type: int
    glasses_color: int
    glasses_size: int
    glasses_vert_pos: int
    mustache_type: int
    beard_type: int
    facial_hair_color: int
    mustache_size: int
    mustache_vert_pos: int
    mole_enabled: bool
    mole_size: int
    mole_vert_pos: int
    mole_horiz_pos: int


def _parse_entry(b: bytes, slot: int, off: int) -> Optional[Mii]:
    f0 = _be16(b, off + 0x00)

    # NOTE: bit 0 (MSB) of f0 was originally treated as an "invalid entry"
    # flag, but a Mii freshly created in a brand-new (never-before-used)
    # RFL_DB.dat was empirically observed with this bit set despite having
    # completely valid, in-game-editable data -- so its real meaning isn't
    # "invalid". An empty name is a reliable enough validity signal on its
    # own (a slot with no name is genuinely unused).
    name = _read_name(b, off + 0x02, 10)
    if not name:
        return None

    gender = _bits(f0, 16, 1, 1)
    birth_month = _bits(f0, 16, 2, 4)
    birth_day = _bits(f0, 16, 6, 5)
    favorite_color = _bits(f0, 16, 11, 4)
    is_favorite = bool(_bits(f0, 16, 15, 1))

    height = b[off + 0x16]
    weight = b[off + 0x17]

    f20 = _be16(b, off + 0x20)
    face_shape = _bits(f20, 16, 0, 3)
    skin_color = _bits(f20, 16, 3, 3)
    facial_feature = _bits(f20, 16, 6, 4)
    mingle_off = bool(_bits(f20, 16, 13, 1))

    f22 = _be16(b, off + 0x22)
    hair_type = _bits(f22, 16, 0, 7)
    hair_color = _bits(f22, 16, 7, 3)
    hair_part_reversed = bool(_bits(f22, 16, 10, 1))

    f24 = _be32(b, off + 0x24)
    eyebrow_type = _bits(f24, 32, 0, 5)
    eyebrow_rotation = _bits(f24, 32, 6, 4)
    eyebrow_color = _bits(f24, 32, 16, 3)
    eyebrow_size = _bits(f24, 32, 19, 4)
    eyebrow_vert_pos = _bits(f24, 32, 23, 5)
    eyebrow_horiz_spacing = _bits(f24, 32, 28, 4)

    f28 = _be32(b, off + 0x28)
    eye_type = _bits(f28, 32, 0, 6)
    eye_rotation = _bits(f28, 32, 8, 3)
    eye_vert_pos = _bits(f28, 32, 11, 5)
    eye_color = _bits(f28, 32, 16, 3)
    eye_size = _bits(f28, 32, 20, 3)
    eye_horiz_spacing = _bits(f28, 32, 23, 4)

    f2c = _be16(b, off + 0x2C)
    nose_type = _bits(f2c, 16, 0, 4)
    nose_size = _bits(f2c, 16, 4, 4)
    nose_vert_pos = _bits(f2c, 16, 8, 5)

    f2e = _be16(b, off + 0x2E)
    mouth_type = _bits(f2e, 16, 0, 5)
    mouth_color = _bits(f2e, 16, 5, 2)
    mouth_size = _bits(f2e, 16, 7, 4)
    mouth_vert_pos = _bits(f2e, 16, 11, 5)

    f30 = _be16(b, off + 0x30)
    glasses_type = _bits(f30, 16, 0, 4)
    glasses_color = _bits(f30, 16, 4, 3)
    glasses_size = _bits(f30, 16, 8, 3)
    glasses_vert_pos = _bits(f30, 16, 11, 5)

    f32 = _be16(b, off + 0x32)
    mustache_type = _bits(f32, 16, 0, 2)
    beard_type = _bits(f32, 16, 2, 2)
    facial_hair_color = _bits(f32, 16, 4, 3)
    mustache_size = _bits(f32, 16, 7, 4)
    mustache_vert_pos = _bits(f32, 16, 11, 5)

    f34 = _be16(b, off + 0x34)
    mole_enabled = bool(_bits(f34, 16, 0, 1))
    mole_size = _bits(f34, 16, 1, 4)
    mole_vert_pos = _bits(f34, 16, 5, 5)
    mole_horiz_pos = _bits(f34, 16, 10, 5)

    creator = _read_name(b, off + 0x36, 10)

    return Mii(
        slot=slot, name=name, creator=creator, gender=gender, is_favorite=is_favorite,
        birth_month=birth_month, birth_day=birth_day, favorite_color=favorite_color,
        height=height, weight=weight, face_shape=face_shape, skin_color=skin_color,
        facial_feature=facial_feature, mingle_off=mingle_off, hair_type=hair_type,
        hair_color=hair_color, hair_part_reversed=hair_part_reversed,
        eyebrow_type=eyebrow_type, eyebrow_rotation=eyebrow_rotation,
        eyebrow_color=eyebrow_color, eyebrow_size=eyebrow_size,
        eyebrow_vert_pos=eyebrow_vert_pos, eyebrow_horiz_spacing=eyebrow_horiz_spacing,
        eye_type=eye_type, eye_rotation=eye_rotation, eye_vert_pos=eye_vert_pos,
        eye_color=eye_color, eye_size=eye_size, eye_horiz_spacing=eye_horiz_spacing,
        nose_type=nose_type, nose_size=nose_size, nose_vert_pos=nose_vert_pos,
        mouth_type=mouth_type, mouth_color=mouth_color, mouth_size=mouth_size,
        mouth_vert_pos=mouth_vert_pos, glasses_type=glasses_type,
        glasses_color=glasses_color, glasses_size=glasses_size,
        glasses_vert_pos=glasses_vert_pos, mustache_type=mustache_type,
        beard_type=beard_type, facial_hair_color=facial_hair_color,
        mustache_size=mustache_size, mustache_vert_pos=mustache_vert_pos,
        mole_enabled=mole_enabled, mole_size=mole_size, mole_vert_pos=mole_vert_pos,
        mole_horiz_pos=mole_horiz_pos,
    )


def read_miis(path: str) -> List[Mii]:
    with open(path, "rb") as fh:
        data = fh.read()

    miis: List[Mii] = []
    for slot in range(MAX_SLOTS):
        off = ENTRY_START + slot * ENTRY_SIZE
        if off + ENTRY_SIZE > len(data):
            break
        mii = _parse_entry(data, slot, off)
        if mii is not None:
            miis.append(mii)
    return miis


def find_rfl_db() -> Optional[str]:
    """Best-effort auto-detection of RFL_DB.dat across common Dolphin/Wii setups.

    Checks a dedicated Archipelago-only Dolphin user profile first (if one
    exists) before falling back to the player's regular/default Dolphin
    profile -- so the client never touches a real personal Mii collection by
    accident. See docs/setup_en.md for why this profile is recommended.
    """
    candidates: List[str] = []

    userprofile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    dedicated_menu_dir = os.path.join(
        userprofile, "Documents", "Perso", "Emulateur", "Dolphin_Archipelago_User",
        "Wii", "shared2", "menu", "FaceLib",
    )
    dedicated_path = os.path.join(dedicated_menu_dir, "RFL_DB.dat")

    # If a dedicated Archipelago-only profile has been set up at all (its
    # folder exists), always use it -- even before Mii Channel has created
    # RFL_DB.dat in it yet (read_miis handles a missing file gracefully).
    # Never fall through to the player's real Dolphin profile in that case:
    # doing so even once would mean editing their real Mii collection.
    if os.path.isdir(dedicated_menu_dir):
        return dedicated_path

    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(os.path.join(appdata, "Dolphin Emulator", "Wii", "shared2", "menu", "FaceLib", "RFL_DB.dat"))

    candidates.append(os.path.join(userprofile, "Documents", "Dolphin Emulator", "Wii", "shared2", "menu", "FaceLib", "RFL_DB.dat"))

    xdg_data = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    candidates.append(os.path.join(xdg_data, "dolphin-emu", "Wii", "shared2", "menu", "FaceLib", "RFL_DB.dat"))
    candidates.append(os.path.join(os.path.expanduser("~"), ".dolphin-emu", "Wii", "shared2", "menu", "FaceLib", "RFL_DB.dat"))
    candidates.append(os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Dolphin", "Wii", "shared2", "menu", "FaceLib", "RFL_DB.dat"))

    # Portable installs: a "Dolphin*" folder anywhere alongside the client, or on any drive root.
    for pattern in ("Dolphin*/User/Wii/shared2/menu/FaceLib/RFL_DB.dat", "*/Wii/shared2/menu/FaceLib/RFL_DB.dat"):
        candidates.extend(glob.glob(pattern))

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


_FIELD_WORD_BITS: Dict[int, int] = {}
for _fname, (_woff, _wbits, _start, _width) in FIELD_SPECS.items():
    _FIELD_WORD_BITS[_woff] = _wbits


MII_ID_OFFSET = 0x18
MII_ID_SIZE = 8


def _make_mii_id(name: str, slot: int) -> bytes:
    """Synthesize a non-zero, per-slot-unique 8-byte "Mii ID" (RFLCreateID)
    for offset 0x18 of a record. A real Mii's on-disk entry always has a
    high-entropy, non-zero value here (creation timestamp + console-derived
    bytes) -- empirically an entry written with this field left at all-zero
    (our original pack_file_record behavior) is silently treated as an
    empty/invalid slot by the real game and never appears on screen, even
    though every other field parses fine. We don't need to replicate the
    real timestamp/console-ID semantics, just guarantee non-zero and unique
    per slot so the game's loader accepts the entry."""
    import hashlib
    digest = hashlib.md5(f"{name}:{slot}".encode("utf-8")).digest()[:MII_ID_SIZE]
    if digest == b"\x00" * MII_ID_SIZE:  # practically impossible, but stay safe
        digest = b"\x01" + digest[1:]
    return digest


def pack_file_record(
    fields: Dict[str, int], name: str, creator: str = "", slot: int = 0, mii_id: Optional[bytes] = None,
) -> bytes:
    """Pack a target Mii dict (targets.py's generate_targets format: the
    FIELD_SPECS face-part fields plus 'height'/'weight') into a full
    ENTRY_SIZE-byte on-disk RFL_DB.dat record, with the given display name.
    Unlike pack_live_struct_record, this uses the FILE's own word layout
    (FIELD_SPECS directly, no eye/eyebrow or glasses/mustache swap).

    `mii_id`, if given, is used verbatim instead of synthesizing one --
    pass the ID read back from an existing real (player-created) slot here.
    The real game's loader silently drops any entry whose synthesized ID it
    doesn't recognize as one it legitimately generated itself (confirmed
    empirically -- see project memory), so a synthesized ID only works for
    entries that already had a real one; there is currently no known way to
    make the game accept an entirely new synthesized identity."""
    buf = bytearray(ENTRY_SIZE)

    name = name[:10]
    for i, ch in enumerate(name):
        code = ord(ch)
        buf[0x02 + i * 2] = (code >> 8) & 0xFF
        buf[0x02 + i * 2 + 1] = code & 0xFF

    creator = creator[:10]
    for i, ch in enumerate(creator):
        code = ord(ch)
        buf[0x36 + i * 2] = (code >> 8) & 0xFF
        buf[0x36 + i * 2 + 1] = code & 0xFF

    buf[0x16] = fields.get("height", 64) & 0xFF
    buf[0x17] = fields.get("weight", 64) & 0xFF

    buf[MII_ID_OFFSET:MII_ID_OFFSET + MII_ID_SIZE] = mii_id if mii_id is not None else _make_mii_id(name, slot)

    words: Dict[int, int] = {woff: 0 for woff in _FIELD_WORD_BITS}
    for field_name, (word_offset, word_bits, start_from_msb, width) in FIELD_SPECS.items():
        if field_name not in fields:
            continue
        words[word_offset] = _pack_bits(words[word_offset], word_bits, start_from_msb, width, fields[field_name])

    for word_offset, value in words.items():
        word_bits = _FIELD_WORD_BITS[word_offset]
        if word_bits == 16:
            buf[word_offset] = (value >> 8) & 0xFF
            buf[word_offset + 1] = value & 0xFF
        else:
            buf[word_offset] = (value >> 24) & 0xFF
            buf[word_offset + 1] = (value >> 16) & 0xFF
            buf[word_offset + 2] = (value >> 8) & 0xFF
            buf[word_offset + 3] = value & 0xFF

    return bytes(buf)


def claim_target_preview(path: str, current_name: str, new_name: str, fields: Dict[str, int]) -> bool:
    """Turn an existing, real (player-created) Mii into a target-preview
    placeholder: renames it to `new_name` and overwrites its face fields to
    `fields` (a targets.py-format dict), while preserving that slot's own
    real, game-issued Mii ID untouched. This is the ONLY known way to make
    a "new" identity show up correctly in-game -- see `pack_file_record`'s
    docstring and project memory for why synthesizing a fresh ID doesn't
    work. Destructive: the Mii previously at `current_name` is permanently
    overwritten (only its identity/ID survives) -- callers must get clear
    player confirmation before calling this (e.g. an explicit client
    command naming the Mii to sacrifice), never do this automatically
    without the player picking which Mii to use.

    Returns False (no changes made) if no Mii is currently named
    `current_name`; True on success."""
    with open(path, "r+b") as fh:
        fh.seek(0)
        data = bytearray(fh.read())

        target_off: Optional[int] = None
        for slot in range(MAX_SLOTS):
            off = ENTRY_START + slot * ENTRY_SIZE
            if off + ENTRY_SIZE > len(data):
                break
            name_bytes = data[off + 0x02:off + 0x02 + 20]
            name = _read_name(bytes(name_bytes), 0, 10)
            if name == current_name:
                target_off = off
                break

        if target_off is None:
            return False

        existing_id = bytes(data[target_off + MII_ID_OFFSET:target_off + MII_ID_OFFSET + MII_ID_SIZE])
        record = pack_file_record(fields, new_name, mii_id=existing_id)
        data[target_off:target_off + ENTRY_SIZE] = record

        new_crc = crc16_ccitt(bytes(data[:CRC_OFFSET]))
        data[CRC_OFFSET:CRC_OFFSET + 2] = new_crc.to_bytes(2, "big")

        fh.seek(0)
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())

    return True


def write_mii_field(path: str, slot: int, field_name: str, value: int) -> None:
    """
    Revert a single field on a single Mii slot to `value`, in place, and
    recompute+rewrite the file's CRC16 footer so the result is a fully valid
    RFL_DB.dat (see crc16_ccitt -- verified against a real Dolphin save).

    This still only touches the 2-4 bytes for that one field plus the 2-byte
    CRC footer (not a full-file rewrite), to minimize the chance of colliding
    with a concurrent write from a running Dolphin.
    """
    word_offset, word_bits, start_from_msb, width = FIELD_SPECS[field_name]
    word_size = word_bits // 8

    entry_offset = ENTRY_START + slot * ENTRY_SIZE
    abs_offset = entry_offset + word_offset

    with open(path, "r+b") as fh:
        fh.seek(abs_offset)
        raw = fh.read(word_size)
        current = int.from_bytes(raw, "big")
        new_word = _pack_bits(current, word_bits, start_from_msb, width, value)

        fh.seek(abs_offset)
        fh.write(new_word.to_bytes(word_size, "big"))
        fh.flush()

        fh.seek(0)
        full = fh.read(CRC_OFFSET)
        new_crc = crc16_ccitt(full)

        fh.seek(CRC_OFFSET)
        fh.write(new_crc.to_bytes(2, "big"))

        fh.flush()
        os.fsync(fh.fileno())


# --- Live Dolphin RAM support -----------------------------------------------
#
# The Mii Channel keeps a "committed" copy of each Mii (post-confirm,
# pre-disk-save) in the Wii's MEM1/MEM2 as the exact same 74-byte
# RFLiMiiDataCore layout used in RFL_DB.dat. We locate it at runtime by
# searching for the Mii's UTF-16BE name (memory addresses are not stable
# across game sessions), then read-modify-write individual fields the same
# way write_mii_field does for the file -- except here, because the *game*
# is the one that eventually flushes this RAM to disk, it recomputes its own
# CRC16 on save, so there's no checksum-corruption risk like the old
# file-patching approach had.

MEM1_BASE = 0x80000000
MEM1_SIZE = 0x01800000  # 24 MiB
MEM2_BASE = 0x90000000
MEM2_SIZE = 0x04000000  # 64 MiB


def read_wii_memory(dme) -> List[tuple]:
    """Read all of MEM1 and MEM2 via dolphin_memory_engine. Returns
    [(base_addr, data), ...], skipping any region that fails to read."""
    chunks = []
    for base, size in ((MEM1_BASE, MEM1_SIZE), (MEM2_BASE, MEM2_SIZE)):
        try:
            chunks.append((base, dme.read_bytes(base, size)))
        except Exception:
            pass
    return chunks


def find_mii_entries_by_name(memory_chunks: List[tuple], name: str) -> List["tuple[int, Mii]"]:
    """Search already-read memory chunks for every live Mii entry whose name
    matches `name` exactly. Returns [(entry_addr, Mii), ...]."""
    needle = name.encode("utf-16-be")
    results = []
    for base, data in memory_chunks:
        start = 0
        while True:
            idx = data.find(needle, start)
            if idx == -1:
                break
            start = idx + 1
            entry_off = idx - 0x02
            if entry_off < 0 or entry_off + ENTRY_SIZE > len(data):
                continue
            raw = data[entry_off:entry_off + ENTRY_SIZE]
            mii = _parse_entry(raw, slot=0, off=0)
            if mii is not None and mii.name == name:
                results.append((base + entry_off, mii))
    return results


def write_mii_field_ram(dme, entry_addr: int, field_name: str, value: int) -> None:
    """Same targeted read-modify-write as write_mii_field, but against live
    Dolphin RAM at `entry_addr` (as returned by find_mii_entries_by_name)."""
    word_offset, word_bits, start_from_msb, width = FIELD_SPECS[field_name]
    word_size = word_bits // 8
    abs_addr = entry_addr + word_offset

    current = int.from_bytes(dme.read_bytes(abs_addr, word_size), "big")
    new_word = _pack_bits(current, word_bits, start_from_msb, width, value)
    dme.write_bytes(abs_addr, new_word.to_bytes(word_size, "big"))
