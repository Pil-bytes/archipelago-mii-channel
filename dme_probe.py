"""
DOL -> flat memory image converter (for importing into Ghidra as Raw Binary
at the correct base address, sidestepping the GameCubeLoader extension not
being picked up by Ghidra's headless ClassSearcher).

DOL header (0x100 bytes):
  0x00: 7x u32 text section file offsets
  0x1C: 11x u32 data section file offsets
  0x48: 7x u32 text section load addresses
  0x64: 11x u32 data section load addresses
  0x90: 7x u32 text section sizes
  0xAC: 11x u32 data section sizes
  0xD8: u32 bss load address
  0xDC: u32 bss size
  0xE0: u32 entry point
"""
import os
import tempfile
import struct
import time

LOG_PATH = r"C:\Users\player\AppData\Local\Temp\mii_probe\dme_probe_result.log"
DOL_PATH = r"C:\Users\player\Documents\Perso\Emulateur\Tools\mii_channel_re\main.dol"
OUT_PATH = r"C:\Users\player\Documents\Perso\Emulateur\Tools\mii_channel_re\main_flat.bin"

MEM1_BASE = 0x80000000
MEM1_SIZE = 0x01800000
MEM2_BASE = 0x90000000
MEM2_SIZE = 0x04000000

DUMP_A = r"C:\Users\player\AppData\Local\Temp\mii_probe\eyetype_before.bin"
DUMP_B = r"C:\Users\player\AppData\Local\Temp\mii_probe\eyetype_after.bin"
DUMP_IDLE1 = r"C:\Users\player\AppData\Local\Temp\mii_probe\eyetype_idle1.bin"
DUMP_IDLE2 = r"C:\Users\player\AppData\Local\Temp\mii_probe\eyetype_idle2.bin"


R6_WINDOW_PATH_1 = r"C:\Users\player\AppData\Local\Temp\mii_probe\r6_window_1.bin"
R6_WINDOW_PATH_2 = r"C:\Users\player\AppData\Local\Temp\mii_probe\r6_window_2.bin"
R6_WINDOW_RADIUS = 0x2000


def _get_r6(dme):
    # r6 (the live Mii-edit struct pointer, *(int*)(*(int*)(r13-0x7064)+0xbc))
    # has been confirmed deterministic/stable across multiple separate
    # Dolphin sessions this project (same guest address every boot, since
    # Wii/GC games don't randomize heap layout) -- hardcode it rather than
    # depending on a capture trampoline being currently deployed (the "real
    # lock check" eye trampoline no longer writes it to scratch). Re-verify
    # this assumption if anything seems off (e.g. via find_committed mode).
    return 0x906919BC


def do_snapshot_near_r6(log, out_path):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked.")
        return
    r6 = _get_r6(dme)
    if not r6:
        log("r6 not captured yet (is the trampoline armed and has the eye category been visited?)")
        return
    start = r6 - R6_WINDOW_RADIUS
    data = dme.read_bytes(start, R6_WINDOW_RADIUS * 2)
    with open(out_path, "wb") as fh:
        fh.write(data)
    log(f"r6=0x{r6:08X}, window [0x{start:08X}, 0x{start + len(data):08X}) written to {out_path}")


def do_diff_near_r6(log):
    with open(R6_WINDOW_PATH_1, "rb") as fh:
        before = fh.read()
    with open(R6_WINDOW_PATH_2, "rb") as fh:
        after = fh.read()
    n = min(len(before), len(after))
    log(f"Comparing {n} bytes (window radius 0x{R6_WINDOW_RADIUS:X} around r6)")
    diffs = []
    for off in range(0, n - 4, 1):
        if before[off:off + 4] != after[off:off + 4]:
            diffs.append(off)
    # Collapse contiguous/overlapping byte-level diffs into word-aligned groups.
    reported = set()
    for off in diffs:
        word_off = off - (off % 4)
        if word_off in reported:
            continue
        reported.add(word_off)
        b_val = struct.unpack(">I", before[word_off:word_off + 4])[0]
        a_val = struct.unpack(">I", after[word_off:word_off + 4])[0]
        rel = word_off - R6_WINDOW_RADIUS
        sign = "+" if rel >= 0 else "-"
        log(f"  r6{sign}0x{abs(rel):X}: 0x{b_val:08X} -> 0x{a_val:08X}  (top6: {b_val>>26} -> {a_val>>26})")
    log(f"Total distinct word offsets changed: {len(reported)}")


def do_snapshot(log, out_path):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked.")
        return
    m1 = dme.read_bytes(MEM1_BASE, MEM1_SIZE)
    m2 = dme.read_bytes(MEM2_BASE, MEM2_SIZE)
    with open(out_path, "wb") as fh:
        fh.write(m1)
        fh.write(m2)
    log(f"Snapshot written to {out_path} ({len(m1)+len(m2)} bytes)")


def _find_eyetype_candidates(before, after):
    n = min(len(before), len(after))
    candidates = {}
    for off in range(0, n - 4, 4):
        if before[off:off + 4] == after[off:off + 4]:
            continue
        b = struct.unpack(">I", before[off:off + 4])[0]
        a = struct.unpack(">I", after[off:off + 4])[0]
        b_type = b >> 26
        a_type = a >> 26
        b_rest = b & 0x3FFFFFF
        a_rest = a & 0x3FFFFFF
        if b_rest == a_rest and 0 <= b_type <= 47 and 0 <= a_type <= 47 and b_type != a_type:
            candidates[off] = (b_type, a_type)
    return candidates


CHECK_ADDRS = [
    0x8031DA60, 0x8031DF70, 0x80326920, 0x8032A5D8, 0x8032C5DC, 0x8032C708,
    0x8035D6FC, 0x80374494, 0x80374498, 0x80374994, 0x80374998, 0x8037E1B4,
    0x8037E1B8, 0x80382068, 0x8038B164, 0x803CDE84, 0x803D00DC, 0x803D0324,
    0x803D1BA4, 0x803FC904, 0x80409624, 0x80426DF4, 0x8042D0C4, 0x80448C48,
]


DEDICATED_RFL_DB_PATH = r"C:\Users\player\Documents\Perso\Emulateur\Dolphin_Archipelago_User\Wii\shared2\menu\FaceLib\RFL_DB.dat"


def do_read_dedicated(log):
    from .mii_reader import read_miis
    miis = read_miis(DEDICATED_RFL_DB_PATH)
    log(f"{len(miis)} Miis found")
    for m in miis:
        log(f"{m}")


FIND_COMMITTED_NAME = "Jon"


def do_find_committed(log):
    import dolphin_memory_engine as dme
    from .mii_reader import read_wii_memory, find_mii_entries_by_name

    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    chunks = read_wii_memory(dme)
    log(f"Read {sum(len(d) for _, d in chunks)} bytes across {len(chunks)} region(s)")

    results = find_mii_entries_by_name(chunks, FIND_COMMITTED_NAME)
    log(f"Found {len(results)} entr(y/ies) named {FIND_COMMITTED_NAME!r}")
    for addr, mii in results:
        log(f"  @0x{addr:08X}: eye_type={mii.eye_type} full={mii}")


def do_apply_dol_patch(log):
    with open(ORIGINAL_APP_PATH, "rb") as fh:
        data = bytearray(fh.read())

    log(f"Original size: {len(data)} bytes")
    log(f"Trampoline size: {len(TRAMPOLINE_BYTES)} bytes")

    # Sanity check: the 4 bytes we're about to overwrite should currently be
    # exactly the original "b FUN_8003bda4" tail-call (48 00 00 04 -- opcode
    # 0x48, LK bit clear) so we don't ever blindly overwrite the wrong offset.
    orig4 = bytes(data[HOOK_FILE_OFFSET:HOOK_FILE_OFFSET + 4])
    log(f"Bytes at hook file offset 0x{HOOK_FILE_OFFSET:X} before patch: {orig4.hex()}")
    if orig4 != bytes.fromhex("48000004"):
        log("REFUSING: bytes at hook offset don't match the expected original 'b' instruction. Aborting.")
        return

    trampoline_file_offset = len(data)
    log(f"Appending trampoline at file offset 0x{trampoline_file_offset:X}")

    # Apply the hook (4 bytes).
    data[HOOK_FILE_OFFSET:HOOK_FILE_OFFSET + 4] = HOOK_BYTES

    # Append the trampoline code at end of file.
    data.extend(TRAMPOLINE_BYTES)
    # Pad to a 32-byte boundary (DOL section alignment convention).
    while len(data) % 32 != 0:
        data.append(0)

    # Register the new section in DOL text-slot 2 (currently unused: 0,0,0).
    struct.pack_into(">I", data, DOL_TEXT2_OFFSET_FIELD, trampoline_file_offset)
    struct.pack_into(">I", data, DOL_TEXT2_ADDR_FIELD, TRAMPOLINE_LOAD_ADDR)
    struct.pack_into(">I", data, DOL_TEXT2_SIZE_FIELD, len(TRAMPOLINE_BYTES))

    with open(PATCHED_APP_PATH, "wb") as fh:
        fh.write(data)

    log(f"Wrote patched DOL: {PATCHED_APP_PATH} ({len(data)} bytes)")

    # Verify by re-reading back.
    with open(PATCHED_APP_PATH, "rb") as fh:
        verify = fh.read()
    log(f"Verify hook bytes: {verify[HOOK_FILE_OFFSET:HOOK_FILE_OFFSET+4].hex()}")
    log(f"Verify text2 offset field: 0x{struct.unpack('>I', verify[DOL_TEXT2_OFFSET_FIELD:DOL_TEXT2_OFFSET_FIELD+4])[0]:X}")
    log(f"Verify text2 addr field: 0x{struct.unpack('>I', verify[DOL_TEXT2_ADDR_FIELD:DOL_TEXT2_ADDR_FIELD+4])[0]:X}")
    log(f"Verify text2 size field: 0x{struct.unpack('>I', verify[DOL_TEXT2_SIZE_FIELD:DOL_TEXT2_SIZE_FIELD+4])[0]:X}")
    log(f"Verify trampoline bytes at file: {verify[trampoline_file_offset:trampoline_file_offset+len(TRAMPOLINE_BYTES)].hex()}")


VERIFY_ADDRS = [
    (0x8003bda0, 4, "hook site (should be 48385260 if our patch is loaded)"),
    (0x803C1000, 0x58, "trampoline body (should start 2C040005 40820050 ...)"),
    (0x803C1040, 1, "scratch lock-bitmask byte"),
]


def do_verify_ram(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return
    for addr, size, desc in VERIFY_ADDRS:
        try:
            raw = dme.read_bytes(addr, size)
            log(f"0x{addr:08X} ({desc}): {raw.hex()}")
        except Exception as e:
            log(f"0x{addr:08X} ({desc}): READ_FAILED {e!r}")

    # Captured r6 (live Mii struct pointer) written by the diagnostic
    # trampoline's extra "stw r6, 0x803C1100" instruction, and a dereference
    # of the field it actually wrote (r6+0x28) to see the CURRENT steady-
    # state value (does our forced eye_type=47 write stick between our own
    # hook's executions, or does something else overwrite it afterward?).
    try:
        r6_raw = dme.read_bytes(0x803C1100, 4)
        r6 = struct.unpack(">I", r6_raw)[0]
        log(f"Captured r6 (live Mii struct ptr) @0x803C1100: 0x{r6:08X}")
        if r6:
            field_raw = dme.read_bytes(r6 + 0x28, 4)
            field = struct.unpack(">I", field_raw)[0]
            log(f"Current value at r6+0x28 (eye word): 0x{field:08X} (eye_type={field >> 26})")
    except Exception as e:
        log(f"Captured-r6 dereference: READ_FAILED {e!r}")

    # r6 is confirmed deterministic across Dolphin sessions for this exact
    # game+profile+Mii, so just check the known address directly (current
    # trampoline doesn't re-capture r6 to scratch, it only forces r6+4).
    try:
        r6_known = 0x906919BC
        field4_raw = dme.read_bytes(r6_known + 4, 4)
        field4 = struct.unpack(">I", field4_raw)[0]
        log(f"Direct read r6(known)+4: 0x{field4:08X} (top6={field4 >> 26})")
    except Exception as e:
        log(f"Direct r6+4 read: READ_FAILED {e!r}")

    # Captured r3 (param_1, the "editor screen context" struct pointer) via
    # the trampoline's extra "stw r3, 0x803C1104" instruction. From this we
    # can compute the eye type-grid widget-group's address (param_1 +
    # current_page*0x18 + 0x87c), read its vtable pointer (+0x14), and read
    # the concrete function address at vtable+0x1c (the "hit-test and
    # select" method) -- this is the function we actually need to decompile
    # to find where a click commits the new value.
    try:
        p1_raw = dme.read_bytes(0x803C1104, 4)
        param_1 = struct.unpack(">I", p1_raw)[0]
        log(f"Captured r3/param_1 (editor context) @0x803C1104: 0x{param_1:08X}")
        if param_1:
            page_raw = dme.read_bytes(param_1 + 0x1c70, 4)
            page = struct.unpack(">I", page_raw)[0]
            log(f"Current page (param_1+0x1c70): {page}")
            group_addr = param_1 + page * 0x18 + 0x87c
            log(f"Type-grid widget-group address: 0x{group_addr:08X}")
            vtable_raw = dme.read_bytes(group_addr + 0x14, 4)
            vtable = struct.unpack(">I", vtable_raw)[0]
            log(f"Vtable pointer (group+0x14): 0x{vtable:08X}")
            if vtable:
                func_raw = dme.read_bytes(vtable + 0x1c, 4)
                func_addr = struct.unpack(">I", func_raw)[0]
                log(f"Hit-test/select method (vtable+0x1c): 0x{func_addr:08X}  <-- decompile this")

    except Exception as e:
        log(f"Captured-r3 vtable chain: READ_FAILED {e!r}")

    # FUN_80010ac0's OWN param_1 (captured via the new hook at 0x80010ad4),
    # used to compute FUN_8003f828's target: FUN_8003f828(param_1+0x34, ...)
    # writes committed field values starting at target+4 (e.g. case 0xc =
    # eye type, doing DAT_80207e38-table bit manipulation on *(target+4)).
    # A liveness canary byte at 0x803C1304 increments every time this hook
    # fires -- read it twice with a short delay to prove the hook is really
    # running every frame (not stale/one-shot) before trusting the capture.
    try:
        canary1 = dme.read_bytes(0x803C1304, 1)[0]
        time.sleep(0.5)
        canary2 = dme.read_bytes(0x803C1304, 1)[0]
        log(f"Liveness canary @0x803C1304: {canary1} -> {canary2} (delta={((canary2 - canary1) % 256)}, should be >0 if hook fires every frame)")

        p1b_raw = dme.read_bytes(0x803C1300, 4)
        param_1b = struct.unpack(">I", p1b_raw)[0]
        log(f"Captured FUN_80010ac0 param_1 @0x803C1300: 0x{param_1b:08X}")
        if param_1b:
            target = param_1b + 0x34
            field_raw = dme.read_bytes(target + 4, 4)
            field = struct.unpack(">I", field_raw)[0]
            log(f"FUN_8003f828 target = param_1+0x34 = 0x{target:08X}")
            log(f"Value at target+4: 0x{field:08X} (top6bits={field >> 26})")

            # Wide dump around param_1b to hunt for the right field if our
            # +0x34+4 arithmetic is off -- scan for any word whose top 6
            # bits equal a recently-confirmed real eye_type pick (17 or 26)
            # to spot the correct offset empirically instead of guessing.
            window = dme.read_bytes(param_1b - 0x20, 0x100)
            for off in range(0, len(window) - 4, 4):
                val = struct.unpack(">I", window[off:off + 4])[0]
                top6 = val >> 26
                if top6 in (17, 26):
                    abs_addr = param_1b - 0x20 + off
                    log(f"  CANDIDATE @0x{abs_addr:08X} (param_1{'+' if abs_addr>=param_1b else '-'}0x{abs(abs_addr-param_1b):X}): 0x{val:08X} top6={top6}")
    except Exception as e:
        log(f"FUN_80010ac0 param_1 chain: READ_FAILED {e!r}")


def do_check_candidates(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked.")
        return
    for addr in CHECK_ADDRS:
        try:
            raw = dme.read_bytes(addr, 4)
            val = struct.unpack(">I", raw)[0]
            eye_type = val >> 26
            log(f"0x{addr:08X}: word=0x{val:08X} eye_type={eye_type}")
        except Exception as e:
            log(f"0x{addr:08X}: READ_FAILED {e!r}")


def do_eyetype_diff(log):
    with open(DUMP_A, "rb") as fh:
        before = fh.read()
    with open(DUMP_B, "rb") as fh:
        after = fh.read()
    with open(DUMP_IDLE1, "rb") as fh:
        idle1 = fh.read()
    with open(DUMP_IDLE2, "rb") as fh:
        idle2 = fh.read()

    log(f"Comparing {min(len(before), len(after))} bytes")

    real = _find_eyetype_candidates(before, after)
    n_idle = min(len(idle1), len(idle2))
    noisy = set(off for off in range(0, n_idle - 4, 4) if idle1[off:off + 4] != idle2[off:off + 4])
    log(f"Real candidates: {len(real)}, idle-noise offsets (any change): {len(noisy)}")

    filtered = {off: v for off, v in real.items() if off not in noisy}
    log(f"After removing idle noise: {len(filtered)} candidate(s)")

    for off, (b_type, a_type) in list(filtered.items())[:200]:
        if off < MEM1_SIZE:
            addr = MEM1_BASE + off
        else:
            addr = MEM2_BASE + (off - MEM1_SIZE)
        log(f"  addr=0x{addr:08X}  eye_type {b_type} -> {a_type}")


# Drop cmd.py here, read result.txt. Override with MII_PROBE_DIR.
SERVE_DIR = os.environ.get("MII_PROBE_DIR") or os.path.join(tempfile.gettempdir(), "mii_probe_serve")


def do_serve(log):
    """Stay hooked and run probe scripts dropped into SERVE_DIR.

    Each launch of this tool costs ~20s of Launcher start-up, which made
    live RE a crawl. This mode stays up instead: write cmd.py into SERVE_DIR
    (it gets `dme`, `rd32`, `rd`, `out` in its namespace), and the result
    appears as result.txt; cmd.py is deleted once it has run."""
    import os
    import traceback
    import dolphin_memory_engine as dme

    os.makedirs(SERVE_DIR, exist_ok=True)
    cmd_path = os.path.join(SERVE_DIR, "cmd.py")
    res_path = os.path.join(SERVE_DIR, "result.txt")
    log(f"serving {SERVE_DIR}")
    while True:
        time.sleep(0.1)
        if not os.path.exists(cmd_path):
            continue
        lines = []
        try:
            if not dme.is_hooked():
                dme.hook()
            src = open(cmd_path, encoding="utf-8").read()
            ns = {
                "dme": dme, "time": time, "struct": struct,
                "rd32": lambda a: struct.unpack(">I", dme.read_bytes(a, 4))[0],
                "rd": lambda a, n: dme.read_bytes(a, n),
                "out": lambda *a: lines.append(" ".join(str(x) for x in a)),
            }
            exec(compile(src, "cmd.py", "exec"), ns)
        except Exception:
            lines.append(traceback.format_exc())
        try:
            os.remove(cmd_path)
        except OSError:
            pass
        with open(res_path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(res_path + ".tmp", res_path)


def do_v9_state(log):
    """Heartbeat + restore table + eyebrow lock bytes, as deltas."""
    import dolphin_memory_engine as dme
    HEARTBEAT, VALUES = 0x803C17F0, 0x803C1500
    LOCKS = {"eyebrow_type": 0x803C1601, "eyebrow_color": 0x803C160D,
             "eyebrow_movement": 0x803C160E}
    NAMES = ["eyebrow_type", "eyebrow_rotation", "eyebrow_color",
             "eyebrow_size", "eyebrow_vert_pos", "eyebrow_horiz_spacing"]

    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked."); return

    def w(a): return struct.unpack(">I", dme.read_bytes(a, 4))[0]

    base = w(HEARTBEAT)
    time.sleep(2.0)
    now = w(HEARTBEAT)
    log(f"heartbeat delta over 2s = {now - base}  (0 = editor closed / trampoline not live)")
    tbl = dme.read_bytes(VALUES, len(NAMES))
    log("restore table: " + ", ".join(f"{n}={tbl[i]}" for i, n in enumerate(NAMES)))
    for k, a in LOCKS.items():
        log(f"lock {k} @ {a:08X} = {dme.read_bytes(a, 1)[0]}  (0 = locked)")
    ptr = w(0x803C17F4)
    log(f"edit struct ptr (published by the trampoline) = {ptr:#010x}")
    if 0x80000000 <= ptr < 0x81800000 or 0x90000000 <= ptr < 0x94000000:
        word = w(ptr + 8)
        log(f"live eyebrow word = {word:#010x}  "
            f"type={(word >> 27) & 0x1f} rot={(word >> 22) & 0xf} "
            f"color={(word >> 13) & 0x7} size={(word >> 9) & 0xf} "
            f"vert={(word >> 4) & 0x1f} spacing={word & 0xf}")
    else:
        log("pointer not plausible -- is the editor open?")


def do_entry_canary(log):
    """Does FUN_8003bda4 (the category-apply function the V7/V8 trampoline
    hooks) run outside live Mii editing?

    V8 black-screened at LAUNCH, not just in the editor, which only makes
    sense if this function also runs during boot -- where r4/r6 need not
    mean what they mean during editing. Report a DELTA over a 10s window,
    never a total: a nonzero count read once says nothing about when."""
    import dolphin_memory_engine as dme
    COUNTER, LAST_R4, LAST_R6 = 0x803C1780, 0x803C1784, 0x803C1788

    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    def rd(a):
        return struct.unpack(">I", dme.read_bytes(a, 4))[0]

    base = rd(COUNTER)
    log(f"baseline counter = {base}  (r4={rd(LAST_R4):#010x} r6={rd(LAST_R6):#010x})")
    for i in range(1, 6):
        time.sleep(2.0)
        now = rd(COUNTER)
        log(f"  +{i*2:2d}s  counter = {now}  delta = {now - base}"
            f"  r4={rd(LAST_R4):#010x} r6={rd(LAST_R6):#010x}")
    log("")
    log("delta 0 while idle in the Plaza => it only runs in the editor,")
    log("so V8's boot crash is NOT an out-of-editor register-contract problem.")


def do_wc24_canary(log):
    """Find where the game keeps the Mii that was dragged onto the envelope.

    The WC24 list screen shows the same rows whichever Mii is dragged, because
    nothing tells the mod which one it was -- but the game clearly knows: its
    confirmation dialog reads "<name> will be sent to ...". The injected row
    filler now stashes that screen's own struct pointer at 0x803C1BF0, so dump
    the struct and look for a Mii name in it (UTF-16BE, 10 chars max)."""
    import dolphin_memory_engine as dme
    STRUCT_PTR = 0x803C1F00  # moved from 0x1BF0 in BuildWC24RowsV2

    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    def plausible(addr):
        # MEM1 and MEM2 both hold game structures -- this screen's lives in
        # MEM2, which an earlier MEM1-only check wrongly rejected.
        return 0x80000000 <= addr < 0x81800000 or 0x90000000 <= addr < 0x94000000

    log("Open the Wii Friend view and drag a Mii onto the envelope, then wait.")
    ptr = 0
    for _ in range(120):
        ptr = struct.unpack(">I", dme.read_bytes(STRUCT_PTR, 4))[0]
        if plausible(ptr):
            break
        time.sleep(0.5)

    if not plausible(ptr):
        log(f"No screen struct captured (read {ptr:#x}). Was the list opened?")
        return

    log(f"Screen struct at {ptr:#010x}")
    log("")

    data = dme.read_bytes(ptr, 0x600)
    log("Readable UTF-16BE text inside the struct:")
    for off in range(0, len(data) - 4, 2):
        chunk = data[off:off + 20]
        try:
            text = chunk.decode("utf-16-be")
        except UnicodeDecodeError:
            continue
        text = text.split(chr(0))[0]
        if len(text) >= 3 and all(32 <= ord(c) < 127 for c in text):
            log(f"  +0x{off:04x}  {text!r}")

    log("")
    log("Pointer fields that look like they point at a Mii record:")
    for off in range(0, 0x600, 4):
        value = struct.unpack(">I", data[off:off + 4])[0]
        if not plausible(value):
            continue
        try:
            probe = dme.read_bytes(value + 2, 20)
            text = probe.decode("utf-16-be").split(chr(0))[0]
        except Exception:
            continue
        if len(text) >= 2 and all(32 <= ord(c) < 127 for c in text):
            log(f"  +0x{off:04x} -> {value:#010x}  name={text!r}")


def do_phase2_canaries(log):
    import time as _time
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    STATUSFORCE_CANARY = 0x803C19E0
    FUN800499CC_CANARY = 0x803C19E4
    FUN80049FF0_CANARY = 0x803C19E8
    FUN8004A428_CANARY = 0x803C19EC
    TOPDISPATCH_CANARY = 0x803C19F0
    TOPDISPATCH_PARAM1 = 0x803C19F4
    TOPDISPATCH_MODE = 0x803C19F8
    SUBSTATE_8004D174 = 0x803C19FC

    def read_all():
        sf = struct.unpack(">I", dme.read_bytes(STATUSFORCE_CANARY, 4))[0]
        fc = struct.unpack(">I", dme.read_bytes(FUN800499CC_CANARY, 4))[0]
        ff0 = struct.unpack(">I", dme.read_bytes(FUN80049FF0_CANARY, 4))[0]
        a428 = struct.unpack(">I", dme.read_bytes(FUN8004A428_CANARY, 4))[0]
        top = struct.unpack(">I", dme.read_bytes(TOPDISPATCH_CANARY, 4))[0]
        p1 = struct.unpack(">I", dme.read_bytes(TOPDISPATCH_PARAM1, 4))[0]
        mode = struct.unpack(">i", dme.read_bytes(TOPDISPATCH_MODE, 4))[0]
        sub = struct.unpack(">I", dme.read_bytes(SUBSTATE_8004D174, 4))[0]
        return sf, fc, ff0, a428, top, p1, mode, sub

    sf1, fc1, ff0_1, a428_1, top1, p1_1, mode1, sub1 = read_all()
    log(f"t=0.0s  FUN_800499cc={fc1}  status-force={sf1}  FUN_80049ff0={ff0_1}  "
        f"FUN_8004a428={a428_1}  top-dispatch calls={top1}  param_1=0x{p1_1:08X}  "
        f"mode(+0x8c)={mode1}  substate(+0x90)={sub1}")
    _time.sleep(1.0)
    sf2, fc2, ff0_2, a428_2, top2, p1_2, mode2, sub2 = read_all()
    log(f"t=1.0s  FUN_800499cc={fc2}  status-force={sf2}  FUN_80049ff0={ff0_2}  "
        f"FUN_8004a428={a428_2}  top-dispatch calls={top2}  param_1=0x{p1_2:08X}  "
        f"mode(+0x8c)={mode2}  substate(+0x90)={sub2}")
    log(f"delta: FUN_800499cc +{fc2-fc1}  status-force +{sf2-sf1}  "
        f"FUN_80049ff0 +{ff0_2-ff0_1}  FUN_8004a428 +{a428_2-a428_1}  top-dispatch +{top2-top1}")
    sub_names = {0: "init", 1: "FUN_8004d458", 2: "FUN_8004d598", 3: "dialog-check",
                 4: "FUN_8004dbd4", 5: "FUN_8004dd7c", 6: "FUN_8004de9c",
                 7: "teardown-a", 8: "teardown-b"}
    log(f"case 9 substate {sub2} = {sub_names.get(sub2, '?')}")

    if ff0_2 != ff0_1 or a428_2 != a428_1:
        log("NEW CANDIDATES ARE FIRING -- FUN_80049ff0 and/or FUN_8004a428 "
            "(reached via FUN_8004924c's state 0xc/0xd, calling "
            "FUN_80056258/FUN_8005636c) are genuinely entered when clicking "
            "Wii Friend. This is very likely the real WC24 chain -- safe to "
            "build the data-redirect hooks on top of these instead of "
            "FUN_80055d74.")
    elif top2 == top1:
        log("The TOP-level Plaza dispatcher (FUN_80042b54) itself never "
            "fired either -- either we're not even on the Plaza screen (is "
            "the game actually sitting on the Wii Friend error dialog when "
            "this probe ran?), or this isn't the right screen-update "
            "function at all.")
    else:
        log(f"Top dispatcher IS running (mode(+0x8c)={mode2}) but never puts "
            f"the screen into mode 7 (FUN_8004924c) -- go straight to case "
            f"{mode2}'s handler in FUN_80042b54's switch instead of guessing "
            f"further.")


def do_dialog_capture(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    ADDRS = {
        "canary": 0x803C1D40,
        "LR": 0x803C1D44,
        "r3(ctx)": 0x803C1D48,
        "r4(flag)": 0x803C1D4C,
        "r5(str1)": 0x803C1D50,
        "r6(str2)": 0x803C1D54,
        "r7(str3)": 0x803C1D58,
        "r8(str4)": 0x803C1D5C,
    }
    vals = {}
    for name, addr in ADDRS.items():
        vals[name] = struct.unpack(">I", dme.read_bytes(addr, 4))[0]
        log(f"{name} @0x{addr:08X} = 0x{vals[name]:08X}")

    if vals["canary"] == 0:
        log("Canary is 0 -- FUN_8002f154 (the generic show-dialog function) "
            "has never been called at all since Dolphin booted. Either the "
            "error dialog uses a different display function, or the hook "
            "isn't active (did Dolphin get fully restarted after this ini "
            "change?).")
    else:
        log(f"FUN_8002f154 has been called {vals['canary']} time(s) total. "
            f"The LAST call's return address (LR) is 0x{vals['LR']:08X} -- "
            f"that address (minus the containing function's start) tells us "
            f"exactly which function raised the most recent dialog. If that "
            f"was the Wii Friend network error, this is the function to "
            f"decompile next.")


def do_facegen_canaries(log):
    import time as _time
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    CANARY_800601E8 = 0x803C1FE0
    CANARY_80060518 = 0x803C1FE4

    def read_both():
        a = struct.unpack(">I", dme.read_bytes(CANARY_800601E8, 4))[0]
        b = struct.unpack(">I", dme.read_bytes(CANARY_80060518, 4))[0]
        return a, b

    a1, b1 = read_both()
    log(f"t=0.0s  FUN_800601e8={a1}  FUN_80060518={b1}")
    _time.sleep(1.0)
    a2, b2 = read_both()
    log(f"t=1.0s  FUN_800601e8={a2}  FUN_80060518={b2}")
    log(f"delta: FUN_800601e8 +{a2-a1}  FUN_80060518 +{b2-b1}")
    if a2 != a1 or b2 != b1:
        log("At least one fires -- this IS the real 'choose a face' screen "
            "logic. Safe to build a data-redirect hook on whichever one is "
            "advancing.")
    elif a1 == 0 and b1 == 0:
        log("Neither has ever fired (both still 0) -- either the probe "
            "wasn't run while actually on the 'choose a face' screen, or "
            "these aren't the right functions either.")
    else:
        log("Both have fired at least once before but aren't advancing "
            "right now -- may just mean the screen isn't actively "
            "re-rendering (e.g. sitting idle after initial draw). Check "
            "whether the nonzero counts make sense (e.g. count near 43 if "
            "FUN_80060518 runs once per grid slot).")


def do_wizard_capture(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    CANARY = 0x803C1F00
    LR = 0x803C1F04
    R3 = 0x803C1F08

    canary = struct.unpack(">I", dme.read_bytes(CANARY, 4))[0]
    lr = struct.unpack(">I", dme.read_bytes(LR, 4))[0]
    r3 = struct.unpack(">I", dme.read_bytes(R3, 4))[0]
    log(f"canary={canary}  LR=0x{lr:08X}  param_1(r3)=0x{r3:08X}")
    if canary == 0:
        log("FUN_80031978 has never been called -- did the user actually "
            "navigate through Create a Mii -> ... -> from an existing "
            "template while the probe was checked? Or this isn't the "
            "'from template' path after all.")
    else:
        log(f"Called {canary} time(s). LR=0x{lr:08X} is the exact call "
            f"site -- decompile whatever function contains this address "
            f"next to find the real entry-point trigger.")


def do_entry_param_capture(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    CANARY = 0x803C1F60
    R3 = 0x803C1F64

    canary = struct.unpack(">I", dme.read_bytes(CANARY, 4))[0]
    r3 = struct.unpack(">I", dme.read_bytes(R3, 4))[0]
    log(f"canary={canary}  FUN_80017720 param_1(r3)=0x{r3:08X}")
    if canary == 0:
        log("Never called -- navigate to 'Choose a face to start with' "
            "first, then re-run the probe.")
    else:
        log(f"Called {canary} time(s). param_1=0x{r3:08X} is exactly what "
            f"we need to pass when calling FUN_80017720 ourselves from the "
            f"Wii Friend hook.")


def do_freeze_diag(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    labels = {
        0: "CP0 (FUN_8004e314 entered at all)",
        1: "CP1 (one-shot flag was clear, doing real work)",
        2: "CP2 (r3/param_1 computed, about to call FUN_80017720)",
        3: "CP3 (FUN_80017720 returned successfully)",
        4: "CP4 (FUN_8002fd48 returned non-NULL)",
    }
    for i in (0, 1, 4, 2, 3):
        addr = 0x803C1EA0 + i * 4
        val = struct.unpack(">I", dme.read_bytes(addr, 4))[0]
        log(f"{labels[i]}: {val}")


def do_deep_freeze_diag(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    gate_labels = {
        0: "GATE-CP0 (FUN_8004e314 entered at all)",
        1: "GATE-CP1 (one-shot flag was clear, doing real work)",
        4: "GATE-CP4 (FUN_8002fd48 returned non-NULL)",
        2: "GATE-CP2 (r3/param_1 computed, about to call the copy)",
        3: "GATE-CP3 (copy returned successfully)",
    }
    for i in (0, 1, 4, 2, 3):
        addr = 0x803C1EA0 + i * 4
        val = struct.unpack(">I", dme.read_bytes(addr, 4))[0]
        log(f"{gate_labels[i]}: {val}")
    log("")

    # 2026-08-29: stripped the 17-checkpoint instrumentation down to a lean
    # passthrough (CP0-12 confirmed reliable across many prior tests, no
    # longer worth the Gecko-code budget) -- back to the original
    # "stwu r1,-0x20(r1)" prologue, and just ONE checkpoint kept (right
    # after the redirect to the loop-diag copy).
    entry_bytes = dme.read_bytes(0x803C2400, 4)
    entry_word = struct.unpack(">I", entry_bytes)[0]
    if entry_word != 0x9421FFE0:
        log(f"WARNING: bytes at 0x803C2400 = 0x{entry_word:08X}, expected "
            f"0x9421FFE0 (stwu r1,-0x20(r1)) -- the 'Phase 3b' Gecko block "
            f"was NOT loaded (code-count limit again, or ini not reloaded). "
            f"Fix that before trusting the checkpoint below.")
    else:
        log("Entry bytes at 0x803C2400 confirmed correct -- copy is loaded.")

    captured_r3 = struct.unpack(">I", dme.read_bytes(0x803C205C, 4))[0]
    captured_r0 = struct.unpack(">I", dme.read_bytes(0x803C2060, 4))[0]
    log(f"Captured r3 (destination address for 'sth r0,0x0(r3)'): 0x{captured_r3:08X}")
    log(f"Captured r0 (value about to be written): 0x{captured_r0:08X}")
    try:
        target_readback = dme.read_bytes(captured_r3, 4)
        val = struct.unpack(">I", target_readback)[0]
        log(f"Read-back at that address (via dme, BEFORE the real store executes): 0x{val:08X}")
    except Exception as e:
        log(f"Read-back at 0x{captured_r3:08X} FAILED: {e!r} -- address is genuinely unmapped, "
            f"confirms the store would fault.")

    bisect7_relay_entry = struct.unpack(">I", dme.read_bytes(0x803C2180, 4))[0]
    bisect7_hook_bytes = struct.unpack(">I", dme.read_bytes(0x80033e10, 4))[0]
    log(f"BISECT7 relay entry bytes @0x803C2180: 0x{bisect7_relay_entry:08X} (expected 0x3D00803C)")
    log(f"BISECT7 hook-site bytes @0x80033e10: 0x{bisect7_hook_bytes:08X} (expected 0x4838E371)")
    bisect7_cp = struct.unpack(">I", dme.read_bytes(0x803C2058, 4))[0]
    log(f"BISECT7 (the exact suspect instruction, 0x80033e10 'lhz r0,0x5a(r1)'): {bisect7_cp}")
    if bisect7_cp == 0:
        log("Never fires (or stays at background baseline) -- confirms the hang is genuinely "
            "AT or immediately triggered by this exact instruction (a plain stack read).")
    else:
        log("Fires above baseline -- this instruction is NOT the culprit after all; "
            "the hang must be in returning from this relay back to 0x80033e14.")

    bisect5_cp = struct.unpack(">I", dme.read_bytes(0x803C2050, 4))[0]
    log(f"BISECT5 (between e00&e1c, at the real 0x80033e0c 'sth' relocated into a relay): {bisect5_cp}")

    bisect4_cp = struct.unpack(">I", dme.read_bytes(0x803C204C, 4))[0]
    log(f"BISECT4 (between e00&e3c, at the real 0x80033e1c 'stw' relocated into a relay): {bisect4_cp}")

    bisect3_cp = struct.unpack(">I", dme.read_bytes(0x803C2048, 4))[0]
    log(f"BISECT3 (between 2&2, at the real 0x80033e00 'sth' relocated into a relay): {bisect3_cp}")

    bisect2_cp = struct.unpack(">I", dme.read_bytes(0x803C2044, 4))[0]
    log(f"BISECT2 (earlier point, at the real 0x80033db0 'lhz' relocated into a relay): {bisect2_cp}")

    bisect_cp = struct.unpack(">I", dme.read_bytes(0x803C2040, 4))[0]
    log(f"BISECT (mid-FUN_80033d04, at the real 0x80033e3c 'sth' relocated into a relay): {bisect_cp}")
    if bisect_cp == 0:
        log("Never fires -- the hang is in the FIRST half of FUN_80033d04's "
            "actually-executed path (prologue through ~0x80033e3c).")
    else:
        log("Fires -- the hang is in the SECOND half (~0x80033e3c through the "
            "tail call at 0x80034194).")

    trampoline_cp = struct.unpack(">I", dme.read_bytes(0x803C1F60, 4))[0]
    log(f"TRAMPOLINE (checkpoint right before tail-calling the real, unmodified FUN_80033d04): {trampoline_cp}")
    if trampoline_cp == 0:
        log("Never fires -- the loop-diag copy's 'bl 0x80033d04' (now redirected "
            "through the trampoline) is never reached at all. The hang would "
            "have to be in the loop-diag copy's OWN prologue/capture code, "
            "which seemed to run fine (we read live r13/heap values from it) -- "
            "worth re-checking that assumption.")
    else:
        log("Fires -- confirms execution DOES reach this exact point and DOES "
            "tail-call into the real FUN_80033d04. Combined with everything "
            "else, this proves the hang is genuinely inside the real, "
            "unmodified FUN_80033d04 -- despite full disassembly showing no "
            "calls (besides the already-retargeted one), no unbounded loops, "
            "no logged CPU exceptions, and all destination memory readable.")

    caller_patch = struct.unpack(">I", dme.read_bytes(0x80034194, 4))[0]
    log(f"Bytes at 0x80034194 (the retarget inside real FUN_80033d04): 0x{caller_patch:08X} "
        f"(expected 0x4838E96D if our retarget is live)")
    if caller_patch != 0x4838E96D:
        log("MISMATCH -- the retarget patch inside the real, shared FUN_80033d04 "
            "is NOT the bytes we deployed. This alone would explain why F5AC-A "
            "never increments for our call: FUN_80033d04 is still calling the "
            "REAL FUN_8013f5ac, not our instrumented copy.")

    cp13 = struct.unpack(">I", dme.read_bytes(0x803C1EC0, 4))[0]
    log(f"CP13-equivalent (after bl 0x803c2900, the loop-diag redirect): {cp13}")
    if cp13 == 0:
        log("Still doesn't fire -- consistent with every prior test, hang "
            "confirmed downstream inside the loop-diag/f5ac/f4ec chain.")
    else:
        log("This fired for the first time -- something changed! The "
            "downstream fix chain may have actually resolved the hang; "
            "re-check GATE-CP3 and whether the screen is now visible.")

    # If CP13 is the wall (bl 0x8005e170, now redirected to an instrumented
    # copy at 0x803c2900 with 3 monotonic loop-iteration counters), these
    # tell us exactly how many completed before the hang: loop1 max 9,
    # loop2 max 0x2b=43, tail max 1.
    log("")
    captured_r13 = struct.unpack(">I", dme.read_bytes(0x803C1F10, 4))[0]
    heap_ptr_a = struct.unpack(">I", dme.read_bytes(0x803C1F14, 4))[0]  # *(r13-0x6cc8), the "current heap" FUN_8014af24 calls vtable+0x14 on
    heap_ptr_b = struct.unpack(">I", dme.read_bytes(0x803C1F18, 4))[0]  # *(r13-0x6cc0), a guard-check heap pointer
    log(f"Captured r13 = 0x{captured_r13:08X}")
    log(f"Captured *(r13-0x6cc8) [current heap, FUN_8014af24 vtable target] = 0x{heap_ptr_a:08X}")
    log(f"Captured *(r13-0x6cc0) [guard-check heap] = 0x{heap_ptr_b:08X}")
    if heap_ptr_a == 0:
        log("Current heap pointer is NULL -- FUN_8014af24 should hit its "
            "graceful 'cannot allocate from heap' error-log path and return "
            "0, NOT hang. If it's hanging anyway despite this being NULL, "
            "the hang is elsewhere (not the heap pointer).")
    else:
        log("Current heap pointer is NON-NULL -- FUN_8014af24 will call "
            "(*(*heap_ptr_a+0x14))(heap_ptr_a,...). If this address isn't a "
            "real, valid EGG::Heap object (e.g. stale/garbage from a "
            "different context), dereferencing its vtable and calling "
            "through it would hang exactly like this.")
        # Pure memory PEEKS via dme -- safe even if heap_ptr_a is garbage,
        # unlike letting the injected PPC code dereference it (which is
        # exactly what's hanging). Follow the same chain FUN_8014af24 does:
        # vtable = *heap_ptr_a; method = *(vtable+0x14).
        try:
            vtable_raw = dme.read_bytes(heap_ptr_a, 4)
            vtable = struct.unpack(">I", vtable_raw)[0]
            log(f"*(heap_ptr_a) [vtable pointer] = 0x{vtable:08X}")
            if vtable:
                method_raw = dme.read_bytes(vtable + 0x14, 4)
                method = struct.unpack(">I", method_raw)[0]
                log(f"*(vtable+0x14) [the method FUN_8014af24 would call] = 0x{method:08X}")
                if 0x80000000 <= method < 0x81800000:
                    log("Method address falls within the normal code region "
                        "(0x80000000-0x81800000) -- looks like a PLAUSIBLE "
                        "function pointer, not obvious garbage. The heap "
                        "object chain may be structurally valid; the hang "
                        "could be genuinely INSIDE that allocator method "
                        "(e.g. it blocks/spins for a reason specific to this "
                        "context) rather than a bad pointer dereference.")
                else:
                    log("Method address is OUTSIDE the normal code region -- "
                        "this is NOT a valid function pointer. Calling "
                        "through it would jump into garbage and hang exactly "
                        "as observed. heap_ptr_a is a stale/wrong pointer.")
            else:
                log("Vtable pointer itself is NULL/zero -- not a valid "
                    "object. Calling through *(vtable+0x14) would read from "
                    "address 0x14 and hang/fault exactly as observed.")
        except Exception as e:
            log(f"Vtable chain read failed: {e!r} -- heap_ptr_a is very "
                f"likely pointing at unmapped memory (consistent with a "
                f"stale/garbage pointer).")
    log("")
    fine_after_struct_init = struct.unpack(">I", dme.read_bytes(0x803C1F20, 4))[0]
    fine_after_small_alloc = struct.unpack(">I", dme.read_bytes(0x803C1F24, 4))[0]
    log(f"FINE-1 (after FUN_80033d04 struct-init, before small 0x2c-byte alloc): {fine_after_struct_init}")
    log(f"FINE-2 (after the small 0x2c-byte alloc via FUN_8014b330, before the big 88000-byte alloc via FUN_800214c4): {fine_after_small_alloc}")
    if fine_after_struct_init == 0:
        log("Hang is in FUN_80033d04 itself (struct init / FUN_8013f5ac), before any allocation happens.")
    elif fine_after_small_alloc == 0:
        log("FUN_80033d04 completed. Hang is in the SMALL (0x2c-byte) allocation via FUN_8014b330 -- "
            "surprising, since this exact call succeeds elsewhere in this same investigation "
            "(e.g. inside FUN_800317fc, which we know completes since CP7 fires).")
    else:
        log("Both FUN_80033d04 and the small allocation completed successfully. The hang is "
            "specifically in FUN_800214c4's BIG (88000-byte) allocation -- consistent with a "
            "heap that's valid but too small/fragmented/wrong for a request this size.")
    log("")
    entry_f4ec = struct.unpack(">I", dme.read_bytes(0x803C2D00, 4))[0]
    if entry_f4ec != 0x3D00803C:
        log(f"WARNING: bytes at 0x803C2D00 = 0x{entry_f4ec:08X}, expected 0x3D00803C -- "
            f"the 'Phase 3e' Gecko block (436 total codes, getting close to the known "
            f"464-code drop threshold) was NOT loaded. Don't trust F4EC-* results below.")
    else:
        log("Entry bytes at 0x803C2D00 confirmed correct -- Phase 3e copy is loaded.")
    f5ac_entry = struct.unpack(">I", dme.read_bytes(0x803C1F50, 4))[0]  # literally first instruction of our FUN_8013f5ac copy
    log(f"F5AC-ENTRY (our FUN_8013f5ac copy entered at all): {f5ac_entry}")
    f5ac_a = struct.unpack(">I", dme.read_bytes(0x803C1F30, 4))[0]  # after bl 0x8013f4ec
    f5ac_b = struct.unpack(">I", dme.read_bytes(0x803C1F34, 4))[0]  # after bl 0x80192378 (else-branch only)
    f5ac_c = struct.unpack(">I", dme.read_bytes(0x803C1F38, 4))[0]  # after bl 0x801528b8 (else-branch only)
    log(f"F5AC-A (after bl 0x8013f4ec, inside FUN_8013f5ac): {f5ac_a}")
    log(f"F5AC-B (after bl 0x80192378, else-branch only): {f5ac_b}")
    log(f"F5AC-C (after bl 0x801528b8, else-branch only): {f5ac_c}")
    if f5ac_a == 0:
        log("Hang is inside FUN_8013f4ec itself (or its own call to FUN_80137afc).")
    elif f5ac_b == 0:
        log("FUN_8013f4ec returned. Either the safe if-branch was taken (no more calls, "
            "shouldn't be able to hang -- if we're still stuck, re-check this reasoning) "
            "or the else-branch was taken and FUN_80192378 (the apparently-empty stub) "
            "itself hangs -- surprising for a function Ghidra shows as just 'return;', "
            "but its real bytes may differ from that shallow decompile.")
    elif f5ac_c == 0:
        log("FUN_80192378 returned. Hang is inside FUN_801528b8 (the 64-bit division "
            "helper) -- surprising since its loop is bounded to ~64 iterations, would "
            "need to be a genuinely different bug (e.g. an actual crash/exception "
            "misread as a hang, or FUN_80192378 corrupted a register FUN_801528b8 "
            "depends on).")
    else:
        log("FUN_8013f5ac runs to completion. The hang must be AFTER this call, back "
            "in FUN_80033d04's own remaining code, or this diag's redirect itself "
            "isn't taking effect -- re-check the caller patch at 0x80034194.")
    log("")

    f4ec_entry = struct.unpack(">I", dme.read_bytes(0x803C1F40, 4))[0]  # literally first instruction of our FUN_8013f4ec copy
    f4ec_after = struct.unpack(">I", dme.read_bytes(0x803C1F44, 4))[0]  # after bl 0x80137afc returns
    captured_singleton_ptr = struct.unpack(">I", dme.read_bytes(0x803C1F48, 4))[0]  # r3 right after FUN_80137afc returns
    log(f"F4EC-ENTRY (our FUN_8013f4ec copy entered at all): {f4ec_entry}")
    log(f"F4EC-AFTER (after bl 0x80137afc returns): {f4ec_after}")
    log(f"Captured pointer from FUN_80137afc() [singleton+0x1f14, or 0 if singleton NULL]: 0x{captured_singleton_ptr:08X}")
    if f4ec_entry == 0:
        log("Our FUN_8013f4ec copy was never entered at all -- the retarget at "
            "0x803c2b2c (inside our own FUN_8013f5ac copy) isn't taking effect, "
            "or F5AC-A already told us we never reach that bl in the first place.")
    elif f4ec_after == 0:
        log("FUN_8013f4ec copy entered, but FUN_80137afc() itself never returns -- "
            "surprising since it's a trivial 4-instruction NULL-check-and-return "
            "with no calls or loops. If confirmed, something environmental (not "
            "the function's own logic) is at fault -- worth re-verifying the "
            "raw bytes at 0x80137afc are genuinely what we decompiled.")
    else:
        log(f"FUN_80137afc() returned successfully with 0x{captured_singleton_ptr:08X}. "
            f"If that's non-zero, the hang is in the subsequent lbz byte-reads from "
            f"that address (0x0/0x1/0x2 offsets) -- meaning the address itself is "
            f"invalid/unmapped despite coming from a structurally-plausible-looking "
            f"chain. If it's zero, FUN_8013f4ec takes the safe early-return path and "
            f"genuinely cannot hang -- the real problem would have to be elsewhere "
            f"entirely, meaning this whole line of investigation was a dead end.")
    log("")
    counter_a = struct.unpack(">I", dme.read_bytes(0x803C1F04, 4))[0]
    counter_b = struct.unpack(">I", dme.read_bytes(0x803C1F08, 4))[0]
    counter_c = struct.unpack(">I", dme.read_bytes(0x803C1F0C, 4))[0]
    log(f"LOOP-A (FUN_8005e170 loop1, bl 0x800214c4, max 9 iterations): {counter_a}")
    log(f"LOOP-B (FUN_8005e170 loop2, bl 0x800214c4, max 43 iterations): {counter_b}")
    log(f"LOOP-C (FUN_8005e170 tail, bl 0x800214c4, max 1): {counter_c}")
    if counter_a < 9:
        log(f"Hang is in loop1, iteration {counter_a + 1} of 9 (the FUN_800214c4 "
            f"call itself, or the FUN_8014b330/FUN_80033d04 calls just before it).")
    elif counter_b < 43:
        log(f"Loop1 completed all 9 iterations. Hang is in loop2, iteration "
            f"{counter_b + 1} of 43.")
    elif counter_c < 1:
        log("Loop1 and loop2 both completed fully (9 and 43). Hang is in the "
            "single tail call to FUN_800214c4.")
    else:
        log("All loop iterations AND the tail call completed -- FUN_8005e170 "
            "itself runs to completion. If CP13 (outer copy) still doesn't "
            "fire, the hang is between FUN_8005e170's return and CP13's "
            "checkpoint code, or this loop-diag copy's own epilogue.")

    # New hypothesis: FUN_80033d04's own body (pure loads/stores, no calls,
    # no unbounded loops) is what's stuck -- F5AC-ENTRY==F5AC-A/B/C proves
    # our redirected FUN_8013f5ac copy is NEVER even reached by our call,
    # only by unrelated background ones. If FUN_80033d04's straight-line
    # code can't loop or call anything hang-prone, the only remaining
    # explanation is a WRITE fault: param_1 (= r6, the live Mii-edit
    # struct) might be allocated far smaller than the ~0x33b0+ bytes
    # FUN_8005e170 writes into. Read a window of real memory around the
    # known r6 address to check for signs of an undersized buffer (e.g. a
    # dolphin_memory_engine read failure, or an abrupt transition to
    # clearly-unrelated data) around the +0x260 offset where the first
    # write inside FUN_80033d04 happens.
    log("")
    r6_known = 0x906919BC
    for off in (0x0, 0xbc, 0x260, 0x2ad, 0x2b0, 0x33b0, 0x33e0):
        addr = r6_known + off
        try:
            val = struct.unpack(">I", dme.read_bytes(addr, 4))[0]
            log(f"r6+0x{off:X} (0x{addr:08X}): 0x{val:08X}")
        except Exception as e:
            log(f"r6+0x{off:X} (0x{addr:08X}): READ_FAILED {e!r} -- "
                f"unmapped/invalid memory at this offset, supports the "
                f"undersized-buffer hypothesis.")


def do_find_mii_id_in_ram(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    from .mii_reader import read_wii_memory

    needle_id = bytes.fromhex("89b6bc64c2c6e6ab")  # Base's real on-disk Mii ID
    needle_name = "Base".encode("utf-16-be")
    needle_magic = bytes.fromhex("524e4344")  # "RNCD" (channel-struct magic, per FUN_80136c20)

    chunks = read_wii_memory(dme)
    log(f"Read {sum(len(d) for _, d in chunks)} bytes across {len(chunks)} region(s)")

    for label, needle in (("Mii-ID bytes", needle_id), ("'Base' name (UTF16BE)", needle_name), ("'RNCD' magic", needle_magic)):
        hits = []
        for base, data in chunks:
            start = 0
            while True:
                idx = data.find(needle, start)
                if idx == -1:
                    break
                hits.append(base + idx)
                start = idx + 1
        log(f"{label}: {len(hits)} hit(s): {[hex(h) for h in hits[:30]]}")
        for addr in hits[:10]:
            for base, data in chunks:
                if base <= addr < base + len(data):
                    off = addr - base
                    window_start = max(0, off - 0x10)
                    window = data[window_start:off + 0x30]
                    log(f"  @0x{addr:08X} window[-0x10,+0x30): {window.hex()}")
                    break


def do_live_id_corrupt_test(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    ID_ADDR = 0x901814BC  # confirmed: entry 0's Mii-ID field in the raw in-RAM file-image copy
    before = dme.read_bytes(ID_ADDR, 8)
    log(f"ID before: {before.hex()}")
    new_id = bytes.fromhex("2d12cc74177873f4")  # same synthesized garbage ID used in the earlier file-based test
    dme.write_bytes(ID_ADDR, new_id)
    after = dme.read_bytes(ID_ADDR, 8)
    log(f"ID after write: {after.hex()}")
    log("Now back out of Wii Friend and back in (no Dolphin restart) and check if 'Base' disappeared.")


def do_find_ramtest_in_ram(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    from .mii_reader import read_wii_memory

    needle_id = bytes.fromhex("2d12cc74177873f4")  # the bad/synthesized ID we wrote to slot 0
    needle_name = "RamTest".encode("utf-16-be")

    chunks = read_wii_memory(dme)
    log(f"Read {sum(len(d) for _, d in chunks)} bytes across {len(chunks)} region(s)")

    for label, needle in (("bad-ID bytes", needle_id), ("'RamTest' name (UTF16BE)", needle_name)):
        hits = []
        for base, data in chunks:
            start = 0
            while True:
                idx = data.find(needle, start)
                if idx == -1:
                    break
                hits.append(base + idx)
                start = idx + 1
        log(f"{label}: {len(hits)} hit(s): {[hex(h) for h in hits[:30]]}")
        for addr in hits[:10]:
            for base, data in chunks:
                if base <= addr < base + len(data):
                    off = addr - base
                    window_start = max(0, off - 0x10)
                    window = data[window_start:off + 0x30]
                    log(f"  @0x{addr:08X} window[-0x10,+0x30): {window.hex()}")
                    break


def do_find_rnod_in_ram(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    from .mii_reader import read_wii_memory

    needle_magic = bytes.fromhex("524e4f44")  # "RNOD" (the FILE's own header magic)

    chunks = read_wii_memory(dme)
    log(f"Read {sum(len(d) for _, d in chunks)} bytes across {len(chunks)} region(s)")

    hits = []
    for base, data in chunks:
        start = 0
        while True:
            idx = data.find(needle_magic, start)
            if idx == -1:
                break
            hits.append(base + idx)
            start = idx + 1
    log(f"'RNOD' magic: {len(hits)} hit(s): {[hex(h) for h in hits[:30]]}")
    for addr in hits[:10]:
        for base, data in chunks:
            if base <= addr < base + len(data):
                off = addr - base
                # dump the first two "entries" worth of bytes after the magic
                window = data[off:off + 4 + 2 * 0x4A]
                log(f"  @0x{addr:08X}: {window.hex()}")
                break


def do_read_loader_canaries(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    labels = [
        "FUN_80009e78", "FUN_8000ccb8", "FUN_8000de08", "FUN_800123e8",
        "FUN_80018ddc", "FUN_8001adc4", "FUN_8006457c", "FUN_800afec8",
        "FUN_80179e68", "FUN_80179ea8", "FUN_80196f98", "FUN_801a2654",
        "FUN_801ae37c_a", "FUN_801ae6fc", "FUN_801ea320", "FUN_801ea680",
        "FUN_801eba30",
    ]
    base = 0x803C1A80
    any_fired = False
    for i, label in enumerate(labels):
        addr = base + i * 4
        val = struct.unpack(">I", dme.read_bytes(addr, 4))[0]
        fired = " <-- FIRED" if val != 0 else ""
        if val != 0:
            any_fired = True
        log(f"canary[{i}] {label} @0x{addr:08X}: {val}{fired}")
    if not any_fired:
        log("None of the 17 candidates fired -- the real loader is none of these; need a different lead.")
    else:
        log("At least one candidate fired -- decompile that one next, it's very likely (part of) the real loader.")


def do_read_bcsetter_capture(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    canary = struct.unpack(">I", dme.read_bytes(0x803C1D80, 4))[0]
    r3 = struct.unpack(">I", dme.read_bytes(0x803C1D84, 4))[0]
    r4 = struct.unpack(">I", dme.read_bytes(0x803C1D88, 4))[0]
    lr = struct.unpack(">I", dme.read_bytes(0x803C1D8C, 4))[0]
    log(f"FUN_80030afc canary: {canary}  param_1(r3)=0x{r3:08X}  param_2(r4)=0x{r4:08X}  LR(caller return addr)=0x{lr:08X}")
    if canary == 0:
        log("Never called -- create a brand new Mii from scratch via the normal in-game editor, then re-run this probe.")
        return
    log("Called! Dumping a window around param_1 and param_2 for context...")
    for label, addr in (("param_1", r3), ("param_2", r4)):
        if addr == 0:
            continue
        try:
            window = dme.read_bytes(addr, 0x40)
            log(f"  {label}=0x{addr:08X} first 0x40 bytes: {window.hex()}")
        except Exception as e:
            log(f"  {label}=0x{addr:08X} READ_FAILED {e!r}")


def do_read_11100_capture(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    canary = struct.unpack(">I", dme.read_bytes(0x803C1E00, 4))[0]
    r3 = struct.unpack(">I", dme.read_bytes(0x803C1E04, 4))[0]
    lr = struct.unpack(">I", dme.read_bytes(0x803C1E08, 4))[0]
    log(f"FUN_80011100 canary: {canary}  param_1(r3)=0x{r3:08X}  LR(caller return addr)=0x{lr:08X}")
    if canary == 0:
        log("Never called -- create a brand new Mii from scratch via the normal in-game editor, then re-run this probe.")
        return
    try:
        window = dme.read_bytes(r3, 0x40)
        log(f"  param_1 first 0x40 bytes: {window.hex()}")
    except Exception as e:
        log(f"  param_1 READ_FAILED {e!r}")


def do_read_f880_capture(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    canary = struct.unpack(">I", dme.read_bytes(0x803C1F00, 4))[0]
    r3 = struct.unpack(">I", dme.read_bytes(0x803C1F04, 4))[0]
    lr = struct.unpack(">I", dme.read_bytes(0x803C1F08, 4))[0]
    log(f"FUN_8000f880 canary: {canary}  param_1(r3)=0x{r3:08X}  LR(caller return addr)=0x{lr:08X}")
    if canary == 0:
        log("Never called -- create a brand new Mii from scratch via the normal in-game editor, then re-run this probe.")
        return
    try:
        window = dme.read_bytes(r3, 0x40)
        log(f"  param_1 first 0x40 bytes: {window.hex()}")
    except Exception as e:
        log(f"  param_1 READ_FAILED {e!r}")


def do_read_scenecreate_capture(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    canary = struct.unpack(">I", dme.read_bytes(0x803C1F60, 4))[0]
    r3 = struct.unpack(">I", dme.read_bytes(0x803C1F64, 4))[0]
    r4 = struct.unpack(">I", dme.read_bytes(0x803C1F68, 4))[0]
    r5 = struct.unpack(">I", dme.read_bytes(0x803C1F6C, 4))[0]
    lr = struct.unpack(">I", dme.read_bytes(0x803C1F70, 4))[0]
    log(f"FUN_8014c7b0 canary: {canary}  param_1(r3)=0x{r3:08X}  param_2/sceneId(r4)={r4}  param_3(r5)=0x{r5:08X}  LR=0x{lr:08X}")
    if canary == 0:
        log("Never called yet.")
        return
    log("This shows the MOST RECENT call only -- if multiple scene transitions happened (e.g. leaving Plaza -> Mii creation -> back to Plaza), this may be the LAST one, not necessarily the Mii-creation one. Check timing carefully.")


def do_trace_creation(log):
    import time as _time
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    SITES = {
        "SceneCreate(FUN_8014c7b0)": (0x803C1F60, [
            ("sceneManager", 0x803C1F64), ("sceneId", 0x803C1F68), ("ctx", 0x803C1F6C), ("LR", 0x803C1F70)
        ]),
        "FUN_80011100": (0x803C1E00, [
            ("param_1", 0x803C1E04), ("LR", 0x803C1E08)
        ]),
        "FUN_80030afc(bc-setter)": (0x803C1D80, [
            ("param_1", 0x803C1D84), ("param_2", 0x803C1D88), ("LR", 0x803C1D8C)
        ]),
    }

    def snapshot():
        vals = {}
        for name, (canary_addr, fields) in SITES.items():
            canary = struct.unpack(">I", dme.read_bytes(canary_addr, 4))[0]
            fvals = {fname: struct.unpack(">I", dme.read_bytes(faddr, 4))[0] for fname, faddr in fields}
            vals[name] = (canary, fvals)
        return vals

    last = snapshot()
    log(f"t=0.0s baseline: " + " | ".join(f"{k}={v[0]}" for k, v in last.items()))

    start = _time.time()
    duration = 90.0
    interval = 0.3
    while _time.time() - start < duration:
        _time.sleep(interval)
        cur = snapshot()
        for name in SITES:
            if cur[name][0] != last[name][0]:
                t = _time.time() - start
                fvals_str = ", ".join(f"{k}=0x{v:08X}" for k, v in cur[name][1].items())
                log(f"t={t:5.1f}s  {name} FIRED (canary {last[name][0]}->{cur[name][0]})  {fvals_str}")
        last = cur

    log("Trace window ended.")


def do_dump_gate_bytes(log):
    import dolphin_memory_engine as dme
    dme.hook()
    time.sleep(0.3)
    if not dme.is_hooked():
        log("Not hooked -- is Dolphin running with the game loaded?")
        return

    log("=== raw bytes at 0x8004E314 (our FUN_8004e314 replacement) ===")
    data = dme.read_bytes(0x8004E314, 0x40)
    for i in range(0, len(data), 4):
        word = struct.unpack(">I", data[i:i+4])[0]
        log(f"0x{0x8004E314+i:08X}: {word:08X}")

    log("")
    log("=== raw bytes at 0x80060740 (facegen hook site) ===")
    data2 = dme.read_bytes(0x80060740, 0x10)
    for i in range(0, len(data2), 4):
        word = struct.unpack(">I", data2[i:i+4])[0]
        log(f"0x{0x80060740+i:08X}: {word:08X}")

    log("")
    log("=== raw bytes at 0x80017720 (FUN_80017720 real entry) ===")
    data3 = dme.read_bytes(0x80017720, 0x10)
    for i in range(0, len(data3), 4):
        word = struct.unpack(">I", data3[i:i+4])[0]
        log(f"0x{0x80017720+i:08X}: {word:08X}")


MODE = "serve"

_TRAMPOLINE_WORDS = [
    # DIAGNOSTIC BUILD: unconditionally forces eye_type to 47 (0x2F) instead
    # of respecting the lock bitmask, to prove whether this trampoline is
    # even being reached at all. Restore the normal 2-instruction revert
    # (just "rlwinm r7,r7,0,6,31" then "stw") once confirmed.
    # 0x803c1000 (guard: only act when category(r4)==eye(5), matches the
    # generic per-refresh call site inside FUN_8003bd68, shared by all
    # categories -- NOT the hub's one-time setup call, which never re-runs)
    "2C040005", "40820050",
    # 0x803c1008 (body)
    "80CD8F9C", "80C600BC", "80E60028", "54E836BE", "3D208020",
    "39297118", "7D4940AE", "3960000C", "7D4A5B96", "39600001",
    "7D6B5030", "3D80803C", "398C1040", "880C0000", "7C005839",
    "40820010", "54E701BE", "64E7BC00", "90E60028",
    # 0x803c1054 (tail branch back into FUN_8003bda4, plain 'b' not 'bl' --
    # this call site is itself a compiler tail-call, LR must stay untouched)
    "4BC7AD50",
]
TRAMPOLINE_BYTES = bytes.fromhex("".join(_TRAMPOLINE_WORDS))
HOOK_BYTES = bytes.fromhex("48385260")  # 'b 0x803c1000' (plain branch, LK=0)

HOOK_FILE_OFFSET = 0x37A60     # file offset of the "b FUN_8003bda4" hook site (inside FUN_8003bd68)
TRAMPOLINE_FILE_OFFSET = None  # computed at runtime = current EOF, appended
TRAMPOLINE_LOAD_ADDR = 0x803C1000
DOL_TEXT2_OFFSET_FIELD = 0x08   # header field: text-section-2 file offset
DOL_TEXT2_ADDR_FIELD = 0x50     # header field: text-section-2 load address
DOL_TEXT2_SIZE_FIELD = 0x98     # header field: text-section-2 size

ORIGINAL_APP_PATH = r"C:\Users\player\Documents\Perso\Emulateur\Tools\mii_channel_re\main.dol"
PATCHED_APP_PATH = r"C:\Users\player\Documents\Perso\Emulateur\Tools\mii_channel_re\main_patched.dol"


def do_dol_convert(log) -> None:
    with open(DOL_PATH, "rb") as fh:
        data = fh.read()

    def u32(off):
        return struct.unpack(">I", data[off:off + 4])[0]

    text_offs = [u32(0x00 + i * 4) for i in range(7)]
    data_offs = [u32(0x1C + i * 4) for i in range(11)]
    text_addrs = [u32(0x48 + i * 4) for i in range(7)]
    data_addrs = [u32(0x64 + i * 4) for i in range(11)]
    text_sizes = [u32(0x90 + i * 4) for i in range(7)]
    data_sizes = [u32(0xAC + i * 4) for i in range(11)]
    bss_addr = u32(0xD8)
    bss_size = u32(0xDC)
    entry = u32(0xE0)

    log(f"entry point: 0x{entry:08X}")
    log(f"bss: 0x{bss_addr:08X} + 0x{bss_size:X}")

    sections = []
    for i, (off, addr, size) in enumerate(zip(text_offs, text_addrs, text_sizes)):
        if size:
            sections.append(("text", i, off, addr, size))
    for i, (off, addr, size) in enumerate(zip(data_offs, data_addrs, data_sizes)):
        if size:
            sections.append(("data", i, off, addr, size))

    for kind, i, off, addr, size in sections:
        log(f"{kind}{i}: fileOff=0x{off:X} addr=0x{addr:08X} size=0x{size:X} (end=0x{addr+size:08X})")

    min_addr = min(addr for _, _, _, addr, _ in sections)
    max_addr = max(addr + size for _, _, _, addr, size in sections)
    if bss_size:
        min_addr = min(min_addr, bss_addr)
        max_addr = max(max_addr, bss_addr + bss_size)

    log(f"overall range: 0x{min_addr:08X} - 0x{max_addr:08X} (0x{max_addr - min_addr:X} bytes)")

    image = bytearray(max_addr - min_addr)
    for kind, i, off, addr, size in sections:
        image[addr - min_addr: addr - min_addr + size] = data[off:off + size]

    with open(OUT_PATH, "wb") as fh:
        fh.write(bytes(image))

    log(f"wrote {len(image)} bytes to {OUT_PATH}")
    log(f"IMPORT WITH BASE ADDRESS: 0x{min_addr:08X}")
    log(f"ENTRY POINT (for reference): 0x{entry:08X}")


def main(*args) -> None:
    lines = []

    def log(msg: str) -> None:
        lines.append(msg)
        with open(LOG_PATH, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

    try:
        if MODE == "serve":
            do_serve(log)
        elif MODE == "v9_state":
            do_v9_state(log)
        elif MODE == "entry_canary":
            do_entry_canary(log)
        elif MODE == "wc24_canary":
            do_wc24_canary(log)
        elif MODE == "dol_convert":
            do_dol_convert(log)
        elif MODE == "snapshot_a":
            do_snapshot(log, DUMP_A)
        elif MODE == "snapshot_b":
            do_snapshot(log, DUMP_B)
        elif MODE == "snapshot_idle1":
            do_snapshot(log, DUMP_IDLE1)
        elif MODE == "snapshot_idle2":
            do_snapshot(log, DUMP_IDLE2)
        elif MODE == "eyetype_diff":
            do_eyetype_diff(log)
        elif MODE == "check_candidates":
            do_check_candidates(log)
        elif MODE == "apply_dol_patch":
            do_apply_dol_patch(log)
        elif MODE == "read_dedicated":
            do_read_dedicated(log)
        elif MODE == "verify_ram":
            do_verify_ram(log)
        elif MODE == "find_committed":
            do_find_committed(log)
        elif MODE == "snapshot_near_r6_1":
            do_snapshot_near_r6(log, R6_WINDOW_PATH_1)
        elif MODE == "snapshot_near_r6_2":
            do_snapshot_near_r6(log, R6_WINDOW_PATH_2)
        elif MODE == "diff_near_r6":
            do_diff_near_r6(log)
        elif MODE == "phase2_canaries":
            do_phase2_canaries(log)
        elif MODE == "dialog_capture":
            do_dialog_capture(log)
        elif MODE == "facegen_canaries":
            do_facegen_canaries(log)
        elif MODE == "wizard_capture":
            do_wizard_capture(log)
        elif MODE == "entry_param_capture":
            do_entry_param_capture(log)
        elif MODE == "freeze_diag":
            do_freeze_diag(log)
        elif MODE == "deep_freeze_diag":
            do_deep_freeze_diag(log)
        elif MODE == "dump_gate_bytes":
            do_dump_gate_bytes(log)
        elif MODE == "find_mii_id_in_ram":
            do_find_mii_id_in_ram(log)
        elif MODE == "live_id_corrupt_test":
            do_live_id_corrupt_test(log)
        elif MODE == "find_ramtest_in_ram":
            do_find_ramtest_in_ram(log)
        elif MODE == "find_rnod_in_ram":
            do_find_rnod_in_ram(log)
        elif MODE == "read_loader_canaries":
            do_read_loader_canaries(log)
        elif MODE == "read_bcsetter_capture":
            do_read_bcsetter_capture(log)
        elif MODE == "read_11100_capture":
            do_read_11100_capture(log)
        elif MODE == "read_f880_capture":
            do_read_f880_capture(log)
        elif MODE == "read_scenecreate_capture":
            do_read_scenecreate_capture(log)
        elif MODE == "trace_creation":
            do_trace_creation(log)
    except Exception as e:
        log(f"FATAL: {e!r}")


if __name__ == "__main__":
    main()
