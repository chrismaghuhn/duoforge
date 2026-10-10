# 0042 - Baton Pass (G74): proposal of phase 1

Status: **proposal, not accepted.** Lane A batch 5, builder H14, branch `chris/expansion-g74-baton-pass`. Entry 5cf in `docs/decisions/0015-content-expansion-pool.md`. No engine code, no table change and no public value in this commit. Phase 2 starts only after the lead answers section 11.

Pin: Pokemon Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`), read only. Champions mod checked: it does not override the move, the switch path, `copyVolatileFrom` or the `noCopy` flags. It does override `clearVolatile` (`data/mods/champions/scripts.ts:121-170`), which resets `timesAttacked` (line 168) and is used below. Builds on 0032 (Substitute), 0023 (determinization), 0025 (the PIVOT pattern) and 0007 (information boundary).

## 1. What the pin does

**The move** (`data/moves.ts:1092-1116`):
- `flags: { metronome: 1 }`. `accuracy: true`, `target: "self"`, category Status, priority 0, no `protect`, no `bypasssub`.
- `onHit(target)` (1097-1103): if `!canSwitch(target.side)` or the target has `commanded`, it sets `[still]`, prints `-fail|target`, and returns `NOT_FAIL`. No switch is requested.
- `self.onHit(source)` (1108-1111): `source.skipBeforeSwitchOutEventFlag = true`. This suppresses the `BeforeSwitchOut` event of the switch that follows (see 3.4).
- `selfSwitch: 'copyvolatile'` (1113).

**The request.** `moveHit` (`sim/battle-actions.ts:1290-1296`): `selfSwitch` counts as done only when `canSwitch(source.side)` and not `commanded`. Then (1311-1313) `source.switchFlag = move.id` when the source is alive and not commanded. The switch request is made at the same point as for U-turn: `sim/battle.ts:2878-2906` (the `switches` table, the `makeRequest('switch')` at 2906). In that loop (2895) the `BeforeSwitchOut` of a pivot runs only when `!pokemon.skipBeforeSwitchOutEventFlag`.

**The switch.** The chosen switch is `runAction` `switch`. `sim/battle-queue.ts:250-254`: a string `switchFlag` becomes the action's `sourceEffect` (the move). `sim/battle-actions.ts:76-79`: `switchCopyFlag` is `'copyvolatile'`.
- 80-86: `BeforeSwitchOut` runs unless `skipBeforeSwitchOutEventFlag` (set above), then the flag is reset.
- 87: `SwitchOut` runs on the leaver. A failed `SwitchOut` (returns false) cancels the switch. This is where Regenerator (G39) heals.
- 88-96: the `End` events of the leaver's ability and item, `cancelAction`.
- 113-114: `pokemon.copyVolatileFrom(oldActive, switchCopyFlag)` if the flag is set (for `copyvolatile` it is).
- 117: `oldActive.clearVolatile()`.
- 122-123: `isActive`, `position`, and the three per-turn flags of the leaver (`statsRaisedThisTurn`, ...) are reset.
- 142: the entering Pokemon gets a fresh `abilityState` and `itemState`.
- 146: `|switch|` (or `|drag|`) with `[from] ${sourceEffect}`, which prints `[from] move: Baton Pass`.
- Then `runSwitch` and `SwitchIn` as for any switch.

**The copy.** `copyVolatileFrom(pokemon, switchCause)` (`sim/pokemon.ts:1246-1275`):
- `this.clearVolatile()` on the receiver first (1247). In Champions this resets its `timesAttacked` (`data/mods/champions/scripts.ts:168`), so a receiver's Rage Fist count starts at 0.
- `this.boosts = pokemon.boosts` (1248, since the flag is not `shedtail`).
- For every volatile `i` of the leaver (1249-1260): skipped when `conditions.getByID(i).noCopy` (1251). Each copied volatile is a shallow clone with `target: this` (1253), so **the state of the volatile moves whole, including its counter, its source and its HP** (the Substitute's `hp`, 1253-1254, is kept by the clone). Linked volatiles are relinked (1255-1263).
- `pokemon.clearVolatile()` on the leaver (1266), then one `Copy` event per copied volatile (1268-1270). Only three moves have a `Copy` handler (Gastro Acid, Power Shift, Power Trick: `data/moves.ts:6452, 13739, 13829`); none is marked in our manifest, so no `Copy` event is reached in the pool.

**The `noCopy` set** (the only volatiles the pin does not copy): `trapped` (`data/conditions.ts:208-210`), `trapper` (218-220), `choicelock` (324-326), `dynamax` (755), `commanded` (809-811), `commanding` (826-828), and the abilities `flashfire` (`data/abilities.ts:1355`), `protosynthesis` (3531) and `quarkdrive` (3667). In our pool: `choicelock`, `trapped`, `trapper`, `flashfire` matter; `dynamax`, `commanded`, `commanding`, `protosynthesis`, `quarkdrive` are not in the pool.

**What `clearVolatile` resets** (`sim/pokemon.ts:1510-1560`, plus Champions 121-170): boosts to zero, `moveSlots` back to base, `transformed` false (and `setSpecies(baseSpecies)` at the end, which undoes Transform), `ability` back to base, `volatiles` cleared (not `dynamax` for Eternatus), `lastMove`/`lastMoveEncore`/`lastMoveUsed` null, `moveThisTurn` '', `moveLastTurnResult` and `moveThisTurnResult` undefined, `lastDamage` 0, `attackedBy` [], `hurtThisTurn` null, `newlySwitched` true, `beingCalledBack` false, `timesAttacked` 0 (Champions). The receiver's `clearVolatile` (1247) and the leaver's (117) both run, so **nothing listed here moves with the pass**.

## 2. Which state moves, and which stays

The engine keeps the volatile state in `dfi_active_slot` (`src/state/battle_internal.h:137-152`) and the tail's `dfi_tail_pos` (`battle_internal.h:296-340`, tail rev 2 to 5). Both are per position. The leaver's fields are cleared by `dfi_vacate`, the entering member's by `dfi_place` (`src/combat/turn.c:7971-7977`). The Baton Pass copy must run **between** the `SwitchOut`/`End` handling and `dfi_vacate`, and must **not** clear the copied fields.

**A. Copied** (the pin copies the volatile whole):

| Engine field | Pin volatile (line) | Notes |
|---|---|---|
| `stages[]` (boosts) | `boosts` object (`pokemon.ts:1248`) | the whole boost table; no `-boost` line |
| `substitute_hp` | `substitute` (`data/moves.ts:18304`) | the HP moves with it (1253-1254). Section 5 |
| `encore_slot`, `encore_turns` | `encore` (`data/moves.ts:4724`) | **see 11.2**: the pin stores a move id (`effectState.move`, 4748), the engine a slot |
| `taunt_turns` | `taunt` (18974) | count |
| `disable_slot`, `disable_turns` | `disable` (3648) | **see 11.2**: `effectState.move` (3691) |
| `heal_block_turns` | `healblock` (8273) | count |
| `perish` | `perishsong` (13233) | count |
| `yawn_turns` | `yawn` (21131) | count; the source of the pin's Yawn is not in our state (only the count), and the engine already models the count alone |
| `leech_seed_source` | `leechseed` (10202) | the source's position moves in the state; the receiver is now the seeded one |
| `focus_energy` | `focusenergy` (5971) | |
| `stockpile`, `stockpile_def`, `stockpile_spd` | `stockpile` (17960) | the layers and the boosts they gave (the boosts already move in `stages`) |
| `charge` | `charge` (2264) | |
| `glaive_rush` | `glaiverush` (6647) | |
| `confusion_turns` | `confusion` (`conditions.ts:162`) | a running counter, hidden for a foe (0023); it moves hidden as it is |
| `throat_chop_turns` | `throatchop` (19389) | |
| `imprison` | `imprison` (9489) | |
| `trap_turns`, `trap_source`, `trap_band` | `partiallytrapped` (`conditions.ts:222`) | the trapper's position stays the same; the pin copies it |
| `stall_level`, `stall_turns` | `stall` (`conditions.ts:439`) | |
| `DFI_VOL_HELPING_HAND`, `DFI_VOL_FOLLOW_ME` (`flags`), `single_turn` bits | `helpinghand` (8573), `followme` (6039) | one-turn volatiles set by an ally this turn; the receiver never moves again this turn, and they end at the residual |
| `position_flags` bits 2-3 (Dragon Cheer crit stage) | `dragoncheer` (4056) | |
| `hits_taken` | not a volatile: `timesAttacked` (Champions reset) | **not copied**: see 2.C |

**B. Reset on the leaver and on the receiver (the pin's `clearVolatile`, not copied):**
- `last_move` (`lastMove` null);
- `move_result` (`moveLastTurnResult` and `moveThisTurnResult` undefined, `moveThisTurn` '');
- `hits_taken` (`timesAttacked` 0 in Champions);
- `ability_state` (the receiver's `abilityState` is fresh, 142; the leaver's is deleted, `started` only);
- `DFI_VOL_NEWLY_SWITCHED` (set on entry, as any switch), `DFI_VOL_UNBURDEN` (to read: section 7);
- the `position_flags` bit 1 (stats raised this turn; the leaver's `statsRaisedThisTurn` is reset at 123, the receiver's is already false: it was benched);
- `lockedmove` / `lock_turns` and `DFI_VOL_CHOICE_LOCK` (see C).

**C. Not copied, and unreachable with a pass** (the holder cannot choose Baton Pass while the state is set, so no pass can carry it):
- `choicelock` (a Choice item locked into a move, `noCopy`, `conditions.ts:324`): the locked holder may only pick the locked move. Not copied, and the receiver is free.
- `charge_turns` (`twoturnmove`, 287), `must_recharge` (`mustrecharge`, 364), `locked_move` with `lock_turns` (`lockedmove`, 253), `protect_kind`/`DFI_VOL_PROTECT` (`protect`, 13961): each one takes the holder's action of the turn. **The engine must refuse with `E_UNSUPPORTED` if it finds one set at a pass**, because the pin would copy the lock (`lockedmove`, `twoturnmove`, `mustrecharge` are not `noCopy`), and that path is not in the pool.
- `DFI_VOL_FLINCH` (`flinch`, 198): a flinch ends the holder's turn before its move, so it cannot be set at a pass.
- `DFI_VOL_FLASH_FIRE` (`flashfire`, `noCopy`): not copied. Flash Fire is not marked in the pool; not copied is the pin's behaviour.

**D. Slot-bound, never moves** (the pin's `slotConditions` are per position and are not part of the copy): `position_flags` bit 0 (Healing Wish, G76), `future_sight` (lane B). A pass leaves them with the position, and `dfi_vacate` must not clear them. The engine must split the clear so that only occupant-bound fields are cleared on a pass.

## 3. The pivot and the switch

**3.1 Flag and table.** Baton Pass needs one new internal flag `DFI_SWITCH_BATON_PASS` (value 8, after `DFI_SWITCH_REVIVE_BLESSING` 7, `battle_internal.h:81-91`) and one row in `dfi_pivot_moves` (`src/state/closure_member.c:23-28`, `DFI_PIVOT_MOVE_COUNT` 4 to 5, `closure_member.h:63`). The flag is internal (not a public value): it is the switch flag of the leaver, read at the switch executor (`turn.c:7937`) exactly as `DFI_SWITCH_UTURN` is. **This is the only code-level value; it does not need the lead's approval**, but I list it so the lead sees it.

**3.2 Boundary.** The user's side is requested at a PIVOT with `slot_mask` = the user's position, as for U-turn and Revival Blessing (0025 item 7). The foe is not requested. The request is made only when the pass did not fail (3.5).

**3.3 The pass itself is a status move.** Its own `-fail` is public (3.5). Its PP is spent as for any move.

**3.4 BeforeSwitchOut is skipped** (`skipBeforeSwitchOutEventFlag`, 1110). In our engine the pivot's `BeforeSwitchOut` runs at the boundary request (`turn.c` near 7943-7947 and the request path). For a pass that event is **not run**. The only `BeforeSwitchOut` handler in the pool's neighbourhood is Pursuit's foe-side handler (`data/moves.ts:14398`) and dynamax (`conditions.ts:780-782`); Pursuit is not marked (no `dfi_pursuit` in the manifest), so no interaction arises in the pool. Refusal: if Pursuit is ever marked, a pass must not trigger it; the note goes into the Pursuit row.

**3.5 Failure.** `canSwitch(side)` false (no living reserve, or the reserve is empty) or the user is `commanded`: the pass prints `-fail|user` with `[still]`, and no request is made. The engine's existing FAIL event (position = user, cause none) carries this, plus the `[still]` on the move line through the existing `attrLastMove` path. A `commanded` user is unreachable in the pool (no `commanding` is marked); the engine refuses if it sees one.

**3.6 The switch line and the event.** `|switch|POKE|DETAILS|HP|[from] move: Baton Pass`. The existing `DUOFORGE_EVENT_SWITCH` (`duoforge.h:991`) with **cause MOVE and id2 = Baton Pass** (the move id, as for U-turn and Parting Shot: `turn.c:7987-7995`). No new event, no new cause.

## 4. What each side sees

| Information | Owner (own side) | Foe (public record) | Public value |
|---|---|---|---|
| The switch and its cause (`[from] move: Baton Pass`) | yes | yes | existing SWITCH, cause MOVE |
| The receiver's HP | exact (the owner's split line) | percent | existing SWITCH HP fields |
| Boosts moved to the receiver | yes (state) | yes, because the holder's boosts were public before the pass (the foe saw the `-boost` lines); the record carries them | none new |
| Presence of a Substitute on the receiver | yes (bit 0) | yes, presence only (V8 of 0032) | none new |
| **The Substitute's HP** | **no** | **no** | **none (lead requirement 1)** |
| Taunt, Encore, Disable, Heal Block, Perish, Yawn, Leech Seed, Focus Energy, Stockpile, Charge, Glaive Rush, Throat Chop, Imprison, partial trap, Dragon Cheer, Helping Hand, Follow Me | yes, as state | as the public record already shows them: the counter as its public remaining turns; a hidden running counter (confusion) stays hidden | none new |

**Key rule for the live tracker (HauptSession).** A copy prints **no** line: no `-start`, no `-boost`, no `-end`. A tracker that only folds lines would lose every copied volatile. The engine's public record carries the copy from the state; the live adapter (`python/duoforge_live`) has to move the tracked volatiles of the leaver to the receiver on a `[from] move: Baton Pass` switch, or refuse. That is HauptSession's, and I will not edit it.

## 5. The Substitute through a pass (lead requirements)

**5.1 Requirement 1: the HP stays hidden from both sides.** The HP is `substitute_hp` in the state. The pass copies it inside the engine. The public surface carries only presence (V8, the existing bit 0) and the existing events, none of which has an amount:
- no event field, view field or encoder column carries `substitute_hp` (0032 section 4);
- the switch event carries the receiver's HP, not the Substitute's;
- the owner's request (`getSwitchRequestData`) does not show a Substitute HP, as 0032 section 4 says, so the owner does not see it either.

**5.2 Requirement 2: the receiver triggers the Substitute public-cause refusal.** `src/state/view.c` already refuses any Substitute on either side (0032 section 14, `DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE` = 8) for the public record, and the honest world (`battle_from_view`) with the same cause. Once the copy sets `substitute_hp` on the receiver's position, the existing presence test refuses **for the receiving position** without any new rule. The phase 2 work is to prove it: a C test that passes a damaged Substitute and asserts that `duoforge_battle_public` and `battle_from_view` both return `DUOFORGE_E_UNSUPPORTED` with cause 8 for the receiver's position, and a recorded battle that shows the pass. The count is HauptSession's arena count.

**5.3 The invariant (open, a decision for the lead).** `src/state/invariants.c:583-584` requires `substitute_hp <= maxhp / 4` of the occupant. A pass moves a Substitute to a receiver with a different maximum HP, so the invariant can fail: the holder's maxhp/4 is the bound the sub was made with, the receiver's may be lower. The pin has no such check (the HP is a number on the volatile). Options:
- **A (no bytes):** the bound becomes `substitute_hp <= 0xFFFF` (the field's range) for a Substitute that came by a pass, with a test that the bound of the creator was kept when it was made. This is a weakening of an invariant; it needs a line in the decision and a mutant. The creator's cap is not in the state, so it cannot be checked after the pass.
- **B (2 bytes):** store the cap (`floor(creator maxhp / 4)`, u16) next to `substitute_hp`, in the rev 5 general reserve (16 bytes, shared with lane B). The invariant then holds exactly. This needs the lead's OK for the bytes.
- **Recommendation: B.** It keeps the invariant that 0032 relies on; A makes it weaker. The cost is two reserve bytes and the rev 5 layout note.

**5.4 Determinization (0023).** A foe-side Substitute is refused in the honest world today (0032 option A), so a pass that brings a foe's Substitute to a foe receiver is refused the same way. An own-side receiver is refused too (cause 8). The pass therefore adds no hypothesis case: no HP is ever derived from a hidden HP.

## 6. Refusals (`E_UNSUPPORTED`, explicit, never a guess)

- A holder that is **Transformed** (decision 0028): the pin's `clearVolatile` calls `setSpecies(baseSpecies)` (`pokemon.ts:1560`), and the copy of Transform's state is not read yet. Refused until read (phase 2).
- A holder or receiver under **Illusion** (0026) or **Imposter** (0027): the pin's copy and the Illusion/Imposter state have not been read together. Refused until read.
- A holder with `choicelock` is not refused: it cannot choose a pass (C above). Unreachable; a guard only.
- `lockedmove`, `twoturnmove`, `mustrecharge`, `protect`, `commanded`, `commanding`, `trapped`, `dynamax` set at a pass: refused (the copy of these is not modelled for the pool; C above).
- A pass whose receiver lacks the move that Encore or Disable names (11.2): refused until read.
- Baton Pass into a Pokemon with `DFI_VOL_UNBURDEN` set: refused until read (`unburden` state, 2.B).

## 7. What is read and what is not

**Read** (pin lines above): the move, the self part, the switch flags, the request, the switch line, the copy, `noCopy`, `clearVolatile`, the Champions `clearVolatile` (`timesAttacked`), the volatiles' conditions (their names and lines).
**Not read yet** (phase 2, before any row is marked):
- Encore's and Disable's target storage and their behaviour when the receiver lacks the move (`data/moves.ts:4724-4770`, `3648-3700`).
- Unburden (its state in the pin: a per-Pokemon volatile or `abilityState`?).
- Transform's copy and its `setSpecies` on clear (0028).
- Illusion and Imposter with a switch (0026, 0027).
- Partial trap under a pass: whether `partiallytrapped` prevents a switch in the pin (the holder's canSwitch).
- Whether a Baton Pass by a holder that is `commanded` is reachable in our pool (it is not, by the manifest).

## 8. The engine change (phase 2)

- `src/combat/turn.c`: the BATON_PASS flag at the switch executor (near 7937-7990): the copy between the SwitchOut/End step and `dfi_vacate`: the copy list of section 2.A, the resets of 2.B, the slot-bound fields of 2.D untouched, no `BeforeSwitchOut`; the event as 3.6.
- The move row: a handler id for Baton Pass (new, in the closure), `selfSwitch: 'copyvolatile'` accepted only for it (`tools/datagen/gen_closure.py:462-468`, which now refuses any non-boolean selfSwitch; `tools/datagen/pool_families.js:1622`, `ENGINE_PIVOTS`), a pool table row with its flags (metronome), the pivot row, and the `DFI_PIVOT_MOVE_COUNT` change.
- `src/state/invariants.c`: the bound of 5.3 (option A or B).
- `src/state/view.c`: no change, if the presence test already covers the receiver (5.2). To check in phase 2 by a C test.
- Pool hash: the table changes, so `gen_closure.py --pool --check` and the two constants (`POOL_TABLE_HASH`, `POOL_HASH_HEX`) and the KP/KPD fingerprints (`tests/test_pool_setup.c`) are updated after regeneration, as the rules say.
- Python: **no change in phase 2.** The live tracker needs the copy rule (section 4). HauptSession's.

## 9. Public values

**None new.** The switch uses `DUOFORGE_EVENT_SWITCH` with the existing `DUOFORGE_CAUSE_MOVE` and id2 = Baton Pass. Presence uses the existing bit 0 of the position extension (0032 V8). The refusal uses the existing cause 8. The internal flag `DFI_SWITCH_BATON_PASS` is not public. No version bump, no header change, no tail bit, except the option B bytes (5.3).

## 10. Evidence plan (phase 2)

- Recorded POOL battles with genders stated (`"data": "pool"`, six members a side, unique items, legal EVs): a boosted holder passes its stages (the receiver attacks with them next turn); a **damaged Substitute passed** (the holder raises a Substitute, takes a hit, passes, the receiver's next hit breaks it: `g74_pass_sub_damaged`, lead requirement 2); Taunt, Encore, Disable, Heal Block, Perish Song, Yawn, Leech Seed, Focus Energy, Stockpile, Dragon Cheer; a Helping Hand one-turn volatile; a pass with no reserve (`-fail`, `[still]`); a pass with Regenerator on the holder (heal on SwitchOut before the copy).
- A C test `tests/test_pool_g74.c`: the copy list (2.A), the resets (2.B), the slot-bound fields kept (2.D), the substitute refusal on the receiver (5.2, cause 8, public and honest world), the no-HP-leak check (the event and view fields hold no HP), the failure path, the BeforeSwitchOut skip.
- Mutation checks: each edited rule must fail a test: a copied volatile dropped (Taunt), the boosts not copied, the Substitute HP reset on the receiver, `noCopy` ignored (choicelock copied), the BeforeSwitchOut run, the slot-bound field cleared, the cause missing on the switch line, the receiver's refusal missing (cause 8), the bound check off by one.
- Campaign: `diff_driver.py random`, seed 74, about 300 battles, pairs over two or three teams with Baton Pass (through the machine lock per chunk, never inside a wrapper).
- Lint, the MinGW check and the full ctest, as the rules say.

## 11. Questions for the lead

1. Section 5.3: option A (loosen the Substitute bound for a passed sub) or B (2 reserve bytes for the creator's cap). My recommendation is B.
2. Section 2.A (Encore and Disable): the pin stores a move id, the engine a slot. Option: store the move id in the reserve (2 bytes per position) or refuse a pass with an Encore or Disable active until read. Which?
3. Section 6: refusal of Transform, Illusion and Imposter holders until read. OK?
4. Section 3.1: `DFI_SWITCH_BATON_PASS` (8) is internal and needs no approval. Tell me if you want it otherwise.
5. Section 4: the live tracker's copy rule goes to HauptSession. OK to put it in the message to HauptSession?

## 12. Known gaps (honest)

- The pin's copy of `helpinghand` and `followme` is read; their effect on the receiver in the same turn is not traced yet.
- The Encore/Disable behaviour when the receiver lacks the move: not read (7).
- Unburden, Transform, Illusion, Imposter, partial trap under a pass: not read (7).
- The reserve-byte question (5.3) and the Encore slot question (11.2) are open; the proposal assumes the answers are not "no".
- Phase 1 had no engine code, no tables and no evidence. Phase 2 is section 13.

## 13. Phase 2: what is built and measured (2026-10-10, builder H14)

Commits on `chris/expansion-g74-baton-pass`: `51ec1029` (the pool row modelled: handler BATON_PASS, pivot flag, table regenerated), `0b3fd447` (the engine checkpoint), `2ec07df5` (the C view proof, the receiver refusal, the guards, the test updates), `e058f894` (the no-reserve failure line, the refusals after it, the third recorded battle). HauptSession's `d0f0659e` (the Python fold) sits on `51ec1029`.

**Decisions applied (lead's answers of section 11):**
- **A (Substitute bound):** a side's bound is the largest `floor(maxhp/4)` among its brought members. Applied in the C invariant (`dfi_substitute_cap`, `src/state/invariants.c`), the Python state model (`substitute_cap`, `tools/state_model/state_v3_model.py`), and the sweep rows of `tests/test_pool_tail.c` (four pinned rows moved). The negative case uses cap + 1; a passed Substitute within a brought member's quarter is valid.
- **B (Encore and Disable):** a pass whose copy would carry Encore or Disable on the passer is `E_UNSUPPORTED`. A pass with no reserve fails cleanly first, as in the pin, so it is not refused. Known gap: the pin stores a move id, the engine a slot; no reserve bytes.
- **C (Transform, Imposter, Illusion):** Transform and the Imposter ability are unmarked (guard in `tests/test_pool_g74.c`). The engine has no state for either, so their refusal path is not reachable. Illusion: a nonzero tail is refused by the state invariant (`DFI_INV_TAIL_SIDE`) until 0026 lands; the dispatch refusal is written but not reachable through a legal state.
- **D (Pursuit):** Pursuit is unmarked, so the skipped `BeforeSwitchOut` has no pool effect (section 3.4 above).

**Lead's requirements:**
- *View fold:* `g74_pass_confused` (Calm Mind; Umbreon's Alluring Voice confuses Espeon on turn 1; the pass on turn 2). `check_view_fold` in `tests/test_pool_g74.c` compares the state before and after the switch on both viewers: the receiver's stages (+1 SpA, +1 SpD) and confused flag equal the passer's; the receiver has not acted, and holds no Protect, charge, Flash Fire, locked slot or reserved flag. The confusion turns are not in the view (hidden), as for any foe.
- *Receiver refusal (cause 8):* `g74_pass_sub_damaged` (Umbreon's Substitute, damaged by two absorbed Icy Winds, passed to Ninetales). `check_receiver_refusal`: the presence bit is on side 0 position 1 for both viewers; `duoforge_battle_public_causes` has the SUBSTITUTE bit; `duoforge_battle_public` is `E_UNSUPPORTED` for both viewers. The HP stays in the engine (`tail.sides[0].positions[1].substitute_hp`) and is in no view. `battle_from_view` takes only a public state, which the record refuses first, so it cannot be reached with this state; that is the same refusal.

**Engine findings (both fixed):**
- The pin rolls a SECONDARY draw for a target that a Substitute absorbed (a `null` target, not `false`; `sim/battle-actions.ts:1336-1349`). The engine skipped it. Found by `g74_pass_sub_damaged` (step 2: tape 5 of 6). Fixed in the generic secondary loop; the Alluring Voice loop has the same condition, but Alluring Voice carries `bypasssub` (`data/moves.ts:290`), so that loop cannot reach an absorbed target.
- A failed Baton Pass printed its move line with the target shown. The pin prints `||[still]` with no target. Fixed with `dfi_still`; the no-reserve failure is checked before the refusals (the refusals had turned a clean failure into an `E_UNSUPPORTED`).

**Recorded battles (pool data, genders stated):** `g74_pass_confused`, `g74_pass_sub_damaged`, `g74_pass_no_reserve` (campaign battle fz_74_0 of run 74, recorded as a choice spec). The conformance count is now 704; tiebreak 704 battles and 3837 stops.

**Mutants (one exact edit each, rebuild, targeted tests; `scratchpad/g74/mutate.py`):** 10 mutants, 8 caught.
- Caught: M2 generic absorbed secondary draw removed (`g74_pass_sub_damaged`, conformance step 2); M3 stages not copied; M4 confusion not copied; M5 Substitute HP not copied; M6 bound back to the occupant's quarter (`pool_tail`, `pool_g74`); M7 Encore not refused; M8 no reserve check (`g74_pass_no_reserve`, conformance); M10 copy never runs.
- M1 (Alluring Voice's absorbed-draw condition removed): **survives, equivalent mutant.** Alluring Voice has `bypasssub`, so no battle can produce an absorbed target for it. Lead's requirement asked for a battle that catches it; none can exist, so I did not force one.
- M9 (Helping Hand and Follow Me not copied): **survives; open gap.** No committed battle uses Helping Hand before a pass. Recording one is the next step.

**Random campaign (seed 74, 300 battles, pairings DD, DE, ED, EE, teams D and E from the battles above):** final run PASS 276, DIVERGENCE 24, UNSUPPORTED 0 (the first run had 151 DIVERGENCE; the second 24 DIVERGENCE and 18 UNSUPPORTED; both causes are fixed, see above). Control with the registry teams A and B (AA, BB, AB, BA, 40 battles, same seed): PASS 40.
- The 24 remaining: 20 "tape not consumed exactly" at step 1 or 2 (speed-tie draws in the `each:Update` group with Sitrus Berry holders on both sides, e.g. `fz_74_4`); 4 `DUOFORGE_E_INVARIANT` (`fz_74_44`, `fz_74_164`, `fz_74_236`, `fz_74_284`, `fz_74_288`: a Substitute on Ninetales and Shadow Ball). Neither bucket contains a Baton Pass line in the failing step; the Substitute cap and the secondary change were excluded by experiment (the cap relaxed, and the generic loop reverted, both still fail). **Not determined**: whether these are pre-existing engine behaviour (speed ties with two item holders, the invariant on a Substitute break) or a G74 interaction. Open; for the lead.

**Quality gates:** full debug ctest 1099 of 1099 on `e058f894` (through `tools/ci/machine_lock.sh`, `DUOFORGE_PYTHON` set to the project venv, `DUOFORGE_PS_REFERENCE_DIR` the pinned checkout); source lint OK (78 files); MinGW `gcc -std=c17 -Wall -Wextra -Werror -Wmissing-field-initializers` clean on the changed sources. Node was on the PATH.

**Not done / open:** the 24 campaign divergences above; the M9 gap (Helping Hand recording); the no-reserve battle's coverage of the commanded case (unmarked); Transform and Imposter refusal paths (no state; guard only); the Illusion dispatch refusal (reachable only after 0026).

## 14. Addendum: classification of the campaign divergences, M9, final numbers (2026-10-10)

**Head** `6e150926` (the Helping Hand battle); this section is committed after it. The engine is unchanged from `e058f894` except the no-reserve order fix and the copy rules listed in section 13.

**Final random campaign** (seed 74, 300 battles, pairings DD, DE, ED, EE, teams D and E): PASS 276, DIVERGENCE 24, UNSUPPORTED 0. Control with the registry teams A and B (AA, BB, AB, BA, 40 battles): PASS 40.

**Classification of the 24 divergences.** The repro comparison ran on a scratch copy of `origin/main` (d4d19364, which has no Baton Pass: the pool row is UNMODELED there and the teams refuse setup), built in a separate directory from a `git archive` export. Nothing was changed on main.
- **Exact pre-existing reproduction (13 of 24, identical step and tape counts to the branch):** fz_74_4, 48, 60, 72, 80, 100, 108, 168, 188, 204, 240, 268 (tape not consumed) and fz_74_44 (E_INVARIANT). The battles contain no Baton Pass before the failing step; the prefix specs are `campaign3/cases/<name>/prefix_spec.json`.
- **Class-level reproduction on main (2 of 24):** fz_74_12 and fz_74_180. Their Baton Pass was replaced by a self-target marked move the species learns (Substitute, Calm Mind, Nasty Plot or Protect, chosen per set), so the battle changed. On main they stop at the same draw class (SPEED_TIE in `each:Update`; the 180 case as E_INVARIANT instead of the branch's tape stop).
- **Not classified (9 of 24):** fz_74_16, 52, 144, 156, 164, 236, 284, 288, 296. Their Baton Pass cannot be removed without changing the recorded choices (on replacement the recording is refused: `Can't pass: ... must make a move`), so no exact main repro exists. Their first stop (the draw the reference makes that the engine does not): `SPEED_TIE each:Update` for 16, 52, 144, 156, 288, 296; `SPEED_TIE switch-order` for 284; `RANDOM_TARGET action-speed` for 164; and for 236 the reference makes no draw at a Baton Pass switch while the engine makes one (tape exhausted at 0 of 0).

**Mechanism of the pre-existing divergence (not fixed in G74).** `dfi_update` in `src/combat/turn.c` (about lines 3372-3390) orders only the holders of Sitrus Berry, Lum Berry or Mental Herb (`dfi_each_order(r, bearers, ...)`). The pin's `eachEvent` (`sim/battle.ts:465-471`) sorts all active Pokemon with `speedSort` (`sim/battle.ts:429-445`), which draws the tie for every equal-speed pair, holders or not. The missing draws in fz_74_4 step 1 are at positions 18 and 20 of the reference tape: `SPEED_TIE each:Update` for `[P:p1a:0:, P:p2b:0:]` (no items), which the engine never draws. The E_INVARIANT of fz_74_44 is the same mismatch surfacing at the next draw: `src/rng/draw.c:16-18` (`dfi_draw_from_tape`) rejects a request whose site or bounds differ from the tape entry (engine: ACCURACY 0..100; tape: SPEED_TIE 0..2 in `each:Update`, index 5). The fz_74_44 repro on main gives `DUOFORGE_E_INVARIANT, tape 5 of 16` at step 2, the same as the branch.

**M9 (Helping Hand and Follow Me not copied): equivalent.** Recorded battle `g74_pass_helping_hand` (Ninetales uses Helping Hand on Espeon, priority +5; Espeon passes to Umbreon in the same turn). The copied volatile has duration 1 and ends at the residual of that turn. Umbreon does not act in that turn, Helping Hand boosts only its holder's moves, and no other reader of the flag exists in the pool. No later state or view can carry it: the step after the switch is at turn 2, and the view shows the flag only between the copy and the residual. The battle passes conformance and the replay (`diff_driver replay`, PASS 1), with the copy in place.

**Open:** the 9 unclassified divergences, in particular 236 (an extra engine draw at a Baton Pass switch, possibly G74) and 164 (a RANDOM_TARGET draw at action-speed, not yet checked against the pass). The `each:Update` tie mechanism is for the lead to assign.
