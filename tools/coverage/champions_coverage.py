#!/usr/bin/env python3
"""Replay game coverage of the engine: the method of the 2026-10-09..11 expansion reports (77.1 % / 81.9 %),
reconstructed for C0 (docs/research/expansion/champions-100.md).

    DUOFORGE_LIBRARY=<libduoforge_shared.so> python3 tools/coverage/champions_coverage.py \
        --sheets SHEETS.jsonl | --replays FILE_OR_DIR... \
        --out DIR [--package PYTHON_DIR] [--format-prefix gen9championsvgc2026regmc] [--data-kind 6] \
        [--singles] [--aggregate-json PATH]

Method (one row per replay game with exactly two open team sheets):
  * Each side's sheet (Showdown packed format) is read member by member. Per member the tokens are
      unknown:FORME <species>   the species is not a row of the data kind's tables (the member is not read further);
      unknown:ITEM <item>       the item is not a row (likewise unknown:ABILITY / unknown:MOVE / unknown:NATURE);
      item:<id> ability:<id> move:<id>   the row exists and duoforge_data_supported says no;
      mega:<Species>@<Stone>    the item is a Mega Stone of the species (duoforge_data_mega_at) and that Mega
                                Evolution is not supported (mega_info.supported 0).
    A side's blockers are the sorted set of its members' tokens; a side with an unknown:* token is reported by its
    unknown:* tokens alone (as the old method did: its names pass came before the support pass). A side is playable when it has none; a game when
    both sides are. The tokens use the ids of the library (data.to_id of the sheet's names).
  * The create check: the side against itself through duoforge_battle_create (duoforge.teams.check), with the
    Stat Point placeholder of #512 (a sheet shows none; 0 with Serious is refused since #406). A side create accepts although it has a blocker is a "create-accepted-but-blocked
    note" (the old reports: 0); a side without a blocker that create refuses is counted by status.
  * Greedy order: repeatedly the token whose support would make the most additional games playable (ties: the
    token first met in game order), as in the old reports.

Usage weights from replay logs (only with --replays): per token the games / team sides containing it, the turns of
those games, the |move| lines of a move token (uses by any side), and "brought": games in which a member carrying
the token was sent out (|switch| or |drag| of its species on its side).

Inputs are private (replays without licence; sheets carry ids). Output: DIR/games.jsonl (per-game blockers: PRIVATE,
stays outside the repository), DIR/report.txt and DIR/aggregate.json (counts per token only, no ids, no per-game
rows; the only file meant to be committed, via --aggregate-json). DIR must be outside the repository.

The library decides support; this tool implements no rule. --package names the python/ directory whose duoforge
package matches the library (for measuring an older commit with its own build).
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


# A sheet shows no Stat Points: the create check uses duoforge_live.teams.SP_PLACEHOLDER (one point in HP, #512),
# which setup accepts under every nature (exactly 0 with Serious is refused since #406, as the pinned validator does).
SP_PLACEHOLDER = (1, 0, 0, 0, 0, 0)


def to_id(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_packed(text):
    """Members of a packed team: (species display name, item, ability, moves, nature, gender)."""
    out = []
    for raw in text.split("]"):
        if not raw:
            continue
        f = raw.split("|")
        f += [""] * (12 - len(f))
        species = f[1] or f[0]
        out.append({"species": species, "item": f[2], "ability": f[3],
                    "moves": [m for m in f[4].split(",") if m], "nature": f[5], "gender": f[7]})
    return out


class Library:
    def __init__(self, data_kind, singles):
        import numpy as np
        import duoforge
        from duoforge import data, teams, _layout
        self.np, self.data, self.teams, self.layout = np, data, teams, _layout
        kind = data_kind
        self.ctx = duoforge.Context(data_kind=kind)
        self.tables = {"species": data.TABLE_SPECIES, "move": data.TABLE_MOVE, "item": data.TABLE_ITEM,
                       "ability": data.TABLE_ABILITY, "nature": data.TABLE_NATURE}
        self.ids, self.sup = {}, {}
        for t, table in self.tables.items():
            n = data.count(self.ctx, table)
            self.ids[t] = {data.name(self.ctx, table, i): i for i in range(n)}
            if t in ("move", "item", "ability"):
                self.sup[t] = [data.supported(self.ctx, table, i) for i in range(n)]
        self._found = {}
        self.megas = {}  # species id -> {stone item id: supported}
        for sid in range(len(self.ids["species"])):
            k = data.mega_count(self.ctx, sid)
            self.megas[sid] = {}
            for j in range(k):
                info = data.mega_at(self.ctx, sid, j)
                self.megas[sid][info["stone"]] = bool(info["supported"])
        self.genders = {"M": _layout.CONSTANTS["DUOFORGE_GENDER_MALE"], "F": _layout.CONSTANTS["DUOFORGE_GENDER_FEMALE"],
                        "": _layout.CONSTANTS["DUOFORGE_GENDER_NONE"], "N": _layout.CONSTANTS["DUOFORGE_GENDER_NONE"]}

    def find(self, table, name):
        """The row id of a name through duoforge_data_find (which also maps the tables' cosmetic aliases, #118), or
        None when the data kind has no such row."""
        key = (table, to_id(name))
        if key not in self._found:
            try:
                self._found[key] = self.data.find(self.ctx, self.tables[table], key[1])
            except Exception as err:  # DuoforgeError: not a row of the kind
                if type(err).__name__ != "DuoforgeError":
                    raise
                self._found[key] = None
        return self._found[key]

    def side(self, members):
        """(blocker tokens, per-member token sets with species, side setup or None)."""
        np, layout = self.np, self.layout
        tokens, per_member = set(), []
        setup = np.zeros((), dtype=layout.SIDE_SETUP)
        setup["member_count"] = min(len(members), layout.MAX_ROSTER)
        complete = len(members) <= layout.MAX_ROSTER
        for k, m in enumerate(members):
            mine = set()
            sid = self.find("species", m["species"])
            if sid is None:
                mine.add(f"unknown:FORME {m['species']}")
                per_member.append((m["species"], mine))
                tokens |= mine
                complete = False
                continue
            out = setup["members"][k] if k < layout.MAX_ROSTER else None
            if out is not None:
                out["species_id"] = sid
                out["gender"] = self.genders.get(m["gender"], self.genders[""])
                out["stat_points"] = SP_PLACEHOLDER
            nat = self.find("nature", m["nature"] or "Serious")
            if nat is None:
                mine.add(f"unknown:NATURE {m['nature']}")
                complete = False
            elif out is not None:
                out["nature"] = nat
            if m["item"]:
                iid = self.find("item", m["item"])
                if iid is None:
                    mine.add(f"unknown:ITEM {m['item']}")
                    complete = False
                else:
                    if not self.sup["item"][iid]:
                        mine.add(f"item:{to_id(m['item'])}")
                    stones = self.megas.get(sid, {})
                    if iid in stones and not stones[iid]:
                        mine.add(f"mega:{m['species']}@{m['item']}")
                    if out is not None:
                        out["item"] = 1 + iid
            aid = self.find("ability", m["ability"])
            if aid is None:
                mine.add(f"unknown:ABILITY {m['ability']}")
                complete = False
            else:
                if not self.sup["ability"][aid]:
                    mine.add(f"ability:{to_id(m['ability'])}")
                if out is not None:
                    out["ability"] = 1 + aid
            moves = m["moves"][:4]
            if out is not None:
                out["move_count"] = len(moves)
            for j, mv in enumerate(moves):
                mid = self.find("move", mv)
                if mid is None:
                    mine.add(f"unknown:MOVE {mv}")
                    complete = False
                    continue
                if not self.sup["move"][mid]:
                    mine.add(f"move:{to_id(mv)}")
                if out is not None:
                    out["moves"][j]["move_id"] = mid
            per_member.append((m["species"], mine))
            tokens |= mine
        unknown = {t for t in tokens if t.startswith("unknown:")}
        if unknown:  # as the old method: a side with a name the tables lack is reported by those names alone
            tokens = unknown
            per_member = [(sp, mine & unknown) for sp, mine in per_member]
        return sorted(tokens), per_member, (setup if complete else None)

    def create(self, setup):
        return self.teams.check(self.ctx, setup)


_SWITCH = re.compile(r"^\|(?:switch|drag)\|(p[12])[a-d]?: [^|]*\|([^,|]+)")
_MOVE = re.compile(r"^\|move\|(p[12])[a-d]?: [^|]*\|([^|]+)")
_TURN = re.compile(r"^\|turn\|(\d+)")
_SHOWTEAM = re.compile(r"^\|showteam\|(p[12])\|(.*)$")


def log_facts(log):
    """(sheets {p1, p2: set of sheet texts}, turns, move uses Counter(move id), sent out {side: set of species ids})."""
    sheets, uses, sent, turns = {}, collections.Counter(), {"p1": set(), "p2": set()}, 0
    for line in log.split("\n"):
        if line.startswith("|showteam|"):
            m = _SHOWTEAM.match(line)
            if m:
                sheets.setdefault(m.group(1), set()).add(m.group(2))
        elif line.startswith("|move|"):
            m = _MOVE.match(line)
            if m:
                uses[to_id(m.group(2))] += 1
        elif line.startswith("|switch|") or line.startswith("|drag|"):
            m = _SWITCH.match(line)
            if m:
                sent[m.group(1)].add(to_id(m.group(2)))
        elif line.startswith("|turn|"):
            m = _TURN.match(line)
            if m:
                turns = max(turns, int(m.group(1)))
    return sheets, turns, uses, sent


def sent_out(species, sent_side):
    """Whether a sheet species was sent out: its id or a forme of it (Mega, battle forme) among the switch species."""
    sid = to_id(species)
    return any(s == sid or s.startswith(sid) for s in sent_side)


def read_games(args):
    """Yields (game id, format id, [sheet p1, sheet p2], facts or None)."""
    if args.sheets:
        with open(args.sheets, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if not row["format"].startswith(args.format_prefix):
                    continue
                yield row["id"], row["format"], row["sheets"], None
        return
    sys.path.insert(0, str(ROOT / "python"))
    from duoforge_replay import source
    for rid, fmt, log in source.games(args.replays, args.format_prefix):
        if not fmt.startswith(args.format_prefix):
            continue
        sheets, turns, uses, sent = log_facts(log)
        # one sheet text per side; a log that shows a side's sheet twice with the same text counts (25 Bo1 games of
        # the 2026-10-02 set print each sheet twice; the old extraction took them)
        if set(sheets) != {"p1", "p2"} or any(len(v) != 1 for v in sheets.values()):
            continue
        yield rid, fmt, [next(iter(sheets["p1"])), next(iter(sheets["p2"]))], (turns, uses, sent)


def greedy(game_sets, limit):
    blocked = [set(g) for g in game_sets if g]
    playable = len(game_sets) - len(blocked)
    total = len(game_sets)
    contains = collections.Counter(t for g in blocked for t in sorted(g))
    order = []
    remaining = blocked
    while remaining and len(order) < limit:
        gain = collections.Counter()
        for g in remaining:
            if len(g) == 1:
                gain[next(iter(g))] += 1
        # ties: the token first met in game order (Counter.most_common keeps insertion order), as the old reports
        best = (gain or contains).most_common(1)[0][0]
        playable += gain.get(best, 0)
        order.append({"token": best, "gain": gain.get(best, 0), "playable": playable,
                      "share": playable / total, "in_games": contains[best]})
        for g in remaining:
            g.discard(best)
        remaining = [g for g in remaining if g]
        contains = collections.Counter(t for g in remaining for t in sorted(g))
    return order


def _runs():
    """This checkout's duoforge/runs.py, loaded as a file of its own: --package may name an older commit's duoforge
    package, which the measurement imports later and which may have no runs module (runs.py imports nothing of it)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("duoforge_runs_of_this_checkout", ROOT / "python" / "duoforge" / "runs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--sheets", help="JSON lines {id, format, sheets: [packed p1, packed p2]} (private)")
    src.add_argument("--replays", nargs="+", help="replay parquet/JSON lines files or directories (private)")
    ap.add_argument("--out", default=None, help="output directory, outside the repository "
                                                "(default: $DUOFORGE_RUNS/coverage/<date>-champions_coverage)")
    ap.add_argument("--package", default=str(ROOT / "python"), help="python/ dir of the duoforge package")
    ap.add_argument("--format-prefix", default="gen9championsvgc2026regmc")
    ap.add_argument("--data-kind", type=int, default=6)
    ap.add_argument("--singles", action="store_true", help="(reserved) singles kind; same token method")
    ap.add_argument("--greedy", type=int, default=400, help="greedy steps to record")
    ap.add_argument("--aggregate-json", help="also write the aggregate JSON here (the committed copy)")
    args = ap.parse_args()

    runs = _runs()  # restructure step 8: the default output and the run's manifest
    if args.out is None:
        args.out = str(runs.default_out("coverage", "champions_coverage"))
    out = Path(args.out).resolve()
    if ROOT in out.parents or out == ROOT:
        sys.exit(f"{out}: the output holds per-game rows and must be outside the repository")
    manifest = runs.Manifest("coverage", "tools/coverage/champions_coverage.py", None, root=ROOT)
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, args.package)
    lib = Library(args.data_kind, args.singles)
    import duoforge
    status_name = duoforge._lib.status_name if hasattr(duoforge._lib, "status_name") else str

    game_sets, n_games = [], 0
    side_total = side_playable = 0
    distinct, distinct_ok = set(), set()
    notes = 0
    refused_clean = collections.Counter()
    tok = collections.defaultdict(lambda: collections.Counter())
    kinds = collections.Counter()
    formats = collections.Counter()
    turns_all = 0
    moves_all = 0
    turns_playable = 0
    with open(out / "games.jsonl", "w", encoding="utf-8") as gfile:
        for gid, fmt, sheets, facts in read_games(args):
            n_games += 1
            formats[fmt] += 1
            sides = []
            for k, packed in enumerate(sheets):
                members = parse_packed(packed)
                blockers, per_member, setup = lib.side(members)
                side_total += 1
                canon = packed  # a distinct team is a distinct sheet text, as in the old reports
                distinct.add(canon)
                if not blockers:
                    side_playable += 1
                    distinct_ok.add(canon)
                if setup is not None:
                    st = lib.create(setup)
                    if st == 0 and blockers:
                        notes += 1
                    if st != 0 and not blockers:
                        refused_clean[status_name(st)] += 1
                for t in blockers:
                    tok[t]["sides"] += 1
                if facts is not None:
                    turns, uses, sent = facts
                    side_key = "p1" if k == 0 else "p2"
                    seen = set()
                    for species, mine in per_member:
                        if mine and sent_out(species, sent[side_key]):
                            seen |= mine
                    for t in seen:
                        tok[t]["sides_brought"] += 1
                sides.append(blockers)
            game = set(sides[0]) | set(sides[1])
            game_sets.append(game)
            for t in game:
                tok[t]["games"] += 1
                kinds[t.split(":")[0]] += 1
            if facts is not None:
                turns, uses, sent = facts
                turns_all += turns
                moves_all += sum(uses.values())
                if not game:
                    turns_playable += turns
                for t in game:
                    tok[t]["turns"] += turns
                for t in game:
                    if t.startswith("move:"):
                        tok[t]["move_uses"] += uses.get(t[5:], 0)
            row = {"id": gid, "b": sides}
            if facts is not None:
                row["t"] = facts[0]  # the game's turns, for champions_batches.py's turn weights
            gfile.write(json.dumps(row) + "\n")  # private: stays in --out
    playable = sum(1 for g in game_sets if not g)
    sole = collections.Counter(next(iter(g)) for g in game_sets if len(g) == 1)
    order = greedy(game_sets, args.greedy)
    agg = {
        "method": "tools/coverage/champions_coverage.py (reconstruction of the 2026-10-09 coverage method)",
        "format_prefix": args.format_prefix, "data_kind": args.data_kind,
        "formats": dict(formats),
        "games": n_games, "games_playable": playable,
        "team_sides": side_total, "team_sides_playable": side_playable,
        "distinct_teams": len(distinct), "distinct_teams_playable": len(distinct_ok),
        "create_accepted_but_blocked": notes, "create_refused_without_blocker": dict(refused_clean),
        "blocker_kinds_game_weighted": dict(kinds),
        "turns": turns_all if args.replays else None, "turns_in_playable_games": turns_playable if args.replays else None,
        "move_uses": moves_all if args.replays else None,
        "tokens": {t: dict(c, sole=sole.get(t, 0)) for t, c in sorted(tok.items(), key=lambda kv: -kv[1]["games"])},
        "greedy": order,
    }
    with open(out / "aggregate.json", "w", encoding="utf-8") as f:
        json.dump(agg, f, indent=1)
    if args.aggregate_json:
        with open(args.aggregate_json, "w", encoding="utf-8") as f:
            json.dump(agg, f, indent=1)
            f.write("\n")
    lines = [f"games {n_games}  both sides playable {playable} ({100 * playable / max(n_games, 1):.1f}%)",
             f"team-sides playable {side_playable}/{side_total}  distinct teams {len(distinct_ok)}/{len(distinct)} "
             f"({100 * len(distinct_ok) / max(len(distinct), 1):.1f}%)  create-accepted-but-blocked notes: {notes}",
             f"blocker kinds (game-weighted): {dict(kinds)}",
             f"create refused without blocker: {dict(refused_clean)}", "",
             "Greedy order (cumulative games playable if supported in this order):"]
    for i, o in enumerate(order[:60], 1):
        lines.append(f"{i:3d}. {o['token']:<45s} + {o['gain']:5d}  -> {o['playable']:6d} ({100 * o['share']:5.1f}%)"
                     f"  [in {o['in_games']} games]")
    (out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest.write(out, package=str(Path(args.package).resolve()))  # the duoforge package the measurement imported
    print("\n".join(lines[:4]))


if __name__ == "__main__":
    main()
