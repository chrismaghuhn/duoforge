# 0083 - Singles: `DUOFORGE_ACTIVE_PER_SIDE` as a capacity, and the Champions-singles development kind

Status: **draft for the HS** (OU lane, step O2 of the [OU design](../superpowers/specs/2026-10-15-gen9-ou-design.md),
section 2.2; Q8 accepted the capacity reading on 2026-10-14). **The number 0083, the kind value 8 and the name
`duoforge_context_active_per_side` are provisional until the HS assigns them** (Q7). The owner's decision of
2026-10-15 (Q1 changed, directly Gen 9 OU) leaves this step as it was: singles on proven mechanics, recorded against
`[Gen 9 Champions] Custom Game`.

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

The reference battles are recorded in `[Gen 9 Champions] Custom Game` (`gen9championscustomgame`, config/formats.ts:316-322):
the Champions mod with no clause, no ban and no Endless Battle Clause, so it tests singles on proven mechanics. Its
`debug: true` reports the exact HP to both players (sim/battle.ts:227) and adds `|debug|` lines. The converter
(`trace_to_c.champions_public_hp`) drops the debug lines and rewrites the **shared** copy of every split line to the
Champions display (sim/pokemon.ts:2066-2074: the floored percentage, at least 1, the flags at 20 and 50); the secret
copies stay exact. Its other option, `battle: {trunc: Math.trunc}`, differs from the default truncation only for
values of 2^16 and more at the 16-bit truncations (sim/battle-actions.ts:1841, 1859; sim/battle.ts:2366-2369), which no
level 50 battle reaches.

## 7. Fixes found by the singles campaigns that apply to doubles too

- A Substitute's hit is a null target, not a false one, for `runMoveEffects` and `selfDrops` (decision 0032): it now
  also sets the selfSwitch flag (U-turn, Flip Turn), `mustrecharge` (Hyper Beam), the lockedmove (Outrage) and Glaive
  Rush's volatile (sim/battle-actions.ts:1062-1065, 1286-1312, 1317-1335).
- A Choice item's lock on a lockedmove names its slot in the observation and in the conformance comparison, as the
  reference's choice lock does.
- Last Respects after a spent Revival Blessing PP of its side is refused (`E_UNSUPPORTED`): `side.totalFainted` counts
  every faint (sim/battle.ts:2554) and the state does not count revivals, so the roster count of decision 0009 section
  4.1 undercounts. A stored counter would be a state change and is left to the HS.
- Moody's residual handler of a Pokemon whose faint is queued and not yet processed (Perish Song's perish0 earlier in the
  same residual) runs and draws: `Pokemon.faint()` only sets hp 0, the handler loop skips only a `fainted` holder
  (sim/battle.ts:512-514), and the boost of a Pokemon at 0 HP does nothing (`cs_moody_perish_1`, `_2`).
- Stance Change resets a type that Soak or Double Shock set, as Mega Evolution already did: `formeChange` calls
  `setSpecies`, which calls `setType(species.types, true)` (sim/pokemon.ts:1387-1392; `cs_stance_soak_1`).
- The converter's Pressure count of the viewer's own Pokemon took the sheet's ability again when a Mega Evolved Pokemon
  switched back in; Mega Evolution is permanent (sim/battle-actions.ts:1902), so the Mega's ability counts
  (`cs_pressure_mega_1`). The engine was right; the reference was wrong.

## 8. Cost of the capacity reading (measured)

`duoforge_battle_encoded_size` is 1357 bytes under the singles kind and under POOL_DEV (the same layout). The empty slot 1
takes 66 bytes per side, 132 per battle (position 21, sealed command 5, tail position 36, tail rev 5 position 2,
Attract source 1, Ally Switch count 1). `duoforge_observation` (736 bytes) carries two empty `duoforge_position_view`s
and two `occupant` bytes at `DUOFORGE_ROSTER_NONE` (34 bytes), `duoforge_observation_ext` (192 bytes) two empty `duoforge_position_ext`s (32 bytes);
`duoforge_public_state` is 1396 bytes with the same 132 empty state bytes. No layout changes.
