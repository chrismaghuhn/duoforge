"""duoforge.python.teams: the team pool (decision 0017).

A pool holds ids, file hashes, weights and side setups; it builds battle
setups for pairs of team indices and refuses weights a sampler cannot use.
"""
import unittest

import numpy as np

import duoforge
from duoforge import teams


def _pool(weights=None):
    return teams.TeamPool.from_setups(("A", "B"), duoforge.reference_setups([0])["sides"][0], weights)


class TeamPoolTest(unittest.TestCase):
    def test_from_setups_and_setups(self):
        pool = _pool()
        self.assertEqual(pool.ids, ("A", "B"))
        self.assertEqual(pool.sha256, ("", ""))
        got = pool.setups(np.array([0, 1]), np.array([1, 1]))
        want = duoforge.reference_setups([0, 3])
        want["rng_initstate"] = 0
        want["rng_initseq"] = 0
        self.assertEqual(got.tobytes(), want.tobytes())

    def test_weights_are_validated(self):
        for bad in ((-1.0, 1.0), (float("nan"), 1.0), (0.0, 0.0), (1.0,), (float("inf"), 1.0)):
            with self.assertRaises(ValueError):
                _pool(bad)
        self.assertEqual(_pool((0.0, 2.0)).weights.tolist(), [0.0, 2.0])
        self.assertEqual(_pool().with_weights((3.0, 1.0)).weights.tolist(), [3.0, 1.0])

    def test_pool_needs_unique_ids_and_matching_sides(self):
        sides = duoforge.reference_setups([0])["sides"][0]
        with self.assertRaises(ValueError):
            teams.TeamPool.from_setups(("A", "A"), sides)
        with self.assertRaises(ValueError):
            teams.TeamPool.from_setups(("A", "B", "C"), sides)


if __name__ == "__main__":
    unittest.main()
