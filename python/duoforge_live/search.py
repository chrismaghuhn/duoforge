"""The live play mode --search honest (option A, plan 2026-10-10-live-honest-search, Task 5).

LiveSearch runs duoforge_search.honest.Honest on the tracker's public parts (Tracker.public_parts: request,
observation, the public record and its status and causes) through a RecordRoots of one environment. It decides no
rule itself; it only classifies the search's answer by the owner's failure classes of 2026-10-10:

- searched: the search's pair is played;
- forced, raw, team: the search has nothing to add (one legal pair, k = 1, team preview); the raw ranking is played,
  no fallback;
- (a) a named refusal (kind "unreconstructible": a public refusal, a missing history, no spread prior): that decision
  is played raw, logged and counted;
- deadline: the search did not answer within min(2 s, 10% of the remaining turn time); played raw, counted apart from
  (a). A search still running from an earlier decision is waited for, never run beside ("busy");
- (b) anything else (an exception, an unknown kind): played raw; the caller marks the game dirty, plays the rest of it
  raw and takes no new challenge until the session is reviewed.
"""
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass

import numpy as np

from duoforge import features
from duoforge_search.errors import SearchError  # noqa: F401  (re-exported for the caller's tests)

DEADLINE_CAP = 2.0  # seconds
DEADLINE_SHARE = 0.10  # of the remaining turn time
_TIMER = re.compile(r"^\|inactive\|Time left: (\d+) sec this turn \| \d+ sec total( \| \d+ sec grace)?$")
_TIMER_ON = "|inactive|Battle timer is ON"
_NO_FALLBACK = ("searched", "forced", "raw", "team")
# The approved spec's search (owner, 2026-10-10): X (mix, lambda 0.5) at K = M = 8 and 16 worlds over the pinned live
# spread table, a foe species without a spread prior refused.
HONEST_SETTINGS = {"k": 8, "m": 8, "s": 16, "rule": "mix", "lam": 0.5, "species_prior": True}


@dataclass(frozen=True)
class Outcome:
    action: object  # the flat pair index (i * OPTIONS + j) to play, or None: the raw ranking
    cause: str  # searched, forced, raw, team, unreconstructible, deadline, busy, error
    fallback: object  # None, "a", "deadline" or "b"
    reason: object  # the search's named reason or the error, or None
    seconds: float

    def as_dict(self):
        return asdict(self)


def parse_timer(line):
    """The seconds left this turn of the player's own timer line (server/room-battle.ts nextRequest), else None."""
    m = _TIMER.match(line)
    return int(m.group(1)) if m else None


def timer_on(line):
    return line.startswith(_TIMER_ON)


def deadline_seconds(turn_left, received, now):
    """min(DEADLINE_CAP, DEADLINE_SHARE of the turn time still left): turn_left seconds as of `received`; None (no
    timer) gives the cap."""
    if turn_left is None:
        return DEADLINE_CAP
    return min(DEADLINE_CAP, DEADLINE_SHARE * max(0.0, turn_left - (now - received)))


def decision_key(room, epoch):
    """The search key of a decision point: a pure function of the battle room and the request epoch."""
    digest = hashlib.blake2b(f"{room}|{int(epoch)}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little")


def _encoded(searcher, observation, obs_part, slot_part, pair_mask):
    """The search network's rows (Batch.query_encoded's per-seat layout) of the live features; zeros for the slots and
    pairs at team preview (pair_mask None), as the live policy's team head reads them."""
    obs = features.as_encoder(np.asarray(obs_part, dtype=np.float32), observation, searcher.encoder)
    if pair_mask is None:
        slots = np.zeros((2, features.OPTIONS, features.SLOT_FEATURES), np.float32)
        pairs = np.zeros((features.OPTIONS, features.OPTIONS), bool)
    else:
        slots = features.slots_as_encoder(np.asarray(slot_part, dtype=np.float32), searcher.encoder)
        pairs = np.asarray(pair_mask, dtype=bool)
    return obs, slots, pairs


class LiveSearch:
    def __init__(self, searcher, roots=None, clock=time.monotonic):
        if roots is None:
            from duoforge_search.record_roots import RecordRoots
            roots = RecordRoots(1)
        self.searcher, self.roots, self.clock = searcher, roots, clock
        self._executor = ThreadPoolExecutor(1, thread_name_prefix="duoforge-live-search")
        self._running = None  # the future of a search that missed its deadline
        self.closers = []  # what load() opened for this search

    def close(self):
        self._executor.shutdown(wait=True)
        for close in self.closers:
            close()
        self.closers = []

    def _classify(self, future, seconds):
        try:
            _, records = future.result()
            record = records[0]
        except Exception as err:  # class (b): every unexpected failure, named
            return Outcome(None, "error", "b", f"{type(err).__name__}: {err}", seconds)
        kind = record.get("kind")
        if kind == "searched":
            return Outcome(int(record["choice"]), kind, None, None, seconds)
        if kind in _NO_FALLBACK:
            return Outcome(None, kind, None, None, seconds)
        if kind == "unreconstructible":
            return Outcome(None, kind, "a", record.get("reason"), seconds)
        return Outcome(None, "error", "b", f"unknown decision kind {kind!r}", seconds)

    def decide(self, parts, obs_part, slot_part, pair_mask, *, key, episode, budget):
        start = self.clock()
        if self._running is not None:
            try:  # the late search gets this decision's budget to finish; the new one gets what is left
                self._running.result(timeout=max(0.0, budget))
            except FutureTimeout:
                return Outcome(None, "busy", "deadline", None, self.clock() - start)
            except Exception:
                pass  # classified below
            budget -= self.clock() - start
            late, self._running = self._running, None
            failed = self._classify(late, 0.0)
            if failed.fallback == "b":  # a late search that failed is still an unexpected error
                return failed
        observation = parts["observation"]
        seat = int(observation["player"])
        obs, slots, pairs = _encoded(self.searcher, observation, obs_part, slot_part, pair_mask)
        self.roots.set(0, seat, request=parts["request"], observation=observation, obs=obs, slots=slots, pairs=pairs,
                       record=parts["record"], status=parts["status"], episode=episode, causes=parts["causes"])
        future = self._executor.submit(self.searcher.decide, self.roots, [0], [seat], [key], [False])
        try:
            future.result(timeout=max(0.0, budget))
        except FutureTimeout:
            self._running = future
            return Outcome(None, "deadline", "deadline", None, self.clock() - start)
        except Exception:
            pass  # classified below
        return self._classify(future, self.clock() - start)


def load(checkpoint_path, settings=None):
    """The LiveSearch of a format-2 checkpoint in its trained layout (HONEST_SETTINGS unless settings is given, the
    live spread table). Its close() also closes the search and its context."""
    import duoforge
    from duoforge_learn import checkpoint
    from duoforge_learn.train import DATA_KINDS
    from duoforge_search import honest
    params, config = checkpoint.load_trained(checkpoint_path)
    model = checkpoint.trained_model(config, params)
    context = duoforge.Context(data_kind=DATA_KINDS[config["data"]["kind"]])
    searcher = None
    try:
        table, _, _ = honest.live_spread_table(context)
        searcher = honest.Honest(context, model, params, checkpoint.encoder_of(config),
                                 checkpoint.ext_supported_of(config), table=table,
                                 **(HONEST_SETTINGS if settings is None else settings))
        live = LiveSearch(searcher)
    except BaseException:
        if searcher is not None:
            searcher.close()
        context.close()
        raise
    live.closers = [searcher.close, context.close]
    return live
