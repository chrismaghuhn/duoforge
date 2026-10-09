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
"""
import collections
import json

import numpy as np

from duoforge import _layout

from . import lines, options, teams
from .data import trace_to_c

C = _layout.CONSTANTS
EV = trace_to_c.EV
FLAG = trace_to_c.FLAG
_MUST_PRESSURE = _layout.CONSTANTS["DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE"]  # step G53
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
CHARGE_TURNS = 2  # twoturnmove's duration: the charge and the locked turn end in the second residual
STATUS = {"brn": 1, "frz": 2, "par": 3, "slp": 4, "psn": 5}

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
        self.flag = 0  # Showdown's switchFlag: asked to switch at the next switch request
        self.fainted = False
        self.reset()

    def reset(self):
        self.stages = [STAGE_NEUTRAL] * 7
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
        self.flags = 0  # DUOFORGE_POSITION_FLAG_* (TEAM_C and POOL): Follow Me, Helping Hand, Unburden
        self.guard_undo = None  # (chain, stall) before a Wide or Quick Guard, until it is known to have run


class _Member:
    def __init__(self, sheet, data):
        self.sheet = sheet
        self.ability = sheet["ability"]
        self.uses = [0] * len(sheet["moves"])
        self.pp_max = [data.pp_max(m) for m in sheet["moves"]]
        self.mega_capable = data.mega_capable(sheet["species"], sheet["item"])
        self.is_mega = 0
        self.item_used = 0
        self.seen = False
        self.hp_percent = 0
        self.hp_flag = 0
        self.status = 0
        # The own side, from the requests.
        self.hp = 0
        self.hp_max = 0
        self.stats = [0] * 5


class Tracker:
    """One battle room as one player sees it. feed() every message of the room in order, accepted() every
    own choice Showdown took; at a decision point (ready) observation() and domain() give DuoForge's view."""

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
        self._conditions = [[0, 0, 0], [0, 0, 0]]  # reflect, light screen, tailwind turns per side
        self._mega_used = [0, 0]
        self._picks = None
        self._accepted = None  # the own choice accepted at the last TURN decision point (it queued the moves)
        self._last_move = None  # (position, move id, target) of the last MOVE event
        self._parting_shot = data.tables["MOVE"]["PARTINGSHOT"]
        self._feint = data.tables["MOVE"].get("FEINT", -1)
        self._turn_scoped = set()  # single-turn features of decision 0018 seen since the turn began (lines.TURN_SCOPED)
        self._guards = set()  # (Wide or Quick Guard feature, side) seen this turn: what a Feint breaks (step G28)
        self._spectator = False  # the own side folded like the foe's, from the public lines (duoforge_replay)
        self.turn_scoped_seen = collections.Counter()  # single-turn feature lines seen, by feature (counters)
        tables = data.tables
        self._choice_items = {tables["ITEM"][k.upper()] + 1 for k in lines.CHOICE_ITEMS if k.upper() in tables["ITEM"]}
        self._unburden = tables["ABILITY"]["UNBURDEN"] + 1 if "UNBURDEN" in tables["ABILITY"] else None
        self._pressure = tables["ABILITY"]["PRESSURE"] + 1 if "PRESSURE" in tables["ABILITY"] else None
        self._follow_me = tables["MOVE"].get("FOLLOWME")
        # Protect and Detect both show "-singleturn|POKEMON|Protect"; a failed one resets the stall counter
        self._stall_moves = {tables["MOVE"][k] for k in ("PROTECT", "DETECT") if k in tables["MOVE"]}
        self._guard_moves = {tables["MOVE"][k] for k in ("WIDEGUARD", "QUICKGUARD") if k in tables["MOVE"]}
        self._helping_hand = tables["MOVE"].get("HELPINGHAND")

    # ------------------------------------------------------------------ input
    def feed(self, lines):
        for line in lines:
            kind = _kind(line)
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
            return
        self._extended_field(line)
        if line.startswith("|-clearnegativeboost|"):
            # White Herb (Team C): the [silent] line the converter skips, after its -enditem; the stages below
            # neutral return to it.
            p = self._at(trace_to_c.ev_pos(line.split("|")[2]))
            p.stages = [max(s, STAGE_NEUTRAL) for s in p.stages]
            return
        self._fold(line)

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
        item_id = self.data.tables["ITEM"].get(trace_to_c.key(item))
        if holder is not None and item_id is not None and holder.sheet["item"] == item_id + 1 and not holder.item_used:
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

    def ability_now(self, ident):
        """The current ability + 1 of the member a protocol ident names."""
        return self._member_of(ident).ability

    def _member_of(self, ident):
        side, name = int(ident[1]) - 1, ident.split(": ", 1)[1]
        if name not in self._names[side]:
            raise lines.Stop(f"structure:{ident} names no member seen yet")
        return self._member(side)[self._names[side][name]]

    def accepted(self, text):
        """The own choice Showdown accepted at the current decision point."""
        if self.request is not None and "active" in self.request:
            self._accepted = text
        if text.startswith("team "):
            self._picks = [int(c) - 1 for c in text[len("team "):]]

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
            ability = trace_to_c.key(mon["ability"])  # "noability": No Ability, 0 as parse_team has it
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

    def _fold(self, line):
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
        try:
            events = trace_to_c.step_events([line], viewer, self._names, maxhp, self.data.tables)
        except trace_to_c.ConversionError as e:  # a SystemExit: callers catch one kind of error
            detail = getattr(e, "detail", None)
            raise lines.Stop(f"converter:{e.rule}" + (f" {detail}" if detail else "")) from e
        except (KeyError, IndexError) as e:  # a form of a known line the parser does not know (untyped, as diff_driver)
            raise lines.Stop(f"converter:untyped {_kind(line)} {type(e).__name__} {e}") from e
        for e in events:
            self._event(e)

    def _at(self, pos):
        return self._positions[pos // 2][pos % 2]

    def _occupant(self, pos):
        p = self._at(pos)
        return None if p.occupant == ROSTER_NONE else self._member(pos // 2)[p.occupant]

    def _event(self, e):
        kind, pos, ident, ident2 = e[0], e[1], e[4], e[5]
        hp, hp_kind, hp_flag, status, detail, amount, flags = e[6], e[8], e[9], e[10], e[11], e[12], e[13]
        foe = pos != NOPOS and pos // 2 != self.side
        public = foe or (self._spectator and pos != NOPOS)  # folded from the public lines
        if kind == EV["TURN"]:
            self._turn = ident
            self._turn_scoped.clear()
            self._guards.clear()
        elif kind in (EV["SWITCH"], EV["DRAG"]):
            # A drag (Step G46) is a switch of the dragged-in member: the occupant is replaced and reset, the HP of the line.
            p = self._at(pos)
            p.occupant, p.flag, p.fainted = ident, 0, False
            p.reset()
            if public:
                m = self._member(pos // 2)[ident]
                m.seen, m.hp_percent, m.hp_flag, m.status = True, hp, hp_flag, status
        elif kind == EV["MOVE"]:
            p = self._at(pos)
            p.acted = 1
            self._last_move = (pos, ident, e[2])
            m = self._occupant(pos)
            if not flags & FLAG["LOCKED"] and ident in m.sheet["moves"]:
                m.uses[m.sheet["moves"].index(ident)] += 1 + self._pressure_extra(pos, ident, e[2], flags)
            if ident in self._guard_moves and not flags & FLAG["LOCKED"]:
                # Wide Guard and Quick Guard add the stall volatile when they run (data/moves.ts onHitSide
                # addVolatile('stall')), also when the side has the guard already (no -singleturn line then), the
                # counter a Protect reads: protect_chain counts them (g7_wide_guard_ally). A -fail undoes it.
                p.guard_undo = (p.chain, p.stall)
                p.chain = min(p.chain + 1, STALL_LEVEL_MAX)
                p.stall = STALL_DURATION
            if (p.choice_slot == MOVE_SLOT_NONE and m.sheet["item"] in self._choice_items and not m.item_used
                    and ident in m.sheet["moves"]):
                # A Choice item locks its holder into the move of its |move| line (data/items.ts onModifyMove,
                # set right before the line) until it leaves (c07 battles, Choice Scarf).
                p.choice_slot = m.sheet["moves"].index(ident)
        elif kind == EV["ACTIVATE"]:
            if e[3] == trace_to_c.CAUSE["ABILITY"] and ident2 == self.data.tables["ABILITY"]["EMERGENCYEXIT"] + 1:
                self._at(pos).flag = 1  # it leaves: asked to switch (id2 names an ability only with cause ABILITY)
            elif e[3] == trace_to_c.CAUSE["MOVE"] and ident2 == self._feint:
                # Feint broke something (step G28, sim/battle-actions.ts hitStepBreakProtect, printed only then): the
                # target's own Protect (its flag) and its stall volatile (chain and stall, a guard_undo that is no longer
                # open), and the Wide Guard and Quick Guard of the target's whole side, a partner's included. Only the
                # target's stall goes: a partner that set the guard keeps its own chain.
                p = self._at(pos)
                p.protecting = p.chain = p.stall = 0
                p.guard_undo = None
                for guard in ("WIDE_GUARD", "QUICK_GUARD"):
                    self._guards.discard((guard, pos // 2))
                    if not any(g[0] == guard for g in self._guards):
                        self._turn_scoped.discard(guard)
        elif kind == EV["FAINT"]:
            p = self._at(pos)
            p.reset()  # a faint clears the position's conditions; the occupant stays until replaced
            p.fainted = True
        elif kind == EV["CANT"]:
            # An ability's block (Armor Tail) names its holder; the move's user, [of], took the action.
            self._at(e[2] if e[3] == trace_to_c.CAUSE["ABILITY"] else pos).acted = 1
        elif kind == EV["CONFUSED"]:
            self._at(pos).acted = 1
        elif kind in (EV["DAMAGE"], EV["HEAL"]):
            if public:
                m = self._occupant(pos)
                m.hp_percent, m.hp_flag = hp, hp_flag
        elif kind == EV["STATUS"]:
            if public:
                self._occupant(pos).status = detail
        elif kind == EV["CURE_STATUS"]:
            if public:
                self._occupant(pos).status = 0
        elif kind in (EV["BOOST"], EV["UNBOOST"]):
            p = self._at(pos)
            sign = 1 if kind == EV["BOOST"] else -1
            last = self._last_move
            if amount > 0 and last is not None and last[1] == self._parting_shot and last[2] == pos:
                self._at(last[0]).flag = 1  # Parting Shot switches its user once it changes a stat (Contrary too)
            p.stages[detail] = min(12, max(0, p.stages[detail] + sign * amount))
        elif kind == EV["CONFUSION_START"]:
            self._at(pos).confused = 1
        elif kind == EV["CONFUSION_END"]:
            self._at(pos).confused = 0
        elif kind == EV["FLASH_FIRE"]:
            self._at(pos).flash_fire = 1
        elif kind == EV["PROTECT"]:
            p = self._at(pos)
            p.protecting = 1
            p.chain = min(p.chain + 1, STALL_LEVEL_MAX)
            p.stall = STALL_DURATION
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
                self._terrain, self._terrain_turns = (1 if detail == 1 else 2), self._field_turns_next
        elif kind == EV["FIELD_END"]:
            if detail == 2:
                self._trick_room = 0
            else:
                self._terrain = self._terrain_turns = 0
        elif kind == EV["SIDE_START"]:
            index = {1: 2, 2: 0, 3: 1}[amount]  # tailwind, reflect, light screen -> the field order
            turns = TAILWIND_TURNS
            if amount != 1:
                user = self._occupant(self._last_move[0])
                clay = self.data.tables["ITEM"]["LIGHTCLAY"] + 1
                turns = SCREEN_TURNS_CLAY if user.sheet["item"] == clay else SCREEN_TURNS
            self._conditions[detail][index] = turns
        elif kind == EV["SIDE_END"]:
            self._conditions[detail][{1: 2, 2: 0, 3: 1}[amount]] = 0
        elif kind == EV["ITEM_END"]:
            m = self._occupant(pos)
            if public:
                m.item_used = 1
            if self._unburden is not None and m.ability == self._unburden:
                self._at(pos).flags |= FLAG_UNBURDEN  # Unburden doubles Speed once the item is gone (c08 battles)
        elif kind == EV["SINGLE_TURN"]:
            if ident == self._follow_me:
                self._at(pos).flags |= FLAG_FOLLOW_ME  # this turn (c11 battles)
            elif ident == self._helping_hand:
                self._at(pos).flags |= FLAG_HELPING_HAND  # on the boosted ally, this turn (c09 battles)
        elif kind == EV["FORME"]:
            pass  # the view keeps the set's species; MEGA sets is_mega and the ability
        elif kind == EV["MEGA"]:
            self._mega_used[pos // 2] = 1
            if public:
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
            self._turn_scoped.clear()
            self._guards.clear()
        elif kind == EV["RESULT"]:
            self.ended = True

    def _own_target(self, slot):
        """The target position the own accepted choice gave the move of `slot`."""
        if self._accepted is None:
            raise ValueError("an own two-turn move without an accepted choice")
        words = self._accepted.split(", ")[slot].split(" ")
        if words[0] != "move" or len(words) < 3:
            raise ValueError(f"an own two-turn move without a target: {self._accepted!r}")
        return trace_to_c.abs_target(self.side, int(words[2]))

    def _upkeep(self):
        def down(n):
            return n - 1 if n > 0 else 0
        self._weather_turns = down(self._weather_turns)
        self._terrain_turns = down(self._terrain_turns)
        self._trick_room = down(self._trick_room)
        self._conditions = [[down(n) for n in c] for c in self._conditions]
        for side in self._positions:
            for p in side:
                p.flag = 1 if p.fainted else 0  # checkFainted at the end of the turn; no other flag carries over
                p.protecting = 0
                p.flags &= ~(FLAG_FOLLOW_ME | FLAG_HELPING_HAND)  # single-turn
                if p.stall:
                    p.stall -= 1
                    if not p.stall:
                        p.chain = 0
                if p.charge:
                    p.charge -= 1
                    if not p.charge:
                        p.locked_slot, p.locked_target = MOVE_SLOT_NONE, TARGET_NONE

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
                   and p.occupant < len(members) and members[p.occupant].ability == self._pressure]
        if not holders:
            return 0
        kind = self.data.target_type(move)
        if self.data.move_flags(move) & _MUST_PRESSURE or kind in ("all", "allAdjacentFoes", "allAdjacent"):
            return len(holders)
        if flags & FLAG["SPREAD"] and kind != "foeSide":
            return len(holders)
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
            if reserve or (boundary == REPLACEMENT and not p.fainted):
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
            pv["locked_slot"] = p.locked_slot if p.locked_slot != MOVE_SLOT_NONE else p.choice_slot
            pv["reserved"] = p.flags
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
        v["reflect_turns"], v["light_screen_turns"], v["tailwind_turns"] = self._conditions[side]

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
        v["is_mega"], v["item_used"] = member.is_mega, member.item_used
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
