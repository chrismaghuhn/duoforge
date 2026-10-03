"""The search in the arena (spec section 8, plan task 10).

SearchPlayer plays evaluate.play_suite's games with a Lookahead, on the
arena's true state: an oracle benchmark (ARCHITECTURE section 10). It has
the Player interface; play_suite passes it the step and its seat in every
game.
"""
import numpy as np

import duoforge
from duoforge import _layout
from duoforge_learn.selfplay import choices_of

from . import seeds


class SearchPlayer:
    """A Lookahead as a player of evaluate.play_suite: indices(batch,
    choices, step, seats) gives the candidate index of the searched action
    of its seat in every game where that seat is requested, NO_CHOICE
    elsewhere, as Player.indices does.

    Decision keys: seeds.decision_keys(arena_seed, env, its episode, the
    root's request epoch, seat). A decision at step max_steps - 1 is the
    arena's last: its leaves are scored by the tiebreak, as play_suite
    scores the game (spec section 5.3). records: the lookahead's records
    of every game row (environment), each with its step."""

    def __init__(self, lookahead, name, arena_seed, max_steps):
        if int(max_steps) < 1:
            raise ValueError(f"max_steps must be at least 1 (got {max_steps})")
        self.lookahead, self.name = lookahead, name
        self.arena_seed, self.max_steps = int(arena_seed), int(max_steps)
        self.records = {}

    def indices(self, batch, choices, step=None, seats=None):
        if step is None or seats is None:
            raise ValueError("a SearchPlayer needs the arena's step and its seats (evaluate.play_suite passes them)")
        envs = batch.envs
        seats = np.asarray(seats)
        if seats.shape != (envs,) or not np.isin(seats, (-1, 0, 1)).all():
            raise ValueError(f"seats must hold 0, 1 or -1 for each of the {envs} games")
        seats = seats.astype(np.int64)
        every = np.arange(envs)
        out = np.full((envs, 2), _layout.NO_CHOICE, dtype=np.uint16)
        playing = every[seats >= 0]
        asked = playing[batch.requests["requested"][playing, seats[playing]] != 0]
        if asked.size == 0:
            return out
        e, p = asked, seats[asked]
        keys = seeds.decision_keys(self.arena_seed, e, [batch.episode(int(x)) for x in e],
                                   batch.requests["epoch"][e, p], p)
        actions, records = self.lookahead.decide(batch, e, p, keys, np.full(e.size, step == self.max_steps - 1))
        for r in records:
            r["step"] = int(step)
            self.records.setdefault(r["env"], []).append(r)
        full = np.zeros((envs, 2), dtype=np.int64)
        full[e, p] = actions
        choices_of(batch, full, choices)
        mine = np.zeros((envs, 2), dtype=bool)
        mine[e, p] = True
        out[mine] = duoforge.joint_indices(batch.domains[mine], choices[mine])
        return out
