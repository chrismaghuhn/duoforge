"""The leaf evaluation of the two-turn tree, the slow tier (duoforge_search.evaluator; plan docs/superpowers/plans/
2026-10-14-depth-search-d2.md step 3): the jax evaluator gives exactly today's leaves (Honest._prepare and _values:
values bit for bit, statuses, tiebreaks) on the A/B/C turn positions, for both seats, with and without the cut-off,
on 2 x 2 x 8 = 32 leaves per decision (two expand chunks and two value calls of the capacity 16), whatever its expand
chunk. The quick tier (test_evaluator_quick) runs one fixed position on every pull request."""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

import unittest

import duoforge
import numpy as np
from duoforge import _layout
from duoforge_search import belief
from python.tests.search.test_evaluator_quick import assert_jax_is_today, make_search, to_first_turn, todays_leaves
from python.tests.search.test_search import _v2s

C = _layout.CONSTANTS


class JaxLeaves(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.params = _v2s()

    def test_the_abc_positions_for_both_seats_and_every_chunk(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = duoforge.teams.load(ctx, ["A", "B", "C"])
            table = belief.SpreadTable.from_sides(pool.sides)
            with duoforge.Batch(ctx, pool.setups(np.array([0, 1, 2]), np.array([1, 2, 0])), 2, 42) as roots, \
                    make_search(ctx, self.model, self.params, 8, 16, table=table, excluded=[1, 2, 0]) as search:
                to_first_turn(search, roots)
                cut_off = 0
                for env in range(3):
                    for seat in (0, 1):
                        for last_step in (False, True):
                            request, values = todays_leaves(self, search, roots, env, seat, 456 + env, last_step)
                            self.assertEqual(request.step.size, 32)
                            cut_off += int((request.tiebreaks != 0).sum())
                            for chunk in (16, 5, 1):
                                with self.subTest(env=env, seat=seat, last_step=last_step, chunk=chunk):
                                    assert_jax_is_today(self, search, request, values, chunk, last_step)
                self.assertGreater(cut_off, 0)


if __name__ == "__main__":
    unittest.main()
