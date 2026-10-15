"""The protocol of one battle room folded into DuoForge's observation.

A Tracker follows what one player receives (spec section 6) and builds, at
each decision point, the OBSERVATION record DuoForge would show that player
(decision 0007). It implements no battle rule: every battle line goes through
the converter's own parser (trace_to_c.step_events, which raises on a line it
does not know), and the events are folded into the fields the observation
reads. The test duoforge.python.live proves the result equal to DuoForge's
observation, byte for byte, at every request of every committed closure
battle; the field sources are in the plan's Task 5 table.

Decision points: at the pin a step's update comes before its requests
(Battle.sendUpdates), so a |request| with a new rqid is a decision point over
the battle lines received since the previous one. At team preview it waits
for the |showteam| lines of both sides. An updated request (update: true)
comes after Showdown refused a choice the request did not rule out (a switch
of a hidden-trapped last active: Side.emitChoiceError, sim/side.ts:527-534):
the current move request again, under a new rqid, with what the refusal
revealed. No battle line comes between, so it is a new request epoch of the
same decision point: the state stays, the options follow the update.

The public record (public_parts, record.py; M12 option A): the tracker also
folds the public facts the canonical public record holds and its views do not
(entry activation ids, move actions since entry, the opponent's knowledge of
each own member, revealed facts, a freeze's turns, the foe's leads), and
record.assemble serialises them. duoforge.python.live proves the record equal
to the engine's at every decision point of every committed closure battle, or
refused with the engine's status and cause mask.
"""
import collections
import json

import numpy as np

from duoforge import _layout
from duoforge._state_layout import VALUES as _ENC

from . import lines, options, teams
from .data import trace_to_c

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
HP_UNKNOWN = 3  # DUOFORGE_HP_UNKNOWN (include/duoforge/duoforge.h)
FLAG_FOLLOW_ME, FLAG_HELPING_HAND, FLAG_UNBURDEN = (C[f"DUOFORGE_POSITION_FLAG_{n}"] for n in
                                                    ("FOLLOW_ME", "HELPING_HAND", "UNBURDEN"))
SPECTATOR = 2  # the converter's viewer of a spectator: no side, so every HP line reads as the public percent
# The items that lengthen a weather from 5 to 8 turns (data/items.ts, data/conditions.ts durationCallback).
_WEATHER_ITEM = {"RainDance": "Damp Rock", "SunnyDay": "Heat Rock", "Sandstorm": "Smooth Rock", "Snowscape": "Icy Rock",
                 "Snow": "Icy Rock"}
PP_EXACT, PP_DERIVED = 1, 2  # DUOFORGE_PP_EXACT, DUOFORGE_PP_DERIVED
STAGE_NEUTRAL = 6  # DFI_STAGE_NEUTRAL: stages are stored biased (src/state/battle_internal.h)
FIELD_TURNS = 5  # weather, terrain, Trick Room
FIELD_TURNS_EXTENDED = 8  # DFI_FIELD_TURNS_MAX: a weather rock or Terrain Extender held by the setter
TAILWIND_TURNS, SCREEN_TURNS, SCREEN_TURNS_CLAY = 4, 5, 8  # DFI_TAILWIND_TURNS_MAX, 5, DFI_SCREEN_TURNS_MAX
STALL_DURATION, STALL_LEVEL_MAX = 2, 6  # DFI_STALL_DURATION (src/combat/turn.c), DFI_STALL_LEVEL_MAX
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



def _condition(text):
    """(hp, hp_max or None, status) of a request's condition: "155/181 par", "0 fnt"."""
    parts = text.split(" ")
    if parts[0] == "0":
        return 0, None, 0
    hp, hp_max = parts[0].split("/")
    status = STATUS[parts[1]] if len(parts) > 1 else 0
    return int(hp), int(hp_max), status


class _Position:
    def __init__(self):
        self.occupant = ROSTER_NONE
        self.flag = 0  # Showdown's switchFlag: asked to switch at the next switch request (its reason, DFI_SWITCH_*)
        self.fainted = False
        self.activation = 0  # the activation id of the occupant's entry (the public record; switches counted in order)
        self.move_actions = 0  # the occupant's move actions since its entry (the public record, _move_action)
        self.confused_action = False  # a confusion -activate began the occupant's current action
        # The position's MOVE action of this turn is still in the queue: every standing occupant queues one at the turn's
        # start unless it switches (a switch-out cancels its actions, sim/battle-actions.ts switchIn); it leaves the queue
        # when it runs (its [move], [cant] or confusion line). A faint does not remove it (the action then does nothing).
        self.move_queued = False
        # Healing Wish's slot condition (G82, decision 0045): the slot's, not the occupant's, so a faint or an entry keeps
        # it (reset leaves it); the heal of an entrant ends it (dfi_wish_heal). The record's position flag bit 0 and the
        # view's HEALING_WISH bit.
        self.wish = 0
        self.reset()

    def reset(self):
        self.stages = [STAGE_NEUTRAL] * 7
        # Speed Swap (step K3, decision 0015 5de): presence only; it ends with the occupant (a switch-out or a faint) and at a
        # forme change or Mega Evolution of the position (both rebuild the stored stats), never with the turn.
        self.speed_swapped = 0
        self.confused = 0
        self.charge = 0
        self.locked_slot = MOVE_SLOT_NONE
        self.locked_target = TARGET_NONE
        self.acted = 0
        self.chain = 0
        self.stall = 0
        self.flash_fire = 0
        self.protecting = 0
        self.choice_slot = MOVE_SLOT_NONE  # the move slot a Choice item locks (TEAM_C and POOL)
        # The POOL view extension (decision 0018), all ended with the occupant (a switch or a faint):
        self.throat_chop = 0  # Throat Chop's turns left (the view shows its presence, the record its count)
        self.must_recharge = 0  # a recharge move hit: the next action is cant|recharge (presence only)
        self.taunt = 0  # Taunt's turns left: the view shows its presence, the record its count (taunt_turns)
        self.yawn = 0  # Yawn's turns left until the sleep: the view shows its presence, the record its count
        self.leech_source = 0  # Leech Seed: the flat position + 1 of the seed's source (the record's leech_seed_source; the
        # drain's heal goes to whoever stands there), 0: none; the volatile ends with the occupant, Baton Pass copies it
        self.imprison = 0  # the occupant used Imprison (presence only, until it leaves)
        self.glaive_rush = 0  # Glaive Rush's drawback is up until the occupant's next action (presence only)
        self.rage_powder = 0  # Rage Powder draws the foes' single-target moves this turn (presence only)
        self.heal_block = 0  # Heal Block's turns left: the view shows its presence, the record its count
        # Attract (step G71): the member code of the holder that infatuates the occupant, 1 + side * DUOFORGE_MAX_ROSTER + roster
        # index (the record's attract_source byte of this position; 0: not infatuated). Ended with the occupant, as the engine's
        # clearing of its byte (dfi_tail_clear_occupant, no line); its visible and silent ends are folded in _fold_event and
        # _silent_attract_end.
        self.attract = 0
        self.attract_from = 0  # the source's flat position while infatuated (POSITION_EXT2 ATTRACT_SOURCE, step G87)
        # The partial trap (step G90, decision 0060), the engine's four tail fields without the drawn turns, which no line shows:
        self.trap = 0  # the volatile is up (the engine's trap_turns is not zero)
        self.trap_source = 0  # the trapper's flat position + 1; 0 once it left the field (the trap then ends at the residual)
        self.trap_move = 0  # the trapping move + 1
        self.trap_band = 0  # the trapper held a Binding Band at the start
        self.trap_elapsed = 0  # TRAP_ELAPSED: residual damage lines since the start (0..5), zero without the trap
        self.type_now = (0, 0)  # the types (id + 1, 0: none) a move set until the occupant leaves (Soak, Double Shock)
        # the record's type2 of the occupant (tail rev 4): Double Shock's remaining type + 1, 0 after Soak; a Mega
        # Evolution ends type_now (the soak_type) and keeps it, as dfi_run_mega does; it ends with the occupant
        self.type2 = 0
        self.disable_turns = 0  # Disable's turns left (the record; the view shows only disable_slot)
        self.cursed = 0  # the Ghost Curse's volatile is up (presence only; it ends with the occupant, step G84b)
        self.encore_turns = 0  # Encore's turns left (the record)
        self.hits_taken = 0  # damaging hits of another Pokemon's move since the entry (the record; Rage Fist)
        self.raised = 0  # a stat of the occupant rose this turn (the record's position flag; Alluring Voice)
        self.lowered = 0  # a stat of the occupant fell this turn (the record's position flag LOWERED; Lash Out, G88)
        self.hurt = 0  # a spread damage left the occupant standing this turn (the record's position flag HURT; Assurance)
        # Ally Switch's volatile (step G80, decision 0044): the level (counter 3^level) and the turns left, 0 = none. It moves
        # with the occupant on a swap (the position object moves) and ends with it (reset).
        self.ally_level = 0
        self.ally_turns = 0
        self.newly_switched = 0  # the occupant came in this turn (the record's flag under the TEAM_C and POOL kinds)
        self.turn_done = True  # no move of the occupant is left this turn (it moved, could not, or came in or fainted)
        self.unburden_unseen = False  # Knock Off hit an Unburden holder and no -enditem followed (record.py refuses)
        # The POOL record's move_result (tail rev 4): the result of the occupant's move action this turn and last turn,
        # each DFI_MOVE_RESULT_* with its unclassified bit, as the library classifies the action's events
        # (Tracker._end_action); None where the library cannot tell it from the events (record.py refuses then).
        self.result_now = 0
        self.result_last = 0
        self.perish = 0  # the Perish count the game showed last, 3 to 1 (0: none)
        self.last_slot = 0  # the move slot + 1 of the occupant's last move line (5: Struggle; None: not on its sheet)
        self.encore_slot = 0  # the move slot + 1 that Encore forces (0: not encored)
        self.disable_slot = 0  # the move slot + 1 that Disable bars (0: none)
        self.ability_now = 0  # the ability + 1 that Trace or Skill Swap gave the occupant (0: its own)
        self.flags = 0  # DUOFORGE_POSITION_FLAG_* (TEAM_C and POOL): Follow Me, Helping Hand, Unburden
        self.guard_undo = None  # (chain, stall) before a Wide or Quick Guard, until it is known to have run
        self.last_move = None  # the move id of pokemon.moveUsed: the occupant's own last move line, none after leaving


# Ally Switch's swap of two positions of one side (step G80, decision 0044 section 10; src/combat/turn.c dfi_swap_position_state).
# The engine exchanges whole slot and tail records and puts back the slot's own fields; the tracker mirrors that as an explicit
# list, so a field added to _Position has to be put on one of the two lists (AllySwitchStateTest). Everything in _SWAP_MOVES
# belongs to the Pokemon and goes with it:
#   - the slot record (dfi_active_slot): occupant, activation, stages, flags (protecting, flash_fire, flags, choice_slot,
#     newly_switched), stall (chain, stall), confused, charge, locked_slot (locked_move), move_actions, flag (switch_flag);
#   - the tail position (dfi_tail_pos), every volatile: substitute and the other tail fields the tracker does not fold are
#     features that stop it at their lines, the folded ones are throat_chop, must_recharge, taunt, yawn, imprison, glaive_rush,
#     rage_powder (the Follow Me flag), heal_block, attract and attract_from (the position's attract_source byte, see below),
#     trap, trap_source, trap_move, trap_band and trap_elapsed (the partial trap), type_now and type2 (Soak and Double Shock,
#     the roster member's soak_type and type2, which the record keys by occupant), disable_slot and disable_turns, encore_slot
#     and encore_turns, cursed, perish, hits_taken, last_slot and last_move, result_now and result_last (move_result),
#     ability_now (the occupant's), ally_level and ally_turns (the Ally Switch counter);
#   - the position flags that ride on the Pokemon: STATS_RAISED (raised), LOWERED (lowered), HURT (hurt), CURSED (cursed);
#     DRAGON_CHEER and DESTINY_BOND are features whose lines stop the tracker, so they are never up here;
#   - the tracker's own scratch of the occupant's action and turn (confused_action, acted, move_queued, turn_done,
#     guard_undo, unburden_unseen, fainted), which the engine keeps in the queue records and the run (they follow the Pokemon).
_SWAP_MOVES = (
    "occupant", "activation", "stages", "protecting", "flash_fire", "flags", "choice_slot", "newly_switched", "chain", "stall",
    "confused", "charge", "locked_slot", "move_actions", "flag", "speed_swapped",
    "throat_chop", "must_recharge", "taunt", "yawn", "imprison", "glaive_rush", "rage_powder", "heal_block", "attract",
    "attract_from", "trap", "trap_source", "trap_move", "trap_band", "trap_elapsed", "type_now", "type2", "disable_slot",
    "disable_turns", "encore_slot", "encore_turns", "cursed", "perish", "hits_taken", "last_slot", "last_move", "result_now",
    "result_last", "ability_now", "ally_level", "ally_turns", "raised", "lowered", "hurt",
    "confused_action", "acted", "move_queued", "turn_done", "guard_undo", "unburden_unseen", "fainted")
# What stays at its position (the slot's, not the Pokemon's): leech_seed_source (the seed's sourceSlot is a slot, sim/pokemon.ts:
# 2002: the drain goes to whoever stands there), Healing Wish's bit 0 (the slot condition; a swap onto a pending one is refused
# before it gets here) and locked_target (a slot location in the pin). Requested slots and sealed commands are not _Position
# fields: they belong to the request of the slot and the tracker keeps them by slot.
_SWAP_SLOT = ("leech_source", "wish", "locked_target")


class _Member:
    def __init__(self, sheet, data):
        self.sheet = sheet
        self.ability = sheet["ability"]
        self.uses = [0] * len(sheet["moves"])
        self.pp_max = [data.pp_max(m) for m in sheet["moves"]]
        self.mega_capable = data.mega_capable(sheet["species"], sheet["item"])
        self.is_mega = 0
        self.item_used = 0
        self.item_now = 0  # the POOL view extension: 0 as the sheet, an item + 1 a move gave it, ITEM_NOW_NONE taken
        # What the opponent knows of the member (the public record's knowledge): seen in battle, its last HP display, the
        # revealed facts (DFI_REVEALED_*); the moves it used are `uses`. A foe member's from its public lines; an own
        # member's from the own lines, its HP display from the library (duoforge.view.hp_display of the exact HP).
        self.seen = False
        self.hp_percent = 0
        self.hp_flag = 0
        self.revealed = 0
        self.status = 0
        # A freeze's turns (the record's status counter): 3 when it starts, one less at each [cant] frz (src/combat/turn.c:
        # the counter is drawn by nobody; the thaw chance is). Folded for both sides from the public lines.
        self.freeze_turns = 0
        self.item_consumed = 0  # its item was used up (the record; a taken item is not), until it gets one
        self.toxic = 0  # badly poisoned, from the status lines of either side (the toxic stage counts only then)
        self.toxic_stage = 0  # the toxic counter (the POOL record): 0 at the status and at an entry, +1 per poison tick
        # Decision 0066 (visible sleep): the cant lines printed since this sleep started (the POOL record's member byte, 0..2): +1 at
        # each cant|X|slp, 0 at the sleep's start and at its end (a cure, a faint, a Wish heal, a revival)
        self.sleep_cant = 0
        # The own side, from the requests.
        self.hp = 0
        self.hp_max = 0
        self.stats = [0] * 5


class SheetContradiction(Exception):
    """A line that contradicts the foe's sheet (only with Tracker.check_foe_sheet, decision 0081): the sheet was drawn,
    not shown (reason: the counter's name)."""

    def __init__(self, reason, member=None):
        super().__init__(reason)
        self.reason = reason
        self.member = member  # the roster index of the foe member whose drawn set the line contradicts


class Tracker:
    """One battle room as one player sees it. feed() every message of the room in order, accepted() every
    own choice Showdown took; at a decision point (ready) observation() and domain() give DuoForge's view."""

    # Class defaults: the tests build a tracker with __new__ and set only what they use (step G80 attributes below).
    _party = None
    _ally_move = None
    _as_pending = None
    # A particle of closed team sheets (decision 0081) folds a drawn foe sheet: it raises SheetContradiction where a line
    # contradicts that sheet and the open-sheet fold would go on. Off for every open-sheet tracker.
    check_foe_sheet = False

    def __init__(self, data, own_text):
        self.data = data
        self.side = None
        self.own_sheets = data.team(own_text)
        self.foe_sets = None
        self.request = None
        self.epoch = 0
        self.ended = False
        self._rqids = set()
        self._lines = []  # the battle lines since the previous decision point
        self._step_lines = []  # those of the current decision point
        self._sheets_seen = set()
        self._own_members = [_Member(s, data) for s in self.own_sheets]
        self._foe_members = None  # from the foe's |showteam|
        self._packed = [None, None]  # the |showteam| payload per side
        self._teamsize = [None, None]  # brought per side (|teamsize|)
        self._names = [{}, {}]  # protocol name -> roster index, per side
        self._positions = [[_Position(), _Position()], [_Position(), _Position()]]
        self._turn = 0
        self._weather = self._weather_turns = 0
        self._field_turns_next = FIELD_TURNS  # set per line by _extended_field
        self._terrain = self._terrain_turns = 0
        self._trick_room = 0
        self._conditions = [[0, 0, 0, 0], [0, 0, 0, 0]]  # reflect, light screen, tailwind, Aurora Veil turns per side
        self._hazards = [collections.Counter(), collections.Counter()]  # entry hazard layers per side, by ext field
        self._mega_used = [0, 0]
        self._next_activation = 1  # the next entry's activation id (the public record)
        self._after_upkeep = False  # the turn's residual ended (|upkeep|) and the next turn has not begun
        self._action = None  # the move action whose events are being collected (_segment)
        # the position whose Mental Herb was just used: the -end lines right after its -enditem are the herb's, not the
        # residual's (dfi_mental_herb ends taunt, encore, disable and heal block in a row, with no cause of their own)
        self._herb_end = None
        # The library data kind of the public record (record.py): None for the tables' kind; a DEV kind of the same tables
        # when the game runs under it (the context's fingerprint is in the record)
        self.record_kind = None
        self._foe_leads = [ROSTER_NONE, ROSTER_NONE]  # the foe's members at its two positions when the battle started
        self._picks = None
        # The own side.pokemon order (the POOL record's party_order): the picks, then every switch-in swaps the incoming
        # member's entry with the position's (sim/battle-actions.ts switchIn)
        self._party = None
        self._accepted = None  # the own choice accepted at the last TURN decision point (it queued the moves)
        self._accepted_commands = None  # its options per position (accepted)
        self._last_move = None  # (position, move id, target) of the last MOVE event
        self._as_pending = None  # the position of the last Ally Switch move line, until its outcome line (step G80)
        self._parting_shot = data.tables["MOVE"]["PARTINGSHOT"]
        self._feint = data.tables["MOVE"].get("FEINT", -1)
        self._baton_pass = data.tables["MOVE"].get("BATONPASS", -1)  # its receiver takes the leaver's copy (G74)
        # the moves of the engine's partial trap (G90); a closure table has none
        self._trap_moves = {data.tables["MOVE"][trace_to_c.key(name)] for name in lines.PARTIAL_TRAP_MOVES
                            if trace_to_c.key(name) in data.tables["MOVE"]}
        self._phantom_force = data.tables["MOVE"].get("PHANTOMFORCE", -1)  # breaks a Protect as Feint does (G58)
        self._turn_scoped = set()  # single-turn features of decision 0018 seen since the turn began (lines.TURN_SCOPED)
        self._guards = set()  # (Wide or Quick Guard feature, side) seen this turn: what a Feint breaks (step G28)
        self._rb_pending = {}  # side -> its Revival Blessing user's position until its revive (step G52, trace_to_c)
        self._spectator = False  # the own side folded like the foe's, from the public lines (duoforge_replay)
        self.turn_scoped_seen = collections.Counter()  # single-turn feature lines seen, by feature (counters)
        tables = data.tables
        self._choice_items = {tables["ITEM"][k.upper()] + 1 for k in lines.CHOICE_ITEMS if k.upper() in tables["ITEM"]}
        self._unburden = tables["ABILITY"]["UNBURDEN"] + 1 if "UNBURDEN" in tables["ABILITY"] else None
        self._pressure = tables["ABILITY"]["PRESSURE"] + 1 if "PRESSURE" in tables["ABILITY"] else None
        self._follow_me = tables["MOVE"].get("FOLLOWME")
        self._rage_powder = tables["MOVE"].get("RAGEPOWDER")
        self._wide_guard = tables["MOVE"].get("WIDEGUARD")
        self._struggle = tables["MOVE"].get("STRUGGLE")
        self._throat_chop_id = tables["MOVE"].get("THROATCHOP")  # a bounced sound move's stop (issue 570, _bounce_cant)
        self._attract = tables["MOVE"].get("ATTRACT")  # the check before an infatuated occupant's move (step G71)
        self._soak = tables["MOVE"].get("SOAK")
        self._symbiosis = tables["ABILITY"]["SYMBIOSIS"] + 1 if "SYMBIOSIS" in tables["ABILITY"] else None
        # Protect and Detect both show "-singleturn|POKEMON|Protect"; a failed one resets the stall counter
        self._stall_moves = {tables["MOVE"][k] for k in ("PROTECT", "DETECT") if k in tables["MOVE"]}
        self._guard_moves = {tables["MOVE"][k] for k in ("WIDEGUARD", "QUICKGUARD") if k in tables["MOVE"]}
        self._helping_hand = tables["MOVE"].get("HELPINGHAND")
        self._knock_off = tables["MOVE"].get("KNOCKOFF")
        self._leech_seed = tables["MOVE"].get("LEECHSEED")
        self._healing_wish = tables["MOVE"].get("HEALINGWISH")
        # the moves whose cost to their own user is directDamage, not spreadDamage (G88: no hurtThisTurn; dfi_deal_ex's
        # callers with spread false): the plain -damage of DIRECT_COST_MOVES; Struggle's recoil is the other one
        self._direct_costs = {tables["MOVE"].get(k) for k in DIRECT_COST_MOVES} - {None}
        self._eject_button = tables["ITEM"].get("EJECTBUTTON")
        self._mental_herb = tables["ITEM"].get("MENTALHERB")
        self._hit_pivots = {tables["MOVE"][k]: v for k, v in _HIT_PIVOTS.items() if k in tables["MOVE"]}
        self._move_pivots = {tables["MOVE"][k]: v for k, v in _MOVE_PIVOTS.items() if k in tables["MOVE"]}
        self._ally_move = tables["MOVE"].get("ALLYSWITCH")  # step G80

    # ------------------------------------------------------------------ input
    def feed(self, lines):
        for line in lines:
            kind = _kind(line)
            if line == "|":
                self._end_action()  # the blank line before the residual (and before the turn's moves): an action ends
            if kind is None or kind in ROOM_LINES:
                continue
            if kind in SESSION_LINES:
                if kind == "init" and self.epoch == 0 and not self._lines and self._foe_members is None:
                    continue  # the room's first line
                raise ValueError(f"the battle session restarted or ended ({line!r}): the tracker cannot follow")
            if kind == "teamsize":
                self._teamsize[int(line.split("|")[2][1]) - 1] = int(line.split("|")[3])
            if kind == "request":
                self._on_request(json.loads(line[len("|request|"):]))
            elif kind == "showteam":
                self._on_showteam(line)
            else:
                self._battle_line(line)

    def _set_boost(self, parts):
        """Belly Drum's (step G86) and Anger Point's (step G77) -setboost: the line shows the Attack stage it leaves; the
        engine's event is the BOOST of the change (dfi_boost: Belly Drum with cause MOVE and the move's id, Anger Point
        with cause ABILITY and the ability's id + 1), which the tracker folds as any boost. The converter computes the
        change from the trace state (trace_to_c); the tracker has the stage itself. A change that is not positive is the
        converter's refusal setboost-change (at +6 before, Anger Point's pin prints no line at all)."""
        flat = trace_to_c.ev_pos(parts[2])
        stat = trace_to_c.EV_STATS.index(parts[3])
        change = STAGE_NEUTRAL + int(parts[4]) - self._at(flat).stages[stat]
        if change <= 0:
            raise lines.Stop("converter:setboost-change")
        if parts[5:] == ["[from] ability: Anger Point"]:
            cause, id2 = trace_to_c.CAUSE["ABILITY"], self.data.tables["ABILITY"]["ANGERPOINT"] + 1
        else:
            cause, id2 = trace_to_c.CAUSE["MOVE"], self.data.tables["MOVE"]["BELLYDRUM"]
        self._event(trace_to_c.ev_tuple(EV["BOOST"], flat, trace_to_c.NOPOS, cause, 0, id2, detail=stat, amount=change))

    def _battle_line(self, line):
        """A battle line: classified (lines.check), then folded; a single-turn feature line is remembered for the
        turn instead (it can matter only at a PIVOT of the same turn, _turn_scoped_stop)."""
        cls = lines.check(line, self) if self._foe_members is not None else "fold"
        if cls is None:
            return
        self._lines.append(line)
        if cls == "keep":
            return  # a line that changes no field (lines.check)
        if cls.startswith("turn:"):
            name = cls[len("turn:"):]
            self._turn_scoped.add(name)
            if name in ("WIDE_GUARD", "QUICK_GUARD"):
                self._guards.add((name, trace_to_c.ev_pos(line.split("|")[2]) // 2))
            self.turn_scoped_seen[name] += 1
            if self._foe_members is not None:
                self._fold(line, fold=False)  # its event still belongs to its move action (_segment)
            return
        self._extended_field(line)
        if line.startswith("|-clearnegativeboost|"):
            # White Herb (Team C): the [silent] line the converter skips, after its -enditem; the stages below
            # neutral return to it.
            p = self._at(trace_to_c.ev_pos(line.split("|")[2]))
            p.stages = [max(s, STAGE_NEUTRAL) for s in p.stages]
            return
        parts = line.split("|")
        if parts[1] in ("-start", "-end") and parts[3:4] == ["Throat Chop"]:
            self._throat_chop(parts)
            return
        if parts[1] == "-singlemove" and parts[3:4] == ["Glaive Rush"]:
            # Glaive Rush's drawback (step G19): its self effect shows only as -singlemove|X|Glaive Rush|[silent]
            # (data/moves.ts glaiverush), which the converter skips; the tracker sets the presence bit here
            pos = lines.flat_position(parts[2])
            if pos is None or parts[4:] != ["[silent]"]:
                raise lines.Stop("line:-singlemove Glaive Rush")
            self._at(pos).glaive_rush = 1
            return
        if parts[1] == "-end" and parts[3:4] == ["Attract"]:
            self._silent_attract_end(parts)
            return
        if parts[1] == "-end" and "[partiallytrapped]" in parts and "[silent]" in parts:
            # a partial trap's silent end (step G90: the source left, a Substitute, the residual with a fainted source); the
            # converter skips [silent] lines, so the tracker clears the trap here. The duration's end is no silent line.
            self._trap_silent_end(parts)
            return
        if parts[1] == "-damage" and "[partiallytrapped]" in parts:
            self._trap_residual(parts)  # counts the residual phase; the damage itself folds as any damage line below
        if parts[1] == "-end" and parts[3:4] == ["move: Yawn"]:
            # Yawn's end (step G31, data/moves.ts yawn onEnd: -end|X|move: Yawn|[silent], before the sleep it brings):
            # the converter skips [silent] lines, so the tracker clears the presence bit here; any other form stops
            pos = lines.flat_position(parts[2])
            if pos is None or parts[4:] != ["[silent]"]:
                raise lines.Stop("line:-end move: Yawn")
            self._at(pos).yawn = 0
            return
        if parts[1] == "-setboost":
            self._set_boost(parts)
            return
        self._fold(line)

    def _silent_attract_end(self, parts):
        """-end|X|Attract|[silent] (data/moves.ts attract onEnd): the infatuation of X ends with no visible line, when its source
        has left the field (onUpdate's removeVolatile, the engine's silent clearing of its byte). The converter skips [silent]
        lines, so the tracker clears the position here, as the Yawn's end does; any other form stops."""
        pos = lines.flat_position(parts[2])
        if pos is None or parts[4:] != ["[silent]"]:
            raise lines.Stop("line:-end Attract")
        self._at(pos).attract = 0

    def _throat_chop(self, parts):
        """Throat Chop's volatile (decision 0018 THROAT_CHOP, step G8; public by the owner's change): the move's
        `-start|X|Throat Chop|[silent]` (data/moves.ts throatchop, onStart) sets the presence bit, its residual
        `-end|X|Throat Chop|[silent]` (onEnd) clears it, and so does the occupant's leaving (the position's reset). The
        converter skips [silent] lines, so the line is folded here; its count is never shown. Any other form stops."""
        pos = lines.flat_position(parts[2])
        if pos is None or parts[4:] != ["[silent]"]:
            raise lines.Stop(f"line:{parts[1]} Throat Chop")
        self._at(pos).throat_chop = THROAT_CHOP_TURNS if parts[1] == "-start" else 0

    def _trap_move_id(self, name):
        """The move id of a partial-trap line's move name, None when the tables have none."""
        return self.data.tables["MOVE"].get(trace_to_c.key(name))

    @staticmethod
    def _trap_clear(p):
        p.trap = p.trap_source = p.trap_move = p.trap_band = p.trap_elapsed = 0

    def _trap_start(self, pos, source, move):
        """The partial trap's start (step G90, decision 0060; `-activate|T|move: M|[of] S`, an ACTIVATE of cause MOVE): the
        engine sets the volatile on a standing target that has none, with the source, the move, the source's Binding Band
        at that moment and a zero elapsed count. A target that has one is refused by the engine with no line, so the
        line cannot come then; the drawn turns are never shown."""
        p = self._at(pos)
        if p.trap:
            raise lines.Stop("trap-start-on-trapped")
        if (p.occupant == ROSTER_NONE or not 0 <= source < len(self._positions) * 2 or source == pos
                or self._at(source).occupant == ROSTER_NONE):
            raise lines.Stop("trap-start-source")
        p.trap, p.trap_source, p.trap_move = 1, source + 1, move + 1
        p.trap_band = 1 if self._holds(self._occupant(source), "BINDINGBAND") else 0
        p.trap_elapsed = 0

    def _trap_end(self, pos, move):
        """The duration's end (`-end|T|move: M|[partiallytrapped]`, VOLATILE_END): the engine clears the trap and its count."""
        p = self._at(pos)
        if not p.trap:
            raise lines.Stop("trap-end-untrapped")
        if p.trap_move != move + 1:
            raise lines.Stop("trap-end-move")
        self._trap_clear(p)

    def _trap_silent_end(self, parts):
        """A partial trap's silent end, `-end|T|M|[partiallytrapped]|[silent]` (the pin prints the move bare; the converter's
        other spelling, "move: M", is taken too): the engine cleared the trap with no event. Any other form stops."""
        pos = lines.flat_position(parts[2]) if len(parts) > 2 else None
        if len(parts) != 6 or parts[1] != "-end" or parts[4] != "[partiallytrapped]" or parts[5] != "[silent]" or pos is None:
            raise lines.Stop("trap-end-line")
        p = self._at(pos)
        if not p.trap:
            raise lines.Stop("trap-end-untrapped")
        name = parts[3][len("move: "):] if parts[3].startswith("move: ") else parts[3]
        if self._trap_move_id(name) != p.trap_move - 1:
            raise lines.Stop("trap-end-move")
        self._trap_clear(p)

    def _trap_residual(self, parts):
        """One residual phase of a partial trap that stays up: `-damage|T|hp|[from] move: M|[partiallytrapped]`. The engine
        counts the phase (TRAP_ELAPSED, +1) before the damage; the phase that ends the trap shows an end line, not this one,
        and the count stays below the duration of at most 6. Any other form stops."""
        pos = lines.flat_position(parts[2]) if len(parts) > 2 else None
        if (len(parts) != 6 or parts[1] != "-damage" or not parts[3] or parts[3].startswith("[") or pos is None
                or parts[5] != "[partiallytrapped]" or not parts[4].startswith("[from] move: ")):
            raise lines.Stop("trap-residual-line")
        p = self._at(pos)
        if not p.trap:
            raise lines.Stop("trap-residual-untrapped")
        if self._trap_move_id(parts[4][len("[from] move: "):]) != p.trap_move - 1:
            raise lines.Stop("trap-residual-move")
        if p.trap_elapsed >= TRAP_ELAPSED_MAX:
            raise lines.Stop("trap-residual-count")
        p.trap_elapsed += 1

    def _trap_source_left(self, pos):
        """The occupant of `pos` leaves (a switch, a drag or a faint): every trap it was the source of keeps its turns, move,
        band and count but has no source any more (dfi_tail_clear_occupant), and the residual ends it silently."""
        for side in self._positions:
            for q in side:
                if q.trap and q.trap_source == pos + 1:
                    q.trap_source = 0

    def _extended_field(self, line):
        """A weather or terrain set by a member that holds the item lengthening it (Damp Rock, Heat Rock, Smooth
        Rock, Icy Rock, Terrain Extender; data/conditions.ts durationCallback: source.hasItem) lasts 8 turns, and no
        line shows it: the setter is the [of] member (an ability) or the last move's user, its item the open
        sheet's unless it was seen used or lost. The next WEATHER or FIELD_START event of this line takes the 8."""
        self._field_turns_next = FIELD_TURNS
        parts = line.split("|")
        kind = parts[1] if len(parts) > 1 else ""
        if kind == "-weather" and len(parts) > 2 and parts[2] in _WEATHER_ITEM and "[upkeep]" not in parts:
            item = _WEATHER_ITEM[parts[2]]
        elif kind == "-fieldstart" and len(parts) > 2 and parts[2].endswith(" Terrain"):
            item = "Terrain Extender"
        else:
            return
        of = [p[len("[of] "):] for p in parts if p.startswith("[of] ")]
        holder = None
        if of:
            holder = self._member_of(of[0])
        elif self._last_move is not None:
            holder = self._occupant(self._last_move[0])
        if holder is not None and self._holds(holder, trace_to_c.key(item)):
            self._field_turns_next = FIELD_TURNS_EXTENDED

    def _turn_scoped_stop(self, boundary):
        """Stop at a PIVOT boundary while a single-turn feature of this turn is up and its bit is not supported."""
        if boundary == PIVOT and self._turn_scoped:
            raise lines.Stop(f"feature:{sorted(self._turn_scoped)[0]}")

    # ------------------------------------------------------------------ what lines.check reads
    def sheet_of(self, ident):
        """The sheet of the member a protocol ident ("p1a: Name") names."""
        return self._member_of(ident).sheet

    def known_sheet(self, ident):
        """The sheet of the member a protocol ident names, or None before its name was seen."""
        side, name = int(ident[1]) - 1, ident.split(": ", 1)[1]
        index = self._names[side].get(name)
        return None if index is None else self._member(side)[index].sheet

    def side_sheets(self, ident):
        """The open sheets of every member of the side a protocol ident names (lines.check: a possible Illusion)."""
        return [m.sheet for m in self._member(int(ident[1]) - 1)]

    def ability_now(self, ident):
        """The current ability + 1 of the member a protocol ident names: the one Trace or Skill Swap gave it while it
        stands at the ident's position, else its own (the sheet's, or its Mega forme's)."""
        member = self._member_of(ident)
        pos = lines.flat_position(ident)
        if pos is not None:
            p = self._at(pos)
            if p.ability_now and p.occupant != ROSTER_NONE and self._member(pos // 2)[p.occupant] is member:
                return p.ability_now
        return member.ability

    def _ability_at(self, pos):
        """The current ability + 1 of the occupant of flat position `pos` (ability_now)."""
        p = self._at(pos)
        return p.ability_now or self._member(pos // 2)[p.occupant].ability

    def item_now(self, ident):
        """The item + 1 the member a protocol ident names holds as far as the lines showed, used up or not (lines.check:
        a line about the holder's own item): the one a move or Symbiosis gave it, 0 after one took it, else the
        sheet's."""
        return self._item_of(self._member_of(ident))

    @staticmethod
    def _item_of(member):
        if member.item_now == ITEM_NOW_NONE:
            return 0
        return member.item_now or member.sheet["item"]

    def _holds(self, member, key):
        """Whether `member` holds the item of ITEM table key `key` now, as far as the lines showed: not seen used up or
        lost (item_used), the sheet's item or the one a move gave it."""
        item = self.data.tables["ITEM"].get(key)
        return item is not None and not member.item_used and self._item_of(member) == item + 1

    def _item_received(self, pos, code, public):
        """The occupant of `pos` now holds the item `code` (+ 1) that a move or Symbiosis gave it: its old item is no
        longer gone, and a Choice item ends its lock (the item's onStart; dfi_set_held)."""
        m = self._occupant(pos)
        m.item_now = code
        m.revealed &= ~REVEALED_ITEM_CONSUMED
        m.item_consumed = 0
        if public:
            m.item_used = 0
        if code in self._choice_items:
            self._at(pos).choice_slot = MOVE_SLOT_NONE

    def _member_of(self, ident):
        side, name = int(ident[1]) - 1, ident.split(": ", 1)[1]
        if name not in self._names[side]:
            raise lines.Stop(f"structure:{ident} names no member seen yet")
        return self._member(side)[self._names[side][name]]

    def accepted(self, text):
        """The own choice Showdown accepted at the current decision point."""
        if self.request is not None and "active" in self.request:
            self._accepted = text
            # the commands of that choice, for the queue of a PIVOT of the turn (the public record): the options whose
            # texts it joins (options.pair_text), None where a part names none
            try:
                lists = self.domain()[1]
            except ValueError:
                lists = None  # options the tracker cannot list (a lock without a known target): the PIVOT queue refuses
            parts = text.split(", ")
            self._accepted_commands = [next((o for o in lists[k] if o.text == parts[k]), None) if k < len(parts) else None
                                       for k in range(2)] if lists is not None else None
        if text.startswith("team "):
            self._picks = [int(c) - 1 for c in text[len("team "):]]
            self._party = list(self._picks)  # side.pokemon of the pin: the pick order, leads first

    @property
    def ready(self):
        """A decision point is complete: its request came (and at team preview both open team sheets)."""
        if self.request is None:
            return False
        return not self.request.get("teamPreview") or len(self._sheets_seen) == 2

    def _on_request(self, request):
        rqid = request.get("rqid")
        if not isinstance(rqid, int):
            raise ValueError("a request without an rqid")
        if rqid in self._rqids:
            return  # sent again (a reconnect): the same decision point
        self._rqids.add(rqid)
        if request.get("update"):
            self._on_updated_request(request)
            return
        side = int(request["side"]["id"][1]) - 1
        if self.side is None:
            self.side = side
        elif side != self.side:
            raise ValueError(f"a request for side {side} in the room of side {self.side}")
        self._foe_sheet()
        self._end_action()  # the step's last action ended with it
        self.request = request
        self.epoch += 1
        self._step_lines, self._lines = self._lines, []
        self._turn_scoped_stop(self.boundary())
        own = self._own_members
        for mon in request["side"]["pokemon"]:
            name = mon["ident"].split(": ", 1)[1]
            self._names[self.side].setdefault(name, options.own_roster({"side": {"pokemon": [mon]}},
                                                                       self.own_sheets, self.data)[mon["ident"]])
            member = own[self._names[self.side][name]]
            hp, hp_max, status = _condition(mon["condition"])
            member.hp, member.status = hp, status
            if hp_max is not None:
                member.hp_max = hp_max
            member.stats = [mon["stats"][k] for k in ("atk", "def", "spa", "spd", "spe")]
            forme = self.data.forme(mon["details"].split(",")[0])
            member.is_mega = 1 if self.data.base_forme(forme) != forme else 0
            # baseAbility: the sheet's or the Mega forme's (formeChange), which the member view shows; "ability" is the
            # current one, which Trace or Skill Swap may have changed (the position's ability_now, from the lines). The
            # pin sends it for every member (sim/pokemon.ts getSwitchRequestData, :1176; a Mega sets it, :1489).
            if "baseAbility" not in mon:
                raise ValueError(f"a request member without baseAbility: {mon.get('ident')!r}")
            ability = trace_to_c.key(mon["baseAbility"])  # "noability": No Ability, 0 as parse_team has it
            member.ability = 0 if ability == "NOABILITY" else self.data.tables["ABILITY"][ability] + 1
            member.item_used = 1 if member.sheet["item"] != 0 and mon["item"] == "" else 0
        if "active" in request:
            for slot, entry in enumerate(request["active"]):
                moves = entry.get("moves", [])
                if len(moves) > 1 or (moves and "pp" in moves[0]):
                    occupant = self._positions[self.side][slot].occupant
                    if occupant == ROSTER_NONE:
                        continue
                    member = own[occupant]
                    for k, move in enumerate(moves):
                        if member.pp_max[k] - member.uses[k] != move["pp"]:
                            raise ValueError(f"own PP of {member.sheet['moves'][k]}: tracked "
                                             f"{member.pp_max[k] - member.uses[k]}, request {move['pp']}")

    def _on_updated_request(self, request):
        """The current move request again after a refused choice (module docstring): only its active entries may
        differ, and no battle line came since it."""
        r = self.request
        if (r is None or "active" not in r or "active" not in request or self._lines
                or request["side"] != r["side"] or len(request["active"]) != len(r["active"])):
            raise ValueError("an updated request that does not update the current move request")
        self.request = request
        self.epoch += 1

    def _on_showteam(self, line):
        _, _, who, packed = line.split("|", 3)
        self._sheets_seen.add(int(who[1]) - 1)
        self._packed[int(who[1]) - 1] = packed
        self._foe_sheet()

    def _foe_sheet(self):
        """The foe's members, once its sheet and the own side are known."""
        if self._foe_members is not None or self.side is None or self._packed[1 - self.side] is None:
            return
        self.foe_sets = teams.unpack(self._packed[1 - self.side])
        for s in self.foe_sets:
            s["species"] = self.data.canonical(s["species"])  # a cosmetic alias (#118) as the tables name its row
        self._foe_members = [_Member(s, self.data) for s in self.data.team(teams.to_text(self.foe_sets))]

    def _member(self, side):
        """The members of a side (the own list first)."""
        return self._own_members if side == self.side else self._foe_members

    # ------------------------------------------------------------------ fold
    def _register(self, line):
        """Learns the roster index of a Pokemon named in a switch line, from the species of its details."""
        parts = line.split("|")
        if parts[1] not in ("switch", "drag"):
            return
        side = int(parts[2][1]) - 1
        name = parts[2].split(": ", 1)[1]
        if name in self._names[side]:
            return
        base = self.data.base_forme(self.data.forme(parts[3].split(",")[0]))
        index = [m for m, member in enumerate(self._member(side)) if member.sheet["species"] == base]
        if len(index) != 1:
            if parts[1] == "drag":
                # Step G46: a drag into a member that is not one member of the side's sheet cannot be represented.
                raise lines.Stop(f"drag:{parts[2]} names no member of the side's sheet")
            raise ValueError(f"{parts[2]} ({parts[3]}) is not one member of its side's sheet")
        self._names[side][name] = index[0]

    def _fold(self, line, fold=True):
        """The line's events into the tracker's fields; fold=False only collects them for the move action's result."""
        if _kind(line) in trace_to_c.NOT_EVENTS:
            return  # setup and layout lines: no event (step_events skips them too)
        if _kind(line) in ("win", "tie") and self._foe_members is None:
            self.ended = True  # over before the sheets (a forfeit during the wait): nothing to fold
            return
        if self._foe_members is None:
            raise ValueError(f"a battle line before both open team sheets: {line!r}")
        self._register(line)
        maxhp = [{n: 100 for n in self._names[s]} for s in (0, 1)]
        own = self._member(self.side)
        if not self._spectator:
            for name, index in self._names[self.side].items():
                maxhp[self.side][name] = own[index].hp_max
        viewer = SPECTATOR if self._spectator else self.side
        parts = line.split("|")
        if _kind(line) == "move" and parts[3:4] == ["Revival Blessing"]:
            user = lines.flat_position(parts[2])
            if user is not None:
                self._rb_pending[user // 2] = user  # its revive comes in the step that answers the request
        swap_ids = None
        if parts[1] == "-activate" and parts[3:6] == ["Skill Swap", "", ""] and len(parts) == 7:
            # an ally Skill Swap names no ability (decision 0041): the two holders' current abilities, known from the
            # open sheets and the lines folded so far, change places
            src, tgt = lines.flat_position(parts[2]), lines.flat_position(parts[6][len("[of] "):])
            if src is not None and tgt is not None and self._at(src).occupant != ROSTER_NONE \
                    and self._at(tgt).occupant != ROSTER_NONE and self._ability_at(src) and self._ability_at(tgt):
                swap_ids = {0: (self._ability_at(tgt) - 1, self._ability_at(src) - 1)}
        try:
            events = trace_to_c.step_events([line], viewer, self._names, maxhp, self.data.tables, self._rb_pending,
                                            swap_ids=swap_ids, lead=self._lines[-4:-1])  # the Leech Seed heal reads back
        except trace_to_c.ConversionError as e:  # a SystemExit: callers catch one kind of error
            detail = getattr(e, "detail", None)
            raise lines.Stop(f"converter:{e.rule}" + (f" {detail}" if detail else "")) from e
        except (KeyError, IndexError) as e:  # a form of a known line the parser does not know (untyped, as diff_driver)
            raise lines.Stop(f"converter:untyped {_kind(line)} {type(e).__name__} {e}") from e
        for e in events:
            if fold:
                self._event(e)
            else:
                self._segment(e)

    def _at(self, pos):
        return self._positions[pos // 2][pos % 2]

    def current_types(self, member, position=None):
        """The types of a member now, as the lines the tracker folds show them: a type a move set while it stands at
        `position` (the position's type_now, #342: Soak's single type, or Double Shock's remaining type; a Mega Evolution
        ends it), else those of its set's forme, or of its Mega forme once it Mega Evolved (the stone of its sheet names
        it). A forme change stops on its own line (FORME_CHANGE is no fold of this tracker; the day it is folded this
        has to know it, so it refuses while it is supported). Without the position a folded type change cannot be
        seen, so it refuses then too. Trick-or-Treat and Forest's Curse stop on their lines (the converter). Lines the
        tracker does not read cannot change them (Roost only hides Flying for a turn, which never decides a Ghost).
        ValueError for a Mega member whose sheet has no stone of its forme."""
        if lines.SUPPORTED >> lines.FEATURES["FORME_CHANGE"] & 1:
            raise lines.Stop("types:FORME_CHANGE")
        if position is not None and position.type_now != (0, 0):
            soak, other = position.type_now  # (id + 1, 0): Soak's type; (0, id + 1): Double Shock's ??? and that type
            return (soak - 1,) if soak else (other - 1,)
        if position is None and lines.SUPPORTED >> lines.FEATURES["TYPE_CHANGE"] & 1:
            raise lines.Stop("types:TYPE_CHANGE")
        forme = member.sheet["species"]
        if member.is_mega:
            forme = self.data.mega_of(forme, member.sheet["item"])
            if forme is None:
                raise ValueError("a Mega member whose sheet has no Mega Stone of its forme")
        return self.data.forme_types(forme)

    def _occupant(self, pos):
        p = self._at(pos)
        return None if p.occupant == ROSTER_NONE else self._member(pos // 2)[p.occupant]

    def _event(self, e):
        self._segment(e)
        herb, self._herb_end = self._herb_end, None
        if herb is not None and e[0] == EV["VOLATILE_END"] and e[1] == herb:
            self._herb_end = herb  # the herb's row of -end lines goes on
        self._fold_event(e, herb)

    def _residual_end(self, e, herb, count, name):
        """A natural end of a counted volatile (no [from], not Mental Herb's row) comes in the residual where its count
        runs out: the tracker's count must be 1 there. Any other count is a counting error (the start's duration rule,
        a wrong move_queued), which stops the tracker instead of writing a wrong count into the record."""
        if e[3] == trace_to_c.CAUSE["NONE"] and e[1] != herb and count != 1:
            raise lines.Stop(f"count:{name} ends at {count}")

    def _segment(self, e):
        """The events of each move action, for its result (the POOL record's move_result): an action begins with its
        user's own [move] line, a [cant] (not an ability's block, which follows the user's [move]) or a confusion line
        (the [move] or [cant] after it belongs to it), and ends where the next one begins, at the residual (|upkeep|),
        at the next turn or at a decision point (_end_action)."""
        kind, pos, cause = e[0], e[1], e[3]
        if kind in (EV["UPKEEP"], EV["TURN"]):
            self._end_action()
            if kind == EV["TURN"]:
                for side in self._positions:
                    for p in side:
                        # endTurn: moveLastTurnResult = moveThisTurnResult, this turn's undefined (src/combat/turn.c)
                        p.result_last, p.result_now = p.result_now, 0
            return
        action = self._action
        # A Magic Bounce holder's [cant] Throat Chop right after the move line that targets it is the bounced run, inside the
        # action (issue 570), not an action of its own
        bounce_cant = action is not None and action["events"] and self._bounce_cant(action["events"][-1], e, action["pos"])
        starts = not bounce_cant and (
            (kind == EV["MOVE"] and cause == trace_to_c.CAUSE["NONE"]) or kind == EV["CONFUSED"] or
            (kind == EV["CANT"] and cause != trace_to_c.CAUSE["ABILITY"]))
        if starts and action is not None and action["pos"] == pos and action["confused"] and kind != EV["CONFUSED"]:
            action["confused"] = False  # the move the confusion line let through, or its [cant]
            action["events"].append(e)
        elif starts:
            # the lines of this action that come before its first one end the previous action's list: a wake-up or thaw
            # ([-curestatus] [msg]), the end of a confusion, Struggle's -activate
            lead = []
            while action is not None and action["events"] and self._pre_action(action["events"], pos):
                lead.insert(0, action["events"].pop())
            self._end_action()
            p = self._at(pos)
            self._action = {"pos": pos, "events": lead + [e], "confused": kind == EV["CONFUSED"],
                            "activation": p.activation}
        elif action is not None:
            action["events"].append(e)

    def _bounce_cant(self, prev, e, user):
        """`e` is the [cant] Throat Chop of the target of `user`'s move line `prev`, a foe: Magic Bounce took the move and
        Throat Chop stopped the bounced run before its line (issue 570, src/combat/turn.c dfi_bounce)."""
        return e[0] == EV["CANT"] and e[3] == trace_to_c.CAUSE["MOVE"] and e[5] == self._throat_chop_id and \
            prev[0] == EV["MOVE"] and prev[3] == trace_to_c.CAUSE["NONE"] and prev[1] == user and prev[2] == e[1] and \
            e[1] != NOPOS and e[1] // 2 != user // 2

    def _pre_action(self, events, pos):
        """The last of `events` is a line of `pos` that comes before its action's first line: a wake-up or a thaw
        ([-curestatus] [msg], not a berry's cure after its -enditem), the end of its confusion, Struggle's -activate."""
        e = events[-1]
        if e[1] != pos:
            return False
        if len(events) > 1 and events[-2][0] == EV["ITEM_END"] and events[-2][1] == pos:
            return False
        return (e[0] == EV["CURE_STATUS"] and e[13] & FLAG["MESSAGE"] and e[3] == trace_to_c.CAUSE["NONE"]) or \
            e[0] == EV["CONFUSION_END"] or \
            (e[0] == EV["ACTIVATE"] and e[3] == trace_to_c.CAUSE["MOVE"] and e[5] == self._struggle) or \
            (e[0] == EV["ACTIVATE"] and e[3] == trace_to_c.CAUSE["MOVE"] and e[5] == self._attract)

    def _end_action(self):
        """The result of the move action that ends here, into its user's position (this turn's): the library's
        classification of its events (record.move_result_of), None where they do not determine it."""
        action, self._action = self._action, None
        if action is None or self.data.kind != "pool":
            return
        from . import record
        events = action["events"]
        # The user may have moved during its own action (Ally Switch): the activation id belongs to the Pokemon, so the slot that
        # now holds it gets the result (src/combat/turn.c dfi_run_move). Another occupant at every slot, or the user fainted:
        # the faint's clearing comes after the result
        side = action["pos"] // 2
        for p in self._positions[side]:
            if p.occupant != ROSTER_NONE and p.activation == action["activation"] and not p.fainted:
                p.result_now = record.move_result_of(self.data, action["pos"], events)
                break
        for i, e in enumerate(events):
            if (e[0] == EV["MOVE"] and e[3] == trace_to_c.CAUSE["ABILITY"] or
                    i > 0 and self._bounce_cant(events[i - 1], e, action["pos"])) and e[1] != NOPOS:
                # Magic Bounce: the holder's result is that of the reflected run (src/combat/turn.c, the bounced move)
                holder = self._at(e[1])
                if holder.occupant != ROSTER_NONE and not holder.fainted:
                    holder.result_now = record.move_result_of(self.data, e[1], events[i:])

    def _fold_event(self, e, herb=None):
        kind, pos, ident, ident2 = e[0], e[1], e[4], e[5]
        hp, hp_kind, hp_flag, status, detail, amount, flags = e[6], e[8], e[9], e[10], e[11], e[12], e[13]
        foe = pos != NOPOS and pos // 2 != self.side
        public = foe or (self._spectator and pos != NOPOS)  # folded from the public lines
        if kind == EV["FAIL"] and e[3] == trace_to_c.CAUSE["NONE"] and pos != NOPOS and self._as_pending == pos:
            # Ally Switch's consecutive roll failed (onPrepareHit false, -fail|X with [still]): the volatile is deleted, the
            # next use starts at level 1 (data/moves.ts:326-357; the engine: dfi_ally_switch_prepare)
            self._at(pos).ally_level = self._at(pos).ally_turns = 0
            self._as_pending = None
        if kind == EV["TURN"]:
            self._turn = ident
            self._after_upkeep = False
            self._turn_scoped.clear()
            self._guards.clear()
            for side in (0, 1):
                for p in self._positions[side]:
                    # endTurn: newlySwitched ends, and the raised flag (statsRaisedThisTurn: not before turn 1, the
                    # battle's start keeps its entry boosts' flag); every standing occupant has its move ahead
                    p.newly_switched = 0
                    if ident > 1:
                        p.raised = p.lowered = p.hurt = 0  # statsLoweredThisTurn and hurtThisTurn as well (G88)
                    p.move_queued = p.occupant != ROSTER_NONE and not p.fainted
                    p.turn_done = p.occupant == ROSTER_NONE or p.fainted
                    # endTurn's DisableMove: choicelock ends for a holder without its Choice item (dfi_end_turn)
                    if p.choice_slot != MOVE_SLOT_NONE and p.occupant != ROSTER_NONE:
                        m = self._member(side)[p.occupant]
                        if m.item_used or self._item_of(m) not in self._choice_items:
                            p.choice_slot = MOVE_SLOT_NONE
        elif kind in (EV["SWITCH"], EV["DRAG"]):
            # A drag (Step G46) is a switch of the dragged-in member: the occupant is replaced and reset, the HP of the line.
            p = self._at(pos)
            self._trap_source_left(pos)
            if p.occupant != ROSTER_NONE:
                self._member(pos // 2)[p.occupant].toxic_stage = 0  # the leaving member's toxic counter ends with it
            passed = None
            if kind == EV["SWITCH"] and e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._baton_pass:
                # Baton Pass (step G74, decision 0042; sim/pokemon.ts copyVolatileFrom): no line shows the copy; of
                # the base view's fields the receiver keeps the leaver's stages and confusion, of the folded view
                # extension what dfi_pass_give copies (_PASSED). The other copied volatiles are decision 0018 features,
                # which stopped the tracker at their start lines.
                passed = (list(p.stages), p.confused, {name: getattr(p, name) for name in _PASSED})
            p.occupant, p.flag, p.fainted = ident, 0, False
            p.reset()
            if passed is not None:
                p.stages, p.confused = passed[0], passed[1]
                for name, value in passed[2].items():
                    setattr(p, name, value)
            p.activation, p.move_actions = self._next_activation, 0  # entries are numbered in the order of their lines
            p.confused_action = False
            p.newly_switched, p.turn_done, p.move_queued = 1, True, False
            self._member(pos // 2)[ident].toxic_stage = 0  # tox's onSwitchIn
            self._next_activation += 1
            if pos // 2 != self.side and self._foe_leads[pos % 2] == ROSTER_NONE:
                self._foe_leads[pos % 2] = ident  # the foe's pick order starts with its leads
            if pos // 2 == self.side and self._party is not None and ident in self._party:
                i = self._party.index(ident)
                self._party[i], self._party[pos % 2] = self._party[pos % 2], self._party[i]
            m = self._member(pos // 2)[ident]
            if public:
                m.seen, m.hp_percent, m.hp_flag, m.status = True, hp, hp_flag, status
            else:
                m.seen = True
                self._own_display(m, hp, e[7])
        elif kind == EV["MOVE"]:
            p = self._at(pos)
            if ident == self._healing_wish and e[3] == trace_to_c.CAUSE["NONE"] and not flags & FLAG["STILL"]:
                # dfi_run_healing_wish: it runs (a reserve stands; a [still] -fail is the refusal for none) and sets the
                # slot's wish; a second one finds it set and changes nothing
                p.wish = 1
            self._as_pending = pos if ident == self._ally_move else None
            if e[3] == trace_to_c.CAUSE["NONE"]:
                # an action of the user (runMove's activeMoveActions++, dfi_run_move); a move line with cause ABILITY is
                # Magic Bounce's reflection (useMove), no action of the holder
                p.acted = 1
                self._move_action(p)
                p.turn_done, p.move_queued = True, False
                if ident in self._move_pivots:
                    p.flag = self._move_pivots[ident]  # a -fail line that follows takes it back
            self._last_move = (pos, ident, e[2])
            if e[3] != trace_to_c.CAUSE["ABILITY"]:
                # the next action ends Glaive Rush's drawback (glaiverush onBeforeMove, step G19). A move line with cause
                # ABILITY is Magic Bounce's reflection, no action of its own; Dancer, whose copy would be one, is not
                # modelled by the engine
                p.glaive_rush = 0
            if e[3] == trace_to_c.CAUSE["NONE"]:
                p.last_move = ident  # runMove's moveUsed, a locked turn too; not a move another effect makes it use
            m = self._occupant(pos)
            if e[3] != trace_to_c.CAUSE["ABILITY"]:
                # the move Encore takes (pokemon.moveUsed after runMove's PP, a locked turn included); a move that Magic
                # Bounce reflects (cause ABILITY, step G57) is not its user's own move
                if ident in m.sheet["moves"]:
                    p.last_slot = m.sheet["moves"].index(ident) + 1
                else:
                    p.last_slot = 5 if ident == self._struggle else None
            if not flags & FLAG["LOCKED"] and e[3] != trace_to_c.CAUSE["ABILITY"] and ident in m.sheet["moves"]:
                # a move Magic Bounce reflects (cause ABILITY, step G57) costs its holder no PP: the pin's useMove
                # deducts none, as DuoForge's knowledge fold
                m.uses[m.sheet["moves"].index(ident)] += 1 + self._pressure_extra(pos, ident, e[2], flags)
            if ident in self._guard_moves and not flags & FLAG["LOCKED"]:
                # Wide Guard and Quick Guard add the stall volatile when they run (data/moves.ts onHitSide
                # addVolatile('stall')), also when the side has the guard already (no -singleturn line then), the
                # counter a Protect reads: protect_chain counts them (g7_wide_guard_ally). A -fail undoes it.
                p.guard_undo = (p.chain, p.stall)
                p.chain = min(p.chain + 1, STALL_LEVEL_MAX)
                p.stall = STALL_DURATION
            holds_choice = not m.item_used and self._item_of(m) in self._choice_items
            if p.choice_slot != MOVE_SLOT_NONE and not holds_choice and e[3] != trace_to_c.CAUSE["ABILITY"]:
                p.choice_slot = MOVE_SLOT_NONE  # choicelock's onBeforeMove: its Choice item is gone (a Trick, Knock Off)
            if self.check_foe_sheet and pos // 2 != self.side and e[3] == trace_to_c.CAUSE["NONE"] and ident != self._struggle:
                # A drawn foe sheet (decision 0081, cts.ParticleTracker) the line contradicts, where the open-sheet fold
                # would go on in silence: an own move off the sheet, or another move than the one a Choice item locked
                if ident not in m.sheet["moves"]:
                    raise SheetContradiction("move-not-on-set")
                if p.choice_slot != MOVE_SLOT_NONE and holds_choice and m.sheet["moves"][p.choice_slot] != ident:
                    raise SheetContradiction("choice-lock", member=p.occupant)
            if (p.choice_slot == MOVE_SLOT_NONE and holds_choice and ident in m.sheet["moves"]
                    and e[3] != trace_to_c.CAUSE["ABILITY"]):
                # A Choice item locks its holder into the move of its |move| line (data/items.ts onModifyMove,
                # set right before the line) until it leaves (c07 battles, Choice Scarf).
                p.choice_slot = m.sheet["moves"].index(ident)
        elif kind == EV["ACTIVATE"]:
            if e[3] == trace_to_c.CAUSE["ABILITY"] and ident2 == self.data.tables["ABILITY"]["EMERGENCYEXIT"] + 1:
                # it leaves: asked to switch (id2 names an ability only with cause ABILITY)
                self._at(pos).flag = SWITCH_EMERGENCY_EXIT
            elif e[3] == trace_to_c.CAUSE["ABILITY"] and ident2 == self._symbiosis:
                # Symbiosis (step G69): the holder passes its item (id: the item + 1) to its ally ([of], `other`), which
                # has used its own up; the holder then holds nothing
                holder = self._occupant(pos)
                holder.item_now = ITEM_NOW_NONE
                holder.revealed |= REVEALED_ITEM_CONSUMED
                if public:
                    holder.item_used = 1
                self._item_received(e[2], ident, public)
            elif e[3] == trace_to_c.CAUSE["MOVE"] and ident2 in self._trap_moves:
                self._trap_start(pos, e[2], ident2)  # the partial trap's start (step G90)
            elif e[3] == trace_to_c.CAUSE["MOVE"] and ident2 in (self._feint, self._phantom_force):
                # Feint broke something (step G28, sim/battle-actions.ts hitStepBreakProtect, printed only then; Phantom
                # Force's `[broken]` line the same, step G58): the target's own Protect (its flag) and its stall
                # volatile (chain and stall, a guard_undo that is no longer open), and the Wide Guard and Quick Guard of
                # the target's whole side, a partner's included. Only the target's stall goes: a partner that set the
                # guard keeps its own chain.
                p = self._at(pos)
                p.protecting = p.chain = p.stall = 0
                p.guard_undo = None
                for guard in ("WIDE_GUARD", "QUICK_GUARD"):
                    self._guards.discard((guard, pos // 2))
                    if not any(g[0] == guard for g in self._guards):
                        self._turn_scoped.discard(guard)
        elif kind == EV["FAINT"]:
            p = self._at(pos)
            self._trap_source_left(pos)
            p.reset()  # a faint clears the position's conditions; the occupant stays until replaced
            p.fainted = True
            # a faint takes a pivot flag (faint(): switchFlag = false); after the residual (Perish Song's) checkFainted asks
            # for the position at once
            p.flag = SWITCH_FAINTED if self._after_upkeep else 0
            p.move_actions = 0
            # a faint that no damage line announced (Perish Song's perish0, step G26): the display shows 0
            m = self._occupant(pos)
            m.hp_percent, m.hp_flag = 0, 0
            m.status, m.freeze_turns = 0, 0  # a fainted member has no status (the views show none; the record holds none)
            m.toxic = m.toxic_stage = 0
            m.sleep_cant = 0  # decision 0066: the sleep's count ends with it
        elif kind == EV["CANT"]:
            # An ability's block (Armor Tail) names its holder; the move's user, [of], took the action.
            blocked = e[3] == trace_to_c.CAUSE["ABILITY"]
            actor = self._at(e[2] if blocked else pos)
            if e[3] == trace_to_c.CAUSE["SLEEP"] and actor.occupant != ROSTER_NONE:
                self._member(pos // 2)[actor.occupant].sleep_cant += 1  # decision 0066: one more cant line of this sleep
            actor.acted = 1
            if not blocked:
                self._move_action(actor)  # a block follows the user's own [move] line: the same action
            actor.turn_done, actor.move_queued = True, False
            actor.glaive_rush = 0  # its action began: glaiverush's onBeforeMove ran first (step G19)
            if e[3] == trace_to_c.CAUSE["RECHARGE"]:
                self._at(pos).must_recharge = 0  # cant|X|recharge: mustrecharge's onBeforeMove ends it (step G17)
            if e[3] == trace_to_c.CAUSE["FREEZE"]:
                m = self._occupant(pos)
                m.freeze_turns = max(m.freeze_turns - 1, 0)
        elif kind == EV["TYPE_CHANGE"]:
            # Soak's single type (detail: its id) or Double Shock's ??? (detail DUOFORGE_TYPE_NONE, amount: the other
            # type + 1), step G11 and decision 0025, until the occupant leaves or Mega Evolves (the tail's soak_type).
            # A plain typechange line is Soak's only after a Soak move line (Magic Powder prints the same form).
            if e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._soak and (
                    self._last_move is None or self._last_move[1] != self._soak):
                raise lines.Stop("line:-start typechange (no Soak)")
            p = self._at(pos)
            p.type_now = (0, amount) if detail == trace_to_c.TYPE_NONE else (detail + 1, 0)
            p.type2 = amount if detail == trace_to_c.TYPE_NONE else 0  # setType replaces both types (Soak)
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_ATTRACT:
            # Attract (step G71, decision 0034): -start|X|Attract|[from] ability: Cute Charm|[of] Y (e[2] = Y's position) keeps Y's
            # member code on X; the visible ends (Mental Herb's and Oblivious's rows) clear it. The silent end (the source left) comes
            # as its own line (_silent_attract_end), and a switch or a faint of X clears it in _Position.reset.
            p = self._at(pos)
            if kind == EV["VOLATILE_START"]:
                holder = self._at(e[2])
                if holder.occupant == ROSTER_NONE:
                    raise lines.Stop("attract-source-unknown")  # the holder of [of] is not on the field
                p.attract = 1 + (e[2] // 2) * C["DUOFORGE_MAX_ROSTER"] + holder.occupant
                p.attract_from = e[2]  # the view's source position (step G87, decision 0080)
            else:
                p.attract, p.attract_from = 0, 0
        elif kind == EV["VOLATILE_END"] and detail == trace_to_c.VOLATILE_PARTIAL_TRAP:
            self._trap_end(pos, ident)  # the duration's end (step G90): the line names the move in `ident`
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_HEAL_BLOCK:
            # Heal Block (step G8, Psychic Noise): -start|X|move: Heal Block and -end|X|move: Heal Block (the duration,
            # Mental Herb); the occupant's leaving ends it with no line; its count is never shown
            if kind == EV["VOLATILE_END"]:
                self._residual_end(e, herb, self._at(pos).heal_block, "heal_block")
            self._at(pos).heal_block = HEAL_BLOCK_TURNS if kind == EV["VOLATILE_START"] else 0
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_TAUNT:
            # Taunt (step G31): -start|X|move: Taunt and -end|X|move: Taunt (the duration, Mental Herb, Oblivious); the
            # occupant's leaving ends it with no line; the view shows its presence, the record its count: one more
            # when the target has been out for a turn and has no move left this turn (dfi_taunt)
            p = self._at(pos)
            if kind == EV["VOLATILE_END"]:
                self._residual_end(e, herb, p.taunt, "taunt")
            p.taunt = 0
            if kind == EV["VOLATILE_START"]:
                p.taunt = TAUNT_TURNS + (1 if not p.newly_switched and not p.move_queued else 0)
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_DISABLE:
            # Disable (step G27): -start|X|Disable|MOVE (also [from] ability: Cursed Body) bars MOVE's slot of the open
            # sheet; -end|X|Disable (the duration, Mental Herb) and the occupant's leaving end it; its count is never
            # shown. A barred move that is not on the sheet stops.
            p = self._at(pos)
            if kind == EV["VOLATILE_END"]:
                self._residual_end(e, herb, p.disable_turns, "disable")
                p.disable_slot = p.disable_turns = 0
            else:
                moves = self._occupant(pos).sheet["moves"]
                if ident not in moves:
                    raise lines.Stop("disable-move-unknown")
                p.disable_slot = moves.index(ident) + 1
                # its count (the record): one less when the target has its move ahead or Cursed Body sets it
                # (dfi_disable_start: the effect comes from the holder's own action in progress)
                by_ability = e[3] == trace_to_c.CAUSE["ABILITY"]
                p.disable_turns = DISABLE_TURNS - (1 if by_ability or p.move_queued else 0)
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_IMPRISON:
            self._at(pos).imprison = 1  # -start|X|move: Imprison (step G38): no end line, it ends with the occupant
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_LEECH_SEED:
            # -start|X|move: Leech Seed (step G84, decision 0047, no [of], no end line): the source is the user of the move
            # line before (the holder of a Magic Bounce reflection); a start after any other line is no case of the engine
            last = self._last_move
            if last is None or last[1] != self._leech_seed or last[0] == pos:
                raise lines.Stop("leech-seed-source-unknown")
            self._at(pos).leech_source = last[0] + 1
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_YAWN:
            self._at(pos).yawn = YAWN_TURNS  # -start|X|move: Yawn|[of] source (step G31); its end line is [silent], above
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_MUST_RECHARGE:
            self._at(pos).must_recharge = 1  # -mustrecharge|X: a recharge move hit (step G17)
        elif kind == EV["CONFUSED"]:
            p = self._at(pos)
            p.acted = 1
            p.glaive_rush = 0  # the action began (a confused self-hit shows no move line)
            self._move_action(p)
            p.confused_action = True  # the action's own move or [cant] line follows, or its self-hit
            p.turn_done, p.move_queued = True, False
        elif kind in (EV["DAMAGE"], EV["HEAL"]):
            m = self._occupant(pos)
            if kind == EV["DAMAGE"] and e[3] == trace_to_c.CAUSE["CONFUSION"]:
                self._at(pos).confused_action = False  # the self-hit ends the action the confusion line began
            if kind == EV["DAMAGE"] and e[3] == trace_to_c.CAUSE["NONE"] and self._last_move is not None \
                    and self._last_move[0] != pos:
                # timesAttacked: a damaging hit of another Pokemon's move (a -damage line without a source)
                user = self._at(self._last_move[0])
                if self._last_move[1] in self._hit_pivots and user.occupant != ROSTER_NONE and not user.fainted \
                        and self._can_switch(self._last_move[0] // 2):
                    user.flag = self._hit_pivots[self._last_move[1]]
                p = self._at(pos)
                p.hits_taken = min(p.hits_taken + 1, HITS_TAKEN_MAX)
                if (self._last_move[1] == self._knock_off and self._unburden is not None
                        and self._ability_at(pos) == self._unburden and not p.flags & FLAG_UNBURDEN
                        and self._item_of(m) and not m.item_used):  # takeItem of a holder without an item: no event
                    # Unburden's onTakeItem answers Knock Off before the item may refuse (a Mega Stone): the volatile can
                    # be set with no line; an -enditem that follows shows the usual case (_unburden_unseen, record.py)
                    p.unburden_unseen = True
            if kind == EV["DAMAGE"] and e[3] == trace_to_c.CAUSE["LEECH_SEED"]:
                # the drain (dfi_leech_drain): `[of]` names the seed's source slot; any other holder or source is no case
                # of the engine (a seed whose start the tracker did not see)
                if self._at(pos).leech_source == 0 or e[2] != self._at(pos).leech_source - 1:
                    raise lines.Stop("leech-seed-drain-source")
            if kind == EV["DAMAGE"] and hp != 0:
                self._hurt(pos, e[3])
            if kind == EV["DAMAGE"] and e[3] == trace_to_c.CAUSE["POISON"] and m.toxic:
                m.toxic_stage = min(m.toxic_stage + 1, TOXIC_STAGE_MAX)  # tox's residual: the stage first, then the damage
            if public:
                m.hp_percent, m.hp_flag = hp, hp_flag
            else:
                self._own_display(m, hp, e[7])
            if kind == EV["HEAL"] and e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._healing_wish:
                # dfi_wish_heal: the entrant's full heal ends the wish and its status (clearStatus, silent: no cure line)
                self._at(pos).wish = 0
                m.status, m.freeze_turns = 0, 0
                m.toxic = m.toxic_stage = 0
                m.sleep_cant = 0  # decision 0066
        elif kind == EV["REVIVE"]:
            # Step G52 (decision 0025): Revival Blessing brings a fainted member of the user's side back at half HP,
            # its status cured; ident is its roster index (the line names it without a position)
            m = self._member(pos // 2)[ident]
            if public:
                m.hp_percent, m.hp_flag = hp, hp_flag
            else:
                self._own_display(m, hp, e[7])
            m.status = 0
            m.sleep_cant = 0  # decision 0066: the revival cures the sleep and its count
            user = self._rb_pending.pop(pos // 2, None)
            if user is not None:
                self._at(user).flag = 0  # the revive answers the request: the flag goes
        elif kind == EV["STATUS"]:
            m = self._occupant(pos)
            if public:
                m.status = detail
            m.freeze_turns = FREEZE_TURNS if detail == STATUS["frz"] else 0
            m.toxic = 1 if detail == STATUS["tox"] else 0
            m.toxic_stage = 0  # tox's onStart
            m.sleep_cant = 0  # decision 0066: a new sleep counts from 0 (the status line of a sleep is public for both)
        elif kind == EV["CURE_STATUS"]:
            m = self._occupant(pos)
            if public:
                m.status = 0
            m.freeze_turns = 0
            m.toxic = m.toxic_stage = 0
            m.sleep_cant = 0  # decision 0066: the cure ends the sleep and its count
        elif kind in (EV["BOOST"], EV["UNBOOST"]):
            p = self._at(pos)
            sign = 1 if kind == EV["BOOST"] else -1
            last = self._last_move
            if amount > 0 and last is not None and last[1] == self._parting_shot and last[2] == pos:
                self._at(last[0]).flag = SWITCH_MOVE  # Parting Shot switches its user once it changes a stat (Contrary too)
            p.stages[detail] = min(12, max(0, p.stages[detail] + sign * amount))
            if kind == EV["BOOST"] and amount > 0:
                p.raised = 1  # statsRaisedThisTurn: a stage really rose
            if kind == EV["UNBOOST"] and amount > 0:
                p.lowered = 1  # statsLoweredThisTurn (G88, dfi_boost): a stage really fell
        elif kind == EV["SWAP"]:
            # Ally Switch (step G80, decision 0044; sim/battle.ts swapPosition): the user and its partner change
            # positions with everything that rides on the Pokemon (_swap_positions: an explicit field list, not an object swap)
            self._swap_positions(pos, e[2])
            if pos // 2 == self.side and self._party is not None:
                # side.pokemon: the two actives exchange their entries (sim/battle.ts:1598-1599)
                self._party[pos % 2], self._party[e[2] % 2] = self._party[e[2] % 2], self._party[pos % 2]
        elif kind == EV["COPY_BOOST"]:
            # Psych Up (step G80): the user takes the target's seven stages (-copyboost; the copied crit volatiles
            # are silent decision 0018 features)
            self._at(pos).stages = list(self._at(e[2]).stages)
        elif kind == EV["CLEAR_ALL_BOOSTS"]:
            # Haze (step G62, decision 0031; data/moves.ts haze onHitField: clearBoosts on getAllActive): every standing
            # active Pokemon's stages return to neutral
            for p in (p for side in self._positions for p in side):
                if p.occupant != ROSTER_NONE and not p.fainted:
                    p.stages = [STAGE_NEUTRAL] * 7
        elif kind == EV["CONFUSION_START"]:
            self._at(pos).confused = 1
        elif kind == EV["CONFUSION_END"]:
            self._at(pos).confused = 0
        elif kind == EV["FLASH_FIRE"]:
            self._at(pos).flash_fire = 1
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_CURSE:
            # The Ghost Curse (step G84b, decision 0063): the holder's CURSED bit, shown to both viewers; the holder's
            # leaving or faint clears it (reset), the source's does not (the residual goes on)
            self._at(pos).cursed = 1
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_PERISH:
            # Perish Song's count (step G26): the residual's -start|X|perishN, N = 3, 2, 1, then perish0 before the
            # holder faints; the cast's own perish3 line is [silent] (no event), so nothing shows until the first count
            self._at(pos).perish = amount
        elif kind == EV["ABILITY"] and e[3] in (trace_to_c.CAUSE["ABILITY"], trace_to_c.CAUSE["MOVE"]):
            # An ability that changed until the occupant leaves or Mega Evolves (the tail's ability_now): Trace's copy
            # (step AC1, -ability|X|NEW|...|[from] ability: Trace: cause ABILITY, the new ability in id2) or a Skill Swap
            # (step G70, decision 0041: cause MOVE, the holder's new ability in id). A swap ends the old abilities:
            # Flash Fire's and Unburden's volatiles go with no line (sim/battle.ts:1325-1326).
            p = self._at(pos)
            new = ident2 if e[3] == trace_to_c.CAUSE["ABILITY"] else ident
            if e[3] == trace_to_c.CAUSE["MOVE"]:
                p.flash_fire = 0
                p.flags &= ~FLAG_UNBURDEN
            p.ability_now = new if new != self._member(pos // 2)[p.occupant].ability else 0
        elif kind in (EV["VOLATILE_START"], EV["VOLATILE_END"]) and detail == trace_to_c.VOLATILE_ENCORE:
            # Encore (step G9): -start|X|Encore forces the slot of the target's last move line (the move must be on
            # its sheet, or the pin's onStart fails without the line); -end|X|Encore (the duration, a used-up move,
            # Mental Herb) and the occupant's leaving end it. A last move the lines do not tie to a slot stops.
            p = self._at(pos)
            if kind == EV["VOLATILE_END"]:
                p.encore_slot = p.encore_turns = 0
            elif p.last_slot in (1, 2, 3, 4):
                p.encore_slot = p.last_slot
                p.encore_turns = ENCORE_TURNS + (1 if p.turn_done else 0)  # one more when it has no move left this turn
            else:
                raise lines.Stop("encore-slot-unknown")
        elif kind == EV["PROTECT"]:
            p = self._at(pos)
            p.protecting = 1
            p.chain = min(p.chain + 1, STALL_LEVEL_MAX)
            p.stall = STALL_DURATION
        elif kind == EV["FAIL"] and e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._ally_move and self._ally_move is not None:
            self._as_pending = None
            self._ally_pass(self._at(pos))  # the roll passed; the onHit found no partner (NOT_FAIL, null)
        elif kind == EV["FAIL"] and e[3] == trace_to_c.CAUSE["NONE"] and self._last_move is not None \
                and self._last_move[0] == pos and self._last_move[1] in self._move_pivots:
            self._at(pos).flag = 0  # Baton Pass or Revival Blessing failed: no switch
        elif kind == EV["FAIL"] and e[3] == trace_to_c.CAUSE["NONE"]:
            # Only the move's own failure is a failed Protect or guard. A FAIL with a cause is another effect of the
            # same position: an Intimidate that the holder's Inner Focus stopped (cause ABILITY, duoforge.h
            # DUOFORGE_EVENT_FAIL) leaves the stall chain as it is.
            if self._last_move is not None and self._last_move[0] == pos and self._last_move[1] in self._stall_moves:
                p = self._at(pos)
                p.chain = p.stall = 0
            elif (self._last_move is not None and self._last_move[0] == pos and self._last_move[1] in self._guard_moves
                  and self._at(pos).guard_undo is not None):
                p = self._at(pos)
                p.chain, p.stall = p.guard_undo  # the guard failed (nobody acts after it): no stall added
                p.guard_undo = None
        elif kind == EV["WEATHER"]:
            if not flags & FLAG["UPKEEP"]:
                self._weather = detail
                self._weather_turns = self._field_turns_next if detail else 0
        elif kind == EV["FIELD_START"]:
            if detail == 2:
                self._trick_room = FIELD_TURNS
            else:
                # DUOFORGE_FIELD_* -> the observation's DUOFORGE_TERRAIN_*: Grassy, Psychic (Team C), Electric and Misty
                # (POOL, step G25)
                self._terrain, self._terrain_turns = _TERRAIN[detail], self._field_turns_next
        elif kind == EV["FIELD_END"]:
            if detail == 2:
                self._trick_room = 0
            else:
                self._terrain = self._terrain_turns = 0
        elif kind in (EV["SIDE_START"], EV["SIDE_END"]) and amount in _HAZARD:
            # an entry hazard (step G37): every -sidestart line lays one layer, up to the move's maximum; its -sideend
            # (Toxic Spikes that a grounded Poison type absorbed, the one removal the engine models) clears it
            field, top = _HAZARD[amount]
            # The Counter keeps the kinds that are up in the order they were created (the record's hazard_order): a
            # further layer keeps its place, an ended kind leaves, one put up again goes last.
            layers = self._hazards[detail]
            if kind == EV["SIDE_START"]:
                layers[field] = min(layers[field] + 1, top)
            else:
                layers.pop(field, None)
        elif kind == EV["SIDE_START"]:
            index = _SIDE_CONDITION[amount]
            turns = TAILWIND_TURNS
            if amount != 1:
                # a screen (Reflect, Light Screen, Aurora Veil, step G20): 5 turns, 8 when the user holds Light Clay
                # (durationCallback); the user is the last move line's
                user = self._occupant(self._last_move[0])
                turns = SCREEN_TURNS_CLAY if self._holds(user, "LIGHTCLAY") else SCREEN_TURNS
            self._conditions[detail][index] = turns
        elif kind == EV["SIDE_END"]:
            self._conditions[detail][_SIDE_CONDITION[amount]] = 0
        elif kind == EV["ITEM_END"]:
            m = self._occupant(pos)
            m.revealed |= REVEALED_ITEM_CONSUMED
            self._at(pos).unburden_unseen = False
            if self._mental_herb is not None and ident2 == self._mental_herb + 1:
                self._herb_end = pos  # its -end lines follow (dfi_mental_herb)
            if e[3] == trace_to_c.CAUSE["NONE"] and self._eject_button is not None and ident2 == self._eject_button + 1:
                self._at(pos).flag = SWITCH_EMERGENCY_EXIT  # Eject Button sets its holder's switchFlag, then the -enditem
            if e[3] != trace_to_c.CAUSE["ITEM_TAKEN"]:
                m.item_consumed = 1  # used up (useItem, eatItem); a taken item is not
            if public:
                m.item_used = 1
            if e[3] == trace_to_c.CAUSE["ITEM_TAKEN"]:
                # a move took the item (Knock Off, Thief, Trick, Switcheroo, Bug Bite; steps G16, G29, G64): the member
                # holds nothing, also after a switch or a faint (the tail's item_now)
                m.item_now = ITEM_NOW_NONE
            if self._unburden is not None and self._ability_at(pos) == self._unburden:
                self._at(pos).flags |= FLAG_UNBURDEN  # Unburden doubles Speed once the item is gone (c08 battles)
        elif kind == EV["ITEM_START"]:
            # a move gave the member an item (Trick, Switcheroo, Thief, Covet; step G29): it holds it now, its old item is
            # no longer "gone"; the one it came from ([of], Thief and Covet) holds nothing. A Choice item that comes
            # ends the receiver's lock (the item's onStart).
            self._item_received(pos, ident2, public)
            if e[2] != NOPOS:
                giver = self._occupant(e[2])
                giver.item_now = ITEM_NOW_NONE
                giver.revealed |= REVEALED_ITEM_CONSUMED
                if e[2] // 2 != self.side or self._spectator:
                    giver.item_used = 1
                if self._unburden is not None and self._ability_at(e[2]) == self._unburden and not self._at(e[2]).fainted:
                    self._at(e[2]).flags |= FLAG_UNBURDEN  # takeItem's TakeItem event (Covet prints no -enditem)
        elif kind == EV["SINGLE_TURN"]:
            if ident == self._follow_me:
                self._at(pos).flags |= FLAG_FOLLOW_ME  # this turn (c11 battles)
            elif ident == self._helping_hand:
                self._at(pos).flags |= FLAG_HELPING_HAND  # on the boosted ally, this turn (c09 battles)
            elif ident == self._wide_guard:
                # Wide Guard (step G7): the side's guard for this turn (the residual ends it, a Feint breaks it), which
                # only a PIVOT inside the turn shows
                self._guards.add(("WIDE_GUARD", pos // 2))
            elif ident == self._rage_powder:
                # Rage Powder (step G30): the extension's RAGE_POWDER bit for this turn, which only a PIVOT inside the
                # turn shows (the residual ends it); the base view's Follow Me flag stays off for it
                self._at(pos).rage_powder = 1
        elif kind == EV["VOLATILE_START"] and detail == trace_to_c.VOLATILE_SPEED_SWAP:
            # Speed Swap (step K3): both positions carry the presence bit; the swapped values are not public
            self._at(pos).speed_swapped = 1
            self._at(e[2]).speed_swapped = 1
        elif kind == EV["FORME"]:
            # the view keeps the set's species; MEGA sets is_mega and the ability. A forme change rebuilds the stored stats
            # (setSpecies), so a live Speed Swap of the position ends (step K3)
            self._at(pos).speed_swapped = 0
        elif kind == EV["MEGA"]:
            self._mega_used[pos // 2] = 1
            self._at(pos).speed_swapped = 0  # formeChange -> setSpecies rebuilds the stored stats (step K3)
            self._at(pos).ability_now = 0  # the Mega forme's ability replaces a copied one (formeChange -> setAbility)
            self._at(pos).type_now = (0, 0)  # and setType(species.types) ends a type that Soak set
            self._occupant(pos).revealed |= REVEALED_MEGA
            self._at(pos).unburden_unseen = False  # the Mega forme's ability ends Unburden's volatile
            # the Mega forme and its ability, at once for both sides: an own member's request shows them only at the next
            # decision point, and the Pressure of the lines between reads the ability (_pressure_extra)
            m = self._occupant(pos)
            m.is_mega = 1
            m.ability = self.data.ability_of(self.data.mega_of(m.sheet["species"], m.sheet["item"]))
        elif kind == EV["PREPARE"]:
            p = self._at(pos)
            m = self._occupant(pos)
            p.charge = CHARGE_TURNS
            p.locked_slot = m.sheet["moves"].index(ident)
            if not foe:
                p.locked_target = self._own_target(pos % 2)
        elif kind == EV["ANIMATION"]:
            p = self._at(pos)
            if p.charge == CHARGE_TURNS and self._last_move is not None and self._last_move[0] == pos:
                # The charge turn's move fired at once (Electro Shot in rain): nothing stays charged.
                p.charge, p.locked_slot, p.locked_target = 0, MOVE_SLOT_NONE, TARGET_NONE
        elif kind == EV["UPKEEP"]:
            self._upkeep()
            self._after_upkeep = True
            self._turn_scoped.clear()
            self._guards.clear()
        elif kind == EV["RESULT"]:
            self.ended = True

    def _can_switch(self, side):
        """A member of `side` can come in (src/combat/turn.c dfi_can_switch): one brought, not fainted and not active, as
        far as the lines showed (a member seen at 0 percent is gone; one never seen stands)."""
        members = self._member(side)
        brought = len(self._picks) if side == self.side and self._picks is not None else self._teamsize[side]
        if brought is None:
            raise ValueError(f"no brought count for side {side}")
        gone = sum(1 for m in members if m.seen and m.hp_percent == 0)
        standing = sum(1 for p in self._positions[side] if p.occupant != ROSTER_NONE and not p.fainted)
        return brought - gone - standing > 0

    @staticmethod
    def _move_action(p):
        """One move action of the occupant of `p` (the record's move_actions: every MOVE action the queue runs for a
        standing occupant, src/combat/turn.c dfi_run_move_body): its first line, a [move], a [cant] or the confusion's
        -activate; the line after that confusion line belongs to the same action."""
        if p.confused_action:
            p.confused_action = False
            return
        p.move_actions = min(p.move_actions + 1, 255)

    @staticmethod
    def _own_display(member, hp, hp_max):
        """An own member's HP as its opponent is shown it (the public record's knowledge): the display of the exact HP of
        an own line (hp of hp_max), from the library."""
        from duoforge import view
        member.hp_percent, member.hp_flag = view.hp_display(hp, hp_max)

    def _own_target(self, slot):
        """The target position the own accepted choice gave the move of `slot`."""
        if self._accepted is None:
            raise ValueError("an own two-turn move without an accepted choice")
        words = self._accepted.split(", ")[slot].split(" ")
        if words[0] != "move" or len(words) < 3:
            raise ValueError(f"an own two-turn move without a target: {self._accepted!r}")
        return trace_to_c.abs_target(self.side, int(words[2]))

    def _swap_positions(self, user, partner):
        """Ally Switch's exchange of the flat positions `user` and `partner` (dfi_swap_position_state, decision 0044 section 10):
        the fields of _SWAP_MOVES go with the Pokemon, those of _SWAP_SLOT stay, and what names a swapped position follows it:
        the trap source of every position (a trapper's flat position + 1) and the Attract source position of every infatuated
        one (the engine derives it from the member code, which does not change). A pending Healing Wish on either slot is the
        engine's E_UNSUPPORTED (its onSwap heal is not modelled): an explicit stop, before anything changes."""
        a, c = self._at(user), self._at(partner)
        if a.wish or c.wish:
            raise lines.Stop("ally-switch-healing-wish")
        self._as_pending = None
        self._ally_pass(a)  # a passed consecutive roll (or the first use): the counter goes up (before the swap, as the engine)
        for name in _SWAP_MOVES:
            va, vc = getattr(a, name), getattr(c, name)
            setattr(a, name, vc)
            setattr(c, name, va)
        for p in (p for side in self._positions for p in side):
            if p.trap_source == user + 1:
                p.trap_source = partner + 1
            elif p.trap_source == partner + 1:
                p.trap_source = user + 1
            if p.attract:
                if p.attract_from == user:
                    p.attract_from = partner
                elif p.attract_from == partner:
                    p.attract_from = user

    def _ally_pass(self, p):
        """Ally Switch's counter after a passed roll: the first use starts at level 1 (no roll), a later one goes up to 6;
        either way the duration is 2 turns (dfi_ally_switch_prepare)."""
        p.ally_level = 1 if p.ally_level == 0 else min(6, p.ally_level + 1)
        p.ally_turns = 2

    def _upkeep(self):
        def down(n):
            return n - 1 if n > 0 else 0
        for side in (0, 1):
            for p in self._positions[side]:
                if p.ally_level:
                    if p.ally_turns <= 1:
                        p.ally_level = p.ally_turns = 0  # the residual's end: turns 1 -> 0 (the volatile is deleted)
                    else:
                        p.ally_turns -= 1
        self._weather_turns = down(self._weather_turns)
        self._terrain_turns = down(self._terrain_turns)
        self._trick_room = down(self._trick_room)
        self._conditions = [[down(n) for n in c] for c in self._conditions]
        for side in self._positions:
            for p in side:
                p.flag = SWITCH_FAINTED if p.fainted else 0  # checkFainted at the end of the turn; no other flag carries over
                p.protecting = 0
                p.flags &= ~(FLAG_FOLLOW_ME | FLAG_HELPING_HAND)  # single-turn
                p.rage_powder = 0
                if p.stall:
                    p.stall -= 1
                    if not p.stall:
                        p.chain = 0
                if p.charge:
                    p.charge -= 1
                    if not p.charge:
                        p.locked_slot, p.locked_target = MOVE_SLOT_NONE, TARGET_NONE
                p.throat_chop = down(p.throat_chop)  # its residual end is silent
                p.encore_turns = down(p.encore_turns)
                # the residual counts (orders 15, 17, 20, 23); each end at 0 shows its line, which the fold read already
                p.taunt, p.heal_block, p.yawn = down(p.taunt), down(p.heal_block), down(p.yawn)
                p.disable_turns = down(p.disable_turns)

    def _hurt(self, pos, cause):
        """hurtThisTurn (G88, dfi_deal_ex): a spread damage that leaves its target standing. Every damage line is spread
        damage except the directDamage of a user's own cost: Struggle's recoil ([from] Recoil after a Struggle line of
        the same position) and the plain -damage of DIRECT_COST_MOVES on their user. A plain -damage on the
        user of another move is no line the engine makes: it stops the tracker rather than guess."""
        last = self._last_move
        own = last is not None and last[0] == pos
        if own and cause == trace_to_c.CAUSE["RECOIL"] and last[1] == self._struggle:
            return
        if own and cause == trace_to_c.CAUSE["NONE"]:
            if last[1] in self._direct_costs:
                return
            raise lines.Stop("line:-damage of the move's own user")
        self._at(pos).hurt = 1

    def _pressure_extra(self, pos, move, target, flags):
        """The extra PP a move use costs for the user's standing foes with Pressure (decision 0030, step G53), counted
        only where the line shows the targets: the named target of a single-target move, every standing foe for the
        spread classes, for "all" and for a MUSTPRESSURE move; none for a foeSide move or a blanked ([still])
        target, which nobody can know. A [spread] line of a single-target move (Expanding Force on Psychic Terrain:
        onModifyMove runs before getMoveTargets, sim/battle-actions.ts useMoveInner) counts every standing foe as
        well: its pressureTargets are all adjacent foes, a foe its Protect leaves out of the [spread] list included."""
        if self._pressure is None or flags & FLAG["STILL"]:
            return 0
        foe = 1 - pos // 2
        members = self._member(foe)
        holders = [k for k, p in enumerate(self._positions[foe]) if p.occupant != ROSTER_NONE and not p.fainted
                   and p.occupant < len(members) and (p.ability_now or members[p.occupant].ability) == self._pressure]
        if not holders:
            return 0
        kind = self.data.target_type(move)
        if self.data.move_flags(move) & _MUST_PRESSURE or kind in ("all", "allAdjacentFoes", "allAdjacent"):
            return len(holders)
        if flags & FLAG["SPREAD"]:
            # a single-target class turned spread (onModifyMove: allAdjacentFoes) hits every adjacent foe; an "allies"
            # move's [spread] list is the user's side (alliesAndSelf), no foe
            return len(holders) if kind in ("normal", "any", "adjacentFoe") else 0
        if kind == "foeSide" or target == NOPOS or target // 2 != foe:
            return 0
        return int(target % 2 in holders)

    # ------------------------------------------------------------------ output
    def boundary(self):
        r = self.request
        if r.get("teamPreview"):
            return TEAM_SELECTION
        if "active" in r:
            return TURN
        return REPLACEMENT if "|upkeep" in self._step_lines else PIVOT

    def _requested(self, side, boundary):
        """(requested, requested slots) of a side at the decision point."""
        r = self.request
        if side == self.side:
            if r.get("wait"):
                return 0, 0
            if boundary == TEAM_SELECTION:
                return 1, 0
            if boundary == TURN:
                return 1, self._occupied(side)
            return 1, sum(1 << k for k, flag in enumerate(r["forceSwitch"]) if flag)
        if boundary == TEAM_SELECTION:
            return 1, 0
        if boundary == TURN:
            return 1, self._occupied(side)
        slots = self._foe_switch_slots(side, boundary)
        return (1, slots) if slots else (0, 0)

    def _occupied(self, side):
        return sum(1 << k for k, p in enumerate(self._positions[side]) if p.occupant != ROSTER_NONE)

    def _foe_switch_slots(self, side, boundary):
        """The foe positions asked to switch (src/combat/turn.c dfi_finish_turn, dfi_pivot): the flagged ones
        (a faint at the end of the turn, Emergency Exit, Parting Shot); a fainted one and any at a PIVOT only
        while the foe has a reserve (brought, unseen or on the bench, standing)."""
        members = self._member(side)
        gone = sum(1 for m in members if m.seen and m.hp_percent == 0)
        standing = sum(1 for p in self._positions[side] if p.occupant != ROSTER_NONE and not p.fainted)
        brought = self._teamsize[side]
        if brought is None:
            raise ValueError("no |teamsize| line for the foe")
        reserve = brought - gone - standing > 0
        out = 0
        for k, p in enumerate(self._positions[side]):
            if p.occupant == ROSTER_NONE or not p.flag:
                continue
            # Revival Blessing's request is made with no check of a living reserve (src/combat/turn.c: the revive answers it)
            if reserve or (boundary == REPLACEMENT and not p.fainted) or p.flag == _ENC["DFI_SWITCH_REVIVE_BLESSING"]:
                out |= 1 << k
        return out

    def observation(self):
        """The OBSERVATION record DuoForge shows this player at the current decision point."""
        if not self.ready:
            raise ValueError("no decision point")
        o = np.zeros((), dtype=_layout.OBSERVATION)
        boundary = self.boundary()
        o["epoch"], o["boundary_kind"], o["player"] = self.epoch, boundary, self.side
        requested, slots = self._requested(self.side, boundary)
        o["requested"], o["slot_mask"] = requested, slots
        o["turn"] = self._turn
        o["weather"], o["weather_turns"] = self._weather, self._weather_turns
        o["terrain"], o["terrain_turns"] = self._terrain, self._terrain_turns
        o["trick_room_turns"] = self._trick_room
        for side in (0, 1):
            self._view_side(o["sides"][side], side, boundary)
        return o

    def _shown_locked_slot(self, p, own):
        """The locked slot the view shows: a running two-turn move's or a Choice lock's, but none for a foe whose last
        move is a lockedmove, whose drawn length may end silently (src/state/observation.c, dfi_maybe_lockedmove)."""
        if not own and p.last_move is not None and self.data.move_flags(p.last_move) & _LOCKED_MOVE:
            return MOVE_SLOT_NONE
        return p.locked_slot if p.locked_slot != MOVE_SLOT_NONE else p.choice_slot

    def _view_side(self, v, side, boundary):
        own = side == self.side
        members = self._member(side)
        v["member_count"] = len(members)
        for m, member in enumerate(members):
            self._view_member(v["members"][m], member, m, side, own, boundary)
        for k, p in enumerate(self._positions[side]):
            pv = v["positions"][k]
            pv["locked_slot"], pv["locked_target"] = MOVE_SLOT_NONE, TARGET_NONE
            if p.occupant == ROSTER_NONE:
                pv["stages"] = [STAGE_NEUTRAL] * 7
                continue
            pv["stages"] = p.stages
            pv["confused"], pv["charging"] = p.confused, 1 if p.charge else 0
            pv["locked_slot"] = self._shown_locked_slot(p, own)
            holder = members[p.occupant]
            gone = holder.item_used or holder.item_now == ITEM_NOW_NONE
            # Unburden doubles the Speed only while the item is gone: an item a move gave hides the flag
            pv["reserved"] = p.flags if gone else p.flags & ~FLAG_UNBURDEN
            if own and p.charge:
                pv["locked_target"] = p.locked_target
            pv["acted"], pv["protect_chain"] = p.acted, p.chain
            pv["flash_fire"], pv["protecting"] = p.flash_fire, p.protecting
        v["occupant"] = [p.occupant for p in self._positions[side]]
        v["mega_used"] = self._mega_used[side]
        order = [ROSTER_NONE] * 6
        if own and self._picks is not None:
            order[:len(self._picks)] = self._picks
        v["brought_order"] = order
        requested, slots = self._requested(side, boundary)
        v["requested"], v["requested_slots"] = requested, slots
        v["reflect_turns"], v["light_screen_turns"], v["tailwind_turns"] = self._conditions[side][:3]

    def _view_member(self, v, member, m, side, own, boundary):
        sheet = member.sheet
        count = len(sheet["moves"])
        v["species_id"] = sheet["species"]  # the set's species; a Mega Evolution shows as is_mega
        v["move_count"] = count
        v["mega_capable"] = 1 if member.mega_capable else 0
        v["gender"], v["nature"] = sheet["gender"], sheet["nature"]
        v["ability"], v["item"] = member.ability, sheet["item"]
        v["move_ids"][:count] = sheet["moves"]
        v["pp_max"][:count] = member.pp_max
        # item_used: the sheet's item is gone (a member without one has none to lose, whatever it got and used since)
        v["is_mega"], v["item_used"] = member.is_mega, member.item_used if sheet["item"] else 0
        active = any(p.occupant == m for p in self._positions[side])
        if own:
            v["hp"], v["hp_max"], v["hp_kind"], v["pp_kind"] = member.hp, member.hp_max, HP_EXACT, PP_EXACT
            v["pp"][:count] = [mx - u for mx, u in zip(member.pp_max, member.uses)]
            v["stats"] = member.stats
            v["stat_points"] = sheet["sp"]
            v["status"] = member.status if member.hp != 0 else 0
            if boundary == TEAM_SELECTION:
                v["location"] = UNDETERMINED
            elif active:
                v["location"] = ACTIVE
            elif self._picks is not None and m in self._picks:
                v["location"] = BENCH
            else:
                v["location"] = NOT_BROUGHT
            return
        v["pp_kind"] = PP_DERIVED
        v["pp"][:count] = [max(mx - u, 0) for mx, u in zip(member.pp_max, member.uses)]
        if member.seen:
            v["hp"], v["hp_flag"], v["hp_max"], v["hp_kind"] = member.hp_percent, member.hp_flag, 100, HP_PERCENT
            v["location"] = ACTIVE if active else BENCH
            v["status"] = member.status if member.hp_percent != 0 else 0
        else:
            v["hp_kind"], v["location"] = HP_UNKNOWN, UNDETERMINED

    def request_record(self):
        """The REQUEST record of the decision point as the engine sets it (duoforge_battle_request): the epoch, the
        boundary, the player, whether it is requested and the positions that need a command. candidate_count stays 0: the
        engine's joint domain excludes pairs by rules the tracker does not hold (its domain() pair mask is provisional), and
        the honest search does not read it."""
        if not self.ready:
            raise ValueError("no decision point")
        r = np.zeros((), dtype=_layout.REQUEST)
        boundary = self.boundary()
        requested, slots = self._requested(self.side, boundary)
        r["epoch"], r["boundary_kind"], r["player"] = self.epoch, boundary, self.side
        r["requested"], r["slot_mask"] = requested, slots
        return r

    def public_parts(self):
        """The player's parts of the decision point for the honest search (duoforge_search.record_roots.RecordRoots):
        dict(request, observation, record, status, causes, reason). record is the public record assembled from what the
        tracker folded (record.assemble) with status 0, or a zero record with status E_UNSUPPORTED, the cause mask that
        duoforge_battle_public_causes gives (0 for a refusal without a cause bit) and the named reason. An expected refusal
        never raises; the engine checks an assembled record (record.check, and the search's own round trip)."""
        from . import record
        observation = self.observation()
        rec, status, causes, reason = record.assemble(self, observation)
        return {"request": self.request_record(), "observation": observation, "record": rec, "status": status,
                "causes": causes, "reason": reason}

    def observation_ext(self):
        """The OBSERVATION_EXT record (decision 0018) DuoForge shows this player at the current decision point: the
        fields of the features this tracker folds (EXT_FIELDS), from the public lines; all zero under a kind without
        the extension (not POOL), as duoforge_battle_observe_ext gives it."""
        if not self.ready:
            raise ValueError("no decision point")
        o = np.zeros((), dtype=_layout.OBSERVATION_EXT)
        if self.data.kind != "pool":
            return o
        o["revision"], o["player"], o["epoch"] = EXT_REVISION, self.side, self.epoch
        o["supported"] = lines.LIBRARY_SUPPORTED
        for side in (0, 1):
            v = o["sides"][side]
            v["aurora_veil_turns"] = self._conditions[side][3]
            v["guard_flags"] = C["DUOFORGE_SIDE_GUARD_WIDE_GUARD"] if ("WIDE_GUARD", side) in self._guards else 0
            for field, _ in _HAZARD.values():
                v[field] = self._hazards[side][field]
            for m, member in enumerate(self._member(side)):
                v["members"][m]["item_now"] = member.item_now
            for k, p in enumerate(self._positions[side]):
                if p.occupant == ROSTER_NONE:
                    continue  # an empty position: all zero
                pv = v["positions"][k]
                pv["volatiles"] = sum(bit for name, bit in _PRESENCE_BITS if getattr(p, name))
                if p.type_now != (0, 0):
                    pv["volatiles"] |= C["DUOFORGE_POSITION_EXT_TYPE_CHANGED"]
                    pv["type_now"] = p.type_now
                pv["perish"], pv["encore_slot"], pv["disable_slot"] = p.perish, p.encore_slot, p.disable_slot
                if p.trap:  # POSITION_EXT2 bits 4 to 6: the elapsed count (zero without the trap)
                    o["volatiles2"][side][k] = sum(bit for n, bit in enumerate(EXT2_TRAP_ELAPSED) if p.trap_elapsed >> n & 1)
                own = self._member(side)[p.occupant].ability
                pv["ability_now"] = p.ability_now if p.ability_now != own else 0  # shown when it differs
                if p.attract:
                    o["volatiles2"][side][k] |= p.attract_from << _ATTRACT_SOURCE_SHIFT
        return o

    def domain(self):
        """The FACTORED_DOMAIN of the decision point (the provisional pair mask), and the slot lists."""
        r = self.request
        if r.get("wait"):
            return options.none_domain(self.epoch), None
        if r.get("teamPreview"):
            return options.team_domain(self.epoch, len(self.own_sheets), r["maxChosenTeamSize"]), None
        locked = {k: p.locked_target for k, p in enumerate(self._positions[self.side]) if p.charge}
        roster_of = {mon["ident"]: self._names[self.side][mon["ident"].split(": ", 1)[1]]
                     for mon in r["side"]["pokemon"]}
        lists = options.slot_options(r, self.side, roster_of, locked)
        return options.domain(lists, self.epoch), lists


def restrict_ext(ext, folds):
    """DuoForge's OBSERVATION_EXT record `ext` as a tracker that folds the features of the mask `folds` shows it: the
    header (revision, player, epoch, supported) and the EXT_FIELDS of those features, everything else zero. KeyError
    for a feature of the mask without an EXT_FIELDS entry."""
    out = np.zeros((), dtype=_layout.OBSERVATION_EXT)
    for name in ("revision", "player", "epoch", "supported"):
        out[name] = ext[name]
    for name, bit in lines.FEATURES.items():
        if not folds >> bit & 1:
            continue
        for where, field in EXT_FIELDS[name]:
            for s in (0, 1):
                src, dst = ext["sides"][s], out["sides"][s]
                if where == "bit":
                    dst["positions"]["volatiles"] = dst["positions"]["volatiles"] | (src["positions"]["volatiles"] & field)
                elif where == "v2bits":
                    out["volatiles2"][s] = out["volatiles2"][s] | (ext["volatiles2"][s] & field)
                elif where == "side_bit":
                    name, bit = field
                    dst[name] = dst[name] | (src[name] & bit)
                elif where == "side":
                    dst[field] = src[field]
                else:
                    group = "positions" if where == "position" else "members"
                    dst[group][field] = src[group][field]
    return out
