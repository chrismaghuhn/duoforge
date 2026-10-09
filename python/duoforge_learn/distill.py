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
import contextlib
import dataclasses
import functools
import json
import time
from pathlib import Path

import jax
import jax.numpy as jnp
import numpy as np
import optax

from . import distill_data

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
EVAL_ROWS = 4096


def _kl_full(p_log, q_log, legal):
    """KL(p || q) over the legal entries of each row; zero-mass entries add nothing (no 0 * -inf)."""
    p = jnp.where(legal, jnp.exp(p_log), 0.0)
    return jnp.sum(jnp.where(p > 0, p * (p_log - q_log), 0.0), axis=-1)


def _terms(params, ref_params, batch, model):
    """Per-row (teacher_kl, ref_kl, value_loss) and their weights (target, policy, value)."""
    b = batch["obs"].shape[0]
    logp_pairs, logp_team, value = model.apply(params, batch["obs"], batch["slots"], batch["mask"])
    ref_pairs, ref_team, _ = model.apply(jax.lax.stop_gradient(ref_params), batch["obs"], batch["slots"],
                                         batch["mask"])
    ref_pairs, ref_team = jax.lax.stop_gradient(ref_pairs), jax.lax.stop_gradient(ref_team)
    w = batch["weight"]
    weights = (w * batch["has_target"], w * batch["policy_row"], w * batch["value_row"])

    # KL(tau || pi) on the teacher's support: sum_k p_k (log p_k - log pi(id_k)); the target ids are legal, so the
    # gathered values are full_joint_log_probs' (the pair head's log-softmax over every legal action).
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
    return (teacher_kl, ref_kl, value_loss), weights


def _sums(terms, weights):
    """Weighted sums of each term (a padded or unweighted row adds exactly 0) and the summed weights."""
    return (tuple(jnp.sum(jnp.where(w > 0, x, 0.0) * w) for x, w in zip(terms, weights)),
            tuple(jnp.sum(w) for w in weights))


def distill_loss(params, ref_params, batch, model):
    """(loss, aux) of a batch of DistillData rows with "weight"; aux holds teacher_kl, ref_kl, value_loss and the
    weights n_target, n_policy, n_value."""
    sums, counts = _sums(*_terms(params, ref_params, batch, model))
    t, r, v = (s / jnp.maximum(c, 1.0) for s, c in zip(sums, counts))
    loss = t + REF_COEF * r + VALUE_COEF * v
    return loss, {"teacher_kl": t, "ref_kl": r, "value_loss": v, "n_target": counts[0], "n_policy": counts[1],
                  "n_value": counts[2]}


_FIELDS = ("obs", "slots", "mask", "team_mask", "is_team", "target_ids", "target_probs", "has_target", "policy_row",
           "value_row", "value_target")


def batch_of(data, rows):
    """The batch of DistillData rows (indices, -1 = padding with weight 0)."""
    rows = np.asarray(rows)
    take = np.clip(rows, 0, None)
    batch = {name: getattr(data, name)[take] for name in _FIELDS}
    batch["weight"] = (rows >= 0).astype(np.float32)
    return batch


class BatchPlan:
    """Keyed batches: every epoch a permutation of the training targets (TARGET_ROWS per step, the last step
    padded), and one stream of non-target rows (NON_TARGET_ROWS per step) that runs on across steps and epochs, a
    new permutation per lap. A cursor (lap, position) resumes the stream."""

    def __init__(self, seed):
        self.seed = int(seed)

    def targets(self, epoch, idx):
        order = np.random.default_rng([self.seed, 1, epoch]).permutation(np.asarray(idx))
        steps = -(-len(order) // TARGET_ROWS)
        out = np.full(steps * TARGET_ROWS, -1, np.int64)
        out[:len(order)] = order
        return out.reshape(steps, TARGET_ROWS)

    def non_targets(self, cursor, idx, steps):
        idx = np.asarray(idx)
        lap, pos = cursor
        need, parts = steps * NON_TARGET_ROWS, []
        while need:
            perm = np.random.default_rng([self.seed, 2, lap]).permutation(idx)
            take = perm[pos:pos + need]
            parts.append(take)
            need -= len(take)
            pos += len(take)
            if pos == len(idx):
                lap, pos = lap + 1, 0
        return np.concatenate(parts).reshape(steps, NON_TARGET_ROWS), (lap, pos)


@functools.partial(jax.jit, static_argnames=("model",))
def _eval_sums(params, ref_params, batch, model):
    return _sums(*_terms(params, ref_params, batch, model))


def evaluate_rows(data, rows, model, params, ref_params):
    """held_teacher_kl, held_ref_kl and held_value_loss over rows, in chunks of EVAL_ROWS (the last one padded):
    each the sum over all chunks divided by the summed weights."""
    rows = np.asarray(rows)
    total, weight = np.zeros(3), np.zeros(3)
    for start in range(0, len(rows), EVAL_ROWS):
        chunk = np.full(EVAL_ROWS, -1, np.int64)
        part = rows[start:start + EVAL_ROWS]
        chunk[:len(part)] = part
        sums, counts = _eval_sums(params, ref_params, batch_of(data, chunk), model)
        total += np.asarray(sums, np.float64)
        weight += np.asarray(counts, np.float64)
    means = total / np.maximum(weight, 1.0)
    return {"held_teacher_kl": float(means[0]), "held_ref_kl": float(means[1]), "held_value_loss": float(means[2])}


def _norm(tree):
    return jnp.sqrt(sum(jnp.sum(jnp.square(x)) for x in jax.tree_util.tree_leaves(tree)))


@functools.partial(jax.jit, static_argnames=("model", "tx"))
def _step(params, opt_state, ref_params, batch, model, tx):
    """One optimizer step; the gradient norms of the policy terms and of the value term are reported apart."""
    def policy_part(p):
        loss, aux = distill_loss(p, ref_params, batch, model)
        return aux["teacher_kl"] + REF_COEF * aux["ref_kl"], aux

    def value_part(p):
        return distill_loss(p, ref_params, batch, model)[1]["value_loss"]

    (_, aux), g_policy = jax.value_and_grad(policy_part, has_aux=True)(params)
    g_value = jax.grad(value_part)(params)
    grads = jax.tree_util.tree_map(lambda a, b: a + VALUE_COEF * b, g_policy, g_value)
    updates, opt_state = tx.update(grads, opt_state, params)
    loss = aux["teacher_kl"] + REF_COEF * aux["ref_kl"] + VALUE_COEF * aux["value_loss"]
    return (optax.apply_updates(params, updates), opt_state, loss, aux, _norm(g_policy), _norm(g_value))


def _save(path, params, config):
    from . import checkpoint
    checkpoint.save(path, jax.tree_util.tree_map(np.asarray, params), config)


@dataclasses.dataclass
class FitResult:
    best_epoch: int
    stop_reason: str
    epochs: list
    steps: int


def fit(data, model, init_params, ref_params, config, out, seed=0, ledger=None):
    """Distills data into a student from init_params (fresh Adam at LR, clip CLIP) against the frozen ref_params.
    Epoch 0 evaluates the start; each later epoch visits every training target once, then evaluates the held-out
    rows. Stops at MAX_EPOCHS, MAX_STEPS (the step that reaches it ends its epoch), PATIENCE epochs without a
    MIN_GAIN gain of the held-out teacher KL, a held-out reference KL above REF_KL_MAX, or a nonfinite value. The
    best epoch is the lowest held-out teacher KL among finite epochs within REF_KL_MAX; params-best.npz holds it
    (the start itself, marked no_gain, when that is epoch 0). Writes log.jsonl, params-epoch-{e}.npz and
    params-best.npz into out, with config (the start's checkpoint config) and a "distill" record."""
    from . import ppo
    out = Path(out)
    idx = distill_data.strata(data)
    tx = ppo.optimizer(LR, CLIP)
    plan = BatchPlan(seed)
    params, opt_state = init_params, tx.init(init_params)
    phase = ledger.phase("distill") if ledger is not None else contextlib.nullcontext()

    def device():
        return ledger.device() if ledger is not None else contextlib.nullcontext()

    def held(p):
        with device():
            m = evaluate_rows(data, idx["held_target"], model, p, ref_params) | \
                {"held_ref_kl": evaluate_rows(data, idx["held_non"], model, p, ref_params)["held_ref_kl"]}
        return m

    with phase, open(out / "log.jsonl", "a", encoding="utf-8") as log:
        def write(record):
            log.write(json.dumps(record) + "\n")
            log.flush()

        def keep(epoch, p, best):
            info = {"epoch": epoch, "best_epoch": best, "no_gain": best == 0}
            _save(out / f"params-epoch-{epoch}.npz", p, config | {"distill": info})

        metrics = held(params)
        epochs = [metrics | {"epoch": 0}]
        write(epochs[0])
        best, best_kl, best_params, stale = 0, metrics["held_teacher_kl"], params, 0
        steps, cursor, reason, start = 0, (0, 0), "max_epochs", time.perf_counter()
        for epoch in range(1, MAX_EPOCHS + 1):
            targets = plan.targets(epoch, idx["train_target"])
            nonfinite = False
            for row in targets:
                if steps == MAX_STEPS:
                    break
                non, cursor = plan.non_targets(cursor, idx["train_non"], 1)
                batch = batch_of(data, np.concatenate([row, non[0]]))
                with device():
                    params, opt_state, loss, aux, g_pol, g_val = jax.block_until_ready(
                        _step(params, opt_state, ref_params, batch, model, tx))
                steps += 1
                record = {"step": steps, "epoch": epoch, "loss": float(loss),
                          **{k: float(v) for k, v in aux.items()}, "grad_norm_policy": float(g_pol),
                          "grad_norm_value": float(g_val), "seconds": round(time.perf_counter() - start, 3)}
                write(record)
                if not np.isfinite([record["loss"], record["grad_norm_policy"], record["grad_norm_value"]]).all():
                    nonfinite = True
                    break
            if nonfinite:
                reason = "nonfinite"
                break
            metrics = held(params)
            record = metrics | {"epoch": epoch}
            epochs.append(record)
            if not np.isfinite(list(metrics.values())).all():
                write(record)
                reason = "nonfinite"
                break
            if metrics["held_ref_kl"] > REF_KL_MAX:
                write(record | {"best": False})
                reason = "ref_kl"
                break
            if metrics["held_teacher_kl"] < best_kl - MIN_GAIN:
                best, best_kl, best_params, stale = epoch, metrics["held_teacher_kl"], params, 0
            else:
                stale += 1
            write(record | {"best": best == epoch})
            keep(epoch, params, best)
            if stale >= PATIENCE:
                reason = "no_gain"
                break
            if steps == MAX_STEPS:
                reason = "max_steps"
                break
        _save(out / "params-best.npz", best_params,
              config | {"distill": {"epoch": best, "best_epoch": best, "no_gain": best == 0, "stop": reason}})
        write({"stop": reason, "best_epoch": best, "steps": steps})
    if ledger is not None:
        ledger.save()
    return FitResult(best, reason, epochs, steps)
