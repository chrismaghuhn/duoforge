# 0008 — Benchmark API, action tally and the first baseline

Status: **built** (2026-10-01); the Release baseline is still to be measured on an idle machine (section 6). Builds on `docs/TESTING_AND_BENCHMARKS.md` sections 4 to 6 (families, workload manifest, diagnostics) and decision `0007` section 8 (the benchmark follows the event log, so it measures the final observation and event cost).

## 1. Owner inputs (2026-10-01)

- A small benchmark API to measure the engine, after the player view.
- A light API that counts what the AI does: moves, switches and so on.
- The machine may not be free while measuring: a busy run must not pass as a measurement.

## 2. What is built

`bench/` holds a static library (`duoforge_bench_lib`: `bench.h`, `tally.h`), the driver `duoforge_bench` and two CTest checks (label `bench`). It is built with the tests (option `DUOFORGE_BUILD_BENCH`, default on), because the reference teams come from the test support (`df_setup_teams`). Only the public API is measured; nothing in `src/` changes.

**Workload `closure-pairings-v1`:** the two reference teams in the pairings A-B, B-A, A-A, B-B; per pairing `--battles N` battles with consecutive `rng_initstate` seeds; a uniform random policy over each requested player's candidates with its own seed (splitmix64, independent of the engine's RNG); a guard of `--max-steps` per battle, counted as a truncation, never as a result. The battles are recorded once as a fixed command source: every bundle and every boundary state.

| Family | Timed | Units |
|---|---|---|
| STEP_CORE `plain` | the replay of every battle's bundles with `duoforge_battle_step`, one restore per battle included | battles, turns, steps, side decisions |
| STEP_CORE `events` | the same with `duoforge_battle_step_events` and full buffers | as above |
| REQUEST | at every recorded boundary, for both players: request, candidates (requested players), observation | calls (player groups) |
| SNAPSHOT `copy` / `codec` | every boundary state restored with `duoforge_battle_copy`, or encoded and decoded | restores, encoded bytes |
| EPISODE_NATIVE | the same battles played live; parts `reset` (create, destroy), `policy` (request, candidates, choice), `step` | battles, turns, steps |

Before STEP_CORE is timed, one untimed replay checks that every battle ends in its recorded state (digest); a mismatch is an error. Every family runs `--warmup` untimed passes and `--repetitions` timed ones and reports per repetition the wall time (QueryPerformanceCounter, CLOCK_MONOTONIC) and the process CPU time; the report gives the median, the counts per repetition and rates derived from the median. Any non-OK status is an error: the driver then exits 1.

**A busy machine is visible:** the workload is single-threaded, so a repetition of at least 100 ms whose process CPU time is below 90 percent of its wall time shared the CPU and is reported as disturbed (`disturbed_repetitions`; the driver warns). Shorter repetitions are not judged (the Windows process clock has coarse ticks).

**Manifest** (the JSON report's first object): engine version, revision and dirty flag (written at build time by `cmake/bench_revision.cmake`), compiler, build type and C flags, OS, CPU and logical processors, worker count 1 without affinity, start time, the workload and its seeds, the policy, the context fingerprint, warmup and repetitions, and the timers. Peak memory and allocation counts are not reported yet.

## 3. Action tally

`dfb_tally_choice(ctx, battle, player, choice, tally)` counts one submitted side choice at its boundary, from the choice and the player's own observation only: team selections and the roster indices led with; slot commands split into moves (by move id; Struggle; Mega declarations; aimed at a foe, the ally or no chosen target), voluntary switches (at TURN), replacements (REPLACEMENT, PIVOT) and passes. A choice that does not fit the boundary is refused (`E_INVALID_ARGUMENT`) and changes nothing. It contains no rule logic and works for any policy, a model included. The driver counts each side's choices of the recorded workload outside every timing and writes them to the report (`choices`); `duoforge.bench.tally` checks that the counts add up on random real-team battles and that a known move and a voluntary switch land where they belong.

## 4. Usage

```text
duoforge_bench --battles 25 --repetitions 5 --warmup 1 --out report.json
duoforge_bench --families step,episode --max-seconds 60
```

Families: `step`, `events`, `request`, `copy`, `codec`, `episode`. `--max-seconds` stops launching further families once exceeded (reported as `skipped_by_time_limit`).

## 5. Not in scope

BATCH_NATIVE and ROLLOUT_END_TO_END (later milestones), peak memory and allocation counts, and any performance target or regression gate (`docs/TESTING_AND_BENCHMARKS.md` section 4: the first benchmark establishes a baseline).

## 6. The baseline

Measured only on an idle machine (the owner confirms), with Release builds of MSVC, GCC and Clang, the default workload (25 battles per pairing, 5 repetitions, 1 warmup), and only from runs without disturbed repetitions. The reports go to `docs/benchmarks/` with their manifests. Debug builds and runs on a busy machine are functional checks only, never results.
