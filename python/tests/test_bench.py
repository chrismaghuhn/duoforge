"""duoforge.python.bench: the bench signature of the honest search (M12 bundle 7; Stockfish's bench, docs/ROADMAP.md).

Perft (test_perft) guards the legal actions; this guards the search. The honest search X (K = M = 8, 16 worlds, mix
0.5, as P1 and the live mode) decides fixed roots, and a SHA-256 over the discrete parts of its decisions is pinned:
the kind, the chosen action, a refusal's reason and causes, the candidate counts, the world count, the respreads, the
dropped bench tuples, the sampled queue pairs, the leaf table's shape and the network's calls and rows. No float value
or strategy enters it.

Platform stability is the point. A real network's float32 results change in the last bits between BLAS builds, so the
network here is a hash: every output of a row comes from SHAKE-256 of the row's bytes, as integers divided by a power of
two (exact in float32), with no reduction across rows. The engine is deterministic, so the roots are the same on every
platform. The one float step left is the search's own arithmetic (log-softmax, the Bayes solve, the mixed draw); the
minimum-margin self-check below proves that no decision sits near a tie a last-bit difference could flip, so a pin
mismatch is a change of the search, not of the platform.

RULE: a deliberate change of the search updates BENCH_SHA256 in the same commit, with the reason in the commit message.
"""
import hashlib
import json
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_search import belief, honest

from ._pivot_fixture import SETUP as PIVOT_SETUP, play_to_pivot

C = _layout.CONSTANTS
ENCODER = 4  # params-49333's encoder, the live search's network
MARGIN = 1e-6  # the draw and the expected values: far above any last-bit difference of float64 arithmetic here
FLOOR_MARGIN = 1e-12  # a probability against the 1e-9 floor: still a thousand times any rounding of values below 1
BENCH_SHA256 = "8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798"
# (reference setup, random-prefix seed, prefix steps after team selection): TURN and REPLACEMENT roots of the four
# reference setups, reached by the native random policy; the team preview of setup 0 and the scripted PIVOT come apart.
PREFIX_ROOTS = ((0, 0x2026101100000701, 1), (1, 0x2026101100000702, 3), (2, 0x2026101100000703, 5),
                (3, 0x2026101100000704, 2), (0, 0x2026101100000705, 7), (2, 0x2026101100000706, 4),
                (1, 0x2026101100000707, 6))
KEY = 0x2026101100000700


class HashNet:
    """The network shape honest.Honest calls (feature_names, check, apply, value), as a row hash."""

    def __init__(self, encoder):
        self.feature_names = features.feature_names(encoder)
        self.calls = {"apply": 0, "apply_rows": 0, "value": 0, "value_rows": 0}  # the search's network work

    def check(self, obs):
        if np.asarray(obs).shape[-1] != len(self.feature_names):
            raise ValueError("a row of another encoder")

    @staticmethod
    def _stream(row, n):
        return np.frombuffer(hashlib.shake_256(np.ascontiguousarray(row).tobytes()).digest(2 * n), dtype="<u2")

    @staticmethod
    def _log_softmax(z):
        z = z.astype(np.float64)
        z = z - z.max(axis=-1, keepdims=True)
        return (z - np.log(np.exp(z).sum(axis=-1, keepdims=True))).astype(np.float32)

    def value(self, params, rows):
        rows = np.asarray(rows, np.float32)
        self.calls["value"] += 1
        self.calls["value_rows"] += len(rows)
        ints = np.array([int(self._stream(r, 1)[0]) for r in rows], np.int64)
        return ((ints - 32768) / 32768.0).astype(np.float32)  # exact: a multiple of 2^-15 in [-1, 1)

    def apply(self, params, obs, slots, mask):
        obs, mask = np.asarray(obs, np.float32), np.asarray(mask, bool).reshape(len(obs), -1)
        pairs, teams, values = [], [], []
        self.calls["apply"] += 1
        self.calls["apply_rows"] += len(obs)
        for b in range(len(obs)):
            s = self._stream(np.concatenate([obs[b].view(np.uint8), np.asarray(slots[b], np.float32).view(np.uint8)
                                             .reshape(-1)]), mask.shape[1] + 360 + 1)
            logits = (s[:mask.shape[1]] / 256.0).astype(np.float32)  # exact multiples of 2^-8
            pairs.append(np.where(mask[b], logits, np.float32(-1e9)))
            teams.append((s[mask.shape[1]:mask.shape[1] + 360] / 256.0).astype(np.float32))
            values.append(np.float32((int(s[-1]) - 32768) / 32768.0))
        self.last_teams = np.stack(teams)  # the team head's logits of the last call (the previews' margin)
        return self._log_softmax(np.stack(pairs)), self._log_softmax(np.stack(teams)), np.array(values, np.float32)


def _searcher(ctx, mask, rule="mix"):
    table = belief.SpreadTable.from_sides(duoforge.reference_setups([0, 1, 2, 3])["sides"].reshape(-1))
    return honest.Honest(ctx, HashNet(ENCODER), None, ENCODER, mask, k=8, m=8, s=16, rule=rule, lam=0.5,
                         workers=2, table=table)


def _roots(ctx):
    """(name, batch) of every bench root, each queried at its decision point, with its search history built."""
    for setup, seed, steps in PREFIX_ROOTS:
        b = duoforge.Batch(ctx, duoforge.reference_setups([setup]), 1, seed)
        yield f"setup{setup}-steps{steps}", b, seed, steps
    yield "pivot", duoforge.Batch(ctx, duoforge.reference_setups([PIVOT_SETUP]), 1, 42), None, None


def _decide(search, b, seed, steps, key):
    """(the team preview records of both seats, their margins, the root's record): the previews are decided first
    (the search's history of each seat), then the prefix is played and the requested seat decides. A preview's margin
    is its best team logit's distance from the second (the team head's argmax)."""
    b.query_factored()
    previews, margins = [], []
    for p in (0, 1):
        previews.append(search.decide(b, [0], [p], [key + p], [False])[1][0])
        top = np.sort(search.model.last_teams[0].astype(np.float64))[::-1]
        margins.append(float(top[0] - top[1]))
    if seed is None:  # the scripted PIVOT
        play_to_pivot(b)
    else:
        policy = duoforge.RandomPolicy(seed, 1)
        policy.start_episode(0, 0)
        for _ in range(steps + 1):  # the team selection, then the prefix
            b.step_factored(policy.choose_factored(b))
            b.query_factored()
            if b.result(0) != 0:
                raise AssertionError("a bench prefix ended its battle")
    seat = 0 if b.requests["requested"][0, 0] else 1
    return previews, margins, search.decide(b, [0], [seat], [key + 2], [False])[1][0]


def _discrete(record, leaves):
    keep = ("kind", "boundary", "seat", "choice", "reason", "causes", "k", "m", "s", "respreads", "bench_dropped",
            "queue_pairs")
    out = {k: record[k] for k in keep if k in record}
    out["leaves"] = leaves
    return out


def _margins(record):
    """(draw, floor, ev): the smallest distance of a searched decision from a flip. draw: the play draw u from every
    cumulative boundary of the played mixed strategy; floor: a probability from PROBABILITY_FLOOR (an exact zero is
    no risk); ev: the best expected value from the second."""
    from duoforge_search import matrix
    x = np.asarray(record["pi_X"], np.float64)
    p = np.where(x < matrix.PROBABILITY_FLOOR, 0.0, x)
    cum = np.cumsum(p / p.sum())[:-1]
    probabilities = np.concatenate([x, np.asarray(record["x"], np.float64)])
    near = np.abs(probabilities[probabilities != 0.0] - matrix.PROBABILITY_FLOOR)
    expected = np.sort(np.asarray(record["expected"], np.float64))[::-1]
    return (float(np.abs(cum - record["u"]).min()) if cum.size else 1.0, float(near.min()) if near.size else 1.0,
            float(expected[0] - expected[1]) if expected.size > 1 else 1.0)


class Bench(unittest.TestCase):
    def signature(self, rule="mix", check=True):
        """(rows, digest) of the bench under the search rule; check: every decision clears its margin."""
        rows = []
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 1) as probe:
                mask = int(probe.observe_ext()[0, 0]["supported"]) & features.version_features(ENCODER)
            with _searcher(ctx, mask, rule) as search:
                for i, (name, b, seed, steps) in enumerate(_roots(ctx)):
                    with b:
                        search.clear()
                        search.model.calls = dict.fromkeys(search.model.calls, 0)
                        previews, preview_margins, record = _decide(search, b, seed, steps, KEY + 16 * i)
                        leaves = list(search.last[-1]["values"].shape) if record["kind"] == "searched" else None
                        if check:
                            self.assertGreaterEqual(min(preview_margins), MARGIN,
                                                    f"{name}: a team preview sits near a tie: pick another root")
                        if check and record["kind"] == "searched":
                            draw, floor, ev = _margins(record)
                            self.assertGreaterEqual(min(draw, ev), MARGIN, f"{name} sits near a tie: pick another root")
                            self.assertGreaterEqual(floor, FLOOR_MARGIN, f"{name} has a probability at the floor")
                        rows.append({"root": name, "previews": [_discrete(r, None) for r in previews],
                                     "decision": _discrete(record, leaves), "network": dict(search.model.calls)})
        return rows, hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def test_bench_signature(self):
        rows, digest = self.signature()
        kinds = [r["decision"]["kind"] for r in rows]
        boundaries = {r["decision"]["boundary"] for r in rows}
        self.assertGreaterEqual(kinds.count("searched"), 5, rows)  # the bench measures the search, not its refusals
        self.assertTrue({"TURN", "PIVOT"} <= boundaries, boundaries)
        self.assertEqual(digest, BENCH_SHA256,
                         "the bench signature moved: a change of the search, the engine, the encoder or the data "
                         "(any of them changes the roots or the decisions); a deliberate change updates BENCH_SHA256 "
                         "with its reason in the commit message\n" + json.dumps(rows, sort_keys=True, indent=1))

    def test_a_search_change_moves_the_digest(self):
        # The signature is sensitive: the expected-value rule in place of the mixed one gives another digest.
        _, digest = self.signature("ev", check=False)
        self.assertNotEqual(digest, BENCH_SHA256)


if __name__ == "__main__":
    unittest.main()
