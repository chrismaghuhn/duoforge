# Stage 3 P1 C2: the repeat with a wider trust region (2026-10-10)

The C2 repeat of the P1 pilot ([plan](../../superpowers/plans/2026-10-08-stage3-p1-pilot.md), section "P1 result and the C2 repeat"; first result: [stage3-p1-result](../2026-10-10-stage3-p1-result/README.md)). The result is **FAIL**: there is no promotion, and the distilled student plays worse than the equal-compute continuation. Per the plan this was the last P1 repeat without a new plan.

Only aggregates appear here. Shards, checkpoints, ledgers, logs and records stay private, in S3 and `C:\Dev\datasets`.

## Run

- **Run:** ed36cbefac97-20261010T141159Z on AWS g6.4xlarge (L4), commit ed36cbef (engine `src/` and `include/` identical to run 1, 2be0afe3), 14:13–14:40 UTC.
- **Generation:** reused from run 1, pinned by SHA (19968 games, 16384 targets).
- **Distill preset C2:** learning rate 1e-4, `REF_KL_MAX` 0.3, up to 16 epochs and 512 steps. `MIN_GAIN` and `PATIENCE` unchanged.
- **Compute match:** pilot 5524 CPU core-s / 368.5 GPU-s, fresh control 5305 / 351.2. Both axes are within 5%.

## Distill

| Epoch | Held-out teacher KL (rel.) | KL to 49333 | Student argmax = teacher argmax |
|---:|---:|---:|---:|
| 0 | 2.362 (1.00) | 0.000 | 0.317 |
| 1 | 2.223 (0.94) | 0.076 | 0.324 |
| 4 | 2.091 (0.89) | 0.117 | 0.320 |
| 8 | 2.001 (0.85) | 0.148 | 0.317 |
| 12 | 1.945 (0.82) | 0.168 | 0.320 |
| 16 (chosen) | 1.909 (0.81) | 0.182 | 0.318 |

- **Stop:** `max_epochs`, after 416 steps.
- **Teacher KL:** still falling at the last epoch, but the predeclared target (≤ 0.70 of epoch 0) was missed.
- **Distance to 49333:** the student moved 0.18 nats, 14× more than in run 1 (0.0126), and stayed below the trust region of 0.3.
- **Argmax agreement:** flat.

## Gate result

| Group | Point | 95% interval | Status |
|---|---:|---|---|
| Pilot vs continuation | 0.468 | [0.439, 0.497] | FAIL |
| Pilot vs frozen 49333 | 0.496 | [0.465, 0.525] | INCONCLUSIVE |
| Panel, pilot − control | −0.026 | [−0.054, 0.002] | INCONCLUSIVE |
| Panel PP_/A/B/C | −0.017 | [−0.057, 0.022] | INCONCLUSIVE |
| Panel LL_ | −0.035 | [−0.070, 0.003] | INCONCLUSIVE |

- **Ladder** (no gate): pilot 0.499, control 0.521.
- **Trick Room diagnostic** (no gate): still 0 reversals of the opponent's Trick Room.

## Reading

- **The student moved its mass, not its top choice.** It shifted probability toward the teacher's moves (teacher KL −19%) without the teacher's top move ever overtaking its own: argmax agreement stayed at 0.32.
- **The changes were noise for play.** The evaluation plays greedily (argmax), so changes to the student's argmax did not follow the teacher. They acted like noise and made it worse than the continuation (0.468, upper bound below 0.5).
- **A design mismatch, an open question:** the teacher's targets are mixed equilibrium strategies (X, entropy about 0.48 nats), and P0 measured the teacher playing its mixture. Imitating a mixture and then playing its argmax is not playing the mixture. That alone can cancel the gain even of a perfect imitation.

## Options put to the owner

1. **Use the search at play time instead of distilling it** (recommended):
   - The teacher (honest X) scores +0.27 [0.21, 0.33] over raw at about 50 ms per decision, within Showdown's turn timer.
   - Gates: live reliability and latency.
2. **End the distillation line** and focus on engine coverage and performance.
3. **A new plan, only on the owner's go:**
   - hard-label distillation (cross-entropy on the teacher's argmax or its played action);
   - a student evaluation that matches how the teacher plays (sampling against greedy);
   - or a larger label budget (P2);
   - a predeclared target of argmax agreement ≥ 0.5.
