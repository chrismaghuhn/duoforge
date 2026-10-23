# Restructure 5b-2: the table set of a format — proof

Stacked on 5b-1 (`restructure/5b-move`) and 5a (`restructure/5-datagen`); base main `8800b625`. The schema of the
`tables` section was agreed with the OU lane through the HS (2026-10-17). This step parametrises the generator; it
builds no table of another format, and Reg M-C stays byte-identical.

## Exact change

| Where | What |
|---|---|
| `data/formats/reg-mc.json` | a `tables` section: `rule_set` `champions`, `symbol_prefix` `pool`, `include_guard` `DUOFORGE_DATA_POOL_TABLES_H`, `stem` `pool_tables`, `learnset_bytes` 64, `bounds` (formes 65534, moves 65535, moves per forme 512, items 254, abilities 254), `excluded_formes` none |
| `tools/datagen/gen_format.py` | `check_tables`: every key required, a missing or unknown key refused by name (`missing [...], unknown [...]`), each value's shape, each excluded forme `{id, reason}` with a non-empty reason, no id twice; the section is optional, and a definition without it builds no tables |
| `tools/datagen/tablegen/source.py` | `BASE_INPUTS` and `RULE_SETS`: a rule set names its override files by role (moves, items, abilities, formats data, learnsets, scripts), their pinned sha256 and its PP cap (`champions`: 20; `None` is no cap); `rule_set(name)` refuses an unknown name; `INPUTS` is their union, unchanged in content and order |
| `tools/datagen/tablegen/formats.py` (new) | `load_table_set(repo, id)`: the definition (and through `gen_format.load_format` its pool's sha256 and the pool's `meta.format_id` and `showdown_commit` against the definition), the pin, the rule set |
| `species.py` | `load_legal_pool(repo, ts)`: the set's pool, checked against the pin and the definition's format id; the excluded formes leave the pool, each named with its reason; one that is not in the pool fails, and so does one that a Mega or a cosmetic forme of the pool needs. `forme_legal(..., learnset_bytes, pool_name)`: fewer bits than pool moves fail instead of rounding up |
| `tables.py` | `build`, `build_pool` and `check_bounds` take the set; the rule set's files replace the literal Champions paths; `check_bounds` checks the pool against the set's bounds and the bounds against the row fields and `DUOFORGE_DATA_MAX_FORME_MOVES` |
| `moves.py` | `parse_move` and `parse_pool_move` take the rule set's `pp_cap` |
| `output.py` | `render_pool(..., ts)`: the learnset width is the set's; `table_set_names` writes the prefix, the guard, the header path `data/formats/<id>/<stem>.h`, the pool source and, for a set with exclusions, their reasons after the guard |
| `gen_closure.py` | `--pool --format <id>` (default `reg-mc`); the output directory is `src/data/formats/<id>/` |

Still Champions-specific (named in the code, for step O8 of the Gen 9 design): `calculatePP`'s formula and the pin
checks of single steps that quote Champions files; a rule set `gen9` without overrides comes with the code that reads
the base data alone.

## Proof

- **P5:** closure, `--team-c`, `--pool` and `--pool --format reg-mc` pass `--check` and write the committed files byte for
  byte; `gen_format.py --check` unchanged (`321b4495…91af`).
- **New tests:** `duoforge.data.table_sets` (offline, 18 cases: the schema refusals, the rule sets, the exclusions
  against a made-up pool, the learnset width, the set bounds, the writer's names, Reg M-C's names leaving the committed
  files unchanged) and `duoforge.data.table_sets_pinned` (with the pinned checkout, 4 more: the whole pool tables of a
  made-up format with another prefix, guard and stem, 65 learnset bytes and one excluded forme; Reg M-C's header again
  byte for byte; the PP cap of the rule set). The first run of the pinned case found that the writer derived its
  learnset width from the move count; it takes the set's now.
- **Regression:** the 19 generator, format and reference-tool tests and the six provenance checks pass;
  `duoforge.data.format_pool_reg_mc` and `format_pool_champions_ou` (the pinned validator makes both committed pools).
- **P1–P4, P6:** no engine source changes; the test inventory gains exactly `duoforge.data.table_sets` and
  `duoforge.data.table_sets_pinned`.
