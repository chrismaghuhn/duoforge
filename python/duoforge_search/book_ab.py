"""Paired preview-book A/B CLI. Every output is private and outside the repo.

The candidate checkpoint without/with book plays the unchanged checkpoint and
the fixed stage-1 panel. Both arms get the same ordered team rows, batch seed,
workers and cutoff. Bootstrap resamples keep paired seat orders together.
Nothing here starts training or turn search.
"""
import argparse
import json
import os
import platform
from pathlib import Path

import numpy as np

import duoforge
from duoforge_learn import book_preview, evaluate, ladder, suite
from duoforge_replay.dataset import refuse_repository

from . import arena

SEED = 0x2026100400000228
PANEL = ("params-0", "params-3600", "params-11000")


def paired_rows(n_teams, games=2000, seed=SEED):
    """Exactly games rows, each matchup in both seat orders (adjacent rows)."""
    if n_teams < 1 or games < 2 or games % 2:
        raise ValueError("games must be a positive even budget (at least 2), with at least one team")
    source = suite.make_suite(n_teams, seed, games=1, budget=games // 2)
    if n_teams <= 8:
        source = source[source["learner_seat"] == 0]
        source = source[np.random.default_rng(seed).permutation(len(source))]
    rows = np.zeros(games, dtype=suite.SUITE)
    for pair in range(games // 2):
        src = source[pair % len(source)]
        seat = int(src["learner_seat"])
        mine, other = int(src[f"side{seat}"]), int(src[f"side{1-seat}"])
        rows[2 * pair] = mine, other, 0, pair
        rows[2 * pair + 1] = other, mine, 1, pair
    return rows


def pool_group(team_id):
    if team_id in ("A", "B", "C") or team_id.startswith("PP_"):
        return "PP_/A/B/C"
    return "LL_" if team_id.startswith("LL_") else "other"


def _arm(records, resamples):
    values = arena.scores(records)
    paired_seats = values.reshape(-1, 2).mean(axis=1)
    return {"games": len(records), "score": float(values.mean()),
            "score_95": list(arena.bootstrap_mean(paired_seats, resamples)),
            "unfinished": int(records["unfinished"].sum()), "unresolved": int(records["unresolved"].sum())}


def comparison(baseline, treatment, rows, pool_ids, player, resamples=2000):
    """Scores/paired seat-cluster CIs, book coverage/fallbacks, learner pool groups."""
    if len(rows) % 2 or baseline.shape != treatment.shape or len(baseline) != len(rows):
        raise ValueError("A/B records must match the same paired rows")
    if (rows["learner_seat"][::2] != 0).any() or (rows["learner_seat"][1::2] != 1).any() or \
            not np.array_equal(rows["side0"][::2], rows["side1"][1::2]) or \
            not np.array_equal(rows["side1"][::2], rows["side0"][1::2]):
        raise ValueError("bootstrap rows must keep both seat orders of a matchup together")
    for field in ("side0", "side1", "learner_seat"):
        if not np.array_equal(baseline[field], rows[field]) or not np.array_equal(treatment[field], rows[field]):
            raise ValueError("A/B pairing records differ from the measured suite")
    def result(indices):
        a, b = baseline[indices], treatment[indices]
        left, right = arena.scores(a).reshape(-1, 2).mean(axis=1), arena.scores(b).reshape(-1, 2).mean(axis=1)
        return {"without_book": _arm(a, resamples), "with_book": _arm(b, resamples),
                "paired_difference": {"score": float((right - left).mean()),
                    "score_95": list(arena.bootstrap_paired(right, left, resamples))},
                "book": player.summary(set(int(i) for i in indices), games=len(indices))}
    groups = {}
    mine = np.where(rows["learner_seat"] == 0, rows["side0"], rows["side1"])
    labels = np.array([pool_group(pool_ids[int(i)]) for i in mine])
    for label in sorted(set(labels)):
        groups[label] = result(np.flatnonzero(labels == label))
    return {**result(np.arange(len(rows))), "by_pool_group": groups}


def run(context, pool, rows, candidate, opponents, evidence, args):
    """Measured arms only; callers may use a tiny synthetic checkpoint/book."""
    output = Path(args.out)
    refuse_repository(output)
    if evidence is None:
        raise ValueError("A/B requires loaded book evidence")
    if output.exists() and any(output.iterdir()):
        raise ValueError("A/B output directory must be empty; refusing to mix measurements")
    output.mkdir(parents=True, exist_ok=True)
    team_sheets = book_preview.sheets(context, pool)
    reports = {}
    for name, opponent in opponents.items():
        raw = evaluate.play_suite(context, pool, rows, candidate, opponent, args.workers, args.seed,
                                  max_steps=args.max_steps)
        player = book_preview.wrap(candidate, evidence, team_sheets, rows, args)
        changed = evaluate.play_suite(context, pool, rows, player, opponent, args.workers, args.seed,
                                      max_steps=args.max_steps)
        arena._write_games(str(output / f"{name}-without-book.csv"), raw)
        arena._write_games(str(output / f"{name}-with-book.csv"), changed)
        (output / f"{name}-preview.json").write_text(json.dumps(player.events, indent=1) + "\n", encoding="utf-8")
        reports[name] = comparison(raw, changed, rows, pool.ids, player, args.resamples)
    return reports


def main(argv=None):
    p = argparse.ArgumentParser(description="Private paired preview-book A/B; no training/search. Default 2000 games per arm per opponent.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--out", required=True, help="empty private output directory outside all repo worktrees")
    p.add_argument("--games", type=int, default=2000)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-steps", type=int, default=arena.MAX_STEPS)
    p.add_argument("--seed", type=lambda x: int(x, 0), default=SEED)
    p.add_argument("--resamples", type=int, default=arena.RESAMPLES)
    p.add_argument("--panel", default=",".join(PANEL), help="stage-1 BC,3600,11000 paths or checkpoint names")
    book_preview.add_arguments(p)
    args = p.parse_args(argv)
    if args.book is None:
        p.error("--book is required for an A/B")
    if args.workers < 1 or args.max_steps < 1 or args.resamples < 1 or not 0 <= args.seed < 2 ** 64:
        p.error("workers, max-steps, resamples must be positive; seed must be uint64")
    if args.games < 2 or args.games % 2:
        p.error("--games must be even and at least 2")
    panel = args.panel.split(",")
    if len(panel) != 3 or not all(panel):
        p.error("--panel must name BC,3600,11000 checkpoints")
    refuse_repository(args.out)
    evidence = book_preview.load_options(args)
    # Fail missing inputs before creating outputs or playing even one arm.
    paths = [arena._checkpoint_path(args.run_dir, args.checkpoint)] + [arena._checkpoint_path(args.run_dir, n) for n in panel]
    checkpoint_hashes = [arena._sha256(path) for path in paths]
    from duoforge_learn import checkpoint, policy
    import jax
    arena.require_deterministic_gpu(jax)
    models = {}
    def load(path, name):
        params, config = checkpoint.load_current(path)
        cfg = checkpoint.model_config(config, params)
        key = json.dumps(cfg, sort_keys=True)
        if key not in models:
            models[key] = policy.make(cfg)
        return evaluate.Player(models[key], params, checkpoint.encoder_of(config), name,
                               checkpoint.ext_supported_of(config)), config
    candidate, cfg = load(paths[0], "candidate")
    opponents, configs = {"same_checkpoint": candidate}, [cfg]
    for label, path in zip(("BC", "3600", "11000"), paths[1:]):
        opponents[label], config = load(path, label)
        configs.append(config)
    pool, kind = ladder._pool_of(args.run_dir)
    rows = paired_rows(len(pool.ids), args.games, args.seed)
    with duoforge.Context(data_kind=kind) as context:
        for config in configs:
            if config.get("format") == 2:
                checkpoint.check_ids(config, context)
        reports = run(context, pool, rows, candidate, opponents, evidence, args)
    conditions = {"games_per_arm_per_opponent": args.games, "workers": args.workers,
                  "seed": args.seed, "max_steps": args.max_steps, "resamples": args.resamples,
                  "bootstrap_unit": "paired seat orders", "book_sha256": evidence.source_sha256,
                  "book_mode": args.book_mode, "book_min_count": args.book_min_count, "book_weight": args.book_weight,
                  "checkpoint_sha256": checkpoint_hashes, "pool": list(pool.ids),
                  "pool_sha256": list(pool.sha256), "data_kind": int(kind), "commit": arena._commit(),
                  "library": duoforge.version(), "numpy": np.__version__, "python": platform.python_version(),
                  "jax": jax.__version__, "backend": jax.default_backend(), "devices": [str(d) for d in jax.devices()],
                  "xla_flags": os.environ.get("XLA_FLAGS", "")}
    Path(args.out, "summary.json").write_text(json.dumps(arena._finite({"conditions": conditions, "opponents": reports}),
                                                     indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Private A/B results: {Path(args.out, 'summary.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
