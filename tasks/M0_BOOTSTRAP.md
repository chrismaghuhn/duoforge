# Codex task: M0 — Bootstrap the separate Pokémon Doubles C engine

## Goal

Create the smallest buildable foundation for a portable C17, headless, deterministic Pokémon doubles battle engine intended for ML. Implement **M0 only**. Do not implement combat, RNG, a Python binding or a learner in this task.

The working project name is `pokemon-doubles-core`, with C symbol prefix `pbd_`. The long-term target is Generation 9 doubles, initially two fixed teams and an explicitly bounded rules closure, not all Pokémon or all generations.

## Workspace safety

Work only in the dedicated workspace opened for this new project. First inspect the directory, existing instruction files, Git status and configured remotes. Do not edit Manafold, OCGForge, Argentum Engine or any reference upstream repository. Preserve unrelated/user changes. Do not create a remote repository, push, open a PR or merge.

If the current workspace is clearly an unrelated existing project, stop before writes and report the mismatch. Otherwise proceed with the dedicated local bootstrap; do not block on future team/regulation/RNG choices that M0 does not need.

## Read first

Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/TESTING_AND_BENCHMARKS.md` and `docs/OPEN_DECISIONS.md`. The other documents provide future contract context. Do not treat future milestones as permission to implement them now.

## Implement

1. A minimal CMake project with C17 selected, a static core library, a small smoke-test executable and CTest registration. Set a documented supported CMake version and do not claim untested compiler compatibility.
2. A minimal public header under `include/pbd/` with only buildable version/status information needed for the smoke test. Do not freeze the future BattleState layout, public step API or replay schema prematurely.
3. Initial source directories for core work and tests. Add directories/files only when they have a purpose; avoid dozens of empty modules.
4. Reproducible local build instructions for Windows and Linux, with Debug and Release configurations/presets appropriate to the supported generators. Compiler warning settings must be compiler-specific. Do not apply GCC-only flags to MSVC.
5. A bounded smoke test proving the library links and its actual implemented version/status query works. No tests that claim simulated Pokémon correctness.
6. Initial CI configuration for Windows and Linux. Add a supported sanitizer configuration where practical and explicitly report if it is not executed here. Keep all jobs finite.
7. Source/support manifest scaffolding that clearly says UNPINNED and UNSUPPORTED where applicable. Do not invent source hashes, chosen teams, regulation identifiers or completed coverage.
8. Update the README with actual commands and the distinction between implemented foundation and future engine functionality.

## Hard boundaries

No damage formula, battle scheduler, generic event bus, complete Pokédex import, Pokémon Showdown server, public server access, GPU dependency, trainer, search algorithm or performance claim.

Do not add broad dependencies for hypothetical later needs. Do not create stubs where a nonexistent battle operation returns success. Do not fetch or vendor large datasets. Do not select a project license on the owner's behalf.

Diagnostic tools are allowed. Do not start long tests without bounded work, progress and a timeout. For this small bootstrap, each command should have a conservative tool timeout; investigate a stall instead of allowing hours of silent execution.

## Validation

Run the actual available-platform Debug and Release configure/build/smoke-test commands. Inspect the final diff. Mark unavailable-platform checks and hosted CI as NOT_RUN unless actually observed. A workflow file is not a successful remote CI run.

No benchmark target is required; M0 does not yet simulate battles and cannot produce meaningful battles/s.

## Final report

Report:

- workspace identity and whether unrelated files remained untouched;
- changed files and implemented scope;
- exact build/test commands with PASS, FAIL, NOT_RUN or BLOCKED;
- unresolved issues or portability risks;
- the proposed next small M1 task.

Stop after M0. Do not automatically implement M1, launch training or perform remote writes.
