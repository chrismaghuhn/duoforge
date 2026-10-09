"""duoforge.python.ticks: a tick's leaf table (stage 3 P2 plan, Task 3).

A fake row-wise value head checks the wiring (dedup, open-leaf filter, fixed chunks, scatter); the bit gate
on the real network is P2 Tasks 1, 4 and 5.
"""
from types import SimpleNamespace
import unittest

import numpy as np

WIDTH = 6


class _Head:
    """A row-wise value head that logs every call's shape."""

    def __init__(self):
        self.calls = []

    def value(self, params, rows):
        rows = np.asarray(rows, np.float32)
        self.calls.append(rows.shape)
        return (rows * np.float32(0.25)).sum(axis=1, dtype=np.float32) + np.float32(0.125)


def _request(rows, open_):
    return SimpleNamespace(rows=np.asarray(rows, np.float32), open=np.asarray(open_, bool))


def _per_request(head, request):
    return np.where(request.open, head.value(None, request.rows), np.float32(0.0)).astype(np.float32)


class TickTable(unittest.TestCase):
    def test_tick_dedup_open_filter_and_fixed_chunks(self):
        from duoforge_search import ticks
        rng = np.random.default_rng(9)
        pool = rng.normal(size=(40, WIDTH)).astype(np.float32)
        a = _request(pool[[0, 1, 2, 3, 1]], [True, True, True, True, True])  # a duplicate inside one request
        b = _request(pool[[2, 4, 5, 6]], [True, False, True, False])  # shares row 2; refused/terminal rows nonzero
        c = _request(pool[[7, 0, 8]], [True, True, False])  # a cut-off leaf: its row is never valued
        table = ticks.TickTable(WIDTH)
        index = [table.add(r) for r in (a, b, c)]
        self.assertEqual(table.unique, 6)  # distinct open rows: 0, 1, 2, 3, 5, 7 (4, 6, 8 are not open)
        for idx, r in zip(index, (a, b, c)):
            self.assertEqual(idx.dtype, np.int64)
            self.assertTrue(((idx >= 0) == r.open).all())  # non-open from the mask, whatever the row holds
        np.testing.assert_array_equal(index[0][[1, 4]], [1, 1])  # the duplicate shares one unique row
        self.assertEqual(index[1][0], index[0][2])  # the same row across requests too
        head = _Head()
        buffer = np.zeros((1024, WIDTH), np.float32)
        values = table.evaluate(head, None, buffer)
        self.assertEqual(head.calls, [(1024, WIDTH)])
        self.assertEqual(values.dtype, np.float32)
        for idx, r in zip(index, (a, b, c)):
            np.testing.assert_array_equal(ticks.scatter(idx, values), _per_request(_Head(), r))
        # Tick sizes: 1 request, 1023 open leaves, 2048 open leaves (an exact multiple): same per-request values.
        many = rng.normal(size=(4096, WIDTH)).astype(np.float32)
        for sizes in ((5,), (1023,), (1000, 1048)):
            requests, start = [], 0
            for n in sizes:
                requests.append(_request(many[start:start + n], np.ones(n, bool)))
                start += n
            head, table = _Head(), ticks.TickTable(WIDTH)
            index = [table.add(r) for r in requests]
            values = table.evaluate(head, None, buffer)
            total = sum(sizes)
            self.assertEqual(head.calls, [(1024, WIDTH)] * -(-total // 1024))
            for idx, r in zip(index, requests):
                np.testing.assert_array_equal(ticks.scatter(idx, values), _per_request(_Head(), r))
        # The tail of the last call is zero padding, never a stale row of an earlier call.
        head, table = _Head(), ticks.TickTable(WIDTH)
        table.add(_request(many[:1030], np.ones(1030, bool)))
        seen = []
        head.value = lambda params, rows: (seen.append(np.array(rows)), _Head.value(head, params, rows))[1]
        table.evaluate(head, None, buffer)
        self.assertFalse(seen[1][6:].any())
        # A hard limit on unique rows, with an explicit error.
        small = ticks.TickTable(WIDTH, max_rows=4)
        small.add(_request(pool[:4], np.ones(4, bool)))
        with self.assertRaisesRegex(ValueError, "limit"):
            small.add(_request(pool[4:6], np.ones(2, bool)))
        with self.assertRaises(ValueError):
            ticks.TickTable(WIDTH).add(_request(pool[:2, :5], np.ones(2, bool)))  # wrong width


if __name__ == "__main__":
    unittest.main()
