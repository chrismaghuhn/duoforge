<a id="5ee"></a>

# 5ee. Life Dew misses a semi-invulnerable ally

- Area: moves
- Step: -
- Tests: duoforge.abilities.life_dew_try_hit, duoforge.reference.conformance_pool_data

5ee. **Life Dew misses a semi-invulnerable ally** (Content lane, builder f672, branch `chris/fix-672-life-dew-invulnerable` on main 69b04cba, merged with main f9a026c3, issue 672; found by the builder of issue 641, decision 0015 entry 5ed; no new public value, draw site or residual kind). Pin (b2cb775): Life Dew (`data/moves.ts:10286-10298`, `target: "allies"`) goes through `trySpreadMoveHit` (`sim/battle-actions.ts:518`, `:550-620`), whose first step is `hitStepInvulnerabilityEvent` (`:556`, `:621-642`), before `hitStepTryHitEvent`. A target in the charge of Phantom Force (the volatile `phantomforce`, `onInvulnerability: false`, `data/moves.ts:13327-13330`) gets the hit result false, unless No Guard is on the user or on that target (`data/abilities.ts:2970-2974`, which returns 0):
   - **The line** is `-miss|user|ally`. A move with two targets is a spread hit (`:551`), so the move line gets no `[miss]` (`:636`).
   - **The ally leaves the targets** (`:605`) before its TryHit and before the hit loop, so it is not healed and shows no `-fail` at full HP. `atLeastOneFailure` becomes true (`:606`).
   - **The user's heal** is unchanged: `-heal`, or `-fail|user|heal` with `[still]` at full HP. The `[spread]` list is the targets left after the hit loop (`:614-618`): the user's slot when it healed, no slot when it failed.
   - Phantom Force is the only semi-invulnerable source the pool marks (`dfi_semi_invulnerable`, `src/combat/flow/queue.h`). Fly, Bounce, Dive, Dig, Shadow Force and Sky Drop are unmarked; Commander (`target.volatiles['commanding']`) is unmarked too.

**The engine.** `dfi_run_heal_move` (`src/combat/turn.c`) runs the ally's TryHit abilities since 5ed but not the Invulnerability step, so a charging ally was healed by the move, or got `-fail` at full HP: a silent divergence on main.
   - **The fix is one clause at that site,** before the TryHit clause. For every heal target, `dfi_invulnerable_to` (the predicate of the hit steps' Invulnerability step, step G58, with No Guard and the Toxic exception) marks the target as stopped and emits `-miss|user|target`. As in the hit steps, `[miss]` is set on the move line only when it has no `[spread]`. The stopped target then skips `dfi_try_hit_abilities` (which skips a target already stopped), leaves the heal list and adds `DFI_MRES_FALSE` through the existing loop.
   - **Other heal moves are unchanged.** Recover and Roost target the user, which is never semi-invulnerable during its own move. Heal Pulse runs the hit steps before its heal and does not reach `dfi_run_heal_move`.

- **Evidence.**
  - **One recorded pool battle,** `life_dew_phantom_force` (`ps_trace.js` against the pin, `--check` matches). It is the probe of issue 672 with two more turns: g32_life_dew's foes, Milotic's Life Dew each turn, Gengar (Cursed Body, Life Orb) with Phantom Force as its ally, six members per team.
    - Step 1: Gengar charges, Milotic at full HP: `-miss|p1a: Milotic|p1b: Gengar`, then `-fail|p1a: Milotic|heal`, and `[spread]` with no slot.
    - Step 2: Gengar's locked Phantom Force runs first and ends the volatile, so Life Dew heals both (`[spread] p1a,p1b`). This is the control.
    - Step 3: Gengar charges again at 41/137: `-miss`, Gengar is not healed, Milotic heals 182 -> 202, and `[spread] p1a`.
  - **Main and the branch on this battle.** `diff_driver.py replay --only '*life_dew*'`: with main's runner (69b04cba) `life_dew_phantom_force` is a DIVERGENCE at step 1 (event 7 of both players: the engine's `-fail` at Gengar where the reference has `-miss|p1a|p1b`); with the branch's runner all four Life Dew battles PASS (`g32_life_dew`, `life_dew_good_as_gold`, `life_dew_water_absorb` too).
  - **Pins.** Pins were captured by `capture_battle_pins.py` for the new battle only. The pool bound in `tests/reference/pins/reg-mc.json` goes from 1096 (main f9a026c3, after merging it) to 1097, the measured file count.
  - **`duoforge.abilities.life_dew_try_hit`** (white-box, tier quick) now also runs the steps of `life_dew_phantom_force` with the reference's tape. It checks:
    - steps 1 and 3: the ally's `-miss` before the user's line, no `[miss]` on the move line, no heal or `-fail` at the ally, and the `[spread]` slots;
    - step 2, the control: both healed;
    - the neighbours: No Guard on the charging ally (step 3) lets the move heal it; No Guard on the user (step 1) lets the move reach the ally at full HP, which fails as the user does.
  - **Mutants.** One lock job on a copy of head 6054974b, with a green baseline of `conformance_pool_data`, `conformance_pool`, `life_dew_try_hit` and `life_dew_water_absorb` before and after:
    - **M1**, the clause removed (main's behaviour), is killed by `conformance_pool_data` (`life_dew_phantom_force` step 1, event 7) and `life_dew_try_hit`.
    - **M2**, `[miss]` on the move line whatever its `[spread]`, is killed by `conformance_pool_data` (step 1, event 6, the move line) and `life_dew_try_hit`.
    - **M3**, the `-miss` shown but the ally left in the targets, is killed by `conformance_pool_data` (step 1, event 9) and `life_dew_try_hit`.
    - `conformance_pool` stays green under all three; the kill is `conformance_pool_data`, which runs the pool battles.
- **Open.** None known for Life Dew. Other semi-invulnerable sources need `dfi_semi_invulnerable` extended when their rows are marked (see there).
