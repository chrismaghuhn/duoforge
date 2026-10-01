"""Policies over a Batch: they choose; legality stays with the engine.

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

_GAMMA = 0x9E3779B97F4A7C15
_M1 = 0xBF58476D1CE4E5B9
_M2 = 0x94D049BB133111EB


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

    def _draw(self, mask, counts):
        """next() % counts for the environments in mask, advancing them."""
        if (counts == 0).any():
            raise ValueError("a requested player has no candidates")
        with np.errstate(over="ignore"):
            self.state[mask] += np.uint64(_GAMMA)
            z = self.state[mask]
            z = (z ^ (z >> np.uint64(30))) * np.uint64(_M1)
            z = (z ^ (z >> np.uint64(27))) * np.uint64(_M2)
            z = z ^ (z >> np.uint64(31))
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
