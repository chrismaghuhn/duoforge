# Preview oracle (issue #458): what the team preview costs against the tournament sun team

**Question (owner, 2026-10-13).** Games are mostly lost at the team matchup or at the bring-4 choice. Before an opening book is built: against one fixed opponent, how much better than our current preview is the best bring-4 and lead choice, and how far apart do the choices lie?

This document was committed before the first measurement (`3fda5ad2`); the results below were added after the runs, aggregates only.

## Setup

- **Tool:** `python -m duoforge_search.preview_oracle` (this branch).
- **Teams:**
  - ours: Team A (`data/teams/A.txt`, the arena team);
  - foe: a top tournament sun team (test team of #458, as of 2026-10). Its sheet with stat points is a private file. Reports name its species, never a player.
  - Both sheets have full stat points: nothing is filled.
- **Pilots: the live search on both seats** (ladder step 0, `HONEST_SETTINGS`). BC6 searches, BC6 is the foe model of the worlds. Each seat's spread table leaves out the other team's registry rows: Team A's for the foe, none for ours, because the foe team is not in the registry.
  - This replaces the raw BC pilots of the ladder's matchup arm. Those pilots played the sun team far below its arena strength: 95–98 % for Team A in the simulator, 4:15 on the arena.
- **Arms:** our team preview is fixed per arm.
  - `today` is our search's own preview, the raw top-1 of BC6, as in live play.
  - The 90 combinations: 15 bring-4 sets times 6 lead pairs. The leads' sides and the bench order are fixed (ascending), so the side of a lead is not measured.
- **The foe's preview** is drawn from its own team head, BC6 raw, by a word of the game's decision key.
  - The draw is identical in every arm, so a game of two arms differs only in our preview.
  - Every arm plays the same suite rows on the same batch seed (common random numbers).
  - A foe draw that differs between two arms stops the summary.
- **Games:** pair k is game k twice, with ours on seat 0 and then on seat 1. A tie counts half; an unresolved game counts as our loss.
- **Machine:** local PC under `tools/ci/machine_lock.sh`, one slot, 8 workers. The networks and outputs stay private, outside the repository.

## Stages (predeclared)

1. **Screen:** all 91 arms (`--arms all`) with 32 pairs each (64 games), seed `0x2026101300000458`.
2. **Confirm:** on a fresh seed `0x2026101300000459`, 256 pairs each (512 games). The arms are `today`, the stage-1 top 5 by score (ties by name), and `today`'s own combination if it is not among them.
3. **Fixed sun lead (HS, 2026-10-13):** the same arms, the same seed and the same pair count as stage 2, with the foe's leads fixed to Charizard + Venusaur (`--foe-lead Charizard,Venusaur`). The bench is still drawn from the foe's team head, given those leads. This is how the arena opponent with this team led in its last set; BC6's team head probably chooses otherwise. It is reported apart from stage 2, with its own loss and spread.

**Code for stages 2 and 3.** If #459 (visible sleep) is merged before stage 2 starts, stages 2 and 3 run on the new main with a library built from it, and the report names both commits. Stage 1 is a screen only and stays on this branch.

## What is reported

- **Result 1, the preview loss:** the stage-2 score of the best confirmed combination minus `today`, in points, paired over game pairs, with a 95 % pair-bootstrap interval.
  - The stage-2 score of the stage-1 winner is reported too. It was not selected on these games, so the stage-2 selection does not bias it.
- **Result 2, the spread of the combinations** (stage 1):
  - the range and standard deviation of the 90 combination scores;
  - the noise of one score (its standard error over the pairs);
  - the spread left after that noise: `sqrt(max(0, var − mean se²))`.
- **Also reported:**
  - marginals per bring-4 set and per lead pair;
  - the foe's preview distribution, i.e. its drawn leads and its brought four;
  - every arm's score split by the foe's lead;
  - unfinished and unresolved games;
  - **per arm**, both seats' raw-fallback shares and their causes (visible sleep among them). Sleep must not hit the arms unequally: an arm whose fallback share is more than 2 points above the arms' median is named, with its causes.

## How it is read (predeclared)

- If the 95 % upper bound of the preview loss is **below 3 points**, a book can gain little against this team: the matchup decides, not the choice.
- If the lower bound is **above 5 points**, the preview is a real lever. The book's matchup arm (#458, measurement 3) is worth building against this team first.
- Anything in between: report it as it is, with no conclusion beyond the numbers.
- The spread after the noise says the same from the other side: under about 3 points, the choices lie close together.

## Caveats

- Both pilots are the same search over the same network. A foe who plays the sun team better than our search would widen or narrow the gap; this arm cannot see that. The mirror arm of #458 (arm 2) measures the team share against the bot share.
- The foe's preview distribution is BC6's, not the arena opponent's. On the arena, the opponent with this team led sun in 10 of 10 games of its last set; the split by foe lead shows the sun lead separately.
## Results

### Stage 1: screen (commit `3fda5ad2`, dirty: false, library built from `d19839e3`, 2026-10-13)

The library's sources are those of `3fda5ad2`: the two commits have the same `src/` and `include/`, and their CMake files differ only in test registrations. The Python ran from `3fda5ad2`. 91 arms of 32 pairs (64 games each, 5,824 games). No game was unfinished or unresolved. All arms played the same foe draws.

- **Our preview today:** BC6's raw top-1 is the combination Milotic + Raichu in the lead, Rillaboom + Ceruledge in the back (`24|03`). The arm `today` scored **65.6 %** [53.1, 76.6]; its combination with the fixed sides and bench order scored 70.3 %.
- **Best combination (selected on these games, so biased upward):** Milotic + Ceruledge in the lead, Rillaboom + Raichu in the back (`23|04`): **85.9 %** [78.1, 93.8]. Against `today`: **+20.3 points** [6.3, 34.4], paired.
- **Stage-1 top 5** (ties by name), which stage 2 confirms:

  | Arm | Lead | Back | Score |
  |---|---|---|---|
  | `23\|04` | Milotic + Ceruledge | Rillaboom + Raichu | 85.9 % |
  | `23\|15` | Milotic + Ceruledge | Staraptor + Gholdengo | 73.4 % |
  | `24\|13` | Milotic + Raichu | Staraptor + Ceruledge | 73.4 % |
  | `12\|03` | Staraptor + Milotic | Rillaboom + Ceruledge | 71.9 % |
  | `02\|34` | Rillaboom + Milotic | Ceruledge + Raichu | 70.3 % |

  `today`'s combination `24|03` (70.3 %, tied with `02|34`, `12|35` and `23|01`) is confirmed as well.
- **Spread of the 90 combinations:**
  - range 76.6 points (9.4 % to 85.9 %), standard deviation 15.8 points;
  - noise of one score 6.0 points;
  - spread left after the noise **14.6 points** (predeclared formula).
  - Added after the runs: the arms play the same games, so their noises are correlated and the predeclared formula subtracts too much noise; it is a lower bound. Subtracting only the noise of the arms' differences (5.8 points) leaves 14.7 points.
- **Worst:** Rillaboom + Staraptor in the lead with Raichu + Gholdengo in the back (`01|45`), 9.4 %.
- **Marginals:**
  - Bring-4, by mean over its 6 lead pairs:
    - best: Rillaboom + Milotic + Ceruledge + Raichu, 65.9 %, its combinations ranging 45.3 to 85.9 %;
    - worst: Rillaboom + Staraptor + Raichu + Gholdengo, 19.3 %.
    - The four best sets all bring Milotic and Ceruledge.
  - Lead pair, by mean over its combinations:
    - best: Milotic + Ceruledge 68.5 %, Milotic + Raichu 63.8 %, Staraptor + Milotic 59.6 %;
    - worst: Rillaboom + Raichu 29.4 %.
- **Foe preview** (BC6's raw team head, the same 64 draws in every arm):
  - leads: Charizard + Venusaur 16, Incineroar + Farigiraf 12, Charizard + Garchomp 9, others 27;
  - brought: Charizard in 56 of 64 games.
- **By foe lead** (the three leads with at least 9 games), `today` / `23|04` / `24|03`:
  - Charizard + Venusaur (16 games): 38 / 75 / 56 %;
  - Charizard + Garchomp (9): 44 / 89 / 78 %;
  - Incineroar + Farigiraf (12): 92 / 92 / 83 %.
- **Fallbacks per arm** (share of searched decisions that fell back to the raw policy):
  - median 18.4 % (ours) and 19.2 % (foe), maximum 27.5 % on both seats;
  - causes: visible sleep (ours 10,468; foe 10,620 decisions over all arms), plus 304 foe decisions with an unsupported public record;
  - **32 arms lie more than 2 points above the median on our seat**, with visible sleep as their only cause (4,947 decisions):
    `02|13`, `02|15`, `02|34`, `02|35`, `03|12`, `03|25`, `05|23`, `12|03`, `12|04`, `12|05`, `12|34`, `12|45`, `13|02`, `15|24`, `23|01`, `23|04`, `23|05`, `23|14`, `23|15`, `23|45`, `24|03`, `24|15`, `24|35`, `25|03`, `25|04`, `25|13`, `25|14`, `25|34`, `34|02`, `35|02`, `35|12`, `45|23`.
    - Four of the five top arms are among them (all but `24|13`); `today` (20.0 %) is not.
  - **32 arms lie more than 2 points above the median on the foe's seat**, with visible sleep (5,045 decisions) and an unsupported public record (73):
    `02|13`, `02|14`, `02|15`, `02|34`, `02|35`, `02|45`, `03|12`, `03|25`, `05|23`, `12|03`, `12|04`, `12|05`, `12|34`, `12|45`, `13|02`, `15|24`, `23|01`, `23|04`, `23|05`, `23|45`, `24|03`, `24|15`, `24|35`, `25|04`, `25|13`, `25|14`, `25|34`, `34|02`, `35|02`, `35|12`, `35|24`, `45|23`.
  - The share rises with the arm's score: correlation 0.69 (ours) and 0.65 (foe) over the 90 combinations. Sleep therefore hits the arms unequally, mostly the winning ones.
  - Stages 2 and 3 ran with #459 (visible sleep) merged, see below.

### Stage 2: confirmation (commit `37e7f508`, dirty: false, library built from it, 2026-10-13)

`37e7f508` is stage 1's commit with main merged in up to `0a5db340` (#461). That merge is the whole difference to stage 1's code: 62 commits of main, #459 (visible sleep, `8d3c0808`) among them, which change 21 files under `src/` and `include/`. The oracle's own code is unchanged. Seed `0x2026101300000459`, 7 arms of 256 pairs (512 games each, 3,584 games). No game was unfinished or unresolved, and all arms played the same foe draws.

| Arm | Lead | Back | Score [95 %] | Against `today`, points [95 %] |
|---|---|---|---|---|
| `23\|04` | Milotic + Ceruledge | Rillaboom + Raichu | 73.8 % [70.3, 77.3] | **+8.2 [2.9, 13.7]** |
| `23\|15` | Milotic + Ceruledge | Staraptor + Gholdengo | 71.9 % [68.0, 75.6] | +6.2 [1.0, 11.5] |
| `24\|03` | Milotic + Raichu | Rillaboom + Ceruledge | 71.5 % [67.6, 75.2] | +5.9 [0.6, 10.9] |
| `24\|13` | Milotic + Raichu | Staraptor + Ceruledge | 68.9 % [64.8, 72.9] | +3.3 [−2.1, 8.6] |
| `today` | (BC6 raw top-1, the four and leads of `24\|03`) | | 65.6 % [61.3, 69.7] | – |
| `02\|34` | Rillaboom + Milotic | Ceruledge + Raichu | 64.5 % [60.4, 68.6] | −1.2 [−6.2, 4.3] |
| `12\|03` | Staraptor + Milotic | Rillaboom + Ceruledge | 63.7 % [59.6, 67.6] | −2.0 [−7.2, 3.1] |

- **Result 1, the preview loss:** the best confirmed combination is the stage-1 winner `23|04`, so both reported numbers are the same: **+8.2 points [2.9, 13.7]** over `today`. The stage-1 estimate (+20.3) was inflated by the selection, as predeclared.
- **Reading (predeclared):** the upper bound is not below 3 points and the lower bound is not above 5 points. This is the middle case: reported as it is, with no conclusion beyond the numbers.
- **The sides and the bench order count:** `today` and `24|03` bring the same four with the same leads; they differ only in the lead sides and the bench order. They are 5.9 points [0.6, 10.9] apart.
- **By foe lead** (leads with at least 40 games), `today` / `23|04` / `24|03`:
  - Incineroar + Farigiraf (121 games): 91 / 88 / 84 %;
  - Charizard + Venusaur (113): **34 / 56 / 50 %**;
  - Charizard + Garchomp (74): 61 / 78 / 69 %;
  - Garchomp + Incineroar (40): 95 / 78 / 90 %.
- **Foe preview** (the same 512 draws in every arm): Charizard is brought in 449 of 512 games; the most frequent four is Charizard + Garchomp + Incineroar + Farigiraf (123).
- **Fallbacks per arm:** with #459, none on our seat in any arm; on the foe seat at most 0.6 % (152 decisions over all arms, all with an unsupported public record, none with visible sleep). No arm is more than 2 points above the median.

### Stage 3: fixed sun lead (commit `37e7f508`, dirty: false, the library of stage 2, 2026-10-13)

The code, library and seed of stage 2, with the foe's leads fixed to Charizard + Venusaur (`--foe-lead Charizard,Venusaur`); the foe's bench is drawn from its team head given those leads. 7 arms of 256 pairs (512 games each, 3,584 games). No game was unfinished or unresolved, and all arms played the same foe draws.

| Arm | Lead | Back | Score [95 %] | Against `today`, points [95 %] |
|---|---|---|---|---|
| `24\|13` | Milotic + Raichu | Staraptor + Ceruledge | 57.4 % [52.9, 61.7] | **+20.1 [14.8, 25.6]** |
| `23\|15` | Milotic + Ceruledge | Staraptor + Gholdengo | 51.8 % [47.7, 56.2] | +14.5 [8.6, 20.3] |
| `23\|04` | Milotic + Ceruledge | Rillaboom + Raichu | 49.8 % [45.3, 54.1] | +12.5 [6.6, 18.6] |
| `24\|03` | Milotic + Raichu | Rillaboom + Ceruledge | 45.5 % [41.2, 50.0] | +8.2 [2.9, 13.7] |
| `12\|03` | Staraptor + Milotic | Rillaboom + Ceruledge | 43.4 % [39.3, 47.5] | +6.1 [0.2, 11.5] |
| `today` | (the four and leads of `24\|03`) | | 37.3 % [33.2, 41.4] | – |
| `02\|34` | Rillaboom + Milotic | Ceruledge + Raichu | 36.1 % [31.8, 40.4] | −1.2 [−7.0, 4.7] |

- **The loss against the sun lead:**
  - the best of these arms, `24|13`, gains **+20.1 points [14.8, 25.6]** over `today`; it is selected on these games, so the number is biased upward;
  - the stage-1 winner `23|04`, not selected on these games, gains **+12.5 points [6.6, 18.6]**.
- **Reading (the predeclared thresholds):** both lower bounds are above 5 points. Against an opponent who always leads Charizard + Venusaur, the preview is a real lever.
- **Spread of the 6 combinations:** range 21.3 points, standard deviation 7.4, noise of one score 2.2, spread left after the noise 7.0 points (7.1 with the paired noise of stage 1's note, 2.1 points).
- **Against stage 2:** the order agrees with stage 2's games against the same lead (113 games per arm there), e.g. `today` 34 %, `23|04` 56 %, `24|13` 55 %.
- **Foe preview:** Charizard + Venusaur in all 512 games; brought with them most often Garchomp + Incineroar (134) and Incineroar + Farigiraf (127).
- **Fallbacks per arm:** none on our seat; on the foe seat at most 0.3 % (55 decisions over all arms, all with an unsupported public record). No arm is more than 2 points above the median.

### Summary

- **Against the opponent's usual previews** (BC6's team head), the best confirmed choice gains +8.2 points [2.9, 13.7]: Milotic + Ceruledge in the lead, Rillaboom + Raichu in the back. This is the predeclared middle case.
- **Against the fixed sun lead,** five of the six confirmed combinations beat `today` (all but `02|34`). The stage-1 winner gains +12.5 points [6.6, 18.6], and the best arm +20.1, selected on these games. The preview is a real lever there.
- **The spread of the 90 combinations** after the noise is 14.6 points by the predeclared formula, a lower bound under common random numbers (14.7 with the paired noise; stage 1).
- **The lead sides and the bench order count:** `today` and `24|03` bring the same four with the same leads and lie 5.9 points [0.6, 10.9] apart (stage 2).
- **Only this one team and BC6's preview on the foe side were measured.** A Book entry from this holds against this team; the archetype "sun" needs further teams. The opponent's best answer to our preview (its exploitability) is the next step of #458, with its own predeclaration.
