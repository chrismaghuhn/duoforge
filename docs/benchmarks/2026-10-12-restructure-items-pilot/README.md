# Restructure step 3: item families and White Herb pilot

## Question and result

Can the existing item families and one bounded item effect leave the turn
monolith without changing battle behavior, test selection or the public surface?
The pilot extracts type-booster/resist-berry effects, live held-item access and
White Herb. Both IPO profiles retain every baseline reference digest, perft pin,
search signature, public layout and exported symbol. Timing results are mixed;
this report makes no performance-neutrality or speedup claim.

Baseline: **`ca17e507`**. Implementation/visibility regression/format-fact naming:
**initially `3a9d04d1`, reviewed source `9b7fa521`**. After HS released the PR slot, current main **`36b55704`** was
merged into `restructure/3-items-pilot` in **`0e2652d4`**, without rebase or main
push. Main's only addition since the baseline is the content-files design
specification; engine, tests, workflows and proof inputs are unchanged by that
merge. The baseline remains `ca17e507`. Fresh PR-head CI is required before HS
merges; the successful implementation CI below does not replace that gate.

## HS review: inlining and paired measurement (current)

Reviewed engine source: **`9b7fa521`**, baseline **`ca17e507`**. The three
held-item accessors now live as private `static inline` definitions in
`src/combat/items/held.h`. Their function bodies are **byte-identical** to the
initial extraction ([inline-body-equivalence.json](inline-body-equivalence.json)).
Rename-only commit `62dbbd33` comes before qualifier/include/CMake edits in
`9b7fa521`. No compiler thresholds, assertions, input workload, generated
records or rule behavior changed.
The supplementary no-IPO events interval still allows +3.63% time despite a
+0.14% point estimate; only the IPO release gate has the tighter bound.

| Review claim | Decision | Result |
|---|---|---|
| Prove hot-helper inlining | FIX_NOW | Before/pilot/inline objdump call-site counts below |
| At least 15 interleaved IPO rounds, <=2% loss | FIX_NOW | 30 balanced A/B pairs, all samples retained; both point and upper 95% limits pass |
| Private static inline access if not inlined | FIX_NOW | All three accessors in `held.h`, unchanged bodies, unchanged exports and P2 |

[inlining.json](inlining.json) retains each surviving call and caller from
`objdump -d`, including `.part`/`.lto_priv` suffixes. Counts are static call
sites, not invocation counts. The shared library and benchmark executable
have the same count vectors in each profile:

| Helper | Baseline | Initial pilot | Private inline |
|---|---:|---:|---:|
| `dfi_holds` | 0 | 13 | 0 |
| `dfi_item_code` | 14 | 2 | 13 |
| `dfi_item_takeable` | 0 | 0 | 0 |

GCC completely inlines `dfi_holds` and `dfi_item_takeable` again. It still
outlines a **local** part of `dfi_item_code`, as it already did in the baseline
(13 sites now, 14 before). `static inline` permits that compiler decision; it
does not force every local symbol to disappear. No new DLL export appears.
Only the other five item helpers need external hidden declarations.

[paired-bench-ipo.json](paired-bench-ipo.json) has **30 pairs / 90 timed samples
per workload per side**; [paired-bench-noipo.json](paired-bench-noipo.json) has
**15 pairs / 45 samples per workload per side**. Each invocation uses two
warmups and three measured repetitions, fixed seeds 20261001/7001, 512 battles
for each of the four closure pairings (2,048 battles, cap 128 steps). The
order alternates AB on odd pairs and BA on even pairs to balance order drift.
The harness binds every child to **CPU 4** with `sched_setaffinity`, and no
local build/test runs concurrently. The native manifest's `affinity: "none"`
is a pre-existing unconditional driver string; the harness's protocol records
the actual applied affinity without editing that raw manifest. Same GCC 14.2,
Release `-O3 -DNDEBUG`, four-CPU quota and fixture fingerprint throughout.
The no-IPO binary's dirty marker reflects proof-document edits only; its
engine/test/tool/public-header tree matches `9b7fa521` exactly.

For each pair, take the median of its three repetitions per side, then compute
**after/before time**. The table uses the median of those paired quotients,
not a quotient of independently collected overall medians. The 95% interval is
20,000 paired bootstrap resamples with seed 20261012. Baseline spread is its
minimum/maximum per-pair median divided by its overall median.

| IPO | Workload | Median time ratio | Change | 95% paired-bootstrap CI | Full ratio range | Baseline relative spread |
|---|---|---:|---:|---|---|---|
| on | plain | 0.988287 | -1.17% | [0.965748, 1.017639] | [0.575128, 1.538917] | [0.954665, 1.737943] |
| on | events | 0.975470 | -2.45% | [0.929935, 1.003846] | [0.707030, 1.824222] | [0.918454, 1.339208] |
| off | plain | 0.981521 | -1.85% | [0.945069, 1.017362] | [0.648444, 1.355472] | [0.948017, 2.046693] |
| off | events | 1.001415 | +0.14% | [0.954886, 1.036258] | [0.918780, 1.647596] | [0.958947, 2.079209] |

**IPO release gate passes:** both time medians and their upper 95% bootstrap
limits are <=1.02, and both medians/intervals lie within their baseline's own
spread. Median throughput ratios are **1.011851 (plain)** and **1.025147
(events)**, above the spec's 0.98 threshold. These cloud observations retain
large outliers; no causal speedup or absolute no-regression guarantee is
claimed. Every sample is retained, including those outliers. All measurements
report zero CPU/wall disturbed flags, zero errors/truncations and identical
**37,199 steps / 27,204 turns / 66,803 side decisions**, including the complete
aggregate move/choice tallies.

[paired-bench-original-pilot.json](paired-bench-original-pilot.json) also retains
the diagnostic 15 one-repetition pairs on the initial pilot: plain median
0.980811, events 1.000896, with wide intervals. The missing `dfi_holds` inlining,
rather than those noisy point estimates, triggered the header fix. The earlier
unpaired timings below are historical and do not establish this release gate.

**Correctness rechecked after the header fix:**
[review-verification.json](review-verification.json) records **14/14 IPO** and
**10/10 no-IPO CTests**, plus **4/4 source-lint/repository-hygiene checks**,
zero failure/skip, including all five area item tests,
format-pins, perft, search bench and both layout suites; the IPO selection also
reruns all three generated-data checks and tiebreak regeneration. All ten
native reference variants are recaptured in **each** build: 2,584 executions,
1,129 unique battles and every byte match the frozen baseline JSON. The 1,407
CTest commands/runtime properties, 238 exported entries, 33 structs/250
constants and 20 data/generator/public-layout/pin source hashes remain equal.
P1–P6 numbers and all reference SHA-256 values below remain valid; the larger
242/6 initial local selections and 12-job source CI below are historical.
Fresh full CI on the final PR head remains HS's merge gate.

Reproduce (outputs must remain outside the repository):

```sh
python docs/benchmarks/2026-10-12-restructure-items-pilot/paired-bench.py \
  --before <ca17e507-ipo-build>/bench/duoforge_bench \
  --after <9b7fa521-ipo-build>/bench/duoforge_bench \
  --rounds 30 --repetitions 3 --warmup 2 --cpu 4 --out <outside-repo-ipo.json>
# For no IPO: use the corresponding OFF binaries and add --ipo off --rounds 15.
```

## Implementation and lineage

The turn still chooses applicability, damage-chain position, handler collection,
speed sorting and RNG use. Item consumption remains its existing
`dfi_use_item`/AfterUseItem/Unburden/Symbiosis path; the berry and White Herb
helpers receive that exact function as a private callback. There is no handler
registry, added rule, allocation, changed field, event or draw order.

The private `dfi_run` scratch definition is copied unchanged, including field
order and lifetime. Position/event helpers are private inline definitions.
The moved position access names the existing `DUOFORGE_ACTIVE_PER_SIDE` (**2u**):
all four affected translation units have byte-identical expanded inputs before
and after this naming change ([witness](named-format-constant.json)).
[body-equivalence.json](body-equivalence.json) checks ten extracted bodies,
normalizing only that constant name and the supplied useItem callback name.
The turn file decreases from **12,678 to 12,489 lines** (189 lines).

| File move | Destination | Move commit |
|---|---|---|
| `src/combat/item_family.h` | `src/combat/items/families.h` | `67987baf`, git mv, **100% rename only** |
| `src/combat/items/held.c` (initial pilot) | `src/combat/items/held.h` | `62dbbd33`, git mv, **100% rename only**, before inline edits |

Includes/comments are edited only after that move commit. Function splits carry
their source credit: family/common extraction `6d4bab9d`, White Herb `7c3a5c52`.
The complete [function-extractions.json](function-extractions.json) map is:

| Function/type/constant | Old source | New source |
|---|---|---|
| `dfi_run (unchanged layout)` | `src/combat/turn.c@ca17e507:40-108` | `src/combat/run_internal.h:12-80` |
| `dfi_pos` | `src/combat/turn.c@ca17e507:121-124` | `src/combat/run_internal.h:82-85` |
| `dfi_at` | `src/combat/turn.c@ca17e507:127-134` | `src/combat/run_internal.h:88-95` |
| `dfi_emit` | `src/combat/turn.c@ca17e507:459-464` | `src/combat/run_internal.h:97-102` |
| `dfi_ev` | `src/combat/turn.c@ca17e507:467-474` | `src/combat/run_internal.h:105-112` |
| `dfi_item_code` | `src/combat/turn.c@ca17e507:305-324` | `src/combat/items/held.h:13-32` |
| `dfi_holds` | `src/combat/turn.c@ca17e507:327-330` | `src/combat/items/held.h:35-38` |
| `dfi_item_takeable` | `src/combat/turn.c@ca17e507:370-374` | `src/combat/items/held.h:46-50` |
| `dfi_type_booster_base_power` | `src/combat/turn.c@ca17e507:2078-2083` | `src/combat/items/families.c:4-14` |
| `dfi_resist_berry_hit` | `src/combat/turn.c@ca17e507:2302-2310` | `src/combat/items/families.c:19-33` |
| `dfi_herb_due` | `src/combat/turn.c@ca17e507:3636-3648` | `src/combat/items/white_herb.c:5-17` |
| `dfi_white_herb` | `src/combat/turn.c@ca17e507:3653-3665` | `src/combat/items/white_herb.c:22-34` |
| `dfi_herb_holder` | `src/combat/turn.c@ca17e507:3715-3719` | `src/combat/items/white_herb.c:38-42` |
| `DFI_POSITIONS` | `src/combat/turn.c@ca17e507:37-37` | `src/combat/run_internal.h:10-10` |

`542d04de` is the separate step-2 follow-up requested by HS: only the two specs
reads in `format_pins.py` and `_reference_pins.load` gain `encoding="utf-8"`.
Both readers pass under an ASCII default locale for **1,129 specs / 1,056 live
pins** ([utf8-check.json](utf8-check.json)); no parsing/assertion/expected-value
changes. `70af1214` adds one case to the existing Python layout suite (4 → 5)
to reject all eight extracted item helper names at the actual DLL boundary.
The three hot accessors are now private static inline definitions; the other
five remain hidden shared helpers.
It introduces no CTest name or property change.

## P1: test inventory and execution

Before/after **1,407 names identical**, SHA-256
`fbd60c25eedbe427e6097993964249e12d5b39e30fdd167137fbb00b2b305913`.
[test-inventory.txt](test-inventory.txt) and
[inventory-comparison.json](inventory-comparison.json) retain the sorted
`ctest -N` inventory and complete per-test JSON comparison: commands, working
directories, environment, labels, timeouts, fixtures and registration order
are unchanged; only registration backtraces are excluded.
Exactly one tier each: **207 quick + 31 full + 1,151 reference + 18 slow**.
CI selectors and workflows have no diff.

[local-test-results.json](local-test-results.json): **242/242 CTests** on the
initial IPO implementation (238 quick/full + 3 data regenerations + tiebreak
regeneration), plus **6/6** selected no-IPO checks; no failure/skip/disabled.
The IPO run includes frozen-pin `--check`: **1,129 certificates/fixture pins
and 1,056 live pins**. The baseline proof selection passed 9/9.
Both full native P2 captures also execute all original runner assertions.

Manual branch CI on source **`3a9d04d1`**:
[12-job matrix](https://github.com/chrismaghuhn/duoforge/actions/runs/38302940369),
[RNG reference](https://github.com/chrismaghuhn/duoforge/actions/runs/38306118385).
**All 12 matrix jobs and the RNG check are green** on that source commit,
recorded in [ci-results.json](ci-results.json). The
conditional quick-profile guard is intentionally skipped in full mode.
Windows GCC/Python/reference already passed **1,407 registrations**, including
`duoforge.python.layout` with its new export guard (0.15 s); JAX-only skips are
the workflow's existing allowance. The earlier run on `7c3a5c52` was superseded
by the current source/guard run and is not a final proof. Fresh PR-head checks
will run when the authorized PR is opened; no CI timeout or scheduling changes.

## P2: every reference result

[reference-results-before.json](reference-results-before.json),
[reference-results-ipo.json](reference-results-ipo.json) and
[reference-results-noipo.json](reference-results-noipo.json) are **byte-equal**:
each profile has **10 variants / 2,584 executions / 1,129 unique battles**,
**11,236 steps / 8,458 stops**. Complete JSON SHA-256:
`712387e820ed6a87f21ac8e047f384abab71fbb80ea99f0e1487a5de846d35e7`.
Every per-battle hash is retained, not merely dataset aggregates. Capture uses
the internal step-2 digest tool; its same-commit observer witness remains in the
step-2 report. No reference payload/trace/spec/pin is moved or regenerated here.

| Variant | Battles | Before = IPO = no IPO SHA-256 |
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

## P3–P6

[verification.json](verification.json) and [source-hashes.json](source-hashes.json)
retain the counts and **20 unchanged source hashes** for data tables, their
generator, public headers, binding layouts, perft pins and the search bench.

- **P3:** perft passes in both profiles: **10 positions / 24 pinned depths**;
  pin-file SHA-256 `90cb0e55b5aed6d2285953338a736b76b7d46e586993b0c5fccceda2230c7c56`.
- **P4:** both profiles pass the **2-case / 8-root / 7-searched-root** search
  bench; `BENCH_SHA256` stays
  `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798`.
- **P5:** closure/extended/pool `gen_closure --check`, conformance and tiebreak
  regeneration checks, and frozen battle-pin `--check` pass. Generated data,
  IDs, table ordering, per-battle observations and the independent format pins
  have no diff. UNMODELED pins remain **146 moves / 18 items / 90 abilities**.
- **P6:** public-header diff empty; both profiles retain the same **238**
  exported type/name entries, SHA-256
  `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`;
  [layout.json](layout.json) retains **33 structs / 250 constants**, SHA-256
  `502ecc2e08dc76cf3004d31115948bc4e69d7843ce5cd5d2492d950464e07e8e`.
  [exported-symbols.txt](exported-symbols.txt) contains no new entry.

Only the new item declarations have hidden visibility on ELF. On Windows their
definitions live in an archive outside CMake's `WINDOWS_EXPORT_ALL_SYMBOLS`
object scan; GNU PE also gets `--exclude-libs` for precisely that archive. MSVC
keeps its existing shared-library IPO policy. Existing exports remain public;
the new layout case verifies eight negative symbol lookups, including Windows
MinGW. No public API/ABI change or library-wide visibility change.

## Initial unpaired bench with IPO on and off (historical)

[bench-comparison.json](bench-comparison.json) records samples, CPU/wall timing,
manifests and counter equality. Same cloud/toolchain: GCC 14.2.0, Release
`-O3 -DNDEBUG`, CMake 4.4.4/Ninja 1.13.2, CPU quota **4**, no competing local
build/test during timing. Native: **2 warmups / 9 repetitions**, four closure
pairings, **512 battles each** (2,048), cap 128 steps, fixed policy/battle seeds
20261001/7001. The work is identical before/after in both profiles:
**37,199 steps / 27,204 turns / 66,803 side decisions**, zero errors/truncations
and identical move/choice tallies. No repetition is marked disturbed by the
driver's CPU/wall criterion.

Search: the existing `Bench.signature()` with all margin assertions and the
pinned hash, **1 warmup / 5 repetitions**, `OPENBLAS_NUM_THREADS=1`, hash network
(no trained weights). Native closure timing does not exercise Team C's White
Herb; whole-battle Team C references and the pool search cover the integration.

| IPO | Workload | Before median ms | After median ms | Change |
|---|---|---:|---:|---:|
| on | STEP_CORE / plain | 357.944 | 371.625 | +3.82% |
| on | STEP_CORE / events | 364.096 | 393.768 | +8.15% |
| on | EPISODE_NATIVE / uniform-random | 575.871 | 597.731 | +3.80% |
| on | pinned honest search | 2982.413 | 2555.788 | -14.30% |
| off | STEP_CORE / plain | 435.949 | 408.343 | -6.33% |
| off | STEP_CORE / events | 424.384 | 427.173 | +0.66% |
| off | EPISODE_NATIVE / uniform-random | 703.446 | 634.386 | -9.82% |
| off | pinned honest search | 2473.761 | 2321.056 | -6.17% |

These are one environment/sample per profile, not a clean causal speed estimate.
In particular the native events profile with IPO is **+8.15%**, while the search
and no-IPO observations often move the other way. No unmeasured neutrality or
improvement is claimed and no behavior/test change was made to improve timings.
No-IPO timings were captured on `7c3a5c52`; after constant naming the final
shared library is byte-identical to the measured one. IPO timings use `3a9d04d1`.

## Location-dependency audit

Active C/C++, Python, CMake, shell, CI, generators and docs have no remaining
`combat/item_family.h` consumer. The item-family test changes only its include
and explanatory path. Shared helpers retain their names/bodies; consumers now
include the private item interface. Reference runners, fixture paths, CTest
invocations, public headers and generated-data inputs remain at their old paths.

[doc-citation-map.json](doc-citation-map.json) maps **35** numbered decision
citations to named helpers. Approximate/abbreviated turn references are also
replaced; `dfi_place` correctly points at `src/state/identity.c`. The independent
historical expansion reports and generator entries are explicitly tied to their
`cfe18c0`/`1aab4c2` snapshots; the third-team citation is a `3133fcc` permalink.
Their generated inventories are retained unchanged rather than hand-edited to
pretend they describe the modern engine. The held-item/header/test paths in
decision 0015 are updated as well. No private weights, checkpoints, replay data,
live logs or run directories are committed; evidence here is public counts,
fixture names, hashes and source paths only.

## Reproduction

Configure as CI: Python 3.12 with NumPy and JAX/optax, Node 22, exactly the pinned
Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc`, `OPENBLAS_NUM_THREADS=1`.
Use one Release build with `-DDUOFORGE_ENABLE_IPO=ON`, another with it `OFF`.
Set existing `DUOFORGE_PYTHON`, `DUOFORGE_LEARN_PYTHON`, `DUOFORGE_NODE` and
`DUOFORGE_PS_REFERENCE_DIR` options. Keep captures outside the repository:

```sh
cmake --build build/restructure --parallel 4
ctest --test-dir build/restructure -L '^(quick|full)$' --parallel 4 --output-on-failure
ctest --test-dir build/restructure -R '^duoforge\.(data\.(closure|extended|pool)_regen|reference\.tiebreak_ref)$' --output-on-failure
python tools/restructure/capture_reference.py . build/restructure <outside-repo-ipo-output>
python tools/restructure/capture_reference.py . build/restructure3-noipo <outside-repo-noipo-output>
build/restructure/bench/duoforge_bench --battles 512 --repetitions 9 --warmup 2 --max-steps 128 --families step,events,episode --out <outside-repo-ipo-bench.json>
build/restructure3-noipo/bench/duoforge_bench --battles 512 --repetitions 9 --warmup 2 --max-steps 128 --families step,events,episode --out <outside-repo-noipo-bench.json>
```

To repeat the search timings, set `PYTHONPATH=<repo>/python:<repo>` and
`DUOFORGE_LIBRARY` to the profile's shared library; run the same snippet in each
fresh process (no CTest/build in parallel):

```python
import statistics, time
from python.tests.search.test_bench import BENCH_SHA256, Bench
test = Bench()
assert test.signature()[1] == BENCH_SHA256  # warmup, all existing assertions
samples = []
for _ in range(5):
    start = time.perf_counter()
    rows, digest = test.signature()
    samples.append(time.perf_counter() - start)
    assert digest == BENCH_SHA256
print(samples, statistics.median(samples), digest)
```
