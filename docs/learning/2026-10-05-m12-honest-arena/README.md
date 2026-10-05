# M12 honest arena: how much of the oracle gain survives (2026-10-04/05)

Honest E scores 0.879 against the raw network, a paired gain of +0.388 [0.364, 0.411]. That retains 95% of its stage-1 oracle gain. N retains 96%; the 50/50 mix X gains +0.314 [0.290, 0.339]. All three improve on raw against the earlier-checkpoint panel too.

**The agreed threshold for stage 3 is met.** E and X both exceed about +0.08 vs raw. Proceed to expert iteration with the agreed 50/50 teacher. This report recommends the next step; it does not start a training run.

The design follows the [stage-1 report](../2026-10-04-m12-stage1/README.md) ([#218](https://github.com/chrismaghuhn/duoforge/pull/218), scripted appendix [#219](https://github.com/chrismaghuhn/duoforge/pull/219)). This measurement covers the raw net and the BC/3600/11000 panel. [aggregates.json](aggregates.json) contains only configuration-level summaries; checkpoints, game rows, decision logs and run directories stay outside the repository.

## Setup

- **Code:** frozen `485cc61473f698757b6c83e76fb5d26a2d64d6ba`, library 0.43.0. This is the solver fix [#233](https://github.com/chrismaghuhn/duoforge/pull/233), merged as `9d47e181`; it builds on `c5313886` (#232). The run uses the PR commit itself. The solver preserves original payoffs and the 1e-9 certificate; no payoff quantization.
- **Network:** `params-18129`, v2-M, encoder 4, SHA-256 `8532b30b855969bed0f003fda5bd4400ad7c468a831ac0385332adb5289f3c2e`. The opponent model always uses this network, including against the panel. All four checkpoint hashes match stage 1.
- **Suite:** the same 79 teams (A/B/C and 76 PP_ teams), POOL, greedy opponents; 2,048 games per agent vs raw, 1,024 per agent and panel opponent. All four raw baseline game tables match stage 1 row for row.
- **Search:** `--search honest --agents N,E,X --lam 0.5 --s 16 --km 8x8 --workers 4`; hidden spreads sampled with the leave-one-team-out setup.
- **Seeds:** arena `0x2026100300000222`, search `0x2026100300000221`, bootstrap `0x2026100300000220`; 2,000 bootstrap resamples, paired game rows for gains; max steps 1,000.
- **Machine:** RTX 4060 Ti, Ryzen 7 5800X, JAX 0.11.2; `XLA_FLAGS=--xla_gpu_deterministic_ops=true`. Four workers and low CPU priority. Stage 1 used eight workers.
- **Capacity:** 1,024 instead of stage 1's 16,384. That fits 16 × 8 × 8 leaves and avoids padding a value call to 16,384 rows. The leaf budget is unchanged; the network batch shape and timings differ, so the cost comparison is descriptive.
- **Run split:** N/E vs raw completed on 2026-10-04 while night run 2 trained; the session ended before X and the panel. Those completed arms were retained at the owner's request. X and the panel resumed detached on 2026-10-05 after training finished. Earlier failed pilots and the superseded full retry are excluded.

## Scores and the oracle comparison

Score is 1 for a win, 0.5 for a tie, 0 for a loss. Brackets give 95% bootstrap intervals. The oracle column is stage 1 at S = 16. Retained gain divides the honest paired improvement by the oracle paired improvement; it is a ratio of point estimates, without a separate confidence interval. Stage 1 did not measure X.

| Opponent | Raw baseline [95%] |
|---|---|
| Raw net | 0.491 [0.470, 0.514] |
| BC | 0.622 [0.592, 0.650] |
| 3600 | 0.494 [0.463, 0.523] |
| 11000 | 0.506 [0.475, 0.538] |

| Opponent | Agent | Honest score [95%] | Honest gain vs raw [95%] | Oracle score [95%] | Oracle gain | Gain retained |
|---|---|---|---|---|---|---|
| Raw net | N | 0.705 [0.686, 0.726] | +0.214 [+0.188, +0.238] | 0.714 [0.695, 0.733] | +0.223 | 96% |
| Raw net | E | 0.879 [0.865, 0.894] | +0.388 [+0.364, +0.411] | 0.901 [0.888, 0.914] | +0.410 | 95% |
| Raw net | X | 0.806 [0.787, 0.823] | +0.314 [+0.290, +0.339] | N/A | N/A | N/A |
| BC | N | 0.739 [0.713, 0.768] | +0.117 [+0.083, +0.153] | 0.741 [0.715, 0.769] | +0.119 | 98% |
| BC | E | 0.757 [0.730, 0.783] | +0.135 [+0.100, +0.172] | 0.787 [0.761, 0.812] | +0.165 | 82% |
| BC | X | 0.774 [0.749, 0.799] | +0.152 [+0.117, +0.186] | N/A | N/A | N/A |
| 3600 | N | 0.633 [0.603, 0.661] | +0.139 [+0.102, +0.175] | 0.636 [0.606, 0.666] | +0.142 | 98% |
| 3600 | E | 0.687 [0.658, 0.714] | +0.192 [+0.156, +0.228] | 0.706 [0.680, 0.734] | +0.212 | 91% |
| 3600 | X | 0.659 [0.631, 0.689] | +0.165 [+0.128, +0.205] | N/A | N/A | N/A |
| 11000 | N | 0.640 [0.609, 0.671] | +0.134 [+0.095, +0.174] | 0.689 [0.663, 0.718] | +0.184 | 73% |
| 11000 | E | 0.706 [0.677, 0.735] | +0.200 [+0.163, +0.238] | 0.714 [0.686, 0.742] | +0.208 | 96% |
| 11000 | X | 0.704 [0.675, 0.732] | +0.198 [+0.162, +0.234] | N/A | N/A | N/A |

## Raw fallbacks

Denominator: every logged requested learner decision, including team selection and forced choices, matching the arena summary. The aggregate also supplies shares among eligible decisions (searched or raw fallback), excluding team/forced choices. Sleep and confusion can overlap, so cause counts need not sum to total fallbacks.

Across the 12 search arms: **3,054 / 153,885 decisions (1.98%)** fell back to raw. Visible sleep is the largest cause (2,045); 11 decisions also had visible confusion.

| Opponent | Agent | Requested decisions | All raw fallbacks | Sleep | Confusion | PIVOT refusal | Ambiguous bench | Redraw exhaustion |
|---|---|---|---|---|---|---|---|---|
| Raw net | N | 20,728 | 396 (1.91%) | 249 (1.20%) | 59 (0.28%) | 74 (0.36%) | 17 (0.08%) | 0 (0.00%) |
| Raw net | E | 19,036 | 370 (1.94%) | 240 (1.26%) | 47 (0.25%) | 67 (0.35%) | 16 (0.08%) | 0 (0.00%) |
| Raw net | X | 19,772 | 404 (2.04%) | 274 (1.39%) | 44 (0.22%) | 73 (0.37%) | 13 (0.07%) | 0 (0.00%) |
| BC | N | 11,518 | 241 (2.09%) | 182 (1.58%) | 30 (0.26%) | 26 (0.23%) | 5 (0.04%) | 0 (0.00%) |
| BC | E | 10,859 | 209 (1.92%) | 146 (1.34%) | 37 (0.34%) | 26 (0.24%) | 4 (0.04%) | 0 (0.00%) |
| BC | X | 10,994 | 248 (2.26%) | 185 (1.68%) | 37 (0.34%) | 21 (0.19%) | 7 (0.06%) | 0 (0.00%) |
| 3600 | N | 10,326 | 202 (1.96%) | 128 (1.24%) | 27 (0.26%) | 33 (0.32%) | 14 (0.14%) | 0 (0.00%) |
| 3600 | E | 9,935 | 172 (1.73%) | 118 (1.19%) | 24 (0.24%) | 25 (0.25%) | 5 (0.05%) | 0 (0.00%) |
| 3600 | X | 10,122 | 192 (1.90%) | 116 (1.15%) | 39 (0.39%) | 30 (0.30%) | 7 (0.07%) | 0 (0.00%) |
| 11000 | N | 10,309 | 193 (1.87%) | 125 (1.21%) | 36 (0.35%) | 27 (0.26%) | 5 (0.05%) | 0 (0.00%) |
| 11000 | E | 10,033 | 205 (2.04%) | 133 (1.33%) | 45 (0.45%) | 22 (0.22%) | 5 (0.05%) | 0 (0.00%) |
| 11000 | X | 10,253 | 222 (2.17%) | 149 (1.45%) | 45 (0.44%) | 22 (0.21%) | 6 (0.06%) | 0 (0.00%) |

Visible sleep/confusion are the explicit public-fact refusals. PIVOT refusal covers other unreconstructible PIVOT records; it does not claim a finer engine-rule diagnosis. Ambiguous bench is verified separately: every queue-mask refusal was replayed and its current/turn-start public seen count checked. Each had fewer than four known brought members in the current or turn-start record. The audit reproduced every decision epoch and final game record for all 15,360 search games. No neutral-domain refusal is guessed to be a bench refusal.

Redraw exhaustion is **0** in all completed arms. In this code it stops the run with a reproduction rather than falling back to raw. Ordinary successful spread redraws are counted separately in the aggregate. There are no unclassified fallback causes.

## Decision time

Milliseconds below are median / p95 of the recorded network + engine + reduction + split cost. Searched-only and all-requested totals are both shown. First-use policy compilation is warmed before that policy timer; these are not whole-run latency measurements.

| Opponent | Agent | Searched ms (median / p95) | All requested ms (median / p95) |
|---|---|---|---|
| Raw net | N | 33.29 / 39.94 | 32.53 / 39.34 |
| Raw net | E | 32.35 / 38.99 | 31.59 / 38.42 |
| Raw net | X | 29.12 / 37.37 | 28.37 / 36.29 |
| BC | N | 31.51 / 40.56 | 30.77 / 39.64 |
| BC | E | 31.68 / 38.22 | 30.99 / 37.61 |
| BC | X | 31.89 / 39.15 | 31.18 / 38.57 |
| 3600 | N | 31.70 / 39.99 | 30.87 / 39.08 |
| 3600 | E | 32.62 / 40.73 | 31.72 / 39.94 |
| 3600 | X | 33.41 / 41.39 | 32.47 / 40.70 |
| 11000 | N | 33.54 / 40.29 | 32.62 / 39.83 |
| 11000 | E | 33.62 / 40.63 | 32.68 / 40.04 |
| 11000 | X | 33.43 / 40.33 | 32.59 / 39.70 |

Stage-1 oracle N/E vs raw took about 5–6 ms median; honest decisions take about 30–34 ms. They build public-information worlds, query the team/policy heads and solve a Bayesian game. The aggregate gives the measured breakdown. Timing also reflects four rather than eight workers, changed padding, and concurrent training for retained N/E. During the earlier concurrent attempt the observed training throughput dipped about 8%; this was reported to the owner. X/panel ran after training ended, with brief public-record replay audits alongside the panel.

Detached X-vs-raw elapsed 10.25 minutes including its raw baseline and compilation; the complete panel elapsed 55.18 minutes including three raw baselines and compilation. Neither includes the interrupted attempts or post-run analysis.

## Validation and decision

**The tail still matters:** 5 of 127,435 searched decisions (0.0039%) used the rational rescue. Their reduction times ranged from 1.81 to 18.03 seconds, totaling 52.81 seconds; the largest recorded reduction was 18.03 seconds. The median/p95 table does not capture those rare stalls. Both saved regression fixtures pass the 50 ms bound, but that is not a worst-case guarantee for arbitrary payoff tables. This remains a solver latency limitation for live play and teacher throughput, even though no single observed rescue lasted minutes.

All 16 configurations have **0 unfinished and 0 unresolved games**. Baseline row equality, checkpoint hashes, bootstrap recomputation and public-record replay audits were checked locally. The solver fix CI passed before it was merged. This PR changes only documentation and aggregate data.

The honest E/X gains exceed the agreed +0.08 threshold against raw and every panel opponent. **Start stage 3 with the 50/50 teacher.** The low fallback share does not make elapsed-turn tracking the first prerequisite; keep it as a later decision if live-play data show a larger visible-counter share. The teacher recommendation uses measured score gains, while its roughly 30 ms search cost remains a practical constraint for expert-iteration throughput.
