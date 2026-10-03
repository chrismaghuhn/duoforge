# Learner v2 on Teams A, B and C (measurement night 2026-10-02/03)

This is the A/B/C stage of decision 0017 (spec `docs/superpowers/specs/2026-10-02-learner-v2-design.md`, plan task 20). It has four parts:
- four training runs (v1 and the v2 presets S, M and L) over the 9 pairings of Teams A, B and C;
- a cross ladder;
- the throughput A/B of the PPO update;
- the ingredients of double-buffering.

The raw data are in `raw/`, the scripts are `raw/night.sh`, `raw/ab_train.py` and `raw/ingredients.py`, and the ladder is in `ladder.json` and `ladder.md`.

## Setup

**Code**
- Commit 59480ea (`raw/COMMIT`), run from a frozen copy of `python/` and `data/teams/` taken at the start of the night.
- Library 0.23.0, a Release build without LTO, in WSL.

**Machine**
- WSL (Ubuntu 24.04), JAX 0.11.2 with CUDA 12 on an RTX 4060 Ti (8 GB), Ryzen 7 5800X.
- 8 workers.
- The other sessions kept the machine quiet in the two measurement windows, with two exceptions noted below.

**Four runs, the same pipeline, only the model differs** (`raw/<run>-config.json`)
- Teams and data: `--teams A,B,C --data-kind team_c`.
- Batch: 256 environments, rollout 32, 4 epochs, Adam 3e-4.
- **Minibatch 2048.** v2-L at 4096 ran out of the 8 GB in the scanned update: one 3.14 GiB allocation, with about 1.4 GB taken by the desktop. One minibatch for all four keeps the comparison fair.
- League: half the environments self-play; the other half play the learner against 4 snapshot slots (slot refresh 50, snapshot every 200).
- Entropy schedule over decisions: 0.02 falling to 0.005 at 50M.
- Cut-offs at 500 steps are scored by the reference's tiebreak (`duoforge_battle_tiebreak`). An unresolved tiebreak is a loss for both seats.
- **4600 updates, about 50M learner decisions per run.** The spec's 200M would have taken about four nights at the planned rates.
- v2-S was stopped by SIGTERM at update 2300 and resumed (`--resume`).
- Evaluation every 200 updates: the suite of all 9 pairings, both seats, 2 games each (36 games), against the random baseline and the previous evaluation.

**Not comparable with the night run of 2026-10-02.**
- Tonight's runs differ in four ways: tiebreak scoring of cut-offs (ties there), the league, three teams, and minibatch 2048.
- So tonight's runs compare only with each other. Throughput compares only within the A/B below, which runs both arms on identical code.

## Results

**Training runs** (`raw/<run>-updates.csv`, `raw/<run>-evaluations.jsonl`; rates are medians of the last 500 updates)

| Run | Parameters | Hours | Learner decisions | Matches | Matches/h | Decisions/s | Collect (policy / encoder / engine) | Update |
|---|---|---|---|---|---|---|---|---|
| v1 | 345,707 | 0.78 | 49.8M | 3.07M | 3.9M | 18,400 | 0.47 s (0.23 / 0.12 / 0.07) | 0.13 s |
| v2-S | 384,751 | 1.14 | 49.5M | 3.03M | 2.7M | 13,700 | 0.47 s (0.25 / 0.11 / 0.06) | 0.30 s |
| v2-M | 2,072,463 | 1.56 | 49.7M | 3.23M | 2.1M | 8,700 | 0.63 s (0.33 / 0.16 / 0.08) | 0.63 s |
| v2-L | 7,871,631 | 2.44 | 49.7M | 3.17M | 1.3M | 6,000 | 0.63 s (0.40 / 0.11 / 0.06) | 1.17 s |

Notes on this table:
- "Matches" counts every training game: self-play and league.
- "Decisions" counts only the learner's rows, not a league opponent's.
- Collection is 32 steps. Policy covers the learner plus the 4 league slots in one vmap call. Encoder is the NumPy encoder; engine covers step and query.

**What the runs show**
- **No run plateaued.** The mean of `vs_previous` (each evaluation against the one 200 updates before) stays above 0.5 in every quarter of every run:

  | Run | Mean `vs_previous` per quarter |
  |---|---|
  | v1 | 0.78, 0.67, 0.71, 0.66 |
  | v2-S | 0.79, 0.66, 0.64, 0.62 |
  | v2-M | 0.73, 0.62, 0.68, 0.69 |
  | v2-L | 0.66, 0.70, 0.76, 0.66 |

  The night run of 2026-10-02 had flattened after about 70 minutes.
- **The league works.** The learner wins 80-81 % of 1.6-1.7M games against its own snapshots in every run.
- **No stalling.** There were 0 cut-offs in all four runs, so also 0 unresolved tiebreaks.
- **Baseline.** Against the random baseline, all runs score 0.97-1.0 from the first evaluation on.
- **Resume under real conditions.** v2-S was stopped by SIGTERM at update 2300, ended cleanly with exit 0, and resumed to update 4600. The `resume` line is in `raw/v2-S-evaluations.jsonl`.

## Cross ladder

All four runs at updates 0, 1600, 3000 and 4600, plus the untrained network: 17 players. Each pair plays the 36-game suite, greedy. Bradley-Terry Elo is relative to `init`, with 95 % intervals from 200 bootstrap resamples. Per-team Elo counts the games in which the player pilots that team.

| Player | Elo | 95 % | Elo A | Elo B | Elo C | Hours into its run |
|---|---|---|---|---|---|---|
| v1 update 1600 | 499 | 444-569 | 516 | 390 | 356 | 0.29 |
| v1 update 3000 | 451 | 395-508 | 530 | 296 | 315 | 0.53 |
| v1 update 4600 | 513 | 464-576 | 654 | 326 | 338 | 0.78 |
| v2-S update 1600 | 546 | 496-606 | 607 | 379 | 420 | 0.40 |
| v2-S update 3000 | 574 | 522-627 | 616 | 420 | 444 | 0.75 |
| v2-S update 4600 | 565 | 509-623 | 593 | 382 | 488 | 1.14 |
| v2-M update 1600 | 472 | 424-522 | 539 | 375 | 270 | 0.55 |
| v2-M update 3000 | 494 | 448-552 | 548 | 382 | 320 | 1.02 |
| v2-M update 4600 | 616 | 554-674 | 741 | 394 | 483 | 1.56 |
| v2-L update 1600 | 454 | 412-508 | 460 | 390 | 279 | 0.86 |
| v2-L update 3000 | 557 | 503-620 | 566 | 493 | 360 | 1.59 |
| v2-L update 4600 | 562 | 508-611 | 621 | 417 | 406 | 2.44 |

The intervals are about ±55 Elo wide, so differences under about 100 Elo are not established.

**At equal decisions (update 4600)**
- v2-M ranks first (616), ahead of v2-S (565), v2-L (562) and v1 (513).
- Only v2-M against v1 is clearly apart.
- v2-L did not use its size in 50M decisions.

**At equal time**
- At about 0.8 h, v2-S (update 3000: 574) and v1 (update 4600: 513) are ahead of v2-M (about update 2300, between 472 and 494) and v2-L (update 1600: 454).
- At about 1.6 h, v2-M (616) is ahead of v2-L (update 3000: 557).
- This fits "smaller networks trained longer beat larger ones trained fewer steps" at this budget. The S/M ordering at equal decisions says M has the capacity once the time is there.

**v2 against v1**
- v2-S is ahead of v1 at all three checkpoints (546/574/565 against 499/451/513), at almost the same parameter count.
- The intervals overlap at 1600 and 4600.

**Per team**
- Every model does best piloting Team A and worst with C or B.
- Why C and B lag is not measured here.

## Throughput: PPO update A/B

Both arms run the same code, the night run's configuration:
- v1, Teams A and B, self-play only;
- 256 environments, 8 workers, minibatch 4096;
- 300 updates per run, 3 interleaved repetitions per arm (`raw/ab_train.py`).

The arms:
- `host`: the update of decision 0014, every minibatch cut on the host and copied.
- `scan`: the samples go to the device once and all epochs run in one jitted `lax.scan`.

The numbers below are the medians of each repetition after 20 warm-up updates. The clean repeat ran 05:30-05:48 (`raw/ab-repeat-*.csv`).

| Arm | Decisions/s | Update | Collect (policy / encoder / engine) |
|---|---|---|---|
| host | 26,337-26,716 | 0.285-0.286 s | 0.254-0.260 s (0.105-0.111 / 0.074-0.075 / 0.042) |
| scan | 34,686-35,711 | 0.153-0.154 s | 0.252-0.264 s (0.105-0.110 / 0.073-0.078 / 0.042-0.046) |

- **Effect:** the update takes 46 % less time (0.154 s against 0.285 s), and decisions per second rise by 30-36 % (the ratios of the slowest and fastest repetitions). Collection is unchanged.
- **Inside the scan update:** the copy is 0.013 s and the compute 0.140 s.
- **The first A/B, 22:00-22:19,** was disturbed from 22:00 to 22:10 (`raw/ab-22h-*.csv`). It shows the same effect, +31 to +39 %, at a slightly lower level, and serves only as a cross-check.
- **Second disturbance:** a short generator script ran at about 05:37, during repetition `host 2`. Its numbers (26,337) sit within the other two (26,624 and 26,716).

## Double-buffering: the ingredients

Overlapping the collection of update k+1 with the PPO update k needs the actor's inference somewhere else. On one GPU stream, an `act` call queued behind the update waits for it.

| Model | `act`, 512 rows, GPU | `act`, 512 rows, CPU |
|---|---|---|
| v1 | 1.56 ms | 12.65 ms |
| v2-S | 1.76 ms | 31.9 ms |
| v2-M | 2.87 ms | 60.0 ms |
| v2-L | 3.97 ms | 122.8 ms |

The figures are medians of 50 calls, from the 05:47 repeat (`raw/ingredients.jsonl`).

On the CPU an update's 32 steps would cost:
- v1: 0.40 s, more than the whole collection of 0.25 s;
- v2-S: 1.0 s;
- v2-L: 3.9 s.

So a CPU actor does not pay. The most any overlap could save at the A/B configuration is the shorter phase: 0.15 s of the 0.40 s update loop, about 37 % of the time. Double-buffering stays unbuilt. The next lever is the owner's order:
1. the encoder in C, in the batch workers (encoder 0.07-0.16 s per update, plus the Python thread);
2. bfloat16 and fewer league opponents per step (the policy share is 0.23-0.40 s, the largest).

## Disturbances, honestly

- 22:00-22:10: a local Python test suite of the HauptSession, and briefly an expansion run. This affects the first A/B and nothing else; the report uses the repeat.
- About 05:37: Builder B's single-threaded generator scripts (no builds). This hit repetition `host 2` of the repeat, with no visible effect.
- The training runs did not need a quiet machine. Their throughput figures are indicative; the learning comparison is at equal decisions.

## Reading

- **The pipeline holds on three teams:**
  - registry teams, N² pairings, the league;
  - tiebreak-scored cut-offs, the entropy schedule;
  - resume after SIGTERM, the per-team suite and ladder.
- Learning keeps rising where the two-team self-play of 2026-10-02 had flattened.
- **Model v2 is at least as good as v1 at the same size**, and v2-M is the strongest at equal decisions. 50M decisions is short, though: v2-L (7.9M parameters) has not used its capacity yet, and the ladder separates only v2-M from v1.
- **Throughput:**
  - The PPO update is no longer the limit for the small models.
  - Collection is: the policy calls first, then the encoder.
  - For v2-M and v2-L the update grows with the network (0.6 and 1.2 s).
