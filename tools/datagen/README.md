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

`--pool` writes the extended tables unchanged as the prefix, then the rows that the steps of the content expansion add (step P1: 16 type boosters, 17 resist berries and the abilities Pixilate, Refrigerate, Overgrow, Torrent and Swarm; step G2: the formes Pelipper, Arcanine-Hisui, Annihilape, Floette-Eternal and Floette-Mega, 22 moves, the items Focus Sash, Expert Belt and Floettite and the abilities Rock Head, Flower Veil and Fairy Aura), in a fixed order that the generator documents. It checks the prefix before it writes: every extended and every closure row is field-equal, and the canonical bytes recomputed from the prefix equal those of the closure and of the extended tables. The closure and `--team-c` output stays byte-identical (`--check`).

Every item and ability, the prefix included, also gets a **family column** in an array of its own, so that the row types stay those of the closure tables: items are `TYPE_BOOSTER` (BasePower x4915/4096 for a type) or `RESIST_BERRY` (halves a hit of a type), abilities `ATE`, `PINCH`, `WEATHER_SETTER` or `TERRAIN_SETTER`, with their type, weather or terrain. The generator reads the parameter from the pinned handler with **one strict pattern per family** (whitespace-normalised, the whole entry: its fields, priorities and handler text). It fails when

- a member that decision 0015 lists deviates from the pattern of its family (the one documented variant is Chilan Berry's Normal hit without the super effective condition, and the Primal guard of the weather setters),
- an id that is not listed follows a pattern,
- the Champions mod changes more than `isNonstandard` of a member,
- an id is not legal: it must be in `docs/research/expansion/data/legal_pool.json`, the committed output of the pinned `TeamValidator`.

Every forme also gets the pool moves it learns (a bitset over the pool moves) and its legal abilities (a list over the pool abilities) in an array of its own: the **set rule of the POOL kinds**. The learnable moves are the forme's block in `data/mods/champions/learnsets.ts`, parsed strictly (every entry must be `"9M"`: no event, egg or level-up source, so learnable means listed) and required to equal the pool moves that the pinned validator accepts for the species (`legal_pool.json`). The abilities are the pokedex's, filtered by the validator and cut to the pool, in slot order; a Mega forme has its one ability and no moves, and an ability that the pin does not release (Lucario-Mega-Z's Aura Guard) fails the generator. A base forme must keep its set's moves and ability.

**The weather step (Sandstorm and Snowscape).** Sand Stream and Snow Warning are members of the weather-setter family (codes 3 and 4 of the family column; the Primal guard of rain and sun is optional in the pattern and absent for them), Sandstorm and Snowscape are the handler ids `SANDSTORM` and `SNOWSCAPE` (listed in `WEATHER_HANDLERS`, owning the field `weather`), and the pool's immunity bytes carry the bit `DFI_IMMUNE_SAND` (32) read from the type chart's `sandstorm` key (Ground, Rock, Steel; `type_chart`); `check_weather_facts` demands every fact of the pinned conditions that the engine hard-codes, and `pool_families.js` calls the pinned handlers for them (damage, boosts, Weather Ball, the immunity of exactly those three types).

**Step G2 and the moves the columns do not model.** The 22 moves of G2 go through the same `parse_move` as every other move, with one addition for the pool mode: nine of them have a callback or a field that no column holds (Throat Chop, Encore, Scald, Wide Guard, First Impression, Recover, Soak, Psychic Noise, Low Kick); step G8 took two of them out of the list again: Throat Chop and Psychic Noise are secondary kinds of the generic column (`DFI_SECONDARY_LOCKOUT`, `DFI_SECONDARY_HEAL_BLOCK`, matched on the exact pinned secondary text) and a new column `dfi_pool_move_flags2[]` holds their consumers' flags (bit 1 `sound`, bit 2 `heal`, in the canonical pool bytes), so seven handler ids remain. As decision 0009 section 3.3 did for Sucker Punch and Follow Me, each is mapped deliberately to a **named handler id** in its special column (`DFI_SPECIAL_THROAT_CHOP` and so on) that owns exactly the callbacks, fields, condition block and secondary the generator names, and the text of every owned field or secondary must be the pinned one. The generic columns stay neutral for what a handler owns (no secondary, no side condition). The engine refuses such a move twice: the support manifest leaves it unmarked, and the turn code returns an error for a special it does not implement. Everything else that a move has and the generator does not know still fails, with a message and never as a `KeyError` (an unknown status, volatile, side condition or pseudo weather included). `punch` (Ice Punch) and `allyanim` (Soak) are ignored move flags in the pool mode only; the generator fails if a pool ability reads one of the ignored flags that has a reader (Iron Fist for `punch`, Sharpness for `slicing`). A step that implements a handler and needs a column changes the tables and the POOL fingerprint and says so. A Champions learnset entry may start with `inherit: true,` (Floette-Eternal's does); any other shape fails as before.

### The whole legal pool (decision 0015 section 4.2)

After the rows of the steps (P1, G2), `--pool` appends a row for **every other forme, move, item and ability of the legal pool of the format**, read from `docs/research/expansion/data/legal_pool.json` (the committed output of the pinned `TeamValidator`; the generator checks its Showdown commit and format) and from the pinned data. The closure, Team C and G2 rows stay exactly where they are (the generator compares them with the extended tables, and `duoforge.data.pool_tables` pins the closure-layout bytes of the 28 formes, 72 moves, 52 items and 29 abilities of the steps). The counts: **346 formes** (the 293 selectable formes less 29 cosmetic copies, plus 82 Mega formes), **511 moves** (the 510 of the pool and Struggle), **166 items**, **215 abilities**; the new rows follow the order of the legal pool file.

- **A forme row** has the dex number, weight, types, base stats, gender rule and ability of the pokedex (cross-checked against the legal pool record), a base forme the moves it learns (the Champions learnset; a forme without an entry of its own, or with an empty one, learns what its base species learns) and the abilities the validator allows, in slot order. A forme outside the closure, Team C and G2 has no set of its own (`set_item` none, no set moves); its ability field is its first legal ability. A base forme links the first Mega forme of the legal pool's order through its stone (Charizard keeps Y and Raichu Y, the closure's); a second Mega forme of the same base (Absol-Z, Charizard-X, Garchomp-Z, Lucario-Z, Raichu-X) is a row of its own with the same base forme and is not reachable in battle. The 29 cosmetic formes that the validator treats as their base forme (Vivillon patterns, Alcremie creams, ...) are no rows: `dfi_pool_forme_aliases` names them (data only, in no hash; `duoforge_data_find` accepts them). Seven non-Mega battle-only formes are no rows.
- **A move row** is encoded as before wherever the tables model it. What they do not model is **UNMODELED**: any callback, any field outside the modelled ones, a secondary, self block, boost, status, volatile, side condition or pseudo weather that no column holds, a target class that the turn code lacks (`allAdjacent`, `scripted`, `allyTeam`, `allies`, `foeSide` are encoded as 11 to 15 in the generated header, never as public values), a `selfSwitch` that has no switch flag of its own (`dfi_pivot_moves`), and a non-boolean `selfSwitch` (Baton Pass, Shed Tail). Such a move gets the special id `UNMODELED`, its effect columns neutral (it claims nothing beyond its type, category, power, accuracy, PP, priority, target class, crit ratio, flags, recoil and drain), and the list of its features. What the generator cannot read at all still fails: a type, category, target class or PP it does not know, a move flag outside the known ones of the pool (POOL_FLAGS), a value that does not fit its byte.
- **An item or ability row** gets a **handler column** value (`DFI_HANDLER_NONE` or `UNMODELED`). It is modelled when it is a row of the closure or Team C (code in the turn core), a family member (a table rule), a row that a step implements by id (`ENGINE_ROWS` of the generator: Focus Sash and Rock Head, step G4; Floettite, Flower Veil and Fairy Aura, step G12), or an entry with no callback, no condition block and no field beyond the inert keys **that no other code reads by its id** (Damp Rock is read by the rain condition, Levitate by `isGrounded`; `ReaderIndex` finds them in the pinned `data/conditions.ts`, the data files and `sim/`). A Mega Stone keeps its `onTakeItem` as data of its Mega link, and a stone whose Mega forme is not the one its base forme links is UNMODELED. The step that marks such a row adds its id to `ENGINE_ROWS` (or gives a move its handler id), which changes the pool table hash like any pool change.
- **Flags.** The move flags byte is full and stays so. A flag that no bit holds matters only when a modelled row reads it; the generator scans the pinned handlers of the prefix rows for the flags they read (`bypasssub` by Chople Berry beside a substitute that no modelled row has, `pledgecombo` by Lightning Rod: both declared in `INERT_FLAG_READS`) and a move row with a flag that matters would be UNMODELED with the flag in its list. None does today. Marking a reader (Soundproof, Iron Fist, ...) is the step that adds the flag column.
- **Nothing half-modelled is marked.** `duoforge.data.pool_tables` fails for a marked row (move, item or ability) with the UNMODELED handler or a list of features; the support manifest is the only mark.
- **The unmodelled features** are a generated comment of every row (`[unmodelled: ...]`) and data: `dfi_pool_move_unmodeled`, `dfi_pool_item_unmodeled` and `dfi_pool_ability_unmodeled` (a string of features separated by `; `, NULL for a modelled row), in no hash.
- **Bounds.** `check_bounds` reads the widths of the state (`dfi_member.species_id`, `dfi_move_slot.move_id`, `item`, `ability`), of the observation and events (`duoforge_member_view`, `duoforge_event`) and of the context from their sources and fails when a count does not fit: a forme or move id is a u16 (0xFFFF is the forme "none" of the pool rows), an item or ability is 1 + the id in a byte so an id is at most 254 (0xFF is the tables' none), at most 512 moves (`DUOFORGE_DATA_MAX_FORME_MOVES`) and three abilities per forme. `src/state/closure_member.c` repeats the same as `_Static_assert`s.
- **The pool row types.** The pool has more than 255 formes, so its forme and item rows are their own types (`dfi_pool_forme_data`, `dfi_pool_item_data`) with u16 forme links; the closure and extended rows keep their u8 types and bytes. The canonical pool bytes are the pool layout (the six counts; 26 bytes per forme; 29 per move; 4 per item; the type chart, immunity bits and natures; then the family columns, the handler columns and the legal moves and abilities of the formes); the closure layout of `dfi_pool_canonical_bytes_of` remains for the prefix hashes and refuses a prefix that it cannot hold. Their SHA-256 is the pool table hash that the POOL fingerprints carry.

Two more files, read only by these rows, are pinned by their SHA-256 in `READER_INPUTS` (they are not part of any table header's provenance): `data/conditions.ts`, six `sim/` files and the Champions `conditions.ts`.

Checks added with the rows: `test_pool_rows.py` (`duoforge.data.pool_rows`: the tables against `legal_pool.json` with code of its own, no checkout), `test_gen_closure.py` (the lenient mode, the item and ability features, the bounds, the aliases) and `pool_families.js` (for every row the UNMODELED marker against the pinned entry, every cosmetic alias against the pinned dex and the validator, and the whole-pool probes of every base forme with every move and ability: 191 thousand validator calls).

The canonical pool bytes are the pool layout above (before the whole-pool rows: the closure layout over the pool data followed by the family columns and the moves and abilities of the formes); their SHA-256 is the pool table hash that the POOL fingerprints carry.

Checks: `duoforge.data.pool_tables` (the prefix, the three hashes, the family columns), `duoforge.state.pool_setup` (the POOL kinds), and under `-DDUOFORGE_PS_REFERENCE_DIR` `duoforge.data.pool_regen` (`--pool --check`) and `duoforge.data.pool_families` (`pool_families.js`, which calls the pinned handlers with a probe for each of the 18 types and requires the generated type, weather or terrain, and runs the pinned validator on the pool's ids, and on every base forme with every pool move and ability; a Mega-only ability such as Fairy Aura is checked through its Mega forme and stone).
