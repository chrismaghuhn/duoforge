"""Policies over a Batch: they choose; legality stays with the engine.

Both refuse a requested player with 0 candidates (ValueError): the engine
never reports one, hand-made arrays might.

RandomPolicy is the native mode's uniform random policy (decision 0012),
vectorized: every environment holds a splitmix64 state seeded from its
policy seed, and each requested player, in player order, takes the choice
of joint rank next() % count. With the same seeds it gives exactly the
native mode's episodes, on the index form and on the factored form.
"""
import ctypes

import numpy as np

from . import _layout
from ._lib import load_library, uint
from .batch import factored_choices

_C = _layout.CONSTANTS

_GAMMA = 0x9E3779B97F4A7C15
_M1 = 0xBF58476D1CE4E5B9
_M2 = 0x94D049BB133111EB
_TAG_POLICY = 0x6466706F6C696331  # "dfpolic1", decision 0012


def _splitmix(z):
    """splitmix64 of a uint64 array (Steele, Lea, Flood 2014), wrapping."""
    with np.errstate(over="ignore"):
        z = z + np.uint64(_GAMMA)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(_M1)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(_M2)
        return z ^ (z >> np.uint64(31))


def seeds(seed, env, episode):
    """(rng_initstate, rng_initseq, policy_seed) of an environment's episode
    (duoforge_batch_seeds)."""
    out = [ctypes.c_uint64() for _ in range(3)]
    load_library().duoforge_batch_seeds(uint(seed, 64, "seed"), uint(env, 32, "env"), uint(episode, 32, "episode"),
                                        *(ctypes.byref(v) for v in out))
    return tuple(v.value for v in out)


class RandomPolicy:
    """The uniform random policy of the native mode, one stream per env."""

    def __init__(self, seed, envs):
        self.seed = uint(seed, 64, "seed")
        self.state = np.zeros(int(envs), dtype=np.uint64)

    def start_episode(self, env, episode):
        """Seeds environment env's stream for `episode`."""
        self.state[env] = seeds(self.seed, env, episode)[2]

    def start_episodes(self, envs, episodes):
        """start_episode for many environments at once. The policy seed is
        decision 0012's derivation in NumPy (splitmix64 of the batch seed, the
        environment, the episode and the tag "dfpolic1"); a test pins it to
        duoforge_batch_seeds."""
        envs = np.asarray(envs)
        episodes = np.asarray(episodes)
        if envs.dtype.kind not in "iu" or episodes.dtype.kind not in "iu" or envs.shape != episodes.shape:
            raise TypeError("envs and episodes must be integer arrays of one shape")
        if envs.size and (envs.min() < 0 or envs.max() >= self.state.size or episodes.min() < 0
                          or episodes.max() >= 1 << 32):
            raise ValueError("an environment or episode is out of range")
        key = np.uint64(self.seed) ^ _splitmix((envs.astype(np.uint64) << np.uint64(32)) | episodes.astype(np.uint64))
        self.state[envs] = _splitmix(key ^ np.uint64(_TAG_POLICY))

    def _draw(self, mask, counts):
        """next() % counts for the environments in mask, advancing them."""
        if (counts == 0).any():
            raise ValueError("a requested player has no candidates")
        z = _splitmix(self.state[mask])
        with np.errstate(over="ignore"):
            self.state[mask] += np.uint64(_GAMMA)
        return z % counts.astype(np.uint64)

    def choose(self, batch):
        """Candidate indices (E,2) uint16; NO_CHOICE for players without a
        request. Reads batch.requests and batch.counts of the last query()."""
        out = np.full((batch.envs, 2), _layout.NO_CHOICE, dtype=np.uint16)
        for p in range(2):
            mask = batch.requests["requested"][:, p] != 0
            if mask.any():
                out[mask, p] = self._draw(mask, batch.counts[mask, p]).astype(np.uint16)
        return out

    def choose_factored(self, batch):
        """Factored choices (E,2) of the same joint ranks as choose(). Reads
        batch.requests and batch.domains of the last query_factored()."""
        out = np.zeros((batch.envs, 2), dtype=_layout.FACTORED_CHOICE)
        for p in range(2):
            mask = batch.requests["requested"][:, p] != 0
            if mask.any():
                ks = self._draw(mask, batch.requests["candidate_count"][mask, p])
                out[mask, p] = factored_choices(batch.domains[mask, p], ks.astype(np.int64))
        return out


class ScriptedPolicy:
    """The scripted baseline (spec section 4), vectorized over (E, 2, 784).

    Each slot command of a candidate scores: a MOVE at an occupied foe
    position 200 minus that foe's shown HP percent (100 to 200, so a move at
    a foe beats every other move and the weaker foe wins); any other MOVE (no
    target, an ally, an empty position) 10; a SWITCH -50; PASS and NONE 0.
    A candidate scores the sum over its two slots; the highest wins, ties to
    the lowest index. It reads only each player's own observation and
    candidates (the last query()).
    """

    def choose(self, batch):
        envs = batch.envs
        requested = batch.requests["requested"] != 0
        counts = batch.counts.astype(np.int64)
        if (counts[requested] == 0).any():
            raise ValueError("a requested player has no candidates")
        out = np.full((envs, 2), _layout.NO_CHOICE, dtype=np.uint16)
        if not requested.any():
            return out
        rows = np.arange(envs)
        # The shown HP percent of each player's foe at each foe slot; -1 for an empty position.
        shown = np.full((envs, 2, 2), -1, dtype=np.int64)
        for p in range(2):
            foe = batch.observations[:, p]["sides"][:, 1 - p]
            for k in range(2):
                occupant = foe["occupant"][:, k].astype(np.int64)
                present = occupant < _layout.MAX_ROSTER
                m = foe["members"][rows, np.where(present, occupant, 0)]
                hp = m["hp"].astype(np.int64)
                hp_max = m["hp_max"].astype(np.int64)
                exact = np.floor_divide(hp * 100, hp_max, out=np.full(envs, 100, np.int64), where=hp_max > 0)
                percent = np.where(m["hp_kind"] == _C["DUOFORGE_HP_PERCENT"], hp,
                                   np.where(m["hp_kind"] == _C["DUOFORGE_HP_EXACT"], exact, 100))
                shown[:, p, k] = np.where(present, percent, -1)
        width = int(counts.max())  # no candidate past every count is read
        cmds = batch.candidates["slots"][:, :, :width]  # (E, 2, width, 2)
        kind = cmds["kind"]
        target = cmds["target"].astype(np.int64)
        player = np.arange(2)[None, :, None, None]
        at_foe = (kind == _C["DUOFORGE_SLOT_MOVE"]) & (target < 4) & ((target >> 1) == 1 - player)
        hp = shown[rows[:, None, None, None], player, np.where(at_foe, target & 1, 0)]
        score = np.where(at_foe & (hp >= 0), 200 - hp,
                         np.where(kind == _C["DUOFORGE_SLOT_MOVE"], 10,
                                  np.where(kind == _C["DUOFORGE_SLOT_SWITCH"], -50, 0)))
        total = score.sum(axis=3)
        valid = np.arange(width)[None, None, :] < counts[:, :, None]
        total = np.where(valid, total, np.iinfo(np.int64).min)
        best = np.argmax(total, axis=2)  # the first maximum: ties go to the lowest index
        out[requested] = best[requested].astype(np.uint16)
        return out
