"""Behavior cloning of Learner v2's model on the replay rows (M11 BC spec, approach A).

The loss of a row is -log P(label set): for a decision, the log of the summed probability of the pairs inside its
label set (bc_data.Rows.label_pairs, pair index i * 32 + j as the model's pair head); for a team selection, the same
over its tuples. The value head learns the outcome (+1 won, -1 lost) with weight value_coef. Rows are weighted
(bc_data.rating_weight, the format weights).
"""
import jax
import jax.numpy as jnp
import numpy as np

_NEG = -1e30  # outside a label set: finite, so a row of the other kind (all outside) gives no NaN gradient


def as_batch(rows):
    """The arrays of bc_data.Rows the loss reads, as JAX arrays."""
    n = len(rows)
    return {"label_pairs": jnp.asarray(rows.label_pairs.reshape(n, -1)), "label_team": jnp.asarray(rows.label_team),
            "is_team": jnp.asarray(rows.is_team), "weight": jnp.asarray(rows.weight, jnp.float32),
            "z": jnp.asarray(rows.z, jnp.float32), "has_z": jnp.asarray(rows.has_z)}


def loss_terms(logp_pairs, logp_team, value, batch, value_coef):
    """(total, {"nll", "value_mse"}) of model outputs (log_softmax pairs (B, 1024), log_softmax team (B, 360),
    value (B,)) against a batch (as_batch)."""
    pair_nll = -jax.nn.logsumexp(jnp.where(batch["label_pairs"], logp_pairs, _NEG), axis=1)
    team_nll = -jax.nn.logsumexp(jnp.where(batch["label_team"], logp_team, _NEG), axis=1)
    nll = jnp.where(batch["is_team"], team_nll, pair_nll)
    w = batch["weight"]
    policy = jnp.sum(w * nll) / jnp.sum(w)
    vw = w * batch["has_z"]
    value_mse = jnp.sum(vw * (value - batch["z"]) ** 2) / jnp.maximum(jnp.sum(vw), 1e-9)
    return policy + value_coef * value_mse, {"nll": policy, "value_mse": value_mse}


def loss(params, net, obs, slots, mask, batch, value_coef):
    """loss_terms of the network's outputs on encoded rows."""
    logp_pairs, logp_team, value = net.apply(params, obs, slots, mask)
    return loss_terms(logp_pairs, logp_team, value, batch, value_coef)


# ------------------------------------------------------------------ the trainer

def _parser():
    import argparse
    p = argparse.ArgumentParser(prog="python -m duoforge_learn.bc", description="Behavior cloning on replay rows.")
    p.add_argument("--data", required=True, nargs="+", help="replay datasets built in parts (duoforge_replay)")
    p.add_argument("--out", required=True, help="the output directory, outside the repository")
    p.add_argument("--preset", choices=("S", "M", "L"), default="M", help="model v2 size")
    for dim in ("embed", "member", "position", "hidden", "layers", "option"):
        p.add_argument(f"--{dim}", type=int, default=None, help="overrides the preset")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--patience", type=int, default=2, help="epochs without a better validation NLL before stopping")
    p.add_argument("--batch", type=int, default=1024)
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--value-coef", type=float, default=0.25)
    p.add_argument("--weights", choices=("rating", "uniform"), default="rating")
    p.add_argument("--format-weight", action="append", default=[], metavar="PREFIX=FACTOR",
                   help="a factor on the rows of a format prefix (repeatable)")
    p.add_argument("--source-weight", action="append", default=[], metavar="SOURCE=FACTOR",
                   help="a factor on the rows of a dataset source (sheet 1 unless named; bo1_belief must be named)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--cache", default=None, help="a directory (outside the repository) for the encoded rows")
    return p


def _format_weights(items):
    out = {}
    for item in items:
        prefix, _, factor = item.partition("=")
        if not prefix or not factor:
            raise SystemExit(f"--format-weight takes PREFIX=FACTOR, not {item!r}")
        if not float(factor) > 0:
            raise SystemExit(f"--format-weight {item!r}: the factor must be above 0 (a batch of weight 0 has no loss)")
        out[prefix] = float(factor)
    for a in out:
        for b in out:
            if a != b and b.startswith(a):
                raise SystemExit(f"--format-weight prefixes {a!r} and {b!r} overlap: a row would match both")
    return out


def _source_weights(items):
    from duoforge_replay import dataset
    out = {}
    for item in items:
        source, _, factor = item.partition("=")
        if source not in dataset.SOURCES or not factor:
            raise SystemExit(f"--source-weight takes SOURCE=FACTOR with a source of {dataset.SOURCES}, not {item!r}")
        if not float(factor) > 0:
            raise SystemExit(f"--source-weight {item!r}: the factor must be above 0")
        out[source] = float(factor)
    return out


def _dataset_key(dirs):
    """The sha256 of every finished part's manifest of the datasets: what the rows were read from."""
    import hashlib
    from pathlib import Path
    from duoforge_replay import dataset
    h = hashlib.sha256()
    for d in dirs:
        for part in dataset.parts(d):
            h.update((Path(part) / "manifest.json").read_bytes())
    return h.hexdigest()


def _rows(args, context, mask, dirs, format_weights, source_weights=None):
    """bc_data.Rows of the datasets, through the cache when one is given."""
    import hashlib
    import json
    from dataclasses import fields
    from pathlib import Path
    from . import bc_data
    if args.cache is None:
        return bc_data.load(dirs, context, mask, format_weights, args.weights, source_weights)
    from duoforge import features
    for d in dirs:  # a cache hit must not skip the library check of the datasets
        bc_data._check_dataset(d, context)
    key = hashlib.sha256(json.dumps(["rows-v2", _dataset_key(dirs), mask, args.weights, format_weights,
                                     source_weights or {},
                                     context.fingerprint().hex(), features.ENCODER, list(features.FEATURE_NAMES)],
                                    sort_keys=True).encode()).hexdigest()[:24]
    path = Path(args.cache) / f"bc-rows-{key}.npz"
    if path.exists():
        with np.load(path) as z:
            return bc_data.Rows(**{f.name: z[f.name] for f in fields(bc_data.Rows)})
    rows = bc_data.load(dirs, context, mask, format_weights, args.weights, source_weights)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez(tmp, **{f.name: getattr(rows, f.name) for f in fields(bc_data.Rows)})
    tmp.replace(path)
    return rows


def _device(rows):
    return jnp.asarray(rows.obs), jnp.asarray(rows.slots), jnp.asarray(rows.mask), as_batch(rows)


def _validate(params, net, rows, index, size, value_coef):
    """Weighted NLL and value MSE, and top-1 over the decisions whose slots are all EXACT, FORCED or not requested
    (at least one EXACT): the model's best pair inside the label set."""
    from duoforge_replay import labels
    nll = mse = wsum = vsum = 0.0
    hits = exact = 0
    for start in range(0, len(index), size):
        chunk = rows.take(index[start:start + size])
        obs, slots, mask, batch = _device(chunk)
        logp_pairs, logp_team, value = net.apply(params, obs, slots, mask)
        _, m = loss_terms(logp_pairs, logp_team, value, batch, value_coef)
        w = float(chunk.weight.sum())
        vw = float((chunk.weight * chunk.has_z).sum())
        nll, wsum = nll + float(m["nll"]) * w, wsum + w
        mse, vsum = mse + float(m["value_mse"]) * vw, vsum + vw
        ok = np.isin(chunk.reason, (labels.EXACT, labels.FORCED, labels.NOT_REQUESTED)).all(axis=1)
        ok &= (chunk.reason == labels.EXACT).any(axis=1) & ~chunk.is_team
        best = np.asarray(jnp.argmax(logp_pairs, axis=1))
        flat = chunk.label_pairs.reshape(len(chunk), -1)
        hits += int(flat[np.arange(len(chunk)), best][ok].sum())
        exact += int(ok.sum())
    return {"val_nll": nll / max(wsum, 1e-9), "val_value_mse": mse / max(vsum, 1e-9),
            "val_top1_exact": hits / exact if exact else None, "val_rows": len(index)}


def train(args):
    """Trains, writes bc.npz (the best validation epoch), bc-log.jsonl and bc-run.json; returns the best metrics."""
    import json
    import time
    from pathlib import Path
    import duoforge
    import optax
    from duoforge import _layout, features
    from duoforge_replay import dataset
    from . import bc_data, checkpoint, policy, ppo
    out = Path(args.out)
    dataset.refuse_repository(out)
    if args.cache is not None:
        dataset.refuse_repository(args.cache)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty: a BC run writes into a fresh directory")
    format_weights = _format_weights(args.format_weight)
    source_weights = _source_weights(args.source_weight)
    dirs = [Path(d) for d in args.data]
    context = duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"])
    try:
        mask = bc_data.bc_mask(context)
        rows = _rows(args, context, mask, dirs, format_weights, source_weights)
        bc_data.check_labels(rows)
        for prefix in format_weights:
            if not np.char.startswith(rows.fmt.astype(str), prefix).any():
                raise ValueError(f"--format-weight {prefix!r} matches no rows of the datasets")
        fingerprint, ids = context.fingerprint().hex(), checkpoint.ids_of(context)
    finally:
        context.close()
    train_index, val_index = np.flatnonzero(~rows.val), np.flatnonzero(rows.val)
    if len(val_index) == 0 or len(train_index) == 0:
        raise ValueError(f"the split leaves {len(train_index)} training and {len(val_index)} validation rows: the "
                         "validation set (bucket 0 of 20 of the sheet pairs) needs games on both sides")
    dims = {k: getattr(args, k) for k in ("embed", "member", "position", "hidden", "layers", "option")
            if getattr(args, k) is not None}
    model_cfg = policy.v2_config(args.preset, **dims)
    net = policy.make(model_cfg)
    params = net.init(jax.random.PRNGKey(args.seed))
    tx = ppo.optimizer(args.learning_rate)
    opt_state = tx.init(params)
    value_coef = args.value_coef

    @jax.jit
    def step(params, opt_state, obs, slots, mask, batch):
        (_, m), grads = jax.value_and_grad(
            lambda p: loss(p, net, obs, slots, mask, batch, value_coef), has_aux=True)(params)
        updates, opt_state = tx.update(grads, opt_state, params)
        return optax.apply_updates(params, updates), opt_state, m

    out.mkdir(parents=True, exist_ok=True)
    best, best_params, best_epoch, waited = None, None, 0, 0
    with open(out / "bc-log.jsonl", "w", encoding="utf-8") as log:
        for epoch in range(1, args.epochs + 1):
            start = time.monotonic()
            nll = wsum = 0.0
            for chunk in bc_data.batches(rows, train_index, args.batch, np.random.default_rng(args.seed + epoch)):
                params, opt_state, m = step(params, opt_state, *_device(chunk))
                w = float(chunk.weight.sum())
                nll, wsum = nll + float(m["nll"]) * w, wsum + w
            record = {"epoch": epoch, "train_nll": nll / wsum,
                      **_validate(params, net, rows, val_index, args.batch, value_coef),
                      "seconds": round(time.monotonic() - start, 2)}
            log.write(json.dumps(record) + chr(10))
            log.flush()
            print(json.dumps(record), flush=True)
            if best is None or record["val_nll"] < best["val_nll"]:
                best, best_params, best_epoch, waited = record, jax.device_get(params), epoch, 0
            else:
                waited += 1
                if waited >= args.patience:
                    break
    config = {"model": model_cfg, "encoder": features.ENCODER, "ext_supported": mask,
              "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
              "data": {"kind": "pool", "fingerprint": fingerprint}, "teams": [], "update": 0,
              "decisions": int(len(train_index)), "ids": ids,
              "train": {"seed": args.seed, "bc": {
                  "datasets": _dataset_key(dirs), "format_weights": format_weights, "source_weights": source_weights,
                  "split": "sheet-pair bucket 0/20", "weights": args.weights, "epochs": args.epochs,
                  "best_epoch": best_epoch, "value_coef": value_coef, "learning_rate": args.learning_rate,
                  "batch": args.batch, "patience": args.patience}}}
    checkpoint.save(str(out / "bc.npz"), best_params, config)
    run = {"args": vars(args), "rows": len(rows), "train_rows": len(train_index), "val_rows": len(val_index),
           "best": best}
    (out / "bc-run.json").write_text(json.dumps(run, indent=1) + chr(10), encoding="utf-8")
    return best


def main(argv=None):
    train(_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
