# 0063 - Ghost Curse (step G84b)

Status: **landed** on main (lane A batch 8, PR #417). Lane A builder H30; HauptSession's tracker fold (hs/g84b-python, hs/g84b-python-2, the CURSED record bit in hs/g80-python-2). Pin: Pokemon Showdown b2cb775; the Champions override `data/mods/champions/moves.ts:165-196` is read first. The non-Ghost Curse is decision 0047.

## 1. Variant and target

- The variant is the user's type **at execution** (`onModifyMove`, `onTryHit` and `onHit` read `source.hasType('Ghost')` then, not at the choice). A Soak, a Double Shock or a Mega forme counts (`dfi_types_of`).
- The request's target class (`dfi_target_class_for_types`, the public query `duoforge_data_request_target_class`): a user without the Ghost type gets the move's `nonGhostTarget` (self, no target); a Ghost user keeps the row's class (normal).
- Targets at execution (`dfi_curse_targets`): a Ghost user whose target is a foe keeps it (no draw). A target that is the user itself (a non-Ghost choice that executed as Ghost) is kept, and `dfi_run_curse` redirects it with one `getRandomTarget` draw. A target that is an ally (the partner, a fainted one, or none): `onModifyMove` sets `randomNormal`, and `useMove` draws `getRandomTarget` twice (after the single and after the run ModifyMove event); the second draw is the target (recording `g84b_ghost_ally_random`: two RANDOM_TARGET draws, one move line).

## 2. Execution of a Ghost user (`dfi_run_curse`)

In the pin's order:

1. TryHit: a foe target with Good as Gold refuses it (`-immune`, status move, `target !== source`; `data/abilities.ts:1630-1636`). The move result is false, no Update.
2. `onTryHit`: a target that already has Curse fails (`-fail` on the user, `[still]`, no halving).
3. `onHit`: `directDamage(maxhp / 2)` to the user (floor, at least 1, no `[from]` on the line; `DFI_DMG_DIRECT`, so Magic Guard does not stop it). Then, for a target that is the user itself, one random-foe draw (above).
4. The target gets the Curse: `-start|X|Curse|[of] user` (event VOLATILE_START, detail `DUOFORGE_VOLATILE_CURSE` 14, other: the user) and its flag. Protect does not stop it (no `protect` flag), and it goes through a Substitute (`bypasssub`).

A failed or immune hit returns before the hit loop's Updates; the success path ends with `dfi_status_hit_end`.

## 3. State: position flag bit 7 CURSED

- The Curse volatile is `DFI_POSFLAG_CURSED` (0x80), bit 7 of the position's `position_flags` (the byte is now full; `DFI_POSFLAG_VALID_MASK` 0xFF).
- **Rule: bit 7 only with an occupant.** The flag is the occupant's own volatile: it is set on a standing target, it ends with the occupant (`dfi_tail_clear_occupant` on a switch or a faint), and an empty position never has it. The C invariant (`src/state/invariants.c`, `posflags_ok`: bit 7 only with `slot->occupant < DUOFORGE_MAX_ROSTER`) and the model (`tools/state_model/state_v3_model.py`, `check_tail`) both require it: of the position flags, only bit 0 (Healing Wish, decision 0045, a slot condition) may stand at an empty position. Decision 0047's option (a), read literally, would have allowed an empty position; this rule replaces it for bit 7.
- Baton Pass copies it: Curse has no `noCopy` (`sim/pokemon.ts:1246-1251`, `copyVolatileFrom`), so the passer's Curse goes to the new occupant.
- Ally Switch moves it with the Pokemon (`dfi_swap_position_state`, `src/combat/turn.c`: every position flag except bit 0, Healing Wish, goes with the Pokemon; decision 0044 sections 2 and 10).

## 4. Residual

`onResidualOrder` 12, sub-order 2 (a condition), a callback every turn with no duration (`data/moves.ts:3295-3303`; the Champions override keeps the condition): `this.damage(baseMaxhp / 4)` on the holder with no source, so the line is `-damage|T|hp|[from] Curse` with no `[of]` (cause `DUOFORGE_CAUSE_CURSE` 23, `DFI_DMG_CONDITION`, so Magic Guard blocks it). Nothing when the holder is down or the amount is zero. Residual kind `DFI_RES_CURSE` 26 (`src/combat/residual_order.h`). Leech Seed and Curse are volatiles of the residual list (`dfi_residual_is_volatile`), whose insertion order is not stored; a residual list whose outcome depends on that order is refused explicitly (`dfi_residual_order_ambiguous`: the order may matter and changes the outcome).

## 5. View

The CURSED bit is public to both viewers (the `-start` line shows it): `DUOFORGE_POSITION_EXT_CURSE` (0x800, `src/state/observation.c`), feature `DUOFORGE_VIEWEXT_FEATURE_CURSE` 36. Its feature bit is in the support mask (`src/data/support_manifest.c`; `tests/test_observation_ext.c` lists it among the tier features). Bit 36 is one of encoder 5's fixed feature bits 0 to 42 (`DFI_ENC_ALL5`, decision 0050), so encoder 5 already has its column; no new encoder column.

## 6. Evidence

- Recorded POOL battles `g84b_ghost_*` (ally_random, baton_copy, good_as_gold, p2_curses_p1, protect_cursed, self_mega, soak_flip, substitute_faint), `g84b_nonghost_curse_fails`, `g84b_residual_burn_curse`, `g84b_residual_curse_tie`, `g84b_residual_leech_order`.
- Campaign (G84b branch head 3aaafd29): 293 PASS, 0 DIVERGENCE, 7 UNSUPPORTED (all `dfi_residual_order_ambiguous`).
- Mutants 5 of 5 caught (09a87427).

## 7. Public values

`DUOFORGE_VOLATILE_CURSE` 14, `DUOFORGE_CAUSE_CURSE` 23 (lane A block). Internal: `DFI_POSFLAG_CURSED` 0x80, `DFI_RES_CURSE` 26.
