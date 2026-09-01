from __future__ import annotations

from typing import Dict

from BaseClasses import Location

from .checks import CHECK_NAMES

LOCATION_ID_BASE = 90100000


class MiiChannelLocation(Location):
    game = "Mii Channel Auto"


location_name_to_id: Dict[str, int] = {
    name: LOCATION_ID_BASE + i for i, name in enumerate(CHECK_NAMES)
}
