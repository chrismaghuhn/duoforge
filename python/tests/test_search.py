"""duoforge.python.search: the JAX parts of the search (decision 0022, spec
docs/superpowers/specs/2026-10-03-m12-search-stage1-design.md).

- Model.value equals the value of apply, bit for bit (plan task 8).
- The lookahead (plan task 9): common random numbers across the cells and
  chunks, the seat's view at the leaves, purity, one decision alone and
  inside a round, a pinned decision on the CPU (its integer and structural
  parts exactly on every machine, its table within a tolerance, the
  table's bytes only under recorded conditions), the decisions that are
  not searched, M' = 1 for a foe without a request, the encoder probe and
  the reproduction data.
- SearchPlayer in play_suite (plan task 10): the step and the seats, K = 1
  reproduces the raw network, the cut-off leaves use the tiebreak.
- The measurement CLI (plan task 11) end to end on tiny checkpoints.

The NumPy parts are in test_search_numpy.py. Teams A and B (the arena: A, B
and C) under POOL, at fixed init keys, on the CPU.
"""
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge.context import reference_setups
from duoforge_search import SearchError, arena, lookahead, matrix, seeds

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
        mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)  # encoder 4 (0050)
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
            model = policy.make(config, features.feature_names(4))  # the encoder-4 rows of _rows
            params = model.init(jax.random.PRNGKey(5))
            want = np.asarray(model.apply(params, obs, slots, mask)[2])
            got = np.asarray(model.value(params, obs))
            self.assertEqual((got.shape, got.dtype), ((64,), np.float32))
            np.testing.assert_array_equal(got.view(np.uint32), want.view(np.uint32))


def _v2s():
    import jax
    from duoforge_learn import policy
    model = policy.make(policy.v2_config("S"), features.feature_names(4))  # pinned values: an encoder-4 model
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
        cls.mask = int(cls.roots.observe_ext()[0, 0]["supported"]) & features.version_features(4)  # encoder 4 (0050)
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

    def test_expected_value_rule(self):
        # Rule "ev" (spec section 5.5): the row with the highest expected value under the foe's probabilities.
        with self._lookahead(rule="ev") as look:
            _, records = self._decide(look)
        for r in records:
            a, q = np.array(r["table"]), np.array(r["foe_probs"])
            self.assertEqual(r["expected"], matrix.expected_values(a, q).tolist())
            self.assertEqual(r["choice"], r["own_pairs"][matrix.expected_choice(a, q, np.arange(r["k"]))])
            # The visible-search contract records all N/E/X outcomes for every rule.
            self.assertEqual(set(r["outcomes"]), set(lookahead.RULES))
            self.assertEqual(r["choice"], r["own_pairs"][r["outcomes"]["ev"]])
            matrix.certify(a, np.array(r["x"]), np.array(r["y"]))
            self.assertIn("same_choice", r["split"])
        self.assertTrue(any(r["changed"] for r in records))  # rows other than the raw network's are played

    def test_mixed_nash_draw(self):
        # Genuinely mixed strategies: the play draw u, a pure function of the key (decision 0022 section 2),
        # picks the row. Pinned on every machine: u is integer-derived, and u lies far from every boundary.
        with self._lookahead() as look:
            _, records = self._decide(look)
        by_env = {r["env"]: r for r in records}
        for env, (u, row) in PINNED_DRAWS.items():
            r = by_env[env]
            self.assertEqual(r["u"], u)
            self.assertEqual(u, float(seeds.play_uniforms(lookahead.SEARCH_SEED, np.uint64([r["key"]]))[0]))
            x = np.array(r["x"])
            self.assertGreaterEqual(int((x >= matrix.PROBABILITY_FLOOR).sum()), 2)
            self.assertGreater(np.min(np.abs(np.cumsum(x)[:-1] - u)), 1e-3)
            self.assertEqual(matrix.draw(x, np.arange(x.size), u), row)
            self.assertEqual(r["choice"], r["own_pairs"][row])
        env = next(iter(PINNED_DRAWS))  # the lowest and the highest u play the first and the last row with mass
        support = np.flatnonzero(np.array(by_env[env]["x"]) >= matrix.PROBABILITY_FLOOR)
        for u, row in ((0.0, support[0]), (1.0 - 2.0 ** -53, support[-1])):
            with mock.patch.object(lookahead.seeds, "play_uniforms", lambda seed, keys, u=u: np.full(len(keys), u)), \
                    self._lookahead() as look:
                _, (r,) = self._decide(look, [env])
            self.assertEqual(r["choice"], r["own_pairs"][row])

    def test_unresolvable_tiebreak_counts_minus_one(self):
        # Spec section 5.3: at the cut-off a tiebreak the engine cannot resolve (E_UNSUPPORTED: the reference's
        # bench order would decide) counts -1 and is counted; any other refusal of the tiebreak stops the run.
        pick = self.envs == self.envs[0]
        with self._lookahead() as look:
            real = look.leaves.tiebreak

            def tiebreak(e, status="DUOFORGE_E_UNSUPPORTED"):
                if e % 3 == 0:
                    raise duoforge.DuoforgeError(status)
                return real(e)

            with mock.patch.object(look.leaves, "tiebreak", tiebreak):
                _, (r,) = look.decide(self.roots, self.envs[pick], self.seats[pick], self.keys[pick], [True])
            last = look.last
            with mock.patch.object(look.leaves, "tiebreak", lambda e: tiebreak(e, "DUOFORGE_E_INVALID_ARGUMENT")):
                with self.assertRaises(duoforge.DuoforgeError):
                    look.decide(self.roots, self.envs[pick], self.seats[pick], self.keys[pick], [True])
        opened = (last["step_statuses"] == 0) & (last["leaf_results"] == 0)
        unresolved = opened & (np.arange(opened.size) % 3 == 0)
        self.assertGreater(int(unresolved.sum()), 0)
        self.assertEqual((r["leaves"]["cut_off"], r["leaves"]["unresolved"]),
                         (int(opened.sum()), int(unresolved.sum())))
        cube = last["tables"][0].values
        cells = cube[last["i"], last["j"], last["sample"]]
        np.testing.assert_array_equal(cells[unresolved], -1.0)
        self.assertTrue(np.isin(cells[opened], (-1.0, 0.0, 1.0)).all())  # results, never the value head

    def test_missed_certificate_carries_the_table(self):
        # Spec section 7: a missed Nash certificate stops the run and writes the table.
        def missed(a):
            raise SearchError("the Nash certificate is missed")

        env = int(self.envs[0])
        with self._lookahead() as look, mock.patch.object(lookahead.matrix, "solve", missed):
            with self.assertRaisesRegex(SearchError, "the run stops") as caught:
                self._decide(look, [env])
            table = look.last["tables"][0]
        data = caught.exception.reproduction
        self.assertEqual((data["env"], data["rule"], data["table"]), (env, "nash", table.a.tolist()))
        self.assertEqual(data["values"], table.values.tolist())

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

    def _pinned(self):
        """The pinned decision: (its record, the lookahead's last leaves, the roots' policy over all rows)."""
        env = int(self.envs[0])
        with self._lookahead() as look:
            _, (record,) = self._decide(look, [env])
            last = look.last
        obs, slots, pairs = self.roots.query_encoded(4, self.mask)
        rows = 2 * ENVS
        logp = np.asarray(self.model.apply(self.params, obs.reshape(rows, -1), slots.reshape((rows,) + slots.shape[2:]),
                                           pairs.reshape((rows,) + pairs.shape[2:]))[0]).reshape(ENVS, 2, -1)
        return record, last, logp, pairs.reshape(ENVS, 2, -1)

    def test_pinned_decision(self):
        # Spec section 10, end to end, on every machine: the integer and structural parts exactly, the table
        # within TABLE_TOLERANCE (the network's float32 values differ in the last bits by machine, section 6).
        import jax
        if jax.default_backend() != "cpu":
            self.skipTest("pinned on the CPU")
        record, last, logp, legal = self._pinned()
        env, seat = record["env"], record["seat"]
        self.assertEqual((env, seat, record["own_pairs"], record["foe_pairs"]), PINNED_DECISION)
        for p, k in ((seat, 3), (1 - seat, 3)):  # the candidates stand far above rounding: an exact pin is safe
            ranked = np.sort(logp[env, p][legal[env, p]])[::-1][:k + 1].astype(np.float64)
            self.assertGreater(np.min(-np.diff(ranked)), 1e-5)
        keys = np.zeros(ENVS, dtype=np.uint64)
        keys[self.envs] = self.keys
        viewers = np.zeros(ENVS, dtype=np.uint8)
        viewers[env] = seat
        with duoforge.Batch(self.ctx, np.resize(reference_setups([0]), 36), 2, SEED) as again:
            obs, step, enc, res, results = again.expand(self.roots, 4, self.mask, lookahead.SEARCH_SEED, keys, viewers,
                                                        last["root_envs"], last["samples"], last["choices"])
            h = hashlib.sha256()
            for x in (last["choices"], last["samples"], step, enc, results, res["boundary_kind"], obs):
                h.update(np.ascontiguousarray(x).tobytes())
        np.testing.assert_array_equal(step, last["step_statuses"])
        self.assertEqual(h.hexdigest(), PINNED_LEAVES)
        self.assertEqual(record["leaves"], {"refused": 0, "terminal": 0, "cut_off": 0, "unresolved": 0,
                                            "TURN": 24, "REPLACEMENT": 12, "PIVOT": 0, "TERMINAL": 0})
        np.testing.assert_allclose(record["table"], PINNED_TABLE, rtol=0, atol=TABLE_TOLERANCE)
        # Row 2 dominates the others by about 1e-4 in every column: the strategy and the choice are exact.
        self.assertEqual((record["x"], record["choice"]), ([0.0, 0.0, 1.0], 99))

    def test_pinned_table_bytes(self):
        # The table's bytes exactly, only under the conditions they were computed in (spec section 6).
        import jax
        conditions = _conditions()
        if conditions != PINNED_TABLE_CONDITIONS:
            self.skipTest(f"the table's bytes are pinned under {PINNED_TABLE_CONDITIONS}, here {conditions}")
        record = self._pinned()[0]
        digest = hashlib.sha256(np.array(record["table"], dtype=np.float64).tobytes()).hexdigest()
        self.assertEqual(digest, PINNED_TABLE_SHA256, f"table {record['table']} under {conditions}")

    def test_encoder_probe_refuses_at_init(self):
        with self.assertRaises(ValueError):  # no mask of the feature bits
            self._lookahead(capacity=4).__init__(self.ctx, self.model, self.params, 4, 1 << 43)
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
        self.assertEqual((data["initstate"], data["initseq"]),
                         duoforge.search_seeds(lookahead.SEARCH_SEED, key, sample))
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
            mask = int(roots.observe_ext()[0, 0]["supported"]) & features.version_features(4)  # encoder 4 (0050)
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

    def test_mixed_round_equals_each_decision_alone(self):
        # Team selections between the searched decisions (the searched index differs from the decision's) and
        # both seats: every searched decision equals itself decided alone, and a leaf of a seat-0 and of a
        # seat-1 decision is valued from its seat's side.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, np.resize(reference_setups([0, 1, 2, 3]), ENVS), 2, SEED) as roots, \
                duoforge.Batch(ctx, reference_setups([0]), 1, SEED) as one:
            policy = duoforge.RandomPolicy(SEED, ENVS)
            for _ in range(4):
                roots.query_factored()
                roots.step_factored(policy.choose_factored(roots))
                roots.reset_terminal()
            for e in (2, 7, 11):
                roots.reset(e, 2)  # back at team selection
            roots.query_factored()
            mask = int(roots.observe_ext()[0, 0]["supported"]) & features.version_features(4)  # encoder 4 (0050)
            every = np.arange(ENVS)
            seats = every % 2
            asked = roots.requests["requested"][every, seats] != 0
            envs, seats = every[asked], seats[asked]
            keys = _keys(roots, envs, seats)
            with lookahead.Lookahead(ctx, self.model, self.params, 4, mask, k=3, m=3, s=4, capacity=256,
                                     workers=2) as look:
                _, records = look.decide(roots, envs, seats, keys, np.zeros(envs.size, bool))
                last = look.last
                searched = [d for d, r in enumerate(records) if r["kind"] == "searched"]
                self.assertIn("team", {r["kind"] for r in records})
                self.assertNotEqual(searched, list(range(len(searched))))
                self.assertEqual({records[d]["seat"] for d in searched}, {0, 1})
                root_keys = np.zeros(ENVS, dtype=np.uint64)
                root_keys[envs] = keys
                for seat in (0, 1):
                    q = next(q for q, d in enumerate(searched) if records[d]["seat"] == seat)
                    x = int(np.flatnonzero((last["decision"] == q) & (last["step_statuses"] == 0)
                                           & (last["leaf_results"] == 0))[0])
                    viewers = np.zeros(ENVS, dtype=np.uint8)
                    viewers[int(last["root_envs"][x])] = seat
                    obs = one.expand(roots, 4, mask, lookahead.SEARCH_SEED, root_keys, viewers,
                                     last["root_envs"][x:x + 1], last["samples"][x:x + 1],
                                     last["choices"][x:x + 1])[0]
                    rows = np.zeros((256, obs.shape[1]), dtype=np.float32)
                    rows[0] = obs[0]
                    self.assertEqual(np.asarray(self.model.value(self.params, rows))[0], last["values"][x])
                for d in searched:
                    _, (alone,) = look.decide(roots, envs[d:d + 1], seats[d:d + 1], keys[d:d + 1], [False])
                    np.testing.assert_array_equal(alone["table"], records[d]["table"])
                    self.assertEqual(alone["choice"], records[d]["choice"])

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


class ArenaSearch(unittest.TestCase):
    """SearchPlayer in play_suite (plan task 10), over Teams A, B and C."""

    @classmethod
    def setUpClass(cls):
        from duoforge import teams
        from duoforge_learn import evaluate, suite
        cls.evaluate = evaluate
        cls.model, cls.params = _v2s()
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.pool = teams.load(cls.ctx, ["A", "B", "C"])
        cls.rows = suite.make_suite(3, SEED, games=2)[:32]
        with duoforge.Batch(cls.ctx, reference_setups([0]), 1, SEED) as b:
            cls.mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)  # encoder 4 (0050)
        cls.raw = evaluate.Player(cls.model, cls.params, 4, "R", ext_supported=cls.mask)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def _searcher(self, **change):
        args = dict(k=1, m=2, s=2, capacity=128, workers=2)
        args.update(change)
        look = lookahead.Lookahead(self.ctx, self.model, self.params, 4, self.mask, **args)
        return look, arena.SearchPlayer(look, "N", ARENA_SEED)

    def _play(self, learner, max_steps, rows=None):
        rows = self.rows if rows is None else rows
        return self.evaluate.play_suite(self.ctx, self.pool, rows, learner, self.raw, 2, ARENA_SEED,
                                        max_steps=max_steps)

    def test_play_suite_passes_step_and_seats(self):
        seen = []
        player = self.evaluate.Player

        class Recording(player):
            def indices(inner, batch, choices, step=None, seats=None, last_step=None):
                seen.append((inner.name, step, seats.copy(), last_step))
                return super().indices(batch, choices, step, seats, last_step)

        rows = self.rows[:8]
        learner = Recording(self.model, self.params, 4, "learner", ext_supported=self.mask)
        opponent = Recording(self.model, self.params, 4, "opponent", ext_supported=self.mask)
        records = self.evaluate.play_suite(self.ctx, self.pool, rows, learner, opponent, 2, ARENA_SEED, max_steps=4)
        np.testing.assert_array_equal(records, self._play(self.raw, 4, rows))  # the keywords change no game
        seat = rows["learner_seat"].astype(np.int64)
        steps = [step for name, step, _, _ in seen if name == "opponent"]
        self.assertEqual(steps, list(range(len(steps))))
        self.assertGreater(len(steps), 1)
        for name, step, seats, last_step in seen:
            want = seat if name == "learner" else 1 - seat
            ok = seats >= 0
            self.assertTrue(ok.any())
            np.testing.assert_array_equal(seats[ok], want[ok])
            self.assertEqual(last_step, step == 3)
        with self.assertRaises(ValueError):  # a searcher cannot play without them
            arena.SearchPlayer(None, "N", ARENA_SEED).indices(None, None)

    def test_k1_reproduces_the_raw_network(self):
        # Plan Review Focus 4: K = 1 plays the raw network's argmax, so N against R is R against R, record for record.
        look, searcher = self._searcher()
        raw, compared = self.raw, []

        class Twin:  # the searcher, its indices compared with the raw network's at every step
            def indices(inner, batch, choices, step=None, seats=None, last_step=None):
                mine = searcher.indices(batch, choices, step, seats, last_step)
                theirs = raw.indices(batch, np.zeros_like(choices), step, seats, last_step)
                e = np.flatnonzero(seats >= 0)
                e = e[batch.requests["requested"][e, seats[e]] != 0]
                np.testing.assert_array_equal(mine[e, seats[e]], theirs[e, seats[e]])
                compared.append(e.size)
                return mine

        with look:
            mine = self._play(Twin(), 30)
        np.testing.assert_array_equal(mine, self._play(self.raw, 30))
        self.assertGreater(sum(compared), 100)
        records = [r for game in searcher.records.values() for r in game]
        self.assertEqual({r["kind"] for r in records} >= {"team", "searched"}, True)
        self.assertTrue(all(r["k"] == 1 for r in records if r["kind"] == "searched"))
        self.assertEqual(sorted(searcher.records), sorted({r["env"] for r in records}))
        for r in records:  # every game at episode 1 of play_suite's batch
            key = seeds.decision_keys(ARENA_SEED, [r["env"]], [1], [r["epoch"]], [r["seat"]])
            self.assertEqual(r["key"], int(key[0]))

    def test_last_step_leaves_use_the_tiebreak(self):
        # Plan Review Focus 3: at the arena's last step every leaf that is neither refused nor TERMINAL is scored
        # by the tiebreak, at no other step; the step is the arena loop's own.
        look, searcher = self._searcher(k=2)
        with look:
            self._play(searcher, 3)
        searched = [r for game in searcher.records.values() for r in game if r["kind"] == "searched"]
        self.assertTrue(any(r["step"] == 2 for r in searched) and any(r["step"] < 2 for r in searched))
        for r in searched:
            leaves = r["leaves"]
            open_leaves = r["k"] * r["m"] * r["s"] - leaves["refused"] - leaves["terminal"]
            self.assertEqual(r["last_step"], r["step"] == 2)
            self.assertEqual(leaves["cut_off"], open_leaves if r["step"] == 2 else 0)


class ArenaCli(unittest.TestCase):
    """The measurement CLI (plan task 11) end to end: a run directory with tiny v2-S checkpoints of Teams A, B
    and C under POOL, its ladder file, two sample counts against R and the panel."""

    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge import teams
        from duoforge_learn import checkpoint, policy
        cls.tmp = tempfile.TemporaryDirectory()
        cls.run_dir = os.path.join(cls.tmp.name, "night")
        os.makedirs(cls.run_dir)
        cfg = policy.v2_config("S", hidden=64)
        params = jax.device_get(policy.make(cfg).init(jax.random.PRNGKey(7)))
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = teams.load(ctx, ["A", "B", "C"])
            with duoforge.Batch(ctx, reference_setups([0]), 1, SEED) as b:
                mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(features.ENCODER)
            config = {"model": cfg, "encoder": features.ENCODER, "ext_supported": mask,
                      "ids": checkpoint.ids_of(ctx), "features": list(features.FEATURE_NAMES),
                      "slot_features": list(features.SLOT_FEATURE_NAMES),
                      "data": {"kind": "pool", "fingerprint": ctx.fingerprint().hex()},
                      "teams": {"ids": list(pool.ids), "sha256": list(pool.sha256), "weights": [1.0] * 3},
                      "decisions": 0, "train": {"seed": 1}}
        for u in (0, 100, 200, 300, 400):
            checkpoint.save(os.path.join(cls.run_dir, f"params-{u}.npz"), params, dict(config, update=u))
        with open(os.path.join(cls.run_dir, "ladder.json"), "w", encoding="utf-8") as f:
            json.dump({"players": [{"player": "init", "elo": 0.0}, {"player": "night update 200", "elo": 12.0},
                                   {"player": "night update 400", "elo": 3.0}]}, f)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _main(self, out, *extra):
        common = ["--run-dir", self.run_dir, "--out", out, "--games", "16", "--km", "2x2", "--capacity", "64",
                  "--workers", "2", "--resamples", "50"]
        self.assertEqual(arena.main(common + list(extra)), 0)
        with open(os.path.join(out, "summary.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_cli_smoke(self):
        import jax
        out = os.path.join(self.tmp.name, "smoke")
        summary = self._main(out, "--opponents", "raw,panel", "--s", "2,4", "--max-steps", "6")
        opponents = ("R", "P25", "P50", "P75")
        searched = {f"{a}-k2m2s{s}-vs-{o}" for a in "NE" for s in (2, 4) for o in opponents}
        self.assertEqual(set(summary["configs"]), searched | {f"R-vs-{o}" for o in opponents})
        for name, c in summary["configs"].items():
            self.assertTrue(os.path.isfile(os.path.join(out, "raw", f"{name}-games.csv")), name)
            self.assertEqual(c["games"], 36)  # the complete suite of three teams
            if name in searched:
                self.assertEqual(c["s"], int(name.split("s")[1].split("-")[0]))
                self.assertIn("paired_vs_R", c)
                self.assertGreater(c["diagnostics"]["decisions"]["searched"], 0)
                with open(os.path.join(out, "raw", f"{name}-decisions.jsonl"), encoding="utf-8") as f:
                    decisions = [json.loads(line) for line in f]
                self.assertTrue(all(r["s"] == c["s"] for r in decisions if r["kind"] == "searched"))
                with open(os.path.join(out, "raw", f"{name}-timing.json"), encoding="utf-8") as f:
                    self.assertGreater(json.load(f)["searched"], 0)
        cond = summary["conditions"]
        self.assertEqual((cond["capacity"], cond["s"], cond["km"], cond["workers"], cond["max_steps"]),
                         (64, [2, 4], ["2x2"], 2, 6))
        self.assertEqual(cond["checkpoint"]["update"], 200)  # the best by the run's ladder file
        with open(os.path.join(self.run_dir, "params-200.npz"), "rb") as f:
            self.assertEqual(cond["checkpoint"]["sha256"], hashlib.sha256(f.read()).hexdigest())
        self.assertEqual([p["update"] for p in cond["panel"]], [100, 200, 300])
        self.assertEqual(cond["pool"]["ids"], ["A", "B", "C"])
        self.assertEqual((cond["jax"], cond["backend"], cond["library"]),
                         (jax.__version__, jax.default_backend(), duoforge.version()))
        for key in ("search_seed", "arena_seed", "bootstrap_seed", "devices", "cpu", "xla_flags", "commit", "oracle"):
            self.assertIn(key, cond)

    def test_cli_named_checkpoint(self):
        out = os.path.join(self.tmp.name, "named")
        summary = self._main(out, "--checkpoint", "params-400", "--agents", "N", "--s", "2", "--max-steps", "3")
        self.assertEqual(set(summary["configs"]), {"R-vs-R", "N-k2m2s2-vs-R"})
        self.assertEqual(summary["conditions"]["checkpoint"]["update"], 400)
        repository = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for bad in (["--agents", "Z"], ["--search", "unknown"], ["--lam", "-0.1"], ["--lam", "1.1"],
                    ["--km", "8"], ["--s", "0"], ["--s", "16,x"], ["--checkpoint", "params-18129"],
                    ["--out", os.path.join(repository, "arena-out")]):
            with self.assertRaises(SystemExit):
                arena.main(["--run-dir", self.run_dir, "--out", out] + bad)

    def test_cli_scripted_opponent(self):
        # --opponents scripted plays evaluate's ScriptedPolicy as opponent S: R-vs-S as the baseline and each
        # searched agent against it; the conditions say so, and raw and panel runs keep their conditions as before.
        out = os.path.join(self.tmp.name, "scripted")
        summary = self._main(out, "--checkpoint", "params-400", "--agents", "N", "--s", "2", "--max-steps", "3",
                             "--opponents", "raw,scripted")
        self.assertEqual(set(summary["configs"]), {"R-vs-R", "N-k2m2s2-vs-R", "R-vs-S", "N-k2m2s2-vs-S"})
        self.assertIs(summary["conditions"]["scripted"], True)
        self.assertEqual(summary["conditions"]["panel"], [])
        self.assertIn("paired_vs_R", summary["configs"]["N-k2m2s2-vs-S"])
        raw_only = self._main(os.path.join(self.tmp.name, "raw-only"), "--checkpoint", "params-400", "--agents", "N",
                              "--s", "2", "--max-steps", "3")
        self.assertNotIn("scripted", raw_only["conditions"])
        with self.assertRaises(SystemExit):
            arena.main(["--run-dir", self.run_dir, "--out", out, "--opponents", "random"])


# Mixed strategies of the LookaheadDecisions round (3 x 3 x 4, capacity 256): environment -> (the play draw u,
# a pure function of the key, and the row it plays). u lies more than 1e-3 from every boundary of the strategy.
PINNED_DRAWS = {12: (0.18192116786271728, 1), 13: (0.9505990374064887, 2)}

# The pinned decision: environment 0, seat 0 of the LookaheadDecisions round (3 x 3 x 4 leaves, capacity 256)
# at v2-S init key 7, on the CPU. On every machine: (env, seat, own pairs, foe pairs), the SHA-256 of the
# leaves' choices, samples, statuses, results, boundaries and C-encoded rows, and the table within the tolerance.
PINNED_DECISION = (0, 0, [98, 101, 99], [261, 37, 267])
PINNED_LEAVES = "5747ca7089aaaf9c7fd650eaddc04f313fefba9c4a7cc70efb80aa14521c3473"
PINNED_TABLE = [[-0.001045780023559928, -0.0011911392211914062, -0.001594386762008071],
                [-0.0011191614903509617, -0.0012734043411910534, -0.0009843618609011173],
                [-0.0006289742887020111, -0.0006185907404869795, -4.029273986816406e-05]]
TABLE_TOLERANCE = 1e-6
# The table's float64 bytes, exact only under these conditions: the network's float32 values differ in the
# last bits by instruction set and batch shape (spec section 6). Measured: the same under
# --xla_cpu_max_isa=AVX2 and AVX512 on this CPU, another value under AVX.
PINNED_TABLE_SHA256 = "56b79262081bb7e9ec52d18ac29634f515041459e065f0192ea14533103eb7ee"
PINNED_TABLE_CONDITIONS = {"jax": "0.11.2", "cpu": "Intel(R) Xeon(R) Processor @ 2.10GHz", "xla_flags": "",
                           "capacity": 256}


def _conditions():
    """The conditions a table's bytes depend on beyond the seeds: the JAX version, the CPU model, the XLA flags
    and the leaf capacity (the pinned decision's: 256)."""
    import platform

    import jax
    cpu = platform.processor()
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            cpu = next(line.split(":", 1)[1].strip() for line in f if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    return {"jax": jax.__version__, "cpu": cpu, "xla_flags": os.environ.get("XLA_FLAGS", ""), "capacity": 256}


if __name__ == "__main__":
    unittest.main()
