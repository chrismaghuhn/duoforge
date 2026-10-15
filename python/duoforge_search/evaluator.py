"""The leaf evaluation of the two-turn tree (D2 of the depth search; docs/superpowers/specs/2026-10-13-depth-search-
design.md sections 6.3 and 7.2; plan docs/superpowers/plans/2026-10-14-depth-search-d2.md step 3).

The tree's leaf phase calls only an evaluator's leaves(): it expands the leaves from their source batch and gives
their step, encode and result statuses, the cut-off's tiebreaks and a value per leaf. Which values are read is the
tree's (a TERMINAL, cut-off or refused leaf's value is not). The evaluator setting picks the implementation:

- "jax": today's mechanics. duoforge_batch_expand in chunks into the leaf batch, the reference's tiebreak for every
  stepped, non-TERMINAL leaf at the cut-off, and the value head through the search's preallocated row buffer: leaf g
  sits at row g mod capacity of value call g div capacity, padded with zeros, whatever the expand chunk is. A row's
  value depends on the batch shape (the lookahead docstring), so the shape is the buffer's, fixed by the settings.
- "engine": the in-engine evaluation of #450 piece 2, D4's hook (#485). Until its library call exists the name is
  refused; its class comes with #485, the tree code does not change.
"""
import time
from typing import NamedTuple

import duoforge
import numpy as np

from .errors import SearchError

EVALUATORS = ("jax", "engine")
UNRESOLVED_TIEBREAK = 0xFFFFFFFF  # a leaf at the cut-off whose tiebreak the engine refuses (E_UNSUPPORTED)


class Leaves(NamedTuple):
    """The evaluated leaves: values (n,) float32, step, encode and results (n,) uint32 (results: DUOFORGE_RESULT_* at
    TERMINAL, else 0), tiebreaks (n,) uint32 (0 off the cut-off, UNRESOLVED_TIEBREAK where it is refused)."""
    values: np.ndarray
    step: np.ndarray
    encode: np.ndarray
    results: np.ndarray
    tiebreaks: np.ndarray


class JaxEvaluator:
    """Leaves expanded into `leaves` (a Batch) and valued by model.value through rows, the search's (capacity, width)
    float32 buffer; chunk: leaves per expand call (default: the buffer's capacity)."""
    name = "jax"

    def __init__(self, leaves, model, params, encoder, ext_supported, rows, chunk=None):
        capacity = rows.shape[0]
        chunk = capacity if chunk is None else chunk
        if type(chunk) is not int or not 1 <= chunk <= leaves.envs:
            raise ValueError(f"the expand chunk must be an int in [1, {leaves.envs}] (got {chunk!r})")
        self.batch, self.model, self.params = leaves, model, params
        self.encoder, self.ext_supported, self.rows, self.chunk = int(encoder), int(ext_supported), rows, chunk

    def leaves(self, source, seed, keys, viewers, root_envs, samples, choices, cut, costs=None):
        """The Leaves of root_envs[i] of source stepped with choices[i] under the search seeds of (seed,
        keys[root_envs[i]], samples[i]) (Batch.expand), viewed by viewers[root_envs[i]]; cut (n,) bool: the leaves at
        the arena's cut-off. costs (optional): seconds added to "leaves" (engine) and "network"."""
        n = len(root_envs)
        cut = np.asarray(cut, dtype=bool)
        if cut.shape != (n,):
            raise ValueError(f"cut needs one flag per leaf ({n})")
        values = np.zeros(n, np.float32)
        step, encode, results, tiebreaks = (np.zeros(n, np.uint32) for _ in range(4))
        capacity = self.rows.shape[0]
        engine = network = 0.0
        self.rows.fill(0)
        first = fill = 0  # the leaf index of the buffer's row 0, and the rows in it

        def flush():
            nonlocal first, fill, network
            t = time.perf_counter()
            values[first:first + fill] = np.asarray(self.model.value(self.params, self.rows))[:fill]
            network += time.perf_counter() - t
            self.rows.fill(0)
            first, fill = first + fill, 0

        for start in range(0, n, self.chunk):
            end = min(n, start + self.chunk)
            t = time.perf_counter()
            row, st, enc, _, res = self.batch.expand(source, self.encoder, self.ext_supported, seed, keys, viewers,
                                                     root_envs[start:end], samples[start:end], choices[start:end])
            step[start:end], encode[start:end], results[start:end] = st, enc, res
            for x in np.flatnonzero((st == 0) & (res == 0) & cut[start:end]):
                try:
                    tiebreaks[start + x] = self.batch.tiebreak(int(x))
                except duoforge.DuoforgeError as err:
                    if err.status_name != "DUOFORGE_E_UNSUPPORTED":
                        raise
                    tiebreaks[start + x] = UNRESOLVED_TIEBREAK
            engine += time.perf_counter() - t
            done = 0
            while done < end - start:
                take = min(capacity - fill, end - start - done)
                self.rows[fill:fill + take] = row[done:done + take]
                fill, done = fill + take, done + take
                if fill == capacity:
                    flush()
        if fill:
            flush()
        if costs is not None:
            costs["leaves"] += engine
            costs["network"] += network
        return Leaves(values, step, encode, results, tiebreaks)


def make(name, **options):
    """The evaluator of an evaluator setting: "jax" (JaxEvaluator(**options)); "engine" is refused by name until #485's
    library call exists; an unknown name is a ValueError."""
    if name not in EVALUATORS:
        raise ValueError(f"evaluator must be one of {EVALUATORS} (got {name!r})")
    if name == "engine":
        raise SearchError("evaluator_engine_unavailable: the in-engine evaluation is #450 piece 2, D4's hook (#485); "
                          "not in this library")
    return JaxEvaluator(**options)
