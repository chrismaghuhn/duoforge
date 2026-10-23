# Restructure 5c: definition files for the shared number spaces — proof

Clean main **`7ef33a66`** (#642) against the clean branch head **`04335969`**, both **dirty=false**. Same source and build
paths in both phases, three profiles: Release with IPO (`-flto=auto -ffat-lto-objects`), Release without IPO, and Debug,
configured with `DUOFORGE_PYTHON`, `DUOFORGE_LEARN_PYTHON`, `DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE`. The before
phase is the one of the 5b-1 proof on the same commit, worktree and build directories
([2026-10-17-restructure-formats-dir](../2026-10-17-restructure-formats-dir/README.md)). Machine: [machine.json](machine.json)
(the owner's PC). Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py) (those of 5b-1, with no test change allowed).

## What changes

Plan item "numbers from one definition" (step 5) for the three headers that hold the shared number spaces:

| Space | Definition file | Header | Guards |
|---|---|---|---|
| draw sites `DFI_SITE_*` (28 sites, free 27-31) | `src/rng/draw_sites.def` | `src/rng/draw.h` | each id equal to its line and below `DFI_SITE_COUNT`; `dfi_site_name` made from the lines (a duplicate id is a duplicate case) |
| residual kinds `DFI_RES_*` (21 kinds) | `src/combat/residual_kinds.def` | `src/combat/residual_order.h` | each number equal to its line; `dfi_res_kind_name` made from the lines |
| volatile bits `DFI_VOL_*` (8 bits) | `src/state/volatile_flags.def` | `src/state/battle_internal.h` | each bit equal to its line; the bits pairwise disjoint (sum = OR over the lines) |
| position flags `DFI_POSFLAG_*` (7 fields) | `src/state/position_flags.def` | `src/state/battle_internal.h` | each mask equal to its line; disjoint; together `DFI_POSFLAG_VALID_MASK` |

- **Format of the definition files.** Each is an X-macro file, one line per member, `MACRO(NAME, value[, "name"])`. It has no include guard. The header includes it with its own macro definition, once for every guard it builds.
- **The headers keep their `#define` constants.** The tokens and types are the same, so every expression that uses them compiles to the same code. An `enum` would make the constants `int`, and with `-Wsign-conversion` that changes warnings and possibly code.
- **What the definition file is.** It is the frozen record: each line's value is checked against the constant at build time (`_Static_assert`).
- **Two places by design.** A renumbering needs both lines changed and shows in review. A new member is two lines: its `#define` and its line in the `.def` file.

- `cmake/checks/lint_sources.cmake`: the site-case rule becomes a rule for all four spaces. Every `#define` of a space must have its line in the definition file, except the named constants that are not members (`DFI_SITE_COUNT`; `DFI_RES_NO_ORDER` and the model bounds; `DFI_VOL_FLAGS_MAX`; the Dragon Cheer shift and max and `DFI_POSFLAG_VALID_MASK`).
- `tools/reference/tests/test_trace_to_c.py`: the converter's `SITES` must be exactly the lines of `draw_sites.def`.
- Not in this step: `turn.c`, the generated Python layouts (`_state_layout.py` is made by the C dump and is unchanged), the HS number register.

**Mutants.** Each of these was compiled with clang `-fsyntax-only`, one at a time:
- A site id changed in the `.def` file, or in the header alone: `static assertion failed … DFI_SITE_DRAG keeps its id in draw_sites.def`.
- A site id above the count: the same assertion fails.
- A residual kind renumbered: its assertion fails.
- A volatile bit changed, in the header or in the `.def` file: its assertion fails.
- A position flag changed: its assertion fails.
- Two sites given one id in both files: `duplicate case value '22'`.
- Two volatile bits sharing a bit in both files: the disjointness assertion fails.
- A `#define DFI_POSFLAG_HURT` without its `.def` line: the lint reports `number-space (DFI_POSFLAG_HURT has no line in src/state/position_flags.def)`.

## Gate: the library is byte-equal

| Profile | `libduoforge_shared.so` before | after | objects |
|---|---|---|---|
| IPO on | `6c58d4f9…` | **same** | the LTO objects differ only in their IR (line numbers of the headers) |
| IPO off | `2a239e54…` | **same** | every engine object byte-equal by name; besides `bench/main.c.o` (the embedded commit) only the four `test_residual_order.c` objects differ (their checks record source lines) |
| Debug | `f7cf7a28…` | ``ceee034f…`` | debug info has the new line numbers |

## P1–P6

- **P1:** the sorted inventory is identical before and after (1599 names in all three profiles), and every test's
  properties are equal (no command change). Selected runs: before 272 IPO / 266 no-IPO, after 273 / 268 (the selection adds
  `duoforge.reference.converter_api`, which gains the `SITES` case, and the live tests); all pass after, and before only
  `duoforge.python.book` failed (stale worktree entries, see the 5b-1 proof; pruned since).
- **Full suite of `04335969`**, locally without IPO, with Python, JAX on the CPU and the pinned checkout: 1599 tests,
  **1597 passed**, one skipped (`duoforge.lint.no_mutable_globals`, "library is not ELF" in this configuration), one failed:
  `duoforge.python.expert_teacher`, known red on this machine (#585, red on main). 91 Python tests ran, none skipped.
- **P2:** 10 variants, 2808 executions, 1241 unique battles, 24664 steps, 9229 stops; result bytes equal before and after,
  with and without IPO, canonical SHA `77dc5c4a6602dceb527cc82d8733ddbaa29850446a8156529cb029db5d12fce5`
  ([per-battle-digests.tsv](per-battle-digests.tsv)); the ten native reference reports byte-equal in all three profiles.
  The draw order is that of an identical library.
- **P3, P4:** `duoforge.python.perft` and `duoforge.python.bench` pass in both profiles; pins and `BENCH_SHA256` unchanged.
- **P5:** no generated file changes; the regen checks and context fingerprints are equal in all profiles.
- **P6:** `include/` diff empty; 249 exports and the layouts (`duoforge_layout_dump`, so also `_state_layout.py`'s values)
  byte-equal in all three profiles.

All counts and hashes: [proof-summary.json](proof-summary.json). The library is byte-equal, so behaviour cannot change; no
differential fuzz run is needed for this step.
