# Implementation roadmap

Every milestone is a separate authorization boundary. A milestone may require multiple small tasks. Prefer one implemented contract with tests per task, not a single prompt asking for an entire engine.

No hosted CI, benchmark or rules certificate exists yet. All exit gates below are future requirements.

## M0 — Workspace, build and development foundation

Implement C17 CMake setup, a tiny core library, a smoke-test executable, CTest registration, documented local builds and initial CI configuration. Establish warnings, bounded execution and a minimal public version/status surface. Add source/coverage manifest scaffolding with explicit UNPINNED/UNSUPPORTED status.

Exit: actual available-platform Debug and Release builds and smoke tests pass; project structure and task boundaries are documented. Unavailable platforms are NOT_RUN. No combat, RNG, Python package or fake passing battle stubs.

Use `tasks/M0_BOOTSTRAP.md`.

## M1 — Deterministic primitives and owned state

Pin and implement the RNG choice and known-answer vectors; explicit arithmetic helpers; roster/position identities; state initialization and invariants; basic canonical codec/digest support and owned state cloning. Establish context compatibility and checked capacities. Add only fields justified by the initial requests/mechanics rather than an imagined complete Pokédex.

Exit: RNG, codec, invariant and clone tests; malformed-input atomicity; clear schema/semantics identifiers for artifacts that actually exist. State snapshots are foundation evidence, not proof that unimplemented future mechanics restore correctly.

## M2 — Requests, joint commands and information boundary

Implement team-selection/request types, complete joint-command validation/enumeration, request epochs, a perspective-safe observation prototype and simultaneous-choice collection semantics. Use explicitly synthetic request fixtures where combat is not yet available. Test constraints for reserve conflicts and side-wide resources.

Exit: exhaustive small-fixture domain tests, information-equivalence tests, stable enumeration and zero gameplay RNG consumption by queries. There must be no fake assertion that the engine already plays correct Pokémon.

Before M3, select the two concrete teams, operational reference commit, rules/information profile and conservative mechanics inventory. This is a small focused selection/review task, not a global census system.

**Owner decision (2026-09-30):** M3 and M4 are executed as one continuous build with no backlog, in the dependency order of `docs/research/mechanics-inventory.md` section 5. The descriptions of M3 and M4 below remain the content; `tasks/M3_M4_COMBAT_CLOSURE.md` is the task statement. M5 and later stay separate authorization boundaries.

## M3 — First combat vertical slice

Implement the selected foundational damage/stat/PP primitives, normal move execution, the necessary immediate effects, switching, faint processing and turn progression. Include implicit behaviors reachable in the slice such as PP exhaustion. Implement the scheduler/continuation structure even before every mid-turn effect exists.

Exit: pinned deterministic reference fixtures, reproducible native traces and replay across ordinary turns. Development fixtures may play out end-to-end, but the full selected matchup remains uncertified if dependencies are missing.

Do not represent an ignored ability, simplified rounding or absent item behavior as a valid competitive game.

## M4 — Doubles mechanics closure

Implement only the selected teams' required interactions: targeting/spread logic, protection, shared transformations when applicable, redirection, priority/dynamic speed ordering, pivot/replacement pauses, status/weather/terrain, items, abilities and ordered residuals as required by the actual inventory.

Split this milestone into dependency-ordered mechanic tasks. Every task includes negative cases, interaction tests and pause/replay tests where applicable. Record source uncertainty rather than inventing behavior.

Exit: every dependency of the declared slice has implementation and test evidence; continuation/restoration and model-visible information behavior pass; no silent unsupported paths. A simplified profile must stay explicitly labeled.

## M5 — First fixed-matchup certification

**Status 2026-10-01:** done for the closure matchups (decision 0010); report `docs/certification/closure-v1/README.md`.

Freeze exact team specifications, rules and information profiles, source pins and the evidence manifest. Run deterministic reference scenarios, controlled-RNG conformance tests, bounded randomized native play, replay verification and failure minimization.

Certification is scoped engineering evidence, not a mathematical proof of every reachable state. Record residual known limitations. Exclude an unsupported setup or change the named profile; do not weaken real rules invisibly.

Exit: a reproducible small certified matchup dataset and test report, with no unresolved known mismatch in the certified scope. Anything requiring unimplemented semantics remains rejected.

## M6 — Batch runtime and measurement

**Status 2026-10-01:** done for the synchronous runtime (decision 0012); report `docs/benchmarks/2026-10-01-batch-scaling/README.md`.

Add resident environment arrays and a worker pool outside the rule core. Reuse per-worker scratch; keep RNG per environment; support heterogeneous request kinds and completed environments. Define deterministic reset-seed derivation and atomic per-environment outcomes.

Start with configurable 1, 2, 4, 8 and larger environment counts as hardware allows, not a hard-coded promise of thousands. A thread is not an environment. Compare worker schedules using identical per-environment commands and seeds.

Exit: single/batch semantic equivalence, reproducibility independent of scheduling, no race findings on tested paths, bounded memory and a reproducible Release benchmark report. Optimization cannot reduce mechanics, candidate completeness or information guarantees.

## M7 — Python ML adapter and trusted trajectories

Add a thin C ABI binding, packed observation and candidate batches, random/scripted baseline drivers and a trajectory exporter. Store policy/opponent IDs, roles, RNG provenance, schema versions, request identifiers, selected canonical commands and outcome/truncation semantics. Keep provenance separated from features.

Exit: native-versus-binding equivalence, trajectory-to-replay checks, no hidden-information features and a small bounded generation example. A trained model is not needed to pass this milestone.

Status: done 2026-10-01 (decision 0013 section 8). The Python package `python/duoforge` drives the batch runtime over ctypes and NumPy; the Python loop equals the native mode byte for byte, recipes replay to features, and the encoder reads only the viewer's observation.

An initial candidate-scoring learner may follow in a separate task. Selecting PPO, recurrent architectures, search or leagues is not part of the engine gate.

## Later

Additional certified teams, broader regulation profiles, recurrent agents, belief-conditioned hypothetical search, best-of-three orchestration and external clients. Add these based on measured needs, not speculative scaffolding.

## Review standard for every slice

A useful completion report includes scope, changed files, test commands/results, unresolved uncertainty, actual artifact paths and proposed next task. Distinguish implemented code, locally tested behavior, hosted CI and certified mechanics. Passing smoke tests never imply a completed rules engine.
