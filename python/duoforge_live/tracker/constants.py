"""The constants and tables the tracker folds with.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

from duoforge import _layout
from duoforge._state_layout import VALUES as _ENC

from .. import lines
from ..data import trace_to_c

C = _layout.CONSTANTS
EV = trace_to_c.EV
FLAG = trace_to_c.FLAG
_MUST_PRESSURE = _layout.CONSTANTS["DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE"]  # step G53
_LOCKED_MOVE = _layout.CONSTANTS["DUOFORGE_MOVE_STATIC_FLAG_LOCKED_MOVE"]  # view audit 2026-10-10
NOPOS = trace_to_c.NOPOS
ROSTER_NONE = C["DUOFORGE_ROSTER_NONE"]
MOVE_SLOT_NONE = C["DUOFORGE_MOVE_SLOT_NONE"]
TARGET_NONE = C["DUOFORGE_TARGET_NONE"]
TEAM_SELECTION, TURN, REPLACEMENT, PIVOT = (C[f"DUOFORGE_BOUNDARY_{n}"] for n in
                                            ("TEAM_SELECTION", "TURN", "REPLACEMENT", "PIVOT"))
UNDETERMINED, BENCH, ACTIVE, NOT_BROUGHT = (C[f"DUOFORGE_LOCATION_{n}"] for n in
                                            ("UNDETERMINED", "BENCH", "ACTIVE", "NOT_BROUGHT"))
HP_EXACT, HP_PERCENT = C["DUOFORGE_HP_EXACT"], C["DUOFORGE_HP_PERCENT"]
HP_UNKNOWN = C["DUOFORGE_HP_UNKNOWN"]
FLAG_FOLLOW_ME, FLAG_HELPING_HAND, FLAG_UNBURDEN = (C[f"DUOFORGE_POSITION_FLAG_{n}"] for n in
                                                    ("FOLLOW_ME", "HELPING_HAND", "UNBURDEN"))
SPECTATOR = 2  # the converter's viewer of a spectator: no side, so every HP line reads as the public percent
PP_EXACT, PP_DERIVED = C["DUOFORGE_PP_EXACT"], C["DUOFORGE_PP_DERIVED"]
STAGE_NEUTRAL = _ENC["DFI_STAGE_NEUTRAL"]  # stages are stored biased
# The durations a field effect starts with and the held items that lengthen them, the engine's own (#512 D1; the
# durationCallback of data/conditions.ts and data/moves.ts): the setter's item is read when the effect starts.
FIELD_TURNS = _ENC["DFI_FIELD_TURNS_MAX"]  # weather, terrain, Trick Room
FIELD_TURNS_EXTENDED = _ENC["DFI_FIELD_TURNS_EXTENDED_MAX"]  # a weather rock or Terrain Extender held by the setter
TAILWIND_TURNS = _ENC["DFI_TAILWIND_TURNS_MAX"]
SCREEN_TURNS, SCREEN_TURNS_CLAY = _ENC["DFI_SCREEN_TURNS"], _ENC["DFI_SCREEN_TURNS_MAX"]  # the latter with Light Clay
STALL_DURATION, STALL_LEVEL_MAX = _ENC["DFI_STALL_DURATION"], _ENC["DFI_STALL_LEVEL_MAX"]
ALLY_SWITCH_LEVEL_MAX, ALLY_SWITCH_TURNS = _ENC["DFI_ALLY_SWITCH_LEVEL_MAX"], _ENC["DFI_ALLY_SWITCH_TURNS_MAX"]
# A -weather line's name (the protocol's; "Snow" is an older server's Snowscape) -> the item that lengthens it (an ITEM id)
_WEATHER_ROCK = {name: _ENC[f"DFI_WEATHER_ROCK_{w}"] for name, w in
                 (("RainDance", "RAIN"), ("SunnyDay", "SUN"), ("Sandstorm", "SAND"), ("Snowscape", "SNOW"),
                  ("Snow", "SNOW"))}
TERRAIN_EXTENDER, SCREEN_EXTENDER = _ENC["DFI_TERRAIN_EXTENDER"], _ENC["DFI_SCREEN_EXTENDER"]
FREEZE_TURNS = _ENC["DFI_FREEZE_TURNS"]  # a freeze's status counter at its start, one less per [cant] frz
THROAT_CHOP_TURNS = _ENC["DFI_TAIL_THROAT_CHOP_MAX"]  # throatchop's duration, counted down in the residual
ENCORE_TURNS = _ENC["DFI_ENCORE_TURNS"]  # encore's duration; one more when its target has no move left this turn
# the durations the #342 volatiles start with (src/state/battle_internal.h), each counted down in the residual
TAUNT_TURNS = _ENC["DFI_TAUNT_TURNS"]  # one more when its target has been out for a turn and has no move left
DISABLE_TURNS = _ENC["DFI_DISABLE_TURNS"]  # one less when its target has its move ahead or Cursed Body sets it
HEAL_BLOCK_TURNS = _ENC["DFI_HEAL_BLOCK_PSYCHIC_NOISE_TURNS"]  # Psychic Noise's, the one Heal Block of the pool
YAWN_TURNS = _ENC["DFI_TAIL_YAWN_MAX"]
TOXIC_STAGE_MAX = _ENC["DFI_TAIL_TOXIC_STAGE_MAX"]  # where the toxic counter stops
HITS_TAKEN_MAX = _ENC["DFI_TAIL_HITS_TAKEN_MAX"]  # where Rage Fist's count stops
CHARGE_TURNS = 2  # twoturnmove's duration: the charge and the locked turn end in the second residual
EXT_REVISION = C["DUOFORGE_OBSERVATION_EXT_REVISION"]
EXT_THROAT_CHOP = C["DUOFORGE_POSITION_EXT_THROAT_CHOP"]
EXT_CURSE = C["DUOFORGE_POSITION_EXT_CURSE"]
EXT2_TRAP_ELAPSED = tuple(C[f"DUOFORGE_POSITION_EXT2_TRAP_ELAPSED_BIT{k}"] for k in range(3))  # the count's bits, low to high
TRAP_ELAPSED_MAX = 5  # DFI_TAIL_TRAP_ELAPSED_MAX: residual phases a partial trap can have been through (d <= 6, the last ends it)
ITEM_NOW_NONE = C["DUOFORGE_ITEM_NOW_NONE"]  # duoforge_member_ext.item_now: the member holds nothing
# The view-extension fields (OBSERVATION_EXT, decision 0018) of each feature the tracker folds: what observation_ext
# writes, and all that restrict_ext keeps of DuoForge's record for a comparison. ("bit", B): bit B of a position's
# volatiles; ("side_bit", (F, B)): bit B of side field F; ("position" | "member" | "side", F): field F of every
# position, member or side record. The base-value
# features show in the base observation alone (lines.BASE_FOLDS).
# volatiles2's ATTRACT_SOURCE bits (step G87): the source's flat position (0-3) at bit _ATTRACT_SOURCE_SHIFT
_ATTRACT_SOURCE_BITS = C["DUOFORGE_POSITION_EXT2_ATTRACT_SOURCE_LO"] | C["DUOFORGE_POSITION_EXT2_ATTRACT_SOURCE_HI"]
_ATTRACT_SOURCE_SHIFT = C["DUOFORGE_POSITION_EXT2_ATTRACT_SOURCE_LO"].bit_length() - 1
EXT_FIELDS = {
    "WEATHER_SAND": (), "WEATHER_SNOW": (), "AILMENT_TOX": (), "TERRAIN_ELECTRIC": (), "TERRAIN_MISTY": (),
    "THROAT_CHOP": (("bit", EXT_THROAT_CHOP),),
    "MUST_RECHARGE": (("bit", C["DUOFORGE_POSITION_EXT_MUST_RECHARGE"]),),
    "TOXIC_SPIKES": (("side", "toxic_spikes"),),
    "STEALTH_ROCK": (("side", "stealth_rock"),),
    "SPIKES": (("side", "spikes"),),
    "STICKY_WEB": (("side", "sticky_web"),),
    "TAUNT": (("bit", C["DUOFORGE_POSITION_EXT_TAUNT"]),),
    "YAWN": (("bit", C["DUOFORGE_POSITION_EXT_YAWN"]),),
    "LEECH_SEED": (("bit", C["DUOFORGE_POSITION_EXT_LEECH_SEED"]),),
    "DISABLE": (("position", "disable_slot"),),
    "IMPRISON": (("bit", C["DUOFORGE_POSITION_EXT_IMPRISON"]),),
    "GLAIVE_RUSH": (("bit", C["DUOFORGE_POSITION_EXT_GLAIVE_RUSH"]),),
    "RAGE_POWDER": (("bit", C["DUOFORGE_POSITION_EXT_RAGE_POWDER"]),),
    "HEAL_BLOCK": (("bit", C["DUOFORGE_POSITION_EXT_HEAL_BLOCK"]),),
    "WIDE_GUARD": (("side_bit", ("guard_flags", C["DUOFORGE_SIDE_GUARD_WIDE_GUARD"])),),
    "TYPE_CHANGE": (("bit", C["DUOFORGE_POSITION_EXT_TYPE_CHANGED"]), ("position", "type_now")),
    "AURORA_VEIL": (("side", "aurora_veil_turns"),),
    "PERISH": (("position", "perish"),),
    "ENCORE": (("position", "encore_slot"),),
    "ABILITY_CHANGE": (("position", "ability_now"),),
    "ITEM_CHANGE": (("member", "item_now"),),
    # Attract (step G71, decision 0034): the presence bit of the infatuated position; its source is the record's byte
    "RESERVE_VOLATILES": (("bit", C["DUOFORGE_POSITION_EXT_ATTRACT"]),),
    # Ghost Curse (step G84b, decision 0063): the holder's CURSED bit, the view bit of the Curse volatile
    "CURSE": (("bit", EXT_CURSE),),
    "SPEED_SWAPPED": (("bit", C["DUOFORGE_POSITION_EXT_SPEED_SWAPPED"]),),  # K3 (decision 0015 5de): the presence bit, no values
    "HEALING_WISH": (("bit", C["DUOFORGE_POSITION_EXT_HEALING_WISH"]),),  # G82: encoder 6's reserve volatile bit 22
    "PARTIAL_TRAP": (("bit", C["DUOFORGE_POSITION_EXT_PARTIAL_TRAP"]),),
    "TRAP_ELAPSED": (("v2bits", sum(EXT2_TRAP_ELAPSED)),),  # POSITION_EXT2 (volatiles2), a record field of its own
    # Attract's source position (step G87, decision 0080): volatiles2 bits 12-13, the source's flat position
    "ATTRACT_SOURCE": (("v2bits", _ATTRACT_SOURCE_BITS),),
    # Gravity (step K4, #475, decision 0015 5dl): the field view's gravity_turns, folded from FIELD_START / FIELD_END detail 6
    "GRAVITY": (("global", "gravity_turns"),),
}
# The presence bits of a position's volatiles: _Position attribute -> DUOFORGE_POSITION_EXT_* bit.
_PRESENCE_BITS = (("throat_chop", EXT_THROAT_CHOP), ("must_recharge", C["DUOFORGE_POSITION_EXT_MUST_RECHARGE"]),
                  ("taunt", C["DUOFORGE_POSITION_EXT_TAUNT"]), ("yawn", C["DUOFORGE_POSITION_EXT_YAWN"]),
                  ("leech_source", C["DUOFORGE_POSITION_EXT_LEECH_SEED"]),
                  ("imprison", C["DUOFORGE_POSITION_EXT_IMPRISON"]), ("glaive_rush", C["DUOFORGE_POSITION_EXT_GLAIVE_RUSH"]),
                  ("rage_powder", C["DUOFORGE_POSITION_EXT_RAGE_POWDER"]), ("heal_block", C["DUOFORGE_POSITION_EXT_HEAL_BLOCK"]),
                   ("attract", C["DUOFORGE_POSITION_EXT_ATTRACT"]), ("cursed", EXT_CURSE),
                   ("wish", C["DUOFORGE_POSITION_EXT_HEALING_WISH"]),
                   ("trap", C["DUOFORGE_POSITION_EXT_PARTIAL_TRAP"]),
                   ("speed_swapped", C["DUOFORGE_POSITION_EXT_SPEED_SWAPPED"]))
# DUOFORGE_FIELD_* of a terrain's FIELD_START event -> DUOFORGE_TERRAIN_* of the observation
_TERRAIN = {1: C["DUOFORGE_TERRAIN_GRASSY"], trace_to_c.FIELD_PSYCHIC_TERRAIN: C["DUOFORGE_TERRAIN_PSYCHIC"],
            trace_to_c.FIELD_ELECTRIC_TERRAIN: C["DUOFORGE_TERRAIN_ELECTRIC"],
            trace_to_c.FIELD_MISTY_TERRAIN: C["DUOFORGE_TERRAIN_MISTY"]}
# The folded _Position fields that Baton Pass gives the entering member (src/combat/turn.c dfi_pass_give: Throat Chop's
# and Perish Song's tail counters among them); Encore, the recharge, a changed type or ability stay with the leaver.
_PASSED = ("throat_chop", "perish", "taunt", "heal_block", "leech_source", "cursed",
           # the partial trap has no noCopy in the pin (pokemon.ts copyVolatileFrom): dfi_pass_give copies its turns, source, move,
           # band and elapsed count (G90), so the receiver is trapped by the same source with the same count
           "trap", "trap_source", "trap_move", "trap_band", "trap_elapsed")  # with their counts (dfi_pass_give copies the turns
# and Leech Seed's source slot: the seed has no noCopy, decision 0047; the Ghost Curse's flag too, step G84b: turn.c's copy keeps CURSED)
# DUOFORGE_SIDE_* of a SIDE_START or SIDE_END event (tailwind 1, reflect 2, light screen 3, Aurora Veil 4) -> the index
# of the side's turns in Tracker._conditions
_SIDE_CONDITION = {1: 2, 2: 0, 3: 1, 4: 3}
# The entry hazards of a SIDE_START or SIDE_END event (DUOFORGE_SIDE_STEALTH_ROCK 5 to _STICKY_WEB 8, step G37): the
# duoforge_side_ext field and its most layers
_HAZARD = {5: ("stealth_rock", 1), 6: ("spikes", 3), 7: ("toxic_spikes", 2), 8: ("sticky_web", 1)}
STATUS = {"brn": 1, "frz": 2, "par": 3, "slp": 4, "psn": 5, "tox": 6}  # DUOFORGE_AILMENT_*
# Why a position must switch (the encoding's switch_flag, DFI_SWITCH_*): the tracker keeps the reason, the views its presence
SWITCH_MOVE, SWITCH_EMERGENCY_EXIT, SWITCH_FAINTED = (_ENC[f"DFI_SWITCH_{n}"] for n in ("MOVE", "EMERGENCY_EXIT", "FAINTED"))
# The moves whose cost to their own user is directDamage, a plain -damage line of the user with no [from] (src/combat/turn.c,
# dfi_deal with DFI_DMG_DIRECT: Substitute, Clangorous Soul, Belly Drum): it sets no hurtThisTurn (Tracker._hurt).
DIRECT_COST_MOVES = ("SUBSTITUTE", "CLANGOROUSSOUL", "BELLYDRUM", "CURSE")  # Ghost Curse: dfi_deal DFI_DMG_DIRECT (G84b)
# The self-switch moves and the reason they flag: a damaging one when it hit a target, its user stands and a reserve can
# come in (src/combat/turn.c, selfSwitch of a damaging move); Baton Pass and Revival Blessing when they do not fail.
_HIT_PIVOTS = {"UTURN": _ENC["DFI_SWITCH_UTURN"], "VOLTSWITCH": _ENC["DFI_SWITCH_VOLT_SWITCH"],
               "FLIPTURN": _ENC["DFI_SWITCH_FLIP_TURN"]}
_MOVE_PIVOTS = {"BATONPASS": _ENC["DFI_SWITCH_BATON_PASS"], "REVIVALBLESSING": _ENC["DFI_SWITCH_REVIVE_BLESSING"]}
REVEALED_ITEM_CONSUMED, REVEALED_MEGA = _ENC["DFI_REVEALED_ITEM_CONSUMED"], _ENC["DFI_REVEALED_MEGA"]

ROOM_LINES = lines.ROOM_LINES
_kind = lines.line_kind  # lines of the room, not of the battle: nobody folds them
# Lines that end or restart the battle session: a reconnect replays the whole log after |init| (and shows a
# choice already sent as |sentchoice|), the others end the session. The tracker cannot fold them correctly.
SESSION_LINES = {"init", "sentchoice", "deinit", "noinit", "expire", "bigerror"}
