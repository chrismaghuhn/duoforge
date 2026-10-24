<a id="5ff"></a>

# 5ff. -, Double Shock changes its user's type after a hit on a Substitute

- Area: moves
- Step: -
- Tests: duoforge.reference.conformance_pool, duoforge.reference.battle_pins, duoforge.reference.conformance_tables

5ff. **-, Double Shock changes its user's type after a hit on a Substitute** (Fuzz lane, branch `fuzz/553-double-shock-substitute`; found by the differential fuzzing of issue 396, issue 553; no new public value). Pin: a target whose hit a Substitute took is null, not false (`data/mods/champions/scripts.ts:349-352`), so selfDrops (`sim/battle-actions.ts:1096`) runs Double Shock's self onHit (`data/moves.ts:3960-3964`): `-start|user|typechange|???/...|[from] move: Double Shock`. The engine's self step counted only `hit[]` (fz_167_14); it now counts `sub_off[]` too, as the recharge and Glaive Rush already do.

- **Evidence.** The recording `fz553_double_shock_substitute` (synthetic teams, trace from the pinned Showdown b2cb775). Every other reference battle is unchanged; the pool set grows by one.
- **Mutant.** The fix reverted alone: killed by `fz553_double_shock_substitute` and by no other battle (`duoforge_diff_runner` over every pool record).
