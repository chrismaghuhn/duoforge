<a id="5fh"></a>

# 5fh. -, A resist berry's [weaken] line after Symbiosis

- Area: items
- Step: -
- Tests: duoforge.reference.conformance_pool, duoforge.reference.battle_pins, duoforge.reference.conformance_tables

5fh. **-, A resist berry's [weaken] line after Symbiosis** (Fuzz lane, branch `fuzz/553-symbiosis-resist-berry`; found by the differential fuzzing of issue 396, issue 553; no new public value). Pin: a resist berry's onSourceModifyDamage calls eatItem (`-enditem|X|Berry|[eat]`, then AfterUseItem: an ally's Symbiosis passes its item, `sim/pokemon.ts:1783-1805`) and then prints `-enditem|X|Berry|[weaken]` (`data/items.ts`, e.g. :4360-4363). The engine played the lines in this order, but the foe's view fold took the `[weaken]` ITEM_END (detail 1) for a new loss and marked the eater's item gone, although Symbiosis had just given it one: the knowledge invariant stopped the battle with E_INVARIANT (fz_204_41). The fold (`src/combat/events.c`) now skips the `[weaken]` line: the `[eat]` line already marked the berry gone. The converter's disguise rows (`trace_to_c.py`) skip it likewise.

- **Evidence.** The recording `fz553_symbiosis_resist_berry` (synthetic teams, trace from the pinned Showdown b2cb775). Every other reference battle is unchanged; the pool set grows by one.
- **Mutant.** The fix reverted alone: killed by `fz553_symbiosis_resist_berry` and by no other battle (`duoforge_diff_runner` over every pool record).
