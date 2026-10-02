"""One battle's decisions, without IO: the tracker, the options and the policy.

feed() takes every message of the battle room. At a decision point where the
player is asked, candidates() ranks the choices as Showdown text, best first:
team tuples by the team head, pairs by the pair head over the provisional
mask (Showdown judges a pair; the client sends the next one after a
rejection). accepted() tells the tracker which choice Showdown took.
"""
from dataclasses import dataclass
from itertools import permutations

from duoforge import features

from . import options
from .tracker import Tracker

# The team head's actions: the ordered 4-of-6 tuples in lexicographic order (duoforge_learn.selfplay.TEAM_TABLE,
# without importing the learner's batch runtime).
TEAM_TABLE = list(permutations(range(6), 4))


@dataclass(frozen=True)
class Candidate:
    text: str
    probability: float


class Game:
    def __init__(self, data, policy, own_text):
        self.tracker = Tracker(data, own_text)
        self.policy = policy

    def feed(self, lines):
        self.tracker.feed(lines)

    @property
    def ready(self):
        return self.tracker.ready

    @property
    def request(self):
        return self.tracker.request

    @property
    def epoch(self):
        return self.tracker.epoch

    @property
    def foe_sets(self):
        return self.tracker.foe_sets

    def asked(self):
        """Whether the player must choose at the current decision point."""
        return self.ready and not self.request.get("wait")

    def candidates(self):
        """The choices of the current decision point, best first."""
        observation = self.tracker.observation()
        domain, lists = self.tracker.domain()
        obs_part, slot_part, pair_mask = features.encode(observation, domain)
        if self.request.get("teamPreview"):
            if len(self.tracker.own_sheets) != 6 or self.request["maxChosenTeamSize"] != 4:
                raise ValueError("the team head knows only six members, four brought")
            return [Candidate(options.team_text(TEAM_TABLE[i]), p)
                    for i, p in self.policy.rank_teams(observation, obs_part)]
        return [Candidate(options.pair_text(lists[0][i], lists[1][j]), p)
                for i, j, p in self.policy.rank_pairs(observation, obs_part, slot_part, pair_mask)]

    def accepted(self, text):
        self.tracker.accepted(text)
