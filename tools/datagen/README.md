# Closure data generator

`gen_closure.py` writes `src/data/closure_tables.h` and `src/data/closure_tables.c`: the immutable data of the two reference teams (decision `0004`), read from the pinned Pokémon Showdown checkout (decision `0006` section 2).

It is offline tooling. The generated files are committed, so building and testing DuoForge needs neither Python nor Showdown.

## What it extracts

- 16 formes (12 sets and 4 Mega formes): dex number, types, base stats, weight, the set's ability, gender rule, Mega link and stone, the set's item and moves.
- 36 moves plus Struggle with the Champions overrides applied: type, category, power, accuracy, base and maximum PP, priority, target class, crit ratio, flags, recoil, drain, secondary effect, boosts, side and field conditions, and the id of the handler for every callback.
- 11 items (the Mega Stone mapping), 16 abilities (ids only), the 18-type chart with the status immunities the closure needs, and the 25 natures.

Every record carries its `path:line` at the pin as a comment.

## What it refuses

The generator fails instead of guessing when

- an input file's sha256 differs from the pin (after CRLF to LF normalisation),
- a move has a field it does not know,
- a move's secondary is not exactly one modelled effect (a status, a volatile, or boosts on the target), for example Flame Charge's self boost,
- a callback is not mapped to a named handler id,
- a set is not legal in the Champions learnsets or formats data.

Data is not mechanics: an id only names a record. Every effect still needs a typed handler in C and an entry in the support manifest.

## Run

```sh
python3 tools/datagen/gen_closure.py <pinned checkout>          # write the files
python3 tools/datagen/gen_closure.py <pinned checkout> --check  # compare only
```

After regenerating, update the two file hashes in `tests/CMakeLists.txt` and the table hash in `tests/test_closure_tables.c`. With `-DDUOFORGE_PS_REFERENCE_DIR=<pinned checkout>` CTest runs the `--check` form as `duoforge.data.closure_regen`.

`test_gen_closure.py` checks the refusals on small move, item and ability texts without a checkout; CTest runs it as `duoforge.data.gen_closure_refusals` whenever Python is found.

## Extended and pool tables

Two more modes write tables that start with the closure:

```sh
python3 tools/datagen/gen_closure.py <pinned checkout> --team-c [--check]  # src/data/extended_tables.{h,c} (decision 0009)
python3 tools/datagen/gen_closure.py <pinned checkout> --pool [--check]    # src/data/pool_tables.{h,c} (decision 0015)
```

`--pool` writes the extended tables unchanged as the prefix, then the rows that the steps of the content expansion add (step P1: 16 type boosters, 17 resist berries and the abilities Pixilate, Refrigerate, Overgrow, Torrent and Swarm), in a fixed order that the generator documents. It checks the prefix before it writes: every extended and every closure row is field-equal, and the canonical bytes recomputed from the prefix equal those of the closure and of the extended tables. The closure and `--team-c` output stays byte-identical (`--check`).

Every item and ability, the prefix included, also gets a **family column** in an array of its own, so that the row types stay those of the closure tables: items are `TYPE_BOOSTER` (BasePower x4915/4096 for a type) or `RESIST_BERRY` (halves a hit of a type), abilities `ATE`, `PINCH`, `WEATHER_SETTER` or `TERRAIN_SETTER`, with their type, weather or terrain. The generator reads the parameter from the pinned handler with **one strict pattern per family** (whitespace-normalised, the whole entry: its fields, priorities and handler text). It fails when

- a member that decision 0015 lists deviates from the pattern of its family (the one documented variant is Chilan Berry's Normal hit without the super effective condition, and the Primal guard of the weather setters),
- an id that is not listed follows a pattern,
- the Champions mod changes more than `isNonstandard` of a member,
- an id is not legal: it must be in `docs/research/expansion/data/legal_pool.json`, the committed output of the pinned `TeamValidator`.

Every forme also gets the pool moves it learns (a bitset over the pool moves) and its legal abilities (a list over the pool abilities) in an array of its own: the **set rule of the POOL kinds**. The learnable moves are the forme's block in `data/mods/champions/learnsets.ts`, parsed strictly (every entry must be `"9M"`: no event, egg or level-up source, so learnable means listed) and required to equal the pool moves that the pinned validator accepts for the species (`legal_pool.json`). The abilities are the pokedex's, filtered by the validator and cut to the pool, in slot order; a Mega forme has its one ability and no moves, and an ability that the pin does not release (Lucario-Mega-Z's Aura Guard) fails the generator. A base forme must keep its set's moves and ability.

The canonical pool bytes are the closure layout over the pool data followed by the family columns and the moves and abilities of the formes; their SHA-256 is the pool table hash that the POOL fingerprints carry.

Checks: `duoforge.data.pool_tables` (the prefix, the three hashes, the family columns), `duoforge.state.pool_setup` (the POOL kinds), and under `-DDUOFORGE_PS_REFERENCE_DIR` `duoforge.data.pool_regen` (`--pool --check`) and `duoforge.data.pool_families` (`pool_families.js`, which calls the pinned handlers with a probe for each of the 18 types and requires the generated type, weather or terrain, and runs the pinned validator on the pool's ids, and on every base forme with every pool move and ability).
