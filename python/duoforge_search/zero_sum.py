"""The exact equilibrium of a finite two-player zero-sum matrix game (issue #458, the mixed team preview).

solve(A) takes the payoff matrix of the row player (who maximizes; the column player minimizes) as rationals and
returns both players' equilibrium mixes and the game's value, in exact rational arithmetic (fractions.Fraction): the
simplex method with Bland's rule on the column player's linear program, the row player's mix from its dual. Before it
returns, it checks the result exactly: both mixes are distributions, and the row mix secures the value against every
column while the column mix concedes no more than it against any row. A result that fails the check raises; there is no
approximate fallback.

gap(A, x, y) is the double oracle's gap of a pair of mixes on a (possibly larger) matrix: the best row's payoff against
y minus the worst column's against x. It is zero exactly when (x, y) is an equilibrium of A.
"""
from fractions import Fraction


def _matrix(a):
    rows = [[Fraction(v) for v in row] for row in a]
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("a payoff matrix has at least one row and one column, every row as long as the first")
    return rows


def _check_mix(mix, size, who):
    if len(mix) != size or any(p < 0 for p in mix) or sum(mix) != 1:
        raise ValueError(f"the {who} mix is no distribution over {size} strategies: {[str(p) for p in mix]}")


def solve(a):
    """(x, y, v): the row player's and the column player's equilibrium mixes (lists of Fraction) and the value of the
    game with payoff matrix a (rows: the maximizer's strategies). Exact; RuntimeError if the check fails."""
    a = _matrix(a)
    m, n = len(a), len(a[0])
    shift = 1 - min(min(row) for row in a)  # B = A + shift >= 1: the LP below is feasible, bounded, its value positive
    # The column player's LP: max sum q s.t. B q <= 1, q >= 0 (the origin is feasible, so no phase 1). At the optimum
    # sum q = 1 / value(B), y = q / sum q, and the dual prices p of the rows give x = p / sum p.
    tableau = [[a[i][j] + shift for j in range(n)] + [Fraction(int(k == i)) for k in range(m)] + [Fraction(1)]
               for i in range(m)]
    basis = [n + i for i in range(m)]  # the slacks
    cost = [Fraction(1)] * n + [Fraction(0)] * m  # the objective's reduced costs (maximize)
    while True:
        entering = next((j for j in range(n + m) if cost[j] > 0), None)  # Bland: the smallest improving index
        if entering is None:
            break
        ratios = [(tableau[i][-1] / tableau[i][entering], basis[i], i) for i in range(m) if tableau[i][entering] > 0]
        if not ratios:
            raise RuntimeError("the game's linear program is unbounded: impossible for a payoff matrix")
        _, _, leave = min(ratios)  # the smallest ratio, ties by the smallest basic index (Bland)
        pivot = tableau[leave][entering]
        tableau[leave] = [v / pivot for v in tableau[leave]]
        for i in range(m):
            if i != leave and tableau[i][entering] != 0:
                f = tableau[i][entering]
                tableau[i] = [v - f * w for v, w in zip(tableau[i], tableau[leave])]
        f = cost[entering]
        cost = [c - f * w for c, w in zip(cost, tableau[leave][:-1])]
        basis[leave] = entering
    q = [Fraction(0)] * n
    for i, var in enumerate(basis):
        if var < n:
            q[var] = tableau[i][-1]
    p = [-cost[n + i] for i in range(m)]  # the rows' dual prices
    total_q, total_p = sum(q), sum(p)
    if total_q <= 0 or total_q != total_p:
        raise RuntimeError(f"the simplex ended without a positive primal-dual pair (sum q {total_q}, sum p {total_p})")
    x, y = [v / total_p for v in p], [v / total_q for v in q]
    value = 1 / total_q - shift
    _check_mix(x, m, "row")
    _check_mix(y, n, "column")
    secured = min(sum(x[i] * a[i][j] for i in range(m)) for j in range(n))
    conceded = max(sum(a[i][j] * y[j] for j in range(n)) for i in range(m))
    if secured != value or conceded != value:
        raise RuntimeError(f"the equilibrium check failed: the row mix secures {secured}, the column mix concedes "
                           f"{conceded}, the value is {value}")
    return x, y, value


def gap(a, x, y):
    """{"best_row": max_i (A y)_i, "worst_column": min_j (x' A)_j, "gap": their difference} for mixes x (rows) and y
    (columns) on payoff matrix a, exact (Fraction)."""
    a = _matrix(a)
    m, n = len(a), len(a[0])
    x, y = [Fraction(v) for v in x], [Fraction(v) for v in y]
    _check_mix(x, m, "row")
    _check_mix(y, n, "column")
    best_row = max(sum(a[i][j] * y[j] for j in range(n)) for i in range(m))
    worst_column = min(sum(x[i] * a[i][j] for i in range(m)) for j in range(n))
    return {"best_row": best_row, "worst_column": worst_column, "gap": best_row - worst_column}
