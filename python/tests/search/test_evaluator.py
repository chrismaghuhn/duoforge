"""The leaf evaluation of the two-turn tree (duoforge_search.evaluator; plan docs/superpowers/plans/2026-10-14-depth-
search-d2.md step 3): the jax evaluator gives exactly today's leaves (Honest._prepare and _values: values, statuses,
tiebreaks) whatever its expand chunk; the engine evaluator is refused by name until #485's call exists."""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

import unittest

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_search import SearchError, belief, evaluator, honest
from python.tests.search.test_search import _v2s

C = _layout.CONSTANTS
KEY = 456


class JaxLeaves(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.params = _v2s()

    def search(self, ctx, s):
        table = belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
        with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)
        return honest.Honest(ctx, self.model, self.params, 4, mask, k=2, m=2, s=s, capacity=16, workers=2,
                             table=table)

    def today(self, ctx, last_step):
        """(search, root, request, values): a turn decision's leaves as Honest prepares and values them today, on
        2 x 2 x 8 = 32 leaves, two expand chunks and two value calls of the capacity 16."""
        search = self.search(ctx, 8)
        root = duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42)
        search.decide(root, [0], [0], [123], [False])  # team preview: the history of the turn's worlds
        root.query_factored()
        choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
        choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
        root.step_factored(choices)
        root.query_factored()
        _, records = search.decide(root, [0], [0], [KEY], [last_step])
        r = records[0]
        self.assertEqual(r["kind"], "searched")
        costs = {"leaves": 0.0, "network": 0.0, "world_builds": 0.0}
        request = search._prepare(0, KEY, np.asarray(r["own_pairs"]), np.asarray(r["weights"]), last_step, costs)
        return search, root, request, search._values(request, costs)

    def evaluate(self, search, request, chunk, last_step):
        jax = evaluator.make("jax", leaves=search.leaves, model=search.model, params=search.params,
                             encoder=search.encoder, ext_supported=search.ext_supported, rows=search._rows,
                             chunk=chunk)
        w = request.plan[2].astype(np.uint32)
        costs = {"leaves": 0.0, "network": 0.0}
        leaves = jax.leaves(search.worlds, search.seed, np.full(search.s, KEY, np.uint64),
                            np.full(search.s, request.p, np.uint8), w, w, request.choices,
                            np.full(w.size, last_step), costs)
        self.assertGreater(costs["leaves"], 0.0)
        self.assertGreater(costs["network"], 0.0)
        return leaves

    def test_the_jax_evaluator_is_todays_leaves_for_every_chunk(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            for last_step in (False, True):
                search, root, request, values = self.today(ctx, last_step)
                with search, root:
                    self.assertEqual(request.step.size, 32)
                    if last_step:
                        self.assertTrue((request.tiebreaks != 0).any())
                    for chunk in (16, 5, 1):
                        with self.subTest(last_step=last_step, chunk=chunk):
                            got = self.evaluate(search, request, chunk, last_step)
                            self.assertEqual(got.values.tobytes(), values.tobytes())
                            for name in ("step", "encode", "results", "tiebreaks"):
                                self.assertEqual(getattr(got, name).tolist(), getattr(request, name).tolist(), name)

    def test_an_expand_chunk_must_fit_the_leaf_batch(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, self.search(ctx, 2) as search:
            for chunk in (0, 17, 4.0):
                with self.subTest(chunk=chunk), self.assertRaisesRegex(ValueError, "chunk"):
                    evaluator.make("jax", leaves=search.leaves, model=search.model, params=search.params,
                                   encoder=search.encoder, ext_supported=search.ext_supported, rows=search._rows,
                                   chunk=chunk)


class Names(unittest.TestCase):
    def test_the_engine_evaluator_is_refused_by_name_until_its_call_exists(self):
        with self.assertRaisesRegex(SearchError, "^evaluator_engine_unavailable"):
            evaluator.make("engine")

    def test_an_unknown_evaluator_is_refused(self):
        with self.assertRaisesRegex(ValueError, "evaluator"):
            evaluator.make("numpy")


if __name__ == "__main__":
    unittest.main()
