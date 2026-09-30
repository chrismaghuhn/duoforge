# DuoForge

DuoForge is a deterministic, headless Pokémon Doubles simulation engine designed for machine-learning workloads.

**Status: M1 (deterministic primitives and owned state).** DuoForge is still **not** a Pokémon battle simulator. It contains the deterministic foundation the simulator will be built on:

- the pinned PCG32 gameplay RNG;
- checked integer helpers;
- an immutable (synthetic) context with a content fingerprint;
- an owned, pointer-free battle state with stable identities and an invariant checker;
- a canonical, versioned binary encoding with a SHA-256 digest;
- clone/copy (snapshot/restore) and reseeding for forks.

No Pokémon species, moves, abilities, items, damage calculation, turn resolution, targeting, requests, observations, batch environments, Python bindings or ML code are implemented. The owner has selected the rules basis (**Pokémon Champions, VGC 2026 Reg M-C**), the reference revision (**Pokémon Showdown `b2cb775`**) and two teams (`docs/decisions/0004`). None of this is implemented yet.

State snapshots and decodability are foundation evidence, **not proof that unimplemented future mechanics restore correctly**.

## Requirements

- CMake 3.23 or newer (verified with 3.23.3 and 3.28.3)
- A C17 compiler: MSVC, GCC or Clang (verified: GCC 13.3, Clang 18.1, MSVC via hosted CI)
- Ninja for the supplied presets

There are no third-party runtime dependencies. Python 3 is used only by the offline oracle in `tools/state_model/`; the build and tests do not need it.

## Build and test

```text
cmake --preset debug
cmake --build --preset debug
ctest --preset debug

cmake --preset release
cmake --build --preset release
ctest --preset release
```

On Linux, the same with AddressSanitizer and UndefinedBehaviorSanitizer (GCC or Clang; Clang needs compiler-rt installed):

```text
cmake --preset sanitize
cmake --build --preset sanitize
ctest --preset sanitize
```

On Windows, run the commands from a Visual Studio Developer Command Prompt so that MSVC is available. Generator-neutral form:

```text
cmake -S . -B build/debug -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DDUOFORGE_WARNINGS_AS_ERRORS=ON
cmake --build build/debug
ctest --test-dir build/debug --output-on-failure --no-tests=error
```

Options:

| Option | Default | Effect |
|---|---|---|
| `DUOFORGE_WARNINGS_AS_ERRORS` | OFF | `-Werror` / `/WX`. CI and all local verification use ON. |
| `DUOFORGE_ENABLE_SANITIZERS` | OFF | ASan + UBSan, non-recovering (GCC/Clang only). |
| `DUOFORGE_PCG_REFERENCE_DIR` | empty | Path to a checkout of `imneme/pcg-c-basic` at `bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3`. Enables the reference tests (`ctest -L reference`): byte-identical KAT regeneration and a 1,024,000-operation lockstep differential. |

Every test is finite and has a timeout. Test groups:

| Group | What it covers |
|---|---|
| `duoforge.unit.*` | Checked arithmetic, byte order, SHA-256 |
| `duoforge.rng.*` | PCG32 known-answer vectors and contract |
| `duoforge.state.*` | Context, setup, identity, invariants, clone/equal/reseed, setup sweep |
| `duoforge.codec.*` | Goldens, negative decoding, exhaustive mutation sweep |
| `duoforge.api.*` | Status names, NULL and context-mismatch sweeps, C++ link |
| `duoforge.lint.*` | Source rules and their self-test; no writable globals |
| `duoforge.provenance.*` | Vendored license hash |
| `duoforge.sanitizer.*` | Sanitizer liveness canaries (sanitizer builds only) |

## Public API (provisional, `include/duoforge/duoforge.h`)

- **Status:** `duoforge_status` (`uint32_t`) codes and `duoforge_status_name`.
- **Context:** `duoforge_context_create`, `duoforge_context_destroy` and `duoforge_context_fingerprint`. The context is synthetic, immutable and shareable read-only.
- **Battle lifecycle:** `duoforge_battle_create` (from a synthetic setup), `duoforge_battle_create_decoded`, `duoforge_battle_clone` and `duoforge_battle_destroy`.
- **Snapshots and codec:** `duoforge_battle_copy` (snapshot/restore), `duoforge_battle_decode`, `duoforge_battle_encoded_size`, `duoforge_battle_encode`, `duoforge_battle_digest` and `duoforge_battle_equal`.
- **Checking and forks:** `duoforge_battle_check` and `duoforge_battle_reseed` (decorrelates a forked copy for search).

Every call is failure-atomic: on error nothing is mutated, written or leaked. Encode, decode, digest, equal, check and reseed are **privileged**: they see hidden state and must never feed a model directly. The ABI is not frozen.

## Documentation

- Decisions: `docs/decisions/0001` (RNG), `0002` (state, identity, encoding), `0003` (build and evidence), `0004` (owner selections)
- Architecture proposal and contracts: `docs/ARCHITECTURE.md`, `docs/DECISION_CONTRACT.md`, `docs/DETERMINISM_AND_REPLAY.md`, `docs/ROADMAP.md`
- Status manifest: `docs/support/README.md`; open decisions: `docs/OPEN_DECISIONS.md`
- Task statements: `tasks/M0_BOOTSTRAP.md`, `tasks/M1_DETERMINISTIC_PRIMITIVES.md`

## Licensing facts

`third_party/pcg-c-basic/` and `src/rng/pcg32_derived.{h,c}` contain material from pcg-c-basic, licensed by its author under the Apache License 2.0 (see `third_party/pcg-c-basic/LICENSE.txt`). The root `LICENSE` is the owner's placeholder; how it refers to third-party material is an open owner decision.

DuoForge makes no claim of full Gen 9 support, VGC compatibility, Pokémon Showdown parity or high performance.
