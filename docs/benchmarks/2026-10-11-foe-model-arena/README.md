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

Pending.
