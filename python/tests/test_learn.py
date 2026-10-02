"""duoforge.python.learn: the learner pipeline's JAX parts (decision 0014).

Self-play steps with masked sampling (the engine refuses any choice outside
its domain); a two-update training run with evaluation and a checkpoint,
which refuses to write into a used directory. The NumPy parts are in
test_learn_numpy.py.
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
from duoforge_learn import model, train
from duoforge_learn.selfplay import TEAM_ACTIONS, SelfPlay


class PipelineTest(unittest.TestCase):
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
            with self.assertRaises(SystemExit):
                train.main(["--updates", "1", "--minutes", "0", "--out", out])
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
