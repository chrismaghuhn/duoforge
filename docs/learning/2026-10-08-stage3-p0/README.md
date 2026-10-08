# Stage 3 P0: honest teacher gate and inference profile â€” 2026-10-08

**P0 strength gate passes:** X improves by +0.2695 [0.2129, 0.3262] against raw params-49333. This exceeds +0.08 and has a positive lower 95% bound. P1 still needs its own reviewed plan and owner go; no training or feature implementation occurred.

## Frozen protocol

Follows [decision 0024](../../decisions/0024-expert-iteration.md) / [approved spec #237](https://github.com/chrismaghuhn/duoforge/pull/237) and [honest-arena #236](https://github.com/chrismaghuhn/duoforge/pull/236). Source `1ea92c562fea707b506b98b4372fbfe6d401d8da`; native library 0.43.0; model v2, hidden 640, three layers, encoder 4. Checkpoint SHA-256: `ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb`.

CPU gate: honest X (N/E mix, lambda=0.5), optional E, own/foe top 8, W=S=16, leaf capacity 1024, four native workers. Teacher foe model is the same frozen network. Preview raw, book off, no oracle. Same frozen 79-team PP_/A/B/C pool and leave-foe-source-out public spread beliefs as the prior measurement; 512 parallel games, stable row/key order. The private harness used the reviewed optional registry-root loader to preserve registry hashes; it added no rule logic.

Each arm plays 512 games against raw 49333 in 256 adjacent swapped-seat blocks, identical pairs/seeds. Score win=1/tie=0.5/loss=0. Bootstrap: 2000 resamples of seat blocks, seeds arena `0x2026100300000222`, search `0x2026100300000221`, bootstrap `0x2026100300000220`, max steps 1000. The panel was not part of this P0 gate.

| Arm | Score [95% CI] | Paired gain over raw [95% CI] |
|---|---|---|
| R | 0.5254 [0.4766, 0.5742] | â€” |
| X | 0.7949 [0.7559, 0.8320] | 0.2695 [0.2129, 0.3262] |
| E | 0.8867 [0.8555, 0.9160] | 0.3613 [0.3066, 0.4141] |

All 1536 games finished with resolved results. E fits the budget but does not replace the predeclared X gate. There were no LL_ games; no LL_ strength claim. P1 promotion requires both PP_/A/B/C and LL_ coverage under the spec.

## Search cost and public refusals

| Arm | Searched decisions | Median / p95 total ms | Network median ms | Engine median ms | Solver median ms | Public refusals / requested |
|---|---:|---:|---:|---:|---:|---:|
| X | 4438 | 50.38 / 57.64 | 39.41 | 6.56 | 4.02 | 154/5353 (2.88%) |
| E | 4218 | 49.72 / 55.29 | 38.94 | 6.50 | 4.00 | 155/5084 (3.05%) |

| Cause (may overlap) | X | E |
|---|---:|---:|
| visible_sleep | 111 | 102 |
| visible_confusion | 15 | 24 |
| public_record_unsupported | 19 | 21 |
| DUOFORGE_E_UNSUPPORTED: queue mask | 9 | 9 |

These are explicit public reconstruction refusals, separate from the proposed P1 deterministic rescue-work fallback rule. P0 used the unchanged solver; it does not implement or validate the P1 rescue budget. No refused/unresolved/cut-off leaves were reported.

Gate service plus compilation/collection took 538.2 s; 8656 searched decisions across X/E gives 16.08 searched decisions/s over the complete gate (including raw baseline and initialization). Per-arm reciprocal median latency is about 20/s, not an end-to-end worker scaling claim. CPU network time is about 39 of 50 ms here; the previous 23/33-ms split is not portable to this checkpoint/backend.

## Fixed-shape inference curve

Ryzen 7 5800X / RTX 4060 Ti, JAX 0.11.2, deterministic GPU operations, affinity to four assigned CPU cores and low priority. One captured public-world policy batch and one captured leaf batch from X; zero padding for extra value rows. This is a small inference microbenchmark, not a multi-state throughput study or GPU whole-search run. Twenty timed repeats after warm-up, output materialization synchronized. Host columns include interface checks, transfer/runtime overhead and output copy. Resident columns keep inputs/params on device and still copy output; host-minus-resident is not a pure transfer timer.

| Value capacity | CPU host median / p95 ms | GPU host median / p95 ms | GPU resident median / p95 ms | CPU/GPU first-call warm s | CPU / GPU first64 bit differences vs64 |
|---|---:|---:|---:|---:|---:|
| 64 | 3.30 / 5.61 | 4.50 / 4.94 | 1.64 / 1.73 | 0.46 / 0.83 | 0 / 0 |
| 256 | 6.59 / 7.26 | 4.81 / 5.23 | 1.59 / 2.67 | 0.47 / 0.73 | 0 / 64 |
| 1024 | 31.03 / 36.15 | 7.37 / 8.55 | 3.00 / 4.93 | 0.49 / 0.92 | 0 / 64 |
| 4096 | 139.11 / 155.04 | 16.19 / 18.98 | 6.92 / 10.67 | 0.57 / 1.01 | 64 / 64 |
| 16384 | 666.00 / 920.71 | 31.65 / 34.43 | 17.19 / 18.91 | 1.12 / 0.97 | 64 / 64 |

At capacity 1024 the value call is 31.03 ms CPU vs 7.37 ms GPU through the host interface (3.00 ms resident). For the joint-policy call at 32 rows, CPU is 5.56 ms and GPU 7.74 ms: a per-decision GPU call can be slower at small shapes. At 1024 policy rows: CPU 170.61 ms vs GPU 14.01 ms. These policy timings materialize pair logits; team-head execution is fused, not independently timed.

All 20 repeats within each fixed shape/device were byte-identical; same-shape host/resident value outputs agreed. Changing capacity changes value bits: CPU first64 differ at 4096/16384; GPU first64 differ at 256 and above. Policy 32-vs-1024 changes 96 CPU logit bits but zero sampled argmax choices; GPU policy comparison changes neither. These are only the sampled rows. Whole-search repeated trajectories and cross-capacity search-action identity were not tested. CPU/GPU bit identity is not claimed.

This supports profiling lockstep GPU batching in a separate phase, but does **not** pass the P2 byte-identity gate or claim a measured batched-search speedup. Fixed-capacity configuration must remain part of reproduction; batching may need layout work or explicit reclassification when bits change.

## Budget, validation and next gate

Full run plus both profiles completed in 597.4 s (about 10 min), below the 3500-s watchdog and one-hour allocation including setup. CPU profile 42.8 s; GPU profile 9.0 s including warm-up. An initial private-harness import failed before games and was corrected; setup time was deducted. No statistical retry, training process change or feature code. The watchdog was not reached.

Recomputed every score/CI/gain from private CSVs; checked 512 games/arm, exact swapped-seat blocks, matched metadata/results, checkpoint fingerprint, private decision counts and profile repeat flags. Data/weights/checkpoints/worlds/tables/run paths remain private. Only aggregate evidence is published.

Next step is a separately reviewed **P1 plan**, not P1 execution. Keep the existing GAE value semantics, matched-budget continuation with its own data, deterministic rescue prerequisite and required group coverage from decision 0024.
