"""NumPy dtypes of the public C structs, with explicit offsets.

Every dtype mirrors one struct of include/duoforge; the test
duoforge.python.layout compares each with the C tool duoforge_layout_dump.
Byte order is native: the arrays are the C library's memory.
"""
import ctypes

import numpy as np

_PTR = ctypes.sizeof(ctypes.c_void_p)


def _struct(fields, itemsize):
    """A structured dtype from (name, format, offset) triples."""
    return np.dtype({
        "names": [f[0] for f in fields],
        "formats": [f[1] for f in fields],
        "offsets": [f[2] for f in fields],
        "itemsize": itemsize,
    })


def _align(n, a):
    return (n + a - 1) // a * a


_U1, _U2, _U4, _U8 = np.uint8, np.uint16, np.uint32, np.uint64

# The C constants the package uses, checked against the dump by name.
CONSTANTS = {
    "DUOFORGE_MAX_CANDIDATES": 784,
    "DUOFORGE_MAX_SLOT_OPTIONS": 32,
    "DUOFORGE_DIGEST_SIZE": 32,
    "DUOFORGE_MAX_ROSTER": 6,
    "DUOFORGE_SIDE_COUNT": 2,
    "DUOFORGE_ACTIVE_PER_SIDE": 2,
    "DUOFORGE_BATCH_NO_CHOICE": 0xFFFF,
    "DUOFORGE_DATA_KIND_CLOSURE": 2,
    "DUOFORGE_CHOICE_TEAM_SELECTION": 1,
    "DUOFORGE_CHOICE_SLOTS": 2,
    "DUOFORGE_BOUNDARY_TEAM_SELECTION": 1,
    "DUOFORGE_BOUNDARY_TURN": 2,
    "DUOFORGE_BOUNDARY_REPLACEMENT": 3,
    "DUOFORGE_BOUNDARY_PIVOT": 4,
    "DUOFORGE_BOUNDARY_TERMINAL": 5,
    "DUOFORGE_RESULT_SIDE_0": 1,
    "DUOFORGE_RESULT_SIDE_1": 2,
    "DUOFORGE_RESULT_TIE": 3,
    "DUOFORGE_SLOT_NONE": 0,
    "DUOFORGE_SLOT_MOVE": 1,
    "DUOFORGE_SLOT_SWITCH": 2,
    "DUOFORGE_SLOT_PASS": 3,
    "DUOFORGE_E_INVALID_ARGUMENT": 2,
    "DUOFORGE_BATCH_MAX_ENVS": 65536,
    "DUOFORGE_BATCH_AUTORESET": 1,
    "DUOFORGE_ROSTER_NONE": 0xFF,
    "DUOFORGE_TARGET_NONE": 0xFF,
    "DUOFORGE_MOVE_SLOT_NONE": 0xFF,
    "DUOFORGE_HP_EXACT": 1,
    "DUOFORGE_HP_PERCENT": 2,
    "DUOFORGE_AILMENT_NONE": 0,
    "DUOFORGE_AILMENT_BURN": 1,
    "DUOFORGE_AILMENT_FREEZE": 2,
    "DUOFORGE_AILMENT_PARALYSIS": 3,
    "DUOFORGE_AILMENT_SLEEP": 4,
    "DUOFORGE_AILMENT_POISON": 5,
    "DUOFORGE_WEATHER_NONE": 0,
    "DUOFORGE_WEATHER_RAIN": 1,
    "DUOFORGE_WEATHER_SUN": 2,
    "DUOFORGE_TERRAIN_NONE": 0,
    "DUOFORGE_TERRAIN_GRASSY": 1,
    "DUOFORGE_LOCATION_UNDETERMINED": 0,
    "DUOFORGE_LOCATION_BENCH": 1,
    "DUOFORGE_LOCATION_ACTIVE": 2,
    "DUOFORGE_LOCATION_NOT_BROUGHT": 3,
}
MAX_CANDIDATES = CONSTANTS["DUOFORGE_MAX_CANDIDATES"]
MAX_SLOT_OPTIONS = CONSTANTS["DUOFORGE_MAX_SLOT_OPTIONS"]
DIGEST_SIZE = CONSTANTS["DUOFORGE_DIGEST_SIZE"]
MAX_ROSTER = CONSTANTS["DUOFORGE_MAX_ROSTER"]
NO_CHOICE = CONSTANTS["DUOFORGE_BATCH_NO_CHOICE"]
DATA_KIND_CLOSURE = CONSTANTS["DUOFORGE_DATA_KIND_CLOSURE"]

# duoforge_context_config: five uint32, then the target-class table pointer.
_TABLE_OFFSET = _align(20, _PTR)
CONTEXT_CONFIG = _struct([
    ("data_kind", _U4, 0),
    ("max_roster", _U4, 4),
    ("brought_count", _U4, 8),
    ("species_count", _U4, 12),
    ("move_count", _U4, 16),
    ("move_target_classes", np.uintp, _TABLE_OFFSET),
], _align(_TABLE_OFFSET + _PTR, max(4, _PTR)))

MOVE_SETUP = _struct([
    ("move_id", _U4, 0),
    ("pp_max", _U4, 4),
], 8)

MEMBER_SETUP = _struct([
    ("species_id", _U4, 0),
    ("hp_max", _U4, 4),
    ("move_count", _U4, 8),
    ("mega_capable", _U4, 12),
    ("moves", (MOVE_SETUP, (4,)), 16),
    ("gender", _U4, 48),
    ("nature", _U4, 52),
    ("stat_points", (_U4, (6,)), 56),
    ("ability", _U4, 80),
    ("item", _U4, 84),
], 88)

SIDE_SETUP = _struct([
    ("member_count", _U4, 0),
    ("members", (MEMBER_SETUP, (6,)), 4),
], 532)

SETUP = _struct([
    ("rng_initstate", _U8, 0),
    ("rng_initseq", _U8, 8),
    ("sides", (SIDE_SETUP, (2,)), 16),
], 1080)

SLOT_COMMAND = _struct([
    ("kind", _U1, 0),
    ("move_slot", _U1, 1),
    ("target", _U1, 2),
    ("mega", _U1, 3),
    ("reserve", _U1, 4),
    ("reserved", (_U1, (3,)), 5),
], 8)

SIDE_CHOICE = _struct([
    ("epoch", _U4, 0),
    ("side", _U1, 4),
    ("kind", _U1, 5),
    ("pick_count", _U1, 6),
    ("picks", (_U1, (6,)), 7),
    ("reserved", (_U1, (3,)), 13),
    ("slots", (SLOT_COMMAND, (2,)), 16),
], 32)

FACTORED_DOMAIN = _struct([
    ("epoch", _U4, 0),
    ("kind", _U1, 4),
    ("slot_count", (_U1, (2,)), 5),
    ("member_count", _U1, 7),
    ("pick_count", _U1, 8),
    ("reserved", (_U1, (3,)), 9),
    ("slots", (SLOT_COMMAND, (2, MAX_SLOT_OPTIONS)), 12),
    ("allowed", (_U4, (MAX_SLOT_OPTIONS,)), 524),
], 652)

FACTORED_CHOICE = _struct([
    ("slot", (_U1, (2,)), 0),
    ("picks", (_U1, (6,)), 2),
], 8)

REQUEST = _struct([
    ("epoch", _U4, 0),
    ("candidate_count", _U4, 4),
    ("boundary_kind", _U1, 8),
    ("player", _U1, 9),
    ("requested", _U1, 10),
    ("slot_mask", _U1, 11),
], 12)

STEP_RESULT = _struct([
    ("epoch", _U4, 0),
    ("kind", _U1, 4),
    ("boundary_kind", _U1, 5),
    ("request_mask", _U1, 6),
    ("reserved", _U1, 7),
], 8)

MEMBER_VIEW = _struct([
    ("species_id", _U2, 0),
    ("hp", _U2, 2),
    ("hp_max", _U2, 4),
    ("move_ids", (_U2, (4,)), 6),
    ("stats", (_U2, (5,)), 14),
    ("pp", (_U1, (4,)), 24),
    ("pp_max", (_U1, (4,)), 28),
    ("stat_points", (_U1, (6,)), 32),
    ("move_count", _U1, 38),
    ("hp_kind", _U1, 39),
    ("hp_flag", _U1, 40),
    ("pp_kind", _U1, 41),
    ("location", _U1, 42),
    ("mega_capable", _U1, 43),
    ("is_mega", _U1, 44),
    ("gender", _U1, 45),
    ("nature", _U1, 46),
    ("ability", _U1, 47),
    ("item", _U1, 48),
    ("item_used", _U1, 49),
    ("status", _U1, 50),
    ("reserved", _U1, 51),
], 52)

POSITION_VIEW = _struct([
    ("stages", (_U1, (7,)), 0),
    ("confused", _U1, 7),
    ("charging", _U1, 8),
    ("locked_slot", _U1, 9),
    ("locked_target", _U1, 10),
    ("acted", _U1, 11),
    ("protect_chain", _U1, 12),
    ("flash_fire", _U1, 13),
    ("protecting", _U1, 14),
    ("reserved", _U1, 15),
], 16)

SIDE_VIEW = _struct([
    ("members", (MEMBER_VIEW, (6,)), 0),
    ("positions", (POSITION_VIEW, (2,)), 312),
    ("member_count", _U1, 344),
    ("occupant", (_U1, (2,)), 345),
    ("mega_used", _U1, 347),
    ("brought_order", (_U1, (6,)), 348),
    ("requested", _U1, 354),
    ("requested_slots", _U1, 355),
    ("reflect_turns", _U1, 356),
    ("light_screen_turns", _U1, 357),
    ("tailwind_turns", _U1, 358),
    ("reserved", _U1, 359),
], 360)

OBSERVATION = _struct([
    ("epoch", _U4, 0),
    ("boundary_kind", _U1, 4),
    ("player", _U1, 5),
    ("requested", _U1, 6),
    ("slot_mask", _U1, 7),
    ("turn", _U2, 8),
    ("weather", _U1, 10),
    ("weather_turns", _U1, 11),
    ("terrain", _U1, 12),
    ("terrain_turns", _U1, 13),
    ("trick_room_turns", _U1, 14),
    ("reserved", _U1, 15),
    ("sides", (SIDE_VIEW, (2,)), 16),
], 736)

# duoforge_batch_config: two uint32, the seed, then the setups pointer.
_SETUPS_OFFSET = _align(16, _PTR)
BATCH_CONFIG = _struct([
    ("env_count", _U4, 0),
    ("worker_count", _U4, 4),
    ("seed", _U8, 8),
    ("setups", np.uintp, _SETUPS_OFFSET),
], _align(_SETUPS_OFFSET + _PTR, 8))

EPISODE = _struct([
    ("env", _U4, 0),
    ("episode", _U4, 4),
    ("steps", _U4, 8),
    ("decisions", _U4, 12),
    ("turns", _U4, 16),
    ("result", _U4, 20),
    ("digest", (_U1, (DIGEST_SIZE,)), 24),
], 56)

# The C struct name of every dtype, as duoforge_layout_dump prints it.
BY_C_NAME = {
    "duoforge_context_config": CONTEXT_CONFIG,
    "duoforge_move_setup": MOVE_SETUP,
    "duoforge_member_setup": MEMBER_SETUP,
    "duoforge_side_setup": SIDE_SETUP,
    "duoforge_battle_setup": SETUP,
    "duoforge_slot_command": SLOT_COMMAND,
    "duoforge_side_choice": SIDE_CHOICE,
    "duoforge_factored_domain": FACTORED_DOMAIN,
    "duoforge_factored_choice": FACTORED_CHOICE,
    "duoforge_request": REQUEST,
    "duoforge_step_result": STEP_RESULT,
    "duoforge_member_view": MEMBER_VIEW,
    "duoforge_position_view": POSITION_VIEW,
    "duoforge_side_view": SIDE_VIEW,
    "duoforge_observation": OBSERVATION,
    "duoforge_batch_config": BATCH_CONFIG,
    "duoforge_batch_episode": EPISODE,
}
