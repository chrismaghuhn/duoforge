# DuoForge

DuoForge is a deterministic C17 battle engine for Pokémon Champions VGC 2026 Reg M-C doubles, built for machine-learning workloads. It is an authoritative simulation core: every rule lives in C, and the Python bindings and ML tooling on top contain none. The rules basis and the reference are owner selections (`docs/decisions/0004`): the format `[Gen 9 Champions] VGC 2026 Reg M-C` and Pokémon Showdown at the pinned revision `b2cb775b0616115b775534eaeff50300e1fc81fc`. The library version is 0.44.0 (`include/duoforge/duoforge.h`). The engine does not claim full Gen 9 support: a mechanic it does not implement is refused at setup with `DUOFORGE_E_UNSUPPORTED`, never approximated.

## Components

- **C core** (`src/`, `include/duoforge/`): PCG32 RNG, owned pointer-free battle state with a canonical encoding and digest, requests and joint choices, the turn core, the perspective-safe observation and per-player event log, the batch runtime, the C encoder and the search support. Headers: `duoforge.h`, `duoforge_batch.h`, `duoforge_encode.h`, `duoforge_search.h`, `duoforge_view.h`.
- **Data kinds** (`DUOFORGE_DATA_KIND_*`): `SYNTHETIC` (no combat), `CLOSURE` (the two reference teams), `TEAM_C` (the extended tables, decision 0009), `POOL` (the growing tables of the content expansion, decision 0015), and a `_DEV` variant of each real kind for development fixtures.
- **`python/duoforge`**: ctypes and NumPy bindings, the batch runtime, views and encoders (current feature encoder version 5, `python/duoforge/features.py`), the random and scripted baselines and trajectory recipes.
- **`python/duoforge_live`**: Showdown protocol adapter for live play (decision 0016).
- **`python/duoforge_replay`**: turns human Reg M-C replays into behaviour-cloning data (decision 0019).
- **`python/duoforge_learn`**: self-play PPO, Learner v2, league and PFSP opponent sampling, behaviour-cloning prior and distillation (decisions 0014, 0017).
- **`python/duoforge_search`**: honest search over public information and expert iteration (decisions 0022 to 0024).
- **`tools/reference`**: records battles from the pinned Showdown and drives differential testing of the engine against it; `tools/difftest` is the C side of that runner.
- **`bench/`**: the benchmark driver and API (decision 0008).

## Current goals

Plan for the week of 2026-10-09.

- **Main goal: engine coverage of the Reg M-C metagame.** Target: at least 99 % of Reg M-C games playable with both sides fully supported. Measured on main on 2026-10-09 15:10: 50.0 % (23.8 % at the start of the week); 69 % of the distinct teams are fully supported. Unsupported mechanics are refused explicitly at setup (`DUOFORGE_E_UNSUPPORTED`), never silently approximated.
- **How:** two parallel expansion lanes, A for moves and B for abilities, items and Mega Evolutions. Each mechanic is differentially tested against recorded Showdown battles, each lane lands as one batch PR, and new public values need a decision note under `docs/decisions`.
- **Performance:** lockstep batching with tick deduplication of network rows for the search teacher (stage 3 P2), measured at 1.43 to 1.48 times on CPU (`docs/learning/2026-10-09-stage3-p2/README.md`).
- **Learning, next:** the stage-3 P1 pilot, expert-iteration data collection and distillation into the policy (`docs/superpowers/plans/2026-10-08-stage3-p1-pilot.md`), with a Trick Room diagnostic in its evaluation.
- **Not now:** no long or overnight training runs this week. Cloud runs only once coverage covers the metagame.

## Requirements

- CMake 3.23 or newer (verified with 3.23.3 and 3.28.3)
- A C17 compiler: MSVC, GCC or Clang (verified: GCC 13.3 and Clang 18.1 on Linux and MSVC in hosted CI; GCC 16.2 MinGW-w64, Clang 23.1 and MSVC 2022 natively on Windows)
- Ninja for the supplied presets

There are no third-party runtime dependencies. Python 3 is used only by the offline oracle in `tools/state_model/`; the build and tests do not need it.

## Build and test

```text
cmake --preset debug
cmake --build --preset debug
ctest --preset debug

cmake --preset release
cmake --build --preset release
ctest --preset release
```

On Linux, the same with AddressSanitizer and UndefinedBehaviorSanitizer (GCC or Clang; Clang needs compiler-rt installed):

```text
cmake --preset sanitize
cmake --build --preset sanitize
ctest --preset sanitize
```

On Windows, run the commands from a Visual Studio Developer Command Prompt so that MSVC is available. Generator-neutral form:

```text
cmake -S . -B build/debug -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DDUOFORGE_WARNINGS_AS_ERRORS=ON
cmake --build build/debug
ctest --test-dir build/debug --output-on-failure --no-tests=error
```

Options:

| Option | Default | Effect |
|---|---|---|
| `DUOFORGE_WARNINGS_AS_ERRORS` | OFF | `-Werror` / `/WX`. CI and all local verification use ON. |
| `DUOFORGE_ENABLE_SANITIZERS` | OFF | ASan + UBSan, non-recovering (GCC/Clang only). |
| `DUOFORGE_ENABLE_IPO` | OFF | Link-time optimization of Release builds (8 to 13 percent faster battles, decision 0008 section 8). The library then links only with the same toolchain; fails the configuration where unsupported. |
| `DUOFORGE_PYTHON` | empty | Python 3.10+ with NumPy 2 for the `duoforge.python.*` tests (see "Python"); without it they report skipped. |
| `DUOFORGE_PCG_REFERENCE_DIR` | empty | Path to a checkout of `imneme/pcg-c-basic` at `bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3`. Enables the reference tests (`ctest -L reference`): byte-identical KAT regeneration and a 1,024,000-operation lockstep differential. |

Every test is finite and has a timeout. Test groups:

| Group | What it covers |
|---|---|
| `duoforge.unit.*` | Checked arithmetic, byte order, SHA-256, damage and stat arithmetic against the reference, draw sites and tape |
| `duoforge.combat.*` | The turn core through the public API: one turn, determinism, continuation across encode/decode, honest `E_UNSUPPORTED`, random play; the closure gate with the real teams (`closure_gate`) and the Team C gate (`team_c_gate`) |
| `duoforge.reference.*` | The recorded reference battles (`tests/reference/traces`) replayed draw for draw, with the request compared after every step (`conformance`), the generated tables against the traces; with a checkout: traces and arithmetic regenerated |
| `duoforge.rng.*` | PCG32 known-answer vectors and contract |
| `duoforge.state.*` | Context, setup, identity, knowledge (HP display as last seen), closure setup (real sets, gate, member invariant), invariants, clone/equal/reseed, setup sweep |
| `duoforge.codec.*` | Goldens, negative decoding (including "rejected: schema 1"), exhaustive mutation sweep |
| `duoforge.request.*` | Exhaustive domains against the oracle, stable and pure enumeration, output convention, step validation and atomicity, honest UNSUPPORTED, re-prompt, contract minimum (snapshots per boundary, stale/late, two-side replacement and pivot, one-side continuation), observation and information equivalence |
| `duoforge.data.*` | Generated closure tables against values read at the pin, the table hash, the Champions stat and PP formulas; optional regeneration against a pinned Showdown checkout (`-DDUOFORGE_PS_REFERENCE_DIR=...`, label `reference`) |
| `duoforge.batch.*` | The batch runtime: native and step mode against single battles, stepping by index and by factored choice |
| `duoforge.python.*` | The Python package (label `python`): layouts against C, loader, native-versus-binding equivalence, recipes, policies and encoder, the example |
| `duoforge.api.*` | Status names, NULL and context-mismatch sweeps, C++ link |
| `duoforge.lint.*` | Source rules and their self-test; no writable globals |
| `duoforge.provenance.*` | Vendored license hash |
| `duoforge.sanitizer.*` | Sanitizer liveness canaries (sanitizer builds only) |

## Python

The package `python/duoforge` (decision 0013) drives the engine from Python over ctypes and NumPy: a batch of environments per call with the GIL released, buffers allocated once, the random and scripted baselines, an observation-only feature encoder and trajectory recipes (seeds and choices, replayed to features). It needs CPython 3.10 or later and NumPy 2; every rule stays in C.

```text
python -m venv .venv
.venv/Scripts/python -m pip install numpy        (Linux: .venv/bin/python)
cmake -S . -B build/py -DBUILD_TESTING=ON -DDUOFORGE_PYTHON=<repo>/.venv/Scripts/python.exe
cmake --build build/py
ctest --test-dir build/py -L python --output-on-failure
```

The tests find the shared library `duoforge_shared` through `DUOFORGE_LIBRARY`; without `DUOFORGE_PYTHON` they report skipped. To use the package directly, set `DUOFORGE_LIBRARY` to the built library and put `python/` on `PYTHONPATH`. The example writes a recipe and replays it:

```text
python -m duoforge.examples.generate --envs 64 --episodes 10 --policy random --workers 4 --out recipes/random640
```

For an RL loop, `Batch.step_query(indices, autoreset=True)` steps, starts every ended episode anew and queries the next boundary in one call. `python -m duoforge.examples.throughput` measures the Python loop against the native mode (`docs/benchmarks/2026-10-02-python-loop/`).

## Learning (decisions 0014, 0017)

`python/duoforge_learn` trains a policy by self-play PPO on the batch runtime: JAX on the GPU, which needs Linux, so in WSL with its own venv and a Release library built there.

```text
python3 -m venv ~/df-learn
~/df-learn/bin/pip install "jax[cuda12]" optax numpy
cmake -S /mnt/c/Dev/src/duoforge -B ~/df-build/learn -G Ninja -DCMAKE_BUILD_TYPE=Release -DDUOFORGE_ENABLE_IPO=ON -DBUILD_TESTING=OFF
cmake --build ~/df-build/learn --target duoforge_shared
cd /mnt/c/Dev/src/duoforge
DUOFORGE_LIBRARY=~/df-build/learn/libduoforge_shared.so PYTHONPATH=python ~/df-learn/bin/python -m duoforge_learn.train --envs 256 --workers 16 --minutes 30 --out ~/df-runs/trial
```

The log (`log.jsonl`) has one line per update; every `--eval-every` updates it adds the greedy policy's win rates against the random and the scripted baselines and against its previous evaluation (`vs_previous`), and saves the parameters. `DUOFORGE_LEARN_PYTHON` (a Python with JAX) enables the test `duoforge.python.learn`; the local CI's Linux GCC Release job sets it when `~/df-learn` exists.

## Public API (provisional, `include/duoforge/duoforge.h`)

- **Status:** `duoforge_status` (`uint32_t`) codes and `duoforge_status_name`.
- **Context:** `duoforge_context_create` (for a data kind), `duoforge_context_destroy` and `duoforge_context_fingerprint`. The context is immutable and shareable read-only; the `duoforge_data_*` queries read its tables.
- **Battle lifecycle:** `duoforge_battle_create` (from a setup; the battle starts at TEAM_SELECTION), `duoforge_battle_create_decoded`, `duoforge_battle_clone` and `duoforge_battle_destroy`.
- **Model-facing decision surface:** `duoforge_battle_request` (one player's request with the exact candidate count), `duoforge_battle_candidates` (the complete joint side-choice domain in documented order; too small a buffer returns `E_CAPACITY` and only the required count), `duoforge_battle_step` (one decision bundle for exactly the requested sides), `duoforge_battle_step_events` (the same step with each player's events; a too-small buffer returns `E_CAPACITY` and the required count) and `duoforge_battle_observe` and `duoforge_battle_observe_ext` (the perspective-safe observation), `duoforge_battle_factored` (the factored choice domain) and `duoforge_battle_result` (the outcome at TERMINAL). Requests, candidates and observations are pure.
- **Snapshots and codec:** `duoforge_battle_copy` (snapshot/restore), `duoforge_battle_decode`, `duoforge_battle_encoded_size`, `duoforge_battle_encode`, `duoforge_battle_digest` and `duoforge_battle_equal`.
- **Checking and forks:** `duoforge_battle_check` and `duoforge_battle_reseed` (decorrelates a forked copy for search).

Every call is failure-atomic: on error nothing is mutated or leaked, and the only out-parameter written on error is the required count of a model-facing query on `E_CAPACITY`. Encode, decode, digest, equal, check and reseed are **privileged**: they see hidden state and must never feed a model directly. The batch runtime (`duoforge_batch.h`) and the encoder, search and view headers sit beside it. The ABI is not frozen.

## Documentation

- Decisions: `docs/decisions/` (0001 to 0029, one file each; 0004 holds the owner selections, 0009 and 0015 the content expansion, 0016 to 0024 the live adapter, learner, replay data and search, 0025 to 0029 newer public values and mechanics)
- Roadmap and status: `docs/ROADMAP.md`, `docs/support/README.md` (status manifest), `docs/OPEN_DECISIONS.md`
- Architecture and contracts: `docs/ARCHITECTURE.md`, `docs/DECISION_CONTRACT.md`, `docs/DETERMINISM_AND_REPLAY.md`, `docs/TESTING_AND_BENCHMARKS.md`, `docs/SOURCES.md`
- Evidence: `docs/certification/closure-v1/`, `docs/benchmarks/`, `docs/learning/` (with `docs/learning/RUNBOOK.md`)
- Plans: `docs/superpowers/plans/`; task statements: `tasks/`
- Research drafts (unverified): `docs/research/`

## License

DuoForge is source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE):

- **Noncommercial use is free.** You may use, change and share it for any noncommercial purpose: research, education, hobby projects and noncommercial organizations.
- **Commercial use** needs a separate license from the owner. Ask via GitHub (`chrismaghuhn`).

Third-party parts keep their own licenses (`THIRD_PARTY_NOTICES.md`):

- **pcg-c-basic.** `third_party/pcg-c-basic/` and `src/rng/pcg32_derived.{h,c}` contain material from it, licensed by its author under the Apache License 2.0 (see `third_party/pcg-c-basic/LICENSE.txt`).
- **Pokémon Showdown.** The generated tables and the recorded traces derive from it, under the MIT License.

DuoForge makes no claim of full Gen 9 support, VGC compatibility beyond the supported mechanics, Pokémon Showdown parity or high performance.
