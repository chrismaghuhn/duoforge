"""duoforge.python.learn_v2_numpy: the NumPy parts of Learner v2 (decision 0017).

Column groups and the host id check of model v2, the team pool's weighted
pairings, the league state machine, schedules, the evaluation suite and
the per-team ladder fits. The JAX parts are in test_learn_v2.py.
"""
import os
import tempfile
import unittest

import numpy as np

from duoforge import features
from duoforge_learn import checkpoint, columns, pairing


def _config(**extra):
    """A complete format-2 config of a small v1 network."""
    return {"model": {"version": 1, "hidden": 8, "option_hidden": 4}, "encoder": features.ENCODER,
            "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
            "data": {"kind": "closure", "fingerprint": "00"}, "teams": {"ids": ["A", "B"], "sha256": ["", ""],
                                                                        "weights": [1.0, 1.0]},
            "update": 3, "decisions": 99, **extra}


def _v1_params(rng, obs=features.OBS_SIZE, slot=features.SLOT_FEATURES, hidden=8, option=4):
    shapes = {"t1": (obs, hidden), "t2": (hidden, hidden), "option_torso": (hidden, option),
              "option_features": (slot, option), "option_out": (option, 2), "team": (hidden, 360),
              "value": (hidden, 1)}
    return {k: {"w": rng.standard_normal(s).astype(np.float32), "b": rng.standard_normal(s[1]).astype(np.float32)}
            for k, s in shapes.items()}


class ColumnsTest(unittest.TestCase):
    def test_groups_partition_the_observation(self):
        cols = columns.columns()
        parts = [cols.glob, cols.side, cols.position, cols.occupant, cols.member, cols.species, cols.item,
                 cols.ability, cols.nature, cols.moves, cols.pp, cols.move_count, cols.present]
        every = np.concatenate([p.reshape(-1) for p in parts])
        self.assertEqual(sorted(every.tolist()), list(range(features.OBS_SIZE)))
        names = features.FEATURE_NAMES
        self.assertTrue(all(names[i].startswith("global.") for i in cols.glob))
        self.assertTrue(all(".occupant." in names[i] for i in cols.occupant.reshape(-1)))
        self.assertEqual(names[cols.species[1, 3]], "foe.member3.species")
        self.assertEqual(names[cols.moves[0, 2, 1]], "own.member2.move1")
        self.assertEqual(names[cols.position[1, 0, 0]], "foe.pos0.stage.atk")
        self.assertEqual(cols.position.shape, (2, 2, 17))
        self.assertEqual([features.SLOT_FEATURE_NAMES[i] for i in cols.slot_move], ["move_slot"])
        self.assertEqual([features.SLOT_FEATURE_NAMES[i] for i in cols.slot_reserve], ["reserve"])
        self.assertEqual(cols.slot_scalar.shape, (10,))

    def test_unknown_column_name_is_refused(self):
        with self.assertRaisesRegex(ValueError, "own.member0.weight"):
            columns.columns(features.FEATURE_NAMES + ("own.member0.weight",))

    def test_check_ids_refuses_an_id_at_capacity(self):
        cols = columns.columns()
        obs = np.zeros((2, features.OBS_SIZE), dtype=np.float32)
        caps = {"species": 1024, "move": 1024, "item": 256, "ability": 256, "nature": 25}
        obs[1, cols.species[0, 0]] = np.float32(1023 / 65535)
        columns.check_ids(obs, cols, caps)
        obs[1, cols.species[0, 0]] = np.float32(1024 / 65535)
        with self.assertRaisesRegex(ValueError, "species id 1024 is outside the model's capacity 1024"):
            columns.check_ids(obs, cols, caps)


class CheckpointTest(unittest.TestCase):
    def test_format2_round_trip(self):
        params = _v1_params(np.random.default_rng(1))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "params-3.npz")
            checkpoint.save(path, params, _config())
            back, config = checkpoint.load(path)
        self.assertEqual(config["format"], 2)
        self.assertEqual(config["features"], list(features.FEATURE_NAMES))
        self.assertEqual(config["update"], 3)
        for layer in params:
            for k in ("w", "b"):
                self.assertTrue(np.array_equal(back[layer][k], params[layer][k]))

    def test_save_requires_the_format2_keys(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(ValueError, "teams"):
            cfg = _config()
            del cfg["teams"]
            checkpoint.save(os.path.join(d, "p.npz"), _v1_params(np.random.default_rng(1)), cfg)

    def test_dropped_column_is_refused(self):
        cfg = _config(features=list(features.FEATURE_NAMES) + ["own.member0.weight"])
        params = _v1_params(np.random.default_rng(1), obs=features.OBS_SIZE + 1)
        with self.assertRaisesRegex(ValueError, "own.member0.weight"):
            checkpoint.widen(params, cfg, features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)

    def test_widening_inserts_zero_rows_by_name(self):
        flags = [n for n in features.FEATURE_NAMES if n.endswith(".flag.follow_me")]
        old = [n for n in features.FEATURE_NAMES if n not in flags]
        params = _v1_params(np.random.default_rng(2), obs=len(old))
        wide, cfg = checkpoint.widen(params, _config(features=old), features.FEATURE_NAMES,
                                     features.SLOT_FEATURE_NAMES)
        self.assertEqual(cfg["features"], list(features.FEATURE_NAMES))
        w = wide["t1"]["w"]
        for n in flags:
            self.assertFalse(w[features.FEATURE_NAMES.index(n)].any())
        for i, n in enumerate(old):
            self.assertTrue(np.array_equal(w[features.FEATURE_NAMES.index(n)], params["t1"]["w"][i]))


class PairingTest(unittest.TestCase):
    def test_pairings_are_pure_and_uniform(self):
        envs = np.repeat(np.arange(100), 90)
        episodes = np.tile(np.arange(90), 100)
        weights = np.ones(3)
        a0, a1 = pairing.pairings(7, envs, episodes, weights)
        b0, b1 = pairing.pairings(7, envs, episodes, weights)
        self.assertTrue(np.array_equal(a0, b0) and np.array_equal(a1, b1))
        alone = [pairing.pairings(7, envs[i:i + 1], episodes[i:i + 1], weights) for i in range(0, 9000, 997)]
        for k, i in enumerate(range(0, 9000, 997)):
            self.assertEqual((int(alone[k][0][0]), int(alone[k][1][0])), (int(a0[i]), int(a1[i])))
        counts = np.bincount(a0 * 3 + a1, minlength=9)
        self.assertTrue(((counts > 880) & (counts < 1120)).all(), counts.tolist())
        c0, _ = pairing.pairings(8, envs, episodes, weights)
        self.assertFalse(np.array_equal(a0, c0))

    def test_zero_weight_is_never_drawn(self):
        envs = np.arange(4000)
        side0, side1 = pairing.pairings(11, envs, np.zeros(4000, dtype=np.int64), np.array([1.0, 0.0, 3.0]))
        both = np.concatenate([side0, side1])
        self.assertFalse((both == 1).any())
        ratio = (both == 2).sum() / (both == 0).sum()
        self.assertTrue(2.6 <= ratio <= 3.4, ratio)

    def test_draw_is_the_documented_formula(self):
        mask = (1 << 64) - 1

        def mix(x):
            z = (x + 0x9E3779B97F4A7C15) & mask
            z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & mask
            z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & mask
            return z ^ (z >> 31)

        want = mix((mix((mix((5 + pairing.PAIR_SIDE1) & mask) + 3) & mask) + 9) & mask)
        got = pairing.draw(5, pairing.PAIR_SIDE1, np.array([3]), np.array([9]))
        self.assertEqual(int(got[0]), want)


if __name__ == "__main__":
    unittest.main()
