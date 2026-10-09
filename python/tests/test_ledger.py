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


if __name__ == "__main__":
    unittest.main()
