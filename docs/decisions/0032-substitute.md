# 0032 - Substitute (G60): proposal of phase 1

Status: **accepted by the lead; public values pending HauptSession.** Lane A builder H2 (batch 2). The lead's decisions of phase 1 are in section 11 (the scope, bypasssub, option A, OHKO). Event and value numbers marked "to be assigned" are for HauptSession. Pin: Pokemon Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`), Champions mod checked (it does not override Substitute, its condition, or the sub-reading rows listed below).

## 1. What the pin does

Citations are `data/moves.ts` unless stated.

**The move** (18305-18322, 18372-18374):
- `flags: { snatch, nonsky, metronome }` (18312). No `protect`, no `bypasssub`. `target: "self"`, accuracy `true`, priority 0.
- `volatileStatus: 'substitute'` (18313).
- Fails, in this order (`onTryHit`, 18314-18322):
  1. the user already has a Substitute: `-fail|user|move: Substitute`, `NOT_FAIL` (18315-18318);
  2. `source.hp <= source.maxhp / 4` (a float compare; equivalent to `4 * hp <= maxhp` in integers) or `maxhp === 1`: `-fail|user|move: Substitute|[weak]` (18319-18322).
- Cost (`onHit`, 18324-18326): `directDamage(target.maxhp / 4)` on the user. `directDamage` clamps to an integer with `clampIntRange(damage, 1)` (`sim/battle.ts:2207-2215`); I have not yet read `clampIntRange` itself, so the floor is to be confirmed in phase 2.
- The Substitute's HP: `effectState.hp = Math.floor(target.maxhp / 4)` (18334). So it is `floor(maxhp/4)` at creation.
- Start (18328-18333): `-start|X|Substitute` (18332). The Shed Tail variant (`[from] move: Shed Tail`, 18330) comes from an unmarked move. A partial trap on the holder ends at the same moment, silently: `-end|X|<source>|[partiallytrapped]|[silent]` and the volatile is deleted (18335-18340).

**What it blocks** (`onTryPrimaryHit`, priority -1, 18340-18366):
- Returns at once when `target === source`, when the move has `bypasssub`, or when `move.infiltrates` (18342). Otherwise, for any move aimed at a foe:
  - `damage = this.actions.getDamage(source, target, move)` (18345), one draw of the damage roll and of the crit;
  - if that is `undefined`, `false` or `null`, the user gets `-fail|user` with `[still]` and the handler returns `null` (18346-18350). `getDamage` returns `undefined` for `basePower 0` (`sim/battle-actions.ts`, the `if (!basePower)` line in `getDamage`, about 1605). So a **status move aimed at a foe with a Substitute fails**, printing a plain `-fail|user` (to be confirmed by a recorded battle);
  - the damage is capped at the Substitute's HP (18351-18353); the HP is reduced (18354); the user's `lastDamage` is set (18355);
  - if HP <= 0: `-ohko` when `move.ohko` (18357), then `removeVolatile` (18358), which runs `onEnd`: `-end|X|Substitute` (18368-18374). **There is no `-activate` line on the breaking hit.**
  - else `-activate|X|move: Substitute|[damage]` (18360). **No amount is printed.**
  - recoil on the damage dealt to the Substitute: `applyRecoilDamage(damage, move, source)` (18362);
  - drain: `heal(ceil(damage * drain[0] / drain[1]), source, target, 'drain')` (18363);
  - `AfterSubDamage` events (18364-18365);
  - returns `HIT_SUBSTITUTE` (18366).
- The caller then sets `targets[i] = null` (`sim/battle-actions.ts:1061-1065`). So after the Substitute absorbs a hit: **no secondary effects, no boosts, no status, no contact-related hit effects on the target**. The shared step 0 is at 1054-1058; `tryPrimaryHitEvent` at 1138-1146; `getSpreadDamage` at 1148-1185 (it skips a null target, so one damage draw per absorbed hit).
- The self part of a move (`moveData.self`, self-drops) is not gated by the target and is to be checked in phase 2 with a recorded battle (for example Overheat or Superpower, which drop the user's own stats).

**How it ends:**
- hit that takes the HP to 0 (`-end`, above);
- Tidy Up: `active.removeVolatile('substitute')` (`data/moves.ts:19637`, move at 19630), `-end` printed by `onEnd`;
- switching out: `clearVolatile` sets `this.volatiles = {}` with **no `End` event and no line** (`sim/pokemon.ts:1508-1540`). The Substitute is removed silently. The switch-in copy (`sim/pokemon.ts:1247-1256`) only copies volatiles; Baton Pass copies the Substitute with its HP (the `shedtail` filter at 1250 is the only exception).

**Infiltrator**: `move.infiltrates` skips the Substitute (18342, and the readers below). The assignment of `infiltrates` was not located yet (not in `data/abilities.ts` at its entry 2136, which has no handler). Phase 2.

**Other readers of `volatiles['substitute']`** (owner, line, what it does with a Substitute up):

| Owner | Pin line | Effect | Marked in `src/data/support_manifest.c` |
|---|---|---|---|
| Intimidate | `abilities.ts:2201` | `-immune|target`, no Attack drop | **yes** (471) |
| Infiltrator | `abilities.ts:2136`, `infiltrates` | skips the Substitute (gen 6 and later) | **yes** (540) |
| Chople Berry | `items.ts:1040` | berry does not activate | **yes** (581) |
| Babiri Berry | `items.ts:365` | same | **yes** (665) |
| Charti Berry | `items.ts:822` | same | **yes** (666) |
| Chilan Berry | `items.ts:909` | same | **yes** (667) |
| Coba Berry | `items.ts:1119` | same | **yes** (668) |
| Colbur Berry | `items.ts:1143` | same | **yes** (669) |
| Haban Berry | `items.ts:2760` | same | **yes** (670) |
| Kasib Berry | `items.ts:3139` | same | **yes** (671) |
| Kebia Berry | `items.ts:3163` | same | **yes** (672) |
| Disguise | `abilities.ts:984, 996` | does not activate | no |
| Ice Face | `abilities.ts:1989, 1997` | does not activate | no |
| Supersweet Syrup | `abilities.ts:4718` | does not activate | no |
| Defog | `data/moves.ts:3458` | evasion drop skipped | no |
| Aromatherapy | `data/moves.ts:580` | ally skipped | no |
| Sky Drop | `data/moves.ts:16721` | fails | no |
| Sparkly Swirl | `data/moves.ts:17403` | ally skipped | no |
| Tidy Up | `data/moves.ts:19637` | removes the Substitute | no |

**`bypasssub`** (the flag that lets a move through a Substitute): the marked moves that carry it are Encore (`data/moves.ts:4732`, manifest 269), Coaching (2598, manifest 295), Disable (name 3653, manifest 331), Taunt (18982, manifest 363), Imprison (9497, manifest 411), Perish Song (13241, manifest 429). Heal Block and Psychic Noise carry it too and are not marked. The full set is a generator check in phase 2.

## 2. The state: no new bytes

- `substitute_hp` already exists: a u16 in the position block of tail rev 2 (`docs/decisions/0015-content-expansion-pool.md` section 7; `src/state/battle_internal.h:279`; the codec's `DFI_ENC_TAIL_POS_SUBSTITUTE_OFF`, `src/codec/state_codec.h:74, 200`).
- The invariant is already there: `substitute_hp <= maxhp / 4` (`src/state/invariants.c:583-584`, integer division, equal to the pin's floor).
- Presence is `substitute_hp != 0`. A Substitute with 0 HP does not exist (the break removes it), so zero means none and no second flag is needed. The existing invariant is enough.
- Clearing: `dfi_tail_clear_occupant` already clears the position's fields when the occupant leaves (rev 2, 0015 section 7). The silent clear of the pin is the same behaviour: no event, no line.
- The rev 5 lane A block (2 bytes per position: `slot_pending`, `future_sight`) is **not** touched by this step.
- Byte impact: none. No tail revision, no size change.

## 3. Public values (all proposals; numbers to be assigned by HauptSession)

| # | Shape | Number | Fields | What the foe sees | Info |
|---|---|---|---|---|---|
| V1 | Event `VOLATILE_START`, detail `DUOFORGE_VOLATILE_SUBSTITUTE` | event 39 (existing); volatile **9** (proposed, first free after IMPRISON 8) | position = holder; detail = 9 | `-start|X|Substitute` (presence only) | no HP |
| V2 | Event `VOLATILE_END`, detail 9 | 40 (existing); volatile 9 | position = holder; detail = 9 | `-end|X|Substitute` (break, Tidy Up) | none |
| V3 | Event `ACTIVATE`, cause `MOVE`, id2 = 446 (move id of Substitute, `DFI_MOVE_SUBSTITUTE`, `src/data/pool_tables.h:768`) | 35 (existing) | position = holder; cause MOVE; id2 = 446; **no amount field** | `-activate|X|move: Substitute|[damage]` (a hit was absorbed) | no amount |
| V4 | Event `FAIL`, cause `MOVE`, id2 = 446, detail 1 = already up, detail 2 = HP too low | 13 (existing); **detail values 1 and 2 are new** | position = user | `-fail|user|move: Substitute` (and `[weak]`) | none |
| V5 | Event `FAIL`, no cause, no detail | 13 (existing) | position = user | `-fail|user` (a status move into a Substitute) | none |
| V6 | Event `IMMUNE`, no cause | 12 (existing) | position = target | `-immune|X` (Intimidate vs a Substitute) | none |
| V7 | Event `DAMAGE`, cause `NONE` | 4 (existing) | position = user, HP after | `-damage|user|hp`: the user's own HP loss, as any damage | own HP is public as today |
| V8 | Position ext volatile bit 0 `DUOFORGE_POSITION_EXT_SUBSTITUTE` | existing bit (`include/duoforge/duoforge.h:841`) | presence, both sides | presence only | no HP |

What is new and needs your OK: **volatile 9** (V1, V2) and **FAIL detail values 1 and 2** (V4). Everything else uses existing events and existing bit 0. The detail values are a decision for you: the alternative is to print `[weak]` and "already up" as V5 with no detail, which loses the difference.

`-ohko` (the one-hit KO of a Substitute's break, `data/moves.ts:18357`): no event exists for it. **Proposal: refuse OHKO moves (`move.ohko`) unless a marked row needs them**; none of the marked rows has one (phase 2 check).

The partial trap ending silently at the start (18335-18340): the state change (`trap_turns`, `trap_source`, `trap_move`, `trap_band` to zero) happens with the Substitute's start and has no event, as in the pin. Phase 2 checks that the trap's own events are not lost.

## 4. What the foe sees, and information safety

- **The Substitute's HP never reaches the foe.** The only public lines are the start (V1), the absorbed hit (V3, no amount), the break (V2), the fail lines (V4, V5), the user's HP cost (V7, the user's own HP, which is public as today). No event field, no view field and no encoder column carries `substitute_hp`.
- **Presence**: V8 (both sides; presence only).
- **The owner's own Substitute HP**: the pin's request does not show it. `getMoveRequestData` (`sim/pokemon.ts:1083-1150`) and `getSwitchRequestData` (1153-1190) have no Substitute entry; the only volatile reads there are `partiallytrapped` (1100) and `commanding` (1182). So **the owner does not see its own Substitute HP either**. The view hides `substitute_hp` on both sides, which matches the info boundary of decision 0007 (the request is the owner's information).
- Currently `src/state/view.c:417` refuses a **foe** Substitute (`E_UNSUPPORTED`) on the public-record path, and `src/state/observation.c` has no writer for the Substitute bit (grep: none). Both change with this step (see section 6).

## 5. Determinization (decision 0023)

- A public-record field for the Substitute is **not needed beyond presence** (V8). "Has a Substitute" is public; the HP is not.
- How a hypothesis world gets the HP: right after the start, the HP is `floor(world's maxhp / 4)`, the same kind of derivation as Revival Blessing's HP from the world's maxhp (0023 line 64: values derived from a hidden one are computed from the world). **That holds only for a fresh Substitute.** Once a hit has been absorbed, the amount of damage is never printed (V3 has no amount), so the remaining HP is hidden and cannot be derived from maxhp. This is why 0023 line 140 refuses a foe Substitute ("whose HP follows hidden damage").
- Options, for your decision:
  - **A (recommended for the first step)**: keep the honest world's refusal of a foe Substitute (E_UNSUPPORTED, as 0023 line 140 says). The public record and the observation show presence; `duoforge_battle_from_view` (the honest world) refuses a foe Substitute. Live games with a foe Substitute then cannot be searched (as today).
  - **B**: draw the HP uniformly from `[1, floor(maxhp/4)]` for an observed Substitute, with the world's own damage afterwards, and reject a world whose break or absorb does not match the public lines (`-end`, `-activate`). This is a sampled hidden variable; 0023 would need its own line for it.

## 6. The engine and the view (phase 2 scope if approved)

- `view.c:417`: keep the public-record refusal for a foe Substitute **or** write presence only; a decision (section 5).
- `observation.c`: write `DUOFORGE_POSITION_EXT_SUBSTITUTE` from `substitute_hp != 0`, both sides.
- The move's handler in `turn.c`: the TryPrimaryHit gate of section 1, the HP cost, the break, the recoil, the drain; events V1-V7.
- Marked rows that change with the Substitute (**they must change in the same step, or the marks become wrong**; today they are right only because no Substitute exists):
  - Intimidate (`src/combat/turn.c` ~943-990 today has the Intimidate code): the `-immune` line instead of the drop (V6);
  - Infiltrator (its `infiltrates` is needed by the gate; the assignment to be found);
  - nine resist berries (Chople, Babiri, Charti, Chilan, Coba, Colbur, Haban, Kasib, Kebia): no activation when the hit lands on the Substitute and the move has no `bypasssub`; the engine has none of them yet, so this is a rule in every berry's handler.
- `bypasssub` (the flag): it is in `IGNORED_FLAGS` (`tools/datagen/gen_closure.py:113`) and `INERT_FLAG_READS = {'bypasssub': 'substitute'}` (2423), because the flag "matters only when a modelled row reads it" (`tools/datagen/README.md:69`, "the move flags byte is full and stays so"). Marking the Substitute makes it matter. Then each marked move that carries it (Encore, Coaching, Disable, Taunt, Imprison, Perish Song, and any other marked one the generator finds) would be UNMODELED. So the flag needs **a bit in the table**. The precedent is the `dfi_pool_move_flags2[]` column (bit 1 `sound`, bit 2 `heal`, `tools/datagen/README.md:61`). **Proposal: bit 3 `bypasssub` in `flags2`** (bit 0 to be checked free). This is a table change: the pool hash moves, and the builder rule applies (regenerate, update `POOL_TABLE_HASH` and `POOL_HASH_HEX`, FP_KP/KPD). It is not a public value.
- `tools/datagen/gen_closure.py:2421-2423`: `INERT_FLAG_READS` loses `bypasssub` and the Substitute's entry changes. The comment at 111 ("Substitute" in the list of flags with no consumer) changes too.

## 7. Rows

**Mark (G60):**
- **Substitute** (`DFI_MOVE_SUBSTITUTE` 446; the move with the gate, the cost, the break, the events V1-V5 and V7).

**Mark only together with the Substitute, as changes to already marked rows (needs your approval, because the scope grows):**
- Intimidate, Infiltrator, the nine resist berries (section 6);
- the marked `bypasssub` moves: Encore, Coaching, Disable, Taunt, Imprison, Perish Song (the flag bit; their rows stay correct, and a test checks that a bypassing move passes the gate).

**Refuse (stay unmarked, `E_UNSUPPORTED` or not in the pool, as now):**
- **Baton Pass** (`data/moves.ts:1097`, `selfSwitch` copies volatiles, with the Substitute and its HP): a non-boolean `selfSwitch` is UNMODELED already (0015 section 4.2); it stays refused. Its handler would have to move `substitute_hp` with the volatile, and the rule is not in this step.
- **Shed Tail** (16166): non-boolean `selfSwitch` and the Substitute's `[from]` start. Refused.
- Tidy Up, Defog, Aromatherapy, Sky Drop, Sparkly Swirl, Disguise, Ice Face, Supersweet Syrup: unmarked, so the Substitute is only the first step. Their gates do not change. (Disguise and Ice Face would need the gate too, if they are marked later: they are not in the manifest.)
- OHKO moves (see section 3).

## 8. Python side (HauptSession owns it; I do not edit)

- `python/duoforge/_layout.py:97` (`DUOFORGE_POSITION_EXT_SUBSTITUTE` = 1) and `:145` (`DUOFORGE_VIEWEXT_FEATURE_SUBSTITUTE` = 23) already exist. A new `DUOFORGE_VOLATILE_SUBSTITUTE` (9) is to be mirrored if `_layout.py` mirrors the volatile ids (to check).
- `python/duoforge_live/lines.py:140` maps `-start|X|Substitute` to the SUBSTITUTE feature. The `-end` and `-activate|…|move: Substitute|[damage]` lines are not mapped in that file (to check); the live adapter must not refuse them after this step, or must say why.
- `python/duoforge/features.py`: the encoder column for volatile bit 0 exists (`src/encode/encode.c:79`); no Python rule change is expected.

## 9. Encoder impact

- **No new column.** The volatile bit 0 column (`dfi_enc_volatile_feature[0] = DUOFORGE_VIEWEXT_FEATURE_SUBSTITUTE`, `src/encode/encode.c:79`) carries presence. The feature bit 23 must be marked supported when the step lands. Whether that alone changes the encoder version is your decision (0029's QUICK_GUARD had no encoder change, and this one is the same shape).

## 10. Tests and checks I will run in phase 2 (not started)

- A C test `tests/test_pool_g60.c` for the gate, the failure cases, the cost, the break, recoil and drain, the bypass, and the silent clear on switch.
- Recorded POOL battles with genders stated for every interaction: Substitute itself, a status move into a Substitute, an attack that breaks it, an absorbed hit with recoil and drain, Intimidate vs a Substitute, a resist berry vs a Substitute, a `bypasssub` move through it (Encore, Taunt), Baton Pass refused.
- Mutation checks: the cost floor, the HP compare, the bypass set, the break ordering, the drain and recoil, the secondaries after an absorbed hit, the Intimidate immunity, the berry gate.
- A differential campaign of about 300 battles.

## 11. What I want from you (lead)

1. Volatile **9** for the Substitute, and FAIL detail values **1 and 2** (V4): yes or no.
2. The `bypasssub` bit in `flags2` (bit 3 proposed): yes or no.
3. Scope of G60: the move alone (and then the marked rows are wrong while the Substitute exists, so this is not an option), or the move with the changes to Intimidate, Infiltrator, the nine berries and the six `bypasssub` moves in the same step.
4. The foe Substitute: option A (refuse in the honest world, public presence only) or B (sampled HP).
5. OHKO refused (section 3): yes or no.

Nothing in phase 2 starts until these are answered.

## 12. Known gaps in this proposal (honest)

- `getDamage`'s `undefined` for a status move is read, not yet confirmed by a recorded battle (the `-fail|user` line for a status move into a Substitute).
- `clampIntRange` (the floor of `directDamage`) is not read.
- The line for the user's HP cost (V7) may carry a `[from]` part in the pin: not read yet.
- Infiltrator's assignment of `infiltrates` is not located.
- The self part of a move against a Substitute (Overheat, Superpower) is not read.
- Multi-hit: each hit of a multi-hit move passes the gate separately? Not read (Twin Beam and Dual Wingbeat are marked, G33).
- The full set of marked rows that carry `bypasssub` comes from a generator check, not from my manual list.

## 13. Phase 2 update: every Substitute line of the pin, and its mapping

Every `add()` of the pin that names the Substitute (grep of `sim/` and `data/`, including the Champions mod):

| Line | Pin | Mapping |
|---|---|---|
| `-start|X|Substitute` | `data/moves.ts:18332` | VOLATILE_START, detail 9 (mapped) |
| `-start|X|Substitute|[from] move: Shed Tail` | `data/moves.ts:18330` | refused (Shed Tail is unmarked; the converter's `-start` branch needs no attribute) |
| `-end|X|Substitute` | `data/moves.ts:18373` (onEnd: break, Tidy Up) | VOLATILE_END, detail 9 (mapped; a switch-out prints none) |
| `-activate|X|move: Substitute|[damage]` | `data/moves.ts:18360` (absorbed hit, no amount) | ACTIVATE, cause MOVE, id2 Substitute (mapped) |
| `-activate|X|Substitute|[damage]` | `sim/battle.ts:2234` | **unreachable in gen 9**: the branch needs `gen <= 1` (battle.ts:2220); the converter refuses it (no `move:` prefix) |
| `-fail|X|move: Substitute` | `data/moves.ts:18316` (already has one) | FAIL, cause MOVE, id2 Substitute, detail EXISTS (mapped) |
| `-fail|X|move: Substitute|[weak]` | `data/moves.ts:18320` (HP a quarter or less) | FAIL, cause MOVE, id2 Substitute, detail WEAK (mapped) |
| `-fail|X` (a status move into a Substitute, `[still]` set by the handler) | `data/moves.ts:18347` | the plain FAIL of the user (mapped, no detail) |
| `-ohko` (a break by an OHKO move) | `data/moves.ts:18357` | refused: no event; a break by an OHKO move is `E_UNSUPPORTED` with a named cause (lead's decision 5) |
| `-end|X|<source>|[partiallytrapped]|[silent]` (the sub's start ends a partial trap) | `data/moves.ts:18335-18340` | silent, dropped by the converter (like every `[silent]` line); the engine clears the trap with no event |
| `-immune|X` (Intimidate vs a Substitute, no `[from]`) | `data/abilities.ts:2201-2202` | IMMUNE, no cause (mapped by the existing `-immune` branch) |
| `-damage|X|hp` (the user's HP cost, no `[from]`) | `sim/battle.ts:2255-2262` (default branch of directDamage) | DAMAGE, cause NONE (existing branch) |

Converter (`tools/reference/trace_to_c.py`): the `-hitcount` count includes the absorbed and the breaking hit (`-activate|X|move: Substitute|[damage]`, `-end|X|Substitute`), as it includes a `-damage` line. The unit suite (89 tests) passes unchanged.

## 14. Public causes

`DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE` = 8u (approved by HauptSession): a Substitute on either side refuses `duoforge_battle_public` and the honest world, with this named cause, counted by the arena (the Python side is HauptSession's, in hs/g60-python).
