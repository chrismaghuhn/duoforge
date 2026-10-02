"""Checkpoints of the learner (decision 0014): the parameters train.save
writes, read back without JAX."""
import json
import re

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
