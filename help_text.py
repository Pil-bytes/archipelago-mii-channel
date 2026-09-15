"""Archipelago texts shown in place of the game's own, screen by screen
(user request 2026-09-15: "separate the hints by the screen that shows").

The dialog block in gecko/HACA01.ini (BuildWC24DialogTable) looks every text
the game sets up by its message id; the client writes a table of
{message id -> UTF-16 text} (client.py, TEXT_TABLE_ADDR). An id missing from
the table, or the client not running, keeps the game's own text.

Ids and what the game shows there (read from the channel's message file,
Tools/mii_channel_re/bmg_messages.txt):
  0000021 / 0000023  the "?" (Help) window: title "Controls" + controls list
  0000080            first-launch message ("Select Help at the bottom...")
  0000052            Mii Parade introduction
  0000059            New Mii button description
  0000054 / 0000007  Edit Mii button description / Edit Mii mode banner
  0000057 / 0000034  Wii Friend button description / Wii Friend mode banner
  0101600            header of the envelope list
  0000031            Erase mode banner

Keep each text about as long as the one it replaces (the windows do not
grow): up to ~38 characters per line. Plain ASCII -- the font has none of
the game's button glyphs as ordinary characters. The game is in English.
"""
from typing import Dict

SCREEN_TEXTS: Dict[str, str] = {
    # "?" window, reachable from the Plaza at any time
    "0000021": "Archipelago",
    "0000023": (
        "Recreate the target Miis (Mii Parade,\n"
        "top right) to send checks.\n"
        "Wii Friend: drop a Mii on the envelope\n"
        "to see what it still has to match.\n"
        "Edit Mii: drop a Mii on Edit.\n"
        "Locked tools come from the multiworld.\n"
        "Always leave with Save & quit."
    ),
    # first launch
    "0000080": (
        "Archipelago: recreate the target Miis\n"
        "of the Mii Parade to send checks.\n"
        "Select Help at the bottom of the\n"
        "screen at any time for a reminder."
    ),
    # Mii Parade
    "0000052": (
        "The target Miis you have to recreate\n"
        "wait here: Target 1, Target 2...\n"
        "Come back and look at them as often\n"
        "as you like."
    ),
    # New Mii
    "0000059": (
        "Create a Mii and edit it towards a\n"
        "target. Favorite color, height and\n"
        "weight are never locked: a good first\n"
        "check. Other tools come as items."
    ),
    # Edit Mii
    "0000054": "Edit a Mii to match its target.",
    "0000007": (
        "Grab a Mii (A+B), drag it to Edit.\n"
        "Grey tools are still locked.\n"
        "Leave with Save & quit to send\n"
        "your checks."
    ),
    # Wii Friend -> the Archipelago checklist
    "0000057": "See what a Mii still has to match\nfor its target, and ask for hints.",
    "0000034": (
        "Grab a Mii (A+B) and drag it to\n"
        "the envelope: the list shows what\n"
        "it still has to match. Grey-red:\n"
        "locked, white: doable, blue: hinted,\n"
        "green: sent, orange: sent but lost."
    ),
    "0101600": "Click a row for details or a\nhint, the header for colours.",
    # Erase
    "0000031": (
        "Grab a Mii (A+B), drag it to Erase.\n"
        "Checks it already sent stay sent."
    ),
    # Plaza <-> Parade transfers are blocked (gecko block "Block transfers");
    # these are the game's own refusals, forced on every transfer.
    "0600500": "Archipelago: Miis can't be sent\nto the Mii Parade.",
    "0000014": "Archipelago: Miis can't be sent\nfrom the Mii Parade to the Plaza.",
}
