"""PPO for self-play over each seat's own decisions (decision 0014 section 5).

The advantages, returns and value targets come from returns.gae. The
policy loss covers the rows where a seat acted; the value loss covers every
row, so the value of a state where a seat waits is trained too (it
bootstraps the rollout's end).
"""
import functools

import jax
import jax.numpy as jnp
import numpy as np
import optax

from . import model
from .returns import gae  # noqa: F401  (the advantages of a rollout)


def optimizer(learning_rate=3e-4, max_norm=0.5):
    return optax.chain(optax.clip_by_global_norm(max_norm), optax.adam(learning_rate))


def _loss(params, batch, evaluate_fn, clip, entropy_coef, value_coef):
    logp, entropy, value = evaluate_fn(params, batch["obs"], batch["slots"], batch["mask"], batch["is_team"],
                                       batch["actions"])
    w = batch["weight"] * batch["acting"]  # the policy's rows
    total = jnp.maximum(w.sum(), 1.0)
    adv = batch["advantages"]
    mean = (adv * w).sum() / total
    std = jnp.sqrt((((adv - mean) ** 2) * w).sum() / total) + 1e-8
    adv = (adv - mean) / std
    ratio = jnp.exp(logp - batch["logp"])
    surrogate = jnp.minimum(ratio * adv, jnp.clip(ratio, 1.0 - clip, 1.0 + clip) * adv)
    policy_loss = -(surrogate * w).sum() / total
    wv = batch["weight"]  # the value's rows: all
    value_loss = (((value - batch["value_targets"]) ** 2) * wv).sum() / jnp.maximum(wv.sum(), 1.0)
    entropy_mean = (entropy * w).sum() / total
    loss = policy_loss + value_coef * value_loss - entropy_coef * entropy_mean
    return loss, (policy_loss, value_loss, entropy_mean)


@functools.partial(jax.jit, static_argnames=("tx", "evaluate_fn", "clip", "value_coef"))
def _update_step(params, opt_state, batch, tx, evaluate_fn, clip, entropy_coef, value_coef):
    (loss, aux), grads = jax.value_and_grad(_loss, has_aux=True)(params, batch, evaluate_fn, clip, entropy_coef,
                                                                 value_coef)
    updates, opt_state = tx.update(grads, opt_state, params)
    return optax.apply_updates(params, updates), opt_state, loss, aux


def _update_host(params, opt_state, tx, samples, rng, evaluate_fn=model.evaluate, epochs=4, minibatch=4096,
                 clip=0.2, entropy_coef=0.01, value_coef=0.5):
    """update as decision 0014 ran it: every minibatch is cut on the host and
    copied to the device. Kept as the reference of update's test."""
    n = samples["actions"].shape[0]
    stats = []
    for _ in range(epochs):
        order = rng.permutation(n)
        for start in range(0, n, minibatch):
            rows = order[start:start + minibatch]
            batch = {k: _pad(v[rows], minibatch) for k, v in samples.items()}
            batch["weight"] = _pad(np.ones(len(rows), dtype=np.float32), minibatch)
            params, opt_state, loss, aux = _update_step(params, opt_state, batch, tx, evaluate_fn, clip,
                                                        jnp.float32(entropy_coef), value_coef)
            stats.append([float(loss)] + [float(a) for a in aux])
    mean = np.mean(stats, axis=0) if stats else np.zeros(4)
    return params, opt_state, {"loss": mean[0], "policy_loss": mean[1], "value_loss": mean[2], "entropy": mean[3]}


def _pad(a, size):
    if a.shape[0] == size:
        return a
    pad = np.zeros((size - a.shape[0],) + a.shape[1:], dtype=a.dtype)
    return np.concatenate([a, pad])


@functools.partial(jax.jit, static_argnames=("tx", "evaluate_fn", "clip", "value_coef"))
def _epochs(params, opt_state, data, order, tx, evaluate_fn, clip, entropy_coef, value_coef):
    """Every minibatch of every epoch in one call: order (steps, minibatch)
    holds the rows of each minibatch in data, which stays on the device."""

    def step(carry, rows):
        params, opt_state = carry
        batch = {k: jnp.take(v, rows, axis=0) for k, v in data.items()}
        (loss, aux), grads = jax.value_and_grad(_loss, has_aux=True)(params, batch, evaluate_fn, clip,
                                                                     entropy_coef, value_coef)
        updates, opt_state = tx.update(grads, opt_state, params)
        return (optax.apply_updates(params, updates), opt_state), jnp.stack([loss, *aux])

    (params, opt_state), stats = jax.lax.scan(step, (params, opt_state), order)
    return params, opt_state, stats


def update(params, opt_state, tx, samples, rng, evaluate_fn=model.evaluate, epochs=4, minibatch=4096, clip=0.2,
           entropy_coef=0.01, value_coef=0.5):
    """PPO epochs over the samples (dict of arrays, one row per decision),
    in minibatches of a fixed size (the last one of an epoch padded with
    rows of weight 0). The samples go to the device once; every epoch's
    permutation (rng, as _update_host draws it) cuts the minibatches there,
    in one jitted scan. Returns (params, opt_state, mean losses with
    t_transfer and t_compute, the seconds of the copy and of the epochs)."""
    import time
    n = samples["actions"].shape[0]
    total = -(-n // minibatch) * minibatch
    t0 = time.perf_counter()
    host = {k: _pad(v, total) for k, v in samples.items()}
    host["weight"] = _pad(np.ones(n, dtype=np.float32), total)
    data = jax.device_put(host)
    jax.block_until_ready(data)
    t1 = time.perf_counter()
    order = np.concatenate([np.concatenate([rng.permutation(n), np.arange(n, total)]) for _ in range(epochs)])
    order = order.reshape(-1, minibatch).astype(np.int32)
    params, opt_state, stats = _epochs(params, opt_state, data, order, tx, evaluate_fn, clip,
                                       jnp.float32(entropy_coef), value_coef)
    stats = np.asarray(jax.block_until_ready(stats))
    t2 = time.perf_counter()
    mean = stats.mean(axis=0) if stats.size else np.zeros(4)
    return params, opt_state, {"loss": mean[0], "policy_loss": mean[1], "value_loss": mean[2], "entropy": mean[3],
                               "t_transfer": t1 - t0, "t_compute": t2 - t1}
