# Restructure step 4: ability families and Fairy Aura

The existing ability families now live in named private headers: `ate.h`,
`pinch.h`, `weather_setter.h`, `terrain_setter.h`; shared live ability access is
in `current.h`. `families.h` keeps the family-test include together. The bounded
Fairy Aura holder scan and BasePower rule are in `fairy_aura.h`. All these hot
helpers are `static inline`; there are no new translation units or CMake source
entries. The turn retains chain positions, setter writes/durations/callbacks,
entry announcements, sorting and RNG order. No rule or public API changes.

Baseline **58f2149d**, compiled source **2397c2ba**, branch
`restructure/4-abilities`. HS released the PR window. The final fetch and merge
of main reported already up to date at **58f2149d**; `gh pr list` was empty.
The compiled source proofs therefore need no refresh after that merge.
Full PR-head CI remains the merge gate; no GitHub job is being monitored.

## Source lineage and location audit

| Old path | New path | Rename-only commit |
|---|---|---|
| `src/combat/ability_family.h` | `src/combat/abilities/families.h` | `34a4438c`, git mv, 100% similarity, nothing else |

Family/access split `41c9c060`, Fairy Aura split `2ce0375c`: both credit
`split from ...@58f2149d`. [function-extractions.json](function-extractions.json)
records **eleven byte-identical original bodies** and **three effect blocks**
with only b/r->b, chain-address and unchanged bool-result wiring.

| Function | Old location @58f2149d | New location |
|---|---|---|
| `dfi_ability_family_for` | `src/combat/ability_family.h:34-41` | `src/combat/abilities/current.h:13-20` |
| `dfi_ability_code` | `src/combat/turn.c:254-264` | `src/combat/abilities/current.h:27-37` |
| `dfi_ability_family_now` | `src/combat/turn.c:267-270` | `src/combat/abilities/current.h:40-43` |
| `dfi_ability` | `src/combat/turn.c:273-276` | `src/combat/abilities/current.h:46-49` |
| `dfi_ate_excluded` | `src/combat/ability_family.h:47-50` | `src/combat/abilities/ate.h:13-16` |
| `dfi_ate_type_fam` | `src/combat/ability_family.h:57-63` | `src/combat/abilities/ate.h:23-29` |
| `dfi_ate_boosts_fam` | `src/combat/ability_family.h:67-70` | `src/combat/abilities/ate.h:33-36` |
| `dfi_ate_base_power` | `src/combat/turn.c:1869-1871` | `src/combat/abilities/ate.h:38-48` |
| `dfi_pinch_applies_fam` | `src/combat/ability_family.h:75-79` | `src/combat/abilities/pinch.h:12-16` |
| `dfi_pinch_attack` | `src/combat/turn.c:2003-2005` | `src/combat/abilities/pinch.h:19-26` |
| `dfi_weather_set_by_fam` | `src/combat/ability_family.h:85-95` | `src/combat/abilities/weather_setter.h:10-20` |
| `dfi_terrain_set_by_fam` | `src/combat/ability_family.h:99-109` | `src/combat/abilities/terrain_setter.h:8-18` |
| `dfi_fairy_aura_on_field` | `src/combat/turn.c:340-349` | `src/combat/abilities/fairy_aura.h:14-23` |
| `dfi_fairy_aura_base_power` | `src/combat/turn.c:1909-1911` | `src/combat/abilities/fairy_aura.h:26-35` |

Active includes and source citations in C tests, decision 0015, decision 0041
and support docs now resolve to the new headers. Audit: C/C++, Python, CMake,
shell, CI, generators and active docs have no `combat/ability_family.h`
consumer. The content-files design's bare old header name describes its
explicitly frozen ca17e507 measurement and is retained as historical evidence.
Tests keep their files, names, command lines, directories and environment.
The existing layout suite adds one export-boundary case (5 -> 6 unittest
cases), with fourteen negative DLL lookups; existing assertions are unchanged.
The first intermediate build exposed a missing direct modifier declaration
include; the family headers now include `core/modifier.h` themselves, without
relaxing warnings or tests.

## P1: inventory and executed tests

**1,407 before = 1,407 after**, sorted inventory SHA-256
`fbd60c25eedbe427e6097993964249e12d5b39e30fdd167137fbb00b2b305913`.
All test ordering/commands/runtime properties match, excluding registration
backtraces only. Tiers: **207 quick + 31 full + 1,151 reference + 18 slow**.
[local-test-results.json](local-test-results.json): baseline 10/10; final
**31/31 IPO** and **27/27 no-IPO** CTests, zero failure/skip/disabled, including
all 15 Ability tests, weather/terrain/Mega interplay, both layouts, perft,
bench, frozen format pins and all four lint/hygiene checks. IPO also reruns
closure/extended/pool generation and tiebreak regeneration. All native test
executables used here are relinked against the changed core. Ten reference
captures in each build execute their original assertions too. **Full CI:
pending automatic PR-head runs; all twelve matrix jobs plus RNG on the PR head
must be green before HS merges.** No CI selector, scheduling or timeout change.

## P2: every battle result

Baseline IPO/no-IPO and after IPO/no-IPO captures are **byte-equal** across
**10 variants / 2,584 executions / 1,129 unique battles per profile**,
**11,236 steps / 8,458 stops**. The one canonical
[reference-results.json](reference-results.json) retains every per-battle hash;
[verification.json](verification.json) records all four byte comparisons.
Complete JSON SHA-256:
`712387e820ed6a87f21ac8e047f384abab71fbb80ea99f0e1487a5de846d35e7`.
Use `tools/restructure/capture_reference.py`; the step-2 same-commit witness
against the retired observer remains valid. No reference fixture/spec/pin or
generated dataset is moved or changed.

| Variant | Battles | Before = after in both builds SHA-256 |
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

- **P3:** both builds pass **10 perft positions / 24 pinned depths**. Pins SHA:
  `90cb0e55b5aed6d2285953338a736b76b7d46e586993b0c5fccceda2230c7c56`.
- **P4:** both builds pass the **2-case / 8-root / 7-searched-root** benchmark
  with `BENCH_SHA256`
  `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798`.
- **P5:** closure/extended/pool `gen_closure --check`, tiebreak regeneration
  and frozen format-pin checks pass. [source-hashes.json](source-hashes.json)
  retains **20 unchanged** data/generator/header/layout/perft/bench source
  hashes. IDs/order/generated bytes unchanged. UNMODELED pins stay
  **146 moves / 18 items / 90 abilities**, as agreed until step 5.
- **P6:** public-header diff empty; **238 exported type/name entries** byte-equal
  in both builds, SHA
  `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`.
  Layout **33 structs / 250 constants** byte-equal, SHA
  `502ecc2e08dc76cf3004d31115948bc4e69d7843ce5cd5d2492d950464e07e8e`.
  No newly shared/external ability definition: all fourteen helpers are
  private static inline functions. The DLL guard tests all fourteen names.

## Inlining and paired performance

[inlining.json](inlining.json) preserves `objdump -d` surviving call sites and
caller names in the IPO shared library and benchmark executable, including
compiler suffixes. These count **static direct call sites**, not invocations.
Both artifacts have the same before/after vector: **25 calls to `dfi_ability`
before = 25 after**; the other ten pre-existing helpers have zero. GCC may
outline a local body despite a static inline declaration; there is no added
call or export. All three new effect helpers (`dfi_ate_base_power`,
`dfi_pinch_attack`, `dfi_fairy_aura_base_power`) have **zero** residual calls.

Paired protocol: **30 balanced A/B pairs per IPO profile**, 3 timed repetitions
per side/workload in each pair (90 samples per side), 2 warmups, all samples
retained. AB odd pairs, BA even pairs; every child bound to CPU 4 by the harness
from the preceding Items report. The driver's `affinity: "none"` is its existing
unconditional literal; outer `protocol.cpu_affinity` records the actual binding
without altering raw output. No local test/build overlaps either timing run.
Same GCC 14.2.0, Release `-O3 -DNDEBUG`, four-CPU quota, fixed seeds
20261001/7001, 512 battles per closure pairing (AB/BA/AA/BB), cap 128 steps.
Every record and choice tally matches: **2,048 battles / 37,199 steps /
27,204 turns / 66,803 side decisions**, zero errors/truncations/disturbed flags.

Per pair, divide the median of its after repetitions by the median before;
report the median of these **after/before time** quotients. The 95% interval
uses 20,000 paired bootstrap samples, seed 20261012. The baseline's own spread
is its min/max pair median relative to its overall median (full data retained
in [paired-bench-ipo.json](paired-bench-ipo.json) and
[paired-bench-noipo.json](paired-bench-noipo.json)).

| IPO | Workload | Median time ratio | Change | 95% paired-bootstrap CI | Full ratio range |
|---|---|---:|---:|---|---|
| on | plain | 0.997133 | -0.29% | [0.976804, 1.008581] | [0.507209, 2.040313] |
| on | events | 0.987371 | -1.26% | [0.931230, 1.002863] | [0.569736, 1.485330] |
| off | plain | 0.978220 | -2.18% | [0.952791, 0.998097] | [0.773751, 1.153898] |
| off | events | 0.996810 | -0.32% | [0.983323, 1.006234] | [0.777456, 1.327226] |

**Both profiles pass:** all four paired time medians <=1.02 (throughput above
0.98) and within their baseline's own spread. All upper 95% limits are <=1.02
as well. Cloud outliers remain visible in the full ranges; this is not a causal
speedup claim or an absolute no-regression guarantee. The closure workload
exercises the common live lookup and -ate/pinch paths; Fairy Aura's full-battle
integration is checked by the pool captures, not a new random-team workload.

## Build risk and binary size

[compile-times.json](compile-times.json): fresh comparable **core + shared**
Release builds, four-way parallelism, configuration excluded, no tests disabled
in the proof profiles. These separate compile-only configurations use
`BUILD_TESTING=OFF`. IPO order before/after, OFF order after/before; one
observation each, shared filesystem caches/host noise, no whole-project or
causal speed claim.

| IPO | Before wall s | After wall s | Before CPU s | After CPU s |
|---|---:|---:|---:|---:|
| on | 24.256 | 20.297 | 68.856 | 61.425 |
| off | 26.668 | 14.150 | 63.891 | 37.501 |

[binary-sizes.json](binary-sizes.json) records file/.text/data/bss sizes and
hashes. IPO `size` text+readonly bytes: **592,867 -> 591,519** (-1,348); data
**19,856 -> 19,856**, bss **8 -> 8**. No extra translation unit is introduced.

## Reproduction

Use the existing CI flags and dependencies: Python 3.12/NumPy/JAX/optax,
`OPENBLAS_NUM_THREADS=1`, Node 22.23.3 and Showdown exactly
`b2cb775b0616115b775534eaeff50300e1fc81fc`. Configure separate Release builds
with IPO ON/OFF and the existing Python/Node/PS CMake options. Build all fifteen
area tests, the three field/Mega tests and all ten reference runners before
capturing their results; a stale statically linked runner is not evidence.

```sh
ctest --test-dir <build> -N
ctest --test-dir <build> --show-only=json-v1
ctest --test-dir <build> -L abilities --output-on-failure
ctest --test-dir <build> -R '^duoforge.python.(layout|state_layout|perft|bench)$' --output-on-failure
python tools/restructure/capture_reference.py . <build> <outside-repo-capture>
python docs/benchmarks/2026-10-12-restructure-items-pilot/paired-bench.py \
  --before <58f2149d-ipo-build>/bench/duoforge_bench \
  --after <2397c2ba-ipo-build>/bench/duoforge_bench \
  --rounds 30 --repetitions 3 --warmup 2 --cpu 4 --out <outside-repo-ipo.json>
# Repeat with OFF binaries, adding --ipo off; keep --rounds 30.
```

No new trained weights, checkpoints, replay payloads, live logs or run directories
are committed. This evidence contains public fixture names/hashes, source
paths, aggregate counters and timing samples only. HS merges; the next area
waits for this area's PR to merge.
