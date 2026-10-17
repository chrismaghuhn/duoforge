# Restructure 5b-1: the generated Reg M-C tables move to `src/data/formats/reg-mc/` — proof

Clean `restructure/5-datagen` **`71118118`** (5a on main `8800b625`) against the clean branch head **`ddff8284`**, both
**dirty=false**. Same source and build paths in both phases, three profiles: Release with IPO (`-flto=auto
-ffat-lto-objects`), Release without IPO, and Debug, with `DUOFORGE_PYTHON` set (the Python tests run in both phases).
Machine as in [machine.json](../2026-10-16-restructure-damage/machine.json). Scripts: [proofs.py](proofs.py),
[summarize.py](summarize.py).

## Exact change

1. **Rename only** (`bac831c5`, `git mv`, 100 %): `closure_tables.{h,c}`, `extended_tables.{h,c}`, `pool_tables.{h,c}`
   and `format_tables.h` go from `src/data/` to `src/data/formats/reg-mc/`, the folder of the format they belong to
   (the OU lane's Gen 9 OU tables get `src/data/formats/<id>/` by the same scheme). `formulas.*` and
   `support_manifest.*` are hand-written engine files and stay.
2. **The paths that name them** (`ddff8284`): every `#include "data/<x>_tables.h"` of `src/`, `tests/`, `bench/` and
   `tools/difftest/`; the source list of `CMakeLists.txt`; the output paths of `gen_closure.py`, `gen_format.py` and
   the include lines they and `gen_move_handlers.py` write; the tools and tests that read the generated files
   (`trace_to_c.py`, `diff_random.py`, `pool_families.js`, `classify_unsupported.py`, the datagen, reference, replay,
   live and state-model tests); `.gitattributes`; the static-column allow-list; the living docs. Historical records
   (decisions, research, benchmark reports) keep the old paths.

The generated files are written again by their generators: each changes in exactly one line, its `#include` of another
generated header (`closure_tables.c`, `extended_tables.{h,c}`, `pool_tables.{h,c}`, `src/combat/generated/move_handlers.h`);
`closure_tables.h` and `format_tables.h` include none and are byte-equal. Ids, rows and the canonical table hashes are
unchanged (closure `86ca9d9f…`, extended `d16b1cef…`, pool `d6eee672…`); `tests/data/provenance.cmake` pins the new file
hashes.

## Gate: the library is byte-equal

| Profile | `libduoforge_shared.so` before | after | objects |
|---|---|---|---|
| IPO on | `d1307524…` | **same** | the LTO objects differ only in their IR, which records the header paths |
| IPO off | `cd754b95…` | **same** | every engine object byte-equal by name; only `bench/main.c.o` (the embedded commit) differs |
| Debug | `5765939d…` | `1487220e…` | debug info names the new paths |

## P1–P6

- **P1:** the sorted inventory is identical before and after (1585 names in both Release profiles, 1584 in Debug). Every
  test's properties are unchanged except the commands of the six `duoforge.provenance.<file>` checks, which name the
  moved files and pin their new hashes. Selected runs: 270 IPO and 264 no-IPO before and after, 0 failed, one skipped
  in both phases (`duoforge.python.evaluator_quick`, needs JAX; the hosted CI runs it).
- **P2:** 10 variants, 2784 executions, **1229 unique battles**, 24320 steps, 9124 stops; result bytes equal before and
  after, with and without IPO, canonical SHA `227e1d4645ed5ac289914e74c4f20be9bc009a3ef7a3ee547bb2ab9dac846b74`
  ([per-battle-digests.tsv](per-battle-digests.tsv)); the ten native reference reports are byte-equal in all three
  profiles.
- **P3, P4:** `duoforge.python.perft` and `duoforge.python.bench` pass in both profiles; the pins are unchanged.
- **P5:** `closure_regen`, `extended_regen`, `pool_regen`, `pool_families`, `format_regmc` and the provenance checks
  pass; the generated files differ only in the include line named above; context fingerprints equal in all profiles.
- **P6:** `include/` diff empty; 249 exports and the layouts byte-equal in all three profiles.

**Full suite, after the proof:** the proof's selection does not run `duoforge.data.format_pool_reg_mc` and
`format_pool_champions_ou`, and a first full run found them red: `docs/research/expansion/tools/build_legal_pool.js`
(which they run) read the headers by their old path. `b31f028f` points it and `tg_verify_teams.js` at the new folder
(two path lines each; the pinned validator makes both committed pools again, byte for byte). The whole CTest suite of
`b31f028f` then passes locally without IPO, **1585 of 1585**; 27 are skipped by this machine's configuration (the
`DUOFORGE_LEARN_PYTHON`/JAX tests and the German-locale check), which the hosted CI runs.

All counts and hashes: [proof-summary.json](proof-summary.json). The library is byte-equal, so behaviour cannot
change; no differential fuzz run is needed for this step.
