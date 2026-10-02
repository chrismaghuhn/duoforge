"""Advantages and value targets over each seat's own decisions (decision
0014 section 5), in NumPy.

A rollout holds T batch steps of E environments and two seats. A seat that
is not requested at a step does not act there; the reward of an episode
(+1, -1, 0 at its end) goes to the seat's last decision of that episode;
discounting counts the seat's own decisions; the values of the states
after the rollout bootstrap the unfinished ones.
"""
import numpy as np


def gae(values, rewards, done, acting, bootstrap, gamma=0.99, lam=0.95):
    """(advantages, returns, value_targets), each (T, E, 2).

    values (T, E, 2): each seat's value of the state at step t; rewards
    (T, E, 2) and done (T, E): the episode that ended after step t; acting
    (T, E, 2): the seat decided at step t; bootstrap (E, 2): the values
    after the last step. Advantages and returns are 0 where a seat did not
    act. value_targets trains the value of every row: the return where the
    seat acted; where it waited, what its next decision returns, or its
    reward if the episode ends first, or the bootstrap after the rollout."""
    t_steps = values.shape[0]
    advantages = np.zeros(values.shape, dtype=np.float64)
    targets = np.zeros(values.shape, dtype=np.float64)
    next_value = bootstrap.astype(np.float64)
    carry = np.zeros_like(next_value)
    pending = np.zeros_like(next_value)
    target = bootstrap.astype(np.float64)
    for t in range(t_steps - 1, -1, -1):
        ended = done[t][:, None]
        next_value = np.where(ended, 0.0, next_value)
        carry = np.where(ended, 0.0, carry)
        pending = np.where(ended, rewards[t], pending)
        target = np.where(ended, rewards[t], target)
        step = pending + gamma * next_value - values[t] + gamma * lam * carry
        advantages[t] = np.where(acting[t], step, 0.0)
        own = step + values[t]
        targets[t] = np.where(acting[t], own, target)
        carry = np.where(acting[t], step, carry)
        next_value = np.where(acting[t], values[t], next_value)
        pending = np.where(acting[t], 0.0, pending)
        target = np.where(acting[t], own, target)
    returns = np.where(acting, advantages + values, 0.0)
    return advantages.astype(np.float32), returns.astype(np.float32), targets.astype(np.float32)


def samples_of(rollout, advantages, value_targets, learner_rows=None):
    """One row per seat and step: the policy learns from the acting rows,
    the value from all of them. learner_rows (E, 2) bool keeps only the
    learner's rows (a league opponent's rows are not training data)."""
    keep = (np.ones(rollout["acting"].shape, dtype=bool) if learner_rows is None
            else np.broadcast_to(learner_rows, rollout["acting"].shape)).reshape(-1)

    def rows(a, tail=False):
        flat = a.reshape((-1,) + a.shape[3:]) if tail else a.reshape(-1)
        return flat[keep]

    return {
        "obs": rows(rollout["obs"], True),
        "slots": rows(rollout["slots"], True),
        "mask": rows(rollout["mask"], True),
        "is_team": rows(rollout["is_team"]),
        "acting": rows(rollout["acting"]).astype(np.float32),
        "actions": rows(rollout["actions"]).astype(np.int32),
        "logp": rows(rollout["logp"]).astype(np.float32),
        "advantages": rows(advantages),
        "value_targets": rows(value_targets),
    }
