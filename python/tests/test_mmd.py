"""duoforge.python.mmd: the Magnetic Mirror Descent objective behind --policy-objective mmd (#359; infrastructure, a
run of one update, no training).

MMD replaces PPO's ratio clipping by a proximal term: the policy loss is -(r * A) plus mmd_prox_coef times the estimate
r log r - r + 1 of KL(policy || behaviour) on the taken actions (r = exp(logp - behaviour logp), never negative, 0 at
r = 1). The magnet is the existing KL anchor (--kl-ref magnet, --kl-coef, --kl-refresh). At the behaviour policy MMD's
gradient is PPO's; a stronger proximal term moves the policy less. The default stays PPO, and a run without the flag
saves the options it saved before.
"""
import os
import tempfile
import unittest

import numpy as np

from duoforge_learn import policy
from python.tests.test_ledger import _SMALL, _train


def _flat(tree):
    import jax
    return np.concatenate([np.ravel(np.asarray(x)) for x in jax.tree_util.tree_leaves(tree)])


class MmdLossTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge_learn import train
        from duoforge_learn.returns import gae, samples_of
        from duoforge_learn.selfplay import SelfPlay
        env = SelfPlay(8, 1, 0x2026101100000359)
        try:
            cls.net = policy.make(dict(policy.V1_DEFAULT))
            cls.params = cls.net.init(jax.random.PRNGKey(359))
            rollout, bootstrap, _, _ = train.collect(env, cls.params, cls.net.act, jax.random.PRNGKey(360), 12)
        finally:
            env.close()
        adv, _, targets = gae(rollout["values"], rollout["rewards"], rollout["done"], rollout["acting"], bootstrap)
        cls.samples = samples_of(rollout, adv, targets)
        o = cls.samples
        cls.now = np.asarray(cls.net.evaluate(cls.params, o["obs"], o["slots"], o["mask"], o["is_team"],
                                              o["actions"])[0])

    def _batch(self, logp):
        return dict(self.samples, logp=logp.astype(np.float32),
                    weight=np.ones(self.samples["actions"].shape[0], np.float32))

    def _grad(self, batch, objective, prox_coef):
        import jax
        from duoforge_learn import ppo
        fn = lambda p: ppo._loss(p, batch, self.net.evaluate, 0.2, 0.01, 0.5, 0.0, objective, prox_coef)
        return jax.grad(lambda p: fn(p)[0])(self.params), fn(self.params)[1]

    def test_at_the_behaviour_policy_the_gradient_is_ppos(self):
        batch = self._batch(self.now)
        ppo_grad, _ = self._grad(batch, "ppo", 0.0)
        mmd_grad, aux = self._grad(batch, "mmd", 3.0)
        np.testing.assert_allclose(_flat(mmd_grad), _flat(ppo_grad), rtol=1e-4, atol=1e-6)
        self.assertAlmostEqual(float(aux[4]), 0.0, places=6)  # the proximal estimate (aux[4]) at r = 1

    def test_the_proximal_term_is_the_kl_estimate_on_the_policy_rows(self):
        shift = np.random.default_rng(7).normal(0.0, 0.5, self.now.shape)
        _, aux = self._grad(self._batch(self.now - shift), "mmd", 1.0)
        r = np.exp(shift)
        w = self.samples["acting"].astype(np.float64)
        want = ((r * shift - r + 1.0) * w).sum() / w.sum()
        self.assertAlmostEqual(float(aux[4]), want, places=4)
        self.assertGreater(float(aux[4]), 0.0)
        # PPO has no proximal term: its statistic is 0.
        _, aux = self._grad(self._batch(self.now - shift), "ppo", 1.0)
        self.assertEqual(float(aux[4]), 0.0)

    def test_an_unknown_objective_is_refused(self):
        from duoforge_learn import ppo
        with self.assertRaisesRegex(ValueError, "objective"):
            ppo.update(self.params, None, None, self.samples, np.random.default_rng(0), self.net.evaluate,
                       objective="rnad")

    def test_a_stronger_proximal_term_moves_the_policy_less(self):
        from duoforge_learn import ppo
        tx = ppo.optimizer(3e-3)
        o, w = self.samples, self.samples["acting"].astype(bool)
        moved = {}
        for coef in (0.1, 10.0):
            params, _, stats = ppo.update(self.params, tx.init(self.params), tx, o, np.random.default_rng(4),
                                          self.net.evaluate, epochs=4, minibatch=64, objective="mmd",
                                          prox_coef=coef)
            self.assertIn("prox", stats)
            after = np.asarray(self.net.evaluate(params, o["obs"], o["slots"], o["mask"], o["is_team"],
                                                 o["actions"])[0])
            moved[coef] = float(np.abs(after - self.now)[w].mean())
        self.assertGreater(moved[0.1], 0.0)
        self.assertLess(moved[10.0], moved[0.1])
        _, _, stats = ppo.update(self.params, tx.init(self.params), tx, o, np.random.default_rng(4),
                                 self.net.evaluate, epochs=1, minibatch=64)
        self.assertNotIn("prox", stats)  # PPO's statistics are as before


class MmdTrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "run")

    def tearDown(self):
        self.tmp.cleanup()

    def _records(self):
        import json
        with open(os.path.join(self.out, "log.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_a_run_trains_with_mmd_and_keeps_it(self):
        from duoforge_learn import runstate
        argv = ["--out", self.out, "--updates", "1", "--minutes", "0", "--policy-objective", "mmd",
                "--mmd-prox-coef", "2", "--kl-ref", "magnet", "--kl-coef", "0.05", "--kl-refresh", "10"] + _SMALL
        self.assertEqual(_train(argv), 0)
        train = runstate.load_state(self.out)["train"]
        self.assertEqual((train["policy_objective"], train["mmd_prox_coef"]), ("mmd", 2.0))
        updates = [r for r in self._records() if "update" in r and "resume" not in r]
        self.assertTrue(np.isfinite(updates[-1]["prox"]))
        self.assertEqual(updates[-1]["policy_objective"], "mmd")
        with self.assertRaisesRegex(SystemExit, "cannot change policy_objective"):
            _train(["--resume", self.out, "--updates", "2", "--policy-objective", "ppo"])
        self.assertEqual(_train(["--resume", self.out, "--updates", "2"]), 0)  # a resume keeps MMD
        self.assertEqual(self._records()[-1]["policy_objective"], "mmd")

    def test_a_ppo_run_saves_no_mmd_option(self):
        from duoforge_learn import runstate
        self.assertEqual(_train(["--out", self.out, "--updates", "1", "--minutes", "0"] + _SMALL), 0)
        train = runstate.load_state(self.out)["train"]
        self.assertFalse({"policy_objective", "mmd_prox_coef"} & set(train))
        updates = [r for r in self._records() if "update" in r and "resume" not in r]
        self.assertFalse({"prox", "policy_objective"} & set(updates[-1]))

    def test_the_prox_coefficient_needs_mmd_and_must_be_positive(self):
        with self.assertRaisesRegex(SystemExit, "--mmd-prox-coef"):
            _train(["--out", self.out, "--updates", "1", "--minutes", "0", "--mmd-prox-coef", "2"] + _SMALL)
        with self.assertRaisesRegex(SystemExit, "--mmd-prox-coef"):
            _train(["--out", self.out, "--updates", "1", "--minutes", "0", "--policy-objective", "mmd",
                    "--mmd-prox-coef", "0"] + _SMALL)


if __name__ == "__main__":
    unittest.main()
