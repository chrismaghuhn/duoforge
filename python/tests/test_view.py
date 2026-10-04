"""NumPy-only view binding round trips, ABI generation and buffer guards."""
import os
from pathlib import Path
import unittest

import numpy as np

import duoforge
from duoforge import _layout, privileged, view
from tools.layout.gen_view_layout import generate


class Views(unittest.TestCase):
    def test_generated_layout_is_current(self):
        source = Path(_layout.__file__).with_name("_view_layout.py")
        self.assertEqual(source.read_text(encoding="utf-8"), generate(os.environ["DUOFORGE_LAYOUT_DUMP"]))

    def test_random_batch_roundtrip_and_reuse(self):
        with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0, 1, 2, 3]), 3, 42) as roots, \
                duoforge.Batch(ctx, duoforge.reference_setups([0, 1, 2, 3]), 4, 43) as worlds:
            players = np.array([0, 1, 0, 1], np.uint32)
            policy = duoforge.RandomPolicy(44, 4)
            first = None
            checked = 0
            pivots = 0
            for _ in range(64):
                roots.query_factored()
                views, statuses = roots.public(players)
                self.assertTrue(np.isin(statuses, [0, _layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"]]).all())
                if first is None:
                    first = views
                self.assertIs(first, views)
                if not statuses.any():
                    h = view.hypotheses(4)
                    for e, p in enumerate(players):
                        h[e] = privileged.hypothesis(roots, e, int(p))
                    self.assertFalse(worlds.from_view(views, h).any())
                    again, ws = worlds.public(players)
                    self.assertFalse(ws.any())
                    np.testing.assert_array_equal(views, again)
                    roots.query_factored()
                    worlds.query_factored()
                    for e, p in enumerate(players):
                        np.testing.assert_array_equal(roots.observations[e, p], worlds.observations[e, p])
                        np.testing.assert_array_equal(roots.domains[e, p], worlds.domains[e, p])
                    checked += 4
                    pivots += int((views["boundary"] == _layout.CONSTANTS["DUOFORGE_BOUNDARY_PIVOT"]).sum())
                roots.step_factored(policy.choose_factored(roots))
                roots.reset_terminal()
            self.assertGreater(checked, 200)
            self.assertGreater(pivots, 0)

    def test_guards_and_atomic_failures(self):
        with duoforge.Context() as ctx, duoforge.Batch(ctx, duoforge.reference_setups([0, 1]), 2, 42) as b:
            players = np.array([0, 1], np.uint32)
            v, _ = b.public(players)
            h = view.hypotheses(2)
            for e, p in enumerate(players):
                h[e] = privileged.hypothesis(b, e, int(p))
            before = b.encode(0)
            for bad, error in ((players.astype(np.uint8), TypeError), (players[:1], ValueError),
                               (np.array([0, 2], np.uint32), ValueError)):
                with self.assertRaises(error):
                    b.public(bad)
            with self.assertRaises(ValueError):
                b.public(np.zeros(4, np.uint32)[::2])
            with self.assertRaises(TypeError):
                b.from_view(np.zeros(2, _layout.OBSERVATION), h)
            with self.assertRaises(ValueError):
                b.from_view(v, h, 3)
            with self.assertRaises(ValueError):
                b.from_view(np.repeat(v, 2)[::2], h)
            unaligned = np.ndarray((2,), dtype=_layout.HYPOTHESIS, buffer=bytearray(h.nbytes + 1), offset=1)
            with self.assertRaises(ValueError):
                b.from_view(v, unaligned)
            self.assertEqual(b.encode(0), before)
            h[0]["revision"] = 99
            st = b.from_view(v, h).copy()
            self.assertNotEqual(int(st[0]), 0)
            self.assertEqual(int(st[1]), 0)
            self.assertEqual(b.encode(0), before)
            self.assertEqual(b.from_view(v[:0], h[:0]).size, 0)
            with self.assertRaises(duoforge.DuoforgeError):
                duoforge.queue_mask(ctx, v[0:1].reshape(()), v[0:1].reshape(()))
            with self.assertRaises(ValueError):
                duoforge.queue_mask(ctx, v, v)
            b.close()
            with self.assertRaises(ValueError):
                b.public(players)
            with self.assertRaises(ValueError):
                privileged.hypothesis(b, 0, 0)


if __name__ == "__main__":
    unittest.main()
