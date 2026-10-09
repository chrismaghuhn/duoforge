"""duoforge.python.expert_teacher: the P1 honest teacher (plan C3, decision 0024).

Synthetic tables, masks and a foe-sensitive NumPy network only; no trained
weights, real data or run outputs. The contract is pinned by literals.
"""
import ctypes
import dataclasses
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


class ReduceBudget(unittest.TestCase):
    def test_reduce_without_budget_calls_the_solvers_as_before(self):
        # The search paths without a teacher budget keep calling matrix.solve/solve_bayes exactly as before
        # (test_search patches them with one-argument stand-ins).
        a = np.array([[[1.0, -1.0], [-1.0, 1.0]]])
        single = honest.matrix.solve(a[0])
        bayes = honest.matrix.solve_bayes(a, [1.0])
        with mock.patch.object(honest.matrix, "solve", lambda table: single):
            honest.reduce(a, [1.0], [[0.5, 0.5]], [0, 1], 0.5, 0.5, oracle=True)
        with mock.patch.object(honest.matrix, "solve_bayes", lambda tables, weights: bayes):
            honest.reduce(a, [1.0], [[0.5, 0.5]], [0, 1], 0.5, 0.5)
        ledger = honest.matrix.WorkLedger()
        honest.reduce(a, [1.0], [[0.5, 0.5]], [0, 1], 0.5, 0.5, budget=ledger)
        self.assertGreater(ledger.consumed.float_pivots, 0)


class Teacher(unittest.TestCase):
    """label_decision on real roots with the synthetic net, at the P1 sizes (K = M = 8, W = 16,
    capacity 1024): 1024 primary and 1152 audit leaves, the audit in two expand chunks."""

    @classmethod
    def setUpClass(cls):
        from duoforge_search import expert_data as ed
        from python.tests.test_expert_data import manifest
        cls.net = FoeSensitiveNet()
        cls.manifest = manifest(ed)

    def make(self, ctx, k=8, net=None, seed=lookahead.SEARCH_SEED, excluded=None):
        net = net or self.net
        table = belief.SpreadTable.from_sides(duoforge.reference_setups([0])["sides"].reshape(-1))
        with duoforge.Batch(ctx, duoforge.reference_setups([0]), 1, 42) as b:
            mask = int(b.observe_ext()[0, 0]["supported"])
        return honest.Honest(ctx, net, net.params, 4, mask, k=k, m=8, s=16, rule="mix", capacity=1024,
                             workers=2, table=table, seed=seed, exclude_teams=excluded)

    def config(self, **kw):
        from duoforge_search import expert as ex
        return ex.TeacherConfig.from_manifest(self.manifest, **kw)

    @staticmethod
    def start_turn(roots):
        roots.query_factored()
        choices = np.zeros((roots.envs, 2), _layout.FACTORED_CHOICE)
        choices["picks"][:, :, :4] = np.arange(4, dtype=np.uint8)
        roots.step_factored(choices)
        roots.query_factored()

    def label(self, search, roots, env, seat, raw, cfg, game=None):
        from duoforge_search import expert as ex
        game = 500 + seat if game is None else game
        key = DecisionKey(game, seat, int(roots.requests[env, seat]["epoch"]))
        return ex.label_decision(search, roots, env=env, seat=seat, key=key, raw_action=raw, raw_logp=-1.25,
                                 last_step=False, config=cfg, manifest=self.manifest)

    def turn_roots(self, ctx, search, envs=2, seat=0):
        from duoforge_search import expert as ex
        b = duoforge.Batch(ctx, np.repeat(duoforge.reference_setups([0]), envs), 2, 42)
        b.query_factored()  # the collector has queried its roots before observing
        ex.observe(search, b, list(range(envs)), [seat] * envs)  # team preview
        self.start_turn(b)
        ex.observe(search, b, list(range(envs)), [seat] * envs)  # turn start
        return b

    @staticmethod
    def low_raw(search, roots, env, seat):
        """The legal pair the policy ranks last: never among the top K."""
        obs, slots, pairs = roots.query_encoded(4, search.ext_supported)
        logp = search._policy(obs[env:env + 1, seat], slots[env:env + 1, seat], pairs[env:env + 1, seat])[0][0]
        legal = np.flatnonzero(pairs[env, seat].reshape(-1))
        return int(legal[np.argsort(-logp[legal], kind="stable")][-1])

    def test_teacher_foe_model_and_privileged_traps(self):
        from duoforge_search import expert as ex
        for seat in (0, 1):
            with self.subTest(seat=seat), duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, \
                    self.make(ctx) as search, self.turn_roots(ctx, search, seat=seat) as b:
                cfg = self.config()
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
                raw = self.low_raw(search, b, 0, seat)
                # Privileged state and the true root bytes must never be read; the teacher has no
                # opponent-network input at all and models the foe with its own net only.
                with mock.patch.object(privileged, "hypothesis", side_effect=AssertionError("privileged")), \
                        mock.patch.object(b._lib, "duoforge_battle_hypothesis", side_effect=AssertionError("direct privileged ABI")), \
                        mock.patch.object(b, "encode", side_effect=AssertionError("true root bytes")):
                    a, c = (self.label(search, b, e, seat, raw, cfg) for e in range(2))
                self.assertIs(a.status, ex.RowStatus.TARGET)
                for name in ("world_digest", "table_digest", "label_digest", "action", "behavior_logp"):
                    self.assertEqual(getattr(a, name), getattr(c, name), name)
                np.testing.assert_array_equal(a.target.ids, c.target.ids)
                self.assertIn(raw, a.target.ids.tolist())
                # A second model with other weights as the teacher's foe model changes the tables:
                # the digests see the network that models the foe.
                with self.make(ctx, net=FoeSensitiveNet(seed=99)) as other:
                    other.history[b] = {k: dict(v) for k, v in search.history[b].items()}  # same public history
                    swapped = self.label(other, b, 0, seat, raw, cfg)
                self.assertNotEqual(swapped.table_digest, a.table_digest)
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

    def test_tau_execution_and_explicit_fallbacks(self):
        import math
        from duoforge_search import expert as ex, matrix
        from duoforge_search import expert_data as ed
        m = self.manifest
        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx, self.make(ctx) as search:
            cfg = self.config(audit_threshold=0)
            with self.turn_roots(ctx, search) as b:
                obs, slots, pairs = b.query_encoded(4, search.ext_supported)
                raw = self.low_raw(search, b, 0, 0)
                top = lookahead.select(search._policy(obs[:1, 0], slots[:1, 0], pairs[:1, 0])[0][0], pairs[0, 0], 9)[0]
                self.assertNotIn(raw, top.tolist())
                key = DecisionKey(500, 0, int(b.requests[0, 0]["epoch"]))
                d = self.label(search, b, 0, 0, raw, cfg)
                # TARGET: the raw action displaces the 8th candidate; X's play distribution, the X draw.
                self.assertIs(d.status, ed.RowStatus.TARGET)
                self.assertIsNone(d.cause)
                np.testing.assert_array_equal(d.target.ids, np.append(top[:7], raw))
                self.assertEqual(d.raw_action, raw)
                probs = d.target.probs
                self.assertLessEqual(abs(math.fsum(probs.tolist()) - 1.0), 1e-12)
                self.assertTrue((probs[probs > 0] >= 1e-9).all())
                index = d.target.ids.tolist().index(d.action)
                self.assertEqual(d.behavior_logp, math.log(float(probs[index])))
                u = (ed.selection_word(key, m.seed, domain="X") >> 11) * 2.0 ** -53
                self.assertEqual(index, int(np.flatnonzero(np.cumsum(probs) > u)[0]))
                self.assertEqual((d.work["status"], d.work["leaves"]), ("ok", 8 * 8 * 16))
                self.assertGreater(d.work["float_pivots"], 0)
                self.assertEqual(dict(d.audit), {"selected": False})
                # Work exhaustion: the raw action with the student's likelihood and a named cause.
                tiny = self.config(audit_threshold=0, budget=matrix.WorkBudget(float_pivots=1))
                w = self.label(search, b, 0, 0, raw, tiny)
                self.assertEqual((w.status, w.cause, w.action, w.behavior_logp, w.target),
                                 (ed.RowStatus.WORK_EXHAUSTED, "work:float_pivots", raw, -1.25, None))
                self.assertEqual(w.work["status"], "float_pivots")
                # The K+1 audit: the displaced 8th candidate returns as the 9th, 1152 leaves in two
                # chunks of capacity 1024, on the same worlds and never changing the label.
                audited = self.label(search, b, 0, 0, raw, self.config(audit_threshold=2**64))
                for name in ("action", "behavior_logp", "status", "world_digest", "table_digest", "label_digest"):
                    self.assertEqual(getattr(audited, name), getattr(d, name), name)
                self.assertEqual(audited.audit["status"], "ok")
                self.assertEqual(audited.audit["candidates"], np.append(top[:8], raw).tolist())
                self.assertEqual(audited.audit["leaves"], 9 * 8 * 16)
                for name in ("action_changed", "value", "value_delta", "certificate", "work"):
                    self.assertIn(name, audited.audit)
                self.assertLessEqual(audited.audit["certificate"], 1e-9)
                real = search._decision
                calls = []

                def audit_exhausts(*args, **kwargs):
                    calls.append(1)
                    if len(calls) == 2:
                        raise matrix.WorkBudgetExceeded(matrix.WorkStatus.EXACT_OPS, kwargs["budget"].consumed)
                    return real(*args, **kwargs)

                with mock.patch.object(search, "_decision", side_effect=audit_exhausts):
                    incomplete = self.label(search, b, 0, 0, raw, self.config(audit_threshold=2**64))
                self.assertEqual(incomplete.audit["status"], "exhausted:exact_ops")
                self.assertEqual((incomplete.action, incomplete.label_digest), (d.action, d.label_digest))
                # Only admitted eligible roots of the learner seat are labeled, after observe(),
                # with the manifest's configuration and their own key.
                one = np.zeros_like(pairs)
                one[0, 0].reshape(-1)[raw] = True
                with mock.patch.object(b, "query_encoded", return_value=(obs, slots, one)), \
                        self.assertRaisesRegex(ValueError, "two legal"):
                    self.label(search, b, 0, 0, raw, cfg)
                for game, seat_key in ((500, 1), (501, 0)):  # wrong seat; game 501's learner is seat 1
                    with self.subTest(game=game, seat=seat_key), self.assertRaises(ValueError):
                        ex.label_decision(search, b, env=0, seat=0, key=DecisionKey(game, seat_key, key.request_epoch),
                                          raw_action=raw, raw_logp=-1.0, last_step=False, config=cfg, manifest=m)
                for bad in (ex.TeacherConfig(seed=8, audit_threshold=0), self.config(audit_threshold=0, lam=0.25),
                            self.config(audit_threshold=0, search_seed=5)):
                    with self.subTest(config=bad), self.assertRaises(ValueError):
                        self.label(search, b, 0, 0, raw, bad)
                for bad_logp in (0.5, float("nan")):
                    with self.assertRaises(ValueError):
                        ex.label_decision(search, b, env=0, seat=0, key=key, raw_action=raw, raw_logp=bad_logp,
                                          last_step=False, config=cfg, manifest=m)
                # Visible sleep has no supported public reconstruction: a named public refusal.
                decode = b._lib.duoforge_battle_decode
                decode.restype = ctypes.c_uint32
                decode.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)
                fixture = np.frombuffer(b.encode(1), np.uint8).copy()  # privileged codec fixture only
                fixture[215 + 109 + 27] = C["DUOFORGE_AILMENT_SLEEP"]
                fixture[215 + 109 + 28] = 2
                self.assertEqual(decode(ctx.handle, b._battle(1), fixture.ctypes.data, fixture.size), 0)
                b.query_factored()
                ex.observe(search, b, [1], [0])
                refused = self.label(search, b, 1, 0, raw, cfg, game=502)
                self.assertEqual((refused.status, refused.cause, refused.action, refused.behavior_logp),
                                 (ed.RowStatus.PUBLIC_REFUSAL, "public:visible_sleep", raw, -1.25))
                search.history[b][(1, 0)]["observed"] = -1
                with self.assertRaisesRegex(ValueError, "observe"):  # a request needs observe() first
                    self.label(search, b, 1, 0, raw, cfg, game=502)
            # A collector that never observed the team preview is a bug, not a public refusal.
            with duoforge.Batch(ctx, duoforge.reference_setups([0]), 2, 42) as late:
                late.query_factored()
                self.start_turn(late)
                ex.observe(search, late, [0], [0])
                with self.assertRaisesRegex(ValueError, "team preview"):
                    self.label(search, late, 0, 0, self.low_raw(search, late, 0, 0), cfg)
            # Rows without a search: the pre-drawn raw action and its likelihood, checked statuses.
            capped = ex.raw_decision(ed.RowStatus.CAP_RAW, raw, -2.5, legal_count=5)
            self.assertEqual((capped.status, capped.action, capped.raw_action, capped.behavior_logp, capped.target,
                              capped.cause), (ed.RowStatus.CAP_RAW, raw, raw, -2.5, None, None))
            self.assertIs(ex.raw_decision(ed.RowStatus.UNSELECTED, raw, -0.5, legal_count=2).status, ed.RowStatus.UNSELECTED)
            self.assertIs(ex.raw_decision(ed.RowStatus.FORCED, raw, 0.0, legal_count=1).status, ed.RowStatus.FORCED)
            for status, logp, count in ((ed.RowStatus.FORCED, 0.0, 2), (ed.RowStatus.FORCED, -0.1, 1),
                                        (ed.RowStatus.CAP_RAW, -1.0, 1), (ed.RowStatus.UNSELECTED, -1.0, 1),
                                        (ed.RowStatus.TARGET, -1.0, 3), (ed.RowStatus.PUBLIC_REFUSAL, -1.0, 3),
                                        (ed.RowStatus.WORK_EXHAUSTED, -1.0, 3), (ed.RowStatus.UNREQUESTED, -1.0, 3),
                                        (ed.RowStatus.CAP_RAW, 0.5, 3), (ed.RowStatus.CAP_RAW, float("inf"), 3)):
                with self.subTest(status=status, logp=logp, count=count), self.assertRaises(ValueError):
                    ex.raw_decision(status, raw, logp, legal_count=count)
            self.assertEqual([ex.learner_seat(g) for g in range(4)], [0, 1, 0, 1])
            for bad in (-1, True, 2**64, 1.0):
                with self.assertRaises(ValueError):
                    ex.learner_seat(bad)
            # teacher_row keeps the collector's actual step values and follows validate_row.
            step = ex.StepData(key=key, logical_tick=3, boundary="TURN", obs=obs[0, 0], slots=slots[0, 0],
                               legal_mask=pairs[0, 0], requested=True, reward=0.25, done=False,
                               collector_value=0.1, bootstrap=-0.3)
            row = ex.teacher_row(d, step, m)
            self.assertEqual((row.status, row.admitted, row.acting, row.value_mask, row.action, row.raw_action),
                             (ed.RowStatus.TARGET, True, True, True, d.action, raw))
            self.assertEqual((row.reward, row.done, row.collector_value, row.bootstrap, row.logical_tick),
                             (0.25, False, 0.1, -0.3, 3))
            np.testing.assert_array_equal(row.sparse_policy.probs, d.target.probs)
            self.assertEqual(ex.teacher_row(audited, step, m).audit["work"]["status"], "ok")  # audit work kept
            self.assertEqual(ex.teacher_row(w, step, m).cause, "work:float_pivots")
            self.assertTrue(ex.teacher_row(w, step, m).admitted)
            self.assertFalse(ex.teacher_row(capped, step, m).admitted)
            waiting = ex.teacher_row(None, dataclasses.replace(step, requested=False), m)
            self.assertEqual((waiting.status, waiting.action, waiting.acting, waiting.value_mask),
                             (ed.RowStatus.UNREQUESTED, None, False, True))
            team = np.zeros(360, bool)
            team[:3] = True
            preview = ex.teacher_row(ex.raw_decision(ed.RowStatus.UNSELECTED, 2, -1.1, legal_count=3),
                                     dataclasses.replace(step, boundary="TEAM_SELECTION", legal_mask=team), m)
            self.assertEqual((preview.status, preview.action), (ed.RowStatus.UNSELECTED, 2))
            for bad_step, decision in ((step, None), (dataclasses.replace(step, requested=False), d),
                                       (dataclasses.replace(step, boundary="TEAM_SELECTION"), d),
                                       (dataclasses.replace(step, key=DecisionKey(501, 0, key.request_epoch)), d)):
                with self.assertRaises(ValueError):
                    ex.teacher_row(decision, bad_step, m)

    def test_teacher_resume_permutation_regrouping_clock_bytes(self):
        import itertools
        import json
        from duoforge_search import expert as ex
        from duoforge_search import expert_data as ed
        m = self.manifest
        envs = 3

        def labels(search, b, games, cfg):
            """Decision bytes by game id; games maps each environment slot to its game."""
            out = {}
            for e, game in games:
                raw = self.low_raw(search, b, e, 0)
                key = DecisionKey(game, 0, int(b.requests[e, 0]["epoch"]))
                out[game] = ex.decision_bytes(ex.label_decision(search, b, env=e, seat=0, key=key, raw_action=raw,
                                                                raw_logp=-1.25, last_step=False, config=cfg, manifest=m))
            return out

        def admit(b, games):
            _, _, pairs = b.query_encoded(4, 0)
            cursor = ed.LabelCursor()
            ed.admit_tick(cursor, [ed.AdmissionRequest(DecisionKey(game, 0, int(b.requests[e, 0]["epoch"])), "TURN",
                                                       int(pairs[e, 0].sum())) for e, game in games])
            return cursor

        def run(ctx, games, groups=((0, 1, 2),), resume=False):
            with self.make(ctx) as search, \
                    duoforge.Batch(ctx, np.repeat(duoforge.reference_setups([0]), envs), 2, 42) as b:
                cfg = self.config(audit_threshold=2**64)  # the audit runs too
                b.query_factored()
                for g in groups:
                    ex.observe(search, b, list(g), [0] * len(g))
                self.start_turn(b)
                for g in groups:
                    ex.observe(search, b, list(g), [0] * len(g))
                cursor = admit(b, games)
                if resume:
                    data = ex.teacher_checkpoint(search, b, cursor, cfg, m)
                    with self.make(ctx) as fresh:
                        restored = ex.restore_teacher(fresh, b, data, cfg, m)
                        return labels(fresh, b, games, cfg), ed.cursor_bytes(restored, m)
                return labels(search, b, games, cfg), ed.cursor_bytes(cursor, m)

        with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            base = run(ctx, [(0, 500), (1, 502), (2, 504)])
            self.assertEqual(len(set(base[0].values())), envs)  # each game's own key words
            # Games permuted across environment slots and call order: per-game bytes are unchanged.
            self.assertEqual(run(ctx, [(2, 500), (0, 502), (1, 504)]), base)
            self.assertEqual(run(ctx, [(1, 504), (2, 500), (0, 502)], groups=((2,), (0, 1))), base)
            self.assertEqual(run(ctx, [(0, 502), (2, 504), (1, 500)], resume=True), base)
            jumps = itertools.count()

            def clock(*_):
                return float(next(jumps) ** 2 * 3.5)

            with mock.patch("time.perf_counter", side_effect=clock), mock.patch("time.monotonic", side_effect=clock):
                self.assertEqual(run(ctx, [(0, 500), (1, 502), (2, 504)]), base)
            # Incompatible or partial resumes are refused.
            with self.make(ctx) as search, self.turn_roots(ctx, search, envs) as b:
                cfg = self.config()
                cursor = admit(b, [(0, 500), (1, 502), (2, 504)])
                data = ex.teacher_checkpoint(search, b, cursor, cfg, m)

                def rehashed(change):
                    value = json.loads(data)
                    change(value)
                    content = {k: v for k, v in value.items() if k != "content_sha256"}
                    return json.dumps({**content, "content_sha256": ed._sha(content)}).encode("ascii")

                cases = {
                    "other config": (data, self.config(budget=ex.matrix.WorkBudget(exact_pivots=31)), m, {}),
                    "other manifest": (data, cfg, dataclasses.replace(m, split_seed=8), {}),
                    "truncated": (data[:-9], cfg, m, {}),
                    "tampered": (data.replace(b'"observed":', b'"observed":1', 1), cfg, m, {}),  # a value, unhashed
                    "key version": (rehashed(lambda v: v.__setitem__("key_version", 2)), cfg, m, {}),
                    "schema": (rehashed(lambda v: v.__setitem__("version", 2)), cfg, m, {}),
                    "record size": (rehashed(lambda v: v["histories"][0].__setitem__("preview", "00")), cfg, m, {}),
                    "fewer envs": (data, cfg, m, {"envs": 2}),
                    "other weights": (data, cfg, m, {"net": FoeSensitiveNet(seed=99)}),
                    "other search seed": (data, self.config(search_seed=5), m, {"seed": 5}),
                    "other exclusions": (data, cfg, m, {"excluded": [None, None, 0]}),
                }
                for name, (blob, config, man, change) in cases.items():
                    env_count = change.pop("envs", envs)
                    with self.subTest(name), self.make(ctx, **change) as fresh, \
                            duoforge.Batch(ctx, np.repeat(duoforge.reference_setups([0]), env_count), 2, 42) as other:
                        target = b if env_count == envs else other
                        with self.assertRaises(ValueError):
                            ex.restore_teacher(fresh, target, blob, config, man)
                with self.make(ctx, k=7) as smaller, self.assertRaises(ValueError):
                    ex.restore_teacher(smaller, b, data, cfg, m)  # the search must run the configuration
                with self.assertRaisesRegex(ValueError, "fresh"):
                    ex.restore_teacher(search, b, data, cfg, m)  # never merged into a live history


if __name__ == "__main__":
    unittest.main()
