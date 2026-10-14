"""PROVISIONAL STUB of the engine's observation digest call (decision 0082, docs/decisions/0082-observation-digest.md;
E1b of #485 brings the call and its Python binding).

It stands in for duoforge_batch_expand_digest so that D2's Python side (infokey.DigestNodes and infokey.DigestKey) is
tested before the call exists. Its statuses follow 0082 ("Status values and publication"): DUOFORGE_OK where the
phase succeeded; a refused projection has a nonzero digest status (here DUOFORGE_E_UNSUPPORTED) and zero bytes; a
failed step keeps digest status OK with zero bytes, its key invalid because of the step status; a stepped leaf, TERMINAL
included, has a digest. Its Python call shape is this file's placeholder until E1b's binding, and its bytes are not the
engine's: the tests that use it test the Python plumbing only (the sidecar by logical node index, its generation and
viewer, refusals by status), never what the viewer saw. After E1b the real call replaces it and this file goes.

A call (batch, roots, version, ext_supported, seed, keys, viewers, root_envs, samples, choices) returns Batch.expand's
five arrays plus digests (n, 32) uint8 and digest_statuses (n,) uint32; leaf i is viewed by viewers[root_envs[i]]. The
stub's digest of a stepped leaf is a SHA-256 over a stub tag, the leaf's viewer and that viewer's public record: under
open team sheets it partitions the nodes exactly as the record key does; where the engine refuses that record, the stub
refuses the digest.
"""
import hashlib

import numpy as np

from duoforge import _layout

DIGEST_OK = 0  # DUOFORGE_OK
DIGEST_REFUSED = _layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"]  # 0082: an unclassified line or request refuses so


class StubDigest:
    """The stub call. refuse: leaf indices of a call (0 .. n - 1) whose digest it refuses; zero: indices it reports ok
    with 32 zero bytes after a successful step (a breach of the contract that the key must reject); calls: each call's
    leaf count; last: the last call's (digests, digest_statuses), copied."""

    def __init__(self, refuse=(), zero=()):
        self.refuse, self.zero = set(refuse), set(zero)
        self.calls, self.last = [], None

    def __call__(self, batch, roots, version, ext_supported, seed, keys, viewers, root_envs, samples, choices):
        legacy = batch.expand(roots, version, ext_supported, seed, keys, viewers, root_envs, samples, choices)
        step = legacy[1]
        n = len(root_envs)
        self.calls.append(n)
        leaf_viewers = np.asarray(viewers)[np.asarray(root_envs, dtype=np.int64)].astype(np.uint32)
        players = np.zeros(batch.envs, np.uint32)
        players[:n] = leaf_viewers
        records, statuses = batch.public(players)
        digests = np.zeros((n, 32), np.uint8)
        digest_statuses = np.full(n, DIGEST_OK, np.uint32)
        for x in range(n):
            if step[x] != 0:
                continue  # a failed step: the digest phase did not run, status OK, zero bytes (0082)
            if statuses[x] != 0 or x in self.refuse:
                digest_statuses[x] = DIGEST_REFUSED  # a refused projection: zero bytes
                continue
            if x not in self.zero:
                digests[x] = np.frombuffer(hashlib.sha256(b"d2-stub-digest\0" + bytes([int(leaf_viewers[x])])
                                                          + records[x].tobytes()).digest(), np.uint8)
        self.last = (digests.copy(), digest_statuses.copy())
        return (*legacy, digests, digest_statuses)
