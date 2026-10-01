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
    """The policy's inputs for every seat of every environment."""

    def __init__(self, batch):
        e = batch.envs
        obs, slots, mask = features.encode_batch(batch.observations.reshape(-1), batch.domains.reshape(-1))
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
    """A batch whose environments restart when their episode ends."""

    def __init__(self, envs, workers, seed, pairings=None):
        self.context = duoforge.Context()
        setups = duoforge.reference_setups(pairings if pairings is not None else [e % 4 for e in range(envs)])
        self.batch = duoforge.Batch(self.context, setups, workers, seed)
        self._choices = np.zeros((envs, 2), dtype=_layout.FACTORED_CHOICE)
        self.batch.query_factored()

    def observe(self):
        return Observation(self.batch)

    def step(self, actions):
        """Plays one batch step; returns (rewards (E,2) float32, done (E,)
        bool): an environment whose episode ended has its seats' rewards and
        starts its next episode."""
        b = self.batch
        choices_of(b, actions, self._choices)
        b.step_factored(self._choices)
        done = b.results["boundary_kind"] == TERMINAL
        rewards = np.zeros((b.envs, 2), dtype=np.float32)
        for e in np.flatnonzero(done):
            rewards[e] = _REWARDS[b.result(e)]
        if done.any():
            b.reset_terminal()
        b.query_factored()
        return rewards, done

    def close(self):
        self.batch.close()
        self.context.close()
