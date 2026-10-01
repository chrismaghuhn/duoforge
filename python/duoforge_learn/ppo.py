"""PPO for self-play over each seat's own decisions (decision 0014 section 5).

A rollout holds T batch steps of E environments and two seats. A seat that
is not requested at a step does not act there; the reward of an episode
(+1, -1, 0 at its end) goes to the seat's last decision of that episode;
the values of the states after the rollout bootstrap the unfinished ones.
"""
import functools

import jax
import jax.numpy as jnp
import numpy as np
import optax

from . import model


def gae(values, rewards, done, acting, bootstrap, gamma=0.99, lam=0.95):
    """(advantages, returns), both (T, E, 2), over every seat's own decisions.

    values (T, E, 2): the value of each seat's state at step t; rewards
    (T, E, 2) and done (T, E): the episode that ended after step t;
    acting (T, E, 2): the seat decided at step t; bootstrap (E, 2): the
    values after the last step. Entries where a seat did not act are 0."""
    t_steps = values.shape[0]
    advantages = np.zeros_like(values)
    next_value = bootstrap.astype(np.float64)
    carry = np.zeros_like(next_value)
    pending = np.zeros_like(next_value)
    for t in range(t_steps - 1, -1, -1):
        ended = done[t][:, None]
        next_value = np.where(ended, 0.0, next_value)
        carry = np.where(ended, 0.0, carry)
        pending = np.where(ended, rewards[t], pending)
        delta = pending + gamma * next_value - values[t]
        step = delta + gamma * lam * carry
        advantages[t] = np.where(acting[t], step, 0.0)
        carry = np.where(acting[t], step, carry)
        next_value = np.where(acting[t], values[t], next_value)
        pending = np.where(acting[t], 0.0, pending)
    returns = np.where(acting, advantages + values, 0.0)
    return advantages.astype(np.float32), returns.astype(np.float32)


def optimizer(learning_rate=3e-4, max_norm=0.5):
    return optax.chain(optax.clip_by_global_norm(max_norm), optax.adam(learning_rate))


def _loss(params, batch, clip, entropy_coef, value_coef):
    logp, entropy, value = model.evaluate(params, batch["obs"], batch["slots"], batch["mask"], batch["is_team"],
                                          batch["actions"])
    w = batch["weight"]
    total = jnp.maximum(w.sum(), 1.0)
    adv = batch["advantages"]
    mean = (adv * w).sum() / total
    std = jnp.sqrt((((adv - mean) ** 2) * w).sum() / total) + 1e-8
    adv = (adv - mean) / std
    ratio = jnp.exp(logp - batch["logp"])
    surrogate = jnp.minimum(ratio * adv, jnp.clip(ratio, 1.0 - clip, 1.0 + clip) * adv)
    policy_loss = -(surrogate * w).sum() / total
    value_loss = (((value - batch["returns"]) ** 2) * w).sum() / total
    entropy_mean = (entropy * w).sum() / total
    loss = policy_loss + value_coef * value_loss - entropy_coef * entropy_mean
    return loss, (policy_loss, value_loss, entropy_mean)


@functools.partial(jax.jit, static_argnames=("tx", "clip", "entropy_coef", "value_coef"))
def _update_step(params, opt_state, batch, tx, clip, entropy_coef, value_coef):
    (loss, aux), grads = jax.value_and_grad(_loss, has_aux=True)(params, batch, clip, entropy_coef, value_coef)
    updates, opt_state = tx.update(grads, opt_state, params)
    return optax.apply_updates(params, updates), opt_state, loss, aux


def update(params, opt_state, tx, samples, rng, epochs=4, minibatch=4096, clip=0.2, entropy_coef=0.01,
           value_coef=0.5):
    """PPO epochs over the samples (dict of arrays, one row per decision),
    in minibatches of a fixed size (the last one padded with weight 0, so
    jit compiles once). Returns (params, opt_state, mean losses)."""
    n = samples["actions"].shape[0]
    stats = []
    for _ in range(epochs):
        order = rng.permutation(n)
        for start in range(0, n, minibatch):
            rows = order[start:start + minibatch]
            batch = {k: _pad(v[rows], minibatch) for k, v in samples.items()}
            batch["weight"] = _pad(np.ones(len(rows), dtype=np.float32), minibatch)
            params, opt_state, loss, aux = _update_step(params, opt_state, batch, tx, clip, entropy_coef,
                                                        value_coef)
            stats.append([float(loss)] + [float(a) for a in aux])
    mean = np.mean(stats, axis=0) if stats else np.zeros(4)
    return params, opt_state, {"loss": mean[0], "policy_loss": mean[1], "value_loss": mean[2], "entropy": mean[3]}


def _pad(a, size):
    if a.shape[0] == size:
        return a
    pad = np.zeros((size - a.shape[0],) + a.shape[1:], dtype=a.dtype)
    return np.concatenate([a, pad])
