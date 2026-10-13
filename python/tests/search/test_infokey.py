"""The observation keys of D2's depth-1 nodes (duoforge_search.infokey; plan docs/superpowers/plans/2026-10-14-depth-
search-d2.md step 2): the engine digest is refused by name until the library has it; the record key (tests only) is
the SHA-256 of the viewer's public record, equal for equal records, different for different ones, and refused under
closed team sheets."""
import hashlib
import unittest

import numpy as np

import duoforge
from duoforge import _layout
from duoforge_search import SearchError, infokey

C = _layout.CONSTANTS


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
    def test_the_digest_is_refused_by_name_until_the_library_has_it(self):
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


if __name__ == "__main__":
    unittest.main()
