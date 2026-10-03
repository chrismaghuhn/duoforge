"""duoforge.python.bc: the behavior-cloning trainer and train.py --init (M11 BC spec), with JAX.

Fixture datasets are built from our own reference battle's log (test_bc_numpy.build_fixture) into temporary
directories outside the repository.
"""
import unittest

import numpy as np

from duoforge_learn import bc_data
from duoforge_replay import labels


def _rows(n_decisions, n_teams, rng, forced_first=False):
    """bc_data.Rows with random labels (obs and slots unused by the loss terms)."""
    n = n_decisions + n_teams
    is_team = np.array([False] * n_decisions + [True] * n_teams)
    mask = rng.random((n, 32, 32)) < 0.7
    a = rng.random((n, 32)) < 0.2
    b = rng.random((n, 32)) < 0.3
    if forced_first:
        a[:] = False
        a[:, 5] = True
    pairs = a[:, :, None] & b[:, None, :] & mask
    for i in range(n_decisions):  # every decision has a non-empty set
        if not pairs[i].any():
            j, k = np.argwhere(mask[i])[0]
            pairs[i, j, k] = True
    pairs[is_team] = False
    team = rng.random((n, 360)) < 0.05
    team[~is_team] = False
    for i in np.flatnonzero(is_team):
        team[i, rng.integers(360)] = True
    reason = np.full((n, 2), labels.EXACT, dtype=np.uint8)
    return bc_data.Rows(obs=np.zeros((n, 1), np.float32), slots=np.zeros((n, 1), np.float32), mask=mask,
                        is_team=is_team, label_pairs=pairs, label_team=team, reason=reason,
                        z=rng.choice([-1.0, 1.0], n).astype(np.float32), has_z=rng.random(n) < 0.8,
                        weight=rng.random(n).astype(np.float32) + 0.25, val=np.zeros(n, bool),
                        side=np.zeros(n, np.uint8), fmt=np.array(["f"] * n), replay=np.array([f"r{i}" for i in range(n)]),
                        point=np.arange(n, dtype=np.uint16))


def _log_softmax(x):
    x = x - x.max(axis=1, keepdims=True)
    return x - np.log(np.exp(x).sum(axis=1, keepdims=True))


class LossTest(unittest.TestCase):
    def brute_force(self, logp_pairs, logp_team, value, rows, value_coef):
        nll = []
        for i in range(len(rows)):
            if rows.is_team[i]:
                nll.append(-np.log(sum(np.exp(logp_team[i, k]) for k in range(360) if rows.label_team[i, k])))
            else:
                nll.append(-np.log(sum(np.exp(logp_pairs[i, a * 32 + b]) for a in range(32) for b in range(32)
                                       if rows.label_pairs[i, a, b])))
        w = rows.weight.astype(np.float64)
        policy = (w * np.array(nll)).sum() / w.sum()
        vw = w * rows.has_z
        vmse = (vw * (value - rows.z) ** 2).sum() / vw.sum()
        return policy + value_coef * vmse, policy, vmse

    def check(self, rows, rng):
        from duoforge_learn import bc
        n = len(rows)
        logp_pairs = _log_softmax(rng.standard_normal((n, 1024)))
        logp_team = _log_softmax(rng.standard_normal((n, 360)))
        value = np.tanh(rng.standard_normal(n))
        total, metrics = bc.loss_terms(logp_pairs, logp_team, value, bc.as_batch(rows), 0.25)
        want, policy, vmse = self.brute_force(logp_pairs, logp_team, value, rows, 0.25)
        self.assertAlmostEqual(float(total), want, places=4)
        self.assertAlmostEqual(float(metrics["nll"]), policy, places=4)
        self.assertAlmostEqual(float(metrics["value_mse"]), vmse, places=4)

    def test_loss_matches_brute_force(self):
        rng = np.random.default_rng(11)
        self.check(_rows(4, 2, rng), rng)

    def test_forced_slot_adds_no_information(self):
        # a FORCED slot has one option: the set is {5} x S1, the loss the marginal over the other slot
        rng = np.random.default_rng(12)
        self.check(_rows(5, 0, rng, forced_first=True), rng)

    def test_empty_label_set_raises(self):
        rng = np.random.default_rng(13)
        rows = _rows(3, 1, rng)
        rows.label_pairs[1] = False
        with self.assertRaises(ValueError) as caught:
            bc_data.check_labels(rows)
        self.assertIn("r1", str(caught.exception))
        self.assertIn("point 1", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
