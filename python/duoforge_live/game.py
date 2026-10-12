"""One battle's decisions, without IO: the tracker, the options and the policy.

feed() takes every message of the battle room. At a decision point where the
player is asked, candidates() ranks the choices as Showdown text, best first:
team tuples by the team head, pairs by the pair head over the provisional
mask (Showdown judges a pair; the client sends the next one after a
rejection). accepted() tells the tracker which choice Showdown took.

With a LiveSearch (--search honest) the search's pair goes first and the raw ranking follows it; the team preview
stays raw (its public record is shown to the search). A decision the search refuses is raw (search.Outcome names the
class); after a class (b) error the game is dirty and the rest of it is raw.
"""
from collections import Counter
from dataclasses import dataclass
from itertools import permutations

from duoforge import features

from . import options, search as live_search
from .tracker import Tracker

# The team head's actions: the ordered 4-of-6 tuples in lexicographic order (duoforge_learn.selfplay.TEAM_TABLE,
# without importing the learner's batch runtime).
TEAM_TABLE = list(permutations(range(6), 4))


@dataclass(frozen=True)
class Candidate:
    text: str
    probability: float


def check_tables(data, policy):
    """A network that reads view-extension record features needs the POOL tables: under the closure kind the
    tracker's extension record is revision 0 and the encoder would treat the records as absent, in silence."""
    if getattr(policy, "ext_supported", 0) & features.RECORD_FEATURES and data.kind != "pool":
        raise ValueError(f"the network reads view-extension records (ext_supported {policy.ext_supported:#x}); "
                         f"they need the pool tables, not {data.kind!r}")


class Game:
    def __init__(self, data, policy, own_text, search=None, room="", episode=0):
        check_tables(data, policy)
        self.tracker = Tracker(data, own_text)
        self.policy = policy
        self.search, self.room, self.episode = search, room, episode
        self.dirty = None  # the class (b) reason: the rest of the game is raw
        self.last_raw = []  # the raw ranking of the last decision point
        self.outcomes = []  # one search.Outcome per decision point played with a search

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

    def candidates(self, budget=live_search.DEADLINE_CAP):
        """The choices of the current decision point, best first (budget: the search's seconds)."""
        observation = self.tracker.observation()
        domain, lists = self.tracker.domain()
        obs_part, slot_part, pair_mask = features.encode(observation, domain, self.tracker.observation_ext(),
                                                         getattr(self.policy, "ext_supported", 0))
        if self.request.get("teamPreview"):
            if len(self.tracker.own_sheets) != 6 or self.request["maxChosenTeamSize"] != 4:
                raise ValueError("the team head knows only six members, four brought")
            self.last_raw = [Candidate(options.team_text(TEAM_TABLE[i]), p)
                             for i, p in self.policy.rank_teams(observation, obs_part)]
            self._search(obs_part, None, None, budget)
            return list(self.last_raw)
        ranked = self.policy.rank_pairs(observation, obs_part, slot_part, pair_mask)
        self.last_raw = [Candidate(options.pair_text(lists[0][i], lists[1][j]), p) for i, j, p in ranked]
        outcome = self._search(obs_part, slot_part, pair_mask, budget)
        if outcome is None or outcome.action is None:
            return list(self.last_raw)
        n = pair_mask.shape[1]
        i, j = divmod(outcome.action, n)
        best = next((c for (a, b, _), c in zip(ranked, self.last_raw) if (a, b) == (i, j)), None)
        if best is None:  # the search played a pair the raw mask does not allow: class (b)
            self.outcomes[-1] = live_search.Outcome(None, "error", "b", f"searched pair {(i, j)} is not allowed",
                                                    outcome.seconds)
            self.dirty = self.outcomes[-1].reason
            return list(self.last_raw)
        return [best] + [c for c in self.last_raw if c is not best]

    def _search(self, obs_part, slot_part, pair_mask, budget):
        if self.search is None:
            return None
        if self.dirty is not None:
            outcome = live_search.Outcome(None, "dirty", None, None, 0.0)
        else:
            try:
                outcome = self.search.decide(self.tracker.public_parts(), obs_part, slot_part, pair_mask,
                                             key=live_search.decision_key(self.room, self.epoch),
                                             episode=self.episode, budget=budget)
            except Exception as err:  # class (b): a failure outside the search (the parts, the roots)
                outcome = live_search.Outcome(None, "error", "b", f"{type(err).__name__}: {err}", 0.0)
            if outcome.fallback == "b":
                self.dirty = outcome.reason
        self.outcomes.append(outcome)
        return outcome

    def summary(self):
        """The counts of the game's search outcomes (the private log's per-game summary)."""
        return {"decisions": len(self.outcomes), "causes": dict(Counter(o.cause for o in self.outcomes)),
                "fallback": dict(Counter(o.fallback for o in self.outcomes if o.fallback is not None)),
                "seconds_max": max((o.seconds for o in self.outcomes), default=0.0), "dirty": self.dirty,
                "spread_fallback": sum(1 for o in self.outcomes if o.spread_fallback),
                "spread_redrawn": sum(1 for o in self.outcomes if o.spread_redrawn)}

    def accepted(self, text):
        self.tracker.accepted(text)
