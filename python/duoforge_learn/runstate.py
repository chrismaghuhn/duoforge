"""The run state of a training run (decision 0017, spec 12.3): everything a
resume needs, written atomically.

state.npz holds the parameters, the optimizer state's leaves, the
environments' episode numbers and the JAX key as arrays, and the rest
(counters, league, NumPy generator, teams, data kind, model, encoder
layout, training options) as JSON. save_state writes a temporary file,
fsyncs it, copies the current state.npz to state.prev.npz and then replaces
state.npz, so a state.npz exists at every moment: an interrupted write
leaves the last complete state.
"""
import json
import os
import shutil
import signal

import numpy as np

from . import checkpoint

STATE, PREVIOUS = "state.npz", "state.prev.npz"
_ARRAYS = ("episodes_seen", "jax_key")


def _write(path, arrays):
    with open(path, "wb") as f:
        np.savez(f, **arrays)
        f.flush()
        os.fsync(f.fileno())


def save_state(run_dir, state):
    """Writes state (dict: params, opt_leaves, episodes_seen, jax_key and
    JSON values) atomically to run_dir/state.npz."""
    arrays = {f"params{k}": v for k, v in checkpoint.flatten(state["params"]).items()}
    arrays |= {f"opt[{i}]": np.asarray(v) for i, v in enumerate(state["opt_leaves"])}
    arrays |= {k: np.asarray(state[k]) for k in _ARRAYS}
    meta = {k: v for k, v in state.items() if k not in ("params", "opt_leaves") + _ARRAYS}
    arrays["meta"] = np.array(json.dumps(meta))
    tmp = os.path.join(run_dir, "state.tmp.npz")
    _write(tmp, arrays)
    current = os.path.join(run_dir, STATE)
    if os.path.exists(current):
        shutil.copyfile(current, os.path.join(run_dir, "state.prev.tmp.npz"))
        os.replace(os.path.join(run_dir, "state.prev.tmp.npz"), os.path.join(run_dir, PREVIOUS))
    os.replace(tmp, current)


def load_state(run_dir, previous=False):
    """The state save_state wrote (previous: the one before it)."""
    path = os.path.join(run_dir, PREVIOUS if previous else STATE)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no run state {path}: {run_dir} is not a resumable run")
    with np.load(path) as npz:
        state = json.loads(str(npz["meta"]))
        state["params"] = checkpoint.unflatten({k[len("params"):]: npz[k] for k in npz.files
                                                if k.startswith("params[")}, path)
        n = sum(1 for k in npz.files if k.startswith("opt["))
        state["opt_leaves"] = [npz[f"opt[{i}]"] for i in range(n)]
        for k in _ARRAYS:
            state[k] = npz[k]
    return state


def restore_opt(tx, params, leaves):
    """The optimizer state of tx for params from saved leaves; ValueError
    when they do not fit (another optimizer or model)."""
    import jax
    template = tx.init(params)
    want = jax.tree_util.tree_leaves(template)
    if len(want) != len(leaves) or any(np.shape(a) != np.shape(b) for a, b in zip(want, leaves)):
        raise ValueError("the saved optimizer state does not fit this model and optimizer")
    return jax.tree_util.tree_unflatten(jax.tree_util.tree_structure(template), [np.asarray(x) for x in leaves])


class StopFlag:
    """Set by SIGTERM (and SIGINT): the run saves its state at the next
    update boundary and ends."""

    def __init__(self):
        self.requested = False

    def install(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._set)
        return self

    def _set(self, signum, frame):
        self.requested = True
