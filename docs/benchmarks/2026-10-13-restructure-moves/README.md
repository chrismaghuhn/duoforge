# Restructure 4: Moves — Events calls and matched controls

The proposed call-out explanation is not supported by `objdump`: the No-IPO
Events graph has **1,306 -> 1,306** static direct call instructions in the bench
and **1,339 -> 1,339** in the shared library. Every moved/new helper has **0 -> 0**
calls and no out-of-line definition or tail jump. They already live as private
`static inline` functions in headers. This follow-up changes no engine code.

All fresh local functional proofs pass. Baseline is **fbc8b24f**, current compiled
source **3affb183**, branch `restructure/4-moves`. The immutable baseline evidence
is reused unchanged; the after suites and both native captures were rerun.
**No PR opened:** HS must explicitly approve opening; hosted CI is pending.

**Bench result:** three medians satisfy the +2% numeric check. No-IPO/events is
**+2.42%**, so its numeric check **FAILS**, while it is inside the identical-binary
control's 95% band **[-3.62%, +6.89%]**. All four satisfy the user's stated
“≤+2% or within own scatter” criterion when these two checks are kept separate.
This is **not** proof of an absolute ≤2% performance loss. No sample is excluded,
and no numeric failure is relabelled as a numeric pass.

## Static Events call comparison

[events-call-audit.json](events-call-audit.json) enumerates counts per target,
all changed caller/callee edges (none), helper counts and indirect call sites.
The traversal starts at `duoforge_battle_step_events` and
`dfi_battle_step_events_tape`, includes direct calls, tail jumps, cold blocks and
branch edges, and resolves same-library PLT calls to their own definitions.
It is a conservative static reachable graph, **not dynamic invocation counts**.
Bench: **174 -> 174** reachable functions; shared: **187 -> 187**.
Indirect `call` instructions: **3 -> 3** in each artifact, unchanged.
No callee's call count and no normalized caller/callee edge count increased.
Compiler `.constprop`, `.isra`, `.part` and `.cold` suffixes are handled explicitly.

| Helper | Before No-IPO calls | After No-IPO calls |
|---|---:|---:|
| `dfi_move_first_turn_only` | 0 | 0 |
| `dfi_move_power_by_weight` | 0 | 0 |
| `dfi_weight_power` | 0 | 0 |
| `dfi_heavy_slam_power` | 0 | 0 |
| `dfi_hard_press_power` | 0 | 0 |
| `dfi_multihit_count` | 0 | 0 |
| `dfi_move_hits` | 0 | 0 |
| `dfi_multiaccuracy_proven` | 0 | 0 |
| `dfi_power_trip_positive_stages` | 0 | 0 |
| `dfi_tri_attack_chance_hit` | 0 | 0 |
| `dfi_is_ohko` | 0 | 0 |
| `dfi_beat_up_hits` | 0 | 0 |
| `dfi_move_special_has_handler` | 0 | 0 |
| `dfi_move_special_status_hit` | 0 | 0 |

[inlining.json](inlining.json) also verifies all 14 helpers in **all eight**
before/after × IPO on/off × bench/shared binaries: zero direct calls, zero
out-of-line definitions and zero tail jumps. No helper became a cross-file
call, so there is no source correction to make for that hypothesis.

## Paired measurements and identical-binary controls

The protocol was fixed before execution: **32 pairs for each of four series**:
IPO change, IPO A/A, no-IPO change, no-IPO A/A. The four series rotate through
four positions each round, **eight times in each position**. Change pairs run AB
on odd rounds and BA on even rounds (**16 of each**). Every A/A pair executes
exactly the same baseline file twice; its two SHA-256 values are equal.

Every run uses **1,024 battles per closure pairing**, **three timed repetitions**
per workload and side (**96 samples per side/workload/series**), **two warmups**,
CPU affinity **4**, seeds **20261001 / 7001**, max steps **128**, and both
`step,events` workloads. Compiler: GCC **14.2.0**, Release `-O3 -DNDEBUG`;
IPO is checked from each manifest. No local build or test overlaps these runs.
The driver's old raw `affinity: none` string is preserved; the outer harness
actually sets child affinity, recorded in `protocol.cpu_affinity`.

Every record and choice tally agrees across all four series:
**4,096 battles, 73,337 steps, 53,625 turns,
131,721 side decisions**, zero errors/truncations/skipped runs.
Each pair uses median(after's three samples) / median(before's three samples);
the reported value is the median of these paired ratios. The 95% intervals use
**20,000 paired-resample medians**, fixed seed **20261012**. Full ranges,
absolute before/after medians, all individual wall/CPU samples and disturbed
flags remain in the JSON. The additional round-matched change/A-A ratios and
intervals are reported separately; they do not replace the primary measurements.

| IPO | Workload | Median time change | Change 95% CI | A/A median change | A/A 95% CI | Numeric ≤+2% | Inside A/A CI |
|---|---|---:|---|---:|---|---|---|
| on | plain | -1.33% | [-4.46%, +1.41%] | -0.39% | [-3.71%, +2.55%] | pass | yes |
| on | events | +1.48% | [-3.43%, +2.56%] | -1.28% | [-3.57%, +1.42%] | pass | no |
| off | plain | +1.51% | [-0.82%, +2.44%] | +0.25% | [-1.30%, +2.42%] | pass | yes |
| off | events | +2.42% | [-0.96%, +5.93%] | +0.09% | [-3.62%, +6.89%] | FAIL | yes |

The numeric 1.02 threshold is unchanged. The separate own-scatter check asks
whether the observed change median lies within the matching A/A 95% interval.
Large A/A outliers demonstrate measurement variation even with no code change.
These intervals cannot statistically establish a hard 2% non-regression bound.
There is no causal speedup claim and no change to tests, timeouts or CI selection.

Raw series: [IPO change](paired-bench-ipo.json), [no-IPO change](paired-bench-noipo.json),
[IPO A/A](paired-bench-control32-ipo.json), [no-IPO A/A](paired-bench-control32-noipo.json).

## P1–P6 against fbc8b24f

- **P1:** **1,409 before = 1,409 after**, sorted inventory SHA-256
  `43e1460e9916439235c3012548241aecf538a6d985bcf9c5a42c349ee36756fe`.
  Full CTest ordering, names, commands, working directories, environments and
  labels compare equal, excluding registration backtraces only. Tiers:
  **209 quick + 31 full + 1,151 reference + 18 slow**. Fresh after suites:
  **62/62 IPO**, **57/57 no-IPO**, zero failures/skips/disabled. Includes all
  **33 Moves tests**, mixed G33, layout, model pins, sleep/view/clone regressions,
  smogon_sets/live_cts and lint/hygiene. Recorded main baseline: **40/40 IPO**,
  **39/39 no-IPO** and **12/12 related checks in each profile**; reused unchanged.
  Full hosted CI waits for PR opening and remains HS's merge gate.
- **P2:** both fresh after captures equal both recorded baseline captures,
  **10 variants / 2,584 executions / 1,129 unique battles / 22,472 steps /
  8,458 stops per profile**, full canonical JSON SHA-256
  `9753fed420cbcddceaa7e4de1e77a73fda9195b093e4cf9e98a06140dd6c7dfd`.
  `capture_reference.py` invokes the test-only `--digest-out`, covering state,
  requests, events, RNG use and stops; original runner assertions execute.
  Live **53/53** rerun with IPO: **11680 equal / 563 refused**, four Unburden
  refusals, **162 tracker stops**. [live-summary.json](live-summary.json).
- **P3:** both profiles pass **10 perft positions / 24 pinned depths**;
  pins SHA `90cb0e55b5aed6d2285953338a736b76b7d46e586993b0c5fccceda2230c7c56`.
- **P4:** both profiles pass **2 cases / 8 roots / 7 searched roots**;
  `BENCH_SHA256` remains
  `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798`.
- **P5:** all three `gen_closure --check` modes, tiebreak regeneration, independent
  format pins and `gen_move_handlers.py --check` pass. **22 existing source hashes**
  unchanged. New generated table SHA
  `beb77f26a35314b1ef87e1dd1975f325ad95d8c66a4845b77c43ce1b550e9d16`.
  UNMODELED data-row pins **146 moves / 18 items / 90 abilities** stay until step 5.
- **P6:** public header diff empty, **238 exports** byte-equal in both modes,
  normalized type/name SHA
  `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`.
  **33 layout structs / 250 constants** equal, canonical SHA
  `2dead3e584403acac03ccc90926c7590593776242c089777b4e0c74a9b215395`;
  raw dump bytes also equal. **16 negative symbol lookups** pass; layout suite
  **6 -> 7 cases**, existing checks retained.

The independent old-predicate test still compares every **122 defined specials
and all 256 uint8 storage values**, plus UINT32_MAX: **2,098 checks**, zero failures
(original **1,581 retained**), **96 late handlers / 26 excluded** and
**18 own-status hits / 104 excluded**. Datagen suite **147 -> 151** cases.
Fresh isolated mutation control passes; all three wrong-table mutants are caught.
No committed generated file is hand-edited. [mutation-controls.json](mutation-controls.json).

| Variant | Battles | Before = after SHA-256 |
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

## Source moves, lineage and dependency audit

Pure `git mv` commit **3aa2ac7d** contains five 100% renames only; separate
split commit **1df05170** credits source `move_rules.h@657dae45` and
`turn.c@657dae45`. Guard commit **75c77c7a** adds the generated phase table.

| Old path | New path | Grouping |
|---|---|---|
| `src/combat/move_rules.h` | `src/combat/moves/families.h` | first_turn_only.h, weight_power.h, hp_power.h |
| `src/combat/multihit_count.h` | `src/combat/moves/multihit.h` | unchanged count + unchanged dfi_move_hits |
| `src/combat/multiaccuracy.h` | `src/combat/moves/multiaccuracy.h` | unchanged |
| `src/combat/power_trip.h` | `src/combat/moves/power_trip.h` | unchanged |
| `src/combat/secondary_rolls.h` | `src/combat/moves/tri_attack.h` | unchanged |

| Function | Old location @fbc8b24f | New location |
|---|---|---|
| `dfi_move_first_turn_only` | `src/combat/move_rules.h:19-22` | `src/combat/moves/first_turn_only.h:14-17` |
| `dfi_move_power_by_weight` | `src/combat/move_rules.h:27-30` | `src/combat/moves/weight_power.h:12-15` |
| `dfi_weight_power` | `src/combat/move_rules.h:32-40` | `src/combat/moves/weight_power.h:17-25` |
| `dfi_heavy_slam_power` | `src/combat/move_rules.h:44-53` | `src/combat/moves/weight_power.h:29-38` |
| `dfi_hard_press_power` | `src/combat/move_rules.h:57-62` | `src/combat/moves/hp_power.h:11-16` |
| `dfi_multihit_count` | `src/combat/multihit_count.h:12-16` | `src/combat/moves/multihit.h:14-18` |
| `dfi_move_hits` | `src/combat/turn.c:6047-6054` | `src/combat/moves/multihit.h:22-29` |
| `dfi_multiaccuracy_proven` | `src/combat/multiaccuracy.h:19-22` | `src/combat/moves/multiaccuracy.h:19-22` |
| `dfi_power_trip_positive_stages` | `src/combat/power_trip.h:16-25` | `src/combat/moves/power_trip.h:16-25` |
| `dfi_tri_attack_chance_hit` | `src/combat/secondary_rolls.h:14-17` | `src/combat/moves/tri_attack.h:14-17` |
| `dfi_is_ohko` | `src/combat/turn.c:1561-1564` | `src/combat/moves/ohko.h:12-15` |
| `dfi_beat_up_hits` | `src/combat/turn.c:6098-6116` | `src/combat/moves/beat_up.h:14-32` |

All **12 original bodies** and the entire `dfi_get_damage` body are byte-equal.
[merge-audit.json](merge-audit.json) compares whole-turn tokens to updated main,
except the three declared moves, include paths and two equivalent predicates.
`turn.c` remains **12,470 -> 12,385 lines (-85)**. No new translation unit,
allocation, hook mask, function-pointer dispatch, CMake entry, public API or ABI.

The special writer is separate from `move_handler_source.py`, which reads the
existing generator's frozen `SPECIAL_IDS_P`/`SPECIAL_POOL` lists. CF1 switches
only this reader to entry files while keeping output byte-identical. Its table
bits describe **phase eligibility**, not support marks: early-returning effects
can have false late-handler rows. Source eligibility and effect/RNG order stay
unchanged. The frozen predicate witness is independent and never regenerated
from these annotations.

Location audit covers C, Python, CMake, shell, JS, CI, generators and docs.
Active includes and citations were adjusted in turn/request, six tests,
decisions 0015/0048 and the Dragon Darts summary. Historical source-revision
citations remain frozen. No later source-location change is needed by this
follow-up. No assertions or expected values are removed or changed.

## Reproduction and retained measurements

Use Node **22.23.3**, pinned Showdown
**b2cb775b0616115b775534eaeff50300e1fc81fc**, CI's Python dependencies,
`OPENBLAS_NUM_THREADS=1`, and separate GCC Release builds with IPO on/off.
Rebuild the shared library, Moves tests, layouts, bench, all ten reference
runners and **duoforge_diff_runner** before the after proofs.

```sh
ctest --test-dir <build> -N
ctest --test-dir <build> --show-only=json-v1
ctest --test-dir <build> -L '^moves$' --output-on-failure
python tools/datagen/gen_move_handlers.py --check
python tools/restructure/capture_reference.py . <build> <outside-repo-output>
objdump -d <before-noipo-bench> > <outside-repo-baseline>/bench-noipo-objdump.txt
objdump -d <after-noipo-bench> > <outside-repo-after>/bench-noipo-objdump.txt
```

[matched-bench.py](matched-bench.py) is the exact outside-repo measurement script;
[events-calls.py](events-calls.py) is the exact static traversal. Their path
constants describe this environment's immutable baseline and after copies;
change paths to reproduce in another workspace, preserve protocol values.
The perft/BENCH global pins and generated output are not edited for measurement.

[PREVIOUS_3AFFB183.md](PREVIOUS_3AFFB183.md) preserves the preceding full report:
original 30-pair/512-battle measurements, 16-pair/512-battle self-control and
16-pair/2048-battle follow-up, including every failed gate. Its former primary
JSONs are retained as [long IPO](paired-bench-long16-ipo.json) and
[long no-IPO](paired-bench-long16-noipo.json). The previous short runs and
self-control remain at their original filenames. Nothing is discarded to obtain
a passing measurement. Previous single compile-only core/shared build timings
are retained, **not freshly remeasured in this call-audit follow-up**, because
engine source is unchanged. [compile-times.json](compile-times.json).

Pre-existing `BulletFlag` cases after `unittest.main()` remain a separate audit
finding; the new four datagen cases are before it and demonstrably run. No
trained weights, checkpoints, replay payloads, live logs or run directories are
published. Reports contain public fixture names, hashes, code paths and timing
aggregates/samples only. No code/security blocker was found. HS approves opening,
reviews and merges; this branch never merges a PR or enables auto-merge.


## HS review follow-up on PR #469

The C extraction is limited to **three functions from `turn.c`**:
`dfi_is_ohko`, `dfi_move_hits`, and `dfi_beat_up_hits`. The other source moves
are the five header renames followed by private header grouping. The move
body is not split into phases in this PR.

The generator now requires every special to belong to **exactly one explicit
phase class**: late handler (96), before guard (23), legacy data (2), or
unsupported (1). It rejects missing or overlapping classes with the special's
name, rejects unknown names in the annotations, and retains the independent
old-predicate witness. No new special is admitted by an exclusion default.

Three new regression tests fail on the reviewed generator and pass after the
fix: a new mapped special must abort generation by name without writing a
header; overlapping classes must fail by name; removing a classification
must not turn an early handler into a late handler. The direct generator
suite is now **154/154** (the prior 151 retained). Regeneration followed by
`--check` is byte-equal to the reviewed header, SHA-256
`beb77f26a35314b1ef87e1dd1975f325ad95d8c66a4845b77c43ce1b550e9d16`.

Fresh follow-up checks: **33/33 Moves tests with IPO**, **33/33 without IPO**,
plus **6/6** generator/mixed-G33/lint/hygiene checks. All **1,409** CTest names
and runtime properties remain identical. Compiled C inputs, public headers,
and generated output are unchanged from `f75283ae`; the preceding P2–P6,
call audit and paired performance measurements are retained with their
original provenance, rather than described as new measurements.

The content-files spec now names the generated phase tables, and its old
move-gate line reference and decision 0066's sleep/move-gate references use
function names. The PR body records this narrower scope and the review fix.
Full hosted CI must pass on the new head; HS alone merges.
