# Random teams in self-play: the A/B plan (lever 17)

**Status:** plan, owner decision of 2026-10-10. Training restarts at 85 % game coverage (68.8 % on 2026-10-10), with encoder 6, the new replay data and the random teams. Nothing here runs before then. The infrastructure (the pool, the provenance, the widening smoke) is in place already. The endpoints below are fixed before any run, and no pair is added afterwards.

**Question:** does a share of self-play games with random Champions teams (tools/reference/random_teams.py) make the network generalize to teams it never trained with, without costing strength on the registry teams it plays today?

## Arms

All arms share the same commit, encoder 6, seed, recipe, initial network and compute budget.

| Arm | Team pool | Start |
| --- | --- | --- |
| **A** | the registry pool (the 652 LL_ teams of the 49333 training pool, their weights) | BC prior from the new replay data, encoder 6 |
| **B** | A's pool, joined by a training corpus at `--random-team-share 0.25` | the same BC prior |
| **C** (option) | A's pool | params-49333 widened to encoder 6 (`checkpoint.load_current`), no BC |

- **Share.** 0.25 is the probability that a side's team comes from the corpus. Sides are drawn independently, so 43.75 % of games have at least one random team and 6.25 % have two.
- **Arm C** separates the BC prior's effect from the random teams' effect. It is optional: it costs a third more compute, and the owner decides at the restart whether it runs.
- **Recipe:** run 3's, i.e. PPO, magnet KL 0.05 refreshed every 500 updates, PFSP league, entropy 0.01, encoder 6 with the library's mask `& version_features(6)`, and the ledger on.
- **Budget:** one compute ledger per arm, stopped at the same CPU core-seconds and GPU-seconds. Both arms run the same device shares (no budget_match: the arms are symmetric). The budget is set at the restart from the coverage-era throughput, and the plan's amendment states it before the run.
- **Training corpus:** pin, seed and count are fixed at the restart (for example 2048 teams, seed `0x2026101100000017`). The run records its provenance: pin, seed, count, and the sha256 of index.json and manifest.json.

## Evaluation (fixed before the run)

- **Held-out corpus.** A second random_teams.py corpus with another seed (for example `0x2026101100000018`, 512 teams), never in any training pool. Its provenance goes into the evaluation manifest. M12 extends `duoforge_search.eval_manifest` by a second pool.
- **Games.** Paired seeds and block seeds as in expert_eval: both seats, both arms on the same team pairs.

### Endpoints

- **E1, primary (generalization):** B against A, head to head, on held-out corpus teams (both sides drawn from the held-out corpus), 4096 pairs. B **passes** if the lower bound of the 95 % interval of B's score is above 0.5.
- **E2, primary (non-inferiority):** B against A, head to head, on registry teams (LL_ pool, its weights), 4096 pairs. B **passes** if the lower bound of the 95 % interval of B's score is at or above **0.48**. That is the non-inferiority margin: B may lose at most 2 points of score on the registry.
- **S1, secondary:** each arm against the ladder (params-39400) and against params-49333 on registry teams, 1536 pairs each. This is reported and is not a gate.
- **S2, secondary (with C):** C against A on both pools, the same sizes as E1 and E2. This is the BC prior's effect; reported only.

### Decision

- **Both E1 and E2 pass:** random teams go into the default training pool at 0.25. A larger share is a new plan.
- **E1 passes and E2 fails:** report, and let the owner choose (a smaller share or a schedule). No promotion.
- **E1 fails:** no promotion. The infrastructure stays (it costs nothing unused).
- No pairs are added after the endpoints are read. A compute mismatch above 5 % between the arms makes the run incomplete (re-plan), as in P1.

## Prerequisites (before the restart)

- **Done (this PR):** the pool takes a random corpus (`--random-teams-root`, `--random-team-share`, `teams.load_root`, `teams.combine`, `teams.corpus_provenance`). Every corpus team is checked by the library, and a refused one stops the run. The provenance goes into the run's config and log. A resume keeps the corpus and refuses another.
- **Done (this PR):** the widening smoke. An encoder 4 network in params-49333's layout widens to encoder 6 with equal outputs and trains one update.
- **M11:** the BC dataset re-encoded with encoder 6, with Bo1 and pick hypotheses only after their positive check, and the BC prior trained from it.
- **M12:** the second evaluation pool in `eval_manifest`, and the head-to-head report of E1 and E2 with their intervals.
- **At the restart:** generate both corpora from the training commit, so the library that judges them is the one that trains. Fix the budget and the corpus sizes in the plan's amendment. Get the owner's go.
