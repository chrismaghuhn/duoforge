# Restructure 4: residual runner in phases — proof

Merged head proof: clean main **`cefc5f67`** against the clean branch head **`02233180`** (`restructure/4-residual`,
main merged, never rebased), both **dirty=false**. A first full proof at `dc9ce14b` against `410a1995` (the cut alone)
gave the same results and stack frames, and callgrind ratios of 1.000798 and 1.000718 as well. Same source and build paths in both phases,
three profiles: Release with IPO (`-flto=auto -ffat-lto-objects`), Release without IPO, and Debug. Machine as in
[machine.json](machine.json) (cloud VM, Xeon @ 2.10GHz, 4 vCPU, GCC 13.3.0, Python 3.13, Node 22.22, Valgrind 3.22,
Showdown `b2cb775b`).

**Gate (HS rule for phase cuts):** (1) a byte-equal cut with forced inlining; failing that, (2) the executed
instructions (callgrind) of the bench run, at most +1.0 % per profile, with the stack frames before and after.
The cut is **not byte-equal**, so (2) applies: **+0.080 % with IPO, +0.072 % without**.

## Exact change

`dfi_residual_events_run` (`src/combat/turn.c@cefc5f67:9819`, 765 lines) keeps its prelude (the Speed update and
the no-order snapshot, its lines 3–23) and calls six phases in its order. Each phase body is the old function's lines,
unchanged except for the stop returns below ([residual-audit.json](residual-audit.json), made by
[audit_residual.py](audit_residual.py)).

| Phase | Old lines (of the function) | New lines (`turn.c@02233180`) | Stop returns | Content |
|---|---|---|---:|---|
| `dfi_residual_collect` | 24–180 | 9833–9989 | 0 | the handlers, unsorted: the field, each side's conditions, each Pokemon's |
| `dfi_residual_order` | 181–226 (without 211) | 10000–10044 | 0 | the sort with its draws, the side conditions' tie draws |
| `dfi_residual_early` | 227–515 | 10056–10344 | 6 | the handlers of orders 1 to 25, in the sorted order |
| `dfi_residual_durations` | 516–621 | 10354–10459 | 4 | the silent counts, side conditions, Trick Room, Gravity, terrain |
| `dfi_residual_late` | 622–661 | 10467–10506 | 1 | Speed Boost and Moody (28), White Herb (29) |
| `dfi_residual_noorder` | 662–765 | 10514–10617 | 0 | the duration handlers without an order, in Speed order (last phase) |

- **Data flow unchanged.** The battle pointer, the list, its count, `early`, `sorted`, `herbs_from` and `first` are
  the old locals. The caller holds them and passes them in; `n`, `early`, `sorted` and `herbs_from` come back through
  pointers. `first` (old line 211) is declared in the caller with the same initialiser. Passing `b` in, rather than
  reloading `r->b` in each phase, keeps the one load of the old function (a first try that reloaded it had 37 more
  instructions statically).
- **Early returns passed through exactly.** Every `return DUOFORGE_OK;` of phases 3 to 5 (all of them behind
  `if (r->ended)`) is `return dfi_residual_stop(stop);`, which sets `*stop` and returns `DUOFORGE_OK`. The caller then
  returns `st`, as the one function returned there. Phase 6 is last and keeps its returns. An `if (r->ended)` between
  phases would not be equivalent: `r->ended` is set in `dfi_process_faints`, which can run deep inside helpers.
- **Forced inlining.** The phases are `static DFI_FORCE_INLINE` (new `src/core/force_inline.h`: `__forceinline` on
  MSVC, `inline __attribute__((always_inline))` on GCC and clang). No heap; no new symbol (P6).
- The comments of the old function stay in the phases. No rename and no other code changes.

## Why not byte-equal

Without IPO, the only function whose instructions differ (addresses normalised) is `dfi_residual_events_run`:
statically 4257 → 4254 instructions. The difference is register allocation and scheduling: `r` is held on the stack
instead of in `%r14`, and other registers are chosen. No logic is added or lost.

## Gate: executed instructions (callgrind)

`valgrind --tool=callgrind` on the bench run of the paired bench (`--battles 1024 --repetitions 3 --warmup 2
--max-steps 128 --policy-seed 20261001 --battle-seed 7001 --families step,events`), one run per binary (deterministic;
the bench's record is equal before and after). Script: [callgrind_gate.py](callgrind_gate.py); data:
[callgrind.json](callgrind.json).

| Profile | Total Ir main `cefc5f67` | Total Ir `02233180` | after / before | Gate (≤ 1.010) |
|---|---:|---:|---:|---|
| IPO on | 64 721 943 699 | 64 773 597 644 | **1.000798** (+0.080 %) | met |
| IPO off | 70 831 261 343 | 70 882 149 781 | **1.000718** (+0.072 %) | met |

Inclusive Ir of `dfi_residual_events_run` (the cut function with its callees): IPO on 2 791 250 631 → 2 858 968 073
(+2.43 %), IPO off 2 856 750 585 → 2 907 639 072 (+1.78 %). Its callees are unchanged (`dfi_residual_sort`
253 096 025 = 253 096 025 with IPO), so the extra work is in the function's own code: the stack-held `r` and the
register choices above. The residual is about 4 % of the run, so the total moves by +0.08 %.

## Stack frames (`-fstack-usage`)

| Function | main `cefc5f67` | `02233180` |
|---|---:|---:|
| `dfi_residual_events_run` (constprop) | 3040 | **3056** (+16) |
| `dfi_residual_sort` | 608 | 608 |
| `dfi_turn_run` | 560 | 560 |

Bytes, the same with IPO off (the compile of `turn.c`) and on (the LTO link stage, `libduoforge_shared.so.ltrans*.su`).
The phases have no frame of their own: they are inlined.

## P1–P6 (merged head `02233180`), all unchanged

- **P1:** 1560 names, identical in all three profiles, every test's properties unchanged. Selected runs 266/266 IPO,
  260/260 no-IPO before and after, 0 failed.
- **P2:** 10 variants, 2742 executions, **1208 unique battles**, 23788 steps, 8952 stops; result bytes equal before
  and after and with and without IPO, canonical SHA `a5af789871ac9164f2c6240db800a3e87b1852ed9c7e5391516653e14bd3c067`
  ([per-battle-digests.tsv](per-battle-digests.tsv)): states, requests, event sequences and RNG use are the same. The
  ten native reference runners' reports are byte-equal in all three profiles. Full Live suite passes.
- **P3:** perft passes in both profiles; `tests/perft/pins.json` unchanged.
- **P4:** search bench passes in both profiles; `BENCH_SHA256` `8283eb8d…b798` unchanged.
- **P5:** no generated byte changes; the regeneration checks pass. Context fingerprints equal in all three profiles.
- **P6:** `include/` diff empty; **249 exports** byte-equal in all three profiles (`75a403d6…7ce2`); layouts byte-equal
  (`37b8f5e1…8774`).

## Differential fuzzing against Showdown (head `02233180`, IPO build)

| Run | Battles | Result |
|---|---:|---|
| `duoforge.reference.diff_replay` | 1208 | 1208 PASS, 0 DIVERGENCE |
| `duoforge.reference.diff_random_smoke` (seed 2, three runs byte-identical) | 16 | 16 PASS |
| `duoforge.reference.diff_domain_smoke` (every request sampled, seed 6) | 8 | 8 PASS |

## Library and objects

| Profile | `libduoforge_shared.so` main `cefc5f67` | `02233180` |
|---|---|---|
| IPO on | `d9f498062cca1d637b242ea7c78feed6978c72b62baed1f8b21ce6fa3df68ae6` | `8999f0f2b6d6224485b3896bfcbb99a2ea7cfe80abe9b90d823a8b2d52f88a1e` |
| IPO off | `1da1fdc12d0eee8cd5e90736048190cd49558d06e71a89106fc0ef7cc0d9b423` | `1761af323e98c9e4f9e21be07f7852cec902b4f2ec6c454437d372bbf94f96a0` |
| Debug | `33aa5bdd…104c` | `5080030d…9f69b` |

The objects that differ are only `turn.c.o` (both targets), `libduoforge.a`, the library and `bench/main.c.o` (the
commit).

## Paired bench (reported, not a gate)

Same protocol as before (32 rounds, change and same-binary control, both IPO modes, CPU 3). Pair `dc9ce14b` /
`410a1995` (the cut alone; the merge adds no code to the residual runner). Ratios are after/before time: **above 1 =
slower**.

| Profile | Workload | Raw median (95 % CI) | Same-binary control (95 % CI) | Adjusted median (95 % CI) |
|---|---|---|---|---|
| IPO on | plain | 1.0095 (+0.95 %; 0.9834–1.0847) | 0.9911 (0.9360–1.0183) | 1.0227 (+2.27 %; 0.9792–1.0851) |
| IPO on | events | 0.9638 (−3.62 %; 0.9343–0.9783) | 0.9846 (0.9450–1.0378) | 0.9788 (−2.12 %; 0.8716–1.0234) |
| IPO off | plain | 1.0274 (+2.74 %; 0.9564–1.0654) | 1.0094 (0.9617–1.0525) | 1.0335 (+3.35 %; 0.9591–1.1169) |
| IPO off | events | 0.9629 (−3.71 %; 0.9456–1.0126) | 0.9987 (0.9409–1.0242) | 0.9808 (−1.92 %; 0.9399–1.0204) |

Every interval contains 1; the spread is that of the two earlier runs on instruction-identical binaries (forms and flow
pieces), so this VM cannot resolve a change of +0.08 %.

## Files

[proofs.py](proofs.py) (P1–P6, objects, fingerprints, native reports, three profiles), [audit_residual.py](audit_residual.py)
and [residual-audit.json](residual-audit.json), [callgrind_gate.py](callgrind_gate.py) and [callgrind.json](callgrind.json),
[paired_bench.py](paired_bench.py) and `paired-bench-<mode>-<change|control>.json`,
[proof-summary.json](proof-summary.json) (includes the stack usage), [test-inventory.txt](test-inventory.txt),
[per-battle-digests.tsv](per-battle-digests.tsv). Only counts, hashes and timings are retained.
