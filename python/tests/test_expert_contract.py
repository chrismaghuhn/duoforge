"""duoforge.python.expert_contract: the P1 learner contract (plan C4, decision 0024).

Synthetic NumPy adapters only: one follows the contract, each other one
breaks it in one way a real learner could. Learner v2 runs the same
validators against its own code in its CI; that gate is not claimed here.
"""
import dataclasses
import math
import unittest

import numpy as np


def _good():
    from duoforge_search import expert_contract as ec

    class Good:
        """The contract's own reference, as a learner would wrap its code."""

        def log_softmax(self, logits, legal):
            return ec.reference_log_softmax(logits, legal)

        def kl_grad(self, logits, legal, tau):
            return ec.reference_kl_grad(logits, legal, tau)

        def loss_terms(self, batch):
            return ec.reference_loss_terms(batch)

        def row_gradients(self, batch):
            return ec.reference_row_gradients(batch)

        def value_targets(self, rows):
            return ec.reference_value_targets(rows)

        def drift(self, history):
            return ec.reference_drift(history)

        def recipe(self):
            return dict(ec.RECIPE)

        def target_batches(self, idx, epoch):
            return ec.reference_target_batches(idx, epoch, seed=5)

        def non_target_batches(self, idx, cursor, steps):
            return ec.reference_non_target_batches(idx, cursor, steps, seed=5)

    return Good


def _named(test, result, check):
    test.assertFalse(result.passed)
    test.assertTrue(any(f.startswith(check) for f in result.failures), result.failures)


class Contract(unittest.TestCase):
    def test_full_joint_provider_normalization_and_gradient(self):
        from duoforge_search import expert_contract as ec
        fixture = ec.make_fixture()
        good = _good()
        result = ec.validate_adapter(good(), fixture)
        self.assertTrue(result.passed, result.failures)
        self.assertEqual(result.failures, ())
        b = fixture.batch
        # The reference: a log-softmax over every legal joint action, -inf elsewhere; empty rows refused.
        rows = b.legal.any(axis=1)
        logp = ec.reference_log_softmax(b.logits[rows], b.legal[rows])
        self.assertTrue(np.isneginf(logp[~b.legal[rows]]).all())
        lse = np.log(np.sum(np.exp(np.where(b.legal[rows], logp, -np.inf)), axis=1))
        np.testing.assert_allclose(lse, 0.0, atol=1e-12)
        with self.assertRaises(ValueError):
            ec.reference_log_softmax(b.logits[:1], np.zeros_like(b.legal[:1]))
        # Waiting and preview rows have no legal pair, as in real data; forced rows one.
        self.assertFalse(b.legal[np.isin(b.kind, ("waiting", "preview"))].any())
        self.assertTrue((b.legal[b.kind == "forced"].sum(axis=1) == 1).all())
        self.assertTrue(b.team_legal.all())  # real team masks are all-true

        class CandidateOnly(good):
            def log_softmax(self, logits, legal):
                # Wrong: renormalized over the eight highest legal logits only.
                top = np.argsort(np.where(legal, -logits, np.inf), axis=1, kind="stable")[:, :8]
                keep = np.zeros_like(legal)
                np.put_along_axis(keep, top, True, axis=1)
                return ec.reference_log_softmax(logits, keep & legal)

        class Unmasked(good):
            def log_softmax(self, logits, legal):
                return ec.reference_log_softmax(logits, np.ones_like(legal))

        class NanGradient(good):
            def kl_grad(self, logits, legal, tau):
                p = np.exp(ec.reference_log_softmax(logits, legal))
                return p - tau + 0.0 * ec.reference_log_softmax(logits, legal)  # 0 * -inf

        class NoRefusal(good):
            def log_softmax(self, logits, legal):
                with np.errstate(all="ignore"):
                    masked = np.where(legal, logits, -np.inf)
                    return masked - np.log(np.sum(np.exp(masked), axis=1, keepdims=True))

        for bad, check in ((CandidateOnly, "normalization"), (Unmasked, "normalization"),
                           (NanGradient, "gradient"), (NoRefusal, "zero_legal")):
            with self.subTest(adapter=bad.__name__):
                _named(self, ec.validate_adapter(bad(), fixture), check)
        # The real provider is checked on its own rows: full-legal normalization, -inf, refusal.
        rng = np.random.default_rng(1)
        obs = rng.normal(size=(6, 16)).astype(np.float32)
        weights = rng.normal(size=(16, 1024)).astype(np.float32)
        legal = rng.random((6, 1024)) < 0.1
        legal[:, :3] = True

        def provider(o, s, mask):
            return ec.reference_log_softmax(o @ weights, mask.reshape(len(o), -1)).astype(np.float32)

        def candidate_provider(o, s, mask):
            return CandidateOnly().log_softmax(o @ weights, mask.reshape(len(o), -1))

        def unrefusing(o, s, mask):
            with np.errstate(all="ignore"):
                return NoRefusal().log_softmax(o @ weights, mask.reshape(len(o), -1))

        self.assertEqual(ec.validate_provider(provider, obs, None, legal), ec.ContractResult(True, ()))
        _named(self, ec.validate_provider(candidate_provider, obs, None, legal), "normalization")
        _named(self, ec.validate_provider(unrefusing, obs, None, legal), "zero_legal")

    def test_learner_contract_gae_masks_drift_resume(self):
        from duoforge_search import expert_contract as ec
        fixture = ec.make_fixture()
        good = _good()
        b = fixture.batch
        # Every row kind is present and the pinned recipe is the plan's (with Learner v2's c_V 0.5).
        self.assertEqual(set(b.kind.tolist()), set(ec.KINDS))
        self.assertEqual(ec.RECIPE, {"batch": 4096, "target_rows": 512, "non_target_rows": 3584, "optimizer": "adam",
                                     "lr": 3e-5, "clip": 0.5, "max_epochs": 4, "max_steps": 128, "ref_coef": 0.1,
                                     "value_coef": 0.5, "gamma": 0.99, "lambda": 0.95, "patience": 2,
                                     "min_improvement": 1e-4, "max_ref_kl": 0.02, "ppo_policy": False, "magnet": False})
        terms = ec.reference_loss_terms(b)
        self.assertAlmostEqual(terms["total"], terms["target_kl"] + 0.1 * terms["reference_kl"]
                               + 0.5 * terms["value_loss"], places=12)
        pair, team, value = ec.reference_row_gradients(b)
        dead = np.isin(b.kind, ("padded", "opponent", "held_out"))
        self.assertTrue((pair[dead] == 0).all() and (team[dead] == 0).all() and (value[dead] == 0).all())
        self.assertTrue((pair[np.isin(b.kind, ("waiting", "forced", "preview"))] == 0).all())  # no pair term
        self.assertTrue((team[b.kind != "preview"] == 0).all())
        # Value targets per row from shuffled rows: returns.gae per (game, seat) in tick order.
        rows = fixture.gae
        targets = ec.reference_value_targets(rows)
        self.assertEqual(targets.shape, rows.game_id.shape)
        cut = rows.game_id == 11  # the cut-off game: its bootstrap counts
        bumped = dataclasses.replace(rows, bootstrap=np.where(cut, rows.bootstrap + 1.0, rows.bootstrap))
        self.assertFalse(np.allclose(ec.reference_value_targets(bumped)[cut], targets[cut]))
        np.testing.assert_array_equal(ec.reference_value_targets(bumped)[~cut], targets[~cut])
        gap = dataclasses.replace(rows, logical_tick=np.where(rows.logical_tick == 2, 7, rows.logical_tick))
        with self.assertRaisesRegex(ValueError, "gap"):
            ec.reference_value_targets(gap)
        # Drift: patience against the best, minimum gain, nonfinite metrics, the 0.02 bound itself.
        for history, expected in fixture.drift_cases:
            with self.subTest(history=history):
                self.assertEqual(ec.reference_drift(history), expected)
        # Batches: every target once per epoch with a padded tail; a resumable non-target stream.
        tb = ec.reference_target_batches(np.arange(1100), 0, seed=5)
        self.assertEqual(tb.shape, (3, 512))
        self.assertEqual(sorted(tb[tb >= 0].tolist()), list(range(1100)))
        self.assertTrue((tb.reshape(-1)[1100:] == -1).all())

        class PaddingInMeans(good):
            def loss_terms(self, batch):
                # Wrong: padded rows counted as ordinary non-target rows.
                kind = np.where(batch.kind == "padded", "non_target", batch.kind)
                return ec.reference_loss_terms(dataclasses.replace(batch, kind=kind))

        class ForcedInReference(good):
            def loss_terms(self, batch):
                kind = np.where(batch.kind == "forced", "non_target", batch.kind)
                return ec.reference_loss_terms(dataclasses.replace(batch, kind=kind))

        class OtherValueCoef(good):
            def loss_terms(self, batch):
                terms = ec.reference_loss_terms(batch)
                return {**terms, "total": terms["total"] + 0.5 * terms["value_loss"]}  # c_V 1.0

        class HeldOutGradient(good):
            def row_gradients(self, batch):
                pair, team, value = ec.reference_row_gradients(batch)
                value = value.copy()
                value[batch.kind == "held_out"] = 1e-3
                return pair, team, value

        class FlippedGradient(good):
            def row_gradients(self, batch):
                pair, team, value = ec.reference_row_gradients(batch)
                return -pair, team, value  # same norms, wrong direction

        class OutcomeMse(good):
            def value_targets(self, rows):
                final = {g: rows.reward[rows.game_id == g].sum() for g in set(rows.game_id.tolist())}
                return np.array([final[g] for g in rows.game_id.tolist()])

        class TerminalAtCut(good):
            def value_targets(self, rows):
                last = np.zeros_like(rows.done)
                for g in set(rows.game_id.tolist()):
                    i = np.flatnonzero(rows.game_id == g)
                    last[i[np.argmax(rows.logical_tick[i])]] = True
                return ec.reference_value_targets(dataclasses.replace(rows, done=rows.done | last))

        class DropsWaiting(good):
            def value_targets(self, rows):
                out = np.zeros(rows.game_id.shape)
                acting = rows.acting
                keep = dataclasses.replace(rows, **{f.name: getattr(rows, f.name)[acting]
                                                    for f in dataclasses.fields(rows) if f.name != "seat_first"})
                renumbered = keep.logical_tick.copy()
                for g in set(keep.game_id.tolist()):
                    i = np.flatnonzero(keep.game_id == g)
                    renumbered[i[np.argsort(keep.logical_tick[i])]] = np.arange(i.size)
                out[acting] = ec.reference_value_targets(dataclasses.replace(keep, logical_tick=renumbered))
                return out

        class PreviousEpochGain(good):
            def drift(self, history):
                prev, stale = history[0]["held_kl"], 0
                for epoch, h in enumerate(history[1:], start=1):
                    if not all(math.isfinite(v) for v in h.values()) or h["ref_kl"] > 0.02:
                        return True, 0
                    stale = 0 if h["held_kl"] < prev - 1e-4 else stale + 1
                    prev = h["held_kl"]
                    if stale >= 2 or epoch >= 4:
                        return True, epoch
                return False, len(history) - 1

        class IgnoresReferenceKl(good):
            def drift(self, history):
                return ec.reference_drift([{**h, "ref_kl": 0.0} for h in history])

        class OtherRate(good):
            def recipe(self):
                return {**ec.RECIPE, "lr": 1e-4}

        class RepeatsTargets(good):
            def target_batches(self, idx, epoch):
                out = ec.reference_target_batches(idx, epoch, seed=5)
                out[-1, 0] = out[0, 0]  # a label twice in one epoch
                return out

        class SameOrderEveryEpoch(good):
            def target_batches(self, idx, epoch):
                return ec.reference_target_batches(idx, 0, seed=5)

        class RestartsStream(good):
            def non_target_batches(self, idx, cursor, steps):
                return ec.reference_non_target_batches(idx, (0, 0), steps, seed=5)  # ignores the cursor

        class Raises(good):
            def loss_terms(self, batch):
                raise RuntimeError("not implemented")

        for bad, check in ((PaddingInMeans, "loss"), (ForcedInReference, "loss"), (OtherValueCoef, "loss"),
                           (HeldOutGradient, "gradients"), (FlippedGradient, "gradients"), (OutcomeMse, "gae"),
                           (TerminalAtCut, "gae"), (DropsWaiting, "gae"), (PreviousEpochGain, "drift"),
                           (IgnoresReferenceKl, "drift"), (OtherRate, "recipe"), (RepeatsTargets, "batches"),
                           (SameOrderEveryEpoch, "batches"), (RestartsStream, "batches"), (Raises, "loss")):
            with self.subTest(adapter=bad.__name__):
                _named(self, ec.validate_adapter(bad(), fixture), check)
        # The fixture is deterministic: no hidden randomness between runs.
        again = ec.make_fixture()
        np.testing.assert_array_equal(again.batch.logits, b.logits)
        self.assertEqual(again.drift_cases, fixture.drift_cases)


if __name__ == "__main__":
    unittest.main()
