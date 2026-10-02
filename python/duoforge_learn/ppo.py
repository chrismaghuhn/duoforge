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


def update(params, opt_state, tx, samples, rng, evaluate_fn=model.evaluate, epochs=4, minibatch=4096, clip=0.2,
           entropy_coef=0.01, value_coef=0.5):
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
