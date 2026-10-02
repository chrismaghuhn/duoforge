"""Checkpoints of the learner (decision 0014): the parameters train.save
writes, read back without JAX."""
import json
import re

import numpy as np

_KEY = re.compile(r"\['([^']+)'\]")


def load(path):
    """(params, config) of a checkpoint; params are nested dicts of NumPy
    arrays, as model.init builds them."""
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
    return params, config
