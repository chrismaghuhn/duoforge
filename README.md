# DuoForge

DuoForge is a deterministic, headless Pokémon Doubles simulation engine designed for machine-learning workloads.

**Status: M2 (requests, joint commands and the information boundary).** DuoForge is still **not** a Pokémon battle simulator. It contains the deterministic foundation and the decision surface the simulator will be built on:

- the pinned PCG32 gameplay RNG;
- checked integer helpers;
- an immutable (synthetic) context with a content fingerprint and a synthetic move target-class table;
- an owned, pointer-free battle state v3 with stable identities, decision boundaries (including TERMINAL), request epochs, sealed commitments, per-player knowledge (HP as last seen) and an invariant checker, plus the fields combat will need (field and side conditions, volatile blocks, action queue), which nothing writes yet;
- a canonical, versioned binary encoding with a SHA-256 digest;
- clone/copy (snapshot/restore) and reseeding for forks;
- team selection (ordered picks) and complete joint side-choice domains per turn, enumerated in a documented deterministic order, with per-player requests, request epochs and simultaneous decision bundles;
- a perspective-safe observation prototype (open team sheets, own exact HP/PP, opponent HP at the Champions percent precision, tagged unknowns);
- generated data tables of the two reference teams from the pinned Showdown revision, and the Champions stat and PP formulas (data only, step 1a of the combat closure);
- the state v3 layout of the combat closure with its invariants, codec and oracle (step 1b-1);
- contexts over the real closure data, validation of real sets with derived stats and PP, and the support gate that still rejects every real team with `DUOFORGE_E_UNSUPPORTED` (step 1b-2);
- the turn core for development teams: turn order with speed ties, damage, accuracy, critical hits, stat stages, secondary stat changes, PP, Struggle and Protect, replaying recorded reference battles draw for draw (step 2);
- switching, fainting, replacement and the win rule: development teams play complete battles to TERMINAL (step 3);
- burn, paralysis, sleep and freeze in their Champions variants, flinch and confusion (step 4);
- the entry abilities Drizzle, Grassy Surge and Intimidate, rain, Grassy Terrain and the ordered residual phase (step 5);
- Tailwind, Reflect, Light Screen and Trick Room (step 6);
- the reactive abilities of the base formes: Stamina, Competitive, Flash Fire, Lightning Rod, Good as Gold, Armor Tail, Prankster and Blaze (step 7);
- the items Leftovers, Sitrus Berry, Grassy Seed, Life Orb, Mystic Water and Light Clay (step 8);
- recoil, drain and self-drops: Wood Hammer, Brave Bird, Bitter Blade, Leech Life, Close Combat, Make It Rain, with Miracle Seed (step 9);
- Weather Ball, Grass Knot, Grassy Glide and Fake Out with its Champions disable rule (step 10a);
- Electro Shot with its charge turn and the locked move in the request (step 10b).

**Combat is partial.** Development teams (data kind `CLOSURE_DEV`: the supported abilities or No Ability, the supported items or none, the supported moves) play complete battles: turns, switches, faints, replacements, statuses and the end of the battle. Everything else returns `DUOFORGE_E_UNSUPPORTED` and changes nothing: Emergency Exit, Parting Shot, a Mega Stone or Mega Evolution. The observation does not show stages or statuses yet. Under SYNTHETIC data every combat bundle is unsupported. The engine knows the data of the two reference teams and validates their sets, but no move, ability or item effect is implemented, so the support gate rejects every real team with `DUOFORGE_E_UNSUPPORTED`. No batch environments, Python bindings or ML code exist. The owner has selected the rules basis (**Pokémon Champions, VGC 2026 Reg M-C**), the reference revision (**Pokémon Showdown `b2cb775`**) and two teams (`docs/decisions/0004`).

State snapshots and decodability are foundation evidence, **not proof that unimplemented future mechanics restore correctly**.

## Requirements

- CMake 3.23 or newer (verified with 3.23.3 and 3.28.3)
- A C17 compiler: MSVC, GCC or Clang (verified: GCC 13.3 and Clang 18.1 on Linux and MSVC in hosted CI; GCC 16.2 MinGW-w64, Clang 23.1 and MSVC 2022 natively on Windows)
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
| `duoforge.unit.*` | Checked arithmetic, byte order, SHA-256, damage and stat arithmetic against the reference, draw sites and tape |
| `duoforge.combat.*` | The turn core through the public API: one turn, determinism, continuation across encode/decode, honest `E_UNSUPPORTED`, random play |
| `duoforge.reference.*` | Thirty-seven recorded reference battles replayed draw for draw, with the request compared after every step (`conformance`), the generated tables against the traces; with a checkout: traces and arithmetic regenerated |
| `duoforge.rng.*` | PCG32 known-answer vectors and contract |
| `duoforge.state.*` | Context, setup, identity, knowledge (HP display as last seen), closure setup (real sets, gate, member invariant), invariants, clone/equal/reseed, setup sweep |
| `duoforge.codec.*` | Goldens, negative decoding (including "rejected: schema 1"), exhaustive mutation sweep |
| `duoforge.request.*` | Exhaustive domains against the oracle, stable and pure enumeration, output convention, step validation and atomicity, honest UNSUPPORTED, re-prompt, contract minimum (snapshots per boundary, stale/late, two-side replacement and pivot, one-side continuation), observation and information equivalence |
| `duoforge.data.*` | Generated closure tables against values read at the pin, the table hash, the Champions stat and PP formulas; optional regeneration against a pinned Showdown checkout (`-DDUOFORGE_PS_REFERENCE_DIR=...`, label `reference`) |
| `duoforge.api.*` | Status names, NULL and context-mismatch sweeps, C++ link |
| `duoforge.lint.*` | Source rules and their self-test; no writable globals |
| `duoforge.provenance.*` | Vendored license hash |
| `duoforge.sanitizer.*` | Sanitizer liveness canaries (sanitizer builds only) |

## Public API (provisional, `include/duoforge/duoforge.h`)

- **Status:** `duoforge_status` (`uint32_t`) codes and `duoforge_status_name`.
- **Context:** `duoforge_context_create` (with the synthetic move target-class table), `duoforge_context_destroy` and `duoforge_context_fingerprint`. The context is synthetic, immutable and shareable read-only.
- **Battle lifecycle:** `duoforge_battle_create` (from a synthetic setup; the battle starts at TEAM_SELECTION), `duoforge_battle_create_decoded`, `duoforge_battle_clone` and `duoforge_battle_destroy`.
- **Model-facing decision surface:** `duoforge_battle_request` (one player's request with the exact candidate count), `duoforge_battle_candidates` (the complete joint side-choice domain in documented order; too small a buffer returns `E_CAPACITY` and only the required count), `duoforge_battle_step` (one decision bundle for exactly the requested sides) and `duoforge_battle_observe` (the perspective-safe observation prototype). Requests, candidates and observations are pure.
- **Snapshots and codec:** `duoforge_battle_copy` (snapshot/restore), `duoforge_battle_decode`, `duoforge_battle_encoded_size`, `duoforge_battle_encode`, `duoforge_battle_digest` and `duoforge_battle_equal`.
- **Checking and forks:** `duoforge_battle_check` and `duoforge_battle_reseed` (decorrelates a forked copy for search).

Every call is failure-atomic: on error nothing is mutated or leaked, and the only out-parameter written on error is the required count of a model-facing query on `E_CAPACITY`. Encode, decode, digest, equal, check and reseed are **privileged**: they see hidden state and must never feed a model directly. The ABI is not frozen.

## Documentation

- Decisions: `docs/decisions/0001` (RNG), `0002` (state, identity, encoding), `0003` (build and evidence), `0004` (owner selections), `0005` (requests, commands, information boundary, state v2), `0006` (combat closure design, proposed; no code yet)
- Architecture proposal and contracts: `docs/ARCHITECTURE.md`, `docs/DECISION_CONTRACT.md`, `docs/DETERMINISM_AND_REPLAY.md`, `docs/ROADMAP.md`
- Status manifest: `docs/support/README.md`; open decisions: `docs/OPEN_DECISIONS.md`
- Task statements: `tasks/M0_BOOTSTRAP.md`, `tasks/M1_DETERMINISTIC_PRIMITIVES.md`, `tasks/M2_REQUESTS_AND_COMMANDS.md`, `tasks/M3_M4_COMBAT_CLOSURE.md` (next, not started)
- Research drafts (unverified): `docs/research/`

## Licensing facts

`third_party/pcg-c-basic/` and `src/rng/pcg32_derived.{h,c}` contain material from pcg-c-basic, licensed by its author under the Apache License 2.0 (see `third_party/pcg-c-basic/LICENSE.txt`). The root `LICENSE` is the owner's placeholder; how it refers to third-party material is an open owner decision.

DuoForge makes no claim of full Gen 9 support, VGC compatibility, Pokémon Showdown parity or high performance.
