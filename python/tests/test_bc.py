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
    return bc_data.Rows.from_arrays(obs=np.zeros((n, 1), np.float32), slots=np.zeros((n, 1), np.float32), mask=mask,
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
        rows.pair_bits[1] = 0
        with self.assertRaises(ValueError) as caught:
            bc_data.check_labels(rows)
        self.assertIn("r1", str(caught.exception))
        self.assertIn("point 1", str(caught.exception))


class ZeroColumnsJaxTest(unittest.TestCase):
    """Learner v2's review: zero_columns keeps every output identical on rows whose new columns are 0."""

    def check(self, cfg):
        import jax
        from duoforge import features
        from duoforge_learn import checkpoint, policy
        net = policy.make(cfg)
        params = jax.device_get(net.init(jax.random.PRNGKey(3)))
        config = {"model": cfg, "features": list(features.FEATURE_NAMES),
                  "slot_features": list(features.SLOT_FEATURE_NAMES)}
        new = features.columns_of(1 << features.FEATURE_BITS["WIDE_GUARD"] | 1 << features.FEATURE_BITS["AILMENT_TOX"])
        zeroed = checkpoint.zero_columns(params, config, new)
        rng = np.random.default_rng(1)
        n = 6
        obs = rng.random((n, features.OBS_SIZE)).astype(np.float32) * 0.3
        obs[:, [features.FEATURE_NAMES.index(c) for c in new]] = 0.0
        if cfg["version"] == 2:
            from duoforge_learn import columns
            cols = columns.columns()
            for idx in (cols.present, cols.species, cols.item, cols.ability, cols.nature, cols.moves, cols.pp,
                        cols.move_count):
                obs[:, np.asarray(idx).ravel()] = 0.0  # ids stay inside the capacities
        slots = rng.random((n, 2, 32, features.SLOT_FEATURES)).astype(np.float32)
        mask = rng.random((n, 32, 32)) < 0.5
        mask[:, 0, 0] = True
        for a, b in zip(net.apply(params, obs, slots, mask), net.apply(zeroed, obs, slots, mask)):
            np.testing.assert_allclose(np.asarray(a), np.asarray(b), rtol=1e-6, atol=1e-6)

    def test_v1(self):
        from duoforge_learn import policy
        self.check(dict(policy.V1_DEFAULT))

    def test_v2_s(self):
        from duoforge_learn import policy
        self.check(policy.v2_config("S"))


def _bits(*names):
    from duoforge import features
    return sum(1 << features.FEATURE_BITS[n] for n in names)


class InitTest(unittest.TestCase):
    """train.py --init (M11 BC spec section 8) from a BC-like checkpoint: v2-S, kind pool, mask Sand|Snow|Tox."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_init_"))
        cls.ckpt = cls.bc_like("bc.npz")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def bc_like(cls, name, feature_names=None, **override):
        import jax
        import duoforge
        from duoforge import _layout, features
        from duoforge_learn import checkpoint, policy
        names = list(feature_names or features.FEATURE_NAMES)
        cfg = policy.v2_config("S", hidden=64)
        net = policy.make(cfg, names, features.SLOT_FEATURE_NAMES)
        params = jax.device_get(net.init(jax.random.PRNGKey(7)))
        with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as context:
            config = {"model": cfg, "encoder": features.ENCODER,
                      "ext_supported": _bits("WEATHER_SAND", "WEATHER_SNOW", "AILMENT_TOX"),
                      "features": names, "slot_features": list(features.SLOT_FEATURE_NAMES),
                      "data": {"kind": "pool", "fingerprint": context.fingerprint().hex()}, "teams": [], "update": 0,
                      "decisions": 10 ** 9, "ids": checkpoint.ids_of(context), "train": {"seed": 1, "bc": {}}}
        config.update(override)
        config = {k: v for k, v in config.items() if v is not None}
        path = cls.tmp / name
        checkpoint.save(str(path), params, config)
        return path

    def run_train(self, name, *extra):
        from duoforge_learn import train
        out = self.tmp / name
        code = train.main(["--envs", "8", "--workers", "2", "--rollout", "8", "--updates", "1", "--minutes", "0",
                           "--eval-every", "100", "--minibatch", "256", "--out", str(out), *extra])
        self.assertEqual(code, 0)
        return out

    def log(self, out):
        import json
        return [json.loads(line) for line in (out / "log.jsonl").read_text(encoding="utf-8").splitlines()]

    def same(self, a, b):
        import jax
        la, lb = jax.tree_util.tree_leaves(a), jax.tree_util.tree_leaves(b)
        return len(la) == len(lb) and all(np.array_equal(x, y) for x, y in zip(la, lb))

    def outputs_equal(self, params_a, params_b, cfg, zero_columns=()):
        from duoforge import features
        from duoforge_learn import columns, policy
        net = policy.make(cfg)
        rng = np.random.default_rng(2)
        obs = rng.random((4, features.OBS_SIZE)).astype(np.float32) * 0.3
        cols = columns.columns()
        for idx in (cols.present, cols.species, cols.item, cols.ability, cols.nature, cols.moves, cols.pp,
                    cols.move_count):
            obs[:, np.asarray(idx).ravel()] = 0.0
        obs[:, [features.FEATURE_NAMES.index(c) for c in zero_columns]] = 0.0
        slots = rng.random((4, 2, 32, features.SLOT_FEATURES)).astype(np.float32)
        mask = np.ones((4, 32, 32), bool)
        for a, b in zip(net.apply(params_a, obs, slots, mask), net.apply(params_b, obs, slots, mask)):
            np.testing.assert_allclose(np.asarray(a), np.asarray(b), rtol=1e-6, atol=1e-6)

    def test_init_first_snapshot_equals_bc(self):
        from duoforge_learn import checkpoint
        mask = checkpoint.load(str(self.ckpt))[1]["ext_supported"]
        out = self.run_train("same", "--init", str(self.ckpt), "--ext-supported", hex(mask))
        bc_params, _ = checkpoint.load_current(str(self.ckpt))
        p0, c0 = checkpoint.load(str(out / "params-0.npz"))
        self.assertTrue(self.same(bc_params, p0))
        self.assertEqual((c0["update"], c0["decisions"], c0["ext_supported"]), (0, 0, mask))
        self.assertEqual(c0["train"]["init"]["ext_supported"], mask)
        records = [r for r in self.log(out) if "update" in r]
        self.assertEqual(records[0]["update"], 1)
        self.assertLess(records[0]["decisions"], 10 ** 6)  # counted from 0, not from the BC rows

    def test_init_wider_mask_zeroes_new_columns(self):
        from duoforge import features
        from duoforge_learn import checkpoint
        out = self.run_train("wide", "--init", str(self.ckpt))  # the default: the library's run-time mask
        bc_params, bc_cfg = checkpoint.load_current(str(self.ckpt))
        p0, c0 = checkpoint.load(str(out / "params-0.npz"))
        old, new = bc_cfg["ext_supported"], c0["ext_supported"]
        self.assertTrue(new & ~old)
        self.assertEqual(self.log(out)[0]["init"]["changes"]["ext_supported"], [old, new])
        self.outputs_equal(bc_params, p0, bc_cfg["model"], features.columns_of(new & ~old))

    def test_init_from_an_older_encoder_is_exact(self):
        # an encoder-2 checkpoint (no extension block) initializes a run of the current encoder: load_current widens
        # by name, the old rows stay, the new ones are zero
        from duoforge import features
        from duoforge_learn import checkpoint
        base = list(features.FEATURE_NAMES[:features.BASE_OBS_SIZE])
        old = self.bc_like("enc2.npz", feature_names=base, encoder=2, ext_supported=None)
        out = self.run_train("enc2", "--init", str(old), "--ext-supported", "0")
        widened, cfg = checkpoint.load_current(str(old))
        p0, c0 = checkpoint.load(str(out / "params-0.npz"))
        self.assertEqual((c0["encoder"], c0["features"]), (features.ENCODER, list(features.FEATURE_NAMES)))
        self.assertTrue(self.same(widened, p0))
        self.outputs_equal(widened, p0, cfg["model"], features.columns_of(features.ALL_FEATURES))

    def test_init_inherits_model_and_kind(self):
        from duoforge_learn import checkpoint
        out = self.run_train("inherit", "--init", str(self.ckpt))
        _, c0 = checkpoint.load(str(out / "params-0.npz"))
        _, bc_cfg = checkpoint.load(str(self.ckpt))
        self.assertEqual(c0["model"], bc_cfg["model"])
        self.assertEqual(c0["data"]["kind"], "pool")

    def refused(self, name, *extra):
        with self.assertRaises(SystemExit) as caught:
            self.run_train(name, *extra)
        return str(caught.exception)

    def test_init_refusals(self):
        self.assertIn("model", self.refused("r-model", "--init", str(self.ckpt), "--model", "v2", "--preset", "L"))
        self.assertIn("kind", self.refused("r-kind", "--init", str(self.ckpt), "--data-kind", "closure"))
        self.assertIn("ext_supported", self.refused("r-small", "--init", str(self.ckpt), "--ext-supported",
                                                     hex(_bits("WEATHER_SAND"))))
        unknown = self.bc_like("enc9.npz", encoder=9)
        self.assertIn("encoder", self.refused("r-enc", "--init", str(unknown)))

    def test_init_mask_wider_than_library_is_refused(self):
        from duoforge import features
        wide = self.bc_like("wider.npz", ext_supported=features.ALL_FEATURES)
        self.assertIn("ext_supported", self.refused("r-wider", "--init", str(wide)))

    def test_init_with_resume_refused(self):
        from duoforge_learn import train
        out = self.run_train("base", "--init", str(self.ckpt))
        with self.assertRaises(SystemExit):
            train.main(["--resume", str(out), "--init", str(self.ckpt), "--updates", "1", "--minutes", "0"])

    def test_resume_of_init_run_does_not_reapply(self):
        from duoforge_learn import train
        out = self.run_train("resumed", "--init", str(self.ckpt))
        self.assertEqual(train.main(["--resume", str(out), "--updates", "2", "--minutes", "0"]), 0)
        records = [r for r in self.log(out) if "update" in r]
        self.assertEqual([r["update"] for r in records], [1, 2])

    def test_init_refuses_shifted_ids(self):
        from duoforge_learn import checkpoint
        _, cfg = checkpoint.load(str(self.ckpt))
        moves = list(cfg["ids"]["move"])
        moves[3], moves[4] = moves[4], moves[3]
        other = {"kind": "pool", "fingerprint": "00"}
        shifted = self.bc_like("shifted.npz", ids={**cfg["ids"], "move": moves}, data=other)
        self.assertIn("move id 3", self.refused("r-ids", "--init", str(shifted)))
        appended = self.bc_like("appended.npz", ids={k: v[:-1] for k, v in cfg["ids"].items()}, data=other)
        self.run_train("appended", "--init", str(appended))

    def test_init_refuses_output_in_repo(self):
        from pathlib import Path
        from duoforge_learn import train
        inside = Path(__file__).resolve().parents[2] / "init-out-never"
        with self.assertRaises((SystemExit, ValueError)):
            train.main(["--envs", "8", "--workers", "2", "--rollout", "8", "--updates", "1", "--minutes", "0",
                        "--out", str(inside), "--init", str(self.ckpt)])
        self.assertFalse(inside.exists())


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
            self.assertEqual(config["ids"], checkpoint.ids_of(context))
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


class EvalTest(unittest.TestCase):
    def test_bc_eval_smoke(self):
        import io
        import json
        import shutil
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path
        from duoforge_learn import bc, bc_eval
        from . import test_bc_numpy as fixture
        tmp = Path(tempfile.mkdtemp(prefix="duoforge_bc_eval_"))
        try:
            data = fixture.build_fixture(tmp, natures=fixture.split_variants(2, 1))
            bc.main(["--data", str(data), "--out", str(tmp / "bc"), "--preset", "S", "--batch", "8", "--epochs", "1"])
            text = io.StringIO()
            with redirect_stdout(text):
                bc_eval.main(["--checkpoint", str(tmp / "bc" / "bc.npz"), "--games", "1", "--seed", "3",
                              "--baseline-random-net"])
            result = json.loads(text.getvalue().strip().splitlines()[-1])
            for key in ("vs_random", "vs_scripted", "random_net_vs_random", "random_net_vs_scripted"):
                self.assertIn("score", result[key], key)
            self.assertGreater(result["n_games"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
