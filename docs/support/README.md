# Support and provenance manifest

This is a status manifest, **not** a mechanics certificate. "IMPLEMENTED + TESTED" means engine primitives with synthetic data only, not supported Pokémon behaviour.

| Area | Status |
|---|---|
| pcg-c-basic (RNG reference) | **PINNED** `bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3` (`third_party/pcg-c-basic/PROVENANCE.md`) |
| Pokémon Showdown (operational reference) | **PINNED** `b2cb775b0616115b775534eaeff50300e1fc81fc` (owner decision; `docs/decisions/0004`). Not vendored. M2 cites it for choice rules, team preview, target classes, open team sheets and HP display (`docs/decisions/0005`); no test executes it |
| Rules profile | **SELECTED** (owner): `[Gen 9 Champions] VGC 2026 Reg M-C`. Set legality (base forme, set moves, gender, nature, Stat Points, ability, item, Species and Item Clause) is **IMPLEMENTED + TESTED**; the battle rules are not |
| Team specifications | **SELECTED** (owner): two teams in `docs/decisions/0004`. The engine validates them and derives every stat line (tested), then **rejects them with `E_UNSUPPORTED`** at the support gate until the closure is complete |
| PCG32 RNG primitive and wrapper contract (0001) | **IMPLEMENTED + TESTED**; no gameplay draw sites exist yet (M3) |
| Arithmetic and byte helpers | **IMPLEMENTED + TESTED** (generic; no Pokémon-semantics helpers) |
| Owned structural state v3, identity, invariants (boundaries incl. TERMINAL, epochs, sealed commitments, knowledge, field and side conditions, volatile blocks, action queue) | **IMPLEMENTED + TESTED** (synthetic data only; the combat fields exist, but no mechanic writes them yet; decision 0006 section 3.1) |
| Canonical encoding v3 (semantics 3, 1009 bytes), SHA-256 digest, clone/copy/equal, reseed | **IMPLEMENTED + TESTED** (synthetic data only; the v1 and v2 goldens are rejected inputs) |
| Team selection (ordered picks), joint side-choice domains, requests, epochs, decision bundles | **IMPLEMENTED + TESTED** against the oracle (synthetic move target classes; `docs/decisions/0005`) |
| Team-selection transition (mechanics-free) | **IMPLEMENTED + TESTED** |
| Turn / replacement / pivot execution | **UNSUPPORTED** (`E_UNSUPPORTED`, atomic; M3/M4). REPLACEMENT and PIVOT boundaries exist structurally only |
| Rule-authorized re-prompt | **STRUCTURAL** (`dfi_reprompt_side`, white-box; no mechanic triggers it) |
| Struggle (all pp 0) | **IMPLEMENTED + TESTED** (offered in the request since step 2c; typeless, random target, recoil) |
| Observation prototype (open sheets, own exact, foe percent HP as last seen, tagged unknowns) | **IMPLEMENTED + TESTED** (prototype; statuses, stages and conditions are not shown yet) |
| Information-equivalence evidence | **TESTED** on paired synthetic states (`duoforge.request.information`) |
| Closure data tables (16 formes, 36 moves plus Struggle, 16 abilities, 11 items, type chart, natures) | **GENERATED + TESTED** from the pin with provenance per record (`tools/datagen/gen_closure.py`, `src/data/closure_tables.*`). **Data only:** no battle can use it yet |
| Champions stat and PP formulas | **IMPLEMENTED + TESTED** (all 16 formes of the two teams; decision 0006) |
| CLOSURE contexts (`CLOSURE`, `CLOSURE_DEV`), setup validation, derived stats and PP, support gate | **IMPLEMENTED + TESTED** (decision 0006 section 2.1); the manifest marks nothing yet |
| Damage and stat arithmetic (4096-based modifiers, base damage, random factor, critical hit, type steps, 16-bit final damage, stat and accuracy stages) | **IMPLEMENTED + TESTED** against values computed by the pinned Showdown (`tools/reference/arith_ref.js`); no move uses it yet |
| RNG draw sites and the test-only tape | **IMPLEMENTED + TESTED** (decision 0006 section 5); no mechanic draws yet |
| Turn core (queue order with speed ties, single and spread damage, accuracy, critical hits, random factor, STAB, type chart, stat stages, self-boosts, secondary stat changes, PP, Struggle, Protect with its stall counter) | **IMPLEMENTED + TESTED** for development teams (CLOSURE_DEV, No Ability, no items); replays 7 recorded reference battles draw for draw (decision 0006 section 4.1) |
| Switching, fainting, replacement, win rule and TERMINAL | **IMPLEMENTED + TESTED** for development teams; 5 of the 12 recorded reference battles play to the end (decision 0006 section 4.2) |
| Statuses, abilities, items, weather, terrain, side and field conditions, Mega Evolution, pivots | **UNSUPPORTED** (`E_UNSUPPORTED`, atomic; steps 4 to 12) |

State snapshots and decodability are foundation evidence, **not proof that unimplemented future mechanics restore correctly**.

## Licensing facts

`third_party/pcg-c-basic/` and `src/rng/pcg32_derived.{h,c}` contain material from pcg-c-basic, licensed by its author under the Apache License 2.0 (see `third_party/pcg-c-basic/LICENSE.txt`). The root `LICENSE` is the owner's placeholder; how it refers to third-party material is an open owner decision (`docs/OPEN_DECISIONS.md`).
