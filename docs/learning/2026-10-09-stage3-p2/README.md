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

| Device | Path | Seconds (two repetitions) | Decisions/s | vs per root |
|---|---|---:|---:|---:|
| CPU | per root | 29.6 / 29.5 | 20.1 / 20.2 | 1.00 |
| CPU | tick, no dedup | 26.7 / 26.3 | 22.3 / 22.6 | 1.11 / 1.12 |
| CPU | **tick** | **20.7 / 19.9** | **28.8 / 29.9** | **1.43 / 1.48** |
| GPU | per root | 34.4 / 33.7 | 17.3 / 17.7 | 1.00 |
| GPU | tick | 31.3 / 30.5 | 19.1 / 19.5 | 1.10 / 1.10 |
| Split | per root | 21.0 / 20.9 | 28.3 / 28.6 | 1.00 |
| Split | **tick** | **16.6 / 16.4** | **35.9 / 36.4** | **1.27 / 1.27** |

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

**Forecast vs. measurement on the CPU:** forecast ≈1.6×, measured 1.43–1.48×.

## Gate (predeclared)

- **PASS on the CPU**, the frozen P1 generation device: identity holds, and the tick path reaches ≥1.25× in both timed repetitions (1.43×, 1.48×).
- **The GPU alone misses the bar** (1.10×).
- **The split passes** (1.27×) and is the fastest overall (≈36 decisions/s vs ≈29 on the CPU). Moving generation to it would change the frozen P1 device and needs an owner decision and its own freeze.

## Next

- Learner v2's collector can switch to `label_tick` per tick without changing any label.
- The remaining big cost is the per-root policy calls: 1 root row plus 1–3 world calls of 32 rows. Batching those across a tick is the next lever. It changes logit bits at other shapes (P0) and therefore needs its own plan and identity gate.
