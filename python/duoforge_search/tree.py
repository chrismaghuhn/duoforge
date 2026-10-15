"""The two-turn tree's solver (D2 of the depth search; docs/superpowers/specs/2026-10-13-depth-search-design.md
sections 3.1, 4.1, 4.4 and 8 "D2 in detail"; plan docs/superpowers/plans/2026-10-14-depth-search-d2.md step 1).

The tree extends the Bayes game of matrix.solve_bayes_rm by one turn:

    root information set (ours, shared by all worlds)           x over K own pairs
     └ world w (weight p_w)                                       foe: y_w over M foe pairs
        └ edge (i, j) → a leaf (TERMINAL, cut-off, a value), or depth-1 node n:
           ├ ours:  information set info[n] (its key holds the root row i), K2 candidates, shared across worlds
           └ foe's: per node (the foe knows its world), M2 candidates
              └ (a, b) → utility z[n, a, b]

A node where only one side is requested has a single (empty) response for the other: info[n] = -1 gives ours (column
0 of z), one valid foe candidate gives the foe's. Candidates are padded to K2 and M2; a padded candidate has no prior,
is never played and its z is never read.

CFR+ as D1 (matrix.solve_bayes_rm): regret-matching+ at every information set and foe node, alternating (ours against
the foe's current strategies, then the foe's against our new ones), linear averaging, a side whose every valid action
pays exactly the same gains no regret, strategies start from the priors. Counterfactual reach: at our depth-1 set,
p_w · y_w(j) of each of its nodes; at a foe node, x(i) (its world's weight is the same in every iteration). The root
step is solve_bayes_rm's arithmetic on the root tables of the current continuation, so a tree without depth-1 nodes is
D1 bit for bit. The gap is the exact exploitability of the averages: our best response bottom-up over our sets, the
foe's per node, then the root as matrix.bayes_exploitability (which it equals without depth-1 nodes). It stops at a gap
of at most epsilon of the tree's range, or raises matrix.RMUnconverged (the named fallback solver_unconverged, Q1).
foe_below = "model" (Q4) keeps the foe's depth-1 strategies at its prior: no regrets there, and its best response
there is not taken.

Python decides no rule here: the tree, its candidates, keys and utilities come from the engine and the networks.
Reproducible like matrix.py: every product and sum over a small axis is accumulated in a fixed order with elementwise
NumPy operations; sums over the nodes of an information set run in node order (np.add.at). The iteration loop works in
buffers allocated once per solve.
"""
import math
from typing import NamedTuple

import numpy as np

from . import matrix
from .errors import SearchError

FOE_BELOW = ("nash", "model")
# From D2's offline pass (plan step 10, docs/benchmarks/2026-10-14-depth-d2): the largest iteration count any recorded
# decision needed to reach epsilon (width 4). The pass's rule (twice that, 980) exceeds its time bound (280), so the
# bound is the measured maximum, apart from the rule; it is checked again on digest-keyed trees before any ladder arm.
# D1's matrix.RM_MAX_ITERATIONS holds for D1's root only (its tables and cost per iteration are not the tree's).
TREE_MAX_ITERATIONS = 490


class Tree(NamedTuple):
    """A two-turn tree. weights (W,): the worlds' weights; leaf (W, K, M): each root edge's value where it is a leaf
    (finite everywhere, read only where node is -1); node (W, K, M): the depth-1 node of each root edge, or -1; info
    (N,): our information set of each node, -1 where we are not requested; z (N, K2, M2): the depth-2 utilities, read
    only at valid entries; own_valid (I, K2) and own_prior (I, K2): our candidates and their prior per set; foe_valid
    (N, M2) and foe_prior (N, M2): the foe's per node. All values from the deciding seat's side."""
    weights: np.ndarray
    leaf: np.ndarray
    node: np.ndarray
    info: np.ndarray
    z: np.ndarray
    own_valid: np.ndarray
    foe_valid: np.ndarray
    own_prior: np.ndarray
    foe_prior: np.ndarray


class TreeSolution(NamedTuple):
    """root: the averages at the root as a matrix.RMSolution (value sum_w p_w min_j (x A_w)_j on the root tables, the
    tree's gap as a share of its range, the iterations); tables (W, K, M): the root tables A_w[i, j] under the averaged
    continuation, unscaled; own (I, K2) and foe (N, M2): the averaged strategies below the root."""
    root: matrix.RMSolution
    tables: np.ndarray
    own: np.ndarray
    foe: np.ndarray


def _own_rows(info, own_valid, k2):
    """(N, K2) bool: our valid responses at each node (column 0 alone where we are not requested)."""
    rows = np.zeros((info.size, k2), dtype=bool)
    mine = info >= 0
    rows[mine] = own_valid[info[mine]]
    rows[~mine, 0] = True
    return rows


def valid_entries(tree):
    """(N, K2, M2) bool: the entries of z the tree reads."""
    info = np.asarray(tree.info, dtype=np.int64)
    own = _own_rows(info, np.asarray(tree.own_valid, dtype=bool), np.shape(tree.z)[1])
    return own[:, :, None] & np.asarray(tree.foe_valid, dtype=bool)[:, None, :]


def _priors(prior, valid, what):
    """The rows of prior renormalized over their valid candidates; mass on a padded candidate is refused."""
    prior = np.asarray(prior, dtype=np.float64)
    if prior.shape != valid.shape or not np.isfinite(prior).all() or (prior < 0).any():
        raise SearchError(f"{what} priors must be nonnegative finite numbers of shape {valid.shape}")
    if (prior[~valid] != 0).any():
        raise SearchError(f"a {what} prior gives mass to a padded candidate")
    return np.stack([matrix._prior(row, valid.shape[1], f"{what} prior {r}") for r, row in enumerate(prior)]) \
        if prior.shape[0] else prior.copy()


def _checked(tree):
    """(a, p, node positions (w, i, j) per node, info, z, own_valid, foe_valid, own prior, foe prior), checked."""
    a, p = matrix._tables(tree.leaf, tree.weights)
    node = np.asarray(tree.node)
    if node.shape != a.shape or not np.issubdtype(node.dtype, np.integer):
        raise SearchError(f"node must be an integer array of shape {a.shape}")
    node = node.astype(np.int64)
    info = np.asarray(tree.info)
    z = np.asarray(tree.z, dtype=np.float64)
    if info.ndim != 1 or not np.issubdtype(info.dtype, np.integer) or z.ndim != 3 or z.shape[0] != info.size \
            or 0 in z.shape[1:]:
        raise SearchError(f"info (N,) and z (N, K2, M2) must agree (got {info.shape}, {z.shape})")
    info = info.astype(np.int64)
    n, k2, m2 = z.shape
    own_valid, foe_valid = np.asarray(tree.own_valid), np.asarray(tree.foe_valid)
    if own_valid.dtype != bool or own_valid.ndim != 2 or own_valid.shape[1] != k2 or \
            foe_valid.dtype != bool or foe_valid.shape != (n, m2):
        raise SearchError(f"own_valid (I, {k2}) and foe_valid ({n}, {m2}) must be bool arrays")
    sets = own_valid.shape[0]
    flat = node.reshape(-1)
    edges = np.flatnonzero(flat >= 0)
    if (flat < -1).any() or not np.array_equal(np.sort(flat[edges]), np.arange(n)):
        raise SearchError(f"every depth-1 node must be reached by exactly one root edge ({n} nodes)")
    where = np.zeros((3, n), dtype=np.int64)
    where[:, flat[edges]] = np.unravel_index(edges, a.shape)
    bad = np.flatnonzero((info < -1) | (info >= sets))
    if bad.size:
        raise SearchError(f"information set {int(info[bad[0]])} of node {int(bad[0])} is not one of the {sets} sets")
    if not np.array_equal(np.unique(info[info >= 0]), np.arange(sets)):
        raise SearchError(f"an information set without a node ({sets} sets)")
    row = np.full(sets, -1, dtype=np.int64)
    for x in np.flatnonzero(info >= 0):
        s, i = int(info[x]), int(where[1, x])
        if row[s] not in (-1, i):
            raise SearchError(f"information set {s} spans the root rows {int(row[s])} and {i} (its key holds the "
                              f"root row: perfect recall)")
        row[s] = i
    if not own_valid.any(axis=1).all() or not foe_valid.any(axis=1).all():
        raise SearchError("a depth-1 information set or node without a candidate")
    own_prior = _priors(tree.own_prior, own_valid, "own")
    foe_prior = _priors(tree.foe_prior, foe_valid, "foe")
    if not np.isfinite(z[valid_entries(tree)]).all():
        raise SearchError("a depth-2 utility that is not finite")
    return a, p, where, row, info, z, own_valid, foe_valid, own_prior, foe_prior


def _first(valid):
    """One-hot rows on each row's first valid candidate."""
    out = np.zeros(valid.shape, dtype=np.float64)
    out[np.arange(valid.shape[0]), np.argmax(valid, axis=1)] = 1.0
    return out


def _normalized(total, prior):
    """Each row of a strategy sum normalized (accumulated over the columns in order), the prior where it is empty."""
    mass = np.zeros(total.shape[0], dtype=np.float64)
    for c in range(total.shape[1]):
        mass += total[:, c]
    out = prior.copy()
    np.divide(total, mass[:, None], out=out, where=mass[:, None] > 0.0)
    return out


def solve_tree(tree, prior, foe_priors, *, iterations=matrix.RM_MAX_ITERATIONS, epsilon=matrix.RM_EPSILON,
               check_every=matrix.RM_CHECK_EVERY, foe_below="nash"):
    """The TreeSolution of tree by CFR+ (see above). prior: our K root candidates' probabilities; foe_priors (W, M):
    each world's root foe candidates' (both renormalized, as solve_bayes_rm). RMUnconverged when the gap of the
    averages is above epsilon at `iterations`. A constant tree plays every first candidate, as solve_bayes_rm."""
    if foe_below not in FOE_BELOW:
        raise ValueError(f"foe_below must be one of {FOE_BELOW} (got {foe_below!r})")
    a, p, where, row, info, z, own_valid, foe_valid, own_prior, foe_prior = _checked(tree)
    nw, k, m = a.shape
    n, k2, m2 = z.shape
    sets = own_valid.shape[0]
    iterations, check_every = matrix._count("iterations", iterations), matrix._count("check_every", check_every)
    epsilon = float(epsilon)
    if not 0.0 < epsilon < 1.0:
        raise SearchError(f"epsilon must lie in (0, 1) (got {epsilon!r})")
    x0 = matrix._prior(prior, k, "prior")
    foe_priors = np.asarray(foe_priors, dtype=np.float64)
    if foe_priors.shape != (nw, m):
        raise SearchError(f"foe_priors must have shape {(nw, m)} (got {foe_priors.shape})")
    y0 = np.stack([matrix._prior(foe_priors[w], m, f"foe_priors[{w}]") for w in range(nw)])
    nodes_w, nodes_i, nodes_j = where
    valid = valid_entries(tree)
    used = np.concatenate([a[np.asarray(tree.node) < 0], z[valid]])
    low = float(used.min())
    span = float(used.max()) - low
    if span == 0.0:
        x = np.zeros(k, dtype=np.float64)
        x[0] = 1.0
        tables = a.copy()
        tables[nodes_w, nodes_i, nodes_j] = low
        return TreeSolution(matrix.RMSolution(matrix.BayesSolution(x, [np.eye(m, dtype=np.float64)[0]
                                                                       for _ in range(nw)], low, False), 0.0, 0),
                            tables, _first(own_valid), _first(foe_valid))
    s = (a - low) / span
    sz = np.where(valid, (z - low) / span, 0.0)  # a padded entry is 0, and every strategy gives it 0
    raw = np.where(valid, z, 0.0)
    mine = info >= 0
    sets_of = info[mine]
    e0 = np.zeros(k2, dtype=np.float64)
    e0[0] = 1.0
    model = foe_below == "model"

    # The root's buffers, as solve_bayes_rm's.
    x, ys = x0.copy(), y0.copy()
    rx, ry = np.zeros(k), np.zeros((nw, m))
    xsum, ysum = np.zeros(k), np.zeros((nw, m))
    rows, row_part = np.zeros((nw, k)), np.zeros((nw, k))
    ours, x_t = np.zeros(k), np.zeros(k)
    cols, col_part, y_t = np.zeros((nw, m)), np.zeros((nw, m)), np.zeros((nw, m))
    foe_value, foe_total, foe_high, foe_low = np.zeros(nw), np.zeros(nw), np.zeros(nw), np.zeros(nw)
    positive, idle, flat = np.zeros(nw, bool), np.zeros((nw, 1), bool), np.zeros(nw, bool)
    cur = np.zeros_like(s)
    # The depth-1 buffers.
    own_sig, own_reg, own_sum = own_prior.copy(), np.zeros((sets, k2)), np.zeros((sets, k2))
    foe_sig, foe_reg, foe_sum = foe_prior.copy(), np.zeros((n, m2)), np.zeros((n, m2))
    node_own, u, cfn = np.zeros((n, k2)), np.zeros((n, k2)), np.zeros((n, k2))
    nk, nm, wv = np.zeros((n, k2)), np.zeros((n, m2)), np.zeros((n, m2))
    v, nv, reach = np.zeros(n), np.zeros(n), np.zeros(n)
    cf, sk, val, set_t = np.zeros((sets, k2)), np.zeros((sets, k2)), np.zeros(sets), np.zeros(sets)
    high, lowest, mass = np.zeros(sets), np.zeros(sets), np.zeros(sets)
    node_high, node_low, node_mass = np.zeros(n), np.zeros(n), np.zeros(n)
    set_flat, set_positive = np.zeros(sets, bool), np.zeros(sets, bool)
    node_flat, node_positive = np.zeros(n, bool), np.zeros(n, bool)

    def gather(strategy, out):
        """Our strategy at each node: its set's, or the single empty response where we are not requested."""
        out[:] = e0
        if sets:
            out[mine] = strategy[sets_of]

    def node_values(own_at, foe_at):
        """v (N,): each node's value; u (N, K2): each of our responses' value against foe_at."""
        u.fill(0.0)
        for b in range(m2):
            np.multiply(sz[:, :, b], foe_at[:, b, None], out=nk)
            np.add(u, nk, out=u)
        v.fill(0.0)
        for c in range(k2):
            np.multiply(own_at[:, c], u[:, c], out=nv)
            np.add(v, nv, out=v)

    def root_tables(values):
        np.copyto(cur, s)
        cur[nodes_w, nodes_i, nodes_j] = values

    def spread(values, valid_rows, out_high, out_low):
        """The highest and lowest value over each row's valid candidates."""
        np.max(np.where(valid_rows, values, -np.inf), axis=1, out=out_high)
        np.min(np.where(valid_rows, values, np.inf), axis=1, out=out_low)

    gap = None
    for t in range(1, iterations + 1):
        # Ours against the foe's current strategies: our depth-1 sets, then the root.
        gather(own_sig, node_own)
        node_values(node_own, foe_sig)
        root_tables(v)
        if sets:
            np.multiply(p[nodes_w], ys[nodes_w, nodes_j], out=reach)
            np.multiply(u, reach[:, None], out=cfn)
            cf.fill(0.0)
            np.add.at(cf, sets_of, cfn[mine])
            np.multiply(x[row], float(t), out=set_t)  # our reach of each set, times t (linear averaging)
            np.multiply(own_sig, set_t[:, None], out=sk)
            own_sum += sk
            val.fill(0.0)
            for c in range(k2):
                np.multiply(own_sig[:, c], cf[:, c], out=set_t)
                val += set_t
            spread(cf, own_valid, high, lowest)
            np.equal(high, lowest, out=set_flat)
            np.subtract(cf, val[:, None], out=sk)
            sk[~own_valid] = 0.0  # a padded candidate gains no regret
            sk[set_flat] = 0.0  # nor any candidate of a set whose every candidate pays the same
            own_reg += sk
            np.maximum(own_reg, 0.0, out=own_reg)
            mass.fill(0.0)
            for c in range(k2):
                mass += own_reg[:, c]
            np.greater(mass, 0.0, out=set_positive)
            np.divide(own_reg, mass[:, None], out=own_sig, where=set_positive[:, None])
            np.copyto(own_sig, own_prior, where=~set_positive[:, None])
        rows.fill(0.0)
        for j in range(m):
            np.multiply(cur[:, :, j], ys[:, j, None], out=row_part)
            rows += row_part
        ours.fill(0.0)
        for w in range(nw):
            np.multiply(rows[w], p[w], out=x_t)
            ours += x_t
        value = 0.0
        for i in range(k):
            value += float(x[i]) * float(ours[i])
        np.multiply(x, float(t), out=x_t)
        xsum += x_t
        if ours.max() != ours.min():
            rx += ours
            rx -= value
            np.maximum(rx, 0.0, out=rx)
        total = 0.0
        for i in range(k):
            total += float(rx[i])
        if total > 0.0:
            np.divide(rx, total, out=x)
        else:
            x[:] = x0
        # The foe's against our new strategies: its depth-1 nodes, then each world's root foe.
        gather(own_sig, node_own)
        wv.fill(0.0)
        for c in range(k2):
            np.multiply(sz[:, c, :], node_own[:, c, None], out=nm)
            wv += nm
        v.fill(0.0)
        for b in range(m2):
            np.multiply(foe_sig[:, b], wv[:, b], out=nv)
            v += nv
        root_tables(v)
        if n and not model:
            np.multiply(ys[nodes_w, nodes_j], float(t), out=nv)  # the foe's reach of each node, times t
            np.multiply(foe_sig, nv[:, None], out=nm)
            foe_sum += nm
            spread(wv, foe_valid, node_high, node_low)
            np.equal(node_high, node_low, out=node_flat)
            np.subtract(v[:, None], wv, out=nm)  # the foe minimizes
            np.multiply(nm, x[nodes_i, None], out=nm)  # our reach of each node
            nm[~foe_valid] = 0.0
            nm[node_flat] = 0.0
            foe_reg += nm
            np.maximum(foe_reg, 0.0, out=foe_reg)
            node_mass.fill(0.0)
            for b in range(m2):
                node_mass += foe_reg[:, b]
            np.greater(node_mass, 0.0, out=node_positive)
            np.divide(foe_reg, node_mass[:, None], out=foe_sig, where=node_positive[:, None])
            np.copyto(foe_sig, foe_prior, where=~node_positive[:, None])
        cols.fill(0.0)
        for i in range(k):
            np.multiply(cur[:, i, :], x[i], out=col_part)
            cols += col_part
        foe_value.fill(0.0)
        for j in range(m):
            np.multiply(ys[:, j], cols[:, j], out=foe_total)
            foe_value += foe_total
        np.multiply(ys, float(t), out=y_t)
        ysum += y_t
        np.max(cols, axis=1, out=foe_high)
        np.min(cols, axis=1, out=foe_low)
        np.equal(foe_high, foe_low, out=flat)
        np.copyto(foe_value, 0.0, where=flat)
        np.copyto(cols, 0.0, where=flat[:, None])
        ry += foe_value[:, None]
        ry -= cols
        np.maximum(ry, 0.0, out=ry)
        foe_total.fill(0.0)
        for j in range(m):
            foe_total += ry[:, j]
        np.greater(foe_total, 0.0, out=positive)
        np.logical_not(positive[:, None], out=idle)
        np.divide(ry, foe_total[:, None], out=ys, where=positive[:, None])
        np.copyto(ys, y0, where=idle)
        if t % check_every == 0 or t == iterations:
            xbar, ybar = matrix._average(xsum), [matrix._average(ysum[w]) for w in range(nw)]
            own_bar = _normalized(own_sum, own_prior)
            foe_bar = foe_prior.copy() if model else _normalized(foe_sum, foe_prior)
            gap = _gap(s, sz, p, where, mine, sets_of, own_valid, foe_valid, model, xbar, ybar, own_bar, foe_bar)
            if gap <= epsilon:
                break
    else:
        raise matrix.RMUnconverged(gap, iterations, epsilon)
    gather(own_bar, node_own)
    u.fill(0.0)  # the unscaled values under the averages
    for b in range(m2):
        np.multiply(raw[:, :, b], foe_bar[:, b, None], out=nk)
        u += nk
    v.fill(0.0)
    for c in range(k2):
        np.multiply(node_own[:, c], u[:, c], out=nv)
        v += nv
    tables = a.copy()
    tables[nodes_w, nodes_i, nodes_j] = v
    value = math.fsum(float(p[w]) * float(np.min(matrix._vecmat(xbar, tables[w]))) for w in range(nw))
    return TreeSolution(matrix.RMSolution(matrix.BayesSolution(xbar, ybar, value, False), float(gap), t), tables,
                        own_bar, foe_bar)


def _gap(s, sz, p, where, mine, sets_of, own_valid, foe_valid, model, xbar, ybar, own_bar, foe_bar):
    """The exact exploitability of the averages on the scaled tree: max_i sum_w p_w (U_w ybar_w)_i - sum_w p_w
    min_j (xbar L_w)_j, with U the root tables under our best response below the root (against foe_bar) and L under
    the foe's (against own_bar; under "model" the foe keeps foe_bar). Without depth-1 nodes, U = L = s and this is
    matrix.bayes_exploitability(s, p, xbar, ybar)."""
    nodes_w, nodes_i, nodes_j = where
    n, k2, m2 = sz.shape
    ub = np.zeros((n, k2))
    for b in range(m2):
        ub += sz[:, :, b] * foe_bar[:, b, None]
    sets = own_valid.shape[0]
    best = np.zeros(n, dtype=np.int64)
    if sets:
        reach = p[nodes_w] * np.stack(ybar)[nodes_w, nodes_j]
        cf = np.zeros((sets, k2))
        np.add.at(cf, sets_of, ub[mine] * reach[mine, None])
        best[mine] = np.argmax(np.where(own_valid, cf, -np.inf), axis=1)[sets_of]  # ties: the first candidate
    upper_nodes = ub[np.arange(n), best]
    own_at = np.zeros((n, k2))
    own_at[:, 0] = 1.0
    if sets:
        own_at[mine] = own_bar[sets_of]
    wb = np.zeros((n, m2))
    for c in range(k2):
        wb += sz[:, c, :] * own_at[:, c, None]
    if model:
        lower_nodes = np.zeros(n)
        for b in range(m2):
            lower_nodes += foe_bar[:, b] * wb[:, b]
    else:
        lower_nodes = np.min(np.where(foe_valid, wb, np.inf), axis=1) if n else np.zeros(0)
    up, low = s.copy(), s.copy()
    up[nodes_w, nodes_i, nodes_j] = upper_nodes
    low[nodes_w, nodes_i, nodes_j] = lower_nodes
    _, q = matrix._tables(up, p)
    upper = np.zeros(s.shape[1], dtype=np.float64)
    lower = 0.0
    for w in range(s.shape[0]):
        upper += q[w] * matrix._matvec(up[w], np.asarray(ybar[w], dtype=np.float64))
        lower += q[w] * float(np.min(matrix._vecmat(xbar, low[w])))
    return float(np.max(upper)) - lower
