# 0020 - Static dex features: a read API for formes, moves, items and abilities

Status: **accepted** (owner, 2026-10-03: the four static functions, `duoforge_data_type_effect`, the generated static-flags column, static target-class values 10-15, one minor bump). Drafted by the expansion lead; requested by Learner v2 through HauptSession. Builds on 0015 (the POOL tables and the data query API, section 4.1) and 0018 (the view extension).

## Problem

Learner v2's model v2.1 wants static features per forme and per move next to its learned id embeddings, so that one network generalises over hundreds of teams instead of memorising ids. The features must come from the same generated tables the engine plays from. Python must not re-derive them from Showdown, and must not hold rule logic (AGENTS.md).

Today the public data API (`duoforge_data_count`, `_name`, `_find`, `_supported`, `_forme_info`, `_forme_moves`) gives names, legality and Mega links, but no types, stats or move numbers.

## Decisions

1. **Four read functions, one per table:**
   - `duoforge_data_forme_static`
   - `duoforge_data_move_static`
   - `duoforge_data_item_static`
   - `duoforge_data_ability_static`

   Each has the shape of `duoforge_data_forme_info`:
   ```c
   duoforge_status duoforge_data_forme_static(const duoforge_context *ctx, uint32_t species_id, duoforge_forme_static *out);
   ```
   The contract:
   - **Fixed structs:** `uint32_t` fields, unused entries zero, no allocation, no pointer into the tables.
   - **Explicit errors:** NULL gives `E_NULL_ARGUMENT`. An id at or beyond `duoforge_data_count` of the context's kind gives `E_INVALID_ARGUMENT`. A kind without combat tables (SYNTHETIC) gives `E_UNSUPPORTED`.
   - **Determinism:** the values are pure functions of (kind, id). They are read from the generated tables under the context's kind, exactly as setup and the turn code read them.
   - **One read per row:** a learner calls each function once per id at start-up and builds its own arrays. There is no batch call, because the tables have at most 511 rows.

2. **Every row answers, modelled or not.** The core numbers are filled from the pin for every row, including UNMODELED ones (0015 section 4.2 lenient rows). Support stays a separate question for `duoforge_data_supported`, so a learner can embed a move the engine cannot play yet. These core numbers are type, category, base power, accuracy, PP, priority and target class.

3. **`duoforge_forme_static`:**
   - `types[2]`: DUOFORGE_TYPE_*; the second is `DUOFORGE_DATA_NONE` for a single type.
   - `base_stats[6]`: HP, Atk, Def, SpA, SpD, Spe.
   - `weight_hg`.
   - `default_ability`: the forme's own ability for a Mega forme, otherwise the first legal one; the full list stays in `forme_info`.
   - `is_mega`.

   That is 13 fields, 52 bytes. Megas are rows like any forme, so a learner gets the post-Mega types and stats directly.

4. **`duoforge_move_static`:**
   - `type`.
   - `category`: physical 0, special 1, status 2; new public constants `DUOFORGE_MOVE_CATEGORY_*`.
   - `base_power`: the pin's basePower. It is 0 for callback moves such as Low Kick and Last Respects, and the `power_rule` bit says so.
   - `accuracy`: 0 means never misses.
   - `pp`: Champions PP after the cap and calculatePP, the value a member starts with.
   - `priority`: signed and unbiased, as `int32_t`.
   - `target_class`: DUOFORGE_TARGET_CLASS_*. Pool rows can carry classes the engine does not resolve. Six new public values cover them: RANDOM_NORMAL 10, ALL_ADJACENT 11, SCRIPTED 12, ALLY_TEAM 13, ALLIES 14, FOE_SIDE 15. `DUOFORGE_TARGET_CLASS_COUNT` stays 9 for the request API, and a separate `DUOFORGE_TARGET_CLASS_STATIC_COUNT` is 15.
   - `flags`: a public bit set `DUOFORGE_MOVE_STATIC_FLAG_*`, see decision 5.
   - `crit_stage`.
   - `drain` and `recoil`: numerator and denominator, 0/0 for none.
   - `secondary_chance`: percent, 0 for none.

   The secondary effect's kind and parameter stay out of v1. Their table encoding is internal and still growing step by step, and exposing it would freeze it.

5. **Move flags need one new table column.** The tables store only the flags the engine reads: contact, protect, charge, defrost, self-switch, sound, heal, recharge and a few internal ones. A learner wants the rest as well: punch, bite, bullet, pulse, slicing, wind, dance, powder, sound and contact. The generator would add a column `dfi_pool_move_static_flags` (u32), generated from the pin's flags object for every row.
   - **No engine reader:** nothing in the engine reads it. It is data for the API only, and a test pins that.
   - **Fingerprints:** POOL fingerprints change once. The CLOSURE and TEAM_C prefix bytes are untouched, because the column sits outside the closure layout.
   - **Public bit order:** fixed in the header, one bit per Showdown flag name, additive only.
   - **Not support:** a flag being reported means nothing about support. Bulletproof and Mega Launcher stay unmarked until a step gives them an engine reader.

6. **Items and abilities: ids plus their family.** A meaningful static feature exists only where the tables already have one, the 0015 family columns:
   - items: type booster with its type, resist berry with its type;
   - abilities: -ate with its type, pinch with its type, weather setter with its weather, terrain setter with its terrain.

   `duoforge_item_static` holds `family` (`DUOFORGE_ITEM_FAMILY_*`, 0 = none), `family_type` and `is_mega_stone` (plus `mega_species` when it is one). `duoforge_ability_static` holds `family` (`DUOFORGE_ABILITY_FAMILY_*`) and `family_param`.

   Everything else about an item or ability is code, not data (Leftovers, Intimidate). It stays an id, and the learner's embedding learns it. New families become new public values, additively, when a step adds them to the generator.

7. **Layout pin and the Python binding:**
   - The four structs and every new constant go into `tools/layout/layout_dump.c` and `python/duoforge/_layout.py` in one commit, as with every public struct.
   - The binding is a thin `python/duoforge/data.py` (`forme_static(ctx, id)`, `move_static(ctx, id)`, …) that copies the struct into a dict or a numpy row.
   - Python computes nothing. Encoder-side normalisation (stats / 255 and so on) is the learner's feature code, as today.

8. **Versioning and evidence:**
   - **Version:** additive public functions, structs and constants, so one minor bump.
   - **Engine tests:** C tests compare every field of every row under the CLOSURE, TEAM_C and POOL kinds against the internal tables.
   - **Pin check:** a generator test cross-checks a sample of rows (every target class, every flag, every family) against the pin's text.
   - **Python test:** checks the binding against the C values.
   - **Unchanged:** no battle, golden or trace changes.

9. **Type effectiveness, a fifth function.** The type chart is an internal table, and a learner could derive it from the public `DUOFORGE_TYPE_*` ids only by re-implementing it, which AGENTS.md forbids. `duoforge_data_type_effect(ctx, attack_type, defend_type, uint32_t *out_num, uint32_t *out_den)` gives the pinned chart's multiplier as a fraction (0, 1/2, 1, 2), with explicit errors for an unknown type.

## Open points

- Whether the secondary-effect kind and parameter go into a later v2 of `move_static` once the encoding stops growing, or stay internal for good.

## Not in scope

- Learnsets beyond `duoforge_data_forme_moves`.
- Natures: the observation already carries the member's computed stats, so the nature's +/- stats would add nothing; it stays an id.
- Anything that depends on the battle state.
