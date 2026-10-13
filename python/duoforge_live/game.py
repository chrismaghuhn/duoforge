"""One battle's decisions, without IO: the tracker, the options and the policy.

feed() takes every message of the battle room. At a decision point where the
player is asked, candidates() ranks the choices as Showdown text, best first:
team tuples by the team head, pairs by the pair head over the provisional
mask (Showdown judges a pair; the client sends the next one after a
rejection). accepted() tells the tracker which choice Showdown took.

With a LiveSearch (--search honest) the search's pair goes first and the raw ranking follows it; the team preview
stays raw (its public record is shown to the search). A decision the search refuses is raw (search.Outcome names the
class); after a class (b) error the game is dirty and the rest of it is raw.

Under closed team sheets (Game.closed_sheets, decision 0081) the tracker is a cts.ParticleTracker: each particle shows
its own observation and public record. The raw ranking is the mean of the policy's probabilities over the particles'
observations (each particle weighs 1/n, as each world of the search), ties to the lower index; the search builds world
w from particle w's record (LiveSearch.decide's worlds).
"""
from collections import Counter
from dataclasses import dataclass
from itertools import permutations

import numpy as np

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


def mean_ranking(rankings, key):
    """[(choice, probability)] of the mean of rankings ([(choice, probability)] each, one per particle), best first,
    equal means to the lower key(choice); a choice missing from a ranking has probability 0 there."""
    total = {}
    for ranking in rankings:
        for choice, p in ranking:
            total[choice] = total.get(choice, 0.0) + float(p)
    n = len(rankings)
    return sorted(((c, t / n) for c, t in total.items()), key=lambda cp: (-cp[1], key(cp[0])))


class Game:
    def __init__(self, data, policy, own_text, search=None, room="", episode=0, tracker=None):
        check_tables(data, policy)
        self.tracker = Tracker(data, own_text) if tracker is None else tracker
        self.closed = callable(getattr(self.tracker, "observations", None))  # a cts.ParticleTracker
        self.policy = policy
        self.search, self.room, self.episode = search, room, episode
        self.dirty = None  # the class (b) reason: the rest of the game is raw
        self.last_raw = []  # the raw ranking of the last decision point
        self.outcomes = []  # one search.Outcome per decision point played with a search

    @classmethod
    def closed_sheets(cls, data, policy, own_text, prior, search=None, room="", episode=0, seed=None, n=None):
        """The game of a closed-sheet battle: its particles (cts.ParticleTracker) drawn from prior under seed and the
        room as the key (cts.SEED, cts.PARTICLES unless given)."""
        from . import cts
        tracker = cts.ParticleTracker(data, own_text, prior, cts.SEED if seed is None else seed, room,
                                      cts.PARTICLES if n is None else n)
        return cls(data, policy, own_text, search=search, room=room, episode=episode, tracker=tracker)

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
        return None if self.closed else self.tracker.foe_sets

    def asked(self):
        """Whether the player must choose at the current decision point."""
        return self.ready and not self.request.get("wait")

    def candidates(self, budget=live_search.DEADLINE_CAP):
        """The choices of the current decision point, best first (budget: the search's seconds)."""
        domain, lists = self.tracker.domain()
        ext_supported = getattr(self.policy, "ext_supported", 0)
        if self.closed:  # one observation per particle (module docstring)
            views = list(zip(self.tracker.observations(), self.tracker.observation_exts()))
        else:
            views = [(self.tracker.observation(), self.tracker.observation_ext())]
        encoded = [features.encode(observation, domain, ext, ext_supported) for observation, ext in views]
        observations = [observation for observation, _ in views]
        obs_parts = [e[0] for e in encoded]
        slot_parts = [e[1] for e in encoded]
        pair_mask = encoded[0][2]  # the own side's domain: the same in every particle
        if any(not np.array_equal(e[2], pair_mask) for e in encoded):
            raise ValueError("the particles disagree on the own pair mask")
        if self.request.get("teamPreview"):
            if len(self.own_sheets) != 6 or self.request["maxChosenTeamSize"] != 4:
                raise ValueError("the team head knows only six members, four brought")
            ranked = mean_ranking([self.policy.rank_teams(o, op) for o, op in zip(observations, obs_parts)],
                                  key=int) if self.closed else self.policy.rank_teams(observations[0], obs_parts[0])
            self.last_raw = [Candidate(options.team_text(TEAM_TABLE[i]), p) for i, p in ranked]
            self._search(obs_parts, None, None, budget)
            return list(self.last_raw)
        n = pair_mask.shape[1]
        if self.closed:
            ranked = [(i, j, p) for (i, j), p in mean_ranking(
                [[((i, j), p) for i, j, p in self.policy.rank_pairs(o, op, sp, pair_mask)]
                 for o, op, sp in zip(observations, obs_parts, slot_parts)], key=lambda ij: ij[0] * n + ij[1])]
        else:
            ranked = self.policy.rank_pairs(observations[0], obs_parts[0], slot_parts[0], pair_mask)
        self.last_raw = [Candidate(options.pair_text(lists[0][i], lists[1][j]), p) for i, j, p in ranked]
        outcome = self._search(obs_parts, slot_parts, pair_mask, budget)
        if outcome is None or outcome.action is None:
            return list(self.last_raw)
        i, j = divmod(outcome.action, n)
        best = next((c for (a, b, _), c in zip(ranked, self.last_raw) if (a, b) == (i, j)), None)
        if best is None:  # the search played a pair the raw mask does not allow: class (b)
            self.outcomes[-1] = live_search.Outcome(None, "error", "b", f"searched pair {(i, j)} is not allowed",
                                                    outcome.seconds)
            self.dirty = self.outcomes[-1].reason
            return list(self.last_raw)
        return [best] + [c for c in self.last_raw if c is not best]

    @property
    def own_sheets(self):
        return (self.tracker.particles[0].tracker if self.closed else self.tracker).own_sheets

    def _search(self, obs_parts, slot_parts, pair_mask, budget):
        """The search's outcome over the parts of the decision point: obs_parts and slot_parts one per particle
        (closed sheets: world w is particle w, with its own records of every decision point) or the one of open
        sheets; slot_parts None at team preview."""
        if self.search is None:
            return None
        if self.dirty is not None:
            outcome = live_search.Outcome(None, "dirty", None, None, 0.0)
        else:
            try:
                slots = [None] * len(obs_parts) if slot_parts is None else slot_parts
                worlds = None
                if self.closed:
                    worlds = list(zip(self.tracker.public_parts(), obs_parts, slots, self.tracker.histories()))
                    parts = worlds[0][0]
                else:
                    parts = self.tracker.public_parts()
                outcome = self.search.decide(parts, obs_parts[0], slots[0], pair_mask,
                                             key=live_search.decision_key(self.room, self.epoch),
                                             episode=self.episode, budget=budget,
                                             **({} if worlds is None else {"worlds": worlds}))
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
