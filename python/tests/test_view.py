"""NumPy-only view binding round trips, ABI generation and buffer guards."""
import os
from pathlib import Path
import unittest

import numpy as np

import duoforge
from duoforge import _layout, privileged, view
from tools.layout.gen_view_layout import generate

from ._pivot_fixture import SETUP, play_to_pivot

STEPS = 128  # lockstep steps of the random round trip


class Views(unittest.TestCase):
    def test_generated_layout_is_current(self):
        source = Path(_layout.__file__).with_name("_view_layout.py")
        self.assertEqual(source.read_text(encoding="utf-8"), generate(os.environ["DUOFORGE_LAYOUT_DUMP"]))

    def test_random_batch_roundtrip_and_reuse(self):
        # Every supported record round-trips through a one-environment world of its own, so a PIVOT record counts even
        # when another environment's record is refused: since the view audit of 2026-10-10 a PIVOT is public only when no
        # move is left to run, and the PIVOTs with a move left are refused (counted, never rebuilt).
        C = _layout.CONSTANTS
        setups = duoforge.reference_setups([0, 1, 2, 3])
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, setups, 3, 42) as roots:
            worlds = [duoforge.Batch(ctx, setups[e:e + 1], 1, 43 + e) for e in range(4)]
            try:
                players = np.array([0, 1, 0, 1], np.uint32)
                policy = duoforge.RandomPolicy(44, 4)
                first = None
                checked = pivots = refused_pivots = 0
                for _ in range(STEPS):
                    roots.query_factored()
                    views, statuses = roots.public(players)
                    self.assertTrue(np.isin(statuses, [0, C["DUOFORGE_E_UNSUPPORTED"]]).all())
                    if first is None:
                        first = views
                    self.assertIs(first, views)
                    pivot = roots.requests["boundary_kind"][np.arange(4), players] == C["DUOFORGE_BOUNDARY_PIVOT"]
                    refused_pivots += int((pivot & (statuses != 0)).sum())
                    for e in np.flatnonzero(statuses == 0):
                        p = int(players[e])
                        w = worlds[e]
                        record = views[e:e + 1].copy()
                        h = view.hypotheses(1)
                        h[0] = privileged.hypothesis(roots, int(e), p)
                        self.assertFalse(w.from_view(record, h).any())
                        again, ws = w.public(np.array([p], np.uint32))
                        self.assertFalse(ws.any())
                        np.testing.assert_array_equal(record, again)
                        w.query_factored()
                        np.testing.assert_array_equal(roots.observations[e, p], w.observations[0, p])
                        np.testing.assert_array_equal(roots.domains[e, p], w.domains[0, p])
                        checked += 1
                        if int(record["boundary"][0]) == C["DUOFORGE_BOUNDARY_PIVOT"]:
                            pivots += 1
                            self.assertEqual(int(record["foe_pending_mask"][0]), 0)  # no pending command is public
                    roots.step_factored(policy.choose_factored(roots))
                    roots.reset_terminal()
            finally:
                for w in worlds:
                    w.close()
            self.assertGreater(checked, 200)
            self.assertGreater(refused_pivots, 0)
            # Random play almost never reaches a public PIVOT (one needs a Protect up and no move left): the scripted one.
            with duoforge.Batch(ctx, duoforge.reference_setups([SETUP]), 1, 45) as b,                     duoforge.Batch(ctx, duoforge.reference_setups([SETUP]), 1, 46) as w:
                play_to_pivot(b)
                for p in (0, 1):
                    record, st = b.public(np.array([p], np.uint32))
                    self.assertEqual(int(st[0]), 0)
                    self.assertEqual(int(record["boundary"][0]), C["DUOFORGE_BOUNDARY_PIVOT"])
                    self.assertEqual(int(record["foe_pending_mask"][0]), 0)
                    record = record.copy()
                    h = view.hypotheses(1)
                    h[0] = privileged.hypothesis(b, 0, p)
                    self.assertFalse(w.from_view(record, h).any())
                    again, ws = w.public(np.array([p], np.uint32))
                    self.assertFalse(ws.any())
                    np.testing.assert_array_equal(record, again)
                    w.query_factored()
                    np.testing.assert_array_equal(b.observations[0, p], w.observations[0, p])
                    np.testing.assert_array_equal(b.domains[0, p], w.domains[0, p])
                    pivots += 1
            self.assertGreater(pivots, 0)

    def test_public_causes_name_the_view_refusals(self):
        # decision 0026 section 4: the mask depends only on the player's view, and public refuses exactly while it is
        # nonzero (a zero mask with a refusal is another cause: a PIVOT, a foe Substitute, ...)
        C = _layout.CONSTANTS
        sleep, confusion = C["DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP"], C["DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION"]
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                duoforge.Batch(ctx, duoforge.reference_setups([0, 1, 2, 3]), 3, 52) as roots:
            players = np.array([0, 1, 1, 0], np.uint32)
            policy = duoforge.RandomPolicy(54, 4)
            seen = {sleep: 0, confusion: 0}
            for _ in range(160):
                roots.query_factored()
                _, statuses = roots.public(players)
                masks, cause_statuses = roots.public_causes(players)
                self.assertFalse(cause_statuses.any())
                for e, p in enumerate(players):
                    ob = roots.observations[e, p]
                    asleep = bool((ob["sides"]["members"]["status"] == C["DUOFORGE_AILMENT_SLEEP"]).any())
                    confused = bool(ob["sides"]["positions"]["confused"].any())
                    self.assertEqual(bool(masks[e] & sleep), asleep, e)
                    self.assertEqual(bool(masks[e] & confusion), confused, e)
                    self.assertEqual(int(masks[e]) & ~(sleep | confusion), 0)  # ILLUSION_POSSIBLE stays 0 until Illusion
                    if masks[e]:
                        self.assertEqual(int(statuses[e]), C["DUOFORGE_E_UNSUPPORTED"])
                    seen[sleep] += asleep
                    seen[confusion] += confused
                roots.step_factored(policy.choose_factored(roots))
                roots.reset_terminal()
            self.assertGreater(seen[sleep], 0)
            with self.assertRaises(ValueError):
                roots.public_causes(np.array([0, 2, 0, 0], np.uint32))

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
