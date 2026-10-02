"""Teams for training (decision 0017): the team pool, and (Task 17) the
registry loader.

A TeamPool holds the teams a run plays: their registry ids, the sha256 of
their files ("" for teams made from setups), sampling weights and side
setups (SIDE_SETUP). It builds the battle setups of pairs of team indices;
the library checks them when a battle starts, so nothing here decides
legality.
"""
import dataclasses
import math

import numpy as np

from . import _layout


class TeamError(ValueError):
    """A team cannot be read or the library refuses it; the message names it."""


def _weights(weights, n):
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=np.float64)
    if w.shape != (n,):
        raise ValueError(f"{w.size} weights for {n} teams")
    for i, x in enumerate(w.tolist()):
        if not math.isfinite(x) or x < 0:
            raise ValueError(f"team weight {i} is {x}: weights must be finite and at least 0")
    if w.sum() <= 0:
        raise ValueError("the team weights sum to 0: no team could be drawn")
    return w


@dataclasses.dataclass(frozen=True)
class TeamPool:
    ids: tuple
    sha256: tuple
    weights: np.ndarray
    sides: np.ndarray

    def __post_init__(self):
        n = len(self.ids)
        if len(set(self.ids)) != n:
            raise ValueError(f"team ids are not unique: {self.ids}")
        if len(self.sha256) != n or self.sides.dtype != _layout.SIDE_SETUP or self.sides.shape != (n,):
            raise ValueError(f"a pool of {n} teams needs {n} hashes and {n} SIDE_SETUP records")
        object.__setattr__(self, "weights", _weights(self.weights, n))

    @staticmethod
    def from_setups(ids, sides, weights=None):
        """A pool of side setups (SIDE_SETUP, (N,)) with ids and no files."""
        sides = np.array(sides, dtype=_layout.SIDE_SETUP).reshape(-1)
        return TeamPool(tuple(ids), ("",) * len(tuple(ids)), weights, sides)

    def with_weights(self, weights):
        return dataclasses.replace(self, weights=weights)

    def setups(self, side0, side1):
        """Battle setups (SETUP, (K,)) of team indices side0 and side1; the
        rng fields are 0 (a batch derives them)."""
        side0, side1 = np.asarray(side0), np.asarray(side1)
        out = np.zeros(side0.shape[0], dtype=_layout.SETUP)
        out["sides"][:, 0] = self.sides[side0]
        out["sides"][:, 1] = self.sides[side1]
        return out
