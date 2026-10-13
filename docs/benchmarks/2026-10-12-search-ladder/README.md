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

**Tightened after the harness review of PR #445 (2026-10-12).** This was before any result of step 1's gated runs was known. Only the ungated sanity arm on one arena matchup was in at that point. Every change makes a gate stricter:
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

## The preview width, arm 1bw (owner, 2026-10-13; predeclared)

**Why.** In the sun-team sanity arm the preview search never changed our four, and it could not have: its top 8 tuples
were 4 orderings each of only 2 bring-and-lead combinations, and none brought Gholdengo. This arm widens the candidates
only. The rule stays step 1b's.

**Change** (`preview_width` "distinct", `preview.distinct`), on step 1b (turn-1 rollout, foe seat played by BC6, best
answer):
- **A combination** is the lead pair and the pair behind it, each unordered: 90 of the 360 tuples' orderings. Its
  probability is the sum over its 4 orderings, and its tuple is the likeliest ordering.
- **Own candidates:** the 8 likeliest combinations, then, for each team member none of them brings, the likeliest
  combination that brings it. Every member is brought by at least one candidate; 8 combinations bring at least 4 members, so k' is 8 to 10.
- **Foe candidates:** the 8 likeliest combinations of the foe model's world-weighted preview, without the cover; each
  world's probability of a column is its combination's.
- The raw choice and the record's `raw` stay the team head's top tuple.

**Correction (review of #462, 2026-10-13).** Merging the 4 orderings also merges the two lead seats (Raichu left and
Milotic right against the reverse). The seats are separate positions in battle and in the network's input, so this is
an approximation, an assumption no test checks, not an equality of the evaluator. Only the bench order was meant to
merge. 1bw's results below measure this approximation. Before 1bw is switched on, a corrected width that merges the
bench order only is a new arm, measured again on the ladder and in the mirror touchstone (owner).

**Runs, after the machine is free:**
1. **Gated:** `--step 1bw --previous 0 --h2h --previous-run <step 0's ladder.json>` against `bot`, `bc6` and `ppo`, 1024
   pairs, then its exclusive latency run (16 pairs against `bot`).
2. **Touchstone (#458):** `--matchup <Team A> <the Nationals sun team, its stated stat points> --step 1bw --previous 0
   --raw`, 256 pairs, `bot` and `ppo` as the sun team's pilots. Reported: 1bw against step 0 and against R per pilot,
   and our four and leads decoded from the records, with how often Gholdengo and Staraptor are brought.
   The private team file states no genders, which `teams.check` refuses by name (`DUOFORGE_E_INVALID_ARGUMENT`); the
   genders are stated in the file before this run, never filled by the harness.

**Criteria, fixed now.** 1bw passes when:
- every gate of the table above holds unchanged against step 0 (strength, no harm, reproduced, fallbacks, latency p99
  ≤ 2.0 s); and
- on the touchstone, 1bw against step 0 is not harmful for either pilot: its upper bound is at least 0.50.

Passing makes it a PR: the live settings then take the preview of 1bw. A failed strength gate means no adoption, as for
steps 1 and 1b, whatever the touchstone shows. For live play the VPS bound applies on top: exclusive p99 ≤ 1.67 s.
The book's preview oracle (#458) measures in parallel how much any bring-and-lead choice can gain against that team.

## The budget step (owner, 2026-10-12)

**Question.** With everything else of the search unchanged, how much strength does more search budget alone bring, and
where does the curve flatten? This section is a predeclaration: it is committed before any budget run. The runs are
`--step b-*` with `--paired-with` against step 0's recorded run.

**The arms.** Each arm is one lever or one fixed combination of step 0's settings (K = M = 8, s = 16, capacity 1024).
Its budget is k · m · s leaves, relative to step 0's 8 · 8 · 16 = 1024, and its capacity is k · m · s, so the leaf
buffer matches the leaves. The S arms are the arms with an s lever.

| arm | lever | budget (× step 0) | pairs | opponents |
|---|---|---|---|---|
| `b-s32` | s = 32 | ×2 | 512 | `bot`, `ppo` (S arm) |
| `b-s64` | s = 64 | ×4 | 512 | `bot`, `ppo` (S arm) |
| `b-s128` | s = 128 | ×8 | 256 | `bot`, `ppo` (S arm) |
| `b-s256` | s = 256 | ×16 | 256 | `bot`, `ppo` (S arm) |
| `b-k16` | k = 16 | ×2 | 512 | `bot` |
| `b-m16` | m = 16 | ×2 | 512 | `bot` |
| `b-km16` | k = m = 16 | ×4 | 512 | `bot`, `ppo` |
| `b-km16-s64` | k = m = 16, s = 64 | ×16 | 256 | `bot` (the costliest arm; `ppo` covers the S arms and b-km16) |

**The pairing.** Each arm is paired by prefix with step 0's recorded run (`--paired-with`), not replayed against it.
- The arm plays this run's games, and its `step_vs_recorded` is the paired h against step 0's step arm on the first
  2 · pairs games of that run, the same seed, networks, pool and spread table.
- Before any game, the run is refused unless: `seed` and `max_steps` equal; the recorded `pairs` is at least this run's;
  the `sha256_prefix` of main, foe, teams and each opponent equals the recorded one; the recorded run has a step arm for
  each opponent with at least 2 · pairs games; and `table_sha256` equals the recorded one.
- The recorded run's arm R is not used.

**The latency.** Each arm is also run alone on the machine (`machine_lock.sh --exclusive`), with 16 pairs against `bot`.
The gate reads the p99 of that run's `arms.step.wall_seconds`.

**The gate.** Local p99 ≤ 1.67 s, which is ≤ 5 s on the VPS, whose cores are about 3× slower. An arm above the gate is
reported with its point, but is not a candidate for adoption.

**Reported, without a gate:**
- the paired h against step 0 with its 95 % interval, per opponent;
- p50, p95 and p99 of the wall seconds per searched decision, local and ×3 for the VPS;
- the duplicate-row share per arm: `duplicate_rows.share` over the searched decisions, by value (rows that repeat an
  earlier row of their own table within 1e-6). A hint of redundancy in the search, not an equivalence proof.

**The result** is a curve: h against step 0, over the p50 seconds per decision, one line per lever. A smoke run of 4
pairs checks the harness only and is not a result.

## The mirror touchstone for 1bw (owner, 2026-10-13; predeclared before any run)

**Why.** 1bw passed every ladder gate, but on the Nationals touchstone it lost 0.480 [0.469, 0.492] against step 0
with `bot` as the sun team's pilot. Neither sim pilot plays that team well (see the sanity arm). The owner's
decision: 1bw lands on main as an option, switched off, and it is switched on live only if it passes this run, where
the live search pilots the sun team.

**Run.** `--matchup <Team A> <the Nationals sun team> --mirror --step 1bw --previous 0`, 512 pairs, seats alternating.
- **The mirror pilot:** the sun team is played by the live search: step 0's settings, with the same main network, foe
  network and spread table as our side. A new mirror searcher is made for each arm, so both arms meet the same pilot
  on the same seeds.
- **No leaked spreads:** the mirror's spread table leaves out Team A's registry entry (A is one of the table's
  sources), as a head-to-head leaves out the foe's team. Our side's table has no entry for the sun team.
- **Paired:** 1bw against step 0, on the same games against the mirror.
- **Reported, not gated:** the scores per arm, our four and leads decoded from the records, and the fallback shares of
  both sides.

The run started at 15:47 measures 1bw as merged, lead seats included. After the correction above it is reported,
but it no longer decides alone. The corrected width is measured in its own mirror run.

**Criterion, fixed now:** no measurable harm. The upper bound of the 95% interval of 1bw against step 0 must be at
least 0.50.
- **Pass:** a small PR switches 1bw on live (`preview_mode` "turn1", `preview_rule` "ev", `preview_width` "distinct").
  Its exclusive latency (p99 1.085 s) is already under the VPS bound of 1.67 s, and its preview LP (at most 10 × 8 × 16:
  20,124 tableau cells) is under the size limit.
- **Fail:** 1bw stays an option, switched off.

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

### Step 1 (2026-10-12): the team preview as a Nash game; no measurable gain

**Verdict: strength misses its gate narrowly; every other gate holds. Step 1 is not adopted.**

The run predates `ladder verdict`'s count fields, so the verdict was first computed by hand. Since the old-report fix
(`search/verdict-old-reports`), `ladder verdict` reads the report: it gives the same gates, adds the latency from the
exclusive run, and reports no pooled fallback share (the old report has no counts to pool).

| gate | result |
|---|---|
| strength: head-to-head, step 1 against step 0 (1024 pairs) | **0.519 [0.498, 0.538]**, 0 unresolved. The lower bound is not above 0.50 |
| no harm: step 1 against step 0, paired | `bot` 0.499 [0.489, 0.508]; `bc6` 0.512 [0.501, 0.523] |
| reproduced: step 0 rerun on step 1's code | identical per-game scores **and** decision digests, for `bot`, `bc6` and `ppo` |
| fallbacks | `bot` 2.3% (step 0: 2.7%); `bc6` 2.2% (2.3%) |
| latency: exclusive run, 16 pairs against `bot` (2026-10-13) | **p99 0.102 s**, passes (p50 0.055 s) |

**Scores per opponent (2048 games each):**

| opponent | step 1 | step 0 |
|---|---|---|
| `bot` | 0.860 | 0.863 |
| `bc6` | 0.721 | 0.698 |
| `ppo` | 0.475 | 0.471 |

- `ppo`, paired: 0.502 [0.489, 0.513].
- The step arm had one unresolved game each against `bot` and `bc6`. These are engine-refused games, scored as the step's loss.

**Diagnosis.** It comes from the ungated sanity arm and the preview records:
- **The Nash solution is pure.** In the sanity arm it had support 1 in every game, so the step plays the best answer of BC6's value head.
- **The worlds play no part.** The value head reads the searcher's public view, which holds no hidden spreads before turn 1. A cell's spread over the worlds is 0.
- **The candidates are half duplicates.** The top-8 team tuples come in pairs the network cannot tell apart (the same bring-four and leads, the bench order swapped). In effect there are 4 candidates.
- **Sanity arm, Team A against an arena sun team (512 games):** step 1 against step 0 h 0.478 [0.466, 0.489] (`bot`) and 0.462 [0.443, 0.481] (`ppo`). This is one fixed team decision replicated 512 times (n = 1), not a general effect.

**What follows:**
- **Step 1b:** the turn-1 rollout, its foe seat played by the foe network, with the best answer. #241 measured this as the only preview form with a gain. It is measured next.
- **Preview dedup:** the plan was to deduplicate the team candidates only where the evaluator cannot tell them apart.
  Arm 1bw below does not do that (correction, review of #462): it merges the lead seats too, an approximation.
- A rerun of step 1 with 2048 pairs is optional. 1b supersedes it as the preview step.

**Provenance.**
- **Code:** search/1-preview-nash at 1b2e5964; the run recorded `dirty: false`.
- **Run:** 16:49 to 20:29, two shared lock slots.
- **Raw output:** private, outside the repository.

### Step 1b (2026-10-12/13): the turn-1 rollout with the foe network; no measurable gain

**Change.** Step 0 plus a team preview by the turn-1 rollout (`preview_mode` "turn1"), whose foe seat is played by the
foe network (BC6), played by the best answer (`preview_rule` "ev"). Turns stay as in step 0.

**Verdict (`ladder verdict`): strength misses its gate narrowly; no harm, reproduction and fallbacks hold. Step 1b is
not adopted.** The exclusive latency run is queued behind the budget arms; it cannot change the verdict.

| gate | result |
|---|---|
| strength: head-to-head, step 1b against step 0 (1024 pairs) | **0.517 [0.497, 0.535]**, 0 unresolved. The lower bound is not above 0.50 |
| no harm: step 1b against step 0, paired | `bot` 0.497 [0.488, 0.506]; `bc6` 0.516 [0.506, 0.528] |
| reproduced: step 0 rerun on step 1b's code | identical per-game scores **and** decision digests, for `bot`, `bc6` and `ppo` |
| fallbacks | `bot` 2.5% (step 0: 2.7%); `bc6` 2.2% (2.3%); `ppo` 2.5% (2.6%, not gated) |
| latency | pending (exclusive run queued). In the shared run, p99 was 0.94–1.09 s, against 0.13–0.19 s for step 0 |

**Scores per opponent (2048 games each):**

| opponent | step 1b | step 0 | step 1b against step 0, paired |
|---|---|---|---|
| `bot` | 0.857 | 0.863 | 0.497 [0.488, 0.506] |
| `bc6` | 0.730 | 0.698 | 0.516 [0.506, 0.528] |
| `ppo` | 0.481 | 0.471 | 0.505 [0.493, 0.517] |

- `bc6` is the foe model and the rollout's foe seat at once, so its row is an upper bound, as in step 0.
- The step arm had one unresolved game against `bc6`, an engine-refused game scored as the step's loss.
- **Cost.** The preview rollout is the expensive decision: it lifts the shared run's p95 from about 0.11 s to
  0.68–0.86 s, and the step arm took about 3,000–3,400 s per opponent against 1,500–1,800 s for step 0.
- **Reading.** Two preview forms (step 1, Nash on the value head; step 1b, the best answer on the turn-1 rollout) both
  land at about +0.02 head-to-head with the lower bound at 0.497. Neither is a measured gain.

**Provenance.**
- **Code:** search/1b-rollout at 7db476a6; the run recorded `dirty: false`.
- **Run:** 19:09 to 01:01, two shared lock slots.
- **Raw output:** private, outside the repository.

### Sanity arm 1b: Team A against the arena sun team (2026-10-13)

`--matchup` with our Team A against the sun team of the live arena (members without stat points take their Smogon
spread), `--step 1b --previous 0 --raw`, 256 pairs against `bot` and `ppo` as the sun team's pilots. Ungated.

| opponent (pilot of the sun team) | step 1b | step 0 | raw (R) | 1b against 0 | 1b against R |
|---|---|---|---|---|---|
| `bot` | 0.977 | 0.977 | 0.906 | 0.500 [0.500, 0.500] | 0.535 [0.521, 0.550] |
| `ppo` | 0.945 | 0.945 | 0.998 | 0.500 [0.500, 0.500] | **0.474 [0.463, 0.483]** |

**Step 1b plays every game exactly as step 0.** In 1024 preview decisions (both arms, both pilots, both seats) the
search changed the raw choice 0 times:
- **Our four, every game:** lead Raichu + Milotic, back Rillaboom + Ceruledge. Staraptor (immune to Ground) and Gholdengo
  (immune to Poison) are never brought, the same choice as on the arena, where we lost 7:13 with it.
- **The candidates cannot do anything else.** The top 8 of BC6's team head are 4 distinct sets, each twice with the bench
  order swapped: lead Raichu + Milotic or Milotic + Raichu, Milotic + Staraptor or Staraptor + Milotic, always with
  Rillaboom + Ceruledge behind. No candidate brings Gholdengo. BC6's prior is flat: the best tuple has 0.036.
- **The opponent's lead is one per pilot,** since both pilots play the preview greedily and every game has the same two
  teams (reconstructed from the networks' greedy preview on the suite's batch, t = 0; the decision records hold our
  choices only). `bot` leads the sun + sleep pair (Charizard + Venusaur, back Incineroar + Toxapex) in all 512 games;
  `ppo` leads Sylveon + Charizard (back Garchomp + Venusaur) in all 512. A split by the opponent's lead is therefore the
  split by pilot above.
- **The predeclared extra arm** (the foe's preview fixed to the sun + sleep lead) is not needed for `bot`, which plays that
  lead always. For `ppo` it would be; it needs a fixed-preview opponent in the harness, not built yet.

**Search against raw with `ppo` as the pilot: 0.474.** The search loses 28 games that raw play wins and wins 1 that raw
play loses. Two facts from the step arm's records:
- **Visible sleep:** 16.6% of the searcher's decisions against `ppo` (12.4% against `bot`) are unreconstructible and played
  raw (`visible_sleep`), against about 1% in the pool runs. This matchup sits far above the 5% fallback gate. #442 / PR
  #459 is the fix to measure here.
- In the lost-but-raw-won games, the search changed the raw choice in 87% of its searched decisions (78% over all games).

**Representativeness.** In the simulator Team A wins 95–98% against the sun team; on the arena we lost 4:15 against
MoccaOTS's own bot. Neither sim pilot plays the sun team well, so this arm says nothing yet about the arena loss. The
touchstone (#458) needs a stronger pilot: at least our own search with that team (a mirror arm).

**Provenance.** search/1b-rollout at 7db476a6, 01:01 to 01:33, p99 0.72 s in the shared run. Team files and raw output
stay private; the report records the teams' SHA-256 prefixes only.

### Arm 1bw (2026-10-13): the preview width; ladder gates hold, the touchstone criterion fails

**Change.** Step 1b with `preview_width` "distinct" (see the predeclaration above).

**Ladder verdict (`ladder verdict` with the exclusive latency run): every gate holds.** It is the first arm whose
head-to-head lower bound is above 0.50.

| gate | result |
|---|---|
| strength: head-to-head, 1bw against step 0 (1024 pairs) | **0.554 [0.534, 0.574]**, 0 unfinished, 0 unresolved |
| no harm: 1bw against step 0, paired | `bot` 0.500 [0.490, 0.509]; `bc6` 0.523 [0.511, 0.535] |
| reproduced: step 0 rerun on 1bw's code | identical per-game scores and decision digests |
| fallbacks | `bot` 2.7% (step 0: 2.7%); `bc6` 2.4% (2.3%); `ppo` 2.5% (2.6%, not gated) |
| latency | exclusive p99 **1.085 s** (≤ 2.0 s; also under the VPS bound of 1.67 s). Shared run: 1.58 s |

| opponent | 1bw | step 0 | 1bw against step 0, paired |
|---|---|---|---|
| `bot` | 0.862 | 0.863 | 0.500 [0.490, 0.509] |
| `bc6` | 0.743 | 0.698 | 0.523 [0.511, 0.535] |
| `ppo` | 0.498 | 0.471 | 0.514 [0.501, 0.527] |

**Touchstone (#458): Team A against the Nationals sun team, 256 pairs. The criterion fails for the `bot` pilot.**

| pilot of the sun team | 1bw | step 0 | raw (R) | 1bw against 0 | 1bw against R |
|---|---|---|---|---|---|
| `bot` | 0.943 | 0.982 | 0.961 | **0.480 [0.469, 0.492]** | 0.491 [0.478, 0.505] |
| `ppo` | 0.938 | 0.938 | 0.934 | 0.500 [0.485, 0.516] | 0.502 [0.489, 0.515] |

- **Our four, every game (both pilots, both seats):** 1bw leads Raichu + Milotic with Ceruledge + Staraptor behind;
  step 0 brings Rillaboom + Ceruledge behind the same lead. 1bw changes the raw choice in all 1024 of its preview
  decisions, always to this one set. Gholdengo is never brought; Staraptor is brought in every 1bw game.
- Against the `bot` pilot this swap costs about 4 points (0.982 → 0.943), and the upper bound 0.492 is below 0.50.

**Outcome by the predeclared criteria: 1bw does not pass.** The ladder gates hold, but the touchstone shows harm for
one pilot. The criterion is not changed after the run.

**The owner's decision (2026-10-13, #440):**
1. 1bw lands on main as an option, switched off. It merges the lead seats, an approximation (see the correction above). Without it the search is bit-identical to main:
   `test_the_default_preview_width_previews_as_on_main` pins main's previews, and the turn pins are unchanged.
2. It is switched on live only if it passes the mirror touchstone above, which was predeclared before its run.

**Provenance.**
- **Code:** search/preview-width at b3e1c0a2; both runs recorded `dirty: false`.
- **Runs:** gated 04:06 to 09:30, two shared lock slots; touchstone 04:06 to 04:55; exclusive latency 09:30 to 09:32.
- **Raw output:** private, outside the repository; team files are recorded by SHA-256 prefix only.

### The budget step (2026-10-12/13): interim, ×2 arms done

**Status.** The ×2 arms are done; b-s64 stopped with a named error; b-km16 is running; b-s128, b-s256, b-km16-s64 and
every exclusive latency run are queued. The curve's x axis needs the exclusive runs, so the wall seconds below come from
the shared strength runs and are not the gate's numbers.

| arm | budget | h against step 0, `bot` [95%] | h against step 0, `ppo` [95%] | duplicate-row share | shared p50 / p99 (s) |
|---|---|---|---|---|---|
| `b-k16` | ×2 | 0.490 [0.477, 0.503] | – | 9.4% | 0.131 / 0.52 |
| `b-m16` | ×2 | 0.496 [0.486, 0.506] | – | 6.6% | 0.114 / 0.27 |
| `b-s32` | ×2 | 0.500 [0.493, 0.508] | 0.492 [0.480, 0.503] | 7.1% (`bot`), 6.1% (`ppo`) | 0.131 / 1.55 (`bot`), 0.129 / 0.89 (`ppo`) |
| `b-s64` | ×4 | stopped (below) | stopped | – | – |

- **No ×2 arm moves the strength.** Every interval holds 0.50; `b-k16`'s point is the lowest. Fallbacks stay at
  2.4–2.9%, every game finished and none was unresolved.
- Read with steps 1 and 1b, this points to the evaluation (BC6's value head) as the limit rather than the search
  budget. The ×8 and ×16 arms decide it; the network-quality measurement is #451.

**b-s64 stopped with a named error, not a fallback.** In the `ppo` arm (the `bot` arm had finished):
`SearchError: the Bayesian simplex did not finish in 10000 iterations`. The chain in `matrix.solve_bayes`:
1. the float simplex gave an empty strategy;
2. the stable float retry missed the certificate narrowly (exploitability 1.8e-8 on a range of 1.8, 64 tables of 8 × 8);
3. the exact rescue (`_bland` on Fractions) starts at the origin, where all 64 · 8 world constraints are degenerate,
   and did not finish within `MAX_ITERATIONS` = 10,000 on its 513-row tableau.

The exact rescue is rare: 1 in about 10,000 searched decisions at s = 32 (1 against `bot`, 2 against `ppo`), and once
in s = 64's `bot` arm, where it finished. Its tableau grows with s (1025 rows at s = 128, 2049 at s = 256), so the
queued S arms above s = 64 will likely stop the same way, and a stop loses the whole run's report.

**b-km16 stopped the same way** (03:38, `ppo` arm; the `bot` arm had finished): 257 rows and 32 variables, although
`b-m16` (257, 24) and `b-s32` (257, 40), no smaller, finished. The stop is rare and not monotone in the size.

| arm | rows (s·m + 1) | variables (k + s) | tableau cells | result |
|---|---|---|---|---|
| 0 | 129 | 24 | 19,866 | never failed |
| `b-k16` | 129 | 32 | 20,898 | never failed |
| `b-m16` | 257 | 24 | 72,474 | finished |
| `b-km16` | 257 | 32 | 74,530 | **stopped** in the exact rescue |
| `b-s32` | 257 | 40 | 76,586 | finished |
| `b-s64` | 513 | 72 | 300,618 | **stopped** in the exact rescue |

Tableau cells are those of the exact rescue: rows × (variables + rows + 1).

**Decided (owner, #440, 2026-10-13): a size limit instead of a list of names.** A search whose Bayesian LP can exceed
**20,898 tableau cells** (b-k16's, the largest that never failed) is refused by name: by `honest.Honest` when it is
built, and for a ladder step before any network loads (`ladder.size_refusal`, `matrix.check_bayes_size`). Step 2's
width "slots" knows its pairs only at a decision, so there each table is checked before its solve. The arms above the
limit stay declared and are never run.

The literal "larger than the largest that succeeded" would admit `b-km16`, which is smaller than `b-s32` and failed.
Two consistent readings remain; this one takes the safe one:
- **b-k16's tableau (20,898 cells), implemented:** the largest size that never failed.
- **b-m16's tableau (72,474 cells), the owner's choice to make:** the largest success below the smallest failure. It
  would admit 2w (below).

Where the planned steps stand:
- **1bw** (preview: 129 rows, at most 10 + 16 = 26 variables, 20,124 cells) is under the limit.
- **2w** is not. Over the 1285 searched decisions of the arena logs its k' has median 19, p90 31 and maximum 34. Only
  33 % of the decisions stay at 16 own pairs or fewer, and k' = 34 is 23,220 cells. The solver repair comes before
  step 2's width arms; 2d, 2e and 2l are under the limit.
- **Live play** (8 × 8 × 16: 19,866 cells) is under the limit.

**Provenance.** search/budget at 25883412 (`dirty: false`), paired by prefix with step 0's run at 1cb3e2d9. 20:29 to
02:13 on two shared lock slots. Raw output private, outside the repository.
