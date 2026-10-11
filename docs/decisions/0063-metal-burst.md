# 0063 - Metal Burst (G97): the foe's last hit, times 1.5

Status: **proposed; engine and generator done in the WIP, recordings pending the lock job** (lane A batch 7, builder H23, decision 0015 letter **5cz**, the second part after Psychic Terrain). Builds on 0046 section 6 (the first pin analysis, deferred there), 0023 (the foe's damage is not public), 0007 (the player view), 0015 (POOL kinds, the tail rev 5 position byte) and the cause 64 of 0046 section 10.

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

## 6. Tests and evidence (planned)

- Recorded battles: the six traces above (`tests/reference/traces`, converted with `trace_to_c.py`), so the usage check of `test_trace_to_c.py` finds a pool battle that uses Metal Burst.
- Codec and invariants: `tests/test_pool_tail.c` (the sweep of bytes 33-35: source 0-4 valid for the other side, 5 to 255 refused as TAIL_POSITION, damage zero when the source is zero; the reserved byte 32 refuses every value but zero).
- Clone, pool setup, provenance: `tests/test_clone_equal.c` (the new fields copied), the fingerprints and hashes of this step.
- View: the cause 64 at a PIVOT with Metal Burst known (refused), at turn 1 and at a turn boundary (not refused).
- Mutants (lock job, after green): the record not cleared at turn end; the record from ally hits; the Substitute hit counted; the target by source identity instead of the slot; the power without the `max(1, ...)`; the Try without the record check.
- Triggers (campaign, lock job, after green): at least 100 Metal Burst uses that hit a target, partner hits not counted (a campaign of the Aggron teams), the switched-out attacker case and the KO case counted separately; plus the Psychic Terrain campaign seed 98 (100 battles, teams X and Y) on the same final head, as the lead asked.
