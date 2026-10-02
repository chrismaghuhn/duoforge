"""The actor-critic network (decision 0014 section 4), in JAX.

Torso: an MLP over the observation part. Slot heads: every option of slot
list s gets a logit from the torso and the option's features; a pair's
logit is the sum of its two options' logits, and pairs outside the engine's
pair mask get none of the probability. Team head: one logit per ordered
4-of-6 tuple. Value head: one scalar from the viewer's perspective.
"""
import jax
import jax.numpy as jnp

MASKED = -1e9  # a pair outside the mask: exp() underflows to exactly 0


def _dense(key, n_in, n_out, scale=1.0):
    w = jax.random.normal(key, (n_in, n_out), dtype=jnp.float32) * (scale * jnp.sqrt(2.0 / n_in))
    return {"w": w, "b": jnp.zeros((n_out,), dtype=jnp.float32)}


def init(key, obs_size, slot_features, team_actions, hidden=256, option_hidden=128):
    """Fresh parameters."""
    k = jax.random.split(key, 7)
    return {
        "t1": _dense(k[0], obs_size, hidden),
        "t2": _dense(k[1], hidden, hidden),
        "option_torso": _dense(k[2], hidden, option_hidden),
        "option_features": _dense(k[3], slot_features, option_hidden),
        "option_out": _dense(k[4], option_hidden, 2, 0.01),
        "team": _dense(k[5], hidden, team_actions, 0.01),
        "value": _dense(k[6], hidden, 1, 0.01),
    }


def _layer(p, x):
    return x @ p["w"] + p["b"]


def apply(params, obs, slots, mask):
    """obs (B, O), slots (B, 2, 32, F), mask (B, 32, 32) bool ->
    (pair log-probabilities (B, 1024), team log-probabilities (B, T),
    value (B,))."""
    h = jax.nn.relu(_layer(params["t1"], obs))
    h = jax.nn.relu(_layer(params["t2"], h))
    hidden = jax.nn.relu(_layer(params["option_torso"], h)[:, None, None, :]
                         + _layer(params["option_features"], slots))
    out = _layer(params["option_out"], hidden)  # (B, 2, 32, 2): output s scores slot list s
    pairs = out[:, 0, :, 0][:, :, None] + out[:, 1, :, 1][:, None, :]
    pairs = jnp.where(mask, pairs, MASKED).reshape(obs.shape[0], -1)
    team = _layer(params["team"], h)
    value = _layer(params["value"], h)[:, 0]
    return jax.nn.log_softmax(pairs), jax.nn.log_softmax(team), value


def _entropy(logp):
    return -jnp.sum(jnp.exp(logp) * logp, axis=-1)


def evaluate(params, obs, slots, mask, is_team, actions):
    """(log-probability of actions, entropy, value) per row; a row's
    distribution is the team head's at TEAM_SELECTION, the pairs' else."""
    logp_pairs, logp_team, value = apply(params, obs, slots, mask)
    pair = jnp.take_along_axis(logp_pairs, jnp.clip(actions, 0, logp_pairs.shape[1] - 1)[:, None], axis=1)[:, 0]
    team = jnp.take_along_axis(logp_team, jnp.clip(actions, 0, logp_team.shape[1] - 1)[:, None], axis=1)[:, 0]
    logp = jnp.where(is_team, team, pair)
    entropy = jnp.where(is_team, _entropy(logp_team), _entropy(logp_pairs))
    return logp, entropy, value


def act(params, key, obs, slots, mask, is_team, greedy=False):
    """(actions, log-probabilities, values) for a batch of rows."""
    logp_pairs, logp_team, value = apply(params, obs, slots, mask)
    if greedy:
        pair = jnp.argmax(logp_pairs, axis=1)
        team = jnp.argmax(logp_team, axis=1)
    else:
        k1, k2 = jax.random.split(key)
        pair = jax.random.categorical(k1, logp_pairs, axis=1)
        team = jax.random.categorical(k2, logp_team, axis=1)
    actions = jnp.where(is_team, team, pair)
    logp = jnp.where(is_team, jnp.take_along_axis(logp_team, team[:, None], axis=1)[:, 0],
                     jnp.take_along_axis(logp_pairs, pair[:, None], axis=1)[:, 0])
    return actions, logp, value
