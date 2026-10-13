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

- **Machine:** the local PC, in WSL (JAX on the CPU), each run under `tools/ci/machine_lock.sh` (no latency is measured, so no run is exclusive). No AWS.
- **Library:** a WSL Release build of this branch's C, which is main's.
- **Code:** this branch. Its tool and this design are committed before the run.

## Results

Pending.
