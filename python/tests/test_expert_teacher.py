"""duoforge.python.expert_teacher: the P1 honest teacher (plan C3, decision 0024).

Synthetic tables, masks and a foe-sensitive NumPy network only; no trained
weights, real data or run outputs. The contract is pinned by literals.
"""
import unittest

import numpy as np

from duoforge_search import lookahead
from duoforge_search.expert_data import SparsePolicy


def _mask(ids):
    mask = np.zeros((32, 32), bool)
    mask.flat[list(ids)] = True
    return mask


def _log_softmax(logits, ids):
    top = float(np.max(logits[ids]))
    return logits - (top + np.log(np.sum(np.exp(logits[ids] - top))))


class FullSpace(unittest.TestCase):
    LEGAL = (3, 7, 40, 41, 100, 200, 300, 400, 500, 513)

    def test_full_target_kl_and_displacement_ties(self):
        from duoforge_search import expert as ex
        mask = _mask(self.LEGAL)
        candidates = np.array([40, 7, 3, 100, 200, 300, 400, 500], np.int64)  # prior-rank order
        # The raw action already among the candidates changes nothing.
        kept = ex.include_student(candidates, 100, mask)
        np.testing.assert_array_equal(kept.ids, candidates)
        self.assertEqual((kept.raw_index, kept.displaced), (3, None))
        # An absent raw action displaces the lowest-ranked candidate; K stays 8.
        shown = ex.include_student(candidates, 513, mask)
        np.testing.assert_array_equal(shown.ids, [40, 7, 3, 100, 200, 300, 400, 513])
        self.assertEqual((shown.raw_index, shown.displaced), (7, 500))
        self.assertEqual(shown.ids.dtype, np.int64)
        # Tied priors: select ranks ties to the lower flat index, so the displaced one is the
        # higher index of the tie, whatever the raw action's own prior.
        logp = np.full(1024, -50.0)
        logp[list(self.LEGAL)] = [-1.0, -2.0, -2.0, -2.0, -3.0, -3.0, -4.0, -4.0, -4.0, -9.0]
        tied, _ = lookahead.select(logp, mask, 8)
        np.testing.assert_array_equal(tied, [3, 7, 40, 41, 100, 200, 300, 400])
        swapped = ex.include_student(tied, 500, mask)
        np.testing.assert_array_equal(swapped.ids, [3, 7, 40, 41, 100, 200, 300, 500])
        self.assertEqual(swapped.displaced, 400)
        # Fewer legal pairs than K: every legal pair is a candidate, the raw action included.
        few = _mask((5, 9))
        small = ex.include_student(np.array([9, 5]), 5, few)
        np.testing.assert_array_equal(small.ids, [9, 5])
        self.assertEqual(small.raw_index, 1)
        for bad in ((np.array([40, 40, 3]), 3), (np.array([40, 1]), 40), (candidates, 1), (candidates, 1024),
                    (candidates, -1), (candidates, True), (np.append(candidates, 513), 513),
                    (np.array([], np.int64), 3), (np.array([40.0, 7.0]), 7)):
            with self.subTest(candidates=bad[0], raw=bad[1]), self.assertRaises(ValueError):
                ex.include_student(bad[0], bad[1], mask)
        with self.assertRaises(ValueError):
            ex.include_student(candidates, 513, mask, k=9)  # K is pinned to 8
        # The full target holds the sparse mass at its joint ids and zero elsewhere.
        policy = SparsePolicy(np.array([40, 7, 513], np.int64), np.array([0.5, 0.25, 0.25]))
        full = ex.full_target(policy, mask)
        self.assertEqual((full.shape, full.dtype), ((1024,), np.float64))
        self.assertEqual((full[40], full[7], full[513]), (0.5, 0.25, 0.25))
        self.assertEqual(np.count_nonzero(full), 3)
        ex.full_target(SparsePolicy(np.array([40, 7], np.int64), np.array([0.5, 0.5 + 9e-7])), mask)
        for ids, probs in (([40, 1], [0.5, 0.5]), ([40, 40], [0.5, 0.5]), ([40, 7], [1.5, -0.5]),
                           ([40, 7], [0.5, np.nan]), ([40, 7], [0.5, 0.5 + 2e-6]), ([40, 1024], [0.5, 0.5]),
                           ([-1, 7], [0.5, 0.5]), (list(self.LEGAL[:9]), [1 / 9] * 9)):
            with self.subTest(ids=ids, probs=probs), self.assertRaises(ValueError):
                ex.full_target(SparsePolicy(np.array(ids, np.int64), np.array(probs, np.float64)), mask)
        # KL(tau || pi) against the student's full-legal distribution differs from the
        # candidate-only renormalization a wrong loss would use.
        logits = np.random.default_rng(20261014).normal(size=1024)
        legal = np.flatnonzero(mask.reshape(-1))
        full_legal = _log_softmax(logits, legal)
        candidate_only = _log_softmax(logits, policy.ids)
        nz = full > 0
        kl_full = float(np.sum(full[nz] * (np.log(full[nz]) - full_legal[nz])))
        kl_cand = float(np.sum(full[nz] * (np.log(full[nz]) - candidate_only[nz])))
        sparse = float(np.sum(policy.probs * (np.log(policy.probs) - full_legal[policy.ids])))
        self.assertAlmostEqual(kl_full, sparse, places=12)
        self.assertGreater(kl_full - kl_cand, 0.1)


if __name__ == "__main__":
    unittest.main()
