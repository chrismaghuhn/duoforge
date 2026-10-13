# Network diagnosis: BC6's policy recall and value calibration (#451, 2026-10-13)

**Question (owner, 2026-10-12).** Which part of the network limits the bot: the policy (which actions become the search's candidates) or the value (how the search scores its leaves)?

The evidence so far points at the network:
- 46% of a top player's actions are not among the live search's 8 candidates;
- at team preview the value barely separates team choices, and the world spread is 0 (search ladder step 1);
- the search beats raw BC6 by only h 0.527–0.6 (search ladder step 0).

This is a measurement only. Nothing is trained, and the search is not changed.

## Networks (private; aggregates only)

- **BC6:** M11's encoder-6 BC (`bc6-M`, SHA-256 prefix `bda5de8e4e96`). It is the live search's foe model and the search ladder's main network. It was trained on human replays (Reg M-C and M-B). Every game of a held-out player (player hash h % 20 == 0, `duoforge_replay.split`) was left out of its training.
- **49333 (control):** params-49333 (`ef1abe65f637`), the PPO network and the live mode's main network. It was trained on self-play only and has seen no human data.

## Sources (private; aggregates only)

| source | what | role |
|---|---|---|
| **held-out games** | the M11 BC6 datasets (`sheet`, `bo1-regmc`, `bo1-regmb`), only the rows of games with a held-out player | policy recall and value calibration on unseen human play; the primary evidence |
| **top player** | the 213 open-sheet games of a top Showdown player (the replay analysis' games); their dataset rows and the live search on them (`duoforge_search.replay_analysis`, branch `m12/handoff-pr3-pr4`, commit `3368b976`) | search against raw play on a strong human; the player is *not* a held-out player, so BC6 saw these games in training |
| **arena** | our arena bot's live client logs (174 battles, 2026-10-12/13) | value traces of our own losses; the value spread over our team choices at preview |

## Tool

`python -m duoforge_search.network_diagnosis` (new, this branch), in four commands. Each writes its private output outside the repository; the report holds aggregates only.

- **`rows`:** reads the dataset rows. For each row and network it records:
  - the rank of the played action in the network's ranking: the joint pair for a turn or a forced switch (labels that name exactly one pair), or the best tuple of the label set for a team selection;
  - the value, the decision kind and the turn.
  Rows with more than one pick hypothesis are left out and counted. Without `--player` it reads the held-out games; with `--player` it reads that player's own rows.
- **`arena`:** replays each log through the live `Tracker` as the client fed it. At every decision point it records both networks' raw rankings and values, the rank of the choice we sent, and the search's cause and choice from the log.
  - **Fidelity check:** where the decision was played raw, the logged top three must equal the log network's raw ranking; for a searched decision, the entries after the search's choice must.
  - **Preview table:** at each team preview, a preview-only search (`preview_mode` "value", no foe network) of each network gives the value table (own candidates × foe candidates × worlds).
- **`outcomes`:** the result of each of the top player's games, for the replay analysis' decision rows.
- **`report`:** the aggregates. Every interval is a 95% percentile bootstrap over games (1000 replicates, seed `0x451`), so rows of one game move together.

**Value as a probability:** p = (clip(v, −1, 1) + 1) / 2, clipped to [0.001, 0.999] for the log loss. The AUC needs no mapping. 49333's value comes from PPO returns (γ = 0.99) and BC6's from a regression on the ±1 result, so the AUC is the comparable measure of discrimination, and Brier and log loss also reflect each value's scale.

## Measurements

1. **Policy recall:** top-1/4/8/16 hit rates of the acting player's action.
   - Split by decision kind (team preview, turn, forced switch), by turn and by the player's rating.
   - Measured on the held-out games, on the top player's rows and on our arena decisions (there it is the rank of the action we sent).
   - The share of decisions whose menu has at most K entries is reported beside each hit rate: a hit on such a decision is free.
2. **Foe-model recall:** the share of held-out human actions outside BC6's top-8 (the search's foe menu M = 8) and top-16.
   - The dataset row holds the acting player's true sets. A world in the search guesses the foe's stat points (open sheets show everything else). This share is therefore a lower bound on the foe menu's real miss rate.
3. **Value calibration:**
   - Brier score, log loss, AUC, ECE and the reliability curve of the value at each decision against the game's result.
   - AUC by turn ("how early does it know?").
   - At team preview: the value spread over our distinct candidate teams, and over the worlds.
   - In our arena losses: the value trace. A loss after a confident value (v ≥ 0.5, p ≥ 0.75, after the preview) counts as "confident"; a loss whose value was never above 0 counts as "never ahead".
4. **Search against network:** on the top player's decisions where the search's choice differs from the main network's raw first choice, which of the two the player played.

## Indicators and reading rule (fixed before the run)

| indicator | definition |
|---|---|
| **P1** | the share of held-out turn decisions whose action is outside BC6's top-8 (the search's K = 8), with its interval |
| **P2** | the share of the top player's scored decisions whose action is outside the live search's 8 candidates |
| **V1** | Δ = P(player plays the search's choice) − P(player plays the raw choice), on the top player's decisions where the two differ. The main network is 49333 here, because it has seen no human data; BC6 as the main network is reported too, but BC6 saw these games |
| **V2** | the held-out value AUC, overall and on turns 1–3, BC6 against 49333 |
| **V3** | the share of team previews whose value spread over our distinct candidate teams is below 0.02 (value units, one point of win probability) |

**Reading rule:**
- The **value** is named the weaker part if V1's 95% upper bound is ≤ 0: where the value overrides the policy, the strong player does not follow the override.
- The **policy** is named the weaker part if P1's 95% lower bound is ≥ 15% and V1's 95% lower bound is > 0. In that case the value moves toward the strong player wherever it gets to judge, but at least one human action in seven never reaches it.
- **Neither rule fires:** the report says that the data do not single out one part. It then recommends by V2, V3 and P2 as secondary evidence and says which numbers decided.

A strong player is a proxy for good play, not ground truth. V1 therefore asks whether the value's overrides move toward expert play; it does not ask whether they win.

## Run conditions

The plan above said the local PC in WSL; the owner moved the run to the project VPS (#451, 2026-10-13). As run:

- **Machine:** the VPS (4 vCPU), in the lane's own folder with its private inputs, 3 single-threaded workers at `nice 19` on cores 1–3 (the bot service was off that day). JAX on the CPU. No timing was measured there, and none is reported.
- **Code:** this branch. `rows` and `outcomes` ran on `dd8fce8c`; `arena` and `report` on `32c395ac`, whose only change is the arena replay's end of battle: it stops at the `|win|`/`|tie` line unfed, as the live client does, instead of feeding it to the tracker (the first run stopped there). The library is a Release build of this branch's C (main's).
- **Replay analysis:** `duoforge_search.replay_analysis` at `3368b976`, byte-identical copy.
- **Deviations:**
  - **Node:** Showdown `b2cb775b` (M11's pin, for the stat source) needs Node ≥ 22.18, so v22.23.3 ran instead of v18.19.1 (official tarball, SHA-256 `df450af8…` checked against nodejs.org's `SHASUMS256.txt`).
  - **Prior:** rebuilt from `data/teams` on the VPS, SHA-256 `6b01a417…`. The replay analysis' original prior (`4d377f69…`) cannot be rebuilt from any `data/teams` commit, and the plan's `b9f3b026` did not come out either, so the top player's search numbers use a prior close to, but not equal to, the original's.
- **Aggregates:** [`report.json`](report.json) holds every number below (no player, room or match ids).

## Results

### Coverage

| source | network | decisions | games | notes |
|---|---|---:|---:|---|
| held-out | both | 293,945 policy rows (64,142 team, 149,627 turn, 80,176 forced); 866,009 value rows | 61,892 | 73,473 rows with several pick hypotheses left out; 49333's encoder refused 78 rows (forced switches) |
| top player | both | 1,974 rows (213 team, 793 turn, 350 forced) | 213 | 381 rows with several pick hypotheses left out |
| top player, live search | 49333 main / BC6 main | 1,429 / 1,445 searched; 923 / 933 scored | 163 / 165 | |
| arena | both | 1,670 (153 team, 1,270 turn, 247 forced) | 153 of 174 logs (94 won) | left out: 16 random-team logs, 2 rejected choices, 2 tracker stops (an `-end ability` line the tracker cannot represent; the live bot forfeits there), 1 reconnect |

**What the held-out games are.** They are the games with a held-out player. BC6 never trained on them, but they were its validation set: the BC run kept the epoch with the best validation loss there. BC6's held-out numbers are therefore slightly optimistic. 49333 never saw any human game.

**Whose rankings the arena logs hold.** The fidelity check found the logged raw rankings to be **BC6's**, not 49333's:
- the logged top three equal BC6's raw ranking in 363 of 407 raw decisions, and 49333's in 19;
- 97.0% of the turn actions we sent are in BC6's top 8, against 47.7% in 49333's.

The arena bot of 2026-10-12/13 therefore ran with BC6 as its main network (its candidates and its raw choices). The bot was configured that way; only this design's assumption (49333 as the live main network) was wrong. The 44 raw decisions where BC6's ranking differs from the log are an open question (see Limits).

### Indicators

| indicator | value | 95% interval | n |
|---|---:|---|---:|
| **P1:** held-out turn actions outside BC6's top 8 | **32.0%** | 31.7–32.3% | 149,627 decisions |
| P1 for 49333 (control) | 69.5% | 69.3–69.8% | 149,627 |
| **P2:** top player's actions outside the live search's 8 candidates, 49333 main | **45.9%** | 43.1–48.8% | 923 |
| P2, BC6 main (in-sample) | 26.7% | 23.6–29.5% | 933 |
| **V1:** Δ, 49333 main | **+0.5 points** | −3.3 to +4.3 | 612 decisions where search ≠ raw |
| V1, BC6 main (in-sample) | −3.2 points | −7.6 to +1.4 | 594 |
| **V2:** held-out value AUC, BC6 / 49333 | **0.793 / 0.727** | Δ +0.066 (0.063–0.068) | 866,009 rows |
| V2 on turns 1–3, BC6 / 49333 | 0.740 / 0.637 | Δ +0.103 (0.099–0.107) | 368,481 |
| **V3:** previews with a team spread below 0.02, BC6 / 49333 | **0% / 0%** | | 152 previews |

For V1, in the decisions where the search overrides the raw choice, the top player plays:
- with 49333 as the main network: the search's choice 12.9%, the raw choice 12.4%, neither 74.7%;
- with BC6 as the main network: the search's choice 15.3%, the raw choice 18.5%, neither 66.2%.

**P2 and the live bot:**
- P2 and V1 were fixed with 49333 as the live main network, and that is the network the bold rows use.
- The bot's actual main network is BC6. Its rows are the live ones (P2 26.7%, V1 −3.2 points), but they are in-sample.

### Reading (the rule fixed before the run)

- **Value rule:** V1's upper bound is +4.3 points, not ≤ 0. It does not fire.
- **Policy rule:** P1's lower bound (31.7%) is ≥ 15%, but V1's lower bound (−3.3 points) is not > 0. It does not fire.
- **Verdict:** neither rule fires. **The data do not single out one part.** Where the value overrides the policy, the strong player follows the override neither more nor less often than the raw choice, to within ±4 points.

**Secondary evidence (V2, V3, P2), as the rule prescribes:**
- **V2:** BC6's value is the better of the two, by a clear margin. It separates won from lost positions with AUC 0.79 on unseen games (0.74 on turns 1–3) and is calibrated (ECE 0.031; every bin of the reliability curve within 6 points). 49333's value is weaker (AUC 0.73, 0.64 on turns 1–3) and overconfident:
  - ECE 0.144;
  - positions it scores at p 0.7–0.8 win 51%;
  - in the arena it was confident (p ≥ 0.75) in 55 of our 59 losses, BC6 in 6.
- **V3:** at team preview the value does separate our candidate teams: the median spread is 0.20 (BC6) and 0.10 (49333), and no preview is flat. The flat spread the question started from is the spread over the worlds (0 at preview, again here), not over the teams.
- **P2:** with 49333's candidates the live search misses the top player's action 46% of the time; with BC6's, 27%.

**Recommendation.** The secondary evidence points at the **policy as candidate supplier**, not at BC6's value:
- BC6's value is good on unseen games and discriminates already at preview;
- BC6's top 8 misses a third of human turn actions; its top 16 misses 16.1% (15.9–16.3%);
- 49333's candidates miss 46% of the top player's actions.

**Concretely:**
- keep BC6 as the candidate supplier (as the arena bot already does);
- test a wider candidate menu (K = 16) or a better-covering policy before any value retraining;
- do not use 49333's value as it stands: on human positions it is the weakest number in this report.

**Decided by:** P1, and P2 against V2. V1 decides nothing in either direction.

**What the null V1 says about the selection rule:** in the arena the search changed BC6's raw choice in 73% of searched decisions, and on the top player's games its changes are not closer to expert play. That is consistent with today's finding of the KO-candidate analysis (the right action is usually in the menu but is not chosen). The parts named there (the value of positions after the move, and the selection rule: Nash mix, λ) are not separated by this measurement.

### Policy recall (held-out; top-1 / 4 / 8 / 16)

| kind | BC6 | 49333 |
|---|---|---|
| team preview (64,142) | 14.6 / 24.6 / 34.7 / 45.5% | 1.0 / 1.9 / 3.7 / 7.3% |
| turn (149,627) | 22.3 / 50.9 / 68.0 / 83.9% | 6.1 / 18.5 / 30.5 / 48.1% |
| forced switch (80,176) | 75.3 / 99.9 / 100 / 100% | 62.1 / 100 / 100 / 100% |

- Every 95% interval is within ±0.4 points.
- A turn's menu has more than 16 entries in 99.9% of decisions, so the turn hits are not free.
- A forced switch has at most 4 entries in 92.4%.
- The paired difference BC6 − 49333 on turns is +16.3 points at top 1 (16.0–16.5) and +37.6 at top 8 (37.2–37.9).

**Turn top 8 by turn** (turn 10 includes later turns): BC6 is flat, between 66.1% and 69.7% over turns 1–10. 49333 lies between 27% and 35%.

**By source and rating** (BC6, turn top 8):
- sources: open-sheet 65.8%, Bo1 Reg M-C 60.8%, Bo1 Reg M-B 70.1%;
- ratings: unrated 60.9%, < 1200 66.5%, 1200–1399 73.2%, 1400–1599 70.5%, ≥ 1600 68.4% (66.1–70.8%, 1,487 decisions).

Recall does not fall for stronger players.

**Foe-model recall:**
- 32.0% of held-out human turn actions are outside BC6's top 8 (the search's foe menu M = 8), and 16.1% outside its top 16.
- This is a lower bound for the live foe menu (a world guesses the foe's stat points).

**Top player** (in-sample for BC6), turn:
- BC6: top 1 18.3%, top 8 65.7%;
- 49333: top 8 34.8%;
- team preview top 8: BC6 13.1% (8.9–17.8%), 49333 8.5%.

The team head's recall is low for both networks, for the strong player most of all.

### Value calibration

| source | network | AUC | Brier | log loss | ECE |
|---|---|---|---|---|---|
| held-out | BC6 | 0.793 (0.790–0.795) | 0.184 (0.183–0.185) | 0.545 | 0.031 |
| held-out | 49333 | 0.727 (0.724–0.730) | 0.235 (0.233–0.236) | 0.686 | 0.144 |
| top player | BC6 | 0.864 (0.835–0.890) | 0.154 | 0.464 | 0.047 |
| top player | 49333 | 0.773 (0.733–0.812) | 0.219 | 0.624 | 0.149 |
| arena | BC6 | 0.815 (0.774–0.853) | 0.182 | 0.536 | 0.104 |
| arena | 49333 | 0.752 (0.701–0.800) | 0.224 | 0.672 | 0.167 |

**AUC by turn** (held-out; preview, then turns 1–10):
- BC6: 0.63, 0.68, 0.74, 0.79, 0.83, 0.86, 0.88, 0.89, 0.90, 0.90, 0.88;
- 49333: 0.53, 0.55, 0.63, 0.71, 0.78, 0.83, 0.86, 0.87, 0.87, 0.88, 0.87.

Both know the result late. At preview, 49333 barely beats a coin (0.527), and BC6 reaches 0.63. From turn 6 on the gap is 0.01–0.03.

**Our arena losses** (59 of 153):

| | BC6 | 49333 |
|---|---|---|
| confident loss (v ≥ 0.5 after the preview) | 6 | 55 |
| never ahead (v never above 0) | 32 | 0 |
| mean value at preview, lost / won | −0.12 / −0.10 | +0.66 / +0.61 |

**Team preview** (152 arena previews, the value search over our 8 candidates against the foe's menu):

| | BC6 | 49333 |
|---|---|---|
| spread median | 0.200 | 0.104 |
| spread p90 | 0.230 | 0.204 |
| spread max | 0.433 | 0.511 |
| spread < 0.02 | 0% | 0% |
| distinct candidate teams of 8 | 4.0 | 4.0 |
| spread over the worlds | 0 | 0 |
| value search changes the raw team | 78% | 72% |

Every preview's 8 candidates hold exactly 4 distinct value rows for both networks: half the candidate slots repeat a team the value cannot tell apart.

### Limits

- **Proxy, not truth:** a human action is a proxy for good play.
- **V1's power:** its interval spans ±4 points around 0. A real effect smaller than that would go unseen.
- **In-sample for BC6:** the top player's games were in BC6's training; the held-out games were its validation set.
- **Top player's search:** it uses the rebuilt prior (`6b01a417…`), not the original.
- **No new search:** the arena's search causes are read from the logs; no search was rerun there.
- **Open question: the 44 raw decisions.**
  - In 44 of 407 raw arena decisions (11%), BC6's ranking on the replayed log differs from the logged one.
  - Likely cause: the observation's inputs built today differ from the bot's at the time, i.e. the prior or the spreads the live bot used then. This is not checked here.
  - The arena's value and rank numbers are read on today's inputs.
