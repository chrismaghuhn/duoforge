# Support and provenance manifest

This is a status manifest, **not** a mechanics certificate. "IMPLEMENTED + TESTED" means engine primitives with synthetic data only, not supported Pokémon behaviour.

| Area | Status |
|---|---|
| pcg-c-basic (RNG reference) | **PINNED** `bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3` (`third_party/pcg-c-basic/PROVENANCE.md`) |
| Pokémon Showdown (operational reference) | **PINNED** `b2cb775b0616115b775534eaeff50300e1fc81fc` (owner decision; `docs/decisions/0004`). Not vendored; not used by any test yet |
| Rules profile | **SELECTED** (owner): `[Gen 9 Champions] VGC 2026 Reg M-C`. **Not implemented** |
| Team specifications | **SELECTED** (owner): two teams in `docs/decisions/0004`. **Not implemented**; the engine cannot load them yet |
| PCG32 RNG primitive and wrapper contract (0001) | **IMPLEMENTED + TESTED**; no gameplay draw sites exist yet (M3) |
| Arithmetic and byte helpers | **IMPLEMENTED + TESTED** (generic; no Pokémon-semantics helpers) |
| Owned structural state, identity, invariants | **IMPLEMENTED + TESTED** (synthetic data only) |
| Canonical encoding v1, SHA-256 digest, clone/copy/equal, reseed | **IMPLEMENTED + TESTED** (synthetic data only) |
| Requests, commands, observations | **UNSUPPORTED** (M2) |
| Pokémon data, mechanics coverage, reference parity | **UNSUPPORTED** |

State snapshots and decodability are foundation evidence, **not proof that unimplemented future mechanics restore correctly**.

## Licensing facts

`third_party/pcg-c-basic/` and `src/rng/pcg32_derived.{h,c}` contain material from pcg-c-basic, licensed by its author under the Apache License 2.0 (see `third_party/pcg-c-basic/LICENSE.txt`). The root `LICENSE` is the owner's placeholder; how it refers to third-party material is an open owner decision (`docs/OPEN_DECISIONS.md`).
