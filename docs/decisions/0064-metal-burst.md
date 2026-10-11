# 0064 - Metal Burst (G97): the foe's last hit, times 1.5

Status: **proposed; engine and generator done in the WIP, recordings pending the lock job** (lane A batch 7, builder H23, decision 0015 letter **5cz**, the second part after Psychic Terrain). Builds on 0046 section 6 (the first pin analysis, deferred there), 0023 (the foe's damage is not public), 0007 (the player view), 0015 (POOL kinds, the tail rev 5 position byte) and the cause 64 of 0046 section 10.
Renumbered from 0063 (collision with the Ghost Curse note on main), 2026-10-11. The purpose texts of the recorded specs (`tests/reference/specs/g97_metal_burst_*.json`, and their copies in `tests/reference/conformance_pool.h`) still say 0063 until the next regeneration.

Pin: Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`). No Champions override of `metalburst` or of the attacked-by record (`data/mods/champions/scripts.ts` has no `gotAttacked` or `damageCallback` hook; its `modifyDamage` at `scripts.ts:196` is in the formula path, which a damage callback never reaches, see 1.1).

## 1. Pin semantics (checked against the pin in step G97)

**1.1 Damage** (not a power). `data/moves.ts:11657-11664`: `damageCallback` returns `(lastDamagedBy.damage * 1.5) || 1`, or 0 without a record. `getDamage` returns the callback before the formula and before `modifyDamage` (`sim/battle-actions.ts:1607` returns, the formula and `modifyDamage` at `:1721` are after it). The value is then the damage: `spreadDamage` clamps it with `clampIntRange(targetDamage, 1)` (`sim/battle.ts:2113`), and `clampIntRange` floors (`lib/utils.ts:320-326`). So the damage dealt is `max(1, floor(1.5 * d))`, where `d` is the HP the record's hit took. Zero from a zero hit becomes 1 (the `|| 1`). There is no base power, no critical hit roll, no damage roll and no type multiplier.

**1.2 Foes and this turn.** `getLastDamagedBy(true)` (`sim/pokemon.ts:935-942`) takes the entries whose `damageValue` is a number and whose source is not an ally (`!this.isAlly(attacker.source)`), and returns the last one. `onTry` (`data/moves.ts:11670-11673`) fails unless that entry has `thisTurn`. `gotAttacked` (`sim/pokemon.ts:917-931`) pushes the entry with `thisTurn: true`; `endTurn` sets `thisTurn = false` for the entries of active sources and removes the others (`sim/battle.ts:1703`, the same loop). Because every entry of a turn is `thisTurn` at once, the record is usable exactly when the last numeric foe entry comes from the current turn.

**1.3 The target is the slot.** `onModifyTarget` (`data/moves.ts:11674-11681`) sets the target to `this.getAtSlot(lastDamagedBy.slot)`. The slot is `source.getSlot()` at the hit (`sim/pokemon.ts:520`, stored by `gotAttacked`). `getAtSlot` (`sim/battle.ts:1611-1617`) returns `side.active[position]` at the time of use. So if the attacker switched out after its hit, **the replacement at that slot is hit**, and the record stays on the defender until the turn ends.

**1.4 A Substitute hit leaves no entry.** The hit steps set `damage[i] = true` and `targets[i] = null` for a Substitute (`sim/battle-actions.ts:1061-1065`). The attacked-by loop runs over `targetsCopy` (`sim/battle-actions.ts:990-997`), which holds the null, and skips it: **no entry at all**, not even `true` (0046 section 6 said `true`; the loop shows the entry is not pushed). Either way `getLastDamagedBy` ignores it. A Substitute hit does not replace the record of an earlier hit this turn, and it does not create one.

**1.5 Multi-hit.** `gotAttacked` runs once per target after the hit loop, with `moveDamage[i]` of the **last executed hit** (`sim/battle-actions.ts:962-997`; the loop ends early when the user or the only target faints). A last hit that misses (`false`) or is absorbed by a Substitute leaves the record that was there before the move: no entry of this move counts. The engine does the same: the record of the move is written from the last executed hit of each foe target, only when that hit was numeric (`src/combat/turn.c`, the `metal_has` flags).

**1.6 Meaning of "cause 64 refused at PIVOT only".** The public record (`duoforge_battle_public`, `duoforge_battle_from_view`, and the observation causes of the live record assembler) refuses with `DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY` (64) while an active Pokemon of either side knows Metal Burst **and the decision is a PIVOT** (a faint replacement or a pivot switch, a mid-turn decision). Reason: the record is the foe's damage of this turn, which is not public (0023 section 1) and is not carried in the view. At turn boundaries the record is zero (`endTurn` clears it, turn 1 has none), so no refusal there, and the view stays exact. The rule is in `src/state/view.c` (`dfi_view_turn_history_risk`, the pivot clause next to Assurance). It is the same cause as 0046, no new value.

## 2. Engine state (tail rev 5, position bytes 33-35)

The 36-byte position block of the POOL tail (`src/codec/state_codec.h`) keeps byte 32 reserved and uses bytes 33-35:

| byte (in position) | field | meaning |
|---|---|---|
| 32 | reserved | zero (`reserved_pad` in memory; the decoder refuses otherwise) |
| 33 | `metal_source` (u8) | flat position of the foe whose last numeric hit this turn set the power, + 1; 0 = none |
| 34-35 | `metal_damage` (u16, LE) | the HP that hit took (the pin's `moveDamage`); zero whenever `metal_source` is zero |

- Cleared at `endTurn` (`src/combat/turn.c`, with the other per-turn flags; the pin's thisTurn rule, 1.2) and with the occupant (`dfi_tail_clear_occupant`, which covers a switch-out and a faint; the pin's `attackedBy` reset at switch-in, `sim/pokemon.ts:1548-1550`).
- Invariant `TAIL_POSITION` (`src/state/invariants.c`): `metal_source` at most 4; zero damage when the source is zero; the source is a foe of the position's side. A record of a fainted occupant is zero (the tail of a fainted occupant is cleared).
- The reserved count is 33 (1 field, 1 per position, 1 per roster member, 16 of rev 5); the encoded tail is 348 bytes, the schema stays 0x0503 (no pool state is frozen; the rev 5 tail is still the one under development).

## 3. Engine behaviour

- **Try** (before the hit steps and the accuracy roll, `src/combat/turn.c`): no record of the user → `dfi_fail_still` (`-fail` and `[still]`, pin `sim/battle-actions.ts:592-596`). The move fails with no draw.
- **Target**: the scripted class (`DFI_TARGET_CLASS_SCRIPTED`) is taken for Metal Burst alone: the occupant of the record's slot (1.3). An empty or fainted occupant is **refused** (`E_UNSUPPORTED`, never a guess) until the recording shows what the pin does (case 6, section 5).
- **Damage** (`dfi_get_damage`, an early return like Super Fang): `max(1, (3 * metal_damage) / 2)`, no crit, no roll, no modifier (1.1).
- **Record** (after the hit loop of the move): for each foe target whose last executed hit was numeric, the victim's `metal_source` = user + 1 and `metal_damage` = the HP it lost (1.5).
- **Guards**: a Metal Burst outside the POOL kinds is refused (`pool_rules`).
- **Generator**: `METAL_BURST` is special 105, UNMODELED moves to 106, the scripted target is modelled for Metal Burst alone (Counter and Mirror Coat are scripted too and stay unmodelled). `check_g97_facts` pins the entry text (1.1-1.3). The manifest marks `DFI_MOVE_METALBURST`. Marked count 246, unmodelled 172.

## 4. What is not modelled

- A target that is empty or fainted at use (refused, section 3), until the recording decides it.
- Counter, Mirror Coat (scripted, unmodelled; they read the same record family and are a later step).
- The view does not carry the record, so a PIVOT with Metal Burst known is refused (1.6), not guessed.

## 5. Recordings (lock job, hand calculation of the sequence)

Teams: X (p1) Aggron (Sturdy, Relaxed; Metal Burst, Protect, Substitute, Earthquake), Glalie (partner), Snorlax, Golisopod, Hippowdon, Slowbro; Y (p2) Dragonite (Choice Scarf), Azumarill, Sylveon, Glalie, Hippowdon, Swampert; for case 3 Y has Swampert with Flip Turn in the second position. Specs `tests/reference/specs/g97_metal_burst_*.json`, learnsets checked (`g96_learn_check.py`). Move numbers: Aggron 1 Metal Burst, 2 Protect, 3 Substitute, 4 Earthquake; Dragonite 2 Protect, 3 Dragon Claw; target 1 = the foe's first position.

Speed order (hand): Dragonite with Choice Scarf (base 80, x1.5) acts before Glalie (base 80) and Aggron (base 50, Relaxed lowers Speed); Swampert (base 60) acts before Aggron. Aggron always acts last in its own turn. Sums of the damage are not hand-computed (Champions stats are not in the pin text); the formula of 1.1 is what each expected line is checked against, using the damage printed in the trace.

| case | spec | turn 1 | expected | turn 2 |
|---|---|---|---|---|
| 1 normal | `g97_metal_burst_normal` | Dragonite Dragon Claw into Aggron (`-damage p1a` = D); Aggron Metal Burst on p2a | p2a takes `max(1, floor(1.5 D))` | Dragonite Dragon Claw again; Metal Burst again on p2a (the record of turn 2 only) |
| 2 no hit | `g97_metal_burst_no_hit` | Aggron Metal Burst first; nobody hits Aggron | `-fail\|p1a: Aggron` and `[still]` on the move line; no damage | - |
| 3 attacker switched | `g97_metal_burst_attacker_switched` | Swampert (p2b) Flip Turn into Aggron (`-damage` D), Swampert leaves; Aggron Metal Burst | the replacement at p2b (Azumarill, first standing reserve) takes `max(1, floor(1.5 D))`, not Swampert | - |
| 4 partner hit | `g97_metal_burst_partner_hit` | Glalie Earthquake hits Aggron (ally) and the foes; Aggron Metal Burst | `-fail\|p1a` with `[still]`: the only numeric entry is the ally's | - |
| 5 Substitute | `g97_metal_burst_substitute` | turn 1: Aggron Substitute, nobody hits | - | Dragonite Dragon Claw into the Substitute (no entry); Aggron Metal Burst: `-fail` `[still]` (no record) |
| 6 source fainted | `g97_metal_burst_source_fainted` | Dragonite Dragon Claw into Aggron (record D); Glalie Icicle Crash into Dragonite (4x Ice on Dragon/Flying): expected KO | Aggron Metal Burst on the fainted slot: the recording says what the pin does (the engine refuses until then) | - |

At most two attempts per case: the first is the spec as written; a second attempt only when the first does not reach the designed condition (for case 6: Dragonite survives Icicle Crash, so the case is a plain hit). Case 3's speed order rests on base Speed 60 against 50 with Relaxed; if the trace shows Aggron first, the case is recorded as it is (the Try fails) and not re-rolled.

### 5.1 Recorded outcome (attempt 2, the corrected specs)

- **normal (as planned):** turn 1 Dragon Claw took 18 (177 to 159), Metal Burst took 27 = floor(1.5 x 18). Turn 2 Dragon Claw took 20 (Leftovers had healed 11 in between), Metal Burst took 30 = 1.5 x 20. Conformant.
- **no_hit (as planned):** `|move|p1a: Aggron|Metal Burst||[still]` and `|-fail|p1a: Aggron`. Conformant. The engine first wrote `[notarget]`: the Try comes before the no-target line; fixed in `dfi_no_target_or_try`.
- **partner_hit (as planned):** Glalie's Earthquake hit Aggron (the ally) while the foes were protected; Metal Burst `-fail` `[still]`. Conformant.
- **attacker_switched (not reached):** the replacement request comes mid-turn after Flip Turn; `max_steps` 2 stopped before Aggron moved. Needs `max_steps` 3.
- **substitute (not reached):** on turn 2 Dragonite took its Protect, not Dragon Claw (the plan entry was not applied to its slot); no Substitute hit happened.
- **source_fainted (not reached):** Icicle Crash left Dragonite at 25 of 198 (Multiscale halves a hit at full HP); Metal Burst then took it to 0 while it was alive. The fainted-target path is not exercised.

The scripted target's draw (`RANDOM_TARGET`, context `resolve`) is dropped by the converter (`drop_reason`: target computed for priority), so the engine draws nothing there. A first version that drew it made every Metal Burst battle diverge; reverted.

Attempt 1 had `max_steps` equal to the turns (the lead switch-in is step 0 of a trace), so only the switch-ins were recorded. Attempt 2 is the first with turns.

### 5.2 Attempt 3, written before the run (lead-approved, one lock job)

**(b) The fainted slot (source_fainted).** When the record's source has fainted and no replacement has come in:

- `getTarget` (`sim/battle.ts:2436-2487`) runs first, with no chosen target: `getRandomTarget` (`sim/battle.ts:2490-2516`), which for a `scripted` move calls `side.randomFoe()` (`sim/battle.ts:2516`, `sim/side.ts:369-373`). That draw is `RANDOM_TARGET` in context `resolve`. The converter drops it: `tools/reference/trace_to_c.py:689-690`, `if site == 'RANDOM_TARGET' and ctx in ('action-speed', 'resolve'): return 'target computed for priority'`, a drop reason. The step report of `diff_random.py` writes such a draw as `dropped: target computed for priority`. The engine therefore draws nothing there (section 5.1).
- `useMoveInner` then runs `ModifyTarget`: `onModifyTarget` sets `getAtSlot(slot)` (`sim/battle-actions.ts:416`, `data/moves.ts:11674-11681`), the fainted Dragonite, which is defined, so the random branch at `:416` does not run. The move line is added with that target (`:457`).
- `getMoveTargets` (`sim/battle-actions.ts:470`, `sim/pokemon.ts:791`), default branch (`sim/pokemon.ts:821-827`): `if (!target || (target.fainted && !target.isAlly(this)) ...)` then `possibleTarget = this.battle.getRandomTarget(this, move)`; no possible target gives `targets: []`; otherwise the target is replaced by a random living foe. **So: a retarget with a draw, not a fail**, as long as a foe is alive. `retargetLastMove` changes the move line to the new target.
- `randomFoe` draws even with one candidate: `PRNG.sample` is `random(items.length)` (`sim/prng.ts:132-136`). The engine's `dfi_random_foe` has the same draw (`src/combat/turn.c`, RANDOM_TARGET over the living foes).
- A faint is replaced at the end of the turn: `makeRequest('switch')` at `sim/battle.ts:2912`, after the queue. So in the turn of the KO the fainted Dragonite is still in its slot when Aggron acts.

The engine implements this in `dfi_move_targets` (SCRIPTED): an occupant that is alive is the target; otherwise `dfi_random_foe` over the user's foes (no living foe: no target). The `RANDOM_TARGET` draw of that retarget is not dropped by the converter (context `execute`, not in the dropped list), so it is a tape entry the engine must consume. Whether it is in the trace as `kept` is what the run decides.

**Plan of source_fainted, by hand.** Speeds (base; Champions stats are not in the pin text, so only the order matters): Dragonite 80 with Choice Scarf (x1.5), Glalie 80, Azumarill 50, Aggron 50 with Relaxed (x0.9), Swampert 60. Order: Dragonite, Glalie, Azumarill, Aggron. Multiscale halves a hit at full HP only; Dragonite is at full HP for the first hit.

- Turn 1: Dragonite Dragon Claw into Aggron (Aggron 177 to about 159, the record D1, like attempt 2). Glalie Icicle Crash into Dragonite: 4x Ice on Dragon/Flying, halved by Multiscale at full HP, 198 to 25 (attempt 2, same draws up to here). Aggron Earthquake: Dragonite is immune (Flying), Azumarill and Glalie take it (Glalie is the ally, not a record). Leftovers heals Aggron 177/16 = 11 at the end of the turn. The Earthquake is Aggron's move, so its own record is not written.
- Turn 2: Dragonite Dragon Claw into Aggron (record D2, the damage of this hit, Leftovers already in). Glalie Icicle Crash into Dragonite at 25: **accuracy 90** (`data/moves.ts:9437-9441`), so a miss (10%) leaves Dragonite alive: then the case is not reached. If it hits, Dragonite faints. Azumarill Waterfall into Glalie (no protect, so Azumarill is a valid target). Aggron Metal Burst at the fainted slot p2a: record D2 numeric, the thisTurn rule holds, the target is retargeted to Azumarill with one draw, damage floor(1.5 D2) on Azumarill.
- Expected sequence: `|move|p1a: Aggron|Metal Burst|p2a: Dragonite` retargeted to `p2b: Azumarill`, then `-damage|p2b: Azumarill|...` of max(1, floor(1.5 D2)).

**(a) attacker_switched.** Turn 1: Swampert (Speed 80) Flip Turn into Aggron (63), Aggron's record; the switch is requested before Aggron acts (the replacement request of the U-turn-type move), Azumarill comes in at p2b as the first standing reserve; Aggron Metal Burst targets the replacement by slot (`getAtSlot`, `sim/battle.ts:1611-1617`). max_steps 3 (lead, turn, replacement).

**(c) substitute, verified by hand.** The attempt-2 plan was not a harness fault: Dragonite holds **Choice Scarf**, so its turn-1 Protect locked it into Protect (the choicelock: the request offers only the locked move). Its turn-2 choice `move 3 1` (Dragon Claw) was not legal, and the plan fell back to its first usable move. The new plan has Dragonite hit Aggron on turn 1 (no Substitute yet: Dragonite acts first), then Aggron makes a Substitute; turn 2 Dragon Claw is the only legal move and hits the Substitute (`battle-actions.ts:1061-1065`, no entry), and Aggron's Metal Burst fails (`-fail`, `[still]`) because the turn-1 record ended with turn 1 (section 1.2). Sub HP is 177/4 = 44; the turn-2 Dragon Claw does about 20, so the Substitute stays up.

**Outcome of attempt 3 (recorded, conformant, final: no fourth attempt).**

- attacker_switched: Flip Turn took 62 from Aggron (177 to 115); Azumarill came in at p2b (`[from] Flip Turn`); Metal Burst took 93 from Azumarill (207 to 114) = floor(1.5 x 62). The target is the replacement at the slot.
- substitute: turn 1 Dragon Claw hit Aggron directly (18); Aggron's Substitute cost 44 (159 to 115). Turn 2 Dragon Claw went into the Substitute (no damage line on Aggron); Metal Burst `-fail` `[still]`.
- source_fainted: turn 1 Dragon Claw 19 on Aggron, Icicle Crash 175 on Dragonite (198 to 23, Multiscale halved it, then Multiscale was gone). Turn 2 Icicle Crash KO'd Dragonite (ACCURACY hit); Metal Burst `|move|p1a: Aggron|Metal Burst|p2b: Azumarill` (retargeted, one RANDOM_TARGET draw in the engine's tape) and took 16 (170 to 154). The record D2 that 16 implies is 11 (floor(1.5 x 11) = 16); the trace shows Aggron's HP after the hit (150 of 177) but not the HP before it, so D2 is inferred, not read. The conformance test matches the tape, so the retarget draw is a kept entry.
- The Choice Scarf locked Dragonite into its first move, which confirms the attempt-2 substitute cause (section 5.2).

**Mutants planned against attempt 3:** the retarget without its draw (the tape differs), the retarget of a fainted target to a fail, the record kept at turn end, the Substitute hit counted as an entry.

## 6. Tests and evidence (planned)

- Recorded battles: the six traces above (`tests/reference/traces`, converted with `trace_to_c.py`), so the usage check of `test_trace_to_c.py` finds a pool battle that uses Metal Burst.
- Codec and invariants: `tests/test_pool_tail.c` (the sweep of bytes 33-35: source 0-4 valid for the other side, 5 to 255 refused as TAIL_POSITION, damage zero when the source is zero; the reserved byte 32 refuses every value but zero).
- Clone, pool setup, provenance: `tests/test_clone_equal.c` (the new fields copied), the fingerprints and hashes of this step.
- View: the cause 64 at a PIVOT with Metal Burst known (refused), at turn 1 and at a turn boundary (not refused).
- Mutants (lock job, after green): the record not cleared at turn end; the record from ally hits; the Substitute hit counted; the target by source identity instead of the slot; the power without the `max(1, ...)`; the Try without the record check.
- Triggers (campaign, lock job, after green): at least 100 Metal Burst uses that hit a target, partner hits not counted (a campaign of the Aggron teams), the switched-out attacker case and the KO case counted separately; plus the Psychic Terrain campaign seed 98 (100 battles, teams X and Y) on the same final head, as the lead asked.

## 7. State at the pause (owner decision: the expansion goal drops to 75 %; G96 pauses, nothing new starts)

- **Psychic Terrain (G96):** campaigns on the HEAD runner, teams X and Y, pairings XY YX XX YY. Seed 96 (campaign 96b, 300 battles): 300 of 300 PASS, blocks 54. Seed 97 (300 battles): 299 PASS, 1 UNSUPPORTED (fz_97_254, the residual speed tie of three or more, `turn.c` residual pair draws, intended refusal, not Psychic Terrain). Together 599 battles: 99 blocks against the goal of 100 (one short). Seed 98 (100 battles) is **open**: not run.
- **Metal Burst (G97):** six recordings (normal, no_hit, partner_hit, attacker_switched, substitute, source_fainted), all conformant with the pinned Showdown after attempt 3 (section 5.2). The cause-64 PIVOT refusal and the record invariant are tested (`tests/test_pool_g97.c`, 47 checks). The nine mutants (`tools/...` scratch script, not in the repo) and the Metal Burst campaign (300 battles, seed 9701; the success, no-record, retarget and replacement counts) are **open**: no lock job was queued or started.
- **Head at the pause:** the branch `chris/expansion-g96-terrain-burst` carries the HS merge (b4d1ae40 is HS's head), the Psychic Terrain engine and campaigns, and the Metal Burst engine, recordings and tests; the quick CI of the last commit is the owner's record in the batch.
- **Not done:** the mutants, the Metal Burst campaign, the Psychic seed 98 campaign, and the 100-block Psychic target.
