"""duoforge.python.search: the JAX parts of the search (decision 0022, spec
docs/superpowers/specs/2026-10-03-m12-search-stage1-design.md).

- Model.value equals the value of apply, bit for bit (plan task 8).

The NumPy parts are in test_search_numpy.py. Teams A and B under POOL, at
fixed init keys, on the CPU.
"""
import unittest

import numpy as np

import duoforge
from duoforge import _layout
from duoforge.context import reference_setups

C = _layout.CONSTANTS
SEED = 0x2026100300000231


def _rows(envs=32, steps=5):
    """obs, slots and pair mask of both seats of `envs` POOL environments
    after `steps` random steps (2 * envs rows), encoder 4 with the library's
    mask."""
    with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
            duoforge.Batch(ctx, np.resize(reference_setups([0, 1, 2, 3]), envs), 2, SEED) as b:
        policy = duoforge.RandomPolicy(SEED, envs)
        for _ in range(steps):
            b.query_factored()
            b.step_factored(policy.choose_factored(b))
            b.reset_terminal()
        b.query_factored()
        mask = int(b.observe_ext()[0, 0]["supported"])
        obs, slots, pairs = (x.copy() for x in b.query_encoded(4, mask))
    return (obs.reshape(2 * envs, -1), slots.reshape((2 * envs,) + slots.shape[2:]),
            pairs.reshape((2 * envs,) + pairs.shape[2:]))


class ModelValue(unittest.TestCase):
    def test_value_equals_apply_value(self):
        import jax
        from duoforge_learn import policy
        obs, slots, mask = _rows()
        self.assertTrue(mask.any())  # real pair masks: the value must not read them
        for config in (policy.V1_DEFAULT, policy.v2_config("S")):
            model = policy.make(config)
            params = model.init(jax.random.PRNGKey(5))
            want = np.asarray(model.apply(params, obs, slots, mask)[2])
            got = np.asarray(model.value(params, obs))
            self.assertEqual((got.shape, got.dtype), ((64,), np.float32))
            np.testing.assert_array_equal(got.view(np.uint32), want.view(np.uint32))


if __name__ == "__main__":
    unittest.main()
