# 0040 - Aegislash: Stance Change and King's Shield (step G66, decision 0015 letter 5cb)

Status: DRAFT, phase 1 (design only, no engine code). Lane A batch 4, builder H9. The values in section 3 are proposals and are not approved; HauptSession assigns the numbers.

Pin: Pokemon Showdown b2cb775 (read only), Champions mod checked first.

## 1. Pin

**Champions mod**
- `data/mods/champions/moves.ts:564-568`: `kingsshield` is `inherit: true`, `isNonstandard: null`, `pp: 5`. Nothing else changes.
- No Champions override for `stancechange` (`data/mods/champions/abilities.ts` has none).
- `data/mods/champions/learnsets.ts:10757-10790`: Aegislash learns `kingsshield` and `protect` (9M).
- `data/mods/champions/formats-data.ts:3391-3396`: `aegislash` tier OU; `aegislashblade` has no tier (battle-only).

**Formes** (`data/pokedex.ts`)
- Aegislash (Shield), 12803-12819: base HP 60, Atk 50, Def 140, SpA 50, SpD 140, Spe 60; Steel/Ghost; dex 681; ability Stance Change.
- Aegislash-Blade, 12820-12833: base HP 60, Atk 140, Def 50, SpA 140, SpD 50, Spe 60; Steel/Ghost; dex 681; `requiredAbility: Stance Change`; `battleOnly: Aegislash`.
- Only the Shield forme can be brought (the Blade is battle-only).

**Stance Change** (`data/abilities.ts:4523-4535`)
- `onModifyMovePriority: 1`, `onModifyMove`: returns for a transformed attacker; returns for a Status move other than King's Shield; King's Shield targets Aegislash, every other move targets Aegislash-Blade; `attacker.formeChange(target)` only when the species name differs.
- Flags: `failroleplay`, `noreceiver`, `noentrain`, `notrace`, `failskillswap`, `cantsuppress`.

**The forme change** (`sim/pokemon.ts`)
- `formeChange` without `isPermanent` (1427-1487): `setSpecies` (1387-1418) re-reads `species.baseStats` with the set's EVs, IVs and nature into `storedStats` and `baseStoredStats`. `maxhp` is not recomputed (only `updateMaxHp`, for a permanent change, touches it), so HP does not change. Speed is 60 in both formes. No `detailschange`, no ability change.
- Line: `battle.add('-formechange', this, species.name, message, '[from] ability: Stance Change')` with `message` undefined. `battle.add` joins with `|` (`sim/battle.ts:3093-3099`), so the line is `|-formechange|p1a: Aegislash|Aegislash-Blade||[from] ability: Stance Change` (empty third field). The same shape for King's Shield with `Aegislash`.
- Reverting: `clearVolatile` calls `setSpecies(this.baseSpecies)` (`sim/pokemon.ts:1559`): the Shield forme comes back on every switch-out, with no line.

**Timing** (`sim/battle-actions.ts:431-439`, `useMove`): the change runs in `ModifyMove` after BeforeMove (sleep, paralysis, flinch and the rest), before the `|move|` line and before the stall check of King's Shield. A King's Shield that fails on the stall counter still changes the forme.

**King's Shield** (`data/moves.ts:9905-9955`)
- Status, accuracy true, priority 4, `stallingMove: true`, `onPrepareHit` (the stall counter as Protect's), `volatileStatus: kingsshield`, target self. Flags: `noassist`, `failcopycat`, `failinstruct` (no `protect` flag).
- Condition: duration 1; `onStart` prints `-singleturn|X|Protect`; `onTryHitPriority: 3`; `onTryHit`: `checkMoveBypassesProtect(move, source, target, false)` (`sim/battle.ts:1300-1310`). With `blockStatus` false, a Status move passes, and so does a move without the `protect` flag. Otherwise it prints `-activate|X|move: Protect`, resets an Outrage lock (unmarked, no effect here) and, when the move makes contact, `boost({atk: -1}, source, target, King's Shield)`: the attacker's Attack drops, the holder is the source. Returns NOT_FAIL.
- `onHit`: `addVolatile('stall')`.

**Breaks and the other protect-ish rows**
- `hitStepBreakProtect` (`sim/battle-actions.ts:758-777`): `breaksProtect` moves (Feint, Phantom Force) remove `kingsshield` with the other variants (list at line 760), remove the side's Wide Guard and Quick Guard for a foe, print `-activate|X|move: <name>|[broken]` (Feint: `-activate|X|move: Feint`), and delete the stall counter.
- `HitProtect` (`sim/battle.ts:1302`): the only handler in the pin is Piercing Drill (`data/abilities.ts:3284`, Future, not in the format). No marked ability bypasses by it.
- Unseen Fist (`data/abilities.ts:5276-5280`) deletes the `protect` flag of contact moves in `onModifyMove`, so its holder's contact moves pass King's Shield and Protect. Unseen Fist is not marked: out of scope, but it is the one ability that would change this design if marked later.

## 2. What the engine already has

- `dfi_run_protect(r, user, kind)` (`src/combat/turn.c:3810-3840`): stall counter, the `DFI_VOL_PROTECT` volatile, `protect_kind` stored in the tail, `DUOFORGE_EVENT_PROTECT` (the `-singleturn` line). King's Shield is this function with a new kind.
- Protect's TryHit step (`src/combat/turn.c:5322-5336`): `hit[i]` and the `BLOCKED` event (`-activate ... move: Protect`). King's Shield differs in two places only: the status exemption and the contact drop.
- The dispatch on the special id (`src/combat/turn.c:6142-6146`, PROTECT and SPIKY_SHIELD).
- `dfi_break_protect` (Feint G28, Phantom Force G58): already removes the variant volatile and resets `protect_kind` (so King's Shield breaks need no change).
- The attack drop: `dfi_boost(r, attacker, {atk -1}, holder, effect)` with a move effect, as the move-caused drops at `turn.c:4469`, `:5582`. Clear Body, Hyper Cutter, Mirror Armor, Defiant and Competitive go through the existing boost path, with the holder as the source.
- Pre-move `ModifyMove` precedent: freeze thaw and Choice Scarf emit before the move line (`turn.c:5910-5925`). Stance Change goes at the same point.
- Tail: `forme_now[DUOFORGE_MAX_ROSTER]` (`src/state/battle_internal.h:337`, `0 = own forme, else forme id + 1`) is already encoded (`src/codec/state_codec.c:120`, `:241`) and checked against `forme_count` (`src/state/invariants.c:707`, `:734`). Nothing writes it today. `src/state/identity.c:30-50` already says that a temporary forme clears `forme_now` itself at the switch-out.
- Stats: `dfi_derive_stats` (`src/state/closure_member.c:353-378`) derives `hp_max` and `stats[]` from a forme's base; `dfi_closure_member_mega_evolve` (`:417-430`) writes `m->stats` for the Mega forme. A temporary forme does the same, with the Blade base.
- Forme ids: `DFI_FORME_AEGISLASH` 244 (`src/data/pool_tables.h:266`, row `pool_tables.c:496`). **No Blade row exists**, and the ability row (`pool_tables.c:3772-3774`, abilities `stancechange`, 46 learnable moves) exists.
- Ability id `DFI_ABILITY_STANCECHANGE` 180 (`pool_tables.h:1106`). Move id `DFI_MOVE_KINGSSHIELD` 277 (`pool_tables.h`, the move table). Both rows are UNMODELED today (`pool_tables.c:1257-1258` for the move).
- Event `DUOFORGE_EVENT_FORME` = 30 (`include/duoforge/duoforge.h:1031`): `[detailschange] position, id: the new forme`, used by Mega only (`turn.c:8100-8104`).
- The view: decision 0018 already specifies `forme` (u16, bit 19 `FORME_CHANGE`, `duoforge.h:894`), and says a temporary forme "is reset when the member leaves the field". `src/state/observation.c` never writes it, and `src/encode/encode.c:270-271` reads `r->forme`, which no C code fills (see proposal G).

## 3. Proposal: what needs a decision

A. **A battle-only Blade forme row.** Appended after the last forme: `DFI_FORME_AEGISLASHBLADE`, base `{60, 140, 50, 140, 50, 60}`, types Steel/Ghost, dex 681, weight as the Shield forme, no legal set and no learnable moves. Changes `DFI_POOL_FORME_COUNT`, the POOL hash and the fingerprints (the generator, `gen_closure.py --pool`). Alternative: derive the Blade stats by swapping Atk with Def and SpA with SpD inside the engine. Rejected: tables are generator-only (decision 0015).

B. **Handler ids.** King's Shield gets a special id: the next free one is 92 after PHANTOM_FORCE 90 (UNMODELED 91 moves). Stance Change keeps ability id 180 and needs its handler marked (manifest and the `ModifyMove` code); ask whether an ability special id is needed too.

C. **`protect_kind` value 2**, `DFI_PROTECT_KINGS_SHIELD`. `DFI_TAIL_PROTECT_KIND_MAX` goes from 1 to 2 (`src/state/battle_internal.h:232`, invariant at `src/state/invariants.c:599`). No new byte: schema 0x0303 stays, the decoder accepts 0 to 2. The Python model (`tools/state_model`) must accept 2.

D. **The temporary forme event.** Reuse `DUOFORGE_EVENT_FORME` (30) with `cause = ABILITY`, `id2 = Stance Change + 1` and `id = the new forme` (Blade or Shield). It prints `-formechange`; Mega keeps cause NONE and `detailschange`. No new event kind. Ask: is reusing 30 with a cause acceptable, or does it need a new kind (48+, your numbering)?

E. **Forme state.** `forme_now[m]` = Blade id + 1 while in the Blade forme, 0 for the Shield. It is set in the Stance Change code and cleared at the switch-out (`dfi_tail_clear_occupant`, `src/state/identity.c`). Stats: `m->stats` re-derived with the Blade base and restored to the Shield's at the switch-out. Phase 2 will check whether the state codec encodes `m->stats` or re-derives it on decode; if re-derived, the decoder needs the same rule.

F. **Tail bytes:** none new (forme_now and protect_kind are both already in the tail).

G. **Public view (existing decision, not a new value).** Decision 0018 (`forme`, bit 19) must be filled for a temporary forme: `observation.c` writes `forme = forme_now` for a standing member, and the encoder reads it. This is a gap between 0018 and the code, found in phase 1; it is not a new value. Flagged so you can decide whether it comes with this step.

## 4. Rows to mark (phase 2, only after approval)

- Ability `stancechange` (id 180): Aegislash's only ability.
- Move `kingsshield` (id 277), with `protect_kind` 2.
- Blade forme row (A), if approved.

Not marked: Baneful Bunker (Toxapex, which has no supported ability), Unseen Fist (unmarked, see section 1), Transform. Mold Breaker is not yet checked against the pin (phase 2 item if it is marked).

## 5. Refusals (E_UNSUPPORTED, never a guess)

- Transform onto or from an Aegislash: `stancechange` checks `transformed`; Transform is unmarked. Refuse if it is ever marked.
- Skill Swap with an Aegislash holder: `failskillswap` (the holder keeps its ability). **Coordination:** if G70 (Skill Swap, batch 4) is marked, its Skill Swap has to fail on Aegislash. Please pass to the G70 builder.
- Role Play, Trace, Entrainment: `failroleplay`, `notrace`, `noentrain`. Refuse each if its row is marked.
- Gastro Acid and other suppressors: `cantsuppress`, so the ability stays. Refuse the suppression if its row is marked.

## 6. Interactions to test (recorded POOL battles, genders stated, six members, unique items, marked rows only)

1. Stance Change: a damaging move changes to the Blade before the `|move|` line, and the Blade's Atk gives more damage than the Shield would (the same hit in both forms).
2. A Status move in the Blade forme: no change, the Blade stays.
3. King's Shield from the Blade: the change to the Shield comes before the move line; the Shield's Def and SpD then apply.
4. King's Shield blocks a contact physical move: the attacker's Atk drops, with Defiant on the attacker (+2, Atk).
5. King's Shield blocks a non-contact attack: no drop.
6. King's Shield passes a Status move (Thunder Wave, Will-O-Wisp).
7. Protect and King's Shield on the shared stall counter: the second use fails, with the stall roll.
8. Feint breaks King's Shield (`-activate ... move: Feint`, the protect_kind reset).
9. Phantom Force breaks King's Shield on its hit (`[broken]`).
10. Switch-out resets the Blade to the Shield with no line (the next `switch` shows the Shield's stats; the view forme goes back to 0).
11. Intimidate on the Blade or the Shield: a stage drop, no forme change.
12. Wide Guard or Quick Guard on the holder's side against a spread move, with King's Shield up.
13. Substitute on the holder (King's Shield used the turn before the Substitute).
14. A Struggle: the change to the Blade (Struggle is Physical).

Mutants: the forme change off, the Blade stats swapped, the status exemption removed, the contact drop off, the drop source wrong (Defiant does not fire), protect_kind not set or not cleared, the stall counter not shared, the switch-out revert missing, `forme_now` not cleared, the `-formechange` line without the `[from]` part.

Campaign: about 300 random battles with Aegislash teams (Stance Change and King's Shield in the team), `diff_driver.py random`, data POOL, under the machine lock. Report PASS, DIVERGENCE, UNSUPPORTED, ORACLE_GAP.

## 7. Open questions for the lead

1. Blade forme row (A): approve, or the swap alternative?
2. Handler ids: King's Shield special id (92?), and whether Stance Change needs one.
3. protect_kind 2 (C): approve the value and the max change.
4. Event 30 with cause ABILITY (D): approve reuse, or a new event kind.
5. The 0018 forme view fill (G): in this step, or a separate one?
6. Skill Swap refusal for G70's builder (section 5).

## 8. Phase 2 decisions (as built)

- **The line carries no cause.** The pin's `formeChange` takes its source from `this.battle.effect`. When a move's use changes the forme (King's Shield, Iron Head), the source is that move, so the line is `|-formechange|POS|SPECIES|` with NO `[from]` attribute and an empty message field (sim/pokemon.ts:1427-1487, battle.add joins an undefined message as ''). The `[from] ability: Stance Change` form exists in the pin, but no recorded battle shows it. The line therefore does not say which ability caused it.
- **The FORME event's cause ABILITY, id2 = Stance Change + 1 comes from the engine's knowledge**, not from the line. The converter (`trace_to_c.py`, the named rule FORME-STANCE) accepts the bare line only when: the species is `Aegislash` or `Aegislash-Blade`; the next line is the move line of the same position; the Shield's forme comes only before King's Shield, and the Blade's forme before any other move. A `-formechange` for any other species, or with another `[from]` ability, is refused (`tools/reference/test_trace_to_c.py`, class FormeStance: negative controls). The conformance then compares the engine's event with the one the reference shows.
- **Stats, strict rule** (`src/state/invariants.c`): the Blade's stats are allowed ONLY for an Aegislash on the Blade forme (`forme_now` = the Blade's id + 1). In every other case, including `forme_now` 0 (the Shield), the member's stats must be the sheet's. `tests/test_pool_g66.c` checks: Blade stats under the Shield are refused; the Blade's forme with the sheet's stats is refused; the Blade's forme with the Blade's stats is valid and is a temporary forme in the public view.
- **Battle length.** A spec's `max_steps` is the number of steps including the opening step 0, so a plan of N turns needs `max_steps` = N + 1. Two of the first recordings ran one turn fewer than planned (the second turn's King's Shield and switch-back did not happen); they are re-recorded.
