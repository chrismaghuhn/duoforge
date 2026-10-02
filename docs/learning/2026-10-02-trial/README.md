# Learner trial run (2026-10-02)

The first run of the learner pipeline (decision 0014): 30 minutes of self-play PPO on the two reference teams (four pairings), to check the pipeline end to end and to see whether the policy learns.

## Setup

- `python -m duoforge_learn.train --envs 256 --workers 16 --rollout 32 --minutes 30 --eval-every 50 --eval-envs 128` (the full configuration is in `config.json`).
- WSL (Ubuntu 24.04), JAX 0.11.2 with CUDA 12 on an RTX 4060 Ti (8 GB), optax 0.2.8, NumPy 2.5.3; library 0.15.0, GCC Release with LTO; Ryzen 7 5800X.
- The machine was shared: during the second half two full local CI runs (another session's and #67's) ran beside it.
- The run used the pipeline as first written, before the review of #68: the value loss covered only the rows where a seat acted, self-play episodes had no cut-off, and the JAX key used the low 31 bits of the seed.

## Results

- 2,667 updates, 39.5 million decisions and 1.68 million episodes in 30 minutes: about 25,000 decisions per second (collection 0.28 s and update 0.30 s per update of 32 steps × 256 environments), also while the CI runs shared the CPU.
- Every 50 updates the greedy policy played 128 fixed-seed episodes against each opponent (both seats, all four pairings). All 54 evaluations are in `evaluations.jsonl`.

| Update | Minutes | Decisions | Entropy | vs random | vs scripted | vs previous |
|---|---|---|---|---|---|---|
| 50 | 0.6 | 0.7 M | 2.37 | 0.977 | 1.000 | 0.969 |
| 250 | 2.6 | 3.6 M | 0.56 | 1.000 | 1.000 | 0.523 |
| 650 | 6.9 | 9.5 M | 0.70 | 0.969 | 1.000 | 0.672 |
| 1050 | 10.9 | 15.5 M | 0.86 | 1.000 | 1.000 | 0.695 |
| 1450 | 15.6 | 21.5 M | 0.60 | 0.992 | 1.000 | 0.445 |
| 1850 | 20.3 | 27.4 M | 0.64 | 0.938 | 1.000 | 0.648 |
| 2250 | 25.3 | 33.4 M | 0.83 | 0.969 | 1.000 | 0.617 |
| 2650 | 29.8 | 39.3 M | 0.73 | 1.000 | 1.000 | 0.750 |

Over all 54 evaluations: against the random baseline at least 0.938 (mean 0.981), against the scripted baseline at least 0.852 (mean 0.987), and against the parameters of the previous evaluation above 0.5 in 49 of 54 (mean 0.649).

For comparison, untrained networks (two seeds, greedy, 256 episodes each) won 0.16 and 0.42 against the random baseline and 0.25 and 0.63 against the scripted one.

A round robin of six checkpoints (`python -m duoforge_learn.ladder <run> --pick 5 --envs 64`, 64 fixed-seed games per pair, greedy; the untrained network of the run's seed included; `ladder.json`) rates them by Bradley-Terry:

| Player | Elo | Mean score |
|---|---|---|
| untrained | 0 | 0.006 |
| update 50 | 655 | 0.453 |
| update 700 | 677 | 0.481 |
| update 1350 | 764 | 0.600 |
| update 2050 | 803 | 0.653 |
| update 2667 | 924 | 0.806 |

## Reading

- **The pipeline works end to end:** self-play over the factored domain, masked sampling (the engine rejected no choice), PPO, evaluation and checkpoints, with finite losses throughout.
- **The baselines are beaten within the first minute** and say nothing about later progress. The checkpoints do: the ladder rises monotonically, by about 270 Elo from update 50 to the end, so a longer run would still improve - against these four matchups.
- **With two teams this is memorisation of four matchups**, not a general player; the run checks the pipeline. More teams (Team C, the expansion) make longer runs worth more.
- The comparison with the previous checkpoint is noisy at 128 greedy episodes; the ladder over several checkpoints measures progress more reliably.
