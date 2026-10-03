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


class TrainerTest(unittest.TestCase):
    """bc.main on a fixture dataset: 3 training games and 1 validation game of our own reference battle."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        from . import test_bc_numpy as fixture
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_bc_train_"))
        cls.data = fixture.build_fixture(cls.tmp, natures=fixture.split_variants(3, 1))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_bc(self, name, *extra):
        from duoforge_learn import bc
        out = self.tmp / name
        bc.main(["--data", str(self.data), "--out", str(out), "--preset", "S", "--batch", "8", "--seed", "5", *extra])
        return out

    def test_bc_runs_and_writes_a_checkpoint(self):
        import json
        import duoforge
        from duoforge import _layout
        from duoforge_learn import bc, checkpoint
        out = self.run_bc("one", "--epochs", "1")
        params, config = checkpoint.load_current(out / "bc.npz")
        for key in checkpoint.FORMAT2_KEYS + ("ext_supported", "train", "ids"):
            self.assertIn(key, config)
        self.assertEqual((config["update"], config["teams"], config["data"]["kind"]), (0, [], "pool"))
        self.assertEqual(config["train"]["seed"], 5)
        with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as context:
            self.assertEqual(config["ext_supported"], bc_data.bc_mask(context))
            self.assertEqual(config["ids"], bc.ids_of(context))
            self.assertEqual(config["data"]["fingerprint"], context.fingerprint().hex())
        log = [json.loads(line) for line in (out / "bc-log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["epoch"] for r in log], [1])
        self.assertGreater(log[0]["val_rows"], 0)

    def test_bc_loss_falls(self):
        import json
        out = self.run_bc("three", "--epochs", "3", "--patience", "3")
        log = [json.loads(line) for line in (out / "bc-log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertLess(log[-1]["train_nll"], log[0]["train_nll"])

    def test_bc_refuses_output_in_repo(self):
        from pathlib import Path
        from duoforge_learn import bc
        inside = Path(__file__).resolve().parents[2] / "bc-out-never"
        with self.assertRaises((ValueError, SystemExit)):
            bc.main(["--data", str(self.data), "--out", str(inside), "--epochs", "1"])
        self.assertFalse(inside.exists())

    def test_empty_validation_is_refused(self):
        from . import test_bc_numpy as fixture
        from duoforge_learn import bc
        only_train = fixture.build_fixture(self.tmp, natures=fixture.split_variants(2, 0), name="trainonly")
        with self.assertRaisesRegex(ValueError, "validation"):
            bc.main(["--data", str(only_train), "--out", str(self.tmp / "noval"), "--epochs", "1"])

    def test_bc_deterministic(self):
        # two runs with the same seed on the CPU give the same parameters, byte for byte
        import os
        import subprocess
        import sys
        from pathlib import Path
        env = {**os.environ, "JAX_PLATFORMS": "cpu"}
        root = Path(__file__).resolve().parents[2]
        outs = []
        for name in ("det-a", "det-b"):
            out = self.tmp / name
            subprocess.run([sys.executable, "-m", "duoforge_learn.bc", "--data", str(self.data), "--out", str(out),
                            "--preset", "S", "--batch", "8", "--seed", "9", "--epochs", "2"], env=env, cwd=root,
                           check=True, capture_output=True)
            with np.load(out / "bc.npz") as z:
                outs.append({k: z[k].tobytes() for k in z.files if k != "config"})
        self.assertEqual(outs[0], outs[1])


if __name__ == "__main__":
    unittest.main()
