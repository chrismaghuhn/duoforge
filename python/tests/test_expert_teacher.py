"""duoforge.python.expert_teacher: the P1 honest teacher (plan C3, decision 0024).

Synthetic tables, masks and a foe-sensitive NumPy network only; no trained
weights, real data or run outputs. The contract is pinned by literals.
"""
import ctypes
import unittest
from unittest import mock

import numpy as np

import duoforge
from duoforge import _layout, features, privileged, view
from duoforge_learn.selfplay import TEAM_TABLE
from duoforge_search import belief, honest, lookahead
from duoforge_search.expert_data import DecisionKey, SparsePolicy

C = _layout.CONSTANTS


class FoeSensitiveNet:
    """A deterministic NumPy stand-in for policy.Model: linear pair, team and
    value heads over the encoded rows, so foe rows and leaves move tables."""

    def __init__(self, seed=20261015, scale=0.05):
        rng = np.random.default_rng(seed)
        self.feature_names = tuple(f"f{i}" for i in range(features.obs_size(4)))
        width = len(self.feature_names)
        self.params = {"pair": (rng.normal(size=(width, 1024)) * scale).astype(np.float32),
                       "slot": (rng.normal(size=(features.SLOT_FEATURES,)) * scale).astype(np.float32),
                       "team": (rng.normal(size=(width, TEAM_TABLE.shape[0])) * scale).astype(np.float32),
                       "value": (rng.normal(size=(width,)) * scale).astype(np.float32)}

    def check(self, obs):
        if np.asarray(obs).shape[-1] != len(self.feature_names):
            raise ValueError("wrong row width")

    @staticmethod
    def _log_softmax(logits, mask):
        logits = np.where(mask, logits, -np.inf)
        top = np.max(logits, axis=-1, keepdims=True)
        return (logits - top - np.log(np.sum(np.exp(logits - top), axis=-1, keepdims=True))).astype(np.float32)

    def apply(self, params, obs, slots, mask):
        obs = np.asarray(obs, np.float32)
        b = obs.shape[0]
        legal = np.asarray(mask, bool).reshape(b, -1)
        slot_term = np.asarray(slots, np.float32).reshape(b, -1, features.SLOT_FEATURES) @ params["slot"]
        pair = obs @ params["pair"] + np.resize(slot_term, (b, 1024))
        pair = self._log_softmax(pair, legal | ~legal.any(axis=1, keepdims=True))
        team = self._log_softmax(obs @ params["team"], np.ones((b, TEAM_TABLE.shape[0]), bool))
        return pair, team, np.tanh(obs @ params["value"])

    def value(self, params, rows):
        return np.tanh(np.asarray(rows, np.float32) @ params["value"]).astype(np.float32)


def _mask(ids):
    mask = np.zeros((32, 32), bool)
    mask.flat[list(ids)] = True
    return mask


def _log_softmax(logits, ids):
    top = float(np.max(logits[ids]))
    return logits - (top + np.log(np.sum(np.exp(logits[ids] - top))))


class FullSpace(unittest.TestCase):
    LEGAL = (3, 7, 40, 41, 100, 200, 300, 400, 500, 513)

    def test_full_target_kl_and_displacement_ties(self):
        from duoforge_search import expert as ex
        mask = _mask(self.LEGAL)
        candidates = np.array([40, 7, 3, 100, 200, 300, 400, 500], np.int64)  # prior-rank order
        # The raw action already among the candidates changes nothing.
        kept = ex.include_student(candidates, 100, mask)
        np.testing.assert_array_equal(kept.ids, candidates)
        self.assertEqual((kept.raw_index, kept.displaced), (3, None))
        # An absent raw action displaces the lowest-ranked candidate; K stays 8.
        shown = ex.include_student(candidates, 513, mask)
        np.testing.assert_array_equal(shown.ids, [40, 7, 3, 100, 200, 300, 400, 513])
        self.assertEqual((shown.raw_index, shown.displaced), (7, 500))
        self.assertEqual(shown.ids.dtype, np.int64)
        # Tied priors: select ranks ties to the lower flat index, so the displaced one is the
        # higher index of the tie, whatever the raw action's own prior.
        logp = np.full(1024, -50.0)
        logp[list(self.LEGAL)] = [-1.0, -2.0, -2.0, -2.0, -3.0, -3.0, -4.0, -4.0, -4.0, -9.0]
        tied, _ = lookahead.select(logp, mask, 8)
        np.testing.assert_array_equal(tied, [3, 7, 40, 41, 100, 200, 300, 400])
        swapped = ex.include_student(tied, 500, mask)
        np.testing.assert_array_equal(swapped.ids, [3, 7, 40, 41, 100, 200, 300, 500])
        self.assertEqual(swapped.displaced, 400)
        # Fewer legal pairs than K: every legal pair is a candidate, the raw action included.
        few = _mask((5, 9))
        small = ex.include_student(np.array([9, 5]), 5, few)
        np.testing.assert_array_equal(small.ids, [9, 5])
        self.assertEqual(small.raw_index, 1)
        for bad in ((np.array([40, 40, 3]), 3), (np.array([40, 1]), 40), (candidates, 1), (candidates, 1024),
                    (candidates, -1), (candidates, True), (np.append(candidates, 513), 513),
                    (np.array([], np.int64), 3), (np.array([40.0, 7.0]), 7)):
            with self.subTest(candidates=bad[0], raw=bad[1]), self.assertRaises(ValueError):
                ex.include_student(bad[0], bad[1], mask)
        with self.assertRaises(ValueError):
            ex.include_student(candidates, 513, mask, k=9)  # K is pinned to 8
        # The full target holds the sparse mass at its joint ids and zero elsewhere.
        policy = SparsePolicy(np.array([40, 7, 513], np.int64), np.array([0.5, 0.25, 0.25]))
        full = ex.full_target(policy, mask)
        self.assertEqual((full.shape, full.dtype), ((1024,), np.float64))
        self.assertEqual((full[40], full[7], full[513]), (0.5, 0.25, 0.25))
        self.assertEqual(np.count_nonzero(full), 3)
        ex.full_target(SparsePolicy(np.array([40, 7], np.int64), np.array([0.5, 0.5 + 9e-7])), mask)
        for ids, probs in (([40, 1], [0.5, 0.5]), ([40, 40], [0.5, 0.5]), ([40, 7], [1.5, -0.5]),
                           ([40, 7], [0.5, np.nan]), ([40, 7], [0.5, 0.5 + 2e-6]), ([40, 1024], [0.5, 0.5]),
                           ([-1, 7], [0.5, 0.5]), (list(self.LEGAL[:9]), [1 / 9] * 9)):
            with self.subTest(ids=ids, probs=probs), self.assertRaises(ValueError):
                ex.full_target(SparsePolicy(np.array(ids, np.int64), np.array(probs, np.float64)), mask)
        # KL(tau || pi) against the student's full-legal distribution differs from the
        # candidate-only renormalization a wrong loss would use.
        logits = np.random.default_rng(20261014).normal(size=1024)
        legal = np.flatnonzero(mask.reshape(-1))
        full_legal = _log_softmax(logits, legal)
        candidate_only = _log_softmax(logits, policy.ids)
        nz = full > 0
        kl_full = float(np.sum(full[nz] * (np.log(full[nz]) - full_legal[nz])))
        kl_cand = float(np.sum(full[nz] * (np.log(full[nz]) - candidate_only[nz])))
        sparse = float(np.sum(policy.probs * (np.log(policy.probs) - full_legal[policy.ids])))
        self.assertAlmostEqual(kl_full, sparse, places=12)
        self.assertGreater(kl_full - kl_cand, 0.1)


class Teacher(unittest.TestCase):
    """label_decision on real roots with the synthetic net (small K, M, W for speed)."""

    @classmethod
    def setUpClass(cls):
        cls.net = FoeSensitiveNet()

    def make(self, ctx, k=3):
        table = belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
        with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            mask = int(b.observe_ext()[0, 0]["supported"])
        return honest.Honest(ctx, self.net, self.net.params, 4, mask, k=k, m=2, s=2, rule="mix",
                             capacity=16, workers=2, table=table)

    def config(self, search, **kw):
        from duoforge_search import expert as ex
        return ex.TeacherConfig(seed=77, k=search.k, m=search.m, worlds=search.s, lam=search.lam,
                                capacity=search.capacity, **kw)

    @staticmethod
    def start_turn(roots):
        roots.query_factored()
        choices = np.zeros((roots.envs, 2), _layout.FACTORED_CHOICE)
        choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
        roots.step_factored(choices)
        roots.query_factored()

    def label(self, search, roots, env, seat, raw, cfg):
        from duoforge_search import expert as ex
        key = DecisionKey(500, seat, int(roots.requests[env, seat]["epoch"]))
        return ex.label_decision(search, roots, env=env, seat=seat, key=key, raw_action=raw,
                                 raw_logp=-1.25, last_step=False, config=cfg)

    def test_teacher_foe_model_and_privileged_traps(self):
        from duoforge_search import expert as ex
        for seat in (0, 1):
            with self.subTest(seat=seat), duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                    duoforge.Batch(ctx, np.repeat(duoforge.reference_setups([0]), 2), 2, 42) as b, \
                    self.make(ctx) as search:
                cfg = self.config(search)
                b.query_factored()  # the collector has queried its roots before observing
                ex.observe(search, b, [0, 1], [seat, seat])  # team preview
                self.start_turn(b)
                ex.observe(search, b, [0, 1], [seat, seat])  # turn start
                v, st = b.public(np.full(2, seat, np.uint32))
                self.assertFalse(st.any())
                # Hidden truth of environment 1 differs: foe stat points, bench order and RNG.
                h = view.hypotheses(2)
                h[0] = privileged.hypothesis(b, 0, seat)  # the foe hidden from this viewer
                h[1] = h[0]
                h[1]["stat_points"] = 0
                h[1]["pick_order"][2:4] = h[0]["pick_order"][2:4][::-1]
                self.assertFalse(b.from_view(np.repeat(v[:1], 2), h).any())
                reseed = b._lib.duoforge_battle_reseed
                reseed.restype = ctypes.c_uint32
                reseed.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64)
                for e in range(2):
                    self.assertEqual(reseed(ctx.handle, b._battle(e), 100 + e, 10 + e), 0)
                v, st = b.public(np.full(2, seat, np.uint32))
                self.assertEqual(v[0].tobytes(), v[1].tobytes())
                truth = [privileged.hypothesis(b, e, seat) for e in range(2)]
                self.assertNotEqual(truth[0].tobytes(), truth[1].tobytes())
                ex.observe(search, b, [0, 1], [seat, seat])
                _, _, pairs = b.query_encoded(4, search.ext_supported)
                raw = int(np.flatnonzero(pairs[0, seat].reshape(-1))[-1])  # a low-prior legal pair
                # Privileged state, the true root bytes and any second (real opponent) network
                # must never be read: the teacher models the foe with its own net only.
                opponent = mock.Mock(side_effect=AssertionError("real opponent network"))
                with mock.patch.object(privileged, "hypothesis", side_effect=AssertionError("privileged")), \
                        mock.patch.object(b._lib, "duoforge_battle_hypothesis", side_effect=AssertionError("direct privileged ABI")), \
                        mock.patch.object(b, "encode", side_effect=AssertionError("true root bytes")):
                    decisions = [self.label(search, b, e, seat, raw, cfg) for e in range(2)]
                opponent.assert_not_called()
                a, c = decisions
                self.assertIs(a.status, ex.RowStatus.TARGET)
                for name in ("world_digest", "table_digest", "label_digest", "action", "behavior_logp"):
                    self.assertEqual(getattr(a, name), getattr(c, name), name)
                np.testing.assert_array_equal(a.target.ids, c.target.ids)
                self.assertIn(raw, a.target.ids.tolist())
                # Negative control: leak the true foe stat points into the sampled worlds and the
                # world digest (and with it the tables) must tell the two environments apart.
                real_sample = search.belief.sample
                current = {}

                def leaky(*args, **kwargs):
                    out = real_sample(*args, **kwargs)
                    out["stat_points"] = np.broadcast_to(truth[current["env"]]["stat_points"][None],
                                                         out["stat_points"].shape).copy()
                    return out

                leaked = []
                with mock.patch.object(search.belief, "sample", side_effect=leaky):
                    for e in range(2):
                        current["env"] = e
                        leaked.append(self.label(search, b, e, seat, raw, cfg))
                self.assertNotEqual(leaked[0].world_digest, leaked[1].world_digest)


if __name__ == "__main__":
    unittest.main()
