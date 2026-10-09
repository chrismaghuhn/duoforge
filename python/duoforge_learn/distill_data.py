"""The teacher shards of stage 3 P1 as training arrays (decision 0024; Learner v2 plan
2026-10-08-stage3-p1-learner, task 2).

load reads every shard of a directory with M12's expert_data.read_shard (which checks the manifest, the rows and
the ticks within a shard) and assembles one trajectory per game: the learner's rows of every lockstep step,
logical_tick 0..T-1 without a gap across shards, done at most on the last row. Its value targets are
returns.gae's, unchanged (gamma 0.99, lambda 0.95): a waiting row takes its seat's next decision's return, and a
truncated episode (done False on its last row) bootstraps from that row's bootstrap.

Each row then falls in at most one policy stratum:
- has_target: a TARGET row (its sparse teacher policy, K <= 8 ids into the 1024 joint actions);
- policy_row: an acting row without a target with at least 2 legal actions (UNSELECTED, CAP_RAW, PUBLIC_REFUSAL,
  WORK_EXHAUSTED, and team preview), for the KL to the frozen reference;
and every row with value_mask is a value row (waiting and FORCED rows are value rows only). held_out is the
manifest's whole-game split (is_held_out).

Shards are read in a process pool (load's workers, default os.cpu_count()): each worker validates its shard with
read_shard and returns plain arrays of the columns load needs (ExpertRow's frozen mappings do not pickle); the
results are consumed in shard-name order, so the data is byte-identical to a sequential load.
"""
import dataclasses
import os
import sys
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from duoforge import _layout

from .returns import gae

K = 8
TEAM_ACTIONS = 360
GAMMA, LAMBDA = 0.99, 0.95  # returns.gae's, unchanged (spec section 3)


@dataclasses.dataclass(frozen=True)
class DistillData:
    """One row per learner row of the shards, in (game, tick) order."""
    obs: np.ndarray          # (N, obs_width) float32
    slots: np.ndarray        # (N, 2, 32, slot_width) float32
    mask: np.ndarray         # (N, 32, 32) bool, the pair mask (all false on team-preview rows)
    team_mask: np.ndarray    # (N, 360) bool, the preview mask (all false on pair rows)
    is_team: np.ndarray      # (N,) bool
    target_ids: np.ndarray   # (N, 8) int64, -1 padded
    target_probs: np.ndarray  # (N, 8) float32, 0 padded
    has_target: np.ndarray   # (N,) bool
    policy_row: np.ndarray   # (N,) bool
    value_row: np.ndarray    # (N,) bool
    value_target: np.ndarray  # (N,) float32
    game_id: np.ndarray      # (N,) int64
    held_out: np.ndarray     # (N,) bool


def _plain(value):
    """A manifest field as plain picklable data (expert_data freezes mappings into MappingProxyType)."""
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _manifest_fields(manifest):
    return {f.name: _plain(getattr(manifest, f.name)) for f in dataclasses.fields(manifest)}


def _shard_columns(path, fields):
    """One shard's rows (read_shard validates them against the manifest of fields) as plain arrays, in file
    order: the columns load assembles. Runs in a pool worker."""
    from duoforge_search import expert_data as ed
    rows = ed.read_shard(Path(path), ed.DataManifest(**fields))
    n, slots_n = len(rows), _layout.MAX_SLOT_OPTIONS
    out = {
        "game_id": np.array([r.key.game_id for r in rows], np.int64),
        "seat": np.array([r.key.seat for r in rows], np.int64),
        "logical_tick": np.array([r.logical_tick for r in rows], np.int64),
        "acting": np.array([r.acting for r in rows], bool),
        "done": np.array([r.done for r in rows], bool),
        "reward": np.array([r.reward for r in rows], np.float64),
        "collector_value": np.array([r.collector_value for r in rows], np.float64),
        "bootstrap": np.array([r.bootstrap for r in rows], np.float64),
        "obs": np.stack([r.obs for r in rows]) if n else np.zeros((0, fields["obs_width"]), np.float32),
        "slots": (np.stack([r.slots for r in rows]) if n
                  else np.zeros((0, 2, slots_n, fields["slot_width"]), np.float32)),
        "mask": np.zeros((n, slots_n, slots_n), bool),
        "team_mask": np.zeros((n, TEAM_ACTIONS), bool),
        "is_team": np.zeros(n, bool),
        "target_ids": np.full((n, K), -1, np.int64),
        "target_probs": np.zeros((n, K), np.float32),
        "has_target": np.zeros(n, bool),
        "policy_row": np.zeros(n, bool),
        "value_row": np.zeros(n, bool),
    }
    for i, r in enumerate(rows):
        team = r.boundary == "TEAM_SELECTION"
        out["is_team"][i] = team
        (out["team_mask"] if team else out["mask"])[i] = r.legal_mask
        out["value_row"][i] = r.value_mask
        if r.status is ed.RowStatus.TARGET:
            k = len(r.sparse_policy.ids)
            out["target_ids"][i, :k] = r.sparse_policy.ids
            out["target_probs"][i, :k] = r.sparse_policy.probs
            out["has_target"][i] = True
        elif r.acting and int(np.count_nonzero(r.legal_mask)) >= 2:
            out["policy_row"][i] = True
    return out


def _shards(shard_dir, manifest, workers):
    """The columns of every shard (*.json) of shard_dir in name order, read by `workers` processes."""
    paths = sorted(Path(shard_dir).glob("*.json"))
    if not paths:
        raise ValueError(f"{shard_dir}: no shard (*.json)")
    fields = _manifest_fields(manifest)
    workers = min(int(workers), len(paths))

    def report(i, part):
        print(f"distill: loaded shard {i}/{len(paths)} ({part['game_id'].size} rows)", file=sys.stderr, flush=True)
        return part

    if workers == 1:
        return [report(i, _shard_columns(p, fields)) for i, p in enumerate(paths, start=1)]
    import concurrent.futures
    import multiprocessing
    # spawn: the parent holds JAX's threads, which a fork must not copy.
    pool = concurrent.futures.ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"))
    try:
        futures = [pool.submit(_shard_columns, str(p), fields) for p in paths]
        parts = [report(i, f.result()) for i, f in enumerate(futures, start=1)]
    except BaseException:
        pool.shutdown(wait=True, cancel_futures=True)  # a refused shard (or a signal) stops the rest at once
        raise
    pool.shutdown(wait=True)
    return parts


def _trajectories(game_id, seat, tick, done):
    """The row order of every game's trajectory (games ascending, each in logical-tick order); ValueError for a
    game of several seats, a duplicate tick, a gap, or an episode that ends before its last row."""
    order = np.lexsort((tick, game_id))
    starts = np.flatnonzero(np.r_[True, np.diff(game_id[order]) != 0])
    for idx in np.split(order, starts[1:]):
        game = int(game_id[idx[0]])
        seats = sorted(set(seat[idx].tolist()))
        if len(seats) != 1:
            raise ValueError(f"game {game}: rows of more than one learner seat {seats}")
        ticks = tick[idx]
        if np.unique(ticks).size != ticks.size:
            raise ValueError(f"game {game}: duplicate logical tick across shards")
        if not np.array_equal(ticks, np.arange(ticks.size)):
            missing = sorted(set(range(int(ticks[-1]) + 1)) - set(ticks.tolist()))
            raise ValueError(f"game {game}: incomplete trajectory, gap at logical tick {missing[0]}")
        if done[idx[:-1]].any():
            raise ValueError(f"game {game}: the episode ends before its last row")
    return order


def value_targets(game_id, seat, logical_tick, acting, reward, done, collector_value, bootstrap):
    """Per row (in the given order): returns.gae's value target of its (game, seat) trajectory, the rows taken in
    logical-tick order (gapless from 0, done at most on the last row: ValueError otherwise), as (T, 1, 2) arrays
    with the learner on its own seat, bootstrapped from the trajectory's last row's bootstrap."""
    game_id, seat, tick = (np.asarray(x, np.int64) for x in (game_id, seat, logical_tick))
    acting, done = np.asarray(acting, bool), np.asarray(done, bool)
    out = np.zeros(game_id.shape, np.float32)
    order = np.lexsort((tick, seat, game_id))  # one sort: (game, seat) groups, each in tick order
    starts = np.flatnonzero(np.r_[True, (np.diff(game_id[order]) != 0) | (np.diff(seat[order]) != 0)])
    for idx in np.split(order, starts[1:]):
        g, s = int(game_id[idx[0]]), int(seat[idx[0]])
        if not np.array_equal(tick[idx], np.arange(idx.size)):
            raise ValueError(f"game {g} seat {s}: logical ticks have a gap or repeat")
        if done[idx[:-1]].any():
            raise ValueError(f"game {g} seat {s}: the episode ends before its last row")
        t = idx.size
        values, rewards = np.zeros((t, 1, 2), np.float32), np.zeros((t, 1, 2), np.float32)
        acts = np.zeros((t, 1, 2), bool)
        values[:, 0, s], rewards[:, 0, s], acts[:, 0, s] = (np.asarray(collector_value)[idx],
                                                            np.asarray(reward)[idx], acting[idx])
        boot = np.zeros((1, 2), np.float32)
        boot[0, s] = np.asarray(bootstrap)[idx[-1]]
        out[idx] = gae(values, rewards, done[idx].reshape(t, 1), acts, boot, gamma=GAMMA, lam=LAMBDA)[2][:, 0, s]
    return out


def load(shard_dir, manifest, workers=None):
    """DistillData of every shard (*.json, read in name order) of shard_dir under manifest, the shards read by
    `workers` processes (default os.cpu_count(); 1 reads them in this process). Progress goes to stderr."""
    from duoforge_search import expert_data as ed
    workers = (os.cpu_count() or 1) if workers is None else workers
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError(f"load workers must be a positive integer (got {workers!r})")
    parts = _shards(shard_dir, manifest, workers)
    cols = {name: np.concatenate([p[name] for p in parts]) for name in parts[0]}
    del parts  # the per-shard copies
    if not cols["game_id"].size:
        raise ValueError(f"{shard_dir}: the shards hold no rows")
    order = _trajectories(cols["game_id"], cols["seat"], cols["logical_tick"], cols["done"])
    cols = {name: v[order] for name, v in cols.items()}
    games = np.unique(cols["game_id"])
    held = dict(zip(games.tolist(), (ed.is_held_out(int(g), manifest.split_seed) for g in games)))
    out = {
        "obs": cols.pop("obs").astype(np.float32, copy=False),
        "slots": cols.pop("slots").astype(np.float32, copy=False),
        "mask": cols["mask"], "team_mask": cols["team_mask"], "is_team": cols["is_team"],
        "target_ids": cols["target_ids"], "target_probs": cols["target_probs"], "has_target": cols["has_target"],
        "policy_row": cols["policy_row"], "value_row": cols["value_row"],
        "value_target": value_targets(cols["game_id"], cols["seat"], cols["logical_tick"], cols["acting"],
                                      cols["reward"], cols["done"], cols["collector_value"], cols["bootstrap"]),
        "game_id": cols["game_id"],
        "held_out": np.array([held[g] for g in cols["game_id"].tolist()], bool),
    }
    for name in ("obs", "slots", "value_target"):
        if not np.isfinite(out[name]).all():
            raise ValueError(f"nonfinite {name} in the shards of {shard_dir}")
    return DistillData(**out)


def strata(data):
    """Row indices: train_target, train_non (policy or value rows without a target), held_target, held_non."""
    non = ~data.has_target & (data.policy_row | data.value_row)
    train, held = ~data.held_out, data.held_out
    return {"train_target": np.flatnonzero(train & data.has_target), "train_non": np.flatnonzero(train & non),
            "held_target": np.flatnonzero(held & data.has_target), "held_non": np.flatnonzero(held & non)}
