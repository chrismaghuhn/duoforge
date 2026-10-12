"""The live play mode --search honest (option A, plan 2026-10-10-live-honest-search, Task 5).

LiveSearch runs duoforge_search.honest.Honest on the tracker's public parts (Tracker.public_parts: request,
observation, the public record and its status and causes) through a RecordRoots of one environment. It decides no
rule itself; it only classifies the search's answer by the owner's failure classes of 2026-10-10:

- searched: the search's pair is played; a foe species the belief drew from its general levels (species_prior
  "count", owner 2026-10-12) is named in the outcome (spread_fallback, spread_redrawn) and counted per game;
- forced, raw, team: the search has nothing to add (one legal pair, k = 1, team preview); the raw ranking is played,
  no fallback;
- (a) a named refusal (kind "unreconstructible": a public refusal, a missing history): that decision
  is played raw, logged and counted;
- deadline: the search did not answer within min(2 s, 10% of the remaining turn time); played raw, counted apart from
  (a). A search still running from an earlier decision is waited for, never run beside ("busy");
- (b) anything else (an exception, an unknown kind): played raw; the caller marks the game dirty, plays the rest of it
  raw and takes no new challenge until the session is reviewed.
"""
import hashlib
import os
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
_TIMER_OFF = "|inactiveoff|"
_NO_FALLBACK = ("searched", "forced", "raw", "team")
# The approved spec's search (owner, 2026-10-10): X (mix, lambda 0.5) at K = M = 8 and 16 worlds over the pinned live
# spread table (Smogon's usage stats first, owner 2026-10-12); a foe species without a spread prior draws the belief's
# general levels, named (species_prior "count"; refusing played whole games raw). The leaf buffer is the decision's K * M * S leaves: the
# padded 16384-row value call was 93% of a decision (#355, docs/benchmarks/2026-10-11-honest-search-breakdown).
HONEST_SETTINGS = {"k": 8, "m": 8, "s": 16, "rule": "mix", "lam": 0.5, "species_prior": "count",
                   "capacity": 1024}


@dataclass(frozen=True)
class Outcome:
    action: object  # the flat pair index (i * OPTIONS + j) to play, or None: the raw ranking
    cause: str  # searched, forced, raw, team, unreconstructible, deadline, busy, error
    fallback: object  # None, "a", "deadline" or "b"
    reason: object  # the search's named reason or the error, or None
    seconds: float
    spread_fallback: object = None  # a searched decision's foe species without a spread prior (species_prior "count")
    spread_redrawn: object = None  # ... and those whose spreads a redraw exhausted

    def as_dict(self):
        return asdict(self)


def parse_timer(line):
    """The seconds left this turn of the player's own timer line (server/room-battle.ts nextRequest), else None."""
    m = _TIMER.match(line)
    return int(m.group(1)) if m else None


def timer_on(line):
    return line.startswith(_TIMER_ON)


def timer_off(line):
    return line.startswith(_TIMER_OFF)


def check_tracker(tracker_class):
    """The live search reads Tracker.public_parts (HauptSession's record assembler): without it --search honest is
    refused at start, before anything is loaded."""
    if not callable(getattr(tracker_class, "public_parts", None)):
        raise SearchError("--search honest needs Tracker.public_parts (the record assembler), which this tracker lacks")


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
        self._running_episode = None
        self.closers = []  # what load() opened for this search
        self.foe_check = None  # load()'s check of the foe network against the library's tables

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
            return Outcome(int(record["choice"]), kind, None, None, seconds, record.get("spread_fallback"),
                           record.get("spread_redrawn"))
        if kind in _NO_FALLBACK:
            return Outcome(None, kind, None, None, seconds)
        if kind == "unreconstructible":
            reason, causes = record.get("reason"), [c for c in record.get("causes", ()) if c != record.get("reason")]
            if causes:  # Honest's named causes of a refused public record (visible sleep, Substitute, ...)
                reason = f"{reason} ({', '.join(causes)})"
            return Outcome(None, kind, "a", reason, seconds)
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
            if failed.fallback == "b":  # a late search that failed is still an unexpected error, named by its game
                return Outcome(None, "error", "b", f"{failed.reason} (late, from episode {self._running_episode})",
                               failed.seconds)
        observation = parts["observation"]
        seat = int(observation["player"])
        obs, slots, pairs = _encoded(self.searcher, observation, obs_part, slot_part, pair_mask)
        self.roots.set(0, seat, request=parts["request"], observation=observation, obs=obs, slots=slots, pairs=pairs,
                       record=parts["record"], status=parts["status"], episode=episode, causes=parts["causes"])
        future = self._executor.submit(self.searcher.decide, self.roots, [0], [seat], [key], [False])
        try:
            future.result(timeout=max(0.0, budget))
        except FutureTimeout:
            self._running, self._running_episode = future, episode
            return Outcome(None, "deadline", "deadline", None, self.clock() - start)
        except Exception:
            pass  # classified below
        outcome = self._classify(future, self.clock() - start)
        if outcome.fallback == "a" and parts.get("reason"):  # the tracker's own named reason beside the search's
            outcome = Outcome(None, outcome.cause, "a", f"{outcome.reason}; tracker: {parts['reason']}",
                              outcome.seconds)
        return outcome


# The live search's foe model (owner 2026-10-12; docs/benchmarks/2026-10-12-bc6-foe-model): M11's encoder-6 BC6 models
# the foe in the worlds (honest.Honest's foe_net), pinned by its file's SHA-256. Its weights are private: the file comes
# from --foe-net or $DUOFORGE_FOE_NET, and a search with nothing configured is refused, never played without it;
# --no-foe-net (None) is the explicit choice of the earlier search, for comparisons. Another foe model needs its own
# measured arena and its pin (--foe-net-sha256, or a new FOE_NET_SHA256).
FOE_NET_SHA256 = "bda5de8e4e960f3df41b029cd4d3d87fc48838fdd47c8562a78649e222ee9f39"
FOE_NET_ENV = "DUOFORGE_FOE_NET"
ENVIRONMENT = object()  # foe_net's default: the path in $DUOFORGE_FOE_NET


def foe_net_path(foe_net=ENVIRONMENT, environ=None):
    """The foe model's file: foe_net itself, $DUOFORGE_FOE_NET for ENVIRONMENT, or None (no foe network) for None.
    ValueError when ENVIRONMENT finds nothing configured."""
    if foe_net is ENVIRONMENT:
        foe_net = (os.environ if environ is None else environ).get(FOE_NET_ENV) or None
        if foe_net is None:
            raise ValueError(f"the live search's foe model (BC6) is not configured: pass --foe-net PATH, set "
                             f"${FOE_NET_ENV}, or choose --no-foe-net")
    return foe_net


def add_foe_net_arguments(parser):
    """--foe-net PATH or --no-foe-net (exclusive) and --foe-net-sha256 (foe_net_of and foe_net_sha256_of read them)."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--foe-net", default=None,
                       help=f"with --search honest: the checkpoint that models the foe in the search's worlds "
                            f"(Honest's foe_net), the pinned BC6 (default: ${FOE_NET_ENV})")
    group.add_argument("--no-foe-net", action="store_true",
                       help="with --search honest: no foe network (the earlier live search, for comparisons)")
    parser.add_argument("--foe-net-sha256", default=None,
                        help="the foe network file's SHA-256, checked before loading (default: the pinned BC6)")


def foe_net_of(args):
    """load's foe_net from parsed add_foe_net_arguments options."""
    if args.no_foe_net:
        return None
    return args.foe_net if args.foe_net else ENVIRONMENT


def foe_net_sha256_of(args):
    return args.foe_net_sha256 or FOE_NET_SHA256


def load(checkpoint_path, settings=None, foe_net=ENVIRONMENT, foe_net_sha256=FOE_NET_SHA256):
    """The LiveSearch of a format-2 checkpoint in its trained layout (HONEST_SETTINGS unless settings is given, the
    live spread table), its worlds modelled by the pinned foe network: foe_net a path, ENVIRONMENT for
    $DUOFORGE_FOE_NET, None for none; a foe network already in settings ("foe_net") is taken as it is. The foe network
    must have foe_net_sha256 and read the library's tables (pkmn_arena.load_foe_net: checkpoint.check_data); its check
    is the LiveSearch's foe_check. Its close() also closes the search and its context."""
    import duoforge
    from duoforge_learn import checkpoint
    from duoforge_learn.train import DATA_KINDS
    from duoforge_search import honest
    settings = HONEST_SETTINGS if settings is None else settings
    foe_check = None
    if "foe_net" not in settings:
        path = foe_net_path(foe_net)
        if path is not None:
            from .pkmn_arena import load_foe_net
            foe, foe_check = load_foe_net(path, foe_net_sha256)
            settings = dict(settings, foe_net=foe)
    params, config = checkpoint.load_trained(checkpoint_path)
    model = checkpoint.trained_model(config, params)
    context = duoforge.Context(data_kind=DATA_KINDS[config["data"]["kind"]])
    searcher = None
    try:
        table, _, _ = honest.live_spread_table(context)
        searcher = honest.Honest(context, model, params, checkpoint.encoder_of(config),
                                 checkpoint.ext_supported_of(config), table=table,
                                 **settings)
        live = LiveSearch(searcher)
    except BaseException:
        if searcher is not None:
            searcher.close()
        context.close()
        raise
    live.closers = [searcher.close, context.close]
    live.foe_check = foe_check
    return live
