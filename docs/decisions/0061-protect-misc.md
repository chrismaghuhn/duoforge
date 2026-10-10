# 0061 - Baneful Bunker and Last Resort (step G94, decision 0015 letter 5cv)

Status: **Baneful Bunker** implemented (branch chris/expansion-g94-protect-misc, commits b5a9666f to 44d2dc0f); **Last Resort** implemented on the same branch on top, tests pending. Lane A builder H29. Pin: Pokemon Showdown b2cb775, Champions mod checked first (`data/mods/champions/` overrides none of the two moves).

## 1. Baneful Bunker (protect_kind 3)

- **Pin.** `data/moves.ts:985-1037`: Poison status move, priority 4, flags `noassist`, `failcopycat` (no `protect` flag), stalling move, `volatileStatus: banefulbunker`. Its condition is Protect's shape: `-singleturn|X|move: Protect`, `onTryHit` = `checkMoveBypassesProtect` then the Outrage reset, `-activate|X|move: Protect`, and for a contact move `source.trySetStatus('psn', target)`. Its only learner in the Champions pool is Toxapex (`data/mods/champions/learnsets.ts:12666`, 9M), whose abilities Limber (G39) and Regenerator are marked; Merciless is not, so a Merciless Toxapex is refused.
- **Engine.** `protect_kind` 3 (`DFI_PROTECT_BANEFUL_BUNKER`, `DFI_TAIL_PROTECT_KIND_MAX` 2 to 3, same schema 0x0503: the value 3 is in the byte that rev 3 defined). `dfi_run_protect` (shared stall counter) and `dfi_protect_targets`: the contact attacker is poisoned by `dfi_try_status(attacker, PSN, origin OTHER, holder)`. The pin passes the condition as the effect, so the line is a plain `-status|X|psn` (no `[from]`); an immune attacker (Poison or Steel) or one that has a status already gets no line.
- **Evidence.** Three recorded POOL battles (`g94_bunker_poison`: a contact Dragon Claw poisons, a Steel Iron Head is stopped silently; `g94_bunker_noncontact`: Earthquake stopped, no poison; `g94_bunker_already_poisoned`: a second contact hit sets nothing). Toxapex holds Lum Berry (Black Sludge is not in the pool).

## 2. Last Resort (lastresort)

- **Pin.** `data/moves.ts:10066-10081`: Physical, 140 power, contact, protect; `onTry` fails when the user has fewer than two move slots, and otherwise unless every slot other than its own Last Resort has `moveSlot.used`. The `used` flag is set by `deductPP` (`sim/pokemon.ts:892`, before the PP test) and cleared at switch-in (`sim/battle-actions.ts:140`). PP cannot give the answer: PP persist across switches while `used` does not.
- **State (rev-5 reserve, no schema bump).** `dfi_pool_tail.move_used`: a nibble per position in flat order, bit k = move slot k used since the occupant came in. Written in the rev-5 reserve bytes 8 and 9 (the other reserve bytes stay zero). Set where the engine deducts PP, cleared by `dfi_tail_clear_occupant`. The invariant: a bit only on an occupied position and below its move count.
- **Rule.** `dfi_last_resort_ok` (`turn.c`) at the TryMove stage, after the Armor Tail check, before the target and special dispatch. A failure is silent after the move line (`|move|` only, no further line), PP is spent, the result is FALSE (the pin's `moveThisTurnResult`).
- **View (approved option c).** `volatiles2` bits 0 to 3 (`DUOFORGE_POSITION_EXT2_LAST_RESORT_USED_1..4`, slot k at bit k-1) are shown only for an occupant that has Last Resort in its current move slots (its open sheet, or a Transform copy). For every other occupant the bits are 0: they decide Last Resort only, and the state keeps them for every occupant (so a copy stays correct). The feature is `DUOFORGE_VIEWEXT_FEATURE_LAST_RESORT_USED` (44), in `DUOFORGE_VIEWEXT_RESERVE_OWN` (four entries). The bits are public: each use is a move line since the switch-in.
- **Encoder 5.** encode.c refuses a nonzero `volatiles2` for encoders below 6 (`DUOFORGE_E_UNSUPPORTED`). With option c that refusal happens only for a state with a Last Resort holder on the field.
- **Pair tests (to be run).** (1) a holder with used moves: the bits are visible and encoder 5 returns E_UNSUPPORTED; (2) a non-holder with used moves: the bits are 0 and encoder 5 runs. In C: `tests/test_pool_g94.c`.

## 3. Pins of the tables

Special ids: BANEFUL_BUNKER 101, LAST_RESORT 102, UNMODELED 103 (generator order, after G78). The pool canonical hash and the KP and KPD fingerprints are in `tests/test_pool_setup.c` and `tests/test_pool_tables.c` and `tools/state_model/state_v3_model.py`.
