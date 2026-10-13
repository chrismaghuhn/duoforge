"""D1's offline pass (spec docs/superpowers/specs/2026-10-13-depth-search-design.md section 9.1; #481): the recorded
searched decisions of a ladder run, solved again by the exact LP and by CFR+ (matrix.solve_bayes_rm), no game played.

    python -m duoforge_search.rm_offline --decisions RUN/step-bot-decisions.jsonl [...] --out DIR
        [--max-iterations 100000] [--epsilon 1e-3] [--check-every 10] [--workers 8] [--limit N] [--every N]

Per decision (the record's tables, weights, foe_probs, own_probs, u and lam, as the search reduced them):
- the iterations CFR+ needs to reach a gap of epsilon of the range (checked every --check-every), and its gap; a
  decision that misses it at --max-iterations is counted by name (unconverged), never dropped;
- the RM value against the LP value, as a share of the range (LP minus RM: the averages' guarantee lies below the
  game's value by at most the gap);
- whether the choice agrees under nash, ev and mix (honest.reduce with the record's play uniform and lam);
- the mass RM's average puts on rows the LP gives 0 (below matrix.PROBABILITY_FLOOR);
- the seconds of each solve (perf_counter, this process only), and RM's seconds per iteration.

Timing is only meaningful in a run of its own under the machine lock with --exclusive and --workers 1. The report
(report.json) holds counts and quantiles; the rows (rows.jsonl) stay with the run, outside the repository.
"""
import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

QUANTILES = (0.5, 0.9, 0.99, 1.0)


def decisions(paths, limit=None, every=1):
    """(file index, line number, record) of every searched decision with tables in the files, in file and line order;
    every: only each every-th of them (a fixed subsample, the first one kept); limit: at most this many."""
    count = 0
    for index, path in enumerate(paths):
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f):
                if '"searched"' not in line:
                    continue
                record = json.loads(line)
                if record.get("kind") != "searched" or "tables" not in record:
                    continue
                count += 1
                if (count - 1) % every:
                    continue
                yield index, number, record
                if limit is not None and (count - 1) // every + 1 >= limit:
                    return


def solve_one(item, max_iterations, epsilon, check_every):
    """The row of one decision (see the module)."""
    from . import honest, matrix
    index, number, record = item
    tables = np.asarray(record["tables"], dtype=np.float64)
    weights = np.asarray(record["weights"], dtype=np.float64)
    qs = np.asarray(record["foe_probs"], dtype=np.float64)
    prior = np.asarray(record["own_probs"], dtype=np.float64)
    u, lam = float(record["u"]), float(record["lam"])
    nw, k, m = tables.shape
    rank = np.arange(k)
    span = float(tables.max() - tables.min())
    row = {"file": index, "line": number, "w": nw, "k": k, "m": m, "span": span}
    t = time.perf_counter()
    lp = matrix.solve_bayes(tables, weights)
    row["lp_seconds"] = time.perf_counter() - t
    row["lp_exact"] = bool(lp.exact)
    t = time.perf_counter()
    try:
        rm = matrix.solve_bayes_rm(tables, weights, prior, qs, iterations=max_iterations, epsilon=epsilon,
                                   check_every=check_every)
    except matrix.RMUnconverged as err:
        row.update(rm_seconds=time.perf_counter() - t, converged=False, iterations=err.iterations, gap=err.gap)
        return row
    row["rm_seconds"] = time.perf_counter() - t
    row.update(converged=True, iterations=rm.iterations, gap=rm.gap)
    row["value_gap"] = 0.0 if span == 0.0 else (lp.value - rm.solution.value) / span
    zero = lp.x < matrix.PROBABILITY_FLOOR
    row["mass_on_lp_zero_rows"] = float(rm.solution.x[zero].sum())
    lp_out, _ = honest.reduce(tables, weights, qs, rank, u, lam)
    rm_out, _ = honest.reduce(tables, weights, qs, rank, u, lam, solver="rm", prior=prior,
                              rm_iterations=max_iterations, rm_epsilon=epsilon)
    row["agree"] = {rule: lp_out[rule] == rm_out[rule] for rule in ("nash", "ev", "mix")}
    return row


def _quantiles(values):
    if not values:
        return None
    a = np.asarray(values, dtype=np.float64)
    return {f"q{q:g}": float(np.quantile(a, q)) for q in QUANTILES} | {"mean": float(a.mean()), "n": int(a.size)}


def summarize(rows, epsilon, max_iterations, check_every):
    """The report's counts and quantiles over the rows."""
    done = [r for r in rows if r["converged"]]
    out = {"decisions": len(rows), "converged": len(done), "unconverged": len(rows) - len(done),
           "epsilon": epsilon, "max_iterations": max_iterations, "check_every": check_every,
           "iterations": _quantiles([r["iterations"] for r in done]),
           "gap": _quantiles([r["gap"] for r in done]),
           "value_gap": _quantiles([r["value_gap"] for r in done]),
           "mass_on_lp_zero_rows": _quantiles([r["mass_on_lp_zero_rows"] for r in done]),
           "agree": {rule: (sum(r["agree"][rule] for r in done) / len(done) if done else None)
                     for rule in ("nash", "ev", "mix")},
           "lp_exact": sum(r["lp_exact"] for r in rows),
           "lp_seconds": _quantiles([r["lp_seconds"] for r in rows]),
           "rm_seconds": _quantiles([r["rm_seconds"] for r in done]),
           "rm_seconds_per_iteration": _quantiles([r["rm_seconds"] / r["iterations"] for r in done if r["iterations"]]),
           "shapes": {f"{w}x{k}x{m}": n for (w, k, m), n in
                      sorted(_count((r["w"], r["k"], r["m"]) for r in rows).items())}}
    # The curve of the bound against the share solved: for each bound T, the decisions that reached epsilon by T.
    needed = np.sort(np.asarray([r["iterations"] for r in done], dtype=np.int64))
    grid = sorted({check_every * 2 ** e for e in range(0, 30) if check_every * 2 ** e <= max_iterations}
                  | {max_iterations})
    out["solved_by"] = {str(T): float(np.searchsorted(needed, T, side="right") / len(rows)) if rows else None
                        for T in grid}
    return out


def _count(items):
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.rm_offline", description=__doc__.split("\n\n")[0])
    p.add_argument("--decisions", nargs="+", required=True, help="a ladder run's decision files (private)")
    p.add_argument("--out", required=True, help="the report directory, outside the repository")
    p.add_argument("--max-iterations", type=int, default=100_000)
    p.add_argument("--epsilon", type=float, default=None, help="the gap target (default matrix.RM_EPSILON)")
    p.add_argument("--check-every", type=int, default=None, help="default matrix.RM_CHECK_EVERY")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--limit", type=int, default=None, help="at most this many decisions")
    p.add_argument("--every", type=int, default=1, help="each every-th searched decision only (a fixed subsample)")
    args = p.parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    from . import matrix
    try:
        refuse_repository(args.out)  # the rows come from private run data (AGENTS.md)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    epsilon = matrix.RM_EPSILON if args.epsilon is None else args.epsilon
    check_every = matrix.RM_CHECK_EVERY if args.check_every is None else args.check_every
    if args.max_iterations < 1 or args.workers < 1 or args.every < 1 or (args.limit is not None and args.limit < 1):
        raise SystemExit("--max-iterations, --workers, --every and --limit must be positive")
    os.makedirs(args.out, exist_ok=True)
    items = decisions(args.decisions, args.limit, args.every)
    rows = []
    with open(os.path.join(args.out, "rows.jsonl"), "w", encoding="utf-8") as f:
        if args.workers == 1:
            results = (solve_one(item, args.max_iterations, epsilon, check_every) for item in items)
        else:
            pool = ProcessPoolExecutor(args.workers)
            results = pool.map(solve_one, items, *(_repeat(x) for x in (args.max_iterations, epsilon, check_every)),
                               chunksize=16)
        for row in results:  # in decision order: map keeps it
            rows.append(row)
            f.write(json.dumps(row) + "\n")
            if len(rows) % 1000 == 0:
                print(f"{len(rows)} decisions", file=sys.stderr, flush=True)
        if args.workers != 1:
            pool.shutdown()
    report = {"decision_files": [os.path.basename(x) for x in args.decisions], "workers": args.workers,
              "limit": args.limit, "every": args.every,
              **summarize(rows, epsilon, args.max_iterations, check_every)}
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0


def _repeat(value):
    while True:
        yield value


if __name__ == "__main__":
    sys.exit(main())
