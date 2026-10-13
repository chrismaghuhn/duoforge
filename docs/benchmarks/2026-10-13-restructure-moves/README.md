# Restructure step 4: move families and generated special guards

Existing shared move rules now live under `src/combat/moves/`, named by family:
first-turn-only, weight power, HP power, multihit, multiaccuracy, Power Trip and
Tri Attack. The bounded Beat Up preparation and OHKO classifier move out of
`turn.c` too. Twelve original function bodies are byte-identical; all hot helpers
are private `static inline`. `dfi_get_damage`'s entire body is byte-identical.
No new translation unit, CMake source entry, public API, hook mask or function
pointer dispatch. The turn keeps every invocation, effect order and RNG draw.
`turn.c` shrinks **12,443 -> 12,358 lines (-85)**.

Baseline **657dae45**, compiled source **75c77c7a**, branch `restructure/4-moves`.
Later commits only fix source citations and add documentation/evidence. **No PR
opened:** HS must explicitly release the window, regardless of `gh pr list`.
Lane A (#442) and CTS have priority. Merge current main without rebase immediately
before opening and refresh proofs affected by that merge. Hosted CI is pending;
its complete matrix and RNG remain HS's merge gate.

## Source lineage and location audit

Pure `git mv` commit **3aa2ac7d** contains these five 100% renames and nothing else:

| Old path | New path after the move | Subsequent grouping |
|---|---|---|
| `src/combat/move_rules.h` | `src/combat/moves/families.h` | umbrella; first_turn_only.h, weight_power.h, hp_power.h |
| `src/combat/multihit_count.h` | `src/combat/moves/multihit.h` | adds the unchanged dfi_move_hits body |
| `src/combat/multiaccuracy.h` | `src/combat/moves/multiaccuracy.h` | unchanged |
| `src/combat/power_trip.h` | `src/combat/moves/power_trip.h` | unchanged |
| `src/combat/secondary_rolls.h` | `src/combat/moves/tri_attack.h` | unchanged |

Split commit **1df05170** credits `split from src/combat/move_rules.h@657dae45`
and `src/combat/turn.c@657dae45`; guard commit **75c77c7a** credits the same turn
baseline. [function-extractions.json](function-extractions.json) maps all twelve
byte-identical bodies:

| Function | Old location @657dae45 | New location |
|---|---|---|
| `dfi_move_first_turn_only` | `src/combat/move_rules.h:19-22` | `src/combat/moves/first_turn_only.h:14-17` |
| `dfi_move_power_by_weight` | `src/combat/move_rules.h:27-30` | `src/combat/moves/weight_power.h:12-15` |
| `dfi_weight_power` | `src/combat/move_rules.h:32-40` | `src/combat/moves/weight_power.h:17-25` |
| `dfi_heavy_slam_power` | `src/combat/move_rules.h:44-53` | `src/combat/moves/weight_power.h:29-38` |
| `dfi_hard_press_power` | `src/combat/move_rules.h:57-62` | `src/combat/moves/hp_power.h:11-16` |
| `dfi_multihit_count` | `src/combat/multihit_count.h:12-16` | `src/combat/moves/multihit.h:14-18` |
| `dfi_move_hits` | `src/combat/turn.c:6026-6033` | `src/combat/moves/multihit.h:22-29` |
| `dfi_multiaccuracy_proven` | `src/combat/multiaccuracy.h:19-22` | `src/combat/moves/multiaccuracy.h:19-22` |
| `dfi_power_trip_positive_stages` | `src/combat/power_trip.h:16-25` | `src/combat/moves/power_trip.h:16-25` |
| `dfi_tri_attack_chance_hit` | `src/combat/secondary_rolls.h:14-17` | `src/combat/moves/tri_attack.h:14-17` |
| `dfi_is_ohko` | `src/combat/turn.c:1561-1564` | `src/combat/moves/ohko.h:12-15` |
| `dfi_beat_up_hits` | `src/combat/turn.c:6077-6095` | `src/combat/moves/beat_up.h:14-32` |

Location audit covers C/C++, Python, CMake, shell, CI workflows, JS, generators
and documentation. Active source paths fixed in turn/request, six C tests,
decision 0015, decision 0048 and the Dragon Darts source summary. Test files,
names, commands, working directories and environments are unchanged; no assertion
was removed or adjusted. Historical reports/research with an explicit old source
revision and the content spec's ca17e507 measurement retain their frozen citations.
A historical G54 mutation filename now also points to its current file.

## Generated special guard: exact phase semantics

`tools/datagen/move_handler_source.py` reads the existing `SPECIAL_IDS_P` and
`SPECIAL_POOL` lists and annotates existing phase ownership. The writer
`tools/datagen/gen_move_handlers.py` consumes `(name, value, hit_guard,
status_hit)` rows and emits `src/combat/generated/move_handlers.h`. CF1 replaces
**only this reader**, retaining the row schema and byte-identical writer output.
The generated artifact is marked linguist-generated and never hand-edited.

The late guard at old `turn.c:8085-8128` becomes
`dfi_move_special_has_handler`; the neighboring generic-status list at old
`turn.c:8060-8068` becomes `dfi_move_special_status_hit`. This migrates two pure
eligibility predicates, without splitting a second large execution phase or
moving the Damage/Hit loop. Other status/boost/forced-switch/heal conditions
stay in their original positions. In particular these are **not overall support
marks**: 23 specials return before the late guard; SCALD/RECOVER are unused
legacy ids; UNMODELED remains refused. The late table preserves **96 true / 26
false** rows, while the own-status-hit table preserves **18 true / 104 false**.
All **122 existing ids** have generated compile-time guards against their old
values. Unknown ids retain the same invariant failure; no new handler is enabled.

`tests/support/special_predicates.h` is an independent, hand-frozen copy of the
old conditions. It is never regenerated from the new annotations. The existing
**quick-tier** `duoforge.combat.move_rules` compares each table to its old witness
for **all 122 defined specials and all 256 uint8_t storage values**, plus an
out-of-range UINT32_MAX boundary. Original **1,581 C checks** remain; now **2,098
checks**, zero failures. [mutation-controls.json](mutation-controls.json): the
unmodified control passes, all three injected table mistakes are caught (remove
Grass Knot, wrongly bypass Fake Out, permit UNMODELED). Mutants use isolated
outside-repository headers and leave committed output untouched.

The existing quick `duoforge.data.gen_closure_refusals` suite runs generator
`--check` and rejects missing/stale output and malformed rows. **147 original
Python cases -> 151**, with no altered assertions; no new CTest names. The layout
suite adds sixteen negative DLL lookups (fourteen functions and both tables),
**6 -> 7 cases**, without changing existing item/ability guards.

## P1: inventory and tests

**1,407 before = 1,407 after**; sorted inventory SHA-256
`fbd60c25eedbe427e6097993964249e12d5b39e30fdd167137fbb00b2b305913`.
The complete CTest JSON's ordering/commands/runtime properties compare identical
(excluding registration backtraces only). Tier counts stay **207 quick + 31 full
+ 1,151 reference + 18 slow**. [local-test-results.json](local-test-results.json):
baseline **37/37 in each build**, final **48/48 IPO** and **44/44 no-IPO**, zero
failures/skips/disabled. These include all **33 Moves tests**, mixed multihit
interplay G33, both layouts, perft, bench, frozen format pins, the generator's
151 cases and all four lint/hygiene checks. IPO also runs closure/extended/pool
regeneration and tiebreak regeneration. All native tests/runners were relinked
against the changed core, including the statically linked ten reference runners.
Full hosted CI is **not yet run on this branch**: the PR waits for HS's release.
No CI selectors, scheduling, timeouts or test behavior were changed.

## P2: all reference records

All four captures (baseline/after x IPO on/off) are **byte-equal**. Per profile:
**10 variants, 2,584 executions, 1,129 unique battles, 22,472 steps** across both
runner kinds (**11,236 conformance + 11,236 tiebreak**) and **8,458 stops**.
[reference-results.json](reference-results.json) retains every per-battle hash;
[verification.json](verification.json) records every byte comparison. Full JSON
SHA-256 `712387e820ed6a87f21ac8e047f384abab71fbb80ea99f0e1487a5de846d35e7`.
The internal digest captures state/requests/events/RNG/stops using
`tools/restructure/capture_reference.py`; the step-2 same-commit observer witness
remains valid. Every runner's original assertions execute during capture.
No reference data, generator, independent battle pin or live pin changed.

| Variant | Battles | Before = after, IPO on/off SHA-256 |
|---|---:|---|
| `duoforge_reference_conformance` | 90 | `620dd6f94faa5fc2751158f062c58edf75f48394aba7a9a49e6bc96bf8f9f271` |
| `duoforge_reference_conformance_pool` | 90 | `af3d4958fd43894492aac19e7911b5b5d9e266fc7afa81cb7a70cc0d878be174` |
| `duoforge_reference_conformance_pool_data` | 966 | `c452a188b6fd32a5796f9b3181a69542b6be335d4ea5a2c9a1b286da3b36d36b` |
| `duoforge_reference_conformance_team_c` | 73 | `1acfad0da5393e2095176d094ab2748800b305cfbfee048e04f127a1720c39c5` |
| `duoforge_reference_conformance_team_c_pool` | 73 | `a951cbfde3e2f00a7ccd9848f7e031f8e3199eea29ce9505cd9bb44713784812` |
| `duoforge_reference_tiebreak` | 90 | `b374c2d908d5bd00776a571f7bc6842722f0fb6e6401c9770b3f27001c07e4ea` |
| `duoforge_reference_tiebreak_pool` | 90 | `5d2dcf40c944203659d77ed19f7b1e42eaaece4cde930b9bf5d392971eaeaab9` |
| `duoforge_reference_tiebreak_pool_data` | 966 | `866ff996d0a311c1f394a5cbc42a8683ae8c24852ed6ad5854e1d5dd8b7d625b` |
| `duoforge_reference_tiebreak_team_c` | 73 | `78e1cb58a1fd273b438d99fb9d5db2bdc876b174da5bc73339bc002b2de7fb34` |
| `duoforge_reference_tiebreak_team_c_pool` | 73 | `6eb6ff381045b710ff04748b0faa5ce587cdcb961a31afc73fddf5af93a40fec` |

## P3-P6

- **P3:** both builds pass **10 perft positions / 24 pinned depths**; pins SHA
  `90cb0e55b5aed6d2285953338a736b76b7d46e586993b0c5fccceda2230c7c56`.
- **P4:** both builds pass **2 cases / 8 roots / 7 searched roots** with
  `BENCH_SHA256` `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798`.
- **P5:** all three `gen_closure --check` modes, tiebreak regeneration and frozen
  format pins pass. [source-hashes.json](source-hashes.json): **20 existing**
  data/generator/public-header/layout/perft/bench sources byte-unchanged. Existing
  generated tables, ids/order and canonical bytes stay frozen. Only the new
  move-phase artifact is generated; its own `--check` passes in both builds.
  UNMODELED pins stay **146 moves / 18 items / 90 abilities** until step 5.
- **P6:** public-header diff empty; **238 exported type/name entries** identical
  in both builds, SHA `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`.
  **33 layout structs / 250 constants** identical, canonical sorted/indented JSON
  SHA `502ecc2e08dc76cf3004d31115948bc4e69d7843ce5cd5d2492d950464e07e8e`.
  The raw dump bytes also compare identical; raw SHA is in verification.json.
  Sixteen new negative shared-library symbol lookups pass in both builds.

## Inlining and paired runtime gate

[inlining.json](inlining.json) records `objdump -d` call counts and surviving
call sites, including compiler suffixes, for the IPO and no-IPO shared library
and benchmark. **All twelve old helpers: 0 calls before = 0 after**, and both
new table predicates have **0 residual calls**, in all four artifacts. These
count static direct call sites, not dynamic invocations. No out-of-line helper
definition or tail jump survives either, in all eight before/after binaries. There is no extra call
or exported helper; every hot helper remains private static inline.

Predeclared protocol: **30 balanced A/B pairs per IPO profile**, three timed
repetitions per side/workload/pair (**90 samples per side**), two warmups,
AB on odd pairs, BA on even pairs, all samples retained. Every child is bound
by the existing Items harness to CPU 4. The raw driver's `affinity: "none"` is
its old unconditional string; outer `protocol.cpu_affinity` records actual
binding without editing raw output. No local builds/tests overlap these timing
runs. GCC **14.2.0**, Release `-O3 -DNDEBUG`, four-CPU quota, seeds **20261001/7001**,
512 battles per closure pairing AB/BA/AA/BB, 128-step cap. Every record and choice
tally matches: **2,048 battles, 37,199 steps, 27,204 turns, 66,803 side decisions**,
zero errors/truncations. Disturbed flags and outliers remain in the raw reports.

For each pair, median(after's three repetitions) / median(before's three);
report the median of these time ratios. The interval is 20,000 paired-bootstrap
median resamples, seed 20261012. Gate: **median after/before time <=1.02** and
within the baseline's own relative min/max pair spread (throughput >=0.98).
Confidence intervals and full ranges show the practical uncertainty; no causal
speedup or absolute no-regression claim.

| IPO | Workload | Median after/before time | Change | 95% paired-bootstrap CI | Full range |
|---|---|---:|---:|---|---|
| on | plain | 0.994459 | -0.55% | [0.975916, 1.007867] | [0.820598, 1.170956] |
| on | events | 0.998980 | -0.10% | [0.990179, 1.006590] | [0.644778, 1.076725] |
| off | plain | 1.004789 | +0.48% | [0.989076, 1.018875] | [0.853127, 1.234294] |
| off | events | 1.007206 | +0.72% | [0.994464, 1.026995] | [0.855571, 1.467977] |


Both IPO profiles pass the declared median runtime gate. The no-IPO/events
95% upper limit is **1.026995**, above 1.02: this sample does not statistically
rule out a loss above 2%, even though the median passes. IPO/plain retains one
after-side disturbed repetition; nothing was dropped or rerun to remove it.
Full paired data:
[paired-bench-ipo.json](paired-bench-ipo.json),
[paired-bench-noipo.json](paired-bench-noipo.json). The closure workload exercises
common first-turn/weight/guard paths; the full pool captures cover Beat Up/OHKO
integration. This is not a new hook-dispatch or random-team workload migration.

## Compile time and binary size

Fresh identical **core + shared** Release builds, parallel 4; configuration
excluded; separate compile-only `BUILD_TESTING=OFF` configs. Neither test proof
profile disables tests. Before/after with IPO; after/before without IPO. One
observation each, shared filesystem caches and cloud noise: report the numbers,
not a causal compile-speed claim or a whole-project measurement.

| IPO | Before wall s | After wall s | Before CPU s | After CPU s |
|---|---:|---:|---:|---:|
| on | 20.296 | 21.837 | 61.688 | 65.417 |
| off | 12.835 | 14.860 | 36.219 | 38.057 |


Both observations are slower after the split; there is no claimed build-speed
improvement. [compile-times.json](compile-times.json) retains CPU and wall times;
[binary-sizes.json](binary-sizes.json) retains both profiles' file/text/data/bss
sizes and hashes. No new translation unit is introduced.

| IPO | Before text+readonly | After text+readonly | Before/after data | Before/after bss |
|---|---:|---:|---|---|
| on | 591,519 | 591,583 | 19,856 / 19,856 | 8 / 8 |
| off | 580,965 | 581,109 | 19,848 / 19,848 | 8 / 8 |

## Reproduction and review notes

Use CI's Python 3.12/NumPy/JAX/optax, `OPENBLAS_NUM_THREADS=1`, Node 22.23.3,
and Showdown **b2cb775b0616115b775534eaeff50300e1fc81fc**. Configure separate
Release builds with IPO on/off and existing Python/Node/PS options. Relink the
Moves tests, mixed G33, layouts, benchmark and all ten reference runners before
running the proofs; stale statically linked runners are not evidence.

```sh
ctest --test-dir <build> -N
ctest --test-dir <build> --show-only=json-v1
ctest --test-dir <build> -L '^moves$' --output-on-failure
ctest --test-dir <build> -R '^duoforge.data.gen_closure_refusals$' --output-on-failure
python tools/datagen/gen_move_handlers.py --check
python tools/restructure/capture_reference.py . <build> <outside-repo-capture>
python docs/benchmarks/2026-10-12-restructure-items-pilot/paired-bench.py \
  --before <657dae45-ipo-build>/bench/duoforge_bench \
  --after <75c77c7a-ipo-build>/bench/duoforge_bench \
  --rounds 30 --repetitions 3 --warmup 2 --cpu 4 --out <outside-repo-ipo.json>
# Repeat with no-IPO binaries and --ipo off.
```

One **pre-existing audit finding**, unchanged here: `BulletFlag` in
`tools/datagen/tests/test_gen_closure.py` is defined after `unittest.main()`, so
its two cases are not reached by CTest's direct-script invocation. The new four
cases are deliberately inserted before that main block and demonstrably execute;
147 old direct-script cases remain, now 151. Registering the old two cases is
separate maintenance, not a test change hidden in this restructure.

No trained weights, checkpoints, replay payloads, live logs or run directories
are committed. Reports contain public fixture names/hashes, source paths, counts
and timing samples only. Security/self-review: no unresolved blocker; no new
allocation, public input/dependency/config/secret. Existing lint and tests pass;
coverage tooling is not configured (outside this PR), UI E2E not applicable to
private C headers. HS reviews and merges; this branch neither merges PRs nor
enables auto-merge, and the next area waits for this PR's merge.
