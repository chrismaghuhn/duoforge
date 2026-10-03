"""duoforge.python.batch_setups: Batch.reset_setups (decision 0017).

An environment reset with a new setup equals the same environment of a fresh
batch that holds that setup; a refused entry raises with the per-entry
statuses and leaves its environment, while the others go through; the
inputs are checked before C sees them.
"""
import unittest

import numpy as np

import duoforge
from duoforge import _layout
from duoforge.errors import DuoforgeError

SEED = 0x2026100200000172
INVALID = _layout.CONSTANTS["DUOFORGE_E_INVALID_ARGUMENT"]


class ResetSetupsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = duoforge.Context()

    def tearDown(self):
        self.ctx.close()

    def test_reset_with_new_setup_equals_fresh_batch(self):
        new = duoforge.reference_setups([3, 2])
        with duoforge.Batch(self.ctx, duoforge.reference_setups([0] * 4), 2, SEED) as a, \
                duoforge.Batch(self.ctx, duoforge.reference_setups([0, 3, 0, 2]), 2, SEED) as b:
            a.reset_setups(np.array([1, 3], np.uint32), np.array([5, 7], np.uint32), new)
            b.reset(1, 5)
            b.reset(3, 7)
            for e in range(4):
                self.assertEqual(a.digest(e), b.digest(e))
            self.assertEqual(a.episode(3), 7)
            self.assertEqual(a.setups[1].tobytes(), new[0].tobytes())

    def test_refused_entry_raises_with_entry_statuses(self):
        setups = np.zeros(2, dtype=_layout.SETUP)
        setups[0] = duoforge.reference_setups([3])[0]
        with duoforge.Batch(self.ctx, duoforge.reference_setups([0] * 4), 1, SEED) as a:
            before = a.digest(2)
            with self.assertRaises(DuoforgeError) as caught:
                a.reset_setups(np.array([1, 2], np.uint32), np.array([4, 4], np.uint32), setups)
            self.assertEqual(int(caught.exception.statuses[1]), INVALID)
            self.assertEqual(int(caught.exception.statuses[0]), 0)
            self.assertEqual(a.digest(2), before)
            self.assertEqual(a.episode(1), 4)
            self.assertEqual(a.episode(2), 0)

    def test_wrong_dtype_or_length(self):
        with duoforge.Batch(self.ctx, duoforge.reference_setups([0] * 2), 1, SEED) as a:
            with self.assertRaises(TypeError):
                a.reset_setups(np.array([0], np.int64), np.array([1], np.uint32), duoforge.reference_setups([1]))
            with self.assertRaises(ValueError):
                a.reset_setups(np.array([0, 1], np.uint32), np.array([1], np.uint32),
                               duoforge.reference_setups([1, 1]))


if __name__ == "__main__":
    unittest.main()
