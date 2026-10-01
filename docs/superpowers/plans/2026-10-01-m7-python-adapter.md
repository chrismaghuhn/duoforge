# M7 Python Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python drives DuoForge's batch runtime once per batch, with zero-copy NumPy buffers, baseline policies and replayable trajectory recipes.

**Architecture:** A shared library exposes the existing C API plus four small functions. A pure-Python package loads it with ctypes and owns NumPy buffers that it passes by pointer. Recipes store seeds and candidate indices and regenerate features by replay.

**Tech Stack:** C17 (engine, CMake, CTest), Python 3.12 in `.venv`, NumPy 2.5, ctypes.

**Spec:** `docs/superpowers/specs/2026-10-01-m7-python-adapter.md`. Decision: `docs/decisions/0013-python-adapter.md`.

**Owner prerequisite (before Task 3's Linux part):** in WSL, `sudo apt install python3.12-venv`.

## Global Constraints

- Library version becomes `0.11.0` (`include/duoforge/duoforge.h`, `tests/test_api_atomicity.c`).
- `src/` follows `cmake/checks/lint_sources.cmake`:
  - no `int`, `long`, `short`, `unsigned`, `signed`, `float`, `double`
  - no `printf`, `memcmp`, `assert`, `malloc`/`free` (use `dfi_alloc_zeroed`/`dfi_free`)
  - a cast `(uint*_t)(` needs `/* wide-operands-reviewed */` on its line
- Warnings are errors (`DUOFORGE_WARNINGS_AS_ERRORS`). MSVC's C4701 counts too, so initialize locals that are read after a conditional write.
- No rule logic in Python (AGENTS.md). Unsupported input fails explicitly, with a raised exception or a status, never silently.
- Python dependencies are NumPy only; the interpreter is `.venv` (git-ignored).
- The batch API allocates nothing per step in the new functions; they use only caller arrays.
- One PR per task (owner rule). Merge on a green `tools/ci/local_ci.sh`, with its summary lines in the PR.
- Stop and report to the owner in short German after every task.

## Review Focus

1. A stale or missing shared library (an old build, a wrong path) must raise `DuoforgeLibraryError` naming the paths tried and the version found, not crash. Task 3.
2. Index arrays of the wrong dtype, shape or memory order (int64, Fortran order, a view) must raise `TypeError`/`ValueError` before any pointer goes to C. Task 4.
3. `step()` after `reset_terminal()` without a new `query()` must raise `DuoforgeError` with `E_STALE_EPOCH` for the reset environments; the others still step. Task 4.
4. A recipe from another library version or context fingerprint must raise `RecipeVersionError` before replaying. Task 5.
5. A requested player with candidate count 0 (impossible from the engine, possible in hand-made arrays) must raise `ValueError` in the policies, never divide by zero. Task 6.

---

### Task 1: Reference setups and battle result in the C API

**Files:**
- Create: `src/state/reference_teams.c` (the team data and `df_put_team` logic moved from `tests/support/fixtures.c`)
- Modify: `include/duoforge/duoforge.h` (two declarations, version 0.11.0), `CMakeLists.txt` (source list), `tests/support/fixtures.c` (`df_setup_teams` calls `duoforge_reference_setup(0u, out)`), `src/state/request.c` or a new `src/state/result.c` (`duoforge_battle_result`)
- Test: `tests/test_reference_api.c` (`duoforge.api.reference_setup`, `duoforge.api.result`)

**Interfaces:**
- Produces: `duoforge_status duoforge_reference_setup(uint32_t pairing, duoforge_battle_setup *out);` and `duoforge_status duoforge_battle_result(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t *out_result);` with the contracts of spec section 2.

- [ ] **Step 1: Write the failing tests**

```c
/* duoforge.api.reference_setup */
duoforge_battle_setup s[4];
for (uint32_t p = 0u; p < 4u; ++p) DF_CHECK(&t, duoforge_reference_setup(p, &s[p]) == DUOFORGE_OK);
duoforge_battle_setup old; df_setup_teams(&old);                  /* before the move: the reference */
DF_CHECK(&t, memcmp(&s[0], &old, sizeof old) == 0);              /* A-B equals today's fixture */
DF_CHECK(&t, memcmp(&s[1].sides[0], &s[0].sides[1], sizeof s[0].sides[0]) == 0); /* B-A swaps */
DF_CHECK(&t, memcmp(&s[2].sides[1], &s[0].sides[0], sizeof s[0].sides[0]) == 0); /* A-A */
DF_CHECK(&t, memcmp(&s[3].sides[0], &s[0].sides[1], sizeof s[0].sides[0]) == 0); /* B-B */
duoforge_battle_setup marker; memset(&marker, 0xA5, sizeof marker); duoforge_battle_setup out = marker;
DF_CHECK(&t, duoforge_reference_setup(4u, &out) == DUOFORGE_E_INVALID_ARGUMENT && memcmp(&out, &marker, sizeof out) == 0);
DF_CHECK(&t, duoforge_reference_setup(0u, NULL) == DUOFORGE_E_NULL_ARGUMENT);
/* duoforge.api.result: 0 at TEAM_SELECTION; at TERMINAL equal to the RESULT event of the last step */
```

The result test plays dataset battle 0 of `docs/certification/closure-v1/dataset.txt` (copy the replay loop from `certify/certify.c` `cert_play`) and compares with the RESULT event.

- [ ] **Step 2: Run** `cmake --build build/gcc-debug && ctest --test-dir build/gcc-debug -R "duoforge.api"` and expect it to fail on the unresolved symbols.
- [ ] **Step 3: Implement both functions.** `duoforge_battle_result` uses the query prologue (`dfi_query_prologue` semantics) and reads `battle->result` (`DFI_RESULT_*` maps 1:1 to `DUOFORGE_RESULT_*`). Bump the version to 0.11.0.
- [ ] **Step 4: Run** the full GCC suite: all green, including `duoforge.certify.dataset`, whose setups now come through the moved data.
- [ ] **Step 5: Commit** "C API: reference setups and battle result (library 0.11.0)".

### Task 2: Batch reset and step by index

**Files:**
- Modify: `include/duoforge/duoforge_batch.h`, `src/batch/batch.c`
- Test: `tests/test_batch_indices.c` (`duoforge.batch.step_indices`, `duoforge.batch.reset`)

**Interfaces:**
- Consumes: `duoforge_batch_query` (decision 0012).
- Produces: `duoforge_status duoforge_batch_reset(duoforge_batch *batch, uint32_t env, uint32_t episode);`, `#define DUOFORGE_BATCH_NO_CHOICE 0xFFFFu`, and `duoforge_status duoforge_batch_step_indices(duoforge_batch *batch, const duoforge_request *requests, const duoforge_side_choice *candidates, const uint32_t *counts, const uint16_t *indices, duoforge_status *statuses, duoforge_step_result *results);`

- [ ] **Step 1: Write the failing tests:**
  - Two batches with the same seed, 37 environments and 4 workers; one steps by bundles built in the test, the other by `step_indices` with the same indices (`next() % count`). After every step all battle digests are equal, up to TERMINAL everywhere.
  - Environment 3 gets index `counts[6]` and environment 8 gets `DUOFORGE_BATCH_NO_CHOICE` for a requested player. Both have status E_INVALID_ARGUMENT and an unchanged digest, the rest step, and the call returns E_INVALID_ARGUMENT.
  - `reset(b, 5, 7)` gives the digest of a single battle created with `duoforge_batch_seeds(seed, 5, 7)`. `reset(b, 37, 0)` returns E_INVALID_ARGUMENT.
- [ ] **Step 2: Run** `ctest -R "duoforge.batch"` and expect failures.
- [ ] **Step 3: Implement.** `step_indices` is a pool job like `dfi_step_slice`; each environment builds its bundle on its own stack. `reset` calls `dfi_batch_reset`.
- [ ] **Step 4: Run** the GCC suite, then `tools/ci/linux_ci.sh clang-tsan` through WSL; both green.
- [ ] **Step 5: Commit** "Batch: reset one environment, step by candidate index".

### Task 2b: Factored domain

**Files:**
- Modify: `include/duoforge/duoforge.h` (`DUOFORGE_MAX_SLOT_OPTIONS`, `duoforge_factored_domain`, `duoforge_factored_choice`, `duoforge_battle_factored`), `src/state/request.c` (built from `dfi_side_lists` and `dfi_pair_allowed`, so both forms share the pair rule), `include/duoforge/duoforge_batch.h` and `src/batch/batch.c` (`duoforge_batch_query_factored`, `duoforge_batch_step_factored`)
- Test: `tests/test_factored.c` (`duoforge.request.factored`, `duoforge.batch.step_factored`)

**Interfaces:**
- Consumes: Task 2's `duoforge_batch_step_indices` (the factored step reuses its per-environment step).
- Produces: the types and three functions of spec section 2 ("Factored domain"), exactly as declared there.

- [ ] **Step 1: Write the failing tests.**
  - Run the play loop of `tests/test_candidates_digest.c` (64 seeds, same policy). At every boundary, expanding the factored domain (row-major pairs; team tuples by lexicographic unranking) gives `memcmp == 0` against `duoforge_battle_candidates`, with the same count.
  - In a batch with 37 environments, a factored step with the choice of joint rank `next() % count` gives the same digests as `step_indices` with that index.
  - A choice whose bit is not set fails only its environment.
  - `sizeof(duoforge_factored_domain) == 652` and `sizeof(duoforge_factored_choice) == 8`.
- [ ] **Step 2: Run** `ctest -R "factored"` and expect failures.
- [ ] **Step 3: Implement.** `duoforge_battle_factored` uses the query prologue, then `dfi_side_lists` for the slot lists and `dfi_pair_allowed` for each bit. At TEAM_SELECTION it sets only the counts.
- [ ] **Step 4: Run** the GCC suite (including `duoforge.request.candidates_digest`) and the TSan job: green.
- [ ] **Step 5: Commit** "Factored candidate domain: slot lists and pair mask (652 bytes per player)".

### Task 3: Shared library, layout dump, Python package skeleton

**Files:**
- Modify: `CMakeLists.txt`:
  - a `DUOFORGE_SOURCES` variable, reused by `duoforge` and the new `duoforge_shared` (SHARED, `POSITION_INDEPENDENT_CODE ON`, `WINDOWS_EXPORT_ALL_SYMBOLS ON`)
  - cache path `DUOFORGE_PYTHON`
- Modify: `.gitignore` (`/.venv/`)
- Create: `tools/layout/layout_dump.c` (`duoforge_layout_dump`: JSON `{"struct": {"size": n, "fields": {"name": [offset, size]}}}`)
- Create: `python/duoforge/__init__.py`, `python/duoforge/_lib.py`, `python/duoforge/_layout.py`, `python/duoforge/errors.py`, `python/duoforge/context.py`
- Create: `python/tests/test_layout.py`, `python/tests/test_lib.py`
- Modify: `tests/CMakeLists.txt` (when `DUOFORGE_PYTHON` is set: `add_test(duoforge.python.<name> COMMAND ${DUOFORGE_PYTHON} -m unittest python.tests.test_<name>)` with environment `DUOFORGE_LIBRARY=$<TARGET_FILE:duoforge_shared>` and `DUOFORGE_LAYOUT_DUMP=$<TARGET_FILE:duoforge_layout_dump>`, label `python`)
- Modify: `tools/ci/local_ci.sh` (`-DDUOFORGE_PYTHON=$ROOT/.venv/Scripts/python.exe` in the `win-gcc-debug` job when that file exists) and `tools/ci/linux_ci.sh` (`-DDUOFORGE_PYTHON=$HOME/df-venv/bin/python` in `gcc-release-ipo` when that file exists; `linux_ci.sh --setup-python` creates `~/df-venv` and installs NumPy, after the owner has installed `python3.12-venv`)

**Interfaces:**
- Produces:
  - `duoforge.load_library() -> ctypes.CDLL`
  - `duoforge.version() -> str`
  - `duoforge.DuoforgeLibraryError`, `duoforge.DuoforgeError(status_name, statuses=None)`
  - `duoforge._layout`: `REQUEST`, `OBSERVATION`, `SIDE_CHOICE`, `STEP_RESULT`, `SETUP`, `CONTEXT_CONFIG`, `EPISODE` (NumPy dtypes, explicit offsets)
  - `duoforge.Context(data_kind=2, max_roster=6, brought_count=4)` with `.handle` and `.close()`
  - `duoforge.reference_setups(pairings: list[int]) -> ndarray[SETUP]`

- [ ] **Step 1: Write the failing tests.** `test_layout`: for every struct in the dump, `dtype.itemsize == size` and `dtype.fields[name][1] == offset` for every listed field. `test_lib`:
  - `version() == "0.11.0"`
  - `DUOFORGE_LIBRARY=nonexistent.dll` raises `DuoforgeLibraryError` whose message contains `nonexistent.dll` (Review Focus 1)
  - `reference_setups([0,1,2,3]).shape == (4,)`
- [ ] **Step 2: Run** `ctest -R duoforge.python` and expect failures.
- [ ] **Step 3: Implement.**
  - `_lib.py` searches `DUOFORGE_LIBRARY`, the package dir, then `build/*/` and `build/*/Release`, and checks `duoforge_version_string()` against `0.11.0`.
  - `_layout.py` writes each dtype with `np.dtype({"names": ..., "formats": ..., "offsets": ..., "itemsize": ...})`.
- [ ] **Step 4: Run** `tools/ci/local_ci.sh --quick`: green, with the Python tests counted in `win-gcc-debug`.
- [ ] **Step 5: Commit** "Python package skeleton over a shared library; layout check".

### Task 4: Batch class and random policy (native vs. binding)

**Files:**
- Create: `python/duoforge/batch.py`, `python/duoforge/policies.py` (`RandomPolicy`, `seeds()`), `python/tests/test_equivalence.py`

**Interfaces:**
- Consumes: Task 2's C functions and Task 3's loader, dtypes and `Context`.
- Produces:
  - `Batch(context, setups, workers, seed)` with buffers `requests` (E,2), `observations` (E,2), `candidates` (E,2,784), `counts` (E,2) uint32, `statuses` (E,), `results` (E,)
  - methods `query()`, `step(indices)`, `reset(env, episode)`, `reset_terminal()`, `play_random(episodes, max_steps) -> ndarray[EPISODE]`, `result(env)`, `digest(env) -> bytes`, `episode(env)`, `close()`
  - `seeds(seed, env, episode) -> tuple[int, int, int]`
  - `RandomPolicy(seed, envs)` with `choose(batch) -> ndarray[(E,2), uint16]` (NO_CHOICE for unrequested players), `choose_factored(batch) -> ndarray[(E,2), FACTORED_CHOICE]` and `start_episode(env, episode)`
  - `Batch.query_factored()`, `Batch.step_factored(choices)`, `joint_index(domain, choice) -> int`, `factored_choice(domain, k) -> FACTORED_CHOICE`

- [ ] **Step 1: Write the failing tests:**
  - 37 environments over the four pairings, seed `0x2026100200000012`, workers 1 and 4. Native `play_random(3, 1000)` must produce byte-identical records to a Python loop: `start_episode` for episodes 1..3, `reset(env, k)`, `query` and `choose`/`step` until TERMINAL, then build the record from `result`, `digest`, steps and decisions.
  - The same with `query_factored` and `choose_factored`/`step_factored` gives the same records.
  - `joint_index(d, factored_choice(d, k)) == k` for every k below the count, over all domains of one episode.
  - `step(np.zeros((E,2), np.int64))` raises `TypeError`, and `step(np.asfortranarray(idx))` raises `ValueError` (Review Focus 2).
  - `reset_terminal()` followed by `step()` without `query()` raises `DuoforgeError("DUOFORGE_E_STALE_EPOCH")` (Review Focus 3).
- [ ] **Step 2: Run** `ctest -R duoforge.python.equivalence` and expect failures.
- [ ] **Step 3: Implement.**
  - `step` checks `indices.dtype == np.uint16`, its shape and `flags.c_contiguous`, then passes `.ctypes.data_as(...)`.
  - `RandomPolicy` holds a uint64 state per environment. splitmix64 is vectorized in NumPy with wrapping uint64 arithmetic (`np.errstate(over="ignore")`).
- [ ] **Step 4: Run** the test and expect PASS for 1 and 4 workers.
- [ ] **Step 5: Commit** "Python batch and random policy, equal to the native mode".

### Task 5: Trajectory recipes

**Files:**
- Create: `python/duoforge/recipes.py`, `python/tests/test_recipes.py`

**Interfaces:**
- Consumes: Task 4's `Batch`, `RandomPolicy`, `seeds`.
- Produces:
  - `RecipeWriter(path, *, seed, max_steps, setups: list[str], policies: list[dict], command: str)` with `add(env, episode, setup, policy: tuple[int, int], choices: ndarray[uint16], steps, result, truncated, digest: bytes)` and `close()`
  - `load(path) -> Recipe`
  - `replay(recipe, workers=1, on_decision=None)`
  - `ReplayMismatch`, `RecipeVersionError`
  - format and manifest exactly as in spec section 6 (`format: "duoforge-recipe-1"`)

- [ ] **Step 1: Write the failing tests:**
  - 16 episodes with `RandomPolicy`, written and loaded, then `replay` without errors. `on_decision` is called exactly `sum(len(choices))` times, and the npz arrays have the spec's names and dtypes.
  - Changing `choice[5]` to another valid index raises `ReplayMismatch`.
  - Changing the manifest's library version raises `RecipeVersionError` before any battle runs (Review Focus 4).
- [ ] **Step 2: Run** and expect failures.
- [ ] **Step 3: Implement** with `np.savez` (without compression) and `json.dump`; the setup hash is `hashlib.sha256(setup.tobytes())`.
- [ ] **Step 4: Run** and expect PASS.
- [ ] **Step 5: Commit** "Trajectory recipes: seeds and indices, replay to features".

### Task 6: Scripted policy and feature encoder

**Files:**
- Modify: `python/duoforge/policies.py` (`ScriptedPolicy`)
- Create: `python/duoforge/features.py` (`encode`), `python/tests/test_policies_features.py`

**Interfaces:**
- Consumes: Task 3's dtypes (observation side and position views, `slot_command` fields).
- Produces: `ScriptedPolicy()` with `choose(batch) -> ndarray[(E,2), uint16]` and the scores of spec section 4, and `encode(observation, domain) -> tuple[ndarray[float32], ndarray[float32], ndarray[bool]]`, which returns the observation part, the slot part (2, 32, k) and the pair mask (32, 32).

- [ ] **Step 1: Write the failing tests:**
  - Over 32 environments played to the end with `ScriptedPolicy`, every chosen index is below `count`, and two runs give the same digests.
  - `encode` gives equal arrays for equal inputs, and different arrays after one changed foe HP percent.
  - The pair mask's sum equals the joint count.
  - Counts with 0 for a requested player raise `ValueError` in both policies (Review Focus 5).
- [ ] **Step 2: Run** and expect failures.
- [ ] **Step 3: Implement**, vectorized over (E,2,784). The candidate features are the slot command fields scaled to [0,1]; the docstring documents the layout.
- [ ] **Step 4: Run** and expect PASS.
- [ ] **Step 5: Commit** "Scripted baseline and observation-only feature encoder".

### Task 7: Example, exit report, M7 done

**Files:**
- Create: `python/duoforge/examples/__init__.py`, `python/duoforge/examples/generate.py`, `python/tests/test_example.py`
- Modify: `docs/decisions/0013-python-adapter.md` (status and the evidence of spec section 8), `docs/ROADMAP.md` (M7 status), `README.md` (a "Python" section with the venv, build and example commands)

**Interfaces:**
- Consumes: everything above.
- Produces: `python -m duoforge.examples.generate --envs N --episodes K --policy random|scripted --workers W --seed S --out PATH`, printing battles, decisions, results per pairing and bytes on disk; exit status 0 only after a clean replay.

- [ ] **Step 1: Write the failing test.** `test_example` runs the module with 8 environments, 2 episodes and `--policy scripted`. It expects exit status 0, two files at `--out` and a printed line `replay: 16 episodes, 0 mismatches`.
- [ ] **Step 2: Run** and expect failure.
- [ ] **Step 3: Implement** the CLI with `argparse`; generation uses Task 4/6 policies and Task 5's writer and replay.
- [ ] **Step 4: Run** the full `tools/ci/local_ci.sh`: all jobs green. Then run the example once with `--envs 64 --episodes 10` and put its output into decision 0013 as the bounded example.
- [ ] **Step 5: Commit** "M7 done: generation example and exit report".
