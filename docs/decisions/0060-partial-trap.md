# 0060 - The partial trap (G90): Bind, Wrap, Fire Spin, Sand Tomb, Snap Trap, Infestation

Status: **in progress** (H26, lane A batch 7, step 5cs). The design was approved by the coordinator on 2026-10-11 (the volatile id, the event shapes, the silent ends, the state, the information safety of section 6). Open points are listed in section 9.

## 1. Problem

Six moves of the Reg M-C pool apply the volatile `partiallytrapped` on a hit (`volatileStatus`, no `onTryHit`). The volatile deals residual damage every turn and stops the target from switching. Blocked teams: Infestation alone blocks 30 of the VGCPastes waiting teams (2026-10-10).

| Move | `data/moves.ts` | Type (Champions) | Category | BP | Accuracy |
|---|---|---|---|---|---|
| Bind | 1337 | Normal | Physical | 15 | 85 |
| Wrap | 21081 | Normal | Physical | 15 | 90 |
| Fire Spin | 5459 | Fire | Special | 35 | 85 |
| Sand Tomb | 15714 | Ground | Physical | 35 | 85 |
| Snap Trap | 17071 | Steel (`data/mods/champions/moves.ts:919`, base Grass) | Physical | 35 | 100 |
| Infestation | 9595 | Bug | Special | 20 | 100 |

All six: target `normal`, `volatileStatus: 'partiallytrapped'`, no secondary.

## 2. The pin

- **Volatile** (`data/conditions.ts:222-258`). `durationCallback`: 8 with a Grip Claw on the source, else `this.random(5, 7)` (5 or 6). `onStart`: `-activate|T|move: X|[of] S`, and `boundDivisor` = 6 when the source holds Binding Band at the start, else 8. `onResidualOrder: 13`. `onResidual`: when the source is not active, fainted or newly switched in (`!source.activeTurns`), the volatile is removed with `-end ... [partiallytrapped] [silent]` and nothing is dealt; otherwise `damage(baseMaxhp / boundDivisor)`. `onEnd`: `-end|T|move: X|[partiallytrapped]`. `onTrapPokemon`: `tryTrap()` only while the source is active.
- **Duration** (`sim/battle.ts:516-523`): the residual decrements the duration first; at 0 the end runs and the residual of that turn deals no damage.
- **Start order** (`data/mods/champions/scripts.ts:374`, `sim/battle-actions.ts:1236-1238`, `sim/pokemon.ts:1969-2030`): damage of the hit, then `runMoveEffects` (the volatile), then the secondaries (none here). `addVolatile` returns false for a fainted target (no draw, no line) and for a target that already has the volatile (no draw, no line, no reset; the damage stands, and the move's result stays the damage number by `combineResults`, `battle-actions.ts:1561-1573`).
- **Substitute** (`data/moves.ts:18335-18340`): its start removes `partiallytrapped` silently. A Substitute absorbs the hit (these moves do not bypass it), so the volatile is not added.
- **Trapped flag** (`sim/battle.ts:1726`, `sim/pokemon.ts:1607-1611`): recomputed at each turn boundary; `tryTrap` fails for a Ghost-type target (`data/typechart.ts:204`, `trapped: 3`), which then still takes the residual damage. A trapped Pokemon cannot choose a voluntary switch in a move request (`sim/side.ts:985-993`). Forced switches (Eject Button, Red Card, drags) and the trapped user's own U-turn (`sim/battle-actions.ts:1311`, no `trapped` check) are not blocked.
- **Gen 1 clauses** (`battle.ts:1646`, `side.ts:691`, `pokemon.ts:1098`) do not apply to gen 9.

## 3. The state (one reserved byte, no new bit)

The tail fields of tail rev 5 hold the trap: `trap_turns` (the remaining turns, 1 to 6 with d in {5, 6}), `trap_source` (flat position of the trapper + 1), `trap_move` (move id + 1), `trap_band` (0/1, the band of the start). The position bit `DUOFORGE_POSITION_EXT_PARTIAL_TRAP` (0x100) and the view feature `DUOFORGE_VIEWEXT_FEATURE_PARTIAL_TRAP` (18) already exist.

**The elapsed count (hidden counters, section 6a).** `trap_elapsed` is the residual phases the trap has been through (0 to 5 while it is up, 0 without it). It is the first of the four reserved bytes of each position's rev 4 block (`DFI_ENC_TAIL_POS_TRAP_ELAPSED_OFF` = 32; the block stays 36 bytes, the reserved count of the tail goes from 45 to 41). The struct `dfi_tail_pos` gets the field and one explicit zero pad byte (`pos_pad`), because its data is 35 bytes and the uint16 members would round it to 36 with an implicit pad; the three size asserts of `state_codec.h` count the pad.

**Source leaves (encoding of this step).** The pin ends the trap silently at the residual once its source is not active. The engine keeps only a flat position, so when the trapper's position is vacated or refilled (`dfi_tail_clear_occupant`, `src/state/identity.c`), every trap whose `trap_source` is that position gets `trap_source = 0`, keeping `trap_turns`, `trap_move` and `trap_band`. The residual then ends it silently. The re-hit window is exact: an existing trap (turns != 0) still refuses a new start, as the pin does. The invariant of the source changes from "turns zero iff source zero" to "turns zero implies source zero". This is the only change of the tail invariants (approved by the coordinator, 2026-10-11).

**Why source 0 exists only within a turn (pin).** The residual handler of the partial trap runs at order 13 (`data/conditions.ts:222-258`). The residual loop checks `handler.state.duration` first (`sim/battle.ts:516-523`), then `onResidual` checks `!source.isActive || source.hp <= 0 || !source.activeTurns`, and when that holds it removes the volatile with `-end ... [silent]` (`data/conditions.ts:236-241`). Every residual of a turn runs before the end-of-turn replacements (REPLACEMENT boundary, after the residual) and before the next turn's TrapPokemon (`sim/battle.ts:1726`). So a trap whose source left during the turn (a PIVOT or any switch within the turn) is ended silently by that turn's residual; no trap with turns and no source reaches a TURN or a REPLACEMENT boundary. The engine keeps this as a state invariant (`src/state/invariants.c`, mirrored in `tools/state_model/state_v3_model.py` `check_tail`): at a TURN or REPLACEMENT boundary, an occupied position with `trap_turns != 0` must have `trap_source != 0`. C test `test_source_leaves` in `tests/test_pool_g90.c` sets the source to 0 at the turn boundary after the Fire Spin and checks that the state is refused (E_INVARIANT), and restored valid. At a PIVOT boundary the source 0 state is valid (the residual has not run yet).

## 4. Public values

- `DUOFORGE_VOLATILE_PARTIAL_TRAP` = 12 (the lead's assignment from the lane A block; 12 was released by G84's Curse).
- Start: `ACTIVATE` with cause `MOVE`, id2 = the move, other = the source (no new cause).
- Residual damage: `DAMAGE` with cause `MOVE`, id2 = the move, other none (no new cause). The converter tells it from other `MOVE` damages by the `[partiallytrapped]` marker of the line (a named rule in `tools/reference/trace_to_c.py`).
- End of the duration: `VOLATILE_END` with detail `PARTIAL_TRAP` and id = the move (the end line names the move).
- Silent ends (the source left, a Substitute, the residual with a fainted source): no event; the view bit clears from the state.
- The elapsed count: `DUOFORGE_POSITION_EXT2_TRAP_ELAPSED_BIT0..BIT2` = 0x10, 0x20, 0x40 (bits 4 to 6 of `duoforge_observation_ext.volatiles2`, the POSITION_EXT2 word; bits 0 to 3 belong to another lane). Its feature is `DUOFORGE_VIEWEXT_FEATURE_TRAP_ELAPSED` = 45 (lane A block, HS registry), listed once in `DUOFORGE_VIEWEXT_RESERVE_OWN` for each of the three bits, with the family `DUOFORGE_VIEWEXT_FEATURE_VOLATILES2` (60). Both features go into the support mask (`support_manifest.c`). Encoder 5 refuses a state with an active trap (`encode.c`: a nonzero `volatiles2` is EncoderAwaitingBit below version 6), as the HS registry accepts.

## 5. Draws

One draw site, `DFI_SITE_PARTIAL_TRAP_TURNS` = 32, `random(5, 7)`, drawn only when the volatile starts (not for a re-hit, not for a fainted target). The converter's site table has the same number (HS range). No draw for the band.

## 6. Information safety (approved 2026-10-11)

- `trap_turns` is a drawn counter: the view writes `DUOFORGE_VIEW_HIDDEN` into it for **both** viewers, the owner included (the drawn value is never shown, decision 0007).
- The presence bit is public. `trap_source`, `trap_move` and `trap_band` are public (the `-activate` line names the source and the move; the band is the source's held item, open information).
- The rebuild (`duoforge_battle_from_view`) of a trapped view is no longer refused: it determinizes the hidden turns (section 6a).
- Decision 0018 row 8 is corrected accordingly (done in this step).

## 6a. Hidden counters (lead decision, 2026-10-11)

- Derivation of `trap_elapsed` (the public counter, engine and view): 0 at the start (`-activate`), +1 at each residual phase while the trap is up (the phase that ends it at 0 clears it), 0 at the end and whenever the trap leaves the position (the occupant's tail is cleared). Saturation at 7 in the code; a legal state never exceeds 5 while the trap is up, because the duration is at most 6 (invariant: `trap_elapsed <= 5` with `trap_turns != 0`, `trap_elapsed == 0` without).
- Posterior of the hidden turns. The duration `d` is `random(5, 7)` (`data/conditions.ts:222-228`, the pin), so `d` is 5 or 6 at 1/2 each. The public view shows `trap_turns = d - e` with the elapsed count `e`, and the trap is up, so `d > e`. Consistent durations: both for `e` at most 4 (1/2 : 1/2), only 6 at `e = 5` (one turn left), none at `e >= 6`, which is refused (`DUOFORGE_E_MALFORMED`: a legal view never shows it).
- Grip Claw (`d = 8` on the source) is not in the Champions pool (`data/mods/champions/items.ts:422`, `isNonstandard: "Past"`), so no trapper can hold it and no duration 8 is drawn; the pool data refuses the item at battle creation, and the view has no item of the source to decide it.
- Sleep and confusion stay refused by the rebuild (E_UNSUPPORTED, as before); the same method could apply later, a decision of the owner.
- The determinized turns are not compared with the truth in the tests (they are hidden); the tests check the consistency set, `e = 5` giving 1, `e = 6` refused, and the public fold of `e` into POSITION_EXT2 for both viewers (`tests/test_pool_g90.c`, `test_elapsed_determinized`).
- Open: the draw of the duration in the rebuild comes from the world's RNG, which `duoforge_battle_from_view` seeds with a constant (0, 0). A constant seed makes the choice the same bit for every view, so it is not a 1/2 : 1/2 posterior across worlds. See section 9, point 3.

## 7. Engine (summary)

- Start: in the damage path of the move, after the damage of each hit, for each hit target with no trap and a standing target: draw, set the four fields, emit the ACTIVATE line.
- Residual: an entry of order 13 in the residual list; the duration goes down first, the end at 0 without damage, the silent clear when the source is gone, else the damage `floor(baseMaxhp / divisor)`, at least 1.
- Trapped flag: a function of the state at the move request (`trap_turns != 0 && trap_source != 0 && target not Ghost`); a trapped occupant gets no voluntary switch option, and a switch choice for it is refused by the existing choice validation.
- Substitute start clears the four fields silently for its user.
- Baton Pass copies the fields already (`dfi_pass_take` / `dfi_pass_give`).

## 8. Refusals and drops

- Grip Claw: dropped (`data/mods/champions/items.ts:422`, `isNonstandard: "Past"`). The 8-turn branch is therefore not modelled; a state that asks for it is refused.
- Whirlpool, Magma Storm, Thunder Cage: the same class, not in this step.

## 9. Open points for the lead

1. The source-left encoding of section 3 (trap_source = 0 while the trap lives on) changes one tail invariant. If the lead prefers a stored identity, that needs a byte.
2. Test counts and mutants: see the step entry 5cs in decision 0015 when the step is complete.
3. The posterior draw of section 6a. The lead's spec says "from the world RNG", but `duoforge_battle_from_view` seeds that RNG with (0, 0) and the view zeroes the RNG bytes, so the draw is one fixed bit for every view, not a sample of the posterior. The sleep and confusion counters of the same function draw from the hypothesis (`duoforge_hypothesis`, one word per hidden value), which the caller samples. The matching design is one word per trapped position in the hypothesis (a public struct change: the `reserved2[4]` bytes would become `trap_pick[4]`, and the revision would move). Decision needed before the push; the code now uses the world RNG as specified.
