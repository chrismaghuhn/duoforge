"""Stage 3 P1, the Learner v2 gate of M12's C4 contract (duoforge_search.expert_contract): the learner's own code
(the model's pair normalization, full_joint_log_probs, the distillation loss, returns.gae through distill_data,
the drift guard and the batch plan) against M12's NumPy reference. The adapter only routes the fixture's arrays
into that code; it computes nothing itself."""
import unittest

import numpy as np


def _scenes():
    if __package__:
        from .test_learn_v2 import _scenes as scenes
    else:
        from test_learn_v2 import _scenes as scenes
    return scenes()


class _HeadModel:
    """A Model whose apply returns the fixture's head outputs: the pairs through the model's own normalization
    (model.pair_log_softmax), the team head as model.apply normalizes it (a log-softmax over all 360 teams,
    inline there); params are {"pairs": (B, 1024) logits, "team": (B, 360) logits, "value": (B,)}."""

    def apply(self, params, obs, slots, mask):
        import jax
        from duoforge_learn import model
        pairs = params["pairs"].reshape(mask.shape)  # the model's pair logits are (B, 32, 32), as its mask
        return model.pair_log_softmax(pairs, mask), jax.nn.log_softmax(params["team"]), params["value"]


_LIVE = ("target", "non_target", "waiting", "forced", "preview")


class _Adapter:
    def __init__(self):
        from duoforge_learn import distill
        self.distill = distill
        self.model = _HeadModel()
        self.plan = distill.BatchPlan(0)

    # The pair normalization the loss uses: the model's masked log-softmax, -inf outside the legal set.
    def log_softmax(self, logits, legal):
        from duoforge_learn import model, policy
        legal = np.asarray(legal, bool)
        policy.refuse_empty_rows(legal)
        return np.asarray(policy.full_joint(model.pair_log_softmax(np.asarray(logits, np.float32), legal), legal))

    def _batch(self, b):
        n = len(b.kind)
        kind = np.asarray(b.kind)
        ids = np.full((n, 8), -1, np.int64)
        probs = np.zeros((n, 8), np.float32)
        for r in range(n):
            support = np.flatnonzero(np.asarray(b.tau[r]) > 0)
            if support.size > 8:
                raise ValueError("a teacher target has more than K = 8 actions")
            ids[r, :support.size] = support
            probs[r, :support.size] = np.asarray(b.tau[r])[support]
        return {"obs": np.zeros((n, 1), np.float32), "slots": np.zeros((n, 1), np.float32),
                "mask": np.asarray(b.legal, bool).reshape(n, 32, 32), "team_mask": np.asarray(b.team_legal, bool),
                "is_team": kind == "preview", "target_ids": ids, "target_probs": probs,
                "has_target": kind == "target", "policy_row": np.isin(kind, ("non_target", "preview")),
                "value_row": np.isin(kind, _LIVE), "value_target": np.asarray(b.value_targets, np.float32),
                "weight": np.isin(kind, _LIVE).astype(np.float32)}

    def _params(self, b):
        return ({"pairs": np.asarray(b.logits, np.float32), "team": np.asarray(b.team_logits, np.float32),
                 "value": np.asarray(b.values, np.float32)},
                {"pairs": np.asarray(b.ref_logits, np.float32), "team": np.asarray(b.ref_team_logits, np.float32),
                 "value": np.zeros(len(b.kind), np.float32)})

    def _grad(self, b, batch):
        import jax
        params, ref = self._params(b)
        return jax.grad(lambda p: self.distill.distill_loss(p, ref, batch, self.model)[0])(params)

    def kl_grad(self, logits, legal, tau):
        from duoforge_search import expert_contract as ec
        n = len(logits)
        b = ec.ContractBatch(np.array(["target"] * n), logits, logits, legal, np.zeros((n, 360), np.float32),
                             np.zeros((n, 360), np.float32), np.ones((n, 360), bool), tau, np.zeros(n, np.float32),
                             np.zeros(n))
        batch = self._batch(b)
        batch["value_row"][:] = False
        # The loss is the mean over the n target rows: n times its gradient is each row's own KL gradient.
        return n * np.asarray(self._grad(b, batch)["pairs"], np.float64)

    def loss_terms(self, b):
        params, ref = self._params(b)
        loss, aux = self.distill.distill_loss(params, ref, self._batch(b), self.model)
        return {"target_kl": float(aux["teacher_kl"]), "reference_kl": float(aux["ref_kl"]),
                "value_loss": float(aux["value_loss"]), "total": float(loss)}

    def row_gradients(self, b):
        grad = self._grad(b, self._batch(b))
        return tuple(np.asarray(grad[k], np.float64) for k in ("pairs", "team", "value"))

    def value_targets(self, rows):
        from duoforge_learn import distill_data
        return distill_data.value_targets(rows.game_id, rows.seat, rows.logical_tick, rows.acting, rows.reward,
                                          rows.done, rows.collector_value, rows.bootstrap)

    def drift(self, history):
        return self.distill.drift([{"held_teacher_kl": h["held_kl"], "held_ref_kl": h["ref_kl"],
                                    "held_value_loss": h["value_loss"]} for h in history])

    def recipe(self):
        from duoforge_learn import distill_data
        d = self.distill
        return {"batch": d.TARGET_ROWS + d.NON_TARGET_ROWS, "target_rows": d.TARGET_ROWS,
                "non_target_rows": d.NON_TARGET_ROWS, "optimizer": d.OPTIMIZER, "lr": d.LR, "clip": d.CLIP,
                "max_epochs": d.MAX_EPOCHS, "max_steps": d.MAX_STEPS, "ref_coef": d.REF_COEF,
                "value_coef": d.VALUE_COEF, "gamma": distill_data.GAMMA, "lambda": distill_data.LAMBDA,
                "patience": d.PATIENCE, "min_improvement": d.MIN_GAIN, "max_ref_kl": d.REF_KL_MAX,
                "ppo_policy": d.PPO_POLICY, "magnet": d.MAGNET}

    def target_batches(self, idx, epoch):
        return self.plan.targets(epoch, idx)

    def non_target_batches(self, idx, cursor, steps):
        return self.plan.non_targets(cursor, idx, steps)


class LearnerContractTest(unittest.TestCase):
    def test_the_learner_passes_the_c4_contract(self):
        from duoforge_search import expert_contract as ec
        result = ec.validate_adapter(_Adapter(), ec.make_fixture())
        self.assertTrue(result.passed, result.failures)

    def test_full_joint_log_probs_passes_the_provider_check(self):
        import jax
        from duoforge_search import expert_contract as ec
        from duoforge_learn import policy
        _, turn = _scenes()
        obs, slots, mask = turn
        model = policy.make(policy.v2_config("S"))
        params = model.init(jax.random.PRNGKey(11))
        result = ec.validate_provider(lambda o, s, legal: model.full_joint_log_probs(params, o, s, legal), obs, slots,
                                      mask)
        self.assertTrue(result.passed, result.failures)


if __name__ == "__main__":
    unittest.main()
