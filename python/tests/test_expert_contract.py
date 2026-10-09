"""duoforge.python.expert_contract: the P1 learner contract (plan C4, decision 0024).

Synthetic NumPy adapters only: one follows the contract, each other one
breaks it in one way a real learner could. Learner v2 runs the same
validator against its own adapter in its CI; that gate is not claimed here.
"""
import dataclasses
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

        def row_grad_norms(self, batch):
            return ec.reference_row_grad_norms(batch)

        def value_targets(self, gae):
            return ec.reference_value_targets(gae)

        def drift(self, history):
            return ec.reference_drift(history)

        def recipe(self):
            return dict(ec.RECIPE)

    return Good


class Contract(unittest.TestCase):
    def test_full_joint_provider_normalization_and_gradient(self):
        from duoforge_search import expert_contract as ec
        fixture = ec.make_fixture()
        good = _good()
        result = ec.validate_adapter(good(), fixture)
        self.assertTrue(result.passed, result.failures)
        self.assertEqual(result.failures, ())
        b = fixture.batch
        # The reference itself: a log-softmax over every legal joint action, -inf elsewhere.
        logp = ec.reference_log_softmax(b.logits, b.legal)
        self.assertTrue(np.isneginf(logp[~b.legal]).all())
        lse = np.log(np.sum(np.exp(np.where(b.legal, logp, -np.inf)), axis=1))
        np.testing.assert_allclose(lse, 0.0, atol=1e-12)
        with self.assertRaises(ValueError):
            ec.reference_log_softmax(b.logits[:1], np.zeros_like(b.legal[:1]))

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
                    return np.where(legal, logits, -np.inf) - np.log(np.sum(np.exp(np.where(legal, logits, -np.inf)),
                                                                             axis=1, keepdims=True))

        for bad, check in ((CandidateOnly, "normalization"), (Unmasked, "normalization"),
                           (NanGradient, "gradient"), (NoRefusal, "zero_legal")):
            with self.subTest(adapter=bad.__name__):
                result = ec.validate_adapter(bad(), fixture)
                self.assertFalse(result.passed)
                self.assertTrue(any(f.startswith(check) for f in result.failures), result.failures)

    def test_learner_contract_gae_masks_drift_resume(self):
        from duoforge_search import expert_contract as ec
        from duoforge_learn import returns
        fixture = ec.make_fixture()
        good = _good()
        b = fixture.batch
        # Every row kind is present and the pinned recipe is the plan's.
        self.assertEqual(set(b.kind.tolist()), set(ec.KINDS))
        self.assertEqual(ec.RECIPE, {"batch": 4096, "target_rows": 512, "non_target_rows": 3584, "optimizer": "adam",
                                     "lr": 3e-5, "clip": 0.5, "max_epochs": 4, "max_steps": 128, "ref_coef": 0.1,
                                     "patience": 2, "min_improvement": 1e-4, "max_ref_kl": 0.02})
        terms = ec.reference_loss_terms(b)
        self.assertAlmostEqual(terms["total"], terms["target_kl"] + 0.1 * terms["reference_kl"]
                               + b.c_v * terms["value_loss"], places=12)
        norms = ec.reference_row_grad_norms(b)
        dead = np.isin(b.kind, ("padded", "opponent", "held_out"))
        self.assertTrue((norms[dead] == 0).all())
        self.assertTrue((norms[~dead] > 0).all())
        # Value targets are returns.gae on the stored inputs (truncated game: its bootstrap).
        g = fixture.gae
        np.testing.assert_array_equal(ec.reference_value_targets(g),
                                      returns.gae(g.values, g.rewards, g.done, g.acting, g.bootstrap)[2][:, 0, g.seat])
        self.assertFalse(g.done.any())  # the fixture is cut off, so the bootstrap matters
        cut = ec.GaeFixture(g.values, g.rewards, g.done.copy(), g.acting, g.bootstrap, g.seat)
        cut.done[-1] = True
        self.assertFalse(np.allclose(ec.reference_value_targets(cut), ec.reference_value_targets(g)))
        # Drift rules: patience, minimum improvement, nonfinite and reference-KL stops, best epoch kept.
        for history, expected in fixture.drift_cases:
            with self.subTest(history=history):
                self.assertEqual(ec.reference_drift(history), expected)

        class PaddingInMeans(good):
            def loss_terms(self, batch):
                # Wrong: padded rows counted as ordinary non-target rows.
                kind = np.where(batch.kind == "padded", "non_target", batch.kind)
                return ec.reference_loss_terms(dataclasses.replace(batch, kind=kind))

        class HeldOutGradient(good):
            def row_grad_norms(self, batch):
                norms = ec.reference_row_grad_norms(batch)
                norms[batch.kind == "held_out"] = 1e-3
                return norms

        class OutcomeMse(good):
            def value_targets(self, gae):
                return np.full(gae.values.shape[0], gae.rewards[:, 0, gae.seat].sum())

        class TerminalAtCut(good):
            def value_targets(self, gae):
                return ec.reference_value_targets(ec.GaeFixture(gae.values, gae.rewards, np.ones_like(gae.done),
                                                                gae.acting, gae.bootstrap, gae.seat))

        class IgnoresReferenceKl(good):
            def drift(self, history):
                return ec.reference_drift([{**h, "ref_kl": 0.0} for h in history])

        class OtherRate(good):
            def recipe(self):
                return {**ec.RECIPE, "lr": 1e-4}

        class Raises(good):
            def loss_terms(self, batch):
                raise RuntimeError("not implemented")

        for bad, check in ((PaddingInMeans, "loss"), (HeldOutGradient, "masks"), (OutcomeMse, "gae"),
                           (TerminalAtCut, "gae"), (IgnoresReferenceKl, "drift"), (OtherRate, "recipe"),
                           (Raises, "loss")):
            with self.subTest(adapter=bad.__name__):
                result = ec.validate_adapter(bad(), fixture)
                self.assertFalse(result.passed)
                self.assertTrue(any(f.startswith(check) for f in result.failures), result.failures)
        # The fixture is deterministic: no hidden randomness between runs.
        again = ec.make_fixture()
        np.testing.assert_array_equal(again.batch.logits, b.logits)
        self.assertEqual(again.drift_cases, fixture.drift_cases)


if __name__ == "__main__":
    unittest.main()
