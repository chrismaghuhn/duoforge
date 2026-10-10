"""The P1 evaluation gate and fixed resource ledger (plan C5, decision 0024).

make_eval_rows predeclares the 12288 raw-play evaluation games: paired
swapped seats, every suite half PP_/A/B/C and half LL_, pilot and control on
mirrored rows. evaluate_records turns their results into fixed groups with
paired-seat bootstrap intervals and gate statuses; nothing chooses an
endpoint after the fact. validate_compute compares the two arms' measured
CPU core-seconds and GPU-seconds (learner ledger.py files) within 5% each.
TrickRoomTracker and trick_room_report are a diagnostic beside the gate (owner
amendment 2026-10-09): Trick Room fields per game, read from play_suite's
batch buffers, and their report; no gate reads them.
Plays nothing, trains nothing; no battle rules here.
"""
import argparse
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import sys
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from duoforge_replay.dataset import refuse_repository

from .arena import BOOTSTRAP_SEED, RESAMPLES

SCHEMA_VERSION = 1
LEDGER_SCHEMA = 1
COMPUTE_TOLERANCE = 0.05
BUCKETS = ("PP", "LL")
ARMS = ("pilot", "control")
PANEL = ("BC", "3600", "11000")  # equal weights 1/3
CHECKPOINTS = ("pilot", "control", "frozen") + PANEL + ("ladder",)
# (suite, opponent, arms, games per arm): 2048 + 2048 + 3 x 1024 x 2 + 1024 x 2 = 12288 games.
SCHEDULE = (("h2h_continuation", "control", ("pilot",), 2048), ("h2h_frozen", "frozen", ("pilot",), 2048),
            *(("panel", opponent, ARMS, 1024) for opponent in PANEL), ("ladder", "ladder", ARMS, 1024))
SCHEDULE_FIELDS = ("game_id", "suite", "opponent", "arm", "bucket", "pair", "student_seat", "student_team",
                   "opponent_team", "seed")
# The Trick Room diagnostic's fields per game (integers >= 0; plan "Owner amendment: Trick Room diagnostic").
TR_FIELDS = ("tr_setter_student", "tr_setter_opponent", "tr_sets_student", "tr_sets_opponent",
             "tr_first_set_turn_student", "tr_reversals_student", "tr_blocks_student", "tr_turns", "tr_unattributed",
             "tr_last_turn_choice")
# The moves the diagnostic classifies chosen actions by (data API names). This is reporting only, no battle rule:
# nothing here feeds a decision of any player.
TR_MOVES = ("trickroom", "taunt", "fakeout", "imprison")
RECORD_FIELDS = SCHEDULE_FIELDS + ("score", "finished") + TR_FIELDS
GAMES = sum(games * len(arms) for _, _, arms, games in SCHEDULE)
# (point bar, interval bar) of the head-to-head gates, interval bar of the panel gates.
H2H_BARS = {"h2h_continuation": (0.52, 0.50), "h2h_frozen": (0.53, 0.50)}
PANEL_BAR, BUCKET_BAR = 0.0, -0.03
GROUPS = ("h2h_continuation", "h2h_frozen", "panel", "panel_PP", "panel_LL")
BLOCKS = tuple(f"{suite}/{opponent}/{arm}/{bucket}" for suite, opponent, arms_, _ in SCHEDULE for arm in arms_
               for bucket in BUCKETS)


class GateStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    INCOMPLETE = "INCOMPLETE"


def _uint(value, name, limit=1 << 64):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not 0 <= value < limit:
        raise ValueError(f"{name} must be an unsigned integer below {limit}")


def _hex(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be 64 lowercase hex digits")


@dataclass(frozen=True)
class EvalManifest:
    """The predeclared evaluation: seed, logical game ids, the pool's hash,
    every checkpoint's hash, the SHA-256 of every schedule block (suite,
    opponent, arm, bucket: its teams, seeds and game ids), raw play with book
    and preview search off, and the bootstrap resamples. Build it with
    make_manifest; nothing here can be changed by the CLI."""
    seed: int
    first_game_id: int
    pool_sha256: str
    checkpoints: Mapping
    schedule: Mapping
    play: str = "raw"
    book: bool = False
    preview_search: bool = False
    resamples: int = RESAMPLES
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        _uint(self.seed, "seed")
        _uint(self.first_game_id, "first_game_id", (1 << 63) - GAMES)  # game ids are int64
        _hex(self.pool_sha256, "pool_sha256")
        if not isinstance(self.checkpoints, Mapping) or set(self.checkpoints) != set(CHECKPOINTS):
            raise ValueError(f"checkpoints must name exactly {CHECKPOINTS}")
        for name in CHECKPOINTS:
            _hex(self.checkpoints[name], f"checkpoint {name}")
        object.__setattr__(self, "checkpoints", MappingProxyType(dict(self.checkpoints)))
        if not isinstance(self.schedule, Mapping) or set(self.schedule) != set(BLOCKS):
            raise ValueError("the schedule must hash every predeclared block")
        for name in BLOCKS:
            _hex(self.schedule[name], f"schedule block {name}")
        object.__setattr__(self, "schedule", MappingProxyType(dict(self.schedule)))
        if self.play != "raw" or self.book is not False or self.preview_search is not False:
            raise ValueError("evaluation plays raw with book and preview search off")
        if type(self.resamples) is not int or self.resamples != RESAMPLES:
            raise ValueError(f"the paired-seat bootstrap uses {RESAMPLES} resamples")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported evaluation manifest schema {self.schema_version!r}")


def manifest_mapping(manifest):
    return {"seed": manifest.seed, "first_game_id": manifest.first_game_id, "pool_sha256": manifest.pool_sha256,
            "checkpoints": dict(manifest.checkpoints), "schedule": dict(manifest.schedule), "play": manifest.play, "book": manifest.book,
            "preview_search": manifest.preview_search, "resamples": manifest.resamples,
            "schema_version": manifest.schema_version}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def pool_sha256(pool):
    """The identity of an evaluation pool: its team ids, file hashes and weights."""
    return hashlib.sha256(_canonical({"ids": list(pool.ids), "sha256": list(pool.sha256),
                                      "weights": [float(w).hex() for w in pool.weights]})).hexdigest()


def _bucket_of(team_id):
    if team_id.startswith("LL_"):
        return "LL"
    if team_id.startswith("PP_") or team_id in ("A", "B", "C"):
        return "PP"
    raise ValueError(f"team {team_id!r} is neither PP_/A/B/C nor LL_")


def _pairs(games):
    """Seat pairs per arm and bucket: games / 2 buckets / 2 seats."""
    return games // 4




def _layout():
    """(suite index, suite, opponent, arms, pairs per bucket, first game index) in schedule order."""
    out, start = [], 0
    for i, (suite, opponent, arms, games) in enumerate(SCHEDULE):
        out.append((i, suite, opponent, arms, _pairs(games), start))
        start += games * len(arms)
    return out


def _seeds(seed, index, bucket, pairs):
    """The battle seeds of a (suite, bucket) block's pairs: one batch seed
    for the whole block, from its own stream, the same for every pool, both
    arms and both seats. The engine derives a battle's RNG from the batch
    seed, the environment index and the episode only (duoforge_batch.h), so
    the runner plays a block's pairs of one arm and seat as one batch of
    that seed, environment = pair, episode 1 (evaluate.play_suite's order):
    pair p's battle RNG is duoforge_batch_seeds(seed, p, 1) on both seats
    and arms."""
    rng = np.random.default_rng([seed, index, BUCKETS.index(bucket), 1])
    block = rng.integers(0, 1 << 63, dtype=np.uint64) * 2 + rng.integers(0, 2, dtype=np.uint64)
    return np.full(pairs, block, dtype=np.uint64)


def _buckets(pool):
    buckets = {b: [] for b in BUCKETS}
    for index, team_id in enumerate(pool.ids):
        buckets[_bucket_of(team_id)].append(index)
    for b, members in buckets.items():
        if not members:
            raise ValueError(f"the evaluation pool needs {'LL_' if b == 'LL' else 'PP_/A/B/C'} teams")
    return buckets


def _block_key(suite, opponent, arm, bucket):
    return f"{suite}/{opponent}/{arm}/{bucket}"


def schedule_hashes(rows):
    """SHA-256 of every block's rows (SCHEDULE_FIELDS in game-id order)."""
    out = {}
    keys = np.array([_block_key(*k) for k in zip(rows["suite"], rows["opponent"], rows["arm"], rows["bucket"])])
    for block in sorted(set(keys.tolist())):
        idx = np.flatnonzero(keys == block)
        idx = idx[np.argsort(rows["game_id"][idx], kind="stable")]
        out[block] = hashlib.sha256(_canonical({k: np.asarray(rows[k])[idx].tolist() for k in SCHEDULE_FIELDS})).hexdigest()
    return out


def make_manifest(pool, *, seed, first_game_id, checkpoints) -> "EvalManifest":
    """The evaluation manifest of pool: its hash and every schedule block's."""
    _buckets(pool)
    _uint(seed, "seed")
    _uint(first_game_id, "first_game_id", (1 << 63) - GAMES)
    rows = _schedule_rows(pool, seed, first_game_id)
    return EvalManifest(seed, first_game_id, pool_sha256(pool), checkpoints, schedule_hashes(rows))


def make_eval_rows(pool, manifest) -> dict:
    """The 12288 predeclared games (SCHEDULE_FIELDS arrays): per suite,
    opponent and bucket the same teams and seeds for every arm, each pair
    played on both seats; checked against the manifest's pool and blocks."""
    if not isinstance(manifest, EvalManifest):
        raise ValueError("make_eval_rows needs an EvalManifest")
    _buckets(pool)
    if pool_sha256(pool) != manifest.pool_sha256:
        raise ValueError("the pool is not the one the evaluation manifest pins")
    rows = _schedule_rows(pool, manifest.seed, manifest.first_game_id)
    if schedule_hashes(rows) != dict(manifest.schedule):
        raise ValueError("the schedule differs from the manifest's blocks")
    return rows


def _schedule_rows(pool, seed, first_game_id):
    buckets = _buckets(pool)
    cols = {name: [] for name in SCHEDULE_FIELDS}
    for index, suite, opponent, arms, pairs, start in _layout():
        draws = {}
        for b in BUCKETS:
            members = np.array(buckets[b])
            weights = np.asarray(pool.weights, np.float64)[members]
            rng = np.random.default_rng([seed, index, BUCKETS.index(b), 0])
            draws[b] = (members[rng.choice(members.size, size=pairs, p=weights / weights.sum())],
                        members[rng.choice(members.size, size=pairs, p=weights / weights.sum())],
                        _seeds(seed, index, b, pairs))
        offset = start
        for arm in arms:
            for b in BUCKETS:
                student, foe, seeds = draws[b]
                for pair in range(pairs):
                    for seat in (0, 1):
                        for name, value in (("game_id", first_game_id + offset), ("suite", suite),
                                            ("opponent", opponent), ("arm", arm), ("bucket", b), ("pair", pair),
                                            ("student_seat", seat), ("student_team", int(student[pair])),
                                            ("opponent_team", int(foe[pair])), ("seed", int(seeds[pair]))):
                            cols[name].append(value)
                        offset += 1
    return _arrays(cols)


_DTYPES = {"game_id": np.int64, "suite": str, "opponent": str, "arm": str, "bucket": str, "pair": np.int64,
           "student_seat": np.int64, "student_team": np.int64, "opponent_team": np.int64, "seed": np.uint64,
           "score": np.float64, "finished": bool, **{name: np.int64 for name in TR_FIELDS}}


def _arrays(cols):
    return {name: np.array(values, dtype=_DTYPES[name]) for name, values in cols.items()}


@dataclass(frozen=True)
class EvalResult:
    status: GateStatus
    scores: Mapping
    groups: Mapping
    provenance: Mapping
    budget_causes: Mapping = field(default_factory=dict)


def _field(name, value):
    """A records field in its exact type: no silent cast (text, booleans or
    fractions as integers, large integers through float)."""
    kind = _DTYPES[name]
    if isinstance(value, np.ndarray):
        allowed = {str: "U", bool: "b", np.float64: "fiu"}.get(kind, "iu")
        if value.ndim != 1 or value.dtype.kind not in allowed:
            raise ValueError(f"records field {name} must be one-dimensional {kind.__name__} (got {value.dtype})")
        items = value.tolist()
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ValueError(f"records field {name} must be a list or array")
    if kind is str:
        ok = all(isinstance(v, str) for v in items)
    elif kind is bool:
        ok = all(isinstance(v, (bool, np.bool_)) for v in items)
    elif kind is np.float64:  # JSON has no NaN: an unfinished game may score null
        items = [math.nan if v is None else v for v in items]
        ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in items)
    else:
        ok = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in items)
    if not ok:
        raise ValueError(f"records field {name} must hold {kind.__name__} values only")
    try:
        return np.array(items, dtype=kind)
    except OverflowError as err:
        raise ValueError(f"records field {name} is out of range") from err


def _check_records(records, manifest):
    """The records' structure against the predeclared schedule; ValueError
    for anything but missing whole blocks (an incomplete group)."""
    if not isinstance(records, Mapping) or set(records) != set(RECORD_FIELDS):
        raise ValueError(f"records need exactly the fields {RECORD_FIELDS}")
    r = {name: _field(name, records[name]) for name in RECORD_FIELDS}
    n = r["game_id"].size
    if any(v.size != n for v in r.values()):
        raise ValueError("records fields differ in length")
    finished = r["finished"] & np.isfinite(r["score"])
    if (finished & ~np.isin(r["score"], (0.0, 0.5, 1.0))).any():
        raise ValueError("a finished game scores 0, 0.5 or 1 for the student")
    layout = {(suite, opponent): (index, arms, pairs, start) for index, suite, opponent, arms, pairs, start in _layout()}
    seen = {}
    for i in range(n):
        block = (str(r["suite"][i]), str(r["opponent"][i]))
        if block not in layout:
            raise ValueError(f"unknown suite/opponent {block}: only the predeclared groups are evaluated")
        index, arms, pairs, start = layout[block]
        arm, bucket, pair, seat = str(r["arm"][i]), str(r["bucket"][i]), int(r["pair"][i]), int(r["student_seat"][i])
        if arm not in arms or bucket not in BUCKETS or not 0 <= pair < pairs or seat not in (0, 1):
            raise ValueError(f"row {i} is outside the schedule")
        key = (block, arm, bucket, pair)
        seen.setdefault(key, []).append(i)
    seed_cache = {}
    for (block, arm, bucket, pair), rows in seen.items():
        if len(rows) != 2 or {int(r["student_seat"][i]) for i in rows} != {0, 1}:
            raise ValueError(f"pair {pair} of {block}/{arm}/{bucket} must be played once on each seat")
        a, b = rows
        index, arms, pairs, start = layout[block]
        for i in rows:
            seat = int(r["student_seat"][i])
            expected = start + ((arms.index(arm) * len(BUCKETS) + BUCKETS.index(bucket)) * pairs + pair) * 2 + seat
            if int(r["game_id"][i]) != manifest.first_game_id + expected:
                raise ValueError(f"row {i} has game id {int(r['game_id'][i])}, the schedule "
                                 f"{manifest.first_game_id + expected}")
        for name in ("student_team", "opponent_team", "seed"):
            if r[name][a] != r[name][b]:
                raise ValueError(f"the two seats of pair {pair} of {block}/{arm}/{bucket} differ in {name}")
        if (index, bucket) not in seed_cache:
            seed_cache[(index, bucket)] = _seeds(manifest.seed, index, bucket, pairs)
        if r["seed"][a] != seed_cache[(index, bucket)][pair]:
            raise ValueError(f"pair {pair} of {block}/{arm}/{bucket} has another seed than the schedule")
    for (block, arm, bucket, pair), rows in seen.items():
        _, arms, _, _ = layout[block]
        for other in arms:
            mirror = seen.get((block, other, bucket, pair))
            if other != arm and mirror is not None:
                for name in ("student_team", "opponent_team", "student_seat"):
                    if sorted(r[name][rows].tolist()) != sorted(r[name][mirror].tolist()):
                        raise ValueError(f"arms differ on mirrored pair {pair} of {block}/{bucket}")
    # Complete blocks must be the predeclared draw exactly (teams, seeds, game ids).
    games = dict(SCHEDULE_TABLE)
    for block, digest in schedule_hashes(r).items():
        suite, opponent, _, _ = block.split("/")
        if (np.array([_block_key(*k) for k in zip(r["suite"], r["opponent"], r["arm"], r["bucket"])]) == block).sum() \
                == _pairs(games[(suite, opponent)]) * 2 and digest != manifest.schedule[block]:
            raise ValueError(f"schedule block {block} differs from the manifest (teams, seeds or game ids)")
    return r


def _pair_scores(r, suite, opponent, arm, bucket):
    """(scores per pair in pair order, complete) of one block."""
    rows = (r["suite"] == suite) & (r["opponent"] == opponent) & (r["arm"] == arm) & (r["bucket"] == bucket)
    games = dict(SCHEDULE_TABLE)[(suite, opponent)]
    pairs = _pairs(games)
    if rows.sum() != pairs * 2:
        return None
    idx = np.flatnonzero(rows)
    idx = idx[np.lexsort((r["student_seat"][idx], r["pair"][idx]))]
    finished = r["finished"][idx] & np.isfinite(r["score"][idx])
    if not finished.all():
        return None
    return r["score"][idx].reshape(pairs, 2).mean(axis=1)


SCHEDULE_TABLE = tuple(((suite, opponent), games) for suite, opponent, _, games in SCHEDULE)


def _interval(stats):
    low, high = np.quantile(stats, (0.025, 0.975))
    return float(low), float(high)


def _rng(group):
    return np.random.default_rng([BOOTSTRAP_SEED, GROUPS.index(group)])


def _stratified(rng, strata, resamples):
    """Resampled means of the pooled pairs, each stratum (bucket) resampled
    within itself so the predeclared 50/50 split is kept."""
    total = sum(s.size for s in strata)
    sums = np.zeros(resamples)
    for s in strata:
        sums += s[rng.integers(0, s.size, size=(resamples, s.size))].sum(axis=1)
    return sums / total


def _h2h(r, group, opponent, manifest):
    blocks = [_pair_scores(r, group, opponent, "pilot", b) for b in BUCKETS]
    if any(x is None for x in blocks):
        return {"status": GateStatus.INCOMPLETE, "point": None, "low": None, "high": None, "pairs": 0}
    scores = np.concatenate(blocks)
    low, high = _interval(_stratified(_rng(group), blocks, manifest.resamples))
    point = float(scores.mean())
    point_bar, low_bar = H2H_BARS[group]
    if point >= point_bar and low > low_bar:
        status = GateStatus.PASS
    elif high <= low_bar:
        status = GateStatus.FAIL
    else:
        status = GateStatus.INCONCLUSIVE
    return {"status": status, "point": point, "low": low, "high": high, "pairs": int(scores.size)}


def _panel(r, group, buckets, bar, manifest):
    """The pilot-minus-control panel difference, equal weights over the
    panel opponents, each opponent's mirrored pairs resampled together."""
    diffs = []
    for opponent in PANEL:
        parts = []
        for b in buckets:
            pilot, control = (_pair_scores(r, "panel", opponent, arm, b) for arm in ARMS)
            if pilot is None or control is None:
                return {"status": GateStatus.INCOMPLETE, "point": None, "low": None, "high": None, "pairs": 0}
            parts.append(pilot - control)
        diffs.append(parts)
    rng = _rng(group)
    stats = np.zeros(manifest.resamples)
    for parts in diffs:
        stats += _stratified(rng, parts, manifest.resamples) / len(PANEL)
    diffs = [np.concatenate(parts) for parts in diffs]
    low, high = _interval(stats)
    point = float(sum(d.mean() for d in diffs) / len(PANEL))
    status = GateStatus.PASS if low > bar else GateStatus.FAIL if high <= bar else GateStatus.INCONCLUSIVE
    return {"status": status, "point": point, "low": low, "high": high, "pairs": int(sum(d.size for d in diffs))}


def evaluate_records(records, manifest, ledgers) -> EvalResult:
    """Fixed groups and gate statuses of the evaluation results. A missing
    or unfinished block makes its group INCOMPLETE; any FAIL, INCONCLUSIVE
    or INCOMPLETE group blocks promotion. ledgers: the (pilot, control)
    arms' own ComputeLedgers (before any shared evaluation charge), checked
    by validate_compute first."""
    if not isinstance(manifest, EvalManifest):
        raise ValueError("evaluate_records needs an EvalManifest")
    pilot, control = ledgers
    validate_compute(pilot, control)
    budget = {}
    for axis in ("cpu_core_seconds", "gpu_seconds"):
        p, c = getattr(pilot, axis), getattr(control, axis)
        budget[axis] = {"pilot": p, "control": c, "relative": 0.0 if p == 0 else (c - p) / p}
    r = _check_records(records, manifest)
    groups = {"h2h_continuation": _h2h(r, "h2h_continuation", "control", manifest),
              "h2h_frozen": _h2h(r, "h2h_frozen", "frozen", manifest),
              "panel": _panel(r, "panel", BUCKETS, PANEL_BAR, manifest),
              "panel_PP": _panel(r, "panel_PP", ("PP",), BUCKET_BAR, manifest),
              "panel_LL": _panel(r, "panel_LL", ("LL",), BUCKET_BAR, manifest)}
    statuses = {g["status"] for g in groups.values()}
    status = next(s for s in (GateStatus.INCOMPLETE, GateStatus.FAIL, GateStatus.INCONCLUSIVE, GateStatus.PASS)
                  if s in statuses or s is GateStatus.PASS)
    scores = {}
    for suite, opponent, arms, _ in SCHEDULE:
        for arm in arms:
            blocks = [_pair_scores(r, suite, opponent, arm, b) for b in BUCKETS]
            scores.setdefault(suite, {})[f"{opponent}/{arm}"] = None if any(x is None for x in blocks) else \
                float(np.concatenate(blocks).mean())
    order = np.argsort(r["game_id"], kind="stable")
    provenance = {"manifest_sha256": hashlib.sha256(_canonical(manifest_mapping(manifest))).hexdigest(),
                  "records_sha256": hashlib.sha256(_canonical({k: [None if isinstance(v, float) and math.isnan(v) else v
                                                                   for v in r[k][order].tolist()]
                                                               for k in RECORD_FIELDS})).hexdigest(),
                  "games": int(r["game_id"].size)}
    return EvalResult(status, scores, groups, provenance, budget)


# ---- the compute ledger ----

@dataclass(frozen=True)
class ComputeLedger:
    """An arm's measured cost (learner ledger.py files): CPU core-seconds
    (getrusage self + children user + system), GPU-seconds (synchronous
    device sections, JIT included) and their breakdown by phase."""
    cpu_core_seconds: float
    gpu_seconds: float
    phases: Mapping
    processes: int = 1

    @staticmethod
    def from_mapping(value):
        if not isinstance(value, Mapping) or set(value) != {"schema", "cpu_core_seconds", "gpu_seconds",
                                                             "processes", "phases"}:
            raise ValueError("a ledger holds exactly schema, cpu_core_seconds, gpu_seconds, processes and phases")
        if type(value["schema"]) is not int or value["schema"] != LEDGER_SCHEMA:
            raise ValueError(f"unsupported ledger schema {value['schema']!r}")
        _uint(value["processes"], "processes")
        if value["processes"] < 1:
            raise ValueError("a ledger records at least one process")
        phases = value["phases"]
        if not isinstance(phases, Mapping):
            raise ValueError("ledger phases must be a mapping")
        sums = {"cpu_core_seconds": 0.0, "gpu_seconds": 0.0}
        clean = {}
        for name, phase in phases.items():
            if not isinstance(name, str) or not isinstance(phase, Mapping) or set(phase) != set(sums):
                raise ValueError(f"ledger phase {name!r} needs exactly {tuple(sums)}")
            clean[name] = {axis: _seconds(phase[axis], f"phase {name} {axis}") for axis in sums}
            for axis in sums:
                sums[axis] += clean[name][axis]
        totals = {axis: _seconds(value[axis], axis) for axis in sums}
        for axis in sums:
            if sums[axis] > totals[axis] * (1 + 1e-9) + 1e-9:
                raise ValueError(f"ledger phases charge more {axis} than the total")
        return ComputeLedger(totals["cpu_core_seconds"], totals["gpu_seconds"],
                             MappingProxyType({k: MappingProxyType(v) for k, v in clean.items()}), int(value["processes"]))

    def to_mapping(self):
        return {"schema": LEDGER_SCHEMA, "cpu_core_seconds": self.cpu_core_seconds, "gpu_seconds": self.gpu_seconds,
                "processes": self.processes, "phases": {k: dict(v) for k, v in self.phases.items()}}


def _seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite nonnegative seconds")
    return float(value)


def validate_compute(pilot, control) -> None:
    """ValueError naming the axis unless the control's measured CPU
    core-seconds and GPU-seconds each lie within 5% of the pilot's:
    |control - pilot| <= 0.05 pilot; a zero pilot axis needs zero."""
    if not isinstance(pilot, ComputeLedger) or not isinstance(control, ComputeLedger):
        raise ValueError("validate_compute needs two ComputeLedgers")
    for axis in ("cpu_core_seconds", "gpu_seconds"):
        p, c = getattr(pilot, axis), getattr(control, axis)
        if p == 0.0 and c != 0.0 or abs(c - p) > COMPUTE_TOLERANCE * p:
            raise ValueError(f"{axis}: control {c:.6g} differs from pilot {p:.6g} by more than 5%")


def charge_shared(pilot, control, shared):
    """Both arms with half of the shared evaluation charged, as phase
    evaluation_share."""
    out = []
    for arm in (pilot, control):
        if "evaluation_share" in arm.phases:
            raise ValueError("the shared evaluation is already charged")
        half = {"cpu_core_seconds": shared.cpu_core_seconds / 2, "gpu_seconds": shared.gpu_seconds / 2}
        phases = {**{k: dict(v) for k, v in arm.phases.items()}, "evaluation_share": half}
        out.append(ComputeLedger.from_mapping({"schema": LEDGER_SCHEMA, "processes": arm.processes, "phases": phases,
                                               "cpu_core_seconds": arm.cpu_core_seconds + half["cpu_core_seconds"],
                                               "gpu_seconds": arm.gpu_seconds + half["gpu_seconds"]}))
    return tuple(out)


# ---- the CLI ----

def _load(path):
    refuse_repository(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"nonfinite JSON {c}")))


def _report(result, pilot, control):
    def plain(group):
        return {k: (v.value if isinstance(v, GateStatus) else v) for k, v in group.items()}
    return {"status": result.status.value, "groups": {k: plain(v) for k, v in result.groups.items()},
            "scores": result.scores, "provenance": result.provenance, "budget_causes": result.budget_causes,
            "compute": {"pilot": pilot.to_mapping(), "control": control.to_mapping()}}


def main(argv: Sequence[str] | None = None) -> int:
    """python -m duoforge_search.expert_eval --manifest M --pilot P --control C
    --baseline B --out O. M: the evaluation manifest; P, C: the arms'
    ledgers; B: {"records": ..., "ledger": ...}, the evaluation games and
    their shared cost. Exit 2 with the cause for a bad manifest, pairing,
    compute match or path; exit 0 with a structured report otherwise, also
    for FAIL, INCONCLUSIVE or INCOMPLETE strength."""
    parser = argparse.ArgumentParser(prog="python -m duoforge_search.expert_eval")
    for flag in ("--manifest", "--pilot", "--control", "--baseline", "--out"):
        parser.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    try:
        refuse_repository(args.out)
        manifest = EvalManifest(**_load(args.manifest))
        pilot, control = (ComputeLedger.from_mapping(_load(p)) for p in (args.pilot, args.control))
        baseline = _load(args.baseline)
        if not isinstance(baseline, dict) or set(baseline) != {"records", "ledger"}:
            raise ValueError("the baseline file holds exactly records and ledger")
        shared = ComputeLedger.from_mapping(baseline["ledger"])
        # The 5% match is on the arms' own use; the shared half is charged for the report only.
        result = evaluate_records(baseline["records"], manifest, (pilot, control))
        pilot, control = charge_shared(pilot, control, shared)
        report = _report(result, pilot, control)
        report["trick_room"] = trick_room_report(baseline["records"])
        data = json.dumps(report, indent=1, sort_keys=True, allow_nan=False)
        with open(args.out, "x", encoding="utf-8") as f:
            f.write(data)
    except (ValueError, TypeError, KeyError, OSError) as err:
        print(f"expert_eval: {err}", file=sys.stderr)
        return 2
    return 0


# ---- the Trick Room diagnostic ----

def tr_moves(context):
    """The move ids of TR_MOVES in context's data (DuoforgeError for a name the data lacks)."""
    from duoforge import data
    return {name: int(data.find(context, data.TABLE_MOVE, name)) for name in TR_MOVES}


class TrickRoomTracker:
    """The Trick Room fields of play_suite's games, in duoforge_learn.luck.Luck's hook form: start(n, seats) for a
    suite of n games (one per environment, the student on seats), before(batch, indices, active, step,
    last_step) after each query and before batch.step(indices), after(batch, dead) after it; fields then holds
    TR_FIELDS -> int64 (n,).

    It reads only the batch's buffers of that query (requests, observations, candidates) and never changes
    them. trick_room_turns of the student's view before and after a turn: 0 to above 0 sets TR, above 1 to 0
    ends it early (1 to 0 is its own end). A change goes to a side only when exactly that side chose a Trick
    Room move (the chosen slot's move id in its own view) on the turn it happened; anything else counts in
    tr_unattributed. A change on a game's last turn is never observed (play_suite queries no more):
    tr_last_turn_choice marks a Trick Room choice left without a later observation."""

    def __init__(self, context):
        from duoforge import _layout
        moves = tr_moves(context)
        self._tr, self._imprison = moves["trickroom"], moves["imprison"]
        self._at_foe = np.array([moves["taunt"], moves["fakeout"]])
        constants = _layout.CONSTANTS
        self._slots, self._move = constants["DUOFORGE_CHOICE_SLOTS"], constants["DUOFORGE_SLOT_MOVE"]
        self._turn_boundary = constants["DUOFORGE_BOUNDARY_TURN"]
        self._no_choice, self._roster = _layout.NO_CHOICE, _layout.MAX_ROSTER
        self.seats = None

    def start(self, n, seats):
        """A new suite of n games, the student on seats (n,)."""
        seats = np.asarray(seats, dtype=np.int64).reshape(-1)
        if seats.size != n or not np.isin(seats, (0, 1)).all():
            raise ValueError("one student seat (0 or 1) per game")
        self.seats = seats
        self._f = {name: np.zeros(n, dtype=np.int64) for name in TR_FIELDS}
        self._started = np.zeros(n, dtype=bool)
        self._dead = np.zeros(n, dtype=bool)
        self._turn = np.full(n, -1, dtype=np.int64)  # the last observation's turn
        self._trick_room = np.zeros(n, dtype=np.int64)
        self._counted = np.full(n, -1, dtype=np.int64)  # the last turn counted in tr_turns
        self._chose = np.full((n, 2), -1, dtype=np.int64)  # the turn a side chose Trick Room on, -1: none open
        self._setter = np.full(n, -1, dtype=np.int64)  # the side that set the running TR, -1 unknown

    @property
    def fields(self):
        out = {name: v.copy() for name, v in self._f.items()}
        out["tr_last_turn_choice"] = (self._chose >= 0).any(axis=1).astype(np.int64)
        return out

    def _knows(self, obs, n):
        """Per side (2, n, 6): the members whose own view lists Trick Room."""
        knows = np.zeros((2, n, self._roster), dtype=bool)
        for p in range(2):
            own = obs["sides"][:, p, p]
            members = own["members"]
            valid = (np.arange(self._roster)[None, :] < own["member_count"][:, None].astype(np.int64))[:, :, None] & \
                (np.arange(4)[None, None, :] < members["move_count"][:, :, None].astype(np.int64))
            knows[p] = ((members["move_ids"] == self._tr) & valid).any(axis=2)
        return knows

    def before(self, batch, indices, active, step, last_step):
        if self.seats is None:
            raise ValueError("start() the suite first")
        n = self.seats.size
        rows = np.arange(n)
        go = np.asarray(active, dtype=bool).reshape(-1) & ~self._dead
        obs = batch.observations
        student = obs[rows, self.seats]
        turn = student["turn"].astype(np.int64)
        trick_room = student["trick_room_turns"].astype(np.int64)
        knows = self._knows(obs, n)
        first = go & ~self._started
        f = self._f
        f["tr_setter_student"][first] = knows[self.seats, rows].any(axis=1)[first]
        f["tr_setter_opponent"][first] = knows[1 - self.seats, rows].any(axis=1)[first]
        self._started |= first

        # The field change since this game's last observation, and who chose Trick Room on that turn.
        seen = go & (self._turn >= 0)
        before = self._trick_room
        sets = seen & (before == 0) & (trick_room > 0)
        ends = seen & (before > 1) & (trick_room == 0)
        change = sets | ends
        chose = (self._chose == self._turn[:, None]) & (self._turn[:, None] >= 0)
        one = chose[:, 0] ^ chose[:, 1]
        side = np.where(chose[:, 0], 0, 1)
        mine = side == self.seats
        f["tr_unattributed"] += change & ~one
        own_set = sets & one & mine
        f["tr_sets_student"] += own_set
        f["tr_first_set_turn_student"] = np.where(own_set & (f["tr_first_set_turn_student"] == 0), self._turn,
                                                  f["tr_first_set_turn_student"])
        f["tr_sets_opponent"] += sets & one & ~mine
        f["tr_reversals_student"] += ends & one & mine & (self._setter == 1 - self.seats)
        self._setter = np.where(sets, np.where(one, side, -1), np.where(ends, -1, self._setter))
        # A choice is open until a change is attributed or a later turn is observed.
        self._chose[change] = -1
        self._chose[go[:, None] & (self._chose >= 0) & (self._chose < turn[:, None])] = -1
        # A turn that begins with TR: its TURN boundary (a same-turn replacement already shows a fresh set).
        count = go & (student["boundary_kind"] == self._turn_boundary) & (trick_room > 0) & (turn != self._counted)
        f["tr_turns"] += count
        self._counted = np.where(count, turn, self._counted)
        self._turn = np.where(go, turn, self._turn)
        self._trick_room = np.where(go, trick_room, self._trick_room)

        # This query's chosen moves: Trick Room choices, and the student's block attempts while TR is inactive.
        indices = np.asarray(indices, dtype=np.int64).reshape(n, 2)
        occupied = []
        for p in range(2):
            occ = obs["sides"][:, p, p]["occupant"].astype(np.int64)
            occupied.append(np.where(occ < self._roster, knows[p][rows[:, None], np.minimum(occ, self._roster - 1)],
                                     False))
        for p in range(2):
            idx = indices[:, p]
            picked = go & (batch.requests["requested"][:, p] != 0) & (idx != self._no_choice) & (idx >= 0)
            cand = batch.candidates[rows, p, np.where(picked, idx, 0)]
            picked &= cand["kind"] == self._slots
            own = obs["sides"][:, p, p]
            student = picked & (self.seats == p) & (trick_room == 0)
            for s in range(2):
                cmd = cand["slots"][:, s]
                occ = own["occupant"][:, s].astype(np.int64)
                slot = cmd["move_slot"].astype(np.int64)
                move_ok = picked & (cmd["kind"] == self._move) & (occ < self._roster) & (slot < 4)
                move = np.where(move_ok, own["members"]["move_ids"][rows, np.minimum(occ, self._roster - 1),
                                                                    np.minimum(slot, 3)].astype(np.int64), -1)
                self._chose[move_ok & (move == self._tr), p] = turn[move_ok & (move == self._tr)]
                target = cmd["target"].astype(np.int64)
                at_setter = (target < 4) & ((target >> 1) == 1 - p) & occupied[1 - p][rows, target & 1]
                imprison = (move == self._imprison) & occupied[p][:, s] & occupied[1 - p].any(axis=1)
                f["tr_blocks_student"] += student & move_ok & ((np.isin(move, self._at_foe) & at_setter) | imprison)

    def after(self, batch, dead):
        """After the step: a game the engine refused is no longer followed."""
        self._dead |= np.asarray(dead, dtype=bool).reshape(-1)


def _rate(scores, rng):
    """{games, score, ci95} of the student's scores; an empty group has no rate."""
    n = scores.size
    if n == 0:
        return {"games": 0, "score": None, "ci95": None}
    means = np.empty(RESAMPLES)
    for start in range(0, RESAMPLES, 100):  # bounded memory for large groups
        stop = min(start + 100, RESAMPLES)
        means[start:stop] = scores[rng.integers(0, n, size=(stop - start, n))].mean(axis=1)
    return {"games": int(n), "score": float(scores.mean()), "ci95": list(_interval(means))}


def _tr_group(r, rows, key):
    def rng(i):
        return np.random.default_rng([BOOTSTRAP_SEED, 0x7452, *key, i])
    s = r["score"]
    sets, first = r["tr_sets_student"], r["tr_first_set_turn_student"]
    opponent_set, opponent_setter = rows & (r["tr_sets_opponent"] > 0), rows & (r["tr_setter_opponent"] > 0)
    turns = first[rows & (sets > 0)]
    return {
        "games": int(rows.sum()),
        "student_setter": _rate(s[rows & (r["tr_setter_student"] > 0)], rng(0)),
        "opponent_setter": _rate(s[opponent_setter], rng(1)),
        "student_sets": {"games_student_setter": int((rows & (r["tr_setter_student"] > 0)).sum()),
                         "games_with_set": int((rows & (sets > 0)).sum()), "sets": int(sets[rows].sum()),
                         "first_turn": {str(int(v)): int((turns == v).sum()) for v in np.unique(turns)}},
        "answers": {"games_opponent_set": int(opponent_set.sum()),
                    "reversals": int(r["tr_reversals_student"][opponent_set].sum()),
                    "games_reversed": int((opponent_set & (r["tr_reversals_student"] > 0)).sum()),
                    "games_opponent_setter": int(opponent_setter.sum()),
                    "blocks": int(r["tr_blocks_student"][opponent_setter].sum()),
                    "games_blocked": int((opponent_setter & (r["tr_blocks_student"] > 0)).sum())},
        "tr_active": _rate(s[rows & (r["tr_turns"] > 0)], rng(2)),
        "tr_inactive": _rate(s[rows & (r["tr_turns"] == 0)], rng(3)),
        "unattributed": int(r["tr_unattributed"][rows].sum()),
    }


def trick_room_report(records) -> dict:
    """The Trick Room diagnostic of the evaluation records, per arm, pooled and per suite: (a) score rate with a
    95% game bootstrap interval where the student's or the opponent's team has a setter; (b) the student's sets
    and first set turns; (c) its reversals of the opponent's TR and block attempts against it; (d) score rate
    with and without an active TR. Finished games only. No gate reads it."""
    names = ("suite", "arm", "score", "finished") + TR_FIELDS
    if not isinstance(records, Mapping) or not set(names) <= set(records):
        raise ValueError(f"the Trick Room report needs the fields {names}")
    r = {name: _field(name, records[name]) for name in names}
    if any(v.size != r["suite"].size for v in r.values()):
        raise ValueError("records fields differ in length")
    done = r["finished"] & np.isfinite(r["score"])
    last = int((done & (r["tr_last_turn_choice"] > 0)).sum())
    suites = tuple(dict.fromkeys(suite for suite, _, _, _ in SCHEDULE))
    arms = {}
    for a, arm in enumerate(ARMS):
        rows = done & (r["arm"] == arm)
        arms[arm] = {"all": _tr_group(r, rows, (a, len(suites))),
                     "by_suite": {suite: _tr_group(r, rows & (r["suite"] == suite), (a, i))
                                  for i, suite in enumerate(suites)}}
    note = (f"Trick Room diagnostic, no gate. A field change on a game's last turn is not observed: {last} games "
            f"chose Trick Room on their last turn and are counted without that turn's effect. A setter is a member "
            f"of the whole team sheet, brought or not.")
    return {"note": note, "last_turn_unobserved_games": last, "arms": arms}


if __name__ == "__main__":
    sys.exit(main())
