"""The luck meter of the live evaluation (#494; definition: docs/benchmarks/2026-10-14-cts-luck/README.md).

For a searched turn of a closed-sheet battle the bot played, luck = V(the state that happened) - the mean of V over C
chance seeds of the same actions. Everything about the battle is the engine's and the replay core's:

- the worlds: the search's own worlds of the decision point (cts.LogReplay with the bot's seed, key and set prior, the
  replayed honest search; world w is particle w), weighed as the search weighs them;
- the same actions: the bot's accepted choice (cts.pair_texts of cts.logged_choice) and, in each world, the foe's action
  the turn's lines show (duoforge_replay.labels.turn_label on that world's foe options, the particle's sheets, the
  world's own roster); a set the lines narrow it to is mixed by the foe model; a world the turn refutes or that cannot
  play what the lines show is left out; a turn the lines tell nothing of, or with no world left, is excluded by name;
- the alternatives: Batch.expand of every world with both choices under C seeds, search_seeds(LUCK_SEED, key, sample),
  the key drawn from the decision's search key (common random numbers: the seeds never depend on the choices);
- V: the bot's value network from its seat (duoforge_learn.luck.leaf_values: a terminal leaf is its result);
- the state that happened: the next decision point's particles, asked or not (a wait request: only the foe chooses,
  LogReplay(waits=True)), each particle's view encoded as the search encodes its root, the particles weighing alike; a
  battle that ended in the turn is its result.

Python averages and classifies nothing of the battle: no crit, miss or roll is read from a line. A turn the engine
refuses (a refused leaf, an unsupported record) is excluded by name, never guessed.
"""
import collections
from dataclasses import dataclass

import numpy as np

LUCK_SEED = 0x2026101400000494
LUCK_TAG = 0x4C55434B  # "LUCK", as duoforge_learn.luck
SAMPLES = 8  # C, the chance seeds per world (HS, 2026-10-14); the README names the C = 32 check


class Excluded(Exception):
    """A turn the meter does not value, named (its reason is counted)."""


@dataclass(frozen=True)
class _Point:
    line: int
    end: int


@dataclass
class Turn:
    """A searched turn waiting for the state that happened: what the next decision point needs of it."""
    seat: int
    key: int
    own: int  # the bot's flat pair
    weights: np.ndarray  # the search's world weights
    contexts: list  # per world: the label context of the foe side at the point (labels.context)
    sets: list  # per world: the particle's foe sets at the point (the world's)
    lines_at: int  # the particle tracker's line count at the point
    turn: int


def foe_options(domain):
    """The slot lists (options.Option, no text) of a world's FACTORED_DOMAIN for one player."""
    from . import options
    out = []
    for s in (0, 1):
        out.append([options.Option(int(o["kind"]), int(o["move_slot"]), int(o["target"]), int(o["mega"]),
                                   int(o["reserve"]), "") for o in domain["slots"][s][:int(domain["slot_count"][s])]])
    return out


def foe_shown(segment, side, lists, ctx):
    """The foe's options that the turn's lines show in one world: per slot the indices of its label
    (labels.turn_label on the world's options, the particle's sheets). One option per slot is the action; more is a
    set the log narrows (a hidden move, an unknown target), mixed by the foe model. Excluded("foe-action-unknown") for
    a slot the log tells nothing of (every option: no line, the game ended first), Excluded("foe-action-unmatched")
    for a slot no option agrees with."""
    from duoforge_replay import labels
    label = labels.turn_label(segment, _Point(0, len(segment)), side, lists, ctx.moves, ctx.member_of, ctx.data.tables,
                              len(segment), ctx.vacant, ctx.barred)
    out = []
    for k in (0, 1):
        found = [i for i in range(len(lists[k])) if label.slots[k] >> i & 1]
        if not found:
            raise Excluded("foe-action-unmatched")
        if len(found) > 1 and label.reasons[k] == labels.UNKNOWN:
            raise Excluded("foe-action-unknown")
        out.append(found)
    return out, tuple(_reason_name(r) for r in label.reasons)

def world_context(ctx, foe_side):
    """The label context of a world: the particle's, with the foe's roster as the world's own engine roster (its
    observation's members, in the world's order: an option's reserve is a roster index of the world), by base species
    (a Mega's, Aegislash's); a base species on two members is refused by name (roster-ambiguous), and a switch line's
    species on none gives no option (the world cannot play it)."""
    import dataclasses
    data = ctx.data
    roster = tuple(data.base_forme(int(m["species_id"])) for m in foe_side["members"][:int(foe_side["member_count"])])
    if len(set(roster)) != len(roster):  # a base species on two members: the switch line's member is not one (named)
        raise Excluded("roster-ambiguous")
    return dataclasses.replace(ctx, roster=roster)

def _reason_name(reason):
    from duoforge_replay import labels
    return {labels.NOT_REQUESTED: "not-requested", labels.EXACT: "exact", labels.TARGET_UNKNOWN: "target-unknown",
            labels.MOVE_HIDDEN: "move-hidden", labels.FORCED: "forced", labels.UNKNOWN: "unknown"}[reason]


def turn_key(search_key):
    """The luck's key of a decision: drawn from its search key (a pure function of the room and the epoch)."""
    from duoforge_learn.pairing import draw
    return int(draw(LUCK_SEED, LUCK_TAG, np.uint64(search_key), np.uint64(0)))


class Meter:
    """The luck of the searched turns of replayed battles, valued by the honest search's own network (its model,
    params, encoder and ext_supported). It owns a leaf batch of worlds x samples environments: close it."""

    def __init__(self, search, samples=SAMPLES):
        import duoforge
        if int(samples) < 1:
            raise ValueError(f"samples must be at least 1 (got {samples})")
        self.search, self.samples = search, int(samples)
        self.capacity = search.s * self.samples
        self.leaves = duoforge.Batch(search.worlds.context, np.resize(duoforge.reference_setups([0]), self.capacity),
                                     1, LUCK_SEED)
        self.last = None

    def close(self):
        self.leaves.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _value(self, rows):
        """The value head on rows (n, width), in one compiled shape (the capacity), float64."""
        model, params = self.search.model, self.search.params
        out = np.empty(rows.shape[0], np.float64)
        buffer = np.zeros((self.capacity, rows.shape[1]), np.float32)
        for start in range(0, rows.shape[0], self.capacity):
            end = min(rows.shape[0], start + self.capacity)
            buffer.fill(0)
            buffer[:end - start] = rows[start:end]
            out[start:end] = np.asarray(model.value(params, buffer), np.float64)[:end - start]
        if not np.isfinite(out).all():
            raise ValueError("the value head gives a value that is not finite")
        return out

    def turn(self, game, record, search_record, policy):
        """The searched turn of a decision point the search just decided (game.candidates; search_record its record):
        a Turn, or Excluded by name."""
        from duoforge_replay import labels
        from . import cts
        if search_record.get("kind") != "searched":
            raise Excluded(f"not-searched:{search_record.get('kind')}")
        if search_record.get("boundary") != "TURN":
            raise Excluded(f"not-turn:{search_record.get('boundary')}")
        try:
            choice = cts.logged_choice(record)
        except cts.Refused as refused:
            raise Excluded(str(refused)) from None
        texts = cts.pair_texts(game, policy)
        if choice not in texts:
            raise Excluded("own-choice-not-allowed")
        own = texts[choice]
        seat = int(search_record["seat"])
        contexts = [labels.context(p.tracker, 1 - seat) for p in game.tracker.particles]
        weights = np.asarray(search_record["weights"], np.float64)
        if weights.shape != (self.search.s,) or len(contexts) != self.search.s:
            raise ValueError(f"{len(contexts)} particles and {weights.shape} weights for {self.search.s} worlds")
        return Turn(seat, int(search_record["key"]), int(own), weights, contexts,
                    [list(p.sets) for p in game.tracker.particles], len(game.tracker._lines()),
                    int(game.tracker.observations()[0]["turn"]))

    def expected(self, turn, segment, facts):
        """(mean value of the turn's alternatives, mixed) on the search's worlds as they still stand (no search ran
        since the turn's point), the worlds weighed by the search, `samples` seeds each. Per world the foe's action the
        lines show; where they narrow it to a set (mixed True), every pair of the set, weighed by the search's foe model
        in that world (Honest's world policy, the pinned foe network) renormalized on the set (HauptSession,
        2026-10-14). A world the turn refutes is left out, the others renormalized: facts are the foe's facts through
        the turn (duoforge_replay.facts.side_facts, as the particle filter takes them), and a world whose sets do not
        agree with them (cts.agrees, the particle filter's own test: a move used, an item or ability revealed that
        its set lacks) could not play the turn. Returns (expected, mixed, worlds left out); Excluded
        ("foe-action-not-in-worlds") when the turn refutes every world."""
        import duoforge
        from duoforge import _layout
        from duoforge_learn.luck import leaf_values
        from duoforge_search import lookahead
        worlds, s, p, foe = self.search.worlds, self.search.s, turn.seat, 1 - turn.seat
        policy = None
        worlds.query_factored()
        n = lookahead.OPTIONS
        asked = bool(worlds.requests[0, foe]["requested"])
        if any(bool(worlds.requests[w, foe]["requested"]) != asked for w in range(s)):
            raise ValueError("the worlds disagree on whether the foe is asked")
        from . import cts
        kept = [w for w in range(s) if all(cts.agrees(x, f) for x, f in zip(turn.sets[w], facts))]
        if not kept:
            raise Excluded("foe-action-not-in-worlds")
        plan = []  # (world, foe pair or None, its weight in the world)
        mixed = False
        self.last = {"foe": [], "reasons": [], "rosters": [], "kept": kept}  # per world played (diagnostics, tests)
        unknown = []  # worlds whose label tells nothing of a foe slot (a world that cannot play the lines is left out)
        for w in kept:
            if not asked:
                plan.append((w, None, 1.0))
                continue
            domain = worlds.domains[w, foe]
            lists = foe_options(domain)
            ctx = world_context(turn.contexts[w], worlds.observations[w, p]["sides"][foe])  # roster-ambiguous: the turn
            try:
                (first, second), reasons = foe_shown(segment, foe, lists, ctx)
            except Excluded as e:
                if str(e) == "foe-action-unknown":
                    unknown.append(w)
                continue
            pairs = [(a, b) for a in first for b in second if int(domain["allowed"][a]) >> b & 1]
            if not pairs:  # the world's own domain bars the pair the lines show (a Choice lock, Taunt, Disable, ...)
                continue
            self.last["foe"].append([(lists[0][a], lists[1][b]) for a, b in pairs])
            self.last["reasons"].append(reasons)
            self.last["rosters"].append(ctx.roster)  # the world's foe roster (base formes), its reserves' order
            if len(pairs) == 1:
                plan.append((w, pairs[0], 1.0))
                continue
            mixed = True
            if policy is None:  # the foe model on the worlds as they stand, read only
                policy = self.search._world_policy()[0]
                worlds.query_factored()  # the domains of the expansion, as the search leaves them
            q = np.exp(np.array([policy[w, foe][a * n + b] for a, b in pairs], np.float64))
            if not np.isfinite(q).all() or q.sum() <= 0:
                raise Excluded("foe-model-zero")
            plan += [(w, pair, float(x)) for pair, x in zip(pairs, q / q.sum())]
        if unknown and len(unknown) == len(kept):  # the lines tell nothing of a foe slot, in every world
            raise Excluded("foe-action-unknown")
        # a world whose label tells nothing where another world's does could not play what the lines show: left out
        played = sorted({w for w, _, _ in plan})
        if not played:
            raise Excluded("foe-action-not-in-worlds")
        kept = played
        k = self.samples
        rows = len(plan) * k
        choices = np.zeros((len(plan), 2), _layout.FACTORED_CHOICE)
        choices["slot"][:, p, 0], choices["slot"][:, p, 1] = divmod(turn.own, n)
        for i, (_, pair, _) in enumerate(plan):
            if pair is not None:
                choices["slot"][i, foe, 0], choices["slot"][i, foe, 1] = pair
        root_envs = np.repeat(np.array([w for w, _, _ in plan], np.uint32), k)
        samples = np.tile(np.arange(k, dtype=np.uint32), len(plan))
        leaf_choices = np.repeat(choices, k, axis=0)
        keys = np.full(worlds.envs, turn_key(turn.key), np.uint64)
        viewers = np.full(worlds.envs, p, np.uint8)
        values = np.empty(rows, np.float64)
        for start in range(0, rows, self.capacity):
            end = min(rows, start + self.capacity)
            obs, step, encode, _, results = self.leaves.expand(
                worlds, self.search.encoder, self.search.ext_supported, LUCK_SEED, keys, viewers,
                root_envs[start:end], samples[start:end], leaf_choices[start:end])
            step, encode, results = (np.array(x, copy=True) for x in (step, encode, results))
            if (step == duoforge._layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"]).any():
                raise Excluded("leaf-refused")
            values[start:end] = leaf_values(self._value(np.array(obs, copy=True)), step, encode, results, p)
        per_pair = values.reshape(len(plan), k).mean(axis=1)
        per_world = np.zeros(s)
        for (w, _, q), v in zip(plan, per_pair):
            per_world[w] += q * v
        weights = turn.weights[kept]
        return float(np.sum(weights * per_world[kept]) / np.sum(weights)), mixed, s - len(kept)

    def actual(self, game, seat, policy):
        """The value of the state that happened, from seat: the particles' views at the game's decision point (asked
        or a wait), each encoded as the search encodes its root, the particles weighing alike."""
        from duoforge import features
        from . import search as live_search
        domain, _ = game.tracker.domain()
        ext_supported = getattr(policy, "ext_supported", 0)
        rows = []
        for observation, ext in zip(game.tracker.observations(), game.tracker.observation_exts()):
            if int(observation["player"]) != seat:
                raise ValueError("a particle's view is not the bot's seat")
            obs_part, slot_part, pair_mask = features.encode(observation, domain, ext, ext_supported)
            rows.append(live_search._encoded(self.search, observation, obs_part, slot_part, pair_mask)[0])
        return float(self._value(np.stack(rows)).mean())


def result_of(records, bot):
    """The battle's result from the bot's side (+1 a win, -1 a loss, 0 a tie), None without an end record."""
    from .client import toid
    end = next((r["end"] for r in records if "end" in r), None)
    if not isinstance(end, str):
        return None
    parts = end.split("|")
    if len(parts) > 1 and parts[1] == "tie":
        return 0.0
    if len(parts) > 2 and parts[1] == "win":
        return 1.0 if toid(parts[2]) == toid(bot) else -1.0
    return None


def battle(path, data, policy, live, team_text, bot, prior, meter, budget=1e9):
    """The luck of one closed-sheet battle log: {"turns": [luck per valued turn], "mixed": [whether the turn's foe
    action was mixed over a set the lines narrow it to], "dropped": [the worlds the turn refuted], "worlds", "result",
    "excluded": Counter, "partial": Counter of valued turns whose rest after a pivot inside them is valued nowhere}.
    live is a LiveSearch whose searcher is a cts.Capture; meter a Meter on its search. cts.Refused for a log the
    replay does not follow (as cts.replay_closed), by name."""
    import json
    from pathlib import Path
    from duoforge_replay import facts as _facts
    from duoforge_replay.points import Skip
    from duoforge_search.errors import SearchError
    from . import cts
    try:
        key = cts.room_of_log(path, bot)
    except ValueError:
        raise cts.Refused("other_bot") from None
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    if not any("feed" in r for r in records):
        raise cts.Refused("open_sheets_log")
    result = result_of(records, bot)
    excluded, luck, mixed, dropped = collections.Counter(), [], [], []
    partial = collections.Counter()  # valued turns whose rest after a pivot inside them is valued nowhere
    searches = differs = 0
    pending = None

    def value(turn, lines, actual):
        """The pending turn's luck (lines: the stream through the turn, its segment from the turn's point on)."""
        try:
            facts = _facts.side_facts(lines, 1 - turn.seat, data)
        except Skip as skip:
            excluded[f"facts:{skip.reason}"] += 1
            return
        try:
            expected, was_mixed, left_out = meter.expected(turn, lines[turn.lines_at:], facts)
        except Excluded as e:
            excluded[str(e)] += 1
            return
        luck.append(actual() - expected)
        mixed.append(was_mixed)
        dropped.append(left_out)
    replayed = cts.LogReplay(records, data, policy, team_text, prior, key, search=live, waits=True)
    for game, record in replayed:
        if pending is not None:  # the state that happened after the pending turn: this point's particles
            lines = game.tracker._lines()
            value(pending, lines, lambda: meter.actual(game, pending.seat, policy))
            if not any(line.startswith("|upkeep") for line in lines[pending.lines_at:]):  # a pivot inside the turn
                if game.request.get("wait"):  # the foe's: the turn is valued at it, the rest of it nowhere
                    partial["rest-after-foe-pivot"] += 1
                elif game.request.get("forceSwitch"):  # the bot's own (a not-turn point follows): the same
                    partial["rest-after-own-pivot"] += 1
            pending = None
        if game.request.get("teamPreview"):
            continue
        if record is None:  # a wait point, or an asked point the bot wrote no decision record for (counted)
            if game.asked():
                excluded["no-decision-record"] += 1
            continue
        if record["accepted"] is None and cts.ended_on(records, record["decision"]):
            record = dict(record, accepted=record["sent"])  # the battle ended on it: played as sent
        live.searcher.records = None
        game.candidates(budget)
        outcome = game.outcomes[-1] if game.outcomes else None
        logged = record.get("search")
        if isinstance(logged, dict) and outcome is not None:  # the replayed search against the bot's (a diagnosis)
            searches += 1
            if logged.get("cause") != outcome.cause or outcome.cause == "searched" and logged.get("action") != outcome.action:
                differs += 1
        if outcome is None or outcome.cause != "searched":
            excluded[f"not-searched:{None if outcome is None else outcome.cause}"] += 1
            continue
        try:
            pending = meter.turn(game, record, live.searcher.records[0], policy)
        except Excluded as e:
            excluded[str(e)] += 1
    if replayed.diverged is not None:
        raise SearchError(f"{Path(path).name}: the replay and the bot disagree on a stop ({replayed.diverged})")
    if replayed.stopped is not None:
        raise cts.Refused(replayed.stopped)
    if pending is not None:  # the battle ended in the pending turn
        if result is None:
            excluded["no-end"] += 1
        else:  # the turn's lines: what was fed since its point, then the last batch, received ({"in"}) but not fed
            last_feed = max(i for i, r in enumerate(records) if "feed" in r)
            value(pending, replayed.game.tracker._lines() + [r["in"] for r in records[last_feed + 1:]
                                                               if isinstance(r.get("in"), str)], lambda: result)
    return {"turns": luck, "mixed": mixed, "dropped": dropped, "worlds": meter.search.s, "result": result,
            "excluded": excluded, "partial": partial, "searches": searches, "search_differs": differs}
