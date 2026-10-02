# Gaps of the cheapest complete teams (expansion order)

Status: **research draft**, agent-generated on 2026-10-02 (Builder C of the expansion track). It is not a contract, not evidence and not a support claim (see `../README.md`). Showdown pin `b2cb775b0616115b775534eaeff50300e1fc81fc`. The DuoForge state analysed is `origin/main` `cfe18c0` (library 0.19.0, Team C complete, differential loop merged); decision 0015 is read from `origin/chris/expansion-p1-pool`. Machine-readable twin: `data/team_gaps.json`; every table below is generated from the same data by `tools/tg_build.js`.

## 1. Summary

- **The survey list is right, and incomplete as a plan.** An independent check from the paste text and the pinned validator reproduces the 29 gaps of the 17 cheapest teams exactly (3 species, 1 ability, 5 items, 20 moves), with no disagreement, no invalid set and every Stat Point spread inside 32 per stat and 66 in total.
- **Name coverage is not playability (F1).** The engine accepts one fixed four-move set per forme (`closure_member.c:41-49`). Only Teams A and B (MC405, MC408) are inside it; the other 15 teams need 42 (forme, move) pairs it lacks. Without a legal-move rule per forme (step G1) no team beyond A and B can be set up, however many rows are added.
- **Gaps are cheaper than they look (F2).** 12 of the 22 moves are encoded by the generator today (Ice Punch needs one ignored flag) and need evidence only; the three species are rows. The real mechanics are Encore (L); Wide Guard, Throat Chop, Soak, Flower Veil and P2 (M); and S items (the pivot cause of U-turn, Focus Sash, Rock Head, Expert Belt, Psychic Noise, First Impression, Scald, Recover, Low Kick, Fairy Aura with Floettite).
- **Three shared resources are full (F3, F4):** the volatile byte, the move flags byte and the position block. Five entries (Throat Chop, Encore, Psychic Noise, Soak, Wide Guard) need state; a POOL-only state tail (step G3) and a second flags column are the way to avoid touching any CLOSURE or TEAM_C byte.
- **Two harness findings (F5):** `ps_trace.js` records Encore's random-target draw as INSERT_TIE, and the converter drops RANDOM_TARGET draws although this one decides the target; the converter also lacks the lines of U-turn, Wide Guard, Encore, Heal Block and Soak.
- **The plan:** G1 to G3 first (one builder for G1 then G2, the state tail beside G2), then the mechanic steps, whose files are disjoint in most pairs (section 5.3). With five builders all 17 teams are playable at t=34 effort points after P1 (MC264, last step G8b); the first new teams after A and B (MC172, MC385) arrive at t=10 with the Focus Sash and Rock Head steps.
- **Variety rule (section 5.4):** near-duplicates of Team A, B or C by the 5-species test: MC246 (5 species shared with A, plan position 5 against curve.txt 3), MC36 (5 species shared with C, plan position 13 against curve.txt 12). The tie-break demotes them only when another team costs within 2 points; the tie events are listed in section 5.4.
- **Owner questions:** 5, the first two block the plan (section 6).

## 2. Verification of the gap list

**Method** (`tools/tg_verify_teams.js`): each paste is read with Showdown's own `Teams.import` and validated with the pinned `TeamValidator` (on a copy: the validator rewrites Mega names); each set's forme (a Mega name becomes its base forme with the stone), item, ability, moves and nature are looked up in `src/data/*.h` and `*.c` of the working tree, not in a list; each set is compared with the fixed set of its forme in the tables.

| Curve | Team | Placing / role | Species | Gaps (by name) | Valid | Inside the member rule today |
|---|---|---|---|---|---|---|
| 1 | MC405 | Team A | Rillaboom, Staraptor, Milotic, Ceruledge, Raichu, Gholdengo | none | yes | yes |
| 2 | MC408 | Team B | Politoed, Golisopod, Archaludon, Farigiraf, Charizard, Grimmsnarl | none | yes | yes |
| 3 | MC246 | 9th | Salamence, Gholdengo, Rillaboom, Milotic, Raichu, Ceruledge | Colbur Berry, Bulk Up | yes | no (2) |
| 4 | MC371 | - | Golisopod, Basculegion, Pelipper, Archaludon, Sneasler, Salamence | Pelipper, Wide Guard | yes | no (6) |
| 5 | MC373 | 383rd | Gholdengo, Sneasler, Salamence, Rillaboom, Incineroar, Raichu | Encore, Rock Slide | yes | no (2) |
| 6 | MC177 | - | Golisopod, Rillaboom, Kingambit, Incineroar, Raichu, Milotic | First Impression, Throat Chop, U-turn | yes | no (6) |
| 7 | MC22 | - | Rillaboom, Golisopod, Salamence, Incineroar, Farigiraf, Basculegion | First Impression, Throat Chop, U-turn | yes | no (6) |
| 8 | MC97 | - | Rillaboom, Golisopod, Pelipper, Milotic, Archaludon, Farigiraf | Pelipper, Flash Cannon, Thunderbolt, U-turn, Wide Guard | yes | no (10) |
| 9 | MC167 | - | Sneasler, Golisopod, Farigiraf, Rillaboom, Basculegion, Salamence | Double-Edge, Soak, Thunderbolt, U-turn | yes | no (8) |
| 10 | MC264 | - | Raichu, Farigiraf, Incineroar, Golisopod, Milotic, Rillaboom | Expert Belt, Encore, Psychic Noise, Thunderbolt | yes | no (6) |
| 11 | MC392 | 21st | Pelipper, Basculegion, Archaludon, Salamence, Rillaboom, Golisopod | Pelipper, Expert Belt, Focus Sash, Drum Beating | yes | no (6) |
| 12 | MC36 | - | Rillaboom, Salamence, Kingambit, Sneasler, Incineroar, Basculegion | Focus Sash, Occa Berry, Double-Edge, Liquidation, Throat Chop, U-turn | yes | no (8) |
| 13 | MC56 | - | Golisopod, Rillaboom, Farigiraf, Kingambit, Pelipper, Salamence | Pelipper, Black Glasses, Colbur Berry, Liquidation, Thunderbolt, U-turn, Wide Guard | yes | no (9) |
| 14 | MC215 | - | Milotic, Pelipper, Kingambit, Rillaboom, Golisopod, Raichu | Pelipper, Black Glasses, Focus Sash, Encore, Recover, Scald, U-turn, Wide Guard | yes | no (11) |
| 15 | MC196 | Runner Up | Pelipper, Incineroar, Rillaboom, Archaludon, Annihilape, Golisopod | Annihilape, Pelipper, Flash Cannon, Ice Punch, Shadow Claw, U-turn, Wide Guard | yes | no (12) |
| 16 | MC172 | - | Farigiraf, Arcanine, Rillaboom, Salamence, Kingambit, Sneasler | Arcanine-Hisui, Focus Sash, Rock Head, Extreme Speed, Head Smash, Thunderbolt | yes | no (6) |
| 17 | MC385 | 59th | Salamence, Raichu, Arcanine, Rillaboom, Gholdengo, Milotic | Arcanine-Hisui, Focus Sash, Rock Head, Extreme Speed, Head Smash | yes | no (5) |

**Result.** Union of the gaps: 3 species (Annihilape, Arcanine-Hisui, Pelipper), 1 ability (Rock Head), 5 items (Black Glasses, Colbur Berry, Expert Belt, Focus Sash, Occa Berry), 20 moves (Bulk Up, Double-Edge, Drum Beating, Encore, Extreme Speed, First Impression, Flash Cannon, Head Smash, Ice Punch, Liquidation, Psychic Noise, Recover, Rock Slide, Scald, Shadow Claw, Soak, Throat Chop, Thunderbolt, U-turn, Wide Guard); natures none (all 25 are in the table). Disagreements with the main session's list by name: **0**. Validator: all 17 teams valid; Stat Points: every set at most 32 per stat and 66 in total. Over all 227 pastes: MC214 and MC213 are invalid (the nonexistent move Precipice Blades), none of them among the 17; only MC405 and MC408 are inside the tables and the member rule.

**Where a name match is not enough** (finding F8 and F1):

| Item | Check | Result |
|---|---|---|
| Forme names | Floette-Eternal vs Floette-Mega, Indeedee-F vs Indeedee (M), Arcanine-Hisui, a Mega name in a paste | MC172 names Salamence-Mega: the setup needs Salamence with Salamencite and its own ability. Five survey teams (MC210, MC221, MC222, MC296, MC354) name Floette-Mega: the base is Floette-Eternal holding Floettite. None of them is among the 17. Indeedee (M) is another forme (Speed 95 against 85) and is not in the tables. |
| Items and stones | does every Mega stone fit its holder | yes in all 17 teams (the validator does not check it: README section 2) |
| Abilities | is the set ability the one the table row would carry | yes in all 17: Pelipper Drizzle, Arcanine-Hisui Rock Head, Annihilape Defiant; in the 227 pastes 14 of 68 formes use more than one ability (Arcanine-Hisui: 28 Rock Head, 5 Intimidate) |
| Natures | all in the 25 of the table | yes |
| Genders | explicit in the paste? | rarely (Grimmsnarl, Basculegion); Showdown draws a random gender for a missing one on a 50/50 species (sim/pokemon.ts:340), the engine requires one (male for every 50/50 species, decision 0009); Floette-Eternal is female only |
| Stat Points | 66 in total, 32 per stat (the Champions rule) | yes in all 227 pastes |
| Moves | in the table AND in the forme's fixed set | no for 15 of the 17 teams (finding F1) |

## 3. Cross-cutting findings

| Id | Finding | Evidence | Consequence | Proposal |
|---|---|---|---|---|
| F1 | Name coverage is not playability: the member rule accepts one fixed set per forme | src/state/closure_member.c:41-49 (dfi_in_set), :86 (setup), :353 (invariant), :102 and :316 (the one ability). Decision 0006 section 2.1 and 0009 section 3.4 define a member as "1 to 4 moves of the forme's set"; 0015 keeps the CLOSURE rules for POOL. tg_verify_teams.js over the 17 teams: only MC405 and MC408 (Teams A and B) are inside; 15 teams carry 42 (forme, move) pairs outside the fixed sets (Protect on Milotic, Swords Dance on Kingambit, Sucker Punch on Golisopod, ...), the gap moves included. The abilities are not the problem here: every set of the 17 uses the one ability the new formes would get. | Closing all 29 gaps as table rows would still leave 15 teams unplayable: every real team beyond A and B needs moves that its forme's fixed set lacks. | A step G1 before any team: the legal moves per forme (a bitset over the pool's moves, derived from the pinned learnsets and cross-checked with legal_pool.json) replace the fixed set under POOL; the ability list per forme can follow (14 of 68 formes in the 227 pastes use more than one ability). Best taken into P1 now, because it is a column of the POOL tables and the POOL fingerprint covers it. |
| F2 | The gap count overstates the cost of data and understates the mechanics | tg_probe_generator.py: 12 of the 22 moves are encoded by the generator today (U-turn, Rock Slide, Double-Edge, Thunderbolt, Flash Cannon, Extreme Speed, Head Smash, Bulk Up, Liquidation, Shadow Claw, Drum Beating, Dazzling Gleam); Ice Punch needs only an ignored flag. The three species are rows. What costs engine work: Encore (L), Wide Guard, Throat Chop with Psychic Noise, Soak, Flower Veil (M), the pivot cause, Focus Sash, Rock Head, First Impression, Scald, Recover, Low Kick, Fairy Aura, and the P2 items (S each). | Teams that look expensive by gap count are cheap by mechanics (MC172 and MC385 need Focus Sash and Rock Head, two S steps) and one-gap teams can be the dearest (MC373: Encore). | Order by effort of the missing mechanics, not by gap count (section 5.4). |
| F3 | The state has no room for the new volatiles | The position's volatile byte is full: eight bits in use (battle_internal.h:62-70). The position block is 21 bytes with no spare byte (src/codec/state_codec.h:10-50, :93). Needed: Encore (last move, slot and turns), Throat Chop and Heal Block (two-turn timers), a Soak type override, and a Wide Guard flag per side. The position view's `reserved` byte has bits 8 to 128 free (duoforge.h:439-446). | Five of the 35 entries need new state; the first of them cannot be built without a layout decision. Decision 0009 stayed inside the v3 layout; this cannot. | One step G3 that adds a POOL-only tail to the state (about 18 bytes: four bytes per position and one per side), valid only under the POOL kinds like 0009's Team C values, so every CLOSURE and TEAM_C state keeps its bytes. Alternatives: schema 4 for every kind (all goldens change) or bit-sharing in spare bits of existing bytes (no size change, obscure). Owner decision (section 6). |
| F4 | The move row's flags byte is full, and three flags gain readers | gen_closure.py:83-84 uses all eight bits. `sound` is read by Throat Chop and held by Snarl (26), Parting Shot (35) and Hyper Voice (40) in the tables today; `heal` is read by Heal Block and is set on drain moves too (the pool has 23, Bitter Blade 12 and Leech Life 21 among the table's); `thawsTarget` is a property of Scald. IGNORED_FLAGS lists sound and heal (gen_closure.py:89-91). `punch`, `slicing` and `allyanim` have no reader in the tables. | Marking Throat Chop or Psychic Noise without the bits would be a silent misbehaviour for existing moves. | A second flags column in the POOL tables (G2/P1) filled for every id, prefix included, with sound, heal, thaws_target; `punch`, `slicing`, `allyanim` go to IGNORED_FLAGS with a generator test that fails when their reader (Iron Fist, Sharpness) enters the tables. The closure and TEAM_C canonical bytes keep only the first byte, like the psn immunity bit of 0009. |
| F5 | Harness and converter gaps found by running the mechanics | tg_probe_reference.js: (a) Encore's changeAction draws a random target inside insertChoice, and ps_trace.js:90-91 tests `insertChoice` before `getRandomTarget`, so the draw is recorded as INSERT_TIE/queue (a probe patch of PRNG.sample confirms one target draw and no tie draw). (b) The converter drops RANDOM_TARGET `resolve` (trace_to_c.py:321-322) although this one decides the target. (c) An unknown `cant` reason is a bare KeyError (trace_to_c.py:667-676), as is `-fail\|X\|heal` (:686-687). (d) The protocol name of Arcanine-Hisui and Floette-Eternal is the base species; only Indeedee-F is mapped (:356). (e) Unknown lines: `[from] U-turn`, `-singleturn\|..\|Wide Guard`, `-start\|..\|Encore` and `\|move: Heal Block`, `-start\|..\|typechange`, `-block`. (f) The ModifyDamage tie rule knows screens and {Life Orb, Chople Berry} only. | Each of these stops a trace loudly or, for (a) and (b), would put a wrong draw in the tape; none is silent, but each step needs its converter change. | Each step lists its converter and harness change (section 5.2). (a) and (b) belong to Encore and are the only ones that change the harness; its version stays 14 because no committed trace has a changeAction. |
| F6 | Row-adding PRs in parallel would fight over generated files | Decision 0015 section 2: the POOL fingerprint changes with every PR that changes the pool data; the generated tables and their sha256 pins in tests/CMakeLists.txt are single files. Decision 0009 section 3.2 generated all Team C data in step 1 for this reason. | Five builders adding their own rows would conflict on the generated file, the pins and the id order, and every recorded trace would need regeneration after each merge. | G2 adds every gap row and every column once (unmarked); the mechanic steps only mark and implement and do not touch the tables. The 35 ids and their columns are in team_gaps.json (`pool_rows`). |
| F7 | Class re-check against classification.json | Five entries change: Ice Punch B to A (the generator needs an ignored flag, no bit; Iron Fist is not in the tables), Rock Head D/M to S, Expert Belt D/M to S, Psychic Noise B to M (Heal Block is a mechanic of its own), Wide Guard C/param with new side state. U-turn stays B (the data is A, the engine's cause is the extension). | Efforts in section 5 follow the re-check. | None. |
| F8 | Verification caveats that are not disagreements | A paste that names a Mega forme (Salamence-Mega in MC172; Floette-Mega in five survey teams) is the base forme holding its stone: the setup refuses a Mega forme, and the ability is the base's (Intimidate, Flower Veil). Indeedee (M) is a different forme from Indeedee-F (Speed 95 against 85) and is not in the tables; the survey name `Indeedee` must not be read as Indeedee-F. Most pastes omit the gender; the engine requires one (decision 0009: male for every 50/50 species), and Showdown draws a random gender for a missing one (sim/pokemon.ts:340), so a spec must state it. Two of the 227 pastes (MC213, MC214) name a move that does not exist (Precipice Blades) and fail the validator; neither is among the 17. | The team converter (not part of this note) normalises all four. | None. |

## 4. The gaps

The 35 entries are the 29 of the survey, Low Kick, Dazzling Gleam, Floette-Eternal with Floettite and Flower Veil, and Fairy Aura (Floette-Mega's only ability, which the survey list does not name but the setup gate requires). Each card answers the questions of the task: the pinned implementation (`moves.ts:N` is `data/moves.ts`, `champions/...` is `data/mods/champions/...`, `sim/...` the pinned sim directory, `turn.c` and `request.c` of `origin/main`), the draws, the protocol lines (the converter's gaps in bold), DuoForge today, new state, interactions and evidence. Every claim about a printed line or a draw is a run of `tools/tg_probe_reference.js`; every file:line is checked by `tools/tg_check_cites.js`.

### 4.1 Species and formes

#### Pelipper

| Aspect | Entry |
|---|---|
| Used by | MC371, MC97, MC392, MC56, MC215, MC196 (6 of 17; 28 of 227 pastes) |
| Pinned | pokedex.ts:5458-5470: Water/Flying, 60/50/100/95/70/65, abilities Keen Eye / Drizzle / Rain Dish(H), 28 kg, dex 279. No override. All 28 Pelipper sets of the 227 pastes use Drizzle, so one ability per forme is enough here. |
| Draws | None. |
| Protocol lines | `\|switch\|p1a: Pelipper\|Pelipper, L50, M\|..` (the protocol name is the species name). |
| DuoForge today | Tables: no (23 formes). Generator: needs a SETS row (species, Drizzle, item, four moves, no Mega); parse_forme reads the dex entry, the Champions formats-data and the learnset (gen_closure.py:340-359, 456-470).<br>Class: none (species are not classified). Re-check: Data only: weight 280 hg, gender rule any, no Mega. The moves of its sets are Weather Ball, Hurricane, Tailwind (built), Wide Guard (G7), Protect, Helping Hand, Ice Beam.<br>Engine: Drizzle is built (turn.c:2683-2692). Flying makes it not grounded (turn.c:111-114). |
| State, public, request | None: species_id is u16 (battle_internal.h:97); the forme row is data. The fixed-set columns of the row are replaced by the legal-move set of G1. |
| Interactions | Flying: Psychic Terrain does not stop priority moves at it and Grassy Terrain neither heals nor boosts for it; x4 weak to Electric (Thunderbolt, Zap Cannon, Electro Shot), x2 to Rock (Rock Slide), immune to Ground; Soak makes it grounded Water (G11).<br>Rain from Drizzle: Hurricane never misses, Weather Ball is Water; its own Tailwind and Wide Guard; Intimidate and Competitive entries run in switch order. |
| Evidence | Spec g02_species_pelipper: the lead entry (Drizzle), Hurricane in rain, Weather Ball, Tailwind; Wide Guard follows with G7<br>Test: Prefix and row tests: weight, types, stats against the pin. |
| Step | G2, effort XS (1 point) |

#### Arcanine-Hisui

| Aspect | Entry |
|---|---|
| Used by | MC172, MC385 (2 of 17; 33 of 227 pastes) |
| Pinned | pokedex.ts:1515-1531: Fire/Rock, 95/115/80/95/80/90, abilities Intimidate / Flash Fire / Rock Head(H), 168 kg, dex 59, 75 % male. Rock Head in 28 of 33 sets of the 227 pastes, Intimidate in 5. |
| Draws | None. |
| Protocol lines | The protocol name of an unnamed Pokemon is its base species: `\|switch\|p1a: Arcanine\|Arcanine-Hisui, L50, M\|..` (sim/pokemon.ts:339-341).<br>**Unknown to the converter:** trace_to_c.py:356 maps only `Indeedee-F` to its protocol name; `Arcanine-Hisui` -> `Arcanine` is a new entry (an unmapped name stops with `unknown-pokemon`). |
| DuoForge today | Tables: no. Generator: needs a SETS row (Rock Head for the 17 teams).<br>Class: none. Re-check: Data only: weight 1680 hg, gender rule any, no Mega. The five Intimidate sets need the ability list of G1.<br>Engine: Rock Head is G4; Intimidate and Flash Fire are built. |
| State, public, request | None: species_id is u16 (battle_internal.h:97); the forme row is data. The fixed-set columns of the row are replaced by the legal-move set of G1. |
| Interactions | Fire/Rock: x4 weak to Water and Ground (`-supereffective` amount 2), x2 to Fighting and Rock; cannot be burned; Flash Fire absorbs Fire moves (turn.c:2168-2180).<br>Head Smash and Flare Blitz with Rock Head: no recoil (G4); Extreme Speed (priority +2) against Psychic Terrain and Armor Tail; Focus Sash on the lead. |
| Evidence | Spec g02_species_arcanine: Intimidate set and Rock Head set (with G4)<br>Test: Alias test: `Arcanine` names Arcanine-Hisui in a trace. |
| Step | G2, effort XS (1 point) |

#### Annihilape

| Aspect | Entry |
|---|---|
| Used by | MC196 (1 of 17; 1 of 227 pastes) |
| Pinned | pokedex.ts:18771-18784: Fighting/Ghost, 110/115/80/50/90/90, abilities Vital Spirit / Inner Focus / Defiant(H), 56 kg, dex 979. The one set in the 227 pastes (MC196) is Choice Scarf, Defiant, Close Combat / Ice Punch / Shadow Claw / U-turn. |
| Draws | None. |
| Protocol lines | `\|switch\|p1a: Annihilape\|Annihilape, L50, M\|..`. |
| DuoForge today | Tables: no. Generator: needs a SETS row (Defiant, Choice Scarf).<br>Class: none. Re-check: Data only: weight 560 hg, gender rule any, no Mega. Defiant and Choice Scarf are built; Ice Punch, Shadow Claw are A (G2), U-turn is G5.<br>Engine: Defiant turn.c:567-572; Choice Scarf lock turn.c:1849-1853. |
| State, public, request | None: species_id is u16 (battle_internal.h:97); the forme row is data. The fixed-set columns of the row are replaced by the legal-move set of G1. |
| Interactions | Ghost: immune to Normal and Fighting (Fake Out, Extreme Speed, a foe's Close Combat); Fighting/Ghost weak to Flying, Psychic, Ghost, Fairy; Choice Scarf lock with U-turn ends on leaving. |
| Evidence | Spec g02_species_annihilape: Close Combat, Ice Punch, Shadow Claw, then U-turn (with G5) |
| Step | G2, effort XS (1 point) |

#### Floette-Eternal (and Floette-Mega)

| Aspect | Entry |
|---|---|
| Used by | none of the 17 (58 of 227 pastes); next ring |
| Pinned | pokedex.ts:12573-12586: Fairy, 74/65/67/125/128/92, abilities Flower Veil / Symbiosis(H), gender F only, 0.9 kg, dex 670. Floette-Mega (:12587-12603): Fairy, 74/85/87/155/148/102, ability Fairy Aura, 100.8 kg, requiredItem Floettite, battleOnly Floette-Eternal.<br>58 of the 227 pastes carry it: Flower Veil 55 / Fairy Aura 3 (a paste that names the Mega), item always Floettite, moves Protect 58, Dazzling Gleam 55, Calm Mind 44, Moonblast 40, Draining Kiss 19, Light of Ruin 16. |
| Draws | None. |
| Protocol lines | `\|switch\|p1a: Floette\|Floette-Eternal, L50, F\|..`; at the Mega `\|detailschange\|p1a: Floette\|Floette-Mega, L50, F`, `\|-mega\|p1a: Floette\|Floette\|Floettite`, `\|-ability\|p1a: Floette\|Fairy Aura` (probe `fairyaura`).<br>**Unknown to the converter:** The protocol name is `Floette`: `Floette-Eternal` -> `Floette` is a new alias (trace_to_c.py:356). |
| DuoForge today | Tables: no. Generator: needs a SETS row with the Mega (gen_closure.py:471-482 checks that the stone matches: items.ts megaStone {Floette-Eternal: Floette-Mega}).<br>Class: none. Re-check: Two rows (base and Mega), gender rule FEMALE, Mega weight 1008 hg. Not the name the survey list uses: a paste that says `Floette-Mega` is Floette-Eternal holding Floettite (MC221, MC222, MC296, MC354, MC210 in the survey). Other set moves: Moonblast (Champions override: 10 %), Calm Mind and Draining Kiss encode today; Light of Ruin is rejected only for its `tags` data key (a Champions-enabled Past move, 1/2 recoil).<br>Engine: The Mega machinery is generic (closure_member.c:131-135, turn.c:2827-2855) and the setup gate needs the Mega's ability marked (closure_member.c:145-150): Floette-Eternal cannot hold Floettite before Fairy Aura is built. |
| State, public, request | None: species_id is u16 (battle_internal.h:97); the forme row is data. The fixed-set columns of the row are replaced by the legal-move set of G1. |
| Interactions | Flower Veil protects its Grass allies (Rillaboom) from Intimidate and status moves; Fairy Aura boosts every Fairy move on the field after the Mega (G12).<br>Species Clause: dex 670; weight 9 hg before and 1008 hg after the Mega (Low Kick, Grass Knot). |
| Evidence | Spec g12_floette_mega: Mega Evolution (forme line, Mega line, ability line), Dazzling Gleam before and after<br>Test: Setup test: Floette-Eternal with Floettite is `E_UNSUPPORTED` until Fairy Aura is marked. |
| Step | G12 (item G12b), effort S (2 points) |

### 4.2 Abilities

#### Rock Head

| Aspect | Entry |
|---|---|
| Used by | MC172, MC385 (2 of 17; 28 of 227 pastes) |
| Pinned | abilities.ts:3906-3917: onDamage: when the effect is `recoil` and the active move is not Struggle, return null (the damage is cancelled). Struggle's recoil never reaches the handler: it is applied with directDamage as `strugglerecoil` (sim/battle-actions.ts:1388-1389), and spreadDamage skips the Damage event for that id (sim/battle.ts:2115). Life Orb damage is an item effect, not `recoil`. No override. |
| Draws | None. |
| Protocol lines | None: the recoil line is simply absent (probe `rockhead`: Head Smash hits, no `[from] Recoil`). |
| DuoForge today | Tables: no (21 abilities). Generator: ability ids carry no data; the row needs the id.<br>Class: D, size M. Re-check: S, not M: one predicate where the recoil is applied. D/S.<br>Engine: Recoil is applied at turn.c:2449-2465; Struggle's is the same code with the STRUGGLE_RECOIL flag (turn.c:2451), which must stay. |
| State, public, request | None. |
| Interactions | Recoil moves: Head Smash, Flare Blitz, Double-Edge, Wood Hammer, Brave Bird, Wave Crash; not Struggle, not Life Orb.<br>The attacker's Emergency Exit check after the recoil (turn.c:2464) must not run when no damage happened; a recoil that would have faulted the user no longer does (a battle ends differently).<br>Focus Sash and Rock Head on one Arcanine-Hisui are the two items of MC172 and MC385: Sash is lost to a lethal hit, Rock Head never. |
| Evidence | Spec g04_rock_head: Head Smash and Flare Blitz with no recoil line, a Rock Head user that would have fainted from recoil, Struggle with a Rock Head user (recoil stays)<br>Test: Negative controls: recoil on Struggle skipped; Life Orb skipped. |
| Step | G4 (item G4b), effort S (2 points) |

#### Flower Veil

| Aspect | Entry |
|---|---|
| Used by | none of the 17 (55 of 227 pastes); next ring |
| Pinned | abilities.ts:1419-1457: onAllyTryBoost: for a Grass-type holder or ally (not a self-inflicted change) every negative boost is deleted and `-block\|target\|ability: Flower Veil\|[of] holder` is shown unless the effect has secondaries; onAllySetStatus: a status from another Pokemon's move without secondaries (or Synchronize) is blocked with the same line, a status from a secondary is blocked silently; onAllyTryAddVolatile: Yawn. flags breakable. No override. |
| Draws | None. |
| Protocol lines | `\|-block\|p1b: Rillaboom\|ability: Flower Veil\|[of] p1a: Floette` after Intimidate's `-ability` line, with no `-unboost` for that target (probe `flowerveil`, step 0).<br>**Unknown to the converter:** `-block`: trace_to_c.py:774-775 (`protocol-line`). |
| DuoForge today | Tables: no. Generator: ability ids carry no data.<br>Class: D, size M. Re-check: D/M confirmed: two hooks and a new public line.<br>Engine: The TryBoost point is in dfi_boost after Contrary and the cap (turn.c:522-529); the status point is dfi_try_status (turn.c:1028-1081). The holder's own side is the flat position XOR 1. |
| State, public, request | None; one event kind (BLOCK with the holder in `other`, cause ABILITY + id2). |
| Interactions | Intimidate on Rillaboom: no drop, so Defiant/Competitive of that Pokemon never trigger; the line is shown per Grass target.<br>Hypnosis, Will-O-Wisp, Spore and the like are blocked on Grass allies; Dire Claw's status pick is blocked silently (it is a secondary), but its SECONDARY and STATUS_PICK draws still happen.<br>Soak makes a Grass ally Water, ending the protection; Contrary reverses the drop first, so nothing is blocked.<br>Floette itself is Fairy, so the holder has no self protection; what it covers is every Grass-type ally on the field. |
| Evidence | Spec g12_flower_veil: the opening Intimidates against a Rillaboom ally, Hypnosis at it, Snarl's secondary drop (silent), the same without the holder<br>Test: Negative controls: no block for a non-Grass ally; Defiant triggering through the block. |
| Step | G12 (item G12a), effort M (4 points) |

#### Fairy Aura (the Mega's ability)

| Aspect | Entry |
|---|---|
| Used by | none of the 17 (3 of 227 pastes); next ring |
| Pinned | abilities.ts:1266-1282: onStart `-ability\|X\|Fairy Aura`; onAnyBasePower at priority 20: a non-status Fairy move that is not self-targeted gets x5448/4096 (x3072/4096 with Aura Break), applied once per move through `move.auraBooster`. Mega-only: Floette-Mega has no other ability. The Start runs at the Mega Evolution (sim/pokemon.ts:1487, 1943). No override. |
| Draws | None. |
| Protocol lines | `\|-ability\|p1a: Floette\|Fairy Aura` after the `-mega` line (probe `fairyaura`). |
| DuoForge today | Tables: no. Generator: ability ids carry no data; it is the ability of a Mega forme row (gen_closure.py:476-479).<br>Class: C, aura, param. Re-check: C confirmed; the family has one legal member, so one rule. The survey list does not name it: it is a gap of Floette-Eternal + Floettite.<br>Engine: BasePower chain turn.c:837-866 (Aerilate 23, Tough Claws 21, the type items 15, Helping Hand 10, terrains 6); the Mega entry runs turn.c:2846-2851 through dfi_has_entry. |
| State, public, request | None. |
| Interactions | Any Fairy move of anyone on the field, a foe's included (Hyper Voice under Pixilate later); two holders boost once; Dazzling Gleam, Moonblast, Draining Kiss (a drain move), Light of Ruin.<br>Chain order: Aerilate/-ate (23) before Fairy Aura (20) before the type items (15): the rounding of the chained modifier depends on it. |
| Evidence | Spec g12_fairy_aura: Dazzling Gleam before and after the Mega, a foe's Fairy move, two holders (one boost)<br>Test: Negative control: the boost for a status move and for a self-targeted one. |
| Step | G12 (item G12b), effort S (2 points) |

### 4.3 Items

#### Focus Sash

| Aspect | Entry |
|---|---|
| Used by | MC392, MC36, MC215, MC172, MC385 (5 of 17; 131 of 227 pastes) |
| Pinned | items.ts:2269-2285: onDamage at priority -40: when the target is at full HP, the damage is at least its HP and the effect is a Move, `target.useItem()` and the damage becomes `hp - 1`. Recoil (effect type Recoil), Rocky Helmet, Life Orb, weather and status damage are not Moves, so the sash ignores them. A confusion hit is a Move, but cannot be lethal at full HP. No override. |
| Draws | None. |
| Protocol lines | `\|-enditem\|p2a: Pelipper\|Focus Sash` before the `-damage` line (probes `focussash`, `rockhead`: after `-supereffective` in a spread hit). |
| DuoForge today | Tables: no (16 items). Generator: items carry only the Mega mapping.<br>Class: C, focus_item, shape. Re-check: C (shape) confirmed: one member in the pool. The hook is the move-damage call of the spread loop (turn.c:2296-2313), per target, with cause NONE.<br>Engine: dfi_deal (turn.c:982-1004) is shared by moves, recoil, helmet, burn and poison; the sash must sit at the move-damage call, not in dfi_deal. |
| State, public, request | None (item_consumed exists); Unburden fires through dfi_use_item (turn.c:1177-1193). |
| Interactions | Multi-target hits: each target decides for itself and the lines come in target order (`-enditem` between the `-damage` lines of two targets); the hit that left a holder at 1 HP still counts as a hit for the secondaries and for Dire Claw's pick draw.<br>Recoil and drain follow the damage actually dealt (hp - 1): Head Smash into a sash holder recoils from that amount (turn.c:2306).<br>Life Orb: the attacker's item damage is not a Move effect and is not stopped; the target's survival does not cancel it.<br>Rocky Helmet: one item per Pokemon, so a sash holder has no helmet; a helmet holder next to it is unaffected, and the sash never saves an attacker from helmet damage (an item effect).<br>Sitrus Berry: not on the same Pokemon; after the sash the holder sits at 1 HP, so an ally's Update phase is unchanged, Emergency Exit fires for a Golisopod holder (turn.c:2472-2476 with hp_before = max) and Unburden starts for Sneasler through dfi_use_item. |
| Evidence | Spec g04_focus_sash: a lethal hit at full HP (`-enditem`, 1 HP), the next hit kills, a hit that is not lethal keeps the sash, a hit after any damage keeps no sash use<br>Spec g04_focus_sash_spread: Hyper Voice into two sash holders, one at full HP and one not; Golisopod with a sash and Emergency Exit; Sneasler with Unburden<br>Test: Negative controls: sash for recoil damage; sash for a hit that is not lethal; sash below full HP. |
| Step | G4 (item G4a), effort S (2 points) |

#### Expert Belt

| Aspect | Entry |
|---|---|
| Used by | MC264, MC392 (2 of 17; 5 of 227 pastes) |
| Pinned | items.ts:1901-1914: onModifyDamage (the attacker's item): `target.getMoveHitData(move).typeMod > 0` gives chainModify([4915, 4096]). The typeMod is the Champions modifyDamage's own (champions/scripts.ts:266-268), set before the ModifyDamage event. No override. |
| Draws | None of its own; a speed tie between two ModifyDamage holders (the attacker's belt, the target's berry) shuffles with SPEED_TIE `event:ModifyDamage`. |
| Protocol lines | None.<br>**Unknown to the converter:** The tie rule: trace_to_c.py:293-304 drops ModifyDamage ties only for screens and for {Life Orb, Chople Berry}; {Expert Belt, resist berry} needs the same commutation argument (4915, 2048 and 2732 chain to 1639 in each of the six orders, computed by tg_check_cites.js) or the converter stops. |
| DuoForge today | Tables: no. Generator: items carry only the Mega mapping.<br>Class: D, size M. Re-check: S: it joins the ModifyDamage chain next to Life Orb. Not a family of 0015; it rides with P2 because P2 rewrites the same chain and the same static asserts.<br>Engine: The chain is turn.c:941-976; its static asserts (turn.c:765-769) cover Life Orb, Chople and a screen only; the type-chart test is `mod > DFI_BIAS6` (turn.c:925). |
| State, public, request | None. |
| Interactions | The type chart: the belt reads the net effectiveness of both defending types (a x2 and a x1/2 type give no boost), as `-supereffective` does; immunity stops the move before the damage.<br>Chain partners: the target's resist berry (Colbur, Occa, Chople), a screen, and no Life Orb (one item); three modifiers at most: 4915, 2048, 2732 chain to 1639 in any order (the assert to add).<br>Speed order of the handlers only matters for the draw; the value does not. |
| Evidence | Spec p02_/g06_expert_belt: a super-effective hit with and without the belt, into a resisted hit, into Colbur Berry and Reflect in one chain<br>Test: The extended `_Static_assert` for the new factor. |
| Step | G6 (item G6b), effort S (2 points) |

#### Colbur Berry

| Aspect | Entry |
|---|---|
| Used by | MC246, MC56 (2 of 17; 17 of 227 pastes) |
| Pinned | items.ts:1133-1156: onSourceModifyDamage (the target's item): a Dark move with typeMod > 0, not into a Substitute, `target.eatItem()` and chainModify(0.5) with `-enditem\|X\|Colbur Berry\|[weaken]` after eatItem's own `-enditem\|..\|[eat]` (sim/pokemon.ts:1768-1809). Same shape as Occa Berry (:4347-4370) and Chople Berry (built, items.ts:1030-1053). No override. |
| Draws | None; the ModifyDamage tie with the attacker's Life Orb or Expert Belt is dropped by the commutation rule. |
| Protocol lines | `-enditem\|X\|Colbur Berry\|[eat]` then `-enditem\|X\|Colbur Berry\|[weaken]` (known: Chople, ITEM_END detail 1). |
| DuoForge today | Tables: no. Generator: items carry only the Mega mapping.<br>Class: C, resist_berry, param. Re-check: C confirmed: decision 0015 P2 turns the hard-coded Chople check (turn.c:958-965) and the berry list of dfi_use_item (turn.c:1185) into table rules for all 18 berries.<br>Engine: turn.c:958-965 is `move_type == DFI_TYPE_FIGHTING && mod > DFI_BIAS6 && dfi_holds(d, DFI_ITEM_CHOPLEBERRY)`. |
| State, public, request | None (item_consumed exists). |
| Interactions | Dark moves: Kowtow Cleave and Sucker Punch (Kingambit), Throat Chop (Incineroar), Snarl (spread: eaten at the first super-effective target). The holders of the 17 teams, Ceruledge (Fire/Ghost, MC246) and Farigiraf (Normal/Psychic, MC56), are weak to Dark.<br>No Substitute in the tables, so the hitSub test never applies; Unburden through dfi_use_item. |
| Evidence | Spec p02_colbur_*: the P2 builder's recorded battles; g06_resist_berry_dark adds Throat Chop and a spread Snarl |
| Step | G6 (item G6a), effort S (2 points) |

#### Occa Berry

| Aspect | Entry |
|---|---|
| Used by | MC36 (1 of 17; 14 of 227 pastes) |
| Pinned | items.ts:4347-4370: as Colbur Berry for Fire moves (`move.type === 'Fire'`, :4356). No override. |
| Draws | None. |
| Protocol lines | `-enditem\|X\|Occa Berry\|[eat]`, `-enditem\|X\|Occa Berry\|[weaken]`. |
| DuoForge today | Tables: no. Generator: items carry only the Mega mapping.<br>Class: C, resist_berry, param. Re-check: C confirmed (P2).<br>Engine: As Colbur Berry. |
| State, public, request | None. |
| Interactions | Fire moves: Flare Blitz, Heat Wave (spread: eaten at the first super-effective target); the holder of the 17 teams is Rillaboom (Grass, MC36); a Flash Fire holder takes no damage, so a berry next to it stays.<br>Rain halves Fire damage before the berry (WeatherModifyDamage) and the berry still needs typeMod > 0. |
| Evidence | Spec p02_occa_*: the P2 builder's recorded battles; g06_resist_berry_fire adds Heat Wave against two berry holders and a Flash Fire holder |
| Step | G6 (item G6a), effort S (2 points) |

#### Black Glasses

| Aspect | Entry |
|---|---|
| Used by | MC56, MC215 (2 of 17; 9 of 227 pastes) |
| Pinned | items.ts:523-537: onBasePower at priority 15: a Dark move gets chainModify([4915, 4096]). No override. |
| Draws | None. |
| Protocol lines | None. |
| DuoForge today | Tables: no. Generator: items carry only the Mega mapping.<br>Class: C, type_boost_item, param. Re-check: C confirmed (P2: 18 type boosters).<br>Engine: turn.c:847-850 hard-codes Mystic Water and Miracle Seed in the BasePower chain. |
| State, public, request | None. |
| Interactions | Dark moves of Kingambit (Kowtow Cleave, Sucker Punch; Defiant), Incineroar (Throat Chop), Grimmsnarl's Spirit Break; after Aerilate/Tough Claws (23, 21) and before Helping Hand (10) and the terrains (6): the chained rounding.<br>A move that Aerilate turned into Flying gets the Flying item, not the Normal one. |
| Evidence | Spec p02_type_booster_*: the P2 builder's recorded battles; g06_black_glasses adds Sucker Punch under Helping Hand |
| Step | G6 (item G6a), effort S (2 points) |

#### Floettite

| Aspect | Entry |
|---|---|
| Used by | none of the 17 (58 of 227 pastes); next ring |
| Pinned | items.ts:2189-2201: `megaStone {Floette-Eternal: Floette-Mega}`, itemUser Floette-Eternal, onTakeItem keeps the stone on its holder; champions/items.ts:342-345 clears isNonstandard. No handler that fires in the data. |
| Draws | None. |
| Protocol lines | `-mega\|X\|Floette\|Floettite` (known: trace_to_c.py:754-755). |
| DuoForge today | Tables: no. Generator: a stone row from the SETS entry (gen_closure.py:432-441).<br>Class: A, mega_stone, param. Re-check: A confirmed. The setup gate also needs the Mega forme's ability marked.<br>Engine: closure_member.c:131-135 (own stone), :145-150 (gate), :266-283 (evolve). |
| State, public, request | None. |
| Interactions | Needs Fairy Aura (the ability gate), Flower Veil only for the base forme's ability. |
| Evidence | Spec g12_floette_mega (above)<br>Test: Setup gate test per member. |
| Step | G12 (item G12b), effort XS (1 point) |

### 4.4 Moves

#### Bulk Up

| Aspect | Entry |
|---|---|
| Used by | MC246 (1 of 17; 4 of 227 pastes) |
| Pinned | moves.ts:1954-1971: Fighting status, PP 20, target self, `boosts {atk: 1, def: 1}`, flags snatch/metronome. No override. |
| Draws | None (accuracy true). |
| Protocol lines | `-boost\|X\|atk\|1` and `-boost\|X\|def\|1` (known). |
| DuoForge today | Tables: no. Generator: encoded today (PRIMARY_SELF boosts).<br>Class: A. Re-check: A confirmed (Coil, Swords Dance and Nasty Plot take the path).<br>Engine: turn.c:2065-2073. |
| State, public, request | None. |
| Interactions | Contrary reverses both boosts (turn.c:524); a primary self change at the +6 cap still prints a line with amount 0 (turn.c:573-576); Defiant and Competitive react to a foe's drop only, never to a self change. |
| Evidence | Spec g02_data_moves_a (Bulk Up from +5 and at the +6 cap) |
| Step | G2, effort XS (1 point) |

#### Dazzling Gleam

| Aspect | Entry |
|---|---|
| Used by | none of the 17 (62 of 227 pastes); next ring |
| Pinned | moves.ts:3378-3390: Fairy 80 BP special, acc 100, PP 10, target allAdjacentFoes. No override. |
| Draws | Per target ACCURACY, CRIT, DAMAGE_ROLL. |
| Protocol lines | `[spread]` move line, damage lines (probe `fairyaura`). |
| DuoForge today | Tables: no. Generator: encoded today (spread, target class 7).<br>Class: A. Re-check: A confirmed.<br>Engine: turn.c:2284-2292. |
| State, public, request | None. |
| Interactions | Fairy Aura x5448/4096 (G12) for any Fairy move on the field, the foes' included; Wide Guard stops it (G7); Dark types resist; Steel and Poison types take x2. |
| Evidence | Spec g02_data_moves_d (Dazzling Gleam into two foes, one Steel) |
| Step | G2, effort XS (1 point) |

#### Double-Edge

| Aspect | Entry |
|---|---|
| Used by | MC167, MC36 (2 of 17; 40 of 227 pastes) |
| Pinned | moves.ts:3879-3892: Normal 120 BP, acc 100, PP 15, contact, `recoil: [33, 100]`. No override. Recoil is applied once after the hit loop from the damage actually dealt (champions/scripts.ts:552-554, sim/battle-actions.ts:1379-1399). |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL only. |
| Protocol lines | `-damage\|user\|..\|[from] Recoil` (known: trace_to_c.py:558). |
| DuoForge today | Tables: no. Generator: encoded today (recoil 33/100, flags 3).<br>Class: A. Re-check: A confirmed (Flare Blitz, Wave Crash and Wood Hammer use the same recoil path).<br>Engine: Recoil turn.c:2449-2465 (round half up, at least 1, with the user's Emergency Exit check). |
| State, public, request | None. |
| Interactions | Rock Head (G4) removes the recoil; a Focus Sash target reduces the damage dealt and so the recoil; Life Orb and Rocky Helmet order with recoil is the c05 case; Normal into Ghost: no damage, no recoil.<br>Aerilate/Pixilate turn it into Flying/Fairy later (P3); under Salamence-Mega Aerilate is already built. |
| Evidence | Spec g02_data_moves_b (recoil next to Life Orb; KO of the target; Emergency Exit through recoil) |
| Step | G2, effort XS (1 point) |

#### Drum Beating

| Aspect | Entry |
|---|---|
| Used by | MC392 (1 of 17; 4 of 227 pastes) |
| Pinned | moves.ts:4294-4311: Grass 80 BP, acc 100, PP 10, `secondary {chance: 100, boosts: {spe: -1}}`. No override (no `metronome` flag). |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL, SECONDARY random(100) (chance 100 still draws). |
| Protocol lines | `-unboost\|X\|spe\|1`. |
| DuoForge today | Tables: no. Generator: encoded today (secondary boost 100%).<br>Class: A. Re-check: A confirmed.<br>Engine: turn.c:2349-2363. |
| State, public, request | None. |
| Interactions | The Speed drop changes the queue before the next move action (queue re-sorted, turn.c:3740-3745); Grassy Terrain and Miracle Seed boost it; Defiant reacts to the drop. |
| Evidence | Spec g02_data_moves_c (Drum Beating changing the order of the next move) |
| Step | G2, effort XS (1 point) |

#### Encore

| Aspect | Entry |
|---|---|
| Used by | MC373, MC264, MC215 (3 of 17; 15 of 227 pastes) |
| Pinned | moves.ts:4724-4783: Normal status, acc 100, PP 5, flags protect/reflectable/mirror/bypasssub/metronome/failencore; `volatileStatus: encore`. Condition: duration 3; onStart takes `target.lastMove`, fails without one, for a `failencore` move or for 0 PP, stores it, `-start\|X\|Encore`, +1 duration when the target has no queued move (:4737-4753); onOverrideAction, onResidualOrder 16 with an onResidual that ends it at 0 PP, onEnd `-end`, onDisableMove disables every other slot (:4754-4777).<br>champions/moves.ts:309-345 replaces onStart: when the target still has a queued action for another move and no Mental Herb, the queue's action is replaced by the encored move (`queue.changeAction`, then its priority is recomputed). That is the main path of Encore: the target never gets to use the move it chose.<br>The replacement goes through sim/battle-queue.ts:301-305 changeAction, then insertChoice (:369-403) and resolveAction (:166-277); runMove's OverrideAction (sim/battle-actions.ts:227-235) stays dormant because the action already holds the encored move. |
| Draws | The replaced action has no target, so resolveAction calls getRandomTarget (sim/battle-queue.ts:268-272): one RANDOM_TARGET random(2) for a foe-targeting move, none for a self move. ps_trace.js:90-91 checks `insertChoice` before `getRandomTarget`, so the harness records this draw as INSERT_TIE/queue (probe `encore`, step 2: one INSERT_TIE[0,2) and no RANDOM_TARGET). The converter would refuse it (`insert-tie`, trace_to_c.py:313-320), and its drop rule for RANDOM_TARGET `resolve` (:321-322) would drop it if the harness labelled it correctly although it decides the target.<br>insertChoice itself draws random(first, last+1) only when the new action ties an existing one in order, priority and speed (INSERT_TIE).<br>Residual: Encore is a callback handler at order 16, so two Encore holders at one Speed draw SPEED_TIE; the converter keeps all-callback `field:Residual` ties (trace_to_c.py:284-285). |
| Protocol lines | `-start\|p2a: Incineroar\|Encore`; the replaced action prints its own move line; `-end\|p2a: Incineroar\|Encore` in the residual after the heals of order 5 (probe `encore`, steps 2 and 4); `-fail\|source` when it fails.<br>**Unknown to the converter:** `-start\|..\|Encore` and `-end\|..\|Encore`: trace_to_c.py:725-733 (ConversionError `start-end-line`).<br>**Unknown to the converter:** The harness label above (ps_trace.js:90-91) and the converter's `resolve` rule (trace_to_c.py:321-322). |
| DuoForge today | Tables: no. Generator: rejected: "unknown primary volatile" (volatileStatus encore; the callbacks are nested in `condition`).<br>Class: D, size L. Re-check: D/L confirmed. Needs: lastMove per position, an Encore volatile (slot + turns), the request lock, queue replacement with its draws, a residual callback at order 16, two public lines.<br>Engine: No lastMove is stored anywhere. The request builder disables moves at request.c:106-175 (PP, choice lock, Fake Out at :141-146); the queue is dfi_queue_record (battle_internal.h:144-152). |
| State, public, request | Per position (POOL tail, G3): last_move (slot + 1) and encore (slot + turns); both cleared on switch-out and faint like the rest of the block.<br>Request: every slot but the encored one is disabled (request.c:133-157); with Fake Out disabled by the Champions rule nothing is left and the slot gets Struggle (c07 path; probe step 3: `enabled [[2],..]`).<br>Public: Encore is shown (`-start`), so one view bit (reserved byte bit 8) and two events (a generic volatile start/end kind with a detail). |
| Interactions | Fake Out: after turn 1 the Champions rule disables it, Encore disables the rest, so the slot Struggles for the remaining turns (probe: Struggle with recoil, `-end Encore` after the third turn).<br>Choice Scarf: the lock already sits on the last move; Encore onto Protect: the stall counter decides (STALL draws as usual).<br>Electro Shot charge (Archaludon): the locked move wins over the Encore request.<br>Encore needs a last move: it fails on a Pokemon that has not moved since entering, on Struggle and on Encore (failencore flag).<br>The duration is 3, or 4 when the target has no queued move (already moved); it ends in the residual at order 16, after Leftovers and Grassy Terrain (5), poison (9), burn (10). |
| Evidence | Spec g09_encore_replace: Encore on a slower target that chose another move (queue replacement, random target, its draw)<br>Spec g09_encore_fake_out: Fake Out on turn 1, Encore on turn 2, Struggle on turns 3 and 4, `-end`<br>Spec g09_encore_paths: fails without a last move, on Struggle and Encore, duration 4 after the target moved, 0 PP ends it, Encore on Protect, on a charging Electro Shot<br>Test: Converter: the label and the keep rule (a control without it is red); `-start`/`-end` mapping; tie draws at the Encore residual. |
| Step | G9 (item G9), effort L (8 points) |

#### Extreme Speed

| Aspect | Entry |
|---|---|
| Used by | MC172, MC385 (2 of 17; 32 of 227 pastes) |
| Pinned | moves.ts:5019-5031: Normal 80 BP, acc 100, PP 5, priority +2, contact. No override. |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL. |
| Protocol lines | Plain move and damage lines. |
| DuoForge today | Tables: no. Generator: encoded today (priority 10 = 2 + 8).<br>Class: A. Re-check: A confirmed (priority is data; Fake Out +3 and Sucker Punch +1 exist).<br>Engine: dfi_move_priority turn.c:266-276; the queue key turn.c:282-322. |
| State, public, request | None. |
| Interactions | Priority above 0 is stopped by Psychic Terrain at grounded foes (turn.c:2133-2157) and by Armor Tail (turn.c:1998-2016); Sucker Punch and Fake Out order against it (+3, +2, +1); Ghost types are immune (Normal); Aerilate turns it Flying. |
| Evidence | Spec g02_data_moves_b (Extreme Speed against Psychic Terrain and Armor Tail, and ahead of a faster Pokemon) |
| Step | G2, effort XS (1 point) |

#### First Impression

| Aspect | Entry |
|---|---|
| Used by | MC177, MC22 (2 of 17; 9 of 227 pastes) |
| Pinned | moves.ts:5473-5491: Bug 90 BP, acc 100, PP 10, priority +2, contact; onTry fails when `source.activeMoveActions > 1`.<br>champions/moves.ts:386-394: Base power 100 and onDisableMove that disables it once `pokemon.activeMoveActions` is non-zero, evaluated at the end of each turn (sim/battle.ts:1691-1698). The same rule as Fake Out (champions/moves.ts:354-361). |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL only. |
| Protocol lines | `-fail\|user` with `[still]` when onTry stops it (known); otherwise plain lines (probe `firstimpression`: the next request has it disabled). |
| DuoForge today | Tables: no. Generator: rejected: "callback onTry is not mapped to a handler".<br>Class: C, first_turn_only, param. Re-check: C confirmed. Fake Out and First Impression share the family; the engine hard-codes Fake Out in two places.<br>Engine: request.c:143-146 compares `mv->move_id == DFI_MOVE_FAKEOUT` and turn.c:2082 `md->special == DFI_SPECIAL_FAKE_OUT && pos->move_actions > 1u`; both must read the family parameter. Base power is 100, not 90: the generator merges the Champions row. |
| State, public, request | None (move_actions exists). |
| Interactions | Moves ahead of Protect-priority (+4) and below Fake Out (+3); Psychic Terrain and Armor Tail stop it (priority); Fake Out + First Impression on one side is legal (two users).<br>Emergency Exit Golisopod takes the hit and leaves: the same Pokemon uses First Impression only once per entry. |
| Evidence | Spec g10_first_impression: turn 1 use, disabled next turn, back after a switch-out and return, blocked by Psychic Terrain<br>Test: Negative control: Fake Out only in the request rule. |
| Step | G10 (item G10a), effort S (2 points) |

#### Flash Cannon

| Aspect | Entry |
|---|---|
| Used by | MC97, MC196 (2 of 17; 29 of 227 pastes) |
| Pinned | moves.ts:5678-5696: Steel 80 BP special, acc 100, PP 10, `secondary {chance: 10, boosts: {spd: -1}}`. No override. |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL, SECONDARY random(100) per hit target. |
| Protocol lines | `-unboost\|X\|spd\|1` (known). |
| DuoForge today | Tables: no. Generator: encoded today (secondary boost, SECONDARY_TARGET).<br>Class: A. Re-check: A confirmed (Snarl and Spirit Break use the secondary boost path).<br>Engine: turn.c:2362-2363. |
| State, public, request | None. |
| Interactions | Defiant and Competitive react to a foe's drop (turn.c:559-572); a secondary drop of an ability holder shows no `-ability` line; Steel into Fairy, Ice and Rock: super effective. |
| Evidence | Spec g02_data_moves_a (Flash Cannon into a Defiant Kingambit: Defiant after the secondary) |
| Step | G2, effort XS (1 point) |

#### Head Smash

| Aspect | Entry |
|---|---|
| Used by | MC172, MC385 (2 of 17; 30 of 227 pastes) |
| Pinned | moves.ts:8226-8239: Rock 150 BP, acc 80, PP 5, contact, `recoil: [1, 2]`. No override. |
| Draws | ACCURACY (80), CRIT, DAMAGE_ROLL. |
| Protocol lines | `-damage\|user\|..\|[from] Recoil`, none under Rock Head (probe `rockhead`). |
| DuoForge today | Tables: no. Generator: encoded today (recoil 1/2, accuracy 80).<br>Class: A. Re-check: A confirmed; the recoil formula is general (`total * a / b`, turn.c:2455).<br>Engine: turn.c:2449-2465. |
| State, public, request | None. |
| Interactions | Rock Head (G4): recoil removed, nothing printed; with a Focus Sash target the recoil follows the damage actually dealt; Emergency Exit of the user after the recoil (turn.c:2464). |
| Evidence | Spec g02_data_moves_b (recoil to the user, half of a dealt amount that rounds up) |
| Step | G2, effort XS (1 point) |

#### Ice Punch

| Aspect | Entry |
|---|---|
| Used by | MC196 (1 of 17; 12 of 227 pastes) |
| Pinned | moves.ts:9387-9403: Ice 75 BP, acc 100, PP 15, flags contact/protect/mirror/punch/metronome, `secondary {chance: 10, status: frz}`. No override. |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL, SECONDARY random(100); freeze duration is fixed 3 in the Champions rule (no draw), thaw 1/4 per turn (FREEZE_THAW, existing). |
| Protocol lines | `-status\|X\|frz` (known). |
| DuoForge today | Tables: no. Generator: rejected: "unknown flag punch".<br>Class: B (flag punch: "the flags byte is full"). Re-check: Re-classed A with a guard. The only reader of `punch` is Iron Fist, which is not in the tables; the generator may add `punch` to IGNORED_FLAGS the way it ignores `slicing` and `bite`, if it also fails when Iron Fist enters the tables. No bit is needed now.<br>Engine: turn.c:1051 (Ice and Sun block freezing); freeze counter turn.c:1066-1068. |
| State, public, request | None. |
| Interactions | Sun and Ice types prevent the freeze; Flare Blitz/Scald thaw; a frozen target loses its turn 1/4 of the time. |
| Evidence | Spec g02_data_moves_c (Ice Punch freezing a target, the thaw draws)<br>Test: Generator test: Iron Fist in the tables while `punch` is ignored fails. |
| Step | G2, effort XS (1 point) |

#### Liquidation

| Aspect | Entry |
|---|---|
| Used by | MC36, MC56 (2 of 17; 15 of 227 pastes) |
| Pinned | moves.ts:10375-10393: Water 85 BP, acc 100, PP 10, contact, `secondary {chance: 20, boosts: {def: -1}}`. No override. |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL, SECONDARY random(100). |
| Protocol lines | `-unboost\|X\|def\|1`. |
| DuoForge today | Tables: no. Generator: encoded today (secondary boost, flags 3).<br>Class: A. Re-check: A confirmed.<br>Engine: turn.c:2362-2363; contact for Rocky Helmet turn.c:2399. |
| State, public, request | None. |
| Interactions | Rain boosts it; Mystic Water (a type booster, P2) stacks in the BasePower chain; Water into Grass and Electric types. |
| Evidence | Spec g02_data_moves_c (Liquidation in rain into a Rocky Helmet holder) |
| Step | G2, effort XS (1 point) |

#### Low Kick

| Aspect | Entry |
|---|---|
| Used by | none of the 17 (64 of 227 pastes); next ring |
| Pinned | moves.ts:10442-10481: Fighting contact, PP 20, basePowerCallback by target weight (>= 2000: 120, 1000: 100, 500: 80, 250: 60, 100: 40, else 20; :10446-10464) and an onTryHit that only fails against Dynamax (:10470-10476). The table is Grass Knot's. |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL only. |
| Protocol lines | Plain lines. |
| DuoForge today | Tables: no. Generator: rejected: "callback basePowerCallback is not mapped to a handler".<br>Class: C, bp_by_target_weight, param. Re-check: C confirmed: the same thresholds as Grass Knot, so one special for both.<br>Engine: turn.c:827-829 holds the weight table inline for DFI_SPECIAL_GRASS_KNOT and reads `weight_hg` of the current forme (a Mega weighs differently). |
| State, public, request | None. |
| Interactions | Weights: Gholdengo 30 kg (60), Rillaboom 90 kg (80), Kingambit 120 kg (100); a Mega Evolution changes the weight; Ghost types are immune (Fighting); Defiant reacts only to stat drops, not to damage. |
| Evidence | Spec g10_low_kick_weights: against five weights, a Mega target<br>Test: Generator test: the two handler bodies equal up to constants. |
| Step | G10 (item G10d), effort S (2 points) |

#### Psychic Noise

| Aspect | Entry |
|---|---|
| Used by | MC264 (1 of 17; 2 of 227 pastes) |
| Pinned | moves.ts:14079-14094: Psychic 75 BP special, acc 100, PP 10, flags protect/mirror/sound/bypasssub/metronome, `secondary {chance: 100, volatileStatus: healblock}`.<br>The Heal Block condition lives on the (Past) move healblock, moves.ts:8273-8347: durationCallback returns 2 for Psychic Noise (:8286-8289); onStart `-start\|X\|move: Heal Block` (:8296); onDisableMove disables every slot with the `heal` flag (:8300-8306); onBeforeMovePriority 6 with `cant\|X\|move: Heal Block\|<move>` (:8307-8313); onResidualOrder 20 and onEnd `-end` (:8320-8323); onTryHeal returns false for all healing (:8324-8333); onRestart does nothing for Psychic Noise, so a second hit neither refreshes nor prints (:8334). |
| Draws | SECONDARY random(100) per hit target (chance 100 still draws). Nothing else. |
| Protocol lines | `-start\|p2a: Milotic\|move: Heal Block`, `-end\|p2a: Milotic\|move: Heal Block` after two residuals, `cant\|p2a: Milotic\|move: Heal Block\|Recover` for a queued heal move (probes `healblock`, `healblockcant`).<br>**Unknown to the converter:** `-start`/`-end` with `move: Heal Block` (ConversionError `start-end-line`); the `cant` reason (bare KeyError, trace_to_c.py:667-676). |
| DuoForge today | Tables: no. Generator: rejected: KeyError 'healblock' (the secondary matches the volatile pattern, but the VOLATILE table has only flinch and confusion).<br>Class: B (secondary volatile healblock). Re-check: Under-sized: Heal Block is a mechanic of its own (TryHeal hook, flag-disabled moves, BeforeMove stop, duration 2 at order 20, public flag). M, sharing machinery with Throat Chop; `heal` is a new flag.<br>Engine: dfi_add_volatile knows flinch and confusion only (turn.c:1085-1110). Heals go through dfi_heal (turn.c:1330-1340) except Grassy Terrain's residual heal, which is inline (turn.c:3125-3135) and needs the same check. |
| State, public, request | Two bits of Heal Block turns per position (POOL tail, G3); view bit 16 (public).<br>`heal` flag in the new flags column: also for the table's drain moves, Bitter Blade (12) and Leech Life (21), which Heal Block disables too (the Showdown `heal` flag is on drain moves: 23 pool moves).<br>Residual: a duration-only entry at order 20 with the end line; request.c skips `heal`-flag moves. |
| Interactions | Blocked heals: Leftovers, Sitrus Berry (the berry is still eaten), Grassy Terrain, drain (Leech Life, Bitter Blade, Draining Kiss), Recover; the probe shows Milotic's Leftovers and Grassy heals missing on both turns and back on the third.<br>Bitter Blade and Leech Life are disabled in the request, not only blocked: Ceruledge and Golisopod lose a move slot for a turn.<br>Heal Block ends at order 20, after Leftovers (5): its last turn still blocks that residual heal.<br>Sound flag: Psychic Noise is itself a sound move (Throat Chop disables it). |
| Evidence | Spec g08_heal_block: lands, Recover/Leech Life disabled, Leftovers and Grassy blocked, `cant` for a queued Recover, `-end` after two residuals, a second Noise does not refresh<br>Spec g08_heal_block_berry: Sitrus Berry eaten without a heal<br>Test: Negative controls: Grassy Terrain heal unchecked (the inline path); duration 3; drain not blocked. |
| Step | G8 (item G8b), effort M (4 points) |

#### Recover

| Aspect | Entry |
|---|---|
| Used by | MC215 (1 of 17; 13 of 227 pastes) |
| Pinned | moves.ts:14806-14820: Normal status, PP 5, target self, flags snatch/heal/metronome, `heal: [1, 2]`. runMoveEffects (sim/battle-actions.ts:1201-1222): full HP gives `-fail\|user\|heal` with `[still]`; otherwise heal(round(baseMaxhp / 2)). |
| Draws | None. |
| Protocol lines | `-heal\|p1a: Milotic\|202/202` (no `[from]`), and `-fail\|p1a: Milotic\|heal` at full HP (probe `recover`).<br>**Unknown to the converter:** `-fail\|X\|heal`: trace_to_c.py:686-687 reads the second argument as an ailment and raises a bare KeyError for `heal`. |
| DuoForge today | Tables: no. Generator: rejected: "unknown field heal".<br>Class: B (heal fraction). Re-check: B confirmed (five heal moves in the classification: Recover, Roost, Moonlight...). Needs a heal fraction column and the `heal` flag (also read by Heal Block).<br>Engine: A status move that is not a self-boost is E_UNSUPPORTED (turn.c:2065-2067); dfi_heal (turn.c:1330-1340) exists for items and drain. |
| State, public, request | None. |
| Interactions | Heal Block disables it in the request and stops a queued one with `cant` (G8); Sitrus Berry and Leftovers order against it; rounding: Math.round on baseMaxhp / 2. |
| Evidence | Spec g10_recover: at full HP (`-fail`), at half HP, after Heal Block lands (with G8) |
| Step | G10 (item G10c), effort S (2 points) |

#### Rock Slide

| Aspect | Entry |
|---|---|
| Used by | MC373 (1 of 17; 77 of 227 pastes) |
| Pinned | moves.ts:15239-15255: Rock 75 BP, acc 90, PP 10, target allAdjacentFoes, `secondary {chance: 30, volatileStatus: flinch}` (:15248-15251). No override. |
| Draws | Per target: ACCURACY (90), CRIT, DAMAGE_ROLL; per hit target SECONDARY random(100) (sim/battle-actions.ts:1336-1352). All existing sites; spread moves are already recorded (Hyper Voice, Heat Wave). |
| Protocol lines | `\|move\|..\|Rock Slide\|..\|[spread] p2a,p2b`, `-damage`, `-supereffective`/`-resisted`, `cant\|X\|flinch`. |
| DuoForge today | Tables: no. Generator: encoded today (flags 2, target class 7, secondary flinch 30).<br>Class: A. Re-check: A confirmed: every field is encoded and turn.c runs spread moves with a flinch secondary (Heat Wave and Fake Out paths).<br>Engine: turn.c:2347-2391 (one SECONDARY draw per hit target), spread damage turn.c:2284-2292. |
| State, public, request | None. |
| Interactions | Wide Guard blocks it per target (G7); Protect per target; the flinch only stops a target that has not moved; Sash on one target (G4); the 0.75 spread factor applies whenever two targets are chosen, also when one of them protects or is missed afterwards (`spreadHit` is set before the hit steps, sim/battle-actions.ts:551; the engine reads `count > 1`, turn.c:2127). |
| Evidence | Spec g02_data_moves_a (one battle with Rock Slide into two foes, one of them protecting, a flinch roll that lands and one that misses) |
| Step | G2, effort XS (1 point) |

#### Scald

| Aspect | Entry |
|---|---|
| Used by | MC215 (1 of 17; 27 of 227 pastes) |
| Pinned | moves.ts:15761-15778: Water 80 BP special, acc 100, PP 15, flags protect/mirror/defrost/metronome, `thawsTarget: true` (:15770), `secondary {chance: 30, status: brn}`. No override.<br>The frozen target thaws in frz.onAfterMoveSecondary (data/conditions.ts:112-116), after the secondaries, DamagingHit, recoil and the second Update (champions/scripts.ts:574-576). A Fire move thaws earlier, in onDamagingHit (conditions.ts:117-121). |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL, SECONDARY random(100) per hit target. No new site. |
| Protocol lines | `-curestatus\|X\|frz\|[msg]` for the target (known); `-curestatus\|user\|frz\|[from] move: Scald` when a frozen user thaws (known since Flare Blitz). |
| DuoForge today | Tables: no. Generator: rejected: "unknown field thawsTarget".<br>Class: B (thawsTarget). Re-check: B confirmed. `defrost` (user thaw) is bit 128 already; thawsTarget is a second property, so one new flag or param bit.<br>Engine: turn.c:2416 thaws a frozen target for `move_type == FIRE` after DamagingHit; Scald needs the same cure at AfterMoveSecondary (after turn.c:2466 Update, before the targets' Emergency Exit :2472-2476). |
| State, public, request | One column bit (thaws_target); no state. |
| Interactions | A frozen target cannot be burned by the same Scald (it keeps frz through the secondaries, then thaws); Sun already prevents freezing; Ice Punch (G2) freezes; the burn secondary also halves a physical attacker's damage once landed. |
| Evidence | Spec g10_scald_thaw: Scald into a frozen Pokemon (seed found by a predicate: Ice Beam freeze on an earlier turn), Scald thawing a frozen Milotic user<br>Test: Negative control: thaw before the secondaries. |
| Step | G10 (item G10b), effort S (2 points) |

#### Shadow Claw

| Aspect | Entry |
|---|---|
| Used by | MC196 (1 of 17; 3 of 227 pastes) |
| Pinned | moves.ts:16059-16072: Ghost 70 BP, acc 100, PP 15, contact, critRatio 2; champions/moves.ts:871-874 adds the `slicing` flag. |
| Draws | ACCURACY, CRIT random(8) (crit ratio 2), DAMAGE_ROLL. |
| Protocol lines | `-crit` (known). |
| DuoForge today | Tables: no. Generator: encoded today (crit ratio 2; slicing ignored).<br>Class: A. Re-check: A confirmed. `slicing` is read by Sharpness only; a guard must fail if Sharpness enters the tables.<br>Engine: turn.c:777-792 (crit table 1/24, 1/8, 1/2, 1). |
| State, public, request | None. |
| Interactions | Normal and Fighting are immune on Ghost targets (Annihilape is Fighting/Ghost itself); a critical hit ignores negative attack stages. |
| Evidence | Spec g02_data_moves_c (Shadow Claw crits at ratio 2) |
| Step | G2, effort XS (1 point) |

#### Soak

| Aspect | Entry |
|---|---|
| Used by | MC167 (1 of 17; 3 of 227 pastes) |
| Pinned | moves.ts:17186-17208: Water status, acc 100, PP 20, flags protect/reflectable/mirror/allyanim/metronome; onHit: a target that is already pure Water, or whose type cannot be set, gives `-fail\|target` and null; otherwise `target.setType(Water)` and `-start\|target\|typechange\|Water`.<br>sim/pokemon.ts:2109-2129 setType keeps the type until the Pokemon leaves, faints or changes forme: setSpecies resets types (:1392), so a Mega Evolution ends it (formeChange :1427-1496). |
| Draws | ACCURACY (100) only (probe `soak`). |
| Protocol lines | `-start\|p2a: Pelipper\|typechange\|Water`; `-fail\|p2a: Pelipper` when repeated (the argument is the target, probe `soak`).<br>**Unknown to the converter:** `-start\|..\|typechange\|..`: trace_to_c.py:725-733 (`start-end-line`). The snapshot does not record types either (ps_trace.js:264-287), so only the line and later `-supereffective` lines show it. |
| DuoForge today | Tables: no. Generator: rejected: "callback onHit is not mapped to a handler" (and flag allyanim is unknown).<br>Class: C, type_set_target, param. Re-check: C confirmed (Magic Powder is the other member). `allyanim` has no reader: add to IGNORED_FLAGS. Needs a per-position type override.<br>Engine: All type reads go through three places: dfi_has_type (turn.c:104-108), dfi_type_immune (:727) and dfi_type_mod (:745); grounded, STAB, the status immunities, Prankster's Dark rule and Poison/Steel immunity use dfi_has_type. |
| State, public, request | One byte per position (POOL tail, G3): type override (type + 1, 0 none), cleared on leaving and by Mega Evolution (dfi_run_mega).<br>Public: the new type is shown (`-start`). The position view is full: bit 32 of `reserved` can mean "Water by Soak" (enough for Soak; Magic Powder would need a field), otherwise one new byte; one event kind or detail. |
| Interactions | A Flying or Levitating target becomes grounded (Psychic Terrain priority block, Grassy Terrain heal and boost); Steel loses its Poison immunity; Ghost loses Normal/Fighting immunity; Fire can be burned.<br>Adaptability and STAB read the attacker's types: Soak on an ally changes the ally's STAB (Adaptability x2 when the new type matches); the target is hit for Electric/Grass x2 (Thunderbolt, Grassy Glide) as a Water type.<br>Mega Evolution resets the type (setSpecies); a Soak on a Mega-capable foe is undone when it evolves.<br>`-fail` shows the target's position, not the user's. |
| Evidence | Spec g11_soak: Soak then Electric and Grass hits, repeated Soak (`-fail`), Soak on a Flying target under Psychic Terrain<br>Spec g11_soak_mega: Soak on a Mega-capable Pokemon, then the Mega Evolution<br>Test: Negative controls: type kept through a switch-out and through a Mega Evolution. |
| Step | G11 (item G11), effort M (4 points) |

#### Throat Chop

| Aspect | Entry |
|---|---|
| Used by | MC177, MC22, MC36 (3 of 17; 60 of 227 pastes) |
| Pinned | moves.ts:19389-19437: Dark 80 BP contact. `secondary {chance: 100, onHit: target.addVolatile(throatchop)}` (:19428-19433). Condition (:19398-19427): duration 2; onStart `-start .. [silent]`; onDisableMove disables every move slot with the `sound` flag (:19403-19409); onBeforeMove at priority 6 and onModifyMove: a sound move gives `cant\|X\|move: Throat Chop` (:19410-19422); onResidualOrder 22 with no onResidual, so a duration handler only; onEnd `-end .. [silent]`. No override. |
| Draws | SECONDARY random(100) per hit target, although the chance is 100 (probe: SECONDARY[0,100) once). Nothing else: the duration is fixed. The probe also shows runMove's target draw before BeforeMove (RANDOM_TARGET execute:allAdjacentFoes, dropped by the converter) when the victim's queued Hyper Voice is stopped. |
| Protocol lines | `-start\|X\|Throat Chop\|[silent]` and `-end\|X\|Throat Chop\|[silent]` (skipped: silent); a sound move already queued: `cant\|p2a: Salamence\|move: Throat Chop` with no move line (tg_probe_reference.js throatchop).<br>**Unknown to the converter:** The `cant` reason `move: Throat Chop`: trace_to_c.py:667-676 maps par/slp/frz/flinch/nopp/ability only, and an unknown reason raises a bare KeyError, not a ConversionError. |
| DuoForge today | Tables: no. Generator: rejected: "unknown secondary" (the secondary has an onHit callback; the condition block has no owner).<br>Class: C, move_lockout, param. Re-check: C confirmed (Taunt is the other member; Heal Block of Psychic Noise is a second flag predicate). Extension: a `sound` flag bit, a lockout volatile with a duration, a request rule.<br>Engine: No lockout exists. The `sound` flag is in IGNORED_FLAGS (gen_closure.py:89), but three table moves carry it: Snarl (26), Parting Shot (35) and Hyper Voice (40); the flags byte is full (gen_closure.py:83-84). |
| State, public, request | Two bits of lockout turns per position (POOL tail, G3); no view bit (the volatile is silent); `sound` in the new flags column for every id, the prefix included.<br>Request: request.c:133-157 skips sound moves; Struggle when nothing else is left.<br>Residual: a duration-only entry at order 22 (turn.c:3030-3039 style); `cant` with cause MOVE + id2 (existing kinds). |
| Interactions | Sound moves in the tables: Hyper Voice (Salamence), Snarl (Archaludon, Incineroar), Parting Shot (Incineroar, Grimmsnarl); Psychic Noise and Round later.<br>BeforeMove order: sleep/freeze 10, flinch 8, Throat Chop and Heal Block 6, confusion 3, paralysis 1 (turn.c:1553-1624): the engine's function must slot it between flinch and confusion.<br>A Choice Scarf holder locked into a sound move has nothing left: Struggle (c07 path). A spread sound move stopped by `cant` spends no PP.<br>Throat Chop is Dark: a Colbur Berry holder halves it; Protect blocks it and no volatile is added (probe step 2). |
| Evidence | Spec g08_throat_chop: the chop lands before a queued Hyper Voice (`cant`), the next request lacks sound moves, the volatile ends after two residuals; a Protect block; Struggle for a Scarf holder with only Hyper Voice<br>Test: Negative controls: no disable in the request; `cant` after the move line; three-turn duration; non-sound moves disabled. |
| Step | G8 (item G8a), effort M (4 points) |

#### Thunderbolt

| Aspect | Entry |
|---|---|
| Used by | MC97, MC167, MC264, MC56, MC172 (5 of 17; 21 of 227 pastes) |
| Pinned | moves.ts:19467-19483: Electric 90 BP, acc 100, PP 15, `secondary {chance: 10, status: par}`. No override. |
| Draws | ACCURACY, CRIT, DAMAGE_ROLL, SECONDARY random(100) per hit target. |
| Protocol lines | `-status\|X\|par` (known). |
| DuoForge today | Tables: no. Generator: encoded today (secondary status par 10).<br>Class: A. Re-check: A confirmed (Zap Cannon has the same status secondary).<br>Engine: turn.c:2364-2365 dfi_try_status; Electric types cannot be paralysed (turn.c:1050). |
| State, public, request | None. |
| Interactions | Lightning Rod redirects an Electric single-target move (turn.c:1935-1963) and Follow Me comes first; Electric types cannot be paralysed (turn.c:1050) and Ground types are immune to the move; a Soak'd target (Water) takes x2 (G11). |
| Evidence | Spec g02_data_moves_a (Thunderbolt into a Lightning Rod holder and into an Electric type) |
| Step | G2, effort XS (1 point) |

#### U-turn

| Aspect | Entry |
|---|---|
| Used by | MC177, MC22, MC97, MC167, MC36, MC56, MC215, MC196 (8 of 17; 80 of 227 pastes) |
| Pinned | moves.ts:20268-20281: Bug 70 BP, acc 100, PP 20, flags contact/protect/mirror/metronome, `selfSwitch: true` (:20277). No Champions override.<br>No callback of its own. The pivot is the core's: runMoveEffects sets `source.switchFlag = move.id` when the hit did something and a reserve exists (sim/battle-actions.ts:1290-1296, 1311-1313); the queue turns the string flag into the switch's `sourceEffect` (sim/battle-queue.ts:250-255); switchIn prints `[from] U-turn` (sim/battle-actions.ts:145-148). Same path as Flip Turn. |
| Draws | None of its own. Ordinary ACCURACY (acc 100 still draws), CRIT, DAMAGE_ROLL per target; the PIVOT answer sorts its switch actions (SPEED_TIE queue, existing). Converter: nothing new. |
| Protocol lines | `\|move\|..\|U-turn\|..`, damage lines, then after the PIVOT answer `\|switch\|p1a: X\|..\|[from] U-turn` (tg_probe_reference.js uturn).<br>**Unknown to the converter:** `[from] U-turn`: trace_to_c.py:570-571 knows only Parting Shot and Flip Turn, so a trace stops with ConversionError `from-attribute`. |
| DuoForge today | Tables: no (50 moves; Flip Turn is id 49). Generator: encoded today (flags 19 = contact\|protect\|selfSwitch).<br>Class: B, no family ("damaging pivot names its move"). Re-check: B for the engine (data alone is A). Family: self-switch moves (Flip Turn built, Parting Shot special, Volt Switch, Teleport). Extension: self-switch cause by move.<br>Engine: The SELF_SWITCH bit is read for Flip Turn only: turn.c:2321-2329 stores DFI_SWITCH_FLIP_TURN, and dfi_run_switch names Flip Turn for that flag (turn.c:2581, 2614). Marking U-turn without a fix would print `[from] Flip Turn` (README section 6.2). |
| State, public, request | One more switch_flag value per damaging pivot move, valid under the POOL kinds (kind limit closure_member.c:14); a generated pivot-move table maps flag to move id for the event. No layout change; no public change (CAUSE_MOVE with id2). |
| Interactions | Flip Turn: one path; both flagged on a side with one reserve is the c04 double pivot.<br>Parting Shot (flag 1, special onHit) and Emergency Exit: Champions EE does not fire when a switch flag is set (turn.c:1157-1163, champions/abilities.ts:22-29), so Golisopod with U-turn flags once.<br>Rocky Helmet: a user that faints loses the flag (sim/pokemon.ts:1585); Choice Scarf: the lock ends on leaving; Focus Sash on the target: the hit still did something, so it pivots.<br>No reserve: the flag is not set (dfi_can_switch). |
| Evidence | Spec g05_uturn: the hit, `[from] U-turn`, the replacement's entry (Intimidate)<br>Spec g05_uturn_paths: Protect (no pivot), KO of the target (pivots), no reserve, Golisopod U-turn with EE, Helmet KO (no pivot), Scarf lock then leave<br>Test: Negative controls: `[from] Flip Turn` for U-turn; flag set without a reserve; the flag valid under CLOSURE or TEAM_C. |
| Step | G5 (item G5), effort S (2 points) |

#### Wide Guard

| Aspect | Entry |
|---|---|
| Used by | MC371, MC97, MC56, MC215, MC196 (5 of 17; 23 of 227 pastes) |
| Pinned | moves.ts:20808-20851: Rock status, PP 10, priority +3, flags snatch, target allySide, `sideCondition: wideguard`. onTry (:20818) fails unless `queue.willAct()`; onHitSide adds the `stall` volatile to the user (:20821-20823), so Wide Guard never rolls for success but raises the counter that Protect rolls against; the side condition (:20824-20846) has duration 1, onSideStart `-singleturn\|user\|Wide Guard`, and onTryHit at priority 4 that stops `allAdjacent` and `allAdjacentFoes` moves with `-activate\|target\|move: Wide Guard` and NOT_FAIL.<br>The TryHit event runs for the whole target array, so a spread move prints one `-activate` per target on the guarded side, and Wide Guard (4) comes before Protect (3) (sim/battle-actions.ts:643-653, sim/battle.ts:1035-1048). |
| Draws | None of its own: the stall counter is only raised. A later Protect rolls STALL random(3) after one Wide Guard (probe `wideguard`, turn 2: STALL/StallMove[0,3)). Spread targets are the converter's `execute:allAdjacentFoes` (dropped). |
| Protocol lines | `-singleturn\|p1a: Pelipper\|Wide Guard`; per target `-activate\|p1b: Milotic\|move: Wide Guard`; the spread line keeps an empty slot list: `\|move\|p2a: Salamence\|Hyper Voice\|p1b: Milotic\|[spread] ` (probe `wideguard`).<br>**Unknown to the converter:** `-singleturn\|..\|Wide Guard` (trace_to_c.py:696-697 ConversionError `singleturn-line`); `-activate\|..\|move: Wide Guard` falls into the generic `move:` branch and becomes an ACTIVATE event, not a BLOCKED one (trace_to_c.py:709-710), which then differs from the engine's Protect-style event. |
| DuoForge today | Tables: no. Generator: rejected: "callback onTry is not mapped to a handler" (and sideCondition wideguard has no entry in SIDE_CONDITION).<br>Class: C, side_guards, param. Re-check: C confirmed (Quick Guard is the other member). Needs a side condition with a one-turn duration, a spread predicate in the hit steps and the stall increment.<br>Engine: Side conditions are Tailwind, Reflect and Light Screen only (turn.c:2030-2052, `E_UNSUPPORTED` above Light Screen at :2037). The hit steps check Psychic Terrain and Protect per target at turn.c:2144-2157; the stall counter is stall_level/stall_turns (turn.c:1643-1673). |
| State, public, request | One side flag for the turn (POOL tail, G3: not a counter, ends in the residual, no line); stall_level + 1 (cap 6) and stall_turns 2 on the user.<br>Public: BLOCKED with a detail for Wide Guard (like Psychic Terrain, duoforge.h:508-511) and SINGLE_TURN with id Wide Guard; a side-view bit. |
| Interactions | Spread moves: Hyper Voice, Heat Wave, Muddy Water, Snarl, Rock Slide, Make It Rain, Dazzling Gleam (all allAdjacentFoes). No spread move in the pool has priority above 0 (checked over the legal pool), so Psychic Terrain (also priority 4) never ties with it.<br>Wide Guard before Protect: a guarded Pokemon that also protects gets Wide Guard's line only (probe).<br>Protect after Wide Guard: STALL random(3), and the other way round the first Protect starts the counter that Wide Guard raises.<br>No spread move may use `allAdjacent` yet (Earthquake family not in the tables); when it comes, its ally hit is also stopped. |
| Evidence | Spec g07_wide_guard: Hyper Voice and Snarl into a guarded side with one Protect on it (both lines per target), then Muddy Water; the empty `[spread]` list<br>Spec g07_wide_guard_stall: Wide Guard then Protect (STALL draw), Protect then Wide Guard, Wide Guard with nobody left to act (`-fail`)<br>Test: Negative controls: Protect before Wide Guard; one line instead of one per target; a single-target move stopped. |
| Step | G7 (item G7), effort M (4 points) |


## 5. Step plan

### 5.1 Steps

P1 (decision 0015, in progress) comes first. Effort points: XS 1, S 2, M 4, L 8. "Teams completed" are those whose last missing step this is in the schedule of section 5.3. "Parallel-safe with" lists steps with no hard conflict (section 5.2) and no dependency between them.

| Step | Mechanics | Gaps | Teams completed | Effort | Depends on | Parallel-safe with |
|---|---|---|---|---|---|---|
| G1 | Member legality for POOL | - | - | 4 (1 PR) | - | - |
| G2 | Gap rows, columns, 12 data-only moves marked | rockslide, doubleedge, thunderbolt, flashcannon, extremespeed, headsmash, bulkup, liquidation, icepunch, shadowclaw, drumbeating, dazzlinggleam, pelipper, arcaninehisui, annihilape | - | 4 (1 PR) | G1 | - |
| G3 | POOL state tail | - | - | 4 (1 PR) | G2 | G4, G6, G10, G12 |
| G4 | Focus Sash and Rock Head | focussash, rockhead | MC172, MC385 | 4 (2 PRs) | G2 | G3, G5, G7, G8, G9, G10, G11, G12 |
| G5 | U-turn | uturn | - | 2 (1 PR) | G2 | G4, G6 |
| G6 | P2 (0015) and Expert Belt | colburberry, occaberry, blackglasses, expertbelt | MC246, MC392, MC56 | 6 (2 PRs) | G2 | G3, G5, G7, G8, G11 |
| G7 | Wide Guard | wideguard | MC371, MC97, MC196 | 4 (1 PR) | G2, G3 | G4, G6 |
| G8 | Throat Chop and Psychic Noise (Heal Block) | throatchop, psychicnoise | MC177, MC22, MC264, MC36 | 6 (2 PRs) | G2, G3 | G4, G6 |
| G9 | Encore | encore | MC373 | 8 (1 PR) | G2, G3 | G4 |
| G10 | First Impression, Scald, Recover, Low Kick | firstimpression, scald, recover, lowkick | MC215 | 8 (4 PRs) | G2 | G3, G4 |
| G11 | Soak | soak | MC167 | 4 (1 PR) | G2, G3 | G4, G6 |
| G12 | Floette-Eternal: Flower Veil, Fairy Aura, Floettite | flowerveil, fairyaura, floettite, floetteeternal | - | 6 (2 PRs) | G2, G6 | G3, G4 |

The foundation steps in words. **G1** replaces the fixed set by a legal-move rule per forme under POOL (finding F1). **G2** adds all rows and columns once, unmarked, and marks the 12 data-only moves and the three species with four recorded battles (finding F6). **G3** adds the POOL state tail and the view bits (finding F3). P2 is step **G6a** and keeps decision 0015's scope; Expert Belt rides with it (same chain, same compile-time asserts). A step marks only what it tested (decision 0015 section 2).

### 5.2 What each step touches

Regions of the shared files (hard conflict = two steps naming one region):

| Region | File and lines | What |
|---|---|---|
| turn.types | src/combat/turn.c 104-114, 720-757 | dfi_has_type, dfi_grounded, dfi_type_immune, dfi_type_mod: the only three reads of a forme's types |
| turn.boost | src/combat/turn.c 504-579 | dfi_boost: Contrary, the cap, the Competitive and Defiant reactions |
| turn.status | src/combat/turn.c 1028-1110 | dfi_try_status and dfi_add_volatile |
| turn.heal | src/combat/turn.c 1330-1340, 1413-1438, 3125-3135 | dfi_heal, the Update (Sitrus Berry) and Grassy Terrain's inline residual heal |
| turn.before | src/combat/turn.c 1553-1624 | dfi_before_move: sleep/freeze, flinch, confusion, paralysis |
| turn.run_front | src/combat/turn.c 1755-2028 | dfi_run_move up to TryMove: support check, targets, PP, lock, move line, redirects |
| turn.run_status | src/combat/turn.c 2029-2073 | the status-move branches: side conditions, Trick Room, primary self boosts |
| turn.ontry | src/combat/turn.c 2076-2101 | the special-handler guard and the Fake Out / Sucker Punch onTry checks |
| turn.hit_steps | src/combat/turn.c 2127-2242 | Psychic Terrain, Protect, TryHit abilities, immunity, accuracy |
| turn.power_bp | src/combat/turn.c 824-866 | base power by weight or fainted count, and the BasePower chain |
| turn.moddmg | src/combat/turn.c 765-769, 941-976 | the ModifyDamage chain and its compile-time order asserts |
| turn.damage_loop | src/combat/turn.c 2283-2313 | spread damage and dfi_deal per target |
| turn.self_switch | src/combat/turn.c 2314-2329 | the switch flag of a damaging pivot move |
| turn.secondaries | src/combat/turn.c 2347-2391 | secondary effects per hit target |
| turn.thaw_after | src/combat/turn.c 2409-2429, 2466-2476 | the Fire thaw and the place after the second Update |
| turn.recoil | src/combat/turn.c 2446-2477 | recoil, the user's Emergency Exit check, the Update after it |
| turn.switch | src/combat/turn.c 2559-2618 | dfi_run_switch: the [switch] event and its cause |
| turn.entry_mega | src/combat/turn.c 2666-2726, 2827-2855 | entry abilities and the Mega Evolution |
| turn.residual | src/combat/turn.c 2859-3242 | the residual list and its handlers |
| turn.use_item | src/combat/turn.c 1177-1193 | dfi_use_item: the berry test and Unburden |
| request.candidates | src/state/request.c 106-175 | dfi_slot_candidates: what a slot may choose |
| state.layout | src/state/battle_internal.h, src/codec/state_codec.{h,c}, src/state/invariants.c, tools/state_model/state_v3_model.py | the state's canonical layout, its checks and the oracle |
| state.limits | src/state/closure_member.c 8-22 | dfi_kind_limits: per data kind, the highest valid flag, status, terrain, switch-flag values |
| state.member | src/state/closure_member.c 41-109, 285-363 | the member rules: moves, ability, gender, item and their invariants |
| public.view | include/duoforge/duoforge.h, src/state/observation.c, python/duoforge/_layout.py 427-461 | the position and side views |
| public.events | include/duoforge/duoforge.h, src/combat/events.c, tests/support/conformance_compare.c 494-571 | event kinds, causes, flags |
| gen | tools/datagen/gen_closure.py 83-112, 219-333 | the generator's encodings and its parse_move |
| tables | src/data/pool_tables.{h,c} (decision 0015) and the pins in tests/CMakeLists.txt | the generated POOL tables, their hashes and fingerprint |
| harness | tools/reference/ps_trace.js 77-107 | the draw classification |
| converter.rules | tools/reference/trace_to_c.py 233-327 | the draw drop rules |
| converter.lines | tools/reference/trace_to_c.py 546-777 | ev_cause and step_events: the protocol lines it knows |

| Step | turn.c regions | Other regions | Additive public changes |
|---|---|---|---|
| G1 | - | gen, tables, state.member, state.limits | - |
| G2 | - | gen, tables | - |
| G3 | - | public.view, state.layout, state.limits | position-view bits for Encore and Heal Block (reserved byte bits 8 and 16) and, for Soak, bit 32 or one more byte; a side-view bit for Wide Guard (the side view's reserved byte) |
| G4 | turn.damage_loop, turn.recoil, turn.use_item | - | - |
| G5 | turn.self_switch, turn.switch | converter.lines, state.limits | - |
| G6 | turn.moddmg, turn.power_bp, turn.use_item | converter.rules | - |
| G7 | turn.hit_steps, turn.residual, turn.run_status | converter.lines, public.events, public.view | BLOCKED detail for Wide Guard; side-view bit |
| G8 | turn.before, turn.heal, turn.residual, turn.secondaries, turn.status | converter.lines, gen, public.events, public.view, request.candidates | position-view bit 16 (Heal Block); CANT with cause MOVE and the stopped move |
| G9 | turn.residual, turn.run_front, turn.status | converter.lines, converter.rules, harness, public.events, public.view, request.candidates | position-view bit 8 (Encore); a volatile start/end event kind or detail |
| G10 | turn.heal, turn.ontry, turn.power_bp, turn.run_status, turn.thaw_after | converter.lines, gen, request.candidates | - |
| G11 | turn.entry_mega, turn.types | converter.lines, gen, public.events, public.view | the changed type (view bit 32 or a byte); a type-change event |
| G12 | turn.boost, turn.entry_mega, turn.power_bp, turn.status | converter.lines, public.events | a BLOCK event kind |

Soft overlaps (mechanical merges, every mechanic step): support manifest (src/data/support_manifest.c); tests/CMakeLists.txt pins and test counts; library version (duoforge.h, python/duoforge/_lib.py, tests/test_api_atomicity.c); docs/support/README.md. The version number of each public change is taken with the other sessions before the PR (decision 0015 section 4).

Hard conflicts between steps (the regions they share):

| Pair | Shared regions |
|---|---|
| G1 - G2 | gen, tables |
| G1 - G3 | state.limits |
| G1 - G5 | state.limits |
| G1 - G8 | gen |
| G1 - G10 | gen |
| G1 - G11 | gen |
| G2 - G8 | gen |
| G3 - G5 | state.limits |
| G3 - G7 | public.view |
| G3 - G8 | public.view |
| G3 - G9 | public.view |
| G4 - G6 | turn.use_item |
| G5 - G7 | converter.lines |
| G5 - G8 | converter.lines |
| G5 - G9 | converter.lines |
| G6 - G9 | converter.rules |
| G7 - G8 | converter.lines, public.events, public.view, turn.residual |
| G7 - G9 | converter.lines, public.events, public.view, turn.residual |
| G8 - G9 | converter.lines, public.events, public.view, request.candidates, turn.residual, turn.status |
| G10 - G2 | gen |
| G10 - G5 | converter.lines |
| G10 - G6 | turn.power_bp |
| G10 - G7 | converter.lines, turn.run_status |
| G10 - G8 | converter.lines, gen, request.candidates, turn.heal |
| G10 - G9 | converter.lines, request.candidates |
| G10 - G11 | converter.lines, gen |
| G10 - G12 | converter.lines, turn.power_bp |
| G11 - G2 | gen |
| G11 - G3 | public.view |
| G11 - G5 | converter.lines |
| G11 - G7 | converter.lines, public.events, public.view |
| G11 - G8 | converter.lines, gen, public.events, public.view |
| G11 - G9 | converter.lines, public.events, public.view |
| G11 - G12 | converter.lines, public.events, turn.entry_mega |
| G12 - G5 | converter.lines |
| G12 - G6 | turn.power_bp |
| G12 - G7 | converter.lines, public.events |
| G12 - G8 | converter.lines, public.events, turn.status |
| G12 - G9 | converter.lines, public.events, turn.status |

### 5.3 Schedule for five builders

The simulation starts at P1 merged (t=0), uses effort points as durations, never runs two steps with a hard conflict together and starts items in the order of section 5.4.

| Start | Items that start (end time) |
|---|---|
| t=0 | G1 (to 4) |
| t=4 | G2 (to 8), G3 (to 8) |
| t=8 | G10a (to 10), G4a (to 10), G4b (to 10), G5 (to 10) |
| t=10 | G10b (to 12), G6a (to 14), G7 (to 14) |
| t=14 | G6b (to 16), G8a (to 18) |
| t=18 | G11 (to 22) |
| t=22 | G10d (to 24), G9 (to 30) |
| t=30 | G10c (to 32) |
| t=32 | G8b (to 34) |
| t=34 | G12a (to 38) |
| t=38 | G12b (to 40) |

At most 4 items run at the same time: the hard conflicts of section 5.2, not the number of builders, limit the schedule. Reading it: one builder owns G1 and then G2 (generator, tables, member rules); the state tail G3 runs beside G2. After G2 and G3 the mechanic steps are spread over five builders; Encore (G9) waits for the lockout step (G8a) because both edit the residual list, the request builder and the converter's `cant` and `-start` handling.

### 5.4 Team order: curve.txt against the plan

**Rule.** Cost is the effort of the steps a team still needs (shared steps once, G3 when first needed; P1, G1, G2 common to all teams beyond A and B). The cheapest team goes first. Teams within 2 points of the cheapest cost about the same (one S step); among them the variety rule decides: (1) a team that shares 5 or more species with Team A, B, C or a team completed earlier is a near-duplicate and goes last; (2) the more species away from the nearest of those, the better; (3) then more archetype tags (rain or sun, Trick Room, Wide Guard); (4) then the cheaper; (5) then the order of `curve.txt`. "Plan" counts P2 as work (4 points); "no tie-break" is the same greedy with tolerance 0; "P2 scheduled" treats P2 as already decided (cost 0).

| Curve | Team | Plan | No tie-break | P2 scheduled | Steps needed | Done | Most species shared | Tags | Move |
|---|---|---|---|---|---|---|---|---|---|
| 1 | MC405 | 1 | 1 | 1 | built | 0 | 6 (A/B/C) | - | same |
| 2 | MC408 | 2 | 2 | 2 | built | 0 | 6 (A/B/C) | rain, sun, trickroom | same |
| 3 | MC246 | 5 | 3 | 3 | G6a | t=14 | 5 (A/B/C) | - | down 2 |
| 4 | MC371 | 7 | 7 | 7 | G3 G7 | t=14 | 3 (A/B/C) | rain, wideguard | down 3 |
| 5 | MC373 | 15 | 15 | 15 | G3 G9 | t=30 | 3 (A/B/C) | - | down 10 |
| 6 | MC177 | 11 | 13 | 11 | G10a G3 G5 G8a | t=18 | 3 (A/B/C) | - | down 5 |
| 7 | MC22 | 12 | 14 | 12 | G10a G3 G5 G8a | t=18 | 3 (A/B/C) | trickroom | down 5 |
| 8 | MC97 | 8 | 8 | 8 | G3 G5 G7 | t=14 | 3 (A/B/C) | rain, trickroom, wideguard | same |
| 9 | MC167 | 14 | 11 | 14 | G11 G3 G5 | t=22 | 3 (A/B/C) | trickroom | down 5 |
| 10 | MC264 | 17 | 16 | 17 | G3 G6a G6b G8a G8b G9 | t=34 | 3 (A/B/C) | trickroom | down 7 |
| 11 | MC392 | 6 | 4 | 4 | G4a G6a G6b | t=16 | 2 (A/B/C) | rain | up 5 |
| 12 | MC36 | 13 | 12 | 13 | G3 G4a G5 G6a G8a | t=18 | 5 (A/B/C) | - | down 1 |
| 13 | MC56 | 9 | 9 | 9 | G3 G5 G6a G7 | t=14 | 2 (A/B/C) | rain, trickroom, wideguard | up 4 |
| 14 | MC215 | 16 | 17 | 16 | G10b G10c G3 G4a G5 G6a G7 G9 | t=32 | 3 (A/B/C) | rain, wideguard | down 2 |
| 15 | MC196 | 10 | 10 | 10 | G3 G5 G7 | t=14 | 2 (A/B/C) | rain, wideguard | up 5 |
| 16 | MC172 | 3 | 5 | 5 | G4a G4b | t=10 | 3 (A/B/C) | trickroom | up 13 |
| 17 | MC385 | 4 | 6 | 6 | G4a G4b | t=10 | 4 (A/B/C) | - | up 13 |

**Where the tie-break changed the curve order.** Against the same greedy with no tie-break (cost only, ties by curve.txt): MC246 3 to 5, MC177 13 to 11, MC22 14 to 12, MC167 11 to 14, MC264 16 to 17, MC392 4 to 6, MC36 12 to 13, MC215 17 to 16, MC172 5 to 3, MC385 6 to 4. Against curve.txt: MC246 3 to 5, MC371 4 to 7, MC373 5 to 15, MC177 6 to 11, MC22 7 to 12, MC167 9 to 14, MC264 10 to 17, MC392 11 to 6, MC36 12 to 13, MC56 13 to 9, MC215 14 to 16, MC196 15 to 10, MC172 16 to 3, MC385 17 to 4. Round 1: MC172 (cost 4, 3 species shared with the nearest reference) is taken; passed over as near-duplicates: MC246 (4, shares 5 with A/MC405). Round 2: MC392 (cost 6, 2 species shared with the nearest reference) is taken although the cheapest, MC246 (4), is cheaper; passed over as near-duplicates: MC246 (4, shares 5 with A/MC405/MC385). Round 3: MC97 (cost 10, 4 species shared with the nearest reference) is taken although the cheapest, MC371 (8), is cheaper; passed over as near-duplicates: MC371 (8, shares 5 with MC392); MC36 (10, shares 5 with C). Round 4: MC177 (cost 6, 3 species shared with the nearest reference) is taken although the cheapest, MC167 and MC36 (4), is cheaper; passed over as near-duplicates: MC36 (4, shares 5 with C). Round 6: MC373 (cost 8, 4 species shared with the nearest reference) is taken; passed over as near-duplicates: MC264 (10, shares 5 with MC177). Round 7: MC215 (cost 4, 5 species shared with the nearest reference) is taken although the cheapest, MC264 (2), is cheaper; every candidate was a near-duplicate, so more archetype tags decided. MC246 is Team A with Salamence for Staraptor (5 of 6 species shared). Its only gap is P2 (4 points) and its steps are built anyway for MC392; with the variety rule it completes at t=14, in the same round as MC392 (t=16), but the first two builds go to MC172 and MC385 (Arcanine-Hisui, Focus Sash, Rock Head) instead of the Team A near-duplicate. The rule costs the curve nothing: P2 is built in round 2.

Why each round chose its team (candidates within the tolerance, with the variety facts):

| Round | Cheapest | Candidates | Chosen | Builds | Tie-break used |
|---|---|---|---|---|---|
| 1 | 4 | MC172 (4; trickroom); MC385 (4; no tag); MC246 (4, near-duplicate of A/MC405; no tag) | MC172 | G4a, G4b | yes |
| 2 | 4 | MC392 (6; rain); MC246 (4, near-duplicate of A/MC405/MC385; no tag) | MC392 | G6a, G6b | yes |
| 3 | 8 | MC97 (10; rain+trickroom+wideguard); MC56 (10; rain+trickroom+wideguard); MC196 (10; rain+wideguard); MC167 (10; trickroom); MC371 (8, near-duplicate of MC392; rain+wideguard); MC36 (10, near-duplicate of C; no tag) | MC97 | G5, G3, G7 | yes |
| 4 | 4 | MC177 (6; no tag); MC167 (4; trickroom); MC22 (6; trickroom); MC36 (4, near-duplicate of C; no tag) | MC177 | G10a, G8a | yes |
| 5 | 4 | MC167 (4, near-duplicate of MC22; trickroom) | MC167 | G11 | no |
| 6 | 8 | MC373 (8; no tag); MC264 (10, near-duplicate of MC177; trickroom) | MC373 | G9 | yes |
| 7 | 2 | MC215 (4, near-duplicate of MC177; rain+wideguard); MC264 (2, near-duplicate of MC177; trickroom) | MC215 | G10b, G10c | yes |
| 8 | 2 | MC264 (2, near-duplicate of MC177; trickroom) | MC264 | G8b | no |

## 6. Open questions for the owner

Q1. Is the learnset gate (G1) part of P1? Under decision 0015 as written, POOL keeps the fixed set per forme, so no team beyond A and B can be set up. Folding it into P1 now saves a second regeneration of the POOL tables and fingerprint.

Q2. How may the state grow (finding F3)? A POOL-only tail (recommended), schema 4 for every kind, or bit-sharing in the existing bytes. The same question for the observation: Soak's type needs bit 32 of the view's reserved byte (enough for Soak alone) or one more byte, which changes the 736-byte observation and the Python feature layout.

Q3. Does the variety rule use Team C as a reference (this note does) and does it count teams completed earlier in the plan? It decides which team gets evidence first when two cost about the same (section 5.4); the same steps get built either way and only the first rounds differ. Builds of the first four rounds without the rule: G6a | G4a+G6b | G4b | G3+G7; with it: G4a+G4b | G6a+G6b | G5+G3+G7 | G10a+G8a.

Q4. May G2 add all 35 rows at once, unmarked, so the POOL fingerprint is fixed for the whole track (finding F6)? The alternative is each step adding its own rows and regenerating the tables after every merge.

Q5. Is P2 (0015) kept where 0015 puts it, right after P1, or may it wait behind the Focus Sash and Rock Head steps that complete two teams sooner? The order table shows both costs.

## 7. Files

- `data/team_gaps.json`: this note as data (entries, steps, schedule, order), from `tools/tg_build.js`.
- `tools/tg_verify_teams.js`: the independent check of the 17 teams (also `--all` for the 227 pastes); `tools/tg_probe_generator.py`: what `gen_closure.py` encodes or rejects for each move; `tools/tg_probe_reference.js` and `tools/tg_probe_encore_draws.js`: short Showdown battles that show the lines and draws of the mechanics; `tools/tg_show.js`: prints a Showdown entry with file:line; `tools/tg_check_cites.js`: checks every citation in the data against the files.
- `tools/tg_gaps_moves.js`, `tools/tg_gaps_other.js`, `tools/tg_plan.js`: the curated entries; `tools/tg_build.js` writes both outputs (`--check` compares them).
- The survey data (pastes, `mc_full_coverage.json`, `curve.txt`) stays outside git in `C:\Dev\src\duoforge-data\vgcpastes-mc-2026-10-02\`; the pastes are cited by id and link only (the id of a team is its survey id, the link is in the JSON).
- Like the other scripts here, these are research tooling, not part of the build or CI; they hard-code `C:/Dev/src/pokemon-showdown` (override: `DUOFORGE_PS_REFERENCE_DIR`) and the survey directory (`DUOFORGE_SURVEY_DIR`).
