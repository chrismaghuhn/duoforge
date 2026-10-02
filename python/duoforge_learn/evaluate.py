"""Win rates of a policy against the baselines (decision 0014 section 6).

Every environment plays fixed-seed episodes: the pairing cycles with the
environment (e % 4) and the learner's seat with e // 4 % 2, so both seats
of all four pairings are covered. The learner plays its most likely
action; the opponent is the random or the scripted baseline, or another
set of parameters (an earlier checkpoint), which also plays its most likely
action. A tie counts half. The engine has no turn limit, and two policies
that only switch never end a battle: an episode still running after
max_steps steps counts as a tie and is reported as unfinished. Each set of
parameters plays on the inputs of its encoder version
(checkpoint.encoder_of, features.as_encoder).
"""
import numpy as np

import duoforge
from duoforge import _layout, features

from .selfplay import Observation, choices_of

C = _layout.CONSTANTS
_SIDE_WINS = (C["DUOFORGE_RESULT_SIDE_0"], C["DUOFORGE_RESULT_SIDE_1"])
_TIE = C["DUOFORGE_RESULT_TIE"]


def win_rate(params, act, opponent, envs=64, workers=4, seed=0x2026100200000020, rounds=1, max_steps=1000, *,
             encoder, opponent_encoder=None):
    """{"win_rate", "wins", "losses", "ties", "unfinished", "episodes"} of
    the policy against `opponent` ("random", "scripted" or parameters); act
    is model.act (jitted). envs is a multiple of 8, so both seats of all four
    pairings play equally often. encoder is the encoder version the
    parameters were trained with (checkpoint.encoder_of), opponent_encoder
    the opponent's when it is parameters; no default picks one."""
    if envs <= 0 or envs % 8 != 0:
        raise ValueError(f"envs must be a positive multiple of 8, not {envs}")
    if isinstance(opponent, dict) and opponent_encoder is None:
        raise ValueError("opponent_encoder is required when the opponent is parameters")
    seat = (np.arange(envs) // 4) % 2
    wins = losses = ties = unfinished = 0
    with duoforge.Context() as ctx:
        setups = duoforge.reference_setups([e % 4 for e in range(envs)])
        with duoforge.Batch(ctx, setups, workers, seed) as batch:
            if isinstance(opponent, dict):
                other = _Snapshot(opponent, act, envs, opponent_encoder)
            elif opponent == "random":
                other = duoforge.RandomPolicy(seed, envs)
            elif opponent == "scripted":
                other = duoforge.ScriptedPolicy()
            else:
                raise ValueError(f"unknown opponent {opponent!r}")
            choices = np.zeros((envs, 2), dtype=_layout.FACTORED_CHOICE)
            rows = np.arange(envs)
            for k in range(1, rounds + 1):
                for e in range(envs):
                    batch.reset(e, k)
                if isinstance(other, duoforge.RandomPolicy):
                    other.start_episodes(rows, np.full(envs, k, dtype=np.uint64))
                for _ in range(max_steps):
                    batch.query()
                    batch.query_factored()
                    requested = batch.requests["requested"] != 0
                    if not requested.any():
                        break
                    indices = other.choose(batch)
                    mine = requested[rows, seat]
                    if mine.any():
                        e = rows[mine]
                        indices[e, seat[mine]] = _greedy_indices(params, act, batch, choices, encoder)[e, seat[mine]]
                    batch.step(indices)
                for e in range(envs):
                    result = batch.result(e)
                    if result == 0:
                        unfinished += 1
                        ties += 1
                    elif result == _TIE:
                        ties += 1
                    elif result == _SIDE_WINS[seat[e]]:
                        wins += 1
                    else:
                        losses += 1
    episodes = wins + losses + ties
    return {"win_rate": (wins + 0.5 * ties) / episodes, "wins": wins, "losses": losses, "ties": ties,
            "unfinished": unfinished, "episodes": episodes}


def _greedy_indices(params, act, batch, choices, encoder):
    """The candidate index of the most likely action of every requested
    seat (E, 2), NO_CHOICE elsewhere, on the inputs of encoder version
    `encoder`."""
    envs = batch.envs
    o = Observation(batch, encoder)
    actions, _, _ = act(params, None, o.obs.reshape(2 * envs, -1), o.slots.reshape((2 * envs,) + o.slots.shape[2:]),
                        o.mask.reshape((2 * envs,) + o.mask.shape[2:]), o.is_team.reshape(-1), greedy=True)
    choices_of(batch, np.asarray(actions).reshape(envs, 2), choices)
    indices = np.full((envs, 2), _layout.NO_CHOICE, dtype=np.uint16)
    requested = batch.requests["requested"] != 0
    if requested.any():
        indices[requested] = duoforge.joint_indices(batch.domains[requested], choices[requested])
    return indices


class _Snapshot:
    """Earlier parameters as an opponent with the baselines' choose()."""

    def __init__(self, params, act, envs, encoder):
        self.params, self.act, self.encoder = params, act, encoder
        self.choices = np.zeros((envs, 2), dtype=_layout.FACTORED_CHOICE)

    def choose(self, batch):
        return _greedy_indices(self.params, self.act, batch, self.choices, self.encoder)
