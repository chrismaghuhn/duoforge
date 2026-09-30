# DuoForge architecture boundaries

The long-term design (`docs/ARCHITECTURE.md`, proposal v0.1) keeps these concerns separate:

- immutable rules/data context;
- mutable per-battle state;
- decision interface;
- execution core;
- information/observation boundary;
- deterministic RNG/replay;
- batch environments;
- ML bindings.

## Implemented (M1, structural only)

| Concern | Status | Decision note |
|---|---|---|
| Deterministic RNG (PCG32, per battle) | Implemented + tested | `docs/decisions/0001-rng-pcg32-contract.md` |
| Synthetic immutable context + fingerprint; owned pointer-free battle state; identity; invariants; canonical encoding v1; digest; clone/copy/equal; reseed | Implemented + tested | `docs/decisions/0002-owned-state-identity-and-encoding-v1.md` |
| Build, sanitizers, lint and evidence policy | Implemented | `docs/decisions/0003-m1-build-and-evidence-policy.md` |
| Owner selections: Champions Reg M-C, Showdown pin, teams | Recorded, not implemented | `docs/decisions/0004-owner-selections-champions-reference-teams.md` |

Source layout: `src/core` (platform rules, checked arithmetic, bytes, allocation, SHA-256), `src/rng`, `src/state`, `src/codec`.

No rules contract, request/command/observation API or binding ABI exists yet. Those require their own reviewed, implemented and tested slices (ROADMAP M2+).
