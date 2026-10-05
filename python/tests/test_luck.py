"""duoforge.python.luck: luck-adjusted evaluation (duoforge_learn.luck).

- leaf_values: the learner's view of every leaf (a refused step -1, a
  terminal leaf its result, else the value head); an encoder refusal and a
  value that is not finite stop the run.
- In play_suite: the games and their records are byte-identical with and
  without the luck measurement, the luck is a pure function of the seeds,
  the last step is never corrected, and over many games the luck averages
  to zero (the control variate keeps the mean).
- The arena CLI: --luck adds the adjusted scores; without it the summary
  has no luck entries.

Teams A, B and C under POOL, tiny v2-S parameters, on the CPU.
"""
import json
import os
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge.context import reference_setups
from duoforge_learn import luck

C = _layout.CONSTANTS
SEED = 0x2026100500000237
WINS = (C["DUOFORGE_RESULT_SIDE_0"], C["DUOFORGE_RESULT_SIDE_1"])
TIE = C["DUOFORGE_RESULT_TIE"]
UNSUPPORTED = C["DUOFORGE_E_UNSUPPORTED"]


class LeafValues(unittest.TestCase):
    def test_kinds(self):
        values = np.array([0.25, 0.5, 0.5, 0.5, -0.75], dtype=np.float32)
        step = np.array([0, UNSUPPORTED, 0, 0, 0], dtype=np.uint32)
        encode = np.zeros(5, dtype=np.uint32)
        results = np.array([0, 0, WINS[1], TIE, 0], dtype=np.uint32)
        np.testing.assert_array_equal(luck.leaf_values(values, step, encode, results, seat=1),
                                      [0.25, -1.0, 1.0, 0.0, -0.75])
        np.testing.assert_array_equal(luck.leaf_values(values, step, encode, results, seat=0)[2], -1.0)

    def test_refusals_stop(self):
        ok = np.zeros(1, dtype=np.uint32)
        with self.assertRaises(luck.LuckError):
            luck.leaf_values(np.zeros(1, np.float32), ok, np.array([UNSUPPORTED], np.uint32), ok, seat=0)
        with self.assertRaises(luck.LuckError):
            luck.leaf_values(np.zeros(1, np.float32), np.array([C["DUOFORGE_E_INVALID_ARGUMENT"]], np.uint32), ok, ok, 0)
        with self.assertRaises(luck.LuckError):
            luck.leaf_values(np.array([np.nan], np.float32), ok, ok, ok, seat=0)

    def test_adjusted_scores(self):
        records = np.zeros(3, dtype=[("result", np.int8)])
        records["result"] = [1, -1, 0]
        totals = np.array([0.5, -0.25, 0.0])
        np.testing.assert_allclose(luck.adjusted_scores(records, totals), [0.75, 0.125, 0.5])


class _Values:
    """A value head that reads column 0."""
    feature_names = ("v",)

    @staticmethod
    def value(params, rows):
        return np.asarray(rows)[:, 0].astype(np.float32)


class _Leaves:
    """expand: leaf value 10 * root env + sample, every step accepted, nothing terminal."""

    def expand(self, roots, version, ext, seed, keys, viewers, root_envs, samples, choices):
        n = root_envs.size
        obs = (10.0 * root_envs + samples).astype(np.float32).reshape(n, 1)
        zero = np.zeros(n, dtype=np.uint32)
        return obs, zero, zero, None, zero


class _Main:
    """The played batch: no request (zero choices), results and the viewer rows set by hand."""

    def __init__(self, actual, other, results, seats):
        n = len(actual)
        self.envs = n
        self.requests = np.zeros((n, 2), dtype=[("requested", np.uint8)])
        self.results = results
        self.obs = np.zeros((n, 2, 1), dtype=np.float32)
        self.obs[np.arange(n), seats, 0] = actual
        self.obs[np.arange(n), 1 - seats, 0] = other  # the other seat's row: never read

    def result(self, e):
        return self.results[e]

    def query_encoded(self, version, ext):
        return self.obs, None, None


class StepTerms(unittest.TestCase):
    def test_luck_is_actual_minus_mean_of_alternatives(self):
        k, n = 4, 4
        judge = object.__new__(luck.Luck)
        judge.model, judge.params, judge.encoder, judge.ext_supported = _Values(), None, 4, 0
        judge.k, judge.seed, judge.capacity = k, 1, 3  # capacity below n * k: chunked
        judge.leaves, judge._rows, judge._actual = _Leaves(), np.zeros((3, 1), dtype=np.float32), None
        seats = np.array([0, 1, 0, 1])
        judge.start(n, seats)
        actual = np.array([0.5, -0.25, 7.0, 0.0])
        results = [0, 0, 0, WINS[0]]  # game 3 ends with side 0's win: seat 1 loses
        batch = _Main(actual, 99.0, results, seats)
        active = np.array([True, True, True, True])
        judge.before(batch, np.zeros((n, 2), np.uint16), active, step=0, last_step=False)
        judge.after(batch, dead=np.array([False, False, True, False]))  # game 2 refused: -1
        mean = 10.0 * np.arange(n) + (k - 1) / 2.0
        want = np.array([0.5, -0.25, -1.0, -1.0]) - mean
        np.testing.assert_allclose(judge.totals, want)
        np.testing.assert_array_equal(judge.terms, [1, 1, 1, 1])
        np.testing.assert_allclose(judge.step_terms, want)


def _v2s():
    import jax
    from duoforge_learn import policy
    model = policy.make(policy.v2_config("S"))
    return model, model.init(jax.random.PRNGKey(7))


class InPlaySuite(unittest.TestCase):
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
            cls.mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)
        cls.raw = evaluate.Player(cls.model, cls.params, 4, "R", ext_supported=cls.mask)
        cls.plain = cls._play(None, 40)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    @classmethod
    def _play(cls, judge, max_steps, rows=None):
        rows = cls.rows if rows is None else rows
        return cls.evaluate.play_suite(cls.ctx, cls.pool, rows, cls.raw, cls.raw, 2, SEED, max_steps=max_steps,
                                       luck=judge)

    def _judge(self, **change):
        args = dict(k=4, capacity=64, workers=2)
        args.update(change)
        return luck.Luck(self.ctx, self.model, self.params, 4, self.mask, **args)

    def test_games_are_unchanged(self):
        with self._judge() as judge:
            records = self._play(judge, 40)
        self.assertEqual(records.tobytes(), self.plain.tobytes())
        self.assertEqual(judge.totals.shape, (len(self.rows),))
        self.assertTrue((judge.terms > 0).all())
        self.assertTrue(np.isfinite(judge.totals).all())
        self.assertGreater(np.abs(judge.totals).max(), 0.0)

    def test_luck_is_a_pure_function_of_the_seeds(self):
        with self._judge() as a, self._judge(workers=1) as b:
            self._play(a, 40)
            self._play(b, 40)
        np.testing.assert_array_equal(a.totals, b.totals)
        np.testing.assert_array_equal(a.terms, b.terms)
        with self._judge(seed=SEED + 1) as c:
            self._play(c, 40)
        self.assertFalse(np.array_equal(a.totals, c.totals))

    def test_steps_without_chance_have_no_luck(self):
        with self._judge() as judge:
            seen = []
            before = judge.before

            def recording(*args, **kw):
                before(*args, **kw)
                if judge._pending is not None:
                    seen.append(judge._leaf_values.copy())
            judge.before = recording
            self._play(judge, 40)
        flat = np.concatenate([(v.max(axis=1) - v.min(axis=1)) < 1e-9 for v in seen])
        steps = judge.step_terms
        self.assertEqual(flat.size, steps.size)
        self.assertGreater(flat.sum(), 20)  # team selection and other steps without a draw
        # K equal alternatives do not prove a step drew nothing: a rare outcome (a critical hit) can miss all K
        # and still happen in the actual step. A mismatch between the actual successor's valuation and the
        # leaves' (another seat, row or choice) would make nearly every such step nonzero.
        self.assertGreater(np.mean(np.abs(steps[flat]) < 1e-5), 0.9)

    def test_leaf_rows_are_the_actual_rows(self):
        """A leaf's row from expand equals the row the actual successor is valued from (query_encoded of the
        same state, the same seat): the leaf batch holds the last chunk's leaves."""
        with self._judge(k=2, capacity=64) as judge:
            self._play(judge, 3)
            obs, statuses, roots, seats = (judge.last[x] for x in ("obs", "open", "root_envs", "seats"))
            rows, _, _ = judge.leaves.query_encoded(4, self.mask)
            leaf = np.flatnonzero(statuses)
            self.assertGreater(leaf.size, 0)
            np.testing.assert_array_equal(rows[leaf, seats[leaf]], obs[leaf])

    def test_last_step_is_not_corrected(self):
        with self._judge() as judge:
            self._play(judge, 1)
        self.assertTrue((judge.terms == 0).all())
        np.testing.assert_array_equal(judge.totals, 0.0)

    def test_luck_averages_to_zero(self):
        from duoforge_learn import suite
        rows = suite.make_suite(3, SEED, games=8)[:96]
        with self._judge(k=8, capacity=256) as judge:
            records = self._play(judge, 60, rows)
        steps = judge.step_terms
        self.assertGreater(steps.size, 500)
        mean, se = steps.mean(), steps.std(ddof=1) / np.sqrt(steps.size)
        self.assertLess(abs(mean), 4 * se, (mean, se))
        adjusted = luck.adjusted_scores(records, judge.totals)
        self.assertEqual(adjusted.shape, (len(rows),))


class ArenaLuck(unittest.TestCase):
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
        for u in (0, 100):
            checkpoint.save(os.path.join(cls.run_dir, f"params-{u}.npz"), params, dict(config, update=u))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _main(self, out, *extra):
        from duoforge_search import arena
        common = ["--run-dir", self.run_dir, "--out", out, "--checkpoint", "params-100", "--games", "16",
                  "--agents", "N", "--km", "2x2", "--s", "2", "--capacity", "64", "--workers", "2",
                  "--resamples", "50", "--max-steps", "6"]
        self.assertEqual(arena.main(common + list(extra)), 0)
        with open(os.path.join(out, "summary.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_cli_luck(self):
        plain = self._main(os.path.join(self.tmp.name, "plain"))
        self.assertNotIn("luck", plain["conditions"])
        self.assertTrue(all("luck" not in c for c in plain["configs"].values()))
        summary = self._main(os.path.join(self.tmp.name, "luck"), "--luck", "2")
        self.assertEqual(summary["conditions"]["luck"]["k"], 2)
        for name, c in summary["configs"].items():
            self.assertEqual(c["score"], plain["configs"][name]["score"], name)  # the games are unchanged
            lk = c["luck"]
            self.assertEqual(len(lk["score_95"]), 2)
            self.assertIn("variance_ratio", lk)
            self.assertGreater(lk["steps"]["corrected"], 0)
        self.assertIn("paired_vs_R", summary["configs"]["N-k2m2s2-vs-R"]["luck"])


if __name__ == "__main__":
    unittest.main()
