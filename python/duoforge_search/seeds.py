"""Decision keys and play draws of the search (decision 0022 section 2),
vectorized over uint64 with duoforge_learn.pairing's splitmix64.

    key = splitmix64(splitmix64(draw(arena_seed, KEY_TAG, env, episode) + epoch) + seat)
    u   = (splitmix64(splitmix64(seed + PLAY_TAG) + key) >> 11) * 2^-53

The key names one decision of an arena game (its root's request epoch and
the deciding seat); the engine derives every leaf's seeds from (search
seed, key, sample) by duoforge_search_seeds, and u is the uniform number
the Nash rule plays its mixed strategy with. Pure functions: an input's
output never depends on the other inputs or their order.
"""
import numpy as np

from duoforge_learn.pairing import draw, splitmix64

KEY_TAG = 0x2201
PLAY_TAG = 0x504C415900000001  # "PLAY"
_U64 = np.uint64
_MASK = 0xFFFFFFFFFFFFFFFF


def _u64(name, values):
    arr = np.asarray(values)
    if not np.issubdtype(arr.dtype, np.integer):
        raise ValueError(f"{name} must be integers (got dtype {arr.dtype})")
    if arr.dtype.kind == "i" and (arr < 0).any():
        raise ValueError(f"{name} must be nonnegative")
    return arr.astype(_U64)


def decision_keys(arena_seed, envs, episodes, epochs, seats):
    """The uint64 decision keys of arrays envs, episodes, epochs and seats
    (broadcast together)."""
    seats = _u64("seats", seats)
    if (seats > 1).any():
        raise ValueError("a seat is 0 or 1")
    base = draw(arena_seed, KEY_TAG, _u64("envs", envs), _u64("episodes", episodes))
    with np.errstate(over="ignore"):
        return splitmix64(splitmix64(base + _u64("epochs", epochs)) + seats)


def play_uniforms(seed, keys):
    """The play draws in [0, 1), 53 bits each, of an array of decision keys."""
    with np.errstate(over="ignore"):
        head = splitmix64(_U64(int(seed) & _MASK) + _U64(PLAY_TAG))
        h = splitmix64(head + _u64("keys", keys))
    return (h >> _U64(11)).astype(np.float64) * 2.0 ** -53
