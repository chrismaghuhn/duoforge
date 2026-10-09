# Stage 3 P2: lockstep leaf batching, paired measurement (2026-10-09)

Task 5 of the [P2 plan](../../superpowers/plans/2026-10-09-stage3-p2-lockstep-batching.md). It was run in a coordinated 60-minute window under the machine lock, from 12:55 to 13:07.

**Setup**
- Code: `label_tick` (Task 4) and `tickbench`.
- Checkpoint: params-49333 (sha256 `ef1abe65…`).
- Machine: Ryzen 7 5800X / RTX 4060 Ti.
- Software: JAX 0.11.2 in WSL, 14 native workers.
- Games: 512 lockstep games from the pinned 79-team P1 pool with its belief and leave-foe-source-out exclusions, played for 12 steps with seeded random moves, so every path sees the same states.
- Labels: every learner request is observed; the admitted roots pass the 1/8 SELECT gate, with no label cap.
- Paths: three (per root, per tick without dedup, per tick with dedup), each with one warm-up and two timed repetitions.

Aggregates: [`aggregates.json`](aggregates.json). Private outputs stay outside the repository.

## Identity

Decision bytes are identical between repetitions and between all three paths on each device: CPU, GPU (`--xla_gpu_deterministic_ops=true`), and the split with policy on the CPU and value on the GPU.

Task 1's probe (#292) had already shown the precondition for params-49333 on this CPU and GPU: value bits independent of row position, neighbours and padding at capacity 1024. No CPU/GPU cross-device claim is made: GPU worlds differ slightly because the team head runs on another device.

## Throughput

596 labels per repetition, 556 of them TARGET.

| Device | Path | Seconds | Decisions/s | Valid targets/s | vs per root | CPU core-s |
|---|---|---:|---:|---:|---:|---:|
| CPU | per root | 29.6 / 29.5 | 20.1 / 20.2 | 18.8 / 18.9 | 1.00 | 150 |
| CPU | tick, no dedup | 26.7 / 26.3 | 22.3 / 22.6 | 20.8 / 21.1 | 1.11 / 1.12 | 121 |
| CPU | **tick** | **20.7 / 19.9** | **28.8 / 29.9** | **26.9 / 27.9** | **1.43 / 1.48** | 78 |
| GPU | per root | 34.4 / 33.7 | 17.3 / 17.7 | 16.2 / 16.5 | 1.00 | 60 |
| GPU | tick, no dedup | 30.7 / 30.8 | 19.4 / 19.4 | 18.1 / 18.1 | 1.12 / 1.10 | 53 |
| GPU | tick | 31.3 / 30.5 | 19.1 / 19.5 | 17.8 / 18.2 | 1.10 / 1.10 | 52 |
| Split | per root | 21.0 / 20.9 | 28.3 / 28.6 | 26.4 / 26.7 | 1.00 | 45 |
| Split | tick, no dedup | 19.3 / 19.8 | 30.9 / 30.1 | 28.8 / 28.1 | 1.09 / 1.05 | 40 |
| Split | **tick** | **16.6 / 16.4** | **35.9 / 36.4** | **33.4 / 34.0** | **1.27 / 1.27** | 38 |

Seconds, rates and ratios are given for both timed repetitions; CPU core-seconds (process, threads included) for the first. On the GPU, dedup buys nothing over the tick without dedup (19.1 vs 19.4 decisions/s). There, the value calls are cheap and the per-root policy calls dominate.

### Where the time goes (first timed repetition)

**Rows:**
- Of 508,928 leaves, 91.5% are open (the table reads a value).
- Byte-equal dedup keeps 49.3% of the open leaves.
- Value rows drop from 576,512 (563 calls) to 235,520 (230 calls), 2.45× fewer.

**Value time:**
- CPU 12.2 → 5.0 s; GPU 7.2 → 2.4 s; split 6.3 → 2.3 s.
- Process CPU core-seconds on the CPU device drop from 150 to 78.

**Policy calls are unchanged:** 1,739 calls, 37,141 rows. That is the recorded deviation; batching them is a later plan with its own identity gate.
- CPU: 7.0 s.
- GPU: 18.7 s for many small calls, which is why per-root work on the GPU is slower than on the CPU. This matches the plan's Amdahl forecast (GPU gain capped by the policy calls).

**GPU memory:** peak 45 MB on the GPU device, 68 MB on the split.

**Forecast vs. measurement on the CPU:** forecast ≈1.6×, measured 1.43–1.48×. Of the 8.9 s saved per repetition, the value calls account for 7.2 s. The rest comes mostly from reading the encoded rows and public records once per tick instead of once per root.

**Limits of the measurement:**
- The three paths ran one after the other (per root ×3, then without dedup ×3, then tick ×3), not interleaved. Drift on the machine would count against one path; the window was exclusive under the machine lock.
- Warm-up and timed runs take about the same time (e.g. CPU tick 20.5 s vs 20.7 s), because the value call is compiled when the search is built.
- Not measured separately:
  - host-to-device transfer bytes (proxy: value rows × 850 float32);
  - JIT seconds;
  - a GPU-seconds ledger;
  - the zero/padding share per call.

## Gate (predeclared)

- **PASS on the CPU**, the frozen P1 generation device: identity holds, and the tick path reaches ≥1.25× in both timed repetitions (1.43×, 1.48×).
- **The GPU alone misses the bar** (1.10×).
- **The split passes** (1.27×) and is the fastest overall (≈36 decisions/s vs ≈29 on the CPU). Moving generation to it would change the frozen P1 device and needs an owner decision and its own freeze.

## Next

- Learner v2's collector can switch to `label_tick` per tick without changing a label, under two conditions. First, the row-independence probe must hold for the checkpoint and machine in use: it was shown here for params-49333 on this CPU and GPU; re-run `rowprobe` for another. Second, a tick must stay within `ticks.MAX_ROWS` (196,608 unique rows, roughly 500 labeled roots at about 385 unique rows each); above that, `label_tick` refuses with `ValueError` where `label_decision` would not.
- The remaining big cost is the per-root policy calls: 1 root row plus 1–3 world calls of 32 rows. Batching those across a tick is the next lever. It changes logit bits at other shapes (P0) and therefore needs its own plan and identity gate.
