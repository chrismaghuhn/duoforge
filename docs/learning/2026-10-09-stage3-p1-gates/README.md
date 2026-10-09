# Stage 3 P1: rescue calibration and evaluation smoke (2026-10-09)

Two pre-pilot gates of the [P1 plan](../../superpowers/plans/2026-10-08-stage3-p1-pilot.md) (C2 step 6, C5 evaluation smoke), run with the owner's go-ahead on a free machine. Code on main `ccdbe467`. Private fixtures, ledgers and records stay outside the repository; this report holds aggregates and fingerprints only.

## C2 step 6: tail calibration of the work budget

The five exact-rescue records of the honest arena (#236) were extracted read-only into the `expert_calibrate` fixture format. `load_rescue_fixture_set` accepted all five (count, SHA-256, shapes 16×8×8, `exact: true`). Each was replayed with `solve_bayes` five ways:
- the current solver without a budget;
- an unlimited ledger (to count the work);
- the default caps;
- a forced exact rescue with the unlimited ledger;
- a forced exact rescue with the default caps.

| Fixture | Float pivots | Exact pivots needed | Exact ops needed | Widest bits | Unbounded (s) | Default caps |
|---|---:|---:|---:|---:|---:|---|
| 0 | 200 | 850 | 29,586,660 | 148 | 36.6 | `exhausted:exact_ops` after 0.41 s |
| 1 | 173 | 77 | 2,469,526 | 186 | 2.9 | `exhausted:exact_ops` after 0.40 s |
| 2 | 278 | 607 | 23,666,639 | 163 | 45.0 | `exhausted:exact_ops` after 0.53 s |
| 3 | 278 | 607 | 23,666,639 | 163 | 38.2 | `exhausted:exact_ops` after 0.59 s |
| 4 | 1533 | 200 | 7,148,641 | 191 | 9.1 | `exhausted:exact_ops` after 0.60 s |

Caps: 4096 float pivots, 32 exact pivots, 250,000 exact ops, 4096 bits.

- **The current solver still needs the rational rescue for all five.** Its float and stable-float paths fail there. Unbounded, the rescue certifies (exploitability ≤ 4.4e-16) in 2.9 to 45.0 s.
- **The default caps turn every rescue into an explicit `WORK_EXHAUSTED` raw fallback.** It happens deterministically within 0.6 s, always on the exact-operation cap. The bits cap never binds: the widest value is 191 bits of 4096. Float pivots stay ≤ 1533 of 4096.
- Fixtures 2 and 3 are the same table: one state decided by the N and the X rule.
- **Gate: pass, caps unchanged.** #236's rate was 5 rescues in 127,435 searched decisions (0.004%), far below the 1% primary-fallback STOP. The exhaustion is counted per decision and never retried.

Fingerprints: manifest `617395fa…`; fixtures `b023e93d…`, `15c0395d…`, `10a128d0…`, `0414e079…`, `46feebc5…`.

## C5: 64-game evaluation smoke

- **Setup:** 64 raw greedy games (`duoforge_learn.evaluate.play_suite`), 32 swapped-seat pairs, 32 games PP_/A/B/C and 32 LL_.
- **Players:** `params-49333` as an arm stand-in against `params-11000` (panel P75). The approved LL_ evaluation registry does not exist yet, so LL_ teams come from the current registry. This is a throughput smoke, not a strength result.
- **Device:** RTX 4060 Ti, JAX 0.11.2 CUDA, `--xla_gpu_deterministic_ops=true`, max 1000 steps, 8 batch workers.
- **Results:**

| | Value |
|---|---:|
| First run, JIT included | 3.23 s (19.8 games/s) |
| Repeat run | 0.67 s (95.6 games/s) |
| Forecast for the 12,288 predeclared games (one JIT warm-up + warm rate) | 2.2 min |
| Unfinished / unresolved games | 0 / 0 |
| Repeat-run records | byte-identical |
| Ledger (`ledger.py`) | 10.06 CPU core-seconds, 3.89 GPU-seconds |

- **Gate: pass.** The bars were ≥5 games/s and a forecast including JIT ≤ 60 min. The 60-minute GPU reserve for evaluation and JIT is far from binding.
- **Not covered:** the real arms, the full opponent set (one JIT per distinct model configuration) and the approved LL_ list. These remain prerequisites of the evaluation itself.
- The smoke's cost is charged to the evaluation reserve (shared, half per arm).

## Next

These gates are a necessary condition, not sufficient. The pilot still waits for:
- Learner v2's collector and contract gate;
- the approved LL_ evaluation manifest;
- the generation smoke (frozen R and forecast);
- an owner run window.
