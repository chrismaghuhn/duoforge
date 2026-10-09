"""Distillation of the stage 3 P1 teacher into a raw student (decision 0024; spec section 3; Learner v2 plan
2026-10-08-stage3-p1-learner, tasks 3-5).

    L = mean_target KL(tau || pi) + 0.1 mean_policy KL(pi_ref || pi) + 0.5 mean_value (v - value_target)^2

- tau is the teacher's sparse policy over the 1024 joint actions; the student's distribution is the pair head's
  log-softmax over all legal actions (Model.full_joint_log_probs), never renormalized over the candidates.
- pi_ref is the frozen reference (params-49333) on the policy rows: acting rows without a target, the pair head's
  full legal distribution, or the team head's on preview rows.
- The value term is ppo._loss's squared error over the value rows (returns.gae targets).
- Each mean divides by its own weight (the batch's weight, 0 on padding). No PPO surrogate, no magnet.

The constants are the spec's and are not options.
"""
import jax
import jax.numpy as jnp

LR = 3e-5
CLIP = 0.5
TARGET_ROWS = 512
NON_TARGET_ROWS = 3584
REF_COEF = 0.1
VALUE_COEF = 0.5
MAX_EPOCHS = 4
MAX_STEPS = 128
MIN_GAIN = 1e-4
PATIENCE = 2
REF_KL_MAX = 0.02


def _kl_full(p_log, q_log, legal):
    """KL(p || q) over the legal entries of each row; zero-mass entries add nothing (no 0 * -inf)."""
    p = jnp.where(legal, jnp.exp(p_log), 0.0)
    return jnp.sum(jnp.where(p > 0, p * (p_log - q_log), 0.0), axis=-1)


def distill_loss(params, ref_params, batch, model):
    """(loss, aux) of a batch of DistillData rows with "weight"; aux holds teacher_kl, ref_kl, value_loss and the
    weights n_target, n_policy, n_value."""
    b = batch["obs"].shape[0]
    logp_pairs, logp_team, value = model.apply(params, batch["obs"], batch["slots"], batch["mask"])
    ref_pairs, ref_team, _ = model.apply(jax.lax.stop_gradient(ref_params), batch["obs"], batch["slots"],
                                         batch["mask"])
    ref_pairs, ref_team = jax.lax.stop_gradient(ref_pairs), jax.lax.stop_gradient(ref_team)
    w = batch["weight"]
    w_target = w * batch["has_target"]
    w_policy = w * batch["policy_row"]
    w_value = w * batch["value_row"]

    # KL(tau || pi) on the teacher's support: sum_k p_k (log p_k - log pi(id_k)).
    probs = batch["target_probs"]
    ids = jnp.clip(batch["target_ids"], 0, logp_pairs.shape[1] - 1)
    student = jnp.take_along_axis(logp_pairs, ids, axis=1)
    keep = probs > 0
    teacher_kl = jnp.sum(jnp.where(keep, probs * (jnp.log(jnp.where(keep, probs, 1.0)) - student), 0.0), axis=-1)

    # KL(pi_ref || pi) over every legal action of the row's own head.
    pair_legal = jnp.reshape(batch["mask"], (b, -1))
    ref_kl = jnp.where(batch["is_team"], _kl_full(ref_team, logp_team, batch["team_mask"]),
                       _kl_full(ref_pairs, logp_pairs, pair_legal))

    value_loss = (value - batch["value_target"]) ** 2

    def mean(x, weight):
        return jnp.sum(jnp.where(weight > 0, x, 0.0) * weight) / jnp.maximum(jnp.sum(weight), 1.0)

    t, r, v = mean(teacher_kl, w_target), mean(ref_kl, w_policy), mean(value_loss, w_value)
    loss = t + REF_COEF * r + VALUE_COEF * v
    return loss, {"teacher_kl": t, "ref_kl": r, "value_loss": v, "n_target": jnp.sum(w_target),
                  "n_policy": jnp.sum(w_policy), "n_value": jnp.sum(w_value)}
