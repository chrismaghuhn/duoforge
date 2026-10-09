"""Stage 3 P1 pilot run tooling (tools/cloud/p1_pilot, used by run.sh): write the collector's DataManifest with every
hash computed exactly as `python -m duoforge_learn.collect_expert` checks it, and freeze the production rounds from
the collection smoke. It implements no battle rule and no learner logic: the hashes come from the collector's own
helpers (collect_expert.model_hash/ids_hash, expert_eval.pool_sha256, honest.spread_table).

usage (PYTHONPATH=python, DUOFORGE_LIBRARY=<lib>, JAX on the CPU as the collector):
  python p1_manifest.py write --init PARAMS --out MANIFEST --rounds R --first-game-id G --workers W
      --seed S --split-seed SS --source-commit SHA --role smoke|production [--teams IDS --team-weights WS
      --teams-root ROOT] [--compiler TEXT]
  python p1_manifest.py freeze --smoke-json SMOKE_RESULT.json [--ledger PILOT_LEDGER] [--cpu-budget 28800]
      [--out FREEZE.json]

freeze reads the collector's final JSON line of the smoke and prints R = ceil(1.25*16384/(512*t)), t = targets/games
(P1 plan, smoke policy). Exit codes of freeze: 0 GO; 20 STOP t = 0; 21 STOP the forecast generation CPU exceeds the
budget; 22 STOP primary work fallbacks above 1 % of the selected roots. write exits 0, or 2 for a refused input.
"""
import argparse
import json
import math
import platform
import sys
from pathlib import Path

LABELS = 16384  # expert_data.LABEL_LIMIT, checked against it in write
GAMES_PER_ROUND = 512
MARGIN = 1.25  # fixed by the plan, not tuned
CPU_BUDGET = 28800.0  # 8 CPU core-hours of generation (P1 plan C5)
WORK_FALLBACK_MAX = 0.01  # primary work fallbacks / selected eligible roots


def pool_of(context, args):
    """The collector CLI's pool rule, verbatim."""
    import duoforge
    from duoforge import teams
    weights = None if args.team_weights is None else [float(w) for w in args.team_weights.split(",")]
    if args.teams is None:
        pool = teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0])
        return pool if weights is None else pool.with_weights(weights)
    return teams.load(context, [t.strip() for t in args.teams.split(",")], root=args.teams_root, weights=weights)


def write(args):
    import duoforge
    import jax
    from duoforge_learn import checkpoint, collect_expert as ce
    from duoforge_learn.train import DATA_KINDS
    from duoforge_search import expert_data as ed, expert_eval, honest
    if ed.LABEL_LIMIT != LABELS:
        raise SystemExit(f"expert_data.LABEL_LIMIT is {ed.LABEL_LIMIT}, this tool freezes with {LABELS}")
    if Path(args.out).exists():
        raise SystemExit(f"{args.out} exists: a manifest is written once")
    sha = ce._file_sha(args.init)
    params, config = checkpoint.load_trained(args.init)
    if checkpoint.encoder_of(config) != 4:
        raise SystemExit(f"{args.init} is encoder {checkpoint.encoder_of(config)}; P1 pins 4")
    with duoforge.Context(data_kind=DATA_KINDS[config["data"]["kind"]]) as ctx:
        pool = pool_of(ctx, args)
        _, _, info = honest.spread_table(ctx)
        manifest = ed.DataManifest(
            source_commit=args.source_commit, checkpoint_hash=sha,
            model_hash=ce.model_hash(checkpoint.model_config(config, params)), encoder=4,
            ids_hash=ce.ids_hash(ctx), pool_hash=expert_eval.pool_sha256(pool), belief_hash=info["sha256"],
            seed=args.seed, split_seed=args.split_seed, key_version=ed.KEY_VERSION, device="cpu",
            runtime=f"python {platform.python_version()}, jax {jax.__version__}", compiler=args.compiler,
            capacity=1024, workers=args.workers, parallel_games=GAMES_PER_ROUND,
            game_count=GAMES_PER_ROUND * args.rounds, rounds=args.rounds, first_game_id=args.first_game_id,
            obs_width=ed.features.obs_size(4), slot_width=ed.features.SLOT_FEATURES,
            teacher_config={"k": 8, "m": 8, "worlds": 16, "lam": 0.5},
            budget={"labels": LABELS, "generation_core_hours": args.core_hours},
            evaluation={"plan": "docs/superpowers/plans/2026-10-08-stage3-p1-pilot.md C5",
                        "role": args.role})
    sha_out = ed.write_manifest(Path(args.out), manifest)
    print(json.dumps({"manifest": args.out, "sha256": sha_out, "rounds": args.rounds, "games": manifest.game_count,
                      "first_game_id": args.first_game_id, "pool_teams": len(pool.ids), "role": args.role}))
    return 0


def freeze(args):
    lines = [line for line in Path(args.smoke_json).read_text().splitlines() if line.strip()]
    if not lines:
        raise SystemExit(f"{args.smoke_json}: no collector result line")
    smoke = json.loads(lines[-1])
    if not smoke.get("complete"):
        raise SystemExit(f"{args.smoke_json}: the smoke is not complete ({smoke})")
    games, targets = smoke["games"], smoke["targets"]
    out = {"smoke_games": games, "smoke_targets": targets, "selected": smoke.get("selected"),
           "work_exhausted": smoke.get("work_exhausted"), "public_refusals": smoke.get("public_refusals"),
           "cuts": smoke.get("cuts"), "engine_unsupported": smoke.get("engine_unsupported")}
    code, reasons = 0, []
    if not games or not targets:
        out |= {"status": "STOP", "stop_reasons": [f"t = 0 (games {games}, targets {targets}): re-plan"]}
        _emit(out, args)
        return 20
    t = targets / games
    rounds = math.ceil(MARGIN * LABELS / (GAMES_PER_ROUND * t))
    out |= {"t_targets_per_game": t, "rounds": rounds, "games": GAMES_PER_ROUND * rounds}
    selected = smoke.get("selected") or 0
    fallback = (smoke.get("work_exhausted") or 0) / selected if selected else 0.0
    out["work_fallback_share"] = fallback
    if fallback > WORK_FALLBACK_MAX:
        reasons.append(f"primary work fallbacks {fallback:.4%} of the selected roots exceed 1 %")
        code = code or 22
    if args.ledger:
        ledger = json.loads(Path(args.ledger).read_text())
        smoke_cpu = ledger["phases"].get("generate", {}).get("cpu_core_seconds", ledger["cpu_core_seconds"])
        forecast = smoke_cpu + smoke_cpu / games * GAMES_PER_ROUND * rounds
        out |= {"smoke_cpu_core_seconds": smoke_cpu, "forecast_generation_cpu_core_seconds": forecast,
                "cpu_budget": args.cpu_budget}
        if forecast > args.cpu_budget:
            reasons.append(f"forecast generation CPU {forecast:.0f} s exceeds the budget {args.cpu_budget:.0f} s")
            code = code or 21
    out |= {"status": "STOP" if reasons else "GO", "stop_reasons": reasons}
    _emit(out, args)
    return code


def _emit(out, args):
    text = json.dumps(out, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)


def main(argv=None):
    p = argparse.ArgumentParser(prog="p1_manifest.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--init", required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--rounds", type=int, required=True)
    w.add_argument("--first-game-id", type=int, required=True)
    w.add_argument("--workers", type=int, required=True, choices=(4, 8, 14))
    w.add_argument("--seed", type=lambda v: int(v, 0), required=True)
    w.add_argument("--split-seed", type=lambda v: int(v, 0), required=True)
    w.add_argument("--source-commit", required=True)
    w.add_argument("--compiler", default="gcc, Release")
    w.add_argument("--core-hours", type=float, default=8.0)
    w.add_argument("--role", choices=("smoke", "production"), required=True)
    w.add_argument("--teams", default=None)
    w.add_argument("--team-weights", default=None)
    w.add_argument("--teams-root", default="data/teams")
    f = sub.add_parser("freeze")
    f.add_argument("--smoke-json", required=True)
    f.add_argument("--ledger", default=None, help="the pilot ledger after the smoke (forecast of the generation CPU)")
    f.add_argument("--cpu-budget", type=float, default=CPU_BUDGET)
    f.add_argument("--out", default=None)
    args = p.parse_args(argv)
    return write(args) if args.cmd == "write" else freeze(args)


if __name__ == "__main__":
    sys.exit(main())
