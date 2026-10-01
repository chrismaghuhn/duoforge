# Support and provenance manifest

This is a status manifest, **not** a mechanics certificate. For the mechanics of the combat closure, "IMPLEMENTED + TESTED" means checked against recorded battles of the pinned Showdown revision; it says nothing about Pokémon, moves, abilities or items outside the closure of the two reference teams.

| Area | Status |
|---|---|
| pcg-c-basic (RNG reference) | **PINNED** `bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3` (`third_party/pcg-c-basic/PROVENANCE.md`) |
| Pokémon Showdown (operational reference) | **PINNED** `b2cb775b0616115b775534eaeff50300e1fc81fc` (owner decision; `docs/decisions/0004`). Not vendored. M2 cites it for choice rules, team preview, target classes, open team sheets and HP display (`docs/decisions/0005`); no test executes it |
| Rules profile | **SELECTED** (owner): `[Gen 9 Champions] VGC 2026 Reg M-C`. Set legality (base forme, set moves, gender, nature, Stat Points, ability, item, Species and Item Clause) is **IMPLEMENTED + TESTED**; the battle rules are not |
| Team specifications | **SELECTED** (owner): two teams in `docs/decisions/0004`. The engine validates them, derives every stat line and plays them from team selection to the end; closure gate passed in step 13 (decision 0006 section 4.13) |
| PCG32 RNG primitive and wrapper contract (0001) | **IMPLEMENTED + TESTED**; the combat draws through the draw sites below |
| Arithmetic and byte helpers | **IMPLEMENTED + TESTED** (generic; no Pokémon-semantics helpers) |
| Owned structural state v3, identity, invariants (boundaries incl. TERMINAL, epochs, sealed commitments, knowledge, field and side conditions, volatile blocks, action queue) | **IMPLEMENTED + TESTED** (decision 0006 section 3.1): synthetic fixtures and the oracle, plus every state of the recorded battles and of random play with CLOSURE data |
| Canonical encoding v3 (semantics 3, 1009 bytes), SHA-256 digest, clone/copy/equal, reseed | **IMPLEMENTED + TESTED** (goldens with synthetic data; the v1 and v2 goldens are rejected inputs); states of real-team battles round-trip at every boundary in the closure gate |
| Team selection (ordered picks), joint side-choice domains, requests, epochs, decision bundles | **IMPLEMENTED + TESTED** against the oracle (synthetic move target classes; `docs/decisions/0005`) |
| Team-selection transition (mechanics-free) | **IMPLEMENTED + TESTED** |
| Turn / replacement / pivot execution | **IMPLEMENTED + TESTED** for CLOSURE data (decision 0006 sections 4.1, 4.2 and 4.12); every bundle under SYNTHETIC data stays `E_UNSUPPORTED` |
| Rule-authorized re-prompt | **STRUCTURAL** (`dfi_reprompt_side`, white-box; no mechanic triggers it) |
| Struggle (all pp 0) | **IMPLEMENTED + TESTED** (offered in the request since step 2c; typeless, random target, recoil) |
| Observation v2: what a player sees (decision 0007) | **IMPLEMENTED + TESTED**: the oracle gives the same bytes for every fixture and player; paired tests on synthetic and real states keep the hidden rolls hidden; the conformance test compares both players' views with the recorded Showdown battles |
| Event log per player (decision 0007 sections 6 and 11) | **IMPLEMENTED + TESTED**: every event of both players matches the protocol lines of the recorded Showdown battles, field by field (61 battles, 19,154 events, all 37 kinds); API failures are atomic; since step 3c each player's knowledge is folded from its events only |
| Information-equivalence evidence | **TESTED** on paired synthetic states (`duoforge.request.information`) |
| Closure data tables (16 formes, 36 moves plus Struggle, 16 abilities, 11 items, type chart, natures) | **GENERATED + TESTED** from the pin with provenance per record (`tools/datagen/gen_closure.py`, `src/data/closure_tables.*`). Used by every CLOSURE battle |
| Champions stat and PP formulas | **IMPLEMENTED + TESTED** (all 16 formes of the two teams; decision 0006) |
| CLOSURE contexts (`CLOSURE`, `CLOSURE_DEV`), setup validation, derived stats and PP, support gate | **IMPLEMENTED + TESTED** (decision 0006 section 2.1); since step 12 the manifest marks every mechanic of the closure |
| Team C expansion: extended tables (closure plus Team C) and the TEAM_C contexts (`TEAM_C`, `TEAM_C_DEV`) | **GENERATED + IMPLEMENTED + TESTED** for step 1 (decision 0009 section 10.1): the closure is the tables' exact prefix (`src/data/extended_tables.*`), TEAM_C takes over the certified profile; Kowtow Cleave, Hyper Voice, Draco Meteor, Wave Crash, Aqua Jet, Defiant and Adaptability against recorded reference battles (`duoforge.reference.conformance_team_c`); every other Team C mechanic is rejected at setup (`E_UNSUPPORTED`) |
| Damage and stat arithmetic (4096-based modifiers, base damage, random factor, critical hit, type steps, 16-bit final damage, stat and accuracy stages) | **IMPLEMENTED + TESTED** against values computed by the pinned Showdown (`tools/reference/arith_ref.js`); every damaging move uses it |
| RNG draw sites and the test-only tape | **IMPLEMENTED + TESTED** (decision 0006 section 5); every draw of the recorded battles comes from the tape at its site |
| Turn core (queue order with speed ties, single and spread damage, accuracy, critical hits, random factor, STAB, type chart, stat stages, self-boosts, secondary stat changes, PP, Struggle, Protect with its stall counter) | **IMPLEMENTED + TESTED** against recorded reference battles, draw for draw (decision 0006 section 4.1) |
| Switching, fainting, replacement, win rule and TERMINAL | **IMPLEMENTED + TESTED** against recorded reference battles that play to the end (decision 0006 section 4.2) |
| Burn, paralysis, sleep and freeze (Champions variants), flinch, confusion | **IMPLEMENTED + TESTED** against recorded reference battles (decision 0006 section 4.3) |
| Entry abilities Drizzle, Grassy Surge and Intimidate; rain; Grassy Terrain's heal; the ordered residual phase | **IMPLEMENTED + TESTED** against recorded reference battles (decision 0006 section 4.4) |
| Drought and sun | **IMPLEMENTED + TESTED** since step 11 (Mega Charizard Y) |
| Tailwind, Reflect, Light Screen, Trick Room | **IMPLEMENTED + TESTED** against recorded reference battles (decision 0006 section 4.5) |
| Stamina, Competitive, Flash Fire (absorb), Lightning Rod, Good as Gold, Armor Tail, Prankster, Blaze | **IMPLEMENTED + TESTED** against recorded reference battles (decision 0006 section 4.6) |
| Leftovers, Sitrus Berry, Grassy Seed, Life Orb, Mystic Water, Light Clay | **IMPLEMENTED + TESTED** against recorded reference battles (decision 0006 section 4.7) |
| Recoil (Wood Hammer, Brave Bird), drain (Bitter Blade, Leech Life), self-drops (Close Combat, Make It Rain), Miracle Seed, Grassy Terrain's Grass boost, Flash Fire's boost | **IMPLEMENTED + TESTED** against recorded reference battles (decision 0006 section 4.8) |
| Weather Ball, Grass Knot, Grassy Glide, Fake Out (disabled after the first move action) | **IMPLEMENTED + TESTED** against recorded reference battles; the request is compared with the reference's after every step (decision 0006 section 4.9) |
| Electro Shot (charge, rain, locked move in the request) | **IMPLEMENTED + TESTED** against recorded reference battles (decision 0006 section 4.10) |
| Mega Evolution with the four stones, Contrary, No Guard, Tough Claws | **IMPLEMENTED + TESTED** against recorded reference battles (decision 0006 section 4.11) |
| Emergency Exit, Parting Shot, PIVOT boundaries | **IMPLEMENTED + TESTED** against recorded reference battles, including Emergency Exit at the end of a turn and two Emergency Exits at once (decision 0006 section 4.12) |
| Closure gate: both real teams in all four pairings | **PASSED** (step 13): 4000 random battles end without errors, replay byte for byte and keep information equivalence; 58 recorded reference battles at the gate, 8 of them with the real teams (decision 0006 section 4.13); 61 since the event log |

State snapshots and decodability are foundation evidence, **not proof that unimplemented future mechanics restore correctly**.

## Licensing facts

`third_party/pcg-c-basic/` and `src/rng/pcg32_derived.{h,c}` contain material from pcg-c-basic, licensed by its author under the Apache License 2.0 (see `third_party/pcg-c-basic/LICENSE.txt`). The root `LICENSE` is the owner's placeholder; how it refers to third-party material is an open owner decision (`docs/OPEN_DECISIONS.md`).
