from dataclasses import dataclass

from Options import Range, PerGameCommonOptions


class MiisRequired(Range):
    """
    How many real Miis you need to have created (in RFL_DB.dat) for the
    "Create N Miis" milestone checks.
    """
    display_name = "Miis Required for Milestones"
    range_start = 5
    range_end = 100
    default = 10


class TargetCount(Range):
    """
    How many random target Miis you must try to recreate exactly. Each
    target adds up to 10 checks (one per matching face-part category, plus
    one for matching height+weight), so raising this significantly increases
    the total number of checks in this world. You reach "Become a Mii
    Master" once every check for every target has been completed.

    Minimum is 5 (not 1) because the gating items alone (progressive page
    unlocks plus separate color/movement unlocks per category) need at
    least that many target-driven checks to have somewhere to go.
    """
    display_name = "Number of Target Miis"
    range_start = 5
    range_end = 20
    default = 5


@dataclass
class MiiChannelOptions(PerGameCommonOptions):
    miis_required: MiisRequired
    target_count: TargetCount
