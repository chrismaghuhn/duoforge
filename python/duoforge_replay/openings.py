"""Protocol-only opening statistics for open-sheet Gen 9 VGC replays.

This module reads the existing replay source units and Showdown protocol logs.
It does not run a battle or infer choices from battle rules. Unrecognized and
malformed protocol records are counted and skipped. The output is derived from
the HolidayOugi replay source and must be kept outside this repository.

Compatibility means that names are present in DuoForge's current POOL tables;
it does not mean that a name exists in the full Champions dex.

Run with::

    python -m duoforge_replay.openings --source REPLAY_PATH --out LOCAL_DIR [--workers N]
"""
import argparse
import collections
import concurrent.futures
import json
import multiprocessing
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from duoforge_live import lines as live_lines
from duoforge_live import teams
from duoforge_live.data import trace_to_c

from . import hindsight, source

CHAMPIONS_PREFIXES = ("gen9championsvgc2026regmc", "gen9championsvgc2026regmb")
SV_VGC_PREFIXES = ("gen9vgc",)
SOURCE_FORMAT_FILTER = "gen9"
SESSION_KINDS = {"init", "sentchoice", "deinit", "noinit", "expire", "bigerror"}

# These are protocol record names, not battle mechanics. Keeping this set lets
# the extractor report new/garbled record kinds without trying to interpret them.
KNOWN_KINDS = live_lines.ROOM_LINES | SESSION_KINDS | {
    "player", "poke", "showteam", "teamsize", "teampreview", "clearpoke", "gametype", "gen", "tier", "rule",
    "format", "choice", "request", "start", "turn", "upkeep", "prematureend", "win", "tie", "move", "switch",
    "drag", "faint", "cant", "detailschange", "replace", "swap", "-damage", "-heal",
    "-sethp", "-status", "-curestatus", "-boost", "-unboost", "-setboost", "-clearboost",
    "-clearallboost", "-clearpositiveboost", "-clearnegativeboost", "-copyboost", "-swapboost", "-invertboost",
    "-supereffective", "-resisted", "-immune", "-miss", "-crit", "-fail", "-block", "-activate", "-prepare",
    "-mustrecharge", "-enditem", "-item", "-ability", "-weather", "-fieldstart", "-fieldend", "-sidestart",
    "-sideend", "-singleturn", "-singlemove", "-start", "-end", "-formechange", "-mega", "-terastallize",
    "-zpower", "-dynamax", "-endability", "-swapsideconditions", "-cureteam", "-fieldactivate", "-transform",
    "-hint", "-center", "-nothing", "-notarget", "-hitcount", "-waiting", "-combine", "-anim",
}
_POSITION = re.compile(r"^(p[12][ab]):(?:\s+(.+))?$")
_WINNER_ID = re.compile(r"[^a-z0-9]")
_BO3_GAME = re.compile(r"Game (\d+)")


class OpeningSkip(Exception):
    """A game that cannot contribute opening rows, named like replay-pipeline skips."""

    def __init__(self, reason, diagnostics=()):
        super().__init__(reason)
        self.reason = reason
        self.diagnostics = tuple(diagnostics)


@dataclass(frozen=True)
class SpeciesItem:
    species: str
    item: str


@dataclass(frozen=True)
class SideOpening:
    rating: int  # -1 when the log has no numeric rating
    team: tuple  # SpeciesItem values, in |poke| preview order
    leads: tuple | None  # the two leads in active-slot order; None when not observable
    brought: tuple | None  # the four brought Pokemon; None when not observable


@dataclass(frozen=True)
class Action:
    turn: int
    side: int
    kind: str  # move, switch, or mega
    position: str  # p1a/p1b/p2a/p2b
    actor: str  # species name from the protocol ident
    name: str  # move, incoming species, or Mega forme
    target: str | None = None  # preserved protocol target; no target is inferred
    switch_context: str = ""  # choice, replacement, pivot, or drag for switch actions


@dataclass(frozen=True)
class OpeningGame:
    replay_id: str
    source: str
    format_id: str
    bo3_game: int
    winner: int  # 0, 1, or -1 for tie/unknown
    sides: tuple
    actions: tuple
    tera_sides: tuple
    pool_compatible: bool
    pool_incompatible_reasons: tuple
    diagnostics: tuple

    @property
    def terastallized(self):
        return any(self.tera_sides)


def source_for_format(format_id):
    """Return the source bucket for Champions M-C/M-B or Scarlet/Violet VGC."""
    format_id = format_id.lower()
    if format_id.startswith(CHAMPIONS_PREFIXES):
        return "champions"
    if format_id.startswith(SV_VGC_PREFIXES):
        return "sv_vgc"
    return None


def _side_index(ident):
    if ident in ("p1", "p2"):
        return int(ident[1]) - 1
    return None


def _ident(value):
    match = _POSITION.fullmatch(value.strip())
    if match is None:
        return None
    return match.group(1), (match.group(1)[1] == "2"), (match.group(2) or "").strip()


def _species_name(name, data):
    """Canonicalize known aliases; retain an explicit stable id for names outside the tables."""
    name = name.strip()
    try:
        data.forme(name)
        return data.canonical(name)
    except ValueError:
        return trace_to_c.key(name).lower()


def _preview_species(payload):
    return payload.split(",", 1)[0].strip()


def _bad(diagnostics, kind):
    diagnostics[f"lines.garbled.{kind}"] += 1


def _record_identifier(value, diagnostics, kind):
    parsed = _ident(value)
    if parsed is None or not parsed[2]:
        _bad(diagnostics, kind)
        return None
    return parsed


def _format_records(log, diagnostics):
    """Count unknown protocol kinds; regular room text and known effects need no interpretation."""
    for line in log:
        kind = live_lines.line_kind(line)
        if kind is None:
            if line.strip() and not line.startswith("||"):
                diagnostics["lines.unknown.no-kind"] += 1
        elif kind not in KNOWN_KINDS:
            diagnostics[f"lines.unknown.{kind}"] += 1


def _canonical_sheets(showteam, pokes, data, diagnostics):
    """Decode both preview sources and pair item sheets to the |poke| species order."""
    packed_by_side = {}
    for side, payload in showteam:
        if side in packed_by_side:
            _bad(diagnostics, "showteam")
            raise OpeningSkip("skip:sheets")
        try:
            sets = teams.unpack(payload)
        except (TypeError, ValueError):
            _bad(diagnostics, "showteam")
            raise OpeningSkip("skip:sheets") from None
        if len(sets) != 6:
            _bad(diagnostics, "showteam")
            raise OpeningSkip("skip:sheets")
        for member in sets:
            member["species"] = _species_name(member["species"], data)
        packed_by_side[side] = sets

    if sorted(packed_by_side) != [0, 1]:
        raise OpeningSkip("skip:sheets")
    if any(len(pokes[side]) != 6 for side in (0, 1)):
        _bad(diagnostics, "poke")
        raise OpeningSkip("skip:sheets")

    result = []
    sheets_for_hindsight = []
    for side in (0, 1):
        available = collections.defaultdict(collections.deque)
        for member in packed_by_side[side]:
            available[trace_to_c.key(member["species"])].append(member)
        ordered = []
        for preview_name in pokes[side]:
            species = _species_name(preview_name, data)
            key = trace_to_c.key(species)
            if not available[key]:
                _bad(diagnostics, "preview-mismatch")
                raise OpeningSkip("skip:sheets")
            member = available[key].popleft()
            ordered.append(SpeciesItem(species, member["item"].strip()))
        if any(queue for queue in available.values()):
            _bad(diagnostics, "preview-mismatch")
            raise OpeningSkip("skip:sheets")
        result.append(tuple(ordered))
        sheets_for_hindsight.append(packed_by_side[side])
    return tuple(result), tuple(sheets_for_hindsight)


def _parse_action(parts, turn, diagnostics, data, active_species, after_upkeep=False, move_seen=False):
    kind = parts[1]
    if len(parts) < 3:
        _bad(diagnostics, kind)
        return None
    parsed = _record_identifier(parts[2], diagnostics, kind)
    if parsed is None:
        return None
    position, side_two, protocol_actor = parsed
    side = int(side_two)
    actor = active_species.get(position, _species_name(protocol_actor, data))
    if kind == "move":
        if len(parts) < 5 or not parts[3].strip():
            _bad(diagnostics, kind)
            return None
        target = _action_target(parts[4].strip() or None, data, active_species)
        return Action(turn, side, "move", position, actor, parts[3].strip(), target)
    if kind in ("switch", "drag"):
        if len(parts) < 4 or not _preview_species(parts[3]):
            _bad(diagnostics, kind)
            return None
        if kind == "drag":
            switch_context = "drag"
        elif after_upkeep:
            switch_context = "replacement"
        elif move_seen or any(part.startswith("[from]") for part in parts[4:]):
            switch_context = "pivot"
        else:
            switch_context = "choice"
        return Action(turn, side, "switch", position, actor, _species_name(_preview_species(parts[3]), data),
                      switch_context=switch_context)
    if kind == "-mega":
        if len(parts) < 4 or not parts[3].strip():
            _bad(diagnostics, kind)
            return None
        return Action(turn, side, "mega", position, actor, _species_name(parts[3].strip(), data))
    return None


def _pool_compatibility(team_sides, actions, used_items, data):
    """Check names against duoforge_live.data's current POOL tables, not a full Champions dex."""
    missing = set()
    for team in team_sides:
        for member in team:
            try:
                data.forme(member.species)
            except ValueError:
                missing.add("species")
    for action in actions:
        if action.kind == "move" and trace_to_c.key(action.name) not in data.tables["MOVE"]:
            missing.add("move")
    for item in used_items:
        if item and trace_to_c.key(item) not in data.tables["ITEM"]:
            missing.add("item")
    order = ("species", "move", "item")
    return tuple(reason for reason in order if reason in missing)


def _items_used_in_opening(log, team_sides, item_events, data, diagnostics):
    """Resolve the held items of active Pokemon from sheets and turn-scoped switch lines."""
    by_side_species = []
    for team in team_sides:
        members = collections.defaultdict(list)
        for member in team:
            members[trace_to_c.key(member.species)].append(member.item)
        by_side_species.append(members)

    used = set(item_events)

    def add_held_item(side, species):
        candidates = by_side_species[side].get(trace_to_c.key(species), [])
        distinct = {item for item in candidates}
        if len(distinct) > 1:
            diagnostics["lines.ambiguous.item-owner"] += 1
        elif distinct:
            item = next(iter(distinct))
            if item:
                used.add(item)

    active = {}
    current_turn = None
    for line in log:
        kind = live_lines.line_kind(line)
        parts = line.split("|")
        if kind == "turn":
            current_turn = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            if current_turn == 1:
                for position, species in active.items():
                    add_held_item(int(position[1]) - 1, species)
            continue
        if kind in ("switch", "drag"):
            if len(parts) < 4:
                continue  # the action parser counts a malformed turn-1-to-3 switch line
            parsed = _ident(parts[2])
            incoming = _preview_species(parts[3])
            if parsed is None or not incoming:
                continue
            position = parsed[0]
            species = _species_name(incoming, data)
            active[position] = species
            if current_turn in (1, 2, 3):
                add_held_item(int(position[1]) - 1, species)
            continue
        if kind == "faint" and len(parts) > 2:
            parsed = _ident(parts[2])
            if parsed is not None:
                active.pop(parsed[0], None)
            continue
        if current_turn in (1, 2, 3) and kind in ("move", "-mega") and len(parts) > 2:
            parsed = _ident(parts[2])
            if parsed is not None:
                species = active.get(parsed[0], parsed[2])
                add_held_item(int(parsed[0][1]) - 1, species)
    return tuple(sorted(used, key=trace_to_c.key))


def extract_game(replay_id, format_id, log, data):
    """Extract opening data from one log. Raises OpeningSkip with the replay pipeline's skip names."""
    if not isinstance(log, str):
        raise OpeningSkip("skip:log")
    source_name = source_for_format(format_id)
    if source_name is None:
        raise OpeningSkip("skip:format")
    lines = [line.rstrip("\r") for line in log.split("\n")]
    diagnostics = collections.Counter()
    _format_records(lines, diagnostics)

    players, ratings = {}, [-1, -1]
    showteam, pokes = [], {0: [], 1: []}
    winner_name = None
    winner = -1
    current_turn = None
    after_upkeep = False
    move_seen = False
    bo3_game = 0
    starts = 0
    actions, tera_sides, item_events = [], [False, False], []
    active_species = {}

    for line in lines:
        kind = live_lines.line_kind(line)
        parts = line.split("|")
        if kind in SESSION_KINDS:
            # The skip is raised after the sheet-count check, matching source.select then game._prepass.
            continue
        if kind == "player":
            if len(parts) < 4 or _side_index(parts[2]) is None or not parts[3].strip():
                _bad(diagnostics, kind)
                continue
            side = _side_index(parts[2])
            players.setdefault(side, parts[3].strip())
            if len(parts) > 5 and parts[5].isdigit() and ratings[side] == -1:
                ratings[side] = int(parts[5])
            elif len(parts) > 5 and parts[5] and not parts[5].isdigit():
                _bad(diagnostics, "rating")
        elif kind == "showteam":
            if len(parts) < 4 or _side_index(parts[2]) is None:
                _bad(diagnostics, kind)
                continue
            showteam.append((_side_index(parts[2]), "|".join(parts[3:])))
        elif kind == "poke":
            if len(parts) < 4 or _side_index(parts[2]) is None or not _preview_species(parts[3]):
                _bad(diagnostics, kind)
                continue
            pokes[_side_index(parts[2])].append(_preview_species(parts[3]))
        elif kind == "turn":
            if len(parts) < 3 or not parts[2].isdigit():
                _bad(diagnostics, kind)
                current_turn = None
                continue
            current_turn = int(parts[2])
            after_upkeep = False
            move_seen = False
        elif kind == "upkeep":
            after_upkeep = True
            move_seen = False
        elif kind == "start":
            starts += 1
        elif kind == "win":
            if len(parts) < 3 or not parts[2].strip():
                _bad(diagnostics, kind)
                continue
            winner_name = parts[2].strip()
        elif kind == "tie":
            winner_name = None
            winner = -1
        elif kind == "uhtml" and len(parts) > 3 and parts[2] == "bestof":
            match = _BO3_GAME.search(parts[3])
            bo3_game = int(match.group(1)) if match else 0

        if kind in ("switch", "drag"):
            action = _parse_action(parts, current_turn or 0, diagnostics, data, active_species, after_upkeep,
                                   move_seen)
            if action is not None:
                active_species[action.position] = action.name
                if current_turn in (1, 2, 3):
                    actions.append(action)
            continue
        if current_turn not in (1, 2, 3):
            continue
        if kind in ("move", "-mega"):
            if kind == "move":
                move_seen = True
            action = _parse_action(parts, current_turn, diagnostics, data, active_species, after_upkeep, move_seen)
            if action is not None:
                actions.append(action)
        elif kind == "-terastallize":
            if len(parts) < 3:
                _bad(diagnostics, kind)
                continue
            parsed = _record_identifier(parts[2], diagnostics, kind)
            if parsed is not None:
                tera_sides[int(parsed[1])] = True
        elif kind in ("-item", "-enditem"):
            if len(parts) < 4 or not parts[3].strip():
                _bad(diagnostics, kind)
            else:
                item_events.append(parts[3].strip())

    if len(showteam) != 2:
        raise OpeningSkip("skip:sheets", sorted(diagnostics.items()))
    if any(kind in SESSION_KINDS for kind in (live_lines.line_kind(line) for line in lines)):
        raise OpeningSkip("skip:session", sorted(diagnostics.items()))
    if starts > 1:
        raise OpeningSkip("skip:two-games", sorted(diagnostics.items()))

    try:
        team_sides, sheets = _canonical_sheets(showteam, pokes, data, diagnostics)
    except OpeningSkip as skip:
        skip.diagnostics = tuple(sorted(diagnostics.items()))
        raise
    if winner_name is not None:
        winner_id = _WINNER_ID.sub("", winner_name.lower())
        winner = next((side for side, player in players.items()
                       if _WINNER_ID.sub("", player.lower()) == winner_id), -1)

    # Use the same pure helpers exported by spectator.py; they inspect protocol lines only.

    side_openings = []
    for side in (0, 1):
        try:
            lead_indexes, _back = hindsight.hindsight(lines, side, data, sheets)
            picks = hindsight.hindsight_picks(lines, side, data, sheets)
            leads = tuple(sheets[side][index]["species"] for index in lead_indexes)
            brought = None if picks is None else tuple(sheets[side][index]["species"] for index in picks)
            if picks is None:
                diagnostics["games.skipped.skip:brought"] += 1
        except (live_lines.Stop, ValueError, IndexError, KeyError) as error:
            reason = error.reason if isinstance(error, live_lines.Stop) else "unknown-species"
            diagnostics[f"games.skipped.leads:{reason}"] += 1
            leads, brought = None, None
        side_openings.append(SideOpening(ratings[side], team_sides[side], leads, brought))

    used_items = _items_used_in_opening(lines, team_sides, item_events, data, diagnostics)
    reasons = _pool_compatibility(team_sides, actions, used_items, data)
    return OpeningGame(
        str(replay_id), source_name, format_id, bo3_game, winner, tuple(side_openings),
        tuple(actions), tuple(tera_sides), not reasons, reasons, tuple(sorted(diagnostics.items())),
    )


def _stable_sort_value(value):
    """Make heterogeneous tuple keys sortable without collapsing None and empty values."""
    if value is None:
        return 0, "", ""
    if isinstance(value, tuple):
        return 1, "tuple", tuple(_stable_sort_value(part) for part in value)
    return 1, type(value).__name__, value


def _add_observation(table, key, won, decisive):
    values = table[key]
    values["count"] += 1
    if decisive:
        values["decisive"] += 1
        values["wins"] += int(won)


def _action_target(target, data, active_species):
    if not target:
        return None
    match = _POSITION.fullmatch(target.strip())
    if match:
        name = active_species.get(match.group(1), (match.group(2) or "").strip())
        return match.group(1) + (": " + _species_name(name, data) if name else "")
    return target.strip()


def _new_aggregate():
    return {
        "lead_stats": collections.defaultdict(collections.Counter),
        "action_stats": collections.defaultdict(collections.Counter),
        "brought_stats": collections.defaultdict(collections.Counter),
        "compatibility": collections.defaultdict(collections.Counter),
        "diagnostics": collections.defaultdict(collections.Counter),
        "game_counters": collections.Counter(),
    }


def _accumulate(stats, game, exclude_terastallized=False):
    group = (game.source, game.format_id)
    stats["compatibility"][group]["games"] += 1
    stats["compatibility"][group]["pool_compatible"] += int(game.pool_compatible)
    stats["compatibility"][group]["pool_incompatible"] += int(not game.pool_compatible)
    stats["compatibility"][group]["terastallized"] += int(game.terastallized)
    for reason in game.pool_incompatible_reasons:
        stats["compatibility"][group][f"pool_incompatible_{reason}"] += 1
    for reason, count in game.diagnostics:
        stats["diagnostics"][(game.source, game.format_id, reason)]["count"] += count

    counters = stats["game_counters"]
    counters["games.processed"] += 1
    counters["games.pool_compatible"] += int(game.pool_compatible)
    counters["games.pool_incompatible"] += int(not game.pool_compatible)
    counters["games.terastallized"] += int(game.terastallized)
    counters["games.excluded.terastallized"] += int(exclude_terastallized and game.terastallized)
    if exclude_terastallized and game.terastallized:
        return

    decisive = game.winner in (0, 1)
    for side in (0, 1):
        own, opposing = game.sides[side], game.sides[1 - side]
        won = game.winner == side
        team_key = tuple(sorted(member.species for member in own.team))
        if own.leads is not None:
            lead_key = (game.source, game.format_id, team_key, tuple(sorted(own.leads)))
            _add_observation(stats["lead_stats"], lead_key, won, decisive)
        if own.brought is not None:
            for species in set(own.brought):
                _add_observation(stats["brought_stats"], (game.source, game.format_id, species), won, decisive)
        if own.leads is None or opposing.leads is None:
            continue
        own_pair, foe_pair = tuple(sorted(own.leads)), tuple(sorted(opposing.leads))
        for action in game.actions:
            if action.turn != 1 or action.side != side:
                continue
            action_key = (game.source, game.format_id, own_pair, foe_pair, action.kind,
                          action.position[-1], action.actor, action.name, action.target, action.switch_context)
            _add_observation(stats["action_stats"], action_key, won, decisive)


def _merge_aggregate(target, partial):
    for name in ("lead_stats", "action_stats", "brought_stats", "compatibility", "diagnostics"):
        for key, values in partial[name].items():
            target[name][key].update(values)
    target["game_counters"].update(partial["game_counters"])


def _aggregate_result(stats):
    def rows(table, fields):
        output = []
        for key, values in sorted(table.items(), key=lambda item: _stable_sort_value(item[0])):
            row = dict(zip(fields, key))
            decisive = values["decisive"]
            row.update(count=values["count"], decisive_count=decisive, wins=values["wins"],
                       win_rate=values["wins"] / decisive if decisive else None)
            output.append(row)
        return output

    lead_rows = rows(stats["lead_stats"], ("source", "format", "team_species", "leads"))
    action_rows = rows(stats["action_stats"], ("source", "format", "leads", "opposing_leads", "action_kind", "slot",
                                                "actor", "action", "target", "switch_context"))
    brought_rows = rows(stats["brought_stats"], ("source", "format", "species"))
    compatibility_rows = []
    for (source_name, format_id), values in sorted(stats["compatibility"].items()):
        compatibility_rows.append({"source": source_name, "format": format_id, **dict(values)})
    diagnostic_rows = [{"source": source_name, "format": format_id, "reason": reason, "count": values["count"]}
                       for (source_name, format_id, reason), values in sorted(stats["diagnostics"].items())]
    return {
        "tables": {
            "leads_per_team": lead_rows,
            "turn_1_actions": action_rows,
            "species_brought": brought_rows,
            "pool_compatibility": compatibility_rows,
        },
        "counters": dict(sorted(stats["game_counters"].items())),
        "diagnostics": diagnostic_rows,
    }


def aggregate(games, exclude_terastallized=False):
    """Build deterministic count/win-rate tables from extracted games."""
    stats = _new_aggregate()
    for game in games:
        _accumulate(stats, game, exclude_terastallized=exclude_terastallized)
    return _aggregate_result(stats)


def read_games(paths, unit_lines=4096, counters=None):
    """Yield supported-format source rows via source.units/read_unit in source order."""
    if unit_lines < 1:
        raise ValueError("unit_lines must be at least 1")
    counters = counters if counters is not None else collections.Counter()
    for unit in source.units(paths, unit_lines=unit_lines):
        yield from source.read_unit(unit, SOURCE_FORMAT_FILTER, counters)


_OPENING_WORKER_DATA = None


def _opening_worker_init(data):
    global _OPENING_WORKER_DATA
    _OPENING_WORKER_DATA = data


def _opening_work_unit(unit, exclude_terastallized, data=None):
    """Extract one source unit and return compact, mergeable table accumulators."""
    if data is None:
        data = _OPENING_WORKER_DATA
    if data is None:
        raise RuntimeError("opening worker data was not initialized")

    read_counters = collections.Counter()
    skipped = collections.Counter()
    skipped_diagnostics = collections.Counter()
    stats = _new_aggregate()
    for replay_id, format_id, log in source.read_unit(unit, SOURCE_FORMAT_FILTER, read_counters):
        read_counters["games.read"] += 1
        source_name = source_for_format(format_id)
        if source_name is None:
            skipped["games.skipped.skip:format"] += 1
            continue
        try:
            game = extract_game(replay_id, format_id, log, data)
        except OpeningSkip as skip:
            skipped[f"games.skipped.{skip.reason}"] += 1
            for reason, count in skip.diagnostics:
                skipped_diagnostics[(source_name, format_id, reason)] += count
            continue
        _accumulate(stats, game, exclude_terastallized=exclude_terastallized)
    return unit.id, stats, dict(read_counters), dict(skipped), dict(skipped_diagnostics)


def _build_result(stats, read_counters, skipped, skipped_diagnostics, exclude_terastallized):
    result = _aggregate_result(stats)
    result["schema_version"] = 1
    result["exclude_terastallized"] = bool(exclude_terastallized)
    result["counters"] = dict(sorted((collections.Counter(result["counters"]) + read_counters + skipped).items()))
    result["diagnostics"] = sorted(result["diagnostics"] + [
        {"source": source_name, "format": format_id, "reason": reason, "count": count}
        for (source_name, format_id, reason), count in skipped_diagnostics.items()
    ], key=lambda row: (row["source"], row["format"], row["reason"]))
    return result


def build(paths, out_dir, data, *, unit_lines=4096, exclude_terastallized=False, workers=1,
          progress_interval=10, log=None):
    """Extract, aggregate, and write JSON into an output directory outside every repository worktree."""
    from . import dataset

    if unit_lines < 1:
        raise ValueError("unit_lines must be at least 1")
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if progress_interval <= 0:
        raise ValueError("progress_interval must be greater than 0")
    log = log or (lambda message: print(message, file=sys.stderr, flush=True))
    out_dir = Path(out_dir)
    dataset.refuse_repository(out_dir)
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError(f"output path {out_dir} is not a directory")

    started = time.monotonic()
    log("openings: indexing source units")
    units = source.units(paths, unit_lines=unit_lines)
    log(f"openings: processing {len(units)} source units with {workers} worker(s)")
    stats = _new_aggregate()
    read_counters = collections.Counter()
    skipped = collections.Counter()
    skipped_diagnostics = collections.Counter()
    completed = 0
    last_report = started

    def absorb(result):
        nonlocal completed
        _unit_id, unit_stats, unit_read, unit_skipped, unit_diagnostics = result
        _merge_aggregate(stats, unit_stats)
        read_counters.update(unit_read)
        skipped.update(unit_skipped)
        skipped_diagnostics.update(unit_diagnostics)
        completed += 1

    def report(force=False):
        nonlocal last_report
        now = time.monotonic()
        if not force and now - last_report < progress_interval:
            return
        elapsed = max(now - started, 1e-9)
        games_read = read_counters["games.read"]
        games_processed = stats["game_counters"]["games.processed"]
        log(f"openings: {completed}/{len(units)} units; {games_read:,} games read, "
            f"{games_processed:,} openings processed; {elapsed:.1f}s elapsed")
        last_report = now

    if workers == 1:
        for unit in units:
            absorb(_opening_work_unit(unit, exclude_terastallized, data))
            report()
    elif units:
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(workers, mp_context=context, initializer=_opening_worker_init,
                                                    initargs=(data,)) as pool:
            queue = iter(units)
            pending = set()
            while len(pending) < workers:
                try:
                    pending.add(pool.submit(_opening_work_unit, next(queue), exclude_terastallized))
                except StopIteration:
                    break
            while pending:
                timeout = max(0.0, progress_interval - (time.monotonic() - last_report))
                finished, pending = concurrent.futures.wait(
                    pending, timeout=timeout, return_when=concurrent.futures.FIRST_COMPLETED)
                if not finished:
                    report(force=True)
                    continue
                for future in finished:
                    absorb(future.result())
                report()
                while len(pending) < workers:
                    try:
                        pending.add(pool.submit(_opening_work_unit, next(queue), exclude_terastallized))
                    except StopIteration:
                        break
    report(force=True)
    result = _build_result(stats, read_counters, skipped, skipped_diagnostics, exclude_terastallized)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "openings.json"
    temporary = out_dir / "openings.json.tmp"
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(output)
    return json.loads(encoded)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build opening statistics and POOL-name coverage for Gen 9 VGC")
    parser.add_argument("--source", required=True, nargs="+", type=Path, help="Parquet/JSONL files or directories")
    parser.add_argument("--out", required=True, type=Path, help="local output directory, outside the repository")
    parser.add_argument("--unit-lines", type=int, default=4096, help="JSONL rows per existing source unit")
    parser.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 1),
                        help="process workers (default: up to 16 available CPU cores; use 1 for serial)")
    parser.add_argument("--progress-interval", type=float, default=10,
                        help="seconds between progress reports (default: 10)")
    parser.add_argument("--exclude-terastallized", action="store_true",
                        help="exclude games with Terastallization in turns 1-3 from statistics tables")
    args = parser.parse_args(argv)
    if args.unit_lines < 1:
        parser.error("--unit-lines must be at least 1")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.progress_interval <= 0:
        parser.error("--progress-interval must be greater than 0")
    from duoforge_live import data as live_data

    result = build(args.source, args.out, live_data.load(kind="pool"), unit_lines=args.unit_lines,
                   exclude_terastallized=args.exclude_terastallized, workers=args.workers,
                   progress_interval=args.progress_interval)
    print(f"wrote {args.out / 'openings.json'} ({result['counters'].get('games.processed', 0)} games)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
