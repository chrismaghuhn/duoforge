# Tail rev 4: state audit and proposal (draft)

Status: **draft for the owner**, no code. Written by Builder E on 2026-10-03 for HauptSession. It audits the top blockers of the two MunchStats team surveys against the pinned Showdown (with the Champions mod) and says which of them need state beyond tail rev 3, which do not, and what a rev 4 would hold.

## 1. Summary

- **Most blockers need no state.** Of the 134 rows annotated here, 112 need nothing beyond tail rev 3 (4 data-only, 79 small rule, 25 handler, 4 heavy; "cost" is defined in section 6), 12 need new state, and 10 are in flight in open PRs.
- **Rev 4 is worth it for a small set.** The state rows that matter by teams are **Rage Powder, Stomping Tantrum and Roost** (525, 309 and 226 teams of 4092 in M-C; 7710, 3686 and 2322 of 25,647 in M-B), then Quick Guard, Protean, Rage Fist, Double Shock and Burn Up, Illusion, Supreme Overlord and Zero to Hero. Everything in rev 4 is one to two bytes per position, member or side.
- **Four of the known candidates are not needed at all:** Ice Face, Protosynthesis, Quark Drive and Commander have no legal species in the pool (`legal_pool.json`: no species lists the ability), so no team can carry them. Disguise and Zero to Hero are legal and small (section 4.4).
- **Recommended cut (B): +40 bytes.** Position 32 to 36 bytes, member 8 to 10, the side's own 8 bytes unchanged; tail 248 to 288 bytes, encoded state 1257 to 1297 (+3.2 percent). A cut with no growth at all (A) covers Rage Powder, Stomping Tantrum, Roost and Quick Guard. The view needs **no new struct and no new revision**: every field fits an existing reserve of the extension (decision 0018 section 9) and most already have a feature bit.
- **Teams, not rows.** With every annotated row resolved, M-C goes from 385 to 2597 passing teams of 4092 (63 percent); M-B from 299 to 12,772 of 25,647 (50 percent). The rev 4 rows add 729 M-C and 7074 M-B of those; without them the same work stops at 1868 (46 percent) and 5698 (22 percent). Section 6 has the curve per cost class.

## 2. Inputs and method

- **Blockers:** `C:\Dev\src\duoforge-data\munchstats-2026-10-03\blockers_mc.json` (Reg M-C, 4092 unique teams, 385 pass) and `blockers_mb.json` (Reg M-B, 25,647 teams, 299 pass), measured against main f57dd66 (0.33.0). They predate the G23-A, G28 and G25 work (section 7), so the numbers here treat those rows as "in flight". The top 60 rows of each file plus rows the scan surfaced (anything with 30 or more M-C teams or 400 or more M-B teams that needs a rule or state) are annotated: 134 rows. Rows not annotated stay unresolved in every "teams that pass" figure, so those figures are lower bounds.
- **Pin:** `C:\Dev\src\pokemon-showdown` at b2cb775b0 (2026-09-30) with `data/mods/champions`. Every row below carries its `file:line` range; a Champions override is marked "mod". Line numbers are of that checkout.
- **Engine state:** tail rev 3 as in PR #159 (branch `chris/expansion-g20-protect-variants`, schema 0x0303): `src/state/battle_internal.h` (`dfi_tail_pos`, `dfi_tail_side`, `dfi_pool_tail`), `src/codec/state_codec.h` (the encoded layout), `docs/decisions/0015` section 7. The unmodelled reason of each row is the generator's own (`dfi_pool_move_unmodeled`, `_item_`, `_ability_` of `src/data/pool_tables.c` on the G28 branch).
- **M11 stops:** `C:\Dev\datasets\m11-replay-2026-10-02\counters.json` (the full run of PR #120: 32,983 games processed, 21,818 perspectives kept, 44,148 stopped). Only aggregate counts are quoted here (decision 0019 keeps the data local).
- **Teams that pass** is computed from the `failing` lists of the two files: a team passes when every blocker it has is in the resolved set. A Mega Stone counts as resolved when the ability of its Mega forme is marked or resolved; its base-forme ability is a separate blocker of the team.
- Nothing in this document was built, run or measured except those counts. Any size or cost claim for the engine (state copy cost, `dfi_clone`) is **not measured**.

## 3. What tail rev 3 holds

Schema 0x0303, 248 bytes under the POOL kinds: a field block of 8 bytes, then per side 120 bytes.

| Scope | Bytes | Used | Reserved | Content |
|---|---:|---:|---:|---|
| field | 8 | 1 | 7 | `gravity_turns` |
| side (x2) | 120 | 6 + 2 reserved + positions + members | 2 | `wide_guard`, `aurora_veil_turns`, `toxic_spikes`, `stealth_rock`, `spikes`, `sticky_web` |
| position (x2 per side, x4) | 32 | 27 | 5 | `last_move`, `encore_slot`, `encore_turns`, `throat_chop_turns`, `heal_block_turns`, `perish`, `taunt_turns`, `disable_slot`, `disable_turns`, `imprison`, `must_recharge`, `trap_turns`, `trap_source`, `trap_band`, `leech_seed_source`, `yawn_turns`, `focus_energy`, `stockpile`, `stockpile_def`, `stockpile_spd`, `charge`, `glaive_rush`, `substitute_hp` (u16), `trap_move` (u16), `protect_kind` (rev 3) |
| member (x6 per side, x12) | 8 | 7 | 1 | `ability_now` (u16), `forme_now` (u16), `soak_type`, `item_now`, `toxic_stage` |

43 of the 248 bytes are reserved (7 + 2 x (2 + 2 x 5 + 6 x 1)). The base state's per-position block (`dfi_active_slot`) is separate: `flags` is a full byte (`FLINCH`, `PROTECT`, `FLASH_FIRE`, `FOLLOW_ME`, `HELPING_HAND`, `UNBURDEN`, `CHOICE_LOCK`, `NEWLY_SWITCHED`: all eight bits used, `battle_internal.h:64-72`), plus `stall_level`, `stall_turns`, `confusion_turns`, `charge_turns`, `locked_move`, `locked_target`, `move_actions`, `switch_flag`. A new single-turn flag therefore cannot go into `flags`; this is why Rage Powder and Roost need rev 4.

## 4. Rev 4 proposal

### 4.1 Fields

All fields are plain bytes, no pointer, no padding, zero when unused, like rev 2 and 3. "Set" and "clear" cite the pin.

| Field | Scope | Size | Range | Set where | Clears where | Needed by |
|---|---|---:|---|---|---|---|
| `move_result` | position | 1 | bits 0-1 this turn, bits 2-3 last turn; each 0 undefined, 1 true, 2 false, 3 null | `BeforeMove` stops (flinch, sleep, paralysis, freeze, `cant` of Disable, Taunt, Imprison, Heal Block) and no PP: `moveThisTurnResult = false` or the `BeforeMove` value (`sim/battle-actions.ts:255-290`); the move's own result in `useMove` (`:371-374`, `:507`, `:616`) | shifted at every turn end, last := this, this := undefined (`sim/battle.ts:1674-1675`, in `endTurn`); undefined on switch-out and faint (`sim/pokemon.ts:1545-1546`; Champions mod `scripts.ts:160-161`) | Stomping Tantrum (`moves.ts:18049-18068`, `=== false`), Temper Flare (`:19185`), Metronome item (`items.ts:4014`, truthy), Truant (`abilities.ts:5184`, this turn `!== undefined`) |
| `single_turn` | position | 1 | bit 0 `RAGE_POWDER`, bit 1 `ROOST`, bits 2-7 free | Rage Powder, Roost (volatile with `duration: 1`, `moves.ts:14598-14632`, `:15428-15463`) | residual of the same turn; switch-out; faint | Rage Powder, Roost; room for Endure and the other one-turn volatiles the replay stops show |
| `hits_taken` | position | 1 | 0 to 6, saturating (power 50 + 50 x n is capped at 350) | each damage number taken from a move (`sim/battle-actions.ts:994`; `+= hit - 1` or 1 for a smart target) | switch-out and faint: the Champions mod resets it in `clearVolatile` (`scripts.ts:122,168`); the base sim keeps it | Rage Fist (`moves.ts:14580-14592`) |
| `ability_state` | position | 1 | 0 to 6, meaning by the position's current ability: Supreme Overlord fallen allies 0-5; Protean "already used" 0/1; Illusion roster index + 1 of the impersonated member | switch-in (Supreme Overlord `onStart`, `abilities.ts:4730-4754`: `min(totalFainted, 5)`, frozen); the first matching move (Protean `:3497-3512`); switch-in (Illusion, `abilities.ts:2055`) | switch-out, faint, any ability change (`ability_now`) | Supreme Overlord, Protean, Illusion |
| `lock_turns` | position | 1 | 0 to 3 | Outrage, Thrash, Petal Dance: `lockedmove` volatile, `trueDuration = random(2, 4)` (`conditions.ts:253-286`); the move itself is `locked_move` of the base state | counts down in the residual; removed when it reaches 1 after the move, then confusion; removed at sleep; switch-out; faint | Outrage (8 M-C, 137 M-B teams), Thrash, Petal Dance |
| `quick_guard` | side | 1 | 0/1 | Quick Guard (`moves.ts:14489-14531`, priority +3, fails if the user is last to act) | residual of the same turn | Quick Guard; the view already has `guard_flags` bit `QUICK_GUARD` |
| `type2` | member | 1 | 0 none, 1-18 type + 1, 255 typeless | Burn Up, Double Shock (`moves.ts:3945-3969`, mod `256-259`): the Fire or Electric type is removed; `soak_type` stays slot 1 | switch-out, faint, Mega Evolution (like `soak_type`) | Double Shock, Burn Up |
| `flags` | member | 1 | bit 0 `HERO_SHOWN`, bits 1-7 free | Palafin's `-activate ability: Zero to Hero` is shown once, at the first switch-in as Hero (`abilities.ts:5625-5645`, `heroMessageDisplayed`) | never (for the battle) | Zero to Hero (the event line only; the forme is `forme_now`) |

Not proposed for rev 4, kept for the owner:

- **`volatile_order` (u16 per position)**, the fix kept on file in decision 0015 step 5o (#154): the rank of each volatile class with a residual handler, as added. Four classes today (counters, Heal Block, Throat Chop, Encore) make 24 orders; once Taunt, Perish, Disable and Yawn are modelled the list has 8 classes and 40,320 orders, so **one byte is not enough, two are**. The refusal rate measured in #154 is about 3.1 percent of the Encore mirror pairing and 0 elsewhere; it only pays if training uses Encore mirrors. Cost: +2 bytes per position (cut C below).
- **Revival Blessing** (92 M-C teams, 47 M-B): needs a fainted member chosen by a request, which is a new request kind and so a public API change, not only state (section 5).

### 4.2 Sizes and reserves

| Cut | Contains | Position | Member | Side | Tail | Encoded state | Reserved after |
|---|---|---:|---:|---:|---:|---:|---:|
| rev 3 (today) | - | 32 | 8 | 120 | 248 | 1257 | 43 |
| **A**, no growth | `move_result`, `single_turn`, `quick_guard` | 32 (2 of 5 reserve used) | 8 | 120 | 248 | 1257 | 33 |
| **B**, recommended | A + `hits_taken`, `ability_state`, `lock_turns`, `type2`, member `flags` | 36 | 10 | 8 + 2 x 36 + 6 x 10 = 140 | 288 | 1297 | 37 |
| **C** | B + `volatile_order` (u16) | 40 | 10 | 148 | 304 | 1313 | 45 |

Arithmetic: rev 3 side = 8 + 2 x 32 + 6 x 8 = 120; tail = 8 + 2 x side. Cut B side = 8 + 2 x 36 + 6 x 10 = 140, tail 8 + 280 = 288 (+40). Cut C side = 8 + 2 x 40 + 6 x 10 = 148, tail 304 (+56). Cut A needs only the schema id (0x0403), the decoder and the mechanic code: no layout growth. In B, the position keeps 4 reserved bytes, the member 1, the side 1, the field 7.

Costs a growth brings (not measured): the state is copied by `dfi_clone` and hashed; +40 bytes is +3.2 percent of the encoded state (+4.5 percent for C). Per AGENTS.md, a performance claim needs a measurement; the clone benchmark would have to run before the owner accepts C. No heap allocation is added.

What a revision bump costs: the schema id (0x0403), `src/codec/state_codec.[ch]`, `dfi_tail_pos` and friends, the invariants (`src/state/invariants.c`), `tools/state_model/state_v3_model.py` and the pins that hash it, the converter's state table (`tools/reference/trace_to_c.py`), the view reading the tail (`src/state/observation.c`), tests, and the refusal of rev 3 by the decoder (as rev 1 and 2 are refused since rev 3). Rev 3 (#159) has not merged yet; if rev 4 follows soon, **#159 and rev 4 could ship as one revision**, saving one bump.

### 4.3 View impact (decision 0018)

No new struct, no new revision of `duoforge_observation_ext`: its growth rule (section 9) appends into reserves and a new field comes with a new `DUOFORGE_VIEWEXT_FEATURE_*` bit (bits 40 to 63 are free), a minor library version.

| Field | View | Needs |
|---|---|---|
| `single_turn` Rage Powder | `volatiles` bit 17 `RAGE_POWDER`, feature 39: exist | nothing new (PIVOT boundary only, as the guards) |
| `quick_guard` | `guard_flags` bit `QUICK_GUARD`, feature 38: exist | nothing new |
| `single_turn` Roost | none | optional: `volatiles` bit 20 `ROOST` (bits 20-31 reserved) and one feature bit; public (`-singleturn` line), PIVOT-only. The replay run stops on it 368 times |
| `move_result` | none | one appended byte `move_failed_last_turn` in the position reserve (4 bytes) plus a feature bit: the failure shows in public lines (`-fail`, `-miss`, `cant`) and decides a power doubling, so a learner would want it |
| `type2` | `type_now[2]`, `TYPE_CHANGED`: exist | nothing new (typeless would need a value, say 19 = "???") |
| Zero to Hero, Disguise, Stance Change | `forme` of the member ext, `FORME_CHANGE` (feature 19): exist | nothing new |
| `ability_state` Supreme Overlord | none | optional (the `-start fallenN` line is public); not needed to choose an action |
| `ability_state` Illusion | `ILLUSION_UP` bit 19 exists | **a decision of its own**: the foe's view of the position must show the impersonated member (species, name, HP), not the real one, until the disguise breaks; today the view shows the truth |
| `hits_taken`, `lock_turns`, `volatile_order`, `flags` | none | not exposed (derived from public lines or engine-internal) |

The state is read only through `dfi_battle`, the view never reads hidden opponent state; every field above is public information of the game's own protocol, so no own-side-only field is added.

### 4.4 The known candidates

| Candidate | Verdict | Evidence |
|---|---|---|
| **Stomping Tantrum** (309 / 3686) | needs state: `move_result` | tri-state per Pokemon; the doubling reads only `=== false`, other consumers read `true` or `!== undefined` (table above). The "null" value (no failure, no success: no choice to make) must not count as a failure |
| **Volatile insertion order** (#154) | one u16 per position, optional | see 4.1; a byte is enough only for four classes |
| **lockedmove** (Outrage, Thrash, Petal Dance) | needs state: `lock_turns`; low value | `conditions.ts:253-286`; 8 + 1 M-C teams, 137 + 3 + 6 M-B; the move and target are `locked_move`/`locked_target` of the base state (Choice and Electro Shot already use them), only the 2-or-3 turn counter and the confusion at the end are new. A random draw `random(2, 4)` is a new draw site (public enum) |
| **Disguise** (Mimikyu; 27 / 278) | **no new state**: `forme_now` (permanent Busted forme) | `abilities.ts:970-1010`: `effectState.busted` lives between `onDamage` and `onUpdate` of one hit; the bust costs 1/8 HP, a hit on a Disguise holder is 0 damage, no crit, neutral effectiveness. Needs a handler. Mimikyu-Busted exists as a pool forme |
| **Ice Face** | **not in the pool** | no legal species lists `iceface` (`legal_pool.json`); Eiscue is not legal |
| **Protosynthesis, Quark Drive** | **not in the pool** | no legal species lists either ability; `boosterenergy` has no team either |
| **Commander** | **not in the pool** | no legal species (Tatsugiri/Dondozo are not legal); the Champions Eject Button mod mentions `commanding`/`commanded`, which cannot occur |
| Stance Change (Aegislash; 35 / 303), Zero to Hero (14 / 180), Hunger Switch (3 / 47) | `forme_now` exists; Zero to Hero needs the message bit | `abilities.ts:4523-4535`, `:5625-5645` |
| Illusion (Zoroark; 44 / 340) | needs `ability_state` and a view decision | skipped by the replay data today (`skip:illusion`, 286 games) |

## 5. Blockers that need rev 4 (the S4 rows)

Teams are M-C then M-B (all teams carrying the blocker, not only those blocked by it alone).

| # | Row | M-C teams | M-B teams | Cost | Pin | What it needs |
|---|---|---:|---:|---|---|---|
| 1 | move `ragepowder` | 525 | 7710 | H | `moves.ts:14598-14632` | redirect of single-target foe moves for the turn; powder-immune sources (Grass type, Overcoat) are not drawn; `onTry` fails it with one active Pokemon per half |
| 2 | move `stompingtantrum` | 309 | 3686 | S | `moves.ts:18049-18068` | `basePowerCallback` doubles on `moveLastTurnResult === false` |
| 3 | move `roost` | 226 | 2322 | S | `moves.ts:15428-15463` | heal 1/2 (the heal column exists) and the Flying type is off until the end of the turn |
| 4 | move `doubleshock` | 96 | 82 | S | `moves.ts:3945-3969` (mod `256-259`) | user must be Electric; afterwards it loses the Electric type (second type slot or typeless): the tail has one `soak_type` per member |
| 5 | move `revivalblessing` | 92 | 47 | HH | `moves.ts:15110-15136` | a fainted member is picked by a request (a new request kind, public API) and revived at 1/2 HP; a slot condition until it is answered |
| 6 | move `quickguard` | 79 | 1220 | H | `moves.ts:14489-14531` | side condition for the turn; blocks priority moves at the guarded side; user's stall counter; only Wide Guard has a tail byte |
| 7 | ability `protean` | 54 | 614 | S | `abilities.ts:3497-3512` | once per switch-in the user takes the type of its move (a pure type: `soak_type`); the "used" bit is ability-scoped state (`effectState.protean`) |
| 8 | ability `illusion` | 44 | 340 | HH | `abilities.ts:2055-2095` | disguise as the last healthy bench member until the first damaging hit (`onDamagingHit`, `onFaint`, `onEnd`); the view of the foe must show the other member: a hidden-information change of decision 0007; 0018 has the bit `ILLUSION_UP` |
| 9 | move `ragefist` | 36 | 573 | S | `moves.ts:14583-14597` (mod `793-796`) | `timesAttacked` of the Pokemon; the Champions mod resets it on switch-out |
| 10 | ability `zerotohero` | 14 | 180 | H | `abilities.ts:5625-5644` | Palafin: the Hero forme at switch-out (`forme_now`, permanent); the `-activate` line shows once at the next switch-in (`heroMessageDisplayed`: a bit per member) |
| 11 | ability `supremeoverlord` | 10 | 197 | S | `abilities.ts:4730-4754` | `effectState.fallen` = fainted allies at switch-in, at most 5, frozen until switch-out; x1.1 per fallen member (`4096, 4506 ... 6144`) |
| 12 | move `burnup` | 8 | 51 | S | `moves.ts:2092-2117` (mod `109-112`) | same mechanic with Fire; 8 teams in M-C, 51 in M-B |

Not state, but a larger decision: **Revival Blessing** (92 M-C teams) needs a request for the member to revive. The replay run shows 135 stops on `move Revival Blessing`. It is listed with the S4 rows because no byte can model it without a new boundary.

## 6. Batchable now: no state beyond rev 3

Cost classes: **D** data-only (the row is already modelled by the generator; mark it and record a battle), **S** small rule (a few lines in an existing path, perhaps one generator column or flag), **H** handler (a named handler with its own events, draws or request changes), **HH** heavy (new machinery: a nested move, a hit loop with a hidden-information view, a new request). "S0" in the pin column means state that rev 2 or 3 already holds. Ranked by M-C teams, then M-B teams.

| # | Row | M-C teams | M-B teams | Cost | Pin | What it needs |
|---|---|---:|---:|---|---|---|
| 1 | ability `flamebody` | 389 | 396 | S | `abilities.ts:1316-1328` | `onDamagingHit`: 30 percent burn on contact; a new draw site (public enum), like Poison Touch |
| 2 | ability `cursedbody` | 376 | 2315 | H | `abilities.ts:784-797` | `onDamagingHit`: 30 percent Disable of the move used (Disable fields exist; a draw site); needs the Disable rules |
| 3 | ability `innerfocus` | 287 | 1168 | S | `abilities.ts:2153-2167` | flinch immunity and Intimidate immunity (`onTryBoost`, the `-fail` line the replay tracker already meets) |
| 4 | ability `sandrush` | 271 | 1183 | S | `abilities.ts:3974-3987` | Speed x2 in sand and sand-damage immunity |
| 5 | move `psychicfangs` | 270 | 2308 | S | `moves.ts:14060-14078` | `onTryHit` removes Reflect, Light Screen and Aurora Veil before the hit (the side fields exist) |
| 6 | move `eruption` | 264 | 1890 | S | `moves.ts:4888-4905` | power from the user's HP, one `basePowerCallback` shared with Water Spout |
| 7 | move `solarbeam` | 261 | 5761 | H | `moves.ts:17224-17259` | two-turn charge (base `charge_turns`, `locked_move`) skipped in sun; power halved in rain, sand and snow; Electro Shot is the precedent for the charge |
| 8 | ability `clearbody` | 249 | 1998 | S | `abilities.ts:523-542` | blocks stat drops by others (`onTryBoost`), with the `-fail` line |
| 9 | move `matchagotcha` | 225 | 6412 | D | `moves.ts:11027-11044` | row is already modelled (drain 1/2, burn 20 percent, thaws the target); Scald is the precedent |
| 10 | ability `hospitality` | 221 | 6471 | S | `abilities.ts:1874-1885` | heals the adjacent ally 1/4 at switch-in, after the other entry abilities (priority -2) |
| 11 | move `sleeppowder` | 203 | 2133 | S | `moves.ts:16851-16865` | row modelled; needs the powder immunity (Grass type, Overcoat) the engine does not read yet; Hypnosis is the precedent for sleep |
| 12 | move `perishsong` | 188 | 945 | H | `moves.ts:13233-13277` | perish counter exists (rev 2, `perish`, max 4); `onHitField` gives every active Pokemon the volatile unless Soundproof stops it (TryHit) or it has it, and prints `-fieldactivate`; counts 3, 2, 1 in the residual (order 24), `perish0` and the faint when the duration ends |
| 13 | move `imprison` | 184 | 694 | H | `moves.ts:9489-9523` | `imprison` flag exists; the request mask must drop the moves both know |
| 14 | ability `levitate` | 183 | 3022 | S | `abilities.ts:2311-2317` | grounded test (Ground immunity, terrains, Spikes, Toxic Spikes, Sticky Web): the engine reads Flying alone at every site; Levitate is read by id in `moves.ts` and `pokemon.ts`; the Mega abilities of Delphox and Garchomp Z are Levitate |
| 15 | move `taunt` | 179 | 2174 | H | `moves.ts:18974-19016` | `taunt_turns` exists (3, 4 when the target had not moved); request mask and `cant` line |
| 16 | move `trick` | 178 | 422 | H | `moves.ts:19865-19911` | `item_now` exists for both members; Sticky Hold, Mega Stones and choice locks interact |
| 17 | item `ejectbutton` | 176 | 59 | S | `items.ts:1680-1704` (mod `266-281`) | Champions mod `onAfterMoveSecondary`: the holder switches after a damaging hit unless a switch is already pending; a `switch_flag` value, not a byte |
| 18 | ability `liquidvoice` | 172 | 689 | S | `abilities.ts:2416-2427` | sound moves become Water (the type-change family, no 4915 boost) |
| 19 | move `gigadrain` | 171 | 2479 | D | `moves.ts:6559-6572` | row modelled (drain 1/2); Drain Punch is the precedent |
| 20 | ability `toxicdebris` | 164 | 1017 | H | `abilities.ts:5104-5117` | `onDamagingHit` (physical): Toxic Spikes on the attacker's side (`toxic_spikes` exists); the layers act at switch-in, which needs Toxic and poison |
| 21 | move `lifedew` | 163 | 3291 | S | `moves.ts:10286-10298` | target class `allies` (14) and a 1/4 heal (the heal column exists) |
| 22 | ability `unnerve` | 160 | 3090 | S | `abilities.ts:5258-5275` | foes cannot eat berries while the holder is on the field; one `-ability` line at switch-in; the once-per-switch-in flag is the activation (derived) |
| 23 | move `bodypress` | 158 | 1361 | S | `moves.ts:1572-1584` | `overrideOffensiveStat` (Defense for the attack); one branch with Foul Play and Psyshock |
| 24 | move `dualwingbeat` | 157 | 3585 | H | `moves.ts:4328-4341` | multihit 2: a hit loop with one crit and damage roll per hit, secondary effects and Focus Sash/Sturdy interplay |
| 25 | ability `chlorophyll` | 147 | 3106 | S | `abilities.ts:512-522` | Speed x2 in sun |
| 26 | ability `speedboost` | 135 | 1177 | S | `abilities.ts:4453-4465` | +1 Speed each residual, not on the switch-in turn (`activeTurns` = the `NEWLY_SWITCHED` flag of the state); residual order 28, sub-order 2 in the residual list of #154 |
| 27 | move `raindance` | 134 | 1467 | S | `moves.ts:14679-14693` | weather move; Sandstorm and Snowscape are the precedent (5 turns; Damp Rock is a separate unmarked item) |
| 28 | move `playrough` | 127 | 2223 | D | `moves.ts:13420-13438` | row modelled (Attack drop 10 percent) |
| 29 | move `clangingscales` | 114 | 580 | S | `moves.ts:2480-2497` | `selfBoost`: Defense -1 for the user after the hit |
| 30 | ability `soundproof` | 114 | 455 | S | `abilities.ts:4436-4452` | sound-flag moves do nothing; `onAllyTryHitSide` for Perish Song |
| 31 | move `tripleaxel` | 113 | 1132 | H | `moves.ts:20005-20023` | multihit 3 with an accuracy check per hit and rising power; the loop of Dual Wingbeat plus `multiaccuracy` |
| 32 | move `steelroller` | 113 | 44 | S | `moves.ts:17893-17913` | fails without a terrain, removes it (`-fieldend`), damage; the terrain fields exist |
| 33 | move `energyball` | 106 | 1472 | D | `moves.ts:4840-4858` | row modelled (Special Defense drop 10 percent) |
| 34 | move `yawn` | 106 | 1070 | H | `moves.ts:21131-21162` | `yawn_turns` exists; sleep at the end of the next turn; immunity checks |
| 35 | ability `magicbounce` | 98 | 302 | HH | `abilities.ts:2437-2464` | reflects status moves by running them again from the holder: nested move execution |
| 36 | move `voltswitch` | 96 | 1322 | S | `moves.ts:20432-20445` | U-turn pattern: a new `switch_flag` value (a value, not a byte); Electric immunity abilities interplay |
| 37 | ability `compoundeyes` | 95 | 614 | S | `abilities.ts:666-677` | accuracy x1.3 (the accuracy chain) |
| 38 | ability `ironfist` | 95 | 230 | S | `abilities.ts:2236-2248` | x1.2 for punch-flag moves (the flag column must exist) |
| 39 | move `sunnyday` | 93 | 1191 | S | `moves.ts:18416-18430` | as Rain Dance |
| 40 | ability `mirrorarmor` | 92 | 566 | H | `abilities.ts:2657-2679` | reflects stat drops to the source; read by id in `moves.ts` |
| 41 | move `waterspout` | 91 | 1189 | S | `moves.ts:20661-20678` | same callback as Eruption |
| 42 | item `widelens` | 89 | 1239 | S | `items.ts:7713-7727` | accuracy x1.1 |
| 43 | ability `sharpness` | 89 | 829 | S | `abilities.ts:4174-4186` | x1.5 for slicing-flag moves (the flag column must exist) |
| 44 | ability `solidrock` | 88 | 376 | S | `abilities.ts:4414-4425` | x0.75 against super effective hits (ModifyDamage chain) |
| 45 | ability `technician` | 87 | 858 | S | `abilities.ts:4916-4930` | x1.5 for power 60 or less (the final base power) |
| 46 | move `twinbeam` | 84 | 1384 | H | `moves.ts:20121-20134` | multihit 2, same loop as Dual Wingbeat |
| 47 | move `clangoroussoul` | 84 | 320 | S | `moves.ts:2498-2526` (mod `121-124`) | costs 1/3 HP, +1 to five stats |
| 48 | ability `multiscale` | 81 | 875 | S | `abilities.ts:2760-2771` | x0.5 at full HP (ModifyDamage chain) |
| 49 | move `freezedry` | 80 | 1412 | S | `moves.ts:6158-6177` (mod `415-418`) | `onEffectiveness`: Water takes super effective damage; 10 percent freeze |
| 50 | move `foulplay` | 75 | 1235 | S | `moves.ts:6144-6157` | `overrideOffensivePokemon` (the target's Attack and stages) |
| 51 | ability `galewings` | 73 | 1118 | S | `abilities.ts:1588-1596` | +1 priority for Flying moves at full HP (Prankster is the precedent) |
| 52 | ability `raindish` | 73 | 940 | S | `abilities.ts:3759-3770` | 1/16 heal in rain (the residual list) |
| 53 | ability `infiltrator` | 73 | 204 | S | `abilities.ts:2131-2139` | ignores the screens and Substitute; read by id in `conditions.ts` |
| 54 | ability `synchronize` | 70 | 115 | S | `abilities.ts:4857-4871` | passes a burn, poison or paralysis back to the source |
| 55 | move `sacredsword` | 68 | 655 | S | `moves.ts:15560-15574` | ignores the target's Defense and Evasion stages |
| 56 | ability `scrappy` | 67 | 804 | S | `abilities.ts:4079-4098` | Normal and Fighting hit Ghost; Intimidate immunity |
| 57 | move `substitute` | 58 | 501 | HH | `moves.ts:18304-18380` | `substitute_hp` exists (rev 2); damage redirection, status/boost immunity, sound and `bypasssub` moves, break line |
| 58 | ability `regenerator` | 56 | 1109 | S | `abilities.ts:3833-3841` (mod `63-70`) | Champions mod: heals 1/3 of the maximum HP at switch-out, silently (`mods/champions/abilities.ts:63-70`); a switch-out hook |
| 59 | ability `damp` | 56 | 918 | S | `abilities.ts:811-828` | blocks Explosion-class moves; `onAnyDamage` for Aftermath |
| 60 | move `poltergeist` | 56 | 497 | S | `moves.ts:13595-13612` | fails without a target item (`item_now`); `-activate` with the item |
| 61 | ability `hypercutter` | 54 | 972 | S | `abilities.ts:1940-1954` | Attack drops by others blocked (`onTryBoost`) |
| 62 | move `phantomforce` | 53 | 483 | HH | `moves.ts:13307-13335` | two-turn semi-invulnerable move; "charging" is `charge_turns` plus `locked_move` (derivable); invulnerability in every hit check; breaks Protect |
| 63 | move `psyshock` | 52 | 1323 | S | `moves.ts:14264-14277` | `overrideDefensiveStat` (Defense for a special hit) |
| 64 | ability `solarpower` | 51 | 1063 | S | `abilities.ts:4396-4413` | Special Attack x1.5 in sun and 1/8 HP loss per turn in sun (the residual list) |
| 65 | ability `friendguard` | 51 | 1056 | S | `abilities.ts:1533-1544` | `onAnyModifyDamage`: x0.75 for the holder's allies |
| 66 | move `disable` | 51 | 778 | H | `moves.ts:3648-3716` (mod `228-239`) | `disable_slot`/`disable_turns` exist; request mask; Cursed Body shares it |
| 67 | move `toxic` | 50 | 1022 | H | `moves.ts:19733-19748` | `toxic_stage` exists (rev 2) but no state may hold status 6 yet (invariants: the status bound); the view enum `AILMENT_TOX` exists |
| 68 | move `brickbreak` | 49 | 695 | S | `moves.ts:1822-1840` | removes the screens of the target side before the hit (like Psychic Fangs) |
| 69 | ability `justified` | 49 | 62 | S | `abilities.ts:2249-2259` | +1 Attack when hit by a Dark move |
| 70 | ability `pressure` | 48 | 297 | S | `abilities.ts:3437-3449` | foes spend 2 PP (PP is in the base state) |
| 71 | move `powertrip` | 47 | 13 | S | `moves.ts:13851-13870` | power from the user's positive stages |
| 72 | move `haze` | 46 | 395 | S | `moves.ts:8156-8175` | clears every stage on the field |
| 73 | move `roar` | 43 | 602 | H | `moves.ts:15157-15171` | forced switch with a random draw and a switch-in request |
| 74 | move `superfang` | 42 | 736 | S | `moves.ts:18461-18476` | `damageCallback`: half of the target's current HP |
| 75 | move `batonpass` | 42 | 153 | HH | `moves.ts:1092-1118` | copies stages and volatiles to the replacement (the position block and the tail fields); a new `switch_flag` value |
| 76 | move `icefang` | 41 | 1241 | S | `moves.ts:9347-9368` | two secondaries (flinch 10 percent, freeze 10 percent): a second secondary slot in the row |
| 77 | ability `queenlymajesty` | 41 | 607 | S | `abilities.ts:3716-3734` | priority moves against the holder and its allies fail (`onFoeTryMove`) |
| 78 | ability `snowcloak` | 40 | 401 | S | `abilities.ts:4370-4386` | evasion in snow, hail immunity |
| 79 | ability `limber` | 39 | 177 | S | `abilities.ts:2368-2386` | paralysis immunity |
| 80 | move `psychup` | 39 | 125 | S | `moves.ts:14211-14243` | copies the target's stages |
| 81 | move `populationbomb` | 38 | 652 | H | `moves.ts:13613-13626` | multihit up to 10 with a draw per hit; same loop |
| 82 | ability `moody` | 37 | 595 | S | `abilities.ts:2701-2734` | residual: +2 in a random stat, -1 in another: two draws |
| 83 | move `infestation` | 36 | 925 | H | `moves.ts:9595-9608` | partial trap fields exist (rev 2); damage 1/8 (1/6 with Binding Band), trap checks in the request |
| 84 | move `banefulbunker` | 36 | 876 | S | `moves.ts:985-1037` (mod `43-46`) | the `protect_kind` byte of rev 3 has room for value 2; poison on contact; follows Spiky Shield (#159) |
| 85 | ability `static` | 36 | 238 | S | `abilities.ts:4536-4548` | 30 percent paralysis on contact; a draw site |
| 86 | ability `moxie` | 36 | 159 | S | `abilities.ts:2749-2759` | +1 Attack after a knock-out (`onSourceAfterFaint`) |
| 87 | ability `punkrock` | 36 | 22 | S | `abilities.ts:3589-3607` | sound moves x1.3; sound damage taken halved |
| 88 | ability `swiftswim` | 35 | 600 | S | `abilities.ts:4808-4818` | Speed x2 in rain |
| 89 | ability `stancechange` | 35 | 303 | H | `abilities.ts:4523-4535` | `forme_now` exists (rev 2); Aegislash switches formes by the move used and is Shield again on switch-out; King's Shield is a Protect variant |
| 90 | item `mentalherb` | 34 | 882 | H | `items.ts:3889-3926` | cures Taunt, Encore, Disable, Heal Block, Torment, attraction; useful only after those volatiles are modelled; read by id in the mod's `moves.ts` |
| 91 | ability `voltabsorb` | 34 | 92 | S | `abilities.ts:5340-5353` | Electric immunity with a heal; Lightning Rod is the precedent |
| 92 | move `stormthrow` | 34 | 55 | S | `moves.ts:18130-18144` (mod `969-972`) | `willCrit` |
| 93 | move `charm` | 33 | 1160 | S | `moves.ts:2339-2355` | primary boost on the target (a boost role "foe"); Fake Tears is the same |
| 94 | ability `cloudnine` | 33 | 387 | H | `abilities.ts:543-562` | suppresses every weather effect while on the field: every weather read must ask |
| 95 | ability `telepathy` | 33 | 251 | S | `abilities.ts:4931-4942` | ally attacks miss the holder |
| 96 | item `scopelens` | 33 | 204 | S | `items.ts:5554-5565` | critical-hit ratio +1 (`onModifyCritRatio`) |
| 97 | ability `sturdy` | 32 | 382 | S | `abilities.ts:4673-4691` | survives a one-hit KO from full HP at 1 HP; Focus Sash is the precedent |
| 98 | move `icespinner` | 32 | 159 | S | `moves.ts:9417-9436` | removes the terrain after the hit (`-fieldend`) |
| 99 | move `faketears` | 31 | 520 | S | `moves.ts:5110-5126` | as Charm |
| 100 | move `flowertrick` | 31 | 459 | S | `moves.ts:5881-5893` | `willCrit` (always a critical hit, no roll) |
| 101 | ability `moldbreaker` | 31 | 362 | H | `abilities.ts:2689-2700` | ignores the `breakable` abilities of the target: every ability read needs a source |
| 102 | ability `disguise` | 27 | 278 | H | `abilities.ts:970-1016` | Mimikyu: the first damaging hit does no damage and "busts" the Disguise (`effectState.busted`, between `onDamage` and `onUpdate` of one hit); the forme becomes Mimikyu-Busted (`forme_now`, permanent) and the Pokemon takes 1/8 HP; crits are cancelled and effectiveness is neutral for that hit |
| 103 | ability `thickfat` | 26 | 287 | S | `abilities.ts:5014-5033` | Mega Venusaur: Fire and Ice damage halved |
| 104 | ability `hugepower` | 17 | 255 | S | `abilities.ts:1886-1895` | Mega Mawile: Attack x2 |
| 105 | ability `sheerforce` | 15 | 211 | S | `abilities.ts:4202-4221` | Mega Camerupt: x1.3 for moves with secondaries, which then lose them |
| 106 | ability `surgesurfer` | 13 | 21 | S | `abilities.ts:4755-4765` | Speed x2 in Electric Terrain (needs G25) |
| 107 | ability `shadowtag` | 11 | 74 | H | `abilities.ts:4156-4173` | Mega Gengar: adjacent foes cannot switch (`onFoeTrapPokemon`, `onFoeMaybeTrapPokemon`): a trapping rule in the request builder, no state; the replay stops show `-activate trapped` |
| 108 | ability `megalauncher` | 9 | 107 | S | `abilities.ts:2546-2557` | Mega Blastoise: pulse-flag moves x1.5; the `pulse` flag is carried but has no column (decision 0015, step G13 note) |
| 109 | ability `auraguard` | 5 | 5 | S | `abilities.ts:310-319` | Mega Lucario Z: contact moves do half damage (`onSourceModifyDamage`) |
| 110 | ability `hungerswitch` | 3 | 47 | H | `abilities.ts:1896-1907` | Morpeko: forme change each turn (`forme_now`) |
| 111 | ability `megasol` | 1 | 14 | H | `abilities.ts:2558-2571` (mod `45-48`) | Champions Mega ability: the holder's moves act as in sun (weather read for the holder); `-activate ability: Mega Sol` in replays |
| 112 | ability `spicyspray` | 0 | 22 | S | `abilities.ts:4466-4475` (mod `82-85`) | burns the attacker when hit (`onDamagingHit`, no draw) |

**More data-only rows** from the survey lists (the generator models them, nobody has marked them; each needs a mark and a recorded battle, and some read a flag the engine does not read yet, to be checked per row as in G21): Fiery Dance (73 / 102), Psycho Cut (64 / 570), Iron Defense (54 / 451), Electroweb (49 / 526), Thunder Punch (42 / 425), X-Scissor (42 / 257), Lumina Crash (36 / 107), Overdrive (36 / 24), Gigaton Hammer (31 / 268), Scorching Sands (29 / 171), Leaf Blade (28 / 421), Boomburst (28 / 34), Discharge (26 / 486), Sludge Wave (25 / 189), Volt Tackle (25 / 177), Bitter Malice (24 / 218), Fire Punch (24 / 124), Meteor Assault (24 / 13), Vacuum Wave (22 / 330), Meteor Mash (20 / 418), Extrasensory (19 / 103), Stone Edge (18 / 337), Surf (18 / 264), Zen Headbutt (17 / 196), Wild Charge (17 / 107), Body Slam (16 / 156), Parabolic Charge (16 / 150), Hammer Arm (15 / 272), Headlong Rush (15 / 148), Aqua Cutter (15 / 137).

Mega Stones are blocked by two abilities each: the base forme's (a separate blocker of the team) and the Mega forme's. They need no state; the Mega is already linked by G23-A. In the table below "marked" is judged against main at 0.34.0.

| Stone | M-C teams | M-B teams | Base ability | Mega ability |
|---|---:|---:|---|---|
| Garchompite Z | 479 | 109 | Rough Skin (marked) | Levitate (not marked) |
| Gengarite | 230 | 1118 | Cursed Body (not marked) | Shadow Tag (not marked; a trapping rule in the request, no state) |
| Metagrossite | 221 | 1850 | Clear Body or Light Metal (not marked) | Tough Claws (marked) |
| Froslassite | 214 | 1525 | Snow Cloak or Cursed Body (not marked) | Snow Warning (marked) |
| Swampertite | 178 | 2437 | Torrent (marked) | Swift Swim (not marked) |
| Lucarionite Z | 173 | 132 | Steadfast, Inner Focus or Justified (not marked) | Aura Guard (not marked) |
| Delphoxite | 172 | 2242 | Blaze (marked) | Levitate (not marked) |
| Dragoninite | 125 | 769 | Inner Focus or Multiscale (not marked) | Multiscale (not marked) |
| Glimmoranite | 105 | 423 | Toxic Debris or Corrosion (not marked) | Adaptability (marked) |
| Blastoisinite | 96 | 1242 | Torrent (marked) | Mega Launcher (not marked; reads the `pulse` flag, which has no column) |
| Cameruptite | 96 | 375 | Magma Armor, Solid Rock or Anger Point (not marked) | Sheer Force (not marked) |
| Mawilite | 68 | 1483 | Intimidate (marked) | Huge Power (not marked) |
| Venusaurite | 12 | 1162 | Overgrow (marked) | Thick Fat (not marked) |

Teams that pass, cumulatively, if the annotated rows of each class are resolved in this order (the counts are teams that pass **in addition** to the 385 and 299 that pass today; overlaps are counted once):

| After | M-C teams passing | M-B teams passing |
|---|---:|---:|
| today (0.33.0 snapshot) | 385 | 299 |
| the in-flight PRs (section 7) | 455 | 416 |
| + data-only rows | 463 | 427 |
| + small rules | 1188 | 1688 |
| + handlers | 1791 | 5506 |
| + heavy rows | 1868 | 5698 |
| + rev 4 rows (A and B together) | 2597 | 12,772 |

The rows of the S4 table, each added **last** on top of all batchable rows: Rage Powder +270 (M-C) / +2794 (M-B), Stomping Tantrum +179 / +1667, Roost +97 / +633, Quick Guard +12 / +140, Double Shock +10 / +17, Rage Fist +9 / +55, Protean +9 / +122, Illusion +7 / +42, Supreme Overlord +4 / +39, Zero to Hero +3 / +32, Revival Blessing +3 / +3, Burn Up +1 / +5.

What still blocks teams after all annotated rows (not state; the next audit): Floette (species unknown, 52 M-C teams), Raichunite X and Pyroarite (Surge Surfer needs G25's Electric Terrain; Unnerve is an S row), the "-illegal" and "-unknown" kinds (a name the Champions rules do not have), Electric Seed and Damp Rock (G25 and the weather items), Steel Beam, Ally Switch, Sniper, Stone Axe, Unaware, Heavy Slam, Snipe Shot, Leech Seed, Electric Surge.

## 7. In flight, and what moved since the snapshot

- move `blizzard` (M-C 380, M-B 3288): PR #170
- move `earthquake` (M-C 371, M-B 8935): PR #170
- move `ancientpower` (M-C 234, M-B 966): PR #170
- move `spikyshield` (M-C 168, M-B 1061): PR #159 (tail rev 3, `protect_kind`)
- move `terrainpulse` (M-C 130, M-B 114): PR #163 (waits for the owner's OK of two FIELD values)
- move `feint` (M-C 125, M-B 884): PR #170
- item `expertbelt` (M-C 83, M-B 794): PR #170
- move `acrobatics` (M-C 78, M-B 296): PR #170
- move `shellsmash` (M-C 77, M-B 961): PR #170
- move `risingvoltage` (M-C 46, M-B 108): PR #163

Also merged since the snapshot: G23-A (the Mega of a stone is a function of (forme, stone), #162), the live data API (#166), the team registry (#168). G23-B/C (#165) lands Levitate and the Mega marks, per the coordinator; if it does, the Levitate and stone rows above move to "done" and the cumulative table shifts accordingly.

## 8. What the replay stops say

The M11 run stopped 44,148 of 66,000 perspectives (the kept 21,818 plus the stopped). The biggest causes that map to this audit (perspectives stopped, not decisions):

| Stop | Count | Maps to |
|---|---:|---|
| `WEATHER_SAND`, `WEATHER_SNOW` | 6822, 4223 | marked since (step 5b) in the engine; the tracker folds them only when `TRACKER_FOLDS` allows (python) |
| `ABILITY_CHANGE` | 3393 | `ability_now` exists (rev 2); Trace is marked; Skill Swap and the others are handlers |
| `THROAT_CHOP` | 2633 | marked (G8); a tracker fold |
| `-fail unboost` | 2246 | Clear Body, Hyper Cutter, Inner Focus and similar (S rows above); a line class in the tracker too |
| `PERISH` | 1415 | `perish` exists (rev 2); Perish Song is an H row |
| `MUST_RECHARGE` | 1186 | marked (G17); a tracker fold |
| `ENCORE` | 1001 | marked (G9); a tracker fold |
| `-singleturn move: Protect` | 872 | a line spelling the tracker does not classify (python), not engine state |
| `FORME_CHANGE` | 703 | `forme_now`; Mimikyu, Aegislash, Palafin |
| `TYPE_CHANGE` | 668 | `soak_type`/`type2` |
| `-block` | 492 | Flower Veil-like lines; a tracker fold |
| `GLAIVE_RUSH` | 469 | marked (G19) |
| `IMPRISON` | 430 | `imprison` exists; Imprison is an H row |
| `-activate move: Trick` | 392 | Trick is an H row (`item_now` exists) |
| `-singleturn move: Roost` | 368 | Roost: `single_turn` bit 1 (rev 4) |
| `TAUNT` | 361 | `taunt_turns` exists; Taunt is an H row |
| `-activate ability: Toxic Debris` | 358 | H row (`toxic_spikes` exists) |
| `move Revival Blessing` | 135 | needs a request kind |
| `move Baton Pass` | 124 | HH row |

Most of these stops are the replay tracker waiting for folds (python, HauptSession's and M11's code) and for engine rules, not for new state: of the 19 lines above, only Roost, Revival Blessing and the Disguise/Illusion/Zero to Hero formes need anything from rev 4.

## 9. For the owner

1. **Accept rev 4 as cut B** (recommended), cut A (no growth, fewer teams: Rage Powder, Stomping Tantrum, Roost, Quick Guard) or cut C (adds the insertion-order byte pair)?
2. **Merge #159 and rev 4 into one revision?** #159 has not merged; a single 0x0403 would save a bump.
3. **View:** the optional bits (Roost bit 20, `move_failed_last_turn` byte, Supreme Overlord): expose them or leave the learner without them?
4. **Illusion** changes what the public view shows (the disguised identity). Defer it, or decide the hidden-information rule first?
5. **Revival Blessing** needs a new request kind (public API): in scope or not?
6. **Draw sites:** several rows add a draw (Flame Body, Static, Cursed Body, Moody, the lockedmove duration): each is a new value of the public draw-site enum (additive, like Poison Touch). Blanket OK or one by one?
7. **Data gaps that are not state:** `species-unknown floette` (52 M-C teams: a Floette forme the pool lacks) and the `-illegal`/`-unknown` kinds (moves and items the Champions rules do not have) are registry questions for the survey owner, not engine work.
