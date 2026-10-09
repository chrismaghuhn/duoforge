"""The compute ledger of stage 3 P1 (Learner v2 plan 2026-10-08-stage3-p1-learner, task 6): CPU core-seconds and
GPU-seconds, measured the same way in the pilot and the continuation control."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from duoforge_learn import ledger


def _busy(seconds):
    end = time.process_time() + seconds
    x = 0
    while time.process_time() < end:
        x += 1
    return x


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_ledger_counts_cpu_and_device_and_survives_restart(self):
        import jax
        import jax.numpy as jnp
        book = ledger.Ledger(self.path)
        with book.phase("collect"):
            _busy(0.2)
        f = jax.jit(lambda a: a @ a)
        a = jnp.ones((256, 256), dtype=jnp.float32)
        with book.phase("update"):
            with book.device():
                jax.block_until_ready(f(a))
            with self.assertRaisesRegex(RuntimeError, "nest"):
                with book.device():
                    with book.device():
                        pass
        book.save()
        first = json.loads(self.path.read_text())
        self.assertGreaterEqual(first["cpu_core_seconds"], 0.15)
        self.assertGreater(first["gpu_seconds"], 0.0)
        self.assertGreaterEqual(first["phases"]["collect"]["cpu_core_seconds"], 0.15)
        self.assertEqual(first["phases"]["collect"]["gpu_seconds"], 0.0)
        self.assertGreater(first["phases"]["update"]["gpu_seconds"], 0.0)
        self.assertEqual(first["processes"], 1)
        # A restart: a second Ledger on the same path adds its own process to the totals.
        again = ledger.Ledger(self.path)
        with again.phase("collect"):
            _busy(0.1)
        again.save()
        second = json.loads(self.path.read_text())
        self.assertEqual(second["processes"], 2)
        self.assertGreaterEqual(second["cpu_core_seconds"], first["cpu_core_seconds"] + 0.08)
        self.assertGreaterEqual(second["gpu_seconds"], first["gpu_seconds"])
        self.assertGreaterEqual(second["phases"]["collect"]["cpu_core_seconds"],
                                first["phases"]["collect"]["cpu_core_seconds"] + 0.08)
        # A save twice in one process does not count the process or its seconds twice.
        again.save()
        third = json.loads(self.path.read_text())
        self.assertEqual(third["processes"], 2)
        self.assertEqual(third["gpu_seconds"], second["gpu_seconds"])
        self.assertLess(third["cpu_core_seconds"], second["cpu_core_seconds"] + 0.05)

    def test_ledger_inside_the_repository_is_refused(self):
        inside = Path(__file__).resolve().parents[2] / "ledger-should-not-exist.json"
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            ledger.Ledger(inside)
        self.assertFalse(inside.exists())

    def test_a_ledger_of_another_schema_is_refused(self):
        self.path.write_text(json.dumps({"schema": 99, "cpu_core_seconds": 1.0}))
        with self.assertRaisesRegex(ValueError, "schema"):
            ledger.Ledger(self.path)


_SMALL = ["--envs", "4", "--workers", "1", "--rollout", "4", "--eval-every", "1000", "--minibatch", "64",
          "--snapshot-every", "1000", "--league-slots", "0", "--self-play-share", "1"]
_LEAGUE = ["--league-slots", "2", "--self-play-share", "0.5", "--slot-refresh", "1", "--snapshot-every", "1"]


def _train(argv):
    from duoforge_learn import train
    return train.run(train.parse(argv))


def _log(out):
    with open(os.path.join(out, "log.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f if '"update"' in line and '"resume"' not in line]


class ControlTest(unittest.TestCase):
    """Task 7: the continuation control stops at a ledger budget and runs each update and each collection step on
    the default device or the CPU by a deterministic share."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "run")
        self.book = os.path.join(self.tmp.name, "ledger.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_train_stops_at_the_ledger_budget(self):
        from duoforge_learn import train
        with self.assertRaises(SystemExit):  # a budget needs a ledger
            train.parse(["--out", self.out, "--stop-cpu-core-seconds", "1"] + _SMALL)
        args = train.parse(["--out", self.out, "--ledger", self.book, "--stop-cpu-core-seconds", "1e-6"] + _SMALL)
        self.assertEqual(args.minutes, 0.0)  # the budget replaces the 60-minute default
        self.assertEqual(train.run(args), 0)
        rows = _log(self.out)
        self.assertEqual([r["update"] for r in rows], [1])
        self.assertEqual(rows[-1]["stopped"], "budget")
        first = json.loads(Path(self.book).read_text())
        self.assertEqual(first["processes"], 1)
        self.assertGreater(first["cpu_core_seconds"], 0.0)
        self.assertGreater(first["phases"]["collect"]["cpu_core_seconds"], 0.0)
        self.assertGreater(first["phases"]["update"]["gpu_seconds"], 0.0)
        # A resume with a larger budget goes on and adds its process to the same ledger.
        self.assertEqual(_train(["--resume", self.out, "--stop-cpu-core-seconds", "1e9", "--updates", "3"]), 0)
        self.assertEqual([r["update"] for r in _log(self.out)], [1, 2, 3])
        second = json.loads(Path(self.book).read_text())
        self.assertEqual(second["processes"], 2)
        self.assertGreater(second["cpu_core_seconds"], first["cpu_core_seconds"])
        # A resume cannot move the arm's spending to another ledger.
        with self.assertRaisesRegex(SystemExit, "ledger"):
            _train(["--resume", self.out, "--ledger", os.path.join(self.tmp.name, "other.json"), "--updates", "4"])

    def test_device_shares_are_deterministic_and_resumable(self):
        self.assertEqual(_train(["--out", self.out, "--ledger", self.book, "--updates", "3",
                                 "--update-gpu-share", "0.25", "--act-gpu-share", "0.5"] + _SMALL + _LEAGUE), 0)
        self.assertEqual(_train(["--resume", self.out, "--updates", "8"]), 0)
        rows = _log(self.out)
        self.assertEqual([r["update_device"] for r in rows],
                         ["cpu", "cpu", "cpu", "default", "cpu", "cpu", "cpu", "default"])
        # 4 rollout steps + 1 bootstrap call per update: every second collection call on the default device.
        self.assertEqual([r["act_default_calls"] for r in rows], [2, 3, 2, 3, 2, 3, 2, 3])
        # Both shares at 0: nothing runs in a device section.
        other = os.path.join(self.tmp.name, "cpu-only")
        book = os.path.join(self.tmp.name, "cpu-only.json")
        self.assertEqual(_train(["--out", other, "--ledger", book, "--updates", "2", "--update-gpu-share", "0",
                                 "--act-gpu-share", "0"] + _SMALL + _LEAGUE), 0)  # league opponents too
        self.assertEqual(json.loads(Path(book).read_text())["gpu_seconds"], 0.0)
        from duoforge_learn import train
        for bad in ("-0.1", "1.5"):
            with self.assertRaises(SystemExit):
                train.parse(["--out", other, "--updates", "1", "--update-gpu-share", bad] + _SMALL)



def _init_checkpoint(path, encoder=4, ext_supported=0):
    """An untrained format-2 v2-S network of encoder `encoder`'s layout, pool data (the P1 continuation's start in
    miniature: params-49333 is encoder 4)."""
    import jax
    import duoforge
    from duoforge import _layout, features
    from duoforge_learn import checkpoint, policy
    cfg = policy.v2_config("S")
    names = list(features.feature_names(encoder))
    params = jax.device_get(policy.make(cfg, names).init(jax.random.PRNGKey(3)))
    with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as context:
        checkpoint.save(path, params, {
            "model": cfg, "encoder": encoder, "ext_supported": ext_supported, "features": names,
            "slot_features": list(features.SLOT_FEATURE_NAMES),
            "data": {"kind": "pool", "fingerprint": context.fingerprint().hex()}, "teams": {}, "update": 0,
            "decisions": 0, "ids": checkpoint.ids_of(context)})


class KeepInitEncoderTest(unittest.TestCase):
    """--keep-init-encoder: the P1 continuation control keeps params-49333's encoder 4 (pilot and control differ
    only in method, not in features); without it a run from an older encoder is widened as before."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.init = os.path.join(self.tmp.name, "init-e4.npz")
        _init_checkpoint(self.init)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_run_keeps_encoder_4_through_league_magnet_eval_and_resume(self):
        import numpy as np
        from duoforge import features
        from duoforge_learn import checkpoint, policy, runstate
        out = os.path.join(self.tmp.name, "kept")
        self.assertEqual(_train(["--out", out, "--init", self.init, "--keep-init-encoder", "--updates", "2",
                                 "--minutes", "0", "--kl-ref", "magnet", "--kl-coef", "0.01"] + _SMALL + _LEAGUE), 0)
        names4 = list(features.feature_names(4))
        state = runstate.load_state(out)
        self.assertEqual(state["encoder"], 4)
        self.assertEqual(state["features"], names4)
        self.assertTrue(state["train"]["keep_init_encoder"])
        for update in (0, 1, 2):  # params-0 is the init; 1 and 2 are league snapshots (--snapshot-every 1)
            params, config = checkpoint.load_trained(os.path.join(out, f"params-{update}.npz"))
            self.assertEqual((config["encoder"], config["features"]), (4, names4))
            want = policy.make(config["model"], names4).init(__import__("jax").random.PRNGKey(0))
            self.assertEqual(checkpoint.flatten(params).keys(), checkpoint.flatten(want).keys())
            for k, v in checkpoint.flatten(want).items():
                self.assertEqual(checkpoint.flatten(params)[k].shape, v.shape, k)  # the input width of encoder 4
        widened, config = checkpoint.load_current(os.path.join(out, "params-2.npz"))  # later code widens it
        self.assertEqual(config["encoder"], features.ENCODER)
        self.assertEqual(features.obs_size(4), len(names4))
        self.assertTrue(any("vs_previous" in r for r in _log(out)))  # the in-run evaluation played encoder 4
        # A resume continues on encoder 4, with a checkpoint as the KL reference (read in the run's layout).
        self.assertEqual(_train(["--resume", out, "--updates", "3", "--minutes", "0", "--kl-ref", self.init]), 0)
        self.assertEqual([r["update"] for r in _log(out)][-1], 3)
        state = runstate.load_state(out)
        self.assertEqual((state["encoder"], state["features"]), (4, names4))
        self.assertTrue(np.isfinite(_log(out)[-1]["loss"]))

    def test_without_the_flag_the_run_is_widened_to_the_current_encoder(self):
        from duoforge import features
        from duoforge_learn import runstate
        out = os.path.join(self.tmp.name, "widened")
        self.assertEqual(_train(["--out", out, "--init", self.init, "--updates", "1", "--minutes", "0"] + _SMALL), 0)
        state = runstate.load_state(out)
        self.assertEqual(state["encoder"], features.ENCODER)
        self.assertEqual(state["features"], list(features.FEATURE_NAMES))
        self.assertNotIn("keep_init_encoder", state["train"])  # the saved options are as before
        with self.assertRaisesRegex(SystemExit, "keep_init_encoder"):  # a resume cannot switch it on
            _train(["--resume", out, "--updates", "2", "--keep-init-encoder"])

    def test_a_kl_reference_of_another_layout_is_refused(self):
        other = os.path.join(self.tmp.name, "ref-e3.npz")
        _init_checkpoint(other, encoder=3)
        with self.assertRaisesRegex(SystemExit, "layout"):
            _train(["--out", os.path.join(self.tmp.name, "ref"), "--init", self.init, "--keep-init-encoder",
                    "--kl-ref", other, "--kl-coef", "0.01", "--updates", "1", "--minutes", "0"] + _SMALL)

    def test_an_init_with_view_extension_features_keeps_its_mask(self):
        import duoforge
        from duoforge import _layout, features
        from duoforge.context import reference_setups
        from duoforge_learn import runstate
        with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, reference_setups([0]), 1, 1) as b:
            mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)
        self.assertNotEqual(mask, 0)
        init = os.path.join(self.tmp.name, "init-e4-ext.npz")
        _init_checkpoint(init, ext_supported=mask)
        out = os.path.join(self.tmp.name, "ext")
        self.assertEqual(_train(["--out", out, "--init", init, "--keep-init-encoder", "--updates", "1",
                                 "--minutes", "0"] + _SMALL), 0)
        state = runstate.load_state(out)
        self.assertEqual((state["encoder"], state["ext_supported"]), (4, mask))

    def test_the_flag_needs_init_and_the_inits_mask(self):
        from duoforge_learn import train
        with self.assertRaises(SystemExit):
            train.parse(["--out", os.path.join(self.tmp.name, "no-init"), "--keep-init-encoder", "--updates", "1"]
                        + _SMALL)
        with self.assertRaisesRegex(SystemExit, "ext_supported"):
            _train(["--out", os.path.join(self.tmp.name, "mask"), "--init", self.init, "--keep-init-encoder",
                    "--ext-supported", "1", "--updates", "1", "--minutes", "0"] + _SMALL)


if __name__ == "__main__":
    unittest.main()
