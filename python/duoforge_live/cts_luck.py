"""The luck meter of the live evaluation (#494; definition: docs/benchmarks/2026-10-14-cts-luck/README.md).

For a searched turn of a closed-sheet battle the bot played, luck = V(the state that happened) - the mean of V over C
chance seeds of the same actions. Everything about the battle is the engine's and the replay core's:

- the worlds: the search's own worlds of the decision point (cts.LogReplay with the bot's seed, key and set prior, the
  replayed honest search; world w is particle w), weighed as the search weighs them;
- the same actions: the bot's accepted choice (cts.pair_texts of cts.logged_choice) and, in each world, the foe's action
  the turn's lines show (duoforge_replay.labels.turn_label on that world's foe options, the particle's sheets): one
  option per foe slot, else the turn is excluded by name (foe-action-ambiguous, foe-action-unmatched);
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


def foe_choice(segment, side, lists, ctx):
    """The flat pair of the foe's two slots that the turn's lines show in one world: (slot 0 option, slot 1 option).
    Excluded("foe-action-ambiguous") when a slot's label holds more than one option (a hidden move, an unknown
    target, no line), Excluded("foe-action-unmatched") when it holds none."""
    from duoforge_replay import labels
    label = labels.turn_label(segment, _Point(0, len(segment)), side, lists, ctx.moves, ctx.member_of, ctx.data.tables,
                              len(segment), ctx.vacant, ctx.barred)
    picks = []
    for k in (0, 1):
        found = [i for i in range(len(lists[k])) if label.slots[k] >> i & 1]
        if not found:
            raise Excluded("foe-action-unmatched")
        if len(found) > 1:  # named by the label's reason (labels: target-unknown, move-hidden, unknown, ...)
            raise Excluded("foe-action-ambiguous:" + _reason_name(label.reasons[k]))
        picks.append(found[0])
    return tuple(picks)



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
            own = cts.pair_texts(game, policy)[cts.logged_choice(record)]
        except cts.Refused as refused:
            raise Excluded(str(refused)) from None
        except KeyError:
            raise Excluded("own-choice-not-allowed") from None
        seat = int(search_record["seat"])
        contexts = [labels.context(p.tracker, 1 - seat) for p in game.tracker.particles]
        weights = np.asarray(search_record["weights"], np.float64)
        if weights.shape != (self.search.s,) or len(contexts) != self.search.s:
            raise ValueError(f"{len(contexts)} particles and {weights.shape} weights for {self.search.s} worlds")
        return Turn(seat, int(search_record["key"]), int(own), weights, contexts, len(game.tracker._lines()),
                    int(game.tracker.observations()[0]["turn"]))

    def expected(self, turn, segment):
        """The mean value of the turn's alternatives on the search's worlds as they still stand (no search ran since
        the turn's point): per world the foe's shown action, `samples` seeds each, the worlds weighed by the search."""
        import duoforge
        from duoforge import _layout
        from duoforge_learn.luck import leaf_values
        from duoforge_search import lookahead
        worlds, s, p, foe = self.search.worlds, self.search.s, turn.seat, 1 - turn.seat
        worlds.query_factored()
        n = lookahead.OPTIONS
        choices = np.zeros((s, 2), _layout.FACTORED_CHOICE)
        choices["slot"][:, p, 0], choices["slot"][:, p, 1] = divmod(turn.own, n)
        asked = bool(worlds.requests[0, foe]["requested"])
        if any(bool(worlds.requests[w, foe]["requested"]) != asked for w in range(s)):
            raise ValueError("the worlds disagree on whether the foe is asked")
        self.last = {"foe": []}  # per world the foe's two options played (diagnostics and tests)
        if asked:
            for w in range(s):
                domain = worlds.domains[w, foe]
                lists = foe_options(domain)
                a, b = foe_choice(segment, foe, lists, turn.contexts[w])
                if not int(domain["allowed"][a]) >> b & 1:
                    raise Excluded("foe-action-not-allowed")
                choices["slot"][w, foe, 0], choices["slot"][w, foe, 1] = a, b
                self.last["foe"].append((lists[0][a], lists[1][b]))
        k = self.samples
        root_envs = np.repeat(np.arange(s, dtype=np.uint32), k)
        samples = np.tile(np.arange(k, dtype=np.uint32), s)
        keys = np.full(worlds.envs, turn_key(turn.key), np.uint64)
        viewers = np.full(worlds.envs, p, np.uint8)
        obs, step, encode, _, results = self.leaves.expand(worlds, self.search.encoder, self.search.ext_supported,
                                                           LUCK_SEED, keys, viewers, root_envs, samples,
                                                           np.repeat(choices, k, axis=0))
        step, encode, results = (np.array(x, copy=True) for x in (step, encode, results))
        if (step == duoforge._layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"]).any():
            raise Excluded("leaf-refused")
        values = leaf_values(self._value(np.array(obs, copy=True)), step, encode, results, p)
        return float(np.sum(turn.weights * values.reshape(s, k).mean(axis=1)) / np.sum(turn.weights))

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
    """The luck of one closed-sheet battle log: {"turns": [luck per valued turn], "result", "excluded": Counter}.
    live is a LiveSearch whose searcher is a cts.Capture; meter a Meter on its search. cts.Refused for a log the
    replay does not follow (as cts.replay_closed), by name."""
    import json
    from pathlib import Path
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
    excluded, luck = collections.Counter(), []
    pending = None
    replayed = cts.LogReplay(records, data, policy, team_text, prior, key, search=live, waits=True)
    for game, record in replayed:
        if pending is not None:  # the state that happened after the pending turn: this point's particles
            segment = game.tracker._lines()[pending.lines_at:]
            try:
                expected = meter.expected(pending, segment)
                luck.append(meter.actual(game, pending.seat, policy) - expected)
            except Excluded as e:
                excluded[str(e)] += 1
            pending = None
        if record is None or game.request.get("teamPreview"):
            continue
        if record["accepted"] is None and cts.ended_on(records, record["decision"]):
            record = dict(record, accepted=record["sent"])  # the battle ended on it: played as sent
        live.searcher.records = None
        game.candidates(budget)
        outcome = game.outcomes[-1] if game.outcomes else None
        if outcome is None or outcome.cause != "searched":
            excluded[f"not-searched:{None if outcome is None else outcome.cause}"] += 1
            continue
        try:
            pending = meter.turn(game, record, live.searcher.records[0], policy)
        except Excluded as e:
            excluded[str(e)] += 1
    if pending is not None:  # the battle ended in the pending turn
        if result is None:
            excluded["no-end"] += 1
        else:  # the turn's lines: what was fed since its point, then the last batch, received ({"in"}) but not fed
            last_feed = max(i for i, r in enumerate(records) if "feed" in r)
            segment = replayed.game.tracker._lines()[pending.lines_at:] +                 [r["in"] for r in records[last_feed + 1:] if isinstance(r.get("in"), str)]
            try:
                luck.append(result - meter.expected(pending, segment))
            except Excluded as e:
                excluded[str(e)] += 1
    if replayed.diverged is not None:
        raise SearchError(f"{Path(path).name}: the replay and the bot disagree on a stop ({replayed.diverged})")
    if replayed.stopped is not None:
        raise cts.Refused(replayed.stopped)
    return {"turns": luck, "result": result, "excluded": excluded}
