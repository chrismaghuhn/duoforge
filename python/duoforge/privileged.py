"""Privileged true-state helpers for tests and the oracle, never an honest player."""
import numpy as np

from . import _layout
from ._lib import ptr, status_name, uint
from .errors import DuoforgeError


def hypothesis(batch, env, player):
    """The true hypothesis of one batch environment (PRIVILEGED)."""
    out = np.zeros((), _layout.HYPOTHESIS)
    st = batch._lib.duoforge_battle_hypothesis(batch.context.handle, batch._battle(env),
                                               uint(player, 32, "player"), ptr(out))
    if st:
        raise DuoforgeError(status_name(st))
    return out
