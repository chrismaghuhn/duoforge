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
"""
import dataclasses
from pathlib import Path

import numpy as np

from duoforge import _layout

from .returns import gae

K = 8
TEAM_ACTIONS = 360


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


def _rows(shard_dir, manifest):
    from duoforge_search import expert_data as ed
    paths = sorted(Path(shard_dir).glob("*.json"))
    if not paths:
        raise ValueError(f"{shard_dir}: no shard (*.json)")
    games = {}
    for path in paths:
        for row in ed.read_shard(path, manifest):
            games.setdefault(row.key.game_id, []).append(row)
    return games


def _trajectory(game, rows):
    seats = {r.key.seat for r in rows}
    if len(seats) != 1:
        raise ValueError(f"game {game}: rows of more than one learner seat {sorted(seats)}")
    rows = sorted(rows, key=lambda r: r.logical_tick)
    ticks = [r.logical_tick for r in rows]
    if len(set(ticks)) != len(ticks):
        raise ValueError(f"game {game}: duplicate logical tick across shards")
    if ticks != list(range(len(ticks))):
        missing = sorted(set(range(ticks[-1] + 1)) - set(ticks))
        raise ValueError(f"game {game}: incomplete trajectory, gap at logical tick {missing[0]}")
    if any(r.done for r in rows[:-1]):
        raise ValueError(f"game {game}: the episode ends before its last row")
    return rows


def _targets(rows):
    """returns.gae over one trajectory (T, 1, 2), the learner on its own seat."""
    t, seat = len(rows), rows[0].key.seat
    values = np.zeros((t, 1, 2), np.float32)
    rewards = np.zeros((t, 1, 2), np.float32)
    acting = np.zeros((t, 1, 2), bool)
    done = np.zeros((t, 1), bool)
    for i, r in enumerate(rows):
        values[i, 0, seat], rewards[i, 0, seat], acting[i, 0, seat], done[i, 0] = (r.collector_value, r.reward,
                                                                                  r.acting, r.done)
    bootstrap = np.zeros((1, 2), np.float32)
    bootstrap[0, seat] = rows[-1].bootstrap
    return gae(values, rewards, done, acting, bootstrap)[2][:, 0, seat]


def load(shard_dir, manifest):
    """DistillData of every shard (*.json, read in name order) of shard_dir under manifest."""
    from duoforge_search import expert_data as ed
    games = _rows(shard_dir, manifest)
    order, targets = [], []
    for game in sorted(games):
        rows = _trajectory(game, games[game])
        order.extend(rows)
        targets.append(_targets(rows))
    n, slots_n = len(order), _layout.MAX_SLOT_OPTIONS
    out = {
        "obs": np.stack([r.obs for r in order]).astype(np.float32),
        "slots": np.stack([r.slots for r in order]).astype(np.float32),
        "mask": np.zeros((n, slots_n, slots_n), bool),
        "team_mask": np.zeros((n, TEAM_ACTIONS), bool),
        "is_team": np.zeros(n, bool),
        "target_ids": np.full((n, K), -1, np.int64),
        "target_probs": np.zeros((n, K), np.float32),
        "has_target": np.zeros(n, bool),
        "policy_row": np.zeros(n, bool),
        "value_row": np.zeros(n, bool),
        "value_target": np.concatenate(targets).astype(np.float32),
        "game_id": np.array([r.key.game_id for r in order], np.int64),
        "held_out": np.array([ed.is_held_out(r.key.game_id, manifest.split_seed) for r in order], bool),
    }
    for i, r in enumerate(order):
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
