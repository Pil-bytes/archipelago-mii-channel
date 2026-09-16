from dataclasses import dataclass

from Options import DeathLink, Range, PerGameCommonOptions


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
    the edit in progress is lost (waits for the editor if it isn't open).
    Being thrown out by it does not send a DeathLink."""
    display_name = "Quit Without Saving Trap Weight"


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


class ShuffleTrapWeight(TrapWeight):
    """How often a trap is "Shuffle": every value of one of your unfinished
    Miis is re-rolled among the values you can already pick."""
    display_name = "Shuffle Trap Weight"


class MutationTrapWeight(TrapWeight):
    """How often a trap is "Mutation": one value of one of your Miis changes,
    finished Miis included (they lose their star until fixed)."""
    display_name = "Mutation Trap Weight"


class DefaultTrapWeight(TrapWeight):
    """How often a trap is "Default": one of your unfinished Miis goes back
    to a Mii made from scratch."""
    display_name = "Default Trap Weight"


class BlindfoldTrapWeight(TrapWeight):
    """How often a trap is "Blindfold": the Mii you edit is invisible for 30
    seconds (waits for the editor)."""
    display_name = "Blindfold Trap Weight"


class LockdownTrapWeight(TrapWeight):
    """How often a trap is "Lockdown": every editor tool locks for 25 seconds
    (waits for the editor)."""
    display_name = "Lockdown Trap Weight"


@dataclass
class MiiChannelOptions(PerGameCommonOptions):
    miis_required: MiisRequired
    target_count: TargetCount
    trap_percentage: TrapPercentage
    quit_without_saving_trap_weight: QuitWithoutSavingTrapWeight
    tool_jam_trap_weight: ToolJamTrapWeight
    paint_spill_trap_weight: PaintSpillTrapWeight
    growth_spurt_trap_weight: GrowthSpurtTrapWeight
    shuffle_trap_weight: ShuffleTrapWeight
    mutation_trap_weight: MutationTrapWeight
    default_trap_weight: DefaultTrapWeight
    blindfold_trap_weight: BlindfoldTrapWeight
    lockdown_trap_weight: LockdownTrapWeight
    death_link: DeathLink
