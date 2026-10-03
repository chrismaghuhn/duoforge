"""Behavior cloning of Learner v2's model on the replay rows (M11 BC spec, approach A).

The loss of a row is -log P(label set): for a decision, the log of the summed probability of the pairs inside its
label set (bc_data.Rows.label_pairs, pair index i * 32 + j as the model's pair head); for a team selection, the same
over its tuples. The value head learns the outcome (+1 won, -1 lost) with weight value_coef. Rows are weighted
(bc_data.rating_weight, the format weights).
"""
import jax
import jax.numpy as jnp
import numpy as np

_NEG = -1e30  # outside a label set: finite, so a row of the other kind (all outside) gives no NaN gradient


def as_batch(rows):
    """The arrays of bc_data.Rows the loss reads, as JAX arrays."""
    n = len(rows)
    return {"label_pairs": jnp.asarray(rows.label_pairs.reshape(n, -1)), "label_team": jnp.asarray(rows.label_team),
            "is_team": jnp.asarray(rows.is_team), "weight": jnp.asarray(rows.weight, jnp.float32),
            "z": jnp.asarray(rows.z, jnp.float32), "has_z": jnp.asarray(rows.has_z)}


def loss_terms(logp_pairs, logp_team, value, batch, value_coef):
    """(total, {"nll", "value_mse"}) of model outputs (log_softmax pairs (B, 1024), log_softmax team (B, 360),
    value (B,)) against a batch (as_batch)."""
    pair_nll = -jax.nn.logsumexp(jnp.where(batch["label_pairs"], logp_pairs, _NEG), axis=1)
    team_nll = -jax.nn.logsumexp(jnp.where(batch["label_team"], logp_team, _NEG), axis=1)
    nll = jnp.where(batch["is_team"], team_nll, pair_nll)
    w = batch["weight"]
    policy = jnp.sum(w * nll) / jnp.sum(w)
    vw = w * batch["has_z"]
    value_mse = jnp.sum(vw * (value - batch["z"]) ** 2) / jnp.maximum(jnp.sum(vw), 1e-9)
    return policy + value_coef * value_mse, {"nll": policy, "value_mse": value_mse}


def loss(params, net, obs, slots, mask, batch, value_coef):
    """loss_terms of the network's outputs on encoded rows."""
    logp_pairs, logp_team, value = net.apply(params, obs, slots, mask)
    return loss_terms(logp_pairs, logp_team, value, batch, value_coef)
