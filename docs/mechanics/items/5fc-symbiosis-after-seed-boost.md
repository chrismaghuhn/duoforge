<a id="5fc"></a>

# 5fc. -, Symbiosis passes its item after a terrain seed's boost

- Area: items
- Step: -
- Tests: duoforge.reference.conformance_pool, duoforge.reference.battle_pins, duoforge.reference.conformance_tables

5fc. **-, Symbiosis passes its item after a terrain seed's boost** (Fuzz lane, branch `fuzz/553-symbiosis-seed`; found by the differential fuzzing of issue 396, issue 553; no new public value). Pin: useItem (`sim/pokemon.ts:1825-1845`) shows the `-enditem`, applies the item's `boosts`, then runs AfterUseItem, where an ally's Symbiosis passes its item (`data/abilities.ts:4837-4851`). The engine's terrain seed (`dfi_terrain_seed`, `src/combat/field/terrain_seeds.h`) called `dfi_use_item`, Symbiosis included, before the boost, so `-activate|...|ability: Symbiosis` came before `-boost` (fz_272_7). It now calls `dfi_use_item_core`, the boost, then `dfi_symbiosis`. The other pool items with `boosts` are the seeds only; White Herb's restore (its `onUse`) also precedes AfterUseItem in the pin, but it is silent and a passed item that would start at once is refused, so its order shows nothing.

- **Evidence.** The recording `fz553_symbiosis_seed` (synthetic teams, trace from the pinned Showdown b2cb775). Every other reference battle is unchanged; the pool set grows by one.
- **Mutant.** The fix reverted alone: killed by `fz553_symbiosis_seed` and by no other battle (`duoforge_diff_runner` over every pool record).
