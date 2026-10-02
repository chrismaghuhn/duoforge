# Testing, conformance, diagnostics and benchmarks

## 1. Test layers

### Unit and arithmetic tests

Test integer rounding, modifier order, type/stat calculations, RNG consumption, PP transitions, state invariants and individual effects. Use independently derived or reference-derived expectations; do not merely run the implementation once and call its output the expected answer.

### Interaction and continuation tests

Examples to implement when the selected slice contains them: protecting one target of a spread move; redirection interacting with targeting; speed changes affecting remaining actions; an actor fainting before its queued move; pivoting with pending opponent actions; replacement into an occupied identity; recoil/residual fainting; simultaneous resource conflicts.

Expected outcomes must be derived from the pinned operational reference and reviewed. These examples are a test inventory, not a statement that their detailed outcome is already specified here.

### Determinism and replay tests

Restore at every exposed decision kind. Replay the same canonical inputs with the same context and RNG. Compare canonical state, public requests and authorized observations. Test diagnostics enabled/disabled and single-worker/multi-worker paths. Cross-compiler comparison is a declared CI goal, not an achieved result.

### Information-boundary tests

Construct paired states/histories with equal authorized information and different unrevealed values. Compare observation bytes, candidate encodings/order/count, errors and visibility. Permit differences only at a rule-authorized disclosure point. Include sealed opponent choices and privileged state digests in leak tests.

### Capacity, fuzz and property tests

Fuzz the public boundary and codecs with validated allocation bounds. Test invalid indices, stale epochs, duplicate reserve selections, illegal transformation combinations, all-fainted/terminal behavior and undersized buffers. Check invariants after successful transitions and unchanged committed state after API errors.

Use suitable compiler sanitizers and static analysis on supported configurations. Record toolchain/version/platform and limitations; do not mark a sanitizer PASS where it was not run.

## 2. Differential testing against Showdown

The operational reference is one pinned revision with fixed data/profile configuration. The normal core does not embed Node or start a server.

A separate local test adapter feeds equivalent initial conditions and canonical choices into the reference, normalizes comparable semantic outputs, and compares the expected state/events at defined boundaries. Human log string equality is not the only correctness criterion; do not discard all event ordering information either.

Randomness needs explicit alignment. Identical seed strings do not produce parity by themselves. Start with deterministic scenarios and targeted random outcomes. Validate a semantic RNG tape/adapter independently, including call-site purpose and number of draws. Document any normalization that could conceal a mismatch.

On disagreement, save the smallest reproducible fixture, pinned versions, both traces and the first mismatching semantic field. Do not automatically change golden files to match the new code. Showdown is a reference implementation, not an infallible oracle for cartridge behavior.

The fuzz corpus (decision 0015 section 6) keeps what the differential loop's random play found worth keeping: `tests/reference/corpus/` holds, for each battle, its choices spec and its trace gzipped, at most about 20 MB in all (what would grow beyond it moves to a release artifact). A battle is promoted (`diff_driver.py promote`) when it found a defect (as the shortest prefix that shows it, once the fix exists: until then it is a regular fixture with its fix) or when it adds a protocol line with its effect, a draw site with its context or a request situation that no committed battle and no corpus battle has. `duoforge.reference.corpus` replays every corpus battle through the converter and the runner of the build from the stored traces, without Node, and each must PASS: it runs in every CI job, the sanitizer jobs included. `duoforge.reference.corpus_size` holds the layout (no orphan, a purpose that says why, traces of the pinned revision, under the cap). See `tools/reference/README.md`.

## 3. Coverage evidence

A coverage report should distinguish:

```text
entity present in data
mechanic identified
handler implemented
unit cases pass
interaction cases pass
request/privacy behavior passes
replay/restore passes
certified under a specific fixed profile and matchup
```

Do not aggregate these into a misleading single 'Pokémon supported' count. Fixed-team closure review includes implicitly invoked mechanics and all enabled configuration choices, not just one successful random rollout.

## 4. Benchmark families

| Family | Measures | Important exclusions/conditions |
|---|---|---|
| STEP_CORE | Native boundary-to-boundary execution | Fixed command source; report included validation/event work |
| REQUEST | Candidate enumeration and observation building | Same profiles and information policy |
| SNAPSHOT | Copy and restore cost | Same-build compatibility; report state/scratch sizes |
| EPISODE_NATIVE | Full native battles | Report reset, policy cost, turns/decisions and truncations |
| BATCH_NATIVE | Resident environments with workers | Same per-env semantics and diagnostic mode |
| ROLLOUT_END_TO_END | Binding, inference and trajectory work | Report policy/device/batch/encoding costs |

Collect battles/s, logical turns/s, decision boundaries/s, submitted side decisions/s and clearly defined internal transitions/s. Do not compare two undefined 'steps/s' counters. Also record elapsed CPU/wall time, peak memory, allocation counts, environment count, worker count and batch fill behavior.

The first benchmark establishes a baseline. No speculative target such as 5,000 Gen-9 doubles battles/s/core is a release requirement.

As built (decision `0008`): `bench/` measures STEP_CORE, REQUEST, SNAPSHOT and EPISODE_NATIVE on the workload `closure-pairings-v1` and counts what each side's policy chose (`dfb_tally`); a repetition whose process CPU time stays well below its wall time is reported as disturbed.

## 5. Reproducible workload manifest

Record engine revision, dirty-worktree flag, binary hash when useful, compiler/flags/build mode, OS, CPU, actual worker count/affinity, teams, profiles, source data hashes, RNG seed set, policy implementation and seed, warmup procedure, measured repetitions and logging mode.

Use Release builds for performance comparisons. Keep validation and rules coverage equal across variants. Warm up where relevant, run repetitions and report variation. Prefer paired workloads or identical canonical action tapes when comparing engine changes; random-policy action sequences can change when domains change.

Report game-length distributions, failures and truncations alongside battles/s. Faster completion from invalid early termination is not an improvement. Linear multiplication of one-core throughput by a CPU's advertised thread count is not a measured scaling result.

## 6. Diagnostics must exist

Support FULL semantic traces, bounded COUNTERS and OFF/production diagnostic modes as justified. Semantic events required for knowledge/observations are not optional diagnostics. Turning verbose logs off must not remove information updates or RNG calls.

Useful counters include battles started/completed, current environment and request, turns and transitions completed, maximum queue/effect depth, capacity failures, RNG draws, last-progress timestamp and worker status. A 'process responding' flag alone does not prove simulation progress.

Long-running drivers must offer explicit finite limits, regular progress, safe interruption and failure artifacts. Proposed CLI shape (not implemented commands):

```text
pbd-bench --workload fixed-matchup-v1 --max-battles 1000 --max-seconds 30 --progress-seconds 2
```

The example values are bounded development defaults, not promised performance. Keep finite per-episode turn/decision safeguards as well. A guard hit is recorded as operational truncation or engine error, never silently as a rules draw.

Profilers, debuggers, stack sampling, sanitizer runs and additional counters are authorized diagnostic techniques within the current task's repository/safety limits. Do not write prompts that forbid all diagnosis while demanding long unattended executions.

## 7. CI progression

M0: available-platform C17 build and smoke tests, with a proposed Windows/Linux workflow.

M1–M4: focused unit, invariants, determinism and information tests; sanitizer configurations where supported.

M5: bounded conformance suite with pinned local reference inputs and replay fixtures. Keep slow cases separately labeled and bounded.

M6–M7: single/batch/binding parity and trajectory integrity. Performance jobs report baselines; a hard regression gate should be introduced only after variance and workload stability are characterized.

Remote CI is PASS only after observing an actual run on the relevant revision. Configuration files alone are not evidence.

**Local CI as the merge gate (2026-10-01).** GitHub Actions on the free plan cannot carry a run per pull request, so a pull request is merged on a green local CI: `tools/ci/local_ci.sh` (Git Bash on the owner's Windows machine) runs the matrix of the former hosted CI and more, writes logs to `build/ci/` and exits non-zero on any failure.

- Windows: GCC Debug (with the Showdown reference traces when the pinned checkout exists), GCC Release with LTO, Clang Release, MSVC x64 Debug, MSVC x64 Release with LTO, MSVC Win32 Release.
- Linux in WSL (`tools/ci/linux_ci.sh`, builds under `~/df-build/ci`): GCC Debug with ASan and UBSan, Clang Debug, GCC and Clang Release with LTO, Clang with ThreadSanitizer for the batch tests.
- `--quick` runs Windows GCC Debug, MSVC Release and Linux GCC ASan+UBSan; `--no-linux` skips WSL.
- Several sessions share the machine: `local_ci.sh` takes the machine lock (`tools/ci/machine_lock.sh`, a lock directory in the user's temp folder) and a second run waits; benchmarks can take it too (`tools/ci/machine_lock.sh <label> <command...>`). The Linux jobs build under `~/df-build/ci/<checkout>-<hash>`, one directory per checkout or worktree.
- Fuzz runs of the differential loop (`tools/reference/diff_driver.py random`) go in chunks of at most 10 minutes, each under that same lock, with the lock free for 30 seconds between two chunks, so that a CI or a benchmark that waits gets it. **Measurements pause the fuzzing completely, with a pause file.** Its path is `$DUOFORGE_FUZZ_PAUSE`, by default `duoforge-fuzz.pause` in `$TEMP` (`%TEMP%` on Windows, `/tmp` where `TEMP` is not set). The driver (`diff_random.py`) looks for it before it starts a chunk and again right after a chunk has the lock; while it exists the fuzz holds no lock and starts no chunk, logs one line `fuzz paused by <path>` and looks again every 15 seconds (a chunk that finds the file after it got the lock leaves at once, with status 75, which gives the lock back). **A measurement creates the file before it takes the lock and removes it afterwards, whatever happens**: `pause=${DUOFORGE_FUZZ_PAUSE:-${TEMP:-/tmp}/duoforge-fuzz.pause}; touch "$pause"; trap 'rm -f "$pause"' EXIT; tools/ci/machine_lock.sh bench <command...>` in Git Bash; in PowerShell make `$env:DUOFORGE_FUZZ_PAUSE`, or `$env:TEMP\duoforge-fuzz.pause`, with `New-Item -ItemType File -Force` and remove it in a `finally`. A chunk that is already running is not stopped (it ends within its 10 minutes, and the measurement waits for the lock as it always did); what the file stops is the next one. Runs with `--no-lock` (CTest inside `local_ci.sh`) ignore the file: they hold no lock to give back, and a pause made while a measurement waits for the lock that the CI holds must not stop that CI.
- The Python package tests (label `python`, M7) run in Windows GCC Debug when the project venv `.venv` exists, and in Linux GCC Release with LTO when `~/df-venv` exists (`tools/ci/linux_ci.sh --setup-python` creates it after `sudo apt install python3.12-venv`). Without an interpreter (`DUOFORGE_PYTHON` empty) they report skipped.

The pull request states the result. The hosted CI runs nightly on main (Clang Release, GCC ASan+UBSan, Clang TSan, MSVC x64 Release) and on demand; the RNG reference weekly and when its files change on main.
