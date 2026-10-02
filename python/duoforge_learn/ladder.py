"""A round robin of checkpoints, rated by Bradley-Terry (decision 0014).

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
    version)]."""
    n = len(players)
    score = np.zeros((n, n))
    games = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            r = evaluate.win_rate(players[i][1], act, players[j][1], envs=envs, workers=workers,
                                  encoder=players[i][2], opponent_encoder=players[j][2])
            score[i, j] = r["win_rate"] * r["episodes"]
            score[j, i] = r["episodes"] - score[i, j]
            games[i, j] = games[j, i] = r["episodes"]
    return score, games


def _checkpoints(run_dir):
    found = []
    for path in glob.glob(os.path.join(run_dir, "params-*.npz")):
        m = re.search(r"params-(\d+)\.npz$", path)
        if m:
            found.append((int(m.group(1)), path))
    return sorted(found)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_learn.ladder", description="Round robin of checkpoints.")
    p.add_argument("run_dir")
    p.add_argument("--pick", type=int, default=10, help="checkpoints, spread evenly over the run (with the last)")
    p.add_argument("--envs", type=int, default=128)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--no-init", action="store_true", help="leave out the untrained network")
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    import jax  # the ladder plays the policies

    from . import model
    from .checkpoint import encoder_of, load
    from .selfplay import TEAM_ACTIONS
    from duoforge import features

    found = _checkpoints(args.run_dir)
    if not found:
        raise SystemExit(f"no checkpoints in {args.run_dir}")
    chosen = [found[round(k * (len(found) - 1) / max(args.pick - 1, 1))] for k in range(min(args.pick, len(found)))]
    chosen = sorted(dict(chosen).items())
    players = []
    config = load(chosen[0][1])[1]
    if not args.no_init:
        seed = int(config["seed"])
        key = jax.random.fold_in(jax.random.PRNGKey(seed & 0xFFFFFFFF), seed >> 32)
        key, sub = jax.random.split(key)
        players.append(("init", model.init(sub, features.OBS_SIZE, features.SLOT_FEATURES, TEAM_ACTIONS),
                        features.ENCODER))
    for u, path in chosen:
        params, config = load(path, obs_size=features.OBS_SIZE)
        players.append((f"update {u}", params, encoder_of(config)))
    act = jax.jit(model.act, static_argnames=("greedy",))
    score, games = round_robin(players, act, envs=args.envs, workers=args.workers)
    elo = ratings(score, games)
    table = [{"player": name, "elo": round(float(e), 1), "score": round(float(score[i].sum() / games[i].sum()), 4)}
             for i, ((name, _, _), e) in enumerate(zip(players, elo))]
    for row in table:
        print(f"{row['player']:>14}  Elo {row['elo']:8.1f}  score {row['score']:.3f}")
    with open(os.path.join(args.run_dir, "ladder.json"), "w", encoding="utf-8") as f:
        json.dump({"players": table, "envs": args.envs, "score": score.tolist(), "games": games.tolist()}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
