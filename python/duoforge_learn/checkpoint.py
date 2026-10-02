"""Checkpoints of the learner (decision 0014): the parameters train.save
writes, read back without JAX."""
import json
import os
import re
import sys

import numpy as np

from duoforge import features

_KEY = re.compile(r"\['([^']+)'\]")


def encoder_of(config):
    """The encoder version a checkpoint's network was trained with: its
    config's "encoder" (train writes features.ENCODER), 1 for a config
    without it (written before; present was species_id != 0). ValueError
    for a version features.as_encoder does not serve."""
    encoder = config.get("encoder", 1)
    if not features.is_version(encoder):
        raise ValueError(f"encoder {encoder!r} is not one this encoder knows: {features.ENCODERS}")
    return encoder


def load(path, obs_size=None):
    """(params, config) of a checkpoint; params are nested dicts of NumPy
    arrays, as model.init builds them. With obs_size, a network whose torso
    takes another number of observation features (a checkpoint of another
    encoder layout, such as the 594 features of 2026-10-02) raises
    ValueError. The width is all load checks; the encoder version the
    network was trained with is encoder_of(config)."""
    params = {}
    with np.load(path) as npz:
        config = json.loads(str(npz["config"]))
        for name in npz.files:
            if name == "config":
                continue
            keys = _KEY.findall(name)
            if not keys or "".join(f"['{k}']" for k in keys) != name:
                raise ValueError(f"{path}: unknown checkpoint entry {name!r}")
            node = params
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = npz[name]
    if obs_size is not None and params["t1"]["w"].shape[0] != obs_size:
        raise ValueError(f"{path}: the network takes {params['t1']['w'].shape[0]} observation features, "
                         f"the encoder makes {obs_size} (a checkpoint of another encoder layout)")
    return params, config


# The 13 inputs the encoder added in #84 (Psychic Terrain, the three position flags of each of the four
# positions), as indices of its 607 features; a 594-feature network gets zero rows there (decision 0016).
WIDEN_594_COLUMNS = (12, 37, 38, 39, 61, 62, 63, 333, 334, 335, 357, 358, 359)


def widen_594(params):
    """A copy of a 594-feature network whose torso takes the 607 features of this encoder: zero rows at
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
