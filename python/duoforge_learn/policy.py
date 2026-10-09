"""One interface over the model versions (decision 0017): v1 (model.py) and v2
(model_v2.py).

make(config) gives a Model for a configuration as checkpoints store it
({"version": 1, ...} or {"version": 2, ...}); its act and apply are jitted
once per Model. act checks the ids model v2 embeds on the host first, so an
id past a capacity raises instead of being clipped.
"""
import functools

import jax
import jax.numpy as jnp
import numpy as np

from duoforge import _layout, features

from . import columns, model, model_v2
from .selfplay import TEAM_ACTIONS

V1_DEFAULT = {"version": 1, "hidden": 256, "option_hidden": 128}
v2_config = model_v2.config


def _entropy(logp):
    return -jnp.sum(jnp.exp(logp) * logp, axis=-1)


def full_joint(logp_pairs, legal):
    """(B, 1024): logp_pairs at the legal joint actions, -inf elsewhere."""
    return jnp.where(jnp.reshape(legal, (logp_pairs.shape[0], -1)), logp_pairs, -jnp.inf)


def refuse_empty_rows(legal):
    """ValueError naming the first row of legal ((B, 32, 32) or (B, 1024), concrete) without a legal action."""
    legal = np.asarray(legal)
    empty = np.flatnonzero(~legal.reshape(legal.shape[0], -1).any(axis=1))
    if empty.size:
        raise ValueError(f"full_joint_log_probs: row {int(empty[0])} has no legal joint action")


def _evaluate(apply, params, obs, slots, mask, is_team, actions):
    logp_pairs, logp_team, value = apply(params, obs, slots, mask)
    pair = jnp.take_along_axis(logp_pairs, jnp.clip(actions, 0, logp_pairs.shape[1] - 1)[:, None], axis=1)[:, 0]
    team = jnp.take_along_axis(logp_team, jnp.clip(actions, 0, logp_team.shape[1] - 1)[:, None], axis=1)[:, 0]
    logp = jnp.where(is_team, team, pair)
    entropy = jnp.where(is_team, _entropy(logp_team), _entropy(logp_pairs))
    return logp, entropy, value


def _value(apply, slot_features, params, obs):
    b = obs.shape[0]
    slots = jnp.zeros((b, 2, _layout.MAX_SLOT_OPTIONS, slot_features), dtype=jnp.float32)
    mask = jnp.zeros((b, _layout.MAX_SLOT_OPTIONS, _layout.MAX_SLOT_OPTIONS), dtype=jnp.bool_)
    return apply(params, obs, slots, mask)[2]


def _act(apply, params, key, obs, slots, mask, is_team, greedy=False):
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


class Model:
    """A model version with its configuration and the encoder layout it reads."""

    def __init__(self, config, feature_names=features.FEATURE_NAMES, slot_names=features.SLOT_FEATURE_NAMES):
        self.config = dict(config)
        version = self.config.get("version")
        self.feature_names = tuple(feature_names)
        self.slot_names = tuple(slot_names)
        if version == 1:
            self._apply = model.apply
            self._cols = None
        elif version == 2:
            self._cols = columns.columns(self.feature_names, self.slot_names)
            self._apply = functools.partial(model_v2.apply, cfg=self.config, cols=self._cols)
        else:
            raise ValueError(f"unknown model version {version!r}")
        self.apply = jax.jit(lambda params, obs, slots, mask: self._apply(params, obs=obs, slots=slots, mask=mask)
                             if version == 2 else self._apply(params, obs, slots, mask))
        self.evaluate = functools.partial(_evaluate, self.apply)
        self._act = jax.jit(functools.partial(_act, self.apply), static_argnames=("greedy",))
        self._value = jax.jit(functools.partial(_value, self.apply, len(self.slot_names)))

    def init(self, key):
        """Fresh parameters."""
        if self.config["version"] == 1:
            return model.init(key, len(self.feature_names), len(self.slot_names), TEAM_ACTIONS,
                              hidden=self.config["hidden"], option_hidden=self.config["option_hidden"])
        return model_v2.init(key, self.config, self._cols)

    def check(self, obs):
        """Raises ValueError for an id model v2 cannot embed (v1: nothing)."""
        if self._cols is not None:
            columns.check_ids(obs, self._cols, self.config["capacities"])

    def act(self, params, key, obs, slots, mask, is_team, greedy=False):
        """(actions, log-probabilities, values) of a batch of rows."""
        self.check(np.asarray(obs))
        if key is None:
            key = jax.random.PRNGKey(0)  # greedy play draws nothing
        return self._act(params, key, obs, slots, mask, is_team, greedy=greedy)

    def value(self, params, obs):
        """The value of a batch of rows (B,) float32, each from its own
        view: apply on all-zero slots and an all-false pair mask, which the
        value does not read (spec section 3), so it is the value training
        computes. A search's leaves need no policy (decision 0022). Checks
        the ids first, as act does."""
        self.check(np.asarray(obs))
        return self._value(params, obs)

    def full_joint_log_probs_traced(self, params, obs, slots, legal_mask):
        """full_joint_log_probs without the host check of empty rows, for
        use inside jitted losses (whose rows are validated at load)."""
        b = obs.shape[0]
        mask = jnp.reshape(legal_mask, (b, _layout.MAX_SLOT_OPTIONS, _layout.MAX_SLOT_OPTIONS))
        return full_joint(self.apply(params, obs, slots, mask)[0], mask)

    def full_joint_log_probs(self, params, obs, slots, legal_mask):
        """(B, 1024) float32: the log-probability of every joint action (slot
        pair i * 32 + j), the pair head's log-softmax over all legal actions
        of legal_mask ((B, 32, 32) or (B, 1024) bool) and -inf where illegal
        (stage 3, P1 plan C4 step 11). Never renormalized over a candidate
        set. Checks on the host first, as act does: an id past a capacity
        and a row without a legal action raise ValueError, so obs and
        legal_mask must be concrete (inside jit, use
        full_joint_log_probs_traced on rows validated beforehand). A loss
        over these values must skip zero-mass entries (0 * -inf is NaN)."""
        try:
            obs_host, legal = np.asarray(obs), np.asarray(legal_mask)
        except jax.errors.TracerArrayConversionError:
            raise ValueError("full_joint_log_probs checks obs and legal_mask on the host: inside jit use "
                             "full_joint_log_probs_traced on validated rows") from None
        self.check(obs_host)
        refuse_empty_rows(legal.reshape(obs_host.shape[0], -1))
        return self.full_joint_log_probs_traced(params, obs, slots, legal_mask)

    @staticmethod
    def count(params):
        """The number of parameters."""
        return int(sum(np.size(x) for x in jax.tree_util.tree_leaves(params)))


def make(config, feature_names=features.FEATURE_NAMES, slot_names=features.SLOT_FEATURE_NAMES):
    """The Model of a configuration."""
    return Model(config, feature_names, slot_names)
