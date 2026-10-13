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
- the fold raising (a lines.Stop or a ValueError): the drawn sets may disagree with the line (an ability the line names,
  a Pressure the own PP do not show), or the line stops every fold (a feature the tracker does not fold). The particle is
  drawn again. Rejection cannot tell the two apart (a set the log needs may be rare in the prior), so MAX_ATTEMPTS
  failed draws stop the tracker by name, "cts:redraw-cap stop:<reason>" or "cts:redraw-cap error:<type>", with the last
  exception as the cause.
A draw that breaks the Item Clause is drawn again without a fold (MAX_DRAWS draws). Every redraw is counted by its reason
(counters); MAX_ATTEMPTS contradicted folds of one particle in a row stop the tracker with "cts:redraw-cap <reason>". No
set agreeing with a member's facts stops it with "cts:no-consistent-set <species>", facts the log cannot give with
"cts:facts <skip>".

The draw of member m of particle i at its attempt a takes the word of (seed, key, foe side, m, a, i), as the replay's set
belief (setbelief.word): the same stream, seed and key give the same particles.
"""
import collections
import json

from duoforge_replay import facts as _facts
from duoforge_replay.points import Skip
from duoforge_replay.setbelief import _pick, word  # noqa: F401  (word is part of this module's contract)

from . import lines, teams
from .data import trace_to_c
from .tracker import SheetContradiction, Tracker

PARTICLES = 16  # one per world of the live search (HONEST_SETTINGS s)
SEED = 0x2026101300000385  # the live draw's seed; the battle room is the key (game.Game.closed_sheets)
MAX_ATTEMPTS = 64  # contradicted draws of one particle in a row, each a fold from the start
MAX_DRAWS = 4096  # draws of one attempt that break the Item Clause (no fold: a draw is cheap)
LEVEL = 50  # the format's level; the open sheets show it, and no stat points
MOVES = 4
_key = trace_to_c.key


def counter_kind(key):
    """A counter's key as an aggregate (the arena's run log): a redraw by a stop keeps the stop's kind only
    (redraw.stop:structure, redraw.stop:cts:...), never the stop's text, which can name a nickname or a line."""
    if not key.startswith("redraw.stop:"):
        return key
    reason = key[len("redraw.stop:"):]
    return "redraw.stop:" + (reason.split(" ")[0] if reason.startswith("cts:") else reason.split(":")[0])


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
            issue = setup_issue(data, s)
            if issue is not None:
                raise ValueError(f"a set the engine refuses ({issue[0]}): {s}")
            self._sets[_species_key(data, s["species"])].append((s, weight))
        self.data = data

    @classmethod
    def from_table(cls, data, path=None, sha256=None):
        """The prior of the committed set table (duoforge_search.smogon_sets): its pinned file (TABLE_SHA256) unless
        path and sha256 name another."""
        from duoforge_search import smogon_sets
        table = smogon_sets.load_table(path or smogon_sets.TABLE_PATH, sha256 or smogon_sets.TABLE_SHA256)
        return cls(data, [({"species": species, "item": item, "ability": ability, "nature": nature, "moves": moves}, n)
                          for species, entry in sorted(table["species"].items())
                          for item, ability, nature, moves, n in entry["sets"]])

    def candidates(self, species):
        """The (set, weight) pairs of a species (a preview name), [] for a species the prior lacks."""
        try:
            return self._sets.get(_species_key(self.data, species), [])
        except ValueError:
            return []


def setup_issue(data, s):
    """data.setup_issue of a set under a gender its species may have (the preview gives a drawn member's own): None
    when the engine's setup accepts it, ("name", None) for a name the tables do not know."""
    try:
        forme = data.forme(s["species"])
    except ValueError:
        return ("name", None)  # a species the tables do not know
    named = [("ITEM", s["item"]), ("NATURE", s["nature"])] + [("MOVE", m) for m in s["moves"]]
    if _key(s["ability"]) != "NOABILITY":
        named.append(("ABILITY", s["ability"]))
    if any(name and _key(name) not in data.tables[table] for table, name in named):
        return ("name", None)  # an item, ability, nature or move the tables do not know
    rule = data.tables["GENDER_RULE"][forme]
    gender = {trace_to_c.GENDER["F"]: "F", trace_to_c.GENDERLESS: ""}.get(rule, "M")
    return data.setup_issue(data.team(teams.to_text([_sheet(s, gender)]))[0])


def _rebuilt(data, sets, member, keep):
    """The sets of `sets` that keep() takes as bases, rebuilt on a member's facts: the revealed item and ability put on,
    the used moves (sorted by name) then the base's own others in its order, up to four; a Choice item's holder gets no
    CHOICE_EXCLUDED move from the base (the set table's rule). A result the engine's setup refuses is left out and
    counted; equal results add their weights. Returns (the sets, how many results were refused)."""
    from duoforge_search.smogon_sets import CHOICE_EXCLUDED, CHOICE_ITEMS
    used = sorted(member.moves)
    if len(used) > MOVES:
        return [], 0
    out, refused = collections.Counter(), 0
    for s, w in sets:
        if w <= 0 or not keep(s):
            continue
        item = s["item"] if member.item is None else member.item
        ability = s["ability"] if member.ability is None else member.ability
        choice = _key(item).lower() in CHOICE_ITEMS
        fill = [m for m in s["moves"] if _key(m) not in {_key(u) for u in used}
                and not (choice and _key(m).lower() in CHOICE_EXCLUDED)]
        candidate = dict(s, item=item, ability=ability, moves=(used + fill)[:MOVES])
        if setup_issue(data, candidate) is None:
            out[json.dumps(candidate, sort_keys=True)] += w
        else:
            refused += 1
    return [(json.loads(k), w) for k, w in sorted(out.items())], refused


def level1(data, sets, member):
    """Level 1 (the replay's set belief, setbelief.SetBelief): when no set agrees with a member's facts, every set that
    agrees on the revealed item and ability is a base for its used moves (_rebuilt): (sets, refused)."""
    return _rebuilt(data, sets, member, lambda s: (member.item is None or _key(s["item"]) == _key(member.item)) and (
        member.ability is None or _key(s["ability"]) == _key(member.ability)))


def level2(data, sets, member):
    """Level 2: when level 1 has no base (an item or ability the prior never pairs with the species), every set of the
    species is a base for the revealed item, ability and used moves (_rebuilt): (sets, refused)."""
    return _rebuilt(data, sets, member, lambda s: True)


def true_sheet(text):
    """A paste's team packed as the open sheets show it (the oracle of #385 step 5): each set in the particles' form
    (_sheet: level 50, no stat points, the paste's gender), as the pinned server's |showteam| line carries it."""
    return teams.pack(teams.to_text([_sheet(s, s.get("gender", "")) for s in teams._paste(text)]))


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
        self.view = None  # (epoch, public parts, observation, extension record) of its last decision point
        self.history = []  # (record, status) of its public parts at each decision point it folded, in order


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
        self._candidates = {}  # (species, item, ability, moves, no Choice) -> its sets: the facts decide them, not the draw
        self._no_choice = set()  # foe members whose original item a contradicted Choice lock shows is no Choice item
        # Before the team-preview request: an open-sheet tracker folds the lines as it would (a battle line before the
        # sheets raises, a battle over before them has ended); the particles fold them again
        self._before = Tracker(data, own_text)

    # ------------------------------------------------------------------ input
    def feed(self, received):
        received = list(received)
        if self.particles is not None:
            self._advance(received)
            return
        for i, line in enumerate(received):
            side = _preview_side(line)
            if side is not None:
                self._before.feed(received[:i + 1])
                self.side = side
                self._events += [("lines", received[:i + 1]), ("sheets", None)]
                facts = self._facts()
                self.particles = [self._redraw(p, facts, None) for p in range(self.n)]
                if received[i + 1:]:
                    self._advance(received[i + 1:])
                return
        self._before.feed(received)
        self._events.append(("lines", received))

    def accepted(self, text):
        if self.particles is None:
            raise ValueError("no team preview yet: no choice can have been accepted")
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
        return self._before.ended if self.particles is None else self.particles[0].tracker.ended

    def domain(self):
        """The own decision point's domain and slot lists: the own side's, the same in every particle."""
        return self.particles[0].tracker.domain()

    def public_parts(self):
        """Tracker.public_parts of every particle at the decision point, in particle order (world w of the search is
        particle w). They are taken when the decision point's request is folded, before accepted()."""
        return [view[1] for view in self._views()]

    def observations(self):
        return [view[2] for view in self._views()]

    def histories(self):
        """Each particle's (record, status) at every decision point so far, the current one last: a particle drawn
        anew brings the records of its own fold (the search's team-preview and turn-start records of world w)."""
        self._views()
        return [list(p.history) for p in self.particles]

    def observation_exts(self):
        """Each particle's OBSERVATION_EXT record (Tracker.observation_ext) of the decision point."""
        return [view[3] for view in self._views()]

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
            raise self._stop(f"cts:facts {skip.reason}") from None

    def _stop(self, reason):
        """The named Stop of a reason, counted by its first word (stop.cts:facts, stop.cts:redraw-cap, ...)."""
        self.counters[f"stop.{reason.split(' ')[0]}"] += 1
        return lines.Stop(reason)

    def _outcome(self, call):
        """None when call() returns, else (reason, the exception, None for a SheetContradiction)."""
        try:
            call()
            return None
        except SheetContradiction as c:
            self._note(c)
            return c.reason, None
        except lines.Stop as stop:
            return f"stop:{stop.reason}", stop
        except ValueError as err:
            return f"error:{type(err).__name__}", err

    @staticmethod
    def _view(t):
        """The tracker's parts at its decision point: the engine's check of its record (public_parts), its
        observation and extension record. A record the engine refuses (a Damp Rock's weather lasting past a drawn
        set's 5 turns) raises."""
        return t.epoch, t.public_parts(), t.observation(), t.observation_ext()

    def _advance(self, received):
        self._events.append(("lines", received))
        facts = self._facts()
        epoch = self.epoch
        failed = {}
        for i, p in enumerate(self.particles):
            if not all(agrees(s, f) for s, f in zip(p.sets, facts)):
                failed[i] = ("facts", None)
                continue

            def step(p=p):
                p.tracker.feed(received)
                if p.tracker.ready and p.tracker.epoch > epoch:
                    p.view = self._view(p.tracker)
                    p.history.append((p.view[1]["record"], p.view[1]["status"]))
            out = self._outcome(step)
            if out is not None:
                failed[i] = out
        for i, (reason, _) in sorted(failed.items()):
            self.particles[i] = self._redraw(i, facts, reason)

    def _redraw(self, i, facts, reason):
        """Particle i drawn anew under `facts` and folded from the start (reason: why, None for the first draw), its
        record checked at every decision point it folds, as a kept particle's was."""
        if reason is not None:
            self.counters[f"redraw.{reason}"] += 1
        candidates = self._all_candidates(facts)
        last, error = reason, None
        for _ in range(MAX_ATTEMPTS):
            p = Particle(self._draw(i, candidates, facts), None)

            def fold(p=p):
                p.tracker, p.view, p.history = self._fold(p.sets)
            out = self._outcome(fold)
            if out is None:
                return p
            last, error = out
            if last == "choice-lock":
                candidates = self._all_candidates(facts)  # the member's Choice sets are out now (_note)
            self.counters[f"redraw.{last}"] += 1
        raise self._stop(f"cts:redraw-cap {last}") from error

    def _note(self, contradiction):
        """A contradicted Choice lock shows that the member's original item is no Choice item: the tracker assumes a
        lock only for an item no line changed, and Showdown enforces the lock (a Klutz holder aside, #448). Every draw
        of that member leaves Choice sets out from now on (counted once per member: choice-excluded)."""
        if contradiction.reason == "choice-lock" and contradiction.member not in self._no_choice:
            self._no_choice.add(contradiction.member)
            self.counters["choice-excluded"] += 1

    def _all_candidates(self, facts):
        """Every member's candidate sets (_candidates_of); a member without any stops the tracker by name."""
        out = []
        for m, member in enumerate(facts):
            found = self._candidates_of(member, m in self._no_choice)
            if not found:
                raise self._stop(f"cts:no-consistent-set {member.species}")
            out.append(found)
        return out

    def _candidates_of(self, member, no_choice=False):
        """The sets a member's facts allow, kept per facts, so the levels' engine checks run once for all particles that
        draw under the same facts. Counted once per distinct facts: level1 or level2 (the level that gave the sets) and
        levels.refused (the rebuilt sets the engine refused). no_choice leaves sets with a Choice item out (_note)."""
        from duoforge_search.smogon_sets import CHOICE_ITEMS
        key = (member.species, member.item, member.ability, member.moves, no_choice)
        if key not in self._candidates:
            sets = self.prior.candidates(member.species)
            if no_choice:
                sets = [(s, w) for s, w in sets if _key(s["item"]).lower() not in CHOICE_ITEMS]
            found = [(s, w) for s, w in sets if w > 0 and agrees(s, member)]
            for name, rebuild in (("level1", level1), ("level2", level2)):
                if not found:
                    found, refused = rebuild(self.data, sets, member)
                    self.counters["levels.refused"] += refused
                    if found:
                        self.counters[name] += 1
            self._candidates[key] = found
        return self._candidates[key]

    def _draw(self, i, candidates, facts):
        """The particle's next sets under the Item Clause: MAX_DRAWS draws that break it stop the tracker."""
        for _ in range(MAX_DRAWS):
            attempt = self._attempts[i]
            self._attempts[i] += 1
            sets = [_sheet(found[_pick(word(self.seed, self.key, 1 - self.side, m, attempt, i),
                                          [w for _, w in found])][0], member.gender)
                    for m, (found, member) in enumerate(zip(candidates, facts))]
            items = [_key(s["item"]) for s in sets if s["item"]]
            if len(items) == len(set(items)):
                return sets
            self.counters["redraw.item-clause"] += 1
        raise self._stop("cts:redraw-cap item-clause")

    def _fold(self, sets):
        """A tracker that folded every event so far with `sets` as the foe's sheet, its view of the last decision point
        and the (record, status) of each decision point (Particle.history). Each decision point it reaches is checked as
        it was when its batch came (review of 2026-10-12: a particle drawn anew must pass every check a kept one
        passed)."""
        t = Tracker(self.data, self.own_text)
        t.check_foe_sheet = True
        t.record_kind = self.record_kind
        own = teams.pack(self.own_text)
        foe = teams.pack(teams.to_text(sets))
        view, history = None, []
        for kind, payload in self._events:
            if kind == "accepted":
                t.accepted(payload)
            elif kind == "lines":
                t.feed(payload)
            else:
                t.feed([f"|showteam|p{s + 1}|" + (own if s == self.side else foe) for s in (0, 1)])
            if t.ready and (view is None or t.epoch > view[0]):
                view = self._view(t)  # a decision point is ready (at team preview: with the sheets)
                history.append((view[1]["record"], view[1]["status"]))
        return t, view, history
