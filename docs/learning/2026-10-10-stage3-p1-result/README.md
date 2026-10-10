# Stage 3 P1: pilot result and diagnosis (2026-10-10)

The P1 pilot of the [P1 plan](../../superpowers/plans/2026-10-08-stage3-p1-pilot.md) ran on AWS. The result is **INCONCLUSIVE**: there is no promotion, and distillation shows no gain at this budget. A read-only diagnosis explains why. The student was allowed to move only 0.013 nats from params-49333, so the pilot was in effect 49333. The owner chose a repeat with a wider trust region (C2, planned separately).

Only aggregates appear here. Shards, checkpoints, ledgers, logs and records stay private, in S3 and `C:\Dev\datasets`.

## Runs

| Run | Where | What | Outcome |
|---|---|---|---|
| local, 2026-10-09 | owner PC, main d3631151 | generation 19968 games / 16384 targets in 23.5 min (6173 CPU core-s incl. smoke) | distill failed: CUDA out of memory on the 8 GB GPU after ~25 min of single-threaded shard loading, not charged; superseded |
| 2be0afe30d62-20261009T172944Z | AWS g6.4xlarge (L4) | generation (4947 CPU core-s), loading 85 s, distill 1.3 min; pilot 5202 CPU core-s / 59.9 GPU-s | control stopped twice: the calibration cap (dropped by the owner), then a compute mismatch (control 62.90 GPU-s, \|Δ\| 3.0002 > 2.9951); control discarded, reported, not charged |
| 60a8766490bf-20261010T120438Z | AWS, pilot imported read-only from the run above | fresh control with the feedback match: 5036 CPU core-s / 60.43 GPU-s against 5202 / 59.90, one process, stopped "matched"; evaluation smoke GO, full evaluation 12288/12288 games, 0 cut-offs, 0 refusals | **INCONCLUSIVE** |

## Gate result

| Group | Point | 95% interval | Bar | Status |
|---|---:|---|---|---|
| Pilot vs continuation (1024 pairs) | 0.477 | [0.447, 0.507] | ≥ 0.52, lower > 0.50 | INCONCLUSIVE |
| Pilot vs frozen 49333 (1024 pairs) | 0.506 | [0.475, 0.537] | ≥ 0.53, lower > 0.50 | INCONCLUSIVE |
| Panel, pilot − control (1536 pairs) | +0.0075 | [−0.016, 0.030] | lower > 0 | INCONCLUSIVE |
| Panel PP_/A/B/C | +0.013 | [−0.023, 0.046] | lower > −0.03 | PASS |
| Panel LL_ | +0.002 | [−0.031, 0.035] | lower > −0.03 | INCONCLUSIVE |

Pairs are not added after the fact; the plan forbids choosing an endpoint after seeing results. With more pairs the head-to-head would also converge near 0.48, below the 0.52 bar.

## Diagnosis (read-only, no compute run)

- **The teacher is clearly stronger than raw.** The P0 gate gave X +0.2695 [0.213, 0.326] against raw 49333; the honest arena #236 gave X +0.314 [0.290, 0.339].
- **The teacher disagrees with the raw move.** Sample: 6 of 78 shards of the local generation (same setup), 1386 targets. The teacher's argmax equals the raw move in 27% of them, the mean mass on the raw move is 0.26 (median 0), and the teacher entropy is about 0.48 nats.
- **The student barely moved.** Its held-out teacher KL went from 2.362 at epoch 0 to 2.302 at epoch 1, the chosen epoch (−2.5%). Its KL to 49333 was 0.0126 nats. `REF_KL_MAX` = 0.02 (distill learning rate 3e-5) stopped distill after 52 steps, at epoch 2 (ref KL 0.0306).
- **Conclusion:** P1 measured that a step of ≤ 0.02 nats from 49333 does not help. That is consistent with 0.506 against frozen 49333, and it is not evidence against distillation. The team pool does not explain it: 49333 was trained on the same 652-team pool that P1 uses throughout.

## Diagnostics beside the gate

- **Trick Room** (no gate; the owner's amendment):
  - In games where its team has a setter, the student set Trick Room in 699 of 1912 (pilot) and 364 of 976 (control); mostly on turn 1.
  - It never reversed an opponent's Trick Room: 0 reversals in 648 (pilot) and 346 (control) games where the opponent set it.
  - Block attempts were rare: 33 of 1868 and 8 of 908 games with an opponent setter.
  - No change was unattributed. 126 games chose Trick Room on their last turn, whose effect is not observed.
  - The arms play different suites, so their TR score rates are not compared.
- **Compute:** the pilot and the fresh control each matched within 5% on both axes. The shared evaluation reserve added 17.7 GPU-s to each arm.

## Limits and known issues

- **Unreconstructible PIVOT records:** the generation used main before the view audit fix. Its public record carried a silent flinch at a PIVOT with a public Protect up. That combination is rare, and the fix (refusing a PIVOT with a queued move left) is in the next M12 bundle.
- **Load time:** loading the shards took ~25 min single-threaded on the local attempt. Learner v2 parallelised it (85 s on AWS).
- **Discarded runs:** the discarded control run and the uncharged local distill attempt are listed above and not charged to either arm.

## Next

The owner chose **C2**: `REF_KL_MAX` 0.3, learning rate 1e-4, up to 16 epochs and 512 steps, with early stop on the held-out teacher KL.
- Generation is reused from run 1, pinned by SHA.
- The control is fresh, matched to the new pilot ledger.
- The gates are unchanged.
- Predeclared target: held-out teacher KL at most 0.70 of epoch 0, reported with the argmax agreement.

It starts only after the owner's go.
