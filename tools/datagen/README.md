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
- a callback is not mapped to a named handler id,
- a set is not legal in the Champions learnsets or formats data.

Data is not mechanics: an id only names a record. Every effect still needs a typed handler in C and an entry in the support manifest.

## Run

```sh
python3 tools/datagen/gen_closure.py <pinned checkout>          # write the files
python3 tools/datagen/gen_closure.py <pinned checkout> --check  # compare only
```

After regenerating, update the two file hashes in `tests/CMakeLists.txt` and the table hash in `tests/test_closure_tables.c`. With `-DDUOFORGE_PS_REFERENCE_DIR=<pinned checkout>` CTest runs the `--check` form as `duoforge.data.closure_regen`.
