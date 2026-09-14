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


class TrapPercentage(Range):
    """
    Percentage of the filler items ("Nothing") replaced by traps. 0 turns
    traps off.
    """
    display_name = "Trap Percentage"
    range_start = 0
    range_end = 100
    default = 20


class TrapWeight(Range):
    range_start = 0
    range_end = 10
    default = 5


class QuitWithoutSavingTrapWeight(TrapWeight):
    """How often a trap is "Quit Without Saving": the Mii editor closes and
    the edit in progress is lost (waits for the editor if it isn't open)."""
    display_name = "Quit Without Saving Trap Weight"
    default = 0   # until the in-game effect is wired up


class ToolJamTrapWeight(TrapWeight):
    """How often a trap is "Tool Jam": one tool you already unlocked locks
    again for 60 seconds."""
    display_name = "Tool Jam Trap Weight"


class PaintSpillTrapWeight(TrapWeight):
    """How often a trap is "Paint Spill": a random colour (hair, eyes,
    eyebrows, mouth, glasses, facial hair or favourite colour) lands on one
    of your Miis."""
    display_name = "Paint Spill Trap Weight"


class GrowthSpurtTrapWeight(TrapWeight):
    """How often a trap is "Growth Spurt": one of your Miis gets a random
    height and weight."""
    display_name = "Growth Spurt Trap Weight"


class BigHeadTrapWeight(TrapWeight):
    """How often a trap is "Big Head": every Mii's head balloons for 30
    seconds."""
    display_name = "Big Head Trap Weight"
    default = 0   # until the in-game effect is wired up


@dataclass
class MiiChannelOptions(PerGameCommonOptions):
    miis_required: MiisRequired
    target_count: TargetCount
    trap_percentage: TrapPercentage
    quit_without_saving_trap_weight: QuitWithoutSavingTrapWeight
    tool_jam_trap_weight: ToolJamTrapWeight
    paint_spill_trap_weight: PaintSpillTrapWeight
    growth_spurt_trap_weight: GrowthSpurtTrapWeight
    big_head_trap_weight: BigHeadTrapWeight
