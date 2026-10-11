# Magnetic Mirror Descent in place of PPO: the plan (#359)

**Status:** plan and implementation behind a flag, 2026-10-11. No training run yet: the run below waits for the training restart and the owner's go.

**Question:** does a learner built to converge to an equilibrium get past the plateau where PPO cycled (750–830 Elo in the first night run)? The learner otherwise stays the same.

## Why MMD first, R-NaD later

- **MMD** (Sokota et al., *A Unified Approach to Reinforcement Learning, Quantal Response Equilibria, and Two-Player Zero-Sum Games*, ICLR 2023) is a change to the loss alone. Its magnet already exists: `--kl-ref magnet` (a frozen copy of the learner, refreshed every `--kl-refresh` updates) with `--kl-coef`, and its entropy term is the entropy bonus. With a refreshed magnet it is the same outer loop as R-NaD.
- **R-NaD** (DeepNash) also changes the rewards: each step's reward becomes r − η log(π(a)/π_reg(a)) for the acting seat, with the opposite sign for the other seat, before GAE. That touches `returns.gae`, the value targets and the league opponents' rows, and it needs its own tests. It is the next step only if MMD shows the direction is right (see Decision).

## What is implemented (this PR)

- `--policy-objective {ppo,mmd}`, default `ppo`. `ppo.OBJECTIVES` lists both, and `ppo.update` refuses any other objective with ValueError.
- **mmd loss:** the policy loss is −(r·A) with no clip, plus `--mmd-prox-coef` times the estimate r log r − r + 1 of KL(policy ‖ behaviour) on the taken actions, with r = exp(logp − behaviour logp).
  - The estimate is never negative and is 0 at r = 1.
  - Per row the loss is least at log r = A / prox_coef, so the step is bounded without clipping.
  - The value loss, the entropy bonus and the KL anchor are unchanged.
- **Statistics:** under mmd, `ppo.update` returns `prox` (the mean proximal estimate). The log line carries `prox` and `policy_objective`. PPO's statistics and log lines stay as they were.
- **Saved options:** only an MMD run saves `policy_objective` and `mmd_prox_coef`, so a PPO run saves exactly what it saved before. A resume keeps the objective and refuses another one.
- **Option checks:** `--mmd-prox-coef` without mmd, or ≤ 0, stops the run.
- **Tests:** `python/tests/test_mmd.py` (CI module `duoforge.python.mmd`).
  - At the behaviour policy, MMD's gradient equals PPO's.
  - The proximal statistic matches the numpy estimate.
  - A stronger proximal term moves the policy less.
  - An unknown objective is refused.
  - A one-update run with mmd plus the magnet records and keeps its options.
  - A PPO run saves no MMD option.
  - The option checks.

## The run (after the restart, with the owner's go)

- **Smoke first (allowed now, private, outside the repository):** 20 updates for each prox_coef in {0.3, 1, 3}, with the magnet (kl_coef 0.05, refresh 500), entropy 0.01, encoder 6 and the restart's pool. Check that `prox` stays finite, that the entropy does not collapse, and that decisions per second are within 5 % of PPO's (the loss adds no forward pass). The value to keep is the smallest prox_coef whose mean |log r| per update stays below PPO's at clip 0.2. It is fixed in the amendment before the run.
- **Arms:** PPO (run 3's recipe) and MMD (the same recipe, with `--policy-objective mmd` and the fixed prox_coef). They share the commit, the start (the restart's BC prior), the pool, the budget (one compute ledger per run, the same CPU core-seconds and GPU-seconds) and **three training seeds per arm**. With one seed per arm, the result is a single-run observation, not evidence for promotion.
- **Endpoints (M13 exit rule: measured alone, before anything is stacked on it):**
  - **E1, Elo at a fixed time per move:** MMD against the previous best agent (the PPO arm's best, and params-49333), head to head on the registry pool. Every MMD network plays every PPO network, 512 pairs per match-up. Scoring and interval follow the random-teams plan (docs/superpowers/plans/2026-10-11-random-teams-ab.md):
    - ties and unresolved games count 0.5;
    - the interval is a two-level cluster bootstrap over training seeds and team pairs, with 10 000 resamples;
    - each MMD seed must be on the passing side of the bound.

    MMD passes if the lower bound of its score is above 0.5.
  - **E2, no cycling:** each arm's snapshots, every 500 updates, play a round robin of 256 pairs per pairing. The run cycles if a later snapshot scores below 0.5 against an earlier one after their 95 % intervals separate. The measure is the share of such inverted pairs; MMD passes if its share is at most PPO's and at most 10 %.
- **Decision:**
  - **E1 and E2 pass (three seeds):** MMD becomes the default objective, by a later PR that changes the default.
  - **E2 passes and E1 does not:** report. R-NaD's reward transform is the next plan.
  - **E2 fails:** report. MMD is not promoted.
  - No pairs are added after the endpoints are read.

## Not in this PR

R-NaD's reward transform; a schedule for prox_coef; a change to the default objective.
