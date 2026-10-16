# Restructure 4: `dfi_event_make` inlined into every caller — proof

Clean main **`19e8d47a`** (with the residual cut #621 and the tools of #627) against the clean branch head
**`d5e65136`** (`restructure/4-event-make`, main merged, never rebased), both **dirty=false**. Same source and build
paths in both phases, three profiles: Release with IPO (`-flto=auto -ffat-lto-objects`), Release without IPO, and
Debug. Machine as in [machine.json](machine.json) (cloud VM, Xeon @ 2.10GHz, 4 vCPU, GCC 13.3.0, Python 3.13,
Node 22.22, Valgrind 3.22, Showdown `b2cb775b`).

## Why

After the phase cuts of step 4, the LTO link stopped inlining `dfi_event_make` (`src/combat/events.c`, another
translation unit) into `dfi_residual_events_run` and other callers. In the bench run of the residual proof, the calls
rose from 253 006 to 1 229 462 (#621). This change makes the inlining independent of the link's growth limits.

## Exact change

1. **`c7cff5f7`:** `dfi_event_make` becomes an inline definition in `src/combat/events.h`, forced into every caller with
   `DFI_ALWAYS_INLINE` (`src/core/inline.h`). `events.c` keeps only `extern duoforge_event dfi_event_make(uint32_t,
   uint32_t);`. By C99 inline, that declaration makes it the translation unit with the one external definition, so the
   symbol and the library's exports stay. The body is unchanged.
2. **`7226f24a`:** new test `duoforge.engine.shared_export_event_make` (`tests/header_check/shared_export_event_make.c`).
   It links `duoforge_shared` alone and calls `dfi_event_make` through the import library, without the inline header,
   then checks the record field by field. A missing export or a second definition fails the link (LNK2019 / LNK2005 on
   MSVC, an undefined or multiple definition elsewhere). It is labelled `quick engine ci-no-skip`, so it runs and may
   not be skipped on every toolchain; on Windows the DLL's directory goes on `PATH`. Counter-check: without the
   `extern` declaration in `events.c`, the link fails with `undefined reference to 'dfi_event_make'`.

## Executed instructions (callgrind, `tools/restructure/callgrind_gate.py` from #627)

The workload is the tool's own (`--battles 128 --repetitions 1 --warmup 0 --max-steps 128 --families step,events
--workers 1`), on the bench executables themselves (statically linked). Groups are a source function with all its
clones. Data: [callgrind-gate.json](callgrind-gate.json).

| Profile | Total Ir main → branch | Ratio (gate ≤ 1.010) | `dfi_event_make` exclusive Ir | `dfi_residual_events_run` exclusive | `dfi_get_damage` exclusive |
|---|---|---:|---|---|---|
| IPO on | 3 671 455 937 → 3 664 684 030 | **0.998156** (−0.18 %) | 179 025 → **0** | 80 285 200 → 80 292 105 | 88 453 170 → 88 431 705 |
| IPO off | 3 995 691 933 → 3 987 796 602 | **0.998024** (−0.20 %) | 9 668 610 → **0** | 80 104 440 → 80 181 560 | 86 964 055 → 87 902 785 |

- **No call to `dfi_event_make` remains**, with or without IPO (`objdump`: 0 calls in the bench binary and in the
  library).
- **Without IPO** the saving is essentially the calls: `dfi_event_make`'s 9.67 million Ir go away, and the total falls
  by 7.9 million.
- **With IPO** the inlining also moves other LTO decisions. Largest exclusive changes: `dfi_turn_run` −82.2 million,
  `dfi_battle_step_observed` +48.2 million, `dfi_queue_choices` +17.6 million, `dfi_finish_turn` +12.9 million (these
  are inlining moves between callers, not new work). The net is −6.8 million.
- The gate's code diff of the measured binaries lists the groups whose code changed. They are every caller of the
  inlined function, and with IPO also the callers whose inlining moved.

## Library size and stack frames

| | main `19e8d47a` | `d5e65136` |
|---|---:|---:|
| `libduoforge_shared.so` IPO on: file / `.text` | 708 728 / 463 418 | 708 880 / 465 658 (+2 240) |
| `libduoforge_shared.so` IPO off: file / `.text` | 809 200 / 474 748 | 813 440 / 480 444 (+5 696) |
| `duoforge_bench` IPO on: `.text` | 385 691 | 382 379 (−3 312) |
| `duoforge_bench` IPO off: `.text` | 440 044 | 445 004 (+4 960) |

`-fstack-usage` (IPO off: the compiles of the library sources; IPO on: the LTO link stage). 27 (IPO off) and 30
(IPO on) functions change their frame: callers that now build the record in their own frame grow by 16 to 48 bytes,
and a few shrink. The largest are below; all of them are in [proof-summary.json](proof-summary.json).

| Function | IPO off main → branch | IPO on main → branch |
|---|---|---|
| `dfi_battle_step_observed` | 11 968 → 12 000 | 11 984 → 12 016 |
| `dfi_residual_events_run` | 3 056 → 3 040 | 3 056 → 3 056 |
| `dfi_run_move_body` | 704 → 736 | 752 → 736 |
| `dfi_turn_run` | 560 → 592 | 560 → 592 |
| `dfi_get_damage` | 400 → 432 | 400 → 432 |

## P1–P6

- **P1:** 1583 → **1584** names in all three profiles: exactly **+`duoforge.engine.shared_export_event_make`**; every
  other test's properties unchanged. Selected runs before 269/269 IPO, 263/263 no-IPO; after **270/270 IPO, 264/264
  no-IPO** (the new quick test), 0 failed.
- **P2:** 10 variants, 2782 executions, **1228 unique battles**, 24314 steps, 9120 stops. Result bytes are equal
  before and after and with and without IPO, canonical SHA
  `54eed6aabb7212e01db7c860b37337a4bcab744f8ce53a942b1a22f5c3ee0427` ([per-battle-digests.tsv](per-battle-digests.tsv)).
  The ten native reference runners' reports are byte-equal in all three profiles.
- **P3:** perft passes in both profiles; `tests/perft/pins.json` unchanged.
- **P4:** search bench passes in both profiles; `BENCH_SHA256` `8283eb8d…b798` unchanged.
- **P5:** no generated byte changes; context fingerprints equal in all three profiles.
- **P6:** `include/` diff empty; **249 exports** byte-equal in all three profiles (`75a403d6…7ce2`), `dfi_event_make`
  among them; layouts byte-equal.

## Differential fuzzing (head `d5e65136`, IPO build)

`diff_replay` 1228/1228 PASS, `diff_random_smoke` 16/16 PASS, `diff_domain_smoke` 8/8 PASS.

## Libraries

| Profile | main `19e8d47a` | `d5e65136` |
|---|---|---|
| IPO on | `5b0ee2d782ca6f3748dce945b0a26e5b808e1c9b8440d1fb02c31de4880d6bb4` | `d382cadb65a0985dcc7d0cb2033baca8516d591a1a9b2fdafaa6e331346debcd` |
| IPO off | `c882beef5da6da40078bdc912563b62c7d8d5bea7958e739da312d60a6c85de2` | `468226f99e180596331635bd8295812689dc766c57df6c76ed43df023a741dcb` |
| Debug | `734623ba…0bbc` | `34bebf81…1885` |

## Files

[proofs.py](proofs.py), [callgrind-gate.json](callgrind-gate.json) (made by `tools/restructure/callgrind_gate.py`),
[proof-summary.json](proof-summary.json) (stack usage of every function), [test-inventory.txt](test-inventory.txt),
[per-battle-digests.tsv](per-battle-digests.tsv). Only counts, hashes and sizes are retained.
