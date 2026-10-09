"""The state model's pinned pool table hash against the hash that tests/test_pool_tables.c proves for the generated tables.

tests/test_pool_tables.c recomputes the SHA-256 of the pool canonical bytes from src/data/pool_tables.c and compares it
with POOL_HASH_HEX; the state model (state_v3_model.py) builds the POOL and POOL_DEV context bytes, and so the
fingerprints that tests/test_pool_setup.c pins, from its own POOL_TABLE_HASH. A step that regenerates the tables and
repins POOL_HASH_HEX must carry the same value into the model, or the model's fingerprints go stale without any test
noticing (seen 2026-10-09: steps G43 and G48 left the model at an older hash). No checkout needed.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


class PoolTableHash(unittest.TestCase):
    def test_model_hash_is_the_pinned_table_hash(self):
        pinned = re.findall(r'#define POOL_HASH_HEX "([0-9a-f]{64})"', read('tests/test_pool_tables.c'))
        model = re.findall(r"^POOL_TABLE_HASH = bytes\.fromhex\('([0-9a-f]{64})'\)", read('tools/state_model/state_v3_model.py'),
                           re.M)
        self.assertEqual(len(pinned), 1, 'tests/test_pool_tables.c must pin exactly one POOL_HASH_HEX')
        self.assertEqual(len(model), 1, 'state_v3_model.py must set exactly one POOL_TABLE_HASH')
        self.assertEqual(model[0], pinned[0], 'state_v3_model.py POOL_TABLE_HASH is stale: copy POOL_HASH_HEX of '
                                              'tests/test_pool_tables.c into it and recompute the POOL fingerprints')


if __name__ == '__main__':
    unittest.main()
