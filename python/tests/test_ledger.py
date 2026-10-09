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


if __name__ == "__main__":
    unittest.main()
