"""The decision points of a replay log, both sides (M11 spec section 7).

A spectator log has no requests. The points come from the line structure:

- TEAM_SELECTION: after both |showteam| lines (which must come before
  |start|);
- TURN: after each |turn|N;
- a switch point: before a |switch| that is not a TURN action. A |switch| is
  a TURN action when no |move|, |cant|, |-mega| or confusion |-activate| line
  of the current turn came before it: at the pin Showdown runs switch actions
  (order 103) before Mega Evolution (104) and moves (200). A switch point is
  a REPLACEMENT when an |upkeep| lies between it and the previous point, else
  a PIVOT (as trace_to_c.boundary_of). It covers the run of |switch| lines up
  to the next action line; a position that switches a second time starts a
  new point, and a switch "[from]" a move (the user's own switch) shares no
  run with another switch of its side.

find() decides nothing about who is asked: the tracker's fold state at the
point does (spectator.SpectatorTracker.at_point).
"""
from dataclasses import dataclass

from duoforge import _layout
from duoforge_live.lines import Stop, flat_position, line_kind

C = _layout.CONSTANTS
TEAM_SELECTION, TURN, REPLACEMENT, PIVOT = (C[f"DUOFORGE_BOUNDARY_{n}"] for n in
                                            ("TEAM_SELECTION", "TURN", "REPLACEMENT", "PIVOT"))
# Lines after which a |switch| of the turn is no TURN action any more.
_ACTED = {"move", "cant", "-mega"}
# Lines that end a run of switch lines: anything that acts or a turn boundary.
_RUN_ENDS = {"move", "cant", "turn", "upkeep", "win", "tie", "-mega"}


class Skip(Exception):
    """A game the pipeline does not use (reason: the counter's name)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Point:
    index: int  # 0-based; the observation's epoch is index + 1
    line: int  # the observation is the fold of lines[:line]
    boundary: int  # DUOFORGE_BOUNDARY_*
    run: tuple = ()  # flat positions side*2+slot that switch in this point's run (switch points)
    end: int = 0  # the label's lines are lines[line:end]: a TURN's until its |upkeep|, a switch point's run
    revive: bool = False  # a Revival Blessing request (step G52): run holds the user's position, nobody else asked




def find(lines):
    """The points of a log (a list of protocol lines). Skip("skip:sheets") without exactly two |showteam| lines,
    Skip("skip:sheets-late") when |start| comes before them; Stop("structure:...") for a log the rules above cannot
    explain."""
    sheets = [i for i, line in enumerate(lines) if line.startswith("|showteam|")]
    if len(sheets) != 2:
        raise Skip("skip:sheets")
    starts = [i for i, line in enumerate(lines) if line_kind(line) == "start"]
    if len(starts) != 1:
        raise Stop("structure:not one |start|")
    if starts[0] < sheets[1]:
        raise Skip("skip:sheets-late")
    points = [Point(0, sheets[1] + 1, TEAM_SELECTION, (), starts[0])]
    turn_open = False  # after |turn| and before its |upkeep|
    acted = False
    upkeep_since_point = False
    run = None  # [start line, positions] of the open switch run
    runs = {}  # point index -> its run
    occupants = {}  # flat position -> the protocol name of its occupant (from the switch lines)
    revive_user = None  # the position of a Revival Blessing user whose revive is still to come (step G52)
    revive_asked_at = 0  # the line its first request came at
    revived = None  # (side, name) of a revive whose instaswitch may follow: its |switch| asks nobody
    for i in range(starts[0] + 1, len(lines)):
        kind = line_kind(lines[i])
        if kind in ("win", "tie"):
            break
        if kind == "move" and lines[i].split("|")[3:4] == ["Revival Blessing"] and "[still]" not in lines[i].split("|"):
            # the user's side is asked whom to revive right after the move line (a pass there defers it: the request
            # comes again after the next action, g52_revive_pivot_no_reserve_ceruledge)
            revive_user = flat_position(lines[i].split("|")[2])
            points.append(Point(len(points), i + 1, PIVOT, (revive_user,), 0, True))
            upkeep_since_point, run = False, None
            revive_asked_at = i + 1
            continue
        elif kind == "-heal" and "[from] move: Revival Blessing" in lines[i].split("|")[4:]:
            start = i - 1 if i > 0 and line_kind(lines[i - 1]) == "split" else i
            if revive_user is not None and any(line_kind(lines[j]) in ("move", "cant")
                                               for j in range(revive_asked_at, start)):
                # passed at the first request: asked again before this line (and the |split| before it)
                points.append(Point(len(points), start, PIVOT, (revive_user,), 0, True))
                upkeep_since_point, run = False, None
            revive_user = None
            side, name = int(lines[i].split("|")[2][1]) - 1, lines[i].split("|")[2].split(": ", 1)[1]
            # Showdown switches the revived member straight back in only when it still holds its position (it fainted
            # there and was never replaced: battle.ts, side.pokemon index < active.length); a benched revive waits for
            # an ordinary replacement request
            revived = (side, name) if any(occupants.get(side * 2 + k) == name for k in range(2)) else None
            continue
        elif kind in _RUN_ENDS and kind != "upkeep":
            revived = None  # the instaswitch into a long-empty position comes after the |upkeep| (g52 battles)
        if run is not None and kind in _RUN_ENDS:
            run = None
        if kind == "turn":
            points.append(Point(len(points), i + 1, TURN))
            turn_open, acted, upkeep_since_point = True, False, False
        elif kind == "upkeep":
            turn_open, upkeep_since_point = False, True
        elif kind in _ACTED or (kind == "-activate" and lines[i].split("|")[3:4] == ["confusion"]):
            acted = True
        elif kind == "switch":
            parts = lines[i].split("|")
            position = flat_position(parts[2])
            incoming = (position // 2, parts[2].split(": ", 1)[1])
            outgoing = occupants.get(position)
            occupants[position] = incoming[1]
            if revived == incoming and not any(x.startswith("[from]") for x in parts[3:]):
                revived = None
                continue  # a revived member into its empty position (0025 item 10): part of the revive's answer
            if len(points) == 1:
                continue  # the leads at |start|, before |turn|1
            if turn_open and not acted:
                continue  # a switch chosen at the TURN point
            # A switch "[from]" a move (Flip Turn, Parting Shot, U-turn: the user's own switch) is asked alone on its
            # side: it shares no run with another switch of that side (c04_flip_turn_double_pivot: Flip Turn's
            # switch, then the Emergency Exit it caused on the same side, two PIVOT points), but the other side's
            # switches join it (c04_flip_turn: Flip Turn and the foe's Emergency Exit, one point asking both).
            own_request = any(x.startswith("[from]") for x in parts[3:])
            # A member that left the field in this run and comes back answers a later request
            # (s13_replacement_after_replacement: Emergency Exit's replacement, then the same member into the
            # fainted ally's position, a PIVOT).
            if run is not None and position not in run[1] and incoming not in run[3] and not any(
                    p // 2 == position // 2 and (alone or own_request) for p, alone in zip(run[1], run[2])):
                run[1].append(position)
                run[2].append(own_request)
                run[3].add((position // 2, outgoing))
                continue
            boundary = REPLACEMENT if upkeep_since_point else PIVOT
            run = [i, [position], [own_request], {(position // 2, outgoing)}]
            runs[len(points)] = run
            points.append(Point(len(points), i, boundary))
            upkeep_since_point = False
    return _ends([p if p.boundary in (TEAM_SELECTION, TURN) or p.revive else _with_run(p, runs[p.index])
                   for p in points], lines)


def _with_run(point, run):
    return Point(point.index, point.line, point.boundary, tuple(run[1]), point.end)


def _ends(points, lines):
    """Each point's label range: a TURN's lines until the turn's |upkeep| (or the end), a switch point's until the
    next action line after its run."""
    out = []
    n = len(lines)
    for p in points:
        end = n
        if p.boundary == TEAM_SELECTION:
            end = p.end
        else:
            for i in range(p.line, n):
                kind = line_kind(lines[i])
                if kind in ("win", "tie") or (p.boundary == TURN and kind == "upkeep"):
                    end = i
                    break
                if p.boundary != TURN and i > p.line and kind in _RUN_ENDS:
                    end = i
                    break
        out.append(Point(p.index, p.line, p.boundary, p.run, end, p.revive))
    return out
