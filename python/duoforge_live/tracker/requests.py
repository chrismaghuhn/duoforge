"""Own choices, requests and the |showteam| sheets.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

from .. import options, teams
from ..data import trace_to_c
from .constants import ROSTER_NONE
from .state import _condition, _Member


class _RequestFolds:
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
