# Stage 3 P2: lockstep leaf batching (M12 search side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** proposal for owner review, 2026-10-09. Docs only. Merging it authorizes Tasks 1 to 4 (code and tests, no run). Task 5's measurements wait for an owner window that does not contend with Learner v2 A/B/training.

**Goal:** One logical tick's teacher decisions share fixed-capacity value calls. Leaves are deduplicated and only open leaves are evaluated. Decisions stay byte-identical to the per-root teacher at the same seeds, capacity, device, runtime and CPU instruction set.

**Architecture:**
- The honest teacher's decision splits into `_prepare` (worlds, every expand chunk and tiebreak, rows copied out) and `_finish` (values in, table, reduction).
- A per-tick table deduplicates open rows incrementally as roots are prepared. It evaluates them in fixed 1024-row calls with a zero-padded tail, reusing Honest's preallocated `_rows` buffer, then scatters the values back to every `_finish`.
- `label_tick` is the per-tick entry; Learner v2's planner across games calls it later. Policy and team calls keep today's per-root shapes.

**Tech Stack:** Python/NumPy, the JAX policy/value model (CPU and GPU), duoforge C batch API (`expand`, `tiebreak`).

**Spec:** [stage-3 design](../specs/2026-10-05-m12-expert-iteration-design.md) section 4 (P2), [decision 0024](../../decisions/0024-expert-iteration.md), [P1 plan](2026-10-08-stage3-p1-pilot.md), [P0 report](../../learning/2026-10-08-stage3-p0/README.md) (fixed-shape inference curve), teacher contract `python/duoforge_search/EXPERT_TEACHER.md`.

**Depends on [#261](https://github.com/chrismaghuhn/duoforge/pull/261) (P1 C3).** `expert.py`, `EXPERT_TEACHER.md` and `Honest._decision(..., budget)` exist only there. Tasks 2 and 4 wait for its merge; Tasks 1 and 3 can run before.

**Local rule:**
- Locally, run only the targeted `pytest python/tests/test_<x>.py -k <name>` commands below. (Neither `python/` nor `python/tests/` has an `__init__.py`; CTest runs the same files as unittest.)
- Full suites run on GitHub CI, never locally.
- Each step is: a red test commit, then the minimal implementation, then the identical targeted command green.
- An expected red is a missing API or a failed assertion, never an environment import failure. No test weakening.
- Register `test_value_rows` in the learn/JAX list and `test_ticks` in the NumPy list of `tests/CMakeLists.txt`. `test_expert_teacher` is already registered (#261).

## Global Constraints

- Collect all leaves of a synchronized step in stable decision/cell/world order.
- Value calls use the fixed capacity 1024 with zero-padded tails. P0 measured that another capacity changes value bits (GPU at ≥256, CPU at ≥4096).
- Finish before actors advance. No async queues, no timeout flush, no active-count-sized calls.
- Pin the parallel-game count (512), chunk order, runtime, shapes and the reproduction conditions: JAX version, CPU model and XLA ISA flags (CPU bits depend on AVX vs AVX2/AVX-512, see `PINNED_TABLE_CONDITIONS` in `python/tests/test_search.py`), and `XLA_FLAGS` including deterministic GPU ops.
- Repeat runs give byte-identical decisions and targets under identical conditions, and agree with the reference audits. If reshaping changes float bits or targets, it is not pure performance: fix the layout or request a separately classified change. No CPU/GPU cross-device bit claim.
- **Recorded deviation from spec section 4:** policy and team calls keep today's per-root shapes. Per root that is the root policy call (1 row) and `_world_policy` (32 rows, 1 to 3 times). Batching them changes logit bits: P0 measured 96 CPU logit bits differing between 32 and 1024 rows. That needs its own identity gate in a later plan.
- Preallocate buffers outside battle hot paths. No routing or pruning changes. Learner v2 owns the planner across games.
- Stop on any identity failure, a memory-limit refusal in the measured setup, or a missed throughput bar (Task 5).
- Real worlds, tables, checkpoints and measurement outputs stay outside the repository (`refuse_repository`). Runs only in owner-approved windows; this week, code and tests only.

## What exists and what this plan adds

- **Existing claim.** `Lookahead`'s docstring (`python/duoforge_search/lookahead.py:237-240`) says a row's value does not depend on its position in the value call, while another batch shape changes it.
- **Existing tests sample that claim.** `test_leaf_values_are_the_seats_view` (`python/tests/test_search.py` ~170-185) and the multi-decision test (~436-463) check one row at position 0 with zero neighbours, at capacity 256 on the CI CPU.
- **Existing shared calls.** `Lookahead.decide` already packs several decisions into shared value calls (`lookahead.py:383-429`: `leaf_plan`, `for c0 in range(0, total, self.capacity)`, `self._rows` with zero padding). Task 3 reuses that chunk/pad code instead of new code.
- **Task 1 adds** a full sweep over all 1024 positions, random neighbours, padding vs filled tails, capacity 1024, the GPU, and real params-49333 on the owner's CPU and GPU. If it fails, the docstring is wrong: report it as a finding, not only a P2 stop.
- **Inputs measured elsewhere:**
  - P0: value call at capacity 1024 is 31.03 ms on CPU, 7.37 ms on GPU through the host (3.00 ms resident); the joint-policy call at 32 rows is 5.56 ms on CPU and 7.74 ms on GPU; CPU network time is about 39 of 50 ms per searched decision.
  - HauptSession probe (params-49333, X, K = M = 8, S = 16, capacity 1024, 64 games × 12 steps, early game phases only): 47.9% of nonzero rows per call are unique, 21.5% of capacity rows are all-zero, unique real rows are 37.6% of capacity (about 2.7× fewer rows), and no row repeats across calls.
  - C3 review: re-querying all environments costs about 3 ms per label.

## Forecast (Amdahl, to be confirmed by Task 5)

- **CPU, per root:** value is about 31 of 50 ms. With 2.7× fewer rows the value share drops to about 11.5 ms, so a root takes about 30.5 ms: **≈1.6×**. Policy, world builds and engine time are unchanged.
- **GPU, per root:**
  - Value: about 7.37 / 2.7 ≈ 2.7 ms (host interface).
  - Policy: 1 + (1 to 3) × 7.74 ms ≈ 15 to 23 ms, which caps the gain.
  - Splitting devices (policy on CPU at 5.56 ms per 32 rows, value on GPU) gives about 11 to 17 ms of policy per root.
  - Task 5 measures both splits. The device of each call type is fixed before measuring and recorded.
  - Batching policy calls would be the next lever, only with its own identity gate.

## Review Focus

1. **Value bits depend on row position, neighbours or padding at capacity 1024, or on the CPU instruction set.** Expected: Task 1 detects it in CI and on the owner's CPU/GPU, and P2 stops for reclassification.
2. **The next root's `_hypotheses` overwrites the worlds while the previous root's rows or tiebreaks are still needed.** Expected: `_prepare` finishes every expand chunk and `leaves.tiebreak` and copies its rows before returning (Task 2 test).
3. **A root of the tick refuses publicly or exhausts its budget.** Expected: only its decision falls back; the other roots' bytes are unchanged (Task 4).
4. **Ticks of different sizes** (1 root, 1023 open leaves, an exact multiple of 1024). Expected: identical per-root bytes (Task 3/4 tests).
5. **Memory for 512 roots.** All rows at 850 float32 would be about 3.4 KB × 1024 × 512 ≈ 1.8 GB. Expected: incremental dedup keeps only unique open rows (≈0.65 GB at the probe's 37.6%), and a hard limit fails with an explicit error (Task 3).

---

### Task 1: Value rows independent of position, neighbours and padding

**Files:**
- Create: `python/duoforge_search/rowprobe.py`
- Test: `python/tests/test_value_rows.py` (JAX list)

**Interfaces:**
- Produces:
  - `row_independence(model, params, rows: ndarray[N, width] float32, capacity: int, seed: int) -> dict` with keys `position_bits`, `neighbour_bits`, `padding_bits` (the number of rows whose float32 value bits ever differ) and `conditions` (JAX version, CPU model, `XLA_FLAGS`, device, capacity).
  - CLI: `python -m duoforge_search.rowprobe --checkpoint PRIVATE --device cpu|gpu --out PRIVATE`.
- Method:
  - Positions: `capacity` calls, each a cyclic shift of the same `capacity` rows, so every row visits every position.
  - Neighbours: a fixed row set with three seeded replacements of the other rows.
  - Padding: the same N < capacity rows with a zero tail vs a tail of real rows.
  - Compare bits with `view(np.uint32)`; no tolerance.

- [ ] **Step 1: Write the failing test** `test_value_rows_position_and_neighbour_independent`.
  - Use the v2 S model with `PRNGKey(7)`, CPU, capacity 1024, and 1024 encoded leaf rows from reference setups.
  - Assert all three counts are 0 and that `conditions` records the CPU model and `XLA_FLAGS`.
- [ ] **Step 2: Run it.** `pytest python/tests/test_value_rows.py -k position_and_neighbour_independent`. Expected: FAIL (ImportError: no module `duoforge_search.rowprobe`).
- [ ] **Step 3: Implement `row_independence` and the CLI.** The CLI refuses repository paths and writes counts and conditions only.
- [ ] **Step 4: Run it.**
  - PASS: the claim holds on the CI CPU only (this says nothing about the owner's Ryzen).
  - FAIL: STOP P2 and report the counts, plus the `Lookahead` docstring as wrong.
- [ ] **Step 5: Commit** ("rowprobe: value bit independence of position, neighbours and padding (P2 T1)").

### Task 2: Two-phase teacher decision, byte-identical (after #261)

**Files:**
- Modify: `python/duoforge_search/honest.py` (`_decision`)
- Test: `python/tests/test_expert_teacher.py`

**Interfaces:**
- Consumes: `Honest._decision(p, key, own, own_p, weights, last_step, costs, budget=None)` (#261).
- Produces:
  - `LeafRequest`, a frozen dataclass with:
    - `p: int`, `key: int`, `own: ndarray[K'] int64`, `last_step: bool`, `weights: ndarray[W]`;
    - `foe_pairs: ndarray[W, M']`, `qs: ndarray[W, M']`, `choices: ndarray[L] FACTORED_CHOICE`;
    - `plan: tuple[ndarray[L], ndarray[L], ndarray[L]]` (i, j, w);
    - `rows: ndarray[L, width] float32` (a copy);
    - `step`, `encode`, `results`, `tiebreaks: ndarray[L]`;
    - `open: ndarray[L] bool` (step 0 and result 0, and not cut off at `last_step`).
  - `Honest._prepare(p, key, own, weights, last_step, costs) -> LeafRequest`: worlds' policy, foe pairs, every expand chunk and every `leaves.tiebreak` done, rows copied before returning.
  - `Honest._finish(request, values: ndarray[L] float32, own_p, costs, budget=None) -> dict`: `lookahead.table` and `reduce`. Values of non-open leaves are 0.0, and a `SearchError` reproduction records them as 0.0 (documented).
  - `_decision` becomes `_finish(_prepare(...), self._values(request), own_p, costs, budget)`, where `_values` runs today's per-root chunks into `self._rows`.
  - `search.last`: one entry per prepared request, in preparation order.

- [ ] **Step 0: Before the refactor, write `test_two_phase_decision_bytes_pinned`.**
  - The `decision_bytes` digest of three P1-size roots, pinned like `PINNED_TABLE_CONDITIONS`: it skips unless JAX, CPU model, `XLA_FLAGS` and capacity match the hosted CI runner.
  - Record the value on the CI runner from the unrefactored code.
- [ ] **Step 1: Write the failing test** `test_two_phase_matches_decision_in_process`.
  - In one process, for three roots, assert `decision_bytes` and `search.last` tables from `_finish(_prepare(...), ...)` equal those from today's `label_decision`.
  - Preparing root B after root A must leave A's request rows and tiebreaks unchanged (bytes compared).
- [ ] **Step 2: Run it.** `pytest python/tests/test_expert_teacher.py -k two_phase`. Expected: FAIL (AttributeError: `_prepare`).
- [ ] **Step 3: Implement `_prepare`/`_finish`/`_values`.** Move code without changing arithmetic order. `_finish` checks `values.shape == (L,)` and dtype float32.
- [ ] **Step 4: Run it.** Same command. Expected: PASS. Hosted CI runs the pinned digest and `test_honest`.
- [ ] **Step 5: Commit** ("honest: two-phase decision, byte-identical (P2 T2)").

### Task 3: Tick leaf table with incremental dedup and fixed chunks

**Files:**
- Create: `python/duoforge_search/ticks.py`
- Test: `python/tests/test_ticks.py` (NumPy list, fake net)

**Interfaces:**
- Consumes: `LeafRequest` (Task 2; the tests build synthetic ones).
- Produces:
  - `TickTable(width: int, max_rows: int = 196608)`. 196608 rows × 3.4 KB ≈ 0.67 GB; passing that raises `ValueError` naming the limit.
  - `TickTable.add(request) -> ndarray[L] int64`: the unique-row index of each open leaf, -1 for non-open leaves. Rows are deduplicated by their bytes, unique rows keep first-occurrence order, and only unique open rows are stored.
  - `TickTable.evaluate(model, params, rows_buffer: ndarray[capacity, width]) -> ndarray[U] float32`: ceil(U / capacity) calls into the given preallocated buffer (Honest's `_rows`), zero-padding the tail, as `Lookahead.decide` does (`lookahead.py:411-429`).
  - `scatter(index, values) -> ndarray[L] float32`: 0.0 where the index is -1.

- [ ] **Step 1: Write the failing test** `test_tick_dedup_open_filter_and_fixed_chunks`. Use three synthetic requests with duplicate rows; one has refused, terminal and cut-off leaves with nonzero rows. Assert:
  - `U` equals the number of distinct open rows;
  - every call has exactly 1024 rows (fake-model call log);
  - scattered values equal per-request values (this is a wiring check; the real bit gate is Tasks 1, 4 and 5);
  - ticks of 1 request, 1023 open leaves and 2048 open leaves give the same per-request values;
  - non-open is decided by statuses even for nonzero rows;
  - `max_rows=4` raises `ValueError` with "limit".
- [ ] **Step 2: Run it.** `pytest python/tests/test_ticks.py -k dedup_open_filter_and_fixed_chunks`. Expected: FAIL (ImportError: no module `duoforge_search.ticks`).
- [ ] **Step 3: Implement `TickTable` and `scatter`.** Dedup key: `rows.view(np.void)` bytes in a dict to the unique index.
- [ ] **Step 4: Run it.** Same command. Expected: `1 passed`.
- [ ] **Step 5: Commit** ("ticks: incremental leaf dedup, open-leaf filter, fixed chunks (P2 T3)").

### Task 4: `label_tick`, identical per root (after #261)

**Files:**
- Modify: `python/duoforge_search/expert.py`, `python/duoforge_search/EXPERT_TEACHER.md`
- Test: `python/tests/test_expert_teacher.py`

**Interfaces:**
- Consumes: `label_decision`'s arguments (#261), `_prepare`/`_finish` (Task 2), `TickTable`/`scatter` (Task 3).
- Produces:
  - `TickRoot(env, seat, key, raw_action, raw_logp)`;
  - `label_tick(search, roots, tick: Sequence[TickRoot], *, last_step, config, manifest) -> tuple[TeacherDecision, ...]`, results in input order.
  - It queries encoded rows and public records once per tick.
  - Per root, in input order: hypotheses, then `_prepare` of the primary, then (if the audit word selects it) `_prepare` of the K+1 audit on the same worlds and weights, before the next root's hypotheses overwrite them.
  - All requests share one `TickTable`. Sharing primary and audit rows is byte-safe once Task 1 holds; each `WorkLedger` counts solver work, not rows.
  - One evaluate per tick, then every `_finish` with its own ledger. Public refusals and work exhaustion are decided per root.
  - `label_decision` stays as the reference path.

- [ ] **Step 1: Write the failing test** `test_label_tick_bytes_equal_per_root`. Use four P1-size roots with the audit forced. Assert:
  - each root's `decision_bytes` equals `label_decision` for that root;
  - a root with visible sleep stays `PUBLIC_REFUSAL` and the others are unchanged;
  - a tiny budget on one root gives `WORK_EXHAUSTED` there only;
  - permuted tick order gives the same per-root bytes;
  - encoded rows are queried once per tick (patched counter);
  - the audit of root 0 is prepared before root 1's hypotheses (call order log).
- [ ] **Step 2: Run it.** `pytest python/tests/test_expert_teacher.py -k label_tick_bytes_equal_per_root`. Expected: FAIL (AttributeError: `label_tick`).
- [ ] **Step 3: Implement `label_tick`.** Document it in EXPERT_TEACHER.md as the per-tick call.
- [ ] **Step 4: Run it.** Same command. Expected: `1 passed`.
- [ ] **Step 5: Commit** ("expert: label_tick shares a tick's value calls, bytes per root unchanged (P2 T4)").

### Task 5: Measurement and report (owner window)

**Files:**
- Create: `python/duoforge_search/tickbench.py`. The benchmark harness drives lockstep roots through `label_decision` or `label_tick` directly; no collector calls `label_tick` yet.
- Create: `docs/learning/<date>-stage3-p2/README.md` and `aggregates.json` (aggregates and fingerprints only).

- [ ] **Step 1: Row independence on the owner's machine.** `rowprobe --device cpu` and `--device gpu` with params-49333 on real leaf rows, conditions recorded. Any nonzero count: STOP and report.
- [ ] **Step 2: Ablation per device** (CPU, GPU, and the split with policy on CPU and value on GPU):
  - three paths: per root, tick without dedup, tick with dedup;
  - 512 games and a fixed 12 lockstep steps from fixed seeds, capacity 1024, one warm-up and two timed repetitions.
  - Report:
    - decisions/s and valid targets/s;
    - calls and rows per call type (unique, open, padded);
    - host-to-device transfers, peak memory, JIT seconds;
    - CPU core-seconds and GPU-seconds (`duoforge_learn/ledger.py`);
    - the measured duplicate and zero shares (the probe's numbers came from early game phases).
- [ ] **Step 3: Identity.** Repeat-run decision/target digests must be equal per device and condition set, and equal between all three paths on each device. Reference audits agree.
- [ ] **Step 4: Gate (predeclared).**
  - PASS needs identity and ≥1.25× decisions/s of the tick-with-dedup path over the per-root path, in both timed repetitions, on the device chosen for generation.
  - Otherwise STOP with the measured cause. No tuning of capacity, seeds or steps after seeing results.
- [ ] **Step 5: Commit the report** (docs only).

## Out of scope

- Learner v2's planner across games and ticks.
- GPU generation for P1. P1 stays on the frozen CPU path; a device change needs its own owner decision.
- Batching policy and team calls (its own identity gate later).
- The regret router (P3).
- Any change of capacity, K, M or W.
