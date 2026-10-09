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
import hashlib
import json
import os
import shutil
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
OPTIMIZER = "adam"  # ppo.optimizer: Adam behind the gradient clip
PPO_POLICY = False  # no PPO surrogate in the distillation
MAGNET = False  # no KL anchor to a moving copy (the reference is the frozen start)
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


def guard(best, best_kl, stale, epoch, metrics):
    """One epoch's held-out metrics against the best so far: (best, best_kl, stale, reason). reason "nonfinite"
    (any metric) or "ref_kl" (held-out reference KL above REF_KL_MAX; that epoch is never best) stops; a held-out
    teacher KL MIN_GAIN below best_kl makes the epoch best, anything else counts as stale, and PATIENCE stale
    epochs stop with "no_gain"."""
    if not np.isfinite(list(metrics.values())).all():
        return best, best_kl, stale, "nonfinite"
    if metrics["held_ref_kl"] > REF_KL_MAX:
        return best, best_kl, stale, "ref_kl"
    if metrics["held_teacher_kl"] < best_kl - MIN_GAIN:
        return epoch, metrics["held_teacher_kl"], 0, None
    stale += 1
    return best, best_kl, stale, "no_gain" if stale >= PATIENCE else None


def drift(history):
    """(stop, best_epoch) after the epochs of history (history[0]: the start, epoch 0): the held-out guard's
    verdict (guard for every epoch, the shared code) and the stop at MAX_EPOCHS. fit additionally stops at
    MAX_STEPS and on a nonfinite training step, which a history of held-out metrics cannot show."""
    if not np.isfinite(list(history[0].values())).all():
        return True, 0
    best, best_kl, stale = 0, history[0]["held_teacher_kl"], 0
    for epoch, metrics in enumerate(history[1:], start=1):
        best, best_kl, stale, reason = guard(best, best_kl, stale, epoch, metrics)
        if reason is not None or epoch >= MAX_EPOCHS:
            return True, best
    return False, best


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
    def parts(p):
        _, aux = distill_loss(p, ref_params, batch, model)
        return jnp.stack([aux["teacher_kl"] + REF_COEF * aux["ref_kl"], aux["value_loss"]]), aux

    _, pullback, aux = jax.vjp(parts, params, has_aux=True)
    g_policy = pullback(jnp.array([1.0, 0.0]))[0]
    g_value = pullback(jnp.array([0.0, 1.0]))[0]
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
    params: object = None
    best_params: object = None


STATE, PREVIOUS = "distill-state.npz", "distill-state.prev.npz"
_CONSTANTS = ("LR", "CLIP", "TARGET_ROWS", "NON_TARGET_ROWS", "REF_COEF", "VALUE_COEF", "MAX_EPOCHS", "MAX_STEPS",
              "MIN_GAIN", "PATIENCE", "REF_KL_MAX", "EVAL_ROWS")


def _constants():
    return {name: globals()[name] for name in _CONSTANTS}


def _save_state(out, state, tx):
    """Writes the fit's state atomically (runstate's pattern: a temporary file, fsync, then a replace)."""
    arrays = {f"params{k}": v for k, v in _flatten(state["params"]).items()}
    arrays |= {f"best{k}": v for k, v in _flatten(state["best_params"]).items()}
    arrays |= {f"opt[{i}]": np.asarray(v) for i, v in enumerate(jax.tree_util.tree_leaves(state["opt_state"]))}
    meta = {k: v for k, v in state.items() if k not in ("params", "best_params", "opt_state")}
    arrays["meta"] = np.array(json.dumps(meta))
    from . import runstate
    tmp = out / "distill-state.tmp.npz"
    runstate._write(tmp, arrays)
    if (out / STATE).exists():
        shutil.copyfile(out / STATE, out / PREVIOUS)
    os.replace(tmp, out / STATE)


def _flatten(params):
    from . import checkpoint
    return checkpoint.flatten(jax.tree_util.tree_map(np.asarray, params))


def _load_state(out, tx, like):
    from . import checkpoint, runstate
    with np.load(out / STATE) as z:
        meta = json.loads(str(z["meta"]))
        params = checkpoint.unflatten({k[len("params"):]: z[k] for k in z.files if k.startswith("params")})
        best = checkpoint.unflatten({k[len("best"):]: z[k] for k in z.files if k.startswith("best")})
        leaves = [z[f"opt[{i}]"] for i in range(sum(k.startswith("opt[") for k in z.files))]
    params = jax.tree_util.tree_map(lambda a, b: np.asarray(a, dtype=np.asarray(b).dtype), params, like)
    return meta | {"params": params, "best_params": best, "opt_state": runstate.restore_opt(tx, params, leaves)}


def fit(data, model, init_params, ref_params, config, out, seed=0, ledger=None, identity=None, resume=False,
        stop=None):
    """Distills data into a student from init_params (fresh Adam at LR, clip CLIP) against the frozen ref_params.

    Epoch 0 evaluates the start; each later epoch visits every training target once, then evaluates the held-out
    rows. Stops at MAX_EPOCHS, MAX_STEPS (the step that reaches it ends its epoch), PATIENCE epochs without a
    MIN_GAIN gain of the held-out teacher KL, a held-out reference KL above REF_KL_MAX, or a nonfinite value. The
    best epoch is the lowest held-out teacher KL among finite epochs within REF_KL_MAX; params-best.npz holds it
    (the start itself, marked no_gain, when that is epoch 0). Writes log.jsonl, params-epoch-{e}.npz and
    params-best.npz into out, with config (the start's checkpoint config) and a "distill" record.

    The state (distill-state.npz) is saved at every epoch end and when stop (an object with .requested, checked
    after every step) asks to stop; resume=True continues from it exactly, and refuses other identity (the
    inputs' hashes), seed or constants. ValueError for a refused start or resume."""
    from . import ppo
    out = Path(out)
    tx = ppo.optimizer(LR, CLIP)
    plan = BatchPlan(seed)
    idx = distill_data.strata(data)
    for name in ("train_target", "train_non", "held_target", "held_non"):
        if not len(idx[name]):
            raise ValueError(f"no {name} rows: the fit and its guards need every stratum")
    if not data.policy_row[idx["held_non"]].any():
        raise ValueError("no policy rows in held_non: the held-out reference KL guard would be blind")
    held_rows = np.concatenate([idx["held_target"], idx["held_non"]])
    who = {"identity": identity or {}, "seed": int(seed), "constants": _constants()}
    if resume:
        if not (out / STATE).exists():
            raise ValueError(f"{out}: no state to resume ({STATE})")
        s = _load_state(out, tx, init_params)
        if s["reason"] is not None:
            raise ValueError(f"{out}: the fit already finished ({s['reason']}); nothing to resume")
        for name in ("identity", "seed", "constants"):
            if s[name] != who[name]:
                changed = sorted(k for k in set(s[name]) | set(who[name])) if isinstance(who[name], dict) else []
                changed = [k for k in changed if s[name].get(k) != who[name].get(k)] or [name]
                raise ValueError(f"resume refused: {name} differs ({', '.join(map(str, changed))})")
    else:
        if out.exists() and any(out.iterdir()):
            raise ValueError(f"{out} is not empty: a fit writes into a fresh directory")
        out.mkdir(parents=True, exist_ok=True)
        s = None
    phase = ledger.phase("distill") if ledger is not None else contextlib.nullcontext()

    def device():
        return ledger.device() if ledger is not None else contextlib.nullcontext()

    def held(p):
        """Teacher KL over the held-out targets, reference KL over the held-out policy rows, value loss over every
        held-out value row."""
        with device():
            return {"held_teacher_kl": evaluate_rows(data, idx["held_target"], model, p, ref_params)["held_teacher_kl"],
                    "held_ref_kl": evaluate_rows(data, idx["held_non"], model, p, ref_params)["held_ref_kl"],
                    "held_value_loss": evaluate_rows(data, held_rows, model, p, ref_params)["held_value_loss"]}

    with phase, open(out / "log.jsonl", "a", encoding="utf-8") as log:
        def write(record):
            log.write(json.dumps(record) + "\n")
            log.flush()

        if s is None:
            metrics = held(init_params)
            write(metrics | {"epoch": 0})
            s = who | {"params": init_params, "opt_state": tx.init(init_params), "best_params": init_params,
                       "epochs": [metrics | {"epoch": 0}], "best": 0, "best_kl": metrics["held_teacher_kl"],
                       "stale": 0, "steps": 0, "cursor": [0, 0], "epoch": 1, "row": 0, "seconds": 0.0,
                       "reason": None if np.isfinite(list(metrics.values())).all() else "nonfinite"}
        start = time.perf_counter() - s["seconds"]
        params, opt_state, reason = s["params"], s["opt_state"], s["reason"]

        def state(**kw):
            return s | {"params": params, "opt_state": opt_state, "seconds": time.perf_counter() - start} | kw

        signalled = False
        while reason is None and s["epoch"] <= MAX_EPOCHS:
            epoch = s["epoch"]
            targets = plan.targets(epoch, idx["train_target"])
            nonfinite = False
            for r in range(s["row"], len(targets)):
                if s["steps"] == MAX_STEPS:
                    break
                non, cursor = plan.non_targets(tuple(s["cursor"]), idx["train_non"], 1)
                batch = batch_of(data, np.concatenate([targets[r], non[0]]))
                with device():
                    params, opt_state, loss, aux, g_pol, g_val = jax.block_until_ready(
                        _step(params, opt_state, ref_params, batch, model, tx))
                s = s | {"steps": s["steps"] + 1, "cursor": list(cursor), "row": r + 1}
                record = {"step": s["steps"], "epoch": epoch, "loss": float(loss),
                          **{k: float(v) for k, v in aux.items()}, "grad_norm_policy": float(g_pol),
                          "grad_norm_value": float(g_val), "seconds": round(time.perf_counter() - start, 3)}
                write(record)
                if not np.isfinite([record["loss"], record["grad_norm_policy"], record["grad_norm_value"]]).all():
                    nonfinite = True
                    break
                if stop is not None and stop.requested:
                    _save_state(out, state(), tx)
                    signalled = True
                    break
            if signalled:
                break
            if nonfinite:
                reason = "nonfinite"
                break
            metrics = held(params)
            record = metrics | {"epoch": epoch}
            s = s | {"epochs": s["epochs"] + [record]}
            best, best_kl, stale, verdict = guard(s["best"], s["best_kl"], s["stale"], epoch, metrics)
            if verdict in ("nonfinite", "ref_kl"):
                write(record if verdict == "nonfinite" else record | {"best": False})
                reason = verdict
                break
            s = s | {"best": best, "best_kl": best_kl, "stale": stale}
            if best == epoch:
                s = s | {"best_params": params}
            write(record | {"best": s["best"] == epoch})
            _save(out / f"params-epoch-{epoch}.npz", params,
                  config | {"distill": {"epoch": epoch, "best_epoch": s["best"], "no_gain": s["best"] == 0}})
            if verdict == "no_gain":
                reason = "no_gain"
            elif s["steps"] == MAX_STEPS:
                reason = "max_steps"
            s = s | {"epoch": epoch + 1, "row": 0}
            _save_state(out, state(reason=reason), tx)
            if ledger is not None:
                ledger.save()
        if signalled:
            reason = "signal"
        else:
            reason = reason or "max_epochs"
        best = s["best"]
        if not signalled:
            _save(out / "params-best.npz", s["best_params"],
                  config | {"distill": {"epoch": best, "best_epoch": best, "no_gain": best == 0, "stop": reason}})
            write({"stop": reason, "best_epoch": best, "steps": s["steps"]})
            _save_state(out, state(reason=reason), tx)
    if ledger is not None:  # after the phase closed, so its seconds are in the phase
        ledger.save()
    return FitResult(best, reason, s["epochs"], s["steps"], params, s["best_params"])


PARAMS_49333_SHA256 = "ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _manifest(path):
    """The DataManifest of M12's manifest file (expert_data.read_manifest checks it) and the file's SHA-256."""
    from duoforge_search import expert_data as ed
    return ed.read_manifest(Path(path)), _sha256(path)


def main(argv=None):
    """python -m duoforge_learn.distill: exit 0 after a finished fit (whatever its stop reason), 2 for a refusal, 3
    when a signal stopped it (resume with --resume)."""
    import argparse
    import sys
    p = argparse.ArgumentParser(prog="python -m duoforge_learn.distill", description="Stage 3 P1 distillation.")
    p.add_argument("--init", required=True, help="the student's start (params-49333)")
    p.add_argument("--reference", required=True, help="the frozen reference of the KL term (params-49333)")
    p.add_argument("--shards", required=True, help="the directory of the teacher shards (*.json)")
    p.add_argument("--manifest", required=True, help="the shards' manifest file (expert_data.write_manifest)")
    p.add_argument("--out", required=True, help="the fit's directory, outside the repository")
    p.add_argument("--resume", action="store_true", help="continue the fit in --out")
    p.add_argument("--seed", type=lambda v: int(v, 0), default=0)
    p.add_argument("--ledger", default=None, help="the arm's compute ledger (ledger.py)")
    p.add_argument("--allow-other-init", action="store_true", help="tests only: another start or reference")
    args = p.parse_args(argv)
    try:
        from duoforge_replay.dataset import refuse_repository
        refuse_repository(args.out)
        if args.resume and not (Path(args.out) / STATE).exists():
            raise ValueError(f"{args.out}: no state to resume ({STATE})")
        from . import checkpoint, runstate
        shas = {"init": _sha256(args.init), "reference": _sha256(args.reference)}
        if not args.allow_other_init and set(shas.values()) != {PARAMS_49333_SHA256}:
            raise ValueError(f"the init and the reference must both be params-49333 ({PARAMS_49333_SHA256}): {shas}")
        manifest, manifest_sha = _manifest(args.manifest)
        # The networks in the layout they were trained with (P1: encoder 4), which the manifest's rows are in.
        init, config = checkpoint.load_trained(args.init)
        ref, ref_config = checkpoint.load_trained(args.reference)
        if checkpoint.encoder_of(config) != manifest.encoder or len(config["features"]) != manifest.obs_width:
            raise ValueError(f"--init is encoder {checkpoint.encoder_of(config)} ({len(config['features'])} "
                             f"features), the manifest's rows encoder {manifest.encoder} ({manifest.obs_width})")
        if (checkpoint.model_config(ref_config, ref), ref_config["features"]) !=                 (checkpoint.model_config(config, init), config["features"]):
            raise ValueError("the reference's model or layout differs from the init's")
        model = checkpoint.trained_model(config, init)
        data = distill_data.load(args.shards, manifest)
        identity = {"manifest": manifest_sha, **shas, "jax": jax.__version__, "optax": optax.__version__,
                    "device": jax.devices()[0].device_kind, "allow_other_init": args.allow_other_init}
        book = None
        if args.ledger:
            from . import ledger as ledger_mod
            book = ledger_mod.Ledger(args.ledger)
        stop = runstate.StopFlag().install()
        try:
            result = fit(data, model, jax.device_put(init), jax.device_put(ref), config, args.out, seed=args.seed,
                         ledger=book, identity=identity, resume=args.resume, stop=stop)
        finally:
            stop.restore()
    except (ValueError, OSError) as err:
        print(f"distill: {err}", file=sys.stderr)
        return 2
    print(json.dumps({"stop": result.stop_reason, "best_epoch": result.best_epoch, "steps": result.steps}))
    return 3 if result.stop_reason == "signal" else 0


if __name__ == "__main__":
    raise SystemExit(main())
