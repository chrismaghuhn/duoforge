"""The two-turn tree's solver (D2 of the depth search): tree.solve_tree, CFR+ over the root, our depth-1 information
sets and the foe's depth-1 nodes.

NumPy only. Spec docs/superpowers/specs/2026-10-13-depth-search-design.md sections 3.1, 4.1, 4.4 and 8 "D2 in detail";
plan docs/superpowers/plans/2026-10-14-depth-search-d2.md step 1: a tree without decision nodes is D1 bit for bit; on
tiny games the solution is within epsilon of the exact normal form's; nodes sharing an information set share one
strategy; every node kind; two solves are byte-equal; the iteration bound refuses by name.
"""
import itertools
import json
import unittest
from pathlib import Path

import numpy as np

from duoforge_search import SearchError, matrix, tree

FIXTURES = Path(__file__).resolve().parent.parent / "support" / "fixtures"
SHAPES = ((2, 2, 2), (16, 8, 8), (16, 16, 8), (3, 5, 1), (5, 1, 4))


def _random_game(rng, shape):
    tables = rng.uniform(-1, 1, shape).astype(np.float32).astype(np.float64)
    return tables, rng.random(shape[0]) + 0.1, rng.random(shape[1]) + 0.01, rng.random(shape[::2]) + 0.01


def _leaves_only(tables, weights, k2=2, m2=2):
    """A tree whose every root edge is a leaf (no depth-1 decision node)."""
    w, k, m = np.shape(tables)
    return tree.Tree(weights=np.asarray(weights, np.float64), leaf=np.asarray(tables, np.float64),
                     node=np.full((w, k, m), -1, np.int64), info=np.zeros(0, np.int64), z=np.zeros((0, k2, m2)),
                     own_valid=np.zeros((0, k2), bool), foe_valid=np.zeros((0, m2), bool),
                     own_prior=np.zeros((0, k2)), foe_prior=np.zeros((0, m2)))


def _random_tree(rng, w, k, m, k2, m2, *, share=False, kinds=("both", "ours", "foes")):
    """A random tree: about half the root edges lead to a depth-1 node of a random kind, the rest are leaves. Our
    information set of a node is (root row, key); share=True gives every world the same key for one (i, j), so those
    nodes merge across the worlds, otherwise each node's key is its own."""
    node = np.full((w, k, m), -1, np.int64)
    leaf = rng.uniform(-1, 1, (w, k, m)).astype(np.float32).astype(np.float64)
    decision = rng.random((w, k, m)) < 0.5
    decision[0, 0, 0] = True
    if share:  # edge (0, 0) leads to a "both" node in every world, all of them under one key
        decision[:, 0, 0] = True
    n = int(decision.sum())
    node[decision] = np.arange(n)
    where = np.argwhere(decision)  # (w, i, j) per node, in node order (both C order)
    kind = ["both" if share and (i, j) == (0, 0) else kinds[int(rng.integers(0, len(kinds)))] for _, i, j in where]
    keys, info = {}, np.full(n, -1, np.int64)
    for x, ((wx, i, j), c) in enumerate(zip(where, kind)):
        if c == "foes":
            continue
        key = (int(i), "shared" if share and (i, j) == (0, 0) else (int(wx), int(j)))
        info[x] = keys.setdefault(key, len(keys))
    own_valid = np.zeros((len(keys), k2), bool)
    own_prior = np.zeros((len(keys), k2))
    for key, s in keys.items():
        count = int(rng.integers(1, k2 + 1)) if k2 > 1 else 1
        own_valid[s, :count] = True
        own_prior[s, :count] = rng.random(count) + 0.01
    foe_valid = np.zeros((n, m2), bool)
    foe_prior = np.zeros((n, m2))
    for x, c in enumerate(kind):
        count = 1 if c == "ours" else int(rng.integers(1, m2 + 1))
        foe_valid[x, :count] = True
        foe_prior[x, :count] = rng.random(count) + 0.01
    z = rng.uniform(-1, 1, (n, k2, m2)).astype(np.float32).astype(np.float64)
    return tree.Tree(weights=rng.random(w) + 0.1, leaf=leaf, node=node, info=info, z=z, own_valid=own_valid,
                     foe_valid=foe_valid, own_prior=own_prior, foe_prior=foe_prior)


def _value(t, wx, x, own, y, foe):
    """World wx's expected payoff of our behaviour (root x, own (I, K2)) against the foe's (root y, foe (N, M2))."""
    total = 0.0
    k, m = t.leaf.shape[1:]
    for i in range(k):
        for j in range(m):
            n = int(t.node[wx, i, j])
            if n < 0:
                v = t.leaf[wx, i, j]
            else:
                mine = own[t.info[n]] if t.info[n] >= 0 else np.eye(t.z.shape[1])[0]
                v = float(mine @ t.z[n] @ foe[n])
            total += x[i] * y[j] * v
    return total


def _pure_ours(t):
    """Every pure strategy of ours: (x, own) one-hot behaviours."""
    k = t.leaf.shape[1]
    choices = [np.flatnonzero(row) for row in t.own_valid]
    for i in range(k):
        for picks in itertools.product(*choices):
            own = np.zeros(t.own_valid.shape)
            own[np.arange(len(picks)), list(picks)] = 1.0
            yield np.eye(k)[i], own


def _pure_foe(t, wx):
    """Every pure strategy of world wx's foe: (y, foe) one-hot behaviours (nodes of other worlds play their first)."""
    m = t.leaf.shape[2]
    mine = sorted({int(t.node[wx, i, j]) for i in range(t.leaf.shape[1]) for j in range(m) if t.node[wx, i, j] >= 0})
    for j in range(m):
        for picks in itertools.product(*[np.flatnonzero(t.foe_valid[n]) for n in mine]):
            foe = np.zeros(t.foe_valid.shape)
            foe[:, 0] = 1.0
            for n, b in zip(mine, picks):
                foe[n] = np.eye(t.foe_valid.shape[1])[b]
            yield np.eye(m)[j], foe


class DegenerateTreeIsD1(unittest.TestCase):
    def assert_same(self, tables, weights, prior, foe_priors, **options):
        d1 = matrix.solve_bayes_rm(tables, weights, prior, foe_priors, **options)
        d2 = tree.solve_tree(_leaves_only(tables, weights), prior, foe_priors, **options)
        self.assertEqual(d2.root.solution.x.tobytes(), d1.solution.x.tobytes())
        self.assertEqual([y.tobytes() for y in d2.root.solution.ys], [y.tobytes() for y in d1.solution.ys])
        self.assertEqual((d2.root.solution.value, d2.root.gap, d2.root.iterations),
                         (d1.solution.value, d1.gap, d1.iterations))
        self.assertEqual(d2.tables.tobytes(), np.asarray(tables, np.float64).tobytes())

    def test_random_tables(self):
        rng = np.random.default_rng(482)
        for shape in SHAPES:
            for _ in range(2):
                with self.subTest(shape=shape):
                    self.assert_same(*_random_game(rng, shape))

    def test_epsilon_and_check_every(self):
        rng = np.random.default_rng(9)
        game = _random_game(rng, (16, 8, 8))
        for options in ({"epsilon": 1e-2}, {"epsilon": 1e-4}, {"check_every": 7}):
            with self.subTest(**options):
                self.assert_same(*game, **options)

    def test_the_recorded_arena_tables(self):
        rng = np.random.default_rng(7)
        for name in ("bayes-arena-16x8x8.json", "bayes-arena-16x8x8-tiny-pivot.json"):
            saved = json.loads((FIXTURES / name).read_text())
            tables = np.asarray(saved["tables"], dtype=np.float64)
            with self.subTest(fixture=name):
                self.assert_same(tables, saved["weights"], rng.random(tables.shape[1]) + 0.01,
                                 rng.random(tables.shape[::2]) + 0.01)

    def test_a_constant_table(self):
        self.assert_same(np.full((3, 4, 2), 0.25), np.ones(3), [0.1, 0.2, 0.3, 0.4], np.ones((3, 2)))

    def test_ties_play_the_prior_as_d1(self):
        rng = np.random.default_rng(5)
        row = rng.random((4, 1, 3))
        self.assert_same(np.repeat(row, 3, axis=1), np.ones(4), [0.7, 0.2, 0.1], np.ones((4, 3)))

    def test_the_iteration_bound_refuses_as_d1(self):
        game = _random_game(np.random.default_rng(3), (16, 8, 8))
        with self.assertRaises(matrix.RMUnconverged) as d1:
            matrix.solve_bayes_rm(*game, iterations=3, check_every=10)
        with self.assertRaises(matrix.RMUnconverged) as d2:
            tree.solve_tree(_leaves_only(*game[:2]), *game[2:], iterations=3, check_every=10)
        self.assertEqual((d2.exception.gap, d2.exception.iterations), (d1.exception.gap, d1.exception.iterations))
        self.assertTrue(str(d2.exception).startswith("solver_unconverged"))


class TinyGamesAgainstTheNormalForm(unittest.TestCase):
    """The exact value of tiny trees from their enumerated normal form (matrix.solve_bayes, certified to 1e-9)."""

    def check(self, t, prior, foe_priors, epsilon=matrix.RM_EPSILON):
        solved = tree.solve_tree(t, prior, foe_priors, epsilon=epsilon)
        ours = list(_pure_ours(t))
        foes = [list(_pure_foe(t, wx)) for wx in range(len(t.weights))]
        width = max(len(f) for f in foes)
        normal = np.array([[[_value(t, wx, x, own, *foes[wx][c % len(foes[wx])]) for c in range(width)]
                            for x, own in ours] for wx in range(len(t.weights))])
        exact = matrix.solve_bayes(normal, t.weights)
        p = np.asarray(t.weights) / np.sum(t.weights)
        x, ys, own, foe = solved.root.solution.x, solved.root.solution.ys, solved.own, solved.foe
        guaranteed = sum(p[wx] * min(_value(t, wx, x, own, y, f) for y, f in foes[wx]) for wx in range(len(p)))
        best = max(sum(p[wx] * _value(t, wx, xo, oo, ys[wx], foe) for wx in range(len(p))) for xo, oo in ours)
        used = np.concatenate([t.leaf[t.node < 0], t.z[tree.valid_entries(t)]])
        span = float(used.max() - used.min())
        self.assertLessEqual(solved.root.gap, epsilon)
        self.assertAlmostEqual(solved.root.gap * span, best - guaranteed, delta=1e-9)
        self.assertLessEqual(guaranteed, exact.value + 1e-9 * span)
        self.assertLessEqual(exact.value - guaranteed, epsilon * span + 1e-9 * span)
        self.assertLessEqual(best - exact.value, epsilon * span + 1e-9 * span)
        return solved

    def test_separate_information_sets(self):
        rng = np.random.default_rng(14)
        for _ in range(6):
            t = _random_tree(rng, 2, 2, 2, 2, 2)
            with self.subTest(nodes=len(t.info)):
                self.check(t, rng.random(2) + 0.01, rng.random((2, 2)) + 0.01)

    def test_merged_information_sets(self):
        rng = np.random.default_rng(15)
        for _ in range(6):
            t = _random_tree(rng, 2, 2, 2, 2, 2, share=True)
            self.assertLess(len(t.own_valid), int((t.info >= 0).sum()))  # one set holds nodes of both worlds
            with self.subTest(nodes=len(t.info)):
                self.check(t, rng.random(2) + 0.01, rng.random((2, 2)) + 0.01)

    def test_three_candidates_below_and_a_tighter_target(self):
        rng = np.random.default_rng(16)
        t = _random_tree(rng, 2, 2, 1, 3, 2)
        self.check(t, rng.random(2) + 0.01, rng.random((2, 1)) + 0.01, epsilon=1e-4)


def _one_edge_tree(z_per_world, info, foe_valid, weights):
    """Every world's root has one edge (K = M = 1), leading to its depth-1 node."""
    z = np.asarray(z_per_world, np.float64)
    w, k2, m2 = z.shape
    sets = int(max(info)) + 1
    return tree.Tree(weights=np.asarray(weights, np.float64), leaf=np.zeros((w, 1, 1)),
                     node=np.arange(w, dtype=np.int64).reshape(w, 1, 1), info=np.asarray(info, np.int64), z=z,
                     own_valid=np.ones((sets, k2), bool), foe_valid=np.asarray(foe_valid, bool),
                     own_prior=np.ones((sets, k2)), foe_prior=np.asarray(foe_valid, np.float64))


class InformationSets(unittest.TestCase):
    # Our-only nodes (the foe has one empty response): world 0 pays 1 for action 0, world 1 pays 1 for action 1.
    Z = [[[1.0], [0.0]], [[0.0], [1.0]]]

    def test_different_keys_are_separate_strategies(self):
        solved = tree.solve_tree(_one_edge_tree(self.Z, [0, 1], [[True], [True]], [0.6, 0.4]), [1.0],
                                 [[1.0], [1.0]])
        self.assertEqual(solved.own.shape, (2, 2))
        self.assertGreater(solved.own[0, 0], 0.999)
        self.assertGreater(solved.own[1, 1], 0.999)
        np.testing.assert_allclose(solved.tables.reshape(-1), [1.0, 1.0], atol=2e-3)

    def test_one_key_is_one_strategy_over_the_worlds(self):
        solved = tree.solve_tree(_one_edge_tree(self.Z, [0, 0], [[True], [True]], [0.6, 0.4]), [1.0],
                                 [[1.0], [1.0]])
        self.assertEqual(solved.own.shape, (1, 2))  # one strategy for both worlds' nodes
        # World 0 weighs more: action 0 in both. Action 1 costs 0.6 - 0.4 per unit of mass, so a gap of at most
        # epsilon (of the range 1) leaves it at most epsilon / 0.2.
        self.assertLessEqual(solved.own[0, 1], matrix.RM_EPSILON / 0.2)
        np.testing.assert_allclose(solved.tables.reshape(-1), [1.0, 0.0], rtol=0, atol=matrix.RM_EPSILON / 0.2)
        self.assertAlmostEqual(solved.root.solution.value, 0.6, delta=2e-3)

    def test_an_information_set_spans_one_root_row(self):
        # Our root row is part of the key (perfect recall): one set over the nodes of rows 0 and 1 is refused.
        t = tree.Tree(weights=np.ones(1), leaf=np.zeros((1, 2, 1)), node=np.array([[[0], [1]]]),
                      info=np.array([0, 0]), z=np.array([[[1.0], [0.0]], [[0.0], [1.0]]]),
                      own_valid=np.ones((1, 2), bool), foe_valid=np.ones((2, 1), bool), own_prior=np.ones((1, 2)),
                      foe_prior=np.ones((2, 1)))
        with self.assertRaisesRegex(SearchError, "root rows"):
            tree.solve_tree(t, np.ones(2), np.ones((1, 1)))
        solved = tree.solve_tree(t._replace(info=np.array([0, 1]), own_valid=np.ones((2, 2), bool),
                                            own_prior=np.ones((2, 2))), np.ones(2), np.ones((1, 1)))
        self.assertEqual(solved.own.shape, (2, 2))


class NodeKinds(unittest.TestCase):
    def test_both_requested_is_the_matrix_game(self):
        pennies = [[[1.0, 0.0], [0.0, 1.0]]]
        solved = tree.solve_tree(_one_edge_tree(pennies, [0], [[True, True]], [1.0]), [1.0], [[1.0]])
        np.testing.assert_allclose(solved.own[0], [0.5, 0.5], atol=2e-3)
        np.testing.assert_allclose(solved.foe[0], [0.5, 0.5], atol=2e-3)
        self.assertAlmostEqual(float(solved.tables[0, 0, 0]), 0.5, delta=2e-3)

    def test_ours_only_takes_the_best_candidate(self):
        solved = tree.solve_tree(_one_edge_tree([[[0.2], [0.7], [0.1]]], [0], [[True]], [1.0]), [1.0], [[1.0]])
        self.assertGreater(solved.own[0, 1], 0.999)
        self.assertAlmostEqual(float(solved.tables[0, 0, 0]), 0.7, delta=1e-3)

    def test_foes_only_takes_the_foes_best_answer(self):
        z = np.array([[[0.2, -0.5, 0.9]]])
        t = tree.Tree(weights=np.ones(1), leaf=np.array([[[0.0, 0.3]]]), node=np.array([[[0, -1]]]),
                      info=np.array([-1]), z=z, own_valid=np.zeros((0, 1), bool), foe_valid=np.ones((1, 3), bool),
                      own_prior=np.zeros((0, 1)), foe_prior=np.ones((1, 3)))
        solved = tree.solve_tree(t, [1.0], [[1.0, 1.0]])
        self.assertEqual(solved.own.shape, (0, 1))
        self.assertGreater(solved.foe[0, 1], 0.999)
        np.testing.assert_allclose(solved.tables, [[[-0.5, 0.3]]], atol=2e-3)
        self.assertGreater(solved.root.solution.ys[0][0], 0.999)  # the foe enters the node it wins

    def test_padded_candidates_are_never_played(self):
        z = np.array([[[0.0, 9.0], [5.0, 9.0]]])  # column 1 and row 1 are padding: their values must not count
        t = tree.Tree(weights=np.ones(1), leaf=np.zeros((1, 1, 1)), node=np.zeros((1, 1, 1), np.int64),
                      info=np.array([0]), z=z, own_valid=np.array([[True, False]]),
                      foe_valid=np.array([[True, False]]), own_prior=np.array([[1.0, 0.0]]),
                      foe_prior=np.array([[1.0, 0.0]]))
        solved = tree.solve_tree(t, [1.0], [[1.0]])
        self.assertEqual(solved.own.tolist(), [[1.0, 0.0]])
        self.assertEqual(solved.foe.tolist(), [[1.0, 0.0]])
        self.assertEqual(float(solved.tables[0, 0, 0]), 0.0)


class FoeBelow(unittest.TestCase):
    def test_model_keeps_the_foe_on_its_prior(self):
        rng = np.random.default_rng(31)
        t = _random_tree(rng, 3, 3, 2, 2, 3)
        solved = tree.solve_tree(t, rng.random(3) + 0.01, rng.random((3, 2)) + 0.01, foe_below="model")
        prior = t.foe_prior / t.foe_prior.sum(axis=1, keepdims=True)
        np.testing.assert_allclose(solved.foe, prior, rtol=0, atol=1e-15)
        self.assertLessEqual(solved.root.gap, matrix.RM_EPSILON)

    def test_unknown_foe_below_is_refused(self):
        t = _random_tree(np.random.default_rng(1), 2, 2, 2, 2, 2)
        with self.assertRaisesRegex(ValueError, "foe_below"):
            tree.solve_tree(t, np.ones(2), np.ones((2, 2)), foe_below="greedy")


class Reproduction(unittest.TestCase):
    def test_two_solves_are_byte_equal(self):
        rng = np.random.default_rng(77)
        t = _random_tree(rng, 16, 4, 4, 3, 3, share=True)
        prior, foe = rng.random(4) + 0.01, rng.random((16, 4)) + 0.01
        a, b = tree.solve_tree(t, prior, foe), tree.solve_tree(t, prior, foe)
        for name in ("tables", "own", "foe"):
            self.assertEqual(getattr(a, name).tobytes(), getattr(b, name).tobytes())
        self.assertEqual(a.root.solution.x.tobytes(), b.root.solution.x.tobytes())
        self.assertEqual((a.root.gap, a.root.iterations, a.root.solution.value),
                         (b.root.gap, b.root.iterations, b.root.solution.value))

    def test_the_iteration_bound_refuses_by_name(self):
        rng = np.random.default_rng(4)
        t = _random_tree(rng, 16, 4, 4, 3, 3)
        with self.assertRaises(matrix.RMUnconverged) as caught:
            tree.solve_tree(t, rng.random(4) + 0.01, rng.random((16, 4)) + 0.01, iterations=2, check_every=10)
        self.assertEqual(caught.exception.iterations, 2)
        self.assertGreater(caught.exception.gap, matrix.RM_EPSILON)


class MalformedTrees(unittest.TestCase):
    def test_refusals(self):
        t = _random_tree(np.random.default_rng(6), 2, 2, 2, 2, 2)
        n = len(t.info)
        twice = t.node.copy()
        twice[twice == n - 1] = 0  # node 0 reached twice, node n - 1 never
        prior_off = t.own_prior.copy()
        prior_off[~t.own_valid] = 0.5
        nan = t.z.copy()
        nan[tree.valid_entries(t)] = np.nan
        bad = [(t._replace(node=twice), "node"), (t._replace(z=nan), "finite"),
               (t._replace(info=np.full(n, len(t.own_valid), np.int64)), "information set"),
               (t._replace(foe_valid=np.zeros_like(t.foe_valid)), "candidate")]
        if (~t.own_valid).any():
            bad.append((t._replace(own_prior=prior_off), "prior"))
        for broken, pattern in bad:
            with self.subTest(pattern=pattern), self.assertRaisesRegex(SearchError, pattern):
                tree.solve_tree(broken, np.ones(2), np.ones((2, 2)))


if __name__ == "__main__":
    unittest.main()
