# M12 Stage 1 (One-Turn Lookahead) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-turn lookahead on top of the learned policy and value, measured in the arena against the same network without search and against a panel of older checkpoints.
- **The search:** own top-K pairs against the foe's top-M pairs, S chance samples each, scored by the value head and reduced by Nash or by the expected value.
- **The measurement:** at a stated budget per decision, with paired bootstrap intervals, in a report labeled as an oracle benchmark.

**Architecture** (approach A, decision 0022):
- **Engine (C):** one parallel batch call, `duoforge_batch_expand`, plus the pure seed function `duoforge_search_seeds`. For each leaf the call copies the root, reseeds, steps the factored pair and C-encodes the viewer's row.
- **Search (Python):** a new package `python/duoforge_search`. It holds the candidates, the leaf rounds, the value calls, the table, the reductions, the records and the arena driver. It contains no rule.

**Tech Stack:** C11 (the library and its CTest tests), Python 3.12 with NumPy 2 (`python/duoforge` and the NumPy parts of `duoforge_search`, unittest), JAX in WSL `~/df-learn` (the model, the search's network calls, the arena).

**Spec:** `docs/superpowers/specs/2026-10-03-m12-search-stage1-design.md`. The section numbers below (S4.3 and so on) refer to it. **Decision:** `docs/decisions/0022-search-support.md` (D0022).

## Global Constraints

**Errors**
- **No silent fallback.** There is no fallback to the raw network inside a search. Every refusal is a status, an exception or a counted, recorded outcome, exactly as S7 lists it.
- **What stops a run:**
  - a refused step in the arena itself counts as `play_suite` counts it;
  - a refused step in a leaf counts −1 and is marked;
  - everything else in the S7 table stops the run and writes its reproduction data.

**Rules and packages**
- **No rule in Python.** Legality comes from the factored domain, outcomes and results from the engine, values from the network.
- **Package dependencies:**
  - `python/duoforge` imports only NumPy and the standard library;
  - `duoforge_search.matrix` and `duoforge_search.seeds` are NumPy-only;
  - `duoforge_search.lookahead` and `duoforge_search.arena` use JAX through `duoforge_learn.policy.Model`.

**Determinism**
- **Seeds:**
  - leaf seeds come only from `duoforge_search_seeds(seed, key, sample)`;
  - decision keys and play draws come from D0022 §2;
  - nothing depends on a worker count, a chunk, a leaf's position or the cell (i, j).
- **The network** runs on padded batches of fixed shape, with `XLA_FLAGS=--xla_gpu_deterministic_ops=true` on the GPU.
- **The arena** processes games in a fixed order.
- **The budget** is a leaf count, never a time.

**Library**
- **No allocation in `duoforge_batch_expand`:** no `dfi_alloc*` in the call or anything it calls. A leaf's temporaries live on the stack, as in `dfi_encode_env`.
- **Versions** are assigned by the HauptSession at merge. Ask it for the number before opening a C PR.
- **A bump** edits `include/duoforge/duoforge.h` (MINOR and STRING), `python/duoforge/_lib.py` `EXPECTED_VERSION`, `python/tests/test_lib.py` (two lines) and `tests/test_api_atomicity.c`.

**Search defaults**

| Setting | Default |
|---|---|
| K, M, S | 8, 8, 16 (1024 leaves) |
| Leaf capacity L | 16,384 |
| Nash certificate | exploitability ≤ 1e-9 |
| Probability floor of the Nash draw | 1e-9 |
| Arena `max_steps` | 1000 |
| Suite budget | 2,048 |
| Bootstrap resamples | 2,000, seed `0x2026100300000220` |
| Search seed | `0x2026100300000221` |
| Arena seed | `0x2026100300000222` |

**Tests and process**
- **Test registration:** tests are `unittest`. NumPy-only modules go in the `foreach` list of `tests/CMakeLists.txt` (run with `DUOFORGE_PYTHON`); JAX modules go in the `DUOFORGE_LEARN_PYTHON` block (run in WSL `~/df-learn`).
- **CI:** every PR is green on the GitHub CI, which is the merge gate since 2026-10-03 (owner). `tools/ci/local_ci.sh` is not required.
- **Review:** every code PR gets a review agent (`fullstack-dev-kit:pr-reviewer`, model opus). Verify each finding before you change anything.
- **Merging:** the HauptSession merges with merge commits. Send it the PR number, the head and the CI result.
- **Staging:** stage files by name. Never `git add -A`.
- **Measurements** (Tasks 12 and 13): announced to the HauptSession, run on a quiet machine, in the daytime only. No GPU and no heavy job from 21:30 to 06:00.

## Review Focus

1. **The cell never reaches the seeds.** If a refactor folds (i, j) or the leaf index into the reseed, common random numbers silently break (test `test_samples_share_seeds_across_cells`, Task 3).
2. **Two status arrays.** An encoder refusal must never read as a step refusal. A step refusal counts −1 and the search goes on; an encoder refusal stops the run (Task 3 `test_step_and_encode_statuses_are_apart`, Task 9 `test_encoder_refusal_stops_the_run`).
3. **The arena's cut-off.** A leaf of the arena's last step is scored by the tiebreak, not by the value head. The step index must be the arena loop's own (Task 10 `test_last_step_leaves_use_the_tiebreak`).
4. **K = 1 is the raw network.** N with K = 1 must reproduce R's records exactly. A difference means the search changes a decision it must not touch: the root encoding, the tie rule or the seat (Task 10 `test_k1_reproduces_the_raw_network`).
5. **The Nash certificate.** A missed certificate stops the run and is never relaxed to make a measurement pass (Task 6).

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/batch/batch_each.h`, `src/batch/batch.c` | the factored bundle builder shared by `step_factored` and `expand` | 1 |
| `include/duoforge/duoforge_search.h`, `src/search/search.c`, `CMakeLists.txt` (the source list of the library target that holds `src/encode/encode.c`) | `duoforge_search_seeds`, `duoforge_batch_expand` | 2, 3 |
| `tests/test_search_seeds.c`, `tests/test_search_expand.c` | CTests `duoforge.search.seeds`, `duoforge.search.expand` | 2, 3 |
| `python/duoforge/_lib.py`, `python/duoforge/batch.py` | `Batch.expand`, `duoforge.search_seeds` | 5 |
| `python/duoforge_search/__init__.py`, `errors.py` | the package; `SearchError` | 6 |
| `python/duoforge_search/matrix.py` | Nash LP, certificate, expected value, ties, the draw | 6 |
| `python/duoforge_search/seeds.py` | decision keys, play draws | 7 |
| `python/duoforge_learn/policy.py` | `Model.value` | 8 |
| `python/duoforge_search/lookahead.py` | candidates, leaf rounds, the table, decisions, records | 9 |
| `python/duoforge_learn/evaluate.py` | `play_suite` passes the step index | 10 |
| `python/duoforge_search/arena.py` | `SearchPlayer`, the measurement CLI, paired bootstrap | 10, 11 |
| `docs/learning/<date>-m12-stage1/` | the report | 12, 13 |

Python tests:
- `python/tests/test_search_expand.py` (Task 5), registered as `search_expand`;
- `test_search_numpy.py` (Tasks 6, 7 and the NumPy parts of 9 and 11), registered as `search_numpy`;
- `test_search.py` (the JAX parts of Tasks 8 to 11), registered as `duoforge.python.search`.

## PRs and order

| PR | Tasks | Branch | Needs on main |
|---|---|---|---|
| Docs | spec, D0022, this plan | `chris/m12-spec` (#198) | — |
| A | 1, 2, 3, 4 | `chris/m12-expand` | decision 0021 (`duoforge_batch_query_encoded`) |
| B | 5 | `chris/m12-bindings` | A |
| C | 6, 7 | `chris/m12-matrix` | — (NumPy only; may start at once) |
| D | 8, 9, 10 | `chris/m12-search` | B, C |
| E | 11, 12, 13 | `chris/m12-arena` | D, and the many-team run's checkpoints |

- **When a branch starts:** from main, once its needs are merged. If a need is still in review, stack on its branch and retarget after the merge.
- **The 0021 re-check:** before PR A, compare S4.3 and D0022 with the merged `duoforge_encode.h`. Any difference (a name, the refusal order) is fixed in the spec, in D0022 and here, in the same PR A.

---

### Task 1: The shared factored bundle builder

**Files:**
- Modify: `src/batch/batch_each.h` (declaration), `src/batch/batch.c` (`dfi_factored_response`, `dfi_choice_bundle`)

**Interfaces:**
- Produces: `duoforge_status dfi_factored_bundle(const duoforge_request req[2], const duoforge_factored_domain dom[2], const duoforge_factored_choice choice[2], duoforge_decision_bundle *out)`. It builds and checks exactly what `duoforge_batch_step_factored` builds today, and `step_factored` calls it. No behavior changes.

- [ ] **Step 1: Move the code.** Extract the body of the factored path of `dfi_choice_bundle` into `dfi_factored_bundle`, with the same checks in the same order:
  - the epoch of player 0's request;
  - a SLOTS choice whose pair bit is not set, or whose index is past its list, is `E_INVALID_ARGUMENT`;
  - TEAM_SELECTION picks are left to the step;
  - an unrequested player gets an all-zero response.
- [ ] **Step 2: Run** `ctest --test-dir build/gcc-debug -R "batch\\."`. Expect PASS, unchanged, in the GCC, Clang and MSVC builds.
- [ ] **Step 3: Commit** `src/batch/batch_each.h src/batch/batch.c` with the message "Batch: the factored bundle builder as an internal function (for decision 0022)".

### Task 2: `duoforge_search_seeds`

**Files:**
- Create: `include/duoforge/duoforge_search.h` (it includes `duoforge_encode.h`), `src/search/search.c`, `tests/test_search_seeds.c`
- Modify: `CMakeLists.txt` (sources), `tests/CMakeLists.txt`: `duoforge_add_test(NAME duoforge.search.seeds SOURCES test_search_seeds.c LIBS duoforge_batch TIMEOUT 60)`

**Interfaces:**
- Produces: the declaration of S4.3 and the formula of D0022 §2.

- [ ] **Step 1: Write the failing test.**
  - `test_known_values`: three (seed, key, sample) triples, (0, 0, 0), (`0x2026100300000221`, 1, 15) and (2^64 − 1, 2^64 − 1, 2^32 − 1), give pinned `initstate`/`initseq`.
    - Compute the literals once with `duoforge_learn.pairing.splitmix64` and the D0022 formula in a Python one-liner, and paste them.
    - Write the one-liner into the test's comment.
  - `test_initseq_below_2_63`: 10,000 triples from a splitmix64 stream; every `initseq < 2^63`.
  - `test_reseed_accepts`: `duoforge_battle_reseed` returns OK with every pair of `test_initseq_below_2_63` on a reference battle.
- [ ] **Step 2: Run, expect a build failure** (undeclared function).
- [ ] **Step 3: Implement** the four lines of D0022 §2 with the library's splitmix64 (`dfi_splitmix` of `src/batch/batch.c`). If it is static, move it to `batch_each.h` as `static inline`.
- [ ] **Step 4: Run, expect PASS** in the GCC, Clang and MSVC builds.
- [ ] **Step 5: Commit** with the message "Search seeds (decision 0022)".

### Task 3: `duoforge_batch_expand`

**Files:**
- Modify: `include/duoforge/duoforge_search.h`, `src/search/search.c`
- Create: `tests/test_search_expand.c`
- Modify: `tests/CMakeLists.txt`: `duoforge_add_test(NAME duoforge.search.expand SOURCES test_search_expand.c LIBS duoforge_batch TIMEOUT 300)`

**Interfaces:**
- Consumes: `dfi_factored_bundle` (Task 1), `duoforge_search_seeds` (Task 2), `dfi_batch_query_player`, `duoforge_battle_observe_ext`, `duoforge_encode` (decision 0021).
- Produces: the declaration and contract comment exactly as in S4.3.

- [ ] **Step 1: Write the failing tests.**

  **Fixtures.**
  - **Contexts:** a POOL context. The roots are a 4-environment batch over two pool pairings that include Teams A and B, run with uniform random indices for 0 to 12 steps per environment, so the roots stand at TURN, REPLACEMENT and, if reached, PIVOT boundaries.
  - **The leaf batch:** 64 environments, any setups of the same context.
  - **The leaves:** per root, every requested own SLOTS choice up to 4 crossed with every foe choice up to 4, samples 0 to 3, viewer `env % 2`.

  **Tests.**
  - `test_leaves_equal_the_single_battle_sequence`. For each leaf, the reference is `duoforge_battle_clone(root)`, `duoforge_battle_reseed` with the Task 2 seeds, `dfi_factored_bundle`-equivalent bundles built in the test from the domains, and `duoforge_battle_step`. Then:
    - `duoforge_battle_digest` of `duoforge_batch_env(leaves, i)` equals the reference's;
    - `results[i]` and `leaf_results[i]` equal the reference;
    - a non-TERMINAL leaf's obs row equals `duoforge_encode(4, mask, …)` of the reference's observation, factored domain and extension for the viewer, byte for byte (`memcmp`), with mask = every supported bit.
  - `test_worker_counts_agree`: the same call with 1, 2, 3, 4, 8 and 16 workers gives byte-equal outputs and digests.
  - `test_samples_share_seeds_across_cells`: for one root and one sample, every cell (i, j) equals its reference clone reseeded with the one pair `duoforge_search_seeds(seed, key, s)`. A cell or leaf index in the seeds fails this test.
  - `test_terminal_leaf_has_a_result_and_a_zero_row`.
    - Find a root and a pair that end the battle: random roots, every pair of the first 4 × 4, until a step is TERMINAL; at most 2,000 tries, else the test fails and names the seed.
    - Expect `leaf_results` to be the reference's result, the row all zero, and `encode_statuses` OK.
  - `test_step_and_encode_statuses_are_apart`.
    - (a) A leaf with a SLOTS choice whose pair bit is clear: `step_statuses[i] = E_INVALID_ARGUMENT`, `encode_statuses[i] = OK`, the row all zero, the other leaves equal their references, and the call returns `E_INVALID_ARGUMENT`.
    - (b) A POOL root with Sand up (a pool team with Sand Stream, found through the data query API by ability name), encoded with version 4 and the Sand bit cleared: `step_statuses[i] = OK`, `encode_statuses[i] = E_UNSUPPORTED`, and the call returns `E_UNSUPPORTED`.
  - `test_refused_step_is_isolated`.
    - Under SYNTHETIC data, a root past team selection: every combat bundle is `E_UNSUPPORTED`, by `duoforge_battle_step`'s contract.
    - A second root at TEAM_SELECTION in the same call steps OK.
    - Each leaf gets its own status, and the call returns `E_UNSUPPORTED`.
  - `test_roots_are_unchanged`: the root digests before and after every call of this file are equal.
  - `test_checks_touch_no_leaf`. Each of the following leaves every leaf digest unchanged:
    - NULL leaves, roots, requests, domains, keys, viewers, root_envs, samples, choices or an output, with count 1: `E_NULL_ARGUMENT`;
    - count past the leaf batch, a root env past the root batch, or a viewer of 2: `E_INVALID_ARGUMENT`;
    - version 0 or 5, or a mask past version 4's bits: what `duoforge_encode` gives for them;
    - batches of two contexts: `E_CONTEXT_MISMATCH`;
    - count 0 with NULL arrays: OK.
- [ ] **Step 2: Run, expect a build failure.**
- [ ] **Step 3: Implement.**
  - **Checks first,** in the order of `test_checks_touch_no_leaf`. Run them over all leaves before `dfi_pool_run`; the root-env range check is O(count).
  - **The pass:** `dfi_pool_run(leaves->pool, slice, &job, count)`. Per leaf:
    1. `duoforge_battle_copy(ctx, leaf, root)`;
    2. `duoforge_battle_reseed` with the seeds;
    3. `dfi_factored_bundle` from `root_requests[2·r]`, `root_domains[2·r]` and `choices[2·i]`;
    4. `duoforge_battle_step` into `results[i]`;
    5. on OK: `duoforge_battle_result`. At TERMINAL write `leaf_results[i]` and zero the row. Otherwise do as `dfi_encode_env` does for one player: `dfi_batch_query_player`, `duoforge_battle_observe_ext` when the mask has a record bit, and `duoforge_encode` with stack slots (768 floats) and pair-mask buffers.
  - **A failed step** zeroes the row and leaves `encode_statuses[i]` OK.
  - **The return:** the lowest failing leaf's step status, else the lowest failing encode status, else OK.
  - **The episode:** set the leaf environment's `terminal` flag from the result, so a later `reset_terminal` on the leaf batch behaves. Its episode number is untouched; the leaf batch is never reset in the search.
- [ ] **Step 4: Run, expect PASS** in the GCC, Clang and MSVC builds.
- [ ] **Step 5: Commit** with the message "Batch expand: copy, reseed, step and encode search leaves in one pass (decision 0022)".

### Task 4: ThreadSanitizer, version, docs

**Files:**
- Modify: the TSan job's test list in `tools/ci/linux_ci.sh` and the hosted workflow (add `duoforge.search.expand`); the version files of the Global Constraints; `docs/ARCHITECTURE.md` §10 (one sentence: search leaves use `duoforge_batch_expand`, which reseeds every leaf from search seeds); `docs/ROADMAP.md` M12 (status line: stage 1's library part).

- [ ] **Step 1:** Add the test to the TSan job. Run that job; expect no race report.
- [ ] **Step 2:** Ask the HauptSession for the version number, then bump it.
- [ ] **Step 3:** Open PR A with the 0021 re-check result in its description; the GitHub CI is the gate.

### Task 5: `Batch.expand` and `duoforge.search_seeds`

**Files:**
- Modify: `python/duoforge/_lib.py` (argtypes), `python/duoforge/batch.py`
- Create: `python/tests/test_search_expand.py`; register `search_expand` in the `foreach` list

**Interfaces:**
- Produces:
  - `duoforge.search_seeds(seed, key, sample) -> (initstate, initseq)`;
  - `Batch.expand(roots, version, ext_supported, seed, keys, viewers, root_envs, samples, choices)`.
- Inputs of `Batch.expand`, called on the leaf batch:
  - `roots` is the root `Batch`; its `requests` and `domains` arrays, as its last `query_encoded` or `query_factored` left them, are passed;
  - `keys` uint64 and `viewers` uint8 have shape (roots.envs,);
  - `root_envs` and `samples` uint32 have shape (n,);
  - `choices` is `_layout.FACTORED_CHOICE` with shape (n, 2).
- It returns `(obs (n, size) float32, step_statuses, encode_statuses, results, leaf_results)` in arrays the batch reuses on the next call.
- It raises `DuoforgeError` with `statuses` set to `step_statuses` for an argument check. It does not raise for per-leaf refusals: those are returned, because the search decides what they mean (S7).

- [ ] **Step 1: Write the failing tests** (NumPy only, a POOL context, as in Task 3).
  - `test_seed_function_matches_the_formula`: `search_seeds` equals the D0022 formula in NumPy over 100 triples.
  - `test_expand_shapes_and_reuse`: the shapes, dtypes and buffer reuse across two calls.
  - `test_worker_counts_agree`: 1 and 4 workers give equal outputs.
  - `test_leaf_row_equals_query_encoded_of_its_environment`: after `expand`, `leaves.query_encoded(4, mask)` gives the same row for the viewer of a non-TERMINAL leaf.
  - `test_argument_errors_raise`: n past the leaf batch, viewer 2, version 5.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** with the patterns of `query_encoded` (`uint`, `ptr`, `_require`, `_buffers`).
- [ ] **Step 4: Run, expect PASS.** Commit with the message "Python: Batch.expand and search_seeds (decision 0022)". Open PR B; the GitHub CI is the gate.

### Task 6: The matrix game

**Files:**
- Create: `python/duoforge_search/__init__.py`, `python/duoforge_search/errors.py` (`SearchError(RuntimeError)`), `python/duoforge_search/matrix.py`, `python/tests/test_search_numpy.py`

**Interfaces:**
- Produces:
  - `solve(a) -> (x, y, value)`: a float64 table (K′, M′), maximized by the row player;
  - `exploitability(a, x, y) -> float`;
  - `expected_choice(a, q, prior_rank) -> int`;
  - `draw(x, prior_rank, u) -> int`.

- [ ] **Step 1: Write the failing tests.**
  - `test_certificate_on_random_tables`: 2,000 tables from a seeded NumPy generator, sizes 1 × 1 to 16 × 16, entries in [−1, 1]. Include integer tables (degenerate), duplicated rows and columns, and constant tables. Every solution has `exploitability ≤ 1e-9`, x and y on the simplex.
  - `test_agrees_with_support_enumeration`: up to 4 × 4, brute-force support enumeration (in the test) gives the same game value within 1e-12.
  - `test_saddle_points_are_pure`: tables with a strict saddle point give x and y with one entry 1.
  - `test_known_games`:
    - matching pennies gives x = y = (½, ½) and value 0;
    - rock–paper–scissors gives (⅓, ⅓, ⅓);
    - a dominated row gets 0.
  - `test_missed_certificate_raises`: a solver result perturbed by the test into a bad x raises `SearchError` naming the gap.
  - `test_expected_choice_ties`: equal Σ q·a goes to the better prior rank; within equal ranks, to the lower index.
  - `test_draw`:
    - probabilities below 1e-9 are dropped and the rest renormalized;
    - the draw walks pairs in prior-rank order;
    - u = 0 gives the first pair with mass, and u → 1 the last.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `solve`.**
  - Shift the table: a′ = a − min(a) + 1, so every entry is ≥ 1.
  - Solve max Σ q subject to a′ q ≤ 1, q ≥ 0, by a dense tableau simplex. The origin is feasible, so no phase 1 is needed.
  - Bland's rule: the lowest-index entering column with a positive reduced cost; ratio-test ties go to the lowest basic index.
  - Read off y = q / Σq and x from the slack columns' reduced costs, normalized; value = 1 / Σq + min(a) − 1.
  - Iteration cap: 10,000; reaching it raises `SearchError`.
  - Run the certificate (`exploitability ≤ 1e-9`) on every solution before returning it.
- [ ] **Step 4: Run, expect PASS.** Commit with the message "Search: the matrix game (exact LP with certificate), expected value, ties, the draw".

### Task 7: Decision keys and play draws

**Files:**
- Create: `python/duoforge_search/seeds.py`
- Modify: `python/tests/test_search_numpy.py`

**Interfaces:**
- Produces:
  - `decision_keys(arena_seed, envs, episodes, epochs, seats) -> uint64 array`;
  - `play_uniforms(seed, keys) -> float64 array`.

  Both follow the D0022 §2 formulas, vectorized, using `duoforge_learn.pairing.splitmix64` and `draw`.

- [ ] **Step 1: Write the failing tests.**
  - `test_keys_formula`: compare with a scalar Python transcription.
  - `test_keys_are_distinct`: 64 envs × 4 episodes × 200 epochs × 2 seats give no collision.
  - `test_uniforms_in_unit_interval`: values in [0, 1) with 53-bit resolution.
  - `test_order_free`: shuffled inputs give shuffled outputs.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.** Commit with the message "Search: decision keys and play draws (decision 0022)". Open PR C; the GitHub CI is the gate.

### Task 8: `Model.value`

**Files:**
- Modify: `python/duoforge_learn/policy.py`
- Create: `python/tests/test_search.py`; register it in the `DUOFORGE_LEARN_PYTHON` block as `duoforge.python.search`

**Interfaces:**
- Produces: `Model.value(params, obs) -> (B,) float32`. It is jitted and calls `apply` with all-zero slots and an all-false mask, so the value is computed by the same function as in training.
  - The value does not read slots or mask (spec S3).
  - A faster value-only network comes only with a measurement.

- [ ] **Step 1: Write the failing test.** `test_value_equals_apply_value`: for v1 and v2-S at init, on 64 encoded rows from a POOL batch (`query_encoded`), `Model.value(params, obs)` equals `apply(params, obs, slots, mask)[2]` with the real slots and mask, bit for bit.
- [ ] **Step 2: Run, expect FAIL. Step 3: Implement. Step 4: Run, expect PASS.** Commit with the message "Model: a value call for search leaves".

### Task 9: The one-turn lookahead

**Files:**
- Create: `python/duoforge_search/lookahead.py`
- Modify: `python/tests/test_search_numpy.py` (the NumPy parts), `python/tests/test_search.py`

**Interfaces:**
- Produces: `Lookahead(context, model, params, encoder, ext_supported, k=8, m=8, s=16, rule="nash", seed=SEARCH_SEED, capacity=16384, workers=8)`.
- `decide(roots, envs, seats, keys, last_step) -> (pair indices (len(envs),), records)`. The inputs:
  - `roots` is a `Batch` whose last `query_encoded(encoder, ext_supported)` is current;
  - `last_step[i]` is true when this step is the arena's last.
- Its parts:
  - `select(logp, mask, k) -> (pair indices, probabilities)`: top k with ties to the lower flat index; k′ = min(k, legal pairs). NumPy.
  - `leaf_plan(k_counts, m_counts, s) -> (decision, i, j, sample)`: arrays in the order decision, i, j, sample. NumPy.
  - `table(values, step_statuses, encode_statuses, leaf_results, tiebreaks, plan, seat) -> (A, standard errors, counts)`, applying S5.3 and S7:
    - TERMINAL gives ±1 or 0 from the seat's side;
    - a refused step gives −1, counted;
    - a last-step leaf gives its tiebreak, and −1 if the tiebreak cannot resolve;
    - any other step status, or any encode status, raises `SearchError` with the root's bytes (`Batch.encode`, privileged; add it to the bindings in this task if it is missing), the pair, the sample and the seeds.

    NumPy.
- Inside one call:
  1. one `model.apply` over the roots' rows of both seats;
  2. `select` for the seat (K) and for the foe (M; M′ = 1 for a foe without a request);
  3. the leaf plan, then chunks of at most `capacity` leaves through `Batch.expand` (the leaf batch is created once in `__init__`);
  4. `Batch.tiebreak` on the last-step leaves, before the next chunk;
  5. one `model.value` per chunk, padded to `capacity` rows;
  6. the table, its rows and columns in prior-rank order, as `select` returns them (`matrix.solve` breaks ties among equilibria by that order); Nash (`matrix.solve` and `matrix.draw` with `seeds.play_uniforms`) or the expected value (`matrix.expected_choice`); the record of S8.5.
     - The record also holds `Solution.exact` (the exact rescue decided).
     - It also counts the table's near-duplicate rows: pairs whose largest difference is below 1e-6. The review of #199 asked for their rate in real tables.
- **Encoder versions:** an encoder version or mask the C encoder refuses raises at `__init__`, through a zero-leaf probe call.

- [ ] **Step 1: Write the failing NumPy tests.**
  - `test_select_top_k_and_ties`: ties go to the lower index; k′ for small domains.
  - `test_leaf_plan_order`.
  - `test_table_rules`: one constructed case per row of S7: terminal win and loss from both seats, a tie, a refused step, a last-step tiebreak, and an unresolvable tiebreak.
  - `test_encoder_refusal_stops_the_run`: an encode status raises `SearchError` naming the leaf.
  - `test_split_half`: the record fields of S8.5 on a constructed value array.
- [ ] **Step 2: Write the failing JAX tests** (POOL, Teams A and B, v2-S at a fixed init key, CPU).
  - `test_samples_share_seeds_across_cells`: in the plan, the seeds of sample s are the same for every (i, j).
  - `test_decision_is_pure`: the same call twice gives equal tables and choices, bit for bit.
  - `test_alone_equals_in_a_round`: one decision alone and inside a round of 16 gives the same table. If this fails on a device, the test reports it as an expected failure for that device only; it is never deleted.
  - `test_pinned_decision` (the owner's note on #205):
    - pinned exactly on every machine: the integer and structural parts of one decision (candidates, leaf outputs and C-encoded rows, leaf kinds, the choice);
    - the table within 1e-6;
    - `test_pinned_table_bytes`: the table's SHA-256 only under its recorded conditions (JAX version, CPU, XLA flags, capacity); elsewhere the test reports itself skipped with both conditions.
  - `test_forced_and_team_selection_are_not_searched`: such decisions make no leaves and are counted.
- [ ] **Step 3: Implement. Step 4: Run, expect PASS.** Commit with the message "Search: the one-turn lookahead (spec S4.2, S5, S7)".

### Task 10: `SearchPlayer` in the arena

**Files:**
- Modify: `python/duoforge_learn/evaluate.py`: `play_suite` passes `step=t`, the loop index, to `learner.indices` and `other.indices`; `Player.indices` accepts and ignores it.
- Create: `python/duoforge_search/arena.py` (`SearchPlayer`)
- Modify: `python/tests/test_search.py`

**Interfaces:**
- Produces: `SearchPlayer(lookahead, name, arena_seed, max_steps)` with the `Player` interface: `indices(batch, choices, step)`.
  - It calls `batch.query_encoded` and `Lookahead.decide` for the environments where its seat is requested, with keys from `seeds.decision_keys(arena_seed, env, batch.episode(env), epoch, seat)` and `last_step = step == max_steps − 1`.
  - It returns factored choice indices as `Player.indices` does.
  - It keeps the records per game row.

- [ ] **Step 1: Write the failing tests.**
  - `test_play_suite_records_unchanged`: the existing suite tests pass with the `step` keyword.
  - `test_k1_reproduces_the_raw_network`: on a 32-row suite over Teams A, B and C (v2-S, fixed init), `SearchPlayer` with K = 1 against R gives records equal to R against R, field for field. Only the search's own records exist in addition.
  - `test_last_step_leaves_use_the_tiebreak`: with `max_steps = 3`, the decisions at step 2 have every non-terminal leaf scored by the tiebreak (record counts).
- [ ] **Step 2: Run, expect FAIL. Step 3: Implement. Step 4: Run, expect PASS.** Commit with the message "Search: SearchPlayer in play_suite". Open PR D; the GitHub CI is the gate.

### Task 11: The measurement CLI

**Files:**
- Modify: `python/duoforge_search/arena.py` (`main`), `python/tests/test_search_numpy.py`, `python/tests/test_search.py`

**Interfaces:**
- Produces: `python -m duoforge_search.arena --run-dir RUN --out DIR [--agents N,E] [--opponents raw,panel] [--sweep] [--games 2048] [--k 8 --m 8 --s 16] [--workers 8]`.
  - **The checkpoint:** the best checkpoint of RUN by its ladder file, or `--checkpoint`.
  - **The panel:** the run's checkpoints nearest to 25, 50 and 75 percent of its updates, via `ladder._checkpoints`; or `--panel A,B,C`.
  - **The pool:** `ladder._pool_of(RUN)`.
  - **The suite:** `make_suite(N, ARENA_SEED, budget=games)`.
  - **Configurations:**
    - main: N vs R, E vs R;
    - panel: R, N and E vs each panel member;
    - sweep (with `--sweep`): S ∈ {4, 64} at 8 × 8, and K × M ∈ {4 × 4, 16 × 16} at S = 16, for N and E vs R.
  - **Outputs:**
    - `DIR/raw/<config>-games.csv`: `play_suite` records plus the seat;
    - `DIR/raw/<config>-decisions.jsonl`: the S8.5 records;
    - `DIR/raw/<config>-timing.json`: median and p95 ms per searched decision, split into network, engine and reduction;
    - `DIR/summary.json`: scores, Elo, intervals, the paired differences, the diagnostics, device and versions.
- Its parts:
  - `bootstrap_mean(values, resamples, seed) -> (low, high)` and `bootstrap_paired(a, b, resamples, seed) -> (low, high)`, NumPy, over game rows;
  - `elo(score)`.

- [ ] **Step 1: Write the failing tests.**
  - NumPy:
    - `test_bootstrap_is_seeded_and_paired`: the same rows give the same interval; a paired difference of identical arrays is (0, 0);
    - `test_elo_mapping`: 0.5 gives 0, and the mapping is monotone.
  - JAX: `test_cli_smoke`, a 16-game run on Teams A, B and C with a tiny checkpoint written by the test. Every output file exists and the summary has every configuration.
- [ ] **Step 2: Run, expect FAIL. Step 3: Implement. Step 4: Run, expect PASS.** Commit with the message "Search: the arena measurement CLI".

### Task 12: Cost per decision (first measurement)

- [ ] **Step 1:** Announce it to the HauptSession. Run in the daytime on a quiet machine: the main configuration N vs R on a 256-game suite, with the many-team checkpoint.
- [ ] **Step 2:** Record the median and p95 ms per searched decision, the split, the searched decisions per game and the device. Write them to `docs/learning/<date>-m12-stage1/README.md` as "Cost", beside the spec's estimate of about 8 ms.
- [ ] **Step 3:** If the measured total is more than 3 times the estimate, stop and report to the owner before Task 13 (the measurement's GPU time would grow by the same factor).

### Task 13: The full measurement and the report

- [ ] **Step 1:** Announce it, then run every configuration of Task 11 with 2,048 games. That is about 25 main-point units, about 2 hours of GPU at the estimate; Task 12 gives the real figure. Run in the daytime only.
- [ ] **Step 2:** Write `docs/learning/<date>-m12-stage1/README.md` in the manner of the learning reports.
  - **The label:** title and first paragraph say "oracle benchmark" and list what the oracle knows (spec S3).
  - **Configuration:** checkpoint, panel, pool, seeds, budget.
  - **The tables:** N and E against R (score, 95 %, Elo); the panel differences; the sweep; the cost; the diagnostics of S8.5.
  - **The gate of S8.6,** stated as met or not met. If not met, a cause analysis (noise, coverage, the value head) from the records.
- [ ] **Step 3:** Commit the report and `raw/` and open PR E; the GitHub CI is the gate.
