# Expansion inventory: the Reg M-C pool, engine effort, usage and differential testing

Status: **research draft**, agent-generated on 2026-10-01. Four read-only research agents of the Team C session produced it (legal pool, effort classes, usage, differential testing), and that session synthesised and spot-checked it. It is not a contract, not evidence and not a support claim (see `../README.md`). Showdown pin `b2cb775b0616115b775534eaeff50300e1fc81fc`. The DuoForge state analysed is Team C step 5 (closure plus Team C tables).

## 1. Summary

- **Pool size.** The format's legal pool is about ten times what DuoForge's tables hold:

  | | Legal pool | DuoForge tables |
  |---|---|---|
  | Selectable formes | 293 | 18 |
  | Mega formes | 82 | 5 |
  | Moves | 510 | 49 |
  | Abilities | 215 | 21 |
  | Items | 166 | 16 |

- **Usage.** The ten most used Pokémon on the ladder are all closure or Team C species. Usage (section 4) is the best order for expansion.
- **Moves are the cheap part.**
  - 140 moves already run on the existing pipeline as data.
  - 146 more need one of 40 generic extensions; 108 of these need only one.
  - 106 of the 142 moves in families are one C rule with a generated table parameter.
- **Abilities are the expensive part.** 128 of 316 are bespoke.
- **Differential testing is feasible.** A loop against Showdown needs a persistent Node worker: 9 to 12 reference battles per second per core, against 1 to 1.6 with a new process per battle.
- **Recommended order** (section 7):
  1. Finish Team C.
  2. A families step.
  3. The first four components of the differential loop.
  4. Usage-driven expansion, toward the top 60 Pokémon (77 % of winning tournament teams fully covered).

## 2. The legal pool

**Method.** A forme, move, ability or item counts as legal when `TeamValidator.validateSet` at the pin accepts a set with it, for the format `gen9championsvgc2026regmc`. The format applies Flat Rules (Obtainable, -Unreleased, -Unobtainable, -Nonexistent, -Mythical, -Restricted Legendary), 66 Stat Points with at most 32 per stat, IVs 31, level 50 and no Tera. The checks:

- **Species:** a complete set naming the forme.
- **Moves:** one single-move set per species and move. That is 293 × 954 = 279,522 validator calls; the result agrees exactly with `checkMove` plus `checkCanLearn`.
- **Items:** on two probe species.
- **Megas:** the base species holding the stone.

The built `dist/` was checked against the TypeScript sources.

| Kind | Legal | In DuoForge's tables | Marked in the support manifest |
|---|---|---|---|
| Formes | 293 selectable: 231 base species, 264 mechanically distinct, 24 cosmetic. Plus 7 battle-only formes and 82 Megas via 81 stones | 18 + 5 Megas | as tables |
| Moves | 510 (17,364 species-move pairs) | 49 (Struggle is engine-internal) | 46 |
| Abilities | 215 (13 only on Megas) | 21 | 19 |
| Items | 166 (81 Mega stones, 85 others) | 16 | 14 |

**Open questions:**

- Lucario-Mega-Z is legal, but its only ability, Aura Guard, is tagged Future.
- Simple can be reached in battle through Simple Beam, but no legal species has it.
- Some entries are tagged as available but cannot be learned: Pound, Power Shift, Soft-Boiled, Spore, and 102 abilities.
- Every learnset entry is "9M": there are no event, egg or level-up sources.
- 29 identical formes need a dedupe policy.
- The validator does not check that a stone matches its holder.

## 3. Effort classes

The pass covers the format's dex without the legality filter: every entry that has no `isNonstandard` flag. The classes are:

- **A:** data that today's generator and engine already handle.
- **B:** data that needs a generic extension.
- **C:** a family. Either one C rule with the parameter generated into the tables ("param"), or a shared hook with code per member ("shape").
- **D:** bespoke, sized L, M or S.

| | A | B | C (param/shape) | D (L/M/S) |
|---|---|---|---|---|
| Moves (515) | 140 | 146 | 142 in 54 families (106/36) | 87 (21/52/14) |
| Abilities (316) | 2 | – | 186 in 62 families (174/12) | 128 (30/76/22) |
| Items (166) | 81 Mega stones | – | 68 in 12 families (59/9) | 17 (1/15/1) |

**Generic extensions for class B moves.** 108 of the B moves need one extension, 31 need two and 7 need three. The extensions:

- **23:** status moves that change the target's stats (Charm, Screech).
- **13:** `allAdjacent` targets such as Earthquake. Grassy Terrain's halving of Earthquake is also missing.
- **12:** `multihit`.
- **10:** self-boost secondaries (Flame Charge).
- **New flag bits** (punch 13, bite 6, powder 5 and others): the `flags` byte of the move row has no free bit left.
- **7 each:** recharge and partial trapping.
- **5 each:** poison secondaries (Team C step 6), heal, primary confusion.
- **4 each:** weather, phazing, OHKO, rampage.

**Largest families** (✓ means a member is implemented):

- **Moves:**
  - conditional base power predicates (11);
  - protect variants ✓, two-turn charge ✓ and semi-invulnerable moves (5 each);
  - trapping, terrain setters and hazards (4 each);
  - screens ✓ and weather accuracy ✓ (3 each).
- **Abilities:**
  - stat-drop immunity (8);
  - "-ate" ✓, status immunity and flag boosters ✓ (6 each);
  - KO boost, type boosters and weather speed (5 each);
  - pinch ✓, weather setters ✓, surges ✓ and contact status (4 each).
- **Items:**
  - Mega stones (81, 5 ✓);
  - type boosters ✓ and resist berries ✓ (18 each);
  - status berries (7);
  - duration extenders ✓ (6).

**Largest bespoke entries:**

- **Moves (L):** Substitute, Transform, Fling, Future Sight, Revival Blessing, Encore, Disable, Copycat, Sleep Talk, Instruct, Baton Pass, Ally Switch, Gravity, Skill Swap, Wish.
- **Abilities (L):** Sheer Force, Neutralizing Gas, Illusion, Magic Bounce, Unaware, Parental Bond, Trace, Opportunist, and ten forme changers.
- **Items:** Choice Scarf.

**Caveats:**

- **Clustering.** Automatic clustering of normalised handler code grouped only 48 of 229 callback moves, 96 of 307 abilities and 126 of 159 items. The other families and the S/M/L sizes are hand-curated judgement.
- **Behaviour outside the handlers is invisible here:**
  - core hooks: Levitate, Iron Ball, the Guts and Facade burn exception, Sheer Force with Life Orb;
  - duration items;
  - the shared conditions behind B moves.
- **"Implemented" means checked on the closure.** Turning hard-coded checks such as `dfi_holds(m, DFI_ITEM_MYSTICWATER)` into table rules is still work.
- **The generator was not run.** Its `parse_move` was re-implemented in JavaScript for this pass.

## 4. Usage

**Source.** Smogon's monthly stats for exactly this format, 2026-09, published 2026-10-01.

- **Size:** 1,631,943 ladder battles, about 9 to 30 September, the first three weeks of Reg M-C.
- **Weighting:** the primary view is cutoff 1500 (rating-weighted). Cutoff 0 differs by at most 4.5 points, and the top 15 moves, items and abilities are the same at both cutoffs.
- **Set data:** items, moves and abilities were read only for the top 41 Pokémon, which is 79 % of team slots; the fetch truncated the rest. The weighted lists below are therefore lower bounds.
- **Team data:** Smogon publishes no joint team data. Team coverage is approximated with 92 readable winning tournament teams from Pikalytics.

**Top 20 Pokémon** (% of teams, cutoff 1500), with species not in DuoForge's tables marked \*:

1. Rillaboom 43.0
2. Sneasler 36.0
3. Incineroar 28.7
4. Salamence-Mega 24.8
5. Indeedee-F 22.4
6. Kingambit 21.4
7. Golisopod-Mega 18.4
8. Basculegion 18.0
9. Farigiraf 16.8
10. Gholdengo 16.6
11. Pelipper\* 14.0
12. Archaludon 13.4
13. Milotic 13.0
14. Raichu-Mega-Y 11.1
15. Arcanine-Hisui\* 10.9
16. Charizard-Mega-Y 9.5
17. Gardevoir-Mega\* 9.0
18. Whimsicott\* 8.9
19. Sinistcha\* 8.9
20. Floette-Mega\* 8.5

**Most common, per 100 teams** (\* = not in DuoForge's tables):

- **Moves:** Protect 299, Fake Out 101, Trick Room 49, Hyper Voice 48, Close Combat 47, Grassy Glide 42, Tailwind 42, Iron Head 40, Flare Blitz 37, Wood Hammer 36, Dire Claw 32, Parting Shot 32, Weather Ball 30, Rock Slide\* 29, Helping Hand 28.
- **Items:** Sitrus Berry 50, Focus Sash\* 46, Life Orb 38, Leftovers 26, Miracle Seed 26, Salamencite 25, Choice Scarf 19, Golisopite 18, Psychic Seed\* 17, Grassy Seed 16, Chople Berry 13, Rocky Helmet 13, Colbur Berry\* 13, Raichunite Y 11, White Herb 11.
- **Abilities:** Grassy Surge 43, Unburden 32, Psychic Surge 29, Intimidate 29, Aerilate 25, Tough Claws 24, Defiant 21, Drizzle 20, Pixilate\* 17, Good as Gold 17, Adaptability 17, Armor Tail 16, Drought 15, Prankster 14, Competitive 13.

**Team coverage** (92 winning tournament teams): every team carries a Mega. The top 41 Pokémon fully cover 54 % of the teams, the top 60 cover 77 % and the top 100 cover 88 %.

## 5. Differential testing against Showdown

The design is in `differential-testing.md`. In short:

- **What exists.** `gen_real_specs.py` discards traces with `UNKNOWN` draws and only counts them. Requests are compared only by their per-slot move masks.
- **The proposed loop** has three persistent processes:
  - a Node worker in which Showdown judges every random choice; each battle is saved as a normal spec, so any finding can become a fixture;
  - `trace_to_c.py` as a library, still the only home of the drop rules;
  - a C runner that replays with the tape.
- **Outcomes.** Every battle ends in exactly one bucket: PASS, DIVERGENCE, ORACLE_GAP, UNSUPPORTED, REF_ERROR or CAP. Drop rules stay strict and nothing is discarded.

**Measured reference throughput** (sequential runs on a busy machine):

| Setup | Time per battle | Per core |
|---|---|---|
| New process per battle | 0.63–0.94 s | 1.1–1.6 battles/s |
| Persistent worker | 2.0–4.3 ms per step | 9–12 battles/s |

Recording draws costs 1.3 to 3.4 times the plain simulation.

**Components:**

1. worker (S);
2. converter library (M);
3. comparators and runner (M–L);
4. driver (M);
5. team generator;
6. coverage;
7. minimizer;
8. frozen corpus;
9. mutation runner;
10. steering.

The acceptance test for 1 to 4 is that all committed battles replay without a divergence.

## 6. Latent issues found (none affects today's data)

1. **Generator, silent misencoding.** `tools/datagen/gen_closure.py` encodes a secondary with a nested `self: { boosts }` (Flame Charge) as a boost on the target, without an error. The Team C session confirmed it by reading the code; a separate session is fixing it so that the generator fails loudly.
2. **Wrong switch cause.** In `src/combat/turn.c`, the switch event of a damaging self-switch always named Flip Turn. **Fixed in step G5**: a damaging pivot has a switch flag of its own (`dfi_pivot_moves`, `src/state/closure_member.c`), the event names the move that set it, and U-turn is marked with five recorded POOL battles (`g5_uturn_a` to `_e`). A further damaging pivot (Volt Switch, Teleport is a status move) needs one more flag value and its row, and must be marked only with its own battle.
3. **Converter, Struggle.** `convert_choice` in `trace_to_c.py` detects Struggle only when every PP is 0. When a disabled Fake Out is the only move with PP, both Showdown and the engine also give Struggle. Random play would report that as a false divergence.
4. **Full flags byte.** The `flags` byte of the move row is full, so new flag bits need a format change.
5. **Grassy Terrain.** Its halving of Earthquake and Bulldoze is missing. It matters once `allAdjacent` moves come.

## 7. Recommended order (the owner decides)

1. **Finish Team C** (steps 6 to 12). Its mechanics are near the top of usage: Dire Claw 32 and Helping Hand 28 per 100 teams, Choice Scarf 19, Psychic Surge on Indeedee-F 22 % of teams, White Herb with Unburden.
2. **A families step.** Turn the hard-coded item and ability checks into rules with table parameters:
   - type boosters (18 items) and resist berries (18);
   - "-ate", pinch, surges and weather setters.

   Each family is one rule covering many ids.
3. **Differential loop, components 1 to 4.** These come before going wide, so that every later batch of mechanics is checked by random play as well as by hand-written specs.
4. **Usage-driven expansion** toward the top 60 Pokémon. Pelipper, Arcanine-Hisui, Gardevoir-Mega (Pixilate is in the "-ate" family), Whimsicott, Sinistcha and Floette-Mega come first, with Focus Sash, Psychic Seed, Colbur Berry and Rock Slide.

**Points for the owner:**

- the data kind for full tables, and its context fingerprint;
- where the fuzz corpus is stored;
- sharing the machine with performance runs.

## 8. Files

- `data/legal_pool.json`: from `tools/build_legal_pool.js`; `tools/lp_*.js` are its cross-checks.
- `data/classification.json`: from `tools/classify.js`, `families.js`, `moves_check.js` and `lib.js`.
- `data/usage.json`: transcribed from the Smogon and Pikalytics pages with a web fetch tool. There is no script.
- `differential-testing.md`: the design sketch, written against the step-5 commit before its review fixes.

The scripts are research tooling, not part of the build or CI. They only read, write their output next to themselves, and hard-code `C:/Dev/src/pokemon-showdown` and the Team C worktree path.
