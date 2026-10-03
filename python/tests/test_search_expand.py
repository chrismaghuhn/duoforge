"""duoforge.python.search_expand: the Python side of the search's leaf expansion
(decision 0022, plan task 5): duoforge.search_seeds and Batch.expand.

The C contract of duoforge_batch_expand is duoforge.search.expand (C); here:
- search_seeds equals decision 0022's formula;
- expand's shapes, dtypes and buffer reuse;
- 1 and 4 workers give equal outputs;
- a leaf's row is the row query_encoded writes for its viewer;
- a leaf's refusal is returned, never raised; the argument checks raise and
  write nothing;
- the rows' width is the library's (duoforge_encoder_size), checked before
  the library writes into the buffer;
- the environments from n on are not touched.
Teams A and B under POOL, with records in the mask.
"""
import ctypes
import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, factored_choices, features, joint_counts
from duoforge.context import reference_setups

C = _layout.CONSTANTS
SEED = 0x2026100300000221
ROOTS = 8
LEAVES = 48
MASK64 = (1 << 64) - 1
UNTOUCHED = 0xA5A5A5A5


def _splitmix(x):
    """splitmix64 as decision 0012 defines it, on Python integers."""
    z = (x + 0x9E3779B97F4A7C15) & MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return z ^ (z >> 31)


def _formula(seed, key, sample):
    """Decision 0022 section 2, written out."""
    h = _splitmix((_splitmix((seed + 0x5345415243480001) & MASK64) + key) & MASK64)
    s = _splitmix((h + sample) & MASK64)
    return _splitmix((s + 1) & MASK64), _splitmix((s + 2) & MASK64) >> 1


def _random_choices(domains, rng):
    """A random allowed choice in every domain; zero where no one is asked."""
    out = np.zeros(domains.shape[0], dtype=_layout.FACTORED_CHOICE)
    kinds = (C["DUOFORGE_CHOICE_SLOTS"], C["DUOFORGE_CHOICE_TEAM_SELECTION"])
    asked = np.flatnonzero(np.isin(domains["kind"], kinds))
    if asked.size:
        counts = joint_counts(domains[asked])
        ks = (rng.random(asked.size) * counts).astype(np.int64)
        out[asked] = factored_choices(domains[asked], ks)
    return out


class SearchExpand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.setups = reference_setups([0, 1, 2, 3])
        cls.roots = duoforge.Batch(cls.ctx, np.resize(cls.setups, ROOTS), 2, SEED)
        rng = np.random.default_rng(0x2026100300000500)
        for _ in range(9):  # roots at several boundaries
            cls.roots.query_factored()
            choices = _random_choices(cls.roots.domains.reshape(-1), rng).reshape(ROOTS, 2)
            cls.roots.step_factored(choices)
            cls.roots.reset_terminal()
        cls.roots.query_factored()
        ext = cls.roots.observe_ext()
        cls.mask = int(ext[0, 0]["supported"])
        cls.keys = rng.integers(0, 2 ** 63, ROOTS, dtype=np.uint64)
        cls.viewers = (np.arange(ROOTS) % 2).astype(np.uint8)
        cls.root_envs = (np.arange(LEAVES) % ROOTS).astype(np.uint32)
        cls.samples = (np.arange(LEAVES) // ROOTS).astype(np.uint32)
        flat = cls.roots.domains[cls.root_envs].reshape(-1)
        cls.choices = _random_choices(flat, rng).reshape(LEAVES, 2)

    @classmethod
    def tearDownClass(cls):
        cls.roots.close()
        cls.ctx.close()

    def _leaves(self, workers, envs=LEAVES):
        return duoforge.Batch(self.ctx, np.resize(self.setups, envs), workers, SEED)

    def _expand(self, leaves, n=LEAVES, **change):
        args = dict(version=4, ext_supported=self.mask, seed=SEED, keys=self.keys, viewers=self.viewers,
                    root_envs=self.root_envs[:n], samples=self.samples[:n], choices=self.choices[:n])
        args.update(change)
        return leaves.expand(self.roots, **args)

    def test_seed_function_matches_the_formula(self):
        rng = np.random.default_rng(0x2026100300000501)
        triples = [(0, 0, 0), (MASK64, MASK64, 2 ** 32 - 1)]
        triples += [(int(rng.integers(0, 2 ** 63)) * 2 + 1, int(rng.integers(0, 2 ** 63)), int(rng.integers(0, 2 ** 32)))
                    for _ in range(98)]
        for seed, key, sample in triples:
            self.assertEqual(duoforge.search_seeds(seed, key, sample), _formula(seed, key, sample))
        self.assertEqual(duoforge.search_seeds(0, 0, 0), (0xD0679AB4D0A42833, 0x74A4499FAFB31CD8))

    def test_expand_shapes_and_reuse(self):
        with self._leaves(2) as leaves:
            obs, step, enc, results, leaf_results = self._expand(leaves)
            self.assertEqual(obs.shape, (LEAVES, 850))
            self.assertEqual(obs.dtype, np.float32)
            for a in (step, enc, leaf_results):
                self.assertEqual((a.shape, a.dtype), ((LEAVES,), np.uint32))
            self.assertEqual((results.shape, results.dtype), ((LEAVES,), _layout.STEP_RESULT))
            again = self._expand(leaves, n=10)
            self.assertTrue(np.shares_memory(again[0], obs))
            self.assertEqual(again[0].shape, (10, 850))

    def test_worker_counts_agree(self):
        with self._leaves(1) as one, self._leaves(4) as four:
            a = [x.copy() for x in self._expand(one)]
            b = self._expand(four)
            for x, y in zip(a, b):
                np.testing.assert_array_equal(x, y)

    def test_leaf_row_equals_query_encoded_of_its_environment(self):
        with self._leaves(2) as leaves:
            obs, step, enc, _, leaf_results = [x.copy() for x in self._expand(leaves)]
            rows, _, _ = leaves.query_encoded(4, self.mask)
            checked = 0
            for i in range(LEAVES):
                viewer = int(self.viewers[self.root_envs[i]])
                if step[i] == 0 and leaf_results[i] == 0:
                    self.assertEqual(int(enc[i]), 0)
                    np.testing.assert_array_equal(obs[i], rows[i, viewer])
                    checked += 1
                else:
                    self.assertFalse(obs[i].any())  # refused or TERMINAL: an all-zero row
            self.assertGreater(checked, 0)

    def test_leaf_refusal_is_returned(self):
        choices = self.choices.copy()
        asked = np.flatnonzero(self.roots.requests[self.root_envs, 0]["requested"] != 0)
        i = int(asked[0])
        choices[i, 0]["slot"] = (31, 31)  # past every slot list
        with self._leaves(2) as leaves:
            _, step, enc, _, _ = self._expand(leaves, choices=choices)
            self.assertEqual(int(step[i]), C["DUOFORGE_E_INVALID_ARGUMENT"])
            self.assertEqual(int(enc[i]), 0)

    def test_untouched_past_n(self):
        with self._leaves(2) as leaves:
            before = [leaves.digest(e) for e in range(LEAVES)]
            self._expand(leaves, n=20)
            after = [leaves.digest(e) for e in range(LEAVES)]
            self.assertEqual(before[20:], after[20:])

    def test_argument_errors_raise(self):
        with self._leaves(2, envs=4) as leaves:
            before = [leaves.digest(e) for e in range(4)]
            viewers = self.viewers.copy()
            viewers[int(self.root_envs[0])] = 2
            with self.assertRaisesRegex(ValueError, "do not fit"):
                self._expand(leaves, n=5)
            with self.assertRaises(duoforge.DuoforgeError):
                self._expand(leaves, n=4, viewers=viewers)
            with self.assertRaises(ValueError):
                self._expand(leaves, n=4, version=5)
            with self.assertRaises(ValueError):  # no mask of the feature bits, as in query_encoded
                self._expand(leaves, n=4, ext_supported=1 << 42)
            with self.assertRaises(duoforge.DuoforgeError):  # past version 3's features: the library refuses
                self._expand(leaves, n=4, version=3, ext_supported=1 << 40)
            with self.assertRaises(duoforge.DuoforgeError):
                leaves.expand(leaves, 4, self.mask, SEED, np.zeros(4, np.uint64), np.zeros(4, np.uint8),
                              np.zeros(1, np.uint32), np.zeros(1, np.uint32),
                              np.zeros((1, 2), _layout.FACTORED_CHOICE))  # leaves == roots
            with self.assertRaises(TypeError):
                self._expand(leaves, n=4, samples=self.samples[:4].astype(np.int64))
            with self.assertRaises(TypeError):
                leaves.expand("roots", 4, self.mask, SEED, self.keys, self.viewers, self.root_envs[:1],
                              self.samples[:1], self.choices[:1])
            self.assertEqual([leaves.digest(e) for e in range(4)], before)  # the refusals touched no leaf
            self.assertEqual(self._expand(leaves, n=0)[0].shape, (0, 850))

    def test_row_width_is_the_library_s(self):
        for version in (1, 2, 3, 4):  # the buffer's width is checked against duoforge_encoder_size
            width = ctypes.c_uint32()
            self.assertEqual(duoforge.load_library().duoforge_encoder_size(version, ctypes.byref(width)), 0)
            self.assertEqual(width.value, features.obs_size(version))
        with self._leaves(2, envs=4) as leaves, mock.patch.object(features, "obs_size", return_value=849):
            with self.assertRaisesRegex(duoforge.DuoforgeLibraryError, "849"):
                self._expand(leaves, n=4)

if __name__ == "__main__":
    unittest.main()
