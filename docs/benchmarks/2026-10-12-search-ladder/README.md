# The search ladder (issue #440): design and gates, step 0

**Question (owner, 2026-10-12).** With the networks fixed, how much playing strength does each improvement of the search add on its own, and where does the curve flatten?

This document is committed before any measurement of the ladder. Each later step adds its own section here, also before its run.

## Fixed for every step

- **Networks:** private, aggregates only.
  - Main network and foe model: M11's BC6 (`bc6-M`, encoder 6). It plays, searches and models the foe (`Honest(foe_net=BC6)`).
  - Opponents, each played raw and greedy:

    | name | network | role |
    |---|---|---|
    | `bot` | `bc6-bot-M` (held-out players, disjoint from BC6's training data) | main opponent |
    | `bc6` | BC6 itself | identical to the foe model, so the foe model knows this opponent exactly |
    | `ppo` | params-49333 | a non-human-like bot; reported, not gated (HauptSession) |
- **Teams:** 49333's pool, 652 teams, because BC6 has no pool of its own.
  - 1024 team pairs from seed `0x2026101200000440`.
  - Each pair is played twice, with the teams and seats swapped.
  - Every arm plays the same games: the same suite rows, on the same batch seed.
- **Tool:** `python -m duoforge_search.ladder` (this branch). One root per decision call, with each decision's wall time measured. A searching arm leaves the opponent's team out of the spread table.
- **Machine:** the local PC under `tools/ci/machine_lock.sh`. Strength runs share the machine. Latency runs hold it alone (`--exclusive`). No AWS.

## Gates for every step N ≥ 1 (`ladder.GATES`, `ladder.verdict`)

| gate | rule |
|---|---|
| strength | head-to-head, step N against step N−1, both searching: the 95% lower bound of N's score, bootstrapped over team pairs, is **above 0.50**, and **no head-to-head game is unresolved** |
| no harm | against `bot` and against `bc6`, paired against step N−1 on the same games: the 95% upper bound of h is **at least 0.50**. Both opponents must be measured |
| reproduced | for each gated opponent, step N−1 rerun on step N's code plays exactly its recorded games: the per-game scores **and** a digest of every decision match (`--previous-run`) |
| fallbacks | **per gated opponent**: its raw fallbacks are at most **5%** of its non-team decisions, or at most its N−1 share plus 1 point where N−1 is above 5% |
| latency | p99 wall seconds per searched decision **≤ 2.0** in the exclusive latency run (`--latency-run`, same step and commit). Without that run the verdict is **pending** and `adopt` is None |
| errors | none: a SearchError stops the run, and a stopped run gives no verdict |

**Tightened after the harness review of PR #445 (2026-10-12), before any step-1 result was known.**
- Strength also needs 0 unresolved head-to-head games: evaluate scores an engine-refused or untiebreakable game as the learner's loss, and the learner is the step.
- Fallbacks are gated per gated opponent, not pooled: pooling over `ppo` could hide a regression against `bot`. The pooled share is reported.
- Reproduced compares the per-game scores and a digest of every decision, not the scores alone.
- Latency comes from the exclusive run (`verdict RUN/ladder.json --latency-run LATENCY/ladder.json`); `adopt` stays pending without it.

**A step that misses the strength gate** is still reported, with its point estimate and its interval. No measurable gain is not the same as no gain.
- In close cases, the step is rerun with 2048 pairs if the machine is free.
- The next step stacks on the last adopted step (the M13 exit rule), unless the owner decides otherwise.

**Reported without a gate:**
- the `ppo` opponent;
- the refused-leaf share (#436);
- a local check against the foreign random bot on the pinned Showdown. BC6 already wins 97–100% there, so it only catches regressions;
- nessie123's agreement and value loss with the replay-analysis tool. BC6 saw nessie's games in training, so only the change between steps is meaningful;
- a small sanity arm on the PKMN Arena teams;
- PKMN Arena results, as aggregates from HauptSession.

## Step 0: the baseline

**Settings:** today's live search, unchanged:
- `HONEST_SETTINGS`: K = M = 8, 16 worlds, rule mix with λ = 0.5, `species_prior` "count", capacity 1024;
- the live spread table, which takes the Smogon rows from #439;
- BC6 as the foe model.

**Runs:**
1. **Strength:** `--step 0 --raw` against `bot`, `bc6` and `ppo`, 1024 pairs. Arm R (BC6 raw) is paired with the search game by game, so the curve starts at raw play.
2. **Latency:** `--step 0` against `bot`, 16 pairs, under `--exclusive`.

Step 0 has no previous step and no strength gate. **Its checks:**
- fallbacks ≤ 5%;
- p99 ≤ 2.0 s;
- no errors.

Step 0 against R is reported, paired with its 95% interval, as the first point of the curve.

## Results

### Step 0 (2026-10-12)

**Checks: all hold.**

| check | rule | result |
|---|---|---|
| fallbacks | ≤ 5% | 2.3–2.7% |
| latency | p99 ≤ 2.0 s (exclusive run) | **0.123 s** |
| errors | none | none: every game finished, none unresolved |
| refused leaves | reported | **0** of 50,944,384 |

**Search against raw play.** The table is per opponent: 2048 games per arm, 1024 team pairs. h is the search's paired score against arm R, BC6 raw, on the same games.

| opponent | search (step 0) [95%] | raw (R) [95%] | h, search against R [95%] |
|---|---|---|---|
| `bot` (bc6-bot-M) | **0.863** [0.848, 0.878] | 0.809 [0.792, 0.825] | **0.527** [0.518, 0.537] |
| `bc6` (the foe model itself) | 0.698 [0.679, 0.715] | 0.500 [0.484, 0.514] | 0.599 [0.588, 0.611] |
| `ppo` (params-49333) | 0.471 [0.450, 0.492] | 0.349 [0.329, 0.369] | **0.561** [0.548, 0.574] |

- **Against the held-out bot**, the search gains 5.5 points of score over raw play.
- **Against `bc6`** the gain is larger, but the foe model is that opponent exactly, so this row is an upper bound.
- **Against 49333**, a PPO network and not human-like:
  - BC6 raw loses: 0.349, consistent with the earlier raw head-to-head of 49333 against BC6, 0.618 for 49333.
  - The search with BC6 as foe model still gains 12 points.

**The search's decisions** (step arm, per opponent):

| | `bot` | `bc6` | `ppo` |
|---|---|---|---|
| searched | 19,404 | 18,729 | 18,372 |
| forced / team | 906 / 2048 | 1219 / 2048 | 1452 / 2048 |
| unreconstructible, played raw | 572 (2.7%) | 477 (2.3%) | 528 (2.6%) |
| … of which visible sleep / visible confusion | 182 / 31 | 171 / 12 | 220 / 46 |
| search changed the raw choice | 76.1% | 75.1% | 74.4% |
| foe-menu coverage | 0.80 | 0.80 | 0.80 |

- **Fallbacks.** Every one is a public record the engine does not support (`DUOFORGE_E_UNSUPPORTED: public record`). About a third of them come from a visible sleep, about 1% of all decisions.
  - #442 makes the hidden sleep counter an exact two-value belief. It is a candidate step of its own.
- **Latency**, exclusive run: step 0 against `bot`, 16 pairs, 295 searched decisions.
  - p50 / p95 / p99 / max: 0.048 / 0.056 / 0.123 / 0.633 s. The maximum is the first decision's compile.
  - In the shared strength run, p99 was 0.10–0.19 s, with a single maximum of 10.5 s while the machine was shared.
- **Run time:** about 20 min per searched arm and 30–45 s per raw arm, on two shared lock slots. 64 min in all, 15:40–16:44.

**Provenance.**
- **Code:** search/0-baseline at 1cb3e2d9, which is main 7f9ee4da's content plus the harness; the run recorded `dirty: false`.
  - The PR head also merges #443 (refused leaves `"drop"`); with 0 refused leaves in step 0 it decides bit for bit as the measured code.
- **Library:** the WSL Release build of main's C (library 0.45.0), JAX on the CPU, AMD Ryzen 7 5800X.
- **Spread table:** `5f079072…`. 256 of the 2048 games' opponent teams are in it, and each was left out of the belief for its game.
- **Networks** (SHA-256 prefixes): BC6 `bda5de8e4e96`, bc6-bot-M `213b773b3448`, params-49333 `ef1abe65f637`.
- **Raw output:** `ladder.json` and the decision records stay private, outside the repository.
