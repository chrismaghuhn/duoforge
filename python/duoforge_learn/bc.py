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

# The run state a --resume continues from (_save_state: before the first epoch, after every epoch, and once more
# marked finished when bc.npz and bc-run.json are written): the parameters, the best epoch's parameters, the
# optimizer state's leaves and a JSON "meta" entry, in one file that a fully written temporary file replaces, so the
# state on disk is always one whole epoch's.
STATE = "bc-state.npz"
STATE_VERSION = 1
# Options a resume may give otherwise: where the run reads and writes, never what it measures. The datasets' content
# is compared instead of their paths (_dataset_key), and whether the rows sit in a memmap cache (bc_data.batches takes
# a memmap batch in another row order) is part of the run's measure (train, _check_measure).
_RESUME_FREE = ("data", "out", "cache", "resume")


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
    p.add_argument("--pick-hypotheses-weight", type=float, default=None, metavar="W",
                   help="take the rows of pick hypotheses at W/H each (left out unless given; M11 pick hypotheses "
                        "spec, section 5)")
    p.add_argument("--split", choices=("sheet", "players", "test-players"), default="sheet",
                   help="the validation split: sheet (the sheet pair; belief datasets by players), players (a test "
                        "player's games held out for every source) or test-players (only the test players' own rows, "
                        "a bot the players split never trained on)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--cache", default=None, help="a directory (outside the repository) for the encoded rows")
    p.add_argument("--resume", action="store_true",
                   help=f"continue the run in --out from its state ({STATE}, written after every epoch): the same "
                        "options, datasets and machine; the run ends as it would have ended uninterrupted")
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
    """bc_data.Rows of the datasets, through the cache when one is given: a directory of memmaps (bc_data.load's
    memmap), so the rows never have to fit in memory; training reads them batch by batch."""
    import hashlib
    import json
    import shutil
    from pathlib import Path
    from . import bc_data
    hyp = args.pick_hypotheses_weight
    split = getattr(args, "split", "sheet")
    if args.cache is None:
        return bc_data.load(dirs, context, mask, format_weights, args.weights, source_weights, hyp, split)
    from duoforge import features
    for d in dirs:  # a cache hit must not skip the library check of the datasets
        bc_data._check_dataset(d, context)
    key = hashlib.sha256(json.dumps(["rows-v3", _dataset_key(dirs), mask, args.weights, format_weights,
                                     source_weights or {}, hyp, split,
                                     context.fingerprint().hex(), features.ENCODER, list(features.FEATURE_NAMES)],
                                    sort_keys=True).encode()).hexdigest()[:24]
    path = Path(args.cache) / f"bc-rows-{key}"
    if (path / "rows.json").exists():
        return bc_data.load_memmap(path, key)
    import os
    import uuid
    from duoforge_replay import dataset
    for stale in path.parent.glob(f"{path.name}.tmp-*"):  # a run that died while writing (POSIX: its pid is gone)
        if os.name == "posix" and not _alive(int(stale.name.split("-")[-2])):
            shutil.rmtree(stale, ignore_errors=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")  # one run's own directory
    rows = bc_data.load(dirs, context, mask, format_weights, args.weights, source_weights, hyp, split, memmap=tmp,
                        key=key)
    del rows  # close the writable memmaps before the directory is renamed
    try:
        tmp.rename(path)
    except OSError:
        if not (path / "rows.json").exists():
            raise
        shutil.rmtree(tmp)  # a parallel run of the same key finished first: its rows are the same
    dataset.fsync_dir(path.parent)
    return bc_data.load_memmap(path, key)


def _alive(pid):
    """Whether a POSIX process `pid` runs (signal 0 checks, sends nothing)."""
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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


def _plain(value):
    """value as JSON reads it back (tuples become lists): what a state compares and stores."""
    import json
    return json.loads(json.dumps(value))


def _run_args(args):
    """The options bc-run.json records: every option but --resume (a resumed run records its first launch's)."""
    return _plain({k: v for k, v in vars(args).items() if k != "resume"})


def _environment():
    """What a bit-identical continuation needs unchanged besides the options and the rows: the versions of JAX, jaxlib,
    NumPy and optax, and the devices JAX computes on."""
    from importlib import metadata
    device = jax.devices()[0]
    return {**{name: metadata.version(name) for name in ("jax", "jaxlib", "numpy", "optax")},
            "platform": device.platform, "device_kind": device.device_kind, "devices": jax.device_count()}


def _save_state(out, state):
    """Writes a run state (dict: params, best_params, opt_leaves and the JSON meta) to out/STATE: a temporary file,
    flushed to the disk, replaces it, so an interrupted write leaves the previous complete state."""
    import json
    import os
    from duoforge_replay import dataset
    from . import checkpoint
    arrays = {f"params{k}": v for k, v in checkpoint.flatten(state["params"]).items()}
    if state["best_params"] is not None:
        arrays |= {f"best_params{k}": v for k, v in checkpoint.flatten(state["best_params"]).items()}
    arrays |= {f"opt[{i}]": np.asarray(v) for i, v in enumerate(state["opt_leaves"])}
    arrays["meta"] = np.array(json.dumps(state["meta"]))
    tmp = out / "bc-state.tmp.npz"
    with open(tmp, "wb") as f:
        np.savez(f, **arrays)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out / STATE)
    dataset.fsync_dir(out)


def _load_state(path):
    """(meta, params, best_params, opt_leaves) of a state _save_state wrote."""
    import json
    from . import checkpoint
    with np.load(path) as npz:
        meta = json.loads(str(npz["meta"]))
        params = checkpoint.unflatten({k[len("params"):]: npz[k] for k in npz.files if k.startswith("params[")},
                                      path)
        best = {k[len("best_params"):]: npz[k] for k in npz.files if k.startswith("best_params[")}
        best_params = checkpoint.unflatten(best, path) if best else None
        n = sum(1 for k in npz.files if k.startswith("opt["))
        opt_leaves = [npz[f"opt[{i}]"] for i in range(n)]
    return meta, params, best_params, opt_leaves


def _resume_state(out, args):
    """The state of the run in `out` for a --resume of it with `args`: SystemExit when there is none, when the run
    finished, or when an option that changes the measurement differs from the run's (any option outside
    _RESUME_FREE). The datasets, the library and the machine are checked once the rows are read (_check_measure)."""
    path = out / STATE
    if not path.is_file():
        raise SystemExit(f"--resume: {out} holds no BC run state ({STATE}): there is no run to continue")
    meta, params, best_params, opt_leaves = _load_state(path)
    if meta.get("version") != STATE_VERSION:
        raise SystemExit(f"--resume: {path} is a state of version {meta.get('version')!r}; this trainer continues "
                         f"version {STATE_VERSION} only")
    if meta["finished"]:
        raise SystemExit(f"--resume: the run in {out} finished after epoch {meta['epoch']} (bc.npz and bc-run.json "
                         "are written): there is nothing to continue")
    old, new = meta["measure"]["args"], _plain(_measured_args(args))
    for name in sorted(set(old) | set(new)):
        if name not in old or name not in new or old[name] != new[name]:
            raise SystemExit(f"--resume: the run in {out} was started with {name} {old.get(name, '(none)')!r}, this "
                             f"call gives {new.get(name, '(none)')!r}: a resume cannot change what the run measures")
    return meta, params, best_params, opt_leaves


def _measured_args(args):
    return {k: v for k, v in vars(args).items() if k not in _RESUME_FREE}


def _check_measure(out, saved, measure):
    """SystemExit naming the first entry of the run's measure (the datasets' content, the library, the rows, the model,
    the machine) that a --resume finds otherwise."""
    for key in sorted(set(saved) | set(measure)):
        old, new = saved.get(key), measure.get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            for sub in sorted(set(old) | set(new)):
                if old.get(sub) != new.get(sub):
                    raise SystemExit(f"--resume: the run in {out} trained with {key} {sub} {old.get(sub)!r}, this "
                                     f"call has {new.get(sub)!r}: the continuation would not be the same run")
        elif old != new:
            raise SystemExit(f"--resume: the run in {out} trained with {key} {old!r}, this call has {new!r}: the "
                             "continuation would not be the same run")


def train(args):
    """Trains, writes bc.npz (the best validation epoch), bc-log.jsonl and bc-run.json; returns the best metrics.

    After every epoch the run state (STATE) is written; --resume continues a cut run from it, and the run ends as an
    uninterrupted one would: the same epochs, bc.npz bit for bit, the same log records and bc-run.json (apart from
    the seconds and the launches)."""
    import json
    import sys
    import time
    from pathlib import Path
    import duoforge
    import optax
    from duoforge import _layout, features
    from duoforge_replay import dataset
    from . import bc_data, checkpoint, policy, ppo, runstate
    out = Path(args.out)
    dataset.refuse_repository(out)
    if args.cache is not None:
        dataset.refuse_repository(args.cache)
    resume = getattr(args, "resume", False)
    saved = _resume_state(out, args) if resume else None
    if not resume and (out / STATE).exists():
        raise SystemExit(f"{out} holds the state of a BC run ({STATE}): continue it with --resume, or give a fresh "
                         "--out")
    if not resume and out.exists() and any(out.iterdir()):
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
                         "validation set (bucket 0 of 20 of the --split's sheet pairs or players) needs games on both "
                         "sides")
    dims = {k: getattr(args, k) for k in ("embed", "member", "position", "hidden", "layers", "option")
            if getattr(args, k) is not None}
    model_cfg = policy.v2_config(args.preset, **dims)
    datasets = _dataset_key(dirs)
    measure = _plain({"args": _measured_args(args), "datasets": datasets, "fingerprint": fingerprint,
                      "encoder": features.ENCODER, "features": list(features.FEATURE_NAMES), "ext_supported": mask,
                      "model": model_cfg, "rows": len(rows), "train_rows": len(train_index),
                      "val_rows": len(val_index), "memmap": isinstance(rows.obs, np.memmap),
                      "environment": _environment()})
    net = policy.make(model_cfg)
    tx = ppo.optimizer(args.learning_rate)
    if saved is None:
        params = net.init(jax.random.PRNGKey(args.seed))
        opt_state = tx.init(params)
        best_params = None
        meta = {"version": STATE_VERSION, "epoch": 0, "records": [], "best": None, "best_epoch": 0, "waited": 0,
                "stopped": False, "finished": False, "args": _run_args(args), "measure": measure, "launches": []}
    else:
        meta, params, best_params, opt_leaves = saved
        _check_measure(out, meta["measure"], measure)
        try:
            opt_state = runstate.restore_opt(tx, params, opt_leaves)
        except ValueError as err:
            raise SystemExit(f"--resume: {out / STATE}: {err}") from None
        print(json.dumps({"resume": str(out), "after_epoch": meta["epoch"]}), file=sys.stderr, flush=True)
    meta["launches"].append({"after_epoch": meta["epoch"], "out": str(out), "data": list(args.data),
                             "cache": args.cache})
    value_coef = args.value_coef

    @jax.jit
    def step(params, opt_state, obs, slots, mask, batch):
        (_, m), grads = jax.value_and_grad(
            lambda p: loss(p, net, obs, slots, mask, batch, value_coef), has_aux=True)(params)
        updates, opt_state = tx.update(grads, opt_state, params)
        return optax.apply_updates(params, updates), opt_state, m

    out.mkdir(parents=True, exist_ok=True)
    best, best_epoch, waited = meta["best"], meta["best_epoch"], meta["waited"]

    def state():
        return {"meta": meta, "params": jax.device_get(params), "best_params": best_params,
                "opt_leaves": jax.device_get(jax.tree_util.tree_leaves(opt_state))}

    if saved is None:
        _save_state(out, state())  # epoch 0: a run cut inside its first epoch can be resumed too
    with open(out / "bc-log.jsonl", "w", encoding="utf-8") as log:
        # A resumed run's log starts with the records of its state (a line a cut launch wrote after its last state is
        # dropped: that epoch runs again); a new run's state has none.
        for record in meta["records"]:
            log.write(json.dumps(record) + chr(10))
        log.flush()
        last = meta["epoch"] if meta["stopped"] else args.epochs  # a state of the stopping epoch trains no more
        for epoch in range(meta["epoch"] + 1, last + 1):
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
            stop = False
            if best is None or record["val_nll"] < best["val_nll"]:
                best, best_params, best_epoch, waited = record, jax.device_get(params), epoch, 0
            else:
                waited += 1
                stop = waited >= args.patience
            meta["records"].append(record)
            meta.update(epoch=epoch, best=best, best_epoch=best_epoch, waited=waited, stopped=stop)
            _save_state(out, state())
            if stop:
                break
    config = {"model": model_cfg, "encoder": features.ENCODER, "ext_supported": mask,
              "features": list(features.FEATURE_NAMES), "slot_features": list(features.SLOT_FEATURE_NAMES),
              "data": {"kind": "pool", "fingerprint": fingerprint}, "teams": [], "update": 0,
              "decisions": int(len(train_index)), "ids": ids,
              "train": {"seed": args.seed, "bc": {
                  "datasets": datasets, "format_weights": format_weights, "source_weights": source_weights,
                  "pick_hypotheses_weight": args.pick_hypotheses_weight,
                  "split": {"players": "players bucket 0/20 (the acting player's rows)",
                            "test-players": "only test players' own rows; val: their bucket 0/20 of h // 20"}.get(
                                getattr(args, "split", "sheet"), "sheet-pair bucket 0/20"),
                  "weights": args.weights, "epochs": args.epochs,
                  "best_epoch": best_epoch, "value_coef": value_coef, "learning_rate": args.learning_rate,
                  "batch": args.batch, "patience": args.patience}}}
    checkpoint.save(str(out / "bc.npz"), best_params, config)
    run = {"args": meta["args"], "rows": len(rows), "train_rows": len(train_index), "val_rows": len(val_index),
           "best": best, "launches": meta["launches"]}
    (out / "bc-run.json").write_text(json.dumps(run, indent=1) + chr(10), encoding="utf-8")
    meta["finished"] = True  # last: a run cut before this point writes bc.npz and bc-run.json again on --resume
    _save_state(out, state())
    return best


def main(argv=None):
    train(_parser().parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
