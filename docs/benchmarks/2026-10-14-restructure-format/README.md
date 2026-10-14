# Restructure 10: format definition — proof

The proof compares clean main **`5a417fe2c0ec8a325edb31a50bea149c36bba1d4`** (after #500) with the clean merged
branch head **`866b99f`** (`restructure/10-format`, main merged by `1d6d8c1`). Both **dirty=false**, same source
and build paths, profiles IPO on (Release, `-flto=auto -ffat-lto-objects`) and IPO off (Release).

Machine: cloud VM, Intel Xeon @ 2.10GHz, x86_64, 4 vCPUs, Linux-6.18.44, GCC 13.3.0 (Ubuntu 24.04), Python 3.13,
Node 22.22.0, Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc` ([machine.json](machine.json)).

## Exact change

- `data/formats/reg-mc.json` (new, hand-written): the Reg M-C facts, each with its line of the pinned Showdown
  checkout (format entry, Flat Rules, banlist, level, team size and pick, moves per set, Stat Points, IVs, clauses,
  Tera, VGC timer), the position count and the pool source by reference: `legal_pool.json`, its SHA-256 and how it
  is made. No copy of the pool.
- `tools/datagen/gen_format.py` (new): writes `src/data/format_tables.h` (`DFI_FORMAT_*`, with `_Static_assert`s
  against `DUOFORGE_ACTIVE_PER_SIDE`, `DUOFORGE_MAX_ROSTER`, `DUOFORGE_MAX_MOVE_SLOTS` and the Stat Point
  constants); `--check`; `--pin <checkout>` compares every quote with its line and reads the value back from it.
- `gen_closure.py --pool` and `pool_families.js` read the format id (and the pool path, checked by SHA-256) from
  the definition instead of a literal.
- Named constants: `DFI_LEVEL`, `DFI_CLOSURE_BROUGHT_COUNT`, `DFI_STAT_POINTS_MAX`, `DFI_STAT_POINTS_TOTAL_MAX`
  are the format constants; the include sits at the end of `context_internal.h` and `formulas.h`, and every
  define is changed in place, so no declaration moves. The Python `Context` defaults are named
  (`_layout.MAX_ROSTER`, `_FORMAT_BROUGHT_COUNT`).
- `docs/architecture/formats.md`: the facts, where code uses them, and what a second format must supply (singles
  and the public `DUOFORGE_ACTIVE_PER_SIDE`, Tera, hazard removal and Heavy-Duty Boots, team and set rules, pool,
  Gen 9 mechanics, timer).
- `.gitattributes` marks `format_tables.h` generated; `tools/datagen/README.md` documents the tool.

No behaviour change, no public header change, no new export, no heap, no generated table byte changed.

## P1–P6

- **P1:** 1455 → **1457** names in both profiles: exactly **+`duoforge.data.format_regmc`** (quick, no checkout)
  and **+`duoforge.data.format_pin`** (reference, with `DUOFORGE_PS_REFERENCE_DIR`); every other test's name,
  command, working directory, environment and labels are identical (registration backtraces omitted). Sorted
  inventory SHA `e17491af…ec37f` → `80d17ac1…44fae`. Selected runs (all quick tests, layouts, perft, bench, lint;
  IPO additionally all regeneration checks, `pool_families`, `tiebreak_ref` and the full Live suite): before
  **238/238 IPO, 232/232 no-IPO**; after **240/240 IPO, 233/233 no-IPO**; zero failures, zero skipped.
- **P2:** 10 variants, 2632 executions, **1153 unique battles**, 22618 steps and 8553 stops per profile; all
  before/after result bytes equal **with and without IPO**, canonical result SHA
  `2ac3c2985c7d513cfa28e366086185a5ff8624e824eca3bbbccb0edd8e400bb7`
  ([per-battle-digests.tsv](per-battle-digests.tsv)). Full Live suite passes.
- **P3:** perft passes in both profiles; `tests/perft/pins.json` SHA `90cb0e55…7c56` unchanged.
- **P4:** search bench passes in both profiles; `BENCH_SHA256`
  `8283eb8d5263073ab59fc27ca703fa08dac87d196d03557daf272560baeab798` unchanged.
- **P5:** `closure_regen`, `extended_regen`, `pool_regen`, `pool_families`, `format_pins` and the new `format_pin`
  pass at the pin; `git diff 5a417fe2 HEAD` of every generated table, `move_handlers.h`, the perft pins and the
  Python pins is empty (`pool_tables.h` `02fb6452…`, `pool_tables.c` `f70359a6…`). The only new generated file is
  `format_tables.h` `321b4495c032f7778946bcabaaabc40def0cde00d91cba2603d6e105043b91af`.
- **P6:** `git diff` of `include/` empty; **239 exports**, byte-equal in both profiles
  (`06fe17a5…601d`); layouts byte-equal (`4eb40481…1a04`).

The definition reproduces today's pool exactly (`duoforge.data.format_regmc`): after the 28 / 72 / 52 / 29 rows of
the content steps, the forme, move, item and ability rows of `pool_tables.c` are the pool source's ids in its own
order (each forme followed by its Mega formes, the 29 cosmetic copies left out, then the Blade row of G66), no
shorter step prefix gives the same rows, and the counts are **347 / 511 / 166 / 215**.

## Performance gate: byte-equal library

| Profile | `libduoforge_shared.so` main `5a417fe2` | merged head `866b99f` |
|---|---|---|
| IPO on | `e8b088cd75ad4730e32f721494ffe77b219aa308c43ff3fc3dbbaf044b270556` | `e8b088cd75ad4730e32f721494ffe77b219aa308c43ff3fc3dbbaf044b270556` |
| IPO off | `4bb8d6c789fbf0c41d7c9d0d05acb95067f5f2948c001cbb30976c0367be85d4` | `4bb8d6c789fbf0c41d7c9d0d05acb95067f5f2948c001cbb30976c0367be85d4` |

Objects (254 per profile, CMake's LTO probe objects excluded):

- **IPO off:** 253 byte-equal; 1 differs, `bench/main.c.o`, which embeds the commit (`cmake/bench_revision.cmake`).
- **IPO on:** 213 byte-equal; 41 differ: **40** are byte-equal after `objcopy -R .gnu.lto_* -R .gnu.debuglto_*`
  (their native code is equal; the fat LTO IR carries source locations, which the new include lines shift), and
  the 41st is `bench/main.c.o` (commit). The two static archives differ because they hold those objects.
- The bench binaries' disassembly is equal in both profiles.

[proof-summary.json](proof-summary.json) lists every differing object.

## Supplement: paired bench (not a gate)

Measured on the pre-merge pair, main `cd0700d9` vs branch `d91be67e` (same code change; both clean), 32 rounds of
the step-4 protocol, pinned to CPU 3 ([paired-bench-ipo.json](paired-bench-ipo.json),
[paired-bench-noipo.json](paired-bench-noipo.json), [control-ipo.json](control-ipo.json),
[control-noipo.json](control-noipo.json)). Direction: `100 × (after/before − 1)` of elapsed time, **positive =
slower**.

| Profile | Variant | Change | Same-binary control |
|---|---|---:|---:|
| IPO on | plain | +2.37 % | +1.19 % |
| IPO on | events | −1.75 % | −4.11 % |
| IPO off | plain | +1.08 % | −0.61 % |
| IPO off | events | −0.59 % | +1.41 % |

This VM is noisy: single rounds of the identical-binary control range from 0.87 to 1.15, and its medians move up
to 4 %. The numbers are within that noise; the native code is equal (above).

## Files

[proofs.py](proofs.py) (P1–P6, objects; `REPO`, `OUT`, `PHASE`), [summarize.py](summarize.py),
[matched-bench.py](matched-bench.py), [proof-summary.json](proof-summary.json),
[test-inventory.txt](test-inventory.txt), [per-battle-digests.tsv](per-battle-digests.tsv). Only counts and hashes
are retained; no state, request, event or replay payload.
