"""The reductions of the table (spec sections 5.5 and 5.6), in NumPy float64.

A table a has one row per own pair and one column per foe pair; the row
player maximizes. solve gives the Nash equilibrium of the zero-sum game by
an exact linear program; expected_choice gives the expected-value rule's
row; draw plays a mixed strategy from a uniform number.

The linear program. The table is shifted to b = a - min(a) + 1, so every
entry is at least 1 and the game value is positive. The column player's
problem max sum(q) subject to b q <= 1, q >= 0 starts feasible at the
origin (no phase 1) and is bounded (every column of b is positive). A dense
tableau simplex with Bland's rule (the lowest entering index with a
positive reduced cost; ratio ties to the lowest basic index) cannot cycle.
At the optimum, y = q / sum(q), the row player's x is the dual, read from
the slack columns' reduced costs, and the value of a is 1 / sum(q) + min(a)
- 1. Every solution passes the certificate before it is returned.
"""
import numpy as np

from .errors import SearchError

CERTIFICATE = 1e-9  # the largest exploitability a solution may have
PROBABILITY_FLOOR = 1e-9  # a mixed strategy's probabilities below it are played as 0
MAX_ITERATIONS = 10_000
_EPS = 1e-12  # a reduced cost or a pivot entry must exceed it to count as positive


def _table(a):
    a = np.asarray(a, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] < 1 or a.shape[1] < 1:
        raise SearchError(f"a table needs at least one row and one column (got shape {a.shape})")
    if not np.isfinite(a).all():
        raise SearchError("a table with a non-finite entry")
    return a


def _strategy(v, n, name):
    v = np.asarray(v, dtype=np.float64)
    if v.shape != (n,) or not np.isfinite(v).all() or (v < 0).any() or abs(v.sum() - 1.0) > CERTIFICATE:
        raise SearchError(f"{name} is not a mixed strategy over {n} entries: {v!r}")
    return v


def exploitability(a, x, y):
    """max_i (a y)_i - min_j (x a)_j: what either player gains at most by
    deviating, 0 exactly at an equilibrium."""
    a = _table(a)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    return float(np.max(a @ y) - np.min(x @ a))


def certify(a, x, y, tol=CERTIFICATE):
    """The exploitability of (x, y) in a; raises SearchError when x or y is
    not a mixed strategy or the exploitability exceeds tol."""
    a = _table(a)
    _strategy(x, a.shape[0], "x")
    _strategy(y, a.shape[1], "y")
    gap = exploitability(a, x, y)
    if not gap <= tol:
        raise SearchError(f"the Nash certificate is missed: exploitability {gap:.3e} > {tol:.0e} "
                          f"on a {a.shape[0]} x {a.shape[1]} table")
    return gap


def _simplex(b):
    """(q, dual) of max sum(q) s.t. b q <= 1, q >= 0, b >= 1 entrywise."""
    k, m = b.shape
    n = m + k
    t = np.zeros((k + 1, n + 1), dtype=np.float64)
    t[:k, :m] = b
    t[:k, m:n] = np.eye(k)
    t[:k, n] = 1.0
    t[k, :m] = 1.0  # reduced costs c_j - z_j; the objective row's last entry is -z
    basis = list(range(m, n))
    for _ in range(MAX_ITERATIONS):
        positive = np.flatnonzero(t[k, :n] > _EPS)
        if positive.size == 0:
            break
        enter = int(positive[0])
        leave = -1
        best = 0.0
        for i in range(k):
            entry = t[i, enter]
            if entry > _EPS:
                ratio = t[i, n] / entry
                if leave < 0 or ratio < best or (ratio == best and basis[i] < basis[leave]):
                    leave, best = i, ratio
        if leave < 0:
            raise SearchError("the linear program is unbounded, which a shifted table cannot be")
        pivot = t[leave] / t[leave, enter]
        t -= np.outer(t[:, enter], pivot)
        t[leave] = pivot
        basis[leave] = enter
    else:
        raise SearchError(f"the simplex did not finish in {MAX_ITERATIONS} iterations")
    q = np.zeros(m, dtype=np.float64)
    for i, var in enumerate(basis):
        if var < m:
            q[var] = t[i, n]
    return q, -t[k, m:n]


def _normalized(v):
    v = np.maximum(v, 0.0)
    total = v.sum()
    if not total > 0.0:
        raise SearchError("the linear program gave an empty strategy")
    return v / total


def solve(a):
    """(x, y, value): a Nash equilibrium of the zero-sum game a (the row
    player maximizes x a y) and its value, certified (CERTIFICATE)."""
    a = _table(a)
    low = float(a.min())
    q, dual = _simplex(a - low + 1.0)
    total = q.sum()
    if not total > 0.0:
        raise SearchError("the linear program gave an empty strategy")
    x = _normalized(dual)
    y = _normalized(q)
    certify(a, x, y)
    return x, y, 1.0 / total + low - 1.0


def _ranks(prior_rank, k):
    rank = np.asarray(prior_rank)
    if rank.shape != (k,) or not np.issubdtype(rank.dtype, np.integer):
        raise SearchError(f"prior_rank must hold {k} integers (got {rank!r})")
    if np.unique(rank).size != k:
        raise SearchError(f"prior_rank must rank every own pair once (got {rank!r})")
    return rank.astype(np.int64)


def expected_choice(a, q, prior_rank):
    """The row with the highest expected value sum_j q_j a[i, j], q
    renormalized; ties, compared exactly, go to the better (lower)
    prior_rank. prior_rank orders the own pairs by policy probability, ties
    already broken to the lower flat index (spec section 5.6)."""
    a = _table(a)
    q = np.asarray(q, dtype=np.float64)
    if q.shape != (a.shape[1],) or not np.isfinite(q).all() or (q < 0).any() or not q.sum() > 0.0:
        raise SearchError(f"q must be {a.shape[1]} nonnegative probabilities with a positive sum (got {q!r})")
    rank = _ranks(prior_rank, a.shape[0])
    score = a @ (q / q.sum())
    best = np.flatnonzero(score == score.max())
    return int(best[np.argmin(rank[best])])


def draw(x, prior_rank, u):
    """The row a mixed strategy x plays for a uniform u in [0, 1):
    probabilities below PROBABILITY_FLOOR count as 0, the rest is
    renormalized, and the rows are walked in prior_rank order; the first
    whose cumulative probability exceeds u is played."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1 or x.size < 1 or not np.isfinite(x).all() or (x < 0).any():
        raise SearchError(f"x is not a mixed strategy: {x!r}")
    u = float(u)
    if not 0.0 <= u < 1.0:
        raise SearchError(f"the play draw must lie in [0, 1) (got {u!r})")
    rank = _ranks(prior_rank, x.size)
    p = np.where(x < PROBABILITY_FLOOR, 0.0, x)
    if not p.sum() > 0.0:
        raise SearchError(f"x has no probability above {PROBABILITY_FLOOR:.0e}: {x!r}")
    order = np.argsort(rank, kind="stable")
    cum = np.cumsum(p[order] / p.sum())
    hit = np.flatnonzero(cum > u)
    if hit.size:
        return int(order[hit[0]])
    return int(order[np.flatnonzero(p[order] > 0.0)[-1]])  # u within rounding of 1: the last row with mass
