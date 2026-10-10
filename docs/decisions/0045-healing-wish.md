# 0045. Healing Wish (G82, decision 0015 letter 5ck)

Status: PHASE 1, design proposal (builder H19). No engine code, no recordings yet. Waiting for the lead's approval.
Pin: Pokemon Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`). Champions overrides: none for `healingwish`
(`data/mods/champions/` has learnsets only: `data/mods/champions/learnsets.ts`, e.g. :634, :719).

## 1. Pin semantics

**The move** (`data/moves.ts:8348-8382`): Psychic, Status, accuracy true, target self, `selfdestruct: "ifHit"`
(:8364), `slotCondition: 'healingwish'` (:8365).

- `onTryHit` (:8357-8363): no bench (`canSwitch(source.side)` false) gives `[still]` and `-fail`, NOT_FAIL. No faint,
  no slot condition. The bench test is `possibleSwitches` (`sim/battle.ts:1574-1586`): living members outside the active
  slots, `side.pokemonLeft` checked first.
- Hit loop (`sim/battle-actions.ts:1244-1246`): `side.addSlotCondition(target, 'healingwish', source, move)` on the user.
  `addSlotCondition` (`sim/side.ts:464-495`): if the position already has the condition and it has no `onRestart`, it
  returns false (:474-476). That makes `didSomething` false, so `damage[i]` is false.
- Faint (`sim/battle-actions.ts:1287-1289`): `if (selfdestruct === 'ifHit' && damage[i] !== false) battle.faint(source, source, move)`.
  It runs after the slot condition in the same hit loop. The `-fail` at :1303-1306 is skipped for any `selfdestruct` move.
- **Second wish on an occupied slot** (corrected 2026-10-10, the lead's check): the hit result is FALSE. addSlotCondition
  returns false (side.ts:474-476), damage[i] is false (battle-actions.ts:1287: no faint), the hit-result filter leaves no
  target, atLeastOneFailure keeps moveThisTurnResult (battle-actions.ts:616), and the wrapper stores FALSE (:371-374).
  The Champions loop breaks before its Updates (scripts.ts:526). No -fail line (selfdestruct, battle-actions.ts:1303-1306).
  Engine: `r->mres |= DFI_MRES_FALSE` (turn.c, dfi_run_healing_wish). Next-turn Stomping Tantrum (G42) reads FALSE (doubled).
- `singleEvent` returns `relayVar`, which defaults to true when there is no callback (`sim/battle.ts:591-595`). So the
  `Start` event in `addSlotCondition` succeeds; the wish is stored.

**The slot condition** (`sim/side.ts:197,267-269`): `side.slotConditions[position]`, a per-position store, not
per-Pokemon. It has no duration and no `onEnd`. It ends only by the heal, through `side.removeSlotCondition`
(`sim/side.ts:504-511`, called at `:8375`). Switch-out (`sim/battle-actions.ts:62-160`) never touches it, and nor
does a faint (`sim/battle.ts:2535-2605` `faintMessages`: `clearVolatile` at :2578-2581 and no side condition is touched). Handlers of the occupant at that
position are collected by `findPokemonEventHandlers` (`sim/battle.ts:1139-1151`). A fainted holder's slot handlers still
run (`fieldEvent`, `sim/battle.ts:514-517`: only non-slot handlers are skipped for a fainted holder).

**The heal** (condition `:8366-8378`): `onSwitchIn` (:8367-8369) forwards to `onSwap` (:8370-8377), which checks
`!target.fainted && (target.hp < target.maxhp || target.status)`. Then:
- `target.heal(target.maxhp)` (`sim/pokemon.ts:1640-1652`): HP only, no event, no TryHeal, no Heal Block check.
- `target.clearStatus()` (`sim/pokemon.ts:1755-1761`): `setStatus('')`, silent. `sim/pokemon.ts` comment: "does not give cure message".
- `-heal|target|hp/max|[from] move: Healing Wish` (:8374). `getHealth` (`sim/pokemon.ts:2060-2070`, Champions branch:
  `floor(100*hp/maxhp) || 1` over 100, no suffix at full HP): the line reads `100/100`.
- `removeSlotCondition` (:8375). If the check fails (full HP, no status), nothing happens and the wish waits.

**Entry priority** (`sim/battle.ts:393-411` `comparePriority`: order, then priority high to low, then speed, then
subOrder low to high). `resolvePriority` (`sim/battle.ts:954-992`): slot condition subOrder 3 (:975-977); side condition
4; field 5; Ability 7; Item 8. Speed is the holder's (`sim/battle.ts:1008-1013`, the fractional field-position tiebreak),
so within one entrant the subOrder decides:
- the wish heal runs BEFORE the hazards (4), Intimidate (ability, 7) and items (8), and AFTER every SwitchIn handler
  with `onSwitchInPriority` > 0 (Unnerve, Klutz +1, `data/abilities.ts:5259,2281`; As One +1, :250/:274; Neutralizing Gas
  +2, :2907; Tera Shift +2, :4965) and BEFORE the priority -1/-2 handlers (Mimicry :2582, Schooling :4045, Shields Down
  :4240, White Herb items, data/items.ts:583,628).
- Intimidate has no priority, so the heal comes before its -boost line.

**When the replacement enters.** The entry is `runSwitch` (`sim/battle-actions.ts:175-188`) and `fieldEvent('SwitchIn',
[entrants])`. A normal switch queues `runSwitch` right after its `[switch]` line (`sim/battle-actions.ts:153-156`); a
drag (Whirlwind, gen 5+) runs it at once (:153-155). Revival Blessing (`sim/battle.ts` 2762-2800) emits `-heal ...
[from] move: Revival Blessing`, queues `instaswitch`, and that reaches `switchIn` and `runSwitch` too.

**Faint timing.** A move's faint does not set `switchFlag` mid-turn. `checkFainted` (`sim/battle.ts:2524-2530`) runs
only when `!this.queue.peek()` (:2838-2843), and the turn queue holds `residual` until it has run. So a Healing Wish
faint is requested AFTER the residual action (which ends with `|upkeep|`), at the end of the turn. The request is
`makeRequest('switch')` (`sim/battle.ts:2912`), then `endTurn` (`sim/battle.ts:1623`). A U-turn, Baton Pass or Eject
Button sets `switchFlag` mid-turn and asks at once (:2912, the same call right after the action).

**No replacement left.** `switches[i] && !canSwitch` clears the flags (`sim/battle.ts:2883-2891`): no request, the slot
stays empty and the wish stays. For a Healing Wish alone this cannot happen after a successful use (the bench is
alive at onTryHit and nothing damages the bench). It is reached only by a later revive or a battle that goes on with
an empty slot.

**Full-HP replacement.** The wish stays: the replacement holds it, and the next entrant of that slot is healed.

**Fainted slot.** The wish stays on the slot while the fainted occupant stands there (the state model keeps it).

**Baton Pass / U-turn.** The slot condition belongs to the position. A pivot out does not remove it, and the next
entrant at that slot is healed if hurt or statused. Baton Pass's copied volatiles do not include side conditions.

**Request flow.** The end-of-turn replacement is a `REPLACEMENT` boundary (C: `dfi_finish_turn`, `src/combat/turn.c:9771`),
the mid-turn one a `PIVOT`. Both already exist; no new boundary.

## 2. State

- Bit 0 of `position_flags` (`src/state/battle_internal.h:263` `DFI_POSFLAG_HEALING_WISH`; struct at :329-331): one bit
  per flat position (= side slot, matching `side.slotConditions[position]`). Set when the user's Healing Wish hit finds
  bit 0 clear, on the user's position (then the user faints, the position keeps the bit). Cleared only by the heal in the
  entrant's entry. Not cleared by a faint, a switch-out, a pivot, a revive or the turn's end.
- **The one real engine problem:** `dfi_tail_clear_occupant` (`src/state/identity.c:34-41`) zeroes the WHOLE per-position
  tail, including `position_flags`. It runs in `dfi_place` (identity.c:118, before a new occupant is written) and in
  `dfi_vacate` (:140). So a replacement would erase the wish at the moment it must fire. Fix: keep bit 0 across that
  zeroing (the bit belongs to the slot, not the occupant). Bits 1-3 keep ending with the occupant, as now.
- Invariant (`src/state/invariants.c:587-591` `dfi_position_flags_ok`, which rejects bit 0 today; :641-645; :712-727 for
  empty positions): bit 0 is allowed at a standing occupant, at a fainted one, and at an EMPTY position (the wish waits on
  an empty slot). Bits 1-3 keep their rules (only with an occupant). Bits 4-7 stay zero.
- Mirror: `tools/state_model/state_v3_model.py:975-977` `position_flags_valid` (rejects bit 0 today), :1019-1020 and
  :1048-1057 (the empty-position rule). Same rule, invariant only (no rule logic in Python).
- **Tests that pin the old rule:** `tests/test_pool_tail.c:952` (`m_healing_wish_bit`) and the row at :1126 assert that bit 0
  is refused. They must change to the new rule (bit 0 accepted at a standing lead and at an empty position; bits 4-7 and
  stage 3 still refused). That is a rule change, not a weakening, and I will call it out in the PR.
- Codec: `src/codec/state_codec.c:84` and :210 keep the byte at its place. No new tail byte, no reserve byte. No tail rev
  change.

## 3. Information safety (decisions 0007, 0023)

- Public: the Healing Wish move line (the move id), the user's FAINT, and the `-heal ... [from] move: Healing Wish` line
  on the entrant. The pending wish is a function of these lines. The protocol shows nothing when the slot condition starts,
  but the opponent can derive the wish from the move and the faint, and the heal line ends it. So the wish is public. No
  refusal is needed.
- But `duoforge_battle_from_view` rebuilds the world from the view. Without a view bit the rebuilt battle would lose the
  wish, and the determinized future would be wrong. So the view needs the bit (section 4), set from bit 0 at every
  position, empty positions included (`src/state/observation.c:355` pattern, as Dragon Cheer and Destiny Bond).
- Silent cure: the entrant's status clears with no protocol line (`clearStatus`, see section 1). The fold of the public
  record has to clear the status too. Options (lead decides): a CURE_STATUS event with no FLAG_MESSAGE (the flag
  description, `include/duoforge/duoforge.h:1018-1019` and :1118, says a message is [msg] only with the flag), or a HEAL
  event whose status reset is carried in the event. I need the lead's answer on which one the converter (trace_to_c.py)
  and the knowledge fold accept silently.

## 4. New public values (requested, numbers NOT chosen by me)

- **View bit** `DUOFORGE_POSITION_EXT_HEALING_WISH`: the next free bit is `0x00400000u` (`include/duoforge/duoforge.h:846-867`,
  last is TRANSFORMED `0x00200000u`). Lead/HauptSession assigns it.
- **View feature** `DUOFORGE_VIEWEXT_FEATURE_HEALING_WISH`: next free is 43 (`duoforge.h:877-918`; `FEATURE_COUNT` is 43).
  Lead/HauptSession assigns it.
- **Event kind:** none. The heal is the existing HEAL (5), `cause MOVE`, `id2` = the Healing Wish move id. The pending
  state needs no event (no protocol line).
- **Cure:** CURE_STATUS (19), silent, OR no event (section 3). Lead decides.
- **Cause:** none new (`DUOFORGE_CAUSE_MOVE`).
- **Volatile, public cause, flags3 bit, pool column:** none. The move id and the pool special id (a new `DFI_SPECIAL_*`
  for `slotCondition`, like Alluring Voice's 91) come from the generator. Lead to confirm whether the special id is
  central.

## 5. Planned recordings (POOL, six members a side, unique items, real genders, marked content only, learnsets from
`data/mods/champions/learnsets.ts`)

- R1 normal heal: X's Healing Wish user faints, the entrant is hurt AND statused. Expect the heal line, status cleared,
  wish consumed, then the next replacement at that slot unhealed.
- R2 full-HP entrant without status: the wish stays. The next entrant (a U-turn or a later faint) is healed.
- R3 the second wish on an occupied slot: the user does not faint, the old wish stays (the pin's silent no-op).
- R4 Revival Blessing into a slot with a pending wish, after a faint and an empty slot: the revive line, then the heal.
- R5 order: the heal line before Intimidate's -boost (the replacement enters with the wish and an Intimidate holder
  on the opposing side, if Intimidate is marked), and before any marked hazard on its side.
- R6 Sitrus speed tie on BOTH sides at the same speed (the hit-loop Update draws: SPEED_TIE each:Update), plus a wish
  entrant, so the tie count includes the wish holder.
- R7 residual order: the holder dies to residual damage (poison or Leftovers-free burn if marked); the replacement
  comes after `|upkeep|`, so the wish acts after the residual.
- Planned mutants (each must fail a test): M1 no status cure; M2 no HP heal; M3 heal at full HP (wish consumed
  always); M4 the wish cleared at switch-out; M5 `dfi_tail_clear_occupant` keeps the old zeroing (wish erased at entry;
  the expected catch: R1); M6 heal after Intimidate (subOrder moved to 8); M7 the user does not faint; M8 second use
  overwrites the wish; M9 the bearer count without the wish (`dfi_run_entries`, `src/combat/turn.c:8388-8440`); M10 invariant refusing bit 0 at an empty position; M11 view
  bit not set. Caught/total reported in the phase-2 report.

## 6. Refusals (E_UNSUPPORTED)

- None for the wish itself. The second-use path and the empty-slot wish are modelled exactly, not refused.
- Conditional refusal: if Neutralizing Gas (onSwitchInPriority +2, `data/abilities.ts:2907`) or Tera Shift (+2, :4965) is
  marked AND can enter with a pending wish, refuse explicitly until the +2 pass exists in `dfi_run_entries`
  (`src/combat/turn.c:8388`, the pass order Unnerve +1, then priority 0). The +1 Unnerve pass already exists.
- Heal Block: `Pokemon.heal` does not check it (`sim/pokemon.ts:1640`), so the wish heals through Heal Block. The C
  must not check it either.

## Open questions for the lead

1. The view bit number, the VIEWEXT feature number (43) and the pool special id (section 4).
2. Silent cure: CURE_STATUS without a message, or the HEAL event carries the status (section 3).
3. Approve: the `dfi_tail_clear_occupant` change, the invariant change and the rewrite of the two `test_pool_tail.c` checks.
4. Confirm the speed-tie bearer count: `ps_trace.js` must count a wish-holding entrant (the C count is in `dfi_run_entries`, `turn.c:8388-8440`).
