# Learner night run (2026-10-02)

The first long run of the learner pipeline (decision 0014), after the review fixes of #68: 330 minutes of self-play PPO on the two reference teams (four pairings).

## Setup

- `python -m duoforge_learn.train --envs 256 --workers 8 --rollout 32 --minutes 330 --eval-every 200 --eval-envs 128` (`config.json`), 02:20 to 07:53.
- WSL (Ubuntu 24.04), JAX 0.11.2 with CUDA 12 on an RTX 4060 Ti (8 GB); library 0.15.0, GCC Release with LTO; Ryzen 7 5800X.
- 8 of the 16 CPU threads, so the other sessions could build and run their CI beside it, which they did all night.

## Results

- 30,415 updates, 438 million decisions and 18.6 million episodes: about 22,000 decisions per second on average, 27,000 at the end.
- No crash, no evaluation episode cut off (the 1000-step limit was never reached), finite losses throughout.
- The 153 evaluations (`evaluations.jsonl`): against the random and the scripted baselines between 0.94 and 1.0 the whole night; against the previous evaluation's parameters above 0.5 in 118 of 153 (mean 0.59). Entropy fell from 0.86 to about 0.3 to 0.5.

A round robin of twelve checkpoints spread over the run and the untrained network (`python -m duoforge_learn.ladder <run> --pick 12 --envs 128`: 128 fixed-seed games per pair, greedy; `ladder.json`):

| Player | Elo | Mean score |
|---|---|---|
| untrained | 0 | 0.010 |
| update 200 | 602 | 0.334 |
| update 3000 | 684 | 0.439 |
| update 5800 | 762 | 0.548 |
| update 8400 | 761 | 0.547 |
| update 11200 | 756 | 0.540 |
| update 14000 | 808 | 0.613 |
| update 16800 | 787 | 0.584 |
| update 19600 | 810 | 0.617 |
| update 22400 | 746 | 0.525 |
| update 25000 | 833 | 0.647 |
| update 27800 | 763 | 0.549 |
| update 30415 | 760 | 0.546 |

## Reading

- **The pipeline holds over a long run:** five and a half hours on a shared machine without a failure.
- **The policy learns in the first hour and then plateaus.** Most of the rating is gained by update 5800 (about 70 minutes); after that the checkpoints move between about 750 and 830 Elo without a trend, and the comparison with the previous checkpoint falls below 0.5 more often (35 of 153). Self-play with shared parameters on four fixed matchups cycles rather than improves; the ladder's differences of 50 Elo between late checkpoints are within the noise of 128 greedy games per pair.
- **What would move it,** once more teams exist: an opponent pool of past checkpoints (league play) against cycling, an entropy schedule, a larger network, and the teams of the Team C track and the expansion. More hours on two teams buy little.
- Ladders rate players within one round robin; the Elo numbers of this run and of the trial are not comparable.
