"""The two-turn tree in the honest search (D2 of the depth search; plan docs/superpowers/plans/2026-10-14-depth-search-
d2.md step 4): its settings and their refusals, and the tree whose every depth-1 node is a leaf deciding exactly as D1.
"""
import os
os.environ["JAX_PLATFORMS"] = "cpu"

import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_search import SearchError, belief, honest, infokey, matrix
from python.tests.search.digest_stub import StubDigest
from python.tests.search.test_search import _v2s

C = _layout.CONSTANTS
# The fields only a depth-2 record has (plan step 8).
DEPTH_FIELDS = ("depth", "tree")


def timeless(records, drop=()):
    return [{k: v for k, v in r.items() if k not in ("cost", "time") + tuple(drop)} for r in records]


class Depth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.params = _v2s()

    def make(self, ctx, table=None, excluded=None, s=2, **settings):
        table = table or belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
        with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)
        return honest.Honest(ctx, self.model, self.params, 4, mask, k=2, m=2, s=s, capacity=16, workers=2,
                             table=table, exclude_teams=excluded, **settings)

    def abc_turn(self, ctx, last_step=False, steps_left=None, **settings):
        """The A/B/C turn decisions (test_honest's pinned positions) under settings: (actions, records)."""
        pool = duoforge.teams.load(ctx, ["A", "B", "C"])
        table = belief.SpreadTable.from_sides(pool.sides)
        with duoforge.Batch(ctx, pool.setups(np.array([0, 1, 2]), np.array([1, 2, 0])), 2, 42) as roots, \
                self.make(ctx, table=table, excluded=[1, 2, 0], **settings) as search:
            # depth 2 asks every decide for steps_left (decision 2): the preview runs without a step limit
            preview = {} if steps_left is None else {"steps_left": [honest.NO_STEP_LIMIT] * 3}
            search.decide(roots, [0, 1, 2], [0, 0, 0], [123] * 3, [False] * 3, **preview)
            roots.query_factored()
            choices = np.zeros((3, 2), _layout.FACTORED_CHOICE)
            choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
            roots.step_factored(choices)
            roots.query_factored()
            extra = {} if steps_left is None else {"steps_left": [steps_left] * 3}
            return search.decide(roots, [0, 1, 2], [0, 0, 0], [456, 457, 458], [last_step] * 3, **extra)


class Settings(Depth):
    def test_the_default_is_depth_one_without_a_node_batch(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, self.make(ctx) as search:
            self.assertEqual(search.depth, 1)
            self.assertIsNone(search.nodes)

    def test_depth_two_builds_its_node_batch(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                self.make(ctx, depth=2, root_solver="rm", info_key="record") as search:
            self.assertEqual(search.nodes.envs, search.s * search.k * search.m)
            self.assertEqual((search.k2, search.m2, search.chance, search.foe_below), (2, 2, 1, "nash"))
            self.assertEqual((search.info_key, search.evaluator.name), ("record", "jax"))

    def test_refused_settings(self):
        rm = {"root_solver": "rm", "info_key": "record"}
        bad = [({"depth": 3}, ValueError, "depth"),
               ({"depth": 2, "info_key": "record"}, ValueError, "root_solver 'rm'"),
               ({"k2": 2}, ValueError, "depth 2"), ({"info_key": "record"}, ValueError, "depth 2"),
               ({"evaluator": "jax"}, ValueError, "depth 2"), ({"foe_below": "nash"}, ValueError, "depth 2"),
               ({"tree_iterations": 10}, ValueError, "depth 2"), ({"chance": 1}, ValueError, "depth 2"),
               ({"depth": 2, **rm, "k2": 0}, ValueError, "k2"), ({"depth": 2, **rm, "m2": 1.5}, ValueError, "m2"),
               ({"depth": 2, **rm, "chance": 2}, ValueError, "chance"),
               ({"depth": 2, **rm, "foe_below": "greedy"}, ValueError, "foe_below"),
               ({"depth": 2, **rm, "tree_iterations": 0}, ValueError, "tree_iterations"),
               ({"depth": 2, "root_solver": "rm"}, SearchError, "^observation_digest_unavailable"),
               ({"depth": 2, **rm, "evaluator": "engine"}, SearchError, "^evaluator_engine_unavailable")]
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            for settings, error, pattern in bad:
                with self.subTest(settings=settings), self.assertRaisesRegex(error, pattern):
                    self.make(ctx, **settings).close()


class TheDefault(Depth):
    def test_the_default_and_depth_one_decide_as_on_main(self):
        # D2 adds depth (and steps_left). Without them, with depth 1 named and with steps_left given, the A/B/C turn
        # decisions are main's: the pinned choices and tables (test_honest), one record for all, no field of D2.
        from python.tests.search.test_honest import PINNED_TABLES
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            runs = [self.abc_turn(ctx), self.abc_turn(ctx, depth=1), self.abc_turn(ctx, steps_left=UNLIMITED)]
        for actions, records in runs:
            self.assertEqual(actions.tolist(), [103, 289, 352])
            for i, r in enumerate(records):
                for name in DEPTH_FIELDS:
                    self.assertNotIn(name, r)
                np.testing.assert_allclose(r["tables"], PINNED_TABLES[i], rtol=0, atol=1e-6)
        self.assertEqual(timeless(runs[0][1]), timeless(runs[1][1]))
        self.assertEqual(timeless(runs[0][1]), timeless(runs[2][1]))


class DegenerateTreeIsD1(Depth):
    def test_at_the_cut_off_depth_two_decides_as_d1(self):
        # The root's step is the arena's last: every depth-1 node is cut off, a leaf of the tree, so the tree is D1's
        # Bayes game and the decision is D1's bit for bit (plan step 4; spec section 8 "D2 in detail").
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            d1_actions, d1 = self.abc_turn(ctx, last_step=True, root_solver="rm")
            d2_actions, d2 = self.abc_turn(ctx, last_step=True, steps_left=1, root_solver="rm", depth=2,
                                           info_key="record")
        self.assertEqual(d2_actions.tolist(), d1_actions.tolist())
        for r in d1:
            self.assertEqual(r["kind"], "searched")
            self.assertGreater(r["leaves"]["cut_off"], 0)
        self.assertEqual(timeless(d2, DEPTH_FIELDS), timeless(d1))
        for r in d2:
            self.assertEqual(r["depth"], {"depth": 2, "k2": 2, "m2": 2, "chance": 1, "info_key": "record",
                                          "evaluator": "jax", "foe_below": "nash",
                                          "max_iterations": honest.tree.TREE_MAX_ITERATIONS,
                                          "epsilon": matrix.RM_EPSILON})
            self.assertEqual(r["tree"]["nodes"], 0)  # every root edge is a leaf
            self.assertEqual(r["tree"]["information_sets"], 0)


DEPTH2 = {"root_solver": "rm", "depth": 2, "info_key": "record"}
UNLIMITED = honest.NO_STEP_LIMIT


def searched(case, records):
    """The indices of the searched records. The record key (tests only) has no key for a depth-1 node whose public
    record the engine refuses (A/B/C position 2 has one): that decision is the named observation_key_refused, every
    other kind fails the test; the engine digest (step 9) keys every node."""
    out = []
    for x, r in enumerate(records):
        if r["kind"] == "searched":
            out.append(x)
        else:
            case.assertEqual((r["kind"], r["reason"]), ("unreconstructible", "observation_key_refused"))
    case.assertGreaterEqual(len(out), 2)
    return out


class StubObservationKey:
    """Stands in for the engine's observation digest of D2 (Q3) until the extension lands: the key of a depth-1 node is
    its root cell (i, j), so the nodes of one cell merge across the worlds. It tests the tree's handling of keys, never
    the engine's observation; the record key and, later, the digest replace it."""
    name = "stub"

    def __init__(self, s):
        self.s = s

    def keys(self, nodes, envs, viewer, closed):
        envs = np.asarray(envs, dtype=np.int64)
        out = np.zeros((envs.size, 32), np.uint8)
        out[:, :8] = (envs // self.s).astype("<u8").view(np.uint8).reshape(-1, 8)  # node env = (i * m + j) * s + w
        return out, np.zeros(envs.size, bool)


class TwoTurns(Depth):
    def test_the_tree_searches_the_next_turn(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            actions, records = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
        for x in searched(self, records):
            action, r = int(actions[x]), records[x]
            self.assertEqual(action, r["choice"])
            self.assertIn(r["choice"], r["own_pairs"])
            t = r["tree"]
            self.assertGreater(t["nodes"], 0)
            self.assertGreater(t["information_sets"], 0)
            self.assertLessEqual(t["information_sets"], t["nodes"])
            self.assertTrue(0.0 <= t["merge_share"] <= 1.0)
            self.assertLessEqual(t["gap"], matrix.RM_EPSILON)
            self.assertGreater(t["iterations"], 0)
            self.assertGreater(t["leaves"]["open"], 0)
            self.assertEqual(t["leaves"]["cut_off"], 0)  # no step limit: no depth-2 leaf is cut off
            self.assertEqual(np.shape(r["tables"]), (2, r["k"], r["m"]))

    def test_every_decision_computed_twice_is_the_same(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            first = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
            second = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
        self.assertEqual(first[0].tolist(), second[0].tolist())
        self.assertEqual(timeless(first[1]), timeless(second[1]))

    def test_lambda_zero_plays_the_best_answer_on_the_root_tables(self):
        # The root rule of spec section 5, unchanged at depth 2: rule ev (λ = 0 of #486) and mix with λ = 0 play the
        # row with the highest expected value of the root tables under the foe model (ties to the prior's order).
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            runs = [self.abc_turn(ctx, steps_left=UNLIMITED, rule=rule, lam=lam, **DEPTH2)
                    for rule, lam in (("ev", 0.5), ("mix", 0.0))]
        for actions, records in runs:
            for x in searched(self, records):
                action, r = int(actions[x]), records[x]
                expected = matrix.bayes_expected_values(r["tables"], r["weights"], r["foe_probs"])
                best = np.flatnonzero(expected == expected.max())
                self.assertEqual(r["outcomes"]["ev"], int(best[0]))
                self.assertEqual(action, r["own_pairs"][r["outcomes"]["ev"]])

    def test_two_steps_left_cut_the_depth_two_leaves_off(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            _, records = self.abc_turn(ctx, steps_left=2, **DEPTH2)
        for x in searched(self, records):
            leaves = records[x]["tree"]["leaves"]
            self.assertGreater(leaves["cut_off"], 0)
            self.assertEqual(leaves["open"], 0)  # every stepped, non-terminal depth-2 leaf takes the tiebreak

    def test_steps_left_is_required_at_depth_two_and_must_agree(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            with self.assertRaisesRegex(ValueError, "steps_left"):
                self.abc_turn(ctx, **DEPTH2)  # None is refused, never a silent default (decision 2)
            for last_step, left in ((True, 5), (False, 1), (True, UNLIMITED), (False, 0)):
                with self.subTest(last_step=last_step, left=left), self.assertRaisesRegex(ValueError, "steps_left"):
                    self.abc_turn(ctx, last_step=last_step, steps_left=left, **DEPTH2)

    def test_a_stub_key_merges_a_root_cell_across_the_worlds(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = duoforge.teams.load(ctx, ["A", "B", "C"])
            table = belief.SpreadTable.from_sides(pool.sides)
            with duoforge.Batch(ctx, pool.setups(np.array([0, 1, 2]), np.array([1, 2, 0])), 2, 42) as roots, \
                    self.make(ctx, table=table, excluded=[1, 2, 0], **DEPTH2) as search:
                search._keys = StubObservationKey(search.s)
                search.decide(roots, [0, 1, 2], [0, 0, 0], [123] * 3, [False] * 3, steps_left=[UNLIMITED] * 3)
                roots.query_factored()
                choices = np.zeros((3, 2), _layout.FACTORED_CHOICE)
                choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
                roots.step_factored(choices)
                roots.query_factored()
                _, records = search.decide(roots, [0], [0], [456], [False], steps_left=[UNLIMITED])
                last = search.last[-1]["tree"]
        r = records[0]
        self.assertEqual(r["kind"], "searched")
        cells = last["cells"]  # (w, i, j) of every depth-1 node
        sets = last["sets"]  # our information set of every node, -1 where we are not requested
        for x in range(len(sets)):
            for y in range(len(sets)):
                if sets[x] >= 0 and sets[y] >= 0:
                    self.assertEqual(sets[x] == sets[y], tuple(cells[x][1:]) == tuple(cells[y][1:]))
        self.assertGreater(r["tree"]["merge_share"], 0.0)
        self.assertEqual(len(last["own"]), r["tree"]["information_sets"])  # one strategy per set

    def test_the_evaluator_is_swapped_without_touching_the_tree(self):
        # D4's hook (#485): whatever implements leaves() values the depth-2 leaves; the tree code is the same.
        calls = []

        class Shifted:
            name = "jax"

            def __init__(self, inner):
                self.inner = inner

            def leaves(self, *args, **kwargs):
                got = self.inner.leaves(*args, **kwargs)
                calls.append(got.values.size)
                return got._replace(values=np.clip(got.values - np.float32(0.25), -1, 1).astype(np.float32))

        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            _, plain = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
            with mock.patch.object(honest.evaluators, "make",
                                            side_effect=lambda name, **o: Shifted(honest.evaluators.JaxEvaluator(**o))):
                _, shifted = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
        done = searched(self, plain)
        self.assertEqual(len(calls), len(done))  # one leaf phase per searched decision
        for a, b in ((plain[x], shifted[x]) for x in done):
            self.assertEqual(b["kind"], "searched")
            self.assertEqual((a["own_pairs"], a["foe_pairs"]), (b["own_pairs"], b["foe_pairs"]))
            self.assertNotEqual(a["tables"], b["tables"])

    def refusing(self, refuse):
        """A patch of evaluators.make whose evaluator marks the depth-2 leaves refuse(choices) selects as refused
        (E_UNSUPPORTED), as C reports a refused step."""
        class Refusing:
            name = "jax"

            def __init__(self, inner):
                self.inner = inner

            def leaves(self, source, seed, keys, viewers, root_envs, samples, choices, cut, costs=None):
                got = self.inner.leaves(source, seed, keys, viewers, root_envs, samples, choices, cut, costs)
                step = got.step.copy()
                step[refuse(np.asarray(root_envs), choices)] = C["DUOFORGE_E_UNSUPPORTED"]
                return got._replace(step=step)

        return mock.patch.object(honest.evaluators, "make",
                                          side_effect=lambda name, **o: Refusing(honest.evaluators.JaxEvaluator(**o)))

    def test_refused_depth_two_leaves_are_named(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            _, base = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
            # Every depth-2 leaf below root row 0 (node env < m * s) refused: row 0 leaves the solve, named.
            with self.refusing(lambda envs, choices: envs < 2 * 2):
                _, part = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
            with self.refusing(lambda envs, choices: np.ones(envs.size, bool)):
                actions, every = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
        for b, p in ((base[x], part[x]) for x in searched(self, base)):
            self.assertEqual(p["kind"], "searched")
            self.assertEqual(p["refused_pairs"], [b["own_pairs"][0]])
            self.assertEqual(p["own_pairs"], b["own_pairs"][1:])
            self.assertGreater(p["tree"]["leaves"]["refused"], 0)
        for x in searched(self, base):
            action, b, r = int(actions[x]), base[x], every[x]
            self.assertEqual((r["kind"], r["reason"], r["causes"]),
                             ("unreconstructible", "engine_refused_leaves", ["engine_refused_leaves"]))
            self.assertEqual(action, b["raw"])  # played raw and counted, as at depth 1


class StubDigestKeyed(Depth):
    """info_key "digest" wired through the honest search against the PROVISIONAL STUB of the engine call (digest_stub,
    decision 0082): the node batch is expanded by the digest call and keyed from its sidecar. The stub's digest folds
    the viewer's public record, so it must decide exactly as the record key; it tests the wiring, never the engine's
    digest."""

    def stubbed(self, stub):
        return mock.patch.object(infokey, "_library_digest_call", return_value=stub)

    def test_depth_two_defaults_to_the_digest_key(self):
        stub = StubDigest()
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, self.stubbed(stub), \
                self.make(ctx, depth=2, root_solver="rm") as search:
            self.assertEqual(search.info_key, "digest")
            self.assertIsInstance(search.nodes, infokey.DigestNodes)
            self.assertEqual(search.nodes.batch.envs, search.s * search.k * search.m)

    def test_the_stub_digest_decides_as_the_record_key(self):
        stub = StubDigest()
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            record = self.abc_turn(ctx, steps_left=UNLIMITED, **DEPTH2)
            with self.stubbed(stub):
                digest = self.abc_turn(ctx, steps_left=UNLIMITED, **{**DEPTH2, "info_key": "digest"})
        self.assertGreater(len(stub.calls), 0)
        self.assertEqual(digest[0].tolist(), record[0].tolist())
        searched(self, record[1])
        for d, r in zip(digest[1], record[1]):
            if "depth" in r:
                self.assertEqual(d["depth"], {**r["depth"], "info_key": "digest"})
        self.assertEqual(timeless(digest[1], ("depth",)), timeless(record[1], ("depth",)))

    def test_a_refused_digest_is_the_named_fallback(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, self.stubbed(StubDigest(refuse=range(1 << 16))):
            _, records = self.abc_turn(ctx, steps_left=UNLIMITED, **{**DEPTH2, "info_key": "digest"})
        for r in records:
            self.assertEqual((r["kind"], r["reason"]), ("unreconstructible", "observation_key_refused"))


class WorldPolicies(Depth):
    def test_world_policies_are_the_root_worlds_policy_after_the_tree(self):
        # Honest.world_policies (#499) at depth 2: the worlds it reads are the root's, as the root _prepare read them,
        # after the whole tree decision. The depth-1 nodes live in their own batch; their phase queries no world and
        # builds none, so the root _prepare is the decision's only query of the worlds.
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool = duoforge.teams.load(ctx, ["A", "B", "C"])
            table = belief.SpreadTable.from_sides(pool.sides)
            with duoforge.Batch(ctx, pool.setups(np.array([0, 1, 2]), np.array([1, 2, 0])), 2, 42) as roots, \
                    self.make(ctx, table=table, excluded=[1, 2, 0], **DEPTH2) as search:
                search.decide(roots, [0, 1, 2], [0, 0, 0], [123] * 3, [False] * 3, steps_left=[UNLIMITED] * 3)
                roots.query_factored()
                choices = np.zeros((3, 2), _layout.FACTORED_CHOICE)
                choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
                roots.step_factored(choices)
                roots.query_factored()
                inside, seen = [False], []
                real_policy, real_prepare = search._world_policy, search._prepare

                def policy():
                    out = real_policy()
                    if inside[0]:
                        seen.append((np.array(out[0], copy=True), np.array(out[3], copy=True)))
                    return out

                def prepare(*args, **kwargs):
                    inside[0] = True
                    try:
                        return real_prepare(*args, **kwargs)
                    finally:
                        inside[0] = False

                with mock.patch.object(search, "_world_policy", policy), mock.patch.object(search, "_prepare", prepare):
                    _, records = search.decide(roots, [0], [0], [456], [False], steps_left=[UNLIMITED])
                self.assertEqual(records[0]["kind"], "searched")
                self.assertGreater(records[0]["tree"]["nodes"], 0)  # the depth-1 phase ran
                self.assertEqual(len(seen), 1)  # one root, one _prepare, one query of its worlds
                root_pp, root_masks = seen[0]
                for seat in (0, 1):
                    logp, masks = search.world_policies(seat)
                    np.testing.assert_array_equal(logp, root_pp[:, seat])
                    np.testing.assert_array_equal(masks, np.asarray(root_masks[:, seat], bool).reshape(search.s, -1))


if __name__ == "__main__":
    unittest.main()
