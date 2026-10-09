"""The P1 honest teacher (plan C3, decision 0024). No battle rules here.

The teacher labels admitted learner roots with the honest search's mixed
rule X over the K own candidates, the student's raw action always among
them. Its foe model is its own frozen network; only C builds worlds.
"""
from dataclasses import dataclass

import numpy as np

from . import lookahead
from .expert_data import MASS_TOLERANCE, SparsePolicy

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
