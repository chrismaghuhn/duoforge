"""duoforge.python.encoder6_net: encoder 6's reserve in the networks (decision 0050).

A fresh model v2 starts the input rows fed only by the reserve at zero, so the reserve changes nothing, before and after
an optimizer step on rows where it is 0 (a bit that appears later has no effect until training sees it set); an
encoder 5 network widened to encoder 6 gives the same outputs, with or without the reserve set.
"""
import unittest

import numpy as np

import duoforge
from duoforge import features

from python.tests.engine.test_encoder6 import _reserve
from python.tests.engine.test_features_ext import _records, _turn_scene


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
            np.testing.assert_allclose(a, b, rtol=1e-6, atol=1e-6)  # wider inputs: another summation order
        # Its reserve rows are zero, so the reserve itself changes nothing either.
        for a, b in zip(self._outputs(six, wide, zero), self._outputs(six, wide, self.part)):
            np.testing.assert_array_equal(a, b)

    def test_an_encoder_4_network_widens_to_encoder_6_and_trains_one_update(self):
        # params-49333's layout in miniature (encoder 4, model v2 S, untrained): load_current widens it to encoder 6
        # with zero rows, so its outputs on rows whose new columns are empty are the encoder 4 network's; a run from
        # it plays one update (a smoke of the start of the next training, not a training run).
        import os
        import tempfile
        from duoforge_learn import checkpoint, policy, runstate
        from python.tests.learn.test_ledger import _SMALL, _init_checkpoint, _train
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "params-e4.npz")
            _init_checkpoint(path, encoder=4)
            params4, config4 = checkpoint.load_trained(path)
            wide, config6 = checkpoint.load_current(path)
            self.assertEqual((config6["encoder"], len(config6["features"])), (6, features.OBS_SIZE))
            four = policy.make(config4["model"], config4["features"])
            six = policy.make(config6["model"], config6["features"])
            empty = self.part.copy()
            empty[:, features.obs_size(4):] = 0.0
            for a, b in zip(self._outputs(four, params4, empty[:, :features.obs_size(4)]),
                            self._outputs(six, wide, empty)):
                np.testing.assert_allclose(a, b, rtol=1e-6, atol=1e-6)
            out = os.path.join(folder, "run")
            self.assertEqual(_train(["--out", out, "--init", path, "--updates", "1", "--minutes", "0"] + _SMALL), 0)
            state = runstate.load_state(out)
            self.assertEqual((state["encoder"], len(state["features"])), (6, features.OBS_SIZE))


if __name__ == "__main__":
    unittest.main()
