"""Self-play PPO training (decisions 0014, 0017).

    python -m duoforge_learn.train --envs 256 --workers 16 --minutes 60 --out runs/trial

Collects --rollout batch steps, updates the policy with PPO and logs one
JSON line per update to <out>/log.jsonl. The first --self-play-share of the
environments play self-play; the others play the learner against frozen
snapshots of itself in --league-slots slots (league.py), which reload a
snapshot drawn from the run's pool every --slot-refresh updates, at an
episode boundary. Snapshots go to <out>/params-<update>.npz (checkpoint
format 2) every --snapshot-every updates and at each evaluation; every
--eval-every updates the greedy policy plays the random and the scripted
baselines and the previous evaluation's parameters (vs_previous above 0.5:
still improving).
"""
import argparse
import json
import os
import sys
import time

import jax
import numpy as np

from duoforge import features

from . import checkpoint, evaluate, league, pairing, policy, ppo
from .returns import gae, samples_of
from .selfplay import SelfPlay

_DIMS = ("embed", "member", "position", "hidden", "layers", "option")


def model_config(args):
    """The model configuration of the command line: v1 (with --hidden) or a
    v2 preset with its dimension overrides."""
    dims = {k: getattr(args, k) for k in _DIMS if getattr(args, k) is not None}
    if args.model == "v1":
        extra = sorted(set(dims) - {"hidden"})
        if extra:
            raise SystemExit(f"model v1 takes only --hidden, not {extra}")
        return {**policy.V1_DEFAULT, **dims}
    return policy.v2_config(args.preset, **dims)


def _rows(o, e):
    return (o.obs.reshape(2 * e, -1), o.slots.reshape((2 * e,) + o.slots.shape[2:]),
            o.mask.reshape((2 * e,) + o.mask.shape[2:]), o.is_team.reshape(-1))


def collect(env, params, act, key, steps, state=None, opponents=None):
    """One rollout: arrays over (T, E, 2) and the bootstrap values. With a
    league (state, opponents), the opponent seat of every league
    environment plays its slot's snapshot."""
    e = env.batch.envs
    keep = {k: [] for k in ("obs", "slots", "mask", "is_team", "acting", "actions", "logp", "values", "rewards",
                            "done")}
    episodes = 0
    if state is not None and state.has_league:
        league_envs = np.flatnonzero(~state.self_play)
        opponent_rows = 2 * league_envs + (1 - state.learner_seat[league_envs])
    for _ in range(steps):
        o = env.observe()
        key, sub, other = jax.random.split(key, 3)
        obs, slots, mask, is_team = _rows(o, e)
        actions, logp, values = act(params, sub, obs, slots, mask, is_team)
        actions = np.array(actions).reshape(e, 2)
        if state is not None and state.has_league:
            r = opponent_rows
            chosen = opponents.act(other, obs[r], slots[r], mask[r], is_team[r], state.slot_of[league_envs])
            actions.reshape(-1)[r] = chosen
        rewards, done = env.step(actions)
        episodes += int(done.sum())
        for name, value in (("obs", o.obs), ("slots", o.slots), ("mask", o.mask), ("is_team", o.is_team),
                            ("acting", o.acting), ("actions", actions), ("logp", np.asarray(logp).reshape(e, 2)),
                            ("values", np.asarray(values).reshape(e, 2)), ("rewards", rewards), ("done", done)):
            keep[name].append(value)
    o = env.observe()
    key, sub = jax.random.split(key)
    _, _, bootstrap = act(params, sub, *_rows(o, e))
    rollout = {k: np.stack(v) for k, v in keep.items()}
    return rollout, np.asarray(bootstrap).reshape(e, 2), episodes, key


def save(path, params, config):
    """A format-1 checkpoint (decision 0014): params with a free config, as
    the runs of 2026-10-02 wrote them; new runs write format 2
    (checkpoint.save)."""
    flat, _ = jax.tree_util.tree_flatten_with_path(params)
    arrays = {jax.tree_util.keystr(k): np.asarray(v) for k, v in flat}
    np.savez(path, config=json.dumps(config), **arrays)


def snapshot_config(train_config, model_cfg, context, update, decisions):
    """The format-2 config of a snapshot of this run."""
    return {"model": model_cfg, "encoder": features.ENCODER, "features": list(features.FEATURE_NAMES),
            "slot_features": list(features.SLOT_FEATURE_NAMES),
            "data": {"kind": "closure", "fingerprint": context.fingerprint().hex()},
            "teams": {"ids": ["A", "B"], "sha256": ["", ""], "weights": [1.0, 1.0]},
            "update": update, "decisions": decisions, "train": train_config}


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
    p.add_argument("--model", choices=("v1", "v2"), default="v1")
    p.add_argument("--preset", choices=("S", "M", "L"), default="S", help="model v2 size")
    for dim in _DIMS:
        p.add_argument(f"--{dim}", type=int, default=None, help="overrides the preset (v1: --hidden only)")
    p.add_argument("--self-play-share", type=float, default=0.5, help="environments with the learner on both seats")
    p.add_argument("--league-slots", type=int, default=4, help="frozen snapshots playing the league environments")
    p.add_argument("--snapshot-every", type=int, default=200, help="updates between snapshots of the learner")
    p.add_argument("--slot-refresh", type=int, default=50, help="updates between league slot reloads")
    args = p.parse_args(argv)
    if args.minutes <= 0 and args.updates <= 0:
        p.error("give --minutes or --updates")
    if args.eval_envs % 8 != 0:
        p.error("--eval-envs must be a multiple of 8 (both seats of all four pairings)")
    return args


class _Pool:
    """The run's snapshots: update numbers whose params-<update>.npz exist."""

    def __init__(self, out):
        self.out, self.updates = out, []

    def save(self, update, params, config):
        checkpoint.save(os.path.join(self.out, f"params-{update}.npz"), params, config)
        if update not in self.updates:
            self.updates.append(update)

    def draw(self, seed, update):
        u = pairing.draw(seed, pairing.LEAGUE_SNAPSHOT, np.array([update]), np.array([0]))
        chosen = self.updates[int(pairing.pick(u, np.ones(len(self.updates)))[0])]
        return chosen, checkpoint.load(os.path.join(self.out, f"params-{chosen}.npz"))[0]


def main(argv=None):
    args = _arguments(sys.argv[1:] if argv is None else list(argv))
    if os.path.isdir(args.out) and os.listdir(args.out):
        raise SystemExit(f"{args.out} is not empty: a run writes into a fresh directory")
    os.makedirs(args.out, exist_ok=True)
    config = vars(args) | {"devices": [str(d) for d in jax.devices()], "encoder": features.ENCODER}
    print(json.dumps(config), flush=True)
    state = league.LeagueState(args.envs, args.self_play_share, args.league_slots, args.slot_refresh, args.seed)
    env = SelfPlay(args.envs, args.workers, args.seed, max_steps=args.max_steps, on_start=state.start,
                   on_end=lambda envs, rewards: state.end(envs, league.learner_results(state, envs, rewards)))
    learner_rows = state.learner_rows()
    # All 64 bits of the seed: the low half makes the key, the high half is folded in.
    key = jax.random.fold_in(jax.random.PRNGKey(args.seed & 0xFFFFFFFF), args.seed >> 32)
    key, sub = jax.random.split(key)
    model_cfg = model_config(args)
    net = policy.make(model_cfg)
    config["model"] = model_cfg
    params = net.init(sub)
    tx = ppo.optimizer(args.learning_rate)
    opt_state = tx.init(params)
    act = net.act
    pool = _Pool(args.out)
    pool.save(0, params, snapshot_config(config, model_cfg, env.context, 0, 0))
    opponents = None
    if state.has_league:
        opponents = league.Opponents(net, state.slots)
        for slot in range(state.slots):
            opponents.set(slot, params)
            state.load(slot, "0")
    rng = np.random.default_rng(args.seed)
    start = time.perf_counter()
    decisions = episodes = 0
    update = 0
    previous = params
    with open(os.path.join(args.out, "log.jsonl"), "a", encoding="utf-8") as log:
        while True:
            update += 1
            t0 = time.perf_counter()
            rollout, bootstrap, ended, key = collect(env, params, act, key, args.rollout, state, opponents)
            advantages, _, value_targets = gae(rollout["values"], rollout["rewards"], rollout["done"],
                                               rollout["acting"], bootstrap)
            samples = samples_of(rollout, advantages, value_targets, learner_rows)
            acted = int(samples["acting"].sum())
            t1 = time.perf_counter()
            params, opt_state, stats = ppo.update(params, opt_state, tx, samples, rng, net.evaluate,
                                                  epochs=args.epochs, minibatch=args.minibatch,
                                                  entropy_coef=args.entropy)
            t2 = time.perf_counter()
            decisions += acted
            episodes += ended
            record = {"update": update, "seconds": round(t2 - start, 1), "decisions": decisions,
                      "episodes": episodes, "collect_s": round(t1 - t0, 3), "update_s": round(t2 - t1, 3),
                      "decisions_per_s": round(acted / (t2 - t0)), "policy_rows": acted,
                      "acted_rows": int(rollout["acting"].sum())}
            record |= {k: round(float(v), 5) for k, v in stats.items()}
            elapsed_min = (t2 - start) / 60
            last = (args.updates and update >= args.updates) or (args.minutes and elapsed_min >= args.minutes)
            evaluating = update % args.eval_every == 0 or last
            if update % args.snapshot_every == 0 or evaluating:
                pool.save(update, params, snapshot_config(config, model_cfg, env.context, update, decisions))
            if state.has_league:
                state.tick(update)
                slot = state.ready()
                if slot >= 0:
                    chosen, snapshot = pool.draw(args.seed, update)
                    opponents.set(slot, snapshot)
                    state.load(slot, str(chosen))
                    record["league_load"] = {"slot": slot, "snapshot": chosen}
            if evaluating:
                for name, opponent in (("random", "random"), ("scripted", "scripted"), ("previous", previous)):
                    result = evaluate.win_rate(params, act, opponent, envs=args.eval_envs, workers=args.workers,
                                               encoder=features.ENCODER, opponent_encoder=features.ENCODER)
                    record[f"vs_{name}"] = round(result["win_rate"], 4)
                    if result["unfinished"]:
                        record[f"unfinished_vs_{name}"] = result["unfinished"]
                if state.has_league:
                    record["league"] = {k: list(v) for k, v in state.stats.items()}
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
