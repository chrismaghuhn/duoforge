"""Trajectory recipes (M7 spec section 6): seeds and choices, not features.

A recipe is two files, <name>.npz (the arrays) and <name>.json (the
manifest). It stores where each episode ran and its candidate indices in
decision order (steps in order, requested players in player order), about
100 bytes per battle. replay() rebuilds every episode with a batch, hands
each decision's inputs to on_decision, and checks steps, result and digest.
"""
import datetime
import hashlib
import json

import numpy as np

from . import _layout
from ._lib import version
from .batch import Batch
from .context import Context, reference_setups

FORMAT = "duoforge-recipe-1"

# The reference pairings a setup table can name (duoforge_reference_setup).
PAIRINGS = {"A-B": 0, "B-A": 1, "A-A": 2, "B-B": 3}

# Array name: (dtype, trailing shape); the leading dimension is N, M or N+1.
ARRAYS = {
    "env": (np.uint32, ()),
    "episode": (np.uint32, ()),
    "setup": (np.uint8, ()),
    "policy": (np.uint16, (2,)),
    "steps": (np.uint32, ()),
    "result": (np.uint8, ()),
    "truncated": (np.bool_, ()),
    "digest": (np.uint8, (_layout.DIGEST_SIZE,)),
    "choice_offset": (np.uint64, ()),
    "choice": (np.uint16, ()),
}


class ReplayMismatch(RuntimeError):
    """A replayed episode differs from its recipe (choice, steps, result or digest)."""


class RecipeVersionError(RuntimeError):
    """The recipe was written by another format, library, context or layout."""


def _describe(dtype):
    """A canonical description of a dtype's memory layout."""
    if dtype.names is not None:
        return {"itemsize": dtype.itemsize,
                "fields": [[n, dtype.fields[n][1], _describe(dtype.fields[n][0])] for n in dtype.names]}
    if dtype.subdtype is not None:
        base, shape = dtype.subdtype
        return {"shape": list(shape), "base": _describe(base)}
    return {"kind": dtype.kind, "itemsize": dtype.itemsize}


def observation_layout_sha256():
    """SHA-256 of the observation dtype's layout (names, offsets, itemsize)."""
    text = json.dumps(_describe(_layout.OBSERVATION), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _setup_table(names):
    table = []
    for name in names:
        if name not in PAIRINGS:
            raise ValueError(f"unknown setup {name!r}; known: {sorted(PAIRINGS)}")
        setup = reference_setups([PAIRINGS[name]])
        table.append({"name": name, "sha256": hashlib.sha256(setup.tobytes()).hexdigest()})
    return table


class RecipeWriter:
    """Collects episodes and writes <path>.npz and <path>.json on close().

    setups names reference pairings ("A-B", "B-A", "A-A", "B-B"); policies
    are dicts with at least a "name". context holds the config the episodes
    ran with (defaults: the certified profile).
    """

    def __init__(self, path, *, seed, max_steps, setups, policies, command, context=None):
        self.path = str(path)
        self.seed = int(seed)
        self.max_steps = int(max_steps)
        self.setups = _setup_table(setups)
        self.policies = [dict(p) for p in policies]
        if any("name" not in p for p in self.policies):
            raise ValueError("every policy needs a name")
        self.command = str(command)
        self.config = dict(context or {"data_kind": _layout.DATA_KIND_CLOSURE, "max_roster": 6, "brought_count": 4})
        with Context(**self.config) as ctx:
            self.fingerprint = ctx.fingerprint().hex()
        self._rows = []
        self._choices = []
        self._closed = False

    def add(self, env, episode, setup, policy, choices, steps, result, truncated, digest):
        """One episode: its candidate indices (uint16, decision order) and outcome."""
        choices = np.asarray(choices)
        if choices.dtype != np.uint16 or choices.ndim != 1:
            raise TypeError("choices must be a one-dimensional uint16 array")
        if not 0 <= int(setup) < len(self.setups):
            raise ValueError(f"setup {setup} is not in the setup table")
        if len(policy) != 2 or not all(0 <= int(p) < len(self.policies) for p in policy):
            raise ValueError(f"policy {policy} is not a pair of policy table indices")
        digest = bytes(digest)
        if len(digest) != _layout.DIGEST_SIZE:
            raise ValueError("a digest has 32 bytes")
        if bool(truncated) != (int(result) == 0):
            raise ValueError("an episode is truncated exactly when it has no result")
        self._rows.append((int(env), int(episode), int(setup), (int(policy[0]), int(policy[1])), int(steps),
                           int(result), bool(truncated), digest))
        self._choices.append(choices.copy())

    def close(self):
        if self._closed:
            return
        n = len(self._rows)
        arrays = {
            "env": np.array([r[0] for r in self._rows], dtype=np.uint32),
            "episode": np.array([r[1] for r in self._rows], dtype=np.uint32),
            "setup": np.array([r[2] for r in self._rows], dtype=np.uint8),
            "policy": np.array([r[3] for r in self._rows], dtype=np.uint16).reshape(n, 2),
            "steps": np.array([r[4] for r in self._rows], dtype=np.uint32),
            "result": np.array([r[5] for r in self._rows], dtype=np.uint8),
            "truncated": np.array([r[6] for r in self._rows], dtype=np.bool_),
            "digest": np.frombuffer(b"".join(r[7] for r in self._rows), dtype=np.uint8).reshape(n, _layout.DIGEST_SIZE),
            "choice_offset": np.concatenate([[0], np.cumsum([len(c) for c in self._choices])]).astype(np.uint64),
            "choice": (np.concatenate(self._choices) if self._choices else np.zeros(0)).astype(np.uint16),
        }
        np.savez(self.path + ".npz", **arrays)
        manifest = {
            "format": FORMAT,
            "library_version": version(),
            "context": self.config,
            "context_fingerprint": self.fingerprint,
            "observation": {"size": _layout.OBSERVATION.itemsize, "layout_sha256": observation_layout_sha256()},
            "seed": self.seed,
            "max_steps": self.max_steps,
            "setups": self.setups,
            "policies": self.policies,
            "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "command": self.command,
            "episodes": n,
            "decisions": int(arrays["choice"].shape[0]),
        }
        with open(self.path + ".json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
            f.write("\n")
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def record(batch, chooser, writer, *, episodes, setup, policy=(0, 0)):
    """Plays `episodes` rounds and adds every episode to the writer: in
    round k (1..episodes) each environment plays episode k from a fresh
    reset with chooser (start_episode, if it has one, then choose), until
    TERMINAL or writer.max_steps steps (truncated). setup holds each
    environment's index into the writer's setup table, policy the policy
    table index of each side."""
    setup = np.asarray(setup)
    if setup.shape != (batch.envs,):
        raise ValueError("one setup index per environment")
    for k in range(1, int(episodes) + 1):
        for e in range(batch.envs):
            if hasattr(chooser, "start_episode"):
                chooser.start_episode(e, k)
            batch.reset(e, k)
        choices = [[] for _ in range(batch.envs)]
        steps = np.zeros(batch.envs, dtype=np.int64)
        while True:
            batch.query()
            requested = batch.requests["requested"] != 0
            running = requested.any(axis=1) & (steps < writer.max_steps)
            if not running.any():
                break
            indices = chooser.choose(batch)
            indices[~running] = _layout.NO_CHOICE
            for e in np.flatnonzero(running):
                choices[e].extend(int(indices[e, p]) for p in range(2) if requested[e, p])
            batch.step(indices, active=running)
            steps[running] += 1
        terminal = ~requested.any(axis=1)
        for e in range(batch.envs):
            writer.add(e, k, int(setup[e]), policy, np.array(choices[e], dtype=np.uint16), int(steps[e]),
                       batch.result(e), not terminal[e], batch.digest(e))


class Recipe:
    """A loaded recipe: manifest (dict) and arrays (name -> ndarray)."""

    def __init__(self, manifest, arrays):
        self.manifest = manifest
        self.arrays = arrays

    def __len__(self):
        return int(self.arrays["env"].shape[0])

    def choices(self, i):
        """Episode i's candidate indices in decision order."""
        lo, hi = self.arrays["choice_offset"][i], self.arrays["choice_offset"][i + 1]
        return self.arrays["choice"][int(lo):int(hi)]


def load(path):
    """Reads <path>.json and <path>.npz; RecipeVersionError for another format."""
    path = str(path)
    with open(path + ".json", encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("format") != FORMAT:
        raise RecipeVersionError(f"format {manifest.get('format')!r}, this package reads {FORMAT!r}")
    with np.load(path + ".npz") as npz:
        arrays = {name: npz[name] for name in npz.files}
    if sorted(arrays) != sorted(ARRAYS):
        raise RecipeVersionError(f"arrays {sorted(arrays)}, expected {sorted(ARRAYS)}")
    n = arrays["env"].shape[0]
    for name, (dtype, tail) in ARRAYS.items():
        lead = {"choice_offset": n + 1, "choice": arrays["choice"].shape[0]}.get(name, n)
        if arrays[name].dtype != dtype or arrays[name].shape != (lead,) + tail:
            raise RecipeVersionError(f"array {name}: {arrays[name].dtype}{arrays[name].shape}")
    return Recipe(manifest, arrays)


def _check_versions(recipe):
    m = recipe.manifest
    found = version()
    if m.get("library_version") != found:
        raise RecipeVersionError(f"written by library {m.get('library_version')}, this is {found}")
    layout = {"size": _layout.OBSERVATION.itemsize, "layout_sha256": observation_layout_sha256()}
    if m.get("observation") != layout:
        raise RecipeVersionError("written with another observation layout")
    for entry in m["setups"]:
        if _setup_table([entry["name"]])[0] != entry:
            raise RecipeVersionError(f"setup {entry['name']} has other bytes now")


def replay(recipe, workers=1, on_decision=None):
    """Replays every episode of the recipe and checks it.

    on_decision(env, episode, player, observation, candidates, count, choice)
    receives each decision's inputs; observation and candidates are views
    into the batch, valid until the next decision. Raises RecipeVersionError
    before anything runs, ReplayMismatch at the first difference.
    """
    _check_versions(recipe)
    m, a = recipe.manifest, recipe.arrays
    with Context(**m["context"]) as ctx:
        if ctx.fingerprint().hex() != m["context_fingerprint"]:
            raise RecipeVersionError("written under another context fingerprint")
        if len(recipe) == 0:
            return
        envs = int(a["env"].max()) + 1
        runs = [[] for _ in range(envs)]  # each environment's episodes, in recipe order
        setup_of = np.zeros(envs, dtype=np.int64)
        for i in range(len(recipe)):
            e = int(a["env"][i])
            if runs[e] and int(a["setup"][i]) != setup_of[e]:
                raise ReplayMismatch(f"environment {e} changes its setup")
            setup_of[e] = int(a["setup"][i])
            runs[e].append(i)
        table = [reference_setups([PAIRINGS[s["name"]]])[0] for s in m["setups"]]
        setups = np.array([table[s] for s in setup_of], dtype=_layout.SETUP)
        with Batch(ctx, setups, workers, m["seed"]) as batch:
            for r in range(max(len(run) for run in runs)):
                _replay_round(batch, recipe, [run[r] if r < len(run) else None for run in runs], on_decision)


def _replay_round(batch, recipe, rows, on_decision):
    a = recipe.arrays
    active = np.array([row is not None for row in rows])
    for e in np.flatnonzero(active):
        batch.reset(e, int(a["episode"][rows[e]]))
    done = np.zeros(batch.envs, dtype=np.int64)  # steps taken
    used = np.zeros(batch.envs, dtype=np.int64)  # choices consumed
    running = active.copy()
    while True:
        batch.query()
        terminal = batch.requests["requested"].sum(axis=1) == 0
        for e in np.flatnonzero(running):
            row = rows[e]
            if terminal[e] or done[e] == int(a["steps"][row]):
                running[e] = False
                _finish(batch, recipe, e, row, done[e], used[e], terminal[e])
        if not running.any():
            return
        indices = np.full((batch.envs, 2), _layout.NO_CHOICE, dtype=np.uint16)
        for e in np.flatnonzero(running):
            row = rows[e]
            choices = recipe.choices(row)
            for p in range(2):
                if batch.requests[e, p]["requested"] == 0:
                    continue
                if used[e] >= len(choices):
                    raise ReplayMismatch(f"env {e} episode {a['episode'][row]}: more decisions than recorded")
                choice = int(choices[used[e]])
                count = int(batch.counts[e, p])
                if choice >= count:
                    raise ReplayMismatch(f"env {e} episode {a['episode'][row]}: choice {choice} of {count}")
                if on_decision is not None:
                    on_decision(e, int(a["episode"][row]), p, batch.observations[e, p],
                                batch.candidates[e, p, :count], count, choice)
                indices[e, p] = choice
                used[e] += 1
        batch.step(indices, active=running)
        done[running] += 1


def _finish(batch, recipe, e, row, steps, used, terminal):
    a = recipe.arrays
    where = f"env {e} episode {a['episode'][row]}"
    if steps != int(a["steps"][row]):
        raise ReplayMismatch(f"{where}: {steps} steps, recorded {a['steps'][row]}")
    if used != len(recipe.choices(row)):
        raise ReplayMismatch(f"{where}: {used} decisions, recorded {len(recipe.choices(row))}")
    if bool(a["truncated"][row]) == bool(terminal):
        raise ReplayMismatch(f"{where}: terminal {bool(terminal)}, recorded truncated {bool(a['truncated'][row])}")
    if batch.result(e) != int(a["result"][row]):
        raise ReplayMismatch(f"{where}: result {batch.result(e)}, recorded {a['result'][row]}")
    if batch.digest(e) != a["digest"][row].tobytes():
        raise ReplayMismatch(f"{where}: final digest differs")
