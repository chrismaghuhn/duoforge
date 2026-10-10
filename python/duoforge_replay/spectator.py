"""The live tracker for a spectator of a replay (M11 spec section 6).

A replay log is the room's spectator channel: no requests, both sides' HP as
the public percentage. SpectatorTracker is duoforge_live's Tracker for a
given side with three changes:

- the own side is folded from the public lines like the foe's (HP percent,
  status, item use, Mega Evolution, PP from the uses seen); a member that
  never entered shows 100/100;
- what only the player knew comes from hindsight or the prior: the picks
  (the members seen during the game), the stat points and stats
  (stats_of, from the prior and the pinned Showdown), the target of an own
  charging move (the charge turn's raw |move| line);
- the decision points come from points.find, not from requests: at_point()
  sets the boundary and who is asked, by the tracker's switch flag rule.

The test duoforge.python.replay proves the observation equal to DuoForge's
at every own point of every committed battle, field by field, the fields
above compared with their documented sources.
"""
from duoforge_live import lines, teams
from duoforge_live.lines import flat_position
from duoforge_live.data import trace_to_c
from duoforge_live.tracker import (ACTIVE, BENCH, HP_PERCENT, NOT_BROUGHT, ROSTER_NONE, TARGET_NONE, UNDETERMINED,
                                   Tracker)

from .labels import REDIRECT_TURN
from .hindsight import BROUGHT, hindsight, hindsight_picks
from .points import TEAM_SELECTION, TURN

HIDDEN_TARGET = -1  # an own charging move's stored target that no line shows


class SpectatorTracker(Tracker):
    """One side of a replay as its player saw it, from the spectator log."""

    def __init__(self, data, sheets, side, picks, stats_of, log):
        super().__init__(data, teams.to_text(sheets[side]))
        self.side = side
        self._log = list(log)  # the whole log, for the hindsight of an own charging move's target
        self._fed = 0  # lines fed so far: the index of the line being folded
        self._spectator = True
        self._hindsight_picks = picks
        self._stats_of = stats_of  # (member index, forme id) -> (stats [6], stat points [6])
        self._raw_target = {}  # flat position -> the target of its last raw |move| line
        self._boundary = None
        self._asked = [(0, 0), (0, 0)]

    def feed(self, lines):
        for line in lines:
            if line.startswith("|win|") or line == "|tie":
                self.ended = True  # a replay names the winner by user name, not by side: nothing to fold
            else:
                super().feed([line])
            self._fed += 1

    def _own_target(self, slot):
        """The stored target of an own charging move, which the game shows its player only. The charge turn's
        |move| line shows none ("|move|POS|Electro Shot||[still]"); the release turn's |move| line, [from]
        lockedmove, names the target the move hits, which is the stored one unless the move was drawn (an
        -activate of Lightning Rod or Storm Drain next to it) or retargeted (a faint on the target's side in
        between). Otherwise, or without a release line, Stop("charge-target-hidden")."""
        position = self.side * 2 + slot
        log = self._log
        for i in range(self._fed + 1, len(log)):
            parts = log[i].split("|")
            kind = parts[1] if len(parts) > 1 else ""
            if kind in ("switch", "faint") and len(parts) > 2 and flat_position(parts[2]) == position:
                break  # it left before the release
            if kind == "move" and flat_position(parts[2]) == position:
                if "[from]lockedmove" not in parts and "[from] lockedmove" not in parts:
                    break
                target = flat_position(parts[4]) if len(parts) > 4 else None
                if target is None:
                    break
                near = log[max(i - 1, 0):i + 3]
                if any("ability: Lightning Rod" in line or "ability: Storm Drain" in line for line in near):
                    break
                if any(line.startswith("|faint|") and flat_position(line.split("|")[2]) is not None
                       and flat_position(line.split("|")[2]) // 2 == target // 2 for line in log[self._fed:i]):
                    break
                if any(p.occupant == ROSTER_NONE or p.fainted for p in self._positions[target // 2]):
                    break  # a position of the target's side is empty now: Showdown may retarget the move
                turn = max(j for j in range(i) if log[j].startswith("|turn|"))
                if any(line.startswith("|-singleturn|") and line.split("|")[3] in REDIRECT_TURN
                       and flat_position(line.split("|")[2]) is not None
                       and flat_position(line.split("|")[2]) // 2 == target // 2 for line in log[turn:i]):
                    break  # a redirector of the target's side was up: the line shows the drawn target
                return target
        return HIDDEN_TARGET  # at_point stops if an observation would show it

    def _check_charge_targets(self):
        for p in self._positions[self.side]:
            if p.charge and p.locked_target == HIDDEN_TARGET:
                raise lines.Stop("charge-target-hidden")

    # ------------------------------------------------------------------ points
    @property
    def ready(self):
        return self._boundary is not None

    def boundary(self):
        return self._boundary

    def _requested(self, side, boundary):
        return self._asked[side]

    def at_point(self, point):
        """The decision point `point` of points.find, after the fold of its lines: its boundary and who is asked.
        Stop("picks-incomplete") past team selection when the picks are not known; Stop("structure:...") when a
        switching position is not one the switch flag rule asks."""
        self.epoch += 1
        self._step_lines, self._lines = self._lines, []
        if point.boundary == TEAM_SELECTION and self._own_illusion():
            # An Illusion holder on the own sheet (decision 0026, step I2): its player knew which member entered,
            # the spectator log names the disguise; the switch lines do not tell the own occupants, so this
            # perspective stops on the feature instead of guessing
            raise lines.Stop("feature:ILLUSION")
        self._boundary = point.boundary
        self._revive = point.revive  # a Revival Blessing request (step G52): superset offers the fainted members
        if point.boundary != TEAM_SELECTION:
            if self._hindsight_picks is None:
                raise lines.Stop("picks-incomplete")
            self._picks = list(self._hindsight_picks)
        if point.boundary == TEAM_SELECTION:
            self._asked = [(1, 0), (1, 0)]
        elif point.boundary == TURN:
            self._asked = [(1, self._occupied(s)) for s in (0, 1)]
        elif point.revive:
            user = point.run[0]
            self._asked = [((1, 1 << (user % 2)) if s == user // 2 else (0, 0)) for s in (0, 1)]
        else:
            for pos in point.run:
                self._at(pos).flag = 1  # a position that switches was asked (also for pivot causes not folded)
            asked = []
            for s in (0, 1):
                slots = self._foe_switch_slots(s, point.boundary)
                for pos in point.run:
                    if pos // 2 == s and not slots >> (pos % 2) & 1:
                        raise lines.Stop(f"structure:p{s + 1}{'ab'[pos % 2]} switches but is not asked")
                asked.append((1, slots) if slots else (0, 0))
            self._asked = asked
        if own_requested(self):
            self._turn_scoped_stop(point.boundary)  # only a point of this perspective can show it
            self._check_charge_targets()

    def _own_illusion(self):
        illusion = self.data.tables["ABILITY"].get("ILLUSION")
        return illusion is not None and any(m.sheet["ability"] == illusion + 1 for m in self._member(self.side))

    # ------------------------------------------------------------------ view
    def _view_member(self, v, member, m, side, own, boundary):
        super()._view_member(v, member, m, side, False, boundary)  # the public view of the member
        if not own:
            return
        if not member.seen:  # never entered: at full HP, as its player knows
            v["hp"], v["hp_flag"], v["hp_max"], v["hp_kind"] = 100, 0, 100, HP_PERCENT
            v["status"] = 0
        active = any(p.occupant == m for p in self._positions[side])
        if boundary == TEAM_SELECTION:
            v["location"] = UNDETERMINED
        elif active:
            v["location"] = ACTIVE
        elif m in self._picks:
            v["location"] = BENCH
        else:
            v["location"] = NOT_BROUGHT
        forme = member.sheet["species"]
        if member.is_mega:
            forme = self.data.mega_of(forme, member.sheet["item"])
        stats, stat_points = self._stats_of(m, forme)
        v["stats"] = stats[1:6]
        v["stat_points"] = stat_points


def own_requested(tracker):
    """Whether the tracker's own side is asked at its current point."""
    return tracker._asked[tracker.side][0] == 1


def walk(tracker, log, points):
    """Folds the log point by point: yields each point after tracker.at_point (read the observation then). A Stop
    ends the walk (the caller counts it); its `line` is the index of the line that stopped it, or the point's line
    when at_point did."""
    done = 0
    for point in points:
        feed_lines(tracker, log, done, point.line)
        done = point.line
        try:
            tracker.at_point(point)
        except lines.Stop as e:
            e.line = point.line
            raise
        yield point


def feed_lines(tracker, log, start, end):
    """Feeds log[start:end] line by line; a Stop gets `line`, the index of its line."""
    for i in range(start, end):
        try:
            tracker.feed([log[i]])
        except lines.Stop as e:
            e.line = i
            raise

