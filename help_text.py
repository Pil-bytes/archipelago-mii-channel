"""Text of the Plaza's "?" window, replaced by an Archipelago explanation
(user request, 2026-09-14).

The game opens that window with FUN_8002f154: title id "0000021"
("Controls") and text id "0000023" (the controls list). The dialog block in
gecko/HACA01.ini (BuildWC24DialogHelp) swaps both for what the client writes
at HELP_TITLE_ADDR / HELP_TEXT_ADDR (client.py), and keeps the game's own
text while those are empty.

One window, no pages: about nine lines of up to ~38 characters fit, like the
game's own controls text. Plain ASCII only -- the channel's font has no
bullets or dashes beyond the basics. The game is in English, so is this.
"""

HELP_TITLE = "Archipelago"

HELP_TEXT = (
    "Recreate the target Miis (Mii Parade,\n"
    "top right) to send checks.\n"
    "What is left: click Wii Friend, grab a\n"
    "Mii (A+B), drop it on the envelope.\n"
    "Grey-red locked, white doable, blue\n"
    "hinted, green sent, orange lost.\n"
    "Click a row: what is missing + Hint.\n"
    "Edit a Mii: drop it on Edit Mii.\n"
    "Always leave with Save & quit."
)
