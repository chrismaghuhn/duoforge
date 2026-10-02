"""Self-play PPO training (decision 0014).

    python -m duoforge_learn.train --envs 256 --workers 16 --minutes 60 --out runs/trial

Collects --rollout batch steps of self-play, updates the policy with PPO,
logs one JSON line per update to <out>/log.jsonl and evaluates the greedy
policy against the random and the scripted baselines and against the
previous evaluation's parameters (vs_previous above 0.5: still improving)
every --eval-every updates, saving the parameters with the configuration
(which names the encoder version, "encoder") to <out>/params-<update>.npz.
"""
import argparse
import json
import os
import sys
import time

import jax
import numpy as np

from duoforge import features

from . import evaluate, model, ppo
from .returns import gae
from .selfplay import TEAM_ACTIONS, SelfPlay


def _act():
    return jax.jit(model.act, static_argnames=("greedy",))


def collect(env, params, act, key, steps):
    """One rollout: arrays over (T, E, 2) and the bootstrap values."""
    e = env.batch.envs
    keep = {k: [] for k in ("obs", "slots", "mask", "is_team", "acting", "actions", "logp", "values", "rewards",
                            "done")}
    episodes = 0
    for _ in range(steps):
        o = env.observe()
        key, sub = jax.random.split(key)
        actions, logp, values = act(params, sub, o.obs.reshape(2 * e, -1), o.slots.reshape((2 * e,) + o.slots.shape[2:]),
                                    o.mask.reshape((2 * e,) + o.mask.shape[2:]), o.is_team.reshape(-1))
        actions = np.asarray(actions).reshape(e, 2)
        rewards, done = env.step(actions)
        episodes += int(done.sum())
        for name, value in (("obs", o.obs), ("slots", o.slots), ("mask", o.mask), ("is_team", o.is_team),
                            ("acting", o.acting), ("actions", actions), ("logp", np.asarray(logp).reshape(e, 2)),
                            ("values", np.asarray(values).reshape(e, 2)), ("rewards", rewards), ("done", done)):
            keep[name].append(value)
    o = env.observe()
    key, sub = jax.random.split(key)
    _, _, bootstrap = act(params, sub, o.obs.reshape(2 * e, -1), o.slots.reshape((2 * e,) + o.slots.shape[2:]),
                          o.mask.reshape((2 * e,) + o.mask.shape[2:]), o.is_team.reshape(-1))
    rollout = {k: np.stack(v) for k, v in keep.items()}
    return rollout, np.asarray(bootstrap).reshape(e, 2), episodes, key


def samples_of(rollout, advantages, value_targets):
    """One row per seat and step: the policy learns from the acting rows,
    the value from all of them."""
    return {
        "obs": rollout["obs"].reshape((-1,) + rollout["obs"].shape[3:]),
        "slots": rollout["slots"].reshape((-1,) + rollout["slots"].shape[3:]),
        "mask": rollout["mask"].reshape((-1,) + rollout["mask"].shape[3:]),
        "is_team": rollout["is_team"].reshape(-1),
        "acting": rollout["acting"].reshape(-1).astype(np.float32),
        "actions": rollout["actions"].reshape(-1).astype(np.int32),
        "logp": rollout["logp"].reshape(-1).astype(np.float32),
        "advantages": advantages.reshape(-1),
        "value_targets": value_targets.reshape(-1),
    }


def save(path, params, config):
    flat, _ = jax.tree_util.tree_flatten_with_path(params)
    arrays = {jax.tree_util.keystr(k): np.asarray(v) for k, v in flat}
    np.savez(path, config=json.dumps(config), **arrays)


def _arguments(argv):
    p = argparse.ArgumentParser(prog="python -m duoforge_learn.train", description="Self-play PPO training.")
    p.add_argument("--envs", type=int, default=256)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--rollout", type=int, default=32, help="batch steps per update")
    p.add_argument("--minutes", type=float, default=60.0, help="stop after this time (0: --updates only)")
    p.add_argument("--updates", type=int, default=0, help="stop after this many updates (0: --minutes only)")
    p.add_argument("--epochs", type=int, default=4)
    p.add_argument("--minibatch", type=int, default=4096)
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--entropy", type=float, default=0.01)
    p.add_argument("--eval-every", type=int, default=25)
    p.add_argument("--eval-envs", type=int, default=64)
    p.add_argument("--seed", type=lambda s: int(s, 0), default=0x2026100200000021)
    p.add_argument("--max-steps", type=int, default=500, help="steps before a self-play episode is cut off as a tie")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    if args.minutes <= 0 and args.updates <= 0:
        p.error("give --minutes or --updates")
    if args.eval_envs % 8 != 0:
        p.error("--eval-envs must be a multiple of 8 (both seats of all four pairings)")
    return args


def main(argv=None):
    args = _arguments(sys.argv[1:] if argv is None else list(argv))
    if os.path.isdir(args.out) and os.listdir(args.out):
        raise SystemExit(f"{args.out} is not empty: a run writes into a fresh directory")
    os.makedirs(args.out, exist_ok=True)
    config = vars(args) | {"devices": [str(d) for d in jax.devices()], "encoder": features.ENCODER}
    print(json.dumps(config), flush=True)
    env = SelfPlay(args.envs, args.workers, args.seed, max_steps=args.max_steps)
    # All 64 bits of the seed: the low half makes the key, the high half is folded in.
    key = jax.random.fold_in(jax.random.PRNGKey(args.seed & 0xFFFFFFFF), args.seed >> 32)
    key, sub = jax.random.split(key)
    params = model.init(sub, features.OBS_SIZE, features.SLOT_FEATURES, TEAM_ACTIONS)
    tx = ppo.optimizer(args.learning_rate)
    opt_state = tx.init(params)
    act = _act()
    rng = np.random.default_rng(args.seed)
    start = time.perf_counter()
    decisions = episodes = 0
    update = 0
    previous = params
    with open(os.path.join(args.out, "log.jsonl"), "a", encoding="utf-8") as log:
        while True:
            update += 1
            t0 = time.perf_counter()
            rollout, bootstrap, ended, key = collect(env, params, act, key, args.rollout)
            advantages, _, value_targets = gae(rollout["values"], rollout["rewards"], rollout["done"],
                                               rollout["acting"], bootstrap)
            samples = samples_of(rollout, advantages, value_targets)
            acted = int(rollout["acting"].sum())
            t1 = time.perf_counter()
            params, opt_state, stats = ppo.update(params, opt_state, tx, samples, rng, epochs=args.epochs,
                                                  minibatch=args.minibatch, entropy_coef=args.entropy)
            t2 = time.perf_counter()
            decisions += acted
            episodes += ended
            record = {"update": update, "seconds": round(t2 - start, 1), "decisions": decisions,
                      "episodes": episodes, "collect_s": round(t1 - t0, 3), "update_s": round(t2 - t1, 3),
                      "decisions_per_s": round(acted / (t2 - t0))}
            record |= {k: round(float(v), 5) for k, v in stats.items()}
            elapsed_min = (t2 - start) / 60
            last = (args.updates and update >= args.updates) or (args.minutes and elapsed_min >= args.minutes)
            if update % args.eval_every == 0 or last:
                save(os.path.join(args.out, f"params-{update}.npz"), params, config)
                for name, opponent in (("random", "random"), ("scripted", "scripted"), ("previous", previous)):
                    result = evaluate.win_rate(params, act, opponent, envs=args.eval_envs, workers=args.workers,
                                               encoder=features.ENCODER, opponent_encoder=features.ENCODER)
                    record[f"vs_{name}"] = round(result["win_rate"], 4)
                    if result["unfinished"]:
                        record[f"unfinished_vs_{name}"] = result["unfinished"]
                previous = params
            log.write(json.dumps(record) + "\n")
            log.flush()
            print(json.dumps(record), flush=True)
            if last:
                break
    env.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
