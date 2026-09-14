from typing import Any, Dict, List

import worlds.LauncherComponents as LauncherComponents
from BaseClasses import ItemClassification, Region, Tutorial
from worlds.AutoWorld import WebWorld, World

from .checks import (MILESTONE_CHECKS, PERFECT_COPY_CATEGORY, TARGET_CHECK_CATEGORIES,
                     TARGET_CHECK_CATEGORIES_ALL, VICTORY_NAME, target_location_name)
from .items import MiiChannelItem, ItemData, item_table, filler_item_names, progressive_item_counts
from .locations import MiiChannelLocation, location_name_to_id
from .options import MiiChannelOptions
from .targets import generate_targets


def launch_client(*args) -> None:
    from .client import main
    LauncherComponents.launch(main, name="MiiChannelClient", args=args)


def launch_dme_probe(*args) -> None:
    from .dme_probe import main
    LauncherComponents.launch(main, name="MiiChannelDMEProbe", args=args)


LauncherComponents.components.append(
    LauncherComponents.Component(
        "Mii Channel Client",
        func=launch_client,
        component_type=LauncherComponents.Type.CLIENT,
    )
)

LauncherComponents.components.append(
    LauncherComponents.Component(
        "Mii Channel RAM Probe",
        func=launch_dme_probe,
        component_type=LauncherComponents.Type.TOOL,
    )
)


class MiiChannelWebWorld(WebWorld):
    theme: str = "grass"

    tutorials = [
        Tutorial(
            "Multiworld Setup Guide",
            "How to set up the automatic Mii Channel client, which reads your real Miis from RFL_DB.dat.",
            "English",
            "setup_en.md",
            "setup/en",
            ["Pil_Bandit"],
        )
    ]


class MiiChannelWorld(World):
    """
    An automatically-tracked Archipelago world for the Wii Mii Channel. It
    reads your real Mii database (RFL_DB.dat) and checks locations for you as
    you actually create and customize Miis -- no manual clicking required.
    """

    game = "Mii Channel Auto"
    options_dataclass = MiiChannelOptions
    options: MiiChannelOptions

    web = MiiChannelWebWorld()

    item_name_to_id: Dict[str, int] = {name: data.code for name, data in item_table.items()}
    location_name_to_id: Dict[str, int] = location_name_to_id

    def generate_early(self) -> None:
        # Frozen for the whole seed -- sent to the client via slot_data and
        # must never be regenerated on the fly (see project memory's "New
        # goal design" section for why: the in-game panel this will
        # eventually drive must show a stable list, not a re-rolled one).
        self.target_miis: List[Dict[str, int]] = generate_targets(
            self.random, self.options.target_count.value
        )

    def create_regions(self) -> None:
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)

        for name, _ in MILESTONE_CHECKS:
            location = MiiChannelLocation(self.player, name, self.location_name_to_id[name], menu)
            menu.locations.append(location)

        for i in range(len(self.target_miis)):
            for category in TARGET_CHECK_CATEGORIES_ALL:
                name = target_location_name(i, category)
                location = MiiChannelLocation(self.player, name, self.location_name_to_id[name], menu)
                menu.locations.append(location)

        victory_location = MiiChannelLocation(
            self.player, VICTORY_NAME, self.location_name_to_id[VICTORY_NAME], menu
        )
        victory_location.place_locked_item(self.create_item("Victory"))
        menu.locations.append(victory_location)

    def create_item(self, name: str) -> MiiChannelItem:
        data: ItemData = item_table[name]
        return MiiChannelItem(name, data.classification, data.code, self.player)

    def create_items(self) -> None:
        item_pool: List[MiiChannelItem] = [self.create_item("Golden Wii Remote")]

        # gating_item_names are all in progressive_item_counts now (each
        # ships in several copies), so adding them here too would duplicate.
        for name, count in progressive_item_counts.items():
            for _ in range(count):
                item_pool.append(self.create_item(name))

        num_locations = len(MILESTONE_CHECKS) + len(self.target_miis) * len(TARGET_CHECK_CATEGORIES_ALL)
        if len(item_pool) > num_locations:
            raise ValueError(
                f"Mii Channel Auto: {len(item_pool)} mandatory items don't fit in "
                f"{num_locations} locations -- raise target_count (currently "
                f"{self.options.target_count.value})."
            )
        while len(item_pool) < num_locations:
            item_pool.append(self.create_item(self.random.choice(filler_item_names)))

        self.multiworld.itempool += item_pool

    def get_filler_item_name(self) -> str:
        return self.random.choice(filler_item_names)

    def set_rules(self) -> None:
        """Every check needs the items that make its values selectable.

        Without rules the generator treated every check as open from the
        start and could put an item behind its own check (Glasses Case on
        "Glasses Type Match"). locks.category_needs is the same computation
        the client's envelope list uses, so "in logic" means the same thing
        in both places. Favorite Color, Body and the Create-N-Miis
        milestones need nothing: they are where the chain starts."""
        from .locks import category_needs, item_copies
        from .targets import CATEGORY_FIELDS

        player = self.player

        def has_all(needs: Dict[str, int]):
            return lambda state: all(state.has(item, player, n) for item, n in needs.items())

        def merge(into: Dict[str, int], needs: Dict[str, int]) -> None:
            for item, n in needs.items():
                into[item] = max(into.get(item, 0), n)

        everything: Dict[str, int] = {}
        for i, target in enumerate(self.target_miis):
            perfect: Dict[str, int] = {}
            for category in TARGET_CHECK_CATEGORIES:
                if category not in CATEGORY_FIELDS:      # Body
                    continue
                needs = category_needs(target, CATEGORY_FIELDS[category])
                merge(perfect, needs)
                if needs:
                    location = self.multiworld.get_location(target_location_name(i, category), player)
                    location.access_rule = has_all(needs)
            self.multiworld.get_location(
                target_location_name(i, PERFECT_COPY_CATEGORY), player).access_rule = has_all(perfect)
            merge(everything, perfect)

        self.multiworld.get_location(VICTORY_NAME, player).access_rule = has_all(everything)
        self.multiworld.get_location("Use Every Face Shape", player).access_rule = has_all(
            {"Face Shape Tool": item_copies("Face Shape Tool")})

    def generate_basic(self) -> None:
        self.multiworld.completion_condition[self.player] = lambda state: state.has("Victory", self.player)

    def fill_slot_data(self) -> Dict[str, Any]:
        return {
            "miis_required": self.options.miis_required.value,
            "target_miis": self.target_miis,
        }
