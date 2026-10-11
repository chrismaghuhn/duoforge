# A human-like foe model in the live search (M7, 2026-10-11)

**Question.** Does the honest search play better against human-like opponents when a behaviour-cloned (BC) network models the foe instead of the search's own network?

Menu coverage (M4, ExIt plan #360) showed why this might help. On M11's held-out human decisions, the played joint action is in the foe menu (the top 8 pairs) of:
- 51.8% for 49333's policy;
- 70.8% for the BC prior mcmb-M.

The owner approved this measurement on 2026-10-11.

**The change.** `honest.Honest(..., foe_net=(model, params, encoder, ext_supported))` adds an optional second network.
- **What the second network supplies:** every policy call on the worlds goes to it, read through its own encoder. That covers the foe's team draw, its queued pair and its menu.
- **What stays with the main network:** the own candidates (the root's policy) and the leaf values.
- **The default is unchanged.** With `foe_net=None`, `test_bench`'s pin and the pinned A/B/C decisions of `test_honest` hold. Given the main network as its own foe network, the search decides bit for bit as without one (`test_the_main_net_as_foe_net_decides_bit_for_bit_as_without`).

## Design (fixed before the run)

- **Main network:** params-49333 (encoder 4), the live mode's network.
- **Search:** live settings (`HONEST_SETTINGS`: K = M = 8, 16 worlds, mix 0.5, species prior, capacity 1024) and the live spread table. The belief leaves the bot's own team out of the table.
- **Arms:**
  - **F:** the search with BC mcmb-M as its foe model (M11's encoder-3 BC prior, trained on Reg M-C and Reg M-B).
  - **M:** the search with 49333 as its own foe model, the live mode today.
  - **R:** context only. 49333's raw play.
- **Opponent of every arm:** BC mc-M played greedily (argmax), standing in for a human player.
  - The bot and the foe model are two networks; the tool refuses identical files.
  - **Limit:** mc-M was trained on Reg M-C only, and mcmb-M's training data contains mc-M's. The foe model therefore resembles this bot more closely than it resembles an unseen human. M11's new encoder-6 BC with a held-out-players split repeats the measurement once it is ready.
- **Games:** 1024 team pairs drawn from 49333's pool (652 teams) with seed `0x2026101100000707`. Each pair is played twice, with the learner's team and seat swapped. Every arm plays the same games: the same rows of `evaluate.play_suite`, on the same batch seed. Games are cut off after 1000 steps and scored by the tiebreak.
- **Timing:** the searcher decides one root per call, as the live mode does. Each decision's wall time is measured.
- **Run conditions:** the run holds the machine alone (`tools/ci/machine_lock.sh --exclusive`), on the CPU, locally. No AWS.
- **Tool:** `python -m duoforge_search.foe_arena --checkpoint params-49333.npz --foe-net mcmb-M/bc.npz --bot mc-M/bc.npz --out DIR --pairs 1024`

## Gates (predeclared; `foe_arena.verdict`)

F is adopted for live play only if every gate holds.

| gate | rule |
|---|---|
| strength | h = 0.5 + (score_F − score_M) / 2 over the paired games. The 95% interval comes from a bootstrap over team pairs (2000 resamples), and its **lower bound must be above 0.50** |
| latency | F's **p99** wall seconds per searched decision **≤ 2.0** (the live arena's gate) |
| fallbacks | F's raw fallbacks (unreconstructible decisions) **≤ 5%** of its non-team decisions. If M's own share is above 5%, F's share may be at most M's share + 1 point |
| errors | none. A SearchError stops the run, and a stopped run gives no verdict |

## Results

**Verdict: every gate holds, so F is adopted for live play by the predeclared rule.** The limit in the design above still applies: the foe model shares the bot's training data. Switching the live mode is a separate change.

| gate | rule | result |
|---|---|---|
| strength | lower bound of h > 0.50 | **h = 0.527, 95% [0.519, 0.536]** over 1024 pairs |
| latency | F's p99 ≤ 2.0 s | **0.084 s** |
| fallbacks | F ≤ 5% | **2.0%** (M: 2.1%) |
| errors | none | none: all 2048 games of every arm finished, none unresolved |

Per arm, against the bot BC mc-M (2048 games each):

| arm | score | searched | forced | team | unreconstructible (raw) | wall per searched decision p50 / p95 / p99 / max (s) | coverage |
|---|---|---|---|---|---|---|---|
| R: 49333 raw | 0.825 | | | | | | |
| M: search, 49333 as foe model | 0.839 | 17291 | 917 | 2048 | 398 (2.1%) | 0.061 / 0.072 / 0.088 / 0.93 | 0.956 |
| F: search, BC mcmb-M as foe model | **0.893** | 16606 | 792 | 2048 | 363 (2.0%) | 0.061 / 0.072 / 0.084 / 2.30 | 0.737 |

- **The gain.** Against this human-like bot, the search with its own network as the foe model gains 1.4 points over raw play, and the BC foe model gains 6.8.
  - Paired, F against M: h = 0.527, the same as 5.4 points of score.
- **Coverage.** This is the share of the foe model's own probability that its menu of 8 pairs holds. It is lower for the BC (0.74 against 0.96), because the BC spreads its probability over more pairs.
- **Latency.** Unchanged in the median and at p99, though F runs one more query and network call per decision.
- **Three slow decisions in F** took over 1 s (2.30, 1.80 and 1.67 s). M's slowest took 0.93 s.
  - The time went to the engine: the leaf expansion took 2.24 s and 1.74 s, and a world build took 1.61 s, where these usually take 4 ms and 8 ms.
  - The foe network takes part in neither step. Its network time in those decisions was 0.03 s, as usual. These outliers are an observation for the engine side and do not touch the gate.
- **Fallbacks.** In both arms they are mostly records the engine's public view does not support: 295 in M and 265 in F. The rest are redraws past the species prior.
- **Run time.** Arm M took 1144 s and arm F 1100 s, with the machine held alone.

## Provenance

- **Code:** m12/foe-net at f1fc1f84 (on main 1880d62f). The tool, the tests and these gates were committed there at 18:55, before the run. The branch was later rebased onto main as dd12bdb0, with the same content and author date.
  - The library was the Release build of that main.
  - `foe_arena.json` records `"commit": null`, because WSL git cannot resolve the Windows worktree's gitdir. The commit is recorded here by hand.
- **Run:** 2026-10-11, 19:04 to 19:44, under `tools/ci/machine_lock.sh --exclusive`.
- **Networks:** the foe model and the bot are distinct files (SHA-256 prefixes `a1e79e3e9b74` and `19bf1ef06d65`).
- **Spread table:** the live table, `91af704d…`. 264 of the 2048 games' bot teams are in it; they were left out of the belief for their game.
- **Raw output:** `foe_arena.json` and the decision records stay private, outside the repository, as do the networks. This report quotes aggregates only.

## What follows

1. **Repeat with M11's encoder-6 BC** with a held-out-players split, so the foe model has not seen the bot's training data. That measurement closes the limit above.
2. **The live switch is the owner's decision.** It would give `duoforge_live.search.load` the foe network as an option (a later PR); this PR changes no live default.
