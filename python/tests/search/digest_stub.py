"""PROVISIONAL STUB of the engine's observation digest (decision 0082; E1a fixes its contract, E1b the library call).

It stands in for the digest sibling call of duoforge_batch_expand so that D2's Python side (infokey.DigestNodes and
infokey.DigestKey) is tested before the call exists. Nothing here is the engine's digest: its signature, its status
values and its bytes are this file's placeholders, and the tests that use it test the Python plumbing only (the sidecar
by logical node index, its generation, refusals by status, the tree's keying), never what the viewer saw. After E1a the
stub follows Astra's contract; after E1b the real call replaces it and this file goes.

A call (batch, roots, version, ext_supported, seed, keys, viewers, root_envs, samples, choices) returns Batch.expand's
five arrays plus digests (n, 32) uint8 and digest_statuses (n,) uint32 (0 ok, anything else refused). The stub's digest
of a stepped leaf is a SHA-256 over a stub tag, the leaf's viewer and that viewer's public record: under open team
sheets it partitions the nodes exactly as the record key does.
"""
import hashlib

import numpy as np

STUB_REFUSED = 1  # a placeholder: E1a names the digest statuses


class StubDigest:
    """The stub call. refuse: leaf indices of a call (0 .. n - 1) whose digest it refuses; zero: indices it reports ok
    with 32 zero bytes (a breach of the contract that the key must reject); calls: each call's leaf count; last: the
    last call's (digests, digest_statuses), copied."""

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
        digest_statuses = np.full(n, STUB_REFUSED, np.uint32)
        for x in range(n):
            if step[x] != 0 or statuses[x] != 0 or x in self.refuse:
                continue  # a failed step or a refused record: the digest is refused, its bytes stay zero
            digest_statuses[x] = 0
            if x not in self.zero:
                digests[x] = np.frombuffer(hashlib.sha256(b"d2-stub-digest\0" + bytes([int(leaf_viewers[x])])
                                                          + records[x].tobytes()).digest(), np.uint8)
        self.last = (digests.copy(), digest_statuses.copy())
        return (*legacy, digests, digest_statuses)
