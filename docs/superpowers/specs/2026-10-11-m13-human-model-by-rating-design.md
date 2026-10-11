# M13 lever 2: a human-play model conditioned on rating (design)

Status: draft for the owner's review (issue #365). Nothing is trained, and nothing runs on AWS, until the owner approves (BC spec section 10, decision 0024).

## Goal

Predict how people at a given rating play, as the search's opponent model on the ladder.

- ROADMAP lever 2 exploits human habits: Protect, Fake Out, the usual switches.
- ROADMAP lever 10 covers the openings, turns 1 and 2.
- The replayreview idea of 2026-10-11 conditions both on the rating ("a 1300 and an 1800 player choose differently").

The issue is done when the model, used as the opponent model, is measured on its own as an Elo difference at a fixed time per move against the previous best agent. This is the M13 exit rule.

## What the data holds

These are aggregates of the M11 datasets of 2026-10-11. A "perspective" is one player's side of one game, rated by that player's ladder rating at game start; "unrated" means -1.

| source | perspectives | unrated | below 1100 | 1100–1299 | 1300–1499 | 1500 and above |
|---|---|---|---|---|---|---|
| Reg M-C Bo3, open sheets | 91,672 | 10,348 | 31,566 | 43,622 | 5,994 | 142 |
| Reg M-C Bo1, `bo1_belief` (part 4) | 117,220 | 5,002 | 30,785 | 54,483 | 24,058 | 2,892 |
| Reg M-B Bo3, open sheets | 115,116 | 21,198 | 25,376 | 51,647 | 16,134 | 761 |

Two facts follow:
- Most data sits below 1300. 1500 and above holds 0.15 % of the M-C sheet perspectives, 0.7 % of the M-B ones and 2.5 % of the Bo1 ones; 1700 and above holds 52 perspectives in all.
- The two players of a game are close in rating: in M-C Bo3 the median gap is 53 points, the 90th percentile 108.

So a model per narrow band would starve at the top, and the opponent's rating tells little beyond the player's own.

## Design

1. **Conditioning, not separate models.**
   - The BC model (`model_v2`, preset M) gets one extra input: the acting player's rating band, as a one-hot of five bands (unrated, below 1100, 1100–1299, 1300–1499, 1500 and above).
   - The one-hot enters the trunk input next to the pooled embeddings.
   - Its columns start at zero, so the model starts as the BC checkpoint it is initialized from (the way `--init` zeroes columns a checkpoint lacks).
   - Rejected alternatives:
     - a model per band starves the top bands (table above);
     - a scalar rating input imposes a linear shape the data cannot check above 1500;
     - the opponent's rating as a second input is left out of the first version, because the gap is small.
2. **Rows.**
   - `bc_data.Rows` gains the acting side's rating band, from `games.npz` ratings.
   - The rating weighting (`rating_weight`) is off for this model, because every band is a target. Each band keeps its natural share.
   - `--band-balance` is an optional factor that raises the rows of the sparse top bands; it is off by default and measured, not assumed.
   - The sources:
     - the sheet rows (`source sheet`);
     - optionally `bo1_belief` rows with an explicit `--source-weight` (Bo1 spec section 5). The Bo1 ladder is where the model would play, and Bo1 holds most of the high-rated games;
     - pick hypothesis rows stay out unless the owner decides otherwise after their validation.
3. **Split.**
   - The validation split is by player hash: bucket 0 of 20 (`split.of_game`), for every source.
   - Reason: a model conditioned on rating must not be validated on the players it trained on. The sheet-pair split of the BC spec keeps a Bo3 match together, but it lets one player's other matches train.
   - This changes the split of this model only, not the BC prior's.
4. **Openings (lever 10).** The model's own heads predict the openings: the team head (four of six, leads) and the pair head on turns 1 and 2. The empirical baseline is `book.Book.turn_1` with its rating bands (`rating_band`), so the model is measured against the frequency table it must beat.
5. **Use in the search.**
   - `Honest` scores the foe's rows with the same network today (`_world_policy`, `_prepare`).
   - It gets an optional `opponent_model`: a second network with its band. That model gives the foe pairs (top m) and the `qs` that the rule `mix` uses, while the own policy and value stay as they are.
   - With `opponent_model` absent, `Honest` behaves byte for byte as now; a test pins this.
   - Live, the adapter reads the opponent's rating from the `|player|` line, which the tracker now ignores (`lines.py`).
   - A missing rating is the band "unrated". This is a band of its own, trained on the unrated rows, not a fallback.

## Measurement

Offline, before any ladder game. These steps need a trained model, so they wait for the owner's training approval.

- **(a) Fit per band.**
  - Measures: the negative log-likelihood of the logged label sets, and the top-1 and top-5 accuracy, on the validation players, per band.
  - Compared against: the BC prior without the band, and the model given the wrong band (one band up and one down).
  - Purpose: the band input is real only if the right band beats the wrong ones.
- **(b) Openings.** On turns 1 and 2: the same measures, against `Book.turn_1` per band. On team selection: the four picked and the leads.
- **(c) Elo at a fixed time per move.**
  - The arena (`duoforge_search.arena`) measures with a leaf budget fitted to a fixed time per move. Agents compared: the previous best agent with and without `opponent_model`.
  - Problem: the arena has no human opponents. Against networks, an opponent model of humans can look worse even when it would help on the ladder.
  - Proposal: a panel of opponents that play as the human model itself samples at a rating. This tests whether the search exploits a human-like player at all, and it is circular by design.
  - The issue counts as done only with the ladder measurement, which the owner must allow (ROADMAP: registered and marked as a bot).

## Open points for the owner

1. **Training approval** for one BC run with the band input, from the current BC prior. The data needs the rebuilt datasets of 2026-10-11 (folds bit 59).
2. **Sources.** Sheet rows only, or also `bo1_belief` rows at a named weight. Recommendation: both, the latter at 0.5, measured per source in (a).
3. **Measurement for "done".** The arena panel of human-model opponents as the gate before the ladder, then a registered ladder run.
4. **Bands.** The five bands above. A band above 1500 can be split once the data holds it.

## Not in this spec

- The Bo3 adaptation of lever 11.
- The opponent-action head of lever 18 (Learner v2).
- The belief network of lever 14.
