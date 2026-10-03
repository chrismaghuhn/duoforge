"""duoforge.python.search: the JAX parts of the search (decision 0022, spec
docs/superpowers/specs/2026-10-03-m12-search-stage1-design.md).

- Model.value equals the value of apply, bit for bit (plan task 8).
- The lookahead (plan task 9): common random numbers across the cells and
  chunks, the seat's view at the leaves, purity, one decision alone and
  inside a round, a pinned table
  digest on the CPU, the decisions that are not searched, M' = 1 for a foe
  without a request, the encoder probe and the reproduction data.

The NumPy parts are in test_search_numpy.py. Teams A and B under POOL, at
fixed init keys, on the CPU.
"""
import hashlib
import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge.context import reference_setups
from duoforge_search import SearchError, lookahead, seeds

C = _layout.CONSTANTS
SEED = 0x2026100300000231
ARENA_SEED = 0x2026100300000222
ENVS = 16


def _rows(envs=32, steps=5):
    """obs, slots and pair mask of both seats of `envs` POOL environments
    after `steps` random steps (2 * envs rows), encoder 4 with the library's
    mask."""
    with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
            duoforge.Batch(ctx, np.resize(reference_setups([0, 1, 2, 3]), envs), 2, SEED) as b:
        policy = duoforge.RandomPolicy(SEED, envs)
        for _ in range(steps):
            b.query_factored()
            b.step_factored(policy.choose_factored(b))
            b.reset_terminal()
        b.query_factored()
        mask = int(b.observe_ext()[0, 0]["supported"])
        obs, slots, pairs = (x.copy() for x in b.query_encoded(4, mask))
    return (obs.reshape(2 * envs, -1), slots.reshape((2 * envs,) + slots.shape[2:]),
            pairs.reshape((2 * envs,) + pairs.shape[2:]))


class ModelValue(unittest.TestCase):
    def test_value_equals_apply_value(self):
        import jax
        from duoforge_learn import policy
        obs, slots, mask = _rows()
        self.assertTrue(mask.any())  # real pair masks: the value must not read them
        for config in (policy.V1_DEFAULT, policy.v2_config("S")):
            model = policy.make(config)
            params = model.init(jax.random.PRNGKey(5))
            want = np.asarray(model.apply(params, obs, slots, mask)[2])
            got = np.asarray(model.value(params, obs))
            self.assertEqual((got.shape, got.dtype), ((64,), np.float32))
            np.testing.assert_array_equal(got.view(np.uint32), want.view(np.uint32))


def _v2s():
    import jax
    from duoforge_learn import policy
    model = policy.make(policy.v2_config("S"))
    return model, model.init(jax.random.PRNGKey(7))


def _keys(batch, envs, seats):
    epochs = batch.requests["epoch"][envs, seats]
    episodes = [batch.episode(int(e)) for e in envs]
    return seeds.decision_keys(ARENA_SEED, envs, episodes, epochs, seats)


class LookaheadDecisions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.model, cls.params = _v2s()
        cls.roots = duoforge.Batch(cls.ctx, np.resize(reference_setups([0, 1, 2, 3]), ENVS), 2, SEED)
        policy = duoforge.RandomPolicy(SEED, ENVS)
        for _ in range(4):
            cls.roots.query_factored()
            cls.roots.step_factored(policy.choose_factored(cls.roots))
            cls.roots.reset_terminal()
        cls.roots.query_factored()
        cls.mask = int(cls.roots.observe_ext()[0, 0]["supported"])
        _, _, pairs = cls.roots.query_encoded(4, cls.mask)
        seats = np.arange(ENVS) % 2
        every = np.arange(ENVS)
        searched = ((cls.roots.requests["requested"][every, seats] != 0)
                    & (cls.roots.domains["kind"][every, seats] == C["DUOFORGE_CHOICE_SLOTS"])
                    & (pairs[every, seats].reshape(ENVS, -1).sum(axis=1) >= 2))
        cls.envs, cls.seats = every[searched], seats[searched]
        cls.keys = _keys(cls.roots, cls.envs, cls.seats)

    @classmethod
    def tearDownClass(cls):
        cls.roots.close()
        cls.ctx.close()

    def _lookahead(self, **change):
        args = dict(k=3, m=3, s=4, capacity=256, workers=2)
        args.update(change)
        return lookahead.Lookahead(self.ctx, self.model, self.params, 4, self.mask, **args)

    def _decide(self, look, envs=None):
        pick = slice(None) if envs is None else np.isin(self.envs, envs)
        n = self.envs[pick].size
        return look.decide(self.roots, self.envs[pick], self.seats[pick], self.keys[pick], np.zeros(n, bool))

    @staticmethod
    def _tables(records):
        return [(r["env"], np.array(r["table"])) for r in records]

    def test_round_is_searched(self):
        self.assertGreaterEqual(self.envs.size, 12)  # the fixture: a round of searched decisions
        with self._lookahead() as look:
            actions, records = self._decide(look)
        self.assertEqual([r["kind"] for r in records], ["searched"] * self.envs.size)
        for r, a in zip(records, actions):
            self.assertEqual((r["k"], r["m"], r["s"]), (3, 3, 4))
            self.assertIn(int(a), r["own_pairs"])
            self.assertEqual(int(a), r["choice"])
            self.assertEqual(r["raw"], r["own_pairs"][0])
            self.assertEqual(sum(r["leaves"][b] for b in ("TURN", "REPLACEMENT", "PIVOT", "TERMINAL"))
                             + r["leaves"]["refused"], 36)
            self.assertAlmostEqual(sum(r["x"]), 1.0, places=12)

    def test_samples_share_seeds_across_cells(self):
        with self._lookahead() as look:
            _, records = self._decide(look)
            last = look.last
            # The plan: a leaf's seeds are those of (search seed, its root's key, its sample), never of its cell.
            for d in np.unique(last["decision"]):
                at = np.flatnonzero(last["decision"] == d)
                env = int(np.unique(last["root_envs"][at])[0])
                self.assertEqual(np.unique(last["root_envs"][at]).size, 1)
                key = int(self.keys[list(self.envs).index(env)])
                np.testing.assert_array_equal(last["samples"][at], last["sample"][at])
                by_sample = {}
                for x in at:
                    seeds_of = duoforge.search_seeds(lookahead.SEARCH_SEED, key, int(last["samples"][x]))
                    by_sample.setdefault(int(last["sample"][x]), set()).add(seeds_of)
                self.assertEqual(sorted(by_sample), [0, 1, 2, 3])
                self.assertTrue(all(len(v) == 1 for v in by_sample.values()))  # one seed pair per sample
                self.assertEqual(len(set().union(*by_sample.values())), 4)
            # The decisions in reverse order: every leaf in another chunk and position, the same tables (the
            # network's batch shape stays capacity; another shape changes its float32 values in the last bits).
            rev = slice(None, None, -1)
            _, reverse = look.decide(self.roots, self.envs[rev], self.seats[rev], self.keys[rev],
                                     np.zeros(self.envs.size, bool))
        for (e, a), (f, b) in zip(self._tables(records), self._tables(reverse[::-1])):
            self.assertEqual(e, f)
            np.testing.assert_array_equal(a, b)

    def test_leaf_values_are_the_seats_view(self):
        # A leaf expanded by hand, the deciding seat its viewer, has the value the lookahead recorded: the
        # leaf's row is the seat's (spec section 5.3), valued in the same padded call shape.
        with self._lookahead() as look, duoforge.Batch(self.ctx, reference_setups([0]), 1, SEED) as one:
            self._decide(look)
            last = look.last
            x = int(np.flatnonzero((last["step_statuses"] == 0) & (last["leaf_results"] == 0))[0])
            env = int(last["root_envs"][x])
            seat = int(self.seats[list(self.envs).index(env)])
            keys = np.zeros(ENVS, dtype=np.uint64)
            keys[self.envs] = self.keys
            for viewer, same in ((seat, True), (1 - seat, False)):
                viewers = np.zeros(ENVS, dtype=np.uint8)
                viewers[env] = viewer
                obs = one.expand(self.roots, 4, self.mask, lookahead.SEARCH_SEED, keys, viewers,
                                 last["root_envs"][x:x + 1], last["samples"][x:x + 1], last["choices"][x:x + 1])[0]
                rows = np.zeros((256, obs.shape[1]), dtype=np.float32)
                rows[0] = obs[0]
                value = np.asarray(self.model.value(self.params, rows))[0]
                self.assertEqual(value == last["values"][x], same)

    def test_decision_is_pure(self):
        with self._lookahead() as look:
            first = self._decide(look)
            second = self._decide(look)
        np.testing.assert_array_equal(first[0], second[0])
        for a, b in zip(first[1], second[1]):
            self.assertEqual({k: v for k, v in a.items() if k != "time"}, {k: v for k, v in b.items() if k != "time"})

    def test_alone_equals_in_a_round(self):
        import jax
        with self._lookahead() as look:
            _, round_records = self._decide(look)
            env = int(self.envs[len(self.envs) // 2])
            _, alone = self._decide(look, [env])
        inside = [r for r in round_records if r["env"] == env][0]
        try:
            np.testing.assert_array_equal(np.array(alone[0]["table"]), np.array(inside["table"]))
            self.assertEqual(alone[0]["choice"], inside["choice"])
        except AssertionError:
            if jax.default_backend() == "cpu":
                raise
            self.skipTest(f"an expected failure on {jax.default_backend()} only (spec section 10): reported")

    def test_pinned_table_digest(self):
        import jax
        if jax.default_backend() != "cpu":
            self.skipTest("the digest is pinned on the CPU")
        with self._lookahead() as look:
            env = int(self.envs[0])
            _, records = self._decide(look, [env])
        digest = hashlib.sha256(np.array(records[0]["table"], dtype=np.float64).tobytes()).hexdigest()
        self.assertEqual(digest, PINNED_TABLE, f"table {records[0]['table']} on {jax.devices()}, JAX {jax.__version__}")

    def test_encoder_probe_refuses_at_init(self):
        with self.assertRaises(ValueError):  # no mask of the feature bits
            self._lookahead(capacity=4).__init__(self.ctx, self.model, self.params, 4, 1 << 42)
        from duoforge_learn import policy
        v3 = policy.make(policy.v2_config("S"), features.feature_names(3))
        with self.assertRaises(duoforge.DuoforgeError):  # a mask past version 3's features: the C encoder refuses
            lookahead.Lookahead(self.ctx, v3, v3.init(__import__("jax").random.PRNGKey(7)), 3, 1 << 40, capacity=4)
        with self.assertRaisesRegex(ValueError, "the model reads"):
            lookahead.Lookahead(self.ctx, self.model, self.params, 3, 0, capacity=4)

    def test_stopped_run_carries_reproduction_data(self):
        def refuse(*args, **kwargs):
            raise lookahead._leaf_error(5, "the encoder refused the row with DUOFORGE_E_INVALID_ARGUMENT")
        env, seat, key = int(self.envs[0]), int(self.seats[0]), int(self.keys[0])
        with self._lookahead() as look, mock.patch.object(lookahead, "table", refuse):
            with self.assertRaisesRegex(SearchError, "the run stops") as caught:
                self._decide(look, [env])
            last = look.last
        data = caught.exception.reproduction
        sample = int(last["sample"][5])
        self.assertEqual((data["env"], data["seat"], data["key"], data["sample"]), (env, seat, key, sample))
        self.assertEqual((data["initstate"], data["initseq"]), duoforge.search_seeds(lookahead.SEARCH_SEED, key, sample))
        self.assertEqual(bytes.fromhex(data["root"]), self.roots.encode(env))
        own = last["choices"][5, seat]["slot"]
        self.assertEqual(data["own_pair"], int(own[0]) * 32 + int(own[1]))


class LookaheadKinds(unittest.TestCase):
    """Spec section 5.7 and M' = 1: decisions without leaves, and a foe
    without a request."""

    @classmethod
    def setUpClass(cls):
        cls.model, cls.params = _v2s()

    def test_forced_and_team_selection_are_not_searched(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, np.resize(reference_setups([0, 1, 2, 3]), ENVS), 2, SEED) as roots:
            roots.query_factored()
            mask = int(roots.observe_ext()[0, 0]["supported"])
            with lookahead.Lookahead(ctx, self.model, self.params, 4, mask, k=2, m=2, s=2, capacity=64,
                                     workers=2) as look:
                every = np.arange(ENVS)
                seats = every % 2
                actions, records = look.decide(roots, every, seats, _keys(roots, every, seats), np.zeros(ENVS, bool))
                self.assertEqual({r["kind"] for r in records}, {"team"})
                self.assertIsNone(look.last)
                self.assertTrue(((actions >= 0) & (actions < 360)).all())
                forced = lone = None
                policy = duoforge.RandomPolicy(SEED, ENVS)
                for _ in range(400):  # random play until a forced decision and a lone decider are met
                    roots.query_factored()
                    _, _, pairs = roots.query_encoded(4, mask)
                    asked = roots.requests["requested"] != 0
                    slots = roots.domains["kind"] == C["DUOFORGE_CHOICE_SLOTS"]
                    count = pairs.reshape(ENVS, 2, -1).sum(axis=2)
                    if forced is None and (asked & slots & (count == 1)).any():
                        e, p = (int(x[0]) for x in np.nonzero(asked & slots & (count == 1)))
                        _, (r,) = look.decide(roots, [e], [p], _keys(roots, [e], [p]), [False])
                        forced = r
                    lone_at = asked & slots & (count >= 2) & ~asked[:, ::-1]
                    if lone is None and lone_at.any():
                        e, p = (int(x[0]) for x in np.nonzero(lone_at))
                        _, (r,) = look.decide(roots, [e], [p], _keys(roots, [e], [p]), [False])
                        lone = r
                        with self.assertRaisesRegex(ValueError, "no request"):  # the foe has no decision
                            look.decide(roots, [e], [1 - p], [0], [False])
                    if forced is not None and lone is not None:
                        break
                    roots.step_factored(policy.choose_factored(roots))
                    roots.reset_terminal()
        self.assertIsNotNone(forced, "no forced decision in 400 random steps")
        self.assertEqual(forced["kind"], "forced")
        self.assertNotIn("table", forced)
        self.assertIsNotNone(lone, "no decision without the foe's request in 400 random steps")
        self.assertEqual((lone["kind"], lone["m"], lone["foe_pairs"], lone["coverage"]), ("searched", 1, [-1], 1.0))

    def test_bad_decisions_are_refused(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, reference_setups([0, 1]), 1, SEED) as roots:
            roots.query_factored()
            with lookahead.Lookahead(ctx, self.model, self.params, 4, 0, k=2, m=2, s=2, capacity=8,
                                     workers=1) as look:
                roots.step_factored(duoforge.RandomPolicy(SEED, 2).choose_factored(roots))
                for envs, seats in (([0, 0], [0, 1]), ([2], [0]), ([0], [2]), ([0, 1], [0])):
                    with self.assertRaises(ValueError):  # twice, past the roots, no seat, one seat short
                        look.decide(roots, envs, seats, [1] * len(envs), [False] * len(envs))
                self.assertEqual(look.decide(roots, [], [], [], [])[1], [])


# One decision's 3 x 3 table (S = 4, capacity 256) at v2-S init key 7, float64 bytes, on the CPU with JAX
# 0.11.2. The same under --xla_cpu_max_isa=AVX2 and AVX512; another JAX version or a CPU without FMA may differ.
PINNED_TABLE = "56b79262081bb7e9ec52d18ac29634f515041459e065f0192ea14533103eb7ee"


if __name__ == "__main__":
    unittest.main()
