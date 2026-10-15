# 0083 - Singles: `DUOFORGE_ACTIVE_PER_SIDE` as a capacity, and the Champions-singles development kind

Status: **draft for the HS** (OU lane, step O2 of the [OU design](../superpowers/specs/2026-10-15-gen9-ou-design.md),
section 2.2; Q8 accepted the capacity reading on 2026-10-14). **The number 0083, the kind value 8 and the name
`duoforge_context_active_per_side` are provisional until the HS assigns them** (Q7). The owner's decision of
2026-10-15 (Q1 changed, directly Gen 9 OU) leaves this step as it was: singles on proven mechanics. Its reference
battles are recorded in `[Gen 9 Champions] OU` (owner and HS, 2026-10-15; section 6).

## 1. The capacity reading

`DUOFORGE_ACTIVE_PER_SIDE` keeps the value 2 and means **the capacity of every position array**
(`include/duoforge/duoforge.h`, the comment above the constant). No struct changes size, no offset moves,
`python/duoforge/_layout.py` is unchanged. The game type comes from the data kind:

- `DUOFORGE_DATA_KIND_POOL_SINGLES_DEV` (provisional value 8): today's pool tables and the POOL_DEV rules (the same
  support manifest, the same pool tail), one position per side. Every existing kind keeps its behaviour and its bytes.
- `duoforge_context_active_per_side(ctx, &n)`: 1 for the singles kind, 2 for every other kind. NULL arguments give
  `DUOFORGE_E_NULL_ARGUMENT`; it allocates nothing. Callers do not derive the game type from a kind table.
- The context refuses a singles config with `brought_count != max_roster` (`E_INVALID_ARGUMENT`): every registered
  member is brought (6 of 6 for a full roster; a roster of 3 brings 3).

## 2. Positions

Flat positions stay `side * 2 + slot`. **Slot 1 of each side is never occupied** under the singles kind:

- The new invariant `SINGLES_SLOT` (`src/state/invariants.c`, the first check of the position loop) refuses a state with
  slot 1 occupied under the singles kind; the same bytes under POOL_DEV are valid. The invariant count goes 51 to 52.
- The request asks slot 0 only (`requested_slots` and `slot_mask` 1).
- **Deviation from the spec text** (section 2.2 said `slot_count[1] = 0`): the factored domain gives slot 1 **one**
  command, `DUOFORGE_SLOT_NONE`, the existing convention for an unrequested slot (`duoforge.h`, "an unrequested slot").
  A domain with zero commands in a slot would have no joint choice at all; with one NONE command the joint count is
  the slot-0 count, and every caller that already handles an unrequested doubles slot handles singles unchanged. A
  side choice that fills slot 1 is `E_INVALID_ARGUMENT`.
- Drag (Roar, Whirlwind, Dragon Tail) draws from `party_order` past the **active count** (1 in singles), not past 2
  (`dfi_drag_in`, sim/battle.ts:1570-1588, getRandomSwitchable from `side.active.length`).

## 3. Team selection

The choice names the **lead**: `pick_count` 1, the TEAM_SELECTION domain is the 6 leads in roster order. The bench follows
in roster order (`dfi_apply_team_selection`), as Showdown's `chooseTeam` fills a choice of leads with the remaining
positions in order (sim/side.ts). A choice of four picks is refused. The engine owns this rule; the converter checks
that the reference's fill order is the lead then the rest ascending and stops (`singles-team-order`) otherwise.

## 4. Targets and the moves that need an ally

- `normal`, `any` and `adjacentFoe` resolve to the foe's slot 0 (flat `(1 - side) * 2`); `adjacentAllyOrSelf` to the
  user; `adjacentAlly` and the classes with no choice take `DUOFORGE_TARGET_NONE`.
- A random target (Outrage, Thrash, Petal Dance, a redirected `randomNormal`) is the one foe **without a draw**
  (sim/battle.ts:2509-2521, getRandomTarget picks from one candidate with no `sample`).
- The spread modifier never applies (one target). Screens use 2048/4096 in singles and 2732/4096 in doubles
  (data/moves.ts:859-860, 10337-10338, 14864-14865: `this.activePerHalf > 1`).
- Follow Me and Rage Powder fail with `-fail` and `[still]` in singles (their onTry: `activePerHalf === 1`); After You
  and Quash take their false path (no ally whose action can move); an `adjacentAlly` move with no target (Helping Hand,
  Coaching's ally part) has no target; Ally Switch's existing no-partner path is Showdown's singles failure.

## 5. Views and worlds

- The public view hides the foe's party order past the **active count** and the pick order past the lead;
  `foe_leads[1]` is `DUOFORGE_VIEW_PICK_NONE` in singles (`duoforge_view.h`, the field comment). In singles the bench
  order follows from the public lead and the public roster, so nothing that was hidden in doubles becomes visible.
- A hypothesis whose pick order is not the lead then the rest ascending is `E_INVALID_ARGUMENT` (not a state of the
  game); the neutral hypothesis builds that order. `duoforge.view` replays 80 singles games through the round trip
  (12362 views, every world byte-equal to the truth but the hidden bench order).

## 6. The reference format

The reference battles are recorded in `[Gen 9 Champions] OU` (`gen9championsou`, config/formats.ts:255-259), the real
format (owner and HS, 2026-10-15; the first draft used `[Gen 9 Champions] Custom Game`). The reasons:

- Showdown shows the HP as a player sees it, so the converter needs no conversion of its own: the HP lines are read as
  in the VGC battles. Custom Game's `debug: true` shows the exact HP to everyone and would need a rewrite in Python.
- It is the same basis as the VGC reference battles, which are recorded in their real format.
- The pool is the one of O1 (`data/formats/champions-ou.json`), and the format's clauses act almost only on the team
  check, not on the battle.

**The clauses.** `Standard` of the Champions mod (data/mods/champions/rulesets.ts:2-15): Obtainable, Team Preview,
Cancel Mod, Endless Battle Clause, Adjust Level = 50, Species Clause, Item Clause = 1, Min Team Size = 6, Sleep Moves
Clause, Nickname Clause, OHKO Clause, Evasion Clause, and the format's banlist (AG, Uber, Moody, Damp Rock, King's
Rock, Light Clay, Quick Claw, Baton Pass, Last Respects, Shed Tail). All of them but the Endless Battle Clause act in
the team validator only. The trace tool (`ps_trace.js`) runs no validator, so every team of the set and of the gate
campaign is checked with the pinned `TeamValidator` for `gen9championsou`: the 26 battles of the set and the 452 teams
of the gate campaign are legal. Team Preview brings 6 of 6, as the kind does (section 3).

**The Endless Battle Clause.** Showdown checks it in `nextTurn` (sim/battle.ts:1773, 1803-1903): nothing happens before
turn 101 (:1836); from turn 101 on, a battle in which every Pokemon is stale ends in a tie or a loss (:1854-1903). The
turn limit of every format ties at turn 1001 (:1839-1843). The engine models neither (no staleness, no turn limit). Under
the singles kind a step that would start turn 101 is therefore **refused by name**: `DUOFORGE_E_UNSUPPORTED` from
`dfi_end_turn`, before any change (test: `duoforge.state.singles`, turn 100 refused and turn 99 accepted). In the reference
battles the clause never acts: the campaigns stop after 100 steps (`--max-steps 100`, so no battle passes turn 100), and
the longest battle of the set ends on turn 52. The doubles kinds keep their behaviour: their formats have no Endless
Battle Clause, and their turn limit at 1001 is not modelled either, as before this step.

## 7. Fixes found by the singles campaigns that apply to doubles too

Every fix below has its own test. Where the case is legal in Reg M-C, the test is a doubles reference battle under
`tests/reference/specs/` that main fails and this step passes. Where the case is a refusal, the test is a white-box C test
that builds the state. The battles named `fz_90_*` come from a doubles differential campaign (seed 90, 400 battles of two
Reg M-C teams).

- A Substitute's hit is a null target, not a false one, for `selfDrops` (decision 0032). The selfSwitch flag, `mustrecharge`
  and the lockedmove came to main with issues 517 to 519. This step adds Glaive Rush's volatile
  (sim/battle-actions.ts:1317-1335). Test: `o2_glaive_rush_substitute` (written for it).
- A Choice item's lock on a lockedmove names its slot in the observation and in the conformance comparison, as the
  reference's choice lock does. This narrows the view audit of 2026-10-10 (#323), which hid the slot of a foe after a
  lockedmove, a Choice lock included: the Choice lock's slot stays when the lock's drawn count ends, so showing it tells
  nothing about the count. The live tracker's view follows (`_shown_locked_slot`). Tests: `o2_choice_lockedmove` (written
  for it; main fails it in the state and both views) and `LockedMoveSlotTest` in `python/tests/live/test_live.py`.
- Last Respects after a spent Revival Blessing PP of its side is refused (`E_UNSUPPORTED`). `side.totalFainted` counts
  every faint (sim/battle.ts:2554), and the state does not count revivals, so the roster count of decision 0009 section
  4.1 undercounts. A stored counter would be a state change and is left to the HS. Test: `duoforge.state.last_respects_revival`.
  It continues the reference battle `o2_last_respects_revival`: after the revival the turn is refused and the battle is
  unchanged; before it the same turn runs.
- Moody's residual handler of a Pokemon whose faint is queued and not yet processed (Perish Song's perish0 earlier in the
  same residual) runs and draws. `Pokemon.faint()` only sets hp 0, the handler loop skips only a `fainted` holder
  (sim/battle.ts:512-514), and the boost of a Pokemon at 0 HP does nothing. Moody is banned in Champions OU but legal in
  Reg M-C. Test: `o2_moody_queued_faint` (`fz_90_17`, cut after its step 5).
- Stance Change resets a type that Soak or Double Shock set, as Mega Evolution already did: `formeChange` calls
  `setSpecies`, which calls `setType(species.types, true)` (sim/pokemon.ts:1387-1392). Test: `o2_stance_change_soak`
  (`fz_90_282`, cut after its step 1).
- The converter's Pressure count of the viewer's own Pokemon took the sheet's ability again when a Mega Evolved Pokemon
  switched back in. Mega Evolution is permanent (sim/battle-actions.ts:1902), so the Mega's ability counts. A Custom Game
  battle with a Mega Absol found it. The engine was right; the converter was wrong. Test: `o2_pressure_after_mega`
  (`fz_90_345`, cut after its step 11); the converter of main fails it on the observed PP.
- A Magic Bounce holder under Throat Chop that bounces a sound move (Parting Shot) shows `cant|holder|move: Throat Chop`,
  and the bounced run ends there. Throat Chop's `onModifyMove` (data/moves.ts:19417-19422) runs in `useMoveInner` before
  the move line (sim/battle-actions.ts:439-445). In doubles, `getRandomTarget` first draws one RANDOM_TARGET over the
  holder's standing foes (sim/battle.ts:2490-2521); in singles it takes the foe's slot 0 without a draw. The engine ran the
  bounced move. The doubles part is its own change (issue 570, test `fz570_throat_chop_bounce`); this step adds the singles
  branch.

Five battles of the same doubles campaign still diverge (`fz_90_14`, `120`, `161`, `217`, `234`). Main fails them too.
In each of them a Moody holder's residual meets the no-order Protect/stall pair of a speed tie: the reference draws that
tie at sort time and then the Moody draws, and the engine draws Moody first. This step does not change that order.

## 8. Cost of the capacity reading (measured)

`duoforge_battle_encoded_size` is 1357 bytes under the singles kind and under POOL_DEV (the same layout). The empty slot 1
takes 66 bytes per side, 132 per battle (position 21, sealed command 5, tail position 36, tail rev 5 position 2,
Attract source 1, Ally Switch count 1). `duoforge_observation` (736 bytes) carries two empty `duoforge_position_view`s
and two `occupant` bytes at `DUOFORGE_ROSTER_NONE` (34 bytes), `duoforge_observation_ext` (192 bytes) two empty `duoforge_position_ext`s (32 bytes);
`duoforge_public_state` is 1396 bytes with the same 132 empty state bytes. No layout changes.
