# M11: pick hypotheses for perspectives whose back picks the log does not show (design)

Status: owner decision via HauptSession (2026-10-11): pick hypotheses yes, as a marked source; rules below.

## Problem

A perspective stops with `picks-incomplete` at its first decision point after team selection when the log does not show which four members its player brought. A member that was brought but never switched in is invisible: the open sheet lists six, the log only those that entered.

| M-C Bo3, HF state 2026-10-05 | perspectives | hypotheses each |
|---|---|---|
| three of the four brought seen | 12,936 | 3 |
| only the two leads seen | 4,389 | 6 |

Together these perspectives hold 76,503 turns, about 12 % of the M-C Bo3 turns. None of them can be resolved exactly from the log. The view needs the picks at every point: `brought_order`, and each own member's location (BENCH or NOT_BROUGHT).

## Design

1. **Hypotheses.** For such a perspective (no Illusion holder, which keeps its own stop), the hypotheses are every pick tuple consistent with the log:
   - the two leads as seen;
   - the back members seen;
   - the missing back picks drawn from the sheet members never seen on the field.

   H is the number of combinations: 3 or 6. No hypothesis contradicts the log, because a candidate never entered.
2. **One run per hypothesis.** The perspective is folded once per hypothesis, with `picks` set to that tuple, and gives its own rows:
   - the own bench, and so the observation and the domain's switch options, follow the hypothesis;
   - the labels are the logged actions, the same in every hypothesis;
   - the team selection row is the one row it already has today, the union label over the consistent picks; it is not repeated.
3. **A common stop.** All hypotheses stop together at the earliest stop line of any of them, with that hypothesis's reason. A point any hypothesis cannot reach is a point none of them keeps.
4. **Marking.**
   - Each row stores `picks_hypotheses = H` (1 when the picks are known), together with its hypothesis index.
   - The dataset stays a sheet dataset, and its manifest records `pick_hypotheses: true`.
   - The rows of a perspective weigh 1/H each in `bc_data`.
5. **BC.**
   - `bc_data` leaves out rows with H > 1 by default.
   - `--pick-hypotheses-weight W` takes them in, at W/H per row. Like `bo1_belief`, the weight must be explicit.
   - Training with them waits for the validation below and for the owner, and BC is paused anyway.
6. **Funnel and turn coverage.**
   - These turns never count as "without a stop".
   - They get their own column: turns with pick hypotheses (the turns a hypothesis perspective keeps before its common stop), counted once per perspective, not once per hypothesis.
   - The headline number stays the turns without a stop over all sheet games (now 73.5 % for M-C).
   - `picks-incomplete` stays a stop reason for the games the hypotheses do not reach.
7. **Build option.**
   - A sheet build makes the hypothesis rows only with `--pick-hypotheses`, so a build without it is unchanged.
   - Both settings record it in their inputs, so a resume refuses the other one.

## Validation (before any training)

Take the test-split games with two sheets in which a perspective's four brought members were seen. In each such perspective, hide each seen back pick once from the hypothesis builder, so that it builds the three hypotheses as if that pick were unseen. Each hypothesis is folded as a build folds one, and compared with the true rows up to the hidden member's first switch-in, which is the last point a real unseen pick could cover. The compared points are those whose label lines end before that switch-in, so that the labels are complete in every fold.

- **(1) Correctness.** The true hypothesis's rows must be byte-identical to the real rows (observation, domain, extension record, label). Any difference is a bug.
- **(2) Effect.** The other hypotheses are measured by:
  - the share of rows whose observation differs, per field group, and whose domain or extension record differs;
  - the Jaccard of the legal pairs;
  - the share of informative label slots whose logged action is no option of the hypothesis (UNKNOWN where the real row knew it).
- **(3) How often the hypotheses differ at all** (HauptSession, 2026-10-11): the share of points at which all H rows are byte-equal. The own `brought_order` and the own members' locations differ by construction, so the share is reported three ways: in full; beyond those pick fields (observation, extension record, label); and in the domain. It is reported for the hidden picks and for the real hypothesis perspectives of the same games.

These measures show how much a wrong bench changes the rows BC would see. (c), the BC comparison, comes later, as for Bo1.

`python -m duoforge_replay validate-hypotheses --source PATH... --prior PRIOR.json --out REPORT.json [--workers N]` writes the report (aggregates only, outside the repository).

## Tests (made-up logs and the committed fixture)

- **Hypothesis count:** a perspective with three of four seen gives 3 hypotheses, with two of four 6. The picks are always the leads plus the seen backs.
- **Rows:** every hypothesis gives rows whose own bench matches its picks; all of them carry H and their index; the team selection row appears once.
- **Common stop:** a stop in one hypothesis only ends all of them at that line.
- **bc_data:** by default it loads no row with H > 1. With the flag it weights W/H, and the flag needs a weight.
- **Funnel:** turns with hypotheses are counted apart from turns without a stop; the headline number is unchanged by the option.
- **Validation:** with the hidden pick, the true hypothesis is byte-identical to the real rows.

## Cost

The rows of these perspectives multiply by about 3.8 on average, for about +0.8 M rows on M-C, or about +0.2 M at weight 1/H. A build takes up to about twice as long for these perspectives.
