# A mixed team preview (issue #458)

**Question (HS, #458, 2026-10-14).** Does a mixed team preview cost the foe its best answer? A mixed preview picks our preview per game from a distribution: the equilibrium of the preview matrix, our previews against the foe's answers. Measured against the tournament sun team.
- **Why:** against one arena opponent we showed the same preview in all 69 games (live-play logs, aggregate count). That opponent then switched to a Charizard sun lead.
- **The single previews measured so far:**
  - our current preview is exploitable against this team (`docs/benchmarks/2026-10-13-preview-exploitability/`, 34.6 points [29.1, 39.8] at commit `d8f30c6a`);
  - the candidate `23|04` is measured in `docs/benchmarks/2026-10-14-preview-exploitability-candidate/`.
- **The aim:** a distribution over our previews that maximizes our worst case over the foe's answers, i.e. minimizes the preview exploitability. Against a fixed mix, no mixed answer of the foe does better than its best single answer, so the worst case is taken over single answers.

This document is committed before the first measurement. Results are added below, aggregates only.

## Setup

- **Tool:** `python -m duoforge_search.preview_oracle` (this PR).
  - `--our-mix 'ARM:P,...'` (foe side) picks our preview per game from a mix of `today` and combinations.
  - `--foe-mix 'ARM:P,...'` (ours side) picks the foe's preview per game from a mix of `drawn` and combinations.
  - A pick is a word of the game's decision key under a tag of its own, independent of the foe's `drawn` draw. Every arm of a run plays the same picks, so the arms stay paired.
  - An arm is refused unless every game picked, each pick played, and each arm of the mix was picked within 4 standard deviations (plus one game) of its expected count. The arm file records the picks and their counts.
  - `matrix DIR... --out FILE [--previous FILE]` reads foe-side runs of one measurement (one per preview of ours) into the matrix of our mean scores. It writes the matrix's exact equilibrium to FILE: our mix, the foe's mix and the value.
    - The rows are sorted (`today` first, then by name) and the columns too (`drawn` first), so the result does not depend on the order of the DIRs; where the equilibrium is not unique, this order picks one.
    - The equilibrium is solved in rational arithmetic (`duoforge_search.zero_sum`: the simplex method with Bland's rule). It is checked exactly before it is written. There is no approximate fallback.
    - With `--previous`, it also writes the gap of the earlier file's mixes on this matrix. The earlier file must be of the same measurement, and this matrix must extend it with the same cells.
  - The runs refuse to pair otherwise: a matrix needs one seed, pairs, commit, dirty state, library and set of foe arms in every run and arm file, with identical foe previews per arm and one preview of ours per row.
- **Everything else is the method of the measurement of `23|04`:**
  - the teams (ours Team A; the foe the tournament sun team, whose sheet is a private file);
  - ladder step 0 on both seats;
  - the common random numbers and the scoring;
  - 8 workers.
- **Arms and fixed order:** a combination's sides and bench order are the ascending ones, as in the preview oracle; `today` plays our search's own choice.
- **Machine:** the HS decides where the series runs.
  - On AWS, if #484 is on main and its equivalence proof is done. Only the HS starts it there.
  - Otherwise locally under `tools/ci/machine_lock.sh` and the WSL watchdog, spread over nights. The labels are `oracle-mix-*`.
  - The report names the machine of each stage. All stages run on one commit (this PR's merge commit, or a later main named before the start) with a library built from it.
  - Networks and outputs stay private, outside the repository.
- **Tool check:** a smoke run of 2 pairs (`--our-mix`, `--foe-mix` and `matrix`). It is not a measurement and is not reported.

## Stages (predeclared)

All matrix cells are played on one seed `0x2026101300000464` with **64 pairs** (128 games per cell). They are paired across rows and columns. A row is one foe-side run (`--our-arm ROW`, or no `--our-arm` for `today`) whose arms are the columns. A new column is added to every row's run, which resumes; a new row is a new run over all columns.

0. **Start:**
   - rows (our previews): `today`, `23|04`;
   - columns (the foe's answers): `drawn`, `15|23` (today's best answer, `d8f30c6a`) and `12|35` (the best answer to `23|04` from its screen, seed `…462`; that measurement's results are added to its README before this series starts).
   - Fill the 6 cells. `matrix` gives the equilibrium `m0`: our mix x0, the foe's mix y0 and the value.
1. **Round r = 1 to 4** (double oracle), with the mixes x and y of `m(r−1)`:
   - (a) **The foe's best answer to our mix:** a screen `--side foe --our-mix x --arms all` (`drawn` and the 90 combinations), 32 pairs. The answer is the screen's best combination (our lowest score, ties by name).
   - (b) **Our best answer to the foe's mix:** a screen `--side ours --foe-mix y --arms all` (`today` and the 90 combinations), 32 pairs. The answer is the screen's best combination (our highest score, ties by name).
   - **Screen seeds:** round r screens (a) on `0x2026101300000465 + 2 (r − 1)` and (b) on the next seed. Round 1 is `…465` and `…466`, round 4 is `…46b` and `…46c`.
   - (c) **Fill:** a new column or row is added only if it is not already in the matrix. Its cells are played at 64 pairs on `…464`. If neither answer is new, the round stops the series (the screens find nothing beyond the matrix).
   - (d) **The gap:** `matrix --previous m(r−1)` on the filled matrix.
     - It is our best row's score against y minus our score against the foe's worst column for us under x: how much a best answer in the filled matrix gains against round r − 1's equilibrium, in points.
     - It is measured **on the filled cells at 64 pairs, not on the screens** (HS). The new equilibrium is `m(r)`.
   - **Stop** when the gap is **below 3 points**, or after **round 4**, whichever comes first.
   - The final mix x\* is our mix of the last `m(r)`.
   - The screens only select: no number of them is reported as a result.
2. **Final measurement on fresh seeds:**
   - (a) **Screen:** `--side foe --our-mix x* --arms all`, 32 pairs, seed `0x202610130000046d`. Its 5 best answers of the foe are our 5 lowest scores, ties by name.
   - (b) **Confirm:** `--side foe --our-mix x*`, arms `drawn` and those 5, **256 pairs**, seed `0x202610130000046e`. That makes 6 arms and 3,072 games.
   - (c) **Controls on the same seed `…46e`, 256 pairs:**
     - today: no `--our-arm`, arms `drawn` and `15|23`;
     - `23|04`: `--our-arm '23|04'`, arms `drawn` and `12|35`.
     - That makes 4 arms and 2,048 games.
   - **Pairing check:** the comparisons are refused unless the three `drawn` arm files have identical foe draws (`foe_drawn`) and the runs the same seed, pairs, commit and library.

The whole series is about 20 to 25 hours at the local pace (about 47 games a minute with 8 workers): the matrix cells, two screens per round and the final measurement.

## What is reported

- **The mix:** x\* and the foe's mix of the last matrix, the value of each `m(r)`, the gap of each round and why the series stopped. All are on the filled cells at 64 pairs; the matrix itself is in points.
- **The mix's preview exploitability (the headline number):** stage 2's score of x\* against `drawn` minus its score against **the final screen's best answer**, in points. It is paired over game pairs with a 95 % pair-bootstrap interval.
  - Beside it: the best of the 5 confirmed answers, marked "selected on stage-2 games, biased upward".
- **The worst-case comparison (headline of the comparison):** x\* against its final screen's best answer (stage 2b) minus today against `15|23` (stage 2c). It is computed as `paired_difference(best_mix, answer_today)` over the game pairs of seed `…46e`.
- **The gain against `drawn`:** x\* against `drawn` minus today against `drawn`, i.e. `paired_difference(drawn_mix, drawn_today)`, paired.
- **Beside them, without a reading:**
  - the same two comparisons against `23|04` (with `12|35` as its answer);
  - the exploitability differences, mix minus today and mix minus `23|04`.
- **Per arm:** unfinished and unresolved games, both seats' raw-fallback shares and their causes, and the mix's pick counts. An arm whose share is more than 2 points above its seat's median is named, with its causes.
- The comparisons are computed outside the tool from the runs' arm files (`scores`), with `preview_oracle.paired_difference` at its default bootstrap seed.

## How it is read (predeclared)

- **The mix's exploitability:** the thresholds of the earlier measurements.
  - Exploitable if its 95 % lower bound is above 5 points.
  - Little to gain for the foe if its upper bound is below 3 points.
  - Otherwise no conclusion beyond the numbers.
- **A candidate for the book (#458, HS, 2026-10-14), the conditions of `23|04`:** the mix is a candidate only if both hold.
  1. **Worst case:** the 95 % **lower bound** of the worst-case comparison is **above −5 points**.
  2. **Better against `drawn`:** the 95 % **lower bound** of the gain against `drawn` is **above 0**.
- An undecided result does not count as better: a condition whose lower bound is not above its threshold fails. The report names each condition that failed, and says whether the interval lies wholly below the threshold or only reaches below it.
- The comparisons against `23|04` and the exploitability differences are reported without a reading.

## Live play (not measured here)

- Whether a mix plays live is decided apart, by the owner and the HS.
- **If it ever does, its randomness comes only from a private source.** It never comes from the room id, the foe's name or any other data the foe can see or know. A pick the foe can compute is no mix.
- The measurement here picks from its seed: it is offline, and its picks must repeat.

## Caveats

- One foe team only, and the caveats of the earlier measurements:
  - both pilots are the same search, at step 0 (live play has used step 2e since 2026-10-14);
  - the previews have fixed sides and bench order;
  - the foe does not adapt during a set;
  - the reference `drawn` is BC6's own preview distribution, not an observed opponent's.
- The double oracle searches its answers with screens of 32 pairs. A best answer that the screens miss is missing from the matrix, and the gap does not see it. The final screen and confirmation on fresh seeds check the mix against all 90 answers again.
- The matrix's equilibrium is exact for the matrix, but its cells are estimates (128 games each). The stop rule and the final measurement allow for that; the matrix value itself carries no interval.
- `15|23` was selected on the screen of `d8f30c6a`, `12|35` on the screen of `23|04` (seed `…462`), on other games than the final measurement's.
