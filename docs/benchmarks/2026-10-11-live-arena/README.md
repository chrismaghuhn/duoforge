# The live search in the live-path arena (issue #362, 2026-10-11)

**Question.** Does the honest search play better than raw play through the real live client, on the real server's timer, without breaking? This was the 75% gate's package 2 (owner, 2026-10-11).

**Answer.** Yes. Every predeclared gate holds:
- the search bot scores **0.658** against the raw bot, 95% interval **[0.613, 0.702]**;
- no crash, no class (b) error, no timer loss;
- raw fallbacks at **3.7%**;
- the decisions' p99 is **0.088 s**.

## Setup

- **Tool:** `python -m duoforge_live.arena` (#401). It runs on a local copy of the pinned Showdown server, started with `--no-security` and bound to the WSL host address only, with the battle timer on.
- **Bots:** two lanes. Each lane holds one search bot (the live mode: honest X, `HONEST_SETTINGS` with capacity 1024, the live spread table, species prior) and one raw bot. Both bots use the same network, params-49333. The network stays private.
- **Teams:** pairs drawn from the checkpoint's pool with seed `0x2026101200000362`. Each pair is played twice with the seats' teams swapped.
  - The pool was first validated with the pinned server's own team validator (`tools/live/validate_pool.js`).
  - 648 of its 652 teams are playable. Four importer (LL_) teams are refused for "0 Stat Points".
- **Games:** 400 planned, 400 played (200 complete pairs); 297 s wall.
- **Machine:** AMD Ryzen 7 5800X, WSL Ubuntu 24.04, JAX on the CPU. The run held the machine alone (`tools/ci/machine_lock.sh --exclusive`).

```
python -m duoforge_live.arena --checkpoint params-49333.npz --out DIR --games 400 --lanes 2 --host <WSL host> --valid-teams <validated ids>
```

## Gates (predeclared, `arena.GATES`) and results

| gate | rule | result |
|---|---|---|
| strength | 95% lower bound of the search bot's score (over the pairs' mean scores) > 0.50 | **0.613** (score 0.658, upper bound 0.702; 263 wins, 137 losses) |
| crashes | 0 internal-error forfeits or failed lanes | 0 |
| class (b) errors | 0 | 0 |
| raw fallbacks (a) | ≤ 5% of the search's decisions | 3.7% (143 of 3899) |
| deadline misses | ≤ 1% | 0 |
| tracker stops | ≤ 1% of the games | 0 |
| timer losses | 0 | 0 |
| p99 decision time | ≤ 2.0 s | 0.088 s |
| all planned games played | 400 of 400, no unfinished game, no incomplete pair | yes |

The search bot's 3899 decisions:

| kind | count |
|---|---|
| searched | 3755 |
| team selection (raw by design) | 400 |
| unreconstructible, played raw (class (a)) | 143 |
| forced (one legal pair) | 1 |

The team selections count once per game. They are outside the 3899 decisions the fallback share is taken over.

Decision times (all decisions): median **0.057 s**, p95 **0.073 s**, maximum **0.717 s**. The maximum is the first decision's compile.

## History of the run

1. **First attempt.** It found a class (b) error. The live tracker's pair mask is provisional, and it allowed a pair the engine refuses ("switch 3, switch 3").
   - Fix in #401: the own candidates come from the engine's domain of the worlds. A refused pair is counted as `cut_pairs` in the record.
2. **Second attempt.** Some challenges failed on pool teams the server refuses.
   - Fix in #401: the pool is validated with the server's own validator first, and the four refused teams are left out (owner's choice, 2026-10-11).
3. **Final run.** The run reported here.

## Provenance

- **Code:** m12/bottleneck at ba7289b7, with main 0bc8d8d9 merged in. The run used that commit's Release library, on 2026-10-11.
  - `arena.json` records `"code": null`, because WSL git cannot resolve the Windows worktree's gitdir. The commit is recorded here by hand.
- **Raw output:** `arena.json`, `games.json` and the bots' logs hold match ids. They stay private, outside the repository (AGENTS.md). This report quotes aggregates only.

## What it means and what it does not

- **What it shows:** the live search beats raw play of the same network on the live path and within the live time budget, without crashing.
- **What it does not show:** the opponent is the search's own network, played raw. Strength against humans or other networks is not measured here.
  - The paired engine evaluation (#356) and the foe-model measurement M7 (a BC bot as the opponent) take that question further.
