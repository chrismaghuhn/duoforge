# 0065 - Psychic Terrain (G96, lane A batch 7, builder H23)

Status: **implemented on chris/expansion-g96-psychic-terrain; evidence on the final head pending** (the lock job of section 6). Metal Burst is not part of this decision: it stays paused, and decision 0064 and tail bytes 33-35 stay reserved (no Metal Burst code may land). Decision 0015 letter **5cz**. Pin: Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`). Builds on 0015 (POOL kinds, the pool tables), 0023 (the public state), 0007 (the view), and the terrain rules already on main (Electric, Misty; the Psychic Seed of 0059/Team C).

## 1. Pin semantics (checked against the pin)

- **The move** (`data/moves.ts:14095`, `psychicterrain`): a status move, `terrain: 'psychicterrain'`, `onTryHitPriority: 4`, duration 5 (8 with Terrain Extender, `durationCallback`), residual order 27, sub-order 7, `-fieldstart|move: Psychic Terrain` (with `[from] ability:` when set by an ability) and `-fieldend|move: Psychic Terrain`.
- **The setter** (`sim/battle-actions.ts:1252-1255`): `moveData.terrain` calls `this.battle.field.setTerrain(moveData.terrain, source, move)`, the same path as Electric and Misty. `Field.setTerrain` (`sim/field.ts:130-137`) returns false when the same terrain is up (the move fails with `-fail` and `[still]`) and otherwise replaces the terrain.
- **The block** (`data/moves.ts:14112-14128`, onTryHit): a move with priority above 0 (`effect.priority > 0.1`, not self) is stopped at a grounded foe (not semi-invulnerable, not an ally): `-activate|target|move: Psychic Terrain` and null (no `-fail`). A priority move against an **airborne** target is not stopped; it gets the hint `Psychic Terrain doesn't affect airborne Pokémon.` (only when the move's priority is above 0).
- **The boost** (`data/moves.ts`, onBasePower): a Psychic-type move of a grounded, not semi-invulnerable user does 5325/4096 times the damage (the Psychic terrain's 1.3).
- **Psychic Seed** (`data/items.ts:4911-4919`): `onTerrainChange` uses the item when the Psychic Terrain is up (boost spd +1), `onStart` at the switch-in too. Its line comes after the `-fieldstart` of the setter.

## 2. Engine (what the branch does)

- The setter is the special `PSYCHIC_TERRAIN` (the generated id 120, after Ally Switch 119 on main; `UNMODELED` is 121; the value is in `src/data/pool_tables.h`), handled in the terrain-start branch of `dfi_run_move_body` next to Electric and Misty: the Terrain Extender duration, the same-terrain `-fail` with `[still]`, the seeds of the terrain change.
- The block and the boost are the terrain rules of the move body (`src/combat/turn.c`, the Psychic block before the hit steps: a priority move at a grounded foe). A spread move with positive priority while the terrain is up is refused (E_UNSUPPORTED, `psychic_block && count > 1`, the intended refusal of this step: no spread move in the data has positive priority).
- The gate of implemented specials lists `DFI_SPECIAL_PSYCHIC_TERRAIN`.
- The view: `duoforge_move_result` maps the setter like the other terrains (HS's fix 6a062ac7, `src/state/view.c`); the cases are in `tests/interactions/test_view.c`.
- No new state: the terrain is the existing field byte and turns.
- Manifest: `DFI_MOVE_PSYCHICTERRAIN` marked (`src/data/support_manifest.c`).

## 3. Refusals and the one intended one

- A spread move with positive priority while the Psychic Terrain is up: E_UNSUPPORTED (section 2).
- Residual speed ties of three or more (`dfi_residual_pair_draws`, `turn.c:10321`): E_UNSUPPORTED, "a bigger group: its shuffle is not modelled". Seen once in seed 97 (fz_97_254, Snorlax's burn at the last step, no terrain in the battle). Pin: `sim/battle.ts:429-456` (`speedSort` with `prng.shuffle` for equal speeds). Intended, not a Psychic Terrain refusal.

## 4. Evidence on the earlier head (the campaigns ran on the G96 base; see section 6 for the final head)

- Recorded battle `g96_psychic_terrain_block` (two sides, the block of grounded Gardevoir and Golisopod, the flying Dragonite not blocked, the Psychic boost, a second setter failing), conformant.
- Campaigns on the HEAD runner of that base, teams X and Y, pairings XY YX XX YY:
  - seed 96, 300 battles: 300 PASS, blocks 54;
  - seed 97, 300 battles: 299 PASS, 1 UNSUPPORTED (section 3), blocks 45;
  - together 599 battles, 99 blocks (the goal of 100 was one short; seed 98 was open at the pause).
- Mutants of the earlier base: P1 the block off, P2 the block also on airborne foes, P3 the Psychic boost off, P4 setting the terrain that is up does not fail, P5 the block also on priority 0, P6 the setter without the Psychic branch: 6 of 6 caught by `conformance_pool_data` and `tiebreak_pool_data`.

## 5. Tracker (HS)

The tracker folds Psychic Terrain on main (`python/duoforge_live`, `_FOLD_FIELD` and `_FOLD_ACTIVATE "move: Psychic Terrain"`, Team C era). HS's batch adds the classifier mapping (6a062ac7) and the POOL_OUTCOME step. The `python/` tests are HS's; the count pins there are set from a CI log only.

## 6. Final evidence (the lock job on the final head)

Run on the C head 841b64a5 (lock job `g96-final-evidence`; the later commit 1f7b1df0 changes only the Python pin `POOL_OUTCOME` equal 11590 to 11604, from the CI log of 841b64a5).

- **Build and sanity:** clean build, then the sanity replay of `g96_psychic_terrain_block` (the recorded Psychic Terrain battle): PASS, before and after the mutants.
- **Runner sha256:** `4ab071c3bfb92de3f9363857cb2b2d113a11badd16ff759e1557a010db97332b` (the clean build); `a050bdb3135f4de6d2f4a843426279dea4e0dd13dd6af4facd2c7b998c674b96` (the clean rebuild after the mutants, same sources). The Windows link is not byte-reproducible (link timestamp); the sanity replay passes on both.
- **Mutants P1-P6** (one edit each in `src/combat/turn.c`, rebuild, catching tests, restore from HEAD, `git diff` empty after the restore): P1 the priority block off, P2 the block also on airborne foes, P3 the Psychic boost off, P5 the block on priority 0 moves, P6 the setter without the Psychic branch: each caught by `duoforge.reference.conformance_pool_data` and `duoforge.reference.tiebreak_pool_data`. P4 (setting the terrain that is up does not fail): caught by `conformance_pool_data`. **6 of 6 caught.** Baseline: 6 of 6 tests pass.
- **Campaigns** (teams X and Y, pairings XY YX XX YY, keep-traces, the HEAD runner):

| seed | battles | result | sets | blocks | airborne not blocked | [still] | Seed uses | Seed boosts | Psychic damage under terrain |
|---|---|---|---|---|---|---|---|---|---|
| 96 | 300 | PASS 300 | 140 | 54 | 3 | 68 | 135 | 135 | 110 |
| 97 | 300 | PASS 299, UNSUPPORTED 1 | 127 | 45 | 1 | 73 | 121 | 121 | 118 |
| 98 | 100 | PASS 100 | 49 | 27 | 1 | 24 | 42 | 42 | 18 |
| **sum** | **700** | **PASS 699, UNSUPPORTED 1** | **316** | **126** | **5** | **165** | **298** | **298** | **246** |

- **The known refusal in seed 97** (fz_97_254, step 24, XX): not a Psychic Terrain refusal. Snorlax's burn kills it at the last step; the battle has no terrain. The refusal is `dfi_residual_pair_draws`, `turn.c:10321`: an equal-speed residual group of three or more ("a bigger group: its shuffle is not modelled"). Pin `sim/battle.ts:429-456` (`speedSort` with `prng.shuffle`). Intended, the same refusal as the residual speed tie of the earlier base.
- **Goal:** blocks 126 in total against 100 (the seed 98 campaign reached 27 on its own). The "blocks" counter is the protocol count of `-activate ... move: Psychic Terrain`; the block against grounded targets only, airborne targets are counted apart.
