# 0044 - Ally Switch, Psych Up and Howl (lane A batch 5, G80)

Status: **proposal, awaiting the lead** (builder H17, 2026-10-10). No engine code for Ally Switch until the answers of section 6 are in. Psych Up and Howl need no new public value (section 7) and are built meanwhile.

Pin: Pokemon Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`, read only). Champions overrides checked first: `data/mods/champions/moves.ts` has an entry for `howl` (line 512) and none for `allyswitch` or `psychup`. Doubles only: the engine's format is doubles, so the triples and format checks of Ally Switch (`data/moves.ts:316-320`) are inert.

## 1. The pin

**Ally Switch** (`data/moves.ts:302-357`): Psychic, Status, accuracy true, priority 2 (`:309`), flags `metronome` only (no `protect`, `snatch`, `mirror`), target self.

- **onPrepareHit** (`:311-313`): `pokemon.addVolatile('allyswitch')`, the user's own volatile.
- **Condition `allyswitch`** (`:332-357`): duration 2, `counterMax` 729 (`:334`), `onStart` sets counter 3. `onRestart` (`:338`) draws `randomChance(1, counter)` (`:343`); on a failed roll it deletes the volatile and returns false; on success it multiplies the counter by 3 while it is below 729 and resets the duration to 2. So the counter is 3^k, k from 1 to 6: the first use is 3, the second consecutive use succeeds with 1/3, the third with 1/9, and so on. The shape is that of the Protect stall condition (`data/conditions.ts:439-462`, counterMax 729 at `:443`, the draw at `:452`), but it is a **separate volatile with its own counter**: it does not share the stall counter of Protect, King's Shield or Wide Guard.
- **Refusal of the volatile (consecutive use).** The condition prints nothing. A failed roll: `singleEvent` returns false (`sim/battle.ts:651` returns `relayVar` only for an undefined result), `addVolatile` returns it on the restart path (`sim/pokemon.ts:1983-1985`), the move's PrepareHit gate fails (`sim/battle-actions.ts:590-598`), which prints `-fail|X` with no move name and sets `[still]`. The move ends there. The volatile is gone, so the next use starts at 3 again.
- **onHit** (`:314-331`): it fails when there is no partner in the other slot (`:323`) or the partner is fainted (`:324`); the pin prints `-fail|X|move: Ally Switch` (`:326`), `[still]` (`:327`), and returns NOT_FAIL (`:328`). The counter already advanced in PrepareHit, so this failure keeps the volatile and its counter.
- **The swap** (`:330`): `swapPosition(pokemon, newPosition, '[from] move: Ally Switch')`, with `newPosition` = the other slot (`:322`).

**swapPosition** (`sim/battle.ts:1588-1607`): prints `|swap|` with the user, the new position and the attribute (public; `this.add` is not split). Then it swaps `side.pokemon[pos]` and `side.pokemon[newPosition]` (the party order, `:1598-1599`), `side.active` and `pokemon.position`. Then `runEvent('Swap', target, pokemon)` for the arriving ally (now at the user's old slot), then `runEvent('Swap', pokemon, target)` for the user (`:1604-1605`).

**Who reacts to Swap.** Only slot conditions in the pin: Healing Wish (`data/moves.ts:8348-8385`, `onSwap` at `:8370`: heals and clears a damaged or statused arrival, removes the slot condition) and Lunar Dance (`data/moves.ts:10585`, same shape). Slot conditions are collected for a Pokemon at its current position (`sim/battle.ts:1139-1140`). No ability or item has an `onSwap` in the pin.

**Targets resolve by slot.** `getLocOf` is absolute per side, from the target's position and its half (`sim/pokemon.ts:784-789`); `getAtLoc` returns the occupant now (`:770`). `getTarget` (`sim/battle.ts:2437`) takes the occupant at execution, so a queued move aimed at a slot hits whoever stands there after the swap. Exceptions in the pin:
- `tracksTarget` (`sim/battle.ts:2437-2450`; the moves are Sky Drop `data/moves.ts:16693` and Snipe Shot `:17148`). Snipe Shot is in the pool and unmodelled (`src/data/pool_tables.c:6945`, "field tracksTarget"); a row that is unmodelled cannot appear in a battle, so this stays out of G80.
- `smartTarget` (Dragon Darts, `data/moves.ts:4128`; `sim/battle.ts:2451-2453`): the current occupant, or a random target when there is none. Its comment (`:2447-2449`) says Dragon Darts can target its own user after Ally Switch. This is G78's rule; G80 must hand the re-resolved target to it.

**Follow Me** (`data/moves.ts:6039-6074`): `onFoeRedirectTarget` returns `this.effectState.target` (`:6062-6066`), the Pokemon that used it, not a slot. The redirection follows the Pokemon.

**Pokemon references.** Partial trap: `source` is the trapper's Pokemon object (`data/conditions.ts:235`, `:250`). Leech Seed: `source` is the seeder's Pokemon object (`data/moves.ts:12980`). Lockedmove: `targetLoc` is a slot location (`data/conditions.ts:309`).

## 2. What moves with the Pokemon and what stays with the slot

The engine stores a slot's Pokemon state in `dfi_active_slot` (`src/state/battle_internal.h:137-152`) and `dfi_tail_pos` (`:297-338`). A swap exchanges the two slots' Pokemon state, and leaves the slot state where it is.

| Field (engine) | Pin | On Ally Switch |
|---|---|---|
| `occupant`, `activation_id`, `stages[7]`, `flags` (incl. `DFI_VOL_FOLLOW_ME`, `DFI_VOL_PROTECT`), `stall_level/turns`, `confusion_turns`, `charge_turns`, `locked_move`, `move_actions`, `switch_flag` | the Pokemon's volatiles and fields | **moves with the Pokemon** |
| `dfi_tail_pos` fields: `substitute_hp`, `last_move`, encore, throat chop, heal block, perish, taunt, disable, imprison, must_recharge, trap fields, yawn, focus_energy, stockpile, charge, glaive_rush, protect_kind, move_result, single_turn, hits_taken, ability_state, lock_turns, `position_flags` bits 1-3 (Alluring Voice raised flag, Dragon Cheer stage) | the Pokemon's | **moves with the Pokemon** |
| `position_flags` bit 0 (Healing Wish, G76) | slot condition `healingwish` (`sim/side.ts:464-510`) | **stays with the slot** |
| `locked_target`, queued move `target` (flat slot) | slot location (`data/conditions.ts:309`; `getTarget`) | **stays with the slot**; the occupant is resolved at execution |
| side conditions: Wide Guard, Quick Guard, Tailwind, Reflect, Light Screen, hazards | `sideCondition` | **stays** (not per slot) |
| `trap_source`, `leech_seed_source` (flat position + 1 of another Pokemon) | the source is a Pokemon object (`data/conditions.ts:235`, `data/moves.ts:12980`) | **relinked**: a swapped source gets its new flat position in the trapped or seeded Pokemon's field |
| `party_order` entries 0 and 1 (the two actives) | `side.pokemon[0]`, `[1]` (`sim/battle.ts:1598-1599`) | **swapped** (the template is `dfi_party_switch`, `src/combat/turn.c:7847`) |
| queue records of the two Pokemon (`slot`, `activation_id`) | the action holds the Pokemon (`action.pokemon`) | **the record's slot follows the Pokemon** (`activation_id` binds it); the target does not change |
| Revival Blessing slot condition | slot (`sim/side.ts:932-965`, `sim/pokemon.ts:1183`) | stays; not reachable (a fainted partner refuses the swap) |
| Future Sight (reserved `future_sight`, not used) | slot target | out of scope for G80 |

## 3. Public values

- **Event `SWAP`, proposed kind 48** (central numbering, HauptSession): `position` = the user's slot before the swap, `other` = the slot it moved to, cause MOVE with id2 = Ally Switch. Both players get the event (the `|swap|` line is public). The foe's view changes through the occupants, which the state already holds; no view field is added. **Ask.**
- **FAIL (existing kind 13)**, two shapes:
  - (a) the consecutive refusal `-fail|X` (no move name, `[still]`): FAIL, no cause, detail 0;
  - (b) `-fail|X|move: Ally Switch` (no partner, or the partner fainted): FAIL with cause MOVE, id2 = Ally Switch, detail 0. The FAIL comment (`include/duoforge/duoforge.h:1002-1007`) gives the detail meaning only with a cause, and it does not define a detail for "fail of this move". **Ask: is detail 0 with cause MOVE the right representation?**
- **No volatile id.** The `allyswitch` condition prints nothing (no START or END line), so DUOFORGE_VOLATILE_* gets nothing new.
- **Hidden counter.** The level k and the turns are not shown. The foe sees the outcome only (swap or FAIL). The public record must not carry them on the foe's side, as the stall level is not carried. **Ask: confirm the masking rule** (how `stall_level` is masked in `src/state/observation.c` / the public record).
- **Healing Wish** (G76, not on main): when it lands, its Swap handler's HEAL line (`-heal`, cause MOVE, id2 Healing Wish) is an existing kind.

## 4. State

- **One new tail byte per position, `ally_switch`** (tail rev 5 reserve, lane A/B shared 16-byte reserve: **ask**): 0 = no volatile; else `(k << 2) | t`, k = 1..6 (the counter is 3^k), t = 1..2 (turns left). Maximum 26. Invariants: the byte is 0 exactly when there is no volatile; k is 0 only then; t is 1 or 2 when nonzero. It is cleared with the occupant (`dfi_tail_clear_occupant`) and moves with it on a swap.
- Why not `position_flags`: bits 4-7 are four bits, and k and t need five.
- **Draws.** One `random(3^k)` for every restart, drawn at the PrepareHit (the pin's `randomChance(1, counter)`, `data/moves.ts:343`). The trace converter needs its own draw label (internal, not public): `tools/reference/trace_to_c.py`.
- **Duration.** The volatile's duration of 2 counts down at the residual (`data/moves.ts:338-357` reset; the countdown is the standard duration handler). Whether the pin draws a SPEED_TIE for the end of this duration next to another handler of the same holder (as decision 0031 found for the Protect and stall pair) is open: the evidence battle decides it.

## 5. Refusals

- None needed in the doubles-only engine (the format and triples checks are inert).
- **Illusion (0026, lane B, not on main).** A swap moves a disguised holder. The foe's fold of `|swap|` must follow the disguise's shown row, and the per-slot `ill_pending` counts must move with the holder. Until 0026 lands, a battle with both Illusion and Ally Switch cannot exist (the Illusion row is not on main). **Ask: does G80 wait for 0026, or does 0026 carry the swap fold?**
- **Healing Wish** (G76, same batch): the swap calls the Healing Wish Swap rule for both arrivals (ally first, then the user). The function is G76's; G80 calls it. G80's Healing Wish battles come after G76 is merged.

## 6. Questions for the lead (answers needed before engine code)

1. Event kind 48 `SWAP`, shape as in section 3? (Or another number.)
2. FAIL representation for `-fail|X|move: Ally Switch`: cause MOVE, id2 Ally Switch, detail 0?
3. The new tail byte `ally_switch` per position (2 bytes): from which part of the lane A/B reserve?
4. The masking rule for the hidden counter on the foe's side.
5. Healing Wish's Swap rule: G76 provides the function; G80 calls it. Same batch, so the merge order matters.
6. Illusion: G80 waits for 0026, or the fold is in 0026?
7. Psych Up and Howl: no new value (section 7). Please confirm.

## 6a. Lead's answers (2026-10-10)

1. Event SWAP (kind 48): pending HauptSession, who assigns event numbers. No code for it yet.
2. FAIL with cause MOVE, id2 Ally Switch, detail 0: approved.
3. The tail byte `ally_switch`: pending HauptSession. The lead asked for 4 bytes (one per position) from the shared rev-5 reserve; position_flags has only bits 5-7 free for this. No byte is taken yet.
4. The hidden counter is masked for the foe exactly as stall_level is. Confirmed.
5. Healing Wish's slot bit stays with the slot. G76 and G80 are in the same batch; the integrator sets the order. The G80 side must work whether G76 is present or not: it refers to the position_flags bit 0 constant (DFI_POSFLAG_HEALING_WISH, on main).
6. Illusion: G80 does not wait for 0026. An Ally Switch is refused while either partner is a possible Illusion holder, with a named cause and a test. 0026 brings the fold later.

Ally Switch engine code stays blocked on items 1 and 3. Psych Up and Howl proceed.

## 7. Psych Up and Howl (rows 2 and 3)

To be written after the research for each row (commit to follow). Psych Up (`data/moves.ts:14211`) copies the boosts and the crit-stage volatiles of the target. Howl (`data/mods/champions/moves.ts:512`, `data/moves.ts:9009`) is a sound move with `target: allies`, Attack +1.

## 8. Evidence plan (Ally Switch; recorded POOL battles, genders stated)

- `g80_allyswitch_basic`: the swap, the `|swap|` line, the party order, and a foe's move aimed at the slot that now holds the other Pokemon.
- `g80_allyswitch_repeat`: three consecutive uses (the draws at 1/3 and 1/9), then a refused roll (`-fail`, `[still]`), and the restart at 3.
- `g80_allyswitch_expire`: two turns without a use: the counter starts again at 3.
- `g80_allyswitch_partner_fainted`: the `-fail|X|move: Ally Switch` line, with the counter already advanced.
- `g80_allyswitch_follow_me`: a Follow Me holder swaps; the redirection follows it.
- `g80_allyswitch_trap`: the trapper swaps; the trapped foe's trap source follows it.
- `g80_allyswitch_protect_stall`: Protect's stall counter is untouched by Ally Switch.
- `g80_allyswitch_spread`: a spread move after a swap (the damage draw order follows the slot order).
- Cross-row (after G76 and G78 are merged): Healing Wish heals the arrival; Dragon Darts that targets its own user after the swap.

Mutants (one edit each, in `src/combat/turn.c`): the counter not restarted, a failed roll not removing the volatile, the swap not moving the Pokemon state, the Healing Wish bit moving, the trap source not relinked, the party order not swapped, the Swap rule for the wrong arrival, the event not emitted. Campaign: about 300 random battles with Ally Switch users, Follow Me, traps and Dragon Darts (the lead's batch campaign).

## 9. Implementation status (builder H17, 2026-10-10; unverified, tests pending)

- **Event 49 SWAP** (lead's allocation) and **event 50 COPY_BOOST** (HauptSession): header, `layout_dump.c`, `_layout.py`, converter branches in `tools/reference/trace_to_c.py` (`|swap|` only as Ally Switch's own line, `-copyboost` only as Psych Up's), refusal tests.
- **Tail**: the Ally Switch byte per position in reserve bytes 4..7 (lead's allocation; bytes 0..3 are lane B's, 8..15 free). Codec round trip, invariant (zero, or level 1..6 with turns 1..2 on a standing occupant), an explicit pad byte, reserved count 45 -> 41, sweep rows 336..339 = `{12, 0, 243, 0, 0, 0, 0, 0}` from the Python model.
- **Draw**: `DFI_SITE_ALLY_SWITCH` 23 (count 24) for the consecutive roll.
- **Engine**: `dfi_psych_up`, `dfi_ally_switch_prepare`, `dfi_ally_switch_swap`, `dfi_run_ally_switch` (`src/combat/turn.c`), the residual countdown of the volatile after the stall countdown.
- **Pool**: Psych Up (special PSYCH_UP 97), Ally Switch (special ALLY_SWITCH 98), Howl (the allies class with PRIMARY_TARGET, the Charm role). Canonical hash `e8f92562...`.

**Healing Wish slot bit interaction: with the Healing Wish step.** Position bit 0 (`DFI_POSFLAG_HEALING_WISH`) stays with the slot in the swap. The Swap rule of Healing Wish (data/moves.ts:8348-8385, onSwap at :8370) belongs to the Healing Wish step, not to G80: no hook is called here. Known issue for that step: `dfi_tail_clear_occupant` (`src/state/identity.c`) clears the whole position, bit 0 included; the Healing Wish step must keep bit 0 across a switch-out, because the pin's slot condition outlives its occupant.

**Open, to check with a recorded battle:** the residual countdown of the allyswitch volatile sits after the stall countdown in the per-position residual loop. The pin's duration end is a no-order, no-callback handler; whether the reference draws a SPEED_TIE for it next to another handler of the same holder (as decision 0031 found for the Protect and stall pair) is not yet known. A battle in which such a tie can occur must be recorded and checked (not done: needs the machine lock).

**Not verified yet:** the layout dump test, every C test for these rows, the recorded battles, the mutants, the campaign and the full ctest (all waiting for the machine lock).
