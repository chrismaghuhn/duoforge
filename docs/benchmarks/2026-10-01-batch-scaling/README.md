# Batch scaling 2026-10-01 (M6)

The Release benchmark report of roadmap M6: the batch runtime (decision 0012) in its native mode, with 1 to 16 worker threads.

**Machine:** AMD Zen 3 (AMD64 Family 25 Model 33), 8 cores, 16 logical processors, Windows 11. The machine is shared with other projects' sessions. Before each run a watcher waited until the other processes used less than 0.8 of a core for 15 seconds. A run in which any worker count had more than one disturbed repetition was repeated, at most three times; GCC and Clang needed three runs, MSVC one.

**Builds:** Release with link-time optimization (`DUOFORGE_ENABLE_IPO`), revision 30667fb, clean tree. GCC 16.2.0, Clang 23.1.2, MSVC 19.44.

**Command:** `duoforge_bench --battles 4000 --repetitions 5 --warmup 1 --families batch --workers 1,2,4,8,12,16`. That is 256 environments (the four pairings in turn) times 63 episodes, 16,128 battles per repetition, with the uniform random policy. Every worker count plays the same battles: the hash of all episode records is the same for every count, with 0 errors. The reports are `gcc.json`, `clang.json` and `msvc.json`.

## Battles per second (median of 5 repetitions)

| Workers | GCC | Clang | MSVC |
|---|---|---|---|
| 1 | 10,458 | 12,148 | 9,997 |
| 2 | 20,667 (1.98×) | 22,963 (1.89×) | 19,408 (1.94×) |
| 4 | 39,586 (3.79×) | 43,519 (3.58×) | 36,989 (3.70×) |
| 8 | 65,292 (6.24×) | 72,357 (5.96×) | 57,665 (5.77×) |
| 12 | 77,396 (7.40×) | 85,540 (7.04×) | 71,105 (7.11×) |
| 16 | 82,173 (7.86×) | 94,668 (7.79×) | 78,908 (7.89×) |

Decisions per second at 16 workers: 2.65 million (GCC), 3.05 million (Clang), 2.54 million (MSVC).

The runtime scales almost linearly to 4 workers. It reaches about 6 times one worker on the 8 physical cores and about 7.8 times on all 16 logical processors, where SMT adds roughly 30 percent.

## Utilization and spread

| Workers | 1 | 2 | 4 | 8 | 12 | 16 |
|---|---|---|---|---|---|---|
| CPU time / (workers × wall), median, GCC / Clang / MSVC (%) | 100 / 100 / 99 | 99 / 99 / 99 | 98 / 97 / 99 | 93 / 90 / 92 | 93 / 91 / 91 | 85 / 87 / 91 |
| run-to-run spread (%) | 9 / 3 / 2 | 4 / 4 / 6 | 4 / 7 / 5 | 7 / 23 / 12 | 3 / 5 / 6 | 11 / 18 / 8 |

From 8 workers on, utilization falls below the 90 percent at which the benchmark calls a repetition disturbed. Two effects add up:
- All logical processors are in use, so any other process takes CPU time from a worker.
- The static slices finish at slightly different times.

The flags at 8 to 16 workers therefore mark contention rather than broken runs. The medians are stable across the repeated runs.

## M6 exit criteria

| Criterion | Evidence |
|---|---|
| Single/batch semantic equivalence | `duoforge.batch.equivalence`: the native mode equals a sequential single-battle reference; the step mode ends in the reference's final states |
| Reproducibility independent of scheduling | the same test with 1, 2, 3, 4, 8 and 16 workers; this benchmark's record hash is equal for every worker count |
| No race findings on tested paths | ThreadSanitizer with Clang 18 and GCC 13 on the batch tests; a job of the local CI and of the nightly hosted CI |
| Bounded memory | allocation only at creation (environments and per-worker scratch of about 41 KB each) and one battle per episode reset; none per step |
| Reproducible Release benchmark report | this report and its manifests |

M6 is done for the synchronous runtime. An asynchronous mode (EnvPool's send and receive with partial batches) is not part of the exit criteria and waits for a measured need.
