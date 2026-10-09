"""Preview-only N/E/X measurement: value vs raw turn-1 rollout, private outputs."""
import argparse
import json
from pathlib import Path

import numpy as np

import duoforge
from duoforge_learn import checkpoint, evaluate, ladder
from duoforge_learn.selfplay import TEAM
from duoforge_replay.dataset import refuse_repository

from . import arena, book_ab, honest


class RawPreview(evaluate.Player):
    """Capture the actual baseline preview rank, not another model batch's argmax."""
    def __init__(self, base):
        self.base, self.name, self.preview = base, base.name, {}
    def indices(self, batch, choices, step=None, seats=None, last_step=None):
        out = self.base.indices(batch, choices, step, seats, last_step)
        for e, p in enumerate(seats):
            if p >= 0 and batch.requests[e, p]["requested"] and batch.domains[e, p]["kind"] == TEAM:
                self.preview[e] = int(out[e, p])
        return out


class PreviewPlayer(evaluate.Player):
    """Literal raw Player calls outside preview; no shape-dependent turn changes."""
    def __init__(self, raw, searched):
        self.raw, self.searched, self.name = raw, searched, searched.name
    def indices(self, batch, choices, step=None, seats=None, last_step=None):
        result = self.raw.indices(batch, choices, step, seats, last_step)
        preview_seats = np.full(batch.envs, -1, np.int64)
        for e, p in enumerate(seats):
            if p >= 0 and batch.requests[e, p]["requested"] and batch.domains[e, p]["kind"] == TEAM:
                preview_seats[e] = p
        selected = np.flatnonzero(preview_seats >= 0)
        if selected.size:
            searched = self.searched.indices(batch, choices, step, preview_seats, last_step)
            result[selected, preview_seats[selected]] = searched[selected, preview_seats[selected]]
        return result


def summary(records, baseline, decisions, baseline_preview, resamples):
    def clustered(rec):
        return arena.scores(rec).reshape(-1, 2).mean(axis=1)
    for field in ("side0", "side1", "learner_seat"):
        if not np.array_equal(records[field], baseline[field]):
            raise ValueError("preview measurement pairings differ")
    b, a = clustered(records), clustered(baseline)
    previews = [r for r in decisions if r["boundary"] == "TEAM_SELECTION"]
    if len({r["env"] for r in previews}) != len(previews):
        raise ValueError("more than one preview per game")
    changed = sum(r["choice"] != baseline_preview[r["env"]] for r in previews)
    searched_changed = sum(r["kind"] == "searched" and r["choice"] != baseline_preview[r["env"]] for r in previews)
    fallback = {}
    for record in previews:
        if record["kind"] == "unreconstructible":
            for cause in record["causes"]:
                fallback[cause] = fallback.get(cause, 0) + 1
    return {"games": len(records), "score": float(b.mean()), "score_95": list(arena.bootstrap_mean(b, resamples)),
            "paired_vs_raw": {"score": float((b - a).mean()), "score_95": list(arena.bootstrap_paired(b, a, resamples))},
            "preview_games": len(previews), "preview_changed": changed, "preview_changed_share": changed / len(records),
            "preview_changed_searched": searched_changed, "preview_changed_fallback": changed - searched_changed,
            "fallback_causes": fallback, "unfinished": int(records["unfinished"].sum()),
            "unresolved": int(records["unresolved"].sum()), "timing": arena.timing(decisions)}


def both_searched_difference(value_records, turn1_records, value_decisions, turn1_decisions, resamples):
    """Conditional diagnostic, preserving seat clusters even with one included seat.
    This post-treatment cohort is not an unbiased whole-suite treatment effect.
    """
    if len(value_records) != len(turn1_records) or len(value_records) % 2:
        raise ValueError("both-searched comparison needs matched seat pairs")
    for field in ("side0", "side1", "learner_seat"):
        if not np.array_equal(value_records[field], turn1_records[field]):
            raise ValueError("both-searched pairings differ")
    sets = [{r["env"] for r in decisions if r["boundary"] == "TEAM_SELECTION" and r["kind"] == "searched"}
            for decisions in (value_decisions, turn1_decisions)]
    selected = np.zeros(len(value_records), bool)
    selected[list(sets[0] & sets[1])] = True
    games = int(selected.sum())
    if not games:
        return {"games": 0, "score": None, "score_95": None, "status": "no_common_searched_games"}
    diff = arena.scores(turn1_records) - arena.scores(value_records)
    sums = (diff * selected).reshape(-1, 2).sum(axis=1)
    weights = selected.reshape(-1, 2).sum(axis=1)
    sums, weights = sums[weights > 0], weights[weights > 0]
    draws = arena._resampled(len(weights), resamples, arena.BOOTSTRAP_SEED)
    estimates = sums[draws].sum(axis=1) / weights[draws].sum(axis=1)
    return {"games": games, "score": float(diff[selected].mean()), "score_95": list(arena._interval(estimates)),
            "status": "conditional_on_both_modes_searched", "bootstrap_unit": "paired seat clusters"}


def run(context, pool, candidate, opponents, table, source_ids, args):
    out = Path(args.out)
    refuse_repository(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("preview output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for opponent_name, opponent in opponents.items():
        budget = args.games if opponent_name == "R" else args.panel_games
        rows = book_ab.paired_rows(len(pool.ids), budget, arena.ARENA_SEED)
        raw = RawPreview(candidate)
        baseline = evaluate.play_suite(context, pool, rows, raw, opponent, args.workers, arena.ARENA_SEED, args.max_steps)
        arena._write_games(str(out / f"raw-vs-{opponent_name}.csv"), baseline)
        results[f"raw-vs-{opponent_name}"] = book_ab._arm(baseline, args.resamples)
        foe_ids = np.where(rows["learner_seat"] == 0, rows["side1"], rows["side0"])
        excluded = [source_ids.get(pool.ids[int(i)]) for i in foe_ids]
        by_mode, by_decisions = {}, {}
        for mode in ("value", "turn1"):
            for agent in args.agents:
                name = f"{agent}-{mode}-vs-{opponent_name}"
                with honest.Honest(context, candidate.model, candidate.params, candidate.encoder,
                                  candidate.ext_supported, k=8, m=8, s=args.worlds, rule=arena.AGENTS[agent],
                                  capacity=args.capacity, workers=args.workers, lam=.5, table=table,
                                  exclude_teams=excluded, preview_mode=mode, preview_only=True,
                                  preview_steps=args.rollout_steps) as search:
                    searched = arena.SearchPlayer(search, name, arena.ARENA_SEED)
                    player = PreviewPlayer(candidate, searched)
                    records = evaluate.play_suite(context, pool, rows, player, opponent, args.workers,
                                                  arena.ARENA_SEED, args.max_steps)
                decisions = [r for e in sorted(searched.records) for r in searched.records[e]]
                arena._write_games(str(out / f"{name}.csv"), records)
                with (out / f"{name}-decisions.jsonl").open("w", encoding="utf-8") as file:
                    for record in decisions:
                        file.write(json.dumps(arena._finite(record), allow_nan=False) + "\n")
                results[name] = summary(records, baseline, decisions, raw.preview, args.resamples)
                by_mode[(agent, mode)] = records
                by_decisions[(agent, mode)] = decisions
        for agent in args.agents:
            left, right = (arena.scores(by_mode[(agent, mode)]).reshape(-1, 2).mean(axis=1) for mode in ("value", "turn1"))
            results[f"{agent}-turn1-minus-value-vs-{opponent_name}"] = {
                "score": float((right - left).mean()), "score_95": list(arena.bootstrap_paired(right, left, args.resamples)),
                "both_searched": both_searched_difference(by_mode[(agent, "value")], by_mode[(agent, "turn1")],
                    by_decisions[(agent, "value")], by_decisions[(agent, "turn1")], args.resamples)}
        # Keep completed opponent arms available if a later arm fails.
        (out / "results.json").write_text(json.dumps(arena._finite(results), indent=1, allow_nan=False), encoding="utf-8")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--teams-root", help="explicit saved team registry; all checkpoint hashes must still match")
    parser.add_argument("--belief-root", help="explicit stated-spread registry for honest worlds")
    parser.add_argument("--panel-run-dir")
    parser.add_argument("--panel", default=",".join(book_ab.PANEL))
    parser.add_argument("--out", required=True)
    parser.add_argument("--games", type=int, default=2048)
    parser.add_argument("--panel-games", type=int, default=1024)
    parser.add_argument("--agents", default="N,E,X")
    parser.add_argument("--worlds", type=int, default=16)
    parser.add_argument("--capacity", type=int, default=1024)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rollout-steps", type=int, default=16)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--resamples", type=int, default=2000)
    args = parser.parse_args(argv)
    args.agents = arena._list(args.agents, "agents", arena.AGENTS)
    if args.games < 2 or args.games % 2 or args.panel_games < 2 or args.panel_games % 2 or \
            min(args.worlds, args.capacity, args.workers, args.rollout_steps, args.max_steps, args.resamples) < 1:
        parser.error("positive capacities and even game budgets required")
    panel_names = args.panel.split(",")
    if len(panel_names) != 3:
        parser.error("panel must name BC,3600,11000")
    try:
        paths = [arena._checkpoint_path(args.run_dir, args.checkpoint)] + book_ab.panel_paths(panel_names, args.panel_run_dir)
    except ValueError as error:
        parser.error(str(error))
    refuse_repository(args.out)
    from duoforge_learn import policy
    import jax
    arena.require_deterministic_gpu(jax)
    models, players, fingerprints, configs = {}, [], {}, []
    for name, path in zip(("R", "BC", "3600", "11000"), paths):
        params, config = checkpoint.load_current(path)
        configs.append(config)
        model_config = checkpoint.model_config(config, params)
        key = json.dumps(model_config, sort_keys=True)
        if key not in models:
            models[key] = policy.make(model_config)
        players.append(evaluate.Player(models[key], params, checkpoint.encoder_of(config), name, checkpoint.ext_supported_of(config)))
        fingerprints[name] = arena._sha256(path)
    pool, kind = ladder._pool_of(args.run_dir, args.teams_root)
    with duoforge.Context(data_kind=kind) as context:
        for config in configs:
            if config.get("format") == 2:
                checkpoint.check_ids(config, context)
        # An explicit --belief-root keeps its whole stated registry; the default is the pinned belief.
        table, source_ids, belief_info = honest.spread_table(
            context, args.belief_root, sources=None if args.belief_root else honest.SPREAD_SOURCES)
        results = run(context, pool, players[0], dict(zip(("R", "BC", "3600", "11000"), players)), table, source_ids, args)
    conditions = {"search": "honest", "preview_only": True, "k": 8, "m": 8, "worlds": args.worlds,
                  "lam": .5, "capacity": args.capacity, "workers": args.workers,
                  "rollout_steps_limit": args.rollout_steps, "games_vs_raw": args.games, "games_vs_panel": args.panel_games,
                  "max_steps": args.max_steps, "resamples": args.resamples, "bootstrap_unit": "paired seat orders",
                  "arena_seed": arena.ARENA_SEED, "search_seed": honest.lookahead.SEARCH_SEED,
                  "checkpoint_sha256": fingerprints, "belief": belief_info, "library": duoforge.version(),
                  "backend": jax.default_backend(), "jax": jax.__version__, "commit": arena._commit()}
    Path(args.out, "summary.json").write_text(json.dumps(arena._finite({"conditions": conditions, "configs": results}),
        indent=1, allow_nan=False), encoding="utf-8")
    print("Private preview measurement completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
