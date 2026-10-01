# Baseline 2026-10-01: closure-pairings-v1

The first baseline of decision 0008 (section 6) and the A/B measurement of the exact step speedups (PR #30).

**Machine:** AMD Zen 3 (AMD64 Family 25 Model 33), 8 cores, 16 logical processors, Windows 11; desktop applications open but idle, CPU load 8 to 12 percent before and after the runs. One worker, no affinity.

**Builds:** Release. GCC 16.2.0 `-O3 -DNDEBUG`, Clang 23.1.2 `-O3 -DNDEBUG`, MSVC 19.44 `/O2 /Ob2 /DNDEBUG`.

**Command:** `duoforge_bench --battles 1000 --repetitions 5 --warmup 1`: 4,000 battles, 52,760 turns, 72,065 steps, 129,495 side decisions, 0 truncations.

## Baseline (revision a16aef2)

`gcc.json`, `clang.json` and `msvc.json` are, per compiler, the first run without disturbed repetitions (GCC and MSVC: the second run; one repetition of their first run was disturbed). Medians over 5 repetitions:

| Family | GCC | Clang | MSVC |
|---|---|---|---|
| STEP_CORE `plain` | 215.8 ms, 333,905 steps/s | 197.0 ms, 365,825 steps/s | 239.5 ms, 300,944 steps/s |
| STEP_CORE `events` | 224.1 ms, 321,595 steps/s | 203.3 ms, 354,427 steps/s | 250.3 ms, 287,913 steps/s |
| REQUEST `request+candidates+observe` | 476.9 ms, 302,221 calls/s | 474.6 ms, 303,670 calls/s | 585.2 ms, 246,307 calls/s |
| SNAPSHOT `copy` | 7.9 ms, 9,095,211 calls/s | 6.9 ms, 10,473,193 calls/s | 8.1 ms, 8,927,222 calls/s |
| SNAPSHOT `codec` | 111.8 ms, 644,662 calls/s | 117.0 ms, 615,932 calls/s | 152.9 ms, 471,441 calls/s |
| EPISODE_NATIVE `uniform-random` | 643.2 ms, 6,218 battles/s | 641.1 ms, 6,239 battles/s | 796.4 ms, 5,022 battles/s |

SNAPSHOT `copy` repetitions take about 8 ms, below the 100 ms a repetition needs to be judged. A battle with the random policy spends about half its time in the policy's queries (request, candidates) and a third in the step.

## A/B: the exact step speedups (PR #30)

A = df8c14d (the engine of main), B = 0251143 (PR #30, the engine of a16aef2). Three rounds per compiler, A and B alternating, the order flipped every round. Only runs without disturbed repetitions count (GCC A 2, B 3, Clang A 1, B 2, MSVC A 1, B 3; the third round was disturbed in several runs). Median time of the whole workload in ms:

| Family | GCC A | GCC B | A/B | Clang A | Clang B | A/B | MSVC A | MSVC B | A/B |
|---|---|---|---|---|---|---|---|---|---|
| STEP_CORE `plain` | 299.1 | 215.0 | 1.39 | 287.9 | 208.7 | 1.38 | 346.7 | 235.4 | 1.47 |
| STEP_CORE `events` | 304.0 | 222.1 | 1.37 | 297.9 | 206.1 | 1.45 | 357.2 | 243.2 | 1.47 |
| REQUEST `request+candidates+observe` | 472.7 | 473.1 | 1.00 | 520.1 | 483.4 | 1.08 | 574.3 | 587.2 | 0.98 |
| SNAPSHOT `codec` | 111.9 | 113.4 | 0.99 | 121.1 | 116.8 | 1.04 | 138.1 | 144.3 | 0.96 |
| EPISODE_NATIVE `uniform-random` | 728.3 | 668.3 | 1.09 | 789.6 | 628.8 | 1.26 | 882.5 | 773.0 | 1.14 |
| &nbsp;&nbsp;part `policy` | 350.2 | 367.4 | 0.95 | 399.2 | 353.7 | 1.13 | 430.4 | 433.9 | 0.99 |
| &nbsp;&nbsp;part `step` | 295.8 | 215.2 | 1.37 | 299.2 | 192.4 | 1.55 | 347.5 | 234.1 | 1.48 |

The step is 1.37 to 1.55 times as fast with every compiler; a whole battle with the random policy 1.09 to 1.26 times, because the policy's queries are not sped up. REQUEST, SNAPSHOT and the policy part are not affected by the speedups (the candidate enumeration only moved its slot lists into a shared function): their ratios (0.95 to 1.13) show the run-to-run noise.

**Limits.** The disturbance check sees time-sharing only, not a busy SMT sibling or a clock change; A and B are therefore interleaved and compared by medians. These are single-thread numbers: they say nothing about scaling over cores.
