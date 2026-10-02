"""A round robin of checkpoints, rated by Bradley-Terry (decisions 0014, 0017).

    python -m duoforge_learn.ladder RUN_DIR --pick 12 --envs 128 --workers 8

The baselines are beaten within a minute and the comparison with the
previous checkpoint is noisy, so progress over a long run is measured here:
the greedy policies of chosen checkpoints (and the untrained network of the
run's seed) play every pair on fixed seeds, both seats of all four pairings
(evaluate.win_rate), and a Bradley-Terry fit turns the scores into Elo
ratings relative to the first player. The table goes to RUN_DIR/ladder.json.
Each checkpoint plays on the inputs of the encoder version it was trained
with (checkpoint.encoder_of: 1 for a config that names none).
"""
import argparse
import glob
import json
import math
import os
import re
import sys

import numpy as np

from . import evaluate


def ratings(score, games, prior=0.5, iterations=2000):
    """Elo ratings (relative to player 0) of a Bradley-Terry fit: score[i, j]
    is what i scored against j in games[i, j] games. Every pair also gets a
    virtual tie of weight `prior`, so a sweep does not give infinity."""
    n = score.shape[0]
    s = score + prior * (1 - np.eye(n))
    g = games + 2 * prior * (1 - np.eye(n))
    wins = s.sum(axis=1)
    p = np.ones(n)
    for _ in range(iterations):
        denom = (g / (p[:, None] + p[None, :])).sum(axis=1)
        p = wins / denom
        p /= math.exp(np.log(p).mean())
    return 400.0 * np.log10(p / p[0])


def round_robin(players, act, envs=128, workers=8):
    """(score, games) over every pair of players [(name, params, encoder
    version)] played by act, or [(name, params, encoder version, act)] each
    played by its own act (checkpoints of different models)."""
    n = len(players)
    score = np.zeros((n, n))
    games = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            r = evaluate.win_rate(players[i][1], _act_of(players[i], act), players[j][1], envs=envs,
                                  workers=workers, encoder=players[i][2], opponent_encoder=players[j][2],
                                  opponent_act=_act_of(players[j], act))
            score[i, j] = r["win_rate"] * r["episodes"]
            score[j, i] = r["episodes"] - score[i, j]
            games[i, j] = games[j, i] = r["episodes"]
    return score, games


def _act_of(player, act):
    return player[3] if len(player) > 3 else act


def _checkpoints(run_dir):
    found = []
    for path in glob.glob(os.path.join(run_dir, "params-*.npz")):
        m = re.search(r"params-(\d+)\.npz$", path)
        if m:
            found.append((int(m.group(1)), path))
    return sorted(found)


BOOTSTRAP_SEED = 0x2026100200000170
LADDER_SEED = 0x2026100200000020


def play_round_robin(context, pool, rows, players, workers, seed=LADDER_SEED):
    """{(i, j): records of player i (learner) against player j over the suite
    rows}, for every pair i < j of players (evaluate.Player)."""
    from . import evaluate
    out = {}
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            out[(i, j)] = evaluate.play_suite(context, pool, rows, players[i], players[j], workers, seed)
    return out


def _matrices(records, n, team=None):
    """(score, games) of the pairs' records; with team, only the games in
    which the scoring player pilots that team."""
    score, games = np.zeros((n, n)), np.zeros((n, n))
    for (i, j), rec in records.items():
        mine = np.where(rec["learner_seat"] == 0, rec["side0"], rec["side1"]).astype(np.int64)
        theirs = np.where(rec["learner_seat"] == 0, rec["side1"], rec["side0"]).astype(np.int64)
        value = (rec["result"].astype(np.float64) + 1.0) / 2.0
        a = np.ones(len(rec), dtype=bool) if team is None else mine == team
        b = np.ones(len(rec), dtype=bool) if team is None else theirs == team
        score[i, j] += value[a].sum()
        games[i, j] += a.sum()
        score[j, i] += (1.0 - value[b]).sum()
        games[j, i] += b.sum()
    return score, games


def fit(records, n, team=None):
    """Elo ratings (relative to player 0) of n players from the pairs'
    records; with team, from the games in which a player pilots that team."""
    return ratings(*_matrices(records, n, team))


def bootstrap(records, n, team=None, resamples=200, seed=BOOTSTRAP_SEED):
    """(low, high): the 2.5 and 97.5 percentiles of fit over resamples of
    every pair's games (with replacement, a fixed seed)."""
    rng = np.random.default_rng(seed)
    fits = []
    for _ in range(resamples):
        drawn = {k: rec[rng.integers(0, len(rec), len(rec))] for k, rec in records.items()}
        fits.append(fit(drawn, n, team))
    fits = np.array(fits)
    return np.percentile(fits, 2.5, axis=0), np.percentile(fits, 97.5, axis=0)


def team_matrix(context, pool, rows, player, workers, seed=LADDER_SEED):
    """(N, N): the side-0 team's score in the player's greedy self-play for
    every pairing (side-0 team a, side-1 team b), over both seat
    assignments of the suite."""
    from . import evaluate
    rec = evaluate.play_suite(context, pool, rows, player, player, workers, seed)
    n = len(pool.ids)
    value = (rec["result"].astype(np.float64) + 1.0) / 2.0
    side0 = np.where(rec["learner_seat"] == 0, value, 1.0 - value)
    total, count = np.zeros((n, n)), np.zeros((n, n))
    np.add.at(total, (rec["side0"].astype(np.int64), rec["side1"].astype(np.int64)), side0)
    np.add.at(count, (rec["side0"].astype(np.int64), rec["side1"].astype(np.int64)), 1)
    return np.divide(total, count, out=np.full((n, n), np.nan), where=count > 0)


def _pool_of(run_dir):
    """(team pool, data kind) of a run, from its first checkpoint: format 2
    names its teams and data kind; format 1 (decision 0014) trained on Teams
    A and B under CLOSURE."""
    import duoforge
    from duoforge import teams

    from .checkpoint import load
    found = _checkpoints(run_dir)
    if not found:
        raise SystemExit(f"no checkpoints in {run_dir}")
    config = load(found[0][1])[1]
    from duoforge import _layout
    kinds = {"closure": "DUOFORGE_DATA_KIND_CLOSURE", "team_c": "DUOFORGE_DATA_KIND_TEAM_C",
             "pool": "DUOFORGE_DATA_KIND_POOL"}
    kind = _layout.CONSTANTS[kinds[config["data"]["kind"] if config.get("format") == 2 else "closure"]]
    saved = config["teams"] if config.get("format") == 2 else {"ids": ["A", "B"], "sha256": ["", ""],
                                                                 "weights": [1.0, 1.0]}
    if all(sha == "" for sha in saved["sha256"]) and set(saved["ids"]) <= {"A", "B"}:
        sides = duoforge.reference_setups([0])["sides"][0]
        by_id = {"A": sides[0], "B": sides[1]}
        return teams.TeamPool.from_setups(saved["ids"], np.array([by_id[t] for t in saved["ids"]]),
                                          saved["weights"]), kind
    train = config.get("train", {})
    with duoforge.Context(data_kind=kind) as ctx:
        pool = teams.load(ctx, saved["ids"], root=train.get("teams_root", "data/teams"), weights=saved["weights"])
    if list(pool.sha256) != list(saved["sha256"]):
        raise SystemExit(f"{run_dir}: a team file changed since the run (sha256 {saved['sha256']} -> {pool.sha256})")
    return pool, kind


def _markdown(table, team_ids):
    head = "| Player | Elo | 95 % | " + " | ".join(f"Elo {t}" for t in team_ids) + " |"
    rule = "|---|---|---|" + "---|" * len(team_ids)
    lines = [head, rule]
    for row in table:
        per = " | ".join(f"{e:.0f}" for e in row["elo_by_team"])
        lines.append(f"| {row['player']} | {row['elo']:.0f} | {row['elo_low']:.0f} to {row['elo_high']:.0f} | {per} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_learn.ladder",
                                description="Round robin of checkpoints over the evaluation suite.")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--pick", type=int, default=6, help="checkpoints per run, spread evenly (with the last)")
    p.add_argument("--games", type=int, default=2, help="games per pairing and seat (<= 8 teams)")
    p.add_argument("--budget", type=int, default=512, help="suite games with more than 8 teams")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--teams-from", default=None, help="the run whose teams the suite uses (default: the first)")
    p.add_argument("--no-init", action="store_true", help="leave out the untrained network")
    p.add_argument("--out", default=None, help="directory for ladder.json and ladder.md (default: the first run)")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    import jax  # the ladder plays the policies

    import duoforge
    from duoforge import features

    from . import evaluate, policy, suite
    from .checkpoint import encoder_of, load, load_current, model_config

    pool, kind = _pool_of(args.teams_from or args.run_dirs[0])
    rows = suite.make_suite(len(pool.ids), LADDER_SEED, games=args.games, budget=args.budget)
    models = {}

    def model_of(cfg):
        key = json.dumps(cfg, sort_keys=True)
        if key not in models:
            models[key] = policy.make(cfg)
        return models[key]

    players = []
    for k, run_dir in enumerate(args.run_dirs):
        found = _checkpoints(run_dir)
        if not found:
            raise SystemExit(f"no checkpoints in {run_dir}")
        chosen = sorted(dict(found[round(i * (len(found) - 1) / max(args.pick - 1, 1))]
                             for i in range(min(args.pick, len(found)))).items())
        label = os.path.basename(os.path.normpath(run_dir))
        if k == 0 and not args.no_init:
            params, config = load(chosen[0][1])
            cfg = model_config(config, params)
            seed = int(config.get("train", config)["seed"])
            key = jax.random.fold_in(jax.random.PRNGKey(seed & 0xFFFFFFFF), seed >> 32)
            key, sub = jax.random.split(key)
            players.append(evaluate.Player(model_of(cfg), model_of(cfg).init(sub), features.ENCODER, "init"))
        for u, path in chosen:
            params, config = load_current(path)
            cfg = model_config(config, params)
            players.append(evaluate.Player(model_of(cfg), params, encoder_of(config), f"{label} update {u}"))
    n = len(players)
    with duoforge.Context(data_kind=kind) as ctx:
        records = play_round_robin(ctx, pool, rows, players, args.workers)
        elo = fit(records, n)
        low, high = bootstrap(records, n)
        per_team = [fit(records, n, t) for t in range(len(pool.ids))]
        per_team_ci = [bootstrap(records, n, t) for t in range(len(pool.ids))]
        best = int(np.argmax(elo))
        matrix = team_matrix(ctx, pool, rows, players[best], args.workers)
    table = []
    for i, player in enumerate(players):
        table.append({"player": player.name, "elo": round(float(elo[i]), 1), "elo_low": round(float(low[i]), 1),
                      "elo_high": round(float(high[i]), 1),
                      "elo_by_team": [round(float(per_team[t][i]), 1) for t in range(len(pool.ids))],
                      "elo_by_team_low": [round(float(per_team_ci[t][0][i]), 1) for t in range(len(pool.ids))],
                      "elo_by_team_high": [round(float(per_team_ci[t][1][i]), 1) for t in range(len(pool.ids))]})
    for row in table:
        print(f"{row['player']:>24}  Elo {row['elo']:8.1f}  [{row['elo_low']:.0f}, {row['elo_high']:.0f}]")
    out = args.out or args.run_dirs[0]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "ladder.json"), "w", encoding="utf-8") as f:
        json.dump({"players": table, "teams": list(pool.ids), "suite": {"games": args.games, "budget": args.budget,
                   "rows": int(rows.shape[0])}, "team_matrix_player": players[best].name,
                   "team_matrix": [[None if np.isnan(x) else round(float(x), 4) for x in r] for r in matrix]},
                  f, indent=1)
    with open(os.path.join(out, "ladder.md"), "w", encoding="utf-8") as f:
        f.write(_markdown(table, list(pool.ids)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
