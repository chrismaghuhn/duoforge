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
import dataclasses
import hashlib
import re
from dataclasses import dataclass

from duoforge_live import lines as line_classes
from duoforge_live import teams
from duoforge_live.data import trace_to_c
from duoforge_live.lines import line_kind
from duoforge_live.tracker import SESSION_LINES

from . import facts as facts_of, labels, setbelief, superset

# Reg M-B (BC spec section 11): the engine's POOL data is Reg M-C's, and two moves have other PP under Reg M-B
# (Strength Sap and Wish: 10, not 5). A Reg M-B game whose sheets hold one is skipped.
REGMB = "gen9championsvgc2026regmb"
REGMB_PP = {"STRENGTHSAP", "WISH"}
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
    sheets: tuple  # (u64, u64): of each |showteam| payload (of each drawn team's paste in a belief game)
    draw: int = 0  # a belief game's draw index (M11 Bo1 spec section 3)


@dataclass
class Row:
    observation: object  # an _layout.OBSERVATION record
    domain: object  # an _layout.FACTORED_DOMAIN record
    side: int
    point: int
    label: labels.Label
    prior_level: tuple  # six levels (prior.LEVELS = no paste)
    belief_level: tuple = None  # a belief game: the own six members' set levels (0 or 1), then the foe's six
    revealed: tuple = None  # a belief game: per own member, the bits of the sheet move slots the game showed


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


def _header(log):
    """(players, ratings, winner, turns, bo3, packed sheets) of a log; Skip("skip:session") for a session line."""
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
    return players, ratings, winner, turns, bo3, packed


def _check_sheets(sheets, format_id, data):
    """Skip unless the engine takes the sheets (sets per side, species canonical): parsing, Reg M-B PP, legality."""
    parsed = []
    for s in (0, 1):
        try:
            parsed.append(data.team(teams.to_text(sheets[s])))  # what the tracker parses: a refusal is a skip
        except trace_to_c.ConversionError as e:
            raise Skip(f"sheet:{e.rule}") from None
    if format_id.startswith(REGMB) and any(trace_to_c.key(m) in REGMB_PP for s in sheets[0] + sheets[1]
                                           for m in s["moves"]):
        raise Skip("skip:regmb-pp")  # BC spec 11: their PP under Reg M-B differ from the engine's (M-C) data
    for sheet, mon in zip(sheets[0] + sheets[1], parsed[0] + parsed[1]):
        issue = data.setup_issue(mon)
        if issue is not None:
            what, index = issue
            name = sheet["moves"][index] if what == "move" else sheet["ability"] if what == "ability" else ""
            raise Skip(f"skip:pool-illegal {sheet['species']} {what} {name}".rstrip())


def _prepass(replay_id, format_id, log, data):
    players, ratings, winner, turns, bo3, packed = _header(log)
    if not packed:
        raise Skip("skip:sheets")
    if sorted(packed) != [0, 1]:
        raise Skip("skip:sheets-one-side")  # two |showteam| lines of one side: no pair of sheets
    if sum(1 for line in log if line_kind(line) == "start") > 1:
        raise Skip("skip:two-games")  # a Bo3 log that holds a second game's lines: one game per row
    sheets = tuple(teams.unpack(packed[s]) for s in (0, 1))
    _check_names(sheets[0] + sheets[1], data)
    for s in sheets[0] + sheets[1]:
        s["species"] = data.canonical(s["species"])  # a cosmetic alias (#118) as the tables name its row
    _check_sheets(sheets, format_id, data)
    record = GameRecord(replay_id, format_id, bo3, tuple(ratings), winner, turns,
                        tuple(_hash8(_to_id(players.get(s, ""))) for s in (0, 1)),
                        tuple(_hash8(packed[s]) for s in (0, 1)))
    return record, sheets


MAX_REDRAWS = 8  # drawn teams per side the engine may refuse before the game is skip:belief-illegal


def draw_sheets(lines, format_id, data, belief, seed, replay_id, draw):
    """(sheets, levels, revealed) of a game without sheets (M11 Bo1 spec sections 2 and 3, option B): per side the
    six members' drawn sets (facts.side_facts, setbelief.SetBelief), their levels, and per member the bits of the
    sheet move slots the game showed. A side the engine refuses is drawn again (attempt + 1) up to MAX_REDRAWS times,
    then Skip("skip:belief-illegal"); a used Reg M-B PP move is Skip("skip:regmb-pp")."""
    key = trace_to_c.key
    sheets, levels, revealed = [], [], []
    for side in (0, 1):
        members = facts_of.side_facts(lines, side, data)
        if format_id.startswith(REGMB) and any(key(m) in REGMB_PP for f in members for m in f.moves):
            raise Skip("skip:regmb-pp")
        for attempt in range(MAX_REDRAWS):
            drawn = [belief.draw(f, setbelief.word(seed, replay_id, side, m, attempt, draw))
                     for m, f in enumerate(members)]
            sheet = [s for s, _ in drawn]
            for s in sheet:
                s["species"] = data.canonical(s["species"])
            try:
                _check_sheets((sheet, sheet), format_id, data)
            except Skip:
                continue
            break
        else:
            raise Skip("skip:belief-illegal")
        sheets.append(sheet)
        levels.append(tuple(level for _, level in drawn))
        revealed.append(tuple(sum(1 << i for i, m in enumerate(s["moves"]) if key(m) in {key(u) for u in f.moves})
                              for s, f in zip(sheet, members)))
    return tuple(sheets), tuple(levels), tuple(revealed)


def _with_drawn_sheets(replay_id, format_id, lines, data, belief, seed, draw, known_sheets):
    """The log of a game without sheets with the drawn teams' |showteam| lines right after its |teampreview|, where
    an open-sheet game has its sheets, and the rows' extra fields (levels, revealed): the sheet pipeline then runs on
    the drawn sheets unchanged (option B)."""
    _, _, _, _, _, packed = _header(lines)
    if packed:
        raise ValueError("a belief game has sheets: the source drops them (drop_sheets) or takes none (bo1_belief)")
    if set(known_sheets) & belief.corpus.sheet_hashes:
        raise ValueError("the game's own sheet is in the corpus: a validation would draw it")
    previews = [i for i, line in enumerate(lines) if line.startswith("|teampreview")]
    if len(previews) != 1:
        raise Skip("skip:belief-preview")
    sheets, levels, revealed = draw_sheets(lines, format_id, data, belief, seed, replay_id, draw)
    shown = [f"|showteam|p{side + 1}|" + teams.pack(teams.to_text(sheets[side])) for side in (0, 1)]
    at = previews[0] + 1
    return lines[:at] + shown + lines[at:], (levels, revealed)


def process(replay_id, format_id, log, data, prior, stats, belief=None, seed=0, draw=0, known_sheets=()):
    """The rows and counters of one game (module docstring). `log` is the replay's text; `prior` a prior.Prior;
    `stats` has stats(species, nature, stat points) (stats.StatSource). With `belief` (a setbelief.SetBelief) the
    game has no sheets and both sides' sheets are drawn (draw_sheets, under seed and draw); known_sheets are the
    hashes of sheets the source dropped, which must not be in the corpus."""
    lines = [line.rstrip("\r") for line in log.split("\n")]
    extra = None
    if belief is not None:
        lines, extra = _with_drawn_sheets(replay_id, format_id, lines, data, belief, seed, draw, known_sheets)
    record, sheets = _prepass(replay_id, format_id, lines, data)
    if belief is not None:
        record = dataclasses.replace(record, draw=draw)
    counters = collections.Counter()
    try:
        points = find(lines)
    except line_classes.Stop as stop:
        counters[f"perspectives.stopped.{stop.reason}"] += 2
        return GameResult(record, [], counters)
    rows = []
    for side in (0, 1):
        rows += _perspective(lines, points, side, sheets, data, prior, stats, counters, extra)
    counters["points.written"] += len(rows)
    return GameResult(record, rows, counters)


def _perspective(lines, points, side, sheets, data, prior, stats, counters, extra=None):
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
        if extra is None:
            rows.append(Row(observation, domain, side, point.index, label, prior_level))
        else:
            levels, revealed = extra
            rows.append(Row(observation, domain, side, point.index, label, prior_level,
                            tuple(levels[side]) + tuple(levels[1 - side]), tuple(revealed[side])))
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
