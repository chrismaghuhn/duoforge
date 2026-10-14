"""0082/E1b binding gates; wire keys come only from the engine."""
import unittest
from unittest import mock
import numpy as np
import duoforge
from duoforge import _layout, features, factored_choices

C = _layout.CONSTANTS
SEED = 0x2026101400000082


class SearchDigest(unittest.TestCase):
    def setUp(self):
        self.ctx = duoforge.Context(C['DUOFORGE_DATA_KIND_POOL'])
        self.setups = duoforge.reference_setups([0, 1])
        self.roots = duoforge.Batch(self.ctx, self.setups, 2, SEED)
        self.leaves = duoforge.Batch(self.ctx, np.resize(self.setups, 8), 3, SEED)
        self.roots.query_factored()
        self.mask = int(self.roots.observe_ext()[0, 0]['supported']) & features.version_features(4)
        self.args = dict(version=4, ext_supported=self.mask, seed=SEED, keys=np.full(2, 91, np.uint64),
                         viewers=np.array([0, 1], np.uint8), root_envs=(np.arange(8) % 2).astype(np.uint32),
                         samples=(np.arange(8) // 2).astype(np.uint32))
        d = self.roots.domains[self.args['root_envs']].reshape(-1)
        self.args['choices'] = factored_choices(d, np.zeros(len(d), np.int64)).reshape(8, 2)

    def tearDown(self):
        self.leaves.close(); self.roots.close(); self.ctx.close()

    def expand(self, n=8, **changes):
        args = dict(self.args)
        for name in ('root_envs', 'samples', 'choices'):
            args[name] = args[name][:n]
        args.update(changes)
        return self.leaves.expand_digest(self.roots, **args)

    def test_legacy_outputs_and_digest_only_mode(self):
        legacy = [a.copy() for a in self.leaves.expand(self.roots, **self.args)]
        observed = [a.copy() for a in self.expand()]
        for a, b in zip(legacy, observed[:5]):
            np.testing.assert_array_equal(a, b)
        digest_only = self.expand(encode=False)
        self.assertIsNone(digest_only[0])
        for i in (1, 3, 4, 5, 6):
            np.testing.assert_array_equal(digest_only[i], observed[i])
        self.assertFalse(digest_only[2].any())
        self.assertEqual(observed[5].shape, (8, 32))
        self.assertEqual(observed[5].dtype, np.uint8)
        self.assertEqual(observed[6].dtype, np.uint32)
        self.assertTrue(observed[5].any(axis=1).all())
        self.assertFalse(observed[6].any())
        self.assertEqual(int(self.leaves.last_expand_error['leaf']), 2**32 - 1)
        self.assertEqual(bytes(self.leaves.last_expand_error['phase']), b'')

    def test_keys_are_viewer_specific_and_invalidated_by_mutation(self):
        out = self.expand()
        envs = np.arange(8, dtype=np.uint32)
        keys, refused = self.leaves.observation_keys(envs, 0)
        np.testing.assert_array_equal(refused, self.args['viewers'][self.args['root_envs']] != 0)
        np.testing.assert_array_equal(keys[~refused], out[5][~refused])
        self.assertFalse(keys[refused].any())
        self.leaves.query_factored()  # read-only calls keep the sidecar valid
        np.testing.assert_array_equal(self.leaves.observation_keys(envs, 0)[0], keys)
        self.leaves.reset(0, 1)
        self.assertTrue(self.leaves.observation_keys(envs, 0)[1].all())

    def test_chunk_permutation_worker_and_tail_invariance(self):
        before = [x.copy() for x in self.expand()]
        root_before = [self.roots.digest(e) for e in range(2)]
        order = np.arange(8)[::-1]
        args = dict(self.args)
        for name in ('root_envs', 'samples', 'choices'):
            args[name] = np.ascontiguousarray(args[name][order])
        for workers in (1, 2, 3, 4, 8, 16):
            with duoforge.Batch(self.ctx, np.resize(self.setups, 8), workers, SEED) as leaves:
                got = leaves.expand_digest(self.roots, **args)
                for a, b in zip(got, before):
                    np.testing.assert_array_equal(a, b[order])
        full = self.expand()
        tail = [x[3:].copy() for x in full]
        partial = self.expand(n=3)
        for a, b in zip(full, tail):
            np.testing.assert_array_equal(a[3:], b)
        self.assertTrue(np.shares_memory(partial[5], full[5]))
        for e in range(2):
            self.assertEqual(root_before[e], self.roots.digest(e))
        # Legacy expansion mutates only the prefix and makes only those keys invalid.
        args = dict(self.args)
        for name in ('root_envs', 'samples', 'choices'):
            args[name] = args[name][:3]
        self.leaves.expand(self.roots, **args)
        _, refused = self.leaves.observation_keys(np.arange(8, dtype=np.uint32), 0)
        self.assertTrue(refused[:3].all())
        self.assertFalse(refused[4])

    def test_switching_cached_modes_cannot_revive_stale_tail_keys(self):
        self.expand()  # cache A, eight keys
        self.expand(n=3, encode=False)  # cache B, only the prefix changes
        choices = self.args['choices'].copy()
        choices[:, 0]['picks'][:, :4] = [1, 0, 2, 3]  # another real team selection
        self.expand(choices=choices)  # A changes every leaf
        self.expand(n=3, encode=False)  # B's old tail may not regain validity
        _, refused = self.leaves.observation_keys(np.arange(8, dtype=np.uint32), 0)
        self.assertTrue(refused[3:].all())

    def test_invalid_viewer_is_preflight_and_preserves_previous_keys(self):
        out = self.expand()
        digest = out[5].copy()
        leaves_before = [self.leaves.digest(e) for e in range(8)]
        viewers = self.args['viewers'].copy(); viewers[1] = 255
        with self.assertRaisesRegex(duoforge.DuoforgeError, 'preflight/observation_viewer'):
            self.expand(viewers=viewers)
        np.testing.assert_array_equal(out[5], digest)
        for e in range(8):
            self.assertEqual(leaves_before[e], self.leaves.digest(e))
        self.assertEqual(int(self.leaves.last_expand_error['leaf']), 2**32 - 1)

    def test_failed_step_is_not_a_successful_key(self):
        choices = self.args['choices'].copy()
        # TEAM_SELECTION: duplicate picks refuse, while other leaves succeed.
        choices[2, 0]['picks'] = 0
        out = self.expand(choices=choices)
        self.assertEqual(int(out[1][2]), C['DUOFORGE_E_INVALID_ARGUMENT'])
        self.assertFalse(out[5][2].any())
        self.assertEqual(int(out[6][2]), 0)
        keys, refused = self.leaves.observation_keys(np.array([0, 2, 4], np.uint32), 0)
        np.testing.assert_array_equal(refused, [False, True, False])
        self.assertFalse(keys[1].any())
        self.assertEqual(int(self.leaves.last_expand_error['leaf']), 2)
        self.assertEqual(bytes(self.leaves.last_expand_error['phase']), b'step')

    def test_error_phase_priority_is_independent_of_worker_schedule(self):
        missing = features.version_features(4) & ~self.mask
        self.assertNotEqual(missing, 0)
        bad_mask = self.mask | (missing & -missing)
        out = self.expand(ext_supported=bad_mask)
        self.assertFalse(out[1].any()); self.assertFalse(out[6].any())
        self.assertTrue((out[2] == C['DUOFORGE_E_UNSUPPORTED']).all())
        self.assertTrue(out[5].any(axis=1).all())
        self.assertEqual(bytes(self.leaves.last_expand_error['phase']), b'encode')
        self.assertEqual(int(self.leaves.last_expand_error['leaf']), 0)
        args = dict(self.args); args['ext_supported'] = bad_mask
        args['choices'] = args['choices'].copy(); args['choices'][7, 0]['picks'] = 0
        for workers in (1, 2, 3, 4, 8, 16):
            with duoforge.Batch(self.ctx, np.resize(self.setups, 8), workers, SEED) as leaves:
                out = leaves.expand_digest(self.roots, **args)
                self.assertEqual(int(out[1][7]), C['DUOFORGE_E_INVALID_ARGUMENT'])
                self.assertEqual(bytes(leaves.last_expand_error['phase']), b'step')
                self.assertEqual(int(leaves.last_expand_error['leaf']), 7)

    def test_preflight_guards_and_unavailable_key(self):
        with self.assertRaisesRegex(duoforge.DuoforgeError, 'observation_digest_unavailable'):
            self.leaves.observation_keys(np.array([0], np.uint32), 0)
        for change, exception in (({'root_envs': self.args['root_envs'].astype(np.uint64)}, TypeError),
                                  ({'samples': np.zeros(7, np.uint32)}, ValueError),
                                  ({'choices': self.args['choices'][:, ::-1]}, ValueError),
                                  ({'encode': 1}, TypeError), ({'version': 999}, ValueError)):
            with self.subTest(change=list(change)):
                with self.assertRaises(exception):
                    self.expand(**change)
        empty = self.expand(n=0)
        self.assertEqual(empty[5].shape, (0, 32))
        for args in ((np.array([8], np.uint32), 0), (np.array([0], np.uint32), 2)):
            with self.assertRaises(ValueError):
                self.leaves.observation_keys(*args)

    def test_successful_terminal_leaf_keeps_digest_and_exact_utility(self):
        policy = duoforge.RandomPolicy(SEED, 2)
        for _ in range(512):
            self.roots.query_factored()
            root_choices = policy.choose_factored(self.roots)
            out = self.expand(choices=root_choices[self.args['root_envs']].copy())
            terminal = np.flatnonzero((out[1] == 0) & (out[4] != 0))
            if terminal.size:
                self.assertFalse(out[6][terminal].any())
                self.assertTrue(out[5][terminal].any(axis=1).all())
                self.assertFalse(out[0][terminal].any())
                self.assertFalse(out[2][terminal].any())
                for e in terminal:
                    self.assertEqual(self.leaves.result(int(e)), int(out[4][e]))
                    viewer = int(self.args['viewers'][self.args['root_envs'][e]])
                    key, refused = self.leaves.observation_keys(np.array([e], np.uint32), viewer)
                    self.assertFalse(refused[0])
                    np.testing.assert_array_equal(key[0], out[5][e])
                return
            self.roots.step_factored(root_choices)
            if all(self.roots.result(e) for e in range(2)):
                break
        self.fail('fixed real playout must produce a successful terminal leaf')

    def test_optional_engine_capability_preserves_legacy_binding(self):
        from duoforge import _lib
        library = self.leaves._lib
        class OlderLibrary:
            def __getattr__(self, name):
                if name == 'duoforge_batch_expand_digest':
                    raise AttributeError(name)
                return getattr(library, name)
        older = OlderLibrary()
        with mock.patch.object(_lib, '_open', return_value=older):
            loaded = _lib._load((('0082-older-library-test',),), 'test-only')
        self.leaves._lib = loaded
        self.assertFalse(self.leaves.expand(self.roots, **self.args)[1].any())
        with self.assertRaisesRegex(duoforge.DuoforgeError, 'observation_digest_unavailable'):
            self.expand()
        self.leaves._lib = library
        self.expand()
        unsigned = self.leaves.observation_keys(np.array([0, 2], np.uint32), 0)
        signed = self.leaves.observation_keys(np.array([0, 2], np.int64), 0)
        for a, b in zip(unsigned, signed):
            np.testing.assert_array_equal(a, b)
        with self.assertRaises(ValueError):
            self.leaves.observation_keys(np.array([-1], np.int64), 0)
        with self.assertRaises(TypeError):
            self.leaves.observation_keys(np.array([0.0]), 0)

    def test_terminal_roots_refuse_without_inheriting_keys(self):
        self.expand()
        self.roots.play_random(1, 512); self.roots.query_factored()
        self.assertTrue(all(self.roots.result(e) for e in range(2)))
        self.args['choices'] = np.zeros((8, 2), _layout.FACTORED_CHOICE)
        out = self.expand()
        self.assertTrue((out[1] == C['DUOFORGE_E_INVALID_ARGUMENT']).all())
        self.assertFalse(out[5].any()); self.assertFalse(out[6].any())
        self.assertFalse(out[0].any()); self.assertFalse(out[2].any())
        self.assertTrue(self.leaves.observation_keys(np.arange(8, dtype=np.uint32), 0)[1].all())


if __name__ == '__main__':
    unittest.main()
