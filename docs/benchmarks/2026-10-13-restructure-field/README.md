# Restructure 4: field-family helpers

**Result:** 15 existing functions extracted into seven private headers; behavior,
RNG consumption and early-return order preserved. Performance gate: **PASS**.
No PR is opened until HS explicitly releases the slot after the Content collection
PR merges; hosted full CI is pending. Queue: Book #479 → CTS → Content → this PR.

Baseline: `aca58173d389613b6b4a89a95d8b1b5e3fe7b2fa`, **dirty=false**. Measured after source: `d15b13afe6b2418487233b0492ec9abdc5b6bc8c`,
**dirty=false**. All paired results record both commits and dirty status, binary
SHA-256 and runtime manifests. Later report-only commits do not change measured
C inputs. IPO is the shipped Release profile.

## Exact scope and lineage

Extraction commit `d520d013` credits `split from src/combat/turn.c@aca58173`.
It moves 15 unchanged function bodies into `src/combat/field/`, grouped as
weather, terrain access, terrain effects, terrain seeds, shared duration,
side conditions and Trick Room's dragged-entrant speed key. **No file is
renamed**. The header includes remain at existing helper dependency boundaries;
all entry points are private `static inline` in the original translation unit.
Two predicates keep their old byte-equal bodies under private static implementation
names (`dfi_grounded_test`, `dfi_weather_suppression_scan`), with tiny inline
wrappers preserving their original call-site names.

`turn.c`: **12,385 → 12,185 lines (−200)**. Every one of the **266 remaining
function bodies** is byte-equal, including `dfi_get_damage`, `dfi_run_move_body`
and all residual functions. The field setters, Trick Room activation/countdown,
damage rules and residual scheduling stay in their existing large functions.
There is no phase extraction, new dispatch table, predicate replacement,
allocation or generator change. Existing switch/predicate bodies are copied
unchanged. The explicit per-special classification and independent predicate
witness added by #469 remain intact.

| Function | Old location | New location |
|---|---|---|
| `dfi_grounded` | `src/combat/turn.c:197-204@aca58173` | `src/combat/field/terrain.h:14-21` (dfi_grounded_test) |
| `dfi_terrain_field_detail` | `src/combat/turn.c:207-213@aca58173` | `src/combat/field/terrain.h:31-37` (dfi_terrain_field_detail) |
| `dfi_weather_rock` | `src/combat/turn.c:229-241@aca58173` | `src/combat/field/weather.h:10-22` (dfi_weather_rock) |
| `dfi_weather_suppressed` | `src/combat/turn.c:283-292@aca58173` | `src/combat/field/weather.h:30-39` (dfi_weather_suppression_scan) |
| `dfi_field_weather` | `src/combat/turn.c:295-298@aca58173` | `src/combat/field/weather.h:49-52` (dfi_field_weather) |
| `dfi_move_weather` | `src/combat/turn.c:303-309@aca58173` | `src/combat/field/weather.h:57-63` (dfi_move_weather) |
| `dfi_weather_speed_ability` | `src/combat/turn.c:444-453@aca58173` | `src/combat/field/weather.h:69-78` (dfi_weather_speed_ability) |
| `dfi_field_start_turns` | `src/combat/turn.c:247-250@aca58173` | `src/combat/field/duration.h:14-17` (dfi_field_start_turns) |
| `dfi_entrant_speed_key` | `src/combat/turn.c:828-832@aca58173` | `src/combat/field/trick_room.h:15-19` (dfi_entrant_speed_key) |
| `dfi_break_screens` | `src/combat/turn.c:4529-4544@aca58173` | `src/combat/field/side_conditions.h:14-29` (dfi_break_screens) |
| `dfi_side_turns` | `src/combat/turn.c:10590-10597@aca58173` | `src/combat/field/side_conditions.h:31-38` (dfi_side_turns) |
| `dfi_clear_terrain` | `src/combat/turn.c:5564-5577@aca58173` | `src/combat/field/terrain_effects.h:12-25` (dfi_clear_terrain) |
| `dfi_seed_terrain` | `src/combat/turn.c:9916-9931@aca58173` | `src/combat/field/terrain_seeds.h:13-28` (dfi_seed_terrain) |
| `dfi_terrain_seed` | `src/combat/turn.c:9935-9955@aca58173` | `src/combat/field/terrain_seeds.h:32-52` (dfi_terrain_seed) |
| `dfi_terrain_change` | `src/combat/turn.c:9959-9978@aca58173` | `src/combat/field/terrain_seeds.h:56-75` (dfi_terrain_change) |

[source-audit.json](source-audit.json) verifies all moved body hashes and the
remaining whole-turn tokens, excluding only the declared extractions, includes
and relocated `DFI_SIDE_KINDS=4` macro. [extraction-map.json](extraction-map.json)
contains the body hashes and line map, including the two implementation aliases
and the retained inline entry-point names. No assertions, parsing or expected
values are changed. Commit `abb0ade9` updates documentation and one test
**docstring path only**.

## Performance-Gate

Fixed before execution: **32 paired comparisons in each profile**, plus **32
identical-binary comparisons in each profile**. Four series rotate through
four round positions, eight times each. AB/BA order alternates, 16 of each.
Each side executes 1,024 battles per closure pairing, two warmups and three
measured repetitions for both plain/Events: 96 samples per side/workload/series.
CPU affinity 4, GCC 14.2 Release `-O3 -DNDEBUG`, IPO explicitly checked from the
manifest, seeds 20261001/7001, max steps 128. No build or test overlaps these runs.
The outer harness sets affinity; the driver's old literal `affinity: none`
remains visible in its unmodified raw manifest.

Each pair ratio is median(after's three samples) / median(before's three
samples); the result is the median of 32 ratios. Confidence intervals are
20,000 paired-bootstrap medians, seed 20261012, percentile 95%. All samples,
outliers and disturbed flags are retained. The gate checks median time ≤1.02
**or** within the matching identical-binary control's 95% interval; failed
numeric checks are not relabelled. These intervals do not prove an absolute
2% non-regression bound. All four observed medians pass the numerical gate and lie inside their A/A
intervals. The plain-workload confidence intervals extend above +2%; this
report does not certify a true loss below 2%. No causal speedup is claimed.

| Profile | Workload | Median time change | Change 95% CI | A/A median | A/A 95% CI | Numerical ≤2% | Within A/A CI |
|---|---|---:|---|---:|---|---|---|
| ipo | plain | +1.34% | [+0.18%, +5.11%] | +0.32% | [-2.46%, +1.88%] | pass | yes |
| ipo | events | +0.27% | [-1.32%, +1.10%] | +0.38% | [-0.89%, +3.71%] | pass | yes |
| noipo | plain | +0.38% | [-1.10%, +3.96%] | -0.92% | [-3.21%, +0.96%] | pass | yes |
| noipo | events | +0.24% | [-0.78%, +1.90%] | -0.30% | [-2.42%, +0.90%] | pass | yes |

Exact protocol, every pair's code/dirty provenance, all samples, wall/CPU times
and control ratios are in [paired-bench-ipo.json](paired-bench-ipo.json),
[paired-bench-noipo.json](paired-bench-noipo.json),
[control-ipo.json](control-ipo.json) and [control-noipo.json](control-noipo.json).
[bench-verification.json](bench-verification.json) confirms 128 completed pairs,
the fixed order, source/binary hashes and all raw sample counts.
The same baseline file is executed twice for each A/A pair (matching binary
hashes). Record and choice tallies match all four series with zero errors,
truncations or time-limit skips. [matched-bench.py](matched-bench.py) is the
exact reproduction script; adjust filesystem paths, retain protocol values.

## Retained initial result and the inlining repair

Initial measured source `abb0ade98ad5573a708521310416d9d6e7b81589`, dirty=false,
used the same fixed 32-pair/change/control protocol. Its results are retained:
IPO plain −0.47%, IPO Events +2.69%, no-IPO plain +1.17%, no-IPO Events +0.12%.
**IPO Events failed both the numerical and own-control checks**: change 95% CI
[+0.75%,+6.23%], A/A 95% CI [−2.68%,+0.28%]. The original failed gate is not
removed or relabelled by the later measurement.

Disassembly exposed code duplication: IPO bench text 449,253→489,248 bytes,
shared 595,639→631,815; `dfi_get_damage` 25,740→37,002 bytes. Grounding and weather
suppression's small source bodies pull larger type/ability accessor work into
callers when the inline hint is applied transitively. Commit `d15b13af` keeps
the two old predicate bodies under ordinary private static implementation
names and exposes their original names through tiny static inline wrappers.
The code bodies, evaluation/return order and state layout remain unchanged;
no compiler-specific attributes or dispatch mechanism are added.

The repaired IPO artifacts (clean `d15b13af`) have bench text 451,508/shared597,711
bytes, and `dfi_get_damage` again 25,740 bytes. This brings the footprint close to baseline; the
new paired measurements above determine the performance gate, rather than
code size alone. [binary-sizes.json](binary-sizes.json) records all three
clean code epochs, both profiles/artifacts and binary hashes. All original
pair/control data are in
[initial-ipo-change.json](initial-ipo-change.json),
[initial-ipo-control.json](initial-ipo-control.json),
[initial-noipo-change.json](initial-noipo-change.json) and
[initial-noipo-control.json](initial-noipo-control.json).

## Call sites and inlining

Conservative static reachable graphs from public step wrappers and their
internal tape implementation, including compiler clones, direct calls, tail
jumps and cold branch edges. Same-library PLT calls resolve to their own
implementations. Compiler constprop/isra/part/cold/lto_priv suffixes are
normalized. IPO folds the bench's plain/Events wrappers into a common internal
implementation, so its graph is not a separately observed dynamic workload.
These counts are **static call instructions, not invocation counts**.

| Artifact/profile | Graph | Direct call sites before → after | Indirect call sites before → after |
|---|---|---:|---:|
| ipo-bench | common_step | 695 → 700 | 1 → 1 |
| ipo-bench | events | 695 → 700 | 1 → 1 |
| ipo-shared | common_step | 1359 → 1364 | 1 → 1 |
| ipo-shared | events | 1357 → 1362 | 1 → 1 |
| noipo-bench | common_step | 1308 → 1313 | 3 → 3 |
| noipo-bench | events | 1306 → 1311 | 3 → 3 |
| noipo-shared | common_step | 1341 → 1346 | 3 → 3 |
| noipo-shared | events | 1339 → 1344 | 3 → 3 |

All 15 original entry-point interfaces are `static inline`; **none increases its direct call
count** in either profile/artifact. The compiler may keep local outlined
specializations or predicate implementations, including the heavier grounding
and suppression work. Those remain in the same translation unit and
have the same or fewer calls. Other helper definitions disappear by inlining.
The reachable graph has five more static call instructions in each artifact/
profile. They come from expanding terrain seed work into its two callers:
`dfi_boost`, `dfi_symbiosis` and `dfi_use_item_core` have duplicated instruction
sites, while the seed-helper calls disappear. This is a compiler inlining
choice; the source call order and runtime work remain unchanged. The tiny
entry wrappers for grounding/suppression leave no new wrapper call sites;
their original predicate bodies retain the baseline 22 and 26/27 call sites.
There are no new cross-translation-unit field calls and no new exports.

| Original helper/body identity | IPO bench | IPO shared | no-IPO bench | no-IPO shared |
|---|---:|---:|---:|---:|
| `dfi_grounded` | 22 → 22 | 22 → 22 | 22 → 22 | 22 → 22 |
| `dfi_terrain_field_detail` | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| `dfi_weather_rock` | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| `dfi_weather_suppressed` | 26 → 26 | 26 → 26 | 27 → 27 | 27 → 27 |
| `dfi_field_weather` | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| `dfi_move_weather` | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| `dfi_weather_speed_ability` | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| `dfi_field_start_turns` | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| `dfi_entrant_speed_key` | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| `dfi_break_screens` | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| `dfi_side_turns` | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| `dfi_clear_terrain` | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| `dfi_seed_terrain` | 2 → 0 | 2 → 0 | 2 → 0 | 2 → 0 |
| `dfi_terrain_seed` | 2 → 0 | 2 → 0 | 2 → 0 | 2 → 0 |
| `dfi_terrain_change` | 1 → 1 | 1 → 1 | 4 → 4 | 4 → 4 |

The two renamed implementation bodies are normalized to their original names
in this table; actual disassembly names remain in the JSON. The retained inline
wrappers themselves have no definitions/call sites in the binary.
[call-audit.json](call-audit.json) retains per-helper counts, definitions, changed
callee/edge counts, artifacts and source provenance; [call-audit.py](call-audit.py)
implements the traversal. Do not confuse keyword `inline` with a guarantee
that every invocation is inlined.

## P1–P6 against aca58173

- **P1:** **1,410 → 1,410 names**, sorted SHA
  `03f079e72fe9f4f3f24cc2f3319f27c2176c8a3731a260a2d0de1c4c9bcf36dc`.
  Commands, working directories, environments, labels and order are identical
  (only registration backtraces omitted). **210 quick  +31 full +1,151 reference
   +18 slow**. Both before/after pass **218/218 IPO** and **213/213 no-IPO**,
  zero failures, skips or disabled tests. Includes all quick tests plus perft,
  search bench, layout, lint and, with IPO, full Live assembler plus regeneration.
  Full hosted CI is pending PR opening and remains HS's merge gate.
- **P2:** byte-equal before/after in both profiles: **10 variants, 2,584 executions,
  1,129 unique battles, 22,472 steps, 8,458 stops per profile**. Full canonical
  digest JSON SHA
  `9753fed420cbcddceaa7e4de1e77a73fda9195b093e4cf9e98a06140dd6c7dfd`.
  The test-only `--digest-out` covers state, requests, events, RNG use and
  stops; native runner assertions still execute. Full Live assembler **53/53**
  before/after; POOL **11680 equal/563 refused**, four Unburden refusals,
  **162 tracker stops**, exactly main's pins.
- **P3:** both profiles pass **10 positions/24 pinned perft depths**, pins SHA
  `90cb0e55b5aed6d2285953338a736b76b7d46e586993b0c5fccceda2230c7c56`.
- **P4:** both profiles pass search bench, **2 cases/8 roots/7 searched roots**;
  `BENCH_SHA256` unchanged:
  `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798`.
- **P5:** all three `gen_closure --check` modes, tiebreak regeneration,
  independent format pins, `gen_move_handlers --check` pass. **23 generated,
  provenance and pin hashes** unchanged. UNMODELED data-row pins **146 moves,
  18 items, 90 abilities** stay unchanged until step 5.
- **P6:** public `include/duoforge/` diff empty. **238 exports**, type/name
  byte-equal in both profiles, SHA
  `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`.
  **33 layout structs/250 constants**, raw dump byte-equal, SHA
  `0bad5754bb4c85b07bbd99aa54a5700a8f2c82135b4eb75734b9fe86c8a3530e`.
  Negative symbol lookups for all 17 private helpers (the 15 original interfaces plus 2 implementation names) pass in both before/after libraries
  and profiles (68 lookups); no public API promotion.

| Variant | Battles | Before=after SHA256 |
|---|---:|---|
| `duoforge_reference_conformance` | 90 | `620dd6f94faa5fc2751158f062c58edf75f48394aba7a9a49e6bc96bf8f9f271` |
| `duoforge_reference_conformance_pool` | 90 | `8be6753e961e86e6a8dbcb77e053f308ea71c31c12a6c11b5212a954fccf79a6` |
| `duoforge_reference_conformance_pool_data` | 966 | `8fbc168fb2199930340a1fabf4923bce5d2553ede17253bd215b7f1ad5b4d200` |
| `duoforge_reference_conformance_team_c` | 73 | `1acfad0da5393e2095176d094ab2748800b305cfbfee048e04f127a1720c39c5` |
| `duoforge_reference_conformance_team_c_pool` | 73 | `4459b937648f3e470ffee6da4761ce0f3d54b2c19f59906774888844bb515792` |
| `duoforge_reference_tiebreak` | 90 | `b374c2d908d5bd00776a571f7bc6842722f0fb6e6401c9770b3f27001c07e4ea` |
| `duoforge_reference_tiebreak_pool` | 90 | `f0d14608caf783a1f99c79dfb78265e18878aaa139865c7ce3500f10635d41cb` |
| `duoforge_reference_tiebreak_pool_data` | 966 | `9bc7b21e8cfc6994147dcc7843581d2a1a08f63aaf1d9db2417511615cd1049f` |
| `duoforge_reference_tiebreak_team_c` | 73 | `78e1cb58a1fd273b438d99fb9d5db2bdc876b174da5bc73339bc002b2de7fb34` |
| `duoforge_reference_tiebreak_team_c_pool` | 73 | `c63fe2df60c180eff91e1c81d297036b2873a342cc32016dab93ae8165ad913b` |

[proof-summary.json](proof-summary.json) records profile-specific results and
hashes; [live-summary.json](live-summary.json) records the registered Live
suite’s 53 passing methods and unchanged POOL aggregates. [reference-results.json](reference-results.json) includes every public
fixture's digest. No raw state/request/event/replay payload is published.

## Capture correction and compile measurements

The initial no-IPO CTest JSON was captured before the full build and omitted
commands for 84 then-unbuilt test programs. The mismatch was detected by the
strict after comparison. Original snapshots were retained outside the repo;
complete registrations were recollected on the **original clean aca58173**
source with binaries present, then compared with the measured after commit. No command,
comparison field, test or assertion was dropped. Both inventories stay 1,410.
[registration-refresh.json](registration-refresh.json) records this correction.

Compile-only samples use the exact CMake commands, redirected object outputs,
no concurrent local builds/tests, one sample per core/shared/profile. Every
sample names its commit and dirty=false. The initial IPO samples are retained;
its attempt stopped before no-IPO because that cache did not export compile
commands. The cache flag was enabled, then no-IPO measured. No code changed.
[compile-before-ipo.json](compile-before-ipo.json),
[compile-before-noipo.json](compile-before-noipo.json) and
[compile-after.json](compile-after.json) retain all samples. Single compile
measurements are informational and do not establish a speedup/regression.

| Profile | Target | Baseline aca58173 (s) | Initial abb0ade9 (s) | Repaired d15b13af (s) |
|---|---|---:|---:|---:|
| ipo | core | 11.483 | 11.360 | 10.256 |
| ipo | shared | 16.155 | 12.177 | 10.550 |
| noipo | core | 10.187 | 12.061 | 10.630 |
| noipo | shared | 11.779 | 14.069 | 11.558 |

All three columns were measured with dirty=false; these are single isolated samples.

Full incremental builds reused caches and had different pending target counts;
they are not a clean-build comparison.

## Location dependency audit and reproduction

Checked C/Python/CMake/shell/JS/CI/generators/docs for references to every moved
helper and direct `turn.c` line citations. Runtime call sites and CMake source
registration stay unchanged. Active helper source citations in decision 0015,
sleep-reset citations in decision 0066, the content-files spec and one datagen
test docstring now use current paths/function anchors. Historical benchmark
reports and the generated research survey pinned to `cfe18c0` retain their
source references. No parsing, assertions, expected values or CI selections
change. New headers are compiler-tracked private include dependencies.

Use the existing GCC Release profiles with IPO on/off, Python dependencies,
Node 22.23.3 and pinned Showdown
`b2cb775b0616115b775534eaeff50300e1fc81fc`, with `OPENBLAS_NUM_THREADS=1`.
The full sorted inventory is in [test-inventory.txt](test-inventory.txt), and
[exported-symbols.txt](exported-symbols.txt)/[layout.json](layout.json) retain
the frozen public-surface dumps. Compile both profiles before collecting the
CTest registration JSON, so every command is resolved even in a fresh build.
Preserve the original checkout's clean Git state for each phase, copy binaries
outside the repository into `before/` and `after/` with matching provenance,
and then run the paired harness. [proofs.py](proofs.py) records this suite’s
commands and selections; its original pre-build metadata capture requires
the complete-registration refresh noted above on a fresh build.
Run `ctest -N`, `ctest --show-only=json-v1`, the area's existing mechanics/flow/
interactions tests and whole-battle checks; `python tools/restructure/capture_reference.py
. <build> <outside-repo-output>` captures the ten reference variants.
`gen_closure --check`, format pins and `gen_move_handlers --check` verify data.
The report scripts describe this cloud's outside-repo paths; no owner-PC
`machine_lock` is needed here. No trained weights, checkpoints, run directories,
private replay data or live-play logs are committed/published.

Prepared with Codex. HS alone opens the PR window and merges; this branch
never merges any PR and never enables auto-merge.
