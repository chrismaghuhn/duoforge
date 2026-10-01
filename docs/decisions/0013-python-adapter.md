# 0013 — Python adapter and trusted trajectories (M7)

Status: proposed 2026-10-01; the owner's questions are in section 7.

## 1. Goal

Roadmap M7: a thin C ABI binding, packed observation and candidate batches, random and scripted baseline drivers, and a trajectory exporter that keeps provenance apart from features. Exit criteria: the binding is equivalent to the native runtime, exported trajectories replay, no feature carries hidden information, and a small bounded generation example works. A trained model is not needed.

## 2. Binding

- **Shared library.** `duoforge_shared` (DLL / `.so`) contains the engine and the batch runtime, and an export macro `DUOFORGE_API` marks the public functions (Windows needs explicit exports). The static libraries stay as they are.
- **Python over ctypes** (`python/duoforge/`):
  - One foreign call per batch. ctypes releases the GIL during the call.
  - NumPy arrays are passed by pointer, so nothing is copied.
  - Python only allocates arrays, calls the library and views the results; no rule logic lives in Python (AGENTS.md).
- **Layouts.** The C structs are NumPy structured dtypes, generated from the public header at build time. A test compares every size and offset with the compiler's, so a header change cannot desynchronize them silently.
- **Dependencies:** Python 3.10 or later and NumPy, nothing else. NumPy is not installed on the owner's machine yet.

## 3. Batches (EnvPool's synchronous mode, decision 0012)

- `query()` fills arrays of shape (environments, 2) for the requests, the observations (736 bytes each, a structured dtype) and the candidate counts, and an array of shape (environments, 2, `DUOFORGE_MAX_CANDIDATES`) for the candidates. The counts give the action mask.
- `step(indices)` takes one candidate index per environment and player. A new C function `duoforge_batch_step_indices` builds the bundles from the candidate array of the last query, so no Python loop over environments is needed. `reset_terminal()` starts finished environments on their next episode.
- Features come from the observation, which is the player's authorized view (decision 0007). A feature encoder (one-hot and the like) may live in Python because it encodes; it does not decide rules.

## 4. Drivers

- **Random:** the native mode (`duoforge_batch_play_random`) and, for the equivalence test, the same policy driven from Python.
- **Scripted:** one simple heuristic baseline that reads only the player's observation and candidates (for example the first damaging move at the foe shown with the least HP). It is a player, not a rule.

## 5. Trajectories

- **Features** (NumPy shards), per decision:
  - the observation bytes and the candidate count
  - the chosen candidate index and the chosen command (32 bytes)
  - the episode's outcome at its end
- **Provenance** (a JSON manifest plus a per-episode table), kept apart from the features:
  - versions and identity: library version, context fingerprint, observation schema
  - seeds: the batch seed, environment and episode, and the derived seeds (decision 0012)
  - policy and opponent ids, and the player's side
  - per decision: the request epoch
  - per episode: result and truncation
- **Replay check:** every exported episode is replayed through a fresh battle and must reach the same final digest, with the same request epoch at every decision.
- **Example:** a bounded generation run (for example 64 environments with 10 episodes each) that writes shards and replays them.

## 6. Later, not in M7: support for search

Pokémon doubles has simultaneous moves, hidden information and chance in every step. Plain AlphaZero-style MCTS does not fit; search needs simultaneous-move variants (decoupled UCT) and determinization or information-set MCTS. The papers the owner gave (RMCTS by Frankston and Howard 2026, PMCTS by Oren et al. 2026) show that the key is to evaluate the neural network in large batches, and Array-Based MCTS (Ragan et al. 2025) suggests node storage in arrays with indices. The engine will then need two functions:

1. **Load a state into a batch environment**, so that many leaves of a search tree step in parallel and their observations go to the network in one batch.
2. **Determinization:** build a complete battle from a player's observation and a sampled assignment of the hidden opponent information (sets, exact HP, items). This needs an owner decision on the belief model; the roadmap lists belief-conditioned search under "Later".

A state copy costs about 110 ns (decision 0008), so search trees can copy states and need no copy-on-write sharing.

## 7. Owner questions

1. **Binding:** ctypes over a shared library (recommended: no compiled extension to maintain, the GIL is released, nothing is copied), or a compiled CPython extension?
2. **Trajectory files:** NumPy `.npz` shards with a JSON manifest (recommended: NumPy only), or Parquet/Arrow (the ML standard, one more dependency)?
3. **NumPy:** may it be installed (`pip install numpy`) in the Python that runs the tests?
