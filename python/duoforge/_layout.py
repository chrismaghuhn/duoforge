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
    "DUOFORGE_MOVE_SLOT_STRUGGLE": 4,
    "DUOFORGE_MOVE_SLOT_RECHARGE": 5,
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
    "DUOFORGE_WEATHER_SAND": 3,
    "DUOFORGE_WEATHER_SNOW": 4,
    "DUOFORGE_TERRAIN_NONE": 0,
    "DUOFORGE_TERRAIN_GRASSY": 1,
    "DUOFORGE_TERRAIN_PSYCHIC": 2,
    "DUOFORGE_POSITION_FLAG_FOLLOW_ME": 1,
    "DUOFORGE_POSITION_FLAG_HELPING_HAND": 2,
    "DUOFORGE_POSITION_FLAG_UNBURDEN": 4,
    "DUOFORGE_LOCATION_UNDETERMINED": 0,
    "DUOFORGE_LOCATION_BENCH": 1,
    "DUOFORGE_LOCATION_ACTIVE": 2,
    "DUOFORGE_LOCATION_NOT_BROUGHT": 3,
    "DUOFORGE_OBSERVATION_EXT_SIZE": 192,
    "DUOFORGE_OBSERVATION_EXT_REVISION": 1,
    "DUOFORGE_DATA_KIND_SYNTHETIC": 1,
    "DUOFORGE_DATA_KIND_TEAM_C": 4,
    "DUOFORGE_DATA_KIND_POOL": 6,
    "DUOFORGE_DATA_TABLE_SPECIES": 1,
    "DUOFORGE_DATA_TABLE_MOVE": 2,
    "DUOFORGE_DATA_TABLE_ITEM": 3,
    "DUOFORGE_DATA_TABLE_ABILITY": 4,
    "DUOFORGE_DATA_TABLE_NATURE": 5,
    "DUOFORGE_DATA_TABLE_COUNT": 5,
    "DUOFORGE_DATA_NONE": 0xFFFFFFFF,
    "DUOFORGE_DATA_MAX_FORME_ABILITIES": 3,
    "DUOFORGE_DATA_MAX_FORME_MOVES": 512,
    "DUOFORGE_GENDER_BIT_MALE": 1,
    "DUOFORGE_GENDER_BIT_FEMALE": 2,
    "DUOFORGE_GENDER_BIT_NONE": 4,
    "DUOFORGE_MOVE_CATEGORY_PHYSICAL": 0,
    "DUOFORGE_MOVE_CATEGORY_SPECIAL": 1,
    "DUOFORGE_MOVE_CATEGORY_STATUS": 2,
    "DUOFORGE_TARGET_CLASS_STATIC_COUNT": 15,
    "DUOFORGE_MOVE_STATIC_FLAG_CONTACT": 1,
    "DUOFORGE_MOVE_STATIC_FLAG_SOUND": 2,
    "DUOFORGE_MOVE_STATIC_FLAG_PUNCH": 4,
    "DUOFORGE_MOVE_STATIC_FLAG_BITE": 8,
    "DUOFORGE_MOVE_STATIC_FLAG_BULLET": 16,
    "DUOFORGE_MOVE_STATIC_FLAG_PULSE": 32,
    "DUOFORGE_MOVE_STATIC_FLAG_SLICING": 64,
    "DUOFORGE_MOVE_STATIC_FLAG_WIND": 128,
    "DUOFORGE_MOVE_STATIC_FLAG_DANCE": 256,
    "DUOFORGE_MOVE_STATIC_FLAG_POWDER": 512,
    "DUOFORGE_MOVE_STATIC_FLAG_POWER_RULE": 1024,
    "DUOFORGE_ITEM_FAMILY_NONE": 0,
    "DUOFORGE_ITEM_FAMILY_TYPE_BOOSTER": 1,
    "DUOFORGE_ITEM_FAMILY_RESIST_BERRY": 2,
    "DUOFORGE_ABILITY_FAMILY_NONE": 0,
    "DUOFORGE_ABILITY_FAMILY_ATE": 1,
    "DUOFORGE_ABILITY_FAMILY_PINCH": 2,
    "DUOFORGE_ABILITY_FAMILY_WEATHER_SETTER": 3,
    "DUOFORGE_ABILITY_FAMILY_TERRAIN_SETTER": 4,
    "DUOFORGE_TYPE_BUG": 0,
    "DUOFORGE_TYPE_DARK": 1,
    "DUOFORGE_TYPE_DRAGON": 2,
    "DUOFORGE_TYPE_ELECTRIC": 3,
    "DUOFORGE_TYPE_FAIRY": 4,
    "DUOFORGE_TYPE_FIGHTING": 5,
    "DUOFORGE_TYPE_FIRE": 6,
    "DUOFORGE_TYPE_FLYING": 7,
    "DUOFORGE_TYPE_GHOST": 8,
    "DUOFORGE_TYPE_GRASS": 9,
    "DUOFORGE_TYPE_GROUND": 10,
    "DUOFORGE_TYPE_ICE": 11,
    "DUOFORGE_TYPE_NORMAL": 12,
    "DUOFORGE_TYPE_POISON": 13,
    "DUOFORGE_TYPE_PSYCHIC": 14,
    "DUOFORGE_TYPE_ROCK": 15,
    "DUOFORGE_TYPE_STEEL": 16,
    "DUOFORGE_TYPE_WATER": 17,
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

# The POOL player-view extension (decision 0018): 192 bytes, alignment 8, all zero under every non-POOL kind.
FIELD_EXT = _struct([
    ("gravity_turns", _U1, 0),
    ("reserved", (_U1, (15,)), 1),
], 16)

POSITION_EXT = _struct([
    ("volatiles", _U4, 0),
    ("ability_now", _U2, 4),
    ("type_now", (_U1, (2,)), 6),
    ("encore_slot", _U1, 8),
    ("disable_slot", _U1, 9),
    ("stockpile", _U1, 10),
    ("perish", _U1, 11),
    ("reserved", (_U1, (4,)), 12),
], 16)

MEMBER_EXT = _struct([
    ("forme", _U2, 0),
    ("item_now", _U1, 2),
    ("reserved", _U1, 3),
], 4)

SIDE_EXT = _struct([
    ("positions", (POSITION_EXT, (2,)), 0),
    ("members", (MEMBER_EXT, (6,)), 32),
    ("aurora_veil_turns", _U1, 56),
    ("stealth_rock", _U1, 57),
    ("spikes", _U1, 58),
    ("toxic_spikes", _U1, 59),
    ("sticky_web", _U1, 60),
    ("guard_flags", _U1, 61),
    ("reserved", (_U1, (2,)), 62),
], 64)

OBSERVATION_EXT = _struct([
    ("revision", _U1, 0),
    ("player", _U1, 1),
    ("reserved0", (_U1, (2,)), 2),
    ("epoch", _U4, 4),
    ("supported", _U8, 8),
    ("field", FIELD_EXT, 16),
    ("sides", (SIDE_EXT, (2,)), 32),
    ("reserved1", (_U1, (32,)), 160),
], 192)

# The static data API (decision 0020): every field a uint32 (priority an int32), no padding.
FORME_INFO = _struct([
    ("dex_num", _U4, 0),
    ("is_mega", _U4, 4),
    ("setup_legal", _U4, 8),
    ("base_species", _U4, 12),
    ("mega_species", _U4, 16),
    ("mega_stone", _U4, 20),
    ("mega_ability", _U4, 24),
    ("mega_supported", _U4, 28),
    ("gender_mask", _U4, 32),
    ("no_ability", _U4, 36),
    ("ability_count", _U4, 40),
    ("abilities", (_U4, (3,)), 44),
    ("move_count", _U4, 56),
], 60)

FORME_STATIC = _struct([
    ("types", (_U4, (2,)), 0),
    ("base_stats", (_U4, (6,)), 8),
    ("weight_hg", _U4, 32),
    ("default_ability", _U4, 36),
    ("is_mega", _U4, 40),
], 44)

MOVE_STATIC = _struct([
    ("type", _U4, 0),
    ("category", _U4, 4),
    ("base_power", _U4, 8),
    ("accuracy", _U4, 12),
    ("pp", _U4, 16),
    ("priority", np.int32, 20),
    ("target_class", _U4, 24),
    ("flags", _U4, 28),
    ("crit_stage", _U4, 32),
    ("drain", (_U4, (2,)), 36),
    ("recoil", (_U4, (2,)), 44),
    ("secondary_chance", _U4, 52),
    ("hits_min", _U4, 56),
    ("hits_max", _U4, 60),
], 64)

ITEM_STATIC = _struct([
    ("family", _U4, 0),
    ("family_type", _U4, 4),
    ("is_mega_stone", _U4, 8),
    ("mega_species", _U4, 12),
], 16)

ABILITY_STATIC = _struct([
    ("family", _U4, 0),
    ("family_param", _U4, 4),
], 8)

NATURE_STATIC = _struct([
    ("raised_stat", _U4, 0),
    ("lowered_stat", _U4, 4),
], 8)

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
    "duoforge_field_ext": FIELD_EXT,
    "duoforge_position_ext": POSITION_EXT,
    "duoforge_member_ext": MEMBER_EXT,
    "duoforge_side_ext": SIDE_EXT,
    "duoforge_observation_ext": OBSERVATION_EXT,
    "duoforge_forme_info": FORME_INFO,
    "duoforge_forme_static": FORME_STATIC,
    "duoforge_move_static": MOVE_STATIC,
    "duoforge_item_static": ITEM_STATIC,
    "duoforge_ability_static": ABILITY_STATIC,
    "duoforge_nature_static": NATURE_STATIC,
    "duoforge_batch_config": BATCH_CONFIG,
    "duoforge_batch_episode": EPISODE,
}
