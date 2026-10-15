"""The exact zero-sum equilibrium (issue #458, the mixed team preview): known games, random games against the exact
equilibrium check, and the double-oracle gap."""
import random
import unittest
from fractions import Fraction as F

from duoforge_search import zero_sum


class SolveTest(unittest.TestCase):
    def test_matching_pennies(self):
        x, y, v = zero_sum.solve([[1, 0], [0, 1]])
        self.assertEqual((x, y, v), ([F(1, 2), F(1, 2)], [F(1, 2), F(1, 2)], F(1, 2)))

    def test_rock_paper_scissors(self):
        x, y, v = zero_sum.solve([[0, -1, 1], [1, 0, -1], [-1, 1, 0]])
        self.assertEqual(x, [F(1, 3)] * 3)
        self.assertEqual(y, [F(1, 3)] * 3)
        self.assertEqual(v, 0)

    def test_a_saddle_point_is_pure(self):
        x, y, v = zero_sum.solve([[3, 1], [4, 2]])
        self.assertEqual((x, y, v), ([0, 1], [0, 1], 2))

    def test_one_cell_and_a_constant_matrix(self):
        self.assertEqual(zero_sum.solve([[F(3, 7)]]), ([1], [1], F(3, 7)))
        x, y, v = zero_sum.solve([[5, 5, 5], [5, 5, 5]])
        self.assertEqual(v, 5)
        self.assertEqual((sum(x), sum(y)), (1, 1))

    def test_a_rectangular_game_with_scores(self):
        a = [[F(37, 128), F(64, 128), F(51, 128)], [F(70, 128), F(40, 128), F(45, 128)]]
        x, y, v = zero_sum.solve(a)
        self.assertEqual(x, [F(25, 39), F(14, 39)])
        self.assertEqual(y, [F(2, 13), 0, F(11, 13)])
        self.assertEqual(v, F(635, 1664))

    def test_the_result_is_exact_rationals(self):
        x, y, v = zero_sum.solve([[0.5, 0.25], [0.125, 1]])
        self.assertTrue(all(isinstance(p, F) for p in x + y + [v]))

    def test_random_games_meet_the_exact_check(self):
        rng = random.Random(458)
        for _ in range(300):
            m, n = rng.randint(1, 7), rng.randint(1, 8)
            levels = rng.choice((2, 3, 257))  # few levels: many ties, the degenerate pivots Bland's rule must end
            a = [[F(rng.randrange(levels), levels - 1) for _ in range(n)] for _ in range(m)]
            x, y, v = zero_sum.solve(a)  # solve checks the equilibrium exactly
            self.assertEqual(zero_sum.gap(a, x, y)["gap"], 0)
            self.assertTrue(min(min(r) for r in a) <= v <= max(max(r) for r in a))

    def test_a_ragged_or_empty_matrix_is_refused(self):
        for bad in ([], [[]], [[1, 2], [3]]):
            with self.assertRaises(ValueError, msg=bad):
                zero_sum.solve(bad)


class GapTest(unittest.TestCase):
    def test_the_gap_of_pure_strategies_in_matching_pennies(self):
        g = zero_sum.gap([[1, 0], [0, 1]], [1, 0], [1, 0])
        self.assertEqual(g, {"best_row": 1, "worst_column": 0, "gap": 1})

    def test_a_larger_matrix_widens_the_gap_of_an_old_equilibrium(self):
        a = [[1, 0], [0, 1]]
        x, y, _ = zero_sum.solve(a)
        wider = [[1, 0, 0], [0, 1, F(1, 4)], [F(3, 4), F(3, 4), F(1, 2)]]  # a new row and a new column
        g = zero_sum.gap(wider, x + [0], y + [0])
        self.assertEqual(g["best_row"], F(3, 4))  # the new row against the old column mix
        self.assertEqual(g["worst_column"], F(1, 8))  # the new column against the old row mix
        self.assertEqual(g["gap"], F(5, 8))

    def test_mixes_must_be_distributions_of_the_right_size(self):
        with self.assertRaisesRegex(ValueError, "row mix"):
            zero_sum.gap([[1, 0], [0, 1]], [F(1, 2), F(1, 3)], [F(1, 2), F(1, 2)])
        with self.assertRaisesRegex(ValueError, "column mix"):
            zero_sum.gap([[1, 0], [0, 1]], [F(1, 2), F(1, 2)], [1])
        with self.assertRaisesRegex(ValueError, "row mix"):
            zero_sum.gap([[1, 0], [0, 1]], [F(3, 2), F(-1, 2)], [F(1, 2), F(1, 2)])


if __name__ == "__main__":
    unittest.main()
