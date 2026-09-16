"""The Dolphin user folder Mii Channel Auto plays in (v1.1, user request
2026-09-16: installing the world must never cost a player their Miis).

RFL_DB.dat is the Wii's one Mii database -- every game reads it. The client
rewrites it all the time (targets in the Parade, locked features reverted,
traps), so it only ever works inside a Dolphin user folder of its own:

  * first launch: the folder is created and the Mii Channel is copied into it
    from the player's regular Dolphin (the channel, its ticket and the system
    files it boots with -- never shared2/menu/FaceLib, so the save starts
    empty and the player's own Miis stay untouched where they are);
  * every launch: the Gecko codes and the "cheats on" setting are written into
    it, and Dolphin is started with -u on it.

A folder is only used if this module created it (marker file), or if the
player named it explicitly in host.yaml.
"""
from __future__ import annotations

import configparser
import os
import shutil
import sys
from typing import Callable, List, Optional, Tuple

MARKER_FILE = "ARCHIPELAGO_MII_CHANNEL_AUTO.txt"
MARKER_TEXT = (
    "This Dolphin user folder belongs to Archipelago's Mii Channel Auto.\n"
    "Its Mii save (Wii/shared2/menu/FaceLib/RFL_DB.dat) is rewritten by the\n"
    "client while you play. Your regular Dolphin folder is never modified.\n"
)
TITLE_HIGH, TITLE_LOW = "00010002", "48414341"   # Mii Channel (HACA)

# What the channel needs to boot, relative to a user folder. The Mii save
# (shared2/menu/FaceLib) is deliberately absent.
COPY_TREES = [
    os.path.join("Wii", "title", TITLE_HIGH, TITLE_LOW),
    os.path.join("Wii", "shared1"),
    os.path.join("Wii", "sys"),
]
COPY_FILES = [
    os.path.join("Wii", "ticket", TITLE_HIGH, TITLE_LOW + ".tik"),
    os.path.join("Wii", "shared2", "sys", "SYSCONF"),
]


def rfl_db_path(profile_dir: str) -> str:
    return os.path.join(profile_dir, "Wii", "shared2", "menu", "FaceLib", "RFL_DB.dat")


def has_mii_channel(user_dir: str) -> bool:
    return os.path.isdir(os.path.join(user_dir, "Wii", "title", TITLE_HIGH, TITLE_LOW, "content"))


def regular_user_dirs(dolphin_exe: str) -> List[str]:
    """Where the player's own Dolphin keeps its data, most likely first."""
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
    if exe_dir:
        out.append(os.path.join(exe_dir, "User"))
    return out


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


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


def _enable_cheats(profile_dir: str) -> None:
    """Config/Dolphin.ini: cheats on (the Gecko codes need it), and no
    first-run analytics question on a folder Dolphin has never seen."""
    path = os.path.join(profile_dir, "Config", "Dolphin.ini")
    ini = configparser.ConfigParser(strict=False, interpolation=None)
    ini.optionxform = str
    try:
        ini.read(path, encoding="utf-8")
    except configparser.Error:
        ini = configparser.ConfigParser(strict=False, interpolation=None)
        ini.optionxform = str
    wanted = {("Core", "EnableCheats"): "True",
              ("Analytics", "PermissionAsked"): "True",
              ("Analytics", "Enabled"): "False"}
    changed = False
    for (section, key), value in wanted.items():
        if not ini.has_section(section):
            ini.add_section(section)
        if ini.get(section, key, fallback=None) != value:
            ini.set(section, key, value)
            changed = True
    if changed or not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            ini.write(fh, space_around_delimiters=True)


def prepare(profile_dir: str, explicit: bool, dolphin_exe: str, source_dir: str,
            gecko_ini: bytes, log: Callable[[str], None]) -> Tuple[bool, str]:
    """Make `profile_dir` ready to play. Returns (ok, message for the player).

    `explicit`: the player named this folder in host.yaml (then an existing
    folder with the channel in it is adopted as is). `source_dir`: the
    regular Dolphin user folder to copy the channel from ("" = find it)."""
    marker = os.path.join(profile_dir, MARKER_FILE)
    if not os.path.isfile(marker):
        if has_mii_channel(profile_dir):
            if not explicit:
                return False, (f"{profile_dir} already holds a Wii that Mii Channel Auto did not create. "
                               "Name it in host.yaml (mii_channel_auto_options > profile_folder) if you "
                               "really want to play in it -- its Mii save will be rewritten.")
        else:
            if os.path.isdir(profile_dir) and os.listdir(profile_dir):
                return False, (f"{profile_dir} is not empty and is not a Mii Channel Auto folder. "
                               "Choose another profile_folder in host.yaml.")
            sources = [source_dir] if source_dir else regular_user_dirs(dolphin_exe)
            source = next((s for s in sources
                           if s and has_mii_channel(s) and not _same(s, profile_dir)), None)
            if source is None:
                return False, ("The Mii Channel is not installed in your Dolphin. In Dolphin: "
                               "Tools > Perform Online System Update (or install the Mii Channel "
                               "WAD), then restart this client. Looked in: " + ", ".join(s for s in sources if s))
            log(f"Creating the Mii Channel Auto Dolphin folder in {profile_dir} "
                f"(the Mii Channel is copied from {source}; your own Miis are not).")
            for rel in COPY_TREES:
                src = os.path.join(source, rel)
                if os.path.isdir(src):
                    shutil.copytree(src, os.path.join(profile_dir, rel), dirs_exist_ok=True)
            for rel in COPY_FILES:
                src = os.path.join(source, rel)
                if os.path.isfile(src):
                    os.makedirs(os.path.dirname(os.path.join(profile_dir, rel)), exist_ok=True)
                    shutil.copy2(src, os.path.join(profile_dir, rel))
        os.makedirs(profile_dir, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(MARKER_TEXT)

    _write_if_changed(os.path.join(profile_dir, "GameSettings", "HACA01.ini"), gecko_ini)
    _enable_cheats(profile_dir)
    return True, ""
