"""Step-4 adapter from the existing generator lists to move-phase rows.

CF1 can replace this reader with entry files without changing the writer.
These bits describe the late guard and generic-status bypass, not support
manifest marks: early-returning status moves have no late hit handler.
"""
from dataclasses import dataclass

from gen_closure import SPECIAL_IDS_P, SPECIAL_POOL


# turn.c@657dae45: the explicit positive list at the late handler guard.
# New specials must be classified deliberately, never admitted by exclusion.
_LATE_GUARD = {
    "NONE", "GRASS_KNOT", "WEATHER_BALL", "HURRICANE", "GRASSY_GLIDE",
    "ELECTRO_SHOT", "FAKE_OUT", "PARTING_SHOT", "PROTECT", "STRUGGLE",
    "DARKEST_LARIAT", "LAST_RESPECTS", "SUCKER_PUNCH", "ENCORE", "FIRST_IMPRESSION",
    "SOAK", "LOW_KICK", "KNOCK_OFF", "EXPANDING_FORCE", "GLAIVE_RUSH",
    "ACROBATICS", "BLIZZARD", "FEINT", "PSYCHIC_FANGS", "SOLAR_BEAM",
    "HP_POWER", "BODY_PRESS", "FOUL_PLAY", "PSYSHOCK", "FREEZE_DRY",
    "CLANGING_SCALES", "STEEL_ROLLER", "BRICK_BREAK", "DISABLE", "RISING_VOLTAGE",
    "TERRAIN_PULSE", "MULTI_HIT_2", "TRIPLE_AXEL", "IMPRISON", "TRICK",
    "SWITCHEROO", "THIEF", "COVET", "SUPER_FANG", "TAUNT",
    "YAWN", "RAGE_FIST", "STONE_AXE", "CEASELESS_EDGE", "MULTI_HIT_10",
    "POWER_TRIP", "THUNDER", "ICE_FANG", "TRI_ATTACK", "DOUBLE_SHOCK",
    "ROOST", "STOMPING_TANTRUM", "LOCKED_MOVE", "MULTI_HIT_2_5", "SCALE_SHOT",
    "QUICK_GUARD", "UPPER_HAND", "HEAL_PULSE", "STRENGTH_SAP", "BEAT_UP",
    "BUG_BITE", "POLTERGEIST", "SHEER_COLD", "AFTER_YOU", "QUASH",
    "SUBSTITUTE", "PHANTOM_FORCE", "STEEL_BEAM", "THUNDER_WAVE", "SKILL_SWAP",
    "ALLURING_VOICE", "DRAGON_CHEER", "FINAL_GAMBIT", "DRAGON_DARTS", "LASH_OUT",
    "ASSURANCE", "HEAVY_SLAM", "HARD_PRESS", "ICE_SPINNER", "BELLY_DRUM",
    "WILL_CRIT", "LEECH_SEED", "CONFUSE", "OHKO", "MEMENTO",
    "LEVEL_DAMAGE", "PARTIAL_TRAP", "ENDEAVOR", "PSYCH_UP", "ALLY_SWITCH",
    "PSYCHIC_TERRAIN", "SPEED_SWAP",
}
# turn.c@657dae45: these move effects return before the late handler guard.
_BEFORE_GUARD = {
    "HELPING_HAND", "FOLLOW_ME", "WIDE_GUARD", "SANDSTORM", "SNOWSCAPE",
    "AURORA_VEIL", "SPIKY_SHIELD", "SHELL_SMASH", "RAGE_POWDER", "RAIN_DANCE",
    "SUNNY_DAY", "CLANGOROUS_SOUL", "ELECTRIC_TERRAIN", "MISTY_TERRAIN",
    "PERISH_SONG", "REVIVAL_BLESSING", "HAZE", "KINGS_SHIELD", "BATON_PASS",
    "DESTINY_BOND", "BANEFUL_BUNKER", "CURSE", "HEALING_WISH",
}
# G10's former handlers became data; their frozen ids remain, unused.
_DATA_ONLY = {"SCALD", "RECOVER"}
# turn.c@657dae45: status moves with their own target-hit handling.
_STATUS_HIT = {
    "PARTING_SHOT", "STRENGTH_SAP", "HEAL_PULSE", "SOAK", "ENCORE", "DISABLE",
    "AFTER_YOU", "QUASH", "TRICK", "SWITCHEROO", "SKILL_SWAP", "SPEED_SWAP", "TAUNT", "YAWN",
    "DRAGON_CHEER", "PSYCH_UP", "ALLY_SWITCH", "LEECH_SEED", "CONFUSE",
}


@dataclass(frozen=True)
class HandlerRow:
    name: str
    value: int
    hit_guard: bool
    status_hit: bool


def rows():
    """Keep the generator's frozen ordering and fail on unexplained ids."""
    ids = tuple(SPECIAL_IDS_P)
    if len(ids) != len(set(ids)) or not 0 < len(ids) <= 256:
        raise ValueError("special ids must be unique and fit the uint8_t column")
    classes = {
        "late handler": _LATE_GUARD,
        "before guard": _BEFORE_GUARD,
        "legacy data": _DATA_ONLY,
        "unsupported": {"UNMODELED"},
    }
    for name in ids:
        assigned = [label for label, members in classes.items() if name in members]
        if len(assigned) != 1:
            raise ValueError(f"DFI_SPECIAL_{name}: expected exactly one phase class; "
                             f"got {', '.join(assigned) or 'none'}")
    unknown = set().union(*classes.values()) - set(ids)
    if unknown:
        raise ValueError("move-phase classes refer to unknown specials: " +
                         ", ".join(f"DFI_SPECIAL_{name}" for name in sorted(unknown)))
    mapped = {entry[0] for entry in SPECIAL_POOL.values()}
    if set(ids) != mapped | _DATA_ONLY | {"NONE", "UNMODELED"}:
        raise ValueError("special ids differ from mapped handlers and legacy data ids")
    if not _BEFORE_GUARD <= mapped or not _STATUS_HIT <= mapped or not _STATUS_HIT <= _LATE_GUARD:
        raise ValueError("move-phase annotations refer to a missing handler")
    return tuple(HandlerRow(n, i, n in _LATE_GUARD, n in _STATUS_HIT)
                 for i, n in enumerate(ids))
