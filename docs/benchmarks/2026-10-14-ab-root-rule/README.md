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
  - `duoforge_live.ab.check_arms` refuses to start unless the arms differ in `rule` alone and the live search's settings are theirs but the rule. The preview, the networks, the foe model (BC6), the worlds, the budget and the deadline are the same. One search plays both arms; each decision sets its battle's rule (`LiveSearch.decide(rule=...)`).
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

The aggregates come from `tools/research/cts_live_eval.py --logs DIR --code COMMIT --labels PRIVATE.json`, under `ab_root_rule`.

- **The outcome** is a battle's result from Ling-Ce's side. Only decided battles count: a win, a loss or a tie, with a tie counted as no win.
  - Battles that ended unfinished (a log without an end) are counted apart, per arm.
  - A battle stays in its arm whatever happened in it (intention to treat). A battle played raw after a class (b) error still counts, and the run logs count those errors per arm.
- **Per arm:** the win rate with its Wilson 95% interval.
- **The difference** is 2e minus 0, with Newcombe's 95% interval (method 10, from the two Wilson intervals).
- **Paired by stratum.** The same per opponent letter, and per foe lead variant (the foe's two lead species, read from its switch lines before turn 1).
  - The strata are where the arms meet the same opponent and the same setup.
  - A stratum is read only when both arms have its minimum (below).
- **Minimum numbers, before any preference:**
  - **Overall:** at least **30 decided battles per arm**.
  - **Per opponent letter or lead variant:** at least **10 decided battles per arm** before that stratum is read. A stratum below it is reported as a count only.
- **Preference:** a rule is preferred only when the overall difference's 95% interval excludes 0 at or after the minimum.
  - Otherwise the test goes on, up to 100 decided battles per arm.
  - If the interval still includes 0 then, the result is "no measured difference". The owner and the HauptSession then decide on other grounds.
  - A stratum whose difference points the other way, with its own interval excluding 0, is named in the report.
- **Reports** hold aggregates only, opponents by letter, with the bot commit and dirty state, the seed's run logs and the tool's commit.

## What this does not measure

- The preview: both arms play the same team selection, and its exploitability (Book, #458) is another question.
- Opponents that change during the test still meet both arms alike, because the allocation is per battle and in blocks. The per-lead strata show whether an arm only did well against one setup.
