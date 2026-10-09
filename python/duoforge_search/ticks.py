"""The leaf table of one lockstep tick (stage 3 P2 plan, Task 3).

Prepared decisions (honest.LeafRequest: rows and the open mask) are added as they are prepared. Only open
leaves (those the table reads a value of) are kept, byte-equal rows once, in first-occurrence order (decision,
then cell, then world). evaluate runs them through fixed-capacity value calls in a preallocated buffer, the
tail zero-padded as Lookahead.decide does; scatter gives each request its values back (0.0 where not open,
which the table never reads). Byte-preserving only where a row's value bits do not depend on its position,
neighbours or padding at the pinned capacity (rowprobe, P2 Task 1).
"""
import numpy as np

MAX_ROWS = 196608  # unique open rows per tick: 196608 x 850 float32 rows is about 0.67 GB


class TickTable:
    def __init__(self, width, max_rows=MAX_ROWS):
        self.width, self.max_rows = int(width), int(max_rows)
        self._index = {}
        self._rows = []

    @property
    def unique(self):
        return len(self._rows)

    def add(self, request):
        """The unique-row index of each leaf of request (int64, -1 where not open)."""
        rows = np.asarray(request.rows)
        open_ = np.asarray(request.open, bool)
        if rows.dtype != np.float32 or rows.ndim != 2 or rows.shape[1] != self.width or open_.shape != rows.shape[:1]:
            raise ValueError(f"a request needs (L, {self.width}) float32 rows and an (L,) open mask")
        index = np.full(rows.shape[0], -1, np.int64)
        for leaf in np.flatnonzero(open_):
            key = rows[leaf].tobytes()
            found = self._index.get(key)
            if found is None:
                if len(self._rows) >= self.max_rows:
                    raise ValueError(f"the tick exceeds its limit of {self.max_rows} unique rows")
                found = self._index[key] = len(self._rows)
                self._rows.append(rows[leaf].copy())
            index[leaf] = found
        return index

    def evaluate(self, model, params, buffer):
        """The values (float32) of the unique rows: ceil(U / capacity) calls of exactly the buffer's
        capacity rows, the tail zero-padded."""
        capacity = buffer.shape[0]
        if buffer.dtype != np.float32 or buffer.shape[1:] != (self.width,):
            raise ValueError(f"the buffer must be (capacity, {self.width}) float32")
        values = np.zeros(self.unique, np.float32)
        for start in range(0, self.unique, capacity):
            end = min(self.unique, start + capacity)
            buffer.fill(0)
            buffer[:end - start] = np.stack(self._rows[start:end])
            values[start:end] = np.asarray(model.value(params, buffer))[:end - start]
        return values


def scatter(index, values):
    """A request's per-leaf values from the tick's unique values (0.0 where index is -1)."""
    index = np.asarray(index, np.int64)
    out = np.zeros(index.shape, np.float32)
    mask = index >= 0
    out[mask] = np.asarray(values, np.float32)[index[mask]]
    return out
