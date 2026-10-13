# Preview oracle (issue #458): what the team preview costs against the Nationals sun team

**Question (owner, 2026-10-13).** Games are mostly lost at the team matchup or at the bring-4 choice. Before an opening book is built: against one fixed opponent, how much better than our current preview is the best bring-4 and lead choice, and how far apart do the choices lie?

This document is committed before the first measurement. Results are added below, aggregates only.

## Setup

- **Tool:** `python -m duoforge_search.preview_oracle` (this branch).
- **Teams:**
  - ours: Team A (`data/teams/A.txt`, the arena team);
  - foe: the sun team that won two Nationals in a row (test team of #458, as of 2026-10). Its sheet with stat points is a private file. Reports name its species, never a player.
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
