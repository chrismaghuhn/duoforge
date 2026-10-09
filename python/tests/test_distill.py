"""Stage 3 P1 distillation, Learner v2 side (plan 2026-10-08-stage3-p1-learner). Synthetic shards only, written
to temporary directories through M12's expert_data."""
import dataclasses
import tempfile
import unittest
from pathlib import Path

import numpy as np

from duoforge import features


def _scenes():
    """test_learn_v2's real observations, both when the tests run as a package (CTest: python.tests.test_distill)
    and from python/tests."""
    if __package__:
        from .test_learn_v2 import _scenes as scenes
    else:
        from test_learn_v2 import _scenes as scenes
    return scenes()


def _manifest(ed):
    return ed.DataManifest(source_commit="a" * 40, checkpoint_hash="b" * 64, model_hash="c" * 64, encoder=4,
                           ids_hash="d" * 64, pool_hash="e" * 64, belief_hash="f" * 64, seed=7, split_seed=9,
                           key_version=1, device="cpu", runtime="synthetic", compiler="synthetic", capacity=1024,
                           workers=4, parallel_games=512, game_count=1024, rounds=2, first_game_id=0,
                           obs_width=features.obs_size(4), slot_width=features.SLOT_FEATURES,
                           teacher_config={"k": 8, "m": 8, "worlds": 16, "lam": .5}, budget={"labels": 16384},
                           evaluation={"synthetic": True})


class _Rows:
    """Builds valid ExpertRows of one game and seat, tick by tick."""

    def __init__(self, ed, m, game, seat=0):
        self.ed, self.m, self.game, self.seat, self.tick, self.epoch = ed, m, game, seat, 0, 0

    def _base(self, **kw):
        ed, m = self.ed, self.m
        row = dict(key=ed.DecisionKey(self.game, self.seat, self.epoch), logical_tick=self.tick, boundary="TURN",
                   obs=np.zeros(m.obs_width, np.float32), slots=np.zeros((2, 32, m.slot_width), np.float32),
                   legal_mask=None, sparse_policy=None, status=ed.RowStatus.UNREQUESTED, raw_action=None,
                   action=None, behavior_logp=None, requested=False, acting=False, learner=True, value_mask=True,
                   admitted=False, reward=0., done=False, collector_value=0., bootstrap=0., cause=None, work={},
                   audit={})
        row.update(kw)
        if row["legal_mask"] is None:
            mask = np.zeros((32, 32), bool)
            mask.flat[[0, 1, 33]] = True
            row["legal_mask"] = mask
        self.tick += 1
        return ed.ExpertRow(**row)

    def wait(self, value, **kw):
        return self._base(collector_value=value, **kw)

    def act(self, status, value, **kw):
        self.epoch += 1
        ed = self.ed
        kw = dict(status=status, requested=True, acting=True, raw_action=1, action=1,
                  behavior_logp=float(np.log(.5)), collector_value=value, key=ed.DecisionKey(self.game, self.seat,
                                                                                              self.epoch)) | kw
        if status is ed.RowStatus.TARGET:
            kw |= dict(admitted=True, sparse_policy=ed.SparsePolicy(np.array([1, 33], np.int64),
                                                                     np.array([.5, .5], np.float64)))
        if status is ed.RowStatus.FORCED:
            mask = np.zeros((32, 32), bool)
            mask.flat[1] = True
            kw |= dict(legal_mask=mask, behavior_logp=0.)
        return self._base(**kw)

    def team(self, value):
        self.epoch += 1
        ed = self.ed
        mask = np.ones(360, bool)
        return self._base(boundary="TEAM_SELECTION", legal_mask=mask, status=ed.RowStatus.UNSELECTED,
                          requested=True, acting=True, raw_action=5, action=5, behavior_logp=float(np.log(1 / 360)),
                          collector_value=value, key=ed.DecisionKey(self.game, self.seat, self.epoch))


def _games(ed, split_seed, train, held):
    """train game ids and held game ids under split_seed."""
    tr, he = [], []
    for g in range(1024):
        (he if ed.is_held_out(g, split_seed) else tr).append(g)
    return tr[:train], he[:held]


class DataTest(unittest.TestCase):
    def setUp(self):
        from duoforge_search import expert_data as ed
        self.ed = ed
        self.m = _manifest(ed)
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge_synthetic_distill_")
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, rows):
        (self.dir / name).unlink(missing_ok=True)  # write_shard never overwrites
        self.ed.write_shard(self.dir / name, rows, self.m)

    def test_strata_split_and_value_targets(self):
        from duoforge_learn import distill_data
        ed, m = self.ed, self.m
        (a, b, c), (d,) = _games(ed, m.split_seed, 3, 1)
        S = ed.RowStatus
        ga = _Rows(ed, m, a)  # target, wait, unselected end with +1
        a_rows = [ga.act(S.TARGET, .5), ga.wait(.4), ga.act(S.UNSELECTED, .2, reward=1., done=True)]
        gb = _Rows(ed, m, b, seat=1)  # truncated: the stored bootstrap on its last row
        b_rows = [gb.act(S.UNSELECTED, .3, bootstrap=.9), gb.act(S.UNSELECTED, .6, bootstrap=.37)]
        gc = _Rows(ed, m, c)  # the learner never acts; the game ends -1
        c_rows = [gc.wait(.1), gc.wait(.2, reward=-1., done=True)]
        gd = _Rows(ed, m, d)  # held out: preview, target, forced
        d_rows = [gd.team(.0), gd.act(S.TARGET, .5), gd.act(S.FORCED, .5, reward=1., done=True)]
        # Game a spans two shards; the files are read in name order.
        self._write("0.json", [a_rows[0], *b_rows])
        self._write("1.json", [*a_rows[1:], *c_rows, *d_rows])
        data = distill_data.load(self.dir, m)
        self.assertEqual(len(data.game_id), 10)
        idx = distill_data.strata(data)
        sets = {k: set(v.tolist()) for k, v in idx.items()}
        names = list(sets)
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                self.assertFalse(sets[x] & sets[y], (x, y))
        held = set(np.flatnonzero(data.game_id == d).tolist())
        self.assertTrue(held and held <= sets["held_target"] | sets["held_non"])
        self.assertFalse(held & (sets["train_target"] | sets["train_non"]))
        self.assertTrue(data.held_out[list(held)].all() and not data.held_out[data.game_id != d].any())

        def rows_of(g):
            return np.flatnonzero(data.game_id == g)

        # Hand-computed GAE (gamma 0.99, lambda 0.95): a waiting row takes its seat's next decision's return.
        np.testing.assert_allclose(data.value_target[rows_of(a)], [0.9504, 1.0, 1.0], atol=1e-5)
        np.testing.assert_allclose(data.value_target[rows_of(b)], [0.37421, 0.3663], atol=1e-4)
        np.testing.assert_allclose(data.value_target[rows_of(c)], [-1.0, -1.0], atol=1e-6)
        self.assertTrue(data.value_row[rows_of(c)].all() and not data.policy_row[rows_of(c)].any())
        # Strata: targets, policy rows (acting, >= 2 legal, no target), value-only rows (waiting, forced).
        ra, rd = rows_of(a), rows_of(d)
        self.assertEqual(data.has_target[ra].tolist(), [True, False, False])
        self.assertEqual(data.policy_row[ra].tolist(), [False, False, True])
        self.assertEqual(data.target_ids[ra[0]].tolist(), [1, 33, -1, -1, -1, -1, -1, -1])
        np.testing.assert_allclose(data.target_probs[ra[0], :2], [.5, .5])
        self.assertEqual(data.is_team[rd].tolist(), [True, False, False])
        self.assertTrue(data.policy_row[rd[0]] and data.team_mask[rd[0]].all() and not data.mask[rd[0]].any())
        self.assertEqual((data.policy_row[rd[2]], data.value_row[rd[2]], data.has_target[rd[2]]), (False, True, False))
        self.assertEqual(sets["held_target"], {int(rd[1])})

    def test_truncation_uses_the_stored_bootstrap(self):
        from duoforge_learn import distill_data
        ed, m = self.ed, self.m
        (b,), _ = _games(ed, m.split_seed, 1, 0)
        S = ed.RowStatus
        gb = _Rows(ed, m, b)
        self._write("0.json", [gb.act(S.UNSELECTED, .3), gb.act(S.UNSELECTED, .6, bootstrap=.37)])
        cut = distill_data.load(self.dir, m).value_target
        gb = _Rows(ed, m, b)
        self._write("0.json", [gb.act(S.UNSELECTED, .3), gb.act(S.UNSELECTED, .6, bootstrap=0.)])
        terminal = distill_data.load(self.dir, m).value_target
        np.testing.assert_allclose(cut, [0.37421, 0.3663], atol=1e-4)
        self.assertGreater(float(np.abs(cut - terminal).min()), 0.3)

    def test_load_refuses_incomplete_trajectories(self):
        from duoforge_learn import distill_data
        ed, m = self.ed, self.m
        (g,), _ = _games(ed, m.split_seed, 1, 0)
        S = ed.RowStatus
        with self.assertRaisesRegex(ValueError, "no shard"):
            distill_data.load(self.dir, m)
        rows = _Rows(ed, m, g)
        first, second = rows.act(S.UNSELECTED, .3), rows.act(S.UNSELECTED, .6)
        self._write("0.json", [first, dataclasses.replace(second, logical_tick=2)])
        with self.assertRaisesRegex(ValueError, "gap"):
            distill_data.load(self.dir, m)
        self._write("0.json", [dataclasses.replace(first, done=True), second])
        with self.assertRaisesRegex(ValueError, "ends before"):
            distill_data.load(self.dir, m)
        self._write("0.json", [first])
        self._write("1.json", [dataclasses.replace(first, key=dataclasses.replace(first.key, request_epoch=5))])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            distill_data.load(self.dir, m)
        other = _Rows(ed, m, g, seat=1)  # one learner seat per game
        self._write("1.json", [other.wait(.1), other.wait(.2)])
        with self.assertRaisesRegex(ValueError, "more than one learner seat"):
            distill_data.load(self.dir, m)


def _log_softmax(x):
    x = x.astype(np.float64)
    m = x.max(axis=-1, keepdims=True)
    return x - m - np.log(np.exp(x - m).sum(axis=-1, keepdims=True))


class LossTest(unittest.TestCase):
    """Task 3: mean_target KL(tau || pi) + 0.1 mean_policy KL(pi_ref || pi) + 0.5 mean_value (v - target)^2."""

    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge_learn import policy
        cls.jax = jax
        team, turn = _scenes()
        cls.model = policy.make(policy.v2_config("S"))
        cls.params = cls.model.init(jax.random.PRNGKey(1))
        cls.ref = cls.model.init(jax.random.PRNGKey(2))
        obs = np.concatenate([turn[0][:7], team[0][:1]])
        slots = np.concatenate([turn[1][:7], team[1][:1]])
        mask = np.concatenate([turn[2][:7], np.zeros_like(turn[2][:1])])
        n = 8
        flat = mask.reshape(n, -1)
        ids = np.full((n, 8), -1, np.int64)
        probs = np.zeros((n, 8), np.float32)
        for r in (0, 1):  # two targets over legal ids, one with a zero-mass entry
            legal = np.flatnonzero(flat[r])[:3]
            ids[r, :len(legal)] = legal
            probs[r, :len(legal)] = [.6, .4, 0.][:len(legal)] if r == 0 else np.full(len(legal), 1 / len(legal))
        cls.batch = {
            "obs": obs, "slots": slots, "mask": mask, "team_mask": np.zeros((n, 360), bool),
            "is_team": np.array([0, 0, 0, 0, 0, 0, 0, 1], bool), "target_ids": ids, "target_probs": probs,
            "has_target": np.array([1, 1, 0, 0, 0, 0, 0, 0], bool),
            "policy_row": np.array([0, 0, 1, 1, 1, 0, 0, 1], bool),
            "value_row": np.array([1, 1, 1, 1, 1, 1, 1, 1], bool),
            "value_target": np.linspace(-1, 1, n).astype(np.float32), "weight": np.ones(n, np.float32)}
        cls.batch["team_mask"][7] = True

    def _reference(self, params, ref, b):
        """The loss in NumPy from apply's outputs."""
        lp, lt, v = (np.asarray(x, np.float64) for x in self.model.apply(params, b["obs"], b["slots"], b["mask"]))
        rp, rt, _ = (np.asarray(x, np.float64) for x in self.model.apply(ref, b["obs"], b["slots"], b["mask"]))
        flat, w = b["mask"].reshape(len(lp), -1), b["weight"]
        tkl = []
        for r in np.flatnonzero(b["has_target"] & (w > 0)):
            keep = b["target_probs"][r] > 0
            p, i = b["target_probs"][r][keep].astype(np.float64), b["target_ids"][r][keep]
            tkl.append(float((p * (np.log(p) - lp[r, i])).sum()))
        rkl = []
        for r in np.flatnonzero(b["policy_row"] & (w > 0)):
            if b["is_team"][r]:
                legal = b["team_mask"][r]
                rkl.append(float((np.exp(rt[r][legal]) * (rt[r][legal] - lt[r][legal])).sum()))
            else:
                legal = flat[r]
                rkl.append(float((np.exp(rp[r][legal]) * (rp[r][legal] - lp[r][legal])).sum()))
        vrows = np.flatnonzero(b["value_row"] & (w > 0))
        vloss = float(((v[vrows] - b["value_target"][vrows]) ** 2).mean())
        return np.mean(tkl) + 0.1 * np.mean(rkl) + 0.5 * vloss, np.mean(tkl), np.mean(rkl), vloss

    def test_loss_terms_match_numpy_reference(self):
        from duoforge_learn import distill
        loss, aux = distill.distill_loss(self.params, self.ref, self.batch, self.model)
        want, tkl, rkl, vloss = self._reference(self.params, self.ref, self.batch)
        self.assertAlmostEqual(float(aux["teacher_kl"]), tkl, places=4)
        self.assertAlmostEqual(float(aux["ref_kl"]), rkl, places=4)
        self.assertAlmostEqual(float(aux["value_loss"]), vloss, places=5)
        self.assertAlmostEqual(float(loss), want, places=4)
        self.assertEqual((int(aux["n_target"]), int(aux["n_policy"]), int(aux["n_value"])), (2, 4, 8))
        self.assertEqual((distill.REF_COEF, distill.VALUE_COEF), (0.1, 0.5))

    def test_loss_is_zero_kl_at_reference_and_finite_at_illegal(self):
        from duoforge_learn import distill
        _, aux = distill.distill_loss(self.params, self.params, self.batch, self.model)
        self.assertAlmostEqual(float(aux["ref_kl"]), 0.0, places=6)
        grads = self.jax.grad(lambda p: distill.distill_loss(p, self.ref, self.batch, self.model)[0])(self.params)
        leaves = [np.asarray(g) for g in self.jax.tree_util.tree_leaves(grads)]
        self.assertTrue(all(np.isfinite(g).all() for g in leaves))
        self.assertGreater(max(float(np.abs(g).max()) for g in leaves), 0.0)

    def test_padding_and_team_rows(self):
        from duoforge_learn import distill
        b = self.batch
        padded = {k: np.concatenate([v, v]) for k, v in b.items()}
        padded["weight"][len(b["weight"]):] = 0.0
        padded["value_target"][len(b["weight"]):] = 1e6  # padding must not reach any term
        loss, aux = distill.distill_loss(self.params, self.ref, b, self.model)
        loss2, aux2 = distill.distill_loss(self.params, self.ref, padded, self.model)
        self.assertAlmostEqual(float(loss2), float(loss), places=5)
        for k in ("n_target", "n_policy", "n_value"):
            self.assertEqual(float(aux2[k]), float(aux[k]))
        # A team row's KL is the team head's: its pair mask is never read.
        noisy = dict(b, mask=b["mask"].copy())
        noisy["mask"][7] = True
        self.assertAlmostEqual(float(distill.distill_loss(self.params, self.ref, noisy, self.model)[1]["ref_kl"]),
                               float(aux["ref_kl"]), places=6)


def _small_data(targets=16, held_targets=4, policy=24, value_only=8, held_policy=6):
    """DistillData of real observations (repeated), with a known layout; held rows carry a value target of 1e6, so
    a held row in a training batch would show in the step's value loss."""
    from duoforge_learn import distill_data
    _, turn = _scenes()
    obs, slots, mask = turn
    kinds = (["t"] * targets + ["p"] * policy + ["v"] * value_only + ["T"] * held_targets + ["P"] * held_policy)
    n = len(kinds)
    pick = np.arange(n) % 7
    flat = mask[pick].reshape(n, -1)
    ids = np.full((n, 8), -1, np.int64)
    probs = np.zeros((n, 8), np.float32)
    for r, k in enumerate(kinds):
        if k in "tT":
            legal = np.flatnonzero(flat[r])[:2]
            ids[r, :len(legal)] = legal
            probs[r, :len(legal)] = 1.0 / len(legal)
    held = np.array([k in "TP" for k in kinds])
    return distill_data.DistillData(
        obs=obs[pick], slots=slots[pick], mask=mask[pick], team_mask=np.zeros((n, 360), bool),
        is_team=np.zeros(n, bool), target_ids=ids, target_probs=probs,
        has_target=np.array([k in "tT" for k in kinds]), policy_row=np.array([k in "pP" for k in kinds]),
        value_row=np.ones(n, bool),
        value_target=np.where(held, 1e6, np.linspace(-.5, .5, n)).astype(np.float32),
        game_id=np.arange(n, dtype=np.int64), held_out=held)


class FitTest(unittest.TestCase):
    """Task 4: keyed batches, epochs, drift guards and the best epoch (the row counts patched small)."""

    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge_learn import policy
        cls.model = policy.make(policy.v2_config("S"))
        cls.params = cls.model.init(jax.random.PRNGKey(4))
        cls.config = {"format": 2}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge-distill-")
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _fit(self, data, **patches):
        from unittest import mock
        from duoforge_learn import distill
        consts = {"TARGET_ROWS": 8, "NON_TARGET_ROWS": 24} | patches
        with mock.patch.multiple(distill, **consts), \
                mock.patch.object(distill, "_save", lambda path, params, config: Path(path).write_text("x")):
            return distill.fit(data, self.model, self.params, self.params, self.config, self.out, seed=3)

    def _log(self):
        import json
        return [json.loads(line) for line in (self.out / "log.jsonl").read_text().splitlines()]

    def test_batch_plan_covers_each_target_once_and_streams_non_targets(self):
        from unittest import mock
        from duoforge_learn import distill
        with mock.patch.multiple(distill, TARGET_ROWS=16, NON_TARGET_ROWS=48):
            plan = distill.BatchPlan(5)
            idx = np.arange(10, 40)
            one, two = plan.targets(1, idx), plan.targets(2, idx)
            self.assertEqual(one.shape, (2, 16))
            for e in (one, two):
                got = e[e >= 0]
                self.assertEqual(sorted(got.tolist()), idx.tolist())
                self.assertEqual((e < 0).sum(), 2)
            self.assertNotEqual(one.tolist(), two.tolist())
            np.testing.assert_array_equal(plan.targets(1, idx), one)
            non = np.arange(100, 130)
            first, cursor = plan.non_targets((0, 0), non, 2)
            second, _ = plan.non_targets(cursor, non, 2)
            whole, _ = plan.non_targets((0, 0), non, 4)
            np.testing.assert_array_equal(np.concatenate([first, second]), whole)
            stream = whole.reshape(-1)
            for lap in range(len(stream) // 30):
                self.assertEqual(sorted(stream[30 * lap:30 * (lap + 1)].tolist()), non.tolist())

    def test_fit_stops_and_keeps_best(self):
        from duoforge_learn import distill
        data = _small_data()
        # (d) every epoch counts as a gain: four epochs of two steps each.
        result = self._fit(data, MIN_GAIN=-1.0)
        self.assertEqual((result.stop_reason, result.steps, len(result.epochs)), ("max_epochs", 8, 5))
        steps = [r for r in self._log() if "step" in r]
        self.assertEqual(len(steps), 8)
        self.assertLess(max(r["value_loss"] for r in steps), 100.0)  # no held row ever trained on
        self.assertTrue(all(r["n_target"] == 8 for r in steps))
        self.assertEqual(self._log()[-1], {"stop": "max_epochs", "best_epoch": result.best_epoch, "steps": 8})
        held = [r for r in self._log() if "held_teacher_kl" in r][-1]
        self.assertEqual(held["epoch"], 4)
        self.assertGreater(held["held_value_loss"], 1e10)  # the held rows are evaluated
        self.assertTrue((self.out / "params-best.npz").exists())
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge-distill-")
        self.out = Path(self.tmp.name)
        # (a) the reference KL guard: best stays epoch 0, the init, marked no_gain.
        result = self._fit(data, REF_KL_MAX=0.0)
        self.assertEqual((result.stop_reason, result.best_epoch, len(result.epochs)), ("ref_kl", 0, 2))
        import jax
        for a, b in zip(jax.tree_util.tree_leaves(result.best_params), jax.tree_util.tree_leaves(self.params)):
            np.testing.assert_array_equal(np.asarray(a), np.asarray(b))  # best epoch 0: the start itself
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge-distill-")
        self.out = Path(self.tmp.name)
        # (b) no gain of MIN_GAIN for PATIENCE epochs.
        result = self._fit(data, MIN_GAIN=1e9)
        self.assertEqual((result.stop_reason, result.best_epoch, len(result.epochs)), ("no_gain", 0, 3))
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge-distill-")
        self.out = Path(self.tmp.name)
        # (e) the step cap inside an epoch: 2 steps per epoch, stop at step 3, evaluated as an epoch end.
        result = self._fit(data, MAX_STEPS=3, MIN_GAIN=-1.0)
        self.assertEqual((result.stop_reason, result.steps, len(result.epochs)), ("max_steps", 3, 3))
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge-distill-")
        self.out = Path(self.tmp.name)
        # (c) a nonfinite value target stops the fit; no epoch after it is kept.
        bad = dataclasses.replace(data, value_target=data.value_target.copy())
        bad.value_target[0] = np.nan
        result = self._fit(bad, MIN_GAIN=-1.0)
        self.assertEqual((result.stop_reason, result.best_epoch), ("nonfinite", 0))
        self.assertFalse((self.out / "params-epoch-1.npz").exists())  # no epoch after the nonfinite step is kept
        self.assertEqual(distill.MAX_EPOCHS, 4)

    def test_fit_refuses_empty_strata_and_reports_the_whole_held_value_loss(self):
        from duoforge_learn import distill
        data = _small_data()
        for kw, name in (({"held_targets": 0}, "held_target"), ({"policy": 0, "value_only": 0}, "train_non"),
                         ({"held_policy": 0}, "held_non")):
            with self.assertRaisesRegex(ValueError, name):
                self._fit(_small_data(**kw))
        result = self._fit(data, MAX_EPOCHS=0)
        held = np.flatnonzero(data.held_out)
        whole = distill.evaluate_rows(data, held, self.model, self.params, self.params)["held_value_loss"]
        self.assertLess(abs(result.epochs[0]["held_value_loss"] - whole), 1e-5 * whole)

    def test_held_metrics_are_weighted_over_chunks(self):
        from unittest import mock
        from duoforge_learn import distill
        data = _small_data()
        rows = np.flatnonzero(data.held_out)
        one = distill.evaluate_rows(data, rows, self.model, self.params, self.params)
        with mock.patch.object(distill, "EVAL_ROWS", 3):  # 10 held rows: chunks of 3, the last one padded
            chunked = distill.evaluate_rows(data, rows, self.model, self.params, self.params)
        for k in one:
            self.assertLess(abs(chunked[k] - one[k]), 1e-5 * max(1.0, abs(one[k])), k)


class _StopAfter:
    """A stop flag that is requested from its n-th check on (fit checks it after every step)."""

    def __init__(self, n):
        self.n, self.checks = n, 0

    @property
    def requested(self):
        self.checks += 1
        return self.checks >= self.n


class CliTest(unittest.TestCase):
    """Task 5 end to end: write_manifest and shards in, a finished fit and a loadable params-best out."""

    def test_cli_fits_from_a_manifest_and_refuses_a_finished_resume(self):
        import json
        import jax
        from duoforge_search import expert_data as ed
        from duoforge_learn import checkpoint, distill, policy
        with tempfile.TemporaryDirectory(prefix="duoforge_synthetic_distill_cli_") as tmp:
            root = Path(tmp)
            m = dataclasses.replace(_manifest(ed), encoder=features.ENCODER,
                                    obs_width=features.obs_size(features.ENCODER))
            ed.write_manifest(root / "manifest.json", m)
            (train_a, train_b), (held,) = _games(ed, m.split_seed, 2, 1)
            S, rows = ed.RowStatus, []
            for game in (train_a, train_b, held):
                g = _Rows(ed, m, game, seat=ed.learner_seat(game) if hasattr(ed, "learner_seat") else 0)
                rows += [g.act(S.TARGET, .4), g.wait(.3), g.act(S.UNSELECTED, .2, reward=1., done=True)]
            (root / "shards").mkdir()
            ed.write_shard(root / "shards" / "0.json", rows, m)
            cfg = policy.v2_config("S")
            params = policy.make(cfg).init(jax.random.PRNGKey(5))
            config = {"model": cfg, "encoder": features.ENCODER, "features": list(features.FEATURE_NAMES),
                      "slot_features": list(features.SLOT_FEATURE_NAMES), "data": {}, "teams": {}, "update": 0,
                      "decisions": 0, "ids": {}}
            checkpoint.save(root / "start.npz", params, config)
            argv = ["--init", str(root / "start.npz"), "--reference", str(root / "start.npz"), "--shards",
                    str(root / "shards"), "--manifest", str(root / "manifest.json"), "--out", str(root / "fit"),
                    "--allow-other-init"]
            self.assertEqual(distill.main(argv), 0)
            best, best_config = checkpoint.load_current(root / "fit" / "params-best.npz")
            self.assertEqual(best_config["model"], cfg)
            self.assertIn(best_config["distill"]["stop"], ("no_gain", "max_epochs", "ref_kl"))
            log = [json.loads(line) for line in (root / "fit" / "log.jsonl").read_text().splitlines()]
            self.assertEqual(log[-1]["stop"], best_config["distill"]["stop"])
            self.assertEqual(distill.main(argv + ["--resume"]), 2)  # a finished fit is not resumed


class ResumeTest(unittest.TestCase):
    """Task 5: an interrupted fit resumes bitwise; a resume with other inputs or constants is refused."""

    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge_learn import policy
        cls.jax = jax
        cls.model = policy.make(policy.v2_config("S"))
        cls.params = cls.model.init(jax.random.PRNGKey(4))
        cls.data = _small_data()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="duoforge-distill-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _fit(self, out, **kw):
        from unittest import mock
        from duoforge_learn import distill
        out.mkdir(exist_ok=True)
        with mock.patch.multiple(distill, TARGET_ROWS=8, NON_TARGET_ROWS=24, MIN_GAIN=-1.0), \
                mock.patch.object(distill, "_save", lambda path, params, config: Path(path).write_text("x")):
            return distill.fit(self.data, self.model, self.params, self.params, {"format": 2}, out, seed=3,
                               identity=kw.pop("identity", {"manifest": "m"}), **kw)

    @staticmethod
    def _lines(out):
        import json
        return [{k: v for k, v in json.loads(line).items() if k != "seconds"}
                for line in (out / "log.jsonl").read_text().splitlines()]

    def _leaves(self, tree):
        return [np.asarray(x) for x in self.jax.tree_util.tree_leaves(tree)]

    def test_resume_mid_epoch_is_bitwise_identical(self):
        whole = self._fit(self.root / "whole")
        cut = self.root / "cut"
        first = self._fit(cut, stop=_StopAfter(3))  # stops after step 3, the first of epoch 2
        self.assertEqual((first.stop_reason, first.steps), ("signal", 3))
        again = self._fit(cut, resume=True)
        self.assertEqual((again.stop_reason, again.steps, again.best_epoch),
                         (whole.stop_reason, whole.steps, whole.best_epoch))
        for a, b in zip(self._leaves(again.params), self._leaves(whole.params)):
            np.testing.assert_array_equal(a, b)
        for a, b in zip(self._leaves(again.best_params), self._leaves(whole.best_params)):
            np.testing.assert_array_equal(a, b)
        self.assertEqual(self._lines(cut), self._lines(self.root / "whole"))
        with np.load(cut / "distill-state.npz") as a, np.load(self.root / "whole" / "distill-state.npz") as b:
            self.assertEqual(sorted(a.files), sorted(b.files))
            for k in a.files:  # params, best params and every optimizer leaf
                if k != "meta":
                    np.testing.assert_array_equal(a[k], b[k], k)
        with self.assertRaisesRegex(ValueError, "finished"):  # a finished fit is not resumed
            self._fit(cut, resume=True)

    def test_resume_refusals(self):
        from unittest import mock
        from duoforge_learn import distill
        out = self.root / "run"
        self._fit(out, stop=_StopAfter(1))
        with self.assertRaisesRegex(ValueError, "manifest"):
            self._fit(out, resume=True, identity={"manifest": "other"})
        with self.assertRaisesRegex(ValueError, "reference"):
            self._fit(out, resume=True, identity={"manifest": "m", "reference": "another file"})
        with mock.patch.object(distill, "LR", 1e-3), self.assertRaisesRegex(ValueError, "LR"):
            self._fit(out, resume=True)
        with self.assertRaisesRegex(ValueError, "no state"):
            self._fit(self.root / "fresh", resume=True)
        with self.assertRaisesRegex(ValueError, "not empty"):
            self._fit(out)
        repo = Path(__file__).resolve().parents[2]
        self.assertEqual(distill.main(["--init", "x", "--reference", "x", "--shards", "x", "--manifest", "x",
                                       "--out", str(repo / "distill-should-not-exist")]), 2)
        self.assertFalse((repo / "distill-should-not-exist").exists())
        import contextlib
        import io
        other = self.root / "not-49333.npz"
        other.write_bytes(b"not params-49333")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = distill.main(["--init", str(other), "--reference", str(other), "--shards", "x", "--manifest", "x",
                                 "--out", str(self.root / "pinned")])
        self.assertEqual(code, 2)
        self.assertIn("params-49333", err.getvalue())
        self.assertEqual(distill.main(["--init", "x", "--reference", "x", "--shards", "x", "--manifest", "x",
                                       "--out", str(self.root / "empty"), "--resume"]), 2)


if __name__ == "__main__":
    unittest.main()
