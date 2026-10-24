<a id="5fb"></a>

# 5fb. -, Illusion ends at its holder's own DamagingHit handler (issue 552)

- Area: abilities
- Step: -
- Tests: duoforge.reference.conformance_pool, duoforge.reference.battle_pins, duoforge.reference.conformance_tables

5fb. **-, Illusion ends at its holder's own DamagingHit handler (issue 552)** (Fuzz lane, branch `fuzz/552-illusion-end-order`; found by the differential fuzzing of issue 396, 11 battles, among them fz_217_36 and, with Cursed Body, fz_122_62; no new public value). Pin: Illusion's `onDamagingHit` (`data/abilities.ts:2071-2075`) has no order, so `runEvent('DamagingHit')` sorts it after the ordered handlers (Rough Skin, order 1; Rocky Helmet, order 2) and, among the unordered handlers, by the target's index in the move's target list (`compareLeftToRightOrder`, `sim/battle.ts:421-426`, a stable sort). The engine ended the disguise of every damaged target before all DamagingHit handlers, so `replace` / `-end Illusion` came before Rocky Helmet's or Rough Skin's `-damage` on the attacker and before an earlier target's Weak Armor or Cursed Body lines.

- **The engine.** `dfi_illusion_break` (`src/combat/turn.c`) ends the disguise (one `ILLUSION_END` event, as before; the folds of decision 0026 section 4 are unchanged) at the holder's ability place in the per-target loop of unordered handlers in `dfi_move_body_hit_loop`: after its status's handler (a thaw), before its item's (Air Balloon) and the attacker's Poison Touch. Illusion is the holder's one ability, so no other ability of it competes. A holder the hit knocked out runs it too, as before (its faint is not processed yet).
- **Evidence.** The recording `fz552_illusion_damaginghit_order` (synthetic teams, trace from the pinned Showdown b2cb775): step 1, Golurk's Iron Head on Zoroark-Hisui disguised as Banette with a Rocky Helmet: the helmet's `-damage` on Golurk, then `replace` and `-end Illusion`; step 4, after a switch out and in that disguises it again, Tauros's Rock Slide hits Polteageist (Weak Armor, p1a) and Zoroark-Hisui (p1b): Weak Armor's lines, then the `replace`. Every other reference battle is unchanged; the pool set grows by one.
- **Mutant.** The old loop back (the disguise of each damaged target ended before Rough Skin): killed by `fz552_illusion_damaginghit_order` and by no other battle.
- **Open.** The original campaign cases (the cloud report) were not rerun on this machine; the recording covers both orders the issue names.
