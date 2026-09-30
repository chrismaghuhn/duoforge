# Primary sources inspected

Inspection date: 2026-09-12. These sources support external factual statements and the choice of reference targets. The architecture itself is a proposed design. Mutable URLs below are **not** immutable implementation pins.

## S1 — pkmn/engine

```text
https://github.com/pkmn/engine
```

The README describes a low-level performance-oriented engine with C bindings and separate update/choice concepts. Its status section places modern generations outside the immediate old-generation implementation work. It is an architectural reference, not evidence for a measured Gen-9 doubles throughput target or a ready Gen-9 backend for this project.

**Pins (added 2026-09-30):** S2–S5 are pinned for M3 at Pokémon Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc` (owner decision; hashes in `docs/decisions/0004`). S6/S7 are pinned for M1 at pcg-c-basic `bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3` (`third_party/pcg-c-basic/PROVENANCE.md`). The mutable URLs below remain documentation, not lock entries.

## S2 — Pokémon Showdown simulator protocol

```text
https://raw.githubusercontent.com/smogon/pokemon-showdown/master/sim/SIM-PROTOCOL.md
```

Relevant sections: player requests, identifying positions, team preview and sending decisions. Doubles choices contain multiple slot commands; target selectors reference positions; execution continues when required player decisions are available. Do not adopt text protocol parsing inside the core merely because this is the reference interface.

## S3 — Pokémon Showdown battle execution

```text
https://raw.githubusercontent.com/smogon/pokemon-showdown/master/sim/battle.ts
```

Relevant functions/sections: event ordering, `runAction`, `turnLoop`, `getActionSpeed`, dynamic queue updates for Gen 8+, mid-turn switch requests, and potential-trapping information behavior. The source demonstrates why one static sort and one monolithic full-turn step are inadequate references for all supported Gen-9 behavior.

## S4 — Pokémon Showdown side/choice handling

```text
https://raw.githubusercontent.com/smogon/pokemon-showdown/master/sim/side.ts
https://raw.githubusercontent.com/smogon/pokemon-showdown/master/sim/battle-queue.ts
```

Relevant portions: `chooseMove`, `chooseSwitch`, request updates, per-choice transformation restrictions and queue ordering. These are useful reference targets for cross-slot validation, hidden-information-sensitive rejection and action scheduling.

## S5 — Pokémon Showdown randomness

```text
https://raw.githubusercontent.com/smogon/pokemon-showdown/master/sim/prng.ts
```

The reference has explicit PRNG state and multiple recognized seed/RNG forms. A new engine's PCG seed is not automatically equivalent to Showdown's RNG input or consumption trace.

## S6 — PCG author's minimal C implementation documentation

```text
https://www.pcg-random.org/using-pcg-c-basic.html
```

Documents per-instance seeded generation, PCG32 state, deterministic examples and bounded sampling. Useful for implementing and independently checking a small explicit simulation RNG. Do not follow examples that seed from time or addresses for reproducible ML environments.

## S7 — PCG minimal C source

```text
https://raw.githubusercontent.com/imneme/pcg-c-basic/master/pcg_basic.c
```

Contains the reference XSH-RR transition, seeding and bounded rejection-sampling implementation, with its notices. Pin a concrete revision and inspect licensing/provenance before copying code. This pack does not vendor it.

## S8 — Official Codex project-instructions documentation

```text
https://developers.openai.com/codex/guides/agents-md/
```

At inspection this redirected to the official project-instructions documentation. It documents reading `AGENTS.md` and layering project instructions. The pack therefore includes a short root instruction file and separate detailed task documents, rather than relying on a long chat prompt as the only source of project context.

## S9 — FIPS 180-4 Secure Hash Standard

```text
https://csrc.nist.gov/pubs/fips/180-4/upd1/final
```

Specification of SHA-256, used for the context fingerprint and state digest (`src/core/sha256.c`, written from the specification; no code imported). Test vectors: the FIPS 180-2 examples and coreutils `sha256sum` 9.4.

## Limits of this research

No code benchmark was reproduced. No Gen-9 C doubles implementation was measured. No current official VGC regulation or chosen two-team matchup was certified. No upstream commit hash was frozen. No external source is treated as proof that this proposed implementation is correct.
