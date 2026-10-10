"""The live search's latency on this machine (plan 2026-10-10-live-honest-search, Task 4).

python -m duoforge_search.live_latency --checkpoint P --out DIR [--games 16] [--max-steps 200] [--seed S]

Plays games on engine batches of one environment over the reference setups: seat 0 decides through
duoforge_live.search.LiveSearch over the batch's own parts (the request, observation, public record, causes and the
live features, as the live bot does over the tracker's), seat 1 plays the network's raw argmax. Every decision of seat 0
is timed from its feature encoding to the search's answer, with no deadline (the budget is BUDGET seconds), so the
distribution is the search's own. The runtime is JAX on the CPU: the NumPy forward is model v1's only and
params-49333 is model v2. Run it alone on the machine (tools/ci/machine_lock.sh --exclusive).

Writes DIR/latency.json: the warm-up (loading, the first team preview and first turn decision), per boundary kind
n, p50, p95, p99 and max seconds and the outcome causes, and the settings. DIR must lie outside the repository.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

BUDGET = 600.0  # seconds: no deadline during the measurement
SEED = 0x2026101000000401
_KINDS = {"DUOFORGE_BOUNDARY_TEAM_SELECTION": "team_selection", "DUOFORGE_BOUNDARY_TURN": "turn",
          "DUOFORGE_BOUNDARY_REPLACEMENT": "replacement", "DUOFORGE_BOUNDARY_PIVOT": "pivot"}


def _arguments(argv):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.live_latency", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True, help="a format-2 checkpoint in its trained layout")
    p.add_argument("--out", required=True, help="the private output directory (outside the repository)")
    p.add_argument("--games", type=int, default=16)
    p.add_argument("--max-steps", type=int, default=200)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--k", type=int, default=None, help="tests only: another K than the live search's")
    p.add_argument("--m", type=int, default=None, help="tests only: another M than the live search's")
    p.add_argument("--worlds", type=int, default=None, help="tests only: another world count than the live search's")
    return p.parse_args(argv)


def _quantiles(seconds):
    s = np.asarray(seconds, dtype=np.float64)
    p50, p95, p99 = (float(np.quantile(s, q, method="higher")) for q in (0.50, 0.95, 0.99))
    return {"p50": p50, "p95": p95, "p99": p99, "max": float(s.max())}


def main(argv=None):
    args = _arguments(argv)
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(args.out)
    if args.games < 1 or args.max_steps < 1:
        raise ValueError("a measurement needs at least one game and one step")
    import duoforge
    from duoforge import _layout, features
    from duoforge_learn import checkpoint
    from duoforge_learn.selfplay import choices_of
    from duoforge_live import search as live_search
    C = _layout.CONSTANTS
    kinds = {C[name]: label for name, label in _KINDS.items()}

    settings = dict(live_search.HONEST_SETTINGS)
    for name, value in (("k", args.k), ("m", args.m), ("s", args.worlds)):
        if value is not None:
            settings[name] = value
    t = time.perf_counter()
    live = live_search.load(args.checkpoint, settings=settings)
    params, config = checkpoint.load_trained(args.checkpoint)
    model = checkpoint.trained_model(config, params)
    load_seconds = time.perf_counter() - t
    searcher = live.searcher
    encoder, ext_supported = searcher.encoder, searcher.ext_supported
    seconds = {label: [] for label in kinds.values()}
    causes = {label: {} for label in kinds.values()}
    first = {}
    setups = duoforge.reference_setups([0, 1, 2, 3])
    try:
        for game in range(args.games):
            with duoforge.Batch(searcher.worlds.context, setups[game % len(setups):][:1], 1,
                                args.seed + game) as b:
                choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
                for step in range(args.max_steps):
                    if b.result(0) != 0:
                        break
                    b.query_factored()
                    obs, slots, pairs = b.query_encoded(encoder, ext_supported)
                    logp_pairs, logp_team, _ = (np.asarray(x) for x in model.apply(params, obs[0], slots[0], pairs[0]))
                    actions = np.zeros((1, 2), np.int64)
                    team = b.domains["kind"][0] == C["DUOFORGE_CHOICE_TEAM_SELECTION"]
                    for p in (0, 1):
                        if b.requests["requested"][0, p] == 0:
                            continue
                        raw = int(np.argmax(logp_team[p] if team[p] else logp_pairs[p]))
                        actions[0, p] = raw
                        if p == 1:
                            continue
                        label = kinds[int(b.requests["boundary_kind"][0, 0])]
                        start = time.perf_counter()
                        records, statuses = b.public(np.zeros(1, np.uint32))
                        mask, _ = b.public_causes(np.zeros(1, np.uint32))
                        parts = {"request": b.requests[0, 0], "observation": b.observations[0, 0],
                                 "record": records[0].copy(), "status": int(statuses[0]), "causes": int(mask[0])}
                        obs_part, slot_part, pair_mask = features.encode(b.observations[0, 0], b.domains[0, 0],
                                                                         b.observe_ext()[0, 0], ext_supported)
                        outcome = live.decide(parts, obs_part, slot_part, None if team[0] else pair_mask,
                                              key=live_search.decision_key(f"latency-{game}", step), episode=game,
                                              budget=BUDGET)
                        elapsed = time.perf_counter() - start
                        if outcome.fallback == "b":
                            raise RuntimeError(f"game {game} step {step}: class (b) {outcome.reason}")
                        first.setdefault(label, elapsed)
                        seconds[label].append(elapsed)
                        causes[label][outcome.cause] = causes[label].get(outcome.cause, 0) + 1
                        if outcome.action is not None:
                            actions[0, 0] = outcome.action
                    choices_of(b, actions, choices)
                    b.step_factored(choices)
    finally:
        live.close()
    report = {"games": args.games, "max_steps": args.max_steps, "seed": args.seed, "runtime": "jax-cpu",
              "settings": settings, "table_sha256": searcher.table_info["sha256"],
              "warmup": {"load_seconds": load_seconds, "first_seconds": first},
              "boundaries": {label: {"n": len(s), **_quantiles(s), "causes": causes[label]}
                             for label, s in seconds.items() if s}}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latency.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
