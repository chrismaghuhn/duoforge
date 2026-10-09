"""duoforge.python.search_numpy: the NumPy parts of the M12 search (decision 0022).

The matrix game (an exact linear program with its certificate and its
exact rescue), the expected-value rule, the tie rules and the play draw
(spec sections 5.5 and 5.6), the decision keys and play draws (decision
0022 section 2), the lookahead's candidates, leaf plan, table rules and
split halves (spec sections 5 and 7), Batch.encode, and the arena
measurement's statistics and checkpoint choice (spec section 8). The
contract is pinned by literals, never by the module's own constants. The
JAX parts are in test_search.py.
"""
import hashlib
import itertools
import json
import math
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from duoforge_learn.pairing import draw as pairing_draw
from duoforge_learn.pairing import splitmix64
from duoforge_search import SearchError, arena, belief, lookahead, matrix, seeds

_MASK = (1 << 64) - 1
_CERTIFICATE = 1e-9  # spec section 5.5, plan Review Focus 5: never relaxed

# Two rows a few float32 ulps apart (2 x 13): the float simplex pivots on a
# rounding-sized entry and ends in a false "unbounded"; the exact rescue
# decides (review of #199).
_NEAR_DUPLICATE_HEX = [
    ["0x1.cdf7920000000p-1", "0x1.a1d5040000000p-1", "-0x1.ad432e0000000p-1", "-0x1.7108e40000000p-4",
     "0x1.e2aa980000000p-2", "0x1.5c62460000000p-1", "-0x1.facf240000000p-2", "0x1.dd1d340000000p-2",
     "0x1.6e073c0000000p-1", "-0x1.51b4500000000p-2", "0x1.ca6d820000000p-1", "0x1.1e80460000000p-7",
     "-0x1.0636a60000000p-1"],
    ["0x1.cdf7940000000p-1", "0x1.a1d5040000000p-1", "-0x1.ad432e0000000p-1", "-0x1.7108ec0000000p-4",
     "0x1.e2aa960000000p-2", "0x1.5c62460000000p-1", "-0x1.facf240000000p-2", "0x1.dd1d320000000p-2",
     "0x1.6e073e0000000p-1", "-0x1.51b4500000000p-2", "0x1.ca6d820000000p-1", "0x1.1e7fc60000000p-7",
     "-0x1.0636a40000000p-1"],
]


def _random_tables(rng, count):
    """Tables of 1 x 1 to 16 x 16: continuous, integer (degenerate),
    constant, and with duplicated rows and columns."""
    for n in range(count):
        k, m = int(rng.integers(1, 17)), int(rng.integers(1, 17))
        kind = n % 4
        if kind == 0:
            a = rng.uniform(-1.0, 1.0, (k, m))
        elif kind == 1:
            a = rng.integers(-1, 2, (k, m)).astype(np.float64)
        elif kind == 2:
            a = np.full((k, m), rng.uniform(-1.0, 1.0))
        else:
            a = rng.uniform(-1.0, 1.0, (k, m))
            a = a[rng.integers(0, k, k)][:, rng.integers(0, m, m)]  # rows and columns repeated
        yield a


def _near_duplicate_tables(rng, count):
    """Tables of 2 x 1 to 16 x 16 with one row a few float32 ulps from
    another; every other one rounded to float32, as value heads give them."""
    for n in range(count):
        k, m = int(rng.integers(2, 17)), int(rng.integers(1, 17))
        a = rng.uniform(-1.0, 1.0, (k, m))
        i, j = rng.choice(k, 2, replace=False)
        a[j] = a[i] + rng.uniform(-6e-8, 6e-8, m)
        if n % 2:
            a = a.astype(np.float32).astype(np.float64)
        yield a


def _budget_cases():
    """(kind, tables, weights) for the budget identity pin: both float
    fixtures, random and near-duplicate worlds, and small exact rescues."""
    for name in ("bayes-arena-16x8x8.json", "bayes-arena-16x8x8-tiny-pivot.json"):
        saved = json.loads((Path(__file__).with_name("fixtures") / name).read_text())
        yield "bayes", np.asarray(saved["tables"], dtype=np.float64), np.asarray(saved["weights"], dtype=np.float64)
    rng = np.random.default_rng(20261009)
    for w, k, m in ((2, 2, 2), (4, 8, 8), (16, 8, 8), (3, 5, 1), (5, 1, 4)):
        yield "bayes", rng.random((w, k, m)).astype(np.float32).astype(np.float64), rng.random(w) + 0.1
    a = rng.uniform(-1, 1, (16, 8, 8)).astype(np.float32).astype(np.float64)
    a[:, 1] = a[:, 0]
    a[:, 2] = a[:, 0] + rng.choice([-1, 1], (16, 8)) * 2**-24
    yield "bayes", a, rng.random(16) + 0.1
    for w, k, m in ((2, 2, 2), (2, 3, 3)):
        yield "bayes_exact", rng.random((w, k, m)), rng.random(w) + 0.1
    for a in _random_tables(np.random.default_rng(20261010), 8):
        yield "matrix", a, None
    yield "matrix", np.array([[float.fromhex(v) for v in row] for row in _NEAR_DUPLICATE_HEX]), None
    for k, m in ((2, 2), (3, 4)):
        yield "matrix_exact", rng.random((k, m)), None


def _budget_digest(solve_bayes, solve):
    """SHA-256 over every solution's bytes; exact cases force the rescue."""
    h = hashlib.sha256()
    for kind, tables, weights in _budget_cases():
        if kind == "bayes":
            sol = solve_bayes(tables, weights)
        elif kind == "bayes_exact":
            with patch.object(matrix, "_bland_float", side_effect=SearchError("float failed")):
                sol = solve_bayes(tables, weights)
        elif kind == "matrix":
            sol = solve(tables)
        else:
            with patch.object(matrix, "_solve_float", side_effect=SearchError("float failed")):
                sol = solve(tables)
        ys = sol.ys if hasattr(sol, "ys") else [sol.y]
        h.update(kind.encode() + sol.x.tobytes() + b"".join(np.asarray(y).tobytes() for y in ys)
                 + struct.pack("<d?", sol.value, sol.exact))
    return h.hexdigest()


def _support_value(a):
    """The game value of a nondegenerate table by support enumeration, for
    up to 4 x 4: equal-size supports, the indifference systems solved
    exactly, the equilibrium conditions checked."""
    k, m = a.shape
    for s in range(1, min(k, m) + 1):
        for rows in itertools.combinations(range(k), s):
            for cols in itertools.combinations(range(m), s):
                sub = a[np.ix_(rows, cols)]
                lhs_x = np.zeros((s + 1, s + 1))
                lhs_x[:s, :s] = sub.T
                lhs_x[:s, s] = -1.0
                lhs_x[s, :s] = 1.0
                lhs_y = np.zeros((s + 1, s + 1))
                lhs_y[:s, :s] = sub
                lhs_y[:s, s] = -1.0
                lhs_y[s, :s] = 1.0
                rhs = np.zeros(s + 1)
                rhs[s] = 1.0
                try:
                    sx = np.linalg.solve(lhs_x, rhs)
                    sy = np.linalg.solve(lhs_y, rhs)
                except np.linalg.LinAlgError:
                    continue
                if (sx[:s] < -1e-12).any() or (sy[:s] < -1e-12).any():
                    continue
                x = np.zeros(k)
                y = np.zeros(m)
                x[list(rows)] = sx[:s]
                y[list(cols)] = sy[:s]
                v = sx[s]
                if np.max(a @ y) <= v + 1e-12 and np.min(x @ a) >= v - 1e-12:
                    return v
    raise AssertionError(f"no equilibrium found by support enumeration for {a!r}")


class Nash(unittest.TestCase):
    def _assert_equilibrium(self, a, sol):
        x, y = sol.x, sol.y
        self.assertEqual(x.shape, (a.shape[0],))
        self.assertEqual(y.shape, (a.shape[1],))
        for v in (x, y):
            self.assertTrue((v >= 0).all())
            self.assertAlmostEqual(math.fsum(v.tolist()), 1.0, delta=1e-12)
        self.assertLessEqual(matrix.exploitability(a, x, y), _CERTIFICATE)
        lower, upper = float(np.min(x @ a)), float(np.max(a @ y))
        self.assertLessEqual(min(lower, upper) - 1e-12, sol.value)
        self.assertLessEqual(sol.value, max(lower, upper) + 1e-12)

    def test_contract_constants(self):
        self.assertEqual(matrix.CERTIFICATE, 1e-9)
        self.assertEqual(matrix.PROBABILITY_FLOOR, 1e-9)

    def test_certificate_on_random_tables(self):
        rng = np.random.default_rng(0x2026100300000600)
        for a in _random_tables(rng, 2000):
            self._assert_equilibrium(a, matrix.solve(a))

    def test_agrees_with_support_enumeration(self):
        rng = np.random.default_rng(0x2026100300000601)
        for _ in range(300):
            a = rng.uniform(-1.0, 1.0, (int(rng.integers(1, 5)), int(rng.integers(1, 5))))
            sol = matrix.solve(a)
            self.assertAlmostEqual(sol.value, _support_value(a), delta=1e-12)

    def test_saddle_points_are_pure(self):
        rng = np.random.default_rng(0x2026100300000602)
        for _ in range(200):
            k, m = int(rng.integers(1, 9)), int(rng.integers(1, 9))
            i, j = int(rng.integers(0, k)), int(rng.integers(0, m))
            a = rng.uniform(-1.0, 1.0, (k, m))
            a[i, :] = rng.uniform(0.1, 1.0, m)  # the row's other entries are better for the row player
            a[:, j] = rng.uniform(-1.0, -0.1, k)  # the column's other entries are worse for the row player
            a[i, j] = 0.0
            sol = matrix.solve(a)
            self.assertAlmostEqual(float(sol.x[i]), 1.0, delta=1e-12)
            self.assertAlmostEqual(float(sol.y[j]), 1.0, delta=1e-12)
            self.assertAlmostEqual(sol.value, 0.0, delta=1e-12)

    def test_known_games(self):
        sol = matrix.solve([[1.0, -1.0], [-1.0, 1.0]])  # matching pennies
        np.testing.assert_allclose(sol.x, [0.5, 0.5], atol=1e-12)
        np.testing.assert_allclose(sol.y, [0.5, 0.5], atol=1e-12)
        self.assertAlmostEqual(sol.value, 0.0, delta=1e-12)
        sol = matrix.solve([[0.0, -1.0, 1.0], [1.0, 0.0, -1.0], [-1.0, 1.0, 0.0]])  # rock, paper, scissors
        np.testing.assert_allclose(sol.x, [1 / 3] * 3, atol=1e-12)
        np.testing.assert_allclose(sol.y, [1 / 3] * 3, atol=1e-12)
        self.assertAlmostEqual(sol.value, 0.0, delta=1e-12)
        sol = matrix.solve([[3.0, -1.0], [-1.0, 1.0], [-2.0, -2.0]])  # the last row is strictly dominated
        self.assertEqual(float(sol.x[2]), 0.0)
        self.assertAlmostEqual(sol.value, 1.0 / 3.0, delta=1e-12)
        sol = matrix.solve([[0.25]])
        self.assertEqual((float(sol.x[0]), float(sol.y[0]), sol.value, sol.exact), (1.0, 1.0, 0.25, False))

    def test_ties_follow_row_order(self):
        """Documented (module, "Rows in prior-rank order"): of several
        equilibria the first rows and columns win, so the search passes rows
        in prior-rank order."""
        sol = matrix.solve(np.full((4, 3), -0.375))  # a constant table
        np.testing.assert_array_equal(sol.x, [1.0, 0.0, 0.0, 0.0])
        np.testing.assert_array_equal(sol.y, [1.0, 0.0, 0.0])
        self.assertEqual(sol.value, -0.375)

    def test_bland_rule_pinned(self):
        """Rows 0 and 1 are both optimal; Bland's rule ends at row 0, the
        largest-reduced-cost rule (Dantzig) at row 1."""
        a = np.array([[2.0, -1.0, -1.0], [2.0, 0.0, -1.0], [-2.0, 2.0, -2.0]])
        sol = matrix.solve(a)
        np.testing.assert_array_equal(sol.x, [1.0, 0.0, 0.0])
        np.testing.assert_array_equal(sol.y, [0.0, 0.0, 1.0])
        self.assertFalse(sol.exact)
        x, y = matrix._simplex_exact(a)  # the rescue follows the same rule
        np.testing.assert_array_equal(x, [1.0, 0.0, 0.0])
        np.testing.assert_array_equal(y, [0.0, 0.0, 1.0])

    def test_certificate_threshold(self):
        """Matching pennies with x off by delta: the exploitability is exactly
        2 delta, and the certificate holds at 1e-9 and no looser."""
        a = np.array([[1.0, -1.0], [-1.0, 1.0]])
        y = np.array([0.5, 0.5])
        for delta, passes in ((1e-6, False), (1e-9, False), (2.5e-10, True)):
            x = np.array([0.5 + delta, 0.5 - delta])
            if passes:
                self.assertAlmostEqual(matrix.certify(a, x, y), 2 * delta, delta=1e-15)
            else:
                with self.assertRaisesRegex(SearchError, "certificate is missed"):
                    matrix.certify(a, x, y)

    def test_flat_tables_are_guarded(self):
        """On a table whose range is below 1 the bound is relative to the
        range, so a flat table cannot pass wrong strategies."""
        a = 0.3 + 1e-10 * np.array([[1.0, -1.0], [-1.0, 1.0]])
        with self.assertRaisesRegex(SearchError, "certificate is missed"):
            matrix.certify(a, [1.0, 0.0], [1.0, 0.0])  # exploitability 2e-10 < 1e-9, but the whole range
        sol = matrix.solve(a)
        np.testing.assert_allclose(sol.x, [0.5, 0.5], atol=1e-9)
        np.testing.assert_allclose(sol.y, [0.5, 0.5], atol=1e-9)

    def test_missed_certificate_raises(self):
        a = np.array([[1.0, -1.0], [-1.0, 1.0]])
        sol = matrix.solve(a)
        with self.assertRaisesRegex(SearchError, "certificate is missed: exploitability"):
            matrix.certify(a, np.array([0.9, 0.1]), sol.y)
        with self.assertRaisesRegex(SearchError, "not a mixed strategy"):
            matrix.certify(a, np.array([0.7, 0.7]), sol.y)

    def test_near_degenerate_tables_are_solved(self):
        """Valid tables with near-duplicate rows are never refused (review of
        #199): the final basis is solved again from the table, and the exact
        rescue decides where the float simplex fails."""
        a = np.array([[0.0, -1.0, 0.0], [0.0, -0.99999999, 1e-8], [-1.0, 1.0, 0.0]])
        self._assert_equilibrium(a, matrix.solve(a))
        a = np.array([[float.fromhex(v) for v in row] for row in _NEAR_DUPLICATE_HEX])
        sol = matrix.solve(a)
        self.assertTrue(sol.exact)
        self._assert_equilibrium(a, sol)
        with self.assertRaisesRegex(SearchError, "unbounded"):  # what the float path alone does
            matrix._solve_float(a, float(a.min()), float(a.max() - a.min()))
        rng = np.random.default_rng(0x2026100300000603)
        for a in _near_duplicate_tables(rng, 3000):
            self._assert_equilibrium(a, matrix.solve(a))

    def test_exact_rescue_agrees(self):
        rng = np.random.default_rng(0x2026100300000604)
        for _ in range(100):
            a = rng.uniform(-1.0, 1.0, (int(rng.integers(1, 7)), int(rng.integers(1, 7))))
            x, y = matrix._simplex_exact(a)
            self.assertLessEqual(matrix.exploitability(a, x, y), 1e-15)
            self.assertAlmostEqual(float(np.max(a @ y)), matrix.solve(a).value, delta=1e-12)

    def test_bad_tables_raise(self):
        for bad in (np.zeros((0, 2)), np.zeros(3), [[np.nan, 0.0]], [[np.inf]]):
            with self.assertRaises(SearchError):
                matrix.solve(bad)


class ExpectedValue(unittest.TestCase):
    def test_expected_choice(self):
        a = np.array([[0.0, 1.0], [0.9, 0.2], [-1.0, -1.0]])
        self.assertEqual(matrix.expected_choice(a, [0.5, 0.5], [0, 1, 2]), 1)  # 0.55 against 0.5
        self.assertEqual(matrix.expected_choice(a, [1.0, 3.0], [0, 1, 2]), 0)  # q is renormalized: 0.75 against 0.375

    def test_expected_choice_ties(self):
        a = np.array([[0.5, 0.5], [0.5, 0.5], [0.0, 1.0]])
        self.assertEqual(matrix.expected_choice(a, [0.5, 0.5], [2, 1, 0]), 2)  # equal: the best prior rank
        self.assertEqual(matrix.expected_choice(a, [0.5, 0.5], [0, 1, 2]), 0)
        self.assertEqual(matrix.expected_choice(a, [0.5, 0.5], [1, 0, 2]), 1)

    def test_identical_rows_tie_to_rank(self):
        """Bit-identical rows score bit-identically whatever their position
        (no BLAS), so the better prior rank wins every time (review of #199)."""
        rng = np.random.default_rng(0x2026100300000605)
        for _ in range(2000):
            k, m = int(rng.integers(2, 17)), int(rng.integers(1, 17))
            a = rng.uniform(-1.0, 0.0, (k, m))
            best, twin = rng.choice(k, 2, replace=False)
            a[best] = rng.uniform(0.5, 1.0, m)  # better than every other row for every q
            a[twin] = a[best]
            q = rng.uniform(0.01, 1.0, m)
            rank = rng.permutation(k)
            want = best if rank[best] < rank[twin] else twin
            self.assertEqual(matrix.expected_choice(a, q, rank), want)

    def test_one_ulp_beats_rank(self):
        a = np.array([[0.5], [np.nextafter(0.5, 1.0)]])
        self.assertEqual(matrix.expected_choice(a, [1.0], [0, 1]), 1)  # higher by one ulp: no tolerance

    def test_bad_inputs_raise(self):
        a = np.zeros((2, 2))
        for q, rank in (([0.0, 0.0], [0, 1]), ([-1.0, 2.0], [0, 1]), ([1.0], [0, 1]), ([1.0, 1.0], [0, 0]),
                        ([1.0, 1.0], [0.0, 1.0])):
            with self.assertRaises(SearchError):
                matrix.expected_choice(a, q, rank)


class Draw(unittest.TestCase):
    def test_draw_walks_rank_order(self):
        x = np.array([0.2, 0.5, 0.3])
        rank = np.array([2, 0, 1])  # walk rows 1, 2, 0
        self.assertEqual(matrix.draw(x, rank, 0.0), 1)
        self.assertEqual(matrix.draw(x, rank, 0.49), 1)
        self.assertEqual(matrix.draw(x, rank, 0.5), 2)
        self.assertEqual(matrix.draw(x, rank, 0.79), 2)
        self.assertEqual(matrix.draw(x, rank, 0.8), 0)
        self.assertEqual(matrix.draw(x, rank, np.nextafter(1.0, 0.0)), 0)

    def test_floor_drops_and_renormalizes(self):
        x = np.array([5e-10, 0.5, 0.5 - 5e-10])
        self.assertEqual(matrix.draw(x, [0, 1, 2], 0.0), 1)  # row 0 is below the floor: no mass
        self.assertEqual(matrix.draw(x, [0, 1, 2], np.nextafter(1.0, 0.0)), 2)

    def test_floor_is_two_sided(self):
        self.assertEqual(matrix.draw([1e-9, 1.0 - 1e-9], [0, 1], 0.0), 0)  # at the floor: kept
        below = np.nextafter(1e-9, 0.0)
        self.assertEqual(matrix.draw([below, 1.0 - below], [0, 1], 0.0), 1)  # just below: dropped

    def test_fallback_when_rounding_ends_below_u(self):
        x = np.full(10, 0.1)
        u = np.nextafter(1.0, 0.0)
        self.assertLessEqual(float(np.cumsum(x / math.fsum(x.tolist()))[-1]), u)  # the path is taken
        self.assertEqual(matrix.draw(x, np.arange(10), u), 9)
        self.assertEqual(matrix.draw(x, np.arange(10)[::-1].copy(), u), 0)  # the last row with mass in rank order

    def test_bad_draws_raise(self):
        for x, u in (([1.0], 1.0), ([1.0], -0.1), ([1e-12], 0.5), ([np.nan], 0.5)):
            with self.assertRaises(SearchError):
                matrix.draw(x, [0], u)


class Seeds(unittest.TestCase):
    def _key(self, arena_seed, env, episode, epoch, seat):
        """A scalar transcription of decision 0022 section 2, with the tag
        written out."""
        sm = lambda v: int(splitmix64(np.uint64(v & _MASK)))
        base = int(pairing_draw(arena_seed, 0x2201, np.array([env]), np.array([episode]))[0])
        return sm(sm((base + epoch) & _MASK) + seat)

    def test_contract_tags(self):
        self.assertEqual(seeds.KEY_TAG, 0x2201)
        self.assertEqual(seeds.PLAY_TAG, 0x504C415900000001)

    def test_known_values(self):
        key = seeds.decision_keys(0x2026100300000222, [3], [5], [7], [1])
        self.assertEqual(int(key[0]), 0x1F5BA13600FA1FC4)  # computed independently in the review of #199
        u = seeds.play_uniforms(0x2026100300000221, np.array([0x1F5BA13600FA1FC4], dtype=np.uint64))
        self.assertEqual(int(u[0] * 2.0 ** 53), 0x1ADCF14469D42B)

    def test_keys_formula(self):
        rng = np.random.default_rng(0x2026100300000700)
        envs = rng.integers(0, 4096, 50)
        episodes = rng.integers(0, 2 ** 32, 50)
        epochs = rng.integers(0, 2 ** 32, 50)
        seats = rng.integers(0, 2, 50)
        keys = seeds.decision_keys(0x2026100300000222, envs, episodes, epochs, seats)
        self.assertEqual(keys.dtype, np.uint64)
        for n in range(50):
            self.assertEqual(int(keys[n]), self._key(0x2026100300000222, int(envs[n]), int(episodes[n]),
                                                     int(epochs[n]), int(seats[n])))

    def test_keys_are_distinct(self):
        env, episode, epoch, seat = np.meshgrid(np.arange(64), np.arange(4), np.arange(200), np.arange(2),
                                                indexing="ij")
        keys = seeds.decision_keys(0x2026100300000222, env.ravel(), episode.ravel(), epoch.ravel(), seat.ravel())
        self.assertEqual(np.unique(keys).size, keys.size)

    def test_uniforms_in_unit_interval(self):
        keys = np.arange(100_000, dtype=np.uint64)
        u = seeds.play_uniforms(0x2026100300000221, keys)
        self.assertEqual(u.dtype, np.float64)
        self.assertTrue(((u >= 0.0) & (u < 1.0)).all())
        self.assertTrue((u * 2.0 ** 53 == np.floor(u * 2.0 ** 53)).all())  # 53-bit resolution
        sm = lambda v: int(splitmix64(np.uint64(v & _MASK)))
        head = sm(0x2026100300000221 + 0x504C415900000001)
        self.assertEqual(u[7], (sm(head + 7) >> 11) * 2.0 ** -53)

    def test_order_free(self):
        rng = np.random.default_rng(0x2026100300000701)
        envs, episodes, epochs = (rng.integers(0, 1000, 40) for _ in range(3))
        seats = rng.integers(0, 2, 40)
        perm = rng.permutation(40)
        keys = seeds.decision_keys(5, envs, episodes, epochs, seats)
        shuffled = seeds.decision_keys(5, envs[perm], episodes[perm], epochs[perm], seats[perm])
        np.testing.assert_array_equal(shuffled, keys[perm])
        np.testing.assert_array_equal(seeds.play_uniforms(9, keys[perm]), seeds.play_uniforms(9, keys)[perm])

    def test_bad_inputs_raise(self):
        with self.assertRaises(ValueError):
            seeds.decision_keys(0, [0], [0], [0], [2])
        with self.assertRaises(ValueError):
            seeds.decision_keys(0, [-1], [0], [0], [0])
        with self.assertRaises(ValueError):
            seeds.play_uniforms(0, [0.5])


_OK = 0
_UNSUPPORTED = 11  # DUOFORGE_E_UNSUPPORTED
_SIDE_0, _SIDE_1, _TIE = 1, 2, 3  # DUOFORGE_RESULT_*


def _table(values, step, encode, results, tiebreaks, seat, last_step=False, k=1, m=2, s=2):
    _, i, j, sample = lookahead.leaf_plan([k], [m], s)
    return lookahead.table(np.array(values, dtype=np.float32), np.array(step), np.array(encode),
                           np.array(results), np.array(tiebreaks), (i, j, sample), seat, last_step)


class LookaheadParts(unittest.TestCase):
    """The NumPy parts of the lookahead (plan task 9): candidates, the leaf
    plan, the table rules of spec sections 5.3 and 7, split halves."""

    def test_contract_constants(self):
        self.assertEqual(lookahead.SEARCH_SEED, 0x2026100300000221)
        self.assertEqual(lookahead.CAPACITY, 16384)
        self.assertEqual(lookahead.NEAR_DUPLICATE, 1e-6)
        self.assertEqual((_UNSUPPORTED, _SIDE_0, _SIDE_1, _TIE), (lookahead._UNSUPPORTED, *lookahead._RESULTS))

    def test_select_top_k_and_ties(self):
        logp = np.full(1024, -50.0, dtype=np.float32)
        mask = np.zeros(1024, dtype=bool)
        legal = [3, 7, 40, 41, 900, 1023]
        mask[legal] = True
        logp[legal] = [-1.0, -0.5, -0.5, -2.0, -0.5, -3.0]
        logp[5] = 0.0  # the best value, but illegal
        pairs, probs = lookahead.select(logp, mask, 4)
        self.assertEqual(pairs.tolist(), [7, 40, 900, 3])  # equal values to the lower flat index
        np.testing.assert_array_equal(probs, np.exp(np.float32([-0.5, -0.5, -0.5, -1.0]).astype(np.float64)))
        self.assertEqual(lookahead.select(logp, mask, 8)[0].tolist(), [7, 40, 900, 3, 41, 1023])  # k' = 6
        self.assertEqual(lookahead.select(logp, mask.reshape(32, 32), 1)[0].tolist(), [7])
        one_ulp = logp.copy()
        one_ulp[900] = np.nextafter(np.float32(-0.5), np.float32(0.0))  # exact comparisons
        self.assertEqual(lookahead.select(one_ulp, mask, 2)[0].tolist(), [900, 7])
        with self.assertRaises(SearchError):
            lookahead.select(logp, np.zeros(1024, dtype=bool), 1)
        with self.assertRaises(ValueError):
            lookahead.select(logp, mask, 0)
        bad = logp.copy()
        bad[41] = np.nan
        with self.assertRaises(SearchError):
            lookahead.select(bad, mask, 2)

    def test_leaf_plan_order(self):
        d, i, j, s = lookahead.leaf_plan([2, 1], [1, 3], 2)
        self.assertEqual(list(zip(d.tolist(), i.tolist(), j.tolist(), s.tolist())),
                         [(0, 0, 0, 0), (0, 0, 0, 1), (0, 1, 0, 0), (0, 1, 0, 1), (1, 0, 0, 0), (1, 0, 0, 1),
                          (1, 0, 1, 0), (1, 0, 1, 1), (1, 0, 2, 0), (1, 0, 2, 1)])
        self.assertEqual(lookahead.leaf_plan([8] * 3, [8] * 3, 16)[0].size, 3 * 1024)
        for k, m, s in (([0], [1], 1), ([1], [1], 0), ([1, 1], [1], 1)):
            with self.assertRaises(ValueError):
                lookahead.leaf_plan(k, m, s)

    def test_table_rules(self):
        # A terminal win, a value-head leaf, a tie, a refused step, from both seats.
        for seat, want in ((0, [0.625, -0.5]), (1, [-0.375, -0.5])):
            t = _table([0.9, 0.25, 0.9, 0.9], [_OK, _OK, _OK, _UNSUPPORTED], [0] * 4, [_SIDE_0, 0, _TIE, 0],
                       [0] * 4, seat)
            np.testing.assert_array_equal(t.a, [want])
            self.assertEqual(t.counts, {"refused": 1, "terminal": 2, "cut_off": 0, "unresolved": 0})
        # The arena's cut-off: the tiebreak (unresolvable: -1) and never the value head; TERMINAL by its result.
        t = _table([0.9] * 4, [_OK] * 4, [0] * 4, [0, 0, 0, _TIE], [_SIDE_1, _SIDE_0, lookahead.UNRESOLVED, 0],
                   1, last_step=True)
        np.testing.assert_array_equal(t.a, [[0.0, -0.5]])
        self.assertEqual(t.counts, {"refused": 0, "terminal": 1, "cut_off": 3, "unresolved": 1})
        np.testing.assert_array_equal(t.values, [[[1.0, -1.0], [-1.0, 0.0]]])
        # Standard errors over the samples; one sample has none.
        t = _table([0.25, 0.75, 0.5, 0.5], [_OK] * 4, [0] * 4, [0] * 4, [0] * 4, 0)
        np.testing.assert_array_equal(t.a, [[0.5, 0.5]])
        np.testing.assert_allclose(t.stderr, [[0.25, 0.0]], rtol=0, atol=1e-15)
        t = _table([0.25, 0.75], [_OK] * 2, [0] * 2, [0] * 2, [0] * 2, 0, s=1)
        self.assertTrue(np.isnan(t.stderr).all())
        # Leaves in another order give the same table.
        _, i, j, sample = lookahead.leaf_plan([2], [2], 2)
        v = np.float32([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
        perm = np.array([5, 0, 7, 2, 1, 6, 3, 4])
        zero = np.zeros(8, dtype=np.int64)
        a = lookahead.table(v, zero, zero, zero, zero, (i, j, sample), 0)
        b = lookahead.table(v[perm], zero, zero, zero, zero, (i[perm], j[perm], sample[perm]), 0)
        np.testing.assert_array_equal(a.a, b.a)
        np.testing.assert_array_equal(a.values, b.values)

    def test_fatal_leaves_stop_the_run(self):
        # Spec section 7: every step status but OK and E_UNSUPPORTED stops the run, naming the leaf.
        for status in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12):  # every status but OK and E_UNSUPPORTED (11)
            step = [_OK, _OK, status, _OK]
            with self.assertRaises(SearchError) as caught:
                _table([0.0] * 4, step, [0] * 4, [0] * 4, [0] * 4, 0)
            self.assertEqual(caught.exception.leaf, 2)
        with self.assertRaisesRegex(SearchError, "leaf 1: the value head") as caught:
            _table([0.0, np.nan, 0.0, 0.0], [_OK] * 4, [0] * 4, [0] * 4, [0] * 4, 0)
        with self.assertRaisesRegex(SearchError, "not at the cut-off"):
            _table([0.0] * 4, [_OK] * 4, [0] * 4, [0] * 4, [0, _SIDE_0, 0, 0], 0)
        with self.assertRaisesRegex(SearchError, "at the cut-off"):
            _table([0.0] * 4, [_OK] * 4, [0] * 4, [0] * 4, [_SIDE_0, 0, _TIE, _TIE], 0, last_step=True)
        with self.assertRaises(SearchError):
            _table([0.0] * 4, [_OK] * 4, [0] * 4, [0, 9, 0, 0], [0] * 4, 0)  # an unknown result
        with self.assertRaises(ValueError):
            _table([0.0] * 3, [_OK] * 3, [0] * 3, [0] * 3, [0] * 3, 0)

    def test_encoder_refusal_stops_the_run(self):
        # Spec section 7: a refused row is never scored -1; the run stops, naming the leaf.
        with self.assertRaisesRegex(SearchError, "leaf 3: the encoder refused") as caught:
            _table([0.0] * 4, [_OK] * 4, [0, 0, 0, 2], [0] * 4, [0] * 4, 1)
        self.assertEqual(caught.exception.leaf, 3)

    def test_split_half(self):
        pennies = [[1.0, -1.0], [-1.0, 1.0]]  # x = y = (1/2, 1/2)
        biased = [[2.0, 0.0], [0.0, 1.0]]  # x = y = (1/3, 2/3)
        cube = np.concatenate([np.repeat(np.array(pennies)[:, :, None], 2, axis=2),
                               np.repeat(np.array(biased)[:, :, None], 2, axis=2)], axis=2)
        out = lookahead.split_half(cube, [0.5, 0.5], "nash")
        np.testing.assert_allclose(out["exploitability"], [0.5, 2.0 / 3.0], rtol=0, atol=1e-12)
        self.assertEqual(lookahead.split_half(cube, [0.5, 0.5], "ev"), {"same_choice": True})
        swap = cube.copy()
        swap[:, :, :2] = [[[0.0], [0.0]], [[1.0], [1.0]]]  # the first half prefers row 1
        self.assertEqual(lookahead.split_half(swap, [0.5, 0.5], "ev"), {"same_choice": False})
        self.assertIsNone(lookahead.split_half(cube[:, :, :3], [0.5, 0.5], "ev"))
        with self.assertRaises(ValueError):
            lookahead.split_half(cube, [0.5, 0.5], "mean")

    def test_near_duplicates(self):
        a = np.array([[0.5, -0.25], [0.5 + 5e-7, -0.25], [0.5, -0.25 - 2e-6], [0.5, -0.25]])
        self.assertEqual(lookahead.near_duplicates(a), 3)  # (0, 1), (0, 3), (1, 3)
        self.assertEqual(lookahead.near_duplicates(a[:1]), 0)


class BatchEncode(unittest.TestCase):
    def test_encode_is_the_canonical_state(self):
        # Batch.encode, privileged: the reproduction data of a stopped search (spec section 7).
        import hashlib

        import duoforge
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups([0, 3]), 1, 7) as b, \
                duoforge.Batch(ctx, duoforge.reference_setups([0, 3]), 1, 7) as twin:
            for e in range(2):
                self.assertEqual(hashlib.sha256(b.encode(e)).digest(), b.digest(e))
                self.assertEqual(b.encode(e), twin.encode(e))
            before = b.encode(0)
            b.query_factored()
            b.step_factored(duoforge.RandomPolicy(7, 2).choose_factored(b))
            self.assertNotEqual(b.encode(0), before)
            self.assertEqual(hashlib.sha256(b.encode(0)).digest(), b.digest(0))
            with self.assertRaises(IndexError):
                b.encode(2)


class ArenaStatistics(unittest.TestCase):
    """The NumPy parts of the measurement (plan task 11, spec section 8)."""

    def test_contract_constants(self):
        self.assertEqual((arena.ARENA_SEED, arena.BOOTSTRAP_SEED, arena.RESAMPLES, arena.GAMES, arena.MAX_STEPS),
                         (0x2026100300000222, 0x2026100300000220, 2000, 2048, 1000))
        self.assertEqual(arena.PANEL, (25, 50, 75))

    def test_bootstrap_is_seeded_and_paired(self):
        rng = np.random.default_rng(0x2026100400000100)
        a, b = rng.choice([0.0, 0.5, 1.0], 300), rng.choice([0.0, 0.5, 1.0], 300)
        low, high = arena.bootstrap_mean(a)
        self.assertEqual((low, high), arena.bootstrap_mean(a.copy()))  # seeded: the same rows, the same interval
        self.assertLess(low, a.mean())
        self.assertLess(a.mean(), high)
        self.assertNotEqual(arena.bootstrap_mean(a, seed=1), arena.bootstrap_mean(a, seed=2))
        self.assertEqual(arena.bootstrap_paired(a, a), (0.0, 0.0))
        self.assertEqual(arena.bootstrap_paired(a, b), arena.bootstrap_mean(a - b))  # the rows resampled together
        self.assertEqual(arena.bootstrap_mean(np.full(10, 0.5)), (0.5, 0.5))
        for bad in (lambda: arena.bootstrap_paired(a, b[:-1]), lambda: arena.bootstrap_mean([]),
                    lambda: arena.bootstrap_mean(a, resamples=0)):
            with self.assertRaises(ValueError):
                bad()

    def test_elo_mapping(self):
        self.assertEqual(arena.elo(0.5), 0.0)
        self.assertAlmostEqual(arena.elo(0.75), 400.0 * math.log10(3.0), places=12)
        s = np.linspace(0.01, 0.99, 99)
        e = arena.elo(s)
        self.assertTrue((np.diff(e) > 0).all())  # monotone
        np.testing.assert_allclose(arena.elo(1.0 - s), -e, rtol=0, atol=1e-9)
        self.assertEqual((arena.elo(0.0), arena.elo(1.0)), (-math.inf, math.inf))
        for bad in (1.5, -0.1, float("nan")):
            with self.assertRaises(ValueError):
                arena.elo(bad)

    def test_checkpoint_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = os.path.join(tmp, "night")
            os.makedirs(run)
            for u in (0, 100, 150, 250, 300, 400):
                open(os.path.join(run, f"params-{u}.npz"), "wb").close()
            panel = arena.panel_checkpoints(run)
            self.assertEqual([(pct, u) for pct, u, _ in panel], [(25, 100), (50, 150), (75, 300)])  # 200: 150 and 250
            self.assertEqual(arena._checkpoint_path(run, "params-250"), os.path.join(run, "params-250.npz"))
            with self.assertRaises(SystemExit):
                arena._checkpoint_path(run, "params-18129")
            with self.assertRaisesRegex(SystemExit, "no ladder.json"):
                arena.best_checkpoint(run)
            players = [{"player": "init", "elo": 900.0}, {"player": "night update 150", "elo": 40.0},
                       {"player": "night update 300", "elo": 55.5}, {"player": "other update 400", "elo": 99.0}]
            with open(os.path.join(run, "ladder.json"), "w", encoding="utf-8") as f:
                json.dump({"players": players}, f)
            self.assertEqual(arena.best_checkpoint(run), os.path.join(run, "params-300.npz"))  # this run's best

    def test_timing_and_diagnostics(self):
        def record(kind, ms=(1.0, 2.0, 3.0, 4.0), **fields):
            r = {"kind": kind, "time": dict(zip(arena.PARTS, (x / 1000.0 for x in ms)))}
            r.update(fields)
            return r

        searched = dict(boundary="TURN", changed=True, coverage=0.5, near_duplicates=1, rule="nash", exact=False,
                        support=[2, 1], split={"exploitability": [0.1, 0.3]},
                        leaves={"refused": 1, "terminal": 0, "cut_off": 0, "unresolved": 0, "TURN": 3})
        records = [record("searched", **searched), record("searched", (2.0, 2.0, 2.0, 2.0), **searched),
                   record("forced"), record("team")]
        clock = arena.timing(records)
        self.assertEqual(clock["searched"], 2)
        self.assertEqual(clock["ms"]["total"]["median"], 9.0)  # (10 + 8) / 2
        self.assertEqual(clock["ms"]["network"]["median"], 1.5)
        self.assertEqual(arena.timing(records[2:]), {"searched": 0, "ms": None})
        d = arena.diagnostics(records, games=2)
        self.assertEqual(d["decisions"], {"searched": 2, "forced": 1, "team": 1})
        self.assertEqual((d["searched_per_game"], d["changed"], d["near_duplicates"], d["exact"]), (1.0, 1.0, 2, 0))
        self.assertEqual(d["leaves"]["refused"], 2)
        self.assertAlmostEqual(d["split_exploitability"], 0.2)
        self.assertEqual(arena._finite({"a": [1.0, math.nan, math.inf], "b": 2}), {"a": [1.0, None, None], "b": 2})


class BayesRule(unittest.TestCase):
    """The Bayesian Nash rule (decision 0023, spec section 6.3)."""

    def test_arena_reproduction_avoids_rational_blowup(self):
        # Numeric payoffs only, captured from the stopped 16-world arena
        # pilot. The origin basis produced an empty float strategy and
        # sent this small game into seconds of rational tableau pivots.
        self._assert_fast_reproduction("bayes-arena-16x8x8.json", 0.5064255588992647)

    def test_arena_tiny_pivot_retries_with_stable_ratio(self):
        self._assert_fast_reproduction("bayes-arena-16x8x8-tiny-pivot.json", -0.150896305394414)

    def _assert_fast_reproduction(self, filename, value):
        fixture = Path(__file__).with_name("fixtures") / filename
        saved = json.loads(fixture.read_text())
        tables, weights = saved["tables"], saved["weights"]
        timings = []
        previous = None
        with patch.object(matrix, "_bland", side_effect=AssertionError("unexpected exact rescue")):
            for _ in range(5):
                start = time.perf_counter()
                sol = matrix.solve_bayes(tables, weights)
                timings.append(time.perf_counter() - start)
                self.assertFalse(sol.exact)
                self.assertLessEqual(matrix.bayes_certify(tables, weights, sol.x, sol.ys), 1e-9)
                self.assertAlmostEqual(sol.value, value, delta=1e-9)
                if previous is not None:
                    np.testing.assert_array_equal(sol.x, previous.x)
                    np.testing.assert_array_equal(sol.ys, previous.ys)
                previous = sol
        # Median tolerates an isolated scheduler interruption on shared CI.
        self.assertLess(float(np.median(timings)), 0.050)

    def test_exact_rescue_remains_certified(self):
        a = np.array([[[1., 0.], [0., 1.]], [[0., 1.], [1., 0.]]])
        with patch.object(matrix, "_bland_float", side_effect=SearchError("float failed")):
            sol = matrix.solve_bayes(a, [1., 1.])
        self.assertTrue(sol.exact)
        self.assertLessEqual(matrix.bayes_certify(a, [1., 1.], sol.x, sol.ys), 1e-9)
        self.assertAlmostEqual(sol.value, 0.5, delta=1e-12)

    def test_many_worlds_with_near_duplicate_rows_and_columns(self):
        rng = np.random.default_rng(20261004)
        for _ in range(30):
            a = rng.uniform(-1, 1, (16, 8, 8)).astype(np.float32).astype(np.float64)
            a[:, 1] = a[:, 0]
            a[:, 2] = a[:, 0] + rng.choice([-1, 1], (16, 8)) * 2**-24
            a[:, :, 1] = a[:, :, 0]
            p = rng.random(16) + 0.1
            sol = matrix.solve_bayes(a, p)
            self.assertLessEqual(matrix.bayes_certify(a, p, sol.x, sol.ys), 1e-9)

    def test_one_world_is_the_matrix_game(self):
        rng = np.random.default_rng(23)
        for k, m in ((1, 1), (2, 3), (8, 8), (16, 16)):
            a = rng.random((k, m))
            got, want = matrix.solve_bayes(a[None], [1.0]), matrix.solve(a)
            self.assertAlmostEqual(got.value, want.value, delta=1e-9)
            np.testing.assert_allclose(got.x, want.x, atol=1e-9)

    def test_certificate_on_random_tables(self):
        rng = np.random.default_rng(230)
        for w, k, m in ((2, 2, 2), (4, 8, 8), (16, 8, 8), (16, 16, 16), (3, 5, 1), (5, 1, 4)):
            a = rng.random((w, k, m)).astype(np.float32).astype(np.float64)
            p = rng.random(w) + 0.1
            sol = matrix.solve_bayes(a, p)
            self.assertLessEqual(matrix.bayes_certify(a, p, sol.x, sol.ys), 1e-9)

    def test_degenerate_and_duplicate_rows(self):
        a = np.array([[[0.2, 0.8], [0.2, 0.8], [0.5, 0.5]], [[0.9, 0.1], [0.9, 0.1], [0.5, 0.5]]])
        a[1, 1, 0] += 1e-7  # a near-duplicate row
        sol = matrix.solve_bayes(a, [1.0, 1.0])
        matrix.bayes_certify(a, [1.0, 1.0], sol.x, sol.ys)
        const = matrix.solve_bayes(np.full((3, 2, 2), 0.25), np.ones(3))
        self.assertEqual(const.value, 0.25)
        self.assertEqual(const.x.tolist(), [1.0, 0.0])

    def test_the_foe_knowing_its_world_changes_our_strategy(self):
        # Row 0 scores 1 in each world, but only in the column the foe of that world avoids; row 1 is safe at 0.4.
        # The averaged table shows row 0 at 0.5 against everything; a foe that knows its world holds it to 0.
        a = np.array([[[1.0, 0.0], [0.4, 0.4]],
                      [[0.0, 1.0], [0.4, 0.4]]])
        sol = matrix.solve_bayes(a, [1.0, 1.0])
        np.testing.assert_allclose(sol.x, [0.0, 1.0], atol=1e-9)
        self.assertAlmostEqual(sol.value, 0.4, delta=1e-12)
        averaged = matrix.solve(a.mean(axis=0))
        np.testing.assert_allclose(averaged.x, [1.0, 0.0], atol=1e-9)
        self.assertAlmostEqual(averaged.value, 0.5, delta=1e-12)

    def test_expected_values_and_mix(self):
        a = np.array([[[1.0, 0.0], [0.0, 1.0]], [[0.0, 1.0], [1.0, 0.0]]])
        ev = matrix.bayes_expected_values(a, [3.0, 1.0], [[1.0, 0.0], [0.0, 2.0]])
        np.testing.assert_allclose(ev, [0.75 * 1.0 + 0.25 * 1.0, 0.0])
        np.testing.assert_allclose(matrix.mix([0.25, 0.75], 0), [0.625, 0.375])
        np.testing.assert_allclose(matrix.mix([0.25, 0.75], 1, lam=1.0), [0.25, 0.75])
        with self.assertRaises(SearchError):
            matrix.mix([0.5, 0.5], 2)
        with self.assertRaises(SearchError):
            matrix.solve_bayes(np.zeros((2, 2, 2)), [1.0, 0.0])


class BoundedSolver(unittest.TestCase):
    """The P1 teacher's deterministic work budget (P1 plan C2 steps 4 and 5)."""

    _AMPLE = {"float_pivots": 10**9, "exact_pivots": 10**9, "exact_ops": 10**12, "bits": 10**9}
    _GOLDEN = "63f2a5e83803e3f8e69d1d4951811a9a05fb176a6bc9c4788bb872f47a29325a"  # pinned on main 1cd5ba8b
    _RATIONAL = np.array([[[0.1, 0.7, 0.3], [0.6, 0.2, 0.9], [0.4, 0.8, 0.5]],
                          [[0.9, 0.1, 0.6], [0.3, 0.8, 0.2], [0.5, 0.4, 0.7]]])

    def _ledger(self, **caps):
        return matrix.WorkLedger(matrix.WorkBudget(**{**self._AMPLE, **caps}))

    @staticmethod
    def _counts(ledger):
        c = ledger.consumed
        return (c.float_pivots, c.exact_pivots, c.exact_ops, c.max_bits)

    def test_bayes_budget_cumulative_and_default_identity(self):
        b = matrix.WorkBudget()
        self.assertEqual((b.float_pivots, b.exact_pivots, b.exact_ops, b.bits), (4096, 32, 250000, 4096))
        self.assertEqual([s.value for s in matrix.WorkStatus], ["ok", "float_pivots", "exact_pivots", "exact_ops", "bits"])
        fresh = matrix.WorkLedger()
        self.assertEqual(fresh.limits, b)
        self.assertEqual(self._counts(fresh), (0, 0, 0, 0))
        self.assertIs(fresh.status, matrix.WorkStatus.OK)
        # budget=None is byte-identical to the solver before budgets existed.
        self.assertEqual(_budget_digest(lambda t, w: matrix.solve_bayes(t, w, budget=None),
                                        lambda a: matrix.solve(a, budget=None)), self._GOLDEN)
        # An ample ledger changes no byte either, and one ledger accumulates over every call
        # (single-world solve included); it never resets per call.
        ledger = self._ledger()
        self.assertEqual(_budget_digest(lambda t, w: matrix.solve_bayes(t, w, budget=ledger),
                                        lambda a: matrix.solve(a, budget=ledger)), self._GOLDEN)
        parts = []

        def bayes_part(t, w):
            parts.append(self._ledger())
            return matrix.solve_bayes(t, w, budget=parts[-1])

        def matrix_part(a):
            parts.append(self._ledger())
            return matrix.solve(a, budget=parts[-1])

        self.assertEqual(_budget_digest(bayes_part, matrix_part), self._GOLDEN)
        counts = [self._counts(p) for p in parts]
        self.assertEqual(self._counts(ledger), (sum(c[0] for c in counts), sum(c[1] for c in counts),
                                                sum(c[2] for c in counts), max(c[3] for c in counts)))
        self.assertTrue(all(v > 0 for v in self._counts(ledger)))
        # Float decisions charge only float pivots, the 1 + W start pivots included.
        self.assertEqual(counts[0][1:], (0, 0, 0))
        self.assertGreaterEqual(counts[0][0], 17)
        self.assertIs(ledger.status, matrix.WorkStatus.OK)

    def test_bayes_budget_cumulative_and_default_identity_exhaustion_is_never_retried(self):
        a, w = self._RATIONAL, [1.0, 2.0]
        ledger = self._ledger(float_pivots=2)
        calls = []
        real = matrix._bland_float

        def spy(*args, **kwargs):
            calls.append(kwargs.get("stable", False))
            return real(*args, **kwargs)

        with patch.object(matrix, "_bland_float", side_effect=spy), \
                patch.object(matrix, "_bland", side_effect=AssertionError("unexpected exact rescue")), \
                self.assertRaises(matrix.WorkBudgetExceeded) as caught:
            matrix.solve_bayes(a, w, budget=ledger)
        self.assertEqual(calls, [False])  # neither the stable retry nor the rescue ran
        self.assertIsInstance(caught.exception, SearchError)
        self.assertIs(caught.exception.status, matrix.WorkStatus.FLOAT_PIVOTS)
        self.assertEqual(caught.exception.consumed, ledger.consumed)
        self.assertEqual(self._counts(ledger), (3, 0, 0, 0))  # charged before the third pivot ran
        self.assertIs(ledger.status, matrix.WorkStatus.FLOAT_PIVOTS)
        # An exhausted ledger refuses every later call, even a constant table, and stays unchanged.
        with self.assertRaises(matrix.WorkBudgetExceeded):
            matrix.solve_bayes(np.full((2, 2, 2), 0.5), [1.0, 1.0], budget=ledger)
        with self.assertRaises(matrix.WorkBudgetExceeded):
            matrix.solve(np.ones((2, 2)), budget=ledger)
        self.assertEqual(self._counts(ledger), (3, 0, 0, 0))
        # Float pivots of the single-world simplex and its basis solves are charged as well.
        with patch.object(matrix, "_simplex_exact", side_effect=AssertionError("unexpected exact rescue")), \
                self.assertRaises(matrix.WorkBudgetExceeded) as caught:
            matrix.solve(a[0], budget=self._ledger(float_pivots=1))
        self.assertIs(caught.exception.status, matrix.WorkStatus.FLOAT_PIVOTS)
        # By hand for [[1, 0], [0, 1]]: two simplex pivots, then two 2 x 2 basis solves of two pivots each.
        ledger = self._ledger()
        matrix.solve(np.eye(2), budget=ledger)
        self.assertEqual(self._counts(ledger), (6, 0, 0, 0))
        # Exact rescues of the same game, counted by hand. solve: 22 to build the tableau, two
        # pivots of 34 (7 ratio-test operations, 5 to divide the pivot row, 2 comparisons, 20 to
        # update two rows), 4 final comparisons and 13 to read the strategies; widest value 3/2.
        ledger = self._ledger()
        with patch.object(matrix, "_solve_float", side_effect=SearchError("float failed")):
            matrix.solve(np.eye(2), budget=ledger)
        self.assertEqual(self._counts(ledger), (0, 2, 107, 2))
        # solve_bayes, one world: 20 to build, 3 slack ones, pivots of 47, 59 and 57 (each with
        # 14 for the objective row), 6 final comparisons, 3 dual negations, 4 conversions.
        ledger = self._ledger()
        with patch.object(matrix, "_bland_float", side_effect=SearchError("float failed")):
            matrix.solve_bayes(np.eye(2)[None], [1.0], budget=ledger)
        self.assertEqual(self._counts(ledger), (0, 3, 199, 2))
        # Every exact cap stops the rescue with its own status.
        for caps, status in (({"exact_pivots": 1}, matrix.WorkStatus.EXACT_PIVOTS),
                             ({"exact_ops": 10}, matrix.WorkStatus.EXACT_OPS),
                             ({"bits": 8}, matrix.WorkStatus.BITS)):
            for name, run in (("bayes", lambda led: matrix.solve_bayes(a, w, budget=led)),
                              ("matrix", lambda led: matrix.solve(a[0], budget=led))):
                ledger = self._ledger(**caps)
                with self.subTest(name=name, status=status), \
                        patch.object(matrix, "_bland_float", side_effect=SearchError("float failed")), \
                        patch.object(matrix, "_solve_float", side_effect=SearchError("float failed")), \
                        self.assertRaises(matrix.WorkBudgetExceeded) as caught:
                    run(ledger)
                self.assertIs(caught.exception.status, status)
                self.assertIs(ledger.status, status)
        # Unexpected errors abort instead of falling back.
        with patch.object(matrix, "_bland_float", side_effect=RuntimeError("bug")), \
                patch.object(matrix, "_bland", side_effect=AssertionError("unexpected exact rescue")), \
                self.assertRaises(RuntimeError):
            matrix.solve_bayes(a, w, budget=self._ledger())
        for caps in ({"float_pivots": -1}, {"bits": 1.5}, {"exact_ops": True}):
            with self.subTest(caps=caps), self.assertRaises(SearchError):
                matrix.WorkBudget(**caps)
        with self.assertRaises(SearchError):
            matrix.solve_bayes(a, w, budget=matrix.WorkBudget())
        with self.assertRaises(SearchError):
            matrix.solve(a[0], budget={"float_pivots": 1})

    def test_primary_and_audit_budgets_with_clock_injection(self):
        rng = np.random.default_rng(20261011)
        tables = rng.random((16, 8, 8)).astype(np.float32).astype(np.float64)
        weights = rng.random(16) + 0.1
        audit_tables = [rng.random((16, 8, 8)).astype(np.float32).astype(np.float64) for _ in range(9)]
        audit_weights = rng.random(16) + 0.1

        def fingerprint(sol, ledger):
            return (sol.x.tobytes(), tuple(y.tobytes() for y in sol.ys), sol.value, sol.exact,
                    self._counts(ledger), ledger.status)

        def primary_only():
            ledger = matrix.WorkLedger()
            return fingerprint(matrix.solve_bayes(tables, weights, budget=ledger), ledger)

        want = primary_only()
        # One primary and K + 1 = 9 audit ledgers with identical caps.
        primary = matrix.WorkLedger()
        audits = [matrix.WorkLedger() for _ in range(9)]
        self.assertTrue(all(led.limits == primary.limits for led in audits))
        statuses = []
        for i, (ledger, audit) in enumerate(zip(audits, audit_tables)):
            if i == 4:  # this audit lands on the rational rescue and exhausts only its own ledger
                with patch.object(matrix, "_bland_float", side_effect=SearchError("float failed")), \
                        self.assertRaises(matrix.WorkBudgetExceeded):
                    matrix.solve_bayes(audit, audit_weights, budget=ledger)
            else:
                matrix.solve_bayes(audit, audit_weights, budget=ledger)
            statuses.append(ledger.status)
            if i == 2:
                sol = matrix.solve_bayes(tables, weights, budget=primary)
        self.assertEqual(fingerprint(sol, primary), want)
        self.assertEqual(statuses.count(matrix.WorkStatus.OK), 8)
        self.assertIn(statuses[4], (matrix.WorkStatus.EXACT_PIVOTS, matrix.WorkStatus.EXACT_OPS, matrix.WorkStatus.BITS))
        # Arbitrary clock jumps change no status, result or counter byte: the budget counts work, not time.
        jumps = itertools.count()

        def clock(*_):
            return float(next(jumps) ** 3 * 977)

        with patch("time.perf_counter", side_effect=clock), patch("time.monotonic", side_effect=clock), \
                patch("time.time", side_effect=clock), patch("time.process_time", side_effect=clock):
            self.assertEqual(primary_only(), want)


def _sides(teams):
    """SIDE_SETUP-like records: teams is a list of member lists (species, nature, item, spread)."""
    dt = np.dtype([("member_count", np.uint32), ("members", np.dtype([("species_id", np.uint32), ("nature", np.uint32),
                   ("item", np.uint32), ("stat_points", np.uint32, (6,))]), (6,))])
    out = np.zeros(len(teams), dtype=dt)
    for t, members in enumerate(teams):
        out[t]["member_count"] = len(members)
        for k, (sp, na, it, spread) in enumerate(members):
            out[t]["members"][k] = (sp, na, it, spread)
    return out


class BeliefTable(unittest.TestCase):
    """The spread table and the world words (decision 0023, spec section 5)."""

    def setUp(self):
        a = [32, 0, 2, 0, 0, 32]
        b = [32, 32, 0, 0, 0, 2]
        c = [0, 32, 2, 0, 0, 32]
        teams = [[(1, 3, 7, a), (2, 4, 0, c)], [(1, 3, 7, a), (1, 3, 9, b)], [(1, 3, 7, b), (5, 3, 0, [0] * 6)],
                 [(1, 3, 7, a), (1, 2, 7, c)], [(1, 3, 7, c)]]
        self.table = belief.SpreadTable.from_sides(_sides(teams))

    def test_skips_sets_without_spreads_and_hashes(self):
        self.assertEqual(self.table.spreads.shape, (8, 6))
        self.assertNotIn(5, self.table.species.tolist())
        again = belief.SpreadTable(self.table.team, self.table.species, self.table.nature, self.table.item,
                                   self.table.spreads)
        self.assertEqual(again.sha256(), self.table.sha256())
        other = belief.SpreadTable(self.table.team, self.table.species, self.table.nature, self.table.item,
                                   self.table.spreads, min_sets=4)
        self.assertNotEqual(other.sha256(), self.table.sha256())

    def test_backoff_levels(self):
        self.assertEqual(self.table.candidates(1, 3, 7)[0], 1)    # five sets of (1, 3, 7)
        self.assertEqual(self.table.candidates(1, 3, 9)[0], 2)    # one set of (1, 3, 9): the (species, nature) level
        self.assertEqual(self.table.candidates(1, 6, 7)[0], 3)    # species only
        self.assertEqual(self.table.candidates(8, 3, 0)[0], 4)    # nature only
        self.assertEqual(self.table.candidates(8, 9, 0)[0], 5)    # everything
        level, rows = self.table.candidates(1, 3, 7, exclude_team=0)
        self.assertEqual(level, 2)  # four sets left of (1, 3, 7): below min_sets
        self.assertNotIn(0, self.table.team[rows].tolist())

    def test_whole_spreads_weighted_by_count(self):
        counts = {}
        level, rows = self.table.candidates(1, 3, 7)
        for i in range(rows.size):
            word = belief.splitmix64(np.uint64(i))  # any words: the index is floor(word * n / 2^64)
            spread, _ = self.table.draw(int(word), 1, 3, 7)
            counts[tuple(spread.tolist())] = counts.get(tuple(spread.tolist()), 0) + 1
        for spread in counts:
            self.assertLessEqual(sum(spread), 66)
        idx = [belief.pick((j << 64) // rows.size + 1, rows.size) for j in range(rows.size)]
        self.assertEqual(idx, list(range(rows.size)))  # every set once over evenly spaced words: a spread seen c times weighs c

    def test_world_words_are_pure(self):
        one = belief.world_words(7, 11, 3, [1, 2, 3])
        self.assertEqual(belief.world_words(7, 11, 3, [3, 2, 1]).tolist(), one[::-1].tolist())
        self.assertNotEqual(belief.world_words(7, 11, 4, [1]).tolist(), one[:1].tolist())
        g = splitmix64(splitmix64(np.uint64(7) + np.uint64(belief.WORLD_TAG)) + np.uint64(11))
        self.assertEqual(int(one[0]), int(splitmix64(splitmix64(g + np.uint64(3)) + np.uint64(1))))
        self.assertEqual(belief.pick(0, 5), 0)
        self.assertEqual(belief.pick((1 << 64) - 1, 5), 4)

    def test_sample(self):
        b = belief.Belief(self.table)
        members = [(1, 3, 7), (2, 4, 0)]
        one = b.sample(members, 4, seed=5, key=9)
        two = b.sample(members, 4, seed=5, key=9)
        for name in one:
            np.testing.assert_array_equal(one[name], two[name])
        self.assertEqual(one["weights"].tolist(), [0.25] * 4)
        self.assertEqual(one["stat_points"].shape, (4, 6, 6))
        self.assertFalse(one["stat_points"][:, 2:].any())
        words = belief.world_words(5, 9, 2, np.arange(64))
        self.assertEqual(int(one["hp"][2, 0]), int(words[belief.WORDS["hp"]]))
        attempts = np.zeros((4, 6), dtype=np.int64)
        attempts[1, 0] = 1
        redrawn = b.sample(members, 4, seed=5, key=9, attempts=attempts)
        want, _ = self.table.draw(int(belief.world_words(5, 9, 1, [belief.WORDS["respread"]])[0]), 1, 3, 7, redraw=1)
        self.assertEqual(redrawn["stat_points"][1, 0].tolist(), want.tolist())
        np.testing.assert_array_equal(redrawn["stat_points"][0], one["stat_points"][0])

    def test_all_256_attempts_back_off_without_shifting_other_words(self):
        b = belief.Belief(self.table)
        first = b.sample([(1, 3, 7)], 1, 5, 9)
        for attempt in (1, 8, 64, 255):
            counts = np.zeros((1, 6), np.int64)
            counts[0, 0] = attempt
            sampled = b.sample([(1, 3, 7)], 1, 5, 9, attempts=counts)
            self.assertEqual(int(sampled["levels"][0, 0]), min(5, 1 + attempt))
            for name in ("hp", "sleep", "confusion", "charge_target", "bench", "queue"):
                np.testing.assert_array_equal(sampled[name], first[name])
        counts[0, 0] = 256
        with self.assertRaisesRegex(ValueError, "255"):
            b.sample([(1, 3, 7)], 1, 5, 9, attempts=counts)

    def test_draw_index(self):
        self.assertEqual(belief.draw_index([0.0, 1.0, 1.0], 0), 1)
        self.assertEqual(belief.draw_index([0.0, 1.0, 1.0], (1 << 64) - 1), 2)
        with self.assertRaises(ValueError):
            belief.draw_index([0.0, 0.0], 1)


if __name__ == "__main__":
    unittest.main()
