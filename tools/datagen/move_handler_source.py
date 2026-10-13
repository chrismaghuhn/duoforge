"""Step-4 adapter from the existing generator lists to move-phase rows.

CF1 can replace this reader with entry files without changing the writer.
These bits describe the late guard and generic-status bypass, not support
manifest marks: early-returning status moves have no late hit handler.
"""
from dataclasses import dataclass

from gen_closure import SPECIAL_IDS_P, SPECIAL_POOL


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
    "AFTER_YOU", "QUASH", "TRICK", "SWITCHEROO", "SKILL_SWAP", "TAUNT", "YAWN",
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
    mapped = {entry[0] for entry in SPECIAL_POOL.values()}
    if set(ids) != mapped | _DATA_ONLY | {"NONE", "UNMODELED"}:
        raise ValueError("special ids differ from mapped handlers and legacy data ids")
    if not _BEFORE_GUARD <= mapped or not _STATUS_HIT <= mapped:
        raise ValueError("move-phase annotations refer to a missing handler")
    excluded = _BEFORE_GUARD | _DATA_ONLY | {"UNMODELED"}
    return tuple(HandlerRow(n, i, n not in excluded, n in _STATUS_HIT)
                 for i, n in enumerate(ids))
