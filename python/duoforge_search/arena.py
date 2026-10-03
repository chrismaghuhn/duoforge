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
    choices, step, seats, last_step) gives the candidate index of the
    searched action of its seat in every game where that seat is requested,
    NO_CHOICE elsewhere, as Player.indices does.

    Decision keys: seeds.decision_keys(arena_seed, env, its episode, the
    root's request epoch, seat). At play_suite's last step (last_step) the
    leaves are scored by the tiebreak, as play_suite scores a game it cuts
    off (spec section 5.3).

    records: the lookahead's records of every game row (environment), each
    with its step. They accumulate over play_suite calls: a SearchPlayer
    (or clear()) per suite. Every leaf is valued from the searcher's side,
    a refused leaf -1 as the refused game is the learner's loss: the
    searcher plays as the learner (spec section 8.2). As the opponent its
    refused leaves still count -1 for itself, while play_suite counts a
    refused game as the learner's loss."""

    def __init__(self, lookahead, name, arena_seed):
        self.lookahead, self.name = lookahead, name
        self.arena_seed = int(arena_seed)
        self.records = {}

    def clear(self):
        """Forgets the records (a new suite)."""
        self.records = {}

    def indices(self, batch, choices, step=None, seats=None, last_step=None):
        if step is None or seats is None or last_step is None:
            raise ValueError("a SearchPlayer needs the arena's step, its seats and the last-step flag "
                             "(evaluate.play_suite passes them)")
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
        actions, records = self.lookahead.decide(batch, e, p, keys, np.full(e.size, bool(last_step)))
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
