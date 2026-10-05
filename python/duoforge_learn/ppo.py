"""PPO for self-play over each seat's own decisions (decision 0014 section 5).

The advantages, returns and value targets come from returns.gae. The
policy loss covers the rows where a seat acted; the value loss covers every
row, so the value of a state where a seat waits is trained too (it
bootstraps the rollout's end).

Two plateau levers (2026-10-04): lr_scale multiplies the optimizer's step
(a learning-rate schedule that leaves the optimizer state's structure as it
is, so saved runs resume), and samples with "ref_logp" (a reference policy's
log-probability of each taken action, for example the BC prior) add
kl_coef times the k3 estimate of KL(policy || reference) on the policy's rows:
(r - 1) - log r with r = exp(ref_logp - logp), never negative. Above
log r = KL_LOG_RATIO_MAX the estimate goes on linearly with k3's slope at
the cap: a rarely drawn action that the reference finds likely made r
unbounded (means up to 7.9e6 in the magnet run of 2026-10-04), and one such
row filled a whole clipped gradient step.
"""
import functools

import jax
import jax.numpy as jnp
import numpy as np
import optax

from . import model
from .returns import gae  # noqa: F401  (the advantages of a rollout)


KL_LOG_RATIO_MAX = 3.0


def _k3(log_r):
    """k3 of log r up to KL_LOG_RATIO_MAX, linear beyond it (same value
    and slope at the cap)."""
    c = KL_LOG_RATIO_MAX
    capped = jnp.minimum(log_r, c)
    return jnp.exp(capped) - 1.0 - capped + (jnp.exp(c) - 1.0) * jnp.maximum(log_r - c, 0.0)


def optimizer(learning_rate=3e-4, max_norm=0.5):
    return optax.chain(optax.clip_by_global_norm(max_norm), optax.adam(learning_rate))


def _loss(params, batch, evaluate_fn, clip, entropy_coef, value_coef, kl_coef=0.0):
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
    if "ref_logp" in batch:  # the KL anchor to a reference policy (k3 on the taken actions)
        log_r = batch["ref_logp"] - logp
        kl_mean = (_k3(log_r) * w).sum() / total
        loss = loss + kl_coef * kl_mean
    else:
        kl_mean = jnp.float32(0.0)
    return loss, (policy_loss, value_loss, entropy_mean, kl_mean)


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
    mean = np.mean(stats, axis=0) if stats else np.zeros(5)
    return params, opt_state, {"loss": mean[0], "policy_loss": mean[1], "value_loss": mean[2], "entropy": mean[3],
                               "kl": mean[4]}


def _pad(a, size):
    if a.shape[0] == size:
        return a
    pad = np.zeros((size - a.shape[0],) + a.shape[1:], dtype=a.dtype)
    return np.concatenate([a, pad])


def reference_logp(params, samples, evaluate_fn=model.evaluate, minibatch=4096):
    """The log-probability under params of each sample's taken action (the
    KL anchor's "ref_logp"), in minibatches of a fixed size, the last one
    padded, so that a large rollout does not ask the device for every row at
    once and every call has one shape."""
    n = samples["actions"].shape[0]
    keys = ("obs", "slots", "mask", "is_team", "actions")
    out = np.empty(n, dtype=np.float32)
    for start in range(0, n, minibatch):
        rows = min(minibatch, n - start)
        batch = [_pad(samples[k][start:start + rows], minibatch) for k in keys]
        out[start:start + rows] = np.asarray(evaluate_fn(params, *batch)[0])[:rows]
    return out


@functools.partial(jax.jit, static_argnames=("tx", "evaluate_fn", "clip", "value_coef"))
def _epochs(params, opt_state, data, order, tx, evaluate_fn, clip, entropy_coef, value_coef, kl_coef, lr_scale):
    """Every minibatch of every epoch in one call: order (steps, minibatch)
    holds the rows of each minibatch in data, which stays on the device."""

    def step(carry, rows):
        params, opt_state = carry
        batch = {k: jnp.take(v, rows, axis=0) for k, v in data.items()}
        (loss, aux), grads = jax.value_and_grad(_loss, has_aux=True)(params, batch, evaluate_fn, clip,
                                                                     entropy_coef, value_coef, kl_coef)
        updates, opt_state = tx.update(grads, opt_state, params)
        updates = jax.tree_util.tree_map(lambda u: u * lr_scale, updates)
        return (optax.apply_updates(params, updates), opt_state), jnp.stack([loss, *aux])

    (params, opt_state), stats = jax.lax.scan(step, (params, opt_state), order)
    return params, opt_state, stats


def update(params, opt_state, tx, samples, rng, evaluate_fn=model.evaluate, epochs=4, minibatch=4096, clip=0.2,
           entropy_coef=0.01, value_coef=0.5, kl_coef=0.0, lr_scale=1.0):
    """PPO epochs over the samples (dict of arrays, one row per decision),
    in minibatches of a fixed size (the last one of an epoch padded with
    rows of weight 0). The samples go to the device once; every epoch's
    permutation (rng, as _update_host draws it) cuts the minibatches there,
    in one jitted scan. lr_scale multiplies every step and kl_coef weighs the
    KL anchor of samples with "ref_logp" (module docstring). Returns (params,
    opt_state, mean losses with t_transfer and t_compute, the seconds of the
    copy and of the epochs)."""
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
                                       jnp.float32(entropy_coef), value_coef, jnp.float32(kl_coef),
                                       jnp.float32(lr_scale))
    stats = np.asarray(jax.block_until_ready(stats))
    t2 = time.perf_counter()
    mean = stats.mean(axis=0) if stats.size else np.zeros(5)
    return params, opt_state, {"loss": mean[0], "policy_loss": mean[1], "value_loss": mean[2], "entropy": mean[3],
                               "kl": mean[4], "t_transfer": t1 - t0, "t_compute": t2 - t1}
