"""duoforge.python.encoder6: encoder 6, the reserve of decision 0050.

Encoder 6 is encoder 5's 862 columns, byte for byte, and 232 reserve columns: one 0/1 column per bit of the bitfields
the content expansion fills (the field's flags, the side's guard bits 2 to 7 and conditions, the position's volatiles
bits 22 to 31, volatiles2 and the observation's position flag bits 3 to 7), named by bit number. A family's columns are
shown under its feature, a bit with a feature of its own name under that one as well, and the position flags always;
encoders 1 to 5 refuse a value in the reserve. A fresh network starts the reserve's input rows at zero, so a bit that
appears later changes nothing until training sees it, and an encoder 5 network widened to encoder 6 gives the same
outputs.
"""
import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features

from python.tests.test_features_ext import _records, _turn_scene

C = _layout.CONSTANTS
COL = {name: i for i, name in enumerate(features.FEATURE_NAMES)}
FAMILY = {name: 1 << features.FEATURE_BITS[name] for name in features._FAMILIES}
FAMILIES = sum(FAMILY.values())


def _side_name(observation, side):
    return "own" if side == int(observation["player"]) else "foe"


def _reserve(ext, observations):
    """Records and observations with a distinct pattern in every reserve family, per absolute side and position."""
    ext, observations = ext.copy(), observations.copy()
    ext["field"]["flags"] = 0b1010_0000_0000_0101
    for s in range(2):
        ext["sides"]["guard_flags"][:, s] |= np.uint8(1 << (2 + s))
        ext["sides"]["conditions"][:, s] = 1 << (5 + s)
        for k in range(2):
            pos = ext["sides"]["positions"]
            pos["volatiles"][:, s, k] |= np.uint32(1 << (22 + s * 2 + k)) | np.uint32(1 << 31)
            ext["volatiles2"][:, s, k] = (1 << (s * 2 + k)) | (1 << 30)
            observations["sides"]["positions"]["reserved"][:, s, k] |= np.uint8(1 << (3 + s * 2 + k))
    return ext, observations


class Encoder6Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context()
        cls.obs, cls.domains = _turn_scene(cls.ctx)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_layout_and_versions(self):
        self.assertEqual((features.ENCODER, features.ENCODERS), (6, (1, 2, 3, 4, 5, 6)))
        self.assertEqual((features.obs_size(5), features.obs_size(6)), (862, 1094))
        self.assertEqual(features.feature_names(5), features.FEATURE_NAMES[:862])
        reserve = features.FEATURE_NAMES[862:]
        self.assertTrue(all(n.startswith("ext6.") for n in reserve))
        self.assertEqual(len(reserve), 16 + 2 * (6 + 8 + 2 * (10 + 32 + 5)))
        self.assertEqual(reserve[:2], ("ext6.global.field_flag.bit0", "ext6.global.field_flag.bit1"))
        self.assertIn("ext6.foe.pos1.volatile.bit31", reserve)
        self.assertIn("ext6.own.pos0.volatile2.bit0", reserve)
        self.assertIn("ext6.own.guard.bit7", reserve)
        self.assertNotIn("ext6.own.guard.bit1", reserve)  # bits 0 and 1 are WIDE_GUARD and QUICK_GUARD
        self.assertEqual(features.version_features(5), (1 << C["DUOFORGE_VIEWEXT_FEATURE_COUNT"]) - 1)
        self.assertEqual(features.version_features(6) & ~features.version_features(5), FAMILIES)
        self.assertEqual({features.FEATURE_BITS[n] for n in features._FAMILIES}, set(range(59, 64)))

    def test_encoder5_columns_are_byte_equal(self):
        ext = _records(self.obs, features.ALL_FEATURES)
        for mask in (0, features.version_features(5), features.ALL_FEATURES & features.version_features(5)):
            six, slots6, pairs6 = features.encode_batch(self.obs, self.domains, ext, mask)
            five, slots5, pairs5 = features.encode_batch(self.obs, self.domains, ext, mask, encoder=5)
            np.testing.assert_array_equal(six, five)  # the same columns: the encoder argument only refuses
            np.testing.assert_array_equal(features.as_encoder(six, self.obs, 5), six[:, :862])
            np.testing.assert_array_equal(slots6, slots5)
            np.testing.assert_array_equal(pairs6, pairs5)
            self.assertFalse(six[:, 862:].any())  # nothing in the reserve

    def test_reserve_columns(self):
        ext, obs = _reserve(_records(self.obs, features.ALL_FEATURES), self.obs)
        part, _, _ = features.encode_batch(obs, self.domains, ext, features.ALL_FEATURES)
        for n in range(obs.shape[0]):
            on = {name for name in features.FEATURE_NAMES[862:] if part[n, COL[name]] == 1.0}
            want = {f"ext6.global.field_flag.bit{k}" for k in (0, 2, 13, 15)}
            for s in range(2):
                side = _side_name(obs[n], s)
                want |= {f"ext6.{side}.guard.bit{2 + s}", f"ext6.{side}.condition.bit{5 + s}"}
                for k in range(2):
                    pre = f"ext6.{side}.pos{k}"
                    want |= {f"{pre}.volatile.bit{22 + s * 2 + k}", f"{pre}.volatile.bit31",
                             f"{pre}.volatile2.bit{s * 2 + k}", f"{pre}.volatile2.bit30", f"{pre}.flag.bit{3 + s * 2 + k}"}
            self.assertEqual(on, want, f"row {n}")
            self.assertTrue(set(part[n, 862:].tolist()) <= {0.0, 1.0})

    def test_a_family_is_shown_under_its_feature(self):
        ext, obs = _reserve(_records(self.obs, features.ALL_FEATURES), self.obs)
        full, _, _ = features.encode_batch(obs, self.domains, ext, features.ALL_FEATURES)
        prefixes = {"FIELD_FLAGS": ".field_flag.", "RESERVE_GUARDS": ".guard.", "SIDE_CONDITIONS": ".condition.",
                    "RESERVE_VOLATILES": ".volatile.", "VOLATILES2": ".volatile2."}
        for family, piece in prefixes.items():
            part, _, _ = features.encode_batch(obs, self.domains, ext, features.ALL_FEATURES & ~FAMILY[family])
            cols = [COL[n] for n in features.FEATURE_NAMES[862:] if piece in n]
            self.assertTrue(full[:, cols].any(), family)
            self.assertFalse(part[:, cols].any(), family)
            others = [i for i in range(862, features.OBS_SIZE) if i not in cols]
            np.testing.assert_array_equal(part[:, others], full[:, others])
        # The position flags are the observation's: shown under every mask, records or not.
        flags = [COL[n] for n in features.FEATURE_NAMES[862:] if ".flag." in n]
        part, _, _ = features.encode_batch(obs, self.domains, None, 0)
        np.testing.assert_array_equal(part[:, flags], full[:, flags])
        self.assertTrue(part[:, flags].any())

    def test_an_own_feature_gates_its_column_as_well(self):
        # A reserve bit with a feature of its own name: its column needs both bits of its set.
        own = {"DUOFORGE_POSITION_EXT_EXAMPLE": 1 << 27, "DUOFORGE_SIDE_CONDITION_EXAMPLE": 1 << 4}
        with mock.patch.dict(features.C, own), mock.patch.dict(features.FEATURE_BITS, {"EXAMPLE": 50}):
            volatiles = features._own_features("DUOFORGE_POSITION_EXT_", features._VOLATILE_FEATURE)
            conditions = features._own_features("DUOFORGE_SIDE_CONDITION_")
            self.assertEqual(volatiles[27], 50)
            self.assertEqual(conditions, {4: 50})
            family = (range(22, 32), features.FEATURE_BITS["RESERVE_VOLATILES"], volatiles)
            self.assertEqual(features._gate(family, 27), FAMILY["RESERVE_VOLATILES"] | 1 << 50)
            self.assertEqual(features._gate(family, 28), FAMILY["RESERVE_VOLATILES"])
        # encode_batch shows a column only with every bit of its set.
        ext, obs = _reserve(_records(self.obs, features.ALL_FEATURES), self.obs)
        col = COL["ext6.own.pos0.volatile.bit31"]
        masks = features.EXT_COLUMN_MASKS.copy()
        masks[col - features.BASE_OBS_SIZE] |= np.uint64(1 << 50)
        with mock.patch.object(features, "EXT_COLUMN_MASKS", masks):
            off, _, _ = features.encode_batch(obs, self.domains, ext, features.ALL_FEATURES)
            supported = ext.copy()
            supported["supported"] = features.ALL_FEATURES | 1 << 50
            with mock.patch.object(features, "ALL_FEATURES", features.ALL_FEATURES | 1 << 50), \
                    mock.patch.object(features, "version_features", lambda encoder: features.ALL_FEATURES | 1 << 50):
                on, _, _ = features.encode_batch(obs, self.domains, supported, features.ALL_FEATURES | 1 << 50)
        self.assertFalse(off[:, col].any())
        self.assertTrue(on[:, col].all())

    def test_older_encoders_refuse_the_reserve(self):
        base = _records(self.obs, features.ALL_FEATURES)
        mask = features.version_features(5)
        for change in ("volatiles", "volatiles2", "guards", "conditions", "field"):
            ext = base.copy()
            if change == "volatiles":
                ext["sides"]["positions"]["volatiles"][0, 1, 0] |= np.uint32(1 << 25)
            elif change == "volatiles2":
                ext["volatiles2"][0, 0, 1] = 1
            elif change == "guards":
                ext["sides"]["guard_flags"][0, 0] |= np.uint8(1 << 6)
            elif change == "conditions":
                ext["sides"]["conditions"][0, 1] = 1
            else:
                ext["field"]["flags"][0] = 1 << 9
            features.encode_batch(self.obs, self.domains, ext, mask)  # encoder 6: shown
            for encoder in (3, 4, 5):
                with self.assertRaises(ValueError, msg=f"{change} encoder {encoder}"):
                    features.encode_batch(self.obs, self.domains, ext, mask & features.version_features(encoder),
                                          encoder=encoder)
        obs = self.obs.copy()
        obs["sides"]["positions"]["reserved"][0, 0, 1] |= np.uint8(1 << 7)
        part, _, _ = features.encode_batch(obs, self.domains)
        for encoder in (1, 2, 3, 4, 5):
            with self.assertRaises(ValueError):
                features.encode_batch(obs, self.domains, encoder=encoder)
            with self.assertRaises(ValueError):
                features.as_encoder(part, obs, encoder)
        with self.assertRaises(ValueError):  # a mask bit encoder 5 has no column for
            features.encode_batch(self.obs, self.domains, base, FAMILY["VOLATILES2"], encoder=5)


class ReserveNetworkTest(unittest.TestCase):
    """A fresh network ignores the reserve until it trains on it; an encoder 5 network widens to encoder 6 exactly."""

    @classmethod
    def setUpClass(cls):
        import jax
        from duoforge_learn import policy
        cls.jax = jax
        cls.ctx = duoforge.Context()
        obs, domains = _turn_scene(cls.ctx)
        ext, obs = _reserve(_records(obs, features.ALL_FEATURES), obs)
        cls.part, cls.slots, cls.pairs = features.encode_batch(obs, domains, ext, features.ALL_FEATURES)
        cls.cfg = policy.v2_config("S")

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def _outputs(self, model, params, part):
        out = model.apply(params, part, self.slots, self.pairs)
        return [np.asarray(x) for x in self.jax.tree_util.tree_leaves(out)]

    def test_fresh_network_ignores_the_reserve(self):
        from duoforge_learn import columns, policy
        model = policy.make(self.cfg)
        params = model.init(self.jax.random.PRNGKey(5))
        zero = self.part.copy()
        zero[:, 862:] = 0.0
        self.assertTrue(self.part[:, 862:].any())
        for a, b in zip(self._outputs(model, params, self.part), self._outputs(model, params, zero)):
            np.testing.assert_array_equal(a, b)
        # A training step on rows whose reserve is all zero keeps the reserve rows at zero.
        import optax
        rows = columns.reserve_rows(self.cfg, model._cols, model.feature_names, model.slot_names)
        self.assertTrue(any(rows.values()))

        def loss(p):
            return sum(self.jax.numpy.sum(x ** 2) for x in self.jax.tree_util.tree_leaves(
                model.apply(p, zero, self.slots, self.pairs)))
        tx = optax.adam(1e-2)
        grads = self.jax.grad(loss)(params)
        updates, _ = tx.update(grads, tx.init(params), params)
        stepped = optax.apply_updates(params, updates)
        for path, picked in rows.items():
            layer = stepped
            for k in path:
                layer = layer[k]
            self.assertFalse(np.asarray(layer["w"])[picked].any(), path)

    def test_encoder5_network_widens_exactly(self):
        from duoforge_learn import checkpoint, policy
        five = policy.make(self.cfg, features.feature_names(5))
        params5 = self.jax.device_get(five.init(self.jax.random.PRNGKey(7)))
        config = {"model": five.config, "features": list(features.feature_names(5)),
                  "slot_features": list(features.SLOT_FEATURE_NAMES)}
        wide, wide_config = checkpoint.widen(params5, config, features.feature_names(6), features.SLOT_FEATURE_NAMES)
        six = policy.make(self.cfg, wide_config["features"])
        zero = self.part.copy()
        zero[:, 862:] = 0.0
        for a, b in zip(self._outputs(five, params5, self.part[:, :862]), self._outputs(six, wide, zero)):
            np.testing.assert_array_equal(a, b)
        # Its reserve rows are zero, so the reserve itself changes nothing either.
        for a, b in zip(self._outputs(six, wide, zero), self._outputs(six, wide, self.part)):
            np.testing.assert_array_equal(a, b)


if __name__ == "__main__":
    unittest.main()
