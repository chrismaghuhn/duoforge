"""Values that C tests pin and the independent state model (state_v3_model.py) derives, compared without a build.

PoolTableHash: tests/test_pool_tables.c recomputes the SHA-256 of the pool canonical bytes from src/data/pool_tables.c and
compares it with POOL_HASH_HEX; the state model builds the POOL and POOL_DEV context bytes, and so the fingerprints that
tests/test_pool_setup.c pins, from its own POOL_TABLE_HASH. A step that regenerates the tables and repins POOL_HASH_HEX must
carry the same value into the model, or the model's fingerprints go stale without any test noticing (seen 2026-10-09: steps
G43 and G48 left the model at an older hash).

PoolTailSweep: tests/test_pool_tail.c pins the model's POOL envelope (ENVELOPE_HEX), the tail bytes of its example (TAIL_HEX)
and, for every tail byte, the outcome counts of the 255 other values (sweep[]). The model computes all three here (the
pool-tail part of the model only, not its full run) and they must be the C test's values: a step that adds or changes a tail
byte or rule must teach the model first (decision 0015 section 7), or this test fails (seen 2026-10-11: batches 6 to 8 had
left four sweep rows kept by hand).

Stdlib only, no checkout of anything else needed.
"""
import os
import re
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


def strip_c_comments(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def c_hex_string(text, name):
    """The value of `static const char NAME[] = "..." "...";` (adjacent literals joined)."""
    m = re.search(r'static const char %s\[\]\s*=\s*((?:"[0-9a-f]*"\s*)+);' % re.escape(name), text)
    if m is None:
        raise AssertionError('tests/test_pool_tail.c has no %s' % name)
    return ''.join(re.findall(r'"([0-9a-f]*)"', m.group(1)))


def c_sweep_rows(text):
    """The rows of `static const unsigned sweep[DFI_ENC_TAIL_SIZE][SWEEP_COLUMNS] = {...};`, as tuples."""
    m = re.search(r'static const unsigned sweep\[DFI_ENC_TAIL_SIZE\]\[SWEEP_COLUMNS\]\s*=\s*\{(.*?)\n\};', text, re.S)
    if m is None:
        raise AssertionError('tests/test_pool_tail.c has no sweep[DFI_ENC_TAIL_SIZE][SWEEP_COLUMNS] table')
    body = strip_c_comments(m.group(1))
    return [tuple(int(v) for v in row.split(',')) for row in re.findall(r'\{([0-9,\s]*)\}', body)]


def c_sweep_columns(text):
    m = re.search(r'enum\s*\{\s*SWEEP_COLUMNS\s*=\s*(\d+)\s*\}', text)
    if m is None:
        raise AssertionError('tests/test_pool_tail.c has no SWEEP_COLUMNS')
    return int(m.group(1))


class PoolTableHash(unittest.TestCase):
    def test_model_hash_is_the_pinned_table_hash(self):
        pinned = re.findall(r'#define POOL_HASH_HEX "([0-9a-f]{64})"', read('tests/data/test_pool_tables.c'))
        model = re.findall(r"^POOL_TABLE_HASH = bytes\.fromhex\('([0-9a-f]{64})'\)", read('tools/state_model/state_v3_model.py'),
                           re.M)
        self.assertEqual(len(pinned), 1, 'tests/test_pool_tables.c must pin exactly one POOL_HASH_HEX')
        self.assertEqual(len(model), 1, 'state_v3_model.py must set exactly one POOL_TABLE_HASH')
        self.assertEqual(model[0], pinned[0], 'state_v3_model.py POOL_TABLE_HASH is stale: copy POOL_HASH_HEX of '
                                              'tests/test_pool_tables.c into it and recompute the POOL fingerprints')


class PoolTailSweep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, HERE)
        try:
            import state_v3_model as model
        finally:
            sys.path.remove(HERE)
        cls.model = model
        cls.c_text = read('tests/data/test_pool_tail.c')

    def test_envelope_is_the_models(self):
        self.assertEqual(c_hex_string(self.c_text, 'ENVELOPE_HEX'), self.model.pool_tail_envelope().hex(),
                         'tests/test_pool_tail.c ENVELOPE_HEX is not the model\'s "pool_tail envelope"')

    def test_example_is_the_models(self):
        want = self.model.pool_tail_example_bytes().hex()
        got = c_hex_string(self.c_text, 'TAIL_HEX')
        self.assertEqual(len(got), 2 * self.model.TAIL_SIZE, 'TAIL_HEX is not %d bytes' % self.model.TAIL_SIZE)
        diff = [i // 2 for i in range(0, len(want), 2) if want[i:i + 2] != got[i:i + 2]]
        self.assertEqual(diff, [], 'tests/test_pool_tail.c TAIL_HEX differs from the model\'s "pool_tail example" at tail '
                                   'bytes %s' % diff)

    def test_sweep_rows_are_the_models(self):
        columns = self.model.SWEEP_COLUMNS
        self.assertEqual(c_sweep_columns(self.c_text), len(columns),
                         'tests/test_pool_tail.c SWEEP_COLUMNS is not the model\'s column count %s' % (columns,))
        pinned = c_sweep_rows(self.c_text)
        self.assertEqual(len(pinned), self.model.TAIL_SIZE, 'sweep[] must have one row per tail byte')
        start = time.perf_counter()
        rows = self.model.pool_tail_sweep()
        elapsed = time.perf_counter() - start
        derived = [tuple(counts.get(c, 0) for c in columns) for counts in rows]
        wrong = ['  %3d: test_pool_tail.c {%s}, model {%s}' % (off, ', '.join(map(str, c)), ', '.join(map(str, m)))
                 for off, (c, m) in enumerate(zip(pinned, derived)) if c != m]
        self.assertEqual(wrong, [], 'sweep[] rows that are not the model\'s (columns %s); teach the model the rule from '
                                    'the decision notes, never copy the decoder\'s counts:\n%s' % (', '.join(columns),
                                                                                                   '\n'.join(wrong)))
        print('pool tail sweep: %d rows, %d decodes in %.1f s' % (len(rows), 255 * len(rows), elapsed), file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
