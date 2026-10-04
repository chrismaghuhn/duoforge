# M12 stage 1: search against the network (an oracle benchmark, 2026-10-04)

The arena measurement of plan PR E (`python -m duoforge_search.arena`, #214; spec section 8), run locally on the owner's RTX 4060 Ti on 2026-10-04.

**This is an oracle benchmark, not a playable result.** The search runs on the **true state**. It knows the foe's stat points and stats, its exact HP and both sides' secret counters (spec section 3; ARCHITECTURE section 10). A live player sees none of that. The numbers bound what search can add; they are not what a bot would gain in a real game. The next spec (owner, 2026-10-04) is a visible-information search that samples hidden stat points from common spreads.

The raw data are in `raw/`:
- `summary.json` per run, with the conditions;
- the games CSVs (play_suite's records);
- the timing files.

They hold only scores, counts and hashes. The decision records (about 490 MB) and every checkpoint stay on the owner's PC (AGENTS.md).

## Setup

- **Code:** main f461823c (library 0.42.0), run from a `git archive` of that commit. That is why `conditions.commit` in `summary.json` is `null`; the commit is f461823c.
- **Network:** `params-18129`, the last checkpoint of the many-team night run `many-c4e96e6` (v2-M, encoder 4, BC start, 652 teams). SHA-256 `8532b30b855969bed0f003fda5bd4400ad7c468a831ac0385332adb5289f3c2e`.
- **Suite:** the 79 teams of the run's first checkpoint (A/B/C and 76 PP_ teams, POOL), the arena seed 0x2026100300000222, greedy.
- **Search:**
  - K × M = 8 × 8 candidates, S = 16, 32 or 64 sampled chance worlds per cell, capacity 16,384;
  - agents N (Nash) and E (expected value against the network's own policy);
  - the search's model of the opponent is always `params-18129`.
- **Machine:** RTX 4060 Ti, Ryzen 7 5800X, JAX 0.11.2, `XLA_FLAGS=--xla_gpu_deterministic_ops=true`, 8 workers.
- **Bootstrap:** 2,000 resamples (seed 0x2026100300000220). The paired differences resample the rows together.

## Cost check (`raw/cost/`)

256 games of N with S = 16 against R:
- **ms per searched decision:** 5.74 median, 8.32 p95. That is under the spec's estimate of about 8 ms and far under the stop threshold of 3×.
- **Breakdown (median):** network 2.46 ms, engine 1.53, reduction 0.73, split 0.79.

## Against the same network without search (`raw/main/`, 2,048 games each)

| Configuration | Score [95 %] | Paired vs R-vs-R [95 %] | Elo | ms per decision (median / p95) |
|---|---|---|---|---|
| R vs R | 0.491 | – | -6 | – |
| N, S = 16 | 0.714 [0.695–0.733] | +0.223 [+0.198–+0.248] | 159 | 5.74 / 7.22 |
| N, S = 32 | 0.729 [0.709–0.748] | +0.237 [+0.210–+0.263] | 171 | 12.00 / 14.34 |
| N, S = 64 | 0.724 [0.705–0.743] | +0.233 [+0.207–+0.258] | 168 | 17.91 / 21.24 |
| E, S = 16 | 0.901 [0.888–0.914] | +0.410 [+0.387–+0.432] | 383 | 4.78 / 5.78 |
| E, S = 32 | 0.900 [0.887–0.913] | +0.409 [+0.385–+0.431] | 382 | 9.30 / 11.00 |
| E, S = 64 | 0.908 [0.895–0.920] | +0.417 [+0.394–+0.439] | 397 | 19.26 / 23.15 |

- **Decisions per configuration:** about 16,000–17,400 searched, plus 2,048 team selections and 750–1,080 forced.
- **Clean games:** 0 unfinished and 0 unresolved games, 0 refused or cut-off leaves.
- **Search behaviour:** coverage 0.987. The search changes the network's choice in about 75 % of decisions.
- **`Solution.exact`:** 0 of the searched decisions of N are exact (17,259, 17,343 and 17,391 records, all `exact: false`). The E records carry no such field.
- **S hardly matters:** 16 worlds are as good as 64, at a quarter of the time.

## Against other opponents (`raw/panel/`, 1,024 games each)

The search still models the opponent as `params-18129`, but it plays three other checkpoints of the same run:
- P25 = `params-0` (the BC prior);
- P50 = `params-3600`;
- P75 = `params-11000`.

| Opponent | R (no search) | N, S = 16: paired vs R | E, S = 16: paired vs R |
|---|---|---|---|
| BC (`params-0`) | 0.622 [0.592–0.650] | +0.119 [+0.086–+0.156] | +0.165 [+0.132–+0.199] |
| `params-3600` | 0.494 [0.463–0.523] | +0.142 [+0.104–+0.179] | +0.212 [+0.177–+0.249] |
| `params-11000` | 0.506 [0.475–0.538] | +0.184 [+0.147–+0.221] | +0.208 [+0.172–+0.246] |

- **The flattery was real.** Against the network that E models perfectly, E gains +0.41. Against other opponents it gains +0.17 to +0.21, about half, because E best-responds to a policy the opponent no longer plays.
- **E stays at or above N** against every opponent:
  - +0.05 against BC and +0.07 against 3600, where the intervals barely overlap;
  - level against 11000.
- **Search helps against other opponents too:** +0.12 to +0.21, about +85 to +150 Elo.
- The panel's ms values may be slightly high: a CPU test ran briefly in parallel. Its scores are unaffected.

## What this decides (owner, 2026-10-04)

- The next M12 spec is a visible-information search: hidden stat points sampled from common spreads (pastes), with Nash, EV and a 50/50 mix. It serves stage 2 (live play) and stage 3 (the teacher).
- **The default teacher is the 50/50 mix N/E** until the honest search has been measured.
- S = 16 is enough.

## Against the scripted agent (`raw/scripted/`, 1,024 games each)

Run on main b7ba0232 (#217, library 0.42.0), again from a `git archive`, so `conditions.commit` is `null`. Same network, seeds and suite; the opponent S is evaluate's ScriptedPolicy (`--opponents scripted`).

| Configuration | Score [95 %] | Paired vs R-vs-S [95 %] | ms per decision (median / p95) |
|---|---|---|---|
| R vs S (no search) | 0.955 [0.941–0.967] | – | – |
| N, S = 16 | 0.958 [0.945–0.970] | +0.003 [-0.013–+0.021] | 5.88 / 7.44 |
| E, S = 16 | 0.958 [0.946–0.970] | +0.003 [-0.013–+0.020] | 4.65 / 5.58 |

0 unfinished and 0 unresolved games.

**At the ceiling:** the network alone already wins 95.5 % against the scripted agent, so search has no room to show a gain, for N or E. This arm cannot separate the teachers; the panel above is the informative comparison.
