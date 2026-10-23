# Restructure 5b-1: the generated Reg M-C tables move to `src/data/formats/reg-mc/` — proof

**Current proof (2026-10-23, after the merge of main):** clean main **`7ef33a66`** (#642) against the clean branch head
**`c60813fb`** (the merge `5ffecc06` of main into the branch, plus `proofs.py` reading its tools from the environment), both
**dirty=false**. Same source and build paths in both phases, three profiles: Release with IPO (`-flto=auto
-ffat-lto-objects`), Release without IPO, and Debug, configured with `DUOFORGE_PYTHON`, `DUOFORGE_LEARN_PYTHON`,
`DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE` (the Python and reference tests run in both phases). Machine:
[machine.json](machine.json) (the owner's PC). Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py). The first proof
(2026-10-17, on 5a `71118118`, a cloud VM) found the same; its numbers are in the git history of this folder.

The merge had one conflict, `tests/data/provenance.cmake` (the branch's path, the hash of the merged `pool_tables.c`); the
two test files main added with the old include path (`test_pool_a2a.c`, `test_pool_lockfam_sleep.c`) were pointed at the new
folder, and every generator writes the merged tables again byte for byte.

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
| IPO on | `6c58d4f9…` | **same** | the LTO objects differ only in their IR, which records the header paths |
| IPO off | `2a239e54…` | **same** | every engine object byte-equal by name; only `bench/main.c.o` (the embedded commit) differs |
| Debug | `f7cf7a28…` | `6175f5c8…` | debug info names the new paths |

## P1–P6

- **P1:** the sorted inventory is identical before and after (1599 names in all three profiles). Every test's properties
  are unchanged except the commands of the six `duoforge.provenance.<file>` checks, which name the moved files and pin their
  new hashes. Selected runs: 272 IPO and 266 no-IPO, before and after; in both phases and both profiles the same one fails,
  `duoforge.python.book` (`test_load_refuses_main_and_other_worktrees_before_reading` walks `git worktree list`, and on this
  machine that lists stale worktrees of other sessions under `/tmp`, which are outside the repository; it is red on main
  too and does not read the tables).
- **P2:** 10 variants, 2808 executions, **1241 unique battles**, 24664 steps, 9229 stops; result bytes equal before and
  after, with and without IPO, canonical SHA `77dc5c4a6602dceb527cc82d8733ddbaa29850446a8156529cb029db5d12fce5`
  ([per-battle-digests.tsv](per-battle-digests.tsv)); the ten native reference reports are byte-equal in all three
  profiles.
- **P3, P4:** `duoforge.python.perft` and `duoforge.python.bench` pass in both profiles; the pins are unchanged.
- **P5:** `closure_regen`, `extended_regen`, `pool_regen`, `pool_families` and the provenance checks pass; the generated
  files differ from main only in the include line named above; context fingerprints equal in all profiles.
- **P6:** `include/` diff empty; 249 exports and the layouts byte-equal in all three profiles.

**Full suite, after the proof:** the proof's selection does not run `duoforge.data.format_pool_reg_mc` and
`format_pool_champions_ou`, and a first full run found them red: `docs/research/expansion/tools/build_legal_pool.js`
(which they run) read the headers by their old path. `b31f028f` points it and `tg_verify_teams.js` at the new folder
(two path lines each; the pinned validator makes both committed pools again, byte for byte). The whole CTest suite of
`b31f028f` then passes locally without IPO, **1585 of 1585**; 27 are skipped by this machine's configuration (the
`DUOFORGE_LEARN_PYTHON`/JAX tests and the German-locale check), which the hosted CI runs.

**Full suite of `c60813fb` (2026-10-23), locally without IPO, with Python, JAX on the CPU and the pinned checkout:** 1599
tests, **1596 passed**, one skipped (`duoforge.lint.no_mutable_globals`, "library is not ELF" in this configuration), two
failed, neither of them about the tables: `duoforge.python.expert_teacher`, known red on this machine (#585, BLAS thread
count, red on main), and `duoforge.python.book`, the stale worktree listing above, which passes once the stale entries are
pruned. 91 Python tests ran (none skipped), 89 of them green.

All counts and hashes: [proof-summary.json](proof-summary.json). The library is byte-equal, so behaviour cannot
change; no differential fuzz run is needed for this step.
