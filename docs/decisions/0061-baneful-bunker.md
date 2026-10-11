# 0061 - Baneful Bunker (step G94, decision 0015 entry 5cx)

Status: **landed** on main (lane A batch 6, PR #388). Decision 0015 records the step as entry 5cx; main's code comments cite "decision 0015 5cv", which in 0015 is the Substitute spread-hit entry. Lane A builder H29. Pin: Pokemon Showdown b2cb775, Champions mod checked first: `data/mods/champions/moves.ts:43-46` overrides only the PP (5, `inherit: true`), so the behaviour is the base move's.

This note is the Baneful Bunker part of the G94 note. Its Last Resort part (sections 2, 4, 5 and 6 of the branch note) is paused with its branch `chris/expansion-g94-protect-misc` (head f543660d) and is not on main; when Last Resort lands, its sections join this file.

## 1. Baneful Bunker (protect_kind 3)

- **Pin.** `data/moves.ts:985-1037`: Poison status move, priority 4, flags `noassist`, `failcopycat` (no `protect` flag), stalling move, `volatileStatus: banefulbunker`. Its condition has Protect's shape: `-singleturn|X|move: Protect`, `onTryHit` = `checkMoveBypassesProtect` then the Outrage reset, `-activate|X|move: Protect`, and for a contact move `source.trySetStatus('psn', target)`. Its only learner in the Champions pool is Toxapex (`data/mods/champions/learnsets.ts:12666`, 9M), whose abilities Limber (G39) and Regenerator are marked; Merciless is not, so a Merciless Toxapex is refused.
- **Engine.** `protect_kind` 3 (`DFI_PROTECT_BANEFUL_BUNKER`; `DFI_TAIL_PROTECT_KIND_MAX` from 2 to 3, same schema 0x0503: the value 3 is in the byte that rev 3 defined). `dfi_run_protect` (shared stall counter) and `dfi_protect_targets`: the contact attacker is poisoned by `dfi_try_status(attacker, PSN, origin OTHER, holder)`. The pin passes the condition as the effect, so the line is a plain `-status|X|psn` (no `[from]`); an immune attacker (Poison or Steel) or one that already has a status gets no line.
- **Evidence.** Three recorded POOL battles: `g94_bunker_poison` (a contact Dragon Claw poisons, a Steel Iron Head is stopped silently), `g94_bunker_noncontact` (Earthquake stopped, no poison), `g94_bunker_already_poisoned` (a second contact hit sets nothing). Toxapex holds Lum Berry (Black Sludge is not in the pool).

## 2. Tables

The special `BANEFUL_BUNKER` has a generator-assigned handler id (`tools/datagen/gen_closure.py`, generator order); the pinned ids, the pool canonical hash and the KP and KPD fingerprints are in `tests/test_pool_setup.c`, `tests/test_pool_tables.c` and `tools/state_model/state_v3_model.py`. No public value is new.
