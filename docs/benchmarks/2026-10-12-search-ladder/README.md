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
| strength | head-to-head, step N against step N−1, both searching: the 95% lower bound of N's score, bootstrapped over team pairs, is **above 0.50** |
| no harm | against `bot` and against `bc6`, paired against step N−1 on the same games: the 95% upper bound of h is **at least 0.50**. Both opponents must be measured |
| reproduced | step N−1, rerun on step N's code, plays exactly its recorded games (`--previous-run`) |
| fallbacks | raw fallbacks are at most **5%** of the non-team decisions, or at most N−1's share plus 1 point where N−1 is above 5% |
| latency | p99 wall seconds per searched decision **≤ 2.0** in the exclusive latency run |
| errors | none: a SearchError stops the run, and a stopped run gives no verdict |

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

## Step 1: the team preview as a Nash matrix game (#363)

**Change.** At team preview, the search solves the bring-four and lead choices of both sides as a Bayes matrix game. It plays the Nash mix (`preview_mode` "value", `preview_rule` "nash"); turns stay as in step 0.
- **Own candidates:** the top 8 of BC6's team head.
- **Foe candidates:** the top 8 of the foe model's team head, BC6, over the sampled worlds.
- **Payoff:** BC6's value after both previews and the entry effects.

Before this step, the team preview was raw by design. A foe network was refused with any preview search. Now it is refused only with the turn-1 rollout (`turn1`), whose rollout plays both seats with the main network.

**Prior evidence (#241, 49333, no foe network).**
- N-value against raw: +0.002 [−0.024, 0.029].
- E-turn1 gained +0.068 against raw self-play only, and nothing against the panel.

A small or no gain is the expected outcome here.

**Arms:**

| arm | `preview_rule` | role |
|---|---|---|
| 1 | nash | the step (#363) |
| 1e | ev | control: the best answer to the foe model, the form #240/#241 measured |
| 1x | mix (λ = 0.5) | control: the live turns' rule |

**Runs:**
- **Step 1:** `--step 1 --previous 0 --h2h --previous-run <step 0's ladder.json>` against `bot`, `bc6` and `ppo`, 1024 pairs. All gates of the table above apply. The gate "reproduced" checks that step 0's games on this code equal step 0's recorded run.
- **1e and 1x:** the head-to-head against step 0, and the paired arms against `bot`, 1024 pairs each. These are reported, not gated.
- **Latency:** step 1 against `bot`, 16 pairs, under `--exclusive`.

**Step 1b (later, HauptSession 2026-10-12).** E/N-turn1 with the foe network needs the rollout to play the foe seat with the foe network. That is not built yet. It is listed here, so that a lead choice that depends on the foe's turn 1 is tested after step 1.

## Results

(after the run)
