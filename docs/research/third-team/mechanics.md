# Mechanics inventory for the third reference team (draft)

Status: **research draft**. It is not a contract, not evidence of implemented behaviour and not a support claim. Every statement was read at Pokémon Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc` (decision 0004). Statements marked **executed** (X1 to X9) were checked by `docs/research/third-team/experiments.js` (27 assertions, all pass) in small ad-hoc battles of the built pin; everything else is source reading. "Closure" means `tools/datagen/gen_closure.py` (SETS, MOVES) and `src/data/support_manifest.c` at origin/main `3133fcc`.

Team C is `team-c.txt`: Sneasler, Incineroar, Salamence, Indeedee-F, Kingambit, Basculegion. Its sets come from the doubles view of pokechamdb (`README.md`).

## 1. Delta against the closure

- **7 new formes** (6 plus Salamence-Mega); none of the 16 closure formes is shared. One Mega per side is already a side-wide flag; Team C has one Mega, so the flag is unchanged.
- **21 distinct moves**: 8 in the closure (Close Combat, Protect, Fake Out, Parting Shot, Tailwind, Trick Room, Psychic, Iron Head) and **13 new** (Dire Claw, Flare Blitz, Darkest Lariat, Hyper Voice, Draco Meteor, Follow Me, Helping Hand, Kowtow Cleave, Sucker Punch, Last Respects, Wave Crash, Aqua Jet, Flip Turn).
- **6 abilities**: Intimidate is in the closure; **5 new**: Unburden, Aerilate (Mega), Psychic Surge, Defiant, Adaptability.
- **6 items**: Sitrus Berry is in the closure; **5 new**: White Herb, Salamencite, Rocky Helmet, Chople Berry, Choice Scarf.
- **New rules and state**: Psychic Terrain (the state has `DFI_TERRAIN_GRASSY` only), poison (statuses are brn/frz/par/slp), four volatiles (Follow Me, Helping Hand, choice lock, Unburden), a per-side faint counter, `adjacentAlly` targeting in the choice layer, one new draw site (the Dire Claw status pick).
- **What the generator says today** (`probe-generator.py` on origin/main, nothing changed): it parses Kowtow Cleave, Hyper Voice, Draco Meteor, Wave Crash, Aqua Jet and Flip Turn; it **fails explicitly** on Dire Claw ("unknown secondary"), Flare Blitz (unknown flag `defrost`), Darkest Lariat (unknown field `ignoreEvasion`), Follow Me and Sucker Punch (callback `onTry`), Helping Hand (`onTryHit`) and Last Respects (`basePowerCallback`). All seven formes, the learnsets, abilities and items resolve through its own lookups. One trap: Flip Turn parses and gets the SELF_SWITCH bit, but no C code reads that bit (only the PARTING_SHOT special pivots, `src/combat/turn.c:1745-1750`), so only the support manifest keeps it from running as a plain damaging move.

## 2. Species (computed Champions stats of the sets)

| Forme | Types | Base HP/Atk/Def/SpA/SpD/Spe | Set stats HP/Atk/Def/SpA/SpD/Spe | hg | Grass Knot BP | pokedex.ts | Gender rule | Showdown abilities |
|---|---|---|---|---|---|---|---|---|
| sneasler | Fighting, Poison | 80/130/60/40/80/120 | 157/200/80/54/100/172 | 430 | 60 | 17573-17587 | 0 (either) | Pressure / Unburden / Poison Touch |
| incineroar | Fire, Dark | 95/115/90/80/90/60 | 202/135/124/90/143/80 | 830 | 80 | 13756-13769 | 0 (either) | Blaze / Intimidate |
| salamence | Dragon, Flying | 95/135/80/110/80/100 | 172/139/100/162/100/167 | 1026 | 100 | 6920-6934 | 0 (either) | Intimidate / Moxie |
| salamencemega | Dragon, Flying | 95/145/130/120/90/120 | 172/148/150/172/110/189 | 1126 | 100 | 6935-6948 | 0 (either) | Aerilate |
| indeedeef | Psychic, Normal | 70/55/65/95/105/85 | 177/75/128/115/127/94 | 280 | 60 | 16969-16982 | 2 (F only) | Own Tempo / Synchronize / Psychic Surge |
| kingambit | Dark, Steel | 100/135/120/60/85/50 | 207/205/140/72/107/70 | 1200 | 100 | 18845-18858 | 0 (either) | Defiant / Supreme Overlord / Pressure |
| basculegion | Water, Ghost | 120/112/65/80/75/78 | 197/164/85/90/95/143 | 1100 | 100 | 17538-17555 | 1 (M only) | Swift Swim / Adaptability / Mold Breaker |

Set stats come from the pin's own formula (`Battle.spreadModify`, `data/mods/champions/scripts.ts:10-40`: HP = base + points + 75, other stats base + points + 20, nature x1.1 / x0.9 truncated); Salamence-Mega uses the same points and nature. Grass Knot BP is what Farigiraf's attack would have against each forme. Gender rule codes are those of `gen_closure.py`; every set states its gender, so no gender draw happens at construction.

## 3. Moves (data/moves.ts with data/mods/champions/moves.ts overrides applied)

| Move | Users | Cat | Type | BP | Acc | Prio | Target | PP base -> Champions max | Secondary / notes | moves.ts | Override | Closure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Close Combat | Sneasler | Phys | Fighting | 120 | 100 | 0 | normal | 5 -> 8 | self: boosts {def:-1,spd:-1} | 2571-2589 |  | yes |
| Dire Claw | Sneasler | Phys | Poison | 80 | 100 | 0 | normal | 15 -> 16 | 30% onHit: sample([psn, par, slp]); flag slicing | 3629-3647 | 217-227 | no |
| Protect | Sneasler, Salamence, Kingambit | Stat | Normal | 0 | true | 4 | self | 5 -> 8 | [onPrepareHit, onHit]; condition [onStart, onTryHit] | 13961-14005 | 765-768 | yes |
| Fake Out | Sneasler, Incineroar | Phys | Normal | 40 | 100 | 3 | normal | 10 -> 12 | 100% volatileStatus: 'flinch'; [onTry, onDisableMove] | 5087-5109 | 354-361 | yes |
| Flare Blitz | Incineroar | Phys | Fire | 120 | 100 | 0 | normal | 15 -> 16 | 10% status: 'brn'; recoil 33/100; flag defrost | 5642-5659 |  | no |
| Parting Shot | Incineroar | Stat | Dark | 0 | 100 | 0 | normal | 20 -> 20 | selfSwitch; flag sound; flag bypasssub; [onHit] | 13165-13185 |  | yes |
| Darkest Lariat | Incineroar | Phys | Dark | 85 | 100 | 0 | normal | 10 -> 12 | ignoreDefensive, ignoreEvasion | 3323-3337 |  | no |
| Hyper Voice | Salamence | Spec | Normal | 90 | 100 | 0 | allAdjacentFoes | 10 -> 12 | flag sound; flag bypasssub | 9207-9219 |  | no |
| Draco Meteor | Salamence | Spec | Dragon | 130 | 90 | 0 | normal | 5 -> 8 | self: boosts {spa:-2} | 4002-4019 |  | no |
| Tailwind | Salamence | Stat | Flying | 0 | true | 0 | allySide | 15 -> 16 | condition [durationCallback, onSideStart, onModifySpe, onSideEnd] | 18875-18914 |  | yes |
| Follow Me | Indeedee-F | Stat | Normal | 0 | true | 2 | self | 20 -> 20 | [onTry]; condition [onStart, onFoeRedirectTarget] | 6039-6074 |  | no |
| Trick Room | Indeedee-F | Stat | Psychic | 0 | true | -7 | all | 5 -> 8 | condition [durationCallback, onFieldStart, onFieldRestart, onFieldEnd] | 19940-19980 |  | yes |
| Helping Hand | Indeedee-F | Stat | Normal | 0 | true | 5 | adjacentAlly | 20 -> 20 | flag bypasssub; [onTryHit]; condition [onStart, onRestart, onBasePower] | 8573-8606 |  | no |
| Psychic | Indeedee-F | Spec | Psychic | 90 | 100 | 0 | normal | 10 -> 12 | 10% boosts: {spd:-1} | 14041-14059 |  | yes |
| Kowtow Cleave | Kingambit | Phys | Dark | 85 | true | 0 | normal | 10 -> 12 | flag slicing | 9985-9996 |  | no |
| Sucker Punch | Kingambit | Phys | Dark | 70 | 100 | 1 | normal | 5 -> 8 | [onTry] | 18396-18415 |  | no |
| Iron Head | Kingambit | Phys | Steel | 80 | 100 | 0 | normal | 15 -> 16 | 20% volatileStatus: 'flinch' | 9722-9738 | 545-551 | yes |
| Last Respects | Basculegion | Phys | Ghost | 50 | 100 | 0 | normal | 10 -> 12 | [basePowerCallback] | 10091-10105 |  | no |
| Wave Crash | Basculegion | Phys | Water | 120 | 100 | 0 | normal | 10 -> 12 | recoil 33/100 | 20679-20691 |  | no |
| Aqua Jet | Basculegion | Phys | Water | 40 | 100 | 1 | normal | 20 -> 20 |  | 453-465 |  | no |
| Flip Turn | Basculegion | Phys | Water | 60 | 100 | 0 | normal | 20 -> 20 | selfSwitch | 5787-5799 |  | no |

PP: base after the Champions cap at 20 (`scripts.ts:3-9`), max = (pp / 5 + 1) * 4 (`scripts.ts:41-43`). The Dire Claw override (30 percent, `slicing`) is the only override of a new move.

## 4. Abilities and items

| Kind | Name | Holder | Base lines | Champions override | Closure |
|---|---|---|---|---|---|
| ability | Unburden | Sneasler | data/abilities.ts:5235-5257 | - | no |
| ability | Intimidate | Incineroar, Salamence | data/abilities.ts:2193-2212 | - | yes |
| ability | Aerilate | Salamence-Mega | data/abilities.ts:57-77 | - | no |
| ability | Psychic Surge | Indeedee-F | data/abilities.ts:3580-3588 | - | no |
| ability | Defiant | Kingambit | data/abilities.ts:901-921 | - | no |
| ability | Adaptability | Basculegion | data/abilities.ts:43-56 | - | no |
| item | White Herb | Sneasler | data/items.ts:7658-7712 | - | no |
| item | Sitrus Berry | Incineroar | data/items.ts:5744-5765 | - | yes |
| item | Salamencite | Salamence | data/items.ts:5506-5517 | items.ts:830-833 | no |
| item | Rocky Helmet | Indeedee-F | data/items.ts:5295-5309 | - | no |
| item | Chople Berry | Kingambit | data/items.ts:1030-1053 | - | no |
| item | Choice Scarf | Basculegion | data/items.ts:983-1005 | - | no |

## 5. The unsupported mechanics, ranked by risk of an exact reimplementation

Scale. **LOW**: a data row, a flag or constants of a mechanic the closure already has. **MEDIUM**: a new state field, a new status or a new hook point. **HIGH**: a new event class, ordering against other holders, hidden information or a change of the decision domain.

| # | Mechanic (Team C use) | Showdown implements (file:line) | Hooks and events | Random draws | Risk and why |
|---|---|---|---|---|---|
| 1 | **Follow Me**: Indeedee-F move, 97.3% | `data/moves.ts:6039-6074`: priority +2, target self, volatile `followme` (duration 1), `onTry` fails if `activePerHalf` <= 1, condition `onFoeRedirectTarget` (priority 1). Redirect site `sim/pokemon.ts:829-831` (`priorityEvent('RedirectTarget')` in `getMoveTargets`; not for spread, self or `tracksTarget` moves); handler ties by `effectOrder`, `sim/battle.ts:994-1000` | move `Try`; volatile `Start`; foe `RedirectTarget` (first defined result wins) | none; the fainted-target retarget (RANDOM_TARGET, `pokemon.ts:823-828`) runs before the redirect | **HIGH.** Rewrites the target of every single-target foe move at execution time. It must be ordered against Lightning Rod (`data/abilities.ts:2352-2362`, `onAnyRedirectTarget`, priority 0); executed X3: Follow Me wins. An `adjacentAlly` move is not redirected (`validTarget`, source reading). Changes the Raichu matchups (Lightning Rod, Electro Shot, Zap Cannon). |
| 2 | **Choice Scarf and `choicelock`**: Basculegion item, 45.8% | `data/items.ts:983-1005` (`onStart` clears the lock, `onModifyMove` adds the volatile, `onModifySpe` x1.5); `data/conditions.ts:324-363` (`onStart` stores the move id, `onBeforeMove` fails another move, `onDisableMove` disables the other slots) | `ModifyMove`, `DisableMove` (also at every turn start, `sim/battle.ts:1691-1694`), `BeforeMove`, `ModifySpe` | none | **HIGH, decision domain.** The legal moves of a slot shrink after its first move until it leaves the field or loses the item (Struggle when the locked move has no PP). The closure locks only the Electro Shot charge (`locked_move`, which also traps); a choice lock does not trap. The lock is revealed information. Speed x1.5 joins the ModifySpe chain. Executed X6: the request disables the other three moves and the choice is rejected. |
| 3 | **White Herb**: Sneasler item, 31.2% | `data/items.ts:7658-7712`: `onStart`, `onAnySwitchIn` (priority -2), `onAnyAfterMega`, `onAnyAfterMove`, `onResidual` (order 29) run one check; `onUse` resets the stages; consumed by `useItem` (`sim/pokemon.ts:1811-1849`) | `Start`, `AnySwitchIn`, `AnyAfterMega`, `AnyAfterMove`, `Residual`, `Use`, then `AfterUseItem` | none | **HIGH.** Reacts to a negative stage from any source after any move, any switch-in, any Mega and at the turn end; also restores accuracy and evasion. A foe Intimidate at the opening consumes it inside the switch-in sequence, so Unburden is active on turn 1 (executed X1: Speed 172 to 344 against Staraptor); after Close Combat's self-drops it fires right after the move (executed X2). The exact engine points of `AnyAfterMove` (also after a protected or failed move) must be matched. |
| 4 | **Sucker Punch**: Kingambit move, 96.8% | `data/moves.ts:18396-18415`: priority +1; `onTry` fails if `queue.willMove(target)` finds no queued move, the move is Status (except Me First) or the target must recharge. `sim/battle-queue.ts:324-332`; `Try` single event `sim/battle-actions.ts:590` (before type immunity and accuracy) | `Try` | none | **HIGH.** Reads the target's queued action: it needs the unexecuted action list at execution time and fails when the target already moved, switched or fainted; the failure leaks the category of the target's choice (hidden information). Interacts with Armor Tail, Psychic Terrain, Protect and Trick Room. Executed X4: fails against Nasty Plot, hits Make It Rain. |
| 5 | **Helping Hand**: Indeedee-F move, 79.5% | `data/moves.ts:8573-8606`: priority +5, target `adjacentAlly`, bypasssub; `onTryHit` fails unless the ally is `newlySwitched` or has a queued move; volatile (duration 1) with `BasePower` priority 10, x1.5 (again per restart). Called from the Champions `spreadMoveHit`, `data/mods/champions/scripts.ts:331-333`; `newlySwitched` is set in the Champions `clearVolatile` (`scripts.ts:166`) and cleared at `sim/battle.ts:1673` | move `TryHit`; volatile `Start`, `Restart`, `BasePower` | none | **HIGH.** First use of the `adjacentAlly` target class (in TARGET_CLASS, never chosen in the closure; the choice layer must offer ally targets, the repo's reference harness cannot, section 8); queue read like Sucker Punch; the x1.5 joins the BasePower chain at priority 10 (after Aerilate 23, before terrain 6, 4096-fixed-point rounding). Executed X4: it resolves before Sucker Punch and works on a partner that switched in this turn. |
| 6 | **Psychic Surge and Psychic Terrain**: Indeedee-F ability, 99.7% | `data/abilities.ts:3580-3588` (`onStart`: `field.setTerrain`); terrain `data/moves.ts:14095-14154`: 5 turns (8 with Terrain Extender); `onTryHit` priority 4 blocks every move with priority > 0.1 that does not target self, against grounded non-ally targets; `onBasePower` priority 6 x5325/4096 for Psychic moves of grounded users; end order 27/7. `sim/field.ts:130-157` (`setTerrain` fails for the same terrain; `FieldStart`; `TerrainChange` for all); `isGrounded` `sim/pokemon.ts:2148-2160` | ability `Start`; field `TryHit` (before Protect's priority 3, `data/moves.ts:13983`), `BasePower`, `FieldStart`, `TerrainChange`, `FieldResidual`, `FieldEnd` | none | **MEDIUM-HIGH.** A second terrain id; a field-level TryHit before Protect; it blocks priority moves of both sides, also the setter's own (executed X5: Aqua Jet blocked, an ally-targeted Fake Out not); Flying types (Salamence, Staraptor, Charizard) stay hittable; the later setter replaces Grassy Terrain (switch-in speed order); `TerrainChange` listeners (Grassy Seed) must see the new terrain; Psychic gets x1.3. |
| 7 | **Unburden**: Sneasler ability, 89.1% | `data/abilities.ts:5235-5257`: `onAfterUseItem` (holder only), `onTakeItem`, `onEnd`; volatile `unburden` with `onModifySpe` x2 while the holder has no item. Speed pipeline `sim/pokemon.ts:596-649`; Champions `getActionSpeed` `data/mods/champions/scripts.ts:46-54`; modifiers accumulate into one 4096-based product, `sim/battle.ts:930-932` | `AfterUseItem`, `TakeItem`, `End`, `ModifySpe` | none, but ties and action order change (SPEED_TIE, queue re-sorted after each action) | **MEDIUM-HIGH.** Item state feeds the action order: Tailwind x2, paralysis x0.5, Choice Scarf x1.5 and Unburden x2 chain into one rounding; items leave through herb, seeds and berries; the volatile stays once set. Executed X1, X2. |
| 8 | **Dire Claw (Champions override) and poison**: Sneasler move, 92.4% | `data/mods/champions/moves.ts:217-227` (30 percent instead of the 50 of `data/moves.ts:3629-3647`; adds `slicing`); `secondaries` `sim/battle-actions.ts:1336-1352`; `trySetStatus` `sim/pokemon.ts:1669`; `psn` `data/conditions.ts:123-137` (residual order 9, baseMaxhp / 8); Champions sleep `data/mods/champions/conditions.ts:11-30` | secondary `Hit`, `SetStatus`, status `Start`, residual 9 | (1) the secondary roll random(100), existing SECONDARY; (2) `sample(['psn','par','slp'])` = random(3), drawn after every successful roll even if the target cannot take a status (the harness records it as SECONDARY[0,3) in context Hit; **new site needed**); (3) for slp `sample([2,3,3])` = random(3), existing SLEEP_TURNS. Executed X9 | **MEDIUM-HIGH.** Poison is new (the generator ignores the `psn` and `tox` type keys today: Steel and Poison immunity; residual 9 sits between Leftovers 5/4 and burn 10); the generator rejects the secondary; the extra draw exists even when the status fails. |
| 9 | **Chople Berry and Rocky Helmet**: Kingambit 42%; Indeedee-F 26.5% (tie with Colbur Berry, the owner took Rocky Helmet) | Chople: `data/items.ts:1030-1053`: the defender's `onSourceModifyDamage`: if the move type matches and the type modifier is > 0, `eatItem()` then x0.5; `onEat` is empty. `eatItem` `sim/pokemon.ts:1768-1809`. Event site: Champions `modifyDamage`, `data/mods/champions/scripts.ts:296` (after burn, before the 16-bit truncation). Rocky Helmet: `data/items.ts:5295-5309`: `onDamagingHit` (order 2): if the move makes contact, `damage(source.baseMaxhp / 6, source, target)`; no Champions override | `SourceModifyDamage` (ModifyDamage), `UseItem`, `TryEatItem`, `Eat`, `EatItem`, `AfterUseItem`; `DamagingHit` | none | **MEDIUM.** The berry is consumed inside the damage calculation of each target, also when the hit does not KO; log order `-supereffective`, `-enditem [eat]`, `-enditem [weaken]`; a resist berry is one mechanism with a type. Executed X7: 102 damage with the berry, 204 without. Chople is reachable through Close Combat and Focus Blast. Rocky Helmet is a second damage source inside the hit: the attacker can faint inside its own move, and the order against recoil, drain, Life Orb and Emergency Exit must be pinned with recorded battles; the contact flag and the `DamagingHit` site exist (Tough Claws, thaw). |
| 10 | **Last Respects**: Basculegion move, 99.8% | `data/moves.ts:10091-10105` (`basePowerCallback`: 50 + 50 * `side.totalFainted`); callback site `sim/battle-actions.ts:1617-1618`; the counter is incremented in `faintMessages`, `sim/battle.ts:2554` (capped at 100), after each action's faint queue | `basePowerCallback`, then the `BasePower` chain | none | **MEDIUM.** One public per-side counter (a state change). It counts at faint processing, not at the damage, so an ally that fainted earlier in the same turn already counts. The power then goes through the chain (STAB 2.0 with Adaptability). Executed X6: 50, then 100 after one faint. |
| 11 | **Aerilate and Salamence-Mega**: Salamencite 97.6% | `data/abilities.ts:57-77` (`onModifyType` priority -1 turns Normal moves into Flying; `onBasePower` priority 23 x4915/4096); `data/items.ts:5506-5517` with the Champions override `data/mods/champions/items.ts:830-833` (obtainable); `canMegaEvo` and `formeChange`, `data/mods/champions/scripts.ts:56-121,182-194` (the Mega's ability comes from the forme; Intimidate does not run again) | `ModifyType`, `BasePower`, Mega action, `formeChange` | none | **LOW-MEDIUM.** The Mega machinery exists (four stones). New: a type-changing hook before STAB and immunity (Hyper Voice hits a Ghost only after the Mega, executed X8) and the BasePower order (23 first). |
| 12 | **Flip Turn**: Basculegion move, 46.4% (the owner's set) | `data/moves.ts:5787-5799` (`selfSwitch: true`); `sim/battle-actions.ts:1290-1296` and `1311-1312` (the switch flag is set when the move did something and the user is alive) | `runMoveEffects`, switch request | none | **MEDIUM.** Only Parting Shot pivots in the closure; a damaging pivot must work with a KO of the target, Protect and an empty bench. The PIVOT boundary and the mid-turn request (`mechanics-inventory.md` sections 2 and 4) are reusable. |
| 13 | **Flare Blitz**: Incineroar move, 91.2% | `data/moves.ts:5642-5659`: flag `defrost`, recoil 33/100, 10% burn. `frz`: `data/conditions.ts:97-111` and Champions `data/mods/champions/conditions.ts:31-56` (a frozen user may use a defrost move and is thawed in `onModifyMove`) | `BeforeMove`, `ModifyMove` | accuracy, crit, damage roll, secondary: existing sites | **LOW.** Recoil and burn exist; the generator rejects the flag `defrost`; thaw-on-use is reachable (Ice Beam freezes). |
| 14 | **Darkest Lariat**: Incineroar move, 41.9% | `data/moves.ts:3323-3337`: `ignoreDefensive` zeroes the target's Def/SpD stage in both directions (`sim/battle-actions.ts:1691-1700`); `ignoreEvasion` (`:719`, `:925`) | damage formula | existing sites | **LOW.** Ignores Stamina, Coil and similar boosts of Team A and B targets; the generator rejects both fields. |
| 15 | **Defiant**: Kingambit ability, 95.6% | `data/abilities.ts:901-921`, the same shape as Competitive (`645-665`): `onAfterEachBoost`, only from non-allies, +2 Atk | `AfterEachBoost` | none | **LOW.** A copy of Competitive with another stat. Executed X1: +2 Atk after a foe Intimidate. Self-inflicted drops (Draco Meteor, Close Combat) do not trigger it. |
| 16 | **Adaptability**: Basculegion ability, 93.9% | `data/abilities.ts:43-56` (`onModifySTAB` returns 2); STAB site `data/mods/champions/scripts.ts:233-260` | `ModifySTAB` | none | **LOW.** One constant in the damage step. |
| 17 | **Data-only moves**: Kowtow Cleave, Hyper Voice, Draco Meteor, Wave Crash, Aqua Jet | `data/moves.ts:9985-9996`, `9207-9219`, `4002-4019`, `20679-20691`, `453-465` | existing | Kowtow Cleave never misses (no ACCURACY draw); Draco Meteor's self drop draws one random(100) at `selfDrops`, `sim/battle-actions.ts:1317-1327`, as Close Combat does | **LOW.** Spread class, recoil, self drops and priority +1 exist; the generator parses all five today. |

## 6. Interactions with the closure teams (each needs a test once implemented)

- **Psychic Terrain and priority.** While it lasts (5 turns), Team A's Fake Out (Rillaboom, Raichu), Shadow Sneak (Ceruledge) and Grassy Glide fail against grounded Team C members; Mega Salamence stays hittable. Team C's own Fake Out, Aqua Jet and Sucker Punch fail against grounded foes too; Farigiraf's Armor Tail already blocks them against Team B.
- **Two terrains.** Rillaboom (Grassy Surge) and Indeedee-F (Psychic Surge) enter in speed order and the later setter wins; Trick Room reverses that order; Ceruledge's Grassy Seed reacts to the Grassy start only.
- **Intimidate chain.** Incineroar and Salamence (Team C) and Staraptor (Team A): Defiant (+2 Atk on Kingambit), White Herb then Unburden (Sneasler), Competitive (Milotic) and Contrary (Mega Staraptor) on the receiving side.
- **Redirection.** Follow Me beats Lightning Rod (executed X3); spread moves (Hyper Voice, Muddy Water, Heat Wave, Snarl) ignore both; the 0.75 spread modifier survives a protecting target.
- **Hidden information.** Sucker Punch against Protect, Trick Room, Nasty Plot, Coil, Swords Dance, Reflect; Helping Hand then Sucker Punch (+5, then +1) from Indeedee-F and Kingambit.
- **Second Trick Room.** Indeedee-F (Team C) and Farigiraf (Team B): the second use ends the room (a closure rule).
- **Poison.** Dire Claw can poison, paralyse or put to sleep; Steel targets are immune to poison (Gholdengo, Archaludon, Mega Golisopod), Raichu to paralysis; Good as Gold blocks status moves, not this secondary.
- **Recoil and weather.** Flare Blitz and Wave Crash recoil with Life Orb on the other side; rain boosts Wave Crash and Aqua Jet and halves Flare Blitz; Mega Charizard Y's sun does the reverse. Draco Meteor's self drop does not trigger Defiant or Competitive (self).
- **Chople Berry** meets Close Combat (Mega Staraptor, STAB), Focus Blast (Raichu) and Sneasler's mirror.
- **Rocky Helmet** answers every contact move into Indeedee-F, for example Fake Out and Close Combat from the closure teams: the attacker takes 1/6 of its maximum HP and can faint inside its own move.
- **Grass Knot** from Farigiraf has 60 power against Sneasler and Indeedee-F, 80 against Incineroar and 100 against the rest (hg table above).

## 7. Suggested implementation order

Principle: low-risk data first, shared machinery together, the high-blast-radius mechanics last. The owner may reorder; the dependencies are in the notes.

1. **Data only**: Kowtow Cleave, Hyper Voice, Draco Meteor, Wave Crash, Aqua Jet; Defiant (a copy of Competitive); Adaptability (STAB 2.0); the seven formes with gender rules and weights. This proves the table extension (new ids, new fingerprint) with no rule risk.
2. **Flags**: Flare Blitz (`defrost`), Darkest Lariat (`ignoreDefensive`, `ignoreEvasion`).
3. **Salamence-Mega, Salamencite, Aerilate**: reuses the Mega machinery, adds the type-change hook and the BasePower order.
4. **Last Respects and Flip Turn**: the per-side faint counter; the generic damaging pivot (the PIVOT boundary is reused).
5. **Chople Berry and Rocky Helmet**: the first item eaten inside damage (`eatItem`, two `-enditem` events) and the first item that damages the attacker (`DamagingHit` with contact).
6. **Dire Claw and poison**: new status, residual order 9, immunities, the new pick draw site.
7. **Choice Scarf**: the decision-domain change; settle legal-action generation before the speed items.
8. **White Herb and Unburden together**: the herb is the trigger in this team; item hooks at switch-in, after every move and at residual 29, and the dynamic speed chain.
9. **Sucker Punch and Helping Hand**: queue introspection and `adjacentAlly` choices; fix the reference harness for ally targets before recording traces.
10. **Psychic Surge and Psychic Terrain**: second terrain, field TryHit before Protect, replacement and seed interplay; the test matrix needs the closure teams' priority moves.
11. **Follow Me last**: it touches target resolution of every single-target move and the order against Lightning Rod.

## 8. Tooling findings

- **`tools/reference/ps_trace.js`** (an ad-hoc run, not committed): 36 random-plan battles of Team C against the two closure teams (three rotations of the team order, three seeds): 19 ran to the end with 0 UNKNOWN draw sites, 17 aborted with `Invalid target for Helping Hand` (the plan fix-up gives foe targets only; it already handles disabled and locked slots). Dire Claw's pick draw is recorded as `SECONDARY[0,3)` in context `Hit`.
- **`tools/datagen/gen_closure.py`**: the failures listed in section 1 are the explicit gate the rules ask for; the type chart keys `psn` and `tox` are in `IGNORED_TYPE_KEYS` and need a consumer for Dire Claw.
- **`src/rng/draw.h`** has no site for a three-way pick; the sleep length site exists.
- **Decision 0004** defines the closure as two teams. The owner decided on 2026-10-01 that Team C is not part of the closure: it is the expansion track, run alongside. New ids still move the context fingerprint of the data that carries them.

## 9. Cheaper variants (the items are the cheapest knob)

Not taken: the owner decided on 2026-10-01 to build the mechanics as they are. Kept as a record.

All of these were validated with `validate-team.js`.

- Choice Scarf to Life Orb on Basculegion (28.9%, in the closure) removes the choice lock and keeps the literal moves.
- White Herb to Grassy Seed on Sneasler (24.5%, in the closure) removes the herb hooks; Unburden still starts when the seed is eaten.
- Colbur Berry to Rocky Helmet (the tie) trades the berry for `DamagingHit` contact damage and is not cheaper.
