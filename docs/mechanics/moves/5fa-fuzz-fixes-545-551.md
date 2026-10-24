<a id="5fa"></a>

# 5fa. -, Six fuzz issues of issue 396: 545, 546, 547, 548, 550 and 551

- Area: moves
- Step: -
- Tests: duoforge.reference.conformance_pool, duoforge.reference.battle_pins, duoforge.reference.conformance_tables

5fa. **-, Six fuzz issues of issue 396: 545, 546, 547, 548, 550 and 551** (Fuzz lane, branch `claude/project-thread-fxsdy2`, PR #628; found by the differential fuzzing of issue 396; no new public value). One commit per cause, all in `src/combat/turn.c`: (a) in `dfi_type_mod`, (b), (c) and (d) in the hit loop phase `dfi_move_body_hit_loop`, (e) in `dfi_substitute_takes`, (f) in `dfi_move_body_try_move`.

- (a) **Iron Ball against a Flying dual type** (issue 548, fz_236_101): Iron Ball's onEffectiveness (`data/items.ts:3056-3060`) returns 0 for every type of a Flying holder, so a Ground move is neutral against Corviknight (not super effective through Steel); not under Gravity. Ingrain and Smack Down are unmarked.
- (b) **Dragon Tail's drag after the damage** (issue 545, fz_177_82): the forceSwitch of a damaging move is step 6 of the Champions spreadMoveHit (`data/mods/champions/scripts.ts:391`), after the damage and the secondaries and before DamagingHit, so Guard Dog's line follows the -damage line, and a target the hit knocked out is not dragged.
- (c) **Air Balloon after the target's own DamagingHit abilities** (issue 546, fz_332_41): a holder's unordered handlers are collected ability before item (`sim/battle.ts:1117-1130`) and the sort is stable, so Weak Armor's lines (and A2a's Poison Point and Gooey) come before -enditem; the attacker's Poison Touch stays after both.
- (d) **Ice Spinner's AfterHit** (issue 547, fz_279_3): the terrain ends after the DamagingHit handlers (`scripts.ts:406-414`), with no test of the user's HP (the Champions loop).
- (e) **Ice Spinner on a Substitute** (issue 547, fz_250_45): the move's onAfterSubDamage ends the terrain when the user has HP (`data/moves.ts:9429-9433`).
- (f) **A non-Ghost Curse is not redirected** (issue 550, fz_101_7): Curse's onModifyMove sets the target to self before getMoveTargets (`data/moves.ts:3276-3281`), so Follow Me and Rage Powder do not take it.
- (g) **lockedmove as a faint point** (issue 551, fz_409_37): the lock's onResidual is a faint point (`sim/battle.ts:560-566`), also for a holder whose perish0 faint is only queued. Both parts came to `main` before this PR merged, with issue 606 ([5dv](5dv-lock-holder-put-to-sleep.md)) and issue 633 ([5ga](../flow/5ga-residual-noorder-tie.md), `dfi_noorder_lock`); this entry adds only the recording `fz551_perish_outrage`, which guards them.

Issue 549 (a failing Skill Swap against Illusion) has the same cause as issue 620 and is fixed by #624 ([5dx](5dx-skill-swap-fails-on-every.md)); all 15 cases of 549 pass with that change.

- **Evidence.** Seven recordings, whole battles with the seeds and choices of the campaign and traces from the pinned Showdown b2cb775: `tests/reference/specs/fz545_dragon_tail_guard_dog.json`, `fz546_balloon_weak_armor`, `fz547_ice_spinner_weak_armor`, `fz547_ice_spinner_substitute`, `fz548_iron_ball_corviknight`, `fz550_curse_follow_me`, `fz551_perish_outrage`. Campaign cases with the fixes (before the restructure merges): 545 16 of 16 (two already passed on main), 546 16 of 17 (fz_340_27 ends in an explicit E_UNSUPPORTED at a later step), 547 15 of 15, 548 16 of 16, 550 11 of 11, 551 4 of 4 (the other seven write no case). Every other reference battle is unchanged; the pool set grows by these seven.
- **Mutants** (on the head after the merge of main abc626f3, `duoforge_diff_runner` over all 1090 pool records): each of (a) to (f) reverted alone is killed by its own recording and by no other battle. Main's issue 633 clause reverted (`dfi_alive` for `dfi_residual_holder_stands` in `dfi_noorder_lock`) is killed by `fz551_perish_outrage` and `noorder_lock_pending_faint`.
- **Open.** Issue 552 (the Illusion end) is not part of this entry.
