"""Checkpoints of the learner (decisions 0014, 0017): the parameters and
their configuration, read back without JAX, and widened by name to a newer
encoder layout or larger embedding capacities.

Format 2 (decision 0017) stores in its config the model configuration, the
encoder version, the column names the network reads (features,
slot_features), the data kind, the team pool and the counters; format 1 (the
files of decision 0014) stores the training options only.
"""
import json
import os
import re
import sys

import numpy as np

from duoforge import data, features

from . import columns

_KEY = re.compile(r"\['([^']+)'\]|\[(\d+)\]")


def flatten(tree, prefix=""):
    """{"['a'][0]['w']": array, ...} of a tree of dicts, lists and arrays."""
    out = {}
    if isinstance(tree, dict):
        for k, v in tree.items():
            out |= flatten(v, prefix + f"['{k}']")
    elif isinstance(tree, (list, tuple)):
        for i, v in enumerate(tree):
            out |= flatten(v, prefix + f"[{i}]")
    else:
        out[prefix] = np.asarray(tree)
    return out


def unflatten(entries, where="checkpoint"):
    """The tree of flatten's entries; ValueError for a malformed name."""
    params = {}
    for name, value in entries.items():
        keys = [k if k else int(i) for k, i in _KEY.findall(name)]
        if not keys or "".join(f"['{k}']" if isinstance(k, str) else f"[{k}]" for k in keys) != name:
            raise ValueError(f"{where}: unknown checkpoint entry {name!r}")
        node = params
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
    return _lists(params)


def _lists(node):
    """Nested dicts whose keys are all ints become lists (model v2's torso)."""
    if not isinstance(node, dict):
        return node
    out = {k: _lists(v) for k, v in node.items()}
    if out and all(isinstance(k, int) for k in out):
        if sorted(out) != list(range(len(out))):
            raise ValueError(f"checkpoint list indices {sorted(out)} are not 0..{len(out) - 1}")
        return [out[k] for k in range(len(out))]
    return out


def encoder_of(config):
    """The encoder version a checkpoint's network was trained with: its
    config's "encoder" (train writes features.ENCODER), 1 for a config
    without it (written before; present was species_id != 0). ValueError
    for a version features.as_encoder does not serve."""
    encoder = config.get("encoder", 1)
    if not features.is_version(encoder):
        raise ValueError(f"encoder {encoder!r} is not one this encoder knows: {features.ENCODERS}")
    return encoder


def ext_supported_of(config):
    """The view-extension mask a checkpoint's network was trained with (its
    config's "ext_supported", 0 without it): which DUOFORGE_VIEWEXT_FEATURE_*
    columns of encoder 3's block it reads. ValueError for a value that is no
    such mask or a nonzero mask of an older encoder version."""
    mask = config.get("ext_supported", 0)
    if not isinstance(mask, int) or isinstance(mask, bool) or not 0 <= mask <= features.ALL_FEATURES:
        raise ValueError(f"ext_supported {mask!r} is not a mask of the {features.FEATURE_COUNT} feature bits")
    encoder = encoder_of(config)
    if mask & ~features.version_features(encoder):
        raise ValueError(f"a checkpoint of encoder {encoder} has no columns for ext_supported {mask:#x} "
                         f"(its features: {features.version_features(encoder):#x})")
    return mask


def load(path, obs_size=None):
    """(params, config) of a checkpoint; params are nested dicts of NumPy
    arrays, as model.init builds them. With obs_size, a network whose torso
    takes another number of observation features (a checkpoint of another
    encoder layout, such as the 594 features of 2026-10-02) raises
    ValueError. The width is all load checks; the encoder version the
    network was trained with is encoder_of(config)."""
    with np.load(path) as npz:
        config = json.loads(str(npz["config"]))
        params = unflatten({name: npz[name] for name in npz.files if name != "config"}, path)
    if obs_size is not None and params["t1"]["w"].shape[0] != obs_size:
        raise ValueError(f"{path}: the network takes {params['t1']['w'].shape[0]} observation features, "
                         f"the encoder makes {obs_size} (a checkpoint of another encoder layout)")
    return params, config


FORMAT2_KEYS = ("model", "encoder", "features", "slot_features", "data", "teams", "update", "decisions", "ids")
EMBEDDINGS = ("species", "move", "item", "ability", "nature")
_TABLES = {"species": data.TABLE_SPECIES, "move": data.TABLE_MOVE, "item": data.TABLE_ITEM,
           "ability": data.TABLE_ABILITY, "nature": data.TABLE_NATURE}
# Format-2 layouts load_current can map to this encoder by column name.
WIDENABLE_ENCODERS = (2, 3, features.ENCODER)


def ids_of(context):
    """{kind: [name of id 0, name of id 1, ...]} of every embedded table
    (EMBEDDINGS) under the context: what the ids a network embeds mean. A
    format-2 config keeps it as "ids" (spec 12.4)."""
    return {kind: [data.name(context, table, i) for i in range(data.count(context, table))]
            for kind, table in _TABLES.items()}


def check_ids(config, context):
    """Checks that every id a checkpoint's network embeds names the same row
    under the context as under the tables it was trained with (config["ids"],
    ids_of): the context's tables may only have grown at the end. ValueError
    naming the first id that moved or went away, or for a config without the
    tables (it cannot be checked across data versions)."""
    stored = config.get("ids")
    if not isinstance(stored, dict):
        raise ValueError("the checkpoint has no id tables, so it cannot be checked across data versions")
    now = ids_of(context)
    for kind in EMBEDDINGS:
        if kind not in stored:
            raise ValueError(f"the checkpoint's id tables lack {kind}")
        old, new = stored[kind], now[kind]
        if len(old) > len(new):
            raise ValueError(f"{kind} id {len(new)} ({old[len(new)]}) is gone: the table has {len(new)} ids now, "
                             f"{len(old)} when the network was trained")
        for i, (a, b) in enumerate(zip(old, new)):
            if a != b:
                raise ValueError(f"{kind} id {i}: {a} -> {b} (the tables changed below the network's ids)")


def save(path, params, config):
    """Writes params (nested dicts and lists of arrays) and a format-2 config;
    ValueError naming a missing key."""
    missing = [k for k in FORMAT2_KEYS if k not in config]
    if missing:
        raise ValueError(f"a format-2 checkpoint config needs {missing}")
    arrays = flatten(params)
    np.savez(path, config=json.dumps({**config, "format": 2}), **arrays)


def load_current(path):
    """(params, config) of a checkpoint widened to the current encoder layout
    (features.FEATURE_NAMES): format 2 by column name, and a network of
    encoder 2 or 3 widened so is one of features.ENCODER (its new rows are
    zero; its ext_supported, none for encoder 2, still lies inside the
    columns it had); a format-1 file must have the width of its own encoder
    version (widen_594 converts the 594-feature ones) and keeps it."""
    params, config = load(path)
    if config.get("format") != 2:
        width, want = params["t1"]["w"].shape[0], features.obs_size(encoder_of(config))
        if width != want:
            raise ValueError(f"{path}: the network takes {width} observation features, the encoder makes "
                             f"{want} (a checkpoint of another encoder layout)")
        return params, config
    if config["features"] != list(features.FEATURE_NAMES) or \
            config["slot_features"] != list(features.SLOT_FEATURE_NAMES):
        encoder = encoder_of(config)
        if encoder not in WIDENABLE_ENCODERS:
            raise ValueError(f"{path}: a format-2 checkpoint of encoder {encoder} cannot be widened")
        params, config = widen(params, config, features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)
        config["encoder"] = features.ENCODER
    return params, config


def model_config(config, params):
    """The model configuration of a checkpoint: format 2 stores it; a format-1
    file is model v1 with the sizes of its parameters."""
    if config.get("format") == 2:
        return dict(config["model"])
    return {"version": 1, "hidden": int(params["t1"]["w"].shape[1]),
            "option_hidden": int(params["option_torso"]["w"].shape[1])}


def _rows(cfg, feature_names, slot_names):
    if cfg["version"] == 1:
        return {("t1",): list(feature_names), ("option_features",): list(slot_names)}
    return columns.input_rows(cfg, columns.columns(feature_names, slot_names), feature_names, slot_names)


def _get(tree, path):
    for k in path:
        tree = tree[k]
    return tree


def _copy(tree):
    if isinstance(tree, dict):
        return {k: _copy(v) for k, v in tree.items()}
    if isinstance(tree, (list, tuple)):
        return [_copy(v) for v in tree]
    return np.asarray(tree)


def widen(tree, config, feature_names, slot_names, capacities=None, fill="init", seed=0):
    """(tree, config) widened from the layout of config ("model", "features",
    "slot_features") to feature_names and slot_names: every layer that reads
    encoder columns gets zero rows for the new ones, old rows move to their
    new places by name. capacities above the model's append embedding rows:
    fill "init" draws them as model_v2.init does (from seed), "zeros" gives
    zeros (Adam moments). A dropped column or a smaller capacity raises
    ValueError naming it."""
    cfg = dict(config["model"])
    old_rows = _rows(cfg, config["features"], config["slot_features"])
    new_rows = _rows(cfg, feature_names, slot_names)
    out = _copy(tree)
    for path, old in old_rows.items():
        new = new_rows[path]
        index = {label: i for i, label in enumerate(new)}
        dropped = [label for label in old if label not in index]
        if dropped:
            raise ValueError(f"the checkpoint reads column {dropped[0]!r}, which the encoder no longer makes")
        layer = _get(out, path)
        w = layer["w"]
        if w.shape[0] != len(old):
            raise ValueError(f"layer {path} has {w.shape[0]} rows, its layout names {len(old)}")
        wide = np.zeros((len(new),) + w.shape[1:], dtype=w.dtype)
        wide[[index[label] for label in old]] = w
        layer["w"] = wide
    new_config = {**config, "features": list(feature_names), "slot_features": list(slot_names)}
    if capacities is not None:
        if cfg["version"] != 2:
            raise ValueError("only model v2 has embedding capacities")
        rng = np.random.default_rng(seed)
        caps = dict(cfg["capacities"])
        for table in EMBEDDINGS:
            have, want = caps[table], int(capacities[table])
            if want < have:
                raise ValueError(f"{table} capacity {want} is below the checkpoint's {have}")
            if want > have:
                old = out[table]
                extra = (rng.standard_normal((want - have,) + old.shape[1:]).astype(old.dtype) * 0.1
                         if fill == "init" else np.zeros((want - have,) + old.shape[1:], dtype=old.dtype))
                out[table] = np.concatenate([old, extra])
            caps[table] = want
        cfg["capacities"] = caps
        new_config["model"] = cfg
    return out, new_config


def _sources(cfg, feature_names, slot_names):
    """The observation columns feeding each row of _rows (columns.input_sources; v1: one column per row of t1)."""
    if cfg["version"] == 1:
        return {("t1",): [{i} for i in range(len(feature_names))],
                ("option_features",): [set() for _ in slot_names]}
    return columns.input_sources(cfg, columns.columns(feature_names, slot_names), feature_names, slot_names)


def zero_columns(tree, config, names):
    """A copy of tree in which every input row fed by the feature columns `names` is 0 (M11 BC spec section 8): a
    network that never saw those columns set starts identical when they come on, and learns them from zero.
    Exact only when every column feeding a zeroed row is one of `names`: model v2 shares a row among every member's
    (or position's) column of a field, and zeroing it under a column that was on before would change the outputs in
    silence, so that is a ValueError naming such a column, as is a name that is not a feature column of config."""
    features_ = list(config["features"])
    index = {n: i for i, n in enumerate(features_)}
    unknown = [n for n in names if n not in index]
    if unknown:
        raise ValueError(f"{unknown[0]!r} is not a feature column of the checkpoint")
    marked = {index[n] for n in names}
    cfg = config["model"]
    labels = _rows(cfg, features_, config["slot_features"])
    sources = _sources(cfg, features_, config["slot_features"])
    out = _copy(tree)
    for path, fed in sources.items():
        rows = [r for r, cols in enumerate(fed) if cols & marked]
        for r in rows:
            outside = sorted(fed[r] - marked)
            if outside:
                raise ValueError(f"row {labels[path][r]!r} of layer {path} is also fed by {features_[outside[0]]!r}, "
                                 "which is not being switched on: zeroing it would change the outputs")
        if rows:
            layer = _get(out, path)
            w = np.array(layer["w"], copy=True)
            w[rows] = 0
            layer["w"] = w
    return out


# The 13 inputs the encoder added in #84 (Psychic Terrain, the three position flags of each of the four
# positions), as indices of its 607 features; a 594-feature network gets zero rows there (decision 0016).
WIDEN_594_COLUMNS = (12, 37, 38, 39, 61, 62, 63, 333, 334, 335, 357, 358, 359)


def widen_594(params):
    """A 594-feature network whose torso takes the 607 features of this encoder (a new t1.w and new dicts; the
    other arrays are shared with `params`): zero rows at
    WIDEN_594_COLUMNS, which are 0 under CLOSURE, so the outputs do not change there. ValueError for another
    width."""
    w = params["t1"]["w"]
    if w.shape[0] != 594:
        raise ValueError(f"widen_594 takes a 594-feature network, not {w.shape[0]}")
    wide = np.zeros((w.shape[0] + len(WIDEN_594_COLUMNS),) + w.shape[1:], dtype=w.dtype)
    keep = np.ones(wide.shape[0], dtype=bool)
    keep[list(WIDEN_594_COLUMNS)] = False
    wide[keep] = w
    out = {k: dict(v) for k, v in params.items()}
    out["t1"]["w"] = wide
    return out


def main(argv=None):
    """python -m duoforge_learn.checkpoint widen IN OUT: a 594-feature checkpoint of encoder 1 as one of 607."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3 or argv[0] != "widen":
        raise SystemExit("usage: python -m duoforge_learn.checkpoint widen IN OUT")
    _, src, dst = argv
    if os.path.exists(dst) or os.path.exists(dst + ".npz"):
        raise SystemExit(f"duoforge_learn.checkpoint: {dst} exists")
    params, config = load(src, obs_size=594)
    if encoder_of(config) != 1:
        raise SystemExit(f"duoforge_learn.checkpoint: {src} is not a checkpoint of encoder 1")
    config = dict(config, encoder=1)  # the network's own version, never features.ENCODER
    wide = widen_594(params)
    arrays = {f"['{a}']['{b}']": v for a, d in wide.items() for b, v in d.items()}
    np.savez(dst, config=json.dumps(config), **arrays)
    return 0


if __name__ == "__main__":
    sys.exit(main())
