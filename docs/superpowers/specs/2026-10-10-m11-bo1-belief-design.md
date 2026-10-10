# M11: Bo1 games without team sheets as a marked belief source (design)

Status: approved by the owner via HauptSession (2026-10-10): option B (section 2), the split by player (section 6).
The BC runs of validation (c) need the owner's OK when they are due.

## 1. Goal and decisions so far

- **Goal (owner, 2026-10-10):** make the Champions games without open team sheets usable as BC data, as a source of their own, marked and weighted separately. The plan is to use them in training only after a measurement fixed in advance comes out positive.
- **Scope (funnel of 2026-10-10, #331):**
  - Reg M-C first: 63,501 games without sheets (63,489 Bo1, 12 Bo3).
  - Reg M-B later, designed in from the start: 271,759 games (271,450 Bo1, 309 Bo3).
  - The sheet games for comparison: M-C 48,333 set up, 616,858 rows; M-B 62,258 set up, 748,247 rows.
  - Reg M-A stays out: different mechanics era, owner decision of 2026-10-10. The funnel report shows it as one row.
- **Data:** HF HolidayOugi state of 2026-10-05, outside the repository. Nothing derived from it goes into the repository.

What every one of these games shows (sample of 2 %, 2026-10-10):
- **Species:** team preview gives all 6 species per side.
- **Moves:** about 3.4 species per side act. Per acting species, mostly 1 or 2 distinct moves are seen; all 4 in about 5 %.
- **Items and abilities:** only when they trigger.
- **Stat points:** never shown. Under open sheets they are not shown either.

## 2. The view question (owner decision: B, 2026-10-10)

The player view (decision 0007) assumes open team sheets: the observation holds both sheets, including the foe's moves, item, ability and nature. Closed team sheets are planned as milestone M14 (decision 0023, section "later") and do not exist yet.

In a Bo1 game without sheets the player knew their own team but not the foe's sets. Two options:

- **A. Wait for the closed-sheet view (M14).** The foe's member views show only what was revealed, and the own side is sampled (section 3). This is the faithful observation. It needs M14 first: a new view, encoder and engine knowledge mode. That is large, and live play needs it too for Bo1 without sheets.
- **B. Use the open-sheet view with sampled sheets for both sides.**
  - The rows exist now.
  - The foe sheet the row shows is a sample: the player did not see it, and it may be wrong. The label is the action the player chose without that knowledge. No true hidden information leaks, but the rows teach "act as if the foe's sheet were X".
  - Both sheets are marked as sampled (section 5). Whether this helps or hurts is exactly what the validation measures (section 6).

**Decision (owner, 2026-10-10): B.** Sampled sheets for both sides, marked as a source of their own, used for validation and, only after the test of section 6 comes out positive, for training. A is decided after M14.

## 3. Reconstruction: fixed facts and a set belief

**Fixed facts per member, from the log and never resampled:**
- species and forme (preview, switch details, detailschange; a Mega forme fixes the stone as the item);
- every move it used;
- an item that was revealed (-item, -enditem, [from] item, Knock Off, Trick);
- an ability that was revealed (-ability, [from] ability);
- which 4 were brought (hindsight picks, as today).

**The existing belief is not enough.** `duoforge_search.belief` (SpreadTable, Belief.sample, honest.spread_table) samples only stat points, keyed by (species, nature, item). Under open sheets those, the moves and the ability are known. Here they are not. The design reuses the belief for the stat points and adds one layer for the sets:

1. **Set corpus:** the sheets of all usable games of the same regulation (Reg M-C Bo3: 46,267 games, about 555,000 sets), plus the registry's `PP_` and `LL_` teams. It is kept outside the repository.
   - **Leave one series out:** the sets of the game's own series (the same sheet hashes, all games of a Bo3) are never drawn. Otherwise the validation would find its own sheet.
   - **Training split only:** the corpus is built from the sheet games of the training split (section 6) alone, so no set of a test player is ever drawn.
2. **Set draw per member:** among the corpus sets of its species and forme that agree with every fixed fact, one set is drawn, frequency-weighted, by a world word (as `belief.pick` does).
   - "Agree" means: the used moves are a subset of the set's moves, and the revealed item and ability are equal.
   - The draw yields moves, item, ability and nature.
3. **Back-off levels**, recorded per member:
   - L0: a whole corpus set agrees with every fact.
   - L1: no whole set agrees. The item and ability come from sets that agree on them; the moves are the used moves, with the missing slots drawn from the species' move frequencies among agreeing sets.
   - L2: the species has fewer than `min_sets` sets in the corpus. The game is skipped and counted (`skip:belief-unsupported <species>`); there is no guess from other species.
4. **Stat points:** the existing prior (`duoforge_replay.prior`, levels 0 to 4) on the drawn set, exactly as for sheet games.
5. **Legality:** every drawn team goes through the same setup check as sheet games (`data.setup_issue`, POOL). A drawn team the engine refuses is redrawn with the next word, at most R times, then skipped and counted (`skip:belief-illegal`).
6. **Determinism:** the words come from (seed, replay id, side, member, draw index). The same games and seed give byte-identical rows, as the sheet pipeline does.

**One sample per game or several:** K samples per game, each its own set of rows with weight 1/K. K = 1 is the default. The validation also runs K = 4, and K stays 1 unless (c) shows a gain from K = 4.

## 4. Labels and masks

- **A played move is always in the drawn set** (section 3, rule 2), so a label never falls outside the domain.
- **The risk is a false negative signal:** a move the player had but never used may be missing from the sample. A sampled move the player did not have takes part in the softmax. The BC loss is −log P(label set) over the legal options. A wrong extra option therefore draws probability mass that the loss pushes down: a weak "did not choose X" signal about an X the player never had. A missing true option only renormalises.
- **Two variants, both measured in section 6:**
  - **M1, the full mask** (default): the legal options of the drawn set, as for sheet games.
  - **M2, the revealed mask:** at move points, the softmax runs only over the moves seen in the game, plus switches and passes. This removes the false negatives, but it is biased toward used moves.
- **Labels never guess.** The label rules stay those of the sheet pipeline (EXACT, TARGET_UNKNOWN, MOVE_HIDDEN, FORCED, UNKNOWN). A stop ends the perspective, as today.

## 5. Marking: a source of its own

- **Separate datasets.** A belief dataset is its own directory. Its `replay-dataset.json` and manifest say `"source": "bo1_belief"`, the belief's version, the corpus SHA-256, K, the mask variant and the seed. A sheet dataset says `"source": "sheet"`.
- **Never mixed silently.** `bc_data.load` refuses a directory without a source, and refuses a `bo1_belief` directory unless the run names its weight (`--source-weight bo1_belief=W`). The run records the weights.
- **Missing values are never given out as real data.** Each row stores per member the belief level (L0 or L1, own and foe) and the prior level of the stat points, alongside `prior_level`. The games table stores K and the draw index. A trainer can filter on all of it. In variant B the observation cannot show what was sampled, so the marks live in the row and the source.

## 6. Validation, the core

Take M-C Bo3 games with sheets, drop the sheets and run them through the same belief pipeline.

**The split is by player, not by game** (HauptSession, 2026-10-10). Each player's hash, the u64 that `games.npz` already stores, falls into bucket 0 of 20 or not.
- A game is a test game when either of its players is in bucket 0.
- A game is a training game only when neither is.
- So no player appears in both. This applies to the sheet games and to the Bo1 games alike: a Bo1 game with a test player is never a training row.
- The test games are never used to build the corpus or to train.
- Only the hashes are used. No player name or id goes into the repository.
- The baseline S of (c) is trained with this split too, so the comparison is fair. It replaces the sheet-pair bucket of `bc.py` for this measurement.

**(a) Set recovery:** per member, against the true sheet:
- the whole move set right;
- recall of the unseen moves;
- item, ability and nature right;
- the stat point L1 distance.

Each is reported overall and per back-off level, for K = 1.

**(b) Row difference:** for the same game, perspective and point:
- the share of points that give a row in both runs (stops differ);
- the observation bytes that differ, per field group (own sheet, foe sheet, stats);
- the Jaccard overlap of the legal masks;
- label agreement (identical label set, or overlap).

**(c) Does it help BC? Fixed in advance:**
- **Runs:**
  - S, BC on the M-C sheet training split;
  - S+B, the same plus the belief rows of the M-C Bo1 games;
  - each with the same seed and steps;
  - the belief weight W ∈ {0.25, 0.5} and the variants M1/M2 and K = 1/4: 2 × 2 × 2 = 8 runs, plus S.
- **Primary metric:** the mean −log P(label set) on the sheet test split. Rows come from real sheets only.
  - S+B is better when the paired bootstrap over games (10,000 resamples) puts the 95 % interval of (S − S+B) above 0.
  - With 8 variants, the interval is Bonferroni-corrected (99.375 %).
- **Guard, non-inferiority:** the best S+B against S in the arena: 2,000 games, alternating seats, Team pool as in the BC report. The lower 95 % bound of S+B's win rate must be at least 48 %.
- **Use rule:** the source goes into training only if the primary metric and the guard both pass. If they do, the variant and weight that won are frozen.

**Caveat:** Bo3 players are on average stronger than Bo1 ladder players. (a) and (b) measure the reconstruction; (c) measures the effect with real Bo1 rows.

## 7. Funnel report (standard report of every build)

Per regulation (M-A, M-B, M-C) and Bo1/Bo3, aggregates only:

total → with sheet / with belief → set up (POOL, legality, names) → perspectives to the end / stopped by reason → rows.

- M-A appears as one row: "excluded (other mechanics era, owner 2026-10-10)", with its game count.
- The sheet pipeline gets the funnel first (the M-B sheet PR); the belief pipeline adds its own stage (belief levels and its skips).

## 8. Order, cost, rules

1. **Order:** the ValueError fix PR, the M-B sheet PR with the funnel, this design's review, then the build in tasks (corpus, set draw, marked dataset, M1/M2, validation (a) and (b)), then (c).
2. **Cost:**
   - The set corpus is built once: a few minutes.
   - The belief build of M-C Bo1 takes the time of the sheet pipeline (about 215 games/s with 8 workers): about 5 minutes per K.
   - (c) needs 9 BC runs on the GPU (WSL), each like the M11 BC run, plus one arena match.
   - Everything runs locally, during the day, with heavy runs through `tools/ci/machine_lock.sh`.
   - **The BC runs of (c) are training runs: they need the owner's OK when (c) is due**, because the plan of this week has no training runs.
3. **Data:** replays, corpus, datasets and checkpoints stay outside the repository. The repository gets code, tests with made-up logs, and reports with aggregates only.
4. **Open owner decisions:**
   - the view option (A or B), section 2;
   - whether M-B Bo1 joins after M-C's (c) passes;
   - the arena pool of the guard.
