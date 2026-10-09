"""The P1 honest teacher (plan C3, decision 0024). No battle rules here.

The teacher labels admitted learner roots with the honest search's mixed
rule X over the K own candidates, the student's raw action always among
them. Its foe model is its own frozen network; only C builds worlds.
"""
import dataclasses
from dataclasses import dataclass, field
import hashlib
import json
import math
from types import MappingProxyType
from typing import Mapping

import numpy as np

import duoforge
from duoforge import _layout

from . import lookahead, matrix, ticks
from .errors import SearchError
from .expert_data import (DECISION_BOUNDARIES, KEY_VERSION, MASS_TOLERANCE, DecisionKey, ExpertRow, LabelCursor,
                          RowStatus, SparsePolicy, cursor_bytes, restore_cursor, selection_word, validate_manifest,
                          validate_row)
from .expert_data import _canonical, _object, _sha
from .honest import Unreconstructible, visible_causes

C = _layout.CONSTANTS
K = 8  # own candidates of a label (P1 fixed contract)
JOINT = lookahead.PAIRS  # full joint pair ids, i0 * 32 + i1
AUDIT_THRESHOLD = (1 << 64) // 100  # the K+1 audit: audit word below it (1%)


@dataclass(frozen=True)
class CandidateSet:
    """The own candidates in prior-rank order with the raw action included:
    ids (K',) int64, the raw action's position, and the candidate it
    displaced (None when it was already present or there was room)."""
    ids: np.ndarray
    raw_index: int
    displaced: int | None


def _legal(mask):
    mask = np.asarray(mask)
    if mask.dtype != np.bool_ or mask.size != JOINT:
        raise ValueError(f"a legal mask needs {JOINT} booleans")
    return mask.reshape(-1)


def _joint_id(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or not 0 <= value < JOINT:
        raise ValueError(f"{name} must be a joint pair id in [0, {JOINT})")
    return int(value)


def include_student(candidates, raw_action, legal_mask, *, k=K) -> CandidateSet:
    """The candidates with the student's raw action: kept where present,
    appended while fewer than K, otherwise displacing the lowest-ranked
    candidate (the last, ties already broken by lookahead.select)."""
    if k != K:
        raise ValueError(f"P1 labels keep exactly K = {K} candidates")
    return _with_raw(candidates, raw_action, legal_mask, k)


def _with_raw(candidates, raw_action, legal_mask, k):
    legal = _legal(legal_mask)
    ids = np.asarray(candidates)
    if ids.ndim != 1 or not 1 <= ids.size <= k or not np.issubdtype(ids.dtype, np.integer):
        raise ValueError(f"candidates must be 1 to {k} integer joint ids")
    ids = ids.astype(np.int64)
    if len(np.unique(ids)) != ids.size or (ids < 0).any() or (ids >= JOINT).any() or not legal[ids].all():
        raise ValueError("candidates must be distinct legal joint ids")
    raw = _joint_id(raw_action, "raw_action")
    if not legal[raw]:
        raise ValueError("the raw action must be legal")
    where = np.flatnonzero(ids == raw)
    if where.size:
        return CandidateSet(ids, int(where[0]), None)
    if ids.size < k:
        return CandidateSet(np.append(ids, raw), int(ids.size), None)
    displaced = int(ids[-1])
    return CandidateSet(np.append(ids[:-1], raw), k - 1, displaced)


def full_target(policy: SparsePolicy, legal_mask) -> np.ndarray:
    """The sparse teacher distribution at its (1024,) joint ids, zero
    elsewhere; never renormalized over the candidates."""
    legal = _legal(legal_mask)
    if not isinstance(policy, SparsePolicy):
        raise ValueError("full_target needs a SparsePolicy")
    ids, probs = np.asarray(policy.ids), np.asarray(policy.probs)
    if ids.dtype != np.int64 or probs.dtype != np.float64 or ids.ndim != 1 or ids.shape != probs.shape \
            or not 1 <= ids.size <= K:
        raise ValueError(f"a sparse policy holds 1 to {K} int64 ids with float64 mass")
    if len(np.unique(ids)) != ids.size or (ids < 0).any() or (ids >= JOINT).any() or not legal[ids].all():
        raise ValueError("sparse ids must be distinct legal joint ids")
    if not np.isfinite(probs).all() or (probs < 0).any() or abs(float(probs.sum()) - 1.0) > MASS_TOLERANCE:
        raise ValueError("sparse mass must be finite, nonnegative and sum to 1")
    full = np.zeros(JOINT, np.float64)
    full[ids] = probs
    return full


@dataclass(frozen=True)
class TeacherConfig:
    """The teacher's search and key configuration. It must equal the data
    manifest's (seed, K, M, W, lambda, capacity; P1 pins 8, 8, 16, 0.5 and
    1024) and the search it labels with, search seed included: build it
    with from_manifest."""
    seed: int  # the manifest seed of the world, X and audit key words
    k: int = K
    m: int = 8
    worlds: int = 16
    lam: float = 0.5
    capacity: int = 1024
    budget: matrix.WorkBudget = field(default_factory=matrix.WorkBudget)
    audit_threshold: int = AUDIT_THRESHOLD
    search_seed: int = lookahead.SEARCH_SEED  # the search's belief and leaf seed
    key_version: int = KEY_VERSION

    @classmethod
    def from_manifest(cls, manifest, **overrides):
        """The configuration a manifest pins; overrides for budget, audit rate
        or search seed (any other change is refused by check_manifest)."""
        validate_manifest(manifest)
        tc = manifest.teacher_config
        fields = {"seed": manifest.seed, "k": tc["k"], "m": tc["m"], "worlds": tc["worlds"], "lam": tc["lam"],
                  "capacity": manifest.capacity}
        return cls(**{**fields, **overrides})

    def check_manifest(self, manifest):
        """ValueError unless the key seed and the search sizes are the manifest's."""
        validate_manifest(manifest)
        tc = manifest.teacher_config
        if (self.seed, self.k, self.m, self.worlds, float(self.lam), self.capacity) != \
                (manifest.seed, tc["k"], tc["m"], tc["worlds"], float(tc["lam"]), manifest.capacity):
            raise ValueError("the teacher configuration differs from the data manifest")

    def __post_init__(self):
        for name in ("seed", "k", "m", "worlds", "capacity", "search_seed"):
            value = getattr(self, name)
            low = 0 if name in ("seed", "search_seed") else 1
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value < 1 << 64:
                raise ValueError(f"teacher {name} must be an integer of at least {low}")
        if self.k > K:
            raise ValueError(f"teacher k must be at most {K}")
        if isinstance(self.lam, bool) or not isinstance(self.lam, (int, float)) or not 0 <= self.lam <= 1:
            raise ValueError("teacher lambda must lie in [0, 1]")
        if not isinstance(self.budget, matrix.WorkBudget):
            raise ValueError("teacher budget must be a matrix.WorkBudget")
        if isinstance(self.audit_threshold, bool) or not isinstance(self.audit_threshold, int) or \
                not 0 <= self.audit_threshold <= 1 << 64:
            raise ValueError("the audit threshold must lie in [0, 2**64]")
        if type(self.key_version) is not int or self.key_version != KEY_VERSION:
            raise ValueError(f"unsupported key version {self.key_version!r}")

    def check(self, search):
        """ValueError unless search runs this configuration with rule X."""
        got = (search.k, search.m, search.s, search.lam, search.capacity, search.rule, search.seed)
        if got != (self.k, self.m, self.worlds, float(self.lam), self.capacity, "mix", self.search_seed):
            raise ValueError(f"the search {got} does not run the teacher configuration")


@dataclass(frozen=True)
class TeacherDecision:
    """What a learner root executes and stores: the action, the collector's
    pre-drawn raw action, the behavior log-likelihood of the action, the
    sparse target (TARGET only), the status with its fallback cause, solver
    work, audit and the world/table/label digests."""
    action: int
    raw_action: int
    behavior_logp: float
    target: SparsePolicy | None
    status: RowStatus
    cause: str | None
    work: Mapping = field(default_factory=dict)
    audit: Mapping = field(default_factory=dict)
    world_digest: str | None = None
    table_digest: str | None = None
    label_digest: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "work", MappingProxyType(dict(self.work)))
        object.__setattr__(self, "audit", MappingProxyType(dict(self.audit)))


def learner_seat(game_id: int) -> int:
    """The learner's seat of a logical game, alternating by game id."""
    if isinstance(game_id, bool) or not isinstance(game_id, int) or not 0 <= game_id < 1 << 64:
        raise ValueError("game_id must be a uint64")
    return game_id % 2


def _uniform(word):
    """A uniform double in [0, 1) from the top 53 bits of a key word."""
    return (word >> 11) * 2.0 ** -53


def _digest(*arrays):
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(a.dtype.str.encode("ascii") + repr(a.shape).encode("ascii") + a.tobytes())
    return h.hexdigest()


def observe(search, roots, envs, seats):
    """Records the public history (team preview, turn start) of each learner
    seat from its current request. The collector calls it on EVERY learner
    request of a tick, raw or labeled, before label_decision."""
    envs, seats = np.asarray(envs, np.int64), np.asarray(seats, np.int64)
    if envs.ndim != 1 or envs.shape != seats.shape or len(set(envs.tolist())) != envs.size or \
            (envs < 0).any() or (envs >= roots.envs).any() or not np.isin(seats, [0, 1]).all():
        raise ValueError("observe needs unique valid environments with one seat each")
    if not envs.size:
        return
    players = np.zeros(roots.envs, np.uint32)
    players[envs] = seats
    records, statuses = roots.public(players)
    for e, p in zip(envs.tolist(), seats.tolist()):
        history = search._observe(roots, e, p, records[e:e + 1].reshape(()).copy(), statuses[e])
        history["observed"] = int(roots.requests[e, p]["epoch"])
        if int(roots.requests[e, p]["boundary_kind"]) == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
            history["preview_observed"] = True  # even when its record was refused


def _costs():
    return {k: 0.0 for k in ("public_records", "world_builds", "team_head", "leaves", "network", "solve")}


def _work(ledger, **extra):
    c = ledger.consumed
    return {"float_pivots": c.float_pivots, "exact_pivots": c.exact_pivots, "exact_ops": c.exact_ops,
            "max_bits": c.max_bits, "status": ledger.status.value, **extra}


def _check_search(search, config, manifest):
    config.check(search)
    config.check_manifest(manifest)
    if search.table_info["sha256"] != manifest.belief_hash:
        raise ValueError("the search's spread table (belief) differs from the manifest's belief_hash")


@dataclass
class _Root:
    """A validated admitted root between the teacher's phases."""
    e: int
    p: int
    key: DecisionKey
    raw_action: int
    raw_logp: float
    logp: np.ndarray
    mask: np.ndarray
    cand: CandidateSet
    history: dict
    record: np.ndarray
    status: int
    world_key: int
    excluded: object


def _root(search, roots, encoded, public, *, env, seat, key, raw_action, raw_logp, config, manifest):
    """The checks and candidates of one admitted root; encoded and public are
    the roots' query_encoded and public outputs of this tick."""
    e, p = int(env), int(seat)
    if not 0 <= e < roots.envs or p not in (0, 1) or not roots.requests[e, p]["requested"]:
        raise ValueError("label_decision needs a requested learner seat")
    if not isinstance(key, DecisionKey) or key.seat != p or key.request_epoch != int(roots.requests[e, p]["epoch"]):
        raise ValueError("the decision key must name this seat and request epoch")
    if not manifest.first_game_id <= key.game_id < manifest.first_game_id + manifest.game_count or \
            learner_seat(key.game_id) != p:
        raise ValueError("the decision key must name a manifest game and its learner seat")
    boundary = lookahead._BOUNDARIES[int(roots.requests[e, p]["boundary_kind"])]
    if boundary not in DECISION_BOUNDARIES:
        raise ValueError(f"only TURN/REPLACEMENT/PIVOT roots are labeled (got {boundary})")
    raw_logp = float(raw_logp)
    if not math.isfinite(raw_logp) or raw_logp > 0:
        raise ValueError("raw_logp must be a finite log-probability")
    history = search.history.get(roots, {}).get((e, p))
    if history is None or history.get("observed") != key.request_epoch or history.get("episode") != roots.episode(e):
        raise ValueError("observe() must record this request before label_decision")
    if not history.get("preview_observed"):
        raise ValueError("observe() missed this game's team preview: a collector error, not a public refusal")
    obs, slots, pairs = encoded
    mask = pairs[e, p]
    if int(mask.sum()) < 2:
        raise ValueError("a labeled root needs at least two legal pairs")
    pp, _, _ = search._policy(obs[e:e + 1, p], slots[e:e + 1, p], pairs[e:e + 1, p])
    candidates, _ = lookahead.select(pp[0], mask, config.k)
    cand = _with_raw(candidates, raw_action, mask, config.k)
    records, statuses = public
    return _Root(e, p, key, int(raw_action), raw_logp, pp[0], mask, cand, history,
                 records[e:e + 1].reshape(()).copy(), int(statuses[e]), selection_word(key, config.seed, domain="world"),
                 None if search.exclude_teams is None else search.exclude_teams[e])


def _worlds(search, roots, r, costs):
    """The root's sampled worlds and weights (Unreconstructible: a public refusal)."""
    if r.status == C["DUOFORGE_E_UNSUPPORTED"]:
        raise Unreconstructible("+".join(visible_causes(roots, r.e, r.p)) or "public_record_unsupported")
    if r.status != 0:
        raise SearchError(f"public record refused: {duoforge.status_name(r.status)}")
    hypotheses, weights, _, _, _ = search._hypotheses(r.record, roots.observations[r.e, r.p], r.history, r.world_key,
                                                      r.excluded, costs)
    return hypotheses, weights


def _fallback(r, status, cause, ledger, hypotheses=None, weights=None):
    world = None if hypotheses is None else _digest(hypotheses, weights)
    return TeacherDecision(r.raw_action, r.raw_action, r.raw_logp, None, status, cause, _work(ledger), {}, world,
                           None, None)


def _target(config, r, result, hypotheses, weights, ledger, audit):
    """TARGET: X's play distribution (sub-floor mass removed, renormalized), the X-word draw, the digests."""
    tables = np.asarray(result["tables"], np.float64)
    world_digest = _digest(hypotheses, weights)
    table_digest = _digest(tables, np.asarray(result["foe_pairs"], np.int64), np.asarray(result["foe_probs"]))
    pi = np.asarray(result["pi_X"], np.float64)
    play = np.where(pi < matrix.PROBABILITY_FLOOR, 0.0, pi)
    play = play / math.fsum(play.tolist())
    index = matrix.draw(pi, np.arange(r.cand.ids.size), _uniform(selection_word(r.key, config.seed, domain="X")))
    action, logp = int(r.cand.ids[index]), math.log(float(play[index]))
    label_digest = _digest(r.cand.ids, play, np.array([action], np.int64), np.array([logp]))
    return TeacherDecision(action, r.raw_action, logp, SparsePolicy(r.cand.ids.copy(), play), RowStatus.TARGET,
                           None, _work(ledger, leaves=int(tables.size)), audit, world_digest, table_digest, label_digest)


def _audited(config, r):
    return selection_word(r.key, config.seed, domain="audit") < config.audit_threshold


def _audit_ids(config, r):
    """The K+1 audit's candidates: the next one added, the raw action kept."""
    return _with_raw(lookahead.select(r.logp, r.mask, config.k + 1)[0], r.raw_action, r.mask, config.k + 1).ids


def _audit_report(config, r, ids, result, primary, weights, action, ledger):
    index = matrix.draw(np.asarray(result["pi_X"]), np.arange(ids.size),
                        _uniform(selection_word(r.key, config.seed, domain="X")))
    return {"selected": True, "status": "ok", "candidates": ids.tolist(), "action": int(ids[index]),
            "action_changed": int(ids[index]) != action, "value": float(result["value"]),
            "value_delta": float(result["value"]) - float(primary["value"]),
            "certificate": float(_certificate(result, weights)), "primary_certificate": float(_certificate(primary, weights)),
            "leaves": int(np.asarray(result["tables"]).size), "work": _work(ledger)}


def _audit_exhausted(ids, err, ledger):
    return {"selected": True, "status": f"exhausted:{err.status.value}", "candidates": ids.tolist(),
            "work": _work(ledger)}


def label_decision(search, roots, *, env, seat, key, raw_action, raw_logp, last_step, config,
                   manifest) -> TeacherDecision:
    """The teacher's decision for an admitted learner root (TURN, REPLACEMENT
    or PIVOT with >= 2 legal pairs) whose ticket was reserved before this
    call, after observe() recorded its request. TARGET: the action drawn
    from X over the candidates (raw action included) with the key's X word,
    its exact play probability as the behavior likelihood. PUBLIC_REFUSAL (no
    supported public reconstruction) and WORK_EXHAUSTED (the work budget):
    the pre-drawn raw action with raw_logp and a named cause. Any other
    failure raises, as does a collector that never observed the game's
    team preview. The per-root reference path; label_tick shares a tick's
    value calls."""
    _check_search(search, config, manifest)
    if not 0 <= int(env) < roots.envs or int(seat) not in (0, 1):
        raise ValueError("label_decision needs a requested learner seat")
    encoded = roots.query_encoded(search.encoder, search.ext_supported)
    players = np.zeros(roots.envs, np.uint32)
    players[int(env)] = int(seat)
    r = _root(search, roots, encoded, roots.public(players), env=env, seat=seat, key=key, raw_action=raw_action,
              raw_logp=raw_logp, config=config, manifest=manifest)
    ledger = matrix.WorkLedger(config.budget)
    costs = _costs()
    search.last = []
    hypotheses = weights = None
    try:
        hypotheses, weights = _worlds(search, roots, r, costs)
        result = search._decision(r.p, r.world_key, r.cand.ids, np.zeros(r.cand.ids.size), weights, bool(last_step),
                                  costs, budget=ledger)
    except Unreconstructible as err:
        return _fallback(r, RowStatus.PUBLIC_REFUSAL, f"public:{err}", ledger)
    except matrix.WorkBudgetExceeded as err:
        return _fallback(r, RowStatus.WORK_EXHAUSTED, f"work:{err.status.value}", ledger, hypotheses, weights)
    audit = {"selected": False}
    if _audited(config, r):
        action = _target(config, r, result, hypotheses, weights, ledger, audit).action
        ids = _audit_ids(config, r)
        audit_ledger = matrix.WorkLedger(config.budget)
        try:
            audited = search._decision(r.p, r.world_key, ids, np.zeros(ids.size), weights, bool(last_step), _costs(),
                                       budget=audit_ledger)
            audit = _audit_report(config, r, ids, audited, result, weights, action, audit_ledger)
        except matrix.WorkBudgetExceeded as err:
            audit = _audit_exhausted(ids, err, audit_ledger)
    return _target(config, r, result, hypotheses, weights, ledger, audit)


def _certificate(result, weights):
    tables = np.asarray(result["tables"], np.float64)
    return matrix.bayes_certify(tables, weights, np.asarray(result["x"]), [np.asarray(y) for y in result["ys"]])


@dataclass(frozen=True)
class TickRoot:
    """One admitted root of a tick: label_decision's per-root arguments."""
    env: int
    seat: int
    key: DecisionKey
    raw_action: int
    raw_logp: float


def label_tick(search, roots, tick, *, last_step, config, manifest, dedup=True, stats=None) -> tuple:
    """label_decision for every admitted root of one logical tick, in input
    order, with the tick's value calls shared (stage 3 P2): the encoded rows
    and public records are read once; per root, in input order, its worlds
    are built and its primary decision prepared, then its K+1 audit on the
    same worlds, before the next root reuses them; all open leaves go
    through one deduplicated TickTable in fixed-capacity calls; then every
    decision is finished with its own ledger. Per-root bytes equal
    label_decision's where value bits do not depend on a row's position,
    neighbours or padding at the capacity (rowprobe, P2 Task 1: shown for
    params-49333 on the owner's CPU and GPU; re-probe for another checkpoint
    or machine). A tick above ticks.MAX_ROWS unique rows raises ValueError,
    and any other failure of one root stops the whole tick. dedup=False
    and stats (a dict filled with the table's counters) serve the P2
    measurement."""
    _check_search(search, config, manifest)
    tick = tuple(tick)
    if not all(isinstance(x, TickRoot) for x in tick):
        raise ValueError("label_tick needs TickRoot entries")
    envs = [int(x.env) for x in tick]
    if len(set(envs)) != len(envs) or any(not 0 <= e < roots.envs for e in envs):
        raise ValueError("label_tick needs one admitted root per environment")
    encoded = roots.query_encoded(search.encoder, search.ext_supported)
    players = np.zeros(roots.envs, np.uint32)
    for x in tick:
        if int(x.seat) not in (0, 1):
            raise ValueError("label_decision needs a requested learner seat")
        players[int(x.env)] = int(x.seat)
    public = roots.public(players)
    search.last = []
    table = ticks.TickTable(search._rows.shape[1], dedup=dedup)
    # Every root is checked before any root builds worlds: a bad root stops the tick before work is spent.
    checked = [_root(search, roots, encoded, public, env=x.env, seat=x.seat, key=x.key, raw_action=x.raw_action,
                     raw_logp=x.raw_logp, config=config, manifest=manifest) for x in tick]
    states = []
    for r in checked:
        costs = _costs()
        try:
            hypotheses, weights = _worlds(search, roots, r, costs)
        except Unreconstructible as err:
            states.append((r, None, err))
            continue
        primary = search._prepare(r.p, r.world_key, r.cand.ids, weights, bool(last_step), costs)
        audit = None
        if _audited(config, r):
            ids = _audit_ids(config, r)
            request = search._prepare(r.p, r.world_key, ids, weights, bool(last_step), _costs())
            audit = (ids, request, table.add(request))
        states.append((r, (hypotheses, weights, primary, table.add(primary), costs, audit), None))
    values = table.evaluate(search.model, search.params, search._rows)
    if stats is not None:
        stats.update(leaves=table.leaves, open_leaves=table.open_leaves, unique=table.unique,
                     value_calls=-(-table.unique // search._rows.shape[0]))
    out = []
    for r, prepared, refusal in states:
        ledger = matrix.WorkLedger(config.budget)
        if prepared is None:
            out.append(_fallback(r, RowStatus.PUBLIC_REFUSAL, f"public:{refusal}", ledger))
            continue
        hypotheses, weights, primary, index, costs, audit = prepared
        try:
            result = search._finish(primary, ticks.scatter(index, values), np.zeros(r.cand.ids.size), costs,
                                    budget=ledger)
        except matrix.WorkBudgetExceeded as err:
            out.append(_fallback(r, RowStatus.WORK_EXHAUSTED, f"work:{err.status.value}", ledger, hypotheses, weights))
            continue
        report = {"selected": False}
        if audit is not None:
            ids, request, audit_index = audit
            action = _target(config, r, result, hypotheses, weights, ledger, report).action
            audit_ledger = matrix.WorkLedger(config.budget)
            try:
                audited = search._finish(request, ticks.scatter(audit_index, values), np.zeros(ids.size), _costs(),
                                         budget=audit_ledger)
                report = _audit_report(config, r, ids, audited, result, weights, action, audit_ledger)
            except matrix.WorkBudgetExceeded as err:
                report = _audit_exhausted(ids, err, audit_ledger)
        out.append(_target(config, r, result, hypotheses, weights, ledger, report))
    return tuple(out)


_RAW_STATUSES = (RowStatus.UNSELECTED, RowStatus.CAP_RAW, RowStatus.FORCED)


def raw_decision(status, raw_action, raw_logp, *, legal_count) -> TeacherDecision:
    """A requested learner root that runs no search: UNSELECTED, CAP_RAW (a
    selected root without a ticket) or FORCED (one legal action, logp 0).
    It executes the collector's pre-drawn raw action; no world, network or
    solver is touched."""
    if status not in _RAW_STATUSES:
        raise ValueError(f"raw_decision covers {[s.value for s in _RAW_STATUSES]} (got {status!r})")
    if isinstance(legal_count, bool) or not isinstance(legal_count, int) or not 1 <= legal_count <= JOINT:
        raise ValueError("legal_count must count the root's legal actions")
    raw_logp = float(raw_logp)
    if not math.isfinite(raw_logp) or raw_logp > 0:
        raise ValueError("raw_logp must be a finite log-probability")
    if (status is RowStatus.FORCED) != (legal_count == 1) or (status is RowStatus.FORCED and raw_logp != 0.0):
        raise ValueError("a root is FORCED exactly when it has one legal action, with logp 0")
    if isinstance(raw_action, bool) or not isinstance(raw_action, (int, np.integer)) or raw_action < 0:
        raise ValueError("raw_action must be an action index")
    return TeacherDecision(int(raw_action), int(raw_action), raw_logp, None, status, None)


@dataclass(frozen=True)
class StepData:
    """The collector's facts of one learner row (acting or waiting)."""
    key: DecisionKey
    logical_tick: int
    boundary: str
    obs: np.ndarray
    slots: np.ndarray
    legal_mask: np.ndarray
    requested: bool
    reward: float
    done: bool
    collector_value: float
    bootstrap: float


def teacher_row(decision, step, manifest):
    """The ExpertRow of a learner step: a waiting step (decision None) is
    UNREQUESTED; a requested step carries its decision's action, likelihood,
    target, status and cause; the collector's reward, done, value and
    bootstrap are kept as given. Checked by validate_row."""
    if not isinstance(step, StepData):
        raise ValueError("teacher_row needs StepData")
    if not isinstance(step.key, DecisionKey) or step.key.seat != learner_seat(step.key.game_id):
        raise ValueError("expert rows hold the learner seat of their game only")
    if (decision is None) == bool(step.requested):
        raise ValueError("a requested step needs a decision and a waiting step none")
    if decision is None:
        fields = {"sparse_policy": None, "status": RowStatus.UNREQUESTED, "raw_action": None, "action": None,
                  "behavior_logp": None, "admitted": False, "cause": None, "work": {}, "audit": {}}
    else:
        if not isinstance(decision, TeacherDecision):
            raise ValueError("teacher_row needs a TeacherDecision")
        admitted = decision.status in (RowStatus.TARGET, RowStatus.PUBLIC_REFUSAL, RowStatus.WORK_EXHAUSTED)
        fields = {"sparse_policy": decision.target, "status": decision.status, "raw_action": decision.raw_action,
                  "action": decision.action, "behavior_logp": decision.behavior_logp, "admitted": admitted,
                  "cause": decision.cause, "work": _counts(decision.work), "audit": decision.audit}
    row = ExpertRow(key=step.key, logical_tick=step.logical_tick, boundary=step.boundary, obs=step.obs,
                    slots=step.slots, legal_mask=step.legal_mask, requested=bool(step.requested),
                    acting=bool(step.requested), learner=True, value_mask=True, reward=step.reward, done=step.done,
                    collector_value=step.collector_value, bootstrap=step.bootstrap, **fields)
    validate_row(row, manifest)
    return row


def _counts(work):
    return {k: int(v) for k, v in work.items() if k != "status"}




CHECKPOINT_VERSION = 1
_CHECKPOINT_FIELDS = {"version", "manifest_sha256", "config", "key_version", "search", "envs", "cursor",
                      "histories", "content_sha256"}
_HISTORY_FIELDS = {"env", "seat", "episode", "observed", "preview_observed", "preview", "turn_start"}


def _params_digest(params):
    """SHA-256 over every parameter array, in sorted key order."""
    h = hashlib.sha256()

    def walk(value, path):
        if isinstance(value, Mapping):
            for k in sorted(value):
                walk(value[k], f"{path}/{k}")
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                walk(v, f"{path}/{i}")
        else:
            a = np.ascontiguousarray(np.asarray(value))
            h.update(path.encode("utf-8") + a.dtype.str.encode("ascii") + repr(a.shape).encode("ascii") + a.tobytes())

    walk(params, "")
    return h.hexdigest()


def _search_identity(search):
    """What a resumed search must share beyond the configuration: the
    network weights, the spread table and the per-environment exclusions."""
    excluded = None if search.exclude_teams is None else \
        [None if x is None else int(x) for x in search.exclude_teams]
    return {"params_sha256": _params_digest(search.params), "table_sha256": search.table_info["sha256"],
            "exclude_teams": excluded}


def decision_bytes(decision) -> bytes:
    """Canonical bytes of a TeacherDecision (action, likelihood, target,
    status, cause, work, audit, digests) for determinism comparisons."""
    if not isinstance(decision, TeacherDecision):
        raise ValueError("decision_bytes needs a TeacherDecision")
    return _canonical(decision)


def _config(config):
    return dataclasses.asdict(config)


def teacher_checkpoint(search, roots, cursor, config, manifest) -> bytes:
    """The teacher's resume state beside the label cursor: every recorded
    public history (episode, team preview, turn start, observed request) of
    roots, bound to the manifest, the teacher configuration and the key
    version. The collector restores its battles; restore_teacher the rest."""
    config.check(search)
    validate_manifest(manifest)
    if not isinstance(cursor, LabelCursor):
        raise ValueError("teacher_checkpoint needs the label cursor")
    histories = []
    for (e, p), h in sorted(search.history.get(roots, {}).items()):
        histories.append({"env": int(e), "seat": int(p), "episode": int(h["episode"]),
                          "observed": h.get("observed"), "preview_observed": bool(h.get("preview_observed")),
                          "preview": h["preview"].tobytes().hex() if "preview" in h else None,
                          "turn_start": h["turn_start"].tobytes().hex() if "turn_start" in h else None})
    content = {"version": CHECKPOINT_VERSION, "manifest_sha256": _sha(manifest), "config": _config(config),
               "key_version": KEY_VERSION, "search": _search_identity(search), "envs": int(roots.envs),
               "cursor": cursor_bytes(cursor, manifest).decode("ascii"), "histories": histories}
    return _canonical({**content, "content_sha256": _sha(content)})


def _record(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("a checkpoint record must be hex text")
    raw = bytes.fromhex(value)
    if len(raw) != _layout.PUBLIC_STATE.itemsize:
        raise ValueError("a checkpoint record does not have the public record size")
    return np.frombuffer(raw, _layout.PUBLIC_STATE).reshape(()).copy()


def restore_teacher(search, roots, data, config, manifest) -> LabelCursor:
    """Restores teacher_checkpoint into a fresh search for the restored
    roots and returns the label cursor (pending reservations kept). Any
    mismatch of manifest, configuration, key version, environments or
    episodes, and any partial or altered checkpoint, raises."""
    config.check(search)
    validate_manifest(manifest)
    if search.history.get(roots):
        raise ValueError("restore_teacher needs a fresh search without history for these roots")
    try:
        state = json.loads(data, object_pairs_hook=_object)
    except (TypeError, ValueError) as err:
        raise ValueError("the teacher checkpoint is not complete JSON") from err
    if not isinstance(state, dict) or set(state) != _CHECKPOINT_FIELDS:
        raise ValueError("invalid teacher checkpoint fields")
    content = {k: v for k, v in state.items() if k != "content_sha256"}
    if state["content_sha256"] != _sha(content):
        raise ValueError("teacher checkpoint integrity mismatch")
    if state["version"] != CHECKPOINT_VERSION or state["key_version"] != KEY_VERSION:
        raise ValueError("unsupported teacher checkpoint or key version")
    if state["manifest_sha256"] != _sha(manifest) or state["config"] != json.loads(_canonical(_config(config))):
        raise ValueError("the teacher checkpoint belongs to another manifest or configuration")
    if state["search"] != json.loads(_canonical(_search_identity(search))):
        raise ValueError("the teacher checkpoint was taken with other weights, spread table or exclusions")
    if state["envs"] != roots.envs:
        raise ValueError("the teacher checkpoint was taken on another number of environments")
    cursor = restore_cursor(state["cursor"].encode("ascii"), manifest)
    restored = {}
    for h in state["histories"]:
        if not isinstance(h, dict) or set(h) != _HISTORY_FIELDS:
            raise ValueError("invalid teacher history fields")
        e, p = h["env"], h["seat"]
        if type(e) is not int or type(p) is not int or not 0 <= e < roots.envs or p not in (0, 1) or (e, p) in restored:
            raise ValueError("invalid teacher history seat")
        if h["episode"] != roots.episode(e):
            raise ValueError("the restored roots are in another episode than the checkpoint")
        if h["observed"] is not None and type(h["observed"]) is not int:
            raise ValueError("invalid observed request epoch")
        if type(h["preview_observed"]) is not bool:
            raise ValueError("invalid preview flag")
        entry = {"episode": h["episode"]}
        if h["observed"] is not None:
            entry["observed"] = h["observed"]
        if h["preview_observed"]:
            entry["preview_observed"] = True
        for name in ("preview", "turn_start"):
            record = _record(h[name])
            if record is not None:
                entry[name] = record
        restored[(e, p)] = entry
    search.history.setdefault(roots, {}).update(restored)
    return cursor
