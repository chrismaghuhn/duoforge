#!/usr/bin/env python3
"""What batches of gaps are worth in replay games: the batch view of tools/research/champions_coverage.py.

    python3 tools/research/champions_batches.py --games DIR/games.jsonl --batches BATCHES.json [--out OUT.json]

DIR/games.jsonl is champions_coverage.py's private per-game output (outside the repository). BATCHES.json is a list
of {"name": str, "tokens": [token, ...]} in the proposed order (tokens as champions_coverage.py writes them, e.g.
"ability:protean", "mega:Gyarados@Gyaradosite" may be given as "mega:gyarados@gyaradosite": mega tokens match by
their ids). Per batch it prints and writes (aggregates only, no per-game rows):
  alone      games / team sides that become playable if only this batch is supported;
  cumulative games / team sides playable after this batch and all before it, in the given order.
A token of no batch keeps its games blocked. Determinism: plain counting, no randomness.
"""
import argparse
import json
import re


def norm(token):
    kind, _, rest = token.partition(":")
    if kind == "mega":
        return "mega:" + re.sub(r"[^a-z0-9@]", "", rest.lower())
    return token


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", required=True)
    ap.add_argument("--batches", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    games = []
    with open(args.games, encoding="utf-8") as f:
        for line in f:
            sides = json.loads(line)["b"]
            games.append([{norm(t) for t in s} for s in sides])
    batches = json.load(open(args.batches, encoding="utf-8"))
    n_games, n_sides = len(games), 2 * len(games)

    def playable(done):
        g = s = 0
        for sides in games:
            ok = [not (side - done) for side in sides]
            s += sum(ok)
            g += all(ok)
        return g, s

    base_g, base_s = playable(set())
    rows, done = [], set()
    for b in batches:
        toks = {norm(t) for t in b["tokens"]}
        ag, as_ = playable(toks)
        done |= toks
        cg, cs = playable(done)
        rows.append({"name": b["name"], "tokens": len(toks), "alone_games": ag - base_g, "alone_sides": as_ - base_s,
                     "cum_games": cg, "cum_games_share": round(cg / n_games, 4), "cum_sides": cs,
                     "cum_sides_share": round(cs / n_sides, 4)})
        print(f"{b['name'][:48]:48s} {len(toks):3d} tok  alone +{ag - base_g:5d} g +{as_ - base_s:5d} s  "
              f"cum {cg:6d} ({100 * cg / n_games:5.1f}%)  sides {cs:6d} ({100 * cs / n_sides:5.1f}%)")
    out = {"games": n_games, "base_games": base_g, "base_sides": base_s, "batches": rows}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
            f.write("\n")


if __name__ == "__main__":
    main()
