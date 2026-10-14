"""The observation keys of our depth-1 nodes (D2 of the depth search; docs/superpowers/specs/2026-10-13-depth-search-
design.md section 4.2, Q3; plan docs/superpowers/plans/2026-10-14-depth-search-d2.md steps 2 and 9).

Two of our depth-1 nodes share an information set exactly when our root row is the same and everything our seat saw
during the step is the same. Python must not decide what we saw, so the key comes from the engine:

- "digest": the engine's 32-byte observation digest of the step for the viewer (decision 0082), written by the digest
  sibling of duoforge_batch_expand in the same call that expands the node. DigestNodes routes the node batch's expand
  to that call and keeps its digests in a sidecar by logical node index; DigestKey reads it. Until the library has the
  call, this key is refused by name. The statuses are 0082's; the call's Python shape is PROVISIONAL until E1b of
  #485 brings the call and its binding (_library_digest_call).
- "record": the SHA-256 of the viewer's public record of the node, for tests only (decision of 2026-10-14). Under open
  team sheets every world gives the root record back, so it never splits nodes by a hidden fact; it may merge nodes
  whose lines differ but fold to the same record. Under closed team sheets a world's record holds its particle's facts,
  so it would split one information set by particle: refused by name there.

A key provider gives the node batch the search expands into (nodes(batch)) and maps nodes (logical node indices, the
node batch's environments) to (keys (n, KEY_BYTES) uint8, refused (n,) bool): refused marks a node whose key the engine
refuses; the search counts it by name.
"""
import hashlib

import numpy as np

from .errors import SearchError

KEY_BYTES = 32
INFO_KEYS = ("digest", "record")
DIGEST_OK = 0  # DUOFORGE_OK (decision 0082): a phase that succeeded; any other step or digest status refuses a key

# The node batch's reads the digest adapter forwards: none changes an environment, so none can leave a key stale.
_FORWARDED = frozenset(("envs", "requests", "domains", "counts", "statuses", "query_factored", "query_encoded",
                        "public", "tiebreak", "result", "observe_ext"))


class RecordKey:
    """The SHA-256 of each node's public record for the viewer (tests only, open team sheets only)."""
    name = "record"

    def nodes(self, batch):
        return batch

    def keys(self, nodes, envs, viewer, closed):
        if closed:
            raise SearchError("info_key 'record' refuses closed team sheets: a world's record holds its particle's "
                              "facts and would split one information set by particle")
        envs = np.asarray(envs, dtype=np.int64)
        records, statuses = nodes.public(np.full(nodes.envs, int(viewer), np.uint32))
        out = np.zeros((envs.size, KEY_BYTES), dtype=np.uint8)
        refused = np.asarray(statuses)[envs] != 0
        for x, e in enumerate(envs.tolist()):
            if not refused[x]:
                out[x] = np.frombuffer(hashlib.sha256(records[e].tobytes()).digest(), dtype=np.uint8)
        return out, refused


class DigestNodes:
    """A node batch whose expand goes to the digest call (call(batch, *Batch.expand's arguments) -> Batch.expand's
    five arrays, digests (n, KEY_BYTES) uint8, digest statuses (n,)) and returns Batch.expand's five arrays. The
    digests land in a sidecar of capacity logical nodes (default: the batch's environments), allocated here: the
    chunk's leaf x at logical node offset + x, with its step status, its viewer and the expansion's generation (0082:
    a failed step keeps digest status OK with zero bytes, its key invalid because of the step). An expand at offset 0
    starts a new generation, so the keys of an earlier expansion are refused, never reused. Only reads of the batch
    are forwarded (an operation that changes an environment would leave its key stale); batch is the batch itself,
    for the calls that take it as their source."""

    def __init__(self, batch, call, capacity=None):
        capacity = batch.envs if capacity is None else capacity
        if type(capacity) is not int or capacity < 1:
            raise ValueError(f"the digest sidecar's capacity must be a positive int (got {capacity!r})")
        self.batch, self.capacity, self._call = batch, capacity, call
        self.digests = np.zeros((capacity, KEY_BYTES), np.uint8)
        self.digest_statuses = np.zeros(capacity, np.uint32)
        self.step_statuses = np.zeros(capacity, np.uint32)
        self.viewers = np.zeros(capacity, np.uint8)
        self.generations = np.zeros(capacity, np.uint64)
        self.generation = 0  # no expansion yet: no entry is valid

    def __getattr__(self, name):
        if name in _FORWARDED:
            return getattr(self.batch, name)
        raise AttributeError(f"DigestNodes does not forward {name!r}: an operation that may change an environment "
                             f"would leave its key stale (use .batch where the batch is only read)")

    def expand(self, roots, version, ext_supported, seed, keys, viewers, root_envs, samples, choices, *, offset=0):
        n = len(root_envs)
        if type(offset) is not int or offset < 0 or offset + n > self.capacity:
            raise ValueError(f"{n} nodes at offset {offset!r} do not fit the digest sidecar's capacity "
                             f"{self.capacity}")
        *legacy, digests, statuses = self._call(self.batch, roots, version, ext_supported, seed, keys, viewers,
                                                root_envs, samples, choices)
        digests, statuses = np.asarray(digests), np.asarray(statuses)
        if digests.shape != (n, KEY_BYTES) or digests.dtype != np.uint8 or statuses.shape != (n,):
            raise SearchError(f"the digest call returned digests {digests.shape} {digests.dtype} and statuses "
                              f"{statuses.shape} for {n} nodes")
        if offset == 0:
            self.generation += 1
        span = slice(offset, offset + n)
        self.digests[span] = digests
        self.digest_statuses[span] = statuses
        self.step_statuses[span] = legacy[1]
        self.viewers[span] = np.asarray(viewers)[np.asarray(root_envs, dtype=np.int64)]
        self.generations[span] = self.generation
        return tuple(legacy)


class DigestKey:
    """The engine's observation digest of each node (decision 0082), read from the DigestNodes sidecar its call filled.
    A node's key is refused where its step or digest status is not DIGEST_OK, where it comes from an earlier
    expansion or another viewer; 32 zero bytes after a successful step and digest break the call's contract and
    raise. It holds under closed
    team sheets: the engine folds only what the viewer saw."""
    name = "digest"

    def __init__(self, call):
        self._call = call

    def nodes(self, batch):
        return DigestNodes(batch, self._call)

    def keys(self, nodes, envs, viewer, closed):
        if not isinstance(nodes, DigestNodes):
            raise TypeError(f"info_key 'digest' reads the sidecar of a DigestNodes batch, not {type(nodes).__name__}")
        envs = np.asarray(envs, dtype=np.int64)
        if envs.size and (envs.min() < 0 or envs.max() >= nodes.capacity):
            raise ValueError(f"a node index outside the digest sidecar's capacity {nodes.capacity}")
        refused = ((nodes.step_statuses[envs] != DIGEST_OK) | (nodes.digest_statuses[envs] != DIGEST_OK)
                   | (nodes.generations[envs] != nodes.generation)
                   | (nodes.viewers[envs] != int(viewer)) | (nodes.generation == 0))
        out = np.where(refused[:, None], 0, nodes.digests[envs]).astype(np.uint8)
        zero = np.flatnonzero(~refused & ~out.any(axis=1))
        if zero.size:
            raise SearchError(f"observation_digest_zero: node {int(envs[zero[0]])} stepped and its digest status is "
                              f"OK, yet its digest is 32 zero bytes, never a valid key (decision 0082)")
        return out, refused


def _library_digest_call():
    """The library's digest sibling of duoforge_batch_expand (decision 0082). E1b of #485 brings it; until then the
    key is refused by name."""
    raise SearchError("observation_digest_unavailable: info_key 'digest' needs the engine's observation digest "
                      "(decision 0082, the digest sibling of duoforge_batch_expand; E1b of #485), not in this library")


def make(name):
    """The key provider of an info_key setting. "digest" is refused by name until the library has the digest call; an
    unknown name is a ValueError."""
    if name not in INFO_KEYS:
        raise ValueError(f"info_key must be one of {INFO_KEYS} (got {name!r})")
    if name == "digest":
        return DigestKey(_library_digest_call())
    return RecordKey()
