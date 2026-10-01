"""duoforge.python.learn: the learner pipeline (decision 0014). Needs JAX.

GAE over each seat's own decisions against a hand computation; the team
head's tuple table against the engine's joint ranks; self-play steps with
masked sampling (the engine refuses any choice outside its domain); a
two-update training run with evaluation and a checkpoint.
"""
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import features
from duoforge_learn import model, ppo, train
from duoforge_learn.selfplay import TEAM_ACTIONS, TEAM_TABLE, SelfPlay


class GaeTest(unittest.TestCase):
    def test_own_decisions_and_terminal_reward(self):
        # One environment, four steps. Seat 0 decides at t = 0, 1, 3; seat 1
        # at t = 0, 2. The episode ends after t = 2, seat 0 winning; t = 3
        # starts the next one, bootstrapped by the values after the rollout.
        values = np.array([[[0.1, 0.2]], [[0.3, 0.0]], [[0.0, 0.4]], [[0.5, 0.0]]], dtype=np.float32)
        rewards = np.zeros((4, 1, 2), dtype=np.float32)
        rewards[2, 0] = (1.0, -1.0)
        done = np.array([[False], [False], [True], [False]])
        acting = np.array([[[True, True]], [[True, False]], [[False, True]], [[True, False]]])
        bootstrap = np.array([[0.6, 0.7]], dtype=np.float32)
        adv, ret = ppo.gae(values, rewards, done, acting, bootstrap, gamma=0.9, lam=0.8)
        expected = np.array([[[0.674, -0.848]], [[0.7, 0.0]], [[0.0, -1.4]], [[0.04, 0.0]]], dtype=np.float32)
        np.testing.assert_allclose(adv, expected, atol=1e-6)
        np.testing.assert_allclose(ret, np.where(acting, expected + values, 0.0), atol=1e-6)


class PipelineTest(unittest.TestCase):
    def test_team_table_is_the_joint_rank(self):
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 1) as batch:
            batch.query_factored()
            domain = batch.domains[0, 0]
            self.assertEqual(int(duoforge.joint_counts(domain)[0]), TEAM_ACTIONS)
            for k in range(TEAM_ACTIONS):
                self.assertEqual(list(duoforge.factored_choice(domain, k)["picks"][:4]), list(TEAM_TABLE[k]))

    def test_selfplay_steps_with_masked_sampling(self):
        import jax
        env = SelfPlay(8, 2, 0x2026100200000022)
        try:
            params = model.init(jax.random.PRNGKey(1), features.OBS_SIZE, features.SLOT_FEATURES, TEAM_ACTIONS)
            act = jax.jit(model.act, static_argnames=("greedy",))
            key = jax.random.PRNGKey(2)
            ended = 0
            for _ in range(80):
                o = env.observe()
                key, sub = jax.random.split(key)
                actions, logp, _ = act(params, sub, o.obs.reshape(16, -1), o.slots.reshape((16,) + o.slots.shape[2:]),
                                       o.mask.reshape((16,) + o.mask.shape[2:]), o.is_team.reshape(-1))
                self.assertTrue(np.isfinite(np.asarray(logp)).all())
                _, done = env.step(np.asarray(actions).reshape(8, 2))  # raises for a choice outside the domain
                ended += int(done.sum())
            self.assertGreater(ended, 0)
        finally:
            env.close()

    def test_training_runs_evaluates_and_saves(self):
        out = tempfile.mkdtemp(prefix="duoforge-learn-")
        try:
            code = train.main(["--envs", "8", "--workers", "2", "--rollout", "8", "--updates", "2", "--minutes", "0",
                               "--eval-every", "1", "--eval-envs", "8", "--minibatch", "256", "--out", out])
            self.assertEqual(code, 0)
            with open(os.path.join(out, "log.jsonl"), encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            self.assertEqual([r["update"] for r in records], [1, 2])
            for r in records:
                self.assertTrue(all(math.isfinite(r[k]) for k in ("loss", "policy_loss", "value_loss", "entropy")))
                self.assertTrue(all(0.0 <= r[k] <= 1.0 for k in ("vs_random", "vs_scripted", "vs_previous")))
            self.assertTrue(os.path.isfile(os.path.join(out, "params-2.npz")))
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
