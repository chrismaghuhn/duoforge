"""Stage 3 P2 Task 5: the paired measurement of per-root vs per-tick teacher labeling.

Lockstep roots play seeded random moves (so every path sees the same states); each step observes every
learner request and labels the admitted roots (the 1/8 SELECT gate, no label cap) through one of three paths:
per_root (label_decision), tick_nodedup (label_tick, every open leaf its own row) and tick (label_tick with
dedup). Decisions are digested per path; counters, wall and CPU time are measured around the labeling only.
No battle rules here; outputs stay private.

CLI (an owner window): python -m duoforge_search.tickbench --checkpoint PATH --device cpu|gpu|split --out PATH
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

PATHS = ("per_root", "tick_nodedup", "tick")


class Counted:
    """A model proxy counting value and policy calls, rows and seconds; with split=True the policy runs on the
    CPU and the value head on the GPU."""

    def __init__(self, model, params, split=False):
        self.model, self.params, self.split = model, params, split
        self.calls = {"value": 0, "policy": 0}
        self.rows = {"value": 0, "policy": 0}
        self.seconds = {"value": 0.0, "policy": 0.0}
        if split:
            import jax
            self._cpu, self._gpu = jax.devices("cpu")[0], jax.devices("gpu")[0]
            self.params_cpu = jax.device_put(params, self._cpu)
            self.params_gpu = jax.device_put(params, self._gpu)

    def __getattr__(self, name):
        return getattr(self.model, name)

    def value(self, params, rows):
        start = time.perf_counter()
        if self.split:
            import jax
            out = np.asarray(self.model.value(self.params_gpu, jax.device_put(np.asarray(rows), self._gpu)))
        else:
            out = np.asarray(self.model.value(params, rows))
        self.seconds["value"] += time.perf_counter() - start
        self.calls["value"] += 1
        self.rows["value"] += int(np.shape(rows)[0])
        return out

    def apply(self, params, *inputs):
        start = time.perf_counter()
        if self.split:
            import jax
            out = self.model.apply(self.params_cpu, *(jax.device_put(np.asarray(x), self._cpu) for x in inputs))
            out = tuple(np.asarray(x) for x in out)
        else:
            out = tuple(np.asarray(x) for x in self.model.apply(params, *inputs))
        self.seconds["policy"] += time.perf_counter() - start
        self.calls["policy"] += 1
        self.rows["policy"] += int(np.shape(inputs[0])[0])
        return out


def run(make_search, make_roots, *, path, steps, config, manifest, seed, select=None, cpu_seconds=None):
    """One repetition of one path: {labels, targets, seconds, cpu_seconds, digest, tick counters}."""
    from duoforge_learn.ledger import cpu_seconds as process_cpu
    from . import expert, lookahead
    from .expert_data import DECISION_BOUNDARIES, DecisionKey, is_selected
    cpu_seconds = cpu_seconds or process_cpu
    select = select or (lambda key: is_selected(key, manifest.seed))
    import duoforge
    digest = hashlib.sha256()
    totals = {"labels": 0, "targets": 0, "seconds": 0.0, "cpu_seconds": 0.0, "leaves": 0, "open_leaves": 0,
              "unique": 0, "tick_value_calls": 0}
    with make_search() as search, make_roots() as roots:
        policy = duoforge.RandomPolicy(seed, roots.envs)
        every = np.arange(roots.envs)
        for _ in range(steps):
            roots.query_factored()
            games = np.array([manifest.first_game_id + roots.episode(int(e)) * roots.envs + int(e) for e in every])
            seats = games % 2
            asked = roots.requests["requested"][every, seats] != 0
            if asked.any():
                expert.observe(search, roots, every[asked], seats[asked])
            _, _, pairs = roots.query_encoded(search.encoder, search.ext_supported)
            tick = []
            for e in np.flatnonzero(asked):
                p = int(seats[e])
                boundary = lookahead._BOUNDARIES[int(roots.requests[e, p]["boundary_kind"])]
                legal = np.flatnonzero(pairs[e, p].reshape(-1))
                key = DecisionKey(int(games[e]), p, int(roots.requests[e, p]["epoch"]))
                if boundary in DECISION_BOUNDARIES and legal.size >= 2 and select(key):
                    tick.append(expert.TickRoot(int(e), p, key, int(legal[0]), -1.0))
            if tick:
                start, cpu = time.perf_counter(), cpu_seconds()
                if path == "per_root":
                    decisions = [expert.label_decision(search, roots, env=r.env, seat=r.seat, key=r.key,
                                                       raw_action=r.raw_action, raw_logp=r.raw_logp, last_step=False,
                                                       config=config, manifest=manifest) for r in tick]
                else:
                    stats = {}
                    decisions = expert.label_tick(search, roots, tick, last_step=False, config=config,
                                                  manifest=manifest, dedup=path == "tick", stats=stats)
                    for name in ("leaves", "open_leaves", "unique"):
                        totals[name] += stats[name]
                    totals["tick_value_calls"] += stats["value_calls"]
                totals["seconds"] += time.perf_counter() - start
                totals["cpu_seconds"] += cpu_seconds() - cpu
                totals["labels"] += len(decisions)
                totals["targets"] += sum(d.status is expert.RowStatus.TARGET for d in decisions)
                for d in decisions:
                    digest.update(expert.decision_bytes(d))
            roots.step_factored(policy.choose_factored(roots))
            roots.reset_terminal()
        model = search.model
        if isinstance(model, Counted):
            totals["calls"], totals["rows"], totals["model_seconds"] = dict(model.calls), dict(model.rows), \
                dict(model.seconds)
    totals["digest"] = digest.hexdigest()
    return totals


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m duoforge_search.tickbench")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--device", choices=("cpu", "gpu", "split"), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--envs", type=int, default=512)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--workers", type=int, default=14)
    args = parser.parse_args(argv)
    if args.envs < 2 or args.envs > 512 or args.envs % 2 or args.workers not in (4, 8, 14):
        # The manifest pins 512 parallel games and 4/8/14 workers; an odd count would move a game's learner seat
        # across resets and with it the leave-foe-source-out exclusion.
        parser.error("--envs must be even and at most 512, --workers one of 4, 8, 14")
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(args.out)
    os.environ["JAX_PLATFORMS"] = {"cpu": "cpu", "gpu": "cuda", "split": "cuda,cpu"}[args.device]
    import dataclasses

    import jax

    import duoforge
    from duoforge import _layout, teams
    from duoforge_learn import checkpoint, policy
    from . import expert, honest, lookahead
    from .expert_data import DataManifest, KEY_VERSION
    from .expert_eval import pool_sha256
    from duoforge import features
    with open(args.checkpoint, "rb") as f:
        checkpoint_sha = hashlib.sha256(f.read()).hexdigest()
    params, config_ = checkpoint.load_current(args.checkpoint)
    model = policy.make(checkpoint.model_config(config_, params))
    encoder, ext = checkpoint.encoder_of(config_), checkpoint.ext_supported_of(config_)
    seed = 0x2026100900000512
    report = {"device": args.device, "envs": args.envs, "steps": args.steps, "workers": args.workers,
              "checkpoint_sha256": checkpoint_sha, "jax": jax.__version__, "jax_devices": [str(d) for d in jax.devices()],
              "xla_flags": os.environ.get("XLA_FLAGS", ""), "paths": {}}
    with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        table, source_ids, info = honest.spread_table(ctx)
        ids = list(honest.SPREAD_SOURCES)
        pool = teams.load(ctx, ids, root=str(Path(honest.__file__).resolve().parents[2] / "data" / "teams"))
        rng = np.random.default_rng(seed)
        side0, side1 = rng.integers(0, len(ids), args.envs), rng.integers(0, len(ids), args.envs)
        setups = pool.setups(side0, side1)
        rounds = 4
        manifest = DataManifest(source_commit="0" * 40, checkpoint_hash=checkpoint_sha, model_hash="0" * 64,
                                encoder=encoder, ids_hash="0" * 64, pool_hash=pool_sha256(pool), belief_hash=info["sha256"],
                                seed=7, split_seed=9, key_version=KEY_VERSION, device="cpu", runtime=jax.__version__,
                                compiler="bench", capacity=1024, workers=args.workers,
                                parallel_games=512, game_count=512 * rounds, rounds=rounds, first_game_id=0,
                                obs_width=features.obs_size(encoder), slot_width=features.SLOT_FEATURES,
                                teacher_config={"k": 8, "m": 8, "worlds": 16, "lam": .5}, budget={"labels": 16384},
                                evaluation={"bench": True})
        config = expert.TeacherConfig.from_manifest(manifest)
        with duoforge.Batch(ctx, setups[:1], 1, seed) as probe:
            mask = int(probe.observe_ext()[0, 0]["supported"])
        games = np.arange(args.envs)
        foe_team = np.where(games % 2 == 0, side1, side0)  # learner_seat(game) = game % 2 in episode 0
        excluded = [source_ids.get(ids[int(t)]) for t in foe_team]

        def make_search():
            search = honest.Honest(ctx, model, params, encoder, ext, k=8, m=8, s=16, rule="mix", capacity=1024,
                                   workers=args.workers, table=table, exclude_teams=excluded)
            search.model = Counted(model, params, split=args.device == "split")
            return search

        def make_roots():
            return duoforge.Batch(ctx, setups, args.workers, seed)

        for path in PATHS:
            reps = []
            for rep in range(3):  # one warm-up, two timed repetitions
                result = run(make_search, make_roots, path=path, steps=args.steps, config=config, manifest=manifest,
                             seed=seed)
                reps.append(result)
            report["paths"][path] = {"warmup": reps[0], "timed": reps[1:]}
        if args.device in ("gpu", "split"):
            stats = jax.devices("gpu")[0].memory_stats() or {}
            report["gpu_peak_bytes"] = stats.get("peak_bytes_in_use")
    digests = {path: {r["digest"] for r in v["timed"] + [v["warmup"]]} for path, v in report["paths"].items()}
    report["identity"] = {"per_path_repeat": all(len(d) == 1 for d in digests.values()),
                          "across_paths": len(set().union(*digests.values())) == 1}
    rate = {path: [r["labels"] / r["seconds"] if r["seconds"] else 0.0 for r in v["timed"]]
            for path, v in report["paths"].items()}
    report["decisions_per_second"] = rate
    report["speedup_tick_vs_per_root"] = [t / p if p else None for t, p in zip(rate["tick"], rate["per_root"])]
    report["gate"] = {"min_speedup": 1.25, "identity": report["identity"]["per_path_repeat"] and
                      report["identity"]["across_paths"],
                      "pass": bool(report["identity"]["per_path_repeat"] and report["identity"]["across_paths"] and
                                   all(s is not None and s >= 1.25 for s in report["speedup_tick_vs_per_root"]))}
    with open(args.out, "x", encoding="utf-8") as f:
        json.dump(report, f, indent=1, sort_keys=True, default=str)
    print(json.dumps({k: report[k] for k in ("decisions_per_second", "speedup_tick_vs_per_root", "identity", "gate")}))
    return 0



if __name__ == "__main__":
    sys.exit(main())
