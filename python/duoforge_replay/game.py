"""One replay game end to end (M11 spec sections 4, 5, 13): rows of both perspectives, or counted reasons.

process() reads one game's log: the pre-pass (sheets, names, Illusion,
players, ratings, winner, Bo3 game number), the decision points, then each
side with a SpectatorTracker up to its first stop. It returns the rows and
the counters; a game the pipeline does not use raises Skip. Every other
exception is a bug, and the caller counts it as internal:<type>.

Counters:
- perspectives.kept, perspectives.stopped.<reason>;
- points.written (rows); points.dropped.<reason>: the game's decision points
  (either side) after a perspective's stop;
- labels.<REASON> per asked slot of the rows, labels.TEAM for team rows;
- turn-scoped.<NAME>: single-turn feature lines that stopped nothing.
"""
import collections
import hashlib
import re
from dataclasses import dataclass

from duoforge_live import lines as line_classes
from duoforge_live import teams
from duoforge_live.data import trace_to_c
from duoforge_live.lines import line_kind
from duoforge_live.tracker import SESSION_LINES

from . import labels, superset
from .points import TEAM_SELECTION, Skip, find
from .prior import LEVELS
from .spectator import SpectatorTracker, feed_lines, hindsight, hindsight_picks, own_requested, walk

REASONS = ("NOT_REQUESTED", "EXACT", "TARGET_UNKNOWN", "MOVE_HIDDEN", "FORCED", "UNKNOWN")

__all__ = ["GameRecord", "GameResult", "Row", "Skip", "process"]


@dataclass(frozen=True)
class GameRecord:
    replay_id: str
    format_id: str
    bo3_game: int  # 0 when unknown
    ratings: tuple  # (int, int), -1 when unknown
    winner: int  # 0, 1, or -1 for a tie or no winner
    turns: int
    players: tuple  # (u64, u64): the first 8 bytes of SHA-256 of each name's to_id
    sheets: tuple  # (u64, u64): of each |showteam| payload


@dataclass
class Row:
    observation: object  # an _layout.OBSERVATION record
    domain: object  # an _layout.FACTORED_DOMAIN record
    side: int
    point: int
    label: labels.Label
    prior_level: tuple  # six levels (prior.LEVELS = no paste)


@dataclass
class GameResult:
    record: GameRecord
    rows: list
    counters: collections.Counter


def _hash8(text):
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")


def _to_id(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())



def _check_names(sets, data):
    """Skip("name:<table> <name>") for a name of a sheet the tables do not have; Skip("skip:illusion") for an
    Illusion holder."""
    tables = data.tables
    if any(trace_to_c.key(s["ability"]) == "ILLUSION" for s in sets):
        raise Skip("skip:illusion")
    for s in sets:
        try:
            data.forme(s["species"])
        except ValueError:
            raise Skip(f"name:FORME {s['species']}") from None
        for table, name in [("ITEM", s["item"]), ("ABILITY", s["ability"]), ("NATURE", s["nature"])] + \
                [("MOVE", m) for m in s["moves"]]:
            if name and trace_to_c.key(name) not in tables[table]:
                raise Skip(f"name:{table} {name}")


def _prepass(replay_id, format_id, log, data):
    players, ratings, winner, turns, bo3, packed = {}, [-1, -1], -1, 0, 0, {}
    for line in log:
        kind = line_kind(line)
        if kind in SESSION_LINES:
            raise Skip("skip:session")
        parts = line.split("|")
        if kind == "player" and len(parts) > 3 and parts[3]:
            side = int(parts[2][1]) - 1
            players.setdefault(side, parts[3])
            if len(parts) > 5 and parts[5].isdigit() and ratings[side] == -1:
                ratings[side] = int(parts[5])
        elif kind == "showteam":
            packed[int(parts[2][1]) - 1] = "|".join(parts[3:])
        elif kind == "turn":
            turns = int(parts[2])
        elif kind == "win":
            names = {_to_id(name): side for side, name in players.items()}
            winner = names.get(_to_id(parts[2]), -1)
        elif kind == "uhtml" and len(parts) > 3 and parts[2] == "bestof":
            m = re.search(r"Game (\d+)", parts[3])
            bo3 = int(m.group(1)) if m else 0
    if sorted(packed) != [0, 1]:
        raise Skip("skip:sheets")
    if sum(1 for line in log if line_kind(line) == "start") > 1:
        raise Skip("skip:two-games")  # a Bo3 log that holds a second game's lines: one game per row
    sheets = tuple(teams.unpack(packed[s]) for s in (0, 1))
    _check_names(sheets[0] + sheets[1], data)
    for s in (0, 1):
        try:
            data.team(teams.to_text(sheets[s]))  # what the tracker parses: a refusal is a skip, not a SystemExit
        except trace_to_c.ConversionError as e:
            raise Skip(f"sheet:{e.rule}") from None
    record = GameRecord(replay_id, format_id, bo3, tuple(ratings), winner, turns,
                        tuple(_hash8(_to_id(players.get(s, ""))) for s in (0, 1)),
                        tuple(_hash8(packed[s]) for s in (0, 1)))
    return record, sheets


def process(replay_id, format_id, log, data, prior, stats):
    """The rows and counters of one game (module docstring). `log` is the replay's text; `prior` a prior.Prior;
    `stats` has stats(species, nature, stat points) (stats.StatSource)."""
    lines = [line.rstrip("\r") for line in log.split("\n")]
    record, sheets = _prepass(replay_id, format_id, lines, data)
    counters = collections.Counter()
    try:
        points = find(lines)
    except line_classes.Stop as stop:
        counters[f"perspectives.stopped.{stop.reason}"] += 2
        return GameResult(record, [], counters)
    rows = []
    for side in (0, 1):
        rows += _perspective(lines, points, side, sheets, data, prior, stats, counters)
    counters["points.written"] += len(rows)
    return GameResult(record, rows, counters)


def _perspective(lines, points, side, sheets, data, prior, stats, counters):
    forme_names = {v: k.lower() for k, v in data.tables["FORME"].items() if k != "COUNT"}
    levels = []
    stat_points = []
    for s in sheets[side]:
        sp, level = prior.lookup(s)
        stat_points.append(sp)
        levels.append(level)
    prior_level = tuple(levels + [LEVELS] * (6 - len(levels)))

    def stats_of(m, forme):
        return stats.stats(forme_names[forme], sheets[side][m]["nature"], stat_points[m]), stat_points[m]

    try:
        leads, back = hindsight(lines, side, data, sheets)
        picks = hindsight_picks(lines, side, data, sheets)
        tracker = SpectatorTracker(data, sheets, side, picks, stats_of, lines)
    except line_classes.Stop as stop:
        counters[f"perspectives.stopped.{stop.reason}"] += 1
        counters[f"points.dropped.{stop.reason}"] += len(points)
        return []
    taken, stop, done = [], None, 0
    try:
        for point in walk(tracker, lines, points):
            done = point.line
            if own_requested(tracker):
                domain, lists = superset.domain(tracker)
                taken.append((point, tracker.observation().copy(), domain.copy(), lists, labels.context(tracker)))
        feed_lines(tracker, lines, done, len(lines))  # a stop after the last point still cuts the last labels
    except line_classes.Stop as e:
        stop = e
    stop_line = len(lines) if stop is None else stop.line
    rows = []
    for point, observation, domain, lists, ctx in taken:
        label = labels.compute(ctx, lines, point, lists, stop_line, leads, back)
        rows.append(Row(observation, domain, side, point.index, label, prior_level))
        if point.boundary == TEAM_SELECTION:
            counters["labels.TEAM"] += 1
        else:
            for reason in label.reasons:
                if reason != labels.NOT_REQUESTED:
                    counters[f"labels.{REASONS[reason]}"] += 1
    for name, n in tracker.turn_scoped_seen.items():
        if stop is None or stop.reason != f"feature:{name}":
            counters[f"turn-scoped.{name}"] += n
    if stop is None:
        counters["perspectives.kept"] += 1
    else:
        counters[f"perspectives.stopped.{stop.reason}"] += 1
        counters[f"points.dropped.{stop.reason}"] += sum(1 for p in points if p.line >= stop.line)
    return rows
