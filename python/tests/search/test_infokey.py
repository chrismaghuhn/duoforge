"""The observation keys of D2's depth-1 nodes (duoforge_search.infokey; plan docs/superpowers/plans/2026-10-14-depth-
search-d2.md steps 2 and 9): the engine digest (decision 0082, Batch.expand_digest) through DigestNodes and DigestKey,
refused by name in a library without the call; the record key (tests only) is the SHA-256 of the viewer's public record,
equal for equal records, different for different ones, and refused under closed team sheets.

The digest tests run the library's call: the sidecar by logical node index, its generation and viewer, refusals by step
and digest status, agreement with the batch's own sidecar (Batch.observation_keys). Two of them alter the call's output
after it ran (Recorded), to see a refused digest and a breach of the contract handled."""
import hashlib
import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_search import SearchError, infokey

C = _layout.CONSTANTS


class Recorded:
    """The library's digest call (infokey._library_digest_call()), recording each call's leaf count and its last
    (digests, digest statuses). refuse: leaf indices of a call whose stepped digest it then reports refused
    (DUOFORGE_E_UNSUPPORTED, zero bytes); zero: indices it then reports OK with zero bytes, a breach of the contract."""

    def __init__(self, refuse=(), zero=()):
        self.call = infokey._library_digest_call()
        self.refuse, self.zero = set(refuse), set(zero)
        self.calls, self.last = [], None

    def __call__(self, batch, roots, version, ext_supported, seed, keys, viewers, root_envs, samples, choices):
        *legacy, digests, statuses = self.call(batch, roots, version, ext_supported, seed, keys, viewers, root_envs,
                                               samples, choices)
        digests, statuses = digests.copy(), statuses.copy()
        n = len(root_envs)
        for x in (x for x in self.refuse if x < n):
            if legacy[1][x] == 0:
                statuses[x], digests[x] = C["DUOFORGE_E_UNSUPPORTED"], 0
        for x in (x for x in self.zero if x < n):
            digests[x] = 0
        self.calls.append(len(root_envs))
        self.last = (digests.copy(), statuses.copy())
        return (*legacy, digests, statuses)


def _stepped(ctx, picks):
    """A batch of len(picks) reference battles, each stepped past team preview with its own picks."""
    batch = duoforge.Batch(ctx, duoforge.reference_setups([0] * len(picks)), 1, 42)
    batch.query_factored()
    choices = np.zeros((batch.envs, 2), _layout.FACTORED_CHOICE)
    for e, order in enumerate(picks):
        choices["picks"][e, :, :4] = np.asarray(order, dtype=np.uint8)
    batch.step_factored(choices)
    return batch


class Keys(unittest.TestCase):
    def test_the_digest_key_runs_on_the_librarys_call(self):
        key = infokey.make("digest")
        self.assertIsInstance(key, infokey.DigestKey)
        self.assertEqual(key.name, "digest")

    def test_a_library_without_the_call_refuses_the_digest_by_name(self):
        class Older:  # a library without duoforge_batch_expand_digest
            pass
        with mock.patch.object(infokey, "load_library", return_value=Older()):
            with self.assertRaisesRegex(SearchError, "^observation_digest_unavailable"):
                infokey.make("digest")

    def test_an_unknown_key_is_refused(self):
        with self.assertRaisesRegex(ValueError, "info_key"):
            infokey.make("state")

    def test_the_record_key_follows_the_viewers_record(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            with _stepped(ctx, [[0, 1, 2, 3], [0, 1, 2, 3], [1, 0, 2, 3]]) as batch:
                key = infokey.make("record")
                keys, refused = key.keys(batch, np.arange(3), 0, closed=False)
                records, _ = batch.public(np.zeros(3, np.uint32))
                expected = [hashlib.sha256(records[e].tobytes()).digest() for e in range(3)]
        self.assertEqual((keys.shape, keys.dtype), ((3, infokey.KEY_BYTES), np.uint8))
        self.assertEqual(refused.tolist(), [False] * 3)
        self.assertEqual([k.tobytes() for k in keys], expected)
        self.assertEqual(keys[0].tobytes(), keys[1].tobytes())  # the same record, the same key
        self.assertNotEqual(keys[0].tobytes(), keys[2].tobytes())  # other leads: another record

    def test_the_record_key_refuses_closed_team_sheets(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, _stepped(ctx, [[0, 1, 2, 3]]) as batch:
            with self.assertRaisesRegex(SearchError, "closed team sheets"):
                infokey.make("record").keys(batch, np.arange(1), 0, closed=True)

    def test_the_record_key_keeps_the_node_batch(self):
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, _stepped(ctx, [[0, 1, 2, 3]]) as batch:
            self.assertIs(infokey.make("record").nodes(batch), batch)


class DigestKeys(unittest.TestCase):
    """DigestNodes and DigestKey on the library's digest call (decision 0082)."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        cls.roots = _stepped(cls.ctx, [[0, 1, 2, 3], [1, 0, 2, 3]])
        cls.roots.query_factored()
        with duoforge.Batch(cls.ctx, duoforge.reference_setups([0]), 1, 42) as b:
            cls.mask = int(b.observe_ext()[0, 0]["supported"]) & features.version_features(4)
        # every root: its first four own joint choices (seat 0) against the foe's first
        root_envs, choices = [], []
        for e in range(cls.roots.envs):
            for k in range(4):
                choice = np.zeros(2, _layout.FACTORED_CHOICE)
                choice[0] = duoforge.factored_choice(cls.roots.domains[e, 0], k)
                choice[1] = duoforge.factored_choice(cls.roots.domains[e, 1], 0)
                root_envs.append(e)
                choices.append(choice)
        cls.root_envs = np.asarray(root_envs, np.uint32)
        cls.choices = np.asarray(choices)
        cls.n = cls.root_envs.size

    @classmethod
    def tearDownClass(cls):
        cls.roots.close()
        cls.ctx.close()

    def batch(self, envs=None):
        batch = duoforge.Batch(self.ctx, duoforge.reference_setups([0] * (envs or self.n)), 1, 42)
        self.addCleanup(batch.close)
        return batch

    def expand(self, target, lo=0, hi=None, viewer=0, choices=None, **kw):
        hi = self.n if hi is None else hi
        choices = self.choices if choices is None else choices
        return target.expand(self.roots, 4, self.mask, 7, np.arange(1, self.roots.envs + 1, dtype=np.uint64),
                             np.full(self.roots.envs, viewer, np.uint8), self.root_envs[lo:hi],
                             np.zeros(hi - lo, np.uint32), choices[lo:hi], **kw)

    def test_the_adapter_expands_as_batch_expand(self):
        raw, call = self.batch(), Recorded()
        nodes = infokey.DigestNodes(self.batch(), call)
        want = [x.copy() for x in self.expand(raw)]
        got = self.expand(nodes)
        self.assertEqual(len(got), 5)
        for name, a, b in zip(("obs", "step", "encode", "results", "leaf_results"), got, want):
            self.assertEqual(a.tobytes(), b.tobytes(), name)
        self.assertEqual(call.calls, [self.n])
        self.assertEqual(int((want[1] == 0).sum()), self.n)  # the plan's leaves all step

    def test_the_keys_are_the_calls_digests_by_logical_index(self):
        call = Recorded()
        nodes = infokey.DigestNodes(self.batch(), call)
        self.expand(nodes)
        digests, statuses = call.last
        envs = np.array([5, 0, 3, 3])
        keys, refused = infokey.DigestKey(call).keys(nodes, envs, 0, closed=False)
        self.assertEqual((keys.shape, keys.dtype), ((4, infokey.KEY_BYTES), np.uint8))
        self.assertEqual(refused.tolist(), (statuses[envs] != 0).tolist())
        self.assertEqual(keys.tobytes(), np.where(refused[:, None], 0, digests[envs]).astype(np.uint8).tobytes())
        self.assertFalse(refused.all())

    def test_a_refused_digest_refuses_its_key(self):
        call = Recorded(refuse={1, 6})
        nodes = infokey.DigestNodes(self.batch(), call)
        self.expand(nodes)
        keys, refused = infokey.DigestKey(call).keys(nodes, np.arange(self.n), 0, closed=False)
        self.assertTrue(refused[1] and refused[6])
        self.assertFalse(keys[[1, 6]].any())

    def test_a_failed_step_refuses_its_key_without_raising(self):
        # 0082: a failed step keeps digest status OK with zero bytes; its key is invalid because of the step status.
        call = Recorded()
        nodes = infokey.DigestNodes(self.batch(), call)
        choices = self.choices.copy()
        choices["slot"][2, 0] = 255  # an option outside every domain: leaf 2's step is refused
        step = self.expand(nodes, choices=choices)[1].copy()
        self.assertNotEqual(int(step[2]), 0)
        digests, statuses = call.last
        self.assertEqual((int(statuses[2]), bool(digests[2].any())), (0, False))
        keys, refused = infokey.DigestKey(call).keys(nodes, np.arange(self.n), 0, closed=False)
        self.assertTrue(refused[2])
        self.assertFalse(keys[2].any())
        self.assertEqual(refused[step == 0].tolist(), (statuses[step == 0] != 0).tolist())

    def test_a_zero_digest_is_never_a_valid_key(self):
        call = Recorded(zero={2})
        nodes = infokey.DigestNodes(self.batch(), call)
        self.expand(nodes)
        key = infokey.DigestKey(call)
        key.keys(nodes, np.array([0, 1]), 0, closed=False)  # the others stay readable
        with self.assertRaisesRegex(SearchError, "zero"):
            key.keys(nodes, np.array([1, 2]), 0, closed=False)

    def test_a_key_from_an_earlier_expansion_is_refused(self):
        call = Recorded()
        nodes = infokey.DigestNodes(self.batch(), call)
        key = infokey.DigestKey(call)
        self.assertTrue(key.keys(nodes, np.arange(self.n), 0, closed=False)[1].all())  # nothing expanded yet
        self.expand(nodes)
        first = key.keys(nodes, np.arange(self.n), 0, closed=False)
        self.expand(nodes, 0, 3)  # a new expansion of three nodes: the rest are stale
        keys, refused = key.keys(nodes, np.arange(self.n), 0, closed=False)
        self.assertTrue(refused[3:].all())
        self.assertEqual(refused[:3].tolist(), first[1][:3].tolist())
        self.assertEqual(keys[:3].tobytes(), first[0][:3].tobytes())

    def test_another_viewer_is_refused(self):
        call = Recorded()
        nodes = infokey.DigestNodes(self.batch(), call)
        self.expand(nodes)
        self.assertTrue(infokey.DigestKey(call).keys(nodes, np.arange(self.n), 1, closed=False)[1].all())

    def test_chunks_store_by_logical_index(self):
        whole_call = Recorded()
        whole = infokey.DigestNodes(self.batch(), whole_call)
        self.expand(whole)
        want = infokey.DigestKey(whole_call).keys(whole, np.arange(self.n), 0, closed=False)
        for chunk in (1, 3, 5):
            with self.subTest(chunk=chunk):
                call = Recorded()
                nodes = infokey.DigestNodes(self.batch(chunk), call, capacity=self.n)
                for start in range(0, self.n, chunk):
                    self.expand(nodes, start, min(self.n, start + chunk), offset=start)
                got = infokey.DigestKey(call).keys(nodes, np.arange(self.n), 0, closed=False)
                self.assertEqual(got[0].tobytes(), want[0].tobytes())
                self.assertEqual(got[1].tolist(), want[1].tolist())

    def test_a_chunk_past_the_capacity_is_refused_and_changes_nothing(self):
        call = Recorded()
        nodes = infokey.DigestNodes(self.batch(), call)
        self.expand(nodes)
        key = infokey.DigestKey(call)
        before = key.keys(nodes, np.arange(self.n), 0, closed=False)
        with self.assertRaisesRegex(ValueError, "capacity"):
            self.expand(nodes, 0, 3, offset=self.n - 2)
        self.assertEqual(call.calls, [self.n])  # refused before the call
        after = key.keys(nodes, np.arange(self.n), 0, closed=False)
        self.assertEqual((after[0].tobytes(), after[1].tolist()), (before[0].tobytes(), before[1].tolist()))
        with self.assertRaisesRegex(ValueError, "capacity"):
            key.keys(nodes, np.array([self.n]), 0, closed=False)

    def test_the_adapter_forwards_reads_and_refuses_the_rest(self):
        raw = self.batch()
        nodes = infokey.DigestNodes(raw, Recorded())
        self.assertIs(nodes.batch, raw)
        self.assertEqual(nodes.envs, raw.envs)
        self.assertIs(nodes.requests, raw.requests)
        self.expand(nodes)
        obs, _, _ = nodes.query_encoded(4, self.mask)
        self.assertEqual(obs.shape[0], self.n)
        with self.assertRaisesRegex(AttributeError, "stale"):
            nodes.step_factored  # an operation that may change an environment would leave its key stale

    def test_the_digest_holds_under_closed_team_sheets(self):
        call = Recorded()
        nodes = infokey.DigestNodes(self.batch(), call)
        self.expand(nodes)
        key = infokey.DigestKey(call)
        open_ = key.keys(nodes, np.arange(self.n), 0, closed=False)
        closed = key.keys(nodes, np.arange(self.n), 0, closed=True)
        self.assertEqual(open_[0].tobytes(), closed[0].tobytes())

    def test_the_digest_key_needs_the_adapter(self):
        with self.assertRaisesRegex(TypeError, "DigestNodes"):
            infokey.DigestKey(Recorded()).keys(self.batch(), np.arange(1), 0, closed=False)

    def test_make_builds_the_digest_key_on_the_librarys_call(self):
        key = infokey.make("digest")
        raw = self.batch()
        nodes = key.nodes(raw)
        self.assertIsInstance(nodes, infokey.DigestNodes)
        self.assertIs(nodes.batch, raw)
        self.expand(nodes)
        keys, refused = key.keys(nodes, np.arange(self.n), 0, closed=False)
        self.assertFalse(refused.any())  # every plan leaf steps and is keyed

    def test_the_keys_agree_with_the_batchs_own_sidecar(self):
        raw = self.batch()
        nodes = infokey.DigestNodes(raw, Recorded())
        self.expand(nodes)
        envs = np.array([0, 3, 5, 7])
        for viewer in (0, 1):
            ours = infokey.DigestKey(None).keys(nodes, envs, viewer, closed=False)
            theirs = raw.observation_keys(envs, viewer)
            self.assertEqual(ours[0].tobytes(), theirs[0].tobytes())
            self.assertEqual(ours[1].tolist(), theirs[1].tolist())

    def test_the_same_step_gives_the_same_key_and_other_steps_other_keys(self):
        nodes = infokey.DigestNodes(self.batch(), Recorded())
        twice = np.concatenate([self.choices[:1], self.choices[:1], self.choices[1:]])
        root_envs = np.concatenate([self.root_envs[:1], self.root_envs])
        nodes.expand(self.roots, 4, self.mask, 7, np.arange(1, self.roots.envs + 1, dtype=np.uint64),
                     np.zeros(self.roots.envs, np.uint8), root_envs[:self.n], np.zeros(self.n, np.uint32),
                     twice[:self.n])
        keys, refused = infokey.DigestKey(None).keys(nodes, np.arange(self.n), 0, closed=False)
        self.assertFalse(refused.any())
        self.assertEqual(keys[0].tobytes(), keys[1].tobytes())  # one leaf twice: one observation
        self.assertGreater(len({k.tobytes() for k in keys}), 1)  # other leads and moves: other observations


if __name__ == "__main__":
    unittest.main()
