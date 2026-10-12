"""The search ladder (issue #440): one search improvement measured against the step before it, paired game by game.

    python -m duoforge_search.ladder --checkpoint MAIN --foe-net FOE --teams-from POOLNET --step N [--previous P]
        [--raw] [--h2h] --opponent NAME=PATH [--opponent ...] --out DIR [--pairs 1024] [--seed SEED] [--workers 8]
        [--max-steps 1000] [--previous-run OLD/ladder.json]

The networks stay fixed along the ladder: MAIN (BC6) searches and plays, FOE (BC6) is the foe model in the searched
worlds, and the team pool is POOLNET's (--teams-from: a pool network's config). A step is a settings dict for
honest.Honest: step N is its base step's settings plus its own delta (STEPS, step_settings); step 0 is the live settings
(duoforge_live.search.HONEST_SETTINGS) unchanged.

Each opponent (a raw greedy network: bc6, bot or ppo) meets the arms "step", "previous" (with --previous) and "R" (with
--raw: MAIN's raw play) over the same suite rows and batch seed, so their games are paired: rows 2k and 2k + 1 are one
team pair, its teams and seats swapped. A searching arm leaves the opponent's own team out of the spread table, as
foe_arena does. --h2h plays step N against the previous step, both searching, over the same rows.

The gates (GATES, verdict()): strength (the head-to-head's lower bound above 0.50), no harm (each gated opponent, bot and
bc6, at most 0.50 at its upper bound against the previous step), fallbacks (raw decisions at most 5 %, or the previous
share plus 1 point where that is above 5 %) and latency (the step's p99 wall seconds per searched decision at most 2.0;
the lead reruns the latency exclusively, as this run shares the machine with its workers).
The output directory lies outside the repository; the networks stay private and the report holds aggregates and per-game
scores only.
"""
import argparse
import copy
import json
import os
import sys
import time

import numpy as np

from . import foe_arena

SEED = 0x2026101200000440
OPPONENT_NAMES = ("bc6", "bot", "ppo")
GATED_OPPONENTS = ("bot", "bc6")  # ppo is reported, not gated
GATES = {"lower_bound": 0.50, "no_harm_upper": 0.50, "p99_seconds": 2.0, "fallback_share": 0.05,
         "fallback_over_previous": 0.01}
STEPS = {"0": {"base": None, "settings": {}}}


def step_settings(name):
    """The settings of a step for honest.Honest: the live HONEST_SETTINGS with the deltas of its base chain applied,
    base first. A fresh dict: HONEST_SETTINGS is never changed. ValueError for an unknown step or a broken base chain."""
    if name not in STEPS:
        raise ValueError(f"unknown step {name!r}: the known steps are {sorted(STEPS)}")
    chain, seen, current = [], set(), name
    while current is not None:
        if current in seen:
            raise ValueError(f"step {name!r}: its base chain loops at {current!r}")
        if current not in STEPS:
            raise ValueError(f"step {current!r}, a base of {name!r}, is unknown")
        seen.add(current)
        chain.append(current)
        current = STEPS[current]["base"]
    from duoforge_live.search import HONEST_SETTINGS
    settings = copy.deepcopy(HONEST_SETTINGS)
    for step in reversed(chain):
        settings.update(copy.deepcopy(STEPS[step]["settings"]))
    return settings


def _pair_bootstrap(per_pair, resamples, seed):
    """The 2.5 and 97.5 percentiles of the means of resampled team pairs (foe_arena.verdict's draw)."""
    if int(resamples) < 1:
        raise ValueError(f"a bootstrap needs resamples (got {resamples})")
    idx = np.random.default_rng(seed).integers(0, per_pair.size, size=(int(resamples), per_pair.size))
    low, high = np.quantile(per_pair[idx].mean(axis=1), (0.025, 0.975))
    return float(low), float(high)


def pair_interval(score, resamples=2000, seed=SEED):
    """The mean score of paired games and its 95 % bootstrap interval over the team pairs: rows 2k and 2k + 1 are one
    pair, averaged first, and the pairs are resampled. {"pairs", "score", "95": [low, high]}."""
    s = np.asarray(score, np.float64).reshape(-1)
    if s.size == 0 or s.size % 2:
        raise ValueError(f"paired games need two rows per team pair (got {s.size} rows)")
    per_pair = s.reshape(-1, 2).mean(axis=1)
    return {"pairs": int(per_pair.size), "score": float(s.mean()),
            "95": list(_pair_bootstrap(per_pair, resamples, seed))}


def paired_h(score_a, score_b, resamples=2000, seed=SEED):
    """The head-to-head h = 0.5 + mean(a - b) / 2 of two arms' paired games (team pairs as in pair_interval), with its
    95 % interval by the same bootstrap over the team pairs (foe_arena.verdict's math)."""
    a = np.asarray(score_a, np.float64).reshape(-1)
    b = np.asarray(score_b, np.float64).reshape(-1)
    if a.shape != b.shape:
        raise ValueError(f"paired scores need the same rows (got {a.size} and {b.size})")
    if a.size == 0 or a.size % 2:
        raise ValueError(f"paired scores need two rows per team pair (got {a.size} rows)")
    per_pair = (a - b).reshape(-1, 2).mean(axis=1)
    low, high = _pair_bootstrap(per_pair, resamples, seed)
    return {"pairs": int(per_pair.size), "mean": 0.5 + float(per_pair.mean()) / 2,
            "95": [0.5 + low / 2, 0.5 + high / 2]}


def refused_leaves(decisions):
    """The refused leaves of the searched decisions: the leaves are k * m * s of each, refused those the engine refused
    (E_UNSUPPORTED). unreconstructible_engine_refused counts the decisions that played raw because of such leaves."""
    searched = [r for r in decisions if r["kind"] == "searched"]
    leaves = sum(r["k"] * r["m"] * r["s"] for r in searched)
    refused = sum(r["leaves"]["refused"] for r in searched)
    return {"leaves": int(leaves), "refused": int(refused),
            "decisions_with_refused": sum(r["leaves"]["refused"] > 0 for r in searched),
            "refused_share": refused / leaves if leaves else 0.0,
            "unreconstructible_engine_refused": sum(r["kind"] == "unreconstructible"
                                                    and r.get("reason") == "engine_refused_leaves"
                                                    for r in decisions)}


def verdict(h2h, paired, records_new, records_prev, p99_seconds):
    """The predeclared gates (GATES). h2h: pair_interval of the step's head-to-head scores; paired: opponent name ->
    paired_h(step, previous); records_new and records_prev: the decision records of the step and of the previous step;
    p99_seconds: the step's p99 wall seconds per searched decision, None without evidence (the latency fails)."""
    share_new, share_prev = foe_arena.fallback_share(records_new), foe_arena.fallback_share(records_prev)
    allowed = GATES["fallback_share"] if share_prev <= GATES["fallback_share"] \
        else share_prev + GATES["fallback_over_previous"]
    gates = {"strength": h2h["95"][0] > GATES["lower_bound"],
             "no_harm": all(paired[name]["95"][1] >= GATES["no_harm_upper"]
                            for name in GATED_OPPONENTS if name in paired),
             "fallback": share_new <= allowed + 1e-12,  # shares are ratios of counts: the tolerance is float noise only
             "latency": p99_seconds is not None and p99_seconds <= GATES["p99_seconds"]}
    return {"h2h": h2h, "paired": paired, "fallback_share_new": share_new, "fallback_share_previous": share_prev,
            "fallback_allowed": allowed, "p99_seconds": p99_seconds, "gates": gates, "adopt": all(gates.values())}


def same_games(scores_a, scores_b):
    """True when two runs' per-game score arrays are identical (the determinism gate)."""
    a, b = np.asarray(scores_a, np.float64), np.asarray(scores_b, np.float64)
    return a.shape == b.shape and bool(np.array_equal(a, b))


def wall_seconds(decisions):
    """The p50, p95, p99 and max wall seconds of the searched decisions; None without any."""
    wall = np.array([r["wall"] for r in decisions if r["kind"] == "searched"], np.float64)
    if wall.size == 0:
        return None
    return {q: float(np.percentile(wall, v)) for q, v in (("p50", 50), ("p95", 95), ("p99", 99), ("max", 100))}


def _summary(records, games, decisions=None, seconds=None):
    """One arm on one opponent: the per-game scores, their pair interval, the unfinished and unresolved games and, for
    a searching arm (decisions given), its decision shares, refused leaves, wall times and diagnostics."""
    from . import arena  # JAX: imported where a run needs it, not where the pure functions are used
    scores = arena.scores(records)
    out = {"scores": [float(x) for x in scores], "pair_interval": pair_interval(scores),
           "unfinished": int(records["unfinished"].sum()), "unresolved": int(records["unresolved"].sum())}
    if decisions is not None:
        out.update({"searched": sum(r["kind"] == "searched" for r in decisions),
                    "fallback_share": foe_arena.fallback_share(decisions),
                    "refused_leaves": refused_leaves(decisions), "wall_seconds": wall_seconds(decisions)})
        if decisions:
            out["diagnostics"] = arena.diagnostics(decisions, games)
    if seconds is not None:
        out["seconds"] = seconds
    return out


def _opponents(items):
    """NAME=PATH items as {name: path}: known names, each at most once, at least one."""
    out = {}
    for item in items:
        name, separator, path = item.partition("=")
        if not separator or not path:
            raise SystemExit(f"--opponent {item!r} is not NAME=PATH")
        if name not in OPPONENT_NAMES:
            raise SystemExit(f"unknown opponent {name!r}: one of {', '.join(OPPONENT_NAMES)}")
        if name in out:
            raise SystemExit(f"opponent {name!r} is given twice")
        out[name] = path
    if not out:
        raise SystemExit("give at least one --opponent NAME=PATH")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.ladder", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True, help="the main network (BC6): it searches; R is its raw play")
    p.add_argument("--foe-net", required=True, help="the foe model in the searched worlds (BC6)")
    p.add_argument("--teams-from", required=True, help="a pool network: its config's teams are the suite's pool")
    p.add_argument("--step", required=True, help="the step measured (STEPS)")
    p.add_argument("--previous", help="the previous step: the paired comparison and the head-to-head's opponent")
    p.add_argument("--raw", action="store_true", help="add arm R: the main network's raw play")
    p.add_argument("--h2h", action="store_true", help="step against previous, both searching, over the same rows")
    p.add_argument("--opponent", action="append", default=[], metavar="NAME=PATH",
                   help="a raw greedy opponent: bc6, bot or ppo (each once)")
    p.add_argument("--out", required=True, help="the output directory, outside the repository")
    p.add_argument("--pairs", type=int, default=1024)
    p.add_argument("--seed", type=lambda text: int(text, 0), default=SEED)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-steps", type=int, default=1000)
    p.add_argument("--previous-run", metavar="LADDER.JSON",
                   help="a recorded run: the previous arm's games must equal its step arm's games")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))

    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository (AGENTS.md)") from None
    opponents = _opponents(args.opponent)
    if args.h2h and args.previous is None:
        raise SystemExit("--h2h needs --previous (the step it plays against)")
    if args.previous_run is not None and args.previous is None:
        raise SystemExit("--previous-run needs --previous")
    try:
        step_cfg = step_settings(args.step)
        previous_cfg = None if args.previous is None else step_settings(args.previous)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    recorded = None
    if args.previous_run is not None:
        with open(args.previous_run, encoding="utf-8") as f:
            recorded = json.load(f)
        name = recorded["conditions"]["step"]["name"]
        if name != args.previous:
            raise SystemExit(f"--previous-run measured step {name!r}, not the previous step {args.previous!r}")

    import duoforge
    from duoforge import _layout, teams
    from duoforge_learn import checkpoint as ck, evaluate
    from . import arena, honest

    C = _layout.CONSTANTS

    def load(path):
        params, config = ck.load_trained(path)
        return {"model": ck.trained_model(config, params), "params": params, "encoder": ck.encoder_of(config),
                "ext": ck.ext_supported_of(config)}

    _, teams_config = ck.load_trained(args.teams_from)
    if teams_config.get("data", {}).get("kind") != "pool":
        raise SystemExit("--teams-from's teams are no pool (its config's data kind must be pool)")
    main_net, foe_net = load(args.checkpoint), load(args.foe_net)
    opponent_nets = {name: load(path) for name, path in opponents.items()}
    paths = {"main": args.checkpoint, "foe": args.foe_net, "teams": args.teams_from,
             **{f"opponent {name}": path for name, path in opponents.items()}}
    digests = {role: arena._sha256(path) for role, path in paths.items()}
    commit, dirty = arena._commit()
    foe_tuple = (foe_net["model"], foe_net["params"], foe_net["encoder"], foe_net["ext"])
    os.makedirs(args.out, exist_ok=True)

    with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        pool = teams.load(ctx, teams_config["teams"]["ids"])
        rows = foe_arena.games(len(pool.ids), args.pairs, args.seed)
        table, source_ids, table_info = honest.live_spread_table(ctx)
        learner_team = np.where(rows["learner_seat"] == 0, rows["side0"], rows["side1"])
        opponent_team = np.where(rows["learner_seat"] == 0, rows["side1"], rows["side0"])

        def excluded(team_indices):
            return [source_ids.get(pool.ids[int(i)]) for i in team_indices]

        def searcher(step_name, exclude):
            options = dict(step_settings(step_name), table=table, exclude_teams=exclude, workers=args.workers,
                           foe_net=foe_tuple)
            return honest.Honest(ctx, main_net["model"], main_net["params"], main_net["encoder"], main_net["ext"],
                                 **options)

        def play_search(arm, step_name, opponent_player):
            with searcher(step_name, excluded(opponent_team)) as search:
                player = arena.SearchPlayer(foe_arena.Timed(search), arm, args.seed)
                records = evaluate.play_suite(ctx, pool, rows, player, opponent_player, args.workers, args.seed,
                                              max_steps=args.max_steps)
            return records, [r for row in sorted(player.records) for r in player.records[row]]

        arm_steps = [("step", args.step)] + ([("previous", args.previous)] if args.previous is not None else [])
        raw_player = evaluate.Player(main_net["model"], main_net["params"], main_net["encoder"], "R", main_net["ext"])
        opponent_out, pooled = {}, {"step": [], "previous": []}
        for name, net in opponent_nets.items():
            opponent_player = evaluate.Player(net["model"], net["params"], net["encoder"], name, net["ext"])
            arms, scores, paired = {}, {}, {}
            for arm, step_name in arm_steps:
                started = time.perf_counter()
                records, decisions = play_search(arm, step_name, opponent_player)
                seconds = time.perf_counter() - started
                pooled[arm].extend(decisions)
                with open(os.path.join(args.out, f"{arm}-{name}-decisions.jsonl"), "w", encoding="utf-8") as f:
                    for r in decisions:
                        f.write(json.dumps(arena._finite(r), allow_nan=False) + "\n")
                arms[arm] = _summary(records, rows.shape[0], decisions, seconds)
                scores[arm] = arena.scores(records)
            if args.raw:
                started = time.perf_counter()
                records = evaluate.play_suite(ctx, pool, rows, raw_player, opponent_player, args.workers, args.seed,
                                              max_steps=args.max_steps)
                arms["R"] = _summary(records, rows.shape[0], None, time.perf_counter() - started)
                scores["R"] = arena.scores(records)
            if args.previous is not None:
                paired["step_vs_previous"] = paired_h(scores["step"], scores["previous"])
            if args.raw:
                paired["step_vs_R"] = paired_h(scores["step"], scores["R"])
            entry = {"arms": arms, "paired": paired,
                     "opponent_is_foe_model": digests[f"opponent {name}"] == digests["foe"]}
            if recorded is not None:  # the previous step rerun on this code reproduces its recorded games
                old = recorded.get("opponents", {}).get(name, {}).get("arms", {}).get("step")
                entry["same_games_as_recorded"] = None if old is None else \
                    same_games(scores["previous"], old["scores"])
            opponent_out[name] = entry

        h2h = verdict_out = p99 = None
        if args.h2h:
            with searcher(args.step, excluded(opponent_team)) as learner_search, \
                    searcher(args.previous, excluded(learner_team)) as opponent_search:
                learner = arena.SearchPlayer(foe_arena.Timed(learner_search), "step", args.seed)
                opponent = arena.SearchPlayer(foe_arena.Timed(opponent_search), "previous", args.seed)
                records = evaluate.play_suite(ctx, pool, rows, learner, opponent, args.workers, args.seed,
                                              max_steps=args.max_steps)
            h2h = {**pair_interval(arena.scores(records)), "unfinished": int(records["unfinished"].sum()),
                   "unresolved": int(records["unresolved"].sum())}
        pool_teams, in_table = len(pool.ids), sum(x is not None for x in excluded(opponent_team))

    p99 = (wall_seconds(pooled["step"]) or {}).get("p99")
    if h2h is not None:
        paired_previous = {name: entry["paired"]["step_vs_previous"] for name, entry in opponent_out.items()}
        verdict_out = verdict(h2h, paired_previous, pooled["step"], pooled["previous"], p99)

    conditions = {
        "seed": hex(args.seed), "pairs": args.pairs, "max_steps": args.max_steps,
        "step": {"name": args.step, "settings": step_cfg},
        "previous": None if args.previous is None else {"name": args.previous, "settings": previous_cfg},
        "arms": [arm for arm, _ in arm_steps] + (["R"] if args.raw else []), "h2h": args.h2h,
        "gates": GATES, "commit": commit, "dirty": dirty, "library": duoforge.version(), "cpu": arena.cpu_model(),
        "encoders": {"main": main_net["encoder"], "foe": foe_net["encoder"],
                     **{f"opponent {name}": net["encoder"] for name, net in opponent_nets.items()}},
        "sha256_prefix": {role: digest[:12] for role, digest in digests.items()},
        "pool_teams": pool_teams, "games": int(rows.shape[0]), "table_sha256": table_info["sha256"],
        "opponent_team_in_table": in_table,
    }
    report = {"conditions": conditions, "opponents": opponent_out, "h2h": h2h, "p99_seconds": p99,
              "verdict": verdict_out}
    with open(os.path.join(args.out, "ladder.json"), "w", encoding="utf-8") as f:
        json.dump(arena._finite(report), f, indent=1, allow_nan=False)
    print(json.dumps(arena._finite({
        "opponents": {name: {"scores": {arm: entry["arms"][arm]["pair_interval"]["score"] for arm in entry["arms"]},
                             "paired": entry["paired"]} for name, entry in opponent_out.items()},
        "h2h": h2h, "p99_seconds": p99,
        "adopt": None if verdict_out is None else verdict_out["adopt"]}), indent=1, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
