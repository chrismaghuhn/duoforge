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

from duoforge import features

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
    if mask and encoder_of(config) != features.ENCODER:
        raise ValueError(f"a checkpoint of encoder {encoder_of(config)} has no ext_supported ({mask:#x})")
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


FORMAT2_KEYS = ("model", "encoder", "features", "slot_features", "data", "teams", "update", "decisions")
EMBEDDINGS = ("species", "move", "item", "ability", "nature")


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
    encoder 2 widened so is one of features.ENCODER (its new rows are zero,
    and with no "ext_supported" the encoder zeros the block too); a format-1
    file must have the width of its own encoder version (widen_594 converts
    the 594-feature ones) and keeps it."""
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
        if encoder not in (2, features.ENCODER):
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


def zero_columns(tree, config, names):
    """A copy of tree in which every input row that reads one of the feature columns `names` is 0 (M11 BC spec
    section 8): a network that never saw those columns set starts identical when they come on, and learns them from
    zero. The rows are found as widen finds them (_rows, by label): a column shared by every member or position
    (model v2) zeroes the shared row. ValueError for a name that is not a feature column of config."""
    names = list(names)
    unknown = [n for n in names if n not in config["features"]]
    if unknown:
        raise ValueError(f"{unknown[0]!r} is not a feature column of the checkpoint")
    cfg = config["model"]
    marked = set(names)
    plain = _rows(cfg, config["features"], config["slot_features"])
    moved = _rows(cfg, [n + "#zero" if n in marked else n for n in config["features"]], config["slot_features"])
    out = _copy(tree)
    for path, labels in plain.items():
        rows = [i for i, (a, b) in enumerate(zip(labels, moved[path])) if a != b]
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
