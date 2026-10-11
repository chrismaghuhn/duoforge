"""M7 (owner 2026-10-11; ExIt plan #360): the live search with a human-like foe model against the live search with its
own network as the foe model, both against a human-like bot.

    python -m duoforge_search.foe_arena --checkpoint MAIN --foe-net BC --bot BOT --out DIR [--pairs 1024]

Arm F: honest.Honest in the live settings (duoforge_live.search.HONEST_SETTINGS, the live spread table) on MAIN, the
worlds' policy from the foe network BC (Honest's foe_net). Arm M: the same search with MAIN as its own foe model, the
live mode today. Arm R (context only): MAIN's raw play. Every arm plays the bot BOT (greedy raw play of a network other
than BC: the bot and the foe model must not be one network) over the same games: team pairs drawn from MAIN's pool,
each pair twice with the teams and the seats swapped, each game in the same environment of a batch on the same seed in
every arm (evaluate.play_suite), so the arms are paired game by game. The searcher decides one root per call, as the
live mode does, and every decision's wall time is kept. The belief leaves the bot's own team out of the spread table.

The gates (predeclared in docs/benchmarks/2026-10-11-foe-model-arena/README.md before the run; verdict()):
- strength: h = 0.5 + (score_F - score_M) / 2, its 95% interval by a bootstrap over the team pairs; F is adopted for live
  play only if the lower bound is above 0.50;
- latency: F's p99 wall seconds per searched decision at most 2.0 (the live arena's gate);
- fallbacks: F's decisions that played raw (unreconstructible) at most 5% of its non-team decisions, or, where M's own
  share is above 5% (the setup's, not the foe model's), at most M's share + 1 point;
- errors: none (a SearchError stops the run, which gives no verdict).
DIR lies outside the repository; the networks stay private and the report holds aggregates only.
"""
import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

SEED = 0x2026101100000707
GATES = {"lower_bound": 0.50, "p99_seconds": 2.0, "fallback_share": 0.05, "fallback_over_m": 0.01}
FALLBACK_KINDS = ("unreconstructible", "raw")


def games(n_teams, pairs, seed=SEED):
    """The suite rows (suite.SUITE) of `pairs` team pairs drawn from n_teams teams: rows 2k and 2k + 1 play pair k, the
    learner's team and seat swapped between them. A pure function of its arguments."""
    from duoforge_learn import suite
    if n_teams < 2 or pairs < 1:
        raise ValueError(f"a pair needs two teams (got {n_teams} teams, {pairs} pairs)")
    r = np.random.default_rng(seed)
    rows = []
    while len(rows) < 2 * pairs:
        a, b = (int(x) for x in r.integers(0, n_teams, 2))
        if a != b:  # row 2k: the learner's team a on seat 0 against b; row 2k + 1: its team b on seat 1 against a
            rows += [(a, b, 0, len(rows) // 2), (a, b, 1, len(rows) // 2)]
    return np.array(rows, dtype=suite.SUITE)


def fallback_share(records):
    """The share of a searcher's non-team decisions that played raw because the search could not run."""
    decisions = [r for r in records if r["kind"] != "team"]
    return sum(r["kind"] in FALLBACK_KINDS for r in decisions) / max(1, len(decisions))


def verdict(score_f, score_m, records_f, records_m, resamples=2000, seed=SEED):
    """The predeclared gates over the paired games (scores per suite row, rows 2k and 2k + 1 one team pair) and the
    two searchers' decision records (each with its wall seconds, "wall")."""
    f, m = np.asarray(score_f, np.float64), np.asarray(score_m, np.float64)
    if f.shape != m.shape or f.size % 2:
        raise ValueError("paired scores need the same rows, two per team pair")
    per_pair = (f - m).reshape(-1, 2).mean(axis=1)
    idx = np.random.default_rng(seed).integers(0, per_pair.size, size=(int(resamples), per_pair.size))
    low, high = np.quantile(per_pair[idx].mean(axis=1), (0.025, 0.975))
    h = {"mean": 0.5 + float(per_pair.mean()) / 2, "95": [0.5 + float(low) / 2, 0.5 + float(high) / 2]}
    wall = np.array([r["wall"] for r in records_f if r["kind"] == "searched"], np.float64)
    p99 = float(np.percentile(wall, 99)) if wall.size else None
    share_f, share_m = fallback_share(records_f), fallback_share(records_m)
    allowed = GATES["fallback_share"] if share_m <= GATES["fallback_share"] else share_m + GATES["fallback_over_m"]
    gates = {"lower_bound": h["95"][0] > GATES["lower_bound"],
             "p99_seconds": p99 is not None and p99 <= GATES["p99_seconds"],
             "fallback_share": share_f <= allowed}
    return {"pairs": int(per_pair.size), "h": h, "score_f": float(f.mean()), "score_m": float(m.mean()),
            "p99_seconds_f": p99, "fallback_share_f": share_f, "fallback_share_m": share_m,
            "fallback_allowed": allowed, "gates": gates, "adopt": all(gates.values())}


def check_nets(foe_net, bot):
    """SystemExit when the foe model and the bot are one network (the same file bytes)."""
    digests = []
    for path in (foe_net, bot):
        with open(path, "rb") as f:
            digests.append(hashlib.sha256(f.read()).hexdigest())
    if digests[0] == digests[1]:
        raise SystemExit("the bot and the foe model are one network: the foe model would know the bot's play")
    return digests


class Timed:
    """The search deciding one root per call, as the live mode does; every record keeps its call's wall seconds."""

    def __init__(self, search):
        self.search = search

    def clear(self):
        self.search.clear()

    def decide(self, roots, envs, seats, keys, last_step):
        actions, records = np.zeros(len(envs), np.int64), []
        for d in range(len(envs)):
            t = time.perf_counter()
            a, (r,) = self.search.decide(roots, envs[d:d + 1], seats[d:d + 1], keys[d:d + 1], last_step[d:d + 1])
            r["wall"] = time.perf_counter() - t
            actions[d] = a[0]
            records.append(r)
        return actions, records


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.foe_arena", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True, help="the main network: own candidates and leaf values")
    p.add_argument("--foe-net", required=True, help="arm F's foe model (a BC prior)")
    p.add_argument("--bot", required=True, help="the opponent's network, played raw and greedy; not the foe model")
    p.add_argument("--out", required=True, help="the output directory, outside the repository")
    p.add_argument("--pairs", type=int, default=1024)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-steps", type=int, default=1000)
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository (AGENTS.md)") from None
    digests = check_nets(args.foe_net, args.bot)

    import duoforge
    from duoforge import _layout, teams
    from duoforge_learn import checkpoint as ck, evaluate
    from duoforge_live.search import HONEST_SETTINGS
    from . import arena, honest

    C = _layout.CONSTANTS
    nets = {}
    for name, path in (("main", args.checkpoint), ("foe", args.foe_net), ("bot", args.bot)):
        params, config = ck.load_trained(path)
        nets[name] = (ck.trained_model(config, params), params, ck.encoder_of(config), ck.ext_supported_of(config),
                      config)
    config = nets["main"][4]
    if config.get("data", {}).get("kind") != "pool":
        raise SystemExit("the main network's teams are no pool")
    os.makedirs(args.out, exist_ok=True)
    commit, dirty = arena._commit()
    report = {"conditions": {"seed": hex(args.seed), "pairs": args.pairs, "max_steps": args.max_steps,
                             "settings": HONEST_SETTINGS, "gates": GATES, "commit": commit, "dirty": dirty,
                             "library": duoforge.version(), "cpu": arena.cpu_model(),
                             "encoders": {k: v[2] for k, v in nets.items()},
                             "foe_and_bot_sha256_prefix": [d[:12] for d in digests]}}
    with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        pool = teams.load(ctx, config["teams"]["ids"])
        rows = games(len(pool.ids), args.pairs, args.seed)
        table, source_ids, table_info = honest.live_spread_table(ctx)
        bot_teams = np.where(rows["learner_seat"] == 0, rows["side1"], rows["side0"])
        excluded = [source_ids.get(pool.ids[int(i)]) for i in bot_teams]
        report["conditions"].update({"pool_teams": len(pool.ids), "games": int(rows.shape[0]),
                                     "table_sha256": table_info["sha256"],
                                     "bot_team_in_table": sum(x is not None for x in excluded)})
        model, params, encoder, ext, _ = nets["bot"]
        bot = evaluate.Player(model, params, encoder, "bot", ext)
        main_model, main_params, main_encoder, main_ext, _ = nets["main"]
        results = {}
        raw = evaluate.Player(main_model, main_params, main_encoder, "R", main_ext)
        results["R"] = (evaluate.play_suite(ctx, pool, rows, raw, bot, args.workers, args.seed,
                                            max_steps=args.max_steps), [])
        for arm, foe in (("M", None), ("F", nets["foe"][:4])):
            options = dict(HONEST_SETTINGS, table=table, exclude_teams=excluded, workers=args.workers)
            if foe is not None:
                options["foe_net"] = foe
            t = time.perf_counter()
            with honest.Honest(ctx, main_model, main_params, main_encoder, main_ext, **options) as search:
                player = arena.SearchPlayer(Timed(search), arm, args.seed)
                records = evaluate.play_suite(ctx, pool, rows, player, bot, args.workers, args.seed,
                                              max_steps=args.max_steps)
            decisions = [r for row in sorted(player.records) for r in player.records[row]]
            results[arm] = (records, decisions)
            with open(os.path.join(args.out, f"{arm}-decisions.jsonl"), "w", encoding="utf-8") as f:
                for r in decisions:
                    f.write(json.dumps(arena._finite(r), allow_nan=False) + "\n")
            report.setdefault("seconds", {})[arm] = time.perf_counter() - t
    for arm, (records, decisions) in results.items():
        score = arena.scores(records)
        out = {"score": float(score.mean()), "unfinished": int(records["unfinished"].sum()),
               "unresolved": int(records["unresolved"].sum())}
        if decisions:
            wall = np.array([r["wall"] for r in decisions if r["kind"] == "searched"])
            out.update({"diagnostics": arena.diagnostics(decisions, int(rows.shape[0])),
                        "wall_seconds": {q: float(np.percentile(wall, v)) for q, v in
                                         (("p50", 50), ("p95", 95), ("p99", 99), ("max", 100))},
                        "fallback_share": fallback_share(decisions)})
        report.setdefault("arms", {})[arm] = out
    report["verdict"] = verdict(arena.scores(results["F"][0]), arena.scores(results["M"][0]),
                                results["F"][1], results["M"][1])
    with open(os.path.join(args.out, "foe_arena.json"), "w", encoding="utf-8") as f:
        json.dump(arena._finite(report), f, indent=1, allow_nan=False)
    print(json.dumps({k: report[k] for k in ("arms", "verdict")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
