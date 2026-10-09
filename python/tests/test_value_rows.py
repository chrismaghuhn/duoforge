"""duoforge.python.value_rows: value bits at a fixed shape independent of a row's position, its neighbours and
the padding (stage 3 P2 plan, Task 1; Lookahead's docstring claims it, test_search samples it).

The result holds only under the conditions it reports (JAX, CPU model and ISA flags, XLA flags, device,
capacity): a green CI says nothing about another CPU or the GPU; rowprobe's CLI measures those privately.
"""
import os
os.environ.setdefault("JAX_PLATFORMS", "cpu")

import unittest

import numpy as np


class _Fake:
    """A value head with a deliberate dependence on the call, for negative controls."""

    def __init__(self, kind):
        self.kind = kind

    def value(self, params, rows):
        rows = np.asarray(rows, np.float32)
        base = rows[:, 0] * np.float32(0.5) + rows[:, 1]
        if self.kind == "position":
            return base + np.arange(len(rows), dtype=np.float32) * np.float32(1e-6)
        if self.kind == "neighbour":
            return base + rows[:, 0].mean(dtype=np.float32) * np.float32(1e-3)
        return base + np.float32(1e-3) * (np.abs(rows).sum(axis=1) == 0).sum(dtype=np.float32)  # padding


class ValueRows(unittest.TestCase):
    def test_value_rows_position_and_neighbour_independent(self):
        from duoforge_search import rowprobe
        from python.tests.test_search import _v2s
        rows = rowprobe.encoded_rows(1536, seed=7)
        self.assertEqual(rows.dtype, np.float32)
        self.assertEqual(len({r.tobytes() for r in rows}), 1536)  # distinct real encoded rows
        model, params = _v2s()
        out = rowprobe.row_independence(model, params, rows, capacity=1024, seed=7)
        self.assertEqual((out["position_bits"], out["neighbour_bits"], out["padding_bits"]), (0, 0, 0), out)
        self.assertEqual(out["conditions"]["capacity"], 1024)
        for key in ("jax", "cpu", "xla_flags", "device", "jax_devices"):
            self.assertIn(key, out["conditions"])
        # The probe itself must see a dependence when there is one.
        fake_rows = np.random.default_rng(3).normal(size=(160, 4)).astype(np.float32)
        for kind, key in (("position", "position_bits"), ("neighbour", "neighbour_bits"), ("padding", "padding_bits")):
            with self.subTest(kind=kind):
                got = rowprobe.row_independence(_Fake(kind), None, fake_rows, capacity=64, seed=1)
                self.assertGreater(got[key], 0)


if __name__ == "__main__":
    unittest.main()
