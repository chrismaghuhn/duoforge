"""Draws of Learner v2 (decision 0017): splitmix64 over (seed, tag, a, b),
a pure function, so pairings, league slots and snapshots and the
evaluation suite never depend on the order a run asked for them.

draw(seed, tag, a, b) = splitmix64(splitmix64(splitmix64(seed + tag) + a) + b)
over uint64 (wrapping); pick turns a draw into an index by inverse
cumulative weight.
"""
import numpy as np

PAIR_SIDE0 = 1
PAIR_SIDE1 = 2
LEAGUE_SLOT = 3
LEAGUE_SNAPSHOT = 4
SUITE = 5

_U64 = np.uint64


def splitmix64(x):
    """The splitmix64 finalizer of x + 0x9E3779B97F4A7C15 (uint64 arrays)."""
    with np.errstate(over="ignore"):
        z = np.asarray(x, dtype=_U64) + _U64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> _U64(30))) * _U64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> _U64(27))) * _U64(0x94D049BB133111EB)
        return z ^ (z >> _U64(31))


def draw(seed, tag, a, b):
    """uint64 draws for arrays a and b (e.g. environments and episodes)."""
    with np.errstate(over="ignore"):
        head = splitmix64(_U64(int(seed) & 0xFFFFFFFFFFFFFFFF) + _U64(tag))
        return splitmix64(splitmix64(head + np.asarray(a).astype(_U64)) + np.asarray(b).astype(_U64))


def pick(u, weights):
    """The indices that draws u select under weights (inverse cumulative)."""
    w = np.asarray(weights, dtype=np.float64)
    cum = np.cumsum(w) / w.sum()
    x = (np.asarray(u, dtype=_U64) >> _U64(11)).astype(np.float64) / float(1 << 53)
    return np.minimum(np.searchsorted(cum, x, side="right"), len(w) - 1).astype(np.int64)


def pairings(seed, envs, episodes, weights):
    """(side-0 team, side-1 team) of environments envs in episodes."""
    return (pick(draw(seed, PAIR_SIDE0, envs, episodes), weights),
            pick(draw(seed, PAIR_SIDE1, envs, episodes), weights))
