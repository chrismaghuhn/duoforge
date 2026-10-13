"""The closed-sheet set prior measured on real sets and games (decision 0081, #385 step 3). Prints aggregates only.

    python tools/research/cts_set_prior_eval.py quality --corpus CORPUS.json
    python tools/research/cts_set_prior_eval.py levels --replays PATH [PATH ...] [--games 2000]

quality: how well the committed set table (cts.SetPrior.from_table) and, for comparison, the registry's raw counts cover
the sets of a set corpus (duoforge_replay.corpus: the open-sheet replays' training split, private, outside the
repository), each set weighted by its count.
- Presence: the true set; a set with its item, ability and moves; with its item, ability and its first two moves (sorted
  by name); with its item and ability; the species missing.
- The mean log probability of the true set where it is present.

levels: the Bo1 games without sheets of the replay files (parquet needs pyarrow), test split only. Every member is checked
with the facts of the whole game (duoforge_replay.facts, the strictest case). Its level is 0 (a table set agrees), 1 or
2 (cts.level1, cts.level2), or none (no legal set). Also counted: the sides that would stop on the prior, and the sides
side_facts refuses, by reason.
"""
import argparse
import collections
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from duoforge_live import cts, data  # noqa: E402
from duoforge_live.data import trace_to_c  # noqa: E402

FORMAT = "gen9championsvgc2026regmc"


def _norm(item, ability, nature, moves):
    k = trace_to_c.key
    return (k(item) if item else "", k(ability), k(nature), tuple(sorted(k(m) for m in moves)))


def registry_raw():
    """{species key: Counter(set)} of the registry's members, counted per member."""
    out = collections.defaultdict(collections.Counter)
    index = json.loads((ROOT / "data" / "teams" / "index.json").read_text(encoding="utf-8"))
    for entry in index["teams"]:
        for block in (ROOT / "data" / "teams" / f"{entry['id']}.txt").read_text(encoding="utf-8").strip().split("\n\n"):
            rows = [r.strip() for r in block.strip().split("\n")]
            head = rows[0]
            item = head.split(" @ ")[1] if " @ " in head else ""
            species = re.sub(r" \([MF]\)$", "", head.split(" @ ")[0])
            ability = next((r[len("Ability: "):] for r in rows if r.startswith("Ability: ")), "")
            nature = next((r[:-len(" Nature")] for r in rows if r.endswith(" Nature")), "")
            moves = [r[2:] for r in rows if r.startswith("- ")]
            out[trace_to_c.key(species)][_norm(item, ability, nature, moves)] += 1
    return out


def table_sets():
    """{species key: Counter(set)} of the committed table, by draws."""
    from duoforge_search import smogon_sets
    out = {}
    for species, entry in smogon_sets.load_table(smogon_sets.TABLE_PATH, smogon_sets.TABLE_SHA256)["species"].items():
        out[trace_to_c.key(species)] = collections.Counter(
            {_norm(item, ability, nature, moves): n for item, ability, nature, moves, n in entry["sets"]})
    return out


def quality(prior, corpus):
    m, ll, lln = collections.Counter(), 0.0, 0
    for species, sets in corpus.items():
        known = prior.get(species)
        for item, ability, nature, moves, n in sets:
            s = _norm(item, ability, nature, moves)
            m["all"] += n
            if not known:
                m["species missing"] += n
                continue
            total = sum(known.values())
            if s in known:
                m["true set"] += n
                ll += n * math.log(known[s] / total)
                lln += n
            same = [t for t in known if t[0] == s[0] and t[1] == s[1]]
            m["item+ability"] += n * bool(same)
            m["item+ability+moves"] += n * any(set(s[3]) <= set(t[3]) for t in same)
            m["item+ability+2 moves"] += n * any(set(s[3][:2]) <= set(t[3]) for t in same)
    shares = {k: round(v / m["all"], 4) for k, v in m.items() if k != "all"}
    return {"sets": m["all"], **shares, "mean log p(true set | present)": round(ll / max(lln, 1), 3)}


def levels(paths, games_max):
    from duoforge_replay import facts, source, split
    from duoforge_replay.points import Skip
    d = data.load(kind="pool")
    prior = cts.SetPrior.from_table(d)
    out, games, sides, stopping = collections.Counter(), 0, 0, 0
    for unit in source.units(paths):
        for _, fmt, log in source.read_unit(unit, (FORMAT,), collections.Counter()):
            lines = log.split("\n")
            if fmt != FORMAT or any(line.startswith("|showteam|") for line in lines):
                continue
            try:
                if split.of_game(split.players_of(lines)) != "test":
                    continue
            except ValueError:
                continue
            games += 1
            for side in (0, 1):
                try:
                    members = facts.side_facts(lines, side, d)
                except Skip as skip:
                    out[f"sides refused: {skip.reason}"] += 1
                    continue
                sides += 1
                stops = False
                for member in members:
                    sets = prior.candidates(member.species)
                    if any(cts.agrees(s, member) for s, _ in sets):
                        out["members: level 0"] += 1
                    elif cts.level1(d, sets, member)[0]:
                        out["members: level 1"] += 1
                    elif cts.level2(d, sets, member)[0]:
                        out["members: level 2"] += 1
                    else:
                        out[f"members: no legal set ({member.species})"] += 1
                        stops = True
                stopping += stops
            if games >= games_max:
                return games, sides, stopping, out
    return games, sides, stopping, out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quality")
    q.add_argument("--corpus", required=True)
    v = sub.add_parser("levels")
    v.add_argument("--replays", nargs="+", required=True)
    v.add_argument("--games", type=int, default=2000)
    args = p.parse_args(argv)
    if args.cmd == "quality":
        corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))["sets"]
        print(json.dumps({"registry, raw counts": quality(registry_raw(), corpus),
                          "set table": quality(table_sets(), corpus)}, indent=1))
    else:
        games, sides, stopping, out = levels(args.replays, args.games)
        members = sum(n for k, n in out.items() if k.startswith("members:"))
        print(json.dumps({"games": games, "sides": sides, "sides stopping on the prior": stopping,
                          **{k: f"{n} ({n / max(members, 1):.1%})" if k.startswith("members:") else n
                             for k, n in sorted(out.items())}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
