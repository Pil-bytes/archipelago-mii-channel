"""Install "Mii Channel Archipelago", a modified copy of the Mii Channel, into
the player's own Dolphin (v1.0.1, user request 2026-09-16: a modified game like
PokePark's, not a separate Dolphin folder).

RFL_DB.dat is the Wii's one Mii database, read by every game, and the client
rewrites the save it plays with all the time. So the copy uses a save of its
own: the path "/shared2/menu/FaceLib/RFL_DB.dat" in its code becomes
".../RFL_AP.dat". The player's Miis and the real Mii Channel stay untouched.

Dolphin keeps installed titles decrypted, so the copy is made from the Mii
Channel already in the player's Dolphin (Wii/title/00010002/48414341):

  * its contents are copied to a new title, 00010002/48415058 ("HAPX"), with
    the save path patched and the TMD's title id and content hash updated;
  * its ticket is copied under the new title id;
  * the Gecko codes go to GameSettings/HAPX01.ini and cheats are enabled.

The client then starts Dolphin with -n on the new title. Every RAM address
the client and the Gecko codes use is unchanged: only a string moves.
"""
from __future__ import annotations

import configparser
import hashlib
import os
import shutil
import struct
import sys
from typing import Callable, List, Tuple

SOURCE_TITLE = ("00010002", "48414341")          # Mii Channel (HACA)
TITLE_HIGH, TITLE_LOW = "00010002", "48415058"   # Mii Channel Archipelago (HAPX)
TITLE_ID = TITLE_HIGH + TITLE_LOW
GAME_ID = "HAPX01"   # HAPX: in no title database (HCAP was a real channel)
DB_PATH = b"/shared2/menu/FaceLib/RFL_DB.dat"
AP_DB_PATH = b"/shared2/menu/FaceLib/RFL_AP.dat"   # same length: patched in place
PATCH_VERSION = "2"                                # bump when the patch changes
# Banner name, every language (user 2026-09-16). IMET holds one name of 42
# UTF-16 characters per language: two lines, the credits under the name.
BANNER_NAME = "Mii Channel AP\nNintendo / Pil_Bandit"
IMET_NAMES = 0x5C          # from the start of the IMET header (magic at +0x40)
IMET_NAME_SIZE = 0x54
IMET_LANGUAGES = 10
IMET_MD5 = 0x5F0           # MD5 of header bytes 0..0x600 with this field zeroed

TMD_TITLE_ID = 0x18C
TMD_CONTENT_COUNT = 0x1DE
TMD_CONTENTS = 0x1E4
TMD_CONTENT_SIZE = 0x24
TICKET_TITLE_ID = 0x1DC


def _title_dir(user_dir: str, high: str, low: str) -> str:
    return os.path.join(user_dir, "Wii", "title", high, low)


def save_path(user_dir: str) -> str:
    return os.path.join(user_dir, "Wii", "shared2", "menu", "FaceLib", "RFL_AP.dat")


def regular_user_dirs(dolphin_exe: str) -> List[str]:
    """Where a Dolphin keeps its data, most likely first."""
    out: List[str] = []
    exe_dir = os.path.dirname(os.path.abspath(dolphin_exe)) if dolphin_exe else ""
    if exe_dir and os.path.isfile(os.path.join(exe_dir, "portable.txt")):
        out.append(os.path.join(exe_dir, "User"))
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            out.append(os.path.join(appdata, "Dolphin Emulator"))
        out.append(os.path.join(os.path.expanduser("~"), "Documents", "Dolphin Emulator"))
    elif sys.platform == "darwin":
        out.append(os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Dolphin"))
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        out.append(os.path.join(xdg, "dolphin-emu"))
        out.append(os.path.join(os.path.expanduser("~"), ".dolphin-emu"))
    return out


def find_user_dir(dolphin_exe: str) -> str:
    """The first candidate that holds a Wii NAND, else the first candidate."""
    candidates = regular_user_dirs(dolphin_exe)
    for c in candidates:
        if os.path.isdir(os.path.join(c, "Wii")):
            return c
    return candidates[0] if candidates else ""


def _write_if_changed(path: str, data: bytes) -> None:
    try:
        with open(path, "rb") as fh:
            if fh.read() == data:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _enable_cheats(user_dir: str) -> bool:
    """Config/Dolphin.ini [Core] EnableCheats = True. Returns True if changed."""
    path = os.path.join(user_dir, "Config", "Dolphin.ini")
    ini = configparser.ConfigParser(strict=False, interpolation=None)
    ini.optionxform = str
    try:
        ini.read(path, encoding="utf-8")
    except configparser.Error:
        return False            # leave a config we can't parse alone
    if ini.get("Core", "EnableCheats", fallback="") == "True":
        return False
    if not ini.has_section("Core"):
        ini.add_section("Core")
    ini.set("Core", "EnableCheats", "True")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        ini.write(fh, space_around_delimiters=True)
    return True


def _rename_banner(data: bytes) -> bytes:
    """The channel's name in its banner (content 0, IMET header)."""
    magic = data.find(b"IMET")
    if magic < 0x40:
        return data
    base = magic - 0x40
    header = bytearray(data[base:base + 0x600])
    name = BANNER_NAME.encode("utf-16-be")[:IMET_NAME_SIZE].ljust(IMET_NAME_SIZE, b"\0")
    for lang in range(IMET_LANGUAGES):
        off = IMET_NAMES + lang * IMET_NAME_SIZE
        header[off:off + IMET_NAME_SIZE] = name
    header[IMET_MD5:IMET_MD5 + 16] = bytes(16)
    header[IMET_MD5:IMET_MD5 + 16] = hashlib.md5(bytes(header)).digest()
    return data[:base] + bytes(header) + data[base + 0x600:]


def _installed_version(user_dir: str) -> str:
    try:
        with open(os.path.join(_title_dir(user_dir, TITLE_HIGH, TITLE_LOW), "archipelago.txt"),
                  encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def install(user_dir: str, gecko_ini: bytes, log: Callable[[str], None]) -> Tuple[bool, str]:
    """Make Mii Channel Archipelago ready in `user_dir`. (ok, message)."""
    src = _title_dir(user_dir, *SOURCE_TITLE)
    dst = _title_dir(user_dir, TITLE_HIGH, TITLE_LOW)
    src_content = os.path.join(src, "content")
    if _installed_version(user_dir) != PATCH_VERSION:
        tmd_path = os.path.join(src_content, "title.tmd")
        ticket = os.path.join(user_dir, "Wii", "ticket", *SOURCE_TITLE[:1], SOURCE_TITLE[1] + ".tik")
        if not (os.path.isfile(tmd_path) and os.path.isfile(ticket)):
            return False, ("The Mii Channel is not installed in this Dolphin (" + user_dir + "). In "
                           "Dolphin: Tools > Perform Online System Update, or install the Mii Channel "
                           "WAD -- then restart this client. If your Dolphin keeps its data elsewhere, "
                           "set dolphin_user_folder in host.yaml.")
        tmd = bytearray(open(tmd_path, "rb").read())
        count = struct.unpack_from(">H", tmd, TMD_CONTENT_COUNT)[0]
        contents = []
        patched = False
        for i in range(count):
            off = TMD_CONTENTS + TMD_CONTENT_SIZE * i
            cid, _index, ctype, size = struct.unpack_from(">IHHQ", tmd, off)
            if ctype & 0x8000:
                continue                       # shared content: stays in Wii/shared1
            name = "%08x.app" % cid
            data = open(os.path.join(src_content, name), "rb").read()
            original = data
            if _index == 0:
                data = _rename_banner(data)
            if DB_PATH in data:
                data = data.replace(DB_PATH, AP_DB_PATH)
                patched = True
            if data != original:
                tmd[off + 16:off + 36] = hashlib.sha1(data).digest()
            contents.append((name, data))
        if not patched:
            return False, ("This Mii Channel version is not supported (its Mii save path was not "
                           "found). Mii Channel v6 (World) is the one tested.")
        tmd[TMD_TITLE_ID:TMD_TITLE_ID + 8] = bytes.fromhex(TITLE_ID)
        tik = bytearray(open(ticket, "rb").read())
        tik[TICKET_TITLE_ID:TICKET_TITLE_ID + 8] = bytes.fromhex(TITLE_ID)

        log(f"Installing Mii Channel Archipelago into {user_dir} "
            "(a copy of your Mii Channel with a save of its own; your Miis are not touched).")
        if os.path.isdir(os.path.join(dst, "content")):
            shutil.rmtree(os.path.join(dst, "content"))
        for name, data in contents:
            _write_if_changed(os.path.join(dst, "content", name), data)
        _write_if_changed(os.path.join(dst, "content", "title.tmd"), bytes(tmd))
        os.makedirs(os.path.join(dst, "data"), exist_ok=True)
        _write_if_changed(os.path.join(user_dir, "Wii", "ticket", TITLE_HIGH, TITLE_LOW + ".tik"), bytes(tik))
        with open(os.path.join(dst, "archipelago.txt"), "w", encoding="utf-8") as fh:
            fh.write(PATCH_VERSION)

    _write_if_changed(os.path.join(user_dir, "GameSettings", GAME_ID + ".ini"), gecko_ini)
    if _enable_cheats(user_dir):
        log("Dolphin's cheats were switched on (Config > General > Enable Cheats): "
            "Mii Channel Archipelago needs its Gecko codes.")
    return True, ""
