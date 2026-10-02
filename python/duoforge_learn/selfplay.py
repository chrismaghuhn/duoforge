"""Self-play over the batch runtime for the learner (decision 0014).

Every environment's two seats are played by the policy being trained. An
action is a flat pair index i * 32 + j at a SLOTS boundary (the options of
slot lists 0 and 1 of the factored domain) or a tuple index at
TEAM_SELECTION (the lexicographic rank among the ordered 4-of-6 tuples, as
TEAM_TABLE lists them). The engine checks every choice; this module only
translates.
"""
import itertools

import numpy as np

import duoforge
from duoforge import _layout, features

C = _layout.CONSTANTS
SLOTS = C["DUOFORGE_CHOICE_SLOTS"]
TEAM = C["DUOFORGE_CHOICE_TEAM_SELECTION"]
TERMINAL = C["DUOFORGE_BOUNDARY_TERMINAL"]
OPTIONS = _layout.MAX_SLOT_OPTIONS
PAIRS = OPTIONS * OPTIONS

# The certified profile (decision 0010): a roster of 6, 4 brought.
ROSTER, BROUGHT = 6, 4
TEAM_TABLE = np.array(list(itertools.permutations(range(ROSTER), BROUGHT)), dtype=np.uint8)
TEAM_ACTIONS = TEAM_TABLE.shape[0]

# Reward of seat 0 and seat 1 for each DUOFORGE_RESULT_*.
_REWARDS = {C["DUOFORGE_RESULT_SIDE_0"]: (1.0, -1.0), C["DUOFORGE_RESULT_SIDE_1"]: (-1.0, 1.0),
            C["DUOFORGE_RESULT_TIE"]: (0.0, 0.0)}


class Observation:
    """The policy's inputs for every seat of every environment, as encoder
    version `encoder` makes them (features.as_encoder: a network of an older
    version gets the inputs it was trained on). The version is named by the
    caller: self-play trains features.ENCODER."""

    def __init__(self, batch, encoder):
        e = batch.envs
        observations = batch.observations.reshape(-1)
        obs, slots, mask = features.encode_batch(observations, batch.domains.reshape(-1))
        obs = features.as_encoder(obs, observations, encoder)
        self.obs = obs.reshape(e, 2, -1)
        self.slots = slots.reshape(e, 2, 2, OPTIONS, features.SLOT_FEATURES)
        self.mask = mask.reshape(e, 2, OPTIONS, OPTIONS)
        kind = batch.domains["kind"]
        self.acting = batch.requests["requested"] != 0
        self.is_team = kind == TEAM
        team = self.acting & self.is_team
        if team.any() and ((batch.domains["member_count"][team] != ROSTER).any()
                           or (batch.domains["pick_count"][team] != BROUGHT).any()):
            raise ValueError(f"the team head knows only the profile {ROSTER}/{BROUGHT}")


def choices_of(batch, actions, out):
    """Writes the FACTORED_CHOICE of every acting seat for actions (E,2)."""
    acting = batch.requests["requested"] != 0
    kind = batch.domains["kind"]
    out[...] = np.zeros((), dtype=out.dtype)
    slots = acting & (kind == SLOTS)
    out["slot"][..., 0] = np.where(slots, actions // OPTIONS, 0)
    out["slot"][..., 1] = np.where(slots, actions % OPTIONS, 0)
    team = acting & (kind == TEAM)
    out["picks"][..., :BROUGHT] = np.where(team[..., None], TEAM_TABLE[np.where(team, actions, 0)], 0)


class SelfPlay:
    """A batch whose environments restart when their episode ends. The
    engine has no turn limit, and two policies that only switch never end a
    battle, so an episode that reaches max_steps steps is cut off and scored
    as a tie: a training choice, not a battle rule."""

    def __init__(self, envs, workers, seed, pairings=None, max_steps=500):
        self.context = duoforge.Context()
        setups = duoforge.reference_setups(pairings if pairings is not None else [e % 4 for e in range(envs)])
        self.batch = duoforge.Batch(self.context, setups, workers, seed)
        self.max_steps = int(max_steps)
        self._steps = np.zeros(envs, dtype=np.int64)
        self._choices = np.zeros((envs, 2), dtype=_layout.FACTORED_CHOICE)
        self.batch.query_factored()

    def observe(self):
        return Observation(self.batch, features.ENCODER)

    def step(self, actions):
        """Plays one batch step; returns (rewards (E,2) float32, done (E,)
        bool): an environment whose episode ended has its seats' rewards and
        starts its next episode."""
        b = self.batch
        choices_of(b, actions, self._choices)
        b.step_factored(self._choices)
        self._steps += 1
        terminal = b.results["boundary_kind"] == TERMINAL
        rewards = np.zeros((b.envs, 2), dtype=np.float32)
        for e in np.flatnonzero(terminal):
            rewards[e] = _REWARDS[b.result(e)]
        if terminal.any():
            b.reset_terminal()
        cut = ~terminal & (self._steps >= self.max_steps)
        for e in np.flatnonzero(cut):
            b.reset(e, b.episode(e) + 1)  # a tie: both rewards stay 0
        done = terminal | cut
        self._steps[done] = 0
        b.query_factored()
        return rewards, done

    def close(self):
        self.batch.close()
        self.context.close()
