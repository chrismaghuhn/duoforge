"""duoforge.python.search_numpy: the NumPy parts of the M12 search (decision 0022).

The matrix game (an exact linear program with its certificate), the
expected-value rule, the tie rules and the play draw (spec sections 5.5
and 5.6), and the decision keys and play draws (decision 0022 section 2).
The JAX parts are in test_search.py.
"""
import itertools
import unittest

import numpy as np

from duoforge_learn.pairing import draw as pairing_draw
from duoforge_learn.pairing import splitmix64
from duoforge_search import SearchError, matrix, seeds

_MASK = (1 << 64) - 1


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
    def test_certificate_on_random_tables(self):
        rng = np.random.default_rng(0x2026100300000600)
        for a in _random_tables(rng, 2000):
            x, y, value = matrix.solve(a)
            self.assertEqual(x.shape, (a.shape[0],))
            self.assertEqual(y.shape, (a.shape[1],))
            for v in (x, y):
                self.assertTrue((v >= 0).all())
                self.assertAlmostEqual(float(v.sum()), 1.0, delta=1e-12)
            self.assertLessEqual(matrix.exploitability(a, x, y), matrix.CERTIFICATE)
            self.assertLessEqual(float(np.min(x @ a)), value + 1e-9)
            self.assertGreaterEqual(float(np.max(a @ y)), value - 1e-9)

    def test_agrees_with_support_enumeration(self):
        rng = np.random.default_rng(0x2026100300000601)
        for _ in range(300):
            a = rng.uniform(-1.0, 1.0, (int(rng.integers(1, 5)), int(rng.integers(1, 5))))
            _, _, value = matrix.solve(a)
            self.assertAlmostEqual(value, _support_value(a), delta=1e-12)

    def test_saddle_points_are_pure(self):
        rng = np.random.default_rng(0x2026100300000602)
        for _ in range(200):
            k, m = int(rng.integers(1, 9)), int(rng.integers(1, 9))
            i, j = int(rng.integers(0, k)), int(rng.integers(0, m))
            a = rng.uniform(-1.0, 1.0, (k, m))
            a[i, :] = rng.uniform(0.1, 1.0, m)  # the row's other entries are better for the row player
            a[:, j] = rng.uniform(-1.0, -0.1, k)  # the column's other entries are worse for the row player
            a[i, j] = 0.0
            x, y, value = matrix.solve(a)
            self.assertAlmostEqual(float(x[i]), 1.0, delta=1e-12)
            self.assertAlmostEqual(float(y[j]), 1.0, delta=1e-12)
            self.assertAlmostEqual(value, 0.0, delta=1e-12)

    def test_known_games(self):
        x, y, value = matrix.solve([[1.0, -1.0], [-1.0, 1.0]])  # matching pennies
        np.testing.assert_allclose(x, [0.5, 0.5], atol=1e-12)
        np.testing.assert_allclose(y, [0.5, 0.5], atol=1e-12)
        self.assertAlmostEqual(value, 0.0, delta=1e-12)
        x, y, value = matrix.solve([[0.0, -1.0, 1.0], [1.0, 0.0, -1.0], [-1.0, 1.0, 0.0]])  # rock, paper, scissors
        np.testing.assert_allclose(x, [1 / 3] * 3, atol=1e-12)
        np.testing.assert_allclose(y, [1 / 3] * 3, atol=1e-12)
        self.assertAlmostEqual(value, 0.0, delta=1e-12)
        x, _, value = matrix.solve([[3.0, -1.0], [-1.0, 1.0], [-2.0, -2.0]])  # the last row is strictly dominated
        self.assertEqual(float(x[2]), 0.0)
        self.assertAlmostEqual(value, 1.0 / 3.0, delta=1e-12)
        x, y, value = matrix.solve([[0.25]])
        self.assertEqual((float(x[0]), float(y[0]), value), (1.0, 1.0, 0.25))

    def test_missed_certificate_raises(self):
        a = np.array([[1.0, -1.0], [-1.0, 1.0]])
        x, y, _ = matrix.solve(a)
        with self.assertRaisesRegex(SearchError, "certificate is missed: exploitability"):
            matrix.certify(a, np.array([0.9, 0.1]), y)
        with self.assertRaisesRegex(SearchError, "not a mixed strategy"):
            matrix.certify(a, np.array([0.7, 0.7]), y)

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

    def test_bad_draws_raise(self):
        for x, u in (([1.0], 1.0), ([1.0], -0.1), ([1e-12], 0.5), ([np.nan], 0.5)):
            with self.assertRaises(SearchError):
                matrix.draw(x, [0], u)


class Seeds(unittest.TestCase):
    def _key(self, arena_seed, env, episode, epoch, seat):
        """A scalar transcription of decision 0022 section 2."""
        sm = lambda v: int(splitmix64(np.uint64(v & _MASK)))
        base = int(pairing_draw(arena_seed, seeds.KEY_TAG, np.array([env]), np.array([episode]))[0])
        return sm(sm((base + epoch) & _MASK) + seat)

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
        head = sm(0x2026100300000221 + seeds.PLAY_TAG)
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


if __name__ == "__main__":
    unittest.main()
