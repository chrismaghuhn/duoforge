"""D2's offline pass (README docs/benchmarks/2026-10-14-depth-d2, plan docs/superpowers/plans/2026-10-14-depth-search-
d2.md step 10): the iteration bound of the two-turn tree's CFR+ solve (tree.TREE_MAX_ITERATIONS) by accuracy and by
time, on trees built beside played games.

    python -m duoforge_search.tree_offline --checkpoint BC6 --foe-net BC6 --teams-from POOLNET --opponent bot=PATH
        --out DIR [--step 2e] [--widths 2,3,4] [--pairs 64] [--max-iterations 50000] [--every 1]
        [--info-key record] [--seed ...] [--workers 8] [--max-steps 1000] [--plain-check]

The games are the ladder's (its seed, pool and rows) played by --step against the one opponent. At every searched turn
decision (each --every-th of them) a depth-2 search per width (the shadow) builds and solves the same root's tree; its
row is written to rows.jsonl at once and never held. The move played stays the step's: a shadow decides beside it and
changes nothing of it. --plain-check plays the same games once without shadows first, and the report gives both runs'
decisions digests (the README requires them equal).

The report (report.json) holds the conditions (commit, dirty, the library's and the networks' sha256), the digests
and the predeclared bounds (bounds, read streamed from rows.jsonl); the rows stay with the run, outside the
repository. Seconds are only meaningful in a run of its own under the machine lock with --exclusive and --workers 1.
"""
import argparse
import contextlib
import json
import math
import os

import numpy as np

from . import tree
from .honest import TREE_PHASES

PHASES = TREE_PHASES
BUDGET_SECONDS = 0.4  # the tree solve's local budget at the widest width (the README: D1's root budget)
SHARES = (40, 80, 160, 320, 640, 1280, 2560, 5120, 10240, 20480, 40960)
QUANTILES = {"median": 50, "p99": 99, "max": 100}


class Shadow:
    """timed (a decide wrapper, foe_arena.Timed) plays; every search of shadows ({width: a depth-2 Honest}) sees every
    decision, and on each every-th searched turn decision of timed it decides the same root, its row written to out
    (one JSON line per width) and flushed. On the other searched turn decisions a shadow only takes the root's public
    record into its history (Honest._observe, as its decide would), so a later decision of the turn has what it needs.
    The records and moves returned are timed's, unchanged."""

    def __init__(self, timed, shadows, out, every=1):
        if type(every) is not int or every < 1:
            raise ValueError(f"every must be a positive int (got {every!r})")
        self.timed, self.shadows, self.out, self.every = timed, dict(shadows), out, every
        self.searched = 0  # the searched turn decisions seen

    def clear(self):
        self.timed.clear()
        for search in self.shadows.values():
            search.clear()

    def decide(self, roots, envs, seats, keys, last_step, steps_left=None):
        if steps_left is None:
            raise ValueError("a shadow needs steps_left (its depth-2 searches refuse None)")
        actions, records = self.timed.decide(roots, envs, seats, keys, last_step, steps_left=steps_left)
        for d, r in enumerate(records):
            one = slice(d, d + 1)
            turn = r["kind"] == "searched" and r["boundary"] != "TEAM_SELECTION"
            take = turn and self.searched % self.every == 0
            self.searched += turn
            for width, search in self.shadows.items():
                if turn and not take:
                    e, p = int(envs[d]), int(seats[d])
                    players = np.zeros(roots.envs, np.uint32)
                    players[e] = p
                    public, statuses = roots.public(players)
                    search._observe(roots, e, p, public[e:e + 1].reshape(()).copy(), int(statuses[e]))
                    continue
                _, (s,) = search.decide(roots, envs[one], seats[one], keys[one], last_step[one],
                                        steps_left=steps_left[one])
                if take:
                    self.out.write(json.dumps(row_of(width, s, r), allow_nan=False) + "\n")
                    self.out.flush()
        return actions, records


def row_of(width, shadow, played):
    """The row of one shadow decision: its width, kind and reason, the played and the shadow's choice, the phases'
    seconds and, for a searched tree, its iterations, gap, nodes, information sets, merge share and leaf kinds; for
    a tree solve that did not converge (solver_unconverged, solver_failed "tree") its iterations and gap (converged
    False); otherwise converged None (a failed root solve keeps its solver_failed "root")."""
    cost = shadow["cost"]
    row = {"width": width, "env": shadow["env"], "key": shadow["key"], "boundary": shadow["boundary"],
           "kind": shadow["kind"], "reason": shadow.get("reason"), "played_choice": played["choice"],
           "choice": shadow["choice"], "choice_differs": shadow["choice"] != played["choice"],
           "policy_seconds": cost["tree_policy"], "evaluate_seconds": cost["tree_evaluate"],
           "solve_seconds": cost["tree_solve"]}
    if shadow["kind"] == "searched":
        t = shadow["tree"]
        row.update(converged=True, iterations=t["iterations"], gap=t["gap"], nodes=t["nodes"],
                   information_sets=t["information_sets"], merge_share=t["merge_share"], leaves=t["leaves"],
                   k=shadow["k"], m=shadow["m"])
    elif shadow.get("reason") == "solver_unconverged" and shadow.get("solver_failed") == "tree":
        row.update(converged=False, iterations=shadow["iterations"], gap=shadow["gap"])
    elif shadow.get("reason") == "solver_unconverged":
        row.update(converged=None, iterations=None, solver_failed=shadow.get("solver_failed"))
    else:
        row.update(converged=None, iterations=None)
    return row


def read_rows(path):
    """The rows of a rows.jsonl, one at a time."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _quantiles(values):
    if not values:
        return None
    a = np.asarray(values, dtype=np.float64)
    return {name: float(np.percentile(a, q)) for name, q in QUANTILES.items()}


def bounds(rows, budget=BUDGET_SECONDS, timing_width=None, bound=None):
    """The README's bounds from rows (an iterable, read once):
    - t_acc: twice the largest iteration count a converged decision needed, up to a multiple of 10; None if any
      decision missed the gap (solver_unconverged) or none converged;
    - t_time: the count at which the tree solve costs `budget` seconds, from the p99 of the solve seconds per
      iteration at timing_width (the widest width by default), down to a multiple of 10;
    - default: t_acc when it is at most t_time, else None (no default is set).
    Also the counts (decisions, unconverged, root_unconverged: a failed root solve, which says nothing about the tree's
    bound, observation_key_refused and its share), the iterations' quantiles per
    width, the share of converged decisions each bound of SHARES solves, and over_bound: per width, the share of keyed
    decisions (converged or not) that the set bound (tree.TREE_MAX_ITERATIONS unless bound is given) would cut off,
    more iterations than it or unconverged at all (the gate of the re-check on digest-keyed trees)."""
    bound = tree.TREE_MAX_ITERATIONS if bound is None else bound
    count, unconverged, refused, root_unconverged = 0, 0, 0, 0
    iterations, per_iteration, widths, keyed, over = {}, {}, set(), {}, {}
    for r in rows:
        count += 1
        widths.add(r["width"])
        if r.get("reason") == "observation_key_refused":
            refused += 1
        if r.get("reason") == "solver_unconverged" and r.get("converged") is None:
            root_unconverged += 1
        if r.get("converged") is not None:
            keyed[r["width"]] = keyed.get(r["width"], 0) + 1
            cut = r["converged"] is False or int(r["iterations"]) > bound
            over[r["width"]] = over.get(r["width"], 0) + int(cut)
        if r.get("converged") is False:
            unconverged += 1
        elif r.get("converged"):
            iterations.setdefault(r["width"], []).append(int(r["iterations"]))
            if r["iterations"] > 0:
                per_iteration.setdefault(r["width"], []).append(r["solve_seconds"] / r["iterations"])
    every = [n for values in iterations.values() for n in values]
    t_acc = None if unconverged or not every else int(math.ceil(2 * max(every) / 10)) * 10
    timing_width = max(widths) if timing_width is None and widths else timing_width
    timing = per_iteration.get(timing_width, [])
    t_time = None
    if timing:
        p99 = float(np.percentile(np.asarray(timing, dtype=np.float64), 99))
        t_time = int(math.floor(budget / p99 / 10)) * 10 if p99 > 0 else None
    return {"decisions": count, "unconverged": unconverged, "root_unconverged": root_unconverged,
            "observation_key_refused": refused,
            "observation_key_refused_share": refused / count if count else None,
            "iterations": {str(w): _quantiles(v) for w, v in sorted(iterations.items())},
            "seconds_per_iteration": {str(w): _quantiles(v) for w, v in sorted(per_iteration.items())},
            "solved_by": {str(t): sum(n <= t for n in every) / len(every) for t in SHARES} if every else None,
            "over_bound": {"bound": bound, "share": {str(w): over[w] / keyed[w] for w in sorted(keyed)},
                           "keyed": {str(w): keyed[w] for w in sorted(keyed)}},
            "t_acc": t_acc, "t_time": t_time, "timing_width": timing_width, "budget_seconds": budget,
            "default": t_acc if t_acc is not None and t_time is not None and t_acc <= t_time else None}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.tree_offline", description=__doc__.split("\n\n")[0])
    p.add_argument("--checkpoint", required=True, help="the main network (BC6)")
    p.add_argument("--foe-net", required=True, help="the foe model in the searched worlds (BC6)")
    p.add_argument("--teams-from", required=True, help="a pool network: its config's teams are the suite's pool")
    p.add_argument("--opponent", required=True, metavar="NAME=PATH", help="the one opponent (the ladder's names)")
    p.add_argument("--out", required=True, help="the output directory, outside the repository")
    p.add_argument("--step", default="2e", help="the played step (ladder.STEPS)")
    p.add_argument("--widths", default="2,3,4", help="the shadows' K2 = M2, comma-separated")
    p.add_argument("--pairs", type=int, default=64)
    p.add_argument("--max-iterations", type=int, default=50_000)
    p.add_argument("--every", type=int, default=1, help="shadow each every-th searched turn decision")
    p.add_argument("--info-key", default="record", help="the shadows' observation key (honest's infokey)")
    p.add_argument("--seed", type=lambda text: int(text, 0), default=None, help="default: the ladder's seed")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-steps", type=int, default=1000)
    p.add_argument("--plain-check", action="store_true", help="play the games once without shadows first")
    args = p.parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    from . import arena, foe_arena, honest, ladder
    try:
        refuse_repository(args.out)
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository (AGENTS.md)") from None
    widths = [int(x) for x in args.widths.split(",")]
    if not widths or any(w < 1 for w in widths) or len(set(widths)) != len(widths):
        raise SystemExit(f"--widths must name distinct positive ints (got {args.widths!r})")
    if args.pairs < 1 or args.max_iterations < 1 or args.every < 1:
        raise SystemExit("--pairs, --max-iterations and --every must be positive")
    seed = ladder.SEED if args.seed is None else args.seed
    name, path = next(iter(ladder._opponents([args.opponent]).items()))
    library = os.environ.get("DUOFORGE_LIBRARY")
    if not library:
        raise SystemExit("DUOFORGE_LIBRARY must name the library (its sha256 is part of the report)")
    paths = {"main": args.checkpoint, "foe": args.foe_net, "teams": args.teams_from, f"opponent {name}": path,
             "library": library}
    digests = {role: arena._sha256(x) for role, x in paths.items()}
    commit, dirty = ladder._checkout()
    if os.environ.get("DUOFORGE_COMMIT"):  # git in WSL cannot read a Windows worktree: the runner states it
        commit, dirty = os.environ["DUOFORGE_COMMIT"], os.environ.get("DUOFORGE_DIRTY", "true") == "true"

    import duoforge
    from duoforge import _layout
    from duoforge_learn import checkpoint as ck, evaluate

    def load(x):
        params, config = ck.load_trained(x)
        return {"model": ck.trained_model(config, params), "params": params, "encoder": ck.encoder_of(config),
                "ext": ck.ext_supported_of(config)}

    _, teams_config = ck.load_trained(args.teams_from)
    if teams_config.get("data", {}).get("kind") != "pool":
        raise SystemExit("--teams-from's teams are no pool (its config's data kind must be pool)")
    main_net, foe_net, opponent_net = load(args.checkpoint), load(args.foe_net), load(path)
    foe_tuple = (foe_net["model"], foe_net["params"], foe_net["encoder"], foe_net["ext"])
    os.makedirs(args.out, exist_ok=True)
    rows_path = os.path.join(args.out, "rows.jsonl")
    with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        pool, pool_info = foe_arena.load_pool(ctx, teams_config["teams"]["ids"])
        rows = foe_arena.games(len(pool.ids), args.pairs, seed)
        table, source_ids, table_info = honest.live_spread_table(ctx)
        opponent_team = np.where(rows["learner_seat"] == 0, rows["side1"], rows["side0"])
        excluded = [source_ids.get(pool.ids[int(i)]) for i in opponent_team]

        def search(**extra):
            options = dict(ladder.step_settings(args.step), table=table, exclude_teams=excluded,
                           workers=args.workers, foe_net=foe_tuple, **extra)
            return honest.Honest(ctx, main_net["model"], main_net["params"], main_net["encoder"], main_net["ext"],
                                 **options)

        opponent = evaluate.Player(opponent_net["model"], opponent_net["params"], opponent_net["encoder"], name,
                                   opponent_net["ext"])

        def play(decider):
            player = arena.SearchPlayer(decider, "step", seed, max_steps=args.max_steps)
            evaluate.play_suite(ctx, pool, rows, player, opponent, args.workers, seed, max_steps=args.max_steps)
            return ladder.decisions_digest([r for row in sorted(player.records) for r in player.records[row]])

        plain = None
        if args.plain_check:
            with search() as alone:
                plain = play(foe_arena.Timed(alone))
        shadow_settings = {"depth": 2, "root_solver": "rm", "rm_iterations": args.max_iterations,
                           "info_key": args.info_key, "tree_iterations": args.max_iterations, "capacity": 16384}
        with contextlib.ExitStack() as stack:
            primary = stack.enter_context(search())
            shadows = {w: stack.enter_context(search(**shadow_settings, k2=w, m2=w)) for w in widths}
            out = stack.enter_context(open(rows_path, "w", encoding="utf-8"))
            played = play(Shadow(foe_arena.Timed(primary), shadows, out, every=args.every))
    report = {"conditions": {"commit": commit, "dirty": dirty, "sha256": digests, "step": args.step,
                             "widths": widths, "pairs": args.pairs, "seed": hex(seed), "every": args.every,
                             "max_iterations": args.max_iterations, "info_key": args.info_key,
                             "max_steps": args.max_steps, "workers": args.workers, "opponent": name,
                             "table_sha256": table_info["sha256"], "shadow_settings": shadow_settings,
                             "pool": pool_info},
              "digests": {"played": played, "plain": plain, "equal": None if plain is None else plain == played},
              "bounds": bounds(read_rows(rows_path), BUDGET_SECONDS, max(widths))}
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, sort_keys=True)
    print(json.dumps(report["bounds"], sort_keys=True))
    print(json.dumps(report["digests"], sort_keys=True))


if __name__ == "__main__":
    main()
