# Project instructions

## Scope and authority

This is the separate `pokemon-doubles-core` project (working name), a C17 headless Generation-9 doubles simulation core for ML and search workloads. Start with two fixed teams and an explicitly bounded mechanics closure. Do not build all generations or all Pokémon at once.

Read the current task, `docs/ARCHITECTURE.md`, and the relevant contract before editing. Architecture v0.1 is a proposal; implemented and tested decisions become binding through a small reviewed decision note. Do not silently change an established contract.

Inspect the workspace, Git status and remotes before writes. Never modify Manafold, OCGForge, Argentum Engine or an upstream reference repository. Do not overwrite unrelated or uncommitted files. Do not create remote repositories, push, open PRs or merge without authorization.

Implement only the assigned slice. A roadmap entry is not authorization to execute it. Do not automatically start the next milestone, a large soak, training or an online battle client.

## Core design rules

- Portable C17 for authoritative simulation. Python may provide offline tooling and later ML bindings; it must not implement parallel combat rules.
- No GUI, network, database, Python interpreter or GPU dependency in the core.
- No mutable globals, global RNG, clock-derived game behavior or allocation-address-derived identifiers.
- Keep immutable data/context separate from pointer-free owned battle state and reusable scratch storage.
- A pointer-free state is an architectural goal, not a portable file format. Never serialize or hash raw C struct bytes.
- Use explicit fixed-width integer arithmetic, defined rounding, checked capacities and validated indices. No signed overflow or undefined shifts.
- Do not implement generic ECS, scripting VM, plugin system, networking protocol or universal event bus without a separate justified task.
- No silent unsupported-mechanic fallback, placeholder damage, ignored ability, dropped event or truncated candidate list.
- No raw full-state pointers, seeds, privileged digests or pending opponent commands in model-facing data.
- Debugging, tracing and profiling are allowed and expected. Do not impose a blanket ban on diagnostic tools.

## Changes and evidence

Add regression tests for every supported mechanic and every fixed bug. Test malformed-input failure atomicity separately from rule-authorized choice rejection/revelation. Preserve simultaneous-choice secrecy and the complete player-selectable command domain of the declared profile.

A fixed-team certificate must include reachable mechanics, including implicit behavior such as PP exhaustion/Struggle and effects that generate or copy other effects when present. An item or move appearing in a data table is not proof of implementation.

Pin reference source revisions and dependency versions before relying on them. Record provenance and preserve applicable notices for any imported material. Do not invent a project license or assume external assets have the same permissions as engine source code.

Prefer one focused, reviewable change over a broad speculative framework. Public API sketches are provisional until their slice implements and tests them. Do not freeze dozens of unused versioned contracts.

## Execution discipline

Every executable test/benchmark must have a finite case count or documented logical budget. Long-running tools additionally need progress output, wall-time limits, safe cancellation and a reproducible failure artifact. Timeouts/truncations are not in-game draws.

Report exact commands, actual outcomes and elapsed times. Distinguish PASS, FAIL, NOT_RUN and BLOCKED. Hosted CI is not PASS merely because a workflow file exists. Never fabricate measurements or test results.

At task completion report: files changed, implemented scope, tests run, tests not run, unresolved issues and the proposed next slice. Stop there.
