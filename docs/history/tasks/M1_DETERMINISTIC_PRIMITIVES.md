# Task: M1 — Deterministic primitives and owned state

## Goal

Implement ROADMAP M1: the pinned RNG with known-answer vectors, explicit arithmetic helpers, roster/position identities, state initialization and invariants, a basic canonical codec and digest, owned-state cloning, context compatibility and checked capacities.

Add only the fields justified by the initial requests and mechanics. Do **not** implement M2 (requests, commands, observations) or any Pokémon rule.

## Read first

`AGENTS.md`, `docs/ROADMAP.md` (M1, M2), `docs/ARCHITECTURE.md`, `docs/DETERMINISM_AND_REPLAY.md`, `docs/DECISION_CONTRACT.md`, `docs/TESTING_AND_BENCHMARKS.md`, `docs/OPEN_DECISIONS.md`.

## Implement

The contracts are written down in the decision notes produced by this task:

- `docs/decisions/0001-rng-pcg32-contract.md`: PCG32 exactly as `pcg-c-basic@bc39cd7`, per instance; draw accounting including rejected words; explicit exhaustion; zero bound as an internal violation; atomic bounded draws; `initseq < 2^63` at the public boundary.
- `docs/decisions/0002-owned-state-identity-and-encoding-v1.md`: status codes and producer classes; synthetic context and fingerprint; owned state v1; identity and activation ids; invariant order; canonical encoding v1 with strict decode order; digest, equality, clone, copy and reseed; M2 constraints.
- `docs/decisions/0003-m1-build-and-evidence-policy.md`: warnings, sanitizers, lint, globals check, canaries, CI, result labels.

## Exit mapping

| ROADMAP M1 item | Evidence |
|---|---|
| RNG + KAT | `duoforge.rng.kat`, `duoforge.rng.contract`; optional `duoforge.rng.kat_regen` and `duoforge.rng.reference_differential` |
| Arithmetic helpers | `duoforge.unit.arith` |
| Identities | `duoforge.state.identity` |
| Initialization + invariants | `duoforge.state.setup`, `duoforge.state.setup_sweep`, `duoforge.state.invariants` |
| Codec / digest | `duoforge.unit.sha256`, `duoforge.codec.golden`, `duoforge.codec.negative`, `duoforge.codec.mutation` |
| Cloning | `duoforge.state.clone_equal` |
| Context compatibility, capacities | `duoforge.state.context`, context-mismatch and capacity cases in `duoforge.api.atomicity`, `duoforge.codec.negative` |
| Malformed-input atomicity | All of the above check untouched outputs and state on every failure |
| Schema/semantics identifiers | Registry in decision 0002 (CONTEXT v1, BATTLE_STATE v1, semantics 1) |

Rule-authorized rejection/revelation is **not applicable in M1**, because M1 has no choices. It remains a separate category for M2.

## Hard boundaries

- **No Pokémon mechanics:** no damage/stat/PP formulas, no turn order, no Struggle.
- **No real data**, and no team or profile loading.
- **No M2 surface:** no requests, commands, epochs or observations.
- **No batch runtime, bindings or benchmarks.**
- **No project license choice.**
- **No Pokémon-semantics arithmetic helpers** (rounding modes, 4096 modifiers): they arrive with their first consumer.

## Validation

Run GCC and Clang in Debug and Release with `-DDUOFORGE_WARNINGS_AS_ERRORS=ON`, plus the GCC sanitizer build and the reference tests against the pinned pcg-c-basic checkout.

Also run the negative controls. Each must turn its test red and pass again after revert.

Report PASS / FAIL / NOT_RUN / BLOCKED / SKIPPED with exact commands and times.

Stop after M1.
