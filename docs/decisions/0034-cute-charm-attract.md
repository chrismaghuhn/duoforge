# 0034 - Cute Charm and the Attract volatile (step G71, lane B batch 5)

Status: **accepted** (owner, 2026-10-10: volatile 11, the rev 5 reserve bytes 0 to 3 for the source, the two draw sites, and the
extension of the Oblivious and Mental Herb rows). The public presence bit is a reserve bit of encoder 6 (decision 0050), so it
needed no version bump. Part of decision 0015 (the content expansion, lane B), entry 5bn. Merged with the Attract fold of the
live tracker (#393) and the source's public bits (decision 0080, step G87).

## The rule (Showdown b2cb775; the Champions mod overrides none of these)

- **Cute Charm** (`data/abilities.ts:798-810`): `onDamagingHit` for a contact move: `randomChance(3, 10)`, then
  `source.addVolatile('attract', holder)` on the attacker. The draw is taken for every contact hit on a damaged holder, also
  when the attacker cannot be infatuated: the gender test is inside the volatile's `onStart`.
- **The attract condition** (`data/moves.ts:706-761`):
  - `onStart`: only opposite genders (M with F, F with M, `data/moves.ts:719`); `runEvent('Attract')` (Oblivious blocks it);
    then `-start|X|Attract|[from] ability: Cute Charm|[of] Y`.
  - `onUpdate`: the volatile ends when its source is not active (`data/moves.ts:737-740`). The end is `-end|X|Attract|[silent]`
    (`onEnd`, `data/moves.ts:750-751`). It does not resume when the source comes back.
  - `onBeforeMovePriority: 2`, `onBeforeMove`: `-activate|X|move: Attract|[of] Y`, then `randomChance(1, 2)`: `cant|X|Attract`
    and the move is not used (`data/moves.ts:743-749`).
- **Oblivious** (an engine row of step G47): immunity to Attract (no `-immune` line: an ability source), and the cure at Update
  (`-end|X|move: Attract|[from] ability: Oblivious`, `data/abilities.ts:3009-3016`).
- **Mental Herb** (an engine row of step G47): cures Attract, and the item is used (`-end|X|move: Attract|[from] item: Mental Herb`).

Only Cute Charm starts Attract in the pool. The move Attract and Destiny Knot stay unmarked (`src/data/pool_tables.c`, `[unmodelled]`
at the Attract move), so the move's own `-start` (which has no `[of]`, `data/moves.ts:732-734`) cannot occur. It stays unmodelled.

## The values (`include/duoforge/duoforge.h`)

- Volatile **11**: `DUOFORGE_VOLATILE_ATTRACT` (VOLATILE_START and VOLATILE_END; the detail of the event).
- Cause **36**: `DUOFORGE_CAUSE_ATTRACT` (the CANT of a stopped move, which names no move: id 0, as Sleep's and Freeze's CANT).
- Public presence bit: `DUOFORGE_POSITION_EXT_ATTRACT` = `0x08000000` (bit 27 of duoforge_position_ext.volatiles). It is a checked
  reserve bit of encoder 6 (`DUOFORGE_VIEWEXT_RESERVE_CHECKED`, RESERVE_VOLATILES bit 27): encoders 1 to 5 refuse it, encoder 6
  shows it under RESERVE_VOLATILES. It has no feature of its own; the source is in decision 0080.
- Internal draw sites (`src/state/battle_internal.h`, `DFI_SITE_*`): **24** `DFI_SITE_CUTE_CHARM` (the 3/10 contact roll, after the
  hit loop, next to Static's site), **25** `DFI_SITE_ATTRACT` (the 1/2 roll at BeforeMove priority 2). Site 23 is Moody (G73), so
  the count is 26. Both sites are appended, the existing sequences are unchanged.

## The state

The infatuation needs one byte per flat position of the INFATUATED occupant: `tail.attract_source[flat]` (`src/state/battle_internal.h`,
`DFI_ATTRACT_SLOTS` = 4). It is the rev 5 reserve bytes 0 to 3 (`DFI_ENC_TAIL5_ATTRACT_OFF`, absolute offset 1341 of the 1357-byte POOL
state), so the schema stays rev 5 and no reserve byte of another family moves.

The byte is **the source member's code**: `1 + side * DUOFORGE_MAX_ROSTER + roster index`, so 1 to 12 (`DFI_ATTRACT_MEMBER_MAX`).
It is 0 when the position is not infatuated. The member is named, not its position: a position is the place the member stands on at
the moment, and the check and the observation find it from the occupants.

- **State check** (`src/state/invariants.c`, `dfi_attract_byte_ok`): a nonzero byte needs a code of 1 to 12 that names a member below
  its side's member count; an infatuated occupant that stands (on the field, not fainted); a source that is not the holder itself;
  the source on the field and not fainted (the pin's `source.isActive`); and the genders of the pair opposite (1 and 2). Anything else is
  an invariant failure. An empty or fainted position keeps no byte.
- **Clear**: a switch-out or a faint of the infatuated occupant clears its byte (`dfi_tail_clear_occupant`).
- **Silent end** (`-end|X|Attract|[silent]`): the byte goes to 0 when the source is no longer active, at the Update after the faint
  is shown (`dfi_faint_shown`, the pin's `faintMessages`, `sim/battle.ts:2566`). A queued faint that is not yet shown keeps Attract,
  as the pin's `isActive` does (commit 824a9aa7: the shown-faint rule, after a campaign divergence of 15, then 20 battles).
- **Ally Switch** (lane A's G80, not on main when this was written): the byte is indexed by the HOLDER's flat position, so the
  swap of two positions must swap the two bytes too. The later step adds that swap and its test.

## Where it shows

- The event stream: `-start`, `-activate` and `-end` as above, with the cause ABILITY (Cute Charm, Oblivious) or MOVE (Mental
  Herb, the Attract check); CANT with cause 36 for the stopped move.
- The public view: the presence bit for both players (decision 0050's reserve bit), and the source's flat position (decision 0080).
- The live tracker (`python/duoforge_live`) folds these lines, with the source per infatuated position (#393).

## The evidence (G71, from the batch PR text)

- 13 recorded POOL battles: infatuation; a turn immobilized by love; the move going through; the source switching out (silent end);
  the source fainting (two regressions of the shown-faint rule); Mental Herb's cure; Oblivious and genderless attackers with a passing
  roll (no infatuation); the same gender; a non-contact hit (no draw); a roll of exactly 3 (no infatuation).
- White-box tests: one test per rule of the state check, the model-derived tail sweep (two valid source codes per position), the
  Oblivious cure at Update, and the presence bit.
- Mutants: 11 of 12 valid ones caught; M12 is equivalent (a member is never the opposite gender of itself).
- Campaign: 600 battles (seed 9720000, kept traces): PASS 600, DIVERGENCE 0 after the shown-faint fix (before it 15, then 20).
- Triggers: Cute Charm draws 2698; infatuations 453; Attract checks 383 (of which cant 189); silent ends 241; Mental Herb cures 62.
  Oblivious cures: 0 in the campaign; the white-box test covers the cure.

## Open

- Ally Switch (G80): the swap of `attract_source` (see above).
- Destiny Knot and the Attract move: unmarked; no source other than Cute Charm is reachable.
