# Restructure step 2: reference data and pins per battle

The generated reference payloads and frozen observations now belong to each battle.
All 1,129 public reference battles retain their results. The original 1,403-test
baseline on `a9e44f8c` is preserved below. After the slot was released, main
`5c99fbd0` was merged without rebasing: it adds `duoforge.python.ladder` and
`duoforge.python.live_cts`, so main and this branch both register **1,405** tests.
[main-slot-comparison.json](main-slot-comparison.json) proves identical names,
commands, all runtime properties and registration order against that main.
The full hosted PR-head matrix remains the merge gate; local checks do not replace it.

## Data and pins

There is one generated JSON file under `tests/reference/battles/reg-mc/<set>/<name>.json`
for each battle. It contains its C conformance payload with local tape/event offsets,
its tiebreak payload and its frozen certified/fixture/live observations.
`tests/reference/data.cmake` discovers the directory, derives registry order and
flat-array bases, and compiles four build-local generated C modules once in a
**test-only** static library. Native builds require no new Python/Node dependency.
The four original generated data headers remain as small declarations with the
same aliases and record types; existing consumers keep their indexing semantics.

| Old generated content | New per-battle directory | Battles |
|---|---|---:|
| `tests/reference/conformance.h` + closure tiebreak rows | `tests/reference/battles/reg-mc/closure/` | 90 |
| `tests/reference/conformance_team_c.h` + Team C tiebreak rows | `tests/reference/battles/reg-mc/team_c/` | 73 |
| `tests/reference/conformance_pool.h` + pool tiebreak rows | `tests/reference/battles/reg-mc/pool/` | 966 |
| `python/tests/live/test_live.py` assembler/stop pins | Closure and pool battle files above | 1,056 |

No whole file was moved. [battle-path-map.csv](battle-path-map.csv) lists **every
battle's old and new paths**, with the old member/step and tiebreak definition
line ranges. Tape/events are distributed into the corresponding battle's local
slices by the converter. [function-extractions.json](function-extractions.json)
records both same-file live-loop extractions and the observer encoding's origin.
The live loops were extracted in commit `02698690`, before pin wiring; assertions
and classification branches are retained. Expected pins are read at test assertions
so the explicit generator can observe a new battle before its pin file exists.

[derived-totals.json](derived-totals.json) was independently compared to the
baseline's per-battle certificate/live observations, not just their global sums:

| Set | Certified | Tiebreak stops | Live outcomes |
|---|---:|---:|---|
| closure | 26 / 90 | 833 | equal 2,594; refused 310 |
| team_c | 23 / 73 | 734 | Not part of the existing live assembler suite |
| pool | 966 / 966 | 5,324 | equal 11,604; refused 639; unburden-without-item-line 4 |

Team C fixture matches total **144**. The pool's **162** tracker stops are
SUBSTITUTE 110, DRAGON_CHEER 20, FORME_CHANGE 10, DESTINY_BOND 10, ROOST 8,
line:-end 2 and ILLUSION 2; its own-PP refusal set has **12** (battle, player) pairs.
All equal the former global pins. BENCH_SHA256 and perft pins remain global.
The UNMODELED pins **146 moves / 18 items / 90 abilities** are intentionally
untouched: they count data-table rows, including rows without battles. Per the
owner's clarification they are derived from definitions in step 5, not here.

## P1: inventory and executed checks

[inventory-comparison.json](inventory-comparison.json) compares the complete
CTest JSON excluding registration backtrace locations only. Commands, working
directories, environments, timeouts, labels, fixtures, scheduling properties and
registration order are identical. [test-inventory.txt](test-inventory.txt) has
1,403 sorted names, SHA-256
`ab415dad8fa1b4923bcc60cfd9715d5e66036693696ca7e1c01deead10b8fd40`.
The tier counts remain **204 quick + 30 full + 1,151 reference + 18 slow = 1,403**.

[local-test-results.json](local-test-results.json) records **240/240 CTests passed,
zero failed/skipped/disabled**: all 234 quick/full checks, live, replay,
tiebreak regeneration and the three generated-engine-data checks. This includes
all ten native reference variants and three record-sync consumers. The full live
suite ran **50** unittest cases, replay **13**, and converter **133** (baseline
132, with one additional directory/payload corruption test). The converter now
checks every per-battle payload as well as declaration headers; none of the old
content checks or refusal assertions were dropped. The frozen pin generator's
`--check` passed for **1,129 battle pins / 1,056 live pins**; a final regeneration
also produces no tracked difference.

[negative-controls.json](negative-controls.json) records 7 malformed digest
rejections, 4 native CLI/write-error controls (including `/dev/full`), 11 live-pin
schema/coverage rejections and import of the collector without expected pins.
Default native runner assertions still pass. Converter helper ResourceWarnings
from existing `open(...).read()` calls are unchanged and did not fail tests.

## P2: canonical per-battle results

[reference-results-before.json](reference-results-before.json) and
[reference-results-after.json](reference-results-after.json) are **byte-equal**:
10 variants, **2,584 battle executions / 1,129 unique battles**, **11,236 steps**
and **8,458 stops** across the repeated dataset/context variants. Both files have
SHA-256 `712387e820ed6a87f21ac8e047f384abab71fbb80ea99f0e1487a5de846d35e7`.
They contain every per-battle digest, not only dataset aggregates.

The native `--digest-out` implementation lives in `tests/support` and emits one
TSV hash/count row per battle over canonical state, requests, step results, RNG
use, ordered events and tiebreak stops. [observer-agreement.json](observer-agreement.json)
proves native output and the old observer agree **on the same commit `cc8d3fc7`**
for all executions. Observer retirement is the separate subsequent commit
`bc81c141`; `tools/restructure/capture_reference.py` now invokes the built runners
and preserves the baseline JSON encoding. Normal CTest invocations have no flag
and add no engine queries or allocation.

## P3–P6

[verification.json](verification.json) records the proof counts and implementation
commit. [source-hashes-before.json](source-hashes-before.json) and
[source-hashes-after.json](source-hashes-after.json) keep the complete provenance:
only the intended reference generators, generated headers and reference/live
test sources differ. Engine tables, their generator, IDs, ordering, public
headers, binding layouts, perft and bench files are unchanged.

- **P3:** perft passes **10 positions / 24 pinned depths**; pin-file SHA-256
  `90cb0e55b5aed6d2285953338a736b76b7d46e586993b0c5fccceda2230c7c56`.
- **P4:** bench passes **2 cases / 8 roots / 7 searched roots**; BENCH_SHA256
  `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798`.
- **P5:** closure/extended/pool `gen_closure --check`, conformance regeneration,
  tiebreak regeneration and the frozen-pin check pass. Canonical data hashes:
  closure `86ca9d9f548042473c0980c496e9bd6bebbde4b3df0ed10a9ba25aa62316ef5c`,
  team_c `d16b1cef1b41f0a573ae74c10102c932c1f4de0ec3c1f33449f920e533a943e5`,
  pool `9453a57d2ad9ccf4b38aec7d5291f0656f83b8f10515f9136c252816ba4769c3`.
- **P6:** public-header diff is empty; [exported-symbols.txt](exported-symbols.txt)
  retains **238** type/name entries, SHA-256
  `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`.
  [layout.json](layout.json) retains **33 structs / 250 constants**, SHA-256
  `502ecc2e08dc76cf3004d31115948bc4e69d7843ce5cd5d2492d950464e07e8e`.

## Build measurement and dependencies

[build-measurement.json](build-measurement.json): Release+IPO, GCC 14.2,
CMake 4.4.4/Ninja 1.13.2, `--parallel 4`, cloud CPU quota 4. All test/support
object paths were absent before each timed build; engine/tool object files
were cached and dependent executables relinked in both. Baseline compiled
**160 C + 1 C++** translation units; after compiled **165 C + 1 C++**, adding
four reference modules and the digest helper. One warm-filesystem sample each:
**933.881 s before / 790.465 s after (−15.36%)**; new configure time **9.101 s**.
This measures test-side rebuilds, not a clean whole-repository build or CI time.
An initial failed attempt exposed the corrected include path/comment warning;
all test object paths were reset before the successful measurement. No timeout,
test behavior, ordering or parallelism setting was changed.

Dependency audit covered C/C++, Python, CMake, JS, shell, workflows and active
reproduction docs. Header includes remain valid through declarations; raw
spec/trace paths and module paths stay unchanged. The converter's small CLI test
trees now copy frozen battle pins; library checks also compare the decomposed
content. The two native runners and live tests use derived totals. The observer
has no live consumer after replacing its collector. Active reference-tool docs
now explain all three generators and no manual global-count update. Historical
mechanic/benchmark reports remain historical; their old commands are not current
regeneration instructions. No CI selector or test registration change is needed.
C17 warnings-as-errors passed. Coverage has no configured repository gate; UI e2e
is not applicable. Self-review found no blocking correctness/security findings.

## Maintainer slot and merged-main validation

Main `5c99fbd0` (including #445, #446, #447 and the #444 timeout update) was
merged into the pushed branch with a merge commit, never rebased. Its two added
CTest names are inherited; restructure adds/removes **zero** names. The sorted
[test-inventory-main-slot.txt](test-inventory-main-slot.txt) has **1,405** entries,
SHA-256 `23cc8e86a2589d1a5c3430b2ffccc25da796fadf75ff8c4e570cc21b4587ad2c`.
Tier counts: **206 quick + 30 full + 1,151 reference + 18 slow = 1,405**.
The full JSON comparison against main again excludes backtrace locations only.

The merged-head rerun passed **242/242 CTests, 0 failures/skips/disabled**:
236 quick/full tests plus the same six affected reference checks. The full live
suite now runs **53** cases (three inherited CTS pool checks), replay **13**;
the per-battle pin generator again checks **1,129 / 1,056** battle/live pins.
[main-slot-test-results.json](main-slot-test-results.json) and
[main-slot-verification.json](main-slot-verification.json) record this separate
rerun; the original prepared-branch results above are historical. The inherited
CTS tests ran without modification under their unchanged 900-second test limit.

P2 was repeated after the merge: every per-battle result remains byte-equal to
`a9e44f8c` and the observer witness. P6 and engine/data/public/binding/perft/bench
source scope were checked again. [main-slot-proof-surface.json](main-slot-proof-surface.json)
records their equality; neither the PR diff nor the restructure changes the CI
workflow. The Linux JAX job inherits main's **60-minute** limit from #444.
The historical build measurement above remains a comparison against `a9e44f8c`;
it has not been relabeled as a new whole-repository measurement.

## Reproduction

Use Node 22 and exactly the Showdown checkout pinned by `.github/workflows/ci.yml`
(`b2cb775b0616115b775534eaeff50300e1fc81fc`). Configure the existing Python, learner,
Node, Showdown, library and diff-runner variables as in CI/reference-tool docs.
Set `OPENBLAS_NUM_THREADS=1` with multi-threaded OpenBLAS. Keep capture outputs
outside the repository:

```sh
cmake --build build/restructure --parallel 4
ctest --test-dir build/restructure -L '^(quick|full)$' --parallel 4 --output-on-failure
ctest --test-dir build/restructure -R '^duoforge\.(python\.(live|replay)$|reference\.tiebreak_ref$|data\.(closure|extended|pool)_regen$)' --parallel 2 --output-on-failure
python tools/reference/capture_battle_pins.py . --check
python tools/restructure/capture_reference.py . build/restructure <outside-repo-output>
```

[tools/reference/README.md](../../../tools/reference/README.md) gives the explicit
regeneration order. These reports contain aggregate counts, hashes and public
fixture paths only; no private recordings, logs or weights are published.
