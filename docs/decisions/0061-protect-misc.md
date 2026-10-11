# 0061 - Baneful Bunker and Last Resort (step G94, decision 0015 letter 5cv)

Status: **Baneful Bunker** implemented (branch chris/expansion-g94-protect-misc, commits b5a9666f to 44d2dc0f); **Last Resort** implemented on the same branch on top, tests pending. Lane A builder H29. Pin: Pokemon Showdown b2cb775, Champions mod checked first (`data/mods/champions/` overrides none of the two moves).

## 1. Baneful Bunker (protect_kind 3)

- **Pin.** `data/moves.ts:985-1037`: Poison status move, priority 4, flags `noassist`, `failcopycat` (no `protect` flag), stalling move, `volatileStatus: banefulbunker`. Its condition is Protect's shape: `-singleturn|X|move: Protect`, `onTryHit` = `checkMoveBypassesProtect` then the Outrage reset, `-activate|X|move: Protect`, and for a contact move `source.trySetStatus('psn', target)`. Its only learner in the Champions pool is Toxapex (`data/mods/champions/learnsets.ts:12666`, 9M), whose abilities Limber (G39) and Regenerator are marked; Merciless is not, so a Merciless Toxapex is refused.
- **Engine.** `protect_kind` 3 (`DFI_PROTECT_BANEFUL_BUNKER`, `DFI_TAIL_PROTECT_KIND_MAX` 2 to 3, same schema 0x0503: the value 3 is in the byte that rev 3 defined). `dfi_run_protect` (shared stall counter) and `dfi_protect_targets`: the contact attacker is poisoned by `dfi_try_status(attacker, PSN, origin OTHER, holder)`. The pin passes the condition as the effect, so the line is a plain `-status|X|psn` (no `[from]`); an immune attacker (Poison or Steel) or one that has a status already gets no line.
- **Evidence.** Three recorded POOL battles (`g94_bunker_poison`: a contact Dragon Claw poisons, a Steel Iron Head is stopped silently; `g94_bunker_noncontact`: Earthquake stopped, no poison; `g94_bunker_already_poisoned`: a second contact hit sets nothing). Toxapex holds Lum Berry (Black Sludge is not in the pool).

## 2. Last Resort (lastresort)

- **Pin.** `data/moves.ts:10066-10081`: Physical, 140 power, contact, protect; `onTry` fails when the user has fewer than two move slots, and otherwise unless every slot other than its own Last Resort has `moveSlot.used`. The `used` flag is set by `deductPP` (`sim/pokemon.ts:892`, before the PP test) and cleared at switch-in (`sim/battle-actions.ts:140`). PP cannot give the answer: PP persist across switches while `used` does not.
- **State (rev-5 reserve, no schema bump).** `dfi_pool_tail.move_used`: a nibble per position in flat order, bit k = move slot k used since the occupant came in. Written in the rev-5 reserve bytes 8 and 9 (the other reserve bytes stay zero). Set where the engine deducts PP, cleared by `dfi_tail_clear_occupant`. The invariant: a bit only on an occupied position and below its move count.
- **Rule.** `dfi_last_resort_ok` (`turn.c`) at the TryMove stage, after the Armor Tail check, before the target and special dispatch. A failure is the move line with `[still]` and then `-fail|user` (`dfi_fail_still`; recorded in `g94_lr_basic`: `|move|p1a: Kangaskhan|Last Resort||[still]` and `|-fail|p1a: Kangaskhan`). PP is spent (deductPP runs before TryMove), the result is FALSE. An earlier reading of mine said the failure was silent; the recorded trace shows the two lines.
- **View (approved option c).** `volatiles2` bits 0 to 3 (`DUOFORGE_POSITION_EXT2_LAST_RESORT_USED_1..4`, slot k at bit k-1) are shown only for an occupant that has Last Resort in its current move slots (its open sheet, or a Transform copy). For every other occupant the bits are 0: they decide Last Resort only, and the state keeps them for every occupant (so a copy stays correct). The feature is `DUOFORGE_VIEWEXT_FEATURE_LAST_RESORT_USED` (44), in `DUOFORGE_VIEWEXT_RESERVE_OWN` (four entries). The bits are public: each use is a move line since the switch-in.
- **Encoder 5.** encode.c refuses a nonzero `volatiles2` for encoders below 6 (`DUOFORGE_E_UNSUPPORTED`). With option c that refusal happens only for a state with a Last Resort holder on the field.
- **Pair tests (to be run).** (1) a holder with used moves: the bits are visible and encoder 5 returns E_UNSUPPORTED; (2) a non-holder with used moves: the bits are 0 and encoder 5 runs. In C: `tests/test_pool_g94.c`.

## 3. Pins of the tables

Special ids: BANEFUL_BUNKER 101, LAST_RESORT 102, UNMODELED 103 (generator order, after G78). The pool canonical hash and the KP and KPD fingerprints are in `tests/test_pool_setup.c` and `tests/test_pool_tables.c` and `tools/state_model/state_v3_model.py`.

## 4. Edge cases of `moveSlot.used` (checked against the pin)

- **Transform.** `transformInto` replaces the moveSlots with new virtual slots (`used: false`, `sim/pokemon.ts:1305-1323`). Transform is unmarked (no manifest bit), so setup refuses it; a guard test checks the mark.
- **Called moves.** Sleep Talk, Copycat, Spite, Eerie Spell and Instruct are unmarked (refused by setup). Metronome, Mirror Move, Assist, Mimic and Sketch have no row in the pool (no `DFI_MOVE_*`), so nothing can select them. The pin's `useMove` for a called move deducts PP of the called move's slot (`battle-actions.ts:282`); this cannot arise here.
- **Encore.** A forced move is an ordinary move action (no lockedmove): deductPP runs, so `used` is set on the encored slot. Encore is marked (`DFI_MOVE_ENCORE`), so the engine's normal PP path covers it; no separate rule.
- **Struggle.** No slot (`move_slot` 4 is not below `DUOFORGE_MAX_MOVE_SLOTS`): no bit, and the pin's `deductPP` finds no slot.
- **Pressure.** The extra PP is taken from the user's own slot, which `used` already covers (`battle-actions.ts:482`); the engine's Pressure step does not touch the bits.
- **PP 0 and disabled slots.** deductPP sets `used` before its PP test (`sim/pokemon.ts:892`); the engine sets the bit before its `pp == 0` check, as the pin. A disabled slot is not in the request, so it is never used.
- **Locked turns (Outrage, charge second turns).** No deductPP (`battle-actions.ts:286-291`): no bit, as the engine's `!locked && !lock_move` block.
- **Switches.** Every change of occupant (switch-out, faint replacement, drag, Baton Pass, Revival) clears the nibble (`dfi_tail_clear_occupant`); the pin resets `used` in `switchIn` (`battle-actions.ts:140`).
- **Refusals.** None needed beyond setup's manifest gate: the copying and calling moves above are unmarked or have no row.

## 5. Where the used flags live: Ally Switch, Baton Pass, switches and Transform

The flags belong to the Pokemon's `moveSlots` (the objects), not to the field position. That decides how they move.

- **Ally Switch** (`data/moves.ts:302-340`, marked in batch 7 as G80): its `onHit` calls `this.swapPosition(pokemon, newPosition, ...)`, which puts the two Pokemon objects into each other's `side.pokemon` and `side.active` entries and sets `position` (`sim/battle.ts:1588-1607`). The objects, and with them `moveSlots[].used`, go with the Pokemon. So for the engine's per-position nibble (`move_used`, bytes 8-9) an Ally Switch must exchange the two positions' nibbles. Until G80 (the central `dfi_swap_position_state`) is on this branch, the bytes are not moved and this step is not complete for Ally Switch: a field test with the swap and the nibbles goes into the function G80 builds, after its merge (batch 8).
- **Baton Pass** (`data/moves.ts:1092`, `selfSwitch: 'copyvolatile'`): the passer's replacement comes in through `copyVolatileFrom` (`sim/pokemon.ts:1246-1266`). That copies volatiles and boosts; it does not touch `moveSlots`. The replacement is a normal switch-in, so `switchIn` resets its `used` flags (`sim/battle-actions.ts:140`). The passer keeps its own flags off the field. In the engine the incoming occupant gets a cleared nibble (`dfi_tail_clear_occupant` on the change of occupant), and the passer's nibble ends with it: the same result.
- **Switch-out.** `clearVolatile` (`sim/pokemon.ts:1508-1519`) sets `moveSlots = baseMoveSlots.slice()`: a shallow copy, so the `used` objects survive it. Only `switchIn` resets them. The engine clears at the change of occupant, which is the same event.
- **Transform.** `transformInto` replaces `moveSlots` with new virtual slots (`used: false`, `sim/pokemon.ts:1305-1323`). Transform is unmarked.

**Probes (scratch scripts, run against the pin b2cb775; not committed).**
1. Switch-out and switch-back (`g94_lr_switch_reset`'s plan, the pin's own Battle, the flags printed after each turn): after four turns Kangaskhan shows `lastresort:U doubleedge:U protect:U earthquake:U`. When Chesnaught comes in (turn 5) the off-field Kangaskhan still shows all four `U`. When Kangaskhan switches back in (turn 6) its flags read `-` on the first line of that turn, and on turn 7 only `lastresort:U`.
2. Transform (a scratch Ditto that uses Protect, then Transform on Milotic): after turn 1 the slot reads `protect:U`; after turn 2 the Ditto has one slot, `coil:-`, the new object (Transform itself is unmarked: this is the pin's behaviour only).

The recorded battle `g94_lr_switch_reset` shows the same reset from the protocol side: Last Resort succeeds on turn 4, and after the switch-back it fails (`-fail|p1a: Kangaskhan`).
