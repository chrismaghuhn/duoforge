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
| BATCH_NATIVE (`batch`, opt-in) | the batch runtime's native mode (decision 0012) over 256 environments (the four pairings in turn), ceil(4 x battles / 256) random-policy episodes each, per worker count of `--workers` (default 1,2,4,8,16); a fresh batch per repetition, its creation untimed; every worker count must give the same episode records (hash) | battles, turns, steps, side decisions per worker count |

Before STEP_CORE is timed, one untimed replay checks that every battle ends in its recorded state (digest); a mismatch is an error. Every family runs `--warmup` untimed passes and `--repetitions` timed ones and reports per repetition the wall time (QueryPerformanceCounter, CLOCK_MONOTONIC) and the process CPU time; the report gives the median, the counts per repetition and rates derived from the median. Any non-OK status is an error: the driver then exits 1.

**A busy machine is visible:** the workload is single-threaded, so a repetition of at least 100 ms whose process CPU time is below 90 percent of its wall time shared the CPU and is reported as disturbed (`disturbed_repetitions`; the driver warns). Shorter repetitions are not judged (the Windows process clock has coarse ticks).

**Manifest** (the JSON report's first object): engine version, revision and dirty flag (written at build time by `cmake/bench_revision.cmake`), compiler, build type, C flags and link-time optimization, OS, CPU and logical processors, worker count 1 without affinity, start time, the workload and its seeds, the policy, the context fingerprint, warmup and repetitions, and the timers. Peak memory and allocation counts are not reported yet.

## 3. Action tally

`dfb_tally_choice(ctx, battle, player, choice, tally)` counts one submitted side choice at its boundary, from the choice and the player's own observation only: team selections and the roster indices led with; slot commands split into moves (by move id; Struggle; Mega declarations; aimed at a foe, the ally or no chosen target), voluntary switches (at TURN), replacements (REPLACEMENT, PIVOT) and passes. A choice that does not fit the boundary is refused (`E_INVALID_ARGUMENT`) and changes nothing. It contains no rule logic and works for any policy, a model included. The driver counts each side's choices of the recorded workload outside every timing and writes them to the report (`choices`); `duoforge.bench.tally` checks that the counts add up on random real-team battles and that a known move and a voluntary switch land where they belong.

## 4. Usage

```text
duoforge_bench --battles 25 --repetitions 5 --warmup 1 --out report.json
duoforge_bench --families step,episode --max-seconds 60
```

Families: `step`, `events`, `request`, `copy`, `codec`, `episode`, and the opt-in `batch` (with `--workers`). `--max-seconds` stops launching further families once exceeded (reported as `skipped_by_time_limit`).

## 5. Not in scope

ROLLOUT_END_TO_END (a later milestone), peak memory and allocation counts, and any performance target or regression gate (`docs/TESTING_AND_BENCHMARKS.md` section 4: the first benchmark establishes a baseline).

## 6. The baseline

Measured only on an idle machine (the owner confirms), with Release builds of MSVC, GCC and Clang, `--battles 1000 --repetitions 5 --warmup 1`, and only from runs without disturbed repetitions. With the default 25 battles per pairing a repetition takes 5 to 18 ms, too short to be judged; with 1000 every family except SNAPSHOT `copy` (about 8 ms) takes 100 ms or more. The reports go to `docs/benchmarks/` with their manifests; the first is `docs/benchmarks/2026-10-01-closure-pairings-v1/`. Debug builds and runs on a busy machine are functional checks only, never results.

## 7. Exact step speedups (2026-10-01)

A sampling profile of the workload put about a third of the step's time into listing the joint domain to find the response, and about as much into checking every member of the result again. Both are now exact shortcuts with the same results (PR #30): membership is decided from the slot lists without listing their product (`dfi_side_accepts`; `duoforge.request.accepts` compares it with the enumeration), and the result's member rules run only for members that differ from the checked input. Every step still checks its input and its result. Measured A/B (the report above): the step 1.37 to 1.55 times as fast, a whole battle with the random policy 1.09 to 1.26 times; about half of such a battle is now the policy's queries.

The candidate lists (PR #39) are written in one pass with closed-form counts, and team selection walks only the valid tuples; the lists are unchanged byte for byte (`duoforge.request.candidates_digest`). Measured A/B (fb1e272 against 744c289, the quiet third round of an interleaved series; the earlier rounds were slowed by another process without being flagged, see section 8): a battle with the random policy 1.31 times as fast with GCC (531.0 to 405.2 ms for the workload), 1.53 with Clang (551.5 to 359.6) and 1.46 with MSVC (640.2 to 437.3), in line with the clean series of section 8.

## 8. Link-time optimization (2026-10-01)

Release builds can link with link-time optimization (`DUOFORGE_ENABLE_IPO`, opt-in; the manifest records it as `ipo`). It is not the default: LTO objects are compiler-specific, so a library built with them links only with the same toolchain (CI showed a C++ test linked by g++ against a Clang-built library fail). GCC and Clang on ELF build fat objects (machine code next to the LTO data), so that the binary checks and a link by another toolchain still see machine code; elsewhere the C++ compiler must belong to the same toolchain, and a toolchain without support fails the configuration. Performance builds (benchmarks, training) turn it on. The full test suite passes with it under GCC, Clang and MSVC. Measured A/B on the same source (744c289), interleaved, CPU load 7 to 15 percent, undisturbed runs only (GCC 3 and 3, Clang 2 and 2, MSVC 2 and 2), median time of the workload in ms:

| Family | GCC | GCC LTO | A/B | Clang | Clang LTO | A/B | MSVC | MSVC LTO | A/B |
|---|---|---|---|---|---|---|---|---|---|
| STEP_CORE `plain` | 205.0 | 190.6 | 1.08 | 200.0 | 176.6 | 1.13 | 251.9 | 216.7 | 1.16 |
| REQUEST `request+candidates+observe` | 227.7 | 221.0 | 1.03 | 191.7 | 194.0 | 0.99 | 232.3 | 212.6 | 1.09 |
| SNAPSHOT `codec` | 112.4 | 97.4 | 1.15 | 119.5 | 102.3 | 1.17 | 141.1 | 125.5 | 1.12 |
| EPISODE_NATIVE `uniform-random` | 415.4 | 385.9 | 1.08 | 360.2 | 334.5 | 1.08 | 444.4 | 394.4 | 1.13 |

Games per second (one core, uniform random policy): GCC 9,629 to 10,364, Clang 11,109 to 11,960, MSVC 9,000 to 10,142; decisions per second 311,735 to 335,526, 359,650 to 387,221 and 291,392 to 328,369.

The disturbance check sees time-sharing only. Another process can slow the workload by a third without taking its core (memory bandwidth, a shared core, clock); a run is therefore compared with its own repetitions and with the other rounds before it counts.
