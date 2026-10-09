# Stage 3 P2: lockstep leaf batching (M12 search side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** proposal for owner review, 2026-10-09. Docs only. Merging it authorizes Tasks 1 to 4 (code and tests, no run). Task 5's measurements wait for an owner window that does not contend with Learner v2 A/B/training.

**Goal:** One logical tick's teacher decisions share fixed-capacity value calls (leaves deduplicated and only open leaves evaluated), with decisions byte-identical to the per-decision teacher at the same seeds, capacity, device and runtime.

**Architecture:**
- The honest teacher's decision splits into two phases. `prepare` builds worlds and expands leaves; `finish` takes leaf values and reduces.
- A tick collector runs every admitted root's `prepare` and gathers the open leaves in stable decision/cell/world order. It deduplicates byte-equal rows, evaluates them in fixed-capacity chunks with a zero-padded tail, scatters the values back and runs every `finish`.
- Learner v2's collector (the planner across games, spec section 4) calls one tick API instead of `label_decision` per root.

**Tech Stack:** Python/NumPy, JAX policy/value model (CPU and GPU), duoforge C batch API (expand).

**Spec:** [stage-3 design](../specs/2026-10-05-m12-expert-iteration-design.md) section 4 (P2), [decision 0024](../../decisions/0024-expert-iteration.md), [P1 plan](2026-10-08-stage3-p1-pilot.md), [P0 report](../../learning/2026-10-08-stage3-p0/README.md) (fixed-shape inference curve), teacher contract `python/duoforge_search/EXPERT_TEACHER.md` (#261).

## Global Constraints

- Collect all leaves of a synchronized step in stable decision/cell/world order.
- Policy/team/value calls use fixed capacities and shapes, padded/masked tail chunks and zero padding.
- Finish before actors advance. No async queues, no timeout flush, no active-count-sized calls.
- Pin the parallel-game count (512), chunk order, runtime and shapes. Value capacity stays 1024. P0 measured that changing capacity changes value bits (GPU at ≥256, CPU at ≥4096).
- Repeat runs must give byte-identical decisions and targets at identical seeds, capacity, device and runtime, and they must agree with the reference audits. If reshaping changes float bits or targets, it is not pure performance: fix the layout or request a separately classified change.
- No CPU/GPU cross-device bit claim.
- Preallocate buffers outside battle hot paths. No routing or pruning changes. Learner v2 owns the planner.
- Stop on any identity failure or no throughput gain.
- Real worlds, tables, checkpoints and measurement outputs stay outside the repository (`refuse_repository`).
- Runs only in owner-approved windows. This week: code and tests only.

## Inputs already measured

- **P0 (inference curve):**
  - value call at capacity 1024: 31.03 ms on CPU, 7.37 ms on GPU through the host, 3.00 ms resident;
  - CPU network time is about 39 of the 50 ms per searched decision;
  - first-64-row bits change with capacity.
- **HauptSession probe** (params-49333, X, K = M = 8, S = 16, capacity 1024, 64 games × 12 steps, 497 value calls):
  - only 47.9% of the nonzero rows within a call are unique;
  - 21.5% of capacity rows are all-zero (terminal leaves and padding);
  - unique real rows are 37.6% of capacity, so deduplication plus skipping non-open leaves cuts network rows about 2.7×;
  - no row repeats across calls, so per-tick dedup suffices and no global cache is needed.
- **C3 review:** each label re-queries every environment's encoded rows and public records (about 3 ms at 512 environments). One query per tick removes it.
- **Not measured yet:** whether a row's value bits at fixed capacity depend on its position in the call or on the other rows. Every byte-identity claim below depends on that measurement (Task 1).

## Review Focus

1. **Row position or neighbours change value bits at a fixed shape** (GEMM tail kernels, XLA fusion). Expected: Task 1 detects it on CPU in CI and on GPU privately, and P2 stops for reclassification instead of shipping different labels.
2. **A leaf the table ignores is skipped but its status was misread** (refused vs open, cut-off at `last_step`). Expected: skipping is decided only from the engine's step/result statuses and the cut-off flag, never from row content. Task 3 tests a cut-off tick.
3. **One root of the tick refuses publicly or exhausts its work budget.** Expected: that decision returns its fallback; the other roots' bytes do not change (Task 4).
4. **Ticks of different sizes** (1 root, 1023 open leaves, an exact multiple of 1024). Expected: the same per-root bytes; the tail chunk is zero-padded (Task 3).
5. **The audit runs inside a batched tick.** Expected: audit leaves never share a dedup table with primary leaves and are charged to their own ledger; the primary label bytes are unchanged (Task 4).

---

### Task 1: Value rows independent of position and neighbours (contract probe)

**Files:**
- Create: `python/tests/test_value_rows.py` (JAX list in `tests/CMakeLists.txt`)
- Create: `python/duoforge_search/rowprobe.py` (the private GPU probe CLI only)

**Interfaces:**
- Produces: `row_independence(model, params, rows: ndarray[N, width], capacity: int, seed: int) -> dict`, with keys `position_bits`, `neighbour_bits`, `padding_bits`: the number of rows whose float32 value bits differ when the row moves within the call, when the other rows change, or when the tail is zero-padded rather than filled.

- [ ] **Step 1: Write the failing test** `test_value_rows_position_and_neighbour_independent`.
  - Use the v2 S model with `PRNGKey(7)` on CPU and capacity 1024.
  - Take 300 encoded leaf rows from reference setups.
  - Assert all three counts are 0 after a seeded permutation, after random neighbours and after a zero-padded tail.
- [ ] **Step 2: Run it.** `python -m unittest python.tests.test_value_rows -v` (JAX). Expected: ERROR, no module `duoforge_search.rowprobe`.
- [ ] **Step 3: Implement `row_independence`.**
  - Evaluate each configuration with one call at the fixed capacity.
  - Compare per-row float32 bit patterns with `view(np.uint32)`.
  - No tolerance anywhere.
- [ ] **Step 4: Run it.**
  - PASS: the CPU contract holds, so continue.
  - FAIL: STOP P2 and report the counts; this is the reclassification case of the spec.
- [ ] **Step 5: Implement the private probe.** `python -m duoforge_search.rowprobe --checkpoint PRIVATE --device gpu --out PRIVATE` runs the same three checks on real leaf rows with params-49333 (owner window, Task 5).
- [ ] **Step 6: Commit** ("value rows: position/neighbour/padding bit independence probe (P2 T1)").

### Task 2: Two-phase teacher decision, byte-identical

**Files:**
- Modify: `python/duoforge_search/honest.py` (`_decision`); `python/duoforge_search/expert.py` (`label_decision`)
- Test: `python/tests/test_expert_teacher.py`

**Interfaces:**
- Produces:
  - `Honest._prepare(p, key, own, weights, last_step, costs) -> LeafRequest(rows: ndarray[L, width] float32, open: ndarray[L] bool, statuses: dict, plan: tuple, foe_pairs: ndarray, qs: ndarray, weights: ndarray)`;
  - `Honest._finish(request, values: ndarray[L] float32, budget) -> dict` (the record `_decision` returns today);
  - `_decision` becomes `_finish(_prepare(...), value(request))`.
- Consumes: the `expert.label_decision` signature from #261, unchanged.

- [ ] **Step 1: Write the failing test** `test_two_phase_decision_bytes_equal`.
  - Run the existing `test_tau_execution_and_explicit_fallbacks` setup.
  - Assert that `decision_bytes` of `label_decision` is equal before and after (golden digest of three games recorded on main), and that `search.last` tables are equal.
- [ ] **Step 2: Run it.** Expected: FAIL, `_prepare` missing.
- [ ] **Step 3: Implement `_prepare`/`_finish`.** Move code without changing arithmetic order. `_finish` checks `values.shape == (L,)` and dtype float32.
- [ ] **Step 4: Run it**, plus `test_honest` (JAX, hosted CI) and `test_expert_teacher`. Expected: PASS, golden digests unchanged.
- [ ] **Step 5: Commit** ("honest: two-phase decision, byte-identical (P2 T2)").

### Task 3: Tick leaf collector with dedup and open-leaf filter

**Files:**
- Create: `python/duoforge_search/ticks.py`
- Test: `python/tests/test_ticks.py` (python list, NumPy fake net; a JAX variant in the learn list)

**Interfaces:**
- Consumes: `LeafRequest` (Task 2).
- Produces:
  - `collect(requests: Sequence[LeafRequest]) -> TickLeaves(unique: ndarray[U, width] float32, index: tuple[ndarray[L_d] int64, ...])`. `index[d][l]` is the unique-row position of open leaf `l` of decision `d`, or -1 when the leaf is not open. Unique rows keep their first-occurrence order (decision, then cell, then world).
  - `evaluate(model, params, unique, capacity) -> ndarray[U] float32`: ceil(U / capacity) calls of exactly `capacity` rows, the tail zero-padded, buffers preallocated once per capacity.
  - `scatter(tick, values) -> tuple[ndarray[L_d] float32, ...]`: open leaves get their value, non-open leaves 0.0 (the table never reads them).
- [ ] **Step 1: Write the failing test** `test_tick_dedup_open_filter_and_fixed_chunks`.
  - Three synthetic requests share duplicate rows; one has refused, terminal and cut-off leaves.
  - Assert:
    - `U` equals the number of distinct open rows;
    - every call has exactly 1024 rows (count the fake model's calls);
    - scattered values equal the per-decision values bit for bit (fake net);
    - a tick of 1, of 1023 open leaves and of 2048 open leaves give the same per-decision values;
    - a non-open leaf is chosen from the statuses even when its row is nonzero.
- [ ] **Step 2: Run it.** Expected: ERROR, no module `ticks`.
- [ ] **Step 3: Implement it.** Dedup key: the row's bytes (`rows.view(np.void)`). Open: the request's `open` mask, from step status, result and the cut-off flag.
- [ ] **Step 4: Run it.** Expected: PASS.
- [ ] **Step 5: Commit** ("ticks: per-tick leaf dedup, open-leaf filter, fixed chunks (P2 T3)").

### Task 4: Tick API for the collector, identity against per-root labels

**Files:**
- Modify: `python/duoforge_search/expert.py`, `python/duoforge_search/EXPERT_TEACHER.md`
- Test: `python/tests/test_expert_teacher.py`

**Interfaces:**
- Consumes: `label_decision` arguments per root (#261), `collect`/`evaluate`/`scatter` (Task 3).
- Produces: `label_tick(search, roots, roots_to_label: Sequence[TickRoot], *, last_step, config, manifest) -> tuple[TeacherDecision, ...]`, where `TickRoot(env, seat, key, raw_action, raw_logp)` and results come back in input order.
  - It queries roots and public records once per tick.
  - Each root's fallbacks (`PUBLIC_REFUSAL`, `WORK_EXHAUSTED`) are decided per root.
  - Audits run as a second collect with their own ledgers.
- [ ] **Step 1: Write the failing test** `test_label_tick_bytes_equal_per_root`. With three or four roots at P1 sizes and the audit forced:
  - assert `decision_bytes` per root equal `label_decision` per root;
  - one root with visible sleep stays `PUBLIC_REFUSAL` and the others are unchanged;
  - a tiny budget on one root gives `WORK_EXHAUSTED` there only;
  - permuted root order gives the same per-root bytes;
  - roots query encoded rows once (patched counter).
- [ ] **Step 2: Run it.** Expected: FAIL, `label_tick` missing.
- [ ] **Step 3: Implement `label_tick`.** Document it in EXPERT_TEACHER.md as the collector's per-tick call. `label_decision` stays as the reference path.
- [ ] **Step 4: Run it.** Expected: PASS.
- [ ] **Step 5: Commit** ("expert: label_tick shares a tick's value calls, bytes per root unchanged (P2 T4)").

### Task 5: Measurement and report (owner window)

**Files:**
- Create: `docs/learning/<date>-stage3-p2/README.md` and `aggregates.json` (aggregates and fingerprints only)

- [ ] **Step 1: GPU row independence.** Run Task 1's `rowprobe` with params-49333 on real leaf rows.
  - Any nonzero count: STOP and write the report (reclassification needed).
- [ ] **Step 2: Paired measurement.** Per-root `label_decision` vs `label_tick`, on CPU and on GPU, with 512 games, fixed seeds, capacity 1024, one warm-up and two timed repetitions. Report:
  - decisions/s and valid targets/s;
  - value/policy calls and rows (unique, open, padded);
  - host-to-device transfers, peak memory, JIT seconds;
  - CPU core-seconds and GPU-seconds (`duoforge_learn/ledger.py`).
- [ ] **Step 3: Identity.** Repeat-run decision/target digests must be equal per device, and equal between the per-root and the tick path on each device. Reference audits agree.
- [ ] **Step 4: Gate.**
  - PASS needs identity and a throughput gain on the device chosen for generation.
  - Otherwise STOP with the measured cause; no tuning of capacity or seeds after seeing results.
- [ ] **Step 5: Commit the report** (docs only).

## Out of scope

- Learner v2's planner across games and ticks.
- GPU teacher generation for P1. P1 stays on the CPU path that was frozen; switching devices needs its own owner decision.
- The regret router (P3).
- Any change of capacity, K, M or W.
