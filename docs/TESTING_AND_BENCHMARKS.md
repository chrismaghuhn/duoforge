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
- The Python package tests (label `python`, M7) run in Windows GCC Debug when the project venv `.venv` exists, and in Linux GCC Release with LTO when `~/df-venv` exists (`tools/ci/linux_ci.sh --setup-python` creates it after `sudo apt install python3.12-venv`). Without an interpreter (`DUOFORGE_PYTHON` empty) they report skipped.

The pull request states the result.

**Hosted CI again on pull requests (2026-10-02).** The repository is public, so hosted minutes are free. `.github/workflows/ci.yml` runs on pull requests to main (not on drafts), on pushes to main, nightly and on demand. A newer push cancels the older run, and a change to docs only runs nothing. It runs:

- the Linux matrix: GCC Debug, Clang Debug and Clang Release;
- one GCC Release job with link-time optimization that also runs the Python tests, the learner's JAX test (CPU) and every reference test against the pinned Showdown (Node 22);
- GCC ASan+UBSan and Clang TSan;
- MSVC x64 Release, x64 Debug and Win32 Release;
- Windows GCC Debug (MSYS2 UCRT64) with the Python tests and every reference test (Node 22, Python on Windows);
- Windows GCC Release with link-time optimization, and Windows Clang Release (MSVC target).

The RNG reference runs weekly and when its files change in a pull request or on main.

**The hosted CI is the merge gate since 2026-10-02 (owner).** A pull request is merged when every check on its head is green. The main session reads them with `gh pr checks`. The local CI (`tools/ci/local_ci.sh`) stays for quick runs before a push (`--quick`), for offline work and for measurements. A session no longer needs the machine lock to get a pull request merged.
