<a id="5ed"></a>

# 5ed. Life Dew runs the TryHit abilities of its ally

- Area: abilities
- Step: -
- Tests: duoforge.abilities.life_dew_try_hit, duoforge.abilities.life_dew_water_absorb, duoforge.reference.conformance_pool_data

5ed. **Life Dew runs the TryHit abilities of its ally** (Content lane, builder fix641, branch `chris/fix-641-life-dew-tryhit` on main abc626f3, issue 641; found in the A2a review, decision 0015 entry 5dy; no new public value, draw site or residual kind). Pin (b2cb775): Life Dew (`data/moves.ts:10286-10298`: Water, Status, `target: "allies"`, `heal: [1, 4]`, accuracy true, no protect flag) goes through `trySpreadMoveHit` (`sim/battle-actions.ts:550-620`). Its step `hitStepTryHitEvent` (`:643-652`) runs the TryHit handlers of every target; the user's own handlers do not stop it, because the ability handlers check `target !== source`. A handler that returns null makes that target's hit result false, and the target leaves the list before the hit loop. The `[spread]` attribute lists the targets left after all steps (`:614-618`). The relevant handlers:
   - **Good as Gold** (`data/abilities.ts:1630-1636`) stops a Status move with `-immune|ally|[from] ability: Good as Gold`.
   - **Water Absorb** (`:5363-5376`) heals the holder by a quarter of its maximum HP through `this.heal`, so the line is `-heal|ally|...|[from] ability: Water Absorb|[of] user`. When that heal does nothing (full HP, Heal Block) the line is `-immune|ally|[from] ability: Water Absorb`.
   - **The hit loop** then heals only the user. At full HP the user gets `-fail|user|heal`, the move line gets `[still]`, and the `[spread]` list is empty.

**The engine.** Heal status moves left the move body early: in `src/combat/turn.c`, the phase-4 branch `dfi_run_heal_move` comes before the hit steps, into `dfi_run_heal_fraction`. So the ally's TryHit abilities never ran.
   - **Before this fix,** Good as Gold was a silent divergence on main: the ally was healed by the move. The Water Absorb case was refused (`E_UNSUPPORTED`) since A2a.
   - **The fix is one clause at that site.** `dfi_run_heal_move` now runs `dfi_try_hit_abilities`, the same function the hit steps call, over the heal targets. It passes the move's current type (`dfi_move_type_now`) and an accuracy that nothing reads. A target that the function stops leaves the list and adds `DFI_MRES_FALSE`, as the hit steps do for a TryHit stop (`atLeastOneFailure`). The heal then runs over the targets that are left.
   - **The added `DFI_MRES_FALSE` never decides the result.** It is correct, but the user is always a target of an allies move and never stopped by its own TryHit, so a TryHit stop alone never empties the list. When the user heals, `DFI_MRES_TRUE` wins; when it fails at full HP, the heal path sets `DFI_MRES_FALSE` itself, as the pin's hit loop makes `atLeastOneFailure` true (`sim/battle-actions.ts:614-616`). No mutant can kill it.
   - **The `[spread]` list** in `dfi_run_heal_fraction` is now keyed on the move line's `DUOFORGE_EVENT_FLAG_SPREAD`, not on the count of the (filtered) targets. This is the same condition on every path: the flag is set when the line has more than one target. A Life Dew whose ally was stopped therefore keeps `[spread]` with the user alone, or with no slot when the user fails.
   - **The A2a refusal is gone.** It was the Water Absorb case in `dfi_run_heal_fraction`. Heal Pulse runs the hit steps before its heal and does not call `dfi_run_heal_move`, so it is unchanged. Recover and Roost target only the user, whose TryHit is not asked.
   - **No other marked TryHit ability reacts to Life Dew:** it is not sound, powder, bullet or OHKO, not Fire or Electric, and it is a Status move, so Telepathy does not apply. Dry Skin and Storm Drain are unmarked.

- **Evidence.**
  - **Two recorded pool battles** (`ps_trace.js` against the pin, `--check` matches). Both use Milotic's Life Dew; the foes are g32_life_dew's Salamence and Garchomp, and both teams have six members.
    - `life_dew_good_as_gold` (Gholdengo as the ally). Step 1: Milotic at full HP, Gholdengo hurt by Dragon Claw, giving `-immune ... Good as Gold`, `-fail|Milotic|heal` and `[spread]` with no slot. Step 2: both hurt, giving `-immune` and Milotic's heal with `[spread] p1a`. Step 3: the full-HP case again.
    - `life_dew_water_absorb` (Vaporeon as the ally). Step 1: both hurt by Hyper Voice; Vaporeon heals 207 -> 237 through Water Absorb `[of] p1a: Milotic`, before Milotic's own heal. Steps 2 and 3: Vaporeon at full HP is `-immune ... Water Absorb`.
  - **Main and the branch on these battles.** `diff_driver.py replay` with main's runner (abc626f3): `life_dew_good_as_gold` DIVERGENCE at step 1 (Gholdengo 179 instead of 140, and the `[spread]` amount); `life_dew_water_absorb` UNSUPPORTED at step 1 (the A2a refusal). With the branch's runner all three Life Dew battles PASS (g32_life_dew too).
  - **Pins.** Pins were captured by `capture_battle_pins.py` for the two new battles only. The pool bound in `tests/reference/pins/reg-mc.json` goes from 1083 to 1085, the measured file count.
  - **`duoforge.abilities.life_dew_try_hit`** (white-box, tier quick) runs the decisive steps of both battles with the reference's tape. It checks:
    - the ally's line, its cause and `[of]`, and that it comes before the user's line;
    - the `[spread]` slots;
    - the neighbours: the ally given Defiant (no TryHit) or Volt Absorb (the same TryHit branch, another type) is healed by the move, with both slots in `[spread]`;
    - that the user's own Good as Gold or Water Absorb is not asked;
    - a hurt Water Absorb ally under Heal Block (Psychic Noise is marked): Heal Block's onTryHeal refuses the ability's heal (`data/moves.ts:8324-8332`), so the line is `-immune|ally|[from] ability: Water Absorb` (`data/abilities.ts:5364-5370`) and the user heals; A2a refused this step.
  - **`duoforge.abilities.life_dew_water_absorb`** is A2a's refusal case (g32_life_dew step 3 with Kingambit given Water Absorb). It now plays the tape with Water Absorb's line at the ally; the user's own Water Absorb and the control show none.
  - **Mutants.** One lock job on copies of head 3f6cf8b7, with a green baseline of the three tests:
    - **M1**, the TryHit clause removed, is killed by `conformance_pool_data` (both battles), `life_dew_try_hit` and `life_dew_water_absorb`.
    - **M2**, the `[spread]` condition back to the target count, is killed by `conformance_pool_data` (both battles) and `life_dew_try_hit`.
- **Open.** Issue 672: Life Dew at an ally in a semi-invulnerable turn (Phantom Force is marked) is a silent divergence on main and on this branch, outside issue 641. The pin's step `hitStepInvulnerabilityEvent` (`sim/battle-actions.ts:621-641`) shows `-miss|user|ally`; the early heal path heals the ally, or shows `-fail` at full HP. A recorded probe (not committed; kept for the fix of issue 672) diverges at step 1 with both runners. Not changed here. Fixed by decision 0015 entry 5ee (`docs/mechanics/moves/5ee-life-dew-misses-a-semi-invulnerable-ally.md`).
