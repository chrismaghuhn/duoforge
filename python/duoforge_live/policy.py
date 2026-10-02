"""The learner's network in NumPy, for play without JAX.

forward(params, obs, slots, mask) is duoforge_learn.model.apply computed with
NumPy in float32 (the test duoforge.python.learn compares the two). A Policy
plays greedily: rank_pairs and rank_teams list the choices best first, ties
to the lower flat index, so the next one after a rejection is defined. The
observation part goes through features.as_encoder with the checkpoint's
encoder version first, so a network sees the inputs it was trained on.
"""
import numpy as np

from duoforge import features
from duoforge_learn import checkpoint

MASKED = np.float32(-1e9)  # a pair outside the mask: exp() underflows to exactly 0, as in model.MASKED


def _layer(p, x):
    return x @ p["w"] + p["b"]


def _relu(x):
    return np.maximum(x, np.float32(0))


def _log_softmax(x):
    z = x - x.max(axis=-1, keepdims=True)
    return z - np.log(np.exp(z).sum(axis=-1, keepdims=True))


def forward(params, obs, slots, mask):
    """obs (B, O), slots (B, 2, 32, F), mask (B, 32, 32) bool -> (pair log-probabilities (B, 1024), team
    log-probabilities (B, T), value (B,)), float32."""
    obs = np.asarray(obs, dtype=np.float32)
    slots = np.asarray(slots, dtype=np.float32)
    h = _relu(_layer(params["t1"], obs))
    h = _relu(_layer(params["t2"], h))
    hidden = _relu(_layer(params["option_torso"], h)[:, None, None, :] + _layer(params["option_features"], slots))
    out = _layer(params["option_out"], hidden)  # (B, 2, 32, 2): output s scores slot list s
    pairs = out[:, 0, :, 0][:, :, None] + out[:, 1, :, 1][:, None, :]
    pairs = np.where(np.asarray(mask, dtype=bool), pairs, MASKED).reshape(obs.shape[0], -1)
    team = _layer(params["team"], h)
    value = _layer(params["value"], h)[:, 0]
    return _log_softmax(pairs), _log_softmax(team), value


def _ranked(logp, allowed):
    """Indices of `allowed` by descending log-probability, ties to the lower index; with probabilities."""
    index = np.flatnonzero(allowed)
    order = index[np.argsort(-logp[index], kind="stable")]
    return [(int(i), float(np.exp(logp[i]))) for i in order]


class Policy:
    """A checkpoint's network, played greedily."""

    def __init__(self, params, encoder=features.ENCODER):
        self.params = params
        self.encoder = encoder

    def _input(self, observation, obs_part):
        return features.as_encoder(np.asarray(obs_part, dtype=np.float32), observation, self.encoder)[None, :]

    def rank_pairs(self, observation, obs_part, slot_part, pair_mask):
        """[(i, j, probability)] of the allowed pairs, best first."""
        logp, _, _ = forward(self.params, self._input(observation, obs_part), slot_part[None], pair_mask[None])
        n = pair_mask.shape[1]
        return [(i // n, i % n, p) for i, p in _ranked(logp[0], np.asarray(pair_mask, dtype=bool).reshape(-1))]

    def rank_teams(self, observation, obs_part):
        """[(index into duoforge_learn.selfplay.TEAM_TABLE, probability)], best first."""
        slots = np.zeros((1, 2, features.OPTIONS, features.SLOT_FEATURES), dtype=np.float32)
        mask = np.zeros((1, features.OPTIONS, features.OPTIONS), dtype=bool)
        _, logp, _ = forward(self.params, self._input(observation, obs_part), slots, mask)
        return _ranked(logp[0], np.ones(logp.shape[1], dtype=bool))


def load(path):
    """The Policy of a checkpoint whose network takes this encoder's features; a 594-feature file raises."""
    params, config = checkpoint.load(path, obs_size=features.OBS_SIZE)
    return Policy(params, checkpoint.encoder_of(config))
