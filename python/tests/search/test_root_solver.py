"""The regret-matching root solver (D1 of the depth search, #481): matrix.solve_bayes_rm against the exact Bayes LP.

NumPy only. Spec docs/superpowers/specs/2026-10-13-depth-search-design.md sections 3.1 and 8: on random and recorded
tables the RM value lies within epsilon of the range of the LP value and its gap is at most epsilon; two runs are
byte-equal; a constant table plays the first row; the solver refuses by name at its iteration bound.
"""
import json
import unittest
from pathlib import Path

import numpy as np

from duoforge_search import SearchError, matrix

FIXTURES = Path(__file__).resolve().parent.parent / "support" / "fixtures"
# Shapes (worlds, own pairs, foe pairs): step 0's 16 x 8 x 8, the budget arms' b-k16 / b-m16 / b-km16 / b-s64, whose
# LPs the size limit refuses (b-km16 and b-s64 stopped the exact rescue, #440), and the small and one-sided edges.
SHAPES = ((2, 2, 2), (16, 8, 8), (16, 16, 8), (16, 8, 16), (16, 16, 16), (64, 8, 8), (3, 5, 1), (5, 1, 4))


def _random_game(rng, shape):
    tables = rng.uniform(-1, 1, shape).astype(np.float32).astype(np.float64)  # float32 values, as the leaves give
    return tables, rng.random(shape[0]) + 0.1, rng.random(shape[1]) + 0.01, rng.random(shape[::2]) + 0.01


class SolveBayesRM(unittest.TestCase):
    def assert_within_epsilon_of_the_lp(self, tables, weights, prior, foe_priors, epsilon=matrix.RM_EPSILON):
        rm = matrix.solve_bayes_rm(tables, weights, prior, foe_priors, epsilon=epsilon)
        lp = matrix.solve_bayes(tables, weights)
        a = np.asarray(tables, dtype=np.float64)
        span = float(a.max() - a.min())
        self.assertLessEqual(rm.gap, epsilon)
        self.assertLessEqual(rm.iterations, matrix.RM_MAX_ITERATIONS)
        # The reported gap is the exact exploitability of the played averages on the scaled tables (to rounding: the
        # solver passes the weights normalized once already).
        scaled = (a - a.min()) / span
        self.assertAlmostEqual(rm.gap, matrix.bayes_exploitability(scaled, weights, rm.solution.x, rm.solution.ys),
                               delta=1e-12)
        # The value is the averages' guaranteed payoff: at most the game's value, and below it by at most the gap.
        self.assertLessEqual(rm.solution.value, lp.value + 1e-9 * span)
        self.assertLessEqual(lp.value - rm.solution.value, epsilon * span + 1e-9 * span)
        self.assertFalse(rm.solution.exact)
        for strategy in [rm.solution.x, *rm.solution.ys]:
            self.assertTrue((strategy >= 0).all())
            self.assertAlmostEqual(float(strategy.sum()), 1.0, delta=1e-12)
        return rm, lp

    def test_random_tables_are_solved_within_epsilon(self):
        rng = np.random.default_rng(481)
        for shape in SHAPES:
            for _ in range(3):
                with self.subTest(shape=shape):
                    self.assert_within_epsilon_of_the_lp(*_random_game(rng, shape))

    def test_near_duplicate_rows_and_columns(self):
        # The tables that made the float LP ill-conditioned (test_search_numpy's BayesRule) are plain for regret
        # matching.
        rng = np.random.default_rng(20261004)
        for _ in range(5):
            tables, weights, prior, foe_priors = _random_game(rng, (16, 8, 8))
            tables[:, 1] = tables[:, 0]
            tables[:, 2] = tables[:, 0] + rng.choice([-1, 1], (16, 8)) * 2**-24
            tables[:, :, 1] = tables[:, :, 0]
            self.assert_within_epsilon_of_the_lp(tables, weights, prior, foe_priors)

    def test_the_recorded_arena_tables(self):
        # Numeric payoffs of two stopped 16-world arena decisions (the float LP's fixtures).
        rng = np.random.default_rng(7)
        for name in ("bayes-arena-16x8x8.json", "bayes-arena-16x8x8-tiny-pivot.json"):
            saved = json.loads((FIXTURES / name).read_text())
            tables = np.asarray(saved["tables"], dtype=np.float64)
            with self.subTest(fixture=name):
                self.assert_within_epsilon_of_the_lp(tables, saved["weights"], rng.random(tables.shape[1]) + 0.01,
                                                     rng.random(tables.shape[::2]) + 0.01)

    def test_a_tighter_target_lands_closer(self):
        rng = np.random.default_rng(12)
        game = _random_game(rng, (16, 8, 8))
        loose, lp = self.assert_within_epsilon_of_the_lp(*game, epsilon=1e-2)
        tight, _ = self.assert_within_epsilon_of_the_lp(*game, epsilon=1e-4)
        self.assertLessEqual(tight.gap, 1e-4)
        self.assertGreaterEqual(tight.iterations, loose.iterations)

    def test_matching_pennies_and_the_foe_knowing_its_world(self):
        pennies = np.array([[[1.0, 0.0], [0.0, 1.0]]])
        rm, _ = self.assert_within_epsilon_of_the_lp(pennies, [1.0], [0.9, 0.1], [[0.2, 0.8]])
        np.testing.assert_allclose(rm.solution.x, [0.5, 0.5], atol=2e-3)
        # Row 0 scores 1 only in the column each world's foe avoids; row 1 is safe at 0.4 (test_search_numpy).
        a = np.array([[[1.0, 0.0], [0.4, 0.4]], [[0.0, 1.0], [0.4, 0.4]]])
        rm, _ = self.assert_within_epsilon_of_the_lp(a, [1.0, 1.0], [0.9, 0.1], [[0.5, 0.5], [0.5, 0.5]])
        self.assertGreater(rm.solution.x[1], 0.99)

    def test_two_runs_are_byte_equal(self):
        rng = np.random.default_rng(99)
        game = _random_game(rng, (16, 16, 16))
        first, second = matrix.solve_bayes_rm(*game), matrix.solve_bayes_rm(*game)
        self.assertEqual(first.solution.x.tobytes(), second.solution.x.tobytes())
        self.assertEqual([y.tobytes() for y in first.solution.ys], [y.tobytes() for y in second.solution.ys])
        self.assertEqual((first.solution.value, first.gap, first.iterations),
                         (second.solution.value, second.gap, second.iterations))

    def test_a_constant_table_plays_the_first_row(self):
        rm = matrix.solve_bayes_rm(np.full((3, 4, 2), 0.25), np.ones(3), [0.1, 0.2, 0.3, 0.4], np.ones((3, 2)))
        self.assertEqual(rm.solution.x.tolist(), [1.0, 0.0, 0.0, 0.0])
        self.assertEqual([y.tolist() for y in rm.solution.ys], [[1.0, 0.0]] * 3)
        self.assertEqual((rm.solution.value, rm.gap, rm.iterations), (0.25, 0.0, 0))

    def test_the_prior_breaks_ties(self):
        # Every own row is the same: our regrets stay 0 (no rounding-sized regret, review of D1: a non-dyadic prior
        # makes x . u differ from the rows by an ulp), so we play the prior (renormalized) throughout.
        rng = np.random.default_rng(5)
        row = rng.random((4, 1, 3))
        for prior in ([2.0, 1.0, 1.0], [0.7, 0.2, 0.1], [0.1, 0.3, 0.6]):
            with self.subTest(prior=prior):
                rm = matrix.solve_bayes_rm(np.repeat(row, 3, axis=1), np.ones(4), prior, np.ones((4, 3)))
                np.testing.assert_allclose(rm.solution.x, np.asarray(prior) / sum(prior), rtol=0, atol=1e-15)
        # The same for a world's foe whose every column pays the same: it plays its prior.
        a = np.array([[[0.2, 0.2], [0.6, 0.6]], [[1.0, 0.0], [0.0, 1.0]]])
        rm = matrix.solve_bayes_rm(a, [1.0, 1.0], [0.5, 0.5], [[0.7, 0.3], [0.5, 0.5]])
        np.testing.assert_allclose(rm.solution.ys[0], [0.7, 0.3], rtol=0, atol=1e-15)

    def test_the_iteration_bound_refuses_by_name(self):
        rng = np.random.default_rng(3)
        game = _random_game(rng, (16, 8, 8))
        with self.assertRaises(matrix.RMUnconverged) as caught:
            matrix.solve_bayes_rm(*game, iterations=3, check_every=10)
        self.assertIsInstance(caught.exception, SearchError)
        self.assertEqual(caught.exception.iterations, 3)
        self.assertGreater(caught.exception.gap, matrix.RM_EPSILON)
        self.assertTrue(str(caught.exception).startswith("solver_unconverged"))

    def test_malformed_inputs_are_refused(self):
        tables, weights = np.zeros((2, 3, 2)) + np.arange(2)[None, None, :], np.ones(2)
        prior, foe = np.ones(3), np.ones((2, 2))
        bad = [((tables, weights, np.ones(2), foe), {}), ((tables, weights, np.zeros(3), foe), {}),
               ((tables, weights, [1.0, -1.0, 1.0], foe), {}), ((tables, weights, prior, np.ones((2, 3))), {}),
               ((tables, weights, prior, [[1.0, 1.0], [0.0, 0.0]]), {}), ((tables, [1.0, 0.0], prior, foe), {}),
               ((tables, weights, prior, foe), {"iterations": 0}), ((tables, weights, prior, foe), {"iterations": 2.0}),
               ((tables, weights, prior, foe), {"check_every": 0}), ((tables, weights, prior, foe), {"epsilon": 0.0}),
               ((tables, weights, prior, foe), {"epsilon": 1.0})]
        for args, kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(SearchError):
                matrix.solve_bayes_rm(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
