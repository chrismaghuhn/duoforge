"""Where the honest search's time per decision goes (issue #355): a reproducible measurement on this machine.

python tools/perf/honest_breakdown.py --checkpoint P --out DIR [--games 8] [--capacities 16384,1024]

Part 1 plays the live search's decisions (X, K = M = 8, 16 worlds, mix 0.5) on engine batches of the reference setups,
as duoforge_search.live_latency does, and sums the search's own cost fields per searched decision: public records,
world builds (from_view and the worlds' policy queries), the team head, the leaves (Batch.expand: clone, reseed,
step and encode of every leaf, in C), the network (the root and world policy calls and the value calls) and the solve.
It does so once per leaf capacity (the value call's padded rows).

Part 2 times the parts of a leaf expansion and of a value call in isolation, median of REPEATS warm runs:
- value calls of the capacity's rows against the 1024 rows one decision needs;
- query_factored against query_encoded on a 1024-environment batch (the encoder's share);
- step_factored of a 1024-environment batch (the engine step without the clone and reseed);
- Batch.expand of the same 1024 leaves (clone + reseed + step + encode);
- from_view of the 16 worlds.

Run it alone on the machine (tools/ci/machine_lock.sh --exclusive). Writes DIR/breakdown.json; DIR must lie outside
the repository (the checkpoint is private; the report quotes aggregates only).
"""
import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np

REPEATS = 20
FIELDS = ("public_records", "world_builds", "team_head", "leaves", "network", "solve")


def _median_seconds(fn, repeats=REPEATS):
    fn()  # warm (JIT, caches)
    out = []
    for _ in range(repeats):
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return statistics.median(out)


def play(ctx, live_search, checkpoint, capacity, games, seed):
    """{field: [seconds per searched decision]} and the decisions' wall times, at one capacity."""
    import duoforge
    from duoforge import _layout, features
    from duoforge_learn import checkpoint as ck
    from duoforge_learn.selfplay import choices_of
    from duoforge_search import honest
    C = _layout.CONSTANTS
    params, config = ck.load_trained(checkpoint)
    model = ck.trained_model(config, params)
    encoder, ext = ck.encoder_of(config), ck.ext_supported_of(config)
    table, _, _ = honest.live_spread_table(ctx)
    costs = {f: [] for f in FIELDS}
    walls = []
    with honest.Honest(ctx, model, params, encoder, ext, k=8, m=8, s=16, rule="mix", lam=0.5, table=table,
                       capacity=capacity) as search:
        setups = duoforge.reference_setups([0, 1, 2, 3])
        for game in range(games):
            search.clear()
            with duoforge.Batch(ctx, setups[game % 4:][:1], 1, seed + game) as b:
                choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
                for step in range(200):
                    if b.result(0) != 0:
                        break
                    obs, slots, pairs = b.query_encoded(encoder, ext)
                    lp, lt, _ = (np.asarray(x) for x in model.apply(params, obs[0], slots[0], pairs[0]))
                    team = b.domains["kind"][0] == C["DUOFORGE_CHOICE_TEAM_SELECTION"]
                    actions = np.zeros((1, 2), np.int64)
                    for p in (0, 1):
                        if b.requests["requested"][0, p]:
                            actions[0, p] = int(np.argmax(lt[p] if team[p] else lp[p]))
                    if b.requests["requested"][0, 0]:
                        t = time.perf_counter()
                        acts, records = search.decide(b, [0], [0], [(seed + game * 1000 + step) % 2 ** 64], [False])
                        wall = time.perf_counter() - t
                        r = records[0]
                        if r["kind"] == "searched":
                            walls.append(wall)
                            for f in FIELDS:
                                costs[f].append(float(r["cost"][f]))
                        if r["kind"] in ("searched", "team", "forced", "raw"):
                            actions[0, 0] = int(acts[0])
                    choices_of(b, actions, choices)
                    b.step_factored(choices)
    return costs, walls


def parts(ctx, checkpoint, capacity):
    """Median seconds of the isolated parts (Part 2)."""
    import duoforge
    from duoforge import _layout, view
    from duoforge_learn import checkpoint as ck
    params, config = ck.load_trained(checkpoint)
    model = ck.trained_model(config, params)
    encoder, ext = ck.encoder_of(config), ck.ext_supported_of(config)
    width = len(config["features"])
    out = {}
    for rows in sorted({capacity, 1024}):
        x = np.zeros((rows, width), np.float32)
        out[f"value_{rows}_rows"] = _median_seconds(lambda: np.asarray(model.value(params, x)))
    n = 1024
    setups = np.resize(duoforge.reference_setups([0, 1, 2, 3]), n)
    with duoforge.Batch(ctx, setups, 8, 7) as b, duoforge.Batch(ctx, setups, 8, 7) as leaves:
        b.query_factored()
        picks = np.zeros((n, 2), _layout.FACTORED_CHOICE)
        picks["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
        b.step_factored(picks)
        b.query_factored()
        out["query_factored_1024"] = _median_seconds(b.query_factored)
        out["query_encoded_1024"] = _median_seconds(lambda: b.query_encoded(encoder, ext))
        policy = duoforge.RandomPolicy(3, n)
        policy.start_episodes(np.arange(n, dtype=np.uint32), np.zeros(n, np.uint32))
        choices = policy.choose_factored(b)
        # the step alone: a fresh copy of the same states each time (reset to the same TURN is not available, so the
        # copy is the expand below; here the batch steps once from the TURN, measured by repetition on clones)
        roots = b
        keys = np.zeros(n, np.uint64)
        viewers = np.zeros(n, np.uint8)
        envs = np.arange(n, dtype=np.uint32)
        out["expand_1024"] = _median_seconds(lambda: leaves.expand(roots, encoder, ext, 1, keys, viewers, envs, envs,
                                                                   choices))
        with duoforge.Batch(ctx, setups, 8, 7) as once:
            once.query_factored()
            once.step_factored(picks)
            once.query_factored()
            t = time.perf_counter()
            once.step_factored(choices)
            out["step_factored_1024_once"] = time.perf_counter() - t
    with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 9) as root, \
            duoforge.Batch(ctx, np.resize(duoforge.reference_setups([0]), 16), 8, 9) as worlds:
        root.query_factored()
        root.step_factored(picks[:1])
        root.query_factored()
        records, statuses = root.public(np.zeros(1, np.uint32))
        from duoforge import privileged
        h = view.hypotheses(16)
        for w in range(16):
            h[w] = privileged.hypothesis(root, 0, 0)
        rec = np.repeat(records[:1].reshape(1), 16)
        out["from_view_16"] = _median_seconds(lambda: worlds.from_view(rec, h))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="python tools/perf/honest_breakdown.py", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--games", type=int, default=8)
    p.add_argument("--capacities", default="16384,1024")
    p.add_argument("--seed", type=int, default=0x2026101200000101)
    args = p.parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(args.out)
    import duoforge
    from duoforge import _layout
    from duoforge_live import search as live_search
    report = {"games": args.games, "seed": args.seed, "settings": live_search.HONEST_SETTINGS, "runs": {}, "parts": {}}
    with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        for capacity in (int(c) for c in args.capacities.split(",")):
            costs, walls = play(ctx, live_search, args.checkpoint, capacity, args.games, args.seed)
            report["runs"][str(capacity)] = {
                "decisions": len(walls), "wall_median": statistics.median(walls), "wall_mean": statistics.fmean(walls),
                "fields_mean": {f: statistics.fmean(v) for f, v in costs.items()},
                "fields_share": {f: sum(v) / sum(walls) for f, v in costs.items()}}
            report["parts"][str(capacity)] = parts(ctx, args.checkpoint, capacity)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "breakdown.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
