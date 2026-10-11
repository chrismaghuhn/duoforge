# Random teams in self-play: the A/B plan (lever 17)

**Status:** plan, owner decision of 2026-10-10. Training restarts at 85 % game coverage (68.8 % on 2026-10-10), with encoder 6, the new replay data and the random teams. Nothing here runs before then. The infrastructure (the pool, the provenance, the widening smoke) is in place already. The endpoints below are fixed before any run, and no pair is added afterwards.

**Question:** does a share of self-play games with random Champions teams (tools/reference/random_teams.py) make the network generalize to teams it never trained with, without costing strength on the registry teams it plays today?

## Arms

All arms share the same commit, encoder 6, recipe, initial network and compute budget. Each arm is trained with **three training seeds** (the same three seeds in every arm), so that the gates see the spread between independently trained networks and not only the evaluation noise.

| Arm | Team pool | Start |
| --- | --- | --- |
| **A** | the registry pool (the 652 teams of the 49333 training pool: 573 LL_, 76 PP_ and Teams A to C, with their weights) | BC prior from the new replay data, encoder 6 |
| **B** | A's pool, joined by a training corpus at `--random-team-share 0.25` | the same BC prior |
| **C** (option) | A's pool | params-49333 widened to encoder 6 (`checkpoint.load_current`), no BC |

- **Share.** 0.25 is the probability that a side's team comes from the corpus. Sides are drawn independently, so 43.75 % of games have at least one random team and 6.25 % have two.
- **Arm C** separates the BC prior's effect from the random teams' effect. It is optional: it costs a third more compute, and the owner decides at the restart whether it runs.
- **Training seeds.** Three per arm (for example `0x2026101100000021` to `…23`), fixed in the amendment. If the owner approves only one seed per arm, the plan still runs, but its result is labelled **a single-run observation, not evidence for promotion**: the Decision section then promotes nothing, whatever the gates show.
- **Recipe:** run 3's, i.e. PPO, magnet KL 0.05 refreshed every 500 updates, PFSP league, entropy 0.01, encoder 6 with the library's mask `& version_features(6)`, and the ledger on.
- **Budget:** one compute ledger per training run, every run stopped at the same CPU core-seconds and GPU-seconds. Both arms run the same device shares (no budget_match: the arms are symmetric). The budget is set at the restart from the coverage-era throughput, and the plan's amendment states it before the run.
- **Training corpus:** pin, seed and count are fixed at the restart (for example 2048 teams, seed `0x2026101100000017`). The run records its provenance: pin, seed, count, and the sha256 of index.json and manifest.json.

## Evaluation (fixed before the run)

- **Held-out corpus.** A second random_teams.py corpus with another seed (for example `0x2026101100000018`, 512 teams), never in any training pool. Its provenance goes into the evaluation manifest. M12 extends `duoforge_search.eval_manifest` by a second pool.
- **Disjointness, asserted.** Random-team ids are content addressed (`RT_<sha16>`), so the same team drawn by both seeds has the same id. `teams.check_disjoint(training corpus, held-out corpus, data/teams)` must pass when the evaluation manifest is written, and the report states that it passed. A shared id stops the evaluation; nothing is filtered silently.
- **Games.** Paired seeds and block seeds as in expert_eval: both seats, both arms on the same team pairs. A *pair* is one team pair played twice with the seats swapped.
- **Match-ups.** With three seeds per arm, E1 and E2 play each B network against each A network (9 match-ups), 512 pairs per match-up, so 4608 pairs per endpoint. Every match-up uses the same 512 team pairs.
- **Scoring.** A win is 1, a loss 0 and a tie 0.5. A game that ends unresolved (cut off, and the tiebreak cannot decide) is scored **0.5 for both seats**. Self-play training scores it as a loss for both seats, and that rule would pull every head-to-head score below 0.5. The report gives the unresolved count per match-up. If more than 1 % of an endpoint's games are unresolved, the endpoint is reported but not read as a gate (re-plan).
- **Interval.** The 95 % interval is a percentile bootstrap with 10 000 resamples and a fixed seed, written into the amendment. It has two levels. (1) It draws the three A seeds and the three B seeds with replacement. (2) Within each drawn match-up, it draws team pairs with replacement; a team pair is one cluster, with both seat orders and all of its games. B's score is the mean over all drawn games. `ladder.bootstrap` (i.i.d. games, 200 resamples) is not used. The bootstrap is part of M12's report and is tested on a fixed fixture.
- **Consistency.** Apart from the interval, each B seed's mean score against the three A seeds must be on the passing side of the bound (above 0.5 for E1, at or above 0.48 for E2). Three seeds are too few for the outer bootstrap level alone to carry the gate.

### Endpoints

- **E1, primary (generalization):** B against A, head to head, on held-out corpus teams (both sides drawn from the held-out corpus), 4608 pairs. B **passes** if the lower bound of the 95 % interval of B's score is above 0.5 and the consistency check holds.
- **E2, primary (non-inferiority):** B against A, head to head, on registry teams (A's pool, its weights), 4608 pairs. B **passes** if the lower bound of the 95 % interval of B's score is at or above **0.48** and the consistency check holds. That is the non-inferiority margin: B may lose at most 2 points of score on the registry.
- **S1, secondary:** each training run against the ladder (params-39400) and against params-49333 on registry teams, 1536 pairs each. This is reported and is not a gate.
- **S2, secondary (with C):** C against A on both pools, the same sizes as E1 and E2. This is the BC prior's effect; reported only.

### Decision

- **Both E1 and E2 pass (three seeds per arm):** random teams go into the default training pool at 0.25. A larger share is a new plan.
- **E1 passes and E2 fails:** report, and let the owner choose (a smaller share or a schedule). No promotion.
- **E1 fails:** no promotion. The infrastructure stays (it costs nothing unused).
- No pairs are added after the endpoints are read. A compute mismatch above 5 % between the arms makes the run incomplete (re-plan), as in P1.

## Prerequisites (before the restart)

- **Done (this PR):** the pool takes a random corpus (`--random-teams-root`, `--random-team-share`, `teams.load_root`, `teams.combine`, `teams.corpus_provenance`). Every corpus team is checked by the library, and a refused one stops the run. The provenance goes into the run's config and log. A resume keeps the corpus and refuses another; it may change the share, and its log line records the change. `teams.load_corpus` reads the pool and its provenance from one read of index.json, and `teams.check_disjoint` refuses a team id in two corpora.
- **Done (this PR):** the widening smoke. An encoder 4 network in params-49333's layout widens to encoder 6 with equal outputs and trains one update.
- **M11:** the BC dataset re-encoded with encoder 6, with Bo1 and pick hypotheses only after their positive check, and the BC prior trained from it.
- **M12:** the second evaluation pool in `eval_manifest` (with `teams.check_disjoint`), and the head-to-head report of E1 and E2: the scoring above (unresolved games 0.5), the two-level cluster bootstrap and the consistency check.
- **At the restart:** generate both corpora from the training commit, so the library that judges them is the one that trains. Fix the budget, the corpus sizes, the training seeds and the bootstrap seed in the plan's amendment. Get the owner's go.
