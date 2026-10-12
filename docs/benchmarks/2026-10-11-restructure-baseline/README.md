# Restructure step 0: baseline

This records the unchanged engine at `618241aba44b56a57a9cec5f731b70ec7e295521`
before the repository restructure. Step 0 adds evidence and its observation
tooling in this directory only. No files move and no engine, test, generated
data, public header or build registration changes.

## Results (P1–P6)

The final verified inventory has **1,397 distinct CTests passed, 0 failed,
0 CTest skips, 0 disabled**. This is the complete initial run plus the
Python recheck after correcting OpenBLAS configuration, not a claim that the
initial run was clean:

| Run | CTests | Passed | Failed | CTest skips |
|---|---:|---:|---:|---:|
| Full Release+IPO run, automatic BLAS threads, parallel 4 | 1,397 | 1,396 | 1 | 0 |
| All Python tests, `OPENBLAS_NUM_THREADS=1`, parallel 2 | 61 | 61 | 0 | 0 |
| Effective final results, one result per test name | 1,397 | 1,397 | 0 | 0 |

Three existing internal unittest skips remain: the AMD-only teacher byte pin,
the search table byte pin tied to a different Intel CPU, and a Raichu
unsupported-stone negative case that no longer applies because this library
supports every Raichu Mega. No skip was introduced. The complete recheck log,
not JUnit's 1,024-byte success-output excerpt, was inspected for these cases.
The complete counts/reasons are in [verification.json](verification.json).
[test-inventory.txt](test-inventory.txt) contains identical sorted before/after
names; [test-outcomes.tsv](test-outcomes.tsv) records which run verified each.

| Proof | Result |
|---|---|
| P1 | 1,397 before/after, sorted inventory identical (SHA-256 `d798d326d719020f7941c9c2e718a079f26773838f16f4472abe7538b5651a9e`); final outcomes above. The base's full hosted matrix has 12 green jobs; PR-head CI is reported in the PR. |
| P2 | Two captures agree: 10 variants, 2,582 battle executions per capture, 11,230 conformance steps, 8,452 tiebreak stops; per-dataset hashes below. |
| P3 | `duoforge.python.perft` passed in both runs: all 10 positions / 24 depth pins match counts and sequence hashes; [perft-pins.json](perft-pins.json). |
| P4 | Both search-bench tests passed in both runs; 8 roots, 7 searched; observed and pinned SHA-256 `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798`; [bench-signature.json](bench-signature.json). |
| P5 | Closure, Team C and Pool `gen_closure.py --check` pass; canonical SHA-256 values below. All 31 [source/provenance hashes](source-hashes.json) equal the base/current checkout. |
| P6 | Header diff empty. All 238 [exported symbols](exported-symbols.txt) identical before/after (SHA-256 `1b8b33f598fc80e114d3df20fc4632f64d987849fb9101ecd8aebf2f6debd8d5`); all 33 structs / 250 constants in [layout.json](layout.json) identical (SHA-256 `502ecc2e08dc76cf3004d31115948bc4e69d7843ce5cd5d2492d950464e07e8e`); `duoforge.python.layout` passed. |

The base's full hosted CI completed successfully:
[12 passed jobs](https://github.com/chrismaghuhn/duoforge/actions/runs/38170604683),
with the conditional quick-profile guard not applicable. Docs-only path filters
prevent an automatic PR run; this PR requires a full dispatch on its exact head
before merge. Local GCC validation is distinct from that head's hosted matrix.
The optional separate PCG checkout job is not enabled in this local profile.

P5 canonical generated-data SHA-256 values:

- Closure (1,883 bytes): `86ca9d9f548042473c0980c496e9bd6bebbde4b3df0ed10a9ba25aa62316ef5c`
- Team C (2,438 bytes): `d16b1cef1b41f0a573ae74c10102c932c1f4de0ec3c1f33449f920e533a943e5`
- Pool (54,758 bytes): `10f8972473fef6e0e3c3a3f4c29bfd46eca685efcd773943e0671e00b5712f22`

The collector also passed seven rejection controls (missing, incomplete,
nested, mismatched, duplicate or empty battle output; ambiguous insertion).
No production coverage/e2e gate applies to these evidence-only additions.

## Question and gates

Can later moves be checked against a concrete baseline for test registration,
reference outcomes, perft, search decisions, generated data and public surface?
The gates are P1–P6 of `docs/superpowers/plans/2026-10-11-repo-restructure.md`.
No changed pin, skipped required test or behavioural fix is accepted here.

## Setup

Linux x86-64, GCC 14.2.0, CMake 4.4.4, Ninja 1.13.2, Python 3.12.14,
NumPy 2.5.3, JAX/jaxlib 0.11.2 (CPU), optax 0.2.8, Node 22.23.3.
The cloud container has a four-CPU quota and 32 GiB memory. The build uses
Release, IPO, warnings as errors, four parallel build/test jobs, and the
existing checkout. No machine lock or extra worktree is used in this isolated
cloud environment. The owner's PC lock does not apply here.

Showdown is checked out at exactly
`b2cb775b0616115b775534eaeff50300e1fc81fc`, installed with
`npm ci --ignore-scripts --omit=dev`, and built with `node build`, matching
the `linux-full` workflow. Dependencies and run outputs live outside the repo.
The optional separate PCG reference-checkout job is not added to this profile.

The teacher row/batch test needs `OPENBLAS_NUM_THREADS=1` with multi-threaded OpenBLAS.

The Python workflow uses `OPENBLAS_NUM_THREADS=1`. With automatic threaded
OpenBLAS on this Intel CPU, the unchanged `expert_teacher` suite failed its
per-root-versus-tick decision-byte comparison and its three-path tickbench
digest comparison. Restricting SIMD and selecting Haswell kernels alone did
not fix either failure. The supported single-thread OpenBLAS setting made
both original tests pass, with no source, assertion or pin changes. See
[OpenBLAS thread controls](https://github.com/OpenMathLib/OpenBLAS#setting-the-number-of-threads-using-environment-variables).
This setting is saved in the cloud environment configuration/start instructions;
it does not edit or inject settings into GitHub Actions.

The existing `test_two_phase_decision_bytes_pinned` unittest explicitly pins
only the owner's AMD CPU/NumPy combinations and skips its byte comparison on
this Intel CPU. Its cross-shape tests still run. This internal unittest skip
is recorded separately from CTest-level skips; no CPU identity is spoofed.

## P2 digest definition

The stock conformance and tiebreak drivers print aggregate assertion counts,
not per-battle digests. `capture_reference.py` compiles temporary copies of
those drivers using their original compile commands and the same built static
libraries. It inserts only calls from `observe.h`; all original assertions,
reference comparisons and failure exits remain. Missing/ambiguous insertion
points, missing variants, compile errors and failing tests abort collection.
The production library and original test sources are not modified.

For each battle, the observer hashes ASCII records (LF endings, decimal
unsigned integers separated by a trailing space, lowercase hex digests):

- Initial state and state after every successful step: the engine's canonical
  state SHA-256, including gameplay RNG state and draw counter; both players'
  requests, explicit fields and query status.
- Each step's consumed RNG tape count and every step-result field.
- Conformance: both players' complete ordered event fields, including reserved
  bytes; no C struct padding is hashed.
- Tiebreak: every recorded stop's prefix, report/public status, public result,
  result mask and report result, plus live-side counts, HP totals and all
  binary64 percentage bit patterns in the engine's order. Fields undefined
  at terminal stops are not read.

A per-battle digest covers the bytes between its `BEGIN`/`END` markers,
excluding those markers. Each variant's aggregate SHA-256 covers sorted ASCII
`battle-name<TAB>per-battle-sha256<LF>` lines. Dataset identity is the enclosing
variant key. Counts/hashes are checked-in evidence; raw state/event streams,
replays and run directories are not committed. The existing tests compare
these same executions to the pinned reference. These digests are a regression
baseline, not an independent proof of all game rules.

## Observer retirement

Step 2 verified the internal `--digest-out` output against this observer on
commit `cc8d3fc7`: all 10 variants / 2,584 battle executions agreed byte for
byte with the recorded baseline. `tools/restructure/observe.h` is retired;
`tools/restructure/capture_reference.py` now invokes the built runners directly.
The historical encoding definition above is unchanged. The reproduction command
below uses that replacement collector (no compiler instrumentation is needed).

## Reproduction

With the versions above installed, from the repository root (substitute your
own absolute dependency, build and external output paths):

```bash
export PATH=/workspace/duoforge-env/node-v22.23.3-linux-x64/bin:/workspace/duoforge-env/venv/bin:$PATH
export PYTHONPATH="$PWD/python"
export DUOFORGE_LIBRARY="$PWD/build/restructure/libduoforge_shared.so"
export OPENBLAS_NUM_THREADS=1
cmake -S . -B build/restructure -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DDUOFORGE_WARNINGS_AS_ERRORS=ON -DDUOFORGE_ENABLE_IPO=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DPython3_EXECUTABLE=/workspace/duoforge-env/venv/bin/python \
  -DDUOFORGE_PYTHON=/workspace/duoforge-env/venv/bin/python \
  -DDUOFORGE_LEARN_PYTHON=/workspace/duoforge-env/venv/bin/python \
  -DDUOFORGE_PS_REFERENCE_DIR=/workspace/duoforge-env/pokemon-showdown
cmake --build build/restructure --parallel 4
ctest --test-dir build/restructure --show-only=json-v1 > /workspace/duoforge-env/inventory.json
ctest --test-dir build/restructure --output-on-failure --no-tests=error \
  --timeout 120 --parallel 4 --output-junit /workspace/duoforge-env/ctest.xml
python tools/restructure/capture_reference.py \
  "$PWD" "$PWD/build/restructure" /workspace/duoforge-env/reference
python tools/datagen/gen_closure.py /workspace/duoforge-env/pokemon-showdown --check
python tools/datagen/gen_closure.py /workspace/duoforge-env/pokemon-showdown --team-c --check
python tools/datagen/gen_closure.py /workspace/duoforge-env/pokemon-showdown --pool --check
nm -D --defined-only build/restructure/libduoforge_shared.so
build/restructure/duoforge_layout_dump > /workspace/duoforge-env/layout.json
```

CTest includes `duoforge.python.perft`, `duoforge.python.bench` and
`duoforge.python.layout`; no regenerated pins are used. Compare sorted test
names, exported symbol type/name pairs (not linker addresses), canonical
layout JSON and all recorded source hashes. Future steps that move the two
reference drivers must update the collector's source paths/insertion points
while preserving the byte-stream definition above.

The native performance baseline must run alone, after the build and tests:

```bash
build/restructure/bench/duoforge_bench --battles 25 --repetitions 5 --warmup 1 \
  --families step,events,request,copy,codec,episode \
  --out /workspace/duoforge-runs/restructure-baseline-native.json
```

Only aggregate measurements are published here. They describe this cloud CPU
and workload; they do not establish a speedup or general platform performance.

## Path map

No old-to-new paths: step 0 moves no files. All additions are below this
directory. Step 1 starts only after the maintainer merges the baseline PR.

## P2 results

Two independent collector compilations/replays produced byte-identical
`reference-results.json` files (the same unchanged engine libraries). All
original reference assertions passed in both runs.

| Dataset/context | Battles | Conformance steps | Tiebreak stops | Conformance SHA-256 | Tiebreak SHA-256 |
|---|---:|---:|---:|---|---|
| Closure / CLOSURE[_DEV] | 90 | 1430 | 833 | `620dd6f94faa5fc2751158f062c58edf75f48394aba7a9a49e6bc96bf8f9f271` | `b374c2d908d5bd00776a571f7bc6842722f0fb6e6401c9770b3f27001c07e4ea` |
| Team C / TEAM_C[_DEV] | 73 | 1337 | 734 | `1acfad0da5393e2095176d094ab2748800b305cfbfee048e04f127a1720c39c5` | `78e1cb58a1fd273b438d99fb9d5db2bdc876b174da5bc73339bc002b2de7fb34` |
| Closure / POOL[_DEV] | 90 | 1430 | 833 | `2e18471bd9ca62169b1d19d758d3ebe6477eedf7670c0e4485cd963d0419edfa` | `9b9dd739a1ae0258b370dd98c8967dfdd8598f681670877e29100c68559ed2e4` |
| Team C / POOL[_DEV] | 73 | 1337 | 734 | `6962a5b69387c839398ff0d902176eed5692c842a5bc74b610833c330999dc96` | `d0c365b69fa0ac3e41454297906cd5c09f39fdd0c3badc08395b77dff6c8fc07` |
| Pool / POOL | 965 | 5696 | 5318 | `009403449acc5babb2acc51cda40e06f266b1e817edbe05463ccb1a761921843` | `c6a477a17a25553f23bcb7b12db7c438394c02eb895107d83ee21fe9093df976` |

Each capture executes 1,291 battles per driver (2,582 total), covering 1,128
unique committed reference battles. Conformance checks 11,230 steps; tiebreak
checks 8,452 stops, with zero ambiguous stops. The full per-battle count/hash
records and original check summaries are in [reference-results.json](reference-results.json).
The SHA-256 of that file is
`0de0b4b243d2b8e2fff43245b217357e9c42613d4229c41c9f82ae69766d056f`.

## Native benchmark baseline

Ran without other builds/tests between the completed full run and the Python
recheck. The workload records **100 battles, 1,773 steps, 1,285 turns** with
**zero errors or truncations**. One warmup and five measured repetitions per
family/variant, one worker; zero disturbed repetitions and no time-limit skips.

| Family / variant | Median wall ms | Wall range ms | Rate |
|---|---:|---:|---|
| STEP_CORE / plain | 14.518 | 14.180–16.353 | 122,125 steps/s |
| STEP_CORE / events | 15.914 | 13.646–20.099 | 111,411 steps/s |
| REQUEST / request+candidates+observe | 9.659 | 9.459–10.752 | 367,120 calls/s |
| SNAPSHOT / copy | 0.114 | 0.109–0.139 | 15,610,554 calls/s |
| SNAPSHOT / codec | 3.637 | 3.336–3.767 | 487,511 calls/s |
| EPISODE_NATIVE / uniform-random | 23.797 | 23.629–26.930 | 74,506 steps/s |

[native-benchmark-summary.json](native-benchmark-summary.json) retains aggregate
counts, medians/ranges, seeds, compiler/flags/IPO, CPU, context fingerprint and
binary hash. Raw samples, action logs and run output directories remain outside
the repository. These short samples describe this cloud CPU/workload only;
they are not a regression threshold, owner-machine comparison or speedup claim.
