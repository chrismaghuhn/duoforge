"""The observation keys of our depth-1 nodes (D2 of the depth search; docs/superpowers/specs/2026-10-13-depth-search-
design.md section 4.2, Q3; plan docs/superpowers/plans/2026-10-14-depth-search-d2.md step 2).

Two of our depth-1 nodes share an information set exactly when our root row is the same and everything our seat saw
during the step is the same. Python must not decide what we saw, so the key comes from the engine:

- "digest": the engine's 32-byte observation digest of the lines the viewer sees in the step, from a sibling call of
  duoforge_batch_expand (decision of 2026-10-14). The call comes after Astra's field step, agreed with Astra, with its
  own decision record; until the library has it, this key is refused by name.
- "record": the SHA-256 of the viewer's public record of the node, for tests only (decision of 2026-10-14). Under open
  team sheets every world gives the root record back, so it never splits nodes by a hidden fact; it may merge nodes
  whose lines differ but fold to the same record. Under closed team sheets a world's record holds its particle's facts,
  so it would split one information set by particle: refused by name there.

A key provider maps nodes (environments of a batch) to (keys (n, KEY_BYTES) uint8, refused (n,) bool): refused marks a
node whose key the engine refuses; the search counts it by name.
"""
import hashlib

import numpy as np

from .errors import SearchError

KEY_BYTES = 32
INFO_KEYS = ("digest", "record")


class RecordKey:
    """The SHA-256 of each node's public record for the viewer (tests only, open team sheets only)."""
    name = "record"

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


def make(name):
    """The key provider of an info_key setting. "digest" is refused by name until the library has the D2 sibling
    call; an unknown name is a ValueError."""
    if name not in INFO_KEYS:
        raise ValueError(f"info_key must be one of {INFO_KEYS} (got {name!r})")
    if name == "digest":
        raise SearchError("observation_digest_unavailable: info_key 'digest' needs the engine's observation digest "
                          "(D2's sibling call of duoforge_batch_expand, spec section 4.2, Q3), not in this library")
    return RecordKey()
