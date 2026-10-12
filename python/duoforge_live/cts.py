"""Closed team sheets: the particle tracker (decision 0081).

Under closed team sheets no |showteam| line comes: a player sees the foe's species and genders at team preview, then
what the log reveals. ParticleTracker holds n particles, each one complete hypothesis of the foe's six sets, drawn from a
SetPrior under the facts of the lines received so far (duoforge_replay.facts.side_facts of the prefix, never of the
whole game). Each particle owns an ordinary open-sheet Tracker. It receives the stream as received, and right after the
team-preview request two synthesized |showteam| lines (the own paste's, the particle's drawn sets), where open sheets
put the real ones. So every particle gives an observation and a public record as under open sheets, and no battle rule
moves into Python.

A particle the log contradicts is replaced by a fresh draw under the current facts, folded again from the start of the
stream. A contradiction is:
- facts: a used move, a revealed item or ability its sets do not have;
- the fold's hook (Tracker.check_foe_sheet): move-not-on-set, choice-lock;
- at a decision point, the engine refusing the particle's record (public_parts raises: a Damp Rock's weather lasting past
  the 5 turns of a drawn set without it);
- the fold raising (a lines.Stop or a ValueError) in some particles but not in all: the drawn sets disagree with a line
  the other particles fold (an ability the line names, a Pressure the own PP do not show). When every particle that
  folded the line raises the same, or UNIFORM redraws in a row do, the line is no contradiction: the tracker raises it,
  as an open-sheet tracker would.
A draw that breaks the Item Clause is drawn again without a fold (MAX_DRAWS draws). Every redraw is counted by its reason
(counters); MAX_ATTEMPTS contradicted folds of one particle in a row stop the tracker with "cts:redraw-cap <reason>". No
set agreeing with a member's facts stops it with "cts:no-consistent-set <species>", facts the log cannot give with
"cts:facts <skip>".

The draw of member m of particle i at its attempt a takes the word of (seed, key, foe side, m, a, i), as the replay's set
belief (setbelief.word): the same stream, seed and key give the same particles.
"""
import collections
import copy
import json

from duoforge_replay import facts as _facts
from duoforge_replay.points import Skip
from duoforge_replay.setbelief import _pick, word  # noqa: F401  (word is part of this module's contract)

from . import lines, teams
from .data import trace_to_c
from .tracker import SheetContradiction, Tracker

PARTICLES = 16  # one per world of the live search (HONEST_SETTINGS s)
MAX_ATTEMPTS = 64  # contradicted draws of one particle in a row, each a fold from the start
MAX_DRAWS = 4096  # draws of one attempt that break the Item Clause (no fold: a draw is cheap)
UNIFORM = 8  # attempts in a row that raise the same: the line, not the drawn sets, is the cause
LEVEL = 50  # the format's level; the open sheets show it, and no stat points
_key = trace_to_c.key


def _species_key(data, name):
    return _key(data.canonical(name))


class SetPrior:
    """Whole sets per species with integer weights: `sets` holds set dicts (teams.unpack's shape: species, item,
    ability, moves, nature; weight 1) or (set, weight) pairs. Every set must be one the engine's setup accepts (a
    ValueError names the first that is not): a drawn team is always a legal one."""

    def __init__(self, data, sets):
        self._sets = collections.defaultdict(list)
        for entry in sets:
            s, weight = entry if isinstance(entry, tuple) else (entry, 1)
            if not isinstance(weight, int) or isinstance(weight, bool) or weight < 0:
                raise ValueError(f"a set weight must be a whole number >= 0: {weight!r}")
            s = {"species": s["species"], "item": s["item"], "ability": s["ability"], "moves": list(s["moves"]),
                 "nature": s["nature"]}
            # the legality of the set, under a gender the species may have (the preview gives the drawn member's own)
            rule = data.tables["GENDER_RULE"][data.forme(s["species"])]
            gender = {trace_to_c.GENDER["F"]: "F", trace_to_c.GENDERLESS: ""}.get(rule, "M")
            member = data.team(teams.to_text([_sheet(s, gender)]))[0]
            issue = data.setup_issue(member)
            if issue is not None:
                raise ValueError(f"a set the engine refuses ({issue[0]}): {s}")
            self._sets[_species_key(data, s["species"])].append((s, weight))
        self.data = data

    def candidates(self, species):
        """The (set, weight) pairs of a species (a preview name), [] for a species the prior lacks."""
        try:
            return self._sets.get(_species_key(self.data, species), [])
        except ValueError:
            return []


def _sheet(s, gender):
    """A set as the open sheets show it: level 50, no stat points, the preview's gender."""
    return {"name": s["species"], "species": s["species"], "item": s["item"], "ability": s["ability"],
            "moves": list(s["moves"]), "nature": s["nature"], "evs": [0] * 6, "gender": gender, "level": LEVEL}


def agrees(s, member):
    """Whether set s agrees with a member's facts (facts.MemberFacts): its used moves are among the set's, and a
    revealed item and ability are the set's."""
    return ((member.item is None or _key(s["item"]) == _key(member.item))
            and (member.ability is None or _key(s["ability"]) == _key(member.ability))
            and {_key(m) for m in member.moves} <= {_key(m) for m in s["moves"]})


class Particle:
    def __init__(self, sets, tracker):
        self.sets, self.tracker = sets, tracker
        self.view = None  # (epoch, public parts, observation) of its last decision point


def _preview_side(line):
    """The own side of a team-preview request line, else None."""
    if not line.startswith("|request|"):
        return None
    request = json.loads(line[len("|request|"):])
    if not request.get("teamPreview"):
        return None
    return int(request["side"]["id"][1]) - 1


class ParticleTracker:
    """A closed-sheet battle room as one player sees it (module docstring). feed() and accepted() as Tracker's; at a
    decision point (ready) public_parts() and observations() give one entry per particle, domain() the own options."""

    def __init__(self, data, own_text, prior, seed, key, n=PARTICLES, record_kind=None):
        if n < 1:
            raise ValueError("a particle tracker needs at least one particle")
        self.data, self.own_text, self.prior = data, own_text, prior
        self.seed, self.key, self.n, self.record_kind = int(seed), str(key), int(n), record_kind
        self.side = None
        self.particles = None  # from the team-preview request on
        self.counters = collections.Counter()
        self._events = []  # ("lines", [...]), ("sheets", None) and ("accepted", text), in the order received
        self._attempts = [0] * self.n

    # ------------------------------------------------------------------ input
    def feed(self, received):
        received = list(received)
        if self.particles is not None:
            self._advance(received)
            return
        for i, line in enumerate(received):
            side = _preview_side(line)
            if side is not None:
                self.side = side
                self._events += [("lines", received[:i + 1]), ("sheets", None)]
                facts = self._facts()
                self.particles = [self._redraw(p, facts, None, 0) for p in range(self.n)]
                if received[i + 1:]:
                    self._advance(received[i + 1:])
                return
        self._events.append(("lines", received))

    def accepted(self, text):
        self._events.append(("accepted", text))
        for p in self.particles:
            p.tracker.accepted(text)

    # ------------------------------------------------------------------ the decision point
    @property
    def ready(self):
        return self.particles is not None and self.particles[0].tracker.ready

    @property
    def request(self):
        return None if self.particles is None else self.particles[0].tracker.request

    @property
    def epoch(self):
        return 0 if self.particles is None else self.particles[0].tracker.epoch

    @property
    def ended(self):
        return self.particles is not None and self.particles[0].tracker.ended

    def domain(self):
        """The own decision point's domain and slot lists: the own side's, the same in every particle."""
        return self.particles[0].tracker.domain()

    def public_parts(self):
        """Tracker.public_parts of every particle at the decision point, in particle order (world w of the search is
        particle w). They are taken when the decision point's request is folded, before accepted()."""
        return [view[1] for view in self._views()]

    def observations(self):
        return [view[2] for view in self._views()]

    def _views(self):
        views = [p.view for p in self.particles or ()]
        if not self.ready or any(v is None or v[0] != self.epoch for v in views):
            raise ValueError("no decision point: the particles' parts are taken when its request is folded")
        return views

    # ------------------------------------------------------------------ particles
    def _lines(self):
        return [line for kind, payload in self._events if kind == "lines" for line in payload]

    def _facts(self):
        """The foe members' facts of the lines received so far (never later ones)."""
        try:
            return _facts.side_facts(self._lines(), 1 - self.side, self.data)
        except Skip as skip:
            raise lines.Stop(f"cts:facts {skip.reason}") from None

    @staticmethod
    def _outcome(call):
        """None when call() returns, else (reason, the exception, None for a SheetContradiction)."""
        try:
            call()
            return None
        except SheetContradiction as c:
            return c.reason, None
        except lines.Stop as stop:
            return f"stop:{stop.reason}", stop
        except ValueError as err:
            return f"error:{type(err).__name__}", err

    @staticmethod
    def _view(p):
        """Takes the particle's parts at its decision point: the engine's check of its record (public_parts) and its
        observation. A record the engine refuses (a Damp Rock's weather lasting past a drawn set's 5 turns) raises."""
        p.view = (p.tracker.epoch, p.tracker.public_parts(), p.tracker.observation())

    def _advance(self, received):
        self._events.append(("lines", received))
        facts = self._facts()
        epoch = self.epoch
        failed, folded = {}, 0
        for i, p in enumerate(self.particles):
            if not all(agrees(s, f) for s, f in zip(p.sets, facts)):
                failed[i] = ("facts", None)
                continue
            folded += 1

            def step(p=p):
                p.tracker.feed(received)
                if p.tracker.ready and p.tracker.epoch > epoch:
                    self._view(p)
            out = self._outcome(step)
            if out is not None:
                failed[i] = out
        raised = [e for _, e in failed.values() if e is not None]
        if folded and len(raised) == folded and len({(type(e), str(e)) for e in raised}) == 1:
            raise raised[0]  # every particle that folded the line stops at it: no particle's sets are the cause
        for i, (reason, _) in sorted(failed.items()):
            self.particles[i] = self._redraw(i, facts, reason, epoch)

    def _redraw(self, i, facts, reason, epoch):
        """Particle i drawn anew under `facts` and folded from the start (reason: why, None for the first draw). A
        decision point past `epoch` (the one before the last batch) has its view taken and checked."""
        if reason is not None:
            self.counters[f"redraw.{reason}"] += 1
        candidates = []
        for member in facts:
            found = [(s, w) for s, w in self.prior.candidates(member.species) if w > 0 and agrees(s, member)]
            if not found:
                raise lines.Stop(f"cts:no-consistent-set {member.species}")
            candidates.append(found)
        last, streak = reason, []
        for _ in range(MAX_ATTEMPTS):
            p = Particle(self._draw(i, candidates, facts), None)

            def fold(p=p):
                p.tracker = self._fold(p.sets)
                if p.tracker.ready and p.tracker.epoch > epoch:
                    self._view(p)
            out = self._outcome(fold)
            if out is None:
                return p
            last, error = out
            self.counters[f"redraw.{last}"] += 1
            if error is None or (streak and (type(streak[0]), str(streak[0])) != (type(error), str(error))):
                streak = []
            if error is not None:
                streak.append(error)
            if len(streak) == UNIFORM:
                raise streak[0]  # every draw stops at the same line: the line, not the sets, is the cause
        raise lines.Stop(f"cts:redraw-cap {last}")

    def _draw(self, i, candidates, facts):
        """The particle's next sets under the Item Clause: MAX_DRAWS draws that break it stop the tracker."""
        for _ in range(MAX_DRAWS):
            attempt = self._attempts[i]
            self._attempts[i] += 1
            sets = [_sheet(copy.deepcopy(found[_pick(word(self.seed, self.key, 1 - self.side, m, attempt, i),
                                                     [w for _, w in found])][0]), member.gender)
                    for m, (found, member) in enumerate(zip(candidates, facts))]
            items = [_key(s["item"]) for s in sets if s["item"]]
            if len(items) == len(set(items)):
                return sets
            self.counters["redraw.item-clause"] += 1
        raise lines.Stop("cts:redraw-cap item-clause")

    def _fold(self, sets):
        """A tracker that folded every event so far with `sets` as the foe's sheet."""
        t = Tracker(self.data, self.own_text)
        t.check_foe_sheet = True
        t.record_kind = self.record_kind
        own = teams.pack(self.own_text)
        foe = teams.pack(teams.to_text(sets))
        for kind, payload in self._events:
            if kind == "lines":
                t.feed(payload)
            elif kind == "sheets":
                t.feed([f"|showteam|p{s + 1}|" + (own if s == self.side else foe) for s in (0, 1)])
            else:
                t.accepted(payload)
        return t
