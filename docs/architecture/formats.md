# Formats

DuoForge plays one format today: **Reg M-C** (`[Gen 9 Champions] VGC 2026 Reg M-C`, Showdown id
`gen9championsvgc2026regmc`, pin `b2cb775b`). Restructure step 10 moved its facts into one definition file so that a
second format (Gen 9 OU, issue #413) has a place to start. Nothing here generalises a rule: the engine still plays
exactly Reg M-C, and every fact below keeps today's value.

## The definition

`data/formats/reg-mc.json` (hand-written) holds:

- the facts of the format, each with the line of the pinned Showdown checkout it comes from: name, mod, game type,
  ruleset, Flat Rules, banlist, level, team size and pick, moves per set, Stat Point limits, IVs, the clauses, Tera
  and the VGC timer;
- `engine.active_per_side`: the position count of the game type;
- the pool source: `data/formats/pools/reg-mc.json` with its SHA-256, made by
  `docs/research/expansion/tools/build_legal_pool.js` (the pinned `TeamValidator` for the format). The pool is a
  reference, never a copy: the ids and their order live in that one file.

Readers:

| Reader | What it reads |
|---|---|
| `tools/datagen/gen_format.py` | writes `src/data/formats/reg-mc/format_tables.h` (`DFI_FORMAT_*`, with `_Static_assert`s against the public constants of the same value); `--check` compares; `--pin <checkout>` compares every quote with its pinned line and reads the value back |
| `tools/datagen/gen_closure.py --pool` | the Showdown format id and the pool source (`load_format`: SHA-256, commit and format id of the pool's meta) |
| `tools/datagen/pool_families.js` | the Showdown format id for the pinned validator |
| C engine | `src/data/formats/reg-mc/format_tables.h` through `formulas.h` (Stat Points), `context_internal.h` (brought count) and `turn.c` (level) |

Checks: `duoforge.data.format_regmc` (quick, no checkout: the definition, the generated header, the pool tables
reproduced exactly from the definition, the named constants in code) and `duoforge.data.format_pin` (with
`DUOFORGE_PS_REFERENCE_DIR`: every quote against the pin).

## The format facts and where they are used

| Fact | Reg M-C | In code |
|---|---|---|
| Game type, positions per side | doubles, 2 | `DUOFORGE_ACTIVE_PER_SIDE` (public, ABI: array bounds of requests, commands, views and the state) = `DFI_FORMAT_ACTIVE_PER_SIDE` |
| Team size | 6 | `DUOFORGE_MAX_ROSTER` (public, ABI) = `DFI_FORMAT_TEAM_SIZE`; Python `Context` default `_layout.MAX_ROSTER` |
| Picked (brought) | 4 | `DFI_CLOSURE_BROUGHT_COUNT` = `DFI_FORMAT_BROUGHT_COUNT` (the certified profile of decision 0010); Python `_FORMAT_BROUGHT_COUNT` |
| Level | 50 | `DFI_LEVEL` = `DFI_FORMAT_LEVEL` (base damage, confusion self-hit, OHKO, Night Shade); the stat formula has no level term |
| Moves per set | 4 | `DUOFORGE_MAX_MOVE_SLOTS` (public, ABI) = `DFI_FORMAT_MOVES_PER_SET` |
| Stat Points | 32 per stat, 66 in all | `DUOFORGE_STAT_POINTS_MAX`, `_TOTAL_MAX` (public) = `DFI_STAT_POINTS_MAX`, `_TOTAL_MAX` = `DFI_FORMAT_STAT_POINTS_*` |
| IVs | all 31 | not read: the Champions stat formula has no IV term |
| Species Clause, Item Clause = 1 | yes | `dfi_closure_side_clauses_hold` (`src/state/closure_member.c`) |
| Nickname Clause, Open Team Sheets | yes | not read by the engine |
| Tera | disabled | no state; Tera Blast and Tera Starstorm are not in the pool |
| Timer | VGC: 420 s, grace 90, 0 per turn, 55 max per turn, 90 first turn, auto choose, DC bank | not read by the engine; the live client waits on the server's timer lines |
| Pool | 347 formes, 511 moves, 166 items, 215 abilities | `src/data/formats/reg-mc/pool_tables.{h,c}` from `gen_closure.py --pool` |

Champions mechanics are not format facts: the stat formula (`+75` / `+20`, nature x1.1 / x0.9), the PP cap of 20,
Mega Evolution and the Champions move and ability overrides belong to the mod and stay where they are.

Consumers outside the engine name the Showdown format id as a protocol string (live client, arena, replay import,
reference tools under `tools/reference/` and `docs/research/`). They are not switched by the definition.

## What a second format has to supply

A second format is a second definition file plus whatever the engine does not have yet. For **Gen 9 OU** (#413):

1. **Singles.** One position per side. `DUOFORGE_ACTIVE_PER_SIDE` is a public constant and part of the ABI (arrays
   in requests, commands, views, the encoder and the state); target classes, spread damage, redirection and ally
   effects assume two positions. This is a public API and ABI change and needs its own decision.
2. **Tera.** Terastallization (choice, type change, STAB rules, Tera Blast, Stellar) has no state and no rule; Reg
   M-C disables it (`facts.terastallization`).
3. **Hazards as an OU format needs them.** Stealth Rock, Spikes, Toxic Spikes and Sticky Web are modelled (step G37)
   and Stone Axe and Ceaseless Edge set them, but removal is not: Defog, Rapid Spin, Court Change, Mortal Spin and
   Tidy Up are UNMODELED in the pool, and Heavy-Duty Boots is not in the pool. With six on the field and frequent
   switches, OU cannot be played without them.
4. **Team and set rules.** 6 of 6 without a pick, level 100, EVs (510 / 252) and IVs instead of Stat Points, and the
   standard clauses (Sleep Moves, OHKO, Evasion, Species; no Item Clause). The stat formula then has level and IV
   terms (Champions has none).
5. **The pool.** A pool source for the format from the pinned validator, and the generator taking the format as an
   input (`gen_closure.py --format`, restructure step 5); a far larger pool may exceed today's id widths
   (`check_bounds`).
6. **Gen 9 mechanics where Champions differs.** Every Champions override (moves, abilities, items, conditions) is a
   mod fact; a Gen 9 format reads the unmodded entries and each difference needs its handler and its proof.
7. **Timer and preview.** Team preview without a pick, and the format's own timer values.
