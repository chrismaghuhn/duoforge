"""The tracker: one battle room as one player sees it.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

import collections
import json

from .. import lines
from ..data import trace_to_c
from .constants import (DIRECT_COST_MOVES, FIELD_TURNS, _HIT_PIVOTS, _kind, _MOVE_PIVOTS, PIVOT, ROOM_LINES,
                        ROSTER_NONE, SESSION_LINES, STAGE_NEUTRAL)
from .state import _Member, _Position
from .conditions import _ConditionFolds
from .sheets import _SheetReads
from .requests import _RequestFolds
from .events import _EventFolds
from .fold_event import _EventFold
from .actions import _ActionFolds
from .views import _Views


class Tracker(_ConditionFolds, _SheetReads, _RequestFolds, _EventFolds, _EventFold, _ActionFolds, _Views):
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
        self._gravity = 0  # K4 (#475): the Gravity turns of the field, 5 from its start (FIELD_START detail 6)
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
        self._trap_moves = data.partial_trap_moves  # the moves of the engine's partial trap (G90; #512 S1)
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

    def _turn_scoped_stop(self, boundary):
        """Stop at a PIVOT boundary while a single-turn feature of this turn is up and its bit is not supported."""
        if boundary == PIVOT and self._turn_scoped:
            raise lines.Stop(f"feature:{sorted(self._turn_scoped)[0]}")
