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
from duoforge_learn import checkpoint, model, train
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

    def test_train_init_widens_encoder3_format2_and_preserves_zero_column_output(self):
        import jax

        model_config = {"version": 1, "hidden": 16, "option_hidden": 8}
        old_params = model.init(jax.random.PRNGKey(314), features.obs_size(3), features.SLOT_FEATURES, TEAM_ACTIONS,
                                hidden=model_config["hidden"], option_hidden=model_config["option_hidden"])
        with tempfile.TemporaryDirectory(prefix="duoforge-train-init-") as folder, duoforge.Context() as context:
            old_path = os.path.join(folder, "encoder-3.npz")
            config = {
                "model": model_config,
                "encoder": 3,
                "ext_supported": 0,
                "features": list(features.FEATURE_NAMES[:features.obs_size(3)]),
                "slot_features": list(features.SLOT_FEATURE_NAMES),
                "data": {"kind": "closure", "fingerprint": context.fingerprint().hex()},
                "teams": {"ids": ["A", "B"], "sha256": ["", ""]},
                "update": 7,
                "decisions": 123,
                "ids": checkpoint.ids_of(context),
            }
            checkpoint.save(old_path, old_params, config)
            args = train.parse(["--init", old_path, "--out", os.path.join(folder, "run"), "--updates", "1",
                                "--minutes", "0"])
            new_params, new_config = train._load_init(args)
            self.assertEqual(new_config["format"], 2)
            self.assertIn("ids", new_config)
            self.assertEqual(new_config["encoder"], features.ENCODER)
            self.assertEqual(args.model, "v1")
            self.assertEqual(args.data_kind, "closure")

            rng = np.random.default_rng(20261003)
            obs3 = rng.standard_normal((4, features.obs_size(3))).astype(np.float32)
            obs4 = np.zeros((4, features.OBS_SIZE), dtype=np.float32)
            obs4[:, :features.obs_size(3)] = obs3
            self.assertFalse(obs4[:, features.obs_size(3):].any())
            slots = rng.standard_normal((4, 2, 32, features.SLOT_FEATURES)).astype(np.float32)
            mask = np.ones((4, 32, 32), dtype=bool)
            output3 = model.apply(old_params, obs3, slots, mask)
            output4 = model.apply(new_params, obs4, slots, mask)
            for old_output, new_output in zip(output3, output4):
                np.testing.assert_allclose(np.asarray(new_output), np.asarray(old_output), rtol=1e-6, atol=1e-6)

    def test_train_init_refuses_unknown_encoder_and_format1(self):
        import jax

        model_config = {"version": 1, "hidden": 8, "option_hidden": 4}
        params = model.init(jax.random.PRNGKey(2718), features.obs_size(3), features.SLOT_FEATURES, TEAM_ACTIONS,
                            hidden=model_config["hidden"], option_hidden=model_config["option_hidden"])
        with tempfile.TemporaryDirectory(prefix="duoforge-train-init-refusals-") as folder, duoforge.Context() as ctx:
            config = {
                "model": model_config,
                "encoder": 9,
                "ext_supported": 0,
                "features": list(features.FEATURE_NAMES[:features.obs_size(3)]),
                "slot_features": list(features.SLOT_FEATURE_NAMES),
                "data": {"kind": "closure", "fingerprint": ctx.fingerprint().hex()},
                "teams": {"ids": ["A", "B"], "sha256": ["", ""]},
                "update": 0,
                "decisions": 0,
                "ids": checkpoint.ids_of(ctx),
            }
            unknown = os.path.join(folder, "unknown-encoder.npz")
            checkpoint.save(unknown, params, config)
            args = train.parse(["--init", unknown, "--out", os.path.join(folder, "unknown-run"), "--updates", "1",
                                "--minutes", "0"])
            with self.assertRaisesRegex(SystemExit, "encoder 9"):
                train._load_init(args)

            legacy = os.path.join(folder, "format-1.npz")
            train.save(legacy, params, {"seed": 1})
            args = train.parse(["--init", legacy, "--out", os.path.join(folder, "legacy-run"), "--updates", "1",
                                "--minutes", "0"])
            with self.assertRaisesRegex(SystemExit, "format 1"):
                train._load_init(args)

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
