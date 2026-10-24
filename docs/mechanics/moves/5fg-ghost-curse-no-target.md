<a id="5fg"></a>

# 5fg. -, A Ghost Curse with no foe standing fails with [notarget]

- Area: moves
- Step: -
- Tests: duoforge.reference.conformance_pool, duoforge.reference.battle_pins, duoforge.reference.conformance_tables

5fg. **-, A Ghost Curse with no foe standing fails with [notarget]** (Fuzz lane, branch `fuzz/553-ghost-curse-no-target`; found by the differential fuzzing of issue 396, issue 553; no new public value). Pin: a Ghost Curse aimed at the user's side becomes randomNormal (the Champions onModifyMove), and useMove calls getRandomTarget twice (`sim/battle-actions.ts:432-442`). With no foe standing it draws nothing and returns the fainted `foe.active[0]` (`sim/battle.ts:2512-2521`: `side.randomFoe()` is null); getMoveTargets finds no target and useMove shows `|move|user|Curse|p2: Name|[notarget]` and `-fail`. The engine's `dfi_curse_targets` returned E_INVARIANT (fz_334_84); it now leaves the move without a target, and the move body's path for a move with nothing to hit prints the same lines.

- **Evidence.** The recording `fz553_ghost_curse_no_target` (synthetic teams, trace from the pinned Showdown b2cb775). Every other reference battle is unchanged; the pool set grows by one.
- **Mutant.** The fix reverted alone: killed by `fz553_ghost_curse_no_target` and by no other battle (`duoforge_diff_runner` over every pool record).
