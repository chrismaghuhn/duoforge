"""The A/B test of the root rule (duoforge_live.ab): the draw, the arms, their one difference."""
import inspect
import unittest

from duoforge_live import ab, search as live_search


class DrawTest(unittest.TestCase):
    def test_the_draw_is_a_pure_function_of_the_seed_and_the_number(self):
        self.assertEqual([ab.arm(5, i) for i in range(40)], [ab.arm(5, i) for i in range(40)])
        self.assertEqual(list(inspect.signature(ab.arm).parameters), ["seed", "index"])  # nothing of the opponent
        self.assertNotEqual([ab.arm(5, i) for i in range(40)], [ab.arm(6, i) for i in range(40)])

    def test_every_block_of_two_plays_each_arm_once_in_a_drawn_order(self):
        for seed in (0, 1, 2**62 + 3):
            arms = [ab.arm(seed, i) for i in range(200)]
            for b in range(100):
                self.assertEqual(sorted(arms[2 * b:2 * b + 2]), sorted(ab.ARMS), (seed, b))
            firsts = [arms[2 * b] for b in range(100)]
            self.assertTrue(20 <= firsts.count(ab.ARMS[0]) <= 80, (seed, firsts.count(ab.ARMS[0])))  # both orders

    def test_a_bad_seed_or_number_is_refused(self):
        for seed, index in ((True, 0), ("1", 0), (1, -1), (1, 1.0), (1, False)):
            with self.subTest(seed=seed, index=index), self.assertRaises(ValueError):
                ab.arm(seed, index)

    def test_new_seeds_are_ints_that_differ(self):
        seeds = {ab.new_seed() for _ in range(8)}
        self.assertTrue(all(isinstance(s, int) and 0 <= s < 2**63 for s in seeds))
        self.assertGreater(len(seeds), 1)


class ArmsTest(unittest.TestCase):
    def test_the_arms_are_steps_0_and_2e_and_differ_in_the_root_rule_alone(self):
        arms = ab.settings()
        self.assertEqual(set(arms), {"0", "2e"})
        self.assertEqual((ab.rule("0"), ab.rule("2e")), ("mix", "ev"))
        self.assertEqual({k: v for k, v in arms["0"].items() if k != "rule"},
                         {k: v for k, v in arms["2e"].items() if k != "rule"})
        self.assertEqual(set(ab.rule(a) for a in ab.ARMS), set(live_search.ROOT_RULES))

    def test_the_live_search_is_an_arm_but_the_rule(self):
        ab.check_arms(live_search.HONEST_SETTINGS)
        ab.check_arms({**live_search.HONEST_SETTINGS, "rule": "mix"})
        for key, value in (("k", 4), ("lam", 0.0), ("s", 32), ("species_prior", True)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "not the arms'"):
                ab.check_arms({**live_search.HONEST_SETTINGS, key: value})


if __name__ == "__main__":
    unittest.main()
