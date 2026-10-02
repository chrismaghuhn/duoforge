# DuoForge

DuoForge is a deterministic, headless Pokémon Doubles simulation engine designed for machine-learning workloads.

**Status: M2 (requests, joint commands and the information boundary).** DuoForge is still **not** a Pokémon battle simulator. It contains the deterministic foundation and the decision surface the simulator will be built on:

- the pinned PCG32 gameplay RNG;
- checked integer helpers;
- an immutable (synthetic) context with a content fingerprint and a synthetic move target-class table;
- an owned, pointer-free battle state v3 with stable identities, decision boundaries (including TERMINAL), request epochs, sealed commitments, per-player knowledge (HP as last seen) and an invariant checker, plus the combat fields (field and side conditions, volatile blocks, action queue);
- a canonical, versioned binary encoding with a SHA-256 digest;
- clone/copy (snapshot/restore) and reseeding for forks;
- team selection (ordered picks) and complete joint side-choice domains per turn, enumerated in a documented deterministic order, with per-player requests, request epochs and simultaneous decision bundles;
- a perspective-safe observation, since observation v2 exactly what a human player sees (decision 0007): open team sheets with abilities, items, natures and maximum PP; own exact HP and PP; the opponent's HP at the Champions percent precision as last seen and its PP derived from the uses seen; statuses, stat stages, confusion, charging moves, Mega formes, items used up; weather, terrain, Trick Room and the side conditions with remaining turns; which sides must answer. Sleep, freeze and confusion turns stay hidden on both sides;
- a per-player event log of every step (decision 0007 section 11): one event per line of the battle protocol the game shows that player, in the game's order, with the own HP exact and the opponent's as the percent display; each player's knowledge of the opponent is folded from these events only (section 12);
- a benchmark driver and API (`bench/`, decision 0008): STEP_CORE, REQUEST, SNAPSHOT and EPISODE_NATIVE on the reference teams with a reproducible manifest, wall and process CPU time per repetition (a busy machine shows as disturbed), and a tally of what each side's policy chose (moves by id, Mega, switches, replacements, passes, targets);
- generated data tables of the two reference teams from the pinned Showdown revision, and the Champions stat and PP formulas (step 1a of the combat closure);
- the state v3 layout of the combat closure with its invariants, codec and oracle (step 1b-1);
- contexts over the real closure data, validation of real sets with derived stats and PP, and the support gate (step 1b-2), which both real teams pass since step 12;
- the turn core for development teams: turn order with speed ties, damage, accuracy, critical hits, stat stages, secondary stat changes, PP, Struggle and Protect, replaying recorded reference battles draw for draw (step 2);
- switching, fainting, replacement and the win rule: development teams play complete battles to TERMINAL (step 3);
- burn, paralysis, sleep and freeze in their Champions variants, flinch and confusion (step 4);
- the entry abilities Drizzle, Grassy Surge and Intimidate, rain, Grassy Terrain and the ordered residual phase (step 5);
- Tailwind, Reflect, Light Screen and Trick Room (step 6);
- the reactive abilities of the base formes: Stamina, Competitive, Flash Fire, Lightning Rod, Good as Gold, Armor Tail, Prankster and Blaze (step 7);
- the items Leftovers, Sitrus Berry, Grassy Seed, Life Orb, Mystic Water and Light Clay (step 8);
- recoil, drain and self-drops: Wood Hammer, Brave Bird, Bitter Blade, Leech Life, Close Combat, Make It Rain, with Miracle Seed (step 9);
- Weather Ball, Grass Knot, Grassy Glide and Fake Out with its Champions disable rule (step 10a);
- Electro Shot with its charge turn and the locked move in the request (step 10b);
- Mega Evolution with Drought, Contrary, No Guard and Tough Claws (step 11);
- Parting Shot and Emergency Exit with real PIVOT boundaries in the middle of a turn, and Emergency Exit at its end (step 12);
- the closure gate (step 13): both teams of decision 0004 play from team selection to the end in all four pairings, conform to recorded reference battles, replay byte for byte and keep information equivalence.

**The combat closure is complete for the two reference teams.** Under CLOSURE data they play complete battles: turns, switches, faints, replacements, pivots, statuses, Mega Evolution and the end of the battle. Development teams (data kind `CLOSURE_DEV`) may also use No Ability. Any other mechanic is outside the closure and is rejected at setup with `DUOFORGE_E_UNSUPPORTED`. The event log of decision 0007 (what happened since the last decision) is not built yet. Under SYNTHETIC data every combat bundle is unsupported. No batch environments, Python bindings or ML code exist. The owner has selected the rules basis (**Pokémon Champions, VGC 2026 Reg M-C**), the reference revision (**Pokémon Showdown `b2cb775`**) and two teams (`docs/decisions/0004`).

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
| `DUOFORGE_ENABLE_IPO` | OFF | Link-time optimization of Release builds (8 to 13 percent faster battles, decision 0008 section 8). The library then links only with the same toolchain; fails the configuration where unsupported. |
| `DUOFORGE_PYTHON` | empty | Python 3.10+ with NumPy 2 for the `duoforge.python.*` tests (see "Python"); without it they report skipped. |
| `DUOFORGE_PCG_REFERENCE_DIR` | empty | Path to a checkout of `imneme/pcg-c-basic` at `bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3`. Enables the reference tests (`ctest -L reference`): byte-identical KAT regeneration and a 1,024,000-operation lockstep differential. |

Every test is finite and has a timeout. Test groups:

| Group | What it covers |
|---|---|
| `duoforge.unit.*` | Checked arithmetic, byte order, SHA-256, damage and stat arithmetic against the reference, draw sites and tape |
| `duoforge.combat.*` | The turn core through the public API: one turn, determinism, continuation across encode/decode, honest `E_UNSUPPORTED`, random play; the closure gate with the real teams (`closure_gate`) and the Team C gate (`team_c_gate`) |
| `duoforge.reference.*` | Fifty-eight recorded reference battles replayed draw for draw, with the request compared after every step (`conformance`), the generated tables against the traces; with a checkout: traces and arithmetic regenerated |
| `duoforge.rng.*` | PCG32 known-answer vectors and contract |
| `duoforge.state.*` | Context, setup, identity, knowledge (HP display as last seen), closure setup (real sets, gate, member invariant), invariants, clone/equal/reseed, setup sweep |
| `duoforge.codec.*` | Goldens, negative decoding (including "rejected: schema 1"), exhaustive mutation sweep |
| `duoforge.request.*` | Exhaustive domains against the oracle, stable and pure enumeration, output convention, step validation and atomicity, honest UNSUPPORTED, re-prompt, contract minimum (snapshots per boundary, stale/late, two-side replacement and pivot, one-side continuation), observation and information equivalence |
| `duoforge.data.*` | Generated closure tables against values read at the pin, the table hash, the Champions stat and PP formulas; optional regeneration against a pinned Showdown checkout (`-DDUOFORGE_PS_REFERENCE_DIR=...`, label `reference`) |
| `duoforge.batch.*` | The batch runtime: native and step mode against single battles, stepping by index and by factored choice |
| `duoforge.python.*` | The Python package (label `python`): layouts against C, loader, native-versus-binding equivalence, recipes, policies and encoder, the example |
| `duoforge.api.*` | Status names, NULL and context-mismatch sweeps, C++ link |
| `duoforge.lint.*` | Source rules and their self-test; no writable globals |
| `duoforge.provenance.*` | Vendored license hash |
| `duoforge.sanitizer.*` | Sanitizer liveness canaries (sanitizer builds only) |

## Python

The package `python/duoforge` (decision 0013) drives the engine from Python over ctypes and NumPy: a batch of environments per call with the GIL released, buffers allocated once, the random and scripted baselines, an observation-only feature encoder and trajectory recipes (seeds and choices, replayed to features). It needs CPython 3.10 or later and NumPy 2; every rule stays in C.

```text
python -m venv .venv
.venv/Scripts/python -m pip install numpy        (Linux: .venv/bin/python)
cmake -S . -B build/py -DBUILD_TESTING=ON -DDUOFORGE_PYTHON=<repo>/.venv/Scripts/python.exe
cmake --build build/py
ctest --test-dir build/py -L python --output-on-failure
```

The tests find the shared library `duoforge_shared` through `DUOFORGE_LIBRARY`; without `DUOFORGE_PYTHON` they report skipped. To use the package directly, set `DUOFORGE_LIBRARY` to the built library and put `python/` on `PYTHONPATH`. The example writes a recipe and replays it:

```text
python -m duoforge.examples.generate --envs 64 --episodes 10 --policy random --workers 4 --out recipes/random640
```

For an RL loop, `Batch.step_query(indices, autoreset=True)` steps, starts every ended episode anew and queries the next boundary in one call. `python -m duoforge.examples.throughput` measures the Python loop against the native mode (`docs/benchmarks/2026-10-02-python-loop/`).

## Learning (decision 0014)

`python/duoforge_learn` trains a policy by self-play PPO on the batch runtime: JAX on the GPU, which needs Linux, so in WSL with its own venv and a Release library built there.

```text
python3 -m venv ~/df-learn
~/df-learn/bin/pip install "jax[cuda12]" optax numpy
cmake -S /mnt/c/Dev/src/duoforge -B ~/df-build/learn -G Ninja -DCMAKE_BUILD_TYPE=Release -DDUOFORGE_ENABLE_IPO=ON -DBUILD_TESTING=OFF
cmake --build ~/df-build/learn --target duoforge_shared
cd /mnt/c/Dev/src/duoforge
DUOFORGE_LIBRARY=~/df-build/learn/libduoforge_shared.so PYTHONPATH=python ~/df-learn/bin/python -m duoforge_learn.train --envs 256 --workers 16 --minutes 30 --out ~/df-runs/trial
```

The log (`log.jsonl`) has one line per update; every `--eval-every` updates it adds the greedy policy's win rates against the random and the scripted baselines and against its previous evaluation (`vs_previous`), and saves the parameters. `DUOFORGE_LEARN_PYTHON` (a Python with JAX) enables the test `duoforge.python.learn`; the local CI's Linux GCC Release job sets it when `~/df-learn` exists.

## Public API (provisional, `include/duoforge/duoforge.h`)

- **Status:** `duoforge_status` (`uint32_t`) codes and `duoforge_status_name`.
- **Context:** `duoforge_context_create` (with the synthetic move target-class table), `duoforge_context_destroy` and `duoforge_context_fingerprint`. The context is synthetic, immutable and shareable read-only.
- **Battle lifecycle:** `duoforge_battle_create` (from a synthetic setup; the battle starts at TEAM_SELECTION), `duoforge_battle_create_decoded`, `duoforge_battle_clone` and `duoforge_battle_destroy`.
- **Model-facing decision surface:** `duoforge_battle_request` (one player's request with the exact candidate count), `duoforge_battle_candidates` (the complete joint side-choice domain in documented order; too small a buffer returns `E_CAPACITY` and only the required count), `duoforge_battle_step` (one decision bundle for exactly the requested sides), `duoforge_battle_step_events` (the same step with each player's events; a too-small buffer returns `E_CAPACITY` and the required count) and `duoforge_battle_observe` (the perspective-safe observation prototype). Requests, candidates and observations are pure.
- **Snapshots and codec:** `duoforge_battle_copy` (snapshot/restore), `duoforge_battle_decode`, `duoforge_battle_encoded_size`, `duoforge_battle_encode`, `duoforge_battle_digest` and `duoforge_battle_equal`.
- **Checking and forks:** `duoforge_battle_check` and `duoforge_battle_reseed` (decorrelates a forked copy for search).

Every call is failure-atomic: on error nothing is mutated or leaked, and the only out-parameter written on error is the required count of a model-facing query on `E_CAPACITY`. Encode, decode, digest, equal, check and reseed are **privileged**: they see hidden state and must never feed a model directly. The ABI is not frozen.

## Documentation

- Decisions: `docs/decisions/0001` (RNG), `0002` (state, identity, encoding), `0003` (build and evidence), `0004` (owner selections), `0005` (requests, commands, information boundary, state v2), `0006` (combat closure design, built), `0007` (player view: observation v2, event log, knowledge from events), `0008` (benchmark API and action tally)
- Architecture proposal and contracts: `docs/ARCHITECTURE.md`, `docs/DECISION_CONTRACT.md`, `docs/DETERMINISM_AND_REPLAY.md`, `docs/ROADMAP.md`
- Status manifest: `docs/support/README.md`; open decisions: `docs/OPEN_DECISIONS.md`
- Task statements: `tasks/M0_BOOTSTRAP.md`, `tasks/M1_DETERMINISTIC_PRIMITIVES.md`, `tasks/M2_REQUESTS_AND_COMMANDS.md`, `tasks/M3_M4_COMBAT_CLOSURE.md` (next, not started)
- Research drafts (unverified): `docs/research/`

## Licensing facts

`third_party/pcg-c-basic/` and `src/rng/pcg32_derived.{h,c}` contain material from pcg-c-basic, licensed by its author under the Apache License 2.0 (see `third_party/pcg-c-basic/LICENSE.txt`). The root `LICENSE` is the owner's placeholder; how it refers to third-party material is an open owner decision.

DuoForge makes no claim of full Gen 9 support, VGC compatibility, Pokémon Showdown parity or high performance.
