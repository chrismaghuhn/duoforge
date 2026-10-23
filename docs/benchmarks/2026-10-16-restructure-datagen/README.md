# Restructure 5a: the table generator split by area — proof

Base: clean main **`8800b625`** (#624 merged). The split is made by script from main's `tools/datagen/gen_closure.py`
(no hand-resolved conflict): [analyse.py](analyse.py) lists its top-level statements with the names each defines and
uses, [assign.py](assign.py) gives each its area (explicit lists, then name rules, then a fixpoint that moves a
statement up to the highest module it uses, so every module imports only from modules below it), and [split.py](split.py)
writes the modules. [verify_split.py](verify_split.py) checks the result.

```sh
python3 analyse.py tools/datagen/gen_closure.py <dir>/stmts.json   # the statements of main's file
python3 assign.py <dir>                                              # <dir>/area3.json
python3 split.py . <dir> 8800b625                                    # tools/datagen/tablegen/, gen_closure.py
python3 verify_split.py . 8800b625
```

## Exact change

| Module (`tools/datagen/tablegen/`) | Statements | Content |
|---|---:|---|
| `source.py` | 18 | the pin, the input hashes, `Source`, the entry parsers, the pattern helpers |
| `species.py` | 24 | formes and Pokémon: team sets, forme and type chart parsers, the legal pool, learnsets, forme legality |
| `moves.py` | 227 | the move parser and its tables, the special handlers and pinned callbacks by step, move and field facts |
| `families.py` | 7 | what item and ability families share: parameter codes, the family derivation, handler ids, engine rows |
| `items.py` | 36 | item families, matchers, parameters, item facts by step |
| `abilities.py` | 52 | ability families, matchers, parameters, ability facts by step (Skill Swap's failskillswap list of #624 included) |
| `rules.py` | 44 | pin checks that span areas, and the content batches C1, C2, C4, C5, K2, A0, A0P1 |
| `tables.py` | 6 | the closure, Team C and pool builds; the width bounds |
| `output.py` | 22 | canonical bytes and the C writers |

`gen_closure.py` keeps its docstring, the options and `main()` (2 statements) and re-exports every name of the modules,
so `gen_closure.<name>` reads as before (the tests, `classify_unsupported.py`, `tools/reference/team_registry.py`).
Every statement moves with the comment and blank lines above it; a function or class keeps two blank lines on each side.

Also: the comment of `data/formats/champions-ou.json` said no data kind plays the format. Since decision 0083 the singles
kind plays it on the Reg M-C pool tables; only no header is generated from the definition. `gen_format.py` (docstring,
output line) and `tools/datagen/README.md` say the same now (no test reads that text).

## Proof

- **Statements:** `verify_split.py`: all **438** top-level statements of `gen_closure.py@8800b625` (imports and the
  docstring aside) are, verbatim, in exactly one of the new files, each file in the old order; the docstring of
  `gen_closure.py` is unchanged; its only new statements are the re-export loop and its `del`.
- **P5:** the three modes write byte-identical output to main's generator and pass `--check` against the committed
  files:

| Mode | Canonical sha256 | `.h` sha256 | `.c` sha256 |
|---|---|---|---|
| closure | `86ca9d9f…6ef5c` | `18e2999c…69c7f` | `490de422…d8450a` |
| `--team-c` | `d16b1cef…943e5` | `b2abef24…75a7d` | `9e736fa4…cc17` |
| `--pool` | `d6eee672…2b5e4` | `4003f3ce…847f0b` | `67810cc0…13e15` |

  The format header is unchanged too (`gen_format.py --check`, `src/data/format_tables.h` `321b4495…91af`).
- **Tests (local, pinned checkout `b2cb775b`):** the 19 generator, format and reference-tool tests pass:
  `duoforge.data.{closure_regen, extended_regen, pool_regen, format_pin, format_pin_champions_ou, pool_families,
  format_pool_reg_mc, format_pool_champions_ou, gen_closure_refusals, test_main_last, pool_names, pool_rows,
  classify_unsupported, format_regmc, format_champions_ou, pool_tables}` and `duoforge.reference.{format_pins,
  team_registry, trace.g39_regenerator}`.
- **P1–P4, P6:** no file under `src/`, `include/`, `tests/`, `cmake/` or a `CMakeLists.txt` changes, so the test
  inventory, the reference results, perft, `BENCH_SHA256`, the exports and the layouts cannot change; the hosted CI is
  the full gate.
