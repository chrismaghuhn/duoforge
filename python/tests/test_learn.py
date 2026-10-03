"""duoforge.python.learn: the learner pipeline's JAX parts (decision 0014).

Self-play steps with masked sampling (the engine refuses any choice outside
its domain); a two-update training run with evaluation and a checkpoint
that names its encoder version, which refuses to write into a used
directory; the ladder plays each checkpoint on its encoder version. The
NumPy parts are in test_learn_numpy.py.
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
from duoforge_learn.checkpoint import encoder_of, load
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
                               "--eval-every", "1", "--minibatch", "256", "--out", out])
            self.assertEqual(code, 0)
            with open(os.path.join(out, "log.jsonl"), encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            self.assertEqual([r["update"] for r in records], [1, 2])
            for r in records:
                self.assertTrue(all(math.isfinite(r[k]) for k in ("loss", "policy_loss", "value_loss", "entropy")))
                self.assertTrue(all(0.0 <= r[k] <= 1.0 for k in ("vs_random", "vs_previous")))
                self.assertEqual(len(r["vs_random_by_team"]), 2)
            self.assertTrue(os.path.isfile(os.path.join(out, "params-2.npz")))
            config = load(os.path.join(out, "params-2.npz"), obs_size=features.OBS_SIZE)[1]
            self.assertEqual(config["encoder"], features.ENCODER)  # its encoder version, for encoder_of
            self.assertEqual(encoder_of(config), 4)
            with self.assertRaises(SystemExit):
                train.main(["--updates", "1", "--minutes", "0", "--out", out])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_ladder_passes_each_checkpoint_its_encoder(self):
        # ladder.main gives every pair's evaluation the players' encoder
        # versions: the untrained network and a checkpoint of this train 4,
        # a checkpoint whose config names none 1 (607 columns); a version 5
        # raises.
        import jax
        from unittest import mock
        from duoforge_learn import evaluate, ladder
        out = tempfile.mkdtemp(prefix="duoforge-ladder-")
        try:
            old = model.init(jax.random.PRNGKey(3), features.BASE_OBS_SIZE, features.SLOT_FEATURES, TEAM_ACTIONS)
            params = model.init(jax.random.PRNGKey(3), features.OBS_SIZE, features.SLOT_FEATURES, TEAM_ACTIONS)
            train.save(os.path.join(out, "params-1.npz"), old, {"seed": 7})
            train.save(os.path.join(out, "params-2.npz"), params, {"seed": 7, "encoder": features.ENCODER})
            calls = []

            def fake(context, pool, rows, learner, opponent, workers, seed, max_steps=1000):
                calls.append((learner.name, learner.encoder, opponent.name, opponent.encoder))
                rec = np.zeros(rows.shape[0], dtype=evaluate.RECORD)
                for f in ("side0", "side1", "learner_seat"):
                    rec[f] = rows[f]
                return rec

            with mock.patch.object(evaluate, "play_suite", fake):
                self.assertEqual(ladder.main([out, "--pick", "2", "--games", "1"]), 0)
            pairs = sorted((a, b) for la, a, lb, b in calls if la != lb)
            self.assertEqual(pairs, [(1, 4), (4, 1), (4, 4)])  # init-update 1, init-update 2, update 1-update 2
            train.save(os.path.join(out, "params-1.npz"), params, {"seed": 7, "encoder": 5})
            with mock.patch.object(evaluate, "play_suite", fake), self.assertRaisesRegex(ValueError, "encoder 5"):
                ladder.main([out, "--pick", "2", "--games", "1"])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_numpy_policy_equals_model_apply(self):
        # The live adapter's NumPy forward pass (duoforge_live.policy) is model.apply: on random parameters and
        # inputs, both log-probabilities and the value agree, and so do the greedy pair and team.
        import jax
        from duoforge_live import policy
        params = model.init(jax.random.PRNGKey(3), features.OBS_SIZE, features.SLOT_FEATURES, TEAM_ACTIONS)
        rng = np.random.default_rng(4)
        n = 64
        obs = rng.random((n, features.OBS_SIZE), dtype=np.float32)
        slots = rng.random((n, 2, 32, features.SLOT_FEATURES), dtype=np.float32)
        mask = rng.random((n, 32, 32)) < rng.random((n, 1, 1))
        mask[:, 0, 0] = True  # at least one pair
        theirs = [np.asarray(x) for x in model.apply(params, obs, slots, mask)]
        numpy_params = jax.tree_util.tree_map(np.asarray, params)
        ours = policy.forward(numpy_params, obs, slots, mask)
        for a, b in zip(ours, theirs):
            self.assertTrue(np.allclose(a, b, rtol=1e-5, atol=1e-4))
        allowed = mask.reshape(n, -1)
        self.assertTrue((np.where(allowed, ours[0], -np.inf).argmax(axis=1) ==
                         np.where(allowed, theirs[0], -np.inf).argmax(axis=1)).all())
        self.assertTrue((ours[1].argmax(axis=1) == theirs[1].argmax(axis=1)).all())


if __name__ == "__main__":
    unittest.main()
