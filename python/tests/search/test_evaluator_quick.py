"""The leaf evaluation of the two-turn tree, the quick tier (duoforge_search.evaluator; plan docs/superpowers/plans/
2026-10-14-depth-search-d2.md step 3): on one fixed position the jax evaluator gives exactly today's leaves
(Honest._prepare and _values: values bit for bit, statuses, tiebreaks), with and without the cut-off, for several
expand chunks and two value calls; the engine evaluator is refused by name until #485's call exists. The slow tier
(test_evaluator) runs the same comparison on more positions, both seats and wider tables."""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

import unittest

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_search import SearchError, belief, evaluator, honest
C = _layout.CONSTANTS
# The tier's budget is a few seconds and the model's first initialization compiles: the smallest dimensions (the
# comparison holds for any network; the slow tier uses test_search's preset-S model).
TINY = {"embed": 4, "member": 8, "position": 8, "hidden": 16, "layers": 1, "option": 8}


def _tiny():
    import jax
    from duoforge_learn import policy
    model = policy.make(policy.v2_config("S", **TINY), features.feature_names(4))
    return model, model.init(jax.random.PRNGKey(7))


def make_search(ctx, model, params, s, capacity, table=None, excluded=None):
    """An Honest search of k = m = 2 on encoder 4 (the model's), with the reference sides' spread table by default."""
    table = table or belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
    with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
        mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)
    return honest.Honest(ctx, model, params, 4, mask, k=2, m=2, s=s, capacity=capacity, workers=2, table=table,
                         exclude_teams=excluded)


def to_first_turn(search, roots):
    """Team preview for both seats of every root (the turn's worlds need its record), then both step past it."""
    envs = list(range(roots.envs))
    for seat in (0, 1):
        search.decide(roots, envs, [seat] * roots.envs, [123] * roots.envs, [False] * roots.envs)
    roots.query_factored()
    choices = np.zeros((roots.envs, 2), _layout.FACTORED_CHOICE)
    choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
    roots.step_factored(choices)
    roots.query_factored()


def todays_leaves(case, search, roots, env, seat, key, last_step):
    """(request, values): the decision's leaves as Honest prepares and values them today, on the worlds its decide
    just built."""
    _, records = search.decide(roots, [env], [seat], [key], [last_step])
    r = records[0]
    case.assertEqual(r["kind"], "searched")
    costs = {"leaves": 0.0, "network": 0.0, "world_builds": 0.0}
    request = search._prepare(seat, key, np.asarray(r["own_pairs"]), np.asarray(r["weights"]), last_step, costs)
    return request, search._values(request, costs)


def assert_jax_is_today(case, search, request, values, chunk, last_step):
    jax = evaluator.make("jax", leaves=search.leaves, model=search.model, params=search.params,
                         encoder=search.encoder, ext_supported=search.ext_supported, rows=search._rows, chunk=chunk)
    w = request.plan[2].astype(np.uint32)
    costs = {"leaves": 0.0, "network": 0.0}
    got = jax.leaves(search.worlds, search.seed, np.full(search.s, request.key, np.uint64),
                     np.full(search.s, request.p, np.uint8), w, w, request.choices, np.full(w.size, last_step), costs)
    case.assertGreater(costs["leaves"], 0.0)
    case.assertGreater(costs["network"], 0.0)
    case.assertEqual(got.values.tobytes(), values.tobytes())
    for name in ("step", "encode", "results", "tiebreaks"):
        case.assertEqual(getattr(got, name).tolist(), getattr(request, name).tolist(), name)


class QuickJaxLeaves(unittest.TestCase):
    # One context, search and root for the class.
    @classmethod
    def setUpClass(cls):
        cls.model, cls.params = _tiny()
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.search = make_search(cls.ctx, cls.model, cls.params, 2, 4)
        cls.roots = duoforge.Batch(cls.ctx, duoforge.reference_setups([0]), 1, 42)
        to_first_turn(cls.search, cls.roots)

    @classmethod
    def tearDownClass(cls):
        cls.roots.close()
        cls.search.close()
        cls.ctx.close()

    def test_one_position_bit_for_bit(self):
        # Reference setup 0, turn 1, seat 0: 2 x 2 x 2 = 8 leaves, two value calls of the capacity 4.
        for last_step in (False, True):
            request, values = todays_leaves(self, self.search, self.roots, 0, 0, 456, last_step)
            self.assertEqual(request.step.size, 8)
            self.assertEqual(bool((request.tiebreaks != 0).any()), last_step)
            for chunk in (4, 3, 1):
                with self.subTest(last_step=last_step, chunk=chunk):
                    assert_jax_is_today(self, self.search, request, values, chunk, last_step)

    def test_an_expand_chunk_must_fit_the_leaf_batch(self):
        search = self.search
        for chunk in (0, 5, 4.0):
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
