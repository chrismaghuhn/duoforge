# Restructure step 1b-2: tiers and areas

Can tests be selected by tier/area while preserving every existing CI selection?
Yes: all 1,403 names and every command, working directory, environment, timeout,
fixture/dependency/scheduling property and registration order match `d19839e3`.
Only labels and their CI selectors change. The hosted PR-head matrix remains the
merge gate; local checks and successful baseline CI do not replace it.

## Tier rule and measurements

Apply in order: pinned Showdown/Node dependency → `reference`; otherwise JAX
learning dependency or at least 120 seconds → `slow`; otherwise less than five
seconds → `quick`; otherwise `full`. Typical duration is the median of two
complete, successful Linux Release CTest runs on exactly the baseline:
[38239492848](https://github.com/chrismaghuhn/duoforge/actions/runs/38239492848)
and [38210931789](https://github.com/chrismaghuhn/duoforge/actions/runs/38210931789).
Both ran all 1,403 tests. [test-labels.csv](test-labels.csv) lists both durations,
the median, required fixture cost, tier, area and auxiliary selectors per test.
No duration is inferred from a skipped fallback.

Required fixture setup contributes to a consuming test's duration. The three
`runner_records*` tests and `dump_views` take only 0.035–1.2 seconds themselves,
but require `records_write` (median 18.805 seconds), so all five belong to `full`.
This keeps `ctest -N -L <tier>` counts disjoint even when CTest adds fixtures.
Fixture properties are unchanged. Optional PCG tests need the pinned PCG C
checkout, not Node/JAX: both are `quick` (0.01/0.02 seconds in baseline RNG CI).
Optional sanitizer canaries are `quick`/`tools`.

| Tier | `ctest -N -L '^<tier>$'` count |
|---|---:|
| quick | 204 |
| full | 30 |
| reference | 1,151 |
| slow | 18 |
| Sum | 1,403 |

Borderlines (median seconds): residual shards 0/1/2/3 = 3.720/5.280/3.595/4.230;
`bc_numpy` 4.405 and `learn_numpy` 3.525 are quick; `expert_data` 6.905,
closure/team-C gates 7.330/7.835 and GCP guards 7.875 are full. Dependency
precedence matters: `random_teams_pin` 3.195 remains reference, and JAX
`pkmn_arena_net` 36.755 and `learner_contract` 35.075 are slow. Non-JAX
`positions` 372.095 is slow. `live`/`replay` 144.385/141.925 remain reference.

## Selection proof

[ci-test-sets.json](ci-test-sets.json) lists the complete sorted **before and after
names for each of all 12 matrix jobs**, the RNG job, MSVC bitness recheck, both
skip guards, presence checks, trace counter, and retained labels. Each pair is
asserted equal and includes a SHA-256 of LF-terminated sorted names. The
conditional quick-profile guard selects no CTests and is unchanged.

The new `ci-*` selectors are independent of tiers and areas. Existing `python`
(63), `bench` (3), `certify` (5), and `sanitizer-canary` (2 in ASan) selections
stay equal. The old dependency label `learn` becomes `requires-jax` (same 17);
`learn` now means the Python folder area. No workflow selected the old `learn`
label. Full-profile `reference` retains the same 1,151 tests. In the no-Showdown
PCG profile, `reference` now correctly labels the two Python fallback tests;
RNG CI selects `ci-rng`, preserving its two native PCG checks.

[profile-comparison.json](profile-comparison.json) records before/after CTest
JSON comparisons for six configurations (including absent interpreter/JAX
fallbacks, ASan, TSan and PCG). Only LABELS and registration backtrace locations
differ; test order and every runtime/scheduling property are identical. Generated
`add_test` commands are also compared, including executables not built in the
optional profiles. Full
Windows selection is additionally checked against the actual baseline Windows
CI log, not inferred from the Linux configuration alone.

The label-based skip/presence checker accepted the complete real Linux and
Windows CI logs. It also passed 28 rejection/allowance controls: skipped ordinary
checks on both platforms, Linux JAX rejection versus Windows allowance, each
of 19 missing Linux-required rows, and an empty trace set. No test is rerun or
filtered by that checker.

## P1–P6 and setup

Main `7f9ee4da` (#439) was merged into this branch without rebase. Inventory,
commands and labels still match the recorded baseline. The affected `honest`
and `live_search` tests, benchmark signature, repository hygiene and source
lint were rechecked: all five passed, zero CTest skips. The PR diff contains
no engine or Python module/test implementation changes against that main.


[verification.json](verification.json) contains the proof counts and hashes.
The baseline sorted [inventory](test-inventory.txt) has SHA-256
`ab415dad8fa1b4923bcc60cfd9715d5e66036693696ca7e1c01deead10b8fd40`.
Local combined quick/full: 234 passed, 0 failures, 0 CTest skips, 207.05 seconds;
PCG: 2 passed. Perft, benchmark signature and layout passed in the subset.
The complete 1,403-test local JAX/reference suite was not rerun: the measured
full baseline logs and required hosted PR-head matrix cover the full suite.

Two fresh [reference captures](reference-results.json) (baseline and labelled
checkout) agree for all 10 variants: 2,584 battle executions, 11,236 conformance
steps and 8,458 tiebreak stops. [Source hashes](source-hashes.json) cover 33
unchanged public/generated/reference/provenance files. All three generator
`--check` modes passed. [Exports](exported-symbols.txt) (238) and
[layout](layout.json) (33 structs, 250 constants) agree with the fresh baseline.

Cloud Linux x86-64, GCC 14.2.0, CMake 4.4.4, Ninja 1.13.2, Python 3.12.14,
NumPy 2.5.3, JAX 0.11.2 CPU, optax 0.2.8, Node 22.23.3. Release+IPO,
warnings as errors, four test workers, `OPENBLAS_NUM_THREADS=1`. Showdown:
`b2cb775b0616115b775534eaeff50300e1fc81fc`; PCG:
`bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3`. Raw logs, builds, temporary
observer executables and outputs stay outside the repository. These files
contain only aggregate proof data, test names and per-battle hashes.

Reproduce using the step-0 README's dependency/build configuration, then:

```bash
ctest --test-dir build/restructure -N
ctest --test-dir build/restructure -N -L '^quick$'
ctest --test-dir build/restructure -N -L '^full$'
ctest --test-dir build/restructure -N -L '^reference$'
ctest --test-dir build/restructure -N -L '^slow$'
ctest --test-dir build/restructure --show-only=json-v1
OPENBLAS_NUM_THREADS=1 ctest --test-dir build/restructure -L '^(quick|full)$' --parallel 4 --output-on-failure
python tools/restructure/capture_reference.py "$PWD" "$PWD/build/restructure" /tmp/duoforge-label-proof
python tools/datagen/gen_closure.py /path/to/pokemon-showdown --check
python tools/datagen/gen_closure.py /path/to/pokemon-showdown --team-c --check
python tools/datagen/gen_closure.py /path/to/pokemon-showdown --pool --check
```

Coverage-skill applicability check: no configured coverage gate/report for
CMake or CI metadata; a CI-tool coverage target would be a separate addition.
No product flow changed, so no e2e generation applies. Existing functional
checks, CI-log controls, shell syntax and source lint pass; self-review found
no blocking correctness or security finding. No secret/dependency change.

## Extraction map and dependency audit

No existing file moves. Seven remaining central registration blocks were
extracted in a separate commit before labels, retaining their original include
positions. [registration-extractions.json](registration-extractions.json)
records exact old lines in `tests/CMakeLists.txt@d19839e3` and new files.
No test implementation, assertion, expected value, pin, generated file,
engine source or public header changed.

Audit: repository CMake registrations, CI workflows, shell helpers and docs
were searched for label/regex selections. TSan, MSVC smoke, Linux/Windows
skip/presence guards and RNG CI change selectors; `tools/ci/linux_ci.sh` changes
its TSan selector; README's PCG command follows RNG CI. Existing `-L python`
usage retains the same set. Historical named-test reproduction commands still
work because names are unchanged. There are no source-path moves/dependencies
in this PR.

## Timeout proposal only

The measured scheduled Linux full job took 39m09s end to end; CTest took
1,604.33 seconds (the push run 1,589.52 seconds). The largest JAX check,
`learn_v2`, has median 740.23 seconds. A separate experiment could prioritize
long JAX/positions checks (for example estimated CTest COST) to improve packing
with four workers. CPU contention and setup/build time require measurement;
no speedup is claimed. This PR changes no COST, PROCESSORS, RUN_SERIAL,
registration order, timeout, parallelism or test behavior.
