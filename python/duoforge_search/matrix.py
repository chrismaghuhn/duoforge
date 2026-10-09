"""The reductions of the table (spec sections 5.5 and 5.6), in NumPy float64.

A table a has one row per own pair and one column per foe pair; the row
player maximizes. solve gives the Nash equilibrium of the zero-sum game by
an exact linear program; expected_choice gives the expected-value rule's
row; draw plays a mixed strategy from a uniform number.

Reproducible on every machine: no BLAS and no LAPACK. A product of the
table with a strategy is accumulated over the columns (or rows) in a fixed
order, so bit-identical rows always get bit-identical scores; sums of
probabilities are math.fsum, correctly rounded; the linear solve is a
Gaussian elimination written out here.

The linear program. The table is scaled to its range first, s = (a -
min(a)) / (max(a) - min(a)) in [0, 1], which keeps its equilibria; b = s + 1
has every entry at least 1. The column player's problem max sum(q) subject
to b q <= 1, q >= 0 starts feasible at the origin (no phase 1) and is
bounded (every column of b is positive). A dense tableau simplex with
Bland's rule (the lowest entering index with a positive reduced cost; ratio
ties to the lowest basic index) cannot cycle. Its final basis is then
solved again from b itself, which removes the rounding the pivots
accumulated: q from B q_B = 1, the row player's x from the duals B^T pi =
c_B. Every solution passes the certificate before it is returned.

The exact rescue. Near-duplicate rows (a few float32 ulps apart) make a
basis ill-conditioned, and a pivot on a rounding-sized entry can end the
float simplex in a false refusal or a missed certificate. Then the same
simplex, with Bland's rule, runs on the table in exact rational arithmetic
(fractions.Fraction), where it always ends at an exact equilibrium; its
strategies are rounded to float and certified as well. The solution says
which path decided (Solution.exact), so a search can count it. It costs
milliseconds (about 6 ms at 8 x 8, 120 ms at 16 x 16) and is rare.

Rows in prior-rank order. Where a table has several equilibria, which one
the simplex returns follows the order of its rows and columns (a constant
table plays its first row and first column). The search passes both in
prior-rank order (spec section 5.6), so such ties go to the better prior.

The work budget (P1 plan C2). solve and solve_bayes take an optional
WorkLedger: the work of one primary teacher decision, shared by every solve
and retry and never reset per call. It counts float pivots (the start
pivots of the Bayesian tableau and the basis solves included), exact
pivots, exact operations (Fraction construction and conversion,
+, -, *, /, negation and comparisons) and the widest exact numerator or
denominator, checked on the starting tableau, every ratio-test quotient, the
stored entries after every exact pivot and the final strategy quotients (a
product inside one row update, bounded by its checked operands, is not
checked on its own). Work whose amount is known in advance (pivots,
tableau construction, row updates, conversions) is charged before it runs;
the comparisons and divisions of Bland's entering and ratio tests, whose
number depends on their outcome, right after they run. A cap stops the
solver at the first charge past it, with WorkBudgetExceeded naming it. That error is
never caught by the float retry or the rescue; the ledger counts work, not
time, so the outcome is the same on every machine. Without a ledger
(budget=None) nothing is counted and every result is byte-identical.
"""
import dataclasses
from dataclasses import dataclass, field
from enum import Enum
import math
from fractions import Fraction
from typing import NamedTuple

import numpy as np

from .errors import SearchError

CERTIFICATE = 1e-9  # the largest exploitability a solution may have, and at most this times the table's range
PROBABILITY_FLOOR = 1e-9  # a mixed strategy's probabilities below it are played as 0
MAX_ITERATIONS = 10_000
_EPS = 1e-12  # a reduced cost or a pivot entry must exceed it to count as positive


class WorkStatus(Enum):
    OK = "ok"
    FLOAT_PIVOTS = "float_pivots"
    EXACT_PIVOTS = "exact_pivots"
    EXACT_OPS = "exact_ops"
    BITS = "bits"


@dataclass(frozen=True)
class WorkBudget:
    """The caps of one primary teacher decision (P1 plan C2)."""
    float_pivots: int = 4096
    exact_pivots: int = 32
    exact_ops: int = 250_000
    bits: int = 4096

    def __post_init__(self):
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SearchError(f"the work budget's {f.name} must be a nonnegative integer (got {value!r})")


@dataclass(frozen=True)
class WorkCounters:
    float_pivots: int = 0
    exact_pivots: int = 0
    exact_ops: int = 0
    max_bits: int = 0


class WorkBudgetExceeded(SearchError):
    """A cap of the work budget is exhausted; never retried or rescued."""

    def __init__(self, status, consumed):
        super().__init__(f"the work budget is exhausted: {status.value} (consumed {consumed})")
        self.status = status
        self.consumed = consumed


@dataclass
class WorkLedger:
    """The work one decision consumed so far against its caps."""
    limits: WorkBudget = field(default_factory=WorkBudget)
    consumed: WorkCounters = field(default_factory=WorkCounters)

    def __post_init__(self):
        if not isinstance(self.limits, WorkBudget) or not isinstance(self.consumed, WorkCounters):
            raise SearchError("a work ledger needs a WorkBudget and WorkCounters")

    @property
    def status(self):
        c, cap = self.consumed, self.limits
        for status, used, limit in ((WorkStatus.FLOAT_PIVOTS, c.float_pivots, cap.float_pivots),
                                    (WorkStatus.EXACT_PIVOTS, c.exact_pivots, cap.exact_pivots),
                                    (WorkStatus.EXACT_OPS, c.exact_ops, cap.exact_ops),
                                    (WorkStatus.BITS, c.max_bits, cap.bits)):
            if used > limit:
                return status
        return WorkStatus.OK

    def check(self):
        status = self.status
        if status is not WorkStatus.OK:
            raise WorkBudgetExceeded(status, self.consumed)

    def charge(self, float_pivots=0, exact_pivots=0, exact_ops=0):
        c = self.consumed
        self.consumed = WorkCounters(c.float_pivots + float_pivots, c.exact_pivots + exact_pivots,
                                     c.exact_ops + exact_ops, c.max_bits)
        self.check()

    def bits(self, values):
        """Records the widest numerator or denominator of exact values."""
        widest = max((max(v.numerator.bit_length(), v.denominator.bit_length()) for v in values), default=0)
        if widest > self.consumed.max_bits:
            self.consumed = dataclasses.replace(self.consumed, max_bits=widest)
        self.check()


class _Unbounded:
    """budget=None: nothing is counted, so the solver runs exactly as before."""

    def charge(self, float_pivots=0, exact_pivots=0, exact_ops=0):
        pass

    def bits(self, values):
        pass


_UNBOUNDED = _Unbounded()


def _ledger(budget):
    if budget is None:
        return _UNBOUNDED
    if not isinstance(budget, WorkLedger):
        raise SearchError(f"budget must be a WorkLedger or None (got {type(budget).__name__})")
    budget.check()  # an exhausted ledger refuses every later call
    return budget


def _table(a):
    a = np.asarray(a, dtype=np.float64)
    if a.ndim != 2 or a.shape[0] < 1 or a.shape[1] < 1:
        raise SearchError(f"a table needs at least one row and one column (got shape {a.shape})")
    if not np.isfinite(a).all():
        raise SearchError("a table with a non-finite entry")
    return a


def _strategy(v, n, name):
    v = np.asarray(v, dtype=np.float64)
    if (v.shape != (n,) or not np.isfinite(v).all() or (v < 0).any()
            or abs(math.fsum(v.tolist()) - 1.0) > CERTIFICATE):
        raise SearchError(f"{name} is not a mixed strategy over {n} entries: {v!r}")
    return v


def _matvec(a, v):
    """a v, accumulated over the columns in a fixed order."""
    out = np.zeros(a.shape[0], dtype=np.float64)
    for j in range(a.shape[1]):
        out += a[:, j] * v[j]
    return out


def _vecmat(v, a):
    """v a, accumulated over the rows in a fixed order."""
    out = np.zeros(a.shape[1], dtype=np.float64)
    for i in range(a.shape[0]):
        out += v[i] * a[i, :]
    return out


def exploitability(a, x, y):
    """max_i (a y)_i - min_j (x a)_j: what either player gains at most by
    deviating, 0 exactly at an equilibrium."""
    a = _table(a)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    return float(np.max(_matvec(a, y)) - np.min(_vecmat(x, a)))


def certify(a, x, y, tol=CERTIFICATE):
    """The exploitability of (x, y) in a; raises SearchError when x or y is
    not a mixed strategy, or when the exploitability exceeds tol or tol times
    the table's range (max(a) - min(a)), whichever is smaller. Measured on
    the table scaled to its range, so the bound means the same on a flat
    table as on a wide one. Every pair of strategies is an equilibrium of a
    constant table (exploitability 0)."""
    a = _table(a)
    x = _strategy(x, a.shape[0], "x")
    y = _strategy(y, a.shape[1], "y")
    low = float(a.min())
    span = float(a.max()) - low
    if span == 0.0:
        return 0.0
    gap = exploitability((a - low) / span, x, y)
    if not gap <= tol * min(1.0, 1.0 / span):
        raise SearchError(f"the Nash certificate is missed: exploitability {gap * span:.3e} (range {span:.3e}) "
                          f"> {tol:.0e} x min(1, range) on a {a.shape[0]} x {a.shape[1]} table")
    return gap * span


def _gauss(mat, rhs, ledger=_UNBOUNDED):
    """The solution of mat z = rhs by Gaussian elimination with partial
    pivoting (the first largest pivot); SearchError for a singular matrix."""
    m = np.array(mat, dtype=np.float64)
    r = np.array(rhs, dtype=np.float64)
    n = r.size
    for c in range(n):
        ledger.charge(float_pivots=1)
        p = c + int(np.argmax(np.abs(m[c:, c])))
        if m[p, c] == 0.0:
            raise SearchError("the final basis of the simplex is singular")
        if p != c:
            m[[c, p]] = m[[p, c]]
            r[[c, p]] = r[[p, c]]
        f = m[c + 1:, c] / m[c, c]
        m[c + 1:, c:] -= np.outer(f, m[c, c:])
        r[c + 1:] -= f * r[c]
    z = np.zeros(n, dtype=np.float64)
    for c in range(n - 1, -1, -1):
        s = r[c]
        for j in range(c + 1, n):
            s -= m[c, j] * z[j]
        z[c] = s / m[c, c]
    return z


def _simplex(b, ledger=_UNBOUNDED):
    """The final basis of max sum(q) s.t. b q <= 1, q >= 0, b >= 1 entrywise:
    one variable index per row, q_j as j < m, the slack of row i as m + i."""
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
            return basis
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
        ledger.charge(float_pivots=1)
        pivot = t[leave] / t[leave, enter]
        t -= np.outer(t[:, enter], pivot)
        t[leave] = pivot
        basis[leave] = enter
    raise SearchError(f"the simplex did not finish in {MAX_ITERATIONS} iterations")


def _enter(costs, positive):
    """Bland's entering index (the first positive reduced cost) and the
    number of comparisons it made."""
    for j, v in enumerate(costs):
        if positive(v):
            return j, j + 1
    return None, len(costs)


def _ratio_test(t, rows, enter, rhs, basis, positive, ops, ledger):
    """Bland's leaving row (the lowest ratio, ties to the lowest basic
    index) and the operations counted so far: one comparison per entry, a
    division per positive entry, then the ratio comparisons evaluated.
    Each quotient's width goes to the ledger."""
    leave, best = -1, None
    for i in range(rows):
        entry = t[i][enter]
        ops += 1
        if positive(entry):
            ratio = t[i][rhs] / entry
            ops += 1
            ledger.bits((ratio,))
            if leave < 0:
                leave, best = i, ratio
                continue
            ops += 1
            if ratio < best:
                leave, best = i, ratio
                continue
            ops += 1
            if ratio == best and basis[i] < basis[leave]:
                leave, best = i, ratio
    return leave, ops


def _simplex_exact(a, ledger=_UNBOUNDED):
    """(x, y) of the table a by the same simplex in exact rational
    arithmetic: b = a - min(a) + 1 exactly, Bland's rule, which cannot cycle
    here, so it ends at an optimal basis; the strategies rounded to float.
    Every Fraction operation is charged to the ledger (see the module)."""
    k, m = a.shape
    n = m + k
    ledger.charge(exact_ops=1 + (k + 1) + 3 * k * m + 2 * k + m)
    low = Fraction(float(a.min()))
    t = [[Fraction(0)] * (n + 1) for _ in range(k + 1)]
    for i in range(k):
        for j in range(m):
            t[i][j] = Fraction(float(a[i, j])) - low + 1
        t[i][m + i] = Fraction(1)
        t[i][n] = Fraction(1)
    for j in range(m):
        t[k][j] = Fraction(1)
    ledger.bits(v for row in t for v in row)
    basis = list(range(m, n))
    for _ in range(MAX_ITERATIONS):
        enter, ops = _enter(t[k][:n], lambda v: v > 0)
        if enter is None:
            ledger.charge(exact_ops=ops)
            break
        leave, ops = _ratio_test(t, k, enter, n, basis, lambda v: v > 0, ops, ledger)
        if leave < 0:
            ledger.charge(exact_ops=ops)
            raise SearchError("the exact linear program is unbounded, which a shifted table cannot be")
        ledger.charge(exact_ops=ops + k)  # the ratio test, then one zero test per other row
        update = [i for i in range(k + 1) if i != leave and t[i][enter] != 0]
        ledger.charge(exact_pivots=1, exact_ops=(n + 1) + 2 * (n + 1) * len(update))
        pivot = t[leave][enter]
        t[leave] = [v / pivot for v in t[leave]]
        for i in update:
            factor = t[i][enter]
            t[i] = [vi - factor * vl for vi, vl in zip(t[i], t[leave])]
        basis[leave] = enter
        ledger.bits(v for row in t for v in row)
    else:
        raise SearchError(f"the exact simplex did not finish in {MAX_ITERATIONS} iterations")
    ledger.charge(exact_ops=1 + m + 3 * k + 2 * m)
    q = [Fraction(0)] * m
    for row, var in enumerate(basis):
        if var < m:
            q[var] = t[row][n]
    total = sum(q)
    xs = [-t[k][m + i] / total for i in range(k)]
    ys = [v / total for v in q]
    ledger.bits([total] + xs + ys)
    x = np.array([float(v) for v in xs], dtype=np.float64)
    y = np.array([float(v) for v in ys], dtype=np.float64)
    return x, y


def _solve_float(a, low, span, ledger=_UNBOUNDED):
    """(x, y) by the float simplex on the table scaled to its range, its
    final basis solved again from the scaled table."""
    k, m = a.shape
    b = (a - low) / span + 1.0
    basis = _simplex(b, ledger)
    square = np.hstack([b, np.eye(k)])[:, basis]
    primal = _gauss(square, np.ones(k), ledger)
    dual = _gauss(square.T, np.array([1.0 if var < m else 0.0 for var in basis]), ledger)
    q = np.zeros(m, dtype=np.float64)
    for row, var in enumerate(basis):
        if var < m:
            q[var] = primal[row]
    return dual, q


def _normalized(v):
    v = np.maximum(v, 0.0)
    total = math.fsum(v.tolist())
    if not total > 0.0:
        raise SearchError("the linear program gave an empty strategy")
    return v / total


class Solution(NamedTuple):
    """A certified equilibrium: the strategies x (rows) and y (columns), the
    value (the midpoint of min(x a) and max(a y), the interval the
    certificate bounds), and whether the exact rescue decided."""
    x: np.ndarray
    y: np.ndarray
    value: float
    exact: bool


def solve(a, *, budget=None):
    """The Solution of the zero-sum game a (the row player maximizes x a
    y): the float simplex, or the exact rescue when the float simplex fails
    or misses the certificate; certified either way (certify), so a
    SearchError from here is a failure of the exact path. Rows and columns in
    prior-rank order: see the module. budget: an optional WorkLedger (see
    the module); its WorkBudgetExceeded is never rescued."""
    ledger = _ledger(budget)
    a = _table(a)
    k, m = a.shape
    low = float(a.min())
    span = float(a.max()) - low
    if span == 0.0:  # a constant table: every pair of strategies is an equilibrium
        x = np.zeros(k, dtype=np.float64)
        y = np.zeros(m, dtype=np.float64)
        x[0] = y[0] = 1.0
        return Solution(x, y, low, False)
    try:
        dual, q = _solve_float(a, low, span, ledger)
        x, y = _normalized(dual), _normalized(q)
        certify(a, x, y)
        exact = False
    except WorkBudgetExceeded:
        raise
    except SearchError:
        dual, q = _simplex_exact(a, ledger)
        x, y = _normalized(dual), _normalized(q)
        certify(a, x, y)
        exact = True
    lower = float(np.min(_vecmat(x, a)))
    upper = float(np.max(_matvec(a, y)))
    return Solution(x, y, (lower + upper) / 2.0, exact)


def _ranks(prior_rank, k):
    rank = np.asarray(prior_rank)
    if rank.shape != (k,) or not np.issubdtype(rank.dtype, np.integer):
        raise SearchError(f"prior_rank must hold {k} integers (got {rank!r})")
    if np.unique(rank).size != k:
        raise SearchError(f"prior_rank must rank every own pair once (got {rank!r})")
    return rank.astype(np.int64)


def expected_values(a, q):
    """The expected value sum_j q_j a[i, j] of every row, q renormalized,
    accumulated over the columns in a fixed order: the scores
    expected_choice compares."""
    a = _table(a)
    q = np.asarray(q, dtype=np.float64)
    if q.shape != (a.shape[1],) or not np.isfinite(q).all() or (q < 0).any() or not q.sum() > 0.0:
        raise SearchError(f"q must be {a.shape[1]} nonnegative probabilities with a positive sum (got {q!r})")
    return _matvec(a, q / math.fsum(q.tolist()))


def expected_choice(a, q, prior_rank):
    """The row with the highest expected value sum_j q_j a[i, j], q
    renormalized (expected_values); ties, compared exactly, go to the better
    (lower) prior_rank. prior_rank orders the own pairs by policy
    probability, ties already broken to the lower flat index (spec section
    5.6)."""
    score = expected_values(a, q)
    rank = _ranks(prior_rank, score.shape[0])
    best = np.flatnonzero(score == score.max())
    return int(best[np.argmin(rank[best])])


def draw(x, prior_rank, u):
    """The row a mixed strategy x plays for a uniform u in [0, 1):
    probabilities below PROBABILITY_FLOOR count as 0, the rest is
    renormalized, and the rows are walked in prior_rank order; the first
    whose cumulative probability exceeds u is played. If rounding leaves the
    last cumulative probability at or below u, the last row with mass is
    played."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1 or x.size < 1 or not np.isfinite(x).all() or (x < 0).any():
        raise SearchError(f"x is not a mixed strategy: {x!r}")
    u = float(u)
    if not 0.0 <= u < 1.0:
        raise SearchError(f"the play draw must lie in [0, 1) (got {u!r})")
    rank = _ranks(prior_rank, x.size)
    p = np.where(x < PROBABILITY_FLOOR, 0.0, x)
    total = math.fsum(p.tolist())
    if not total > 0.0:
        raise SearchError(f"x has no probability above {PROBABILITY_FLOOR:.0e}: {x!r}")
    order = np.argsort(rank, kind="stable")
    cum = np.cumsum(p[order] / total)
    hit = np.flatnonzero(cum > u)
    if hit.size:
        return int(order[hit[0]])
    return int(order[np.flatnonzero(p[order] > 0.0)[-1]])


# ---- the Bayesian game (decision 0023; spec section 6.3) ----
#
# One strategy x of the row player holds in every world w (weight p_w); the
# column player knows its world and best-responds in each:
#     maximize sum_w p_w v_w  s.t.  v_w <= sum_i x_i b_w[i, j] for all w, j;  sum_i x_i <= 1;  x, v >= 0
# on the tables scaled together to [0, 1] and shifted by 1 (b >= 1), so the
# origin is feasible and sum_i x_i = 1 at the optimum. The float tableau
# starts instead at x[0] = 1 and each world's worst column value, avoiding
# the degenerate origin. A dense tableau simplex with Bland's rule solves
# it; the duals of the rows (w, j), divided by p_w, are the column player's
# strategies y_w. If certification fails, a float retry uses a stable
# two-pass ratio test before the rational Bland rescue. All paths certify
# the original tables at the same tolerance.


def _tables(tables, weights):
    a = np.asarray(tables, dtype=np.float64)
    if a.ndim != 3 or 0 in a.shape or not np.isfinite(a).all():
        raise SearchError(f"tables must be a finite (W, K, M) array (got shape {a.shape})")
    p = np.asarray(weights, dtype=np.float64)
    if p.shape != (a.shape[0],) or not np.isfinite(p).all() or (p <= 0).any():
        raise SearchError(f"weights must be {a.shape[0]} positive numbers (got {p!r})")
    return a, p / math.fsum(p.tolist())


def bayes_exploitability(tables, weights, x, ys):
    """max_i sum_w p_w (a_w y_w)_i - sum_w p_w min_j (x a_w)_j: 0 exactly at
    an equilibrium of the Bayesian game."""
    a, p = _tables(tables, weights)
    x = np.asarray(x, dtype=np.float64)
    upper = np.zeros(a.shape[1], dtype=np.float64)
    lower = 0.0
    for w in range(a.shape[0]):
        upper += p[w] * _matvec(a[w], np.asarray(ys[w], dtype=np.float64))
        lower += p[w] * float(np.min(_vecmat(x, a[w])))
    return float(np.max(upper)) - lower


def bayes_certify(tables, weights, x, ys, tol=CERTIFICATE):
    """As certify, for the Bayesian game: on the tables scaled together to
    their range."""
    a, p = _tables(tables, weights)
    x = _strategy(x, a.shape[1], "x")
    ys = [_strategy(ys[w], a.shape[2], f"y[{w}]") for w in range(a.shape[0])]
    low = float(a.min())
    span = float(a.max()) - low
    if span == 0.0:
        return 0.0
    gap = bayes_exploitability((a - low) / span, p, x, ys)
    if not gap <= tol * min(1.0, 1.0 / span):
        raise SearchError(f"the Bayesian Nash certificate is missed: exploitability {gap * span:.3e} "
                          f"(range {span:.3e}) on {a.shape[0]} tables of {a.shape[1]} x {a.shape[2]}")
    return gap * span


def _bayes_tableau(b, p, zero, one):
    """The rows of the LP above over a number type (float or Fraction)."""
    nw, k, m = len(b), len(b[0]), len(b[0][0])
    nvar = k + nw
    rows = []
    for w in range(nw):
        for j in range(m):
            row = [zero] * nvar
            for i in range(k):
                row[i] = -b[w][i][j]
            row[k + w] = one
            rows.append(row)
    rows.append([one] * k + [zero] * nw)
    rhs = [zero] * (nw * m) + [one]
    cost = [zero] * k + [p[w] for w in range(nw)]
    return rows, rhs, cost


def _bland(rows, rhs, cost, zero, positive, ledger=_UNBOUNDED):
    """max cost . z s.t. rows z <= rhs (rhs >= 0), z >= 0, by a dense tableau
    simplex with Bland's rule. Returns (z, duals) of the final tableau. With
    a ledger (exact values only), every operation is charged (see the module)."""
    r, n = len(rows), len(cost)
    ledger.charge(exact_ops=r)
    t = [list(rows[i]) + [zero] * r + [rhs[i]] for i in range(r)]
    for i in range(r):
        t[i][n + i] = zero + 1
    obj = list(cost) + [zero] * r + [zero]
    ledger.bits(v for row in t + [obj] for v in row)
    basis = list(range(n, n + r))
    width = n + r + 1
    for _ in range(MAX_ITERATIONS):
        enter, ops = _enter(obj[:n + r], positive)
        if enter is None:
            ledger.charge(exact_ops=ops)
            break
        leave, ops = _ratio_test(t, r, enter, -1, basis, positive, ops, ledger)
        if leave < 0:
            ledger.charge(exact_ops=ops)
            raise SearchError("the Bayesian linear program is unbounded, which shifted tables cannot be")
        ledger.charge(exact_ops=ops + (r - 1))  # the ratio test, then one zero test per other row
        update = [i for i in range(r) if i != leave and t[i][enter] != 0]
        ledger.charge(exact_pivots=1, exact_ops=width + 2 * width * len(update) + 2 * width)
        pivot = t[leave][enter]
        t[leave] = [v / pivot for v in t[leave]]
        for i in update:
            f = t[i][enter]
            t[i] = [vi - f * vl for vi, vl in zip(t[i], t[leave])]
        f = obj[enter]
        obj = [vi - f * vl for vi, vl in zip(obj, t[leave])]
        basis[leave] = enter
        ledger.bits(v for row in t + [obj] for v in row)
    else:
        raise SearchError(f"the Bayesian simplex did not finish in {MAX_ITERATIONS} iterations")
    ledger.charge(exact_ops=r)
    z = [zero] * n
    for row, var in enumerate(basis):
        if var < n:
            z[var] = t[row][-1]
    duals = [-obj[n + i] for i in range(r)]
    return z, duals


def _bland_float(b, p, stable=False, ledger=_UNBOUNDED):
    """_bland on the float tableau of the LP above, in NumPy (no BLAS: the
    pivot is an elementwise update). With stable=True, retry using a
    two-pass ratio test to avoid tiny pivots on nearly tied constraints;
    the returned strategies still require the original certificate."""
    nw, k, m = b.shape
    r = nw * m + 1
    n = k + nw
    t = np.zeros((r + 1, n + r + 1), dtype=np.float64)
    for w in range(nw):
        t[w * m:(w + 1) * m, :k] = -b[w].T
        t[w * m:(w + 1) * m, k + w] = 1.0
    t[r - 1, :k] = 1.0
    t[r - 1, -1] = 1.0
    t[:r, n:n + r] = np.eye(r)
    t[r, k:n] = p
    basis = list(range(n, n + r))

    def pivot_at(leave, enter):
        ledger.charge(float_pivots=1)
        pivot = t[leave] / t[leave, enter]
        t[:] -= np.outer(t[:, enter], pivot)
        t[leave] = pivot
        basis[leave] = enter

    # Start at the feasible first-row strategy, rather than the highly
    # degenerate origin (all W*M world constraints have zero RHS there).
    # Set x[0] = 1, then v[w] = min_j b[w, 0, j]. Each world pivot has
    # coefficient exactly 1; the remaining RHS are nonnegative slacks.
    # First minima preserve the column order. Avoiding the zero-length
    # origin pivots also avoids amplifying roundoff into a false optimum.
    pivot_at(r - 1, 0)
    for w in range(nw):
        pivot_at(w * m + int(np.argmin(b[w, 0])), k + w)
    seen = set()
    for _ in range(MAX_ITERATIONS):
        if stable:
            signature = tuple(basis)
            if signature in seen:
                raise SearchError("the stable Bayesian float tableau repeated a basis")
            seen.add(signature)
        positive = np.flatnonzero(t[r, :n + r] > _EPS)
        if positive.size == 0:
            break
        enter = int(positive[0])
        leave, best = -1, 0.0
        if stable:
            # Harris two-pass ratio test: first bound the step with a
            # small primal feasibility allowance, then choose the largest
            # pivot among the eligible rows (ties by basic variable).
            # This tolerance is NOT a payoff/certificate tolerance: a
            # result is accepted only after bayes_certify on the input.
            entries = t[:r, enter]
            candidates = np.flatnonzero(entries > _EPS)
            if candidates.size:
                rhs = np.maximum(t[candidates, -1], 0.0)
                ratios = rhs / entries[candidates]
                limit = np.min((rhs + _EPS) / entries[candidates])
                eligible = candidates[ratios <= limit]
                largest = np.max(entries[eligible])
                leave = min((int(i) for i in eligible if entries[i] == largest), key=lambda i: basis[i])
        else:
            for i in range(r):
                entry = t[i, enter]
                if entry > _EPS:
                    ratio = t[i, -1] / entry
                    if leave < 0 or ratio < best or (ratio == best and basis[i] < basis[leave]):
                        leave, best = i, ratio
        if leave < 0:
            raise SearchError("the Bayesian linear program is unbounded, which shifted tables cannot be")
        pivot_at(leave, enter)
    else:
        raise SearchError(f"the Bayesian simplex did not finish in {MAX_ITERATIONS} iterations")
    z = np.zeros(n, dtype=np.float64)
    for row, var in enumerate(basis):
        if var < n:
            z[var] = t[row, -1]
    return z.tolist(), (-t[r, n:n + r]).tolist()


class BayesSolution(NamedTuple):
    """A certified equilibrium of the Bayesian game: x (rows), ys (one column
    strategy per world), the value sum_w p_w min_j (x a_w)_j, and whether the
    exact rescue decided."""
    x: np.ndarray
    ys: list
    value: float
    exact: bool


def solve_bayes(tables, weights, *, budget=None):
    """The BayesSolution of tables (W, K, M) with world weights (W,): the
    float simplex, then a stable float retry, or the exact rescue when both
    fail or miss the unchanged certificate. With W = 1 it is the matrix
    game of solve. budget: an optional WorkLedger shared by all three paths
    (see the module); its WorkBudgetExceeded is never retried or rescued."""
    ledger = _ledger(budget)
    a, p = _tables(tables, weights)
    nw, k, m = a.shape
    low = float(a.min())
    span = float(a.max()) - low
    if span == 0.0:
        x = np.zeros(k, dtype=np.float64)
        x[0] = 1.0
        ys = [np.eye(m, dtype=np.float64)[0] for _ in range(nw)]
        return BayesSolution(x, ys, low, False)

    def strategies(z, duals, to_float):
        x = _normalized(np.array([to_float(v) for v in z[:k]], dtype=np.float64))
        ys = []
        for w in range(nw):
            yw = np.array([to_float(duals[w * m + j]) for j in range(m)], dtype=np.float64)
            ys.append(_normalized(yw))
        return x, ys

    try:
        z, duals = _bland_float((a - low) / span + 1.0, p, ledger=ledger)
        x, ys = strategies(z, duals, float)
        bayes_certify(a, p, x, ys)
        exact = False
    except WorkBudgetExceeded:
        raise
    except SearchError:
        try:
            z, duals = _bland_float((a - low) / span + 1.0, p, stable=True, ledger=ledger)
            x, ys = strategies(z, duals, float)
            bayes_certify(a, p, x, ys)
            exact = False
        except WorkBudgetExceeded:
            raise
        except SearchError:
            # Fraction(low), each entry constructed, shifted and offset, the
            # weights, the negated table entries and the two constants.
            ledger.charge(exact_ops=1 + 3 * nw * k * m + nw + nw * m * k + 2)
            lo = Fraction(low)
            b = [[[Fraction(float(v)) - lo + 1 for v in row] for row in a[w]] for w in range(nw)]
            pf = [Fraction(float(v)) for v in p]
            zero, one = Fraction(0), Fraction(1)
            rows, rhs, cost = _bayes_tableau(b, pf, zero, one)
            z, duals = _bland(rows, rhs, cost, zero, lambda v: v > 0, ledger)
            ledger.charge(exact_ops=k + nw * m)  # the conversions to float
            x, ys = strategies(z, duals, float)
            bayes_certify(a, p, x, ys)
            exact = True
    value = math.fsum(float(p[w]) * float(np.min(_vecmat(x, a[w]))) for w in range(nw))
    return BayesSolution(x, ys, value, exact)


def bayes_expected_values(tables, weights, qs):
    """sum_w p_w sum_j q_w,j a_w[i, j] for every row, each q_w renormalized:
    the scores of the expected-value rule over worlds."""
    a, p = _tables(tables, weights)
    out = np.zeros(a.shape[1], dtype=np.float64)
    for w in range(a.shape[0]):
        out += p[w] * expected_values(a[w], qs[w])
    return out


def mix(x, best, lam=0.5):
    """The mixed rule X: lam * x + (1 - lam) * e_best (spec section 6.5)."""
    x = np.asarray(x, dtype=np.float64)
    if not 0.0 <= lam <= 1.0 or not 0 <= best < x.size:
        raise SearchError(f"mix needs 0 <= lam <= 1 and a row of x (got {lam}, {best})")
    out = lam * x
    out[best] += 1.0 - lam
    return out
