# Restructure 4: `dfi_run_move_body` in phases — proof

Clean main **`8800b625`** (with #629, `dfi_event_make` inline) against the clean branch head **`d3d853ca`**
(`restructure/4-move-body`), both **dirty=false**. Same source and build paths in both phases, three profiles: Release
with IPO (`-flto=auto -ffat-lto-objects`), Release without IPO, and Debug. Machine as in [machine.json](machine.json)
(cloud VM, Xeon @ 2.10GHz, 4 vCPU, GCC 13.3.0, Python 3.13, Node 22.22, Valgrind 3.22, Showdown `b2cb775b`).

**Gate (HS rule for phase cuts):** the cut is not byte-equal, so the gate is the total executed instructions of the
bench run (`tools/restructure/callgrind_gate.py`), at most +1.0 % per profile. Result: **+0.44 % with IPO, +0.26 %
without**, so the gate is met.

## Exact change

`dfi_run_move_body` (`src/combat/turn.c@8800b625:6395`, 2025 lines) keeps its prelude (its lines 3–9: the hit index,
the battle, side, user, position, member, `*ran`) and calls seven phases in its order. Every phase body is the old
function's lines ([move-body-audit.json](move-body-audit.json), made by [audit_move_body.py](audit_move_body.py); the
cut itself is [cut_move_body.py](cut_move_body.py)).

| Phase | Old lines (of the function) | New lines (`turn.c@d3d853ca`) | Returns passed on | Content |
|---|---|---|---:|---|
| `dfi_move_body_prepare` | 10–108 | 6440–6537 | 11 | the actor and its targets, getTarget, Stalwart, BeforeMove, Mega Sol |
| `dfi_move_body_announce` | 109–218 | 6566–6675 | 5 | the PP, ModifyMove, Stance Change, the move line |
| `dfi_move_body_try_move` | 219–404 | 6705–6890 | 5 | the redirections, Dragon Darts, Pressure, the charge turn, TryMove |
| `dfi_move_body_status_handlers` | 405–615 | 6913–7123 | 39 | the status moves with their own handler |
| `dfi_move_body_hit_steps` | 616–1028 | 7151–7562 | 22 | onTry, the accuracy modifiers, the hit steps, the status hit |
| `dfi_move_body_hit_loop` | 1029–1843 | 7595–8407 | 46 | the hit loop |
| `dfi_move_body_after_loop` | 1844–2024 | 8438–8618 | 0 | recoil, MoveFail, selfBoost, Life Orb (last phase) |

- **Returns passed on exactly.** In this function every `return` ends the move, including the returns that pass on a
  handler's status (`return dfi_run_helping_hand(…)`). So every `return X;` of phases 1 to 6 (128 of them) is
  `return dfi_move_body_stop(stop, X);`, which sets `*stop`. The caller then returns that value, as the one function
  returned it. Phase 7 is last and keeps its returns.
- **Data flow unchanged.** The 24 scalars that more than one phase uses live in `dfi_move_body_state` on the
  caller's stack. Each phase starts from them (`T x = c->x;`) and, at its normal end, writes back what a later phase
  reads (`c->x = x;`). The four arrays that cross phases (`targets`, `hit`, `hp_before`, `sub_struggle`) are the
  caller's locals and are passed in; their declaration lines move to the caller unchanged (old lines 41, 738, 1065,
  1075; no array is read before its old declaration point, and none is passed to `sizeof`).
- **Forced inlining.** The phases are `static DFI_ALWAYS_INLINE` (`src/core/inline.h`). No heap, no new symbol (P6).
- No rename, no other code changes, and the comments stay with their code.

## Gate: executed instructions (`tools/restructure/callgrind_gate.py`)

The workload is the tool's (`--battles 128 --repetitions 1 --warmup 0 --max-steps 128 --families step,events
--workers 1`), on the bench executables (statically linked). Groups are a source function with all its clones. Data:
[callgrind-gate.json](callgrind-gate.json).

| Profile | Total Ir main → branch | Ratio (gate ≤ 1.010) | `dfi_run_move_body` exclusive | `dfi_run_move_body` inclusive |
|---|---|---:|---|---|
| IPO on | 3 664 684 064 → 3 680 853 015 | **1.004412** (+0.44 %) | 143 040 355 → 144 980 180 (+1.36 %) | 630 794 265 → 646 961 840 |
| IPO off | 3 987 796 635 → 3 998 145 927 | **1.002595** (+0.26 %) | 145 027 735 → 144 494 870 (−0.37 %) | 657 762 970 → 668 112 255 |

**Where the delta is.** The function's own code changes little. The extra instructions are calls to small helpers
that the move body inlined before and now calls. Largest exclusive changes:

| Group | IPO on | IPO off |
|---|---:|---:|
| `dfi_holds` | +8 899 740 | +8 644 385 |
| `dfi_at` | +6 780 225 | +6 328 210 |
| `dfi_item_code` | −5 463 250 | −5 252 220 |
| `dfi_ability` | +1 152 660 | +1 119 210 |
| `dfi_run_move_body` | +1 939 825 | −532 865 |

`dfi_at`, `dfi_holds`, `dfi_item_code`, `dfi_has_type`, `dfi_alive` and a few others now exist as out-of-line copies
(see the stack table). GCC's inliner applies size limits per caller, and the cut changes how it accounts the one
very large body, so some small helpers stay calls. The same effect as with `dfi_event_make` (#629), here inside one
translation unit. Forcing these helpers inline would be its own small PR; this gate does not need it.

## Stack frames (`-fstack-usage`)

| Function | main `8800b625` | `d3d853ca` |
|---|---:|---:|
| `dfi_run_move_body` (IPO off: `.constprop`) | 736 | **720** (−16) |

New out-of-line helpers (both profiles): `dfi_alive`, `dfi_at`, `dfi_field_start_turns`, `dfi_holds`, `dfi_item_code`,
`dfi_last_move`, `dfi_move_of`, `dfi_piercing_drill_passes` 8 bytes each, `dfi_status_hit_end` 16, `dfi_has_type` 48,
`dfi_fail_still` 96; with IPO also `dfi_use_item` 32 (and `dfi_leaf_guard_sun` 24 → 32). Folded into their callers:
`dfi_status_updates` (16, IPO off) and `dfi_after_hit_updates` (16, IPO on). The full table is in
[proof-summary.json](proof-summary.json).

| | main | branch |
|---|---:|---:|
| `libduoforge_shared.so` `.text`, IPO on / off | 466 138 / 480 924 | 466 058 / 480 364 |
| `duoforge_bench` `.text`, IPO on / off | 382 875 / 445 484 | 385 019 / 444 716 |

## P1–P6 (head `d3d853ca`), all unchanged

- **P1:** 1585 names, identical in all three profiles, every test's properties unchanged. Selected runs 270/270 IPO,
  264/264 no-IPO before and after, 0 failed.
- **P2:** 10 variants, 2784 executions, **1229 unique battles**, 24320 steps, 9124 stops. Result bytes are equal
  before and after and with and without IPO, canonical SHA
  `227e1d4645ed5ac289914e74c4f20be9bc009a3ef7a3ee547bb2ab9dac846b74` ([per-battle-digests.tsv](per-battle-digests.tsv)).
  States, requests, event sequences and RNG use are the same. The ten native reference runners' reports are
  byte-equal in all three profiles.
- **P3:** perft passes in both profiles; `tests/perft/pins.json` unchanged.
- **P4:** search bench passes in both profiles; `BENCH_SHA256` `8283eb8d…b798` unchanged.
- **P5:** no generated byte changes; context fingerprints equal in all three profiles.
- **P6:** `include/` diff empty; **249 exports** byte-equal in all three profiles; layouts byte-equal.

## Differential fuzzing (head `d3d853ca`, IPO build)

`diff_replay` 1229/1229 PASS, `diff_random_smoke` 16/16 PASS, `diff_domain_smoke` 8/8 PASS.

## Libraries

| Profile | main `8800b625` | `d3d853ca` |
|---|---|---|
| IPO on | `d13075243fd4d7b2129956ce3cc1d5ef3782421bf255882d233224fe9b110395` | `6284138541a79f328d0d787d122da68309229246b62cafef0d0675e550abf8e4` |
| IPO off | `cd754b95be1a32565258123125fbcd811d24e90d99aafed1cc99267af819ea7d` | `890622db25666ca2352127775c5b81288ac87275c21dc0e7a6bb4c69f119cf15` |
| Debug | `5765939d…20df9` | `0ce1a35a…bc286` |

Only `turn.c.o` (both targets), `libduoforge.a`, the library and `bench/main.c.o` (the commit) differ.

## Files

[proofs.py](proofs.py), [cut_move_body.py](cut_move_body.py), [audit_move_body.py](audit_move_body.py) and
[move-body-audit.json](move-body-audit.json), [callgrind-gate.json](callgrind-gate.json) (made by
`tools/restructure/callgrind_gate.py`), [proof-summary.json](proof-summary.json) (stack usage of every function),
[test-inventory.txt](test-inventory.txt), [per-battle-digests.tsv](per-battle-digests.tsv).
