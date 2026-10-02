# Reference harness (pinned Pokemon Showdown)

Scripts here run against the pinned Showdown checkout (`b2cb775b0616115b775534eaeff50300e1fc81fc`, decision 0004) and turn its behaviour into committed C test data (decision 0006 section 7). CTest never needs Node: the generated files are committed, and the checks below run only when `-DDUOFORGE_PS_REFERENCE_DIR=<checkout>` is set and Node is found.

## `arith_ref.js`

Reference values of the damage and stat arithmetic: `Battle.modify`, `chainModify`, `Battle.randomizer` with a fixed roll, `Dex.trunc` and `Pokemon.calculateStat` on a real Pokemon of the format are called directly. The expressions the reference computes inline (base damage, the critical hit, type and final steps of `modifyDamage`, the accuracy stages) are evaluated with the reference's own `trunc` and cited in the script.

```sh
node tools/reference/arith_ref.js <checkout> > tests/reference/arith_ref.h
node tools/reference/arith_ref.js <checkout> --check tests/reference/arith_ref.h
```

CTest runs the `--check` form as `duoforge.reference.arith` (label `reference`). `duoforge.unit.modifier` compares `src/core/modifier.c` with the committed header.

## `ps_trace.js`

Records a complete battle. A spec (`tests/reference/specs/*.json`) gives the format, a PRNG seed, both teams as Showdown paste text (gender always given) and either the choices in request order (`choices`) or a plan (`plan`: per side the choices for its move requests in order, the last one repeated, and `max_steps`). In plan mode the harness answers team preview with the first four, a replacement with the first standing reserves and a fainted slot with `pass`; a planned move without PP falls back to the first move with PP, a target is dropped for a move that takes none and is 1 for a move that needs one. A planned switch of a trapped Pokémon (for example one charging a two-turn move) becomes "move 1 1". It records the choices it made. Draws inside a status or confusion handler are named by the effect and event the reference is running (sleep and confusion turns, freeze thaw, full paralysis, confusion self-hit). In the speed sort of `runSwitch` each Pokémon is labelled with its SwitchIn handlers and whether it is entering, in the speed sort of an `each:` event with the effects of its handlers; the snapshot records the weather and terrain durations and the moves each request offers. The harness runs the battle with a recording PRNG and writes a trace (`tests/reference/traces/*.json`): for every choice entry the draws it caused (site, context, bounds, value), the protocol lines and the state at the next boundary (exact HP, status, stages, PP, volatiles, active slots, requests).

```sh
node tools/reference/ps_trace.js <checkout> tests/reference/specs/s2_turn_core_1.json > tests/reference/traces/s2_turn_core_1.json
node tools/reference/ps_trace.js <checkout> tests/reference/specs/s2_turn_core_1.json --check tests/reference/traces/s2_turn_core_1.json
```

The site of a draw is read from its call stack, the context from the reference's event entry points, which the harness wraps (`queue`, `insert`, `switch-order`, `each:<event>`, `field:<event>`, `event:<event>`, and for random targets `action-speed`, `resolve` or `execute`). A draw it cannot classify is written as `UNKNOWN`; such a trace must not become a fixture. CTest reruns every spec as `duoforge.reference.trace.<name>` (label `reference`). Decision 0006 section 5.1 explains what the families mean for aligning DuoForge with the reference.

As a module, `require('./ps_trace.js')` gives `run(root, spec, specFile)`, `PIN` and `HARNESS_VERSION`. `run` records one battle from a parsed spec and returns the trace text, exactly what the command line prints; `root` is the checkout and `specFile` the spec's path, of which the trace stores the file name. It never exits the process: errors throw. The Showdown modules stay cached by `require`, so one process can record many battles. `run` first resets the state the harness keeps outside the battle (the event stack and the flags of the draw classification), so a run that threw leaves nothing behind. The command line is `run` plus the `--check` comparison. CTest records every committed spec in one process as `duoforge.reference.trace_run` (label `reference`): each result must equal its committed trace, a rejected choice must throw and leave the next run unchanged, and five specs (closure and Team C, one that ends the battle) run again in reverse order.

## `trace_to_c.py`

Turns every spec and trace into `tests/reference/conformance.h`: the teams in DuoForge ids, the slot commands per step, the expected members (HP, PP, stages, stall counter, the item still held), status, status counter and confusion turns, the boundary and result after the step, the occupants of the positions, the order of the entries, weather, terrain, Trick Room and the side conditions with their remaining turns, the moves each request offers, and the tape. Each player's view of the other side (seen members and their last public HP display) is rebuilt from the public copy of the protocol lines; a public HP that is not a Champions percent display stops the conversion. Each player's events of every step (decision 0007 section 11) are rebuilt from the protocol lines that player sees: the own copy of a split line for its owner, the public copy for the opponent; attributes that amend a move line are folded into its event, `[silent]` lines and hints are not events, and an unknown line or attribute stops the conversion. Residual ties between callbacks (burn, Grassy Terrain) are kept, because the engine draws them; entry-order ties are kept when two entering Pokémon have entry abilities; `each:` ties are kept when two tied Pokémon hold Sitrus Berry or Grassy Seed (their order is the order of their lines); when both sides' same side condition ends in one residual, the tie becomes an entry stating which side's end line comes first; queue-insertion ties among entries that run together and ties between screen handlers are dropped. The converter rejects a gender the species cannot have: the reference fixes it silently, DuoForge refuses the team. A `pass` the reference wants for a slot that a replacement does not ask becomes no command. Draws without effect are dropped by named rules whose preconditions it checks (decision 0006 section 5.1); each step records how many were dropped. Shuffle draws become relative to their group. CTest checks that the committed headers are what the script makes of the traces (`duoforge.reference.conformance_tables`).

```sh
python tools/reference/trace_to_c.py .           # write the three headers below
python tools/reference/trace_to_c.py . --check   # compare them
```

It writes three files. `tests/reference/conformance.h` holds the closure battles and `conformance_team_c.h` the battles whose spec says `"data": "team_c"` (read with the extended tables). The record types of both (`df_conf_member`, `df_conf_step` and the others) are written to `tests/reference/conformance_types.h` from one template in the script; the two data headers include it, and so do the comparators of `tests/support/conformance_compare.c` (the checks of the replay, which later runners share).

The script is also a library (`import trace_to_c` from `tools/reference`). `load_battle(root, name)` reads a spec and a trace and is the only file IO of a conversion. `convert_battle(name, spec, trace, tables)` is pure and returns plain data in the field order of the `df_conf_*` types: the name, the purpose, the member count, the members as int tuples, and per step the `df_conf_step` fields, with the step's own tape entries (site, lo, hi, value) and each player's event tuples in place of offsets into the shared arrays, and the number of dropped draws; with the total dropped. `format_battle(data, out, all_tape, all_events)` writes that data as the C tables, appending to the shared tape and event arrays, and `spec_is_team_c(name, spec)` reads the Team C decision from a spec. `step_record(st, tape_off, ev_off, ev_len)` is one step as the nested int tuple of its `df_conf_step` in declaration order, the one place in Python where that order is written down; `format_battle` prints it, and a runner that writes records can flatten the same tuple (the member rows and the event tuples are in declaration order already). The drop rules stay in one place and are checked as before.

Whatever the converter does not model raises `ConversionError`, a `SystemExit` with a short stable `rule` (for example `protocol-line`, `unclassified-draw`, `residual-tie-callbacks`, `struggle-request`; it is the first argument of each `raise` in the script) and an optional `detail` that groups the cases (the protocol line kind, the attribute, the effects of the tie). The message is unchanged, so a script that does not catch it still prints it to stderr and exits with status 1.

CTest also runs `test_trace_to_c.py` as `duoforge.reference.converter_api` (Python only, no Node and no checkout). Its negative controls change in-memory copies of committed battles and assert the rule, the detail and the exact message of each refusal. It checks that the library reproduces the three committed headers, the shape of the data against the declarations of the record types (and `step_record` against the declared field names), that `convert_battle` does no file IO and leaves its inputs alone, that a choice passing both slots of a switch request converts, and the command line: `--check`, the usage message, a refused trace (status 1 and its message) and write and check of all three files on a small copy.

To add a battle: write a spec (gender for every gendered species), record its trace with `ps_trace.js`, run `trace_to_c.py`, and raise the battle count in `tests/test_conformance.c`.

The checkout needs `npm ci --ignore-scripts --omit=dev` and `node build` once, so that `dist/sim` exists.

## `gen_real_specs.py`

Reference battles of the real teams for the certification (decision 0010, M5 step 3). For each pairing (A-B, B-A, A-A, B-B) it builds candidate specs from `tests/reference/teams/team_a.txt` and `team_b.txt`: the six sets in a seeded random order (team preview brings the first four), a seeded random plan and a seeded reference PRNG seed (splitmix64, stable across Python versions). It records every candidate with `ps_trace.js`, drops traces with an `UNKNOWN` draw site or without a result, and keeps per pairing the battles that add the most coverage (protocol line kinds with their effect, draw sites with their context), greedily. The kept specs are written as `<prefix>_<pairing>_<k>.json` and recorded again from that path.

```
python tools/reference/gen_real_specs.py --checkout <pinned checkout> --candidates 40 --keep 4
```

With `--team-c` it builds the pairings of the Team C gate instead (decision 0009, step 12): C-A, C-B, A-C, B-C and C-C, with the real Team C of `docs/research/third-team/team-c.txt`, under the TEAM_C data kind. The defaults then are `--seed 2026100212 --prefix c12_real`, which reproduce the committed `c12_real_*` battles.

```
python tools/reference/gen_real_specs.py --checkout <pinned checkout> --team-c
```

## The differential loop: worker, records, runner, driver

The pieces below carry `docs/research/expansion/differential-testing.md` (components 1 to 4, replay mode): a persistent worker records battles with the pinned Showdown, the converter turns each trace into data, a C runner replays that data in the engine and compares, and a driver puts every battle in a bucket. Replay mode runs the committed specs; every one must come out PASS.

### `ps_worker.js`

```sh
node tools/reference/ps_worker.js <pinned checkout>
```

One Node process that records many battles. It speaks JSON lines: one request per stdin line, one response per stdout line, in request order, nothing else on stdout (what a library prints goes to stderr). It exits at EOF.

```
{"id": n, "cmd": "version"}  ->  {"id": n, "ok": true, "node": process.version, "pin": PIN, "harness": HARNESS_VERSION}
{"id": n, "cmd": "record", "spec": <spec object>, "spec_file": "<basename.json>"}
                             ->  {"id": n, "ok": true, "trace": "<the trace text of ps_trace.run>"}
anything that throws, an unknown command, a line that is not a request
                             ->  {"id": n, "ok": false, "error": "<message>", "stack": "<first lines>"}
```

`id` is an integer the client chooses and gets back; a line that is not a JSON object with an integer `id` is answered with `"id": null`. A bad request never ends the worker. `record` is `ps_trace.run(checkout, spec, spec_file)` and nothing else: `spec_file` is the file name the trace stores (no directory), and the trace text is exactly what the command line prints, so the committed traces stay the reference. A `play` command (random choices, each judged by Showdown) comes later and goes where `ps_worker.js` says so; until then it is an unknown command. `duoforge.reference.worker_protocol` (label `reference`, needs Node and the checkout) checks the protocol over raw pipes: the answers and their order, a request that throws followed by a normal one, every kind of line it cannot use, that stdout stays clean, EOF.

### `conformance_records.py`

```sh
python tools/reference/conformance_records.py --all <repo root> --out <dir>   # closure.records and team_c.records
```

The records are what the C runner reads: one battle of `convert_battle`'s data as line-oriented ASCII, `B` (name, closure or Team C, member count, step count, dropped draws), `M` (a member row), then per step `S` (the step record), its `T` lines (the kept draws) and its `E` lines (the events of player 0, then player 1's), and `END`. Every number is written; the format has no defaults. The field order is the converter's: the member rows, `step_record()` and the event tuples are flattened in the order they have, and the writer has no list of fields of its own. The offsets in a step record are into the tape and the events of its own battle. The format is described in the docstring of the module; `write_battle(data, team_c, out)` writes one battle, all or nothing, and refuses (ValueError) what the format cannot hold.

CTest writes the records of all committed battles into the build directory (`duoforge.reference.records_write`, the setup of a fixture) and `duoforge.reference.runner_records` and `duoforge.reference.runner_records_team_c` read them with `tools/difftest/records.c` and require every battle, member, step, mon, tape entry and event to equal the compiled tables (`conformance.h`, `conformance_team_c.h`): `memcmp` of zeroed structs, the name and the per-battle offsets compared separately. Their negative controls flip one field of a copy of a parsed battle at a time (the comparison must report each one) and feed the reader damaged copies of a battle (each must be refused). The reader follows the `df_conf_*` declarations field by field, and static asserts on their sizes stop the build when a record type changes.

### `duoforge_diff_runner`

```sh
duoforge_diff_runner [records file]      # without a file: records on stdin
```

Built with the tests (`tools/difftest`; it links `duoforge_test_support`, which has the comparators, and is white-box like the conformance test). For each battle in the input it sets the teams up and picks the context exactly as `tests/test_conformance.c` does (closure battles under CLOSURE, then CLOSURE_DEV; Team C battles under TEAM_C, then TEAM_C_DEV), steps with `dfi_battle_step_events_tape` (the reference's kept draws as the tape, which must be consumed exactly), then compares the state, the observations and the events with `df_conf_compare_*` and checks `duoforge_battle_check`. The first step with a difference ends the battle. On stdout come the messages of the comparators (indented two spaces) and one flushed line per battle:

```
R <name> <PASS|DIVERGENCE|UNSUPPORTED> <CLOSURE|CLOSURE_DEV|TEAM_C|TEAM_C_DEV> <step|-> <steps> <detail>
```

The step is the first failing one (`-` for a PASS and for a battle that could not be created), `steps` is how many the records hold, and the detail is the rest of the line (`-` for a PASS). UNSUPPORTED: the create (after the DEV fallback) or a step returned `DUOFORGE_E_UNSUPPORTED`. DIVERGENCE: any other create or step failure (the status name is in the detail), a tape not consumed exactly (used of length), or a difference of a comparator or of the check. Exit status 0 at the end of the input, 2 for input that is not the format (a bug of whoever wrote it: stderr names the line), 1 for any other failure. Line ends are LF on every platform (stdin and stdout are binary on Windows).

### `diff_driver.py`

```sh
python tools/reference/diff_driver.py replay --checkout <pinned checkout> --runner <duoforge_diff_runner> \
    [--workers N] [--only <glob>] [--out DIR] [--node <node>]
```

For each committed spec, in name order: the worker records it, and its trace must equal the committed trace (line ends as LF), else the battle is REF_ERROR ("trace differs from the committed trace"; a worker answer `ok: false` is REF_ERROR with its error). `trace_to_c` converts it: a `ConversionError` is ORACLE_GAP with its rule and detail, and a `KeyError`, `IndexError`, `ValueError` or `TypeError` out of `convert_battle` is ORACLE_GAP with the rule `untyped:<ExceptionType>` and the message and the function and line that raised it as detail; nothing else is caught. The records go to the runner, whose line gives PASS, DIVERGENCE or UNSUPPORTED, with its messages. Every battle is in exactly one of the five buckets.

`--workers` threads (default 4) each own one Node worker and one runner. A child that dies, does not answer in 300 seconds or answers out of protocol is a failure of the tool, not a bucket: the replay stops with status 3 and writes nothing. `--out` (default `build/diff/<UTC yyyymmdd-hhmmss>-replay`) gets `battles.jsonl`, one line per battle in name order (`name`, `bucket`, `rule`, `detail`, `step`, `steps`, `context`, `messages`; `null` where there is nothing; for ORACLE_GAP the message is the converter's), and `summary.json` with the counts per bucket and per rule, the Node version, the pin, the harness version, the git HEAD and the library version (from `duoforge.h`). Neither file depends on thread timing. Exit status 0 only if every battle is PASS, 1 if one is not, 2 for a bad command line, 3 for a failure of the tool. The driver only orchestrates: the rules are the converter's and the engine's.

`duoforge.reference.diff_replay` (label `reference`, needs Node and the checkout) runs it over all specs with 4 workers. `duoforge.reference.diff_driver` needs Python only: it feeds fake workers and runners to the bucket logic and the order of the output (the converter is real, the refusals come from edited copies of committed battles), runs the child clients against stand-in processes, tests the records writer, and, with the runner this build makes (`DUOFORGE_DIFF_RUNNER`, which CTest sets), takes every committed battle through the driver with a stand-in that answers the committed traces.
