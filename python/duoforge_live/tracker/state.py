"""A position's and a member's folded state, and the closed-sheet contradiction.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

from .constants import MOVE_SLOT_NONE, ROSTER_NONE, STAGE_NEUTRAL, STATUS, TARGET_NONE


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
#     newly_switched), stall (chain, stall), confused, charge, locked_slot (locked_move) and locked_target, move_actions, flag
#     (switch_flag);
#   - the tail position (dfi_tail_pos), every volatile: substitute and the other tail fields the tracker does not fold are
#     features that stop it at their lines, the folded ones are throat_chop, must_recharge, taunt, yawn, imprison, glaive_rush,
#     rage_powder (the Follow Me flag), heal_block, attract and attract_from (the position's attract_source byte, see below),
#     trap, trap_source, trap_move, trap_band and trap_elapsed (the partial trap), type_now and type2 (Soak and Double Shock,
#     the roster member's soak_type and type2, which the record keys by occupant), leech_source (the seed), disable_slot and
#     disable_turns, encore_slot and encore_turns, cursed, perish, hits_taken, last_slot and last_move, result_now and
#     result_last (move_result), ability_now (the occupant's), ally_level and ally_turns (the Ally Switch counter);
#   - the position flags that ride on the Pokemon: STATS_RAISED (raised), LOWERED (lowered), HURT (hurt), CURSED (cursed);
#     DRAGON_CHEER and DESTINY_BOND are features whose lines stop the tracker, so they are never up here;
#   - the tracker's own scratch of the occupant's action and turn (confused_action, acted, move_queued, turn_done,
#     guard_undo, unburden_unseen, fainted), which the engine keeps in the queue records and the run (they follow the Pokemon).
_SWAP_MOVES = (
    "occupant", "activation", "stages", "protecting", "flash_fire", "flags", "choice_slot", "newly_switched", "chain", "stall",
    "confused", "charge", "locked_slot", "locked_target", "move_actions", "flag", "speed_swapped", "leech_source",
    "throat_chop", "must_recharge", "taunt", "yawn", "imprison", "glaive_rush", "rage_powder", "heal_block", "attract",
    "attract_from", "trap", "trap_source", "trap_move", "trap_band", "trap_elapsed", "type_now", "type2", "disable_slot",
    "disable_turns", "encore_slot", "encore_turns", "cursed", "perish", "hits_taken", "last_slot", "last_move", "result_now",
    "result_last", "ability_now", "ally_level", "ally_turns", "raised", "lowered", "hurt",
    "confused_action", "acted", "move_queued", "turn_done", "guard_undo", "unburden_unseen", "fainted")
# The seed (leech_source) is a volatile of the seeded Pokemon and goes with it; its value, the source's sourceSlot, is a slot and is
# not relinked (sim/pokemon.ts:2002: the drain goes to whoever stands there, the holder itself when it stands there, issue 541).
# locked_target goes with the Pokemon's locked action (issue 541, dfi_swap_position_state). What stays at its position (the slot's,
# not the Pokemon's): Healing Wish's bit 0 (the slot condition; a swap onto a pending one is refused before it gets here).
# Requested slots and sealed commands are not _Position fields: they belong to the request of the slot and the tracker keeps them
# by slot.
_SWAP_SLOT = ("wish",)


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
