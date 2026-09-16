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
from typing import Dict, List, Optional, Tuple

ENTRY_START = 0x04
ENTRY_SIZE = 0x4A
MAX_SLOTS = 100

# Right after the 100-entry array (0x04 + 100 * 0x4A) sits the slot-usage
# bitmap, MSB-first: slot N is byte SLOT_BITMAP_OFFSET + N // 8, bit
# 0x80 >> (N % 8). THIS is what the game treats as "is this slot occupied",
# not the entry contents -- an entry whose bit is clear is ignored on load
# AND zeroed out when the game next writes the file back. Confirmed live
# (2026-09-04): entries written without their bit set were actively purged,
# which for a long time looked like the game rejecting synthesized Miis.
SLOT_BITMAP_OFFSET = 0x1CEC

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
    # f0 "options" word (offset 0x00) -- gender/birthday bits live here too
    # but aren't currently used by anything, so aren't listed; only the two
    # fields this project actually reads/writes are.
    "favorite_color": (0x00, 16, 11, 4),
    "is_favorite": (0x00, 16, 15, 1),
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
# layout above) was long believed to pack the SAME per-field bit layout into
# each word. Measured live on 2026-09-11 that is FALSE for the eye and
# eyebrow words, which are reordered (see BuildTrampolineV13.java for the
# measured layouts of every word); the halfword categories do match. So
# pack_live_struct_record below is wrong for eyes/eyebrows -- it is only
# used by the abandoned Phase 2 panel code. The word offsets are right: eye and
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
    # 8-byte Mii id (file offset 0x18): how the running game refers to a Mii,
    # e.g. in the object that mirrors the Mii currently picked up.
    mii_id: bytes = b""


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
        mole_horiz_pos=mole_horiz_pos, mii_id=bytes(b[off + 0x18:off + 0x20]),
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

    `mii_id`, if given, is used verbatim instead of synthesizing one.

    WARNING: a record built by this function is REJECTED by the game (it
    gets zeroed out on the next load) because every field absent from
    `fields` is left at 0, and 0 is out of valid range for the size and
    position fields. Use `clone_entry` instead to build a displayable Mii --
    it inherits valid values for everything it isn't explicitly told to
    change. This function remains only for `claim_target_preview`, which
    overwrites a full real entry anyway."""
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


MII_CHANNEL_TITLE_ID = "0001000248414341"  # NAND title 00010002/48414341 ("HACA")

# A real, game-created entry, captured from a live RFL_DB.dat and kept here
# so target previews can be written into a completely empty save.
# clone_entry only makes sense against a record the game itself produced:
# every field it isn't told to change has to already hold a valid value
# (a record built from zeroes gets purged on load -- see clone_entry). Its
# name and Mii ID are always overwritten, so only the field values and the
# console ID it carries survive into a preview.
_TEMPLATE_ENTRY_B64 = (
    "AAIAVAAxACAANgAvADIANQAAAAAAAEBAibi7CcLG5qsABEJBMb0oogiMCEgUSbiNAIoAiiUFAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAA="
)


def _slot_bit(slot: int) -> Tuple[int, int]:
    return SLOT_BITMAP_OFFSET + slot // 8, 0x80 >> (slot % 8)


def slot_in_use(data: bytes, slot: int) -> bool:
    byte_index, mask = _slot_bit(slot)
    return bool(data[byte_index] & mask)


def set_slot_in_use(data: bytearray, slot: int, in_use: bool) -> None:
    byte_index, mask = _slot_bit(slot)
    if in_use:
        data[byte_index] |= mask
    else:
        data[byte_index] &= ~mask & 0xFF


def make_mii_id(console_id: bytes, seconds_ago: int = 0) -> bytes:
    """Synthesize a Mii ID the game accepts (confirmed live 2026-09-04).

    Layout: top nibble 0x8 (created-on-a-Wii flag), low 28 bits =
    (seconds since 2006-01-01) / 4 in LOCAL time -- not UTC, verified by
    decoding a real Mii's ID back to the exact minute it was created --
    followed by the 4-byte console ID, which is copied from an existing
    entry rather than invented.

    `seconds_ago` backdates the timestamp, so a batch of Miis written in the
    same instant still get distinct IDs."""
    import datetime

    when = datetime.datetime.now() - datetime.timedelta(seconds=seconds_ago)
    ticks = int((when - datetime.datetime(2006, 1, 1)).total_seconds()) // 4
    return (0x80000000 | (ticks & 0x0FFFFFFF)).to_bytes(4, "big") + console_id


def clone_entry(source: bytes, name: str, mii_id: bytes, fields: Dict[str, int]) -> bytes:
    """Build a displayable entry by cloning a real one and overriding only
    name, ID and the given face fields.

    This is the ONLY way found that makes the game accept a Mii it didn't
    create itself: packing a record from scratch leaves the size/position
    fields at 0, which is out of range and gets the entry purged, whereas
    everything left untouched here inherits already-valid values."""
    record = bytearray(source)

    for i in range(10):
        code = ord(name[i]) if i < len(name) else 0
        record[0x02 + i * 2] = (code >> 8) & 0xFF
        record[0x02 + i * 2 + 1] = code & 0xFF

    record[MII_ID_OFFSET:MII_ID_OFFSET + MII_ID_SIZE] = mii_id

    if "height" in fields:
        record[0x16] = fields["height"] & 0xFF
    if "weight" in fields:
        record[0x17] = fields["weight"] & 0xFF

    for field_name, (word_offset, word_bits, start_from_msb, width) in FIELD_SPECS.items():
        if field_name not in fields:
            continue
        size = word_bits // 8
        word = int.from_bytes(record[word_offset:word_offset + size], "big")
        word = _pack_bits(word, word_bits, start_from_msb, width, fields[field_name])
        record[word_offset:word_offset + size] = word.to_bytes(size, "big")

    return bytes(record)


def write_synthetic_miis(path: str, entries: List[Tuple[str, Dict[str, int]]]) -> List[int]:
    """Write a batch of fully synthetic Miis (e.g. the AP target previews)
    into free slots, so they show up in the Plaza next to the player's own.

    Idempotent: any existing Mii whose name matches one of `entries` is
    freed first, so calling this again just refreshes them. Player Miis are
    never touched -- only free slots (bitmap bit clear) are used.

    Clones one of the player's own Miis when there is one (so previews carry
    this console's own ID), and falls back to the entry embedded above when
    the save is empty -- otherwise a brand-new game would show no targets
    until the player had created a Mii, which is exactly when they most need
    to see what to build."""
    wanted_names = {name for name, _ in entries}

    with open(path, "r+b") as fh:
        data = bytearray(fh.read())

        template: Optional[bytes] = None
        for slot in range(MAX_SLOTS):
            off = ENTRY_START + slot * ENTRY_SIZE
            if not slot_in_use(data, slot):
                continue
            name = _read_name(bytes(data[off + 0x02:off + 0x02 + 20]), 0, 10)
            # A slot the bitmap calls used but whose entry is blank is a
            # leaked slot: the game zeroes entries it rejects without ever
            # clearing their bit, so without this it would stay unusable
            # forever and previews would drift further down the file on
            # every rewrite.
            if name in wanted_names or not name:
                data[off:off + ENTRY_SIZE] = bytes(ENTRY_SIZE)
                set_slot_in_use(data, slot, False)
            elif template is None:
                template = bytes(data[off:off + ENTRY_SIZE])

        if template is None:
            import base64
            template = base64.b64decode(_TEMPLATE_ENTRY_B64)

        console_id = template[MII_ID_OFFSET + 4:MII_ID_OFFSET + MII_ID_SIZE]
        free_slots = [s for s in range(MAX_SLOTS) if not slot_in_use(data, s)]

        written: List[int] = []
        for (name, fields), slot in zip(entries, free_slots):
            record = clone_entry(template, name, make_mii_id(console_id, 60 * (len(written) + 1)), fields)
            off = ENTRY_START + slot * ENTRY_SIZE
            data[off:off + ENTRY_SIZE] = record
            set_slot_in_use(data, slot, True)
            written.append(slot)

        new_crc = crc16_ccitt(bytes(data[:CRC_OFFSET]))
        data[CRC_OFFSET:CRC_OFFSET + 2] = new_crc.to_bytes(2, "big")

        fh.seek(0)
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())

    return written


# --- Mii Parade (RFL's "hidden database") ------------------------------------
#
# Layout read straight off the game's own code (Ghidra, 2026-09-11):
#   FUN_80147dd4 (format)      'RNHD' at 0x1D00, u16 head at 0x1D04, u16 tail at
#                              0x1D06 (0xFFFF = empty), then 10000 list entries.
#   FUN_8013ca98 (append)      entry = 8-byte Mii id, u16 next, u16 prev; 15-bit
#                              indices, 0x7FFF = none; bit 15 of `next` = the
#                              Mii's gender bit (0x4000 of its first u16).
#   FUN_8013c55c (remove)      standard doubly-linked unlink, fixing head/tail.
#   FUN_8013ea44 (Plaza->Parade record)  first 0x36 bytes of the Plaza record,
#                              rest zero, birthday bits cleared (& 0xC01F) --
#                              which is why a Mii sent to the Parade loses its
#                              birthday and creator.
#   FUN_8013ccb8 (send)        the 0x40-byte record goes to 0x1F1E0 + index*0x40,
#                              outside the CRC; the list itself is inside it.
#   FUN_80146994 (Parade view) does NOT walk the list: it scans all 10000 entries
#                              for a non-null id, shuffles them, and loads each
#                              record, rejecting one whose id doesn't match.
# The 2026-09-05 attempt read the entries at 0x1D04 instead of 0x1D08 -- four
# bytes off -- which is why a hand-built list showed one Mii or thousands.
PARADE_HEAD_OFFSET = 0x1D04
PARADE_TAIL_OFFSET = 0x1D06
PARADE_LIST_OFFSET = 0x1D08
PARADE_LIST_STRIDE = 12
PARADE_CAPACITY = 10000
PARADE_NONE = 0x7FFF
PARADE_DATA_OFFSET = 0x1F1E0
PARADE_RECORD_SIZE = 0x40
PARADE_COPIED_BYTES = 0x36


@dataclass
class ParadeEntry:
    index: int
    mii_id: bytes
    next: int
    prev: int
    gender_flag: int
    record: bytes

    @property
    def name(self) -> str:
        return _read_name(self.record, 0x02, 10)


def plaza_to_parade_record(record: bytes) -> bytes:
    """What the game itself stores when a Mii is sent to the Parade."""
    out = bytearray(PARADE_RECORD_SIZE)
    out[:PARADE_COPIED_BYTES] = record[:PARADE_COPIED_BYTES]
    first = int.from_bytes(out[0:2], "big") & 0xC01F
    out[0:2] = first.to_bytes(2, "big")
    return bytes(out)


def read_parade(path: str) -> Tuple[int, int, List[ParadeEntry]]:
    """(head, tail, every entry with a non-null id), in index order."""
    with open(path, "rb") as fh:
        data = fh.read()
    head = _be16(data, PARADE_HEAD_OFFSET)
    tail = _be16(data, PARADE_TAIL_OFFSET)
    entries: List[ParadeEntry] = []
    for i in range(PARADE_CAPACITY):
        off = PARADE_LIST_OFFSET + i * PARADE_LIST_STRIDE
        mii_id = data[off:off + 8]
        if mii_id == bytes(8):
            continue
        nxt = _be16(data, off + 8)
        prv = _be16(data, off + 10)
        rec_off = PARADE_DATA_OFFSET + i * PARADE_RECORD_SIZE
        entries.append(ParadeEntry(i, mii_id, nxt & 0x7FFF, prv & 0x7FFF, nxt >> 15,
                                   data[rec_off:rec_off + PARADE_RECORD_SIZE]))
    return head, tail, entries


def write_parade_miis(path: str, entries: List[Tuple[str, Dict[str, int]]],
                      id_offset_seconds: int = 3600) -> List[int]:
    """Put `entries` (name, face fields) in the Mii Parade, replacing any
    earlier Parade Mii with the same name and keeping every other one.

    The list is rebuilt in canonical form -- kept Miis first, then the new
    ones, at indices 0..K-1, chained next/prev, head 0, tail K-1 -- rather
    than patched in place: the game keys Parade Miis by id, never by index,
    so renumbering is harmless, and it repairs whatever state earlier
    experiments left behind (this file had head 0x7FFF, i.e. no valid head).

    IDs are backdated by `id_offset_seconds` so they never collide with the
    Plaza previews written in the same instant (same console id): two Miis
    sharing an id would be the same Mii to the game.

    Must only run while Dolphin is closed -- the running game owns the file
    and writes its in-memory copy of this region back."""
    import base64

    wanted = {name for name, _ in entries}
    with open(path, "r+b") as fh:
        data = bytearray(fh.read())

        _, _, current = read_parade(path)
        kept = [e for e in current if e.name not in wanted]

        template: Optional[bytes] = None
        for slot in range(MAX_SLOTS):
            off = ENTRY_START + slot * ENTRY_SIZE
            if slot_in_use(data, slot) and _read_name(bytes(data[off + 2:off + 22]), 0, 10):
                template = bytes(data[off:off + ENTRY_SIZE])
                break
        if template is None:
            template = base64.b64decode(_TEMPLATE_ENTRY_B64)
        console_id = template[MII_ID_OFFSET + 4:MII_ID_OFFSET + MII_ID_SIZE]

        new_records: List[bytes] = []
        for k, (name, fields) in enumerate(entries):
            plaza = clone_entry(template, name,
                                make_mii_id(console_id, id_offset_seconds + 60 * (k + 1)), fields)
            new_records.append(plaza_to_parade_record(plaza))

        final = [e.record for e in kept] + new_records
        if len(final) > PARADE_CAPACITY:
            raise ValueError("Parade full")

        # Clear the whole list and every record slot previously in use.
        for i in range(PARADE_CAPACITY):
            off = PARADE_LIST_OFFSET + i * PARADE_LIST_STRIDE
            data[off:off + 8] = bytes(8)
            data[off + 8:off + 10] = PARADE_NONE.to_bytes(2, "big")
            data[off + 10:off + 12] = PARADE_NONE.to_bytes(2, "big")
        for e in current:
            rec_off = PARADE_DATA_OFFSET + e.index * PARADE_RECORD_SIZE
            data[rec_off:rec_off + PARADE_RECORD_SIZE] = bytes(PARADE_RECORD_SIZE)

        count = len(final)
        for i, record in enumerate(final):
            gender = (int.from_bytes(record[0:2], "big") >> 14) & 1
            nxt = i + 1 if i + 1 < count else PARADE_NONE
            prv = i - 1 if i > 0 else PARADE_NONE
            off = PARADE_LIST_OFFSET + i * PARADE_LIST_STRIDE
            data[off:off + 8] = record[MII_ID_OFFSET:MII_ID_OFFSET + MII_ID_SIZE]
            data[off + 8:off + 10] = ((gender << 15) | nxt).to_bytes(2, "big")
            data[off + 10:off + 12] = prv.to_bytes(2, "big")
            rec_off = PARADE_DATA_OFFSET + i * PARADE_RECORD_SIZE
            data[rec_off:rec_off + PARADE_RECORD_SIZE] = record

        head = 0 if count else 0xFFFF
        tail = count - 1 if count else 0xFFFF
        data[PARADE_HEAD_OFFSET:PARADE_HEAD_OFFSET + 2] = head.to_bytes(2, "big")
        data[PARADE_TAIL_OFFSET:PARADE_TAIL_OFFSET + 2] = tail.to_bytes(2, "big")

        new_crc = crc16_ccitt(bytes(data[:CRC_OFFSET]))
        data[CRC_OFFSET:CRC_OFFSET + 2] = new_crc.to_bytes(2, "big")

        fh.seek(0)
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())

    return list(range(len(kept), count))


def remove_miis_by_name(path: str, names) -> int:
    """Delete every Plaza Mii whose name is in `names` (entry zeroed, slot
    bit cleared -- the bitmap is what the game trusts -- CRC rewritten).
    Returns how many were removed. Dolphin must be closed."""
    wanted = set(names)
    with open(path, "r+b") as fh:
        data = bytearray(fh.read())
        removed = 0
        for slot in range(MAX_SLOTS):
            off = ENTRY_START + slot * ENTRY_SIZE
            if not slot_in_use(data, slot):
                continue
            if _read_name(bytes(data[off + 0x02:off + 0x02 + 20]), 0, 10) in wanted:
                data[off:off + ENTRY_SIZE] = bytes(ENTRY_SIZE)
                set_slot_in_use(data, slot, False)
                removed += 1
        if removed:
            new_crc = crc16_ccitt(bytes(data[:CRC_OFFSET]))
            data[CRC_OFFSET:CRC_OFFSET + 2] = new_crc.to_bytes(2, "big")
            fh.seek(0)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    return removed


# Fields stored as a whole byte of the entry rather than a FIELD_SPECS
# bitfield. Writing them through FIELD_SPECS raised KeyError halfway through
# a trap (user 2026-09-16: Shuffle and Default did nothing).
BYTE_FIELDS: Dict[str, int] = {"height": 0x16, "weight": 0x17}


def _field_layout(field_name: str) -> Tuple[int, int, int, int]:
    """(word offset, word bits, start from msb, width) of any writable field."""
    if field_name in BYTE_FIELDS:
        return BYTE_FIELDS[field_name], 8, 0, 8
    return FIELD_SPECS[field_name]


def write_mii_field(path: str, slot: int, field_name: str, value: int) -> None:
    """
    Revert a single field on a single Mii slot to `value`, in place, and
    recompute+rewrite the file's CRC16 footer so the result is a fully valid
    RFL_DB.dat (see crc16_ccitt -- verified against a real Dolphin save).

    This still only touches the 2-4 bytes for that one field plus the 2-byte
    CRC footer (not a full-file rewrite), to minimize the chance of colliding
    with a concurrent write from a running Dolphin.
    """
    word_offset, word_bits, start_from_msb, width = _field_layout(field_name)
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


def write_mii_fields(path: str, slot: int, changes: Dict[str, int]) -> None:
    """write_mii_field for several fields of one Mii at once: every word
    patched, then a single CRC recompute (a trap re-rolls ~40 fields)."""
    layouts = {name: _field_layout(name) for name in changes}   # unknown field: nothing written
    entry_offset = ENTRY_START + slot * ENTRY_SIZE
    with open(path, "r+b") as fh:
        for field_name, value in changes.items():
            word_offset, word_bits, start_from_msb, width = layouts[field_name]
            word_size = word_bits // 8
            fh.seek(entry_offset + word_offset)
            current = int.from_bytes(fh.read(word_size), "big")
            fh.seek(entry_offset + word_offset)
            fh.write(_pack_bits(current, word_bits, start_from_msb, width, value).to_bytes(word_size, "big"))
        fh.flush()
        fh.seek(0)
        new_crc = crc16_ccitt(fh.read(CRC_OFFSET))
        fh.seek(CRC_OFFSET)
        fh.write(new_crc.to_bytes(2, "big"))
        fh.flush()
        os.fsync(fh.fileno())


def write_mii_name(path: str, slot: int, name: str) -> None:
    """Rename a single Mii slot in place (name bytes only, ID/face fields
    untouched), recomputing the CRC footer. Used to give a player's own Mii
    a permanent visual confirmation when it achieves a "Perfect Copy" match
    (see client.py) -- same safe small-patch pattern as write_mii_field."""
    name = name[:10]
    name_bytes = bytearray(20)
    for i, ch in enumerate(name):
        code = ord(ch)
        name_bytes[i * 2] = (code >> 8) & 0xFF
        name_bytes[i * 2 + 1] = code & 0xFF

    entry_offset = ENTRY_START + slot * ENTRY_SIZE
    abs_offset = entry_offset + 0x02

    with open(path, "r+b") as fh:
        fh.seek(abs_offset)
        fh.write(bytes(name_bytes))
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


def find_mii_entries_by_name(memory_chunks: List[tuple], name: str,
                             mii_id: Optional[bytes] = None) -> List["tuple[int, Mii]"]:
    """Search already-read memory chunks for every live Mii entry whose name
    matches `name` exactly. Returns [(entry_addr, Mii), ...].

    Pass the Mii's 8-byte id whenever something will be WRITTEN there: a short
    name matches all over RAM (user 2026-09-16: a Default Trap on a Mii named
    "'" wrote Mii fields into the game's memory and crashed it). The whole
    20-byte name field must match too, padding included."""
    needle = name.encode("utf-16-be")
    name_field = needle[:20].ljust(20, b"\0")
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
            if raw[0x02:0x16] != name_field:
                continue
            if mii_id is not None and raw[MII_ID_OFFSET:MII_ID_OFFSET + MII_ID_SIZE] != mii_id:
                continue
            mii = _parse_entry(raw, slot=0, off=0)
            if mii is not None and mii.name == name:
                results.append((base + entry_off, mii))
    return results


CREATOR_OFFSET = 0x36
CREATOR_SIZE = 20  # 10 UTF-16 characters, same as the name


def write_mii_creator(path: str, slot: int, text: str) -> None:
    """Overwrite a Mii's creator name (10 characters) and fix the CRC.

    The Mii Channel shows this line right under the name when a Mii is
    clicked in the Plaza -- confirmed live -- which makes it a second
    readable text field. The mod puts its progress readout here rather than
    in the name, so the player keeps the name they chose."""
    with open(path, "r+b") as fh:
        data = bytearray(fh.read())
        off = ENTRY_START + slot * ENTRY_SIZE + CREATOR_OFFSET
        encoded = text[:10].encode("utf-16-be")
        data[off:off + CREATOR_SIZE] = encoded + b"\x00" * (CREATOR_SIZE - len(encoded))

        new_crc = crc16_ccitt(bytes(data[:CRC_OFFSET]))
        data[CRC_OFFSET:CRC_OFFSET + 2] = new_crc.to_bytes(2, "big")

        fh.seek(0)
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def write_mii_creator_ram(dme, entry_addr: int, text: str) -> None:
    """Same as write_mii_creator but against the running game's own copy,
    so the bubble updates without leaving the channel."""
    encoded = text[:10].encode("utf-16-be")
    dme.write_bytes(entry_addr + CREATOR_OFFSET, encoded + b"\x00" * (CREATOR_SIZE - len(encoded)))


def write_mii_name_ram(dme, entry_addr: int, name: str) -> None:
    """Patch a Mii's name in live Dolphin RAM (20 bytes at entry+0x02).

    The game keeps its own copy of the Mii list in memory and never re-reads
    RFL_DB.dat while running, so a rename on disk alone stays invisible
    until the channel is re-entered. Patching the live copy too is what
    makes an in-game progress counter update while the player is playing."""
    encoded = name[:10].encode("utf-16-be")
    dme.write_bytes(entry_addr + 0x02, encoded + b"\x00" * (20 - len(encoded)))


def write_mii_field_ram(dme, entry_addr: int, field_name: str, value: int) -> None:
    """Same targeted read-modify-write as write_mii_field, but against live
    Dolphin RAM at `entry_addr` (as returned by find_mii_entries_by_name)."""
    word_offset, word_bits, start_from_msb, width = _field_layout(field_name)
    word_size = word_bits // 8
    abs_addr = entry_addr + word_offset

    current = int.from_bytes(dme.read_bytes(abs_addr, word_size), "big")
    new_word = _pack_bits(current, word_bits, start_from_msb, width, value)
    dme.write_bytes(abs_addr, new_word.to_bytes(word_size, "big"))
