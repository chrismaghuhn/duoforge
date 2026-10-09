"""The P1 honest teacher (plan C3, decision 0024). No battle rules here.

The teacher labels admitted learner roots with the honest search's mixed
rule X over the K own candidates, the student's raw action always among
them. Its foe model is its own frozen network; only C builds worlds.
"""
from dataclasses import dataclass, field
import hashlib
import math
from types import MappingProxyType
from typing import Mapping

import numpy as np

import duoforge
from duoforge import _layout

from . import lookahead, matrix
from .errors import SearchError
from .expert_data import (DECISION_BOUNDARIES, KEY_VERSION, MASS_TOLERANCE, DecisionKey, RowStatus, SparsePolicy,
                          selection_word)
from .honest import Unreconstructible

C = _layout.CONSTANTS
K = 8  # own candidates of a label (P1 fixed contract)
JOINT = lookahead.PAIRS  # full joint pair ids, i0 * 32 + i1


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
    """The teacher's search and key configuration, checked against the
    search it labels with. P1 pins K = M = 8, W = 16, lambda 0.5 and
    capacity 1024 through the data manifest; tests may use smaller searches."""
    seed: int  # the manifest seed of the world, X and audit key words
    k: int = K
    m: int = 8
    worlds: int = 16
    lam: float = 0.5
    capacity: int = 1024
    budget: matrix.WorkBudget = field(default_factory=matrix.WorkBudget)
    key_version: int = KEY_VERSION

    def __post_init__(self):
        for name in ("seed", "k", "m", "worlds", "capacity"):
            value = getattr(self, name)
            low = 0 if name == "seed" else 1
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value < 1 << 64:
                raise ValueError(f"teacher {name} must be an integer of at least {low}")
        if self.k > K:
            raise ValueError(f"teacher k must be at most {K}")
        if isinstance(self.lam, bool) or not isinstance(self.lam, (int, float)) or not 0 <= self.lam <= 1:
            raise ValueError("teacher lambda must lie in [0, 1]")
        if not isinstance(self.budget, matrix.WorkBudget):
            raise ValueError("teacher budget must be a matrix.WorkBudget")
        if type(self.key_version) is not int or self.key_version != KEY_VERSION:
            raise ValueError(f"unsupported key version {self.key_version!r}")

    def check(self, search):
        """ValueError unless search runs this configuration with rule X."""
        got = (search.k, search.m, search.s, search.lam, search.capacity, search.rule)
        if got != (self.k, self.m, self.worlds, float(self.lam), self.capacity, "mix"):
            raise ValueError(f"the search {got} does not run the teacher configuration")


@dataclass(frozen=True)
class TeacherDecision:
    """What a learner root executes and stores: the action, its behavior
    log-likelihood, the sparse target (TARGET only), the status with its
    fallback cause, solver work, audit and the world/table/label digests."""
    action: int
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


def label_decision(search, roots, *, env, seat, key, raw_action, raw_logp, last_step, config) -> TeacherDecision:
    """The teacher's decision for an admitted learner root (TURN, REPLACEMENT
    or PIVOT with >= 2 legal pairs) whose ticket was reserved before this
    call, after observe() recorded its request. TARGET: the action drawn
    from X over the candidates (raw action included) with the key's X word,
    its exact play probability as the behavior likelihood. PUBLIC_REFUSAL (no
    supported public reconstruction) and WORK_EXHAUSTED (the work budget):
    the pre-drawn raw action with raw_logp and a named cause. Any other
    failure raises."""
    config.check(search)
    e, p = int(env), int(seat)
    if not 0 <= e < roots.envs or p not in (0, 1) or not roots.requests[e, p]["requested"]:
        raise ValueError("label_decision needs a requested learner seat")
    if not isinstance(key, DecisionKey) or key.seat != p or key.request_epoch != int(roots.requests[e, p]["epoch"]):
        raise ValueError("the decision key must name this seat and request epoch")
    boundary = lookahead._BOUNDARIES[int(roots.requests[e, p]["boundary_kind"])]
    if boundary not in DECISION_BOUNDARIES:
        raise ValueError(f"only TURN/REPLACEMENT/PIVOT roots are labeled (got {boundary})")
    raw_logp = float(raw_logp)
    if not math.isfinite(raw_logp) or raw_logp > 0:
        raise ValueError("raw_logp must be a finite log-probability")
    history = search.history.get(roots, {}).get((e, p))
    if history is None or history.get("observed") != key.request_epoch or history.get("episode") != roots.episode(e):
        raise ValueError("observe() must record this request before label_decision")
    obs, slots, pairs = roots.query_encoded(search.encoder, search.ext_supported)
    mask = pairs[e, p]
    if int(mask.sum()) < 2:
        raise ValueError("a labeled root needs at least two legal pairs")
    pp, _, _ = search._policy(obs[e:e + 1, p], slots[e:e + 1, p], pairs[e:e + 1, p])
    candidates, _ = lookahead.select(pp[0], mask, search.k)
    cand = include_student(candidates, raw_action, mask)
    players = np.zeros(roots.envs, np.uint32)
    players[e] = p
    records, statuses = roots.public(players)
    record = records[e:e + 1].reshape(()).copy()
    world_key = selection_word(key, config.seed, domain="world")
    ledger = matrix.WorkLedger(config.budget)
    costs = {k: 0.0 for k in ("public_records", "world_builds", "team_head", "leaves", "network", "solve")}
    excluded = None if search.exclude_teams is None else search.exclude_teams[e]
    search.last = []
    hypotheses = weights = None

    def work(**extra):
        c = ledger.consumed
        return {"float_pivots": c.float_pivots, "exact_pivots": c.exact_pivots, "exact_ops": c.exact_ops,
                "max_bits": c.max_bits, "status": ledger.status.value, **extra}

    def fallback(status, cause):
        world = None if hypotheses is None else _digest(hypotheses, weights)
        return TeacherDecision(int(raw_action), raw_logp, None, status, cause, work(), {}, world, None, None)

    try:
        if statuses[e] == C["DUOFORGE_E_UNSUPPORTED"]:
            observation = roots.observations[e, p]
            causes = []
            if (observation["sides"]["members"]["status"] == C["DUOFORGE_AILMENT_SLEEP"]).any():
                causes.append("visible_sleep")
            if observation["sides"]["positions"]["confused"].any():
                causes.append("visible_confusion")
            raise Unreconstructible("+".join(causes) or "public_record_unsupported")
        if statuses[e] != 0:
            raise SearchError(f"public record refused: {duoforge.status_name(int(statuses[e]))}")
        hypotheses, weights, _, _, _ = search._hypotheses(record, roots.observations[e, p], history, world_key,
                                                          excluded, costs)
        result = search._decision(p, world_key, cand.ids, np.zeros(cand.ids.size), weights, bool(last_step),
                                  costs, budget=ledger)
    except Unreconstructible as err:
        return fallback(RowStatus.PUBLIC_REFUSAL, f"public:{err}")
    except matrix.WorkBudgetExceeded as err:
        return fallback(RowStatus.WORK_EXHAUSTED, f"work:{err.status.value}")
    tables = np.asarray(result["tables"], np.float64)
    world_digest = _digest(hypotheses, weights)
    table_digest = _digest(tables, np.asarray(result["foe_pairs"], np.int64), np.asarray(result["foe_probs"]))
    # The exact distribution the draw plays: X without sub-floor mass, renormalized.
    pi = np.asarray(result["pi_X"], np.float64)
    play = np.where(pi < matrix.PROBABILITY_FLOOR, 0.0, pi)
    play = play / math.fsum(play.tolist())
    index = matrix.draw(pi, np.arange(cand.ids.size), _uniform(selection_word(key, config.seed, domain="X")))
    action, logp = int(cand.ids[index]), math.log(float(play[index]))
    label_digest = _digest(cand.ids, play, np.array([action], np.int64), np.array([logp]))
    return TeacherDecision(action, logp, SparsePolicy(cand.ids.copy(), play), RowStatus.TARGET, None,
                           work(leaves=int(tables.size)), {}, world_digest, table_digest, label_digest)
