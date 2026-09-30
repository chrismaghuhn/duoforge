# Mechanics inventory for the two reference teams (draft)

Status: **research draft, source-read only**. It is not a contract, not evidence of implemented behaviour and not a support claim. Every statement was read at Pokémon Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc` (decision 0004). **Nothing was executed**: no Node, no simulator run. Statements in the eight earlier rows that say "executed" come from the first research pass and were not re-run here.

This file completes the pre-M3 inventory required by `docs/ROADMAP.md`: the four missing Team B members, the three cross-cutting passes, a verification pass and a proposed M3/M4 split. The per-Pokémon detail is in `matchup-inventory-draft.jsonl` (12 rows, 375 mechanics); this file is the synthesis.

## 1. Closure

- 12 Pokémon and 4 Mega formes (Staraptor, Raichu-Y, Golisopod, Charizard-Y); at most one Mega per side per battle, so Team A chooses between Staraptor and Raichu and Team B between Golisopod and Charizard.
- 36 distinct moves, 12 base abilities plus 4 Mega abilities, 11 distinct items (Sitrus Berry is held once on each team).
- Field effects: Grassy Terrain (Rillaboom), rain (Politoed), sun (Mega Charizard Y), Trick Room (Farigiraf), Tailwind (Staraptor), Reflect and Light Screen (Grimmsnarl).
- Statuses reachable: paralysis (Zap Cannon), sleep (Hypnosis), freeze (Ice Beam), burn (Heat Wave). No poison source.
- Volatiles reachable: flinch (Fake Out, Iron Head), confusion (Hurricane), protect and stall, Flash Fire boost, two-turn charge and locked move (Electro Shot). No Encore, Disable, Taunt, Substitute, trapping, Leech Seed or partial trapping.
- All four new sets are legal in the champions learnsets and formats-data at the pin.

### Species, computed Champions stats (formula data/mods/champions/scripts.ts:10-40)

| Team | Forme | Types | Base HP/Atk/Def/SpA/SpD/Spe | Set stats HP/Atk/Def/SpA/SpD/Spe | hg | Grass Knot BP | pokedex.ts |
|---|---|---|---|---|---|---|---|
| A | rillaboom | Grass | 100/125/90/60/70/85 | 193/194/112/72/96/113 | 900 | 80 | 15678-15692 |
| A | staraptor | Normal, Flying | 85/120/70/50/60/100 | 192/140/90/63/82/167 | 249 | 40 | 7423-7437 |
| A | staraptormega | Fighting, Flying | 85/140/100/60/90/110 | 192/160/120/72/112/178 | 500 | 80 | 7438-7452 |
| A | milotic | Water | 95/60/79/100/125/81 | 202/72/128/120/165/101 | 1620 | 100 | 6502-6515 |
| A | ceruledge | Fire, Ghost | 75/125/80/60/100/85 | 181/167/124/72/123/106 | 620 | 80 | 18122-18135 |
| A | raichu | Electric | 60/90/55/90/80/110 | 164/99/80/110/100/178 | 300 | 60 | 804-819 |
| A | raichumegay | Electric | 60/100/55/160/80/130 | 164/108/80/180/100/200 | 260 | 60 | 852-866 |
| A | gholdengo | Steel, Ghost | 87/60/95/133/91/84 | 179/72/117/187/127/118 | 300 | 60 | 19101-19115 |
| B | politoed | Water | 90/75/75/90/100/70 | 197/85/95/154/120/94 | 339 | 60 | 3980-3993 |
| B | golisopod | Bug, Water | 75/125/140/60/90/40 | 182/194/160/72/111/61 | 1080 | 100 | 14516-14530 |
| B | golisopodmega | Bug, Steel | 75/150/175/70/120/40 | 182/222/195/81/141/61 | 1480 | 100 | 14531-14545 |
| B | archaludon | Steel, Dragon | 90/105/130/125/65/85 | 197/112/166/145/109/114 | 600 | 80 | 19501-19514 |
| B | farigiraf | Normal, Psychic | 120/90/70/110/70/60 | 224/99/121/130/107/80 | 1600 | 100 | 18798-18811 |
| B | charizard | Fire, Flying | 78/84/78/109/85/100 | 169/93/116/132/105/163 | 905 | 80 | 106-122 |
| B | charizardmegay | Fire, Flying | 78/104/78/159/115/100 | 169/111/116/182/135/163 | 1005 | 100 | 138-152 |
| B | grimmsnarl | Dark, Fairy | 95/120/65/95/75/60 | 202/140/99/115/126/72 | 610 | 80 | 16636-16650 |

### Moves (data/moves.ts with data/mods/champions/moves.ts overrides applied)

| Move | Users | Cat | Type | BP | Acc | Prio | Target | PP base -> Champions max | Secondary / notes | moves.ts | Override |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bitterblade | Ceruledge | Phys | Fire | 90 | 100 | 0 | normal | 10 -> 12 |  | 1368-1380 |  |
| bravebird | Staraptor | Phys | Flying | 120 | 100 | 0 | any | 15 -> 16 |  | 1775-1788 |  |
| closecombat | Staraptor | Phys | Fighting | 120 | 100 | 0 | normal | 5 -> 8 |  | 2571-2589 |  |
| coil | Milotic | Stat | Poison | 0 | true | 0 | self | 20 -> 20 |  | 2606-2624 |  |
| dragonpulse | Archaludon | Spec | Dragon | 85 | 100 | 0 | any | 10 -> 12 |  | 4163-4175 |  |
| drillrun | Golisopod | Phys | Ground | 80 | 95 | 0 | normal | 10 -> 12 |  | 4280-4293 |  |
| electroshot | Archaludon | Spec | Electric | 130 | 100 | 0 | normal | 10 -> 12 |  | 4630-4659 |  |
| fakeout | Raichu, Rillaboom | Phys | Normal | 40 | 100 | 3 | normal | 10 -> 12 | 100% volatileStatus: 'flinch', [override has onDisableMove] | 5087-5109 | 354-361 |
| focusblast | Raichu | Spec | Fighting | 120 | 70 | 0 | normal | 5 -> 8 | 10% boosts: { spd: -1, }, | 5952-5970 |  |
| grassknot | Farigiraf | Spec | Grass | 0 | 100 | 0 | normal | 20 -> 20 |  | 7537-7577 |  |
| grassyglide | Rillaboom | Phys | Grass | 55 | 100 | 0 | normal | 20 -> 20 |  | 7655-7672 |  |
| heatwave | Charizard | Spec | Fire | 95 | 90 | 0 | allAdjacentFoes | 10 -> 12 | 10% status: 'brn', | 8516-8532 |  |
| highhorsepower | Rillaboom | Phys | Ground | 95 | 95 | 0 | normal | 10 -> 12 |  | 8885-8897 |  |
| hurricane | Charizard | Spec | Flying | 110 | 70 | 0 | any | 10 -> 12 | 30% volatileStatus: 'confusion', | 9026-9054 |  |
| hypnosis | Milotic | Stat | Psychic | 0 | 60 | 0 | normal | 20 -> 20 |  | 9220-9234 |  |
| icebeam | Milotic, Politoed | Spec | Ice | 90 | 100 | 0 | normal | 10 -> 12 | 10% status: 'frz', | 9302-9318 |  |
| ironhead | Golisopod | Phys | Steel | 80 | 100 | 0 | normal | 15 -> 16 | 20% volatileStatus: 'flinch', (champions) | 9722-9738 | 545-551 |
| leechlife | Golisopod | Phys | Bug | 80 | 100 | 0 | normal | 10 -> 12 |  | 10188-10201 |  |
| lightscreen | Grimmsnarl | Stat | Psychic | 0 | true | 0 | allySide | 30 -> 20 |  | 10315-10355 |  |
| makeitrain | Gholdengo | Spec | Steel | 120 | 95 | 0 | allAdjacentFoes | 5 -> 8 |  [override has self:] | 10934-10951 | 609-617 |
| muddywater | Milotic, Politoed | Spec | Water | 90 | 85 | 0 | allAdjacentFoes | 10 -> 12 | 30% boosts: { accuracy: -1, }, | 12398-12416 |  |
| nastyplot | Gholdengo | Stat | Dark | 0 | true | 0 | self | 20 -> 20 |  | 12548-12564 |  |
| partingshot | Grimmsnarl | Stat | Dark | 0 | 100 | 0 | normal | 20 -> 20 |  | 13165-13185 |  |
| protect | Archaludon, Ceruledge, Charizard, Farigiraf, Gholdengo, Golisopod, Politoed, Raichu, Staraptor | Stat | Normal | 0 | true | 4 | self | 5 -> 8 |  | 13961-14005 | 765-768 |
| psychic | Farigiraf | Spec | Psychic | 90 | 100 | 0 | normal | 10 -> 12 | 10% boosts: { spd: -1, }, | 14041-14059 |  |
| reflect | Grimmsnarl | Stat | Psychic | 0 | true | 0 | allySide | 20 -> 20 |  | 14842-14882 |  |
| shadowball | Gholdengo | Spec | Ghost | 80 | 100 | 0 | normal | 15 -> 16 | 20% boosts: { spd: -1, }, | 16020-16038 |  |
| shadowsneak | Ceruledge | Phys | Ghost | 40 | 100 | 1 | normal | 30 -> 20 |  | 16115-16127 |  |
| snarl | Archaludon | Spec | Dark | 55 | 95 | 0 | allAdjacentFoes | 15 -> 16 | 100% boosts: { spa: -1, }, | 17085-17103 |  |
| spiritbreak | Grimmsnarl | Phys | Fairy | 75 | 100 | 0 | normal | 15 -> 16 | 100% boosts: { spa: -1, }, | 17602-17619 |  |
| swordsdance | Ceruledge | Stat | Normal | 0 | true | 0 | self | 20 -> 20 |  | 18691-18707 |  |
| tailwind | Staraptor | Stat | Flying | 0 | true | 0 | allySide | 15 -> 16 |  | 18875-18914 |  |
| trickroom | Farigiraf | Stat | Psychic | 0 | true | -7 | all | 5 -> 8 |  | 19940-19980 |  |
| weatherball | Charizard, Politoed | Spec | Normal | 50 | 100 | 0 | normal | 10 -> 12 |  | 20692-20745 |  |
| woodhammer | Rillaboom | Phys | Grass | 120 | 100 | 0 | normal | 15 -> 16 |  | 21018-21031 |  |
| zapcannon | Raichu | Spec | Electric | 120 | 50 | 0 | normal | 5 -> 8 | 100% status: 'par', | 21163-21179 |  |

### Abilities and items in the closure

| Kind | Name | Holder | Base lines | Champions override |
|---|---|---|---|---|
| ability | Grassy Surge | Rillaboom | data/abilities.ts:1707-1715 | - |
| ability | Intimidate | Staraptor | data/abilities.ts:2193-2212 | - |
| ability | Competitive | Milotic | data/abilities.ts:645-665 | - |
| ability | Flash Fire | Ceruledge | data/abilities.ts:1341-1381 | - |
| ability | Lightning Rod | Raichu | data/abilities.ts:2343-2367 | - |
| ability | Good as Gold | Gholdengo | data/abilities.ts:1630-1641 | - |
| ability | Drizzle | Politoed | data/abilities.ts:1078-1087 | - |
| ability | Emergency Exit | Golisopod | data/abilities.ts:1250-1265 | abilities.ts:22-29 |
| ability | Stamina | Archaludon | data/abilities.ts:4514-4522 | - |
| ability | Armor Tail | Farigiraf | data/abilities.ts:215-233 | - |
| ability | Blaze | Charizard | data/abilities.ts:460-479 | - |
| ability | Prankster | Grimmsnarl | data/abilities.ts:3425-3436 | - |
| ability (Mega) | Contrary | staraptormega | data/abilities.ts:678-690 | - |
| ability (Mega) | No Guard | raichumegay | data/abilities.ts:2970-2985 | - |
| ability (Mega) | Tough Claws | golisopodmega | data/abilities.ts:5066-5077 | - |
| ability (Mega) | Drought | charizardmegay | data/abilities.ts:1088-1097 | - |
| item | Miracle Seed | Rillaboom | data/items.ts:4135-4149 | - |
| item | Staraptite | Staraptor | data/items.ts:5977-5988 | items.ts:898-901 |
| item | Sitrus Berry | Milotic | data/items.ts:5744-5765 | - |
| item | Grassy Seed | Ceruledge | data/items.ts:2595-2617 | - |
| item | Raichunite Y | Raichu | data/items.ts:5047-5058 | items.ts:766-769 |
| item | Life Orb | Gholdengo | data/items.ts:3404-3420 | - |
| item | Mystic Water | Politoed | data/items.ts:4254-4268 | - |
| item | Golisopite | Golisopod | data/items.ts:2529-2540 | items.ts:402-405 |
| item | Leftovers | Archaludon | data/items.ts:3338-3351 | - |
| item | Sitrus Berry | Farigiraf | data/items.ts:5744-5765 | - |
| item | Charizardite Y | Charizard | data/items.ts:800-811 | items.ts:142-145 |
| item | Light Clay | Grimmsnarl | data/items.ts:3444-3453 | - |

## 2. Pass A: implicit mechanics

These are needed by every battle although no set lists them. References are in the JSONL rows; the anchors below are the ones re-read in this pass.

| Mechanic | What the closure needs | Anchor |
|---|---|---|
| Action ordering | Order classes switch 103, megaEvo 104, moves 200, residual 300; instaswitch 3 for forced replacements; priority, then speed, then shuffle on ties; re-sort after every action | `sim/battle-queue.ts:174-192`, `sim/battle.ts:404-411`, `sim/battle.ts:2649` |
| Speed | Champions action speed is `-speed` under Trick Room, no 13-bit truncation; Tailwind doubles; paralysis halves | `data/mods/champions/scripts.ts:46-54` |
| Speed ties | Only Mega Staraptor 178 and base Raichu 178 (same side) tie; every other pair is distinct, also under Trick Room | species table below |
| Damage | `tr(tr(tr(tr(2L/5+2)*BP*A)/D)/50)`, then spread 0.75, weather, crit 1.5, random `100 - random(16)`, STAB, type, burn, final modifiers | `sim/battle-actions.ts:1718`, `data/mods/champions/scripts.ts:196-312`, `sim/battle.ts:2391-2394` |
| Critical hits | Default critRatio 1 gives 1/24; Drill Run has critRatio 2 (`data/moves.ts:4289`) and gives 1/8; no crit-boosting item or ability | `sim/battle-actions.ts:1623-1646` |
| Accuracy | One draw per target for numeric accuracy (also at 100); skipped for `true`, No Guard, Flash Fire absorption, rain Hurricane; stages from Muddy Water (-1) and Coil (+1) | `sim/battle-actions.ts:690-760` |
| Secondary effects | One `random(100)` per secondary and target, drawn even at 100% | `sim/battle-actions.ts:1336-1352` |
| Stat stages | -6..+6, reset on switch, crit rules; hooks for Stamina, Competitive, Contrary, Intimidate | `sim/battle.ts:2020-2090` |
| PP and Struggle | Champions PP formula; Struggle when nothing is selectable; Fake Out disabled after the first active move action | `data/mods/champions/scripts.ts:3-9,41-43`, `data/moves.ts:18211-18232`, `data/mods/champions/moves.ts:354-361` |
| Switching | Voluntary switch, forced replacement, pivot; switch-in abilities run in speed order; Megas persist | `sim/battle-actions.ts:62-209`, `data/mods/champions/scripts.ts:56-121` |
| Mid-turn requests | A side with a set `switchFlag` and a live bench gets a switch request while the rest of the turn stays queued | `sim/battle.ts:2876-2915` |
| Faint and win | Faint queue, replacement, last-faint rule when both sides run out | `sim/battle.ts:2535-2617` |
| Residual phase | Handlers sorted by order, speed, sub-order: weather upkeep 1; terrain heal 5/2; Leftovers 5/4; burn 10; screens 26; Tailwind 26/5; Trick Room 27/1; terrain end 27/7 | `sim/battle.ts:484-510` |
| Retargeting | A single-target move whose target is gone picks a random foe (one RNG draw) | `sim/battle.ts:2440-2521` |

## 3. Pass B: cross-team interactions

Each line is an interaction that needs an explicit test once implemented.

- **Weather is internal to Team B.** Drizzle (Politoed) and Drought (Mega Charizard Y) are on the same side and Team A has no setter. The last setter wins; simultaneous entries resolve by speed (rain wins normally, sun under Trick Room). Sun halves Politoed's Water moves, drops Charizard's own Hurricane to 50% accuracy and blocks freeze; rain makes Hurricane and Electro Shot immediate and perfect.
- **Redirection and absorption.** Base Raichu's Lightning Rod redirects and absorbs Electro Shot (and gives Raichu +1 SpA) until Raichu Mega Evolves. Ceruledge's Flash Fire absorbs Heat Wave and a Fire Weather Ball. Farigiraf and Ceruledge/Gholdengo have Ghost and Normal immunities against each other's moves.
- **Priority blocking.** Armor Tail cancels Fake Out, Shadow Sneak and a terrain-boosted Grassy Glide aimed at either Team B active while Farigiraf is on the field. Team A has no answer (no Mold Breaker).
- **Status moves against Good as Gold.** Gholdengo is immune to Parting Shot (no drop, no pivot) and Hypnosis is Team A's own. Trick Room and the screens are unaffected.
- **Stat-drop reactions.** Snarl, Spirit Break, Parting Shot and Psychic's secondary trigger Competitive (+2 SpA on Milotic) and are inverted by Contrary (Mega Staraptor). Intimidate (base Staraptor) lowers Team B's physical attackers on each Staraptor entry.
- **Defensive stacking.** Stamina raises Archaludon's Defense after every hit, Leftovers and Grassy Terrain heal it each turn, and Grimmsnarl's screens last 8 turns with Light Clay; Team A has no screen removal, item removal or stat reset.
- **Pivots.** Parting Shot and Emergency Exit are both Team B. A one-side mid-turn switch request is reachable every turn; a two-side pivot is **unreachable** in this matchup (Team A has no pivot move and no Eject Button).
- **Speed control.** Tailwind (4 turns) against Trick Room (5 turns); under Trick Room Tailwind makes Team A move later. Paralysis from Zap Cannon is guaranteed once Mega Raichu Y's No Guard is active.
- **Thresholds.** Sitrus Berry at half HP (Farigiraf 112, Milotic 101), Emergency Exit at half (Golisopod 91), Blaze at one third (Charizard 56), Grassy Seed on terrain start.
- **Recoil and self-damage.** Wood Hammer, Brave Bird and Life Orb on Team A; none on Team B except Struggle. Double KOs and the last-faint rule are reachable.
- **Spread moves into Protect.** Muddy Water, Make It Rain, Heat Wave and Snarl keep the 0.75 modifier when one target protects (`spreadHit` is fixed before the hit steps, `sim/battle-actions.ts:551`).
- **Mega Staraptor changes type** to Fighting/Flying, which flips several matchups (Psychic, Hurricane and Spirit Break become 2x).

## 4. Pass C: decisions and information

What the M2 decision surface already covers, and what the closure adds.

| Topic | Finding | Consequence |
|---|---|---|
| Boundaries | TEAM_SELECTION, TURN, REPLACEMENT and a one-side PIVOT are reachable. A two-side PIVOT is not reachable with these teams | Keep the two-side case structural and test it with synthetic fixtures only |
| Target classes | Only normal, any, self, allAdjacentFoes, allySide and all occur; the M2 table T1 equals the pinned data | No new class needed for M3/M4 |
| Locked move | After an Electro Shot charge the slot is locked and trapped: only that move, no switch, no Mega (`sim/pokemon.ts:1086-1140`) | State needs the charge volatile; the domain needs a locked-move rule (state v3) |
| Fake Out | Disabled once the user has taken a move action since entering (`activeMoveActions`) | State needs a per-activation counter; domain rule |
| Struggle | Offered when no move is selectable; Mega is not offered then | M2 returns `E_UNSUPPORTED`; M3 must implement it |
| Mega | Charizard and Golisopod share Team B's single Mega; Staraptor and Raichu share Team A's | Already a side-wide flag in M2 |
| Trapping and re-prompts | No trapping ability or move exists in either team, `maybeTrapped` is never set | Rule-authorized re-prompt stays structural; no hidden-trapping leak to model yet |
| Disabling effects | No Encore, Disable, Taunt, Torment, Imprison, choice item or Assault Vest | No further domain restriction in this closure |
| Hidden facts | Bench identity and order until sent in, exact HP, PP, the Mega choice until declared, the gameplay RNG | Matches decision 0005 section 6 |
| Revealed facts | Item consumption (Sitrus Berry, Grassy Seed), ability activations, stat stages, field start and end, HP percent | Knowledge state must record them as events (M3/M4) |
| RNG draw sites | Speed-tie shuffle, accuracy, crit, damage roll, secondary, Protect stall, confusion (start, per turn, self-hit roll), sleep duration, freeze thaw, full paralysis, random retarget | Each site needs a named draw in the M3 RNG accounting |
| Gender | Drawn from the RNG at construction when a set omits it (Grimmsnarl is fixed male) | Always specify gender in fixtures so battle draws stay aligned |

## 5. Proposed split between M3 and M4 (owner decision)

The roadmap asks for a first vertical slice and then dependency-ordered closure tasks. This is a proposal, not a decision.

**M3, first combat slice.** Real species, stat and move data for the two teams, restricted to:

1. stat and PP formulas, stat stages, the damage pipeline with crit, random factor, STAB, type chart and spread modifier;
2. accuracy with stages, plain damaging moves (single target and spread), self-boost moves (Swords Dance, Nasty Plot, Coil);
3. Protect with the stall counter, priority brackets, speed sort and tie shuffle;
4. PP deduction and Struggle;
5. voluntary switching, fainting, real REPLACEMENT boundaries and the win rule;
6. named RNG draw sites and reference fixtures from the pinned simulator.

Any set whose remaining mechanics are not implemented stays rejected at setup; an M3 battle is a labelled development fixture, not a certified game.

**M4, closure in dependency order.**

1. Secondary effects and statuses (paralysis, sleep, freeze, burn, flinch, confusion).
2. Entry abilities, weather and terrain (Drizzle, Drought, Grassy Surge, Intimidate) and the residual phase.
3. Side and field conditions (Tailwind, Reflect, Light Screen, Trick Room).
4. Reactive abilities (Stamina, Competitive, Contrary, Flash Fire, Lightning Rod, Good as Gold, Armor Tail, Prankster, Blaze, No Guard, Tough Claws).
5. Items (Leftovers, Sitrus Berry, Grassy Seed, Life Orb, Miracle Seed, Mystic Water, Light Clay).
6. Recoil, drain and self-drops (Wood Hammer, Brave Bird, Bitter Blade, Leech Life, Close Combat, Make It Rain).
7. Special moves (Weather Ball, Hurricane, Grass Knot, Grassy Glide, Fake Out, Electro Shot with the locked move).
8. Mega Evolution for the four formes.
9. Pivots (Parting Shot, Emergency Exit) with real PIVOT boundaries.

## 6. Verification pass

Automated checks (`tools/research/verify_inventory.py`, run on 2026-09-30 against the pinned files):

- **References:** 973 distinct references in the 12 rows; 971 are `path:line` references across 31 files and every line range lies inside the pinned file. Two references in the earlier rows carry no line range (`data/typechart.ts` and a `data/moves.ts grassknot` note).
- **Stats:** 12 stat lines quoted in species entries were recomputed from `data/pokedex.ts` base stats, the Stat Points of decision 0004 and the champions formula; mismatches: none.
- **Target classes:** the M2 fixture table T1 against the pinned `target` field of the 36 moves: identical.
- **Legality:** the four new sets have all their moves in `data/mods/champions/learnsets.ts` and a tier in `formats-data.ts`.
- **Counts:** 36 distinct moves, 12 rows, 375 mechanics.
- **Re-read by hand in this pass:** team preview and choice rules (`sim/side.ts`), target validation, open team sheets and HP display (M2), and for the four new members every ability, item, move, condition and champions override listed in the tables of section 1.

Limits of this pass:

- Source reading only. The differential fixtures recommended in `champions-reg-mc-report-draft.md` section 5 need Node and the pinned repository; they were **not run**.
- The eight earlier rows were not re-derived line by line. Their quoted stat lines were recomputed (all match) and every reference was checked to point inside an existing file; their behavioural claims and the ones marked "executed" remain unverified.
- The pinned champions mod files are not yet in decision 0004's hash table. Their sha256 at the pin, for whoever starts M3:

| File | sha256 |
|---|---|
| `data/mods/champions/abilities.ts` | `86c3843d402f1ff7be276d8f2da08d6744b8a8822349560b300ddcfa9c1fbc52` |
| `data/mods/champions/conditions.ts` | `851507309dde0b58807e33b17d8ce7e607dad70893546f67bad294ad70249005` |
| `data/mods/champions/formats-data.ts` | `a512b537a84574a324c250c6ff99ad60f0cf1e82420fdae60d4635eec8661e13` |
| `data/mods/champions/items.ts` | `b39dafa66d136ebb1a8576367ced2c9f4519aa1c17d5d65c59b368ac15d7de77` |
| `data/mods/champions/learnsets.ts` | `826d302703358260a1c4967e2bf8edd15f1fe7e0f664c8ab14aff734906cc9d0` |
| `data/mods/champions/moves.ts` | `1d317da33d3e36d430a9cbe195c2ef9bb9a6fc2f3e0516ba2200da8a394080bc` |
| `data/mods/champions/rulesets.ts` | `31671152a6ff1f09d81a5306baadaa1593ef235e5c7cdcc9180c67bac8e84cd9` |
| `data/mods/champions/scripts.ts` | `a6cc11eeb525ad58dee9010dd0d42274a5b4dacb39ce8653f4888cbd2f4f459d` |
| `config/formats.ts` | `62f69eea51f71096e32bfa610115376b041c43e8f28c4a5535bfd60b229494f5` |
| `sim/dex-formats.ts` | `94ac9f4ea4be767603d35336e8019d7daef4fa0a24f1b66727f2ceb8efa9e545` |

The base files used here (`sim/side.ts`, `sim/battle.ts`, `sim/pokemon.ts`, `sim/battle-actions.ts`, `sim/battle-queue.ts`, `sim/field.ts`, `data/moves.ts`, `data/abilities.ts`, `data/items.ts`, `data/conditions.ts`, `data/pokedex.ts`, `data/typechart.ts`) match the hashes in decision 0004.

## 7. Open points for the owner

1. Accept, change or reject the M3/M4 split in section 5.
2. Decide whether fixtures always specify gender (recommended) so no construction-time draw exists.
3. Executed reference fixtures need a Node environment with the pinned repository; decide where they run.
4. State v3 will need at least a per-activation move-action counter (Fake Out), the two-turn charge volatile with its locked move, stat stages, statuses, field and side conditions. This is M3/M4 schema work, not part of M2.
5. The earlier rows contain two references without line numbers (listed in section 6); fix them when the rows are next edited.
