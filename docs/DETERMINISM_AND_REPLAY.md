# Determinism, RNG and replay — proposed

## 1. Reproducibility envelope

The deterministic input is not merely a seed. It includes the exact engine semantics, immutable data, rules/information profiles, initial team configurations, RNG contract and canonical accepted commands. External budgets and policy identities are separate provenance.

A worker number, thread ID, allocation address, wall clock or completion order must not influence combat. Given identical per-environment inputs, different worker counts must yield the same per-environment results. Different policy actions obviously invalidate that comparison.

Define integer widths, signedness, overflow policy, modifier rounding and canonical iteration order. A stable RNG cannot compensate for undefined C behavior or nondeterministic event ordering.

## 2. Proposed initial RNG

Use a version-pinned PCG32 XSH-RR implementation with explicit per-battle state as the starting proposal. The primary implementation documents seeded state and bounded sampling [S6, S7]. The exact implementation, notices and contract must be fixed and tested in M1; the RNG is not yet an implemented dependency.

Use only re-entrant/per-instance functions. Do not use the library's global generator. Define an engine wrapper with raw-word consumption accounting, supported ranges, zero-bound rejection and serialization. Rejection-sampling attempts count as consumed words. Initialization behavior, draw-count initialization and exhaustion behavior require known-answer tests.

The setup API can initially accept an explicit per-battle `(initstate, initseq)` pair. For batch generation, define a deterministic tagged mapping from `(root seed, environment identity, episode identity)` to those inputs outside the hot path; pin that mapping before M6. Do not invent an ad-hoc dependence on which worker happens to execute reset. Record both effective RNG inputs in provenance. Never claim statistical independence solely because two seeds differ.

Separate gameplay RNG from policy exploration, matchup selection, dataset shuffling and hypothetical search RNG. Separate explicit state is the requirement; a complex cryptographic stream framework is not needed in the first battle slice.

## 3. No automatic Showdown seed parity

Our native RNG contract and Showdown's PRNG contract are distinct. Showdown's source supports named RNG variants and has its own calls, bounded conversions and draw order [S5]. The same numeric seed is not evidence that a native battle and Showdown should take the same path.

For conformance testing:

1. Start with deterministic mechanics fixtures and controlled individual random outcomes.
2. Add a test-only semantic RNG tape with typed purposes, expected draw counts and explicit exhaustion errors.
3. Align outcomes at genuine corresponding semantic draw sites; do not inject arbitrary values until the test happens to pass.
4. Treat raw same-seed parity as a separate deliverable requiring a specifically validated reference-compatible RNG adapter and call-order alignment.

Do not put a reference compatibility mode into the production core merely to make a golden file pass. Test control must be distinguishable from normal execution and excluded from certified production inputs unless explicitly intended.

## 4. Fast snapshots versus portable serialization

**In-process snapshot:** copy owned pointer-free battle state under the exact same context/layout/build compatibility contract. This may use assignment or `memcpy`. Restore all authoritative information, including continuations, RNG, request state and player knowledge.

**Portable replay/checkpoint:** explicitly serialize fields in a canonical order with fixed widths and byte order. Never write `sizeof(struct)` raw bytes; padding, enum layout and pointer representation are not the wire contract. Do not use `memcmp` of structs as semantic equality.

Cross-build loading is allowed only where schema and semantics compatibility is established. Old artifacts must not silently acquire the new engine's behavior. Either retain a compatible reader/semantics implementation or reject the mismatch.

Model recurrent memory is external to combat state. A full environment-training checkpoint may additionally include policy memory and trajectory-writer position, but that is not the same artifact as a core battle snapshot.

## 5. Manifest and events

A replay manifest should contain:

```text
replay_schema
engine_revision / semantic_version
rules_profile_id + hash
information_profile_id + hash
data_revision + content_hash
support_manifest_hash
initial_team_specifications or immutable references + hashes
RNG contract + explicit initial RNG inputs
```

A step record binds canonical commands to the request boundary and can include expected next-boundary and canonical state digests. Diagnostic full traces may include RNG tags and private events; they must not be supplied to a competitive policy.

Full-state canonical digests are diagnostics and replay checks. They can encode hidden information and must not be exposed as observation features or candidate IDs. External chunk hashes verify artifacts, not battle-rule correctness.

Persistent raw event history need not be copied with each battle. Store the compact information state needed to reproduce observations; keep replay/trajectory logs externally. A branching writer uses explicit branch/checkpoint boundaries rather than appending conflicting histories to the same stream.

## 6. Failure atomicity

Begin with a straightforward working-copy implementation for mutable transitions: validate inputs, execute using a temporary battle and staged outputs, then commit on success. This is a design choice, not a performance claim. Profile before replacing it with in-place mutation plus rollback.

An API error leaves the previously committed battle valid. A rule-authorized revelation/re-prompt is a successful semantic result and can legitimately mutate knowledge/request state. Keep those categories separate.

A full output buffer must not cause partial battle progression. An operational interruption needs either a defined safe checkpoint or rollback to the last committed boundary; no half-applied move may masquerade as a resumable state.

## 7. Required evidence

Known-answer RNG tests; bound-zero and rejection behavior; canonical codec round-trip and negative tests; snapshot/restore at every request kind; replay equivalence after multiple pauses; equality of FULL/COUNTERS/OFF diagnostic modes; per-environment equivalence under different worker schedules; cross-compiler golden replay comparison on declared targets.

Pin exact source revisions before claiming these results. Until then they are requirements, not achieved properties.
