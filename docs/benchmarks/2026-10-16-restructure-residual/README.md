# Restructure 4: residual runner in phases — proof

Merged head proof: clean main **`001a492e`** (with the damage cut #615 and the content batches) against the clean
branch head **`708adff5`** (`restructure/4-residual`, main merged, never rebased), both **dirty=false**. Earlier full
proofs at `dc9ce14b`/`410a1995` and `cefc5f67`/`02233180` were equally clean. Same source and build paths in both
phases, three profiles: Release with IPO (`-flto=auto -ffat-lto-objects`), Release without IPO, and Debug. Machine as
in [machine.json](machine.json) (cloud VM, Xeon @ 2.10GHz, 4 vCPU, GCC 13.3.0, Python 3.13, Node 22.22,
Valgrind 3.22, Showdown `b2cb775b`).

**Gate (HS rule for phase cuts):** (1) a byte-equal cut with forced inlining; failing that, (2) the executed
instructions (callgrind) of the bench run, at most +1.0 % in total per profile, with the stack frames before and
after. The cut is **not byte-equal**, so (2) applies. Result: **+0.149 % with IPO, +0.072 % without**, so the gate
is met.

## Exact change

`dfi_residual_events_run` (`src/combat/turn.c@001a492e:9272`, 765 lines) keeps its prelude (the Speed update and the
no-order snapshot, its lines 3–23) and calls six phases in its order. Each phase body is the old function's lines,
unchanged except for the stop returns below ([residual-audit.json](residual-audit.json), made by
[audit_residual.py](audit_residual.py)).

| Phase | Old lines (of the function) | New lines (`turn.c@708adff5`) | Stop returns | Content |
|---|---|---|---:|---|
| `dfi_residual_collect` | 24–180 | 9286–9442 | 0 | the handlers, unsorted: the field, each side's conditions, each Pokemon's |
| `dfi_residual_order` | 181–226 (without 211) | 9453–9497 | 0 | the sort with its draws, the side conditions' tie draws |
| `dfi_residual_early` | 227–515 | 9509–9797 | 6 | the handlers of orders 1 to 25, in the sorted order |
| `dfi_residual_durations` | 516–621 | 9807–9912 | 4 | the silent counts, side conditions, Trick Room, Gravity, terrain |
| `dfi_residual_late` | 622–661 | 9920–9959 | 1 | Speed Boost and Moody (28), White Herb (29) |
| `dfi_residual_noorder` | 662–765 | 9967–10070 | 0 | the duration handlers without an order, in Speed order (last phase) |

- **Data flow unchanged.** The battle pointer, the list, its count, `early`, `sorted`, `herbs_from` and `first` are
  the old locals. The caller holds them and passes them in; `n`, `early`, `sorted` and `herbs_from` come back through
  pointers. `first` (old line 211) is declared in the caller with the same initialiser. Passing `b` in keeps the one
  load of the old function; a first try that reloaded `r->b` in each phase had 37 more instructions.
- **Early returns passed through exactly.** Every `return DUOFORGE_OK;` of phases 3 to 5 (all of them behind
  `if (r->ended)`) is `return dfi_residual_stop(stop);`, which sets `*stop` and returns `DUOFORGE_OK`. The caller then
  returns `st`, as the one function returned there. Phase 6 is last and keeps its returns. An `if (r->ended)` between
  phases would not be equivalent: `r->ended` is set in `dfi_process_faints`, which can run deep inside helpers.
- **Forced inlining.** The phases are `static DFI_ALWAYS_INLINE` (`src/core/inline.h` from the damage cut:
  `__forceinline` on MSVC, `inline __attribute__((always_inline))` on GCC and clang). No heap; no new symbol (P6).
- The comments of the old function stay in the phases. No rename and no other code changes.

## Gate: executed instructions (callgrind)

`valgrind --tool=callgrind` on the bench run of the paired bench (`--battles 1024 --repetitions 3 --warmup 2
--max-steps 128 --policy-seed 20261001 --battle-seed 7001 --families step,events`), one run per binary
(deterministic; the bench's record is equal before and after). What is measured is the bench binary itself
(`duoforge_bench`, statically linked; its sha256 is in [callgrind.json](callgrind.json)). The function's figure is the
sum of all its symbols (`dfi_residual_events_run*`: `.constprop.0`; `.constprop.0.cold` runs no instruction).
Scripts: [callgrind_gate.py](callgrind_gate.py), [callgrind_calls.py](callgrind_calls.py) (call counts,
[callgrind-calls.txt](callgrind-calls.txt)).

| Profile | Total Ir main → branch | Total Δ (gate ≤ +1.0 %) | Self Ir `dfi_residual_events_run*` main → branch | Function Δ | Δ outside the function |
|---|---|---|---|---|---|
| IPO on | 64 778 086 528 → 64 874 335 084 | +96 248 556 (**+0.149 %**) | 1 591 505 240 → 1 659 021 299 | +67 516 059 (+4.24 %) | +28 732 497 |
| IPO off | 70 915 244 364 → 70 966 132 819 | +50 888 455 (**+0.072 %**) | 1 605 148 246 → 1 656 036 733 | +50 888 487 (+3.17 %) | −32 |

### Why the function grows

- **IPO off (+3.17 %):** the calls are unchanged (`dfi_event_make` 652 613 times before and after). The difference is
  register allocation: the old function keeps `r` in `%r14`; after the cut it is held on the stack, so the `r->…`
  accesses in the loops reload it.
- **IPO on (+4.24 %), mostly calls:** `dfi_event_make` (`src/combat/events.c`, another translation unit) is inlined
  only by the LTO link, under its global growth limits. Before the cut it was inlined into `dfi_residual_events_run`
  (0 calls); after the cut it is not (333 307 calls). Across all callers the calls rise from 253 006 to 1 229 462. The
  link stops inlining it in other functions too, and that is the +28.7 million outside the function. The damage
  session found the same effect for its cut (tools PR #627). Forcing the inlining of `dfi_event_make` would be its own
  small PR; it is not needed for this gate.

## Stack frames (`-fstack-usage`)

| Function | main `001a492e` | `708adff5` |
|---|---:|---:|
| `dfi_residual_events_run` (constprop) | 3040 | **3056** (+16) |
| `dfi_residual_sort` | 608 | 608 |
| `dfi_turn_run` | 560 | 560 |

Bytes, the same with IPO off (the compile of `turn.c`) and on (the LTO link stage, `libduoforge_shared.so.ltrans*.su`).
The phases have no frame of their own: they are inlined.

## P1–P6 (merged head `708adff5`), all unchanged

- **P1:** 1582 names, identical in all three profiles, every test's properties unchanged. Selected runs 268/268 IPO,
  262/262 no-IPO before and after, 0 failed.
- **P2:** 10 variants, 2782 executions, **1228 unique battles**, 24314 steps, 9120 stops; result bytes equal before
  and after and with and without IPO, canonical SHA `54eed6aabb7212e01db7c860b37337a4bcab744f8ce53a942b1a22f5c3ee0427`
  ([per-battle-digests.tsv](per-battle-digests.tsv)). States, requests, event sequences and RNG use are the same. The
  ten native reference runners' reports are byte-equal in all three profiles. The full Live suite passes.
- **P3:** perft passes in both profiles; `tests/perft/pins.json` unchanged.
- **P4:** search bench passes in both profiles; `BENCH_SHA256` `8283eb8d…b798` unchanged.
- **P5:** no generated byte changes; the regeneration checks pass. Context fingerprints equal in all three profiles.
- **P6:** `include/` diff empty; **249 exports** byte-equal in all three profiles; layouts byte-equal.

## Differential fuzzing against Showdown (head `708adff5`, IPO build)

| Run | Battles | Result |
|---|---:|---|
| `duoforge.reference.diff_replay` | 1228 | 1228 PASS, 0 DIVERGENCE |
| `duoforge.reference.diff_random_smoke` (seed 2, three runs byte-identical) | 16 | 16 PASS |
| `duoforge.reference.diff_domain_smoke` (every request sampled, seed 6) | 8 | 8 PASS |

## Library and objects

| Profile | `libduoforge_shared.so` main `001a492e` | `708adff5` |
|---|---|---|
| IPO on | `9ea808a5328bd458f17dddc9260561e00160afea7aa1c6e6dc24c26bb8d03f73` | `e330fe66614e2fa9e2df9bc907e6fa254b7a57967f766370564c08ca58473ce6` |
| IPO off | `9ddceac9644c827682f8ee549e20f44baa505f9196cff7a366907198a742743d` | `ccf2e15558517b0e9f59b323ba5b720af0b9e2a5c9233bdb9bb858900ddd248a` |
| Debug | `9b65b8b9…ca85` | `d181d6cd…9148` |

Only `turn.c.o` (both targets), `libduoforge.a`, the library and `bench/main.c.o` (the commit) differ.

## Paired bench (reported, not a gate)

Same protocol as before (32 rounds, change and same-binary control, both IPO modes, CPU 3), pair `dc9ce14b` /
`410a1995` (the cut alone). Ratios are after/before time: **above 1 = slower**.

| Profile | Workload | Raw median (95 % CI) | Same-binary control (95 % CI) | Adjusted median (95 % CI) |
|---|---|---|---|---|
| IPO on | plain | 1.0095 (+0.95 %; 0.9834–1.0847) | 0.9911 (0.9360–1.0183) | 1.0227 (+2.27 %; 0.9792–1.0851) |
| IPO on | events | 0.9638 (−3.62 %; 0.9343–0.9783) | 0.9846 (0.9450–1.0378) | 0.9788 (−2.12 %; 0.8716–1.0234) |
| IPO off | plain | 1.0274 (+2.74 %; 0.9564–1.0654) | 1.0094 (0.9617–1.0525) | 1.0335 (+3.35 %; 0.9591–1.1169) |
| IPO off | events | 0.9629 (−3.71 %; 0.9456–1.0126) | 0.9987 (0.9409–1.0242) | 0.9808 (−1.92 %; 0.9399–1.0204) |

Every interval contains 1; the spread is that of the two earlier runs on instruction-identical binaries (forms and flow
pieces), so this VM cannot resolve changes of this size.

## Files

[proofs.py](proofs.py) (P1–P6, objects, fingerprints, native reports, three profiles), [audit_residual.py](audit_residual.py)
and [residual-audit.json](residual-audit.json), [callgrind_gate.py](callgrind_gate.py), [callgrind.json](callgrind.json),
[callgrind_calls.py](callgrind_calls.py) and [callgrind-calls.txt](callgrind-calls.txt), [paired_bench.py](paired_bench.py)
and `paired-bench-<mode>-<change|control>.json`, [proof-summary.json](proof-summary.json) (includes the stack usage),
[test-inventory.txt](test-inventory.txt), [per-battle-digests.tsv](per-battle-digests.tsv). Only counts, hashes and
timings are retained. The callgrind scripts give way to `tools/restructure/` from #627 once it is merged.
