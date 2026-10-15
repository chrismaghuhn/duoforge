# Live A/B test of the search's root rule

The owner decided this on 2026-10-14 (#385, issuecomment-6175931093). This file fixes the design and the analysis **before the deploy**. No rule is preferred before the minimum numbers below are reached.

## Why

Under the live search 2e, Ling-Ce went 1:13 against opponent A (bot commit `5c503d8a`), where step 0 had gone 15:30 (`1ffa6a03`). That comparison is not fair:
- Opponent A changed its team selection between the two periods. Step 0 always met A's Garchomp + Grimmsnarl lead. 2e met mostly the Charizard + Grimmsnarl lead.
- Our own team, bring and leads stayed the same in all 69 battles against A.

Only a comparison over the same time, battle by battle, separates the rule from the opponent.

## Design

- **Two arms, the root rule only.**
  - Arm `0` is ladder step 0: the root's mixed rule, λ = 0.5, exactly the settings of bot commit `1ffa6a03`.
  - Arm `2e` is ladder step 2e: the best answer, the live search since `a7dd956b`.
  - `duoforge_live.ab.check_arms` refuses to start unless the arms differ in `rule` alone and the live search's settings are theirs but the rule. The command line refuses the test without the pinned foe model BC6.
  - So the preview, the networks, the foe model, the worlds, the budget and the deadline are the same.
  - The honest search computes every rule's row at each decision; the rule only picks the row played.
  - One search plays both arms; each decision sets its battle's rule (`LiveSearch.decide(rule=...)`).
- **Allocation per battle, in blocks of two.**
  - The battles the bot plays with its `--team` are numbered in the order it opens them.
  - Block b (battles 2b and 2b + 1) plays one battle of each arm, in an order drawn from the run's seed and b alone (`ab.arm(seed, index)`).
  - The draw reads nothing of the opponent, the format or the battle.
  - A battle of another format draws no number.
- **Logged.**
  - The run log's head names the seed and both arms' settings (`ab_root_rule`), and the live search's settings (`search_settings`).
  - Each battle log's first record names its arm, its number, its rule and its settings (`search_rule`).
- **Started with** `python -m duoforge_live --server arena ... --search honest --team TEAM --ab-root-rule [--ab-seed N]`. Without `--ab-seed`, a new random seed is drawn and named in the run log.

## Analysis (fixed before the first battle)

The aggregates come from `tools/research/cts_live_eval.py --logs DIR --code COMMIT --labels PRIVATE.json`, under `ab_root_rule`. The HauptSession fixed the reading on 2026-10-14.

- **The outcome** is a battle's result from Ling-Ce's side. Only decided battles count: a win, a loss or a tie, with a tie counted as no win.
- **Intention to treat.** Every battle that names an arm counts in that arm, whatever happened in it. Each arm reports its battles by kind:
  - the decided ones;
  - the unfinished ones (a log without an end), counted apart;
  - those played without the search after a class (b) error (`without_search`).
- **Per arm:** the win rate with its Wilson 95% interval.
- **The difference** is 2e minus 0, with Newcombe's interval (method 10, from the two Wilson intervals; checked against his published example in the tests).
- **Read only at three fixed looks**, when both arms have **30, 60 and 100 decided battles**.
  - At 30 and at 60 the difference's **99%** interval counts; at 100 its **95%** interval.
  - A rule is preferred only when the interval of the look reached excludes 0. Before the first look nothing is read.
  - If the 95% interval at 100 still includes 0, the result is **"no measured difference"**.
  - The tool names the look reached (`look`) and that look's interval (`at_look`).
- **Strata are descriptive only.** The arms are also counted per opponent letter and per foe lead variant (the foe's two lead species, read from its switch lines before turn 1).
  - A stratum shows its win rates and an unpaired difference from 10 decided battles per arm on; below that, its counts only.
  - A stratum has no look and is never a ground for preferring a rule.
- **Power.** With 100 decided battles per arm and win rates near 50%, the 95% interval of the difference is about ±14 percentage points wide. A true difference of 13 to 15 points is therefore detected only about half the time; detecting one with 80% power needs about 20 points. A smaller difference stays "no measured difference".
- **Reports** hold aggregates only, opponents by letter, with the bot commit and dirty state, the run logs (seed) and the tool's commit.

### Opponents the search mostly cannot reach, and a deploy during the test (fixed after the technical check, before any look at results)

Fixed on 2026-10-14 (HauptSession, final) after the technical check of the first 30 battles: the allocation recomputed, the logging, no deadline. The check looked at no result, no win and no outcome.

- **The primary reading is intention to treat over all battles.** The looks of 30, 60 and 100 count every decided battle per arm, whatever its opponent, with the 99%, 99% and 95% intervals above.
- **Opponents the search mostly cannot reach are a descriptive stratum.**
  - An opponent's no-search share is its battles' non-team decisions answered without the search, out of all its non-team decisions. A decision without the search is one that is not `searched`: unreconstructible, forced, raw or deadline.
  - The share is computed **per opponent and bot commit, over both arms together**, never per arm, so the rule cannot change the classification. It is computed at each look.
  - Against an opponent above 50%, both arms play the raw policy at most of its points (#464: a particle holding unmodelled content), so the root rule can hardly act there.
  - These opponents are reported apart, with their counts per arm, as a description only. They stay in the primary reading and are never a ground for a preference.
- **Pooled across bot commits.** A deploy during the test (first main with #500, Speed Swap) does not start a separate series. The primary reading pools the commits, and the results are also reported per commit, as a description.
  - At a restart the bot draws a **new seed**, named in its new run log, and its blocks start anew from battle number 0.
  - A last block left incomplete before the restart, with one battle of one arm, is counted by name (`incomplete_blocks`). Its battle stays in its arm.
- **A replay of earlier battles on newer code is descriptive only**, for example the share of decisions that would have been searchable with Speed Swap modelled. It never enters the rule's reading.

### Sections by bot commit (addendum of 2026-10-15, before any look at results)

Fixed on 2026-10-15 (HauptSession), before the deploy of #558 (with the fuzzing fixes #517 to #522) and #512 D1/S1, and before any look at results. At that time the test held **15 decided battles in arm 0 and 15 in arm 2e**, all 30 on `c1f00e87`: the decided battles were counted per arm from the run logs (whether a log has an end line), without their outcomes, and no win rate was looked at. The bot has played no battle on `59d8a540` since its deploy (it plays on challenge only). This **replaces** the pooling across bot commits above:

- **Each bot commit is a section**, with its own seed and its own blocks from battle number 0. A last block left incomplete at a deploy is counted by name (`incomplete_blocks`); its battle stays in its arm and section.

  | Section | Bot commit | Decided battles at this addendum (arm 0 / arm 2e) |
  |---|---|---|
  | 1 | `c1f00e87` | 15 / 15 |
  | 2 | `59d8a540` | 0 / 0 |
  | 3 | `00931d3a` (#558 and D1/S1) | 0 / 0 |

  Section 3 began with the deploy of 2026-10-15, 06:58 UTC: bot commit `00931d3a50ed5b3a524c46dd94b562055c58029a` without local changes, library `5b3f7dae…`, run log `arena-run-20261015T065804Z`, seed `5548249904766606275`. The commit was entered here afterwards from the HauptSession's deploy message, without any look at results.

  A later deploy during the test starts a further section in the same way.
- **Reports** give each section on its own: per arm the decided battles and the win rate with its Wilson interval, and the difference with Newcombe's interval.
- **The overall estimate** is the difference **stratified by section** (Mantel-Haenszel):
  - Σ w_s (p2e_s − p0_s) / Σ w_s, with w_s = n0_s · n2e_s / (n0_s + n2e_s), over the sections with decided battles in both arms (n: decided battles of the arm in section s, p: its win rate, a tie counted as no win);
  - its interval is the normal one with variance Σ w_s² (p0_s (1 − p0_s) / n0_s + p2e_s (1 − p2e_s) / n2e_s) / (Σ w_s)², at the look's level: 99% at 30 and at 60, 95% at 100;
  - while only one section has decided battles in both arms, the reading is that section's Newcombe interval, as before.
- **The looks of 30, 60 and 100** count the decided battles **per arm over all sections**. A rule is preferred only when the look's interval (stratified, or Newcombe's while one section) excludes 0; "no measured difference" otherwise at 100.
- **Why:** #558 and D1/S1 change the engine's setup, the closed-sheet prior and the lines the tracker reads, and each deploy may change the bot's strength. Pooling the commits would mix such a change with the rule's effect.
- **The tool** (`cts_live_eval.py`, `ab_arms`) computes the stratified difference before the first look that spans more than one section.

## Replays of the test's battles

`cts.LogReplay` and `cts.replay` read the rule a battle's first record names (`cts.logged_rule`), so the KO check and the luck meter replay each battle under its own arm's rule. A decision without a rule plays the search's own (`LiveSearch.base_rule`), never a rule an earlier battle set.

## What this does not measure

- The preview: both arms play the same team selection, and its exploitability (Book, #458) is another question.
- Opponents that change during the test still meet both arms alike, because the allocation is per battle and in blocks. The per-lead strata show whether an arm only did well against one setup.
