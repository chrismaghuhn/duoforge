"""The learner's network in NumPy, for play without JAX.

forward(params, obs, slots, mask) is duoforge_learn.model.apply computed with
NumPy in float32 (the test duoforge.python.learn compares the two). A Policy
plays greedily: rank_pairs and rank_teams list the choices best first, ties
to the lower flat index, so the next one after a rejection is defined. The
observation part goes through features.as_encoder with the checkpoint's
encoder version first, so a network sees the inputs it was trained on.

forward is model v1's. A checkpoint of another model version (model v2: params-49333, the honest search's network)
plays through its own network in its trained layout (ModelPolicy, JAX on the CPU); load picks by the checkpoint.
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
    if index.size == 0:
        raise ValueError("nothing to rank: no choice is allowed")
    order = index[np.argsort(-logp[index], kind="stable")]
    return [(int(i), float(np.exp(logp[i]))) for i in order]


class Policy:
    """A checkpoint's network, played greedily on the inputs of its encoder version (features.ENCODERS;
    checkpoint.encoder_of reads it from a config) and view-extension mask (checkpoint.ext_supported_of). The
    Game encodes the tracker's OBSERVATION_EXT record (Tracker.observation_ext): a feature the tracker does not fold
    stops it at the line that would set it (lines._feature), so until then that feature's fields are truly zero
    (HauptSession, 2026-10-10); the base values (Sand, Snow, Electric, Misty, Tox) come from the observation."""

    def __init__(self, params, encoder, ext_supported=0):
        self.params = params
        self.encoder = encoder
        self.ext_supported = ext_supported

    def _forward(self, obs, slots, mask):
        return forward(self.params, obs, slots, mask)

    def _input(self, observation, obs_part):
        return features.as_encoder(np.asarray(obs_part, dtype=np.float32), observation, self.encoder)[None, :]

    def rank_pairs(self, observation, obs_part, slot_part, pair_mask):
        """[(i, j, probability)] of the allowed pairs, best first."""
        slots = features.slots_as_encoder(np.asarray(slot_part, dtype=np.float32), self.encoder)
        logp, _, _ = self._forward(self._input(observation, obs_part), slots[None], pair_mask[None])
        n = pair_mask.shape[1]
        return [(i // n, i % n, p) for i, p in _ranked(logp[0], np.asarray(pair_mask, dtype=bool).reshape(-1))]

    def rank_teams(self, observation, obs_part):
        """[(index into duoforge_learn.selfplay.TEAM_TABLE, probability)], best first."""
        slots = np.zeros((1, 2, features.OPTIONS, features.SLOT_FEATURES), dtype=np.float32)
        mask = np.zeros((1, features.OPTIONS, features.OPTIONS), dtype=bool)
        _, logp, _ = self._forward(self._input(observation, obs_part), slots, mask)
        return _ranked(logp[0], np.ones(logp.shape[1], dtype=bool))


def table_kind(config):
    """The live tables' kind (data.load) of a checkpoint's config: its data kind, "closure" for a format-1 file. The
    tracker's view (and its extension record) is the kind the network was trained under; Team C data has no live
    tables, so it is refused."""
    kind = config.get("data", {}).get("kind", "closure") if config.get("format") == 2 else "closure"
    if kind not in ("closure", "pool"):
        raise ValueError(f"no live tables of data kind {kind!r}")
    return kind


class ModelPolicy(Policy):
    """A format-2 checkpoint's own network (checkpoint.trained_model) in its trained layout, through JAX."""

    def __init__(self, model, params, encoder, ext_supported=0):
        super().__init__(params, encoder, ext_supported)
        self.model = model

    def _forward(self, obs, slots, mask):
        return tuple(np.asarray(x) for x in self.model.apply(self.params, obs, slots, np.asarray(mask, dtype=bool)))


def load(path):
    """The Policy of a checkpoint whose network takes the features of its own encoder version
    (features.obs_size); a 594-feature file raises. A format-2 checkpoint of a model version other than 1 is a
    ModelPolicy."""
    params, config = checkpoint.load(path)
    if config.get("format") == 2 and checkpoint.model_config(config, params).get("version") != 1:
        params, config = checkpoint.load_trained(path)
        return ModelPolicy(checkpoint.trained_model(config, params), params, checkpoint.encoder_of(config),
                           checkpoint.ext_supported_of(config))
    encoder = checkpoint.encoder_of(config)
    width, want = params["t1"]["w"].shape[0], features.obs_size(encoder)
    if width != want:
        raise ValueError(f"{path}: the network takes {width} observation features, encoder {encoder} makes {want} "
                         "(a checkpoint of another encoder layout)")
    return Policy(params, encoder, checkpoint.ext_supported_of(config))
