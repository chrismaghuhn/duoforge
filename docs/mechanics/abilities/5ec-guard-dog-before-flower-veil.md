<a id="5ec"></a>

# 5ec. Guard Dog before Flower Veil

- Area: abilities
- Step: -
- Tests: duoforge.abilities.guard_dog_flower_veil, duoforge.reference.conformance_pool_data

5ec. **Guard Dog before Flower Veil** (Content lane, Opus builder, branch `chris/fix-640-guard-dog`, issue 640, the Guard Dog part; no new public value, draw site or residual kind). Pin: `data/abilities.ts:1727-1744` (`guarddog`, `onTryBoostPriority: 2`), `:1419-1437` (`flowerveil.onAllyTryBoost`, default priority 0), `sim/battle.ts:2034` (`runEvent('TryBoost')`, its handlers by priority, the higher first); the Champions mod overrides neither.
   - **The pin.** Guard Dog's TryBoost handler always runs before Flower Veil's, whatever the Speeds. When Intimidate meets a Grass holder of Guard Dog next to a Flower Veil holder, Guard Dog deletes `boost.atk` and raises the holder's Attack by 1 (the nested boost: `-ability|holder|Guard Dog|boost`, then `-boost|holder|atk|1`). Flower Veil then finds no drop left, so no `-block` shows. Intimidate drops only Attack, so Flower Veil has nothing else to delete.
   - **The engine before.** `dfi_boost` (`src/combat/turn.c`) ran Flower Veil's handler first. It printed `-block|holder|ability: Flower Veil`, and then Guard Dog boosted anyway. That was wrong every time, not a Speed race.
   - **The engine now.** Guard Dog's branch comes first among the TryBoost handlers of `dfi_boost`, and it marks the Attack drop as deleted (`veil[ATK]`). Flower Veil's loop skips every drop that is already deleted and counts only its own deletions for the line and for `flower_veiled` (which the A2a refusals of Illuminate and White Smoke read). Nothing else moved: the Speed-race double lines of Clear Body, Keen Eye, Hyper Cutter, Big Pecks and Mirror Armor, and the Intimidate guards Inner Focus, Scrappy and Oblivious, stay as they were (the rest of issue 640).
   - **Reach.** Only Mabosstiff (Dark) has Guard Dog in the pool, so no forme is a Grass holder. Skill Swap (step G70) makes one. The marked Grass formes that learn Skill Swap in the Champions learnsets are Trevenant, the four Gourgeist and Meowscarada. Forest's Curse is not marked.
- **Evidence.** Two reference battles against the pin (pool; recorded with `ps_trace.js`, `--check` matches), one for each Speed relation, so a Speed-sorted order cannot pass both:
   - `guard_dog_flower_veil_skill_swap` (seed ending `640e`): Meowscarada (M, Speed 159, faster than Florges at 95) uses Skill Swap on the foe Mabosstiff next to its ally Florges (F, Flower Veil). Gyarados then replaces Mabosstiff, and its Intimidate gives Meowscarada `-ability Guard Dog boost`, `-boost atk 1` and no `-block`, while Florges takes `-unboost atk 1`. On main abc626f3, `diff_driver.py replay` makes it a DIVERGENCE at step 2 (event 2: the engine shows Flower Veil's ACTIVATE where the reference shows Guard Dog's ABILITY). With the fix it is a PASS.
   - `guard_dog_flower_veil_slow_holder` (seed ending `640f`): the same with the slower Trevenant (M, Relaxed, Speed 68, against Florges at 97; Trevenant moves last in turn 1). The pin's lines are the same: Guard Dog first, no `-block`.
   - `duoforge.reference.conformance_pool_data` replays both. Their pins were captured for the new battles only. The pool bound in `tests/reference/pins/reg-mc.json` is the measured file count after merging main 69b04cba (1093 plus these two: 1095).
   - `duoforge.abilities.guard_dog_flower_veil` (white-box, both POOL kinds) runs step 2 of each battle on the reference tape in three variants and checks the recorded Speed relation and positions:
     - As recorded: Guard Dog's line and +1, no `-block`.
     - With the holder's own ability (Overgrow, Natural Cure), so Flower Veil alone: the `-block`, no change.
     - With Florges's Symbiosis, so Guard Dog alone: Guard Dog's line and +1.
     - Florges loses 1 Attack in every variant.
   - Mutants, in one lock job after a green baseline and then a clean rebuild:
     - M1, main's order (Flower Veil's handler before Guard Dog's): killed by `conformance_pool_data` (both battles, step 2, event 2) and by the white-box test (a `-block` in the variants with Guard Dog).
     - M2 keeps the order, but Flower Veil reads again the drop that Guard Dog deleted: killed the same way (event 4).
     - M3 orders the two handlers by Speed (the faster holder's first): the faster-holder battle still passes, and `guard_dog_flower_veil_slow_holder` fails at step 2 (event 2, and the stages). The white-box test fails in the slow-holder variants.
     - No other battle fails under any mutant.
- **Open.** The rest of issue 640: the Speed race between Flower Veil and the holder's own TryBoost handlers (Clear Body, Keen Eye, Hyper Cutter, Big Pecks, Mirror Armor, Inner Focus, Scrappy, Oblivious) on a Grass holder made by Skill Swap.
