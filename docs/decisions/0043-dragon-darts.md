# 0043 - Dragon Darts (G78): the split of a two-target hit

Status: **accepted** (H16, lane A batch 5, step 5ch). The lead approved the model on 2026-10-10 (the answers of the coordinator: model and draw order approved as written; R1, R2, R4 and R5 approved as refusals; Emergency Exit modelled with the two battles; the special id at the next free value; the Dragapult learner value stays). The implementation is in `src/combat/turn.c` (`dfi_smart_targets`, the `smart` flag of `dfi_run`, the split in the hit loop, the silent steps); the pool row is `DFI_SPECIAL_DRAGON_DARTS` (97, UNMODELED 98). Results and open points are in the section "Phase 2 results" below.

## Problem

Dragon Darts (`data/moves.ts:4118-4132`: Dragon, Physical, base power 50, accuracy 100, pp 10, `multihit: 2`, `smartTarget: true`, target `normal`, flags protect, mirror, metronome, noparentalbond; no contact flag) does not hit the same Pokemon twice. Its first hit goes to the chosen foe, its second hit goes to that foe's partner, when the partner can be hit. The engine has no two-target single-move path: `dfi_move_targets` (`src/combat/turn.c:1311`) returns one target for the NORMAL class, and the hit loop (`turn.c:6980-7060`) hits every target of a move on every hit. The multi-hit refusal `hits_total != 1 && (count != 1 || spread)` (`turn.c:6952`) is the only place where a multi-hit spread move is turned away today. The 5ca entry dropped the row for this reason.

## The pin (Showdown b2cb775; the Champions mod changes only the hit loop)

- **Move row:** `data/moves.ts:4118-4132`. No Champions override in `data/mods/champions/moves.ts` (none exists for dragondarts; the mod's own `scripts.ts` only changes the loop below). Champions learnsets: only `dragapult` (`data/mods/champions/learnsets.ts:14883`, `9M`), and `learned_by_count` 1 in `docs/research/expansion/data/legal_pool.json`.
- **Targets, `getMoveTargets` default branch** (`sim/pokemon.ts:822-855`): a fainted chosen target is retargeted with `getRandomTarget`; RedirectTarget runs first (`:829-831`, the Follow Me hook); then for `smartTarget` `targets = this.getSmartTargets(target, move)` (`:832-834`); the move's `pressureTargets` is `targets` (`:847`, Pressure counts both).
- **`getSmartTargets`** (`sim/pokemon.ts:757-767`): the partner is `target.adjacentAllies()[0]`. The partner is `[target]` with `move.smartTarget = false` when there is no partner, when the partner is the user, or when the partner has no hp. If the target has no hp, the result is `[partner]` with smartTarget false. Otherwise `[target, partner]`. `adjacentAllies` (`:724-726`) is the side's standing allies, and `isAdjacent` in doubles is `this !== pokemon2` (`:741-746`), so in doubles the partner is the other live slot of the target's side. No draw.
- **`getTarget`** (`sim/battle.ts:2451-2454`): a smart move takes the chosen slot unless it is fainted, then `getRandomTarget` (one draw, the existing `DFI_SITE_RANDOM_TARGET`).
- **Move line:** `addMove('move', ..., target)` (`sim/battle-actions.ts:457`) is printed before `getMoveTargets`, with the chosen target. `retargetLastMove` (`sim/battle.ts:3141-3146`) rewrites that line's target field.
- **`useMoveInner`** (`sim/battle-actions.ts:467-470`) keeps `targets` (both) and sets `target = targets[last]` for the local only; `runMove`'s AfterMove (`:311-312`) takes getTarget's result (the chosen target), so the engine's `r->move_target = targets[0]` stays right.
- **`trySpreadMoveHit`** (`:551`): `spreadHit` is never set for a smart move, so no 0.75 (the damage's `spread` flag stays false; `turn.c:1873` is the only use of 0.75). `:607`: `if (move.smartTarget && atLeastOneFailure) move.smartTarget = false;` after any step whose results contain a `false`. The steps (gen 9): invulnerability `:633-637`, TryHit (Protect), type immunity `:661`, accuracy `:739-748`, break protect, steal boosts, then the hit loop.
- **Invulnerability** (`:633-640`): a dropped target sets smartTarget false silently; otherwise `[miss]` on the move line (`:636`) and `-miss`.
- **Protect** (`data/moves.ts:1008-1014`, and the same text at `:2043-2049`): with smartTarget set, it sets `move.smartTarget = false` and prints nothing; otherwise `-activate|X|move: Protect`. It returns `NOT_FAIL` (`data/moves.ts:1025`, the empty string), so `hitStepTryHitEvent` (`sim/battle-actions.ts:643-655`) does not count it as a failure.
- **Type immunity** (`:661`): `runImmunity(move, !move.smartTarget)`. `runImmunity` with message false returns false silently (`sim/pokemon.ts:2255`). So a Fairy target (immune to Dragon) prints nothing while smartTarget is set, and prints `-immune|X` once it is cleared.
- **Accuracy** (`:739-748`): `randomChance(accuracy, 100)` for each target still in play, in target order (`sim/battle.ts:350-353`; `sim/prng.ts:115-117`: `random(100) < 100`, so the draw happens at accuracy 100). A miss sets smartTarget false silently when it is set; otherwise `[miss]` on the move line and `-miss|user|X`.
- **Hit count:** `targetHits = move.multihit || 1` (`scripts.ts:434`) is the number 2, so there is no `sample` and no draw. The Champions loop (`data/mods/champions/scripts.ts:427-593`, `hitStepMoveHitLoop`):
  - `:463`: stop when every target is down. A fainted first target does not stop the second hit.
  - `:466-470`: while smartTarget is set and two targets remain, hit `h` goes to `targets[h-1]`; otherwise both hits go to `targets.slice(0)`, the single survivor.
  - `:474-478`: from hit 2 on, `addMove('-anim', user, move, target)` (the ANIMATION event); on hit 1, `retargetLastMove(target)`.
  - `:521-523`: smartTarget pushes each hit's damage array; otherwise the array is replaced by the last hit's.
  - `:526`: a hit whose damage array has no non-false entry ends the loop.
  - `:538`: the user's faint ends the loop only when a single target is in play.
  - `:547-549`: `-hitcount` only when smartTarget is not a boolean, so a Dragon Darts line never has `-hitcount`.
  - `:557-565`: `gotAttacked(move, moveDamage[i])` for each target; `timesAttacked += smartTarget ? 1 : hit - 1`.
  - `:580-589`: EmergencyExit is checked with `curDamage = targets.length === 1 ? move.totalDamage : d` (see the Emergency Exit paragraph below).
- **Stomping Tantrum** (`data/moves.ts:18049-18068`): doubles its base power when `moveLastTurnResult === false`. The result is `moveThisTurnResult` (`sim/battle-actions.ts:616`: `null` when nothing was hit and no step failed; otherwise true when a target survived and false when a step failed and nothing survived).
- **Pressure** (`data/abilities.ts:3441-3444`, `onDeductPP` returns 1 for a foe): counted over `pressureTargets` (both targets of a split), before TryMove (`battle-actions.ts:467-484`).

## Engine today

- `dfi_move_targets` (`turn.c:1311-1426`): NORMAL returns one target, with the existing random retarget (`dfi_random_foe`) when the chosen foe is gone.
- The hit loop (`turn.c:6980-7060`): per hit, every target with `hit[i]`, the `spread` flag set when count > 1 (`:6700`, `:6883`, `:6937-6944`).
- The multi-hit draw `DFI_SITE_MULTIHIT_COUNT` (`turn.c:6944-6947`) is G54's only; Dragon Darts draws none.
- `dfi_pressure_extra` (`turn.c:5126-5146`) already counts the targets list and the holders.
- ANIMATION is already emitted (`turn.c:6342`, Weather skip), and the converter maps `-anim` to it (`tools/reference/trace_to_c.py:1661-1668`).
- Stomping Tantrum reads the mres classifier (`DFI_MRES_*`), which already gives TRUE for a surviving target, FALSE for a failed step, NULL for a Protect-only block.

## Proposed model

**State: none new.** The `smart` flag and the survivor list are locals of one move use (no heap, no tail byte, no view bit, no event kind, no cause id, no public value). The only table change is one internal pool special, `DFI_SPECIAL_DRAGON_DARTS` (see the questions).

**Targets.** `dfi_move_targets` (NORMAL class) gives the chosen target T as now, after the redirect and the random retarget. Then the partner P is the other slot of T's side if it stands. If P is absent, or T is the user's ally, the move has one target and smart is false. Otherwise `targets = [T, P]`, `count = 2`, `smart = true`. No draw.

**Pressure.** `dfi_pressure_extra(..., targets, count)` with the two targets, unchanged.

**Hit steps.** The existing steps keep their order (invulnerability, TryHit, type immunity, TryImmunity, accuracy). The flag `smart` is consumed as the pin consumes it:
- a drop in invulnerability: `smart = false`, no line;
- a Protect on a target: `smart = false`, no line when smart is set, `-activate|X|move: Protect` when it is not;
- a type immunity: no line when smart is set, `-immune|X` when it is not;
- an accuracy miss: `smart = false`, no line when smart is set, `[miss]` on the move line and `-miss|user|X` when it is not;
- after each step, if any result of that step is false, `smart = false`;
- the move line of hit 1 is retargeted to the first survivor (`retargetLastMove`), and this is the only change of the printed target.

**The loop.** With two survivors and smart set: hit 1 on T, then hit 2 on P, each hit with its own crit roll and damage roll, the `-anim` line before hit 2's damage. With one survivor S: hit 1 and hit 2 on S, the move line retargeted to S when S is not T, `-anim` before hit 2. The faint of T after hit 1 does not stop hit 2. The faints and the post-move steps (secondaries, AfterMove, Life Orb) come once after the loop, as the engine already does for multi-hit moves. No `-hitcount`. No `[spread]`. No 0.75.

**Post-loop bookkeeping, as the pin does it.**
- `timesAttacked`: +1 per target in a split (one hit each), and +2 for a survivor who took both hits (the pin's `hit - 1`), which is the engine's per-hit count already.
- `gotAttacked`: in a split each target gets its own hit's damage; with one survivor the pin calls it once with the last hit's damage (`:523`, `:557-562`). Counter and Mirror Coat read this record, so the engine must keep it.
- Emergency Exit: the pin's damage array is `[undefined, d2]` after a split (hit 1 writes index 0, hit 2 replaces the array with `[damage[1]]` at `:468`, then writes index 1). So after a split only the partner P is checked for Emergency Exit, with its second hit's damage; T is never checked. With one survivor the pin uses the total of both hits. **This is my trace of the pin, not yet confirmed by a battle.** The proposal is to model it exactly with the two battles of the evidence plan; if a battle disagrees, the holder is refused instead.

**Draw order (the complete list for a split).**
1. The random retarget, only when the chosen foe is fainted (existing).
2. Accuracy: one `random(100)` for T, then one for P, each only if that target is still in play (so a target that fails the TryHit or the immunity step draws nothing).
3. Hit 1: the crit roll and the damage roll of T (the existing single-target damage order).
4. Hit 2: the same for P.
5. Cursed Body's DamagingHit draw (existing), once per hit when the holder is hit.

No draw: the partner, the hit count (`multihit` is the number 2), the Pressure, the `-anim`, the retarget, the Protect and immunity lines.

**Result (Stomping Tantrum).** TRUE when one target survives the steps, FALSE when a step failed and nothing survived, NULL when nothing survived and no step failed (both Protect). This is the existing mres classifier unchanged.

**Refusals (E_UNSUPPORTED, named, never a guess):**
- **R1, Protect (or another TryHit stopper) on both targets.** The pin's second Protect prints `-activate` (the flag is already clear) and the order of two stoppers is decided by priority and speed (a tie draws). Not modelled.
- **R2, a Substitute on either target** (decision 0032). Its hit is answered as `true` by spreadMoveHit, and the loop's `targets[hit-1]` mapping and `targetsCopy` are changed by it (`scripts.ts:467`, `:557`). Not traced for a split. Refused for the whole move while a Substitute stands on a target.
- **R3, a user's faint inside the loop.** Dragon Darts has no contact, so no contact ability or Rocky Helmet fires, and the user cannot faint inside the loop. The engine refuses it if it happens (a guard, not a model).
- **R4, Dragon Darts used by a called move** (Sleep Talk, Metronome, Copycat, Mirror Move, Instruct, Dancer). The called move's targets come from the caller's path. Refused unless the caller's path already routes through `dfi_move_targets` (to be checked in phase 2).
- **R5, a holder of Red Card, Eject Button or Eject Pack among the targets** (AfterMoveSecondary with two targets). Refused until a battle shows the order.
- **Not refused (checked, not reachable):** Quick Guard and Wide Guard (priority 0 and an allAdjacentFoes-only rule), Psychic Terrain (positive priority only), Magic Bounce (no reflectable flag), Rocky Helmet, Rough Skin and the other contact effects (no contact), Sheer Force (no secondaries), Sturdy and Focus Sash (per target, per hit, the existing code), Lightning Rod and Storm Drain (Electric and Water only).

## Evidence plan (recorded POOL battles, genders stated, six members a side, Item Clause, marked moves only)

Each battle is recorded with `ps_trace.js` and converted with `trace_to_c.py`; each runs in the conformance and tiebreak replays.
1. `g78_split`: two foes stand, no failure. Expect T then P, `-anim` before P's damage, no `-hitcount`, no `[spread]`.
2. `g78_protect_t`: T uses Protect. Expect no Protect line for T's first failure (silent), P hit twice, the move line retargeted to P. This is the retarget evidence.
3. `g78_protect_p`: P uses Protect. Expect T hit twice, no line for P.
4. `g78_fairy_p` (P is Fairy): the immunity is silent; T hit twice.
5. `g78_protect_t_fairy_p` (T Protect, then P Fairy): the second failure prints `-immune|P`; the result is FALSE (a following Stomping Tantrum doubles).
6. `g78_ko_t_hit1` (T faints on hit 1): P still takes hit 2; the faint line comes after P's damage.
7. `g78_pressure2` (both foes with Pressure): the user loses 3 PP for one use.
8. `g78_partner_absent` (one foe on the field): two hits on the survivor, `-anim`, no partner.
9. `g78_ally_target` (Dragon Darts on the user's own ally): one target, two hits.
10. `g78_fainted_target` (the chosen foe is down before the move): the random draw, then the split.
11. `g78_ee_p` and `g78_ee_t` (Golisopod, Emergency Exit, as P and as T): the check of P only, as traced above.
12. `g78_refuse_sub` (a Substitute on T): E_UNSUPPORTED (R2).

Mutants (one edit each in `turn.c`, each killed by a battle above): partner from the user's side; hit 2 on T; smart not cleared at Protect (a printed line where the pin is silent); no `-anim`; 0.75 applied to the split; no retarget; Pressure counted on T only; Stomping mres TRUE after a failed step; a faint of T ending the loop; Emergency Exit checked on T; accuracy draw for P skipped.

Campaign: `diff_driver.py random`, 300 battles, the teams of `g78_split` and `g78_protect_t_fairy_p` (two Dragapult with Dragon Darts, Fairy and Protect users), POOL, pin b2cb775. Run directly (the driver takes the lock per chunk).

## Public values, tables and pins

- **No public value** (no header constant, event kind, cause id, view bit, tail byte, flags bit or volatile). The ANIMATION, MOVE and DAMAGE events are the existing ones.
- **Pool special:** `DFI_SPECIAL_DRAGON_DARTS` (the next free id, 97 at `main`, `UNMODELED` becomes 98). The row is marked in `src/data/support_manifest.c`. Batch 5's other builders take ids in parallel, so the lead orders them at merge.
- Regeneration: `gen_closure.py --pool`; the new POOL table hash goes into `tools/state_model/state_v3_model.py` and `tests/test_pool_tables.c`; FP_KP and KPD into `tests/test_pool_setup.c`.

## Questions for the lead

1. Approve the model above, in particular the `smart` flag as the pin consumes it, the survivor rule, and the draw order.
2. Approve R1, R2, R4 and R5 as refusals in this batch, or name the ones you want modelled now.
3. Emergency Exit: model the traced arithmetic with the two battles (my recommendation), or refuse any Emergency Exit or Wimp Out holder among the targets.
4. The pool special id (97, or the lead's number), given that batch 5 builds in parallel.
5. Value check: only one Champions learner (Dragapult, `learned_by_count` 1). Is +82 still the right value for this row?

## Phase 2 results (H16)

**Engine and tables.** `src/combat/turn.c`: `dfi_smart_targets` (the partner after the redirections, the refusals R2 and R5),
the `smart` flag (silent while set, cleared by a drop, as in the pin), the split in the hit loop (hit k on the k-th target, the
`-anim` before hit 2, the move line retargeted on the first hit), `dfi_move_hits` (two hits, a number: no draw), the whitelist of
handled specials, Emergency Exit skipped for the first target of a split (the pin's damage array). Pool row: `DFI_SPECIAL_DRAGON_DARTS`
= 97, UNMODELED = 98, marked moves 198 (was 197), UNMODELED moves 180 (was 181); pool hash `34f64221af56...bd14da0`.

**Setup finding.** Sneasler's set in the first draft had Sucker Punch, which is not in DuoForge's learnset for that forme (Showdown
does not validate learnsets at battle creation; DuoForge does). The G78 set uses Protect and Poison Jab (both learnable and marked).

**Recorded battles (12, `"data": "pool"`, `tests/reference/specs/g78_*.json`).** split, protect_t, protect_p, fairy_p,
protect_t_fairy_p, pressure2, ally_target, ko_t_hit1 (six turns, the first target falls on hit 1 and the partner takes hit 2),
partner_absent (seed 1 with the no-protect variant: the first target falls in the same turn and the partner slot is empty, so
the move is retargeted at random to the foe that stands), fainted_target (seed 26 of the same variant), ee_p (Emergency Exit on the
partner, check on the second hit), ee_t (Golisopod crosses half on hit 1 of a split: no Emergency Exit, as the pin reads).
The long battles of the no-protect variant were chosen because the first draft produced approved refusal R1 in the recording
(two foes protecting on one turn with Dragon Darts): the reference allows that step, so such a step cannot be a conformance battle.

**Tests.** `duoforge.reference.conformance_pool_data`: 713 battles pass. `duoforge.reference.tiebreak_pool_data`: 713 battles,
3875 stops. `duoforge.state.pool_g78`: 63 checks, 0 failures (the row, the branch states, PP 7 after Pressure of two foes, the
move result after a blocked split, R1, R2 and R5 refused with E_UNSUPPORTED).

**Mutants (11 of 11 caught).** Each mutant is one edit of `turn.c`; baseline (unmutated head) 2 of 2 green.
1 partner from the user's side: `pool_g78` (test_split, test_protect_t, the move result, PP, R1, R5) and conformance;
2 second hit on the first target: `pool_g78` (test_split) and conformance (7 failures);
3 Protect line printed while smartTarget is set: conformance (6 failures);
4 no `-anim`: conformance (11 failures);
5 split as a spread (0.75): conformance (E_INVARIANT battles and the damage lines);
6 no retarget of the move line: conformance (5 failures);
7 Pressure counts the first target only: `pool_g78` (test_pressure2) and conformance;
8 no FALSE for the immunity drop: `pool_g78` (test_protect_t_fairy_p, move result) only;
9 a fall of the first target ends the loop: conformance (ee_t, fainted_target, ko_t_hit1, partner_absent, protect_t);
10 Emergency Exit checked on the first target: conformance (ee_t, fainted_target, ko_t_hit1, partner_absent);
11 accuracy draw of the second target skipped: conformance (six battles, E_INVARIANT at step 1).
Every mutant result is a red run with the mutation and a green baseline for the same two tests.

**Campaign** (`diff_driver.py random`, seed 78, 300 battles, pairings GG, HH, GH, HG, the two G78 teams; the mirror pairings put a
Sitrus holder on each side at equal speed, which exercises the SPEED_TIE Update draws): PASS 284, DIVERGENCE 1, ORACLE_GAP 0,
UNSUPPORTED 15. The 15 refusals are all R1 (both targets of a split use Protect in that turn; 15 of 300 battles, 5%). R2 (Substitute)
fired 0 times and R5 (Red Card or Eject Button) 0 times in these battles. The DIVERGENCE is `fz_78_146` (pairing GH, index 146), step 19:
`DUOFORGE_E_INVARIANT` with no draw consumed. The reference step: Kingambit (partner) protects, Dragapult's Dragon Darts, whose ally
target is empty, is retargeted at random to Milotic, which faints on hit 1. **Open:** the cause is not identified. It is not an
R1 case, and the step is inside the new code path (random retarget of a smart move whose partner protects). Reproduction:
`diff_driver.py random ... --start 146 --battles 147`. It is reported, not fixed.

**Local checks run.** Targeted ctest (regex `pool_tables|conformance_pool|tiebreak_pool|converter_api|gen_closure|state_model|python.replay_unit|python.live|pool_g78|pool_setup|pool_g16|pool_g29|pool_g34|pool_g39|pool_g44|pool_g54|pool_g58|pool_g62|pool_g64|pool_g68|pool_g70`): 26 tests, 22 passed, 0 failed, 4 skipped (`duoforge.python.live`, `live_unit`, `live_client`, `replay_unit`: the project venv is absent on this machine). Python unit tests run separately: `tools/datagen/test_gen_closure.py` 132 of 132, `tools/reference/test_trace_to_c.py` 97 of 97. Source lint `cmake -DROOT=... -P cmake/checks/lint_sources.cmake`: OK (78 files). MinGW `-Wall -Wextra -Werror -Wmissing-field-initializers` on `turn.c` and `test_pool_g78.c`: clean.

**Full suite.** On GitHub (`gh workflow run ci.yml`), see the report.

**Open points.** (1) The `fz_78_146` divergence above. (2) R1 is the common refusal (5% of random battles); R2 and R5 were not sampled, so their rates are unknown. (3) The four python live tests were skipped locally.
