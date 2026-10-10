# duoforge_replay: training rows from Showdown replays (M11)

Public Showdown replays of Reg M-C with open team sheets become rows for behavior cloning. Each row is one player at one decision:
- DuoForge's observation of that player;
- the superset options;
- the set of options the log shows the player chose.

Design: `docs/superpowers/specs/2026-10-02-m11-replay-data-design.md`.

**Data rule.** The replay dataset (HolidayOugi on Hugging Face) states no license. The following never go into this repository:
- the replays;
- the prior file;
- the shards;
- checkpoints trained on them.

The writer refuses an output directory inside the repository. Tests use only our own reference battles.

## Commands

```sh
python -m duoforge_replay prior --pastes <dir of pastes> --out <prior.json>
python -m duoforge_replay build --source <parquet or jsonl files or dirs> --prior <prior.json> --out <dir> \
    [--workers N] [--limit-parts N] [--unit-lines N] [--ps-dir <pinned Showdown>] [--node node]     [--format-prefix gen9championsvgc2026regmc gen9championsvgc2026regmb]
python -m duoforge_replay funnel <dir> [--top N]
```

A prefix that would take Reg M-A games (`gen9championsvgc2026regma`, or a shorter one) is refused. Reg M-A ran under
another mechanics era: Showdown before Champions 1.1.0, then a mod of its own. The owner excluded it on 2026-10-10.

The opening-book builder reads the same replay sources and writes count and win-rate tables:

```sh
python -m duoforge_replay.openings --source <parquet or jsonl files or dirs> --out <dir> \
    [--workers N] [--progress-interval SECONDS]
```

It defaults to up to 16 worker processes, or the number of available CPU cores if lower. Set `--workers 1` for a
serial run. The parallel runner reports progress to stderr every 10 seconds by default, and every run reports after
the final source unit. Reports include completed units, games read, openings processed and elapsed time. The JSON
output is derived from the unlicensed replay dataset, so keep `--out` outside the repository.

Opening exports now use **schema_version 2**. `leads_per_team` retains aligned `team_species`/`team_items`,
`opposing_team_species`, both lead pairs, `backs` (null unless both backs were observed), and `rating_band` plus
`opposing_rating_band`. Bands store `floor(rating / 100) * 100` (e.g. 1511 and 1599 both become 1500), or -1
if unknown; exact per-game ratings are not aggregation keys. Each perspective contributes once to the lead table.
Rating bands and back pairs
are part of the aggregation key, so they can be filtered or marginalized without guessing. Turn-1 rows retain
both rating bands and `side` (0/1), allowing protocol targets to be interpreted relative to the observing side.
Species-brought and compatibility tables remain descriptive summaries. Regenerate old schema-1 exports;
the missing fields cannot be recovered from those files. Experimental schema-2 exports with unbanded `rating`
fields must also be regenerated; the reader refuses them instead of guessing. Serial and parallel exports remain
byte-identical.

## Query the opening book

```sh
PYTHONPATH=python python -m duoforge_replay.book --book /private/openings.json \
    --own @/private/own.txt --foe @/private/foe.txt
```

`--own`/`--foe` accept literal Showdown pastes, `@paste-file`, or six comma-separated species names.
The book CLI needs NumPy for the existing shared dataset/path guard, but no battle library or replay processing.
Paste headers supply species and items; other paste lines are ignored. Species-only queries skip the item-exact
level explicitly. Names compare by Showdown ID spelling; use the exporter's canonical species names.
The module is read-only, refuses input paths inside any worktree of this repo via `refuse_repository`, and
never writes a derived cache. Keep redirected JSON output outside the repository too. Fixtures are hand-written
in test code and written only into temporary directories. Loading schema 1 or an unknown version fails explicitly.

Python API: `model = book.load(path)`, `model.leads(own_six, foe_six)`, and
`model.turn_1(own_ordered_pair, opposing_ordered_pair)`. Team entries may be species strings (items unknown) or
`{"species": "...", "item": "..."}` dictionaries (empty item means known no item). Pair queries preserve the
caller's a/b order for own slots. All answers identify their level, confidence, counts, win rates, normalized
probabilities and skipped levels. An empty answer has level `unavailable`; it never substitutes a uniform prior.

Lead backoff order:

1. `exact_team`: own species/items and opposing six species.
2. `team_ignoring_items`: both six-species teams, ignoring items.
3. `lead_pair_vs_opposing_lead_pair`: observed own pairs and foe pairs contained in the query sixes, marginalizing
   teams. Pass `opposing_leads=` to condition on a particular observed foe pair instead. Without it, the result
   explicitly reports `opposing_leads_marginalized`.
4. `single_species`: product of marginal lead-species frequencies, normalized across pairs with both species
   supported by at least `min_count` observations. This independence approximation can suggest unseen pairs;
   their pair `count` is zero and `win_rate` is null. `species_counts` and `support_count` expose the marginal
   evidence. Products are weights, never synthetic game counts. The result's `count` sums actual pair observations.

The first three levels require at least `min_count` matching perspective observations in total (default 20),
after source/rating filters. The threshold applies to a level's sample, not each candidate. Back pairs are
jointly distributed with leads when observed and contained in the query own six, otherwise null; no unseen
backs are filled in. Marginal species suggestions always have null backs. Win rates are `wins / decisive_count`;
ties and unknown winners do not enter the denominator. Confidence is a specificity label (`high` for item-exact
matchups, `medium` for species-team matchups, `low` for broader priors), not a calibrated statistical interval.

Turn-1 queries back off per queried actor from `exact_pairs` to `single_species`. Counts describe protocol
action observations, not distinct games or complete player decisions. Move rows and switches with
`switch_context == "choice"` contribute; pivot/replacement/drag switches and supplementary Mega events do not.
Only actors in the historical lead pair contribute; moves by Pokemon entering later are excluded.
The output retains `observed_slots` counts because query slots may differ from historical slots. Protocol targets are
made relative to the row's player (`own:a`, `foe:b`, optionally followed by the observed species); other targets
and missing targets are preserved. No target legality, slot remapping or action legality is inferred. These
are descriptive suggestions, not executable engine actions. Confidence is `medium` for exact pairs, `low` for species.

The default source is only `champions`. SV VGC requires `--source sv_vgc` (repeat `--source champions` to combine),
or `sources=("sv_vgc",)` in Python. `--min-rating`/`--max-rating` (Python: `min_rating`/`max_rating`) filter the
observing player's rating-band lower edge, inclusively. Bounds must be multiples of 100:
`--min-rating 1500 --max-rating 1500` selects the entire 1500-1599 band. Cutoffs such as 1550 are explicitly rejected because the
export cannot distinguish ratings within a band. Unknown ratings are excluded; a selected source with only unknown
ratings fails explicitly when a bound is requested. `opposing_rating_band` remains available in the export but is not filtered
by these options. `--min-count` changes the threshold. Equal probabilities sort by a fixed serialized key, so
input row order does not affect the result.

At preview, actual leads are unknown. The CLI prints turn-1 suggestions for an explicitly labeled hypothetical
scenario using the highest-weight own and foe preview suggestions. If either side has no supported suggestion,
`turn_1` is empty. Use `--own-leads SpeciesA,SpeciesB --foe-leads SpeciesC,SpeciesD` for a specific scenario.
The book is not connected to training or turn search. Evaluation can opt into preview-only use as described below;
the paired measurement must precede any recommendation to enable it by default.

## Opt-in preview evaluation and private A/B

Both `python -m duoforge_search.arena` and `python -m duoforge_learn.ladder` accept
`--book /private/openings.json --book-min-count 20 --book-mode override|prior --book-weight 0.5`.
Omitting `--book` returns the original player object, without extra network calls or output fields. In the arena,
the book affects only the candidate's preview (raw and searched configurations); opponents remain unchanged.
In the ladder, every selected player uses the same opt-in preview policy, including the best player's team matrix.
Ladder `--book` requires an explicit `--out` distinct from every input run directory, preserving the run's
ordinary `ladder.json`. Automatic `arena.best_checkpoint` refuses any ladder file containing a `book` key;
use an ordinary ladder or choose `--checkpoint` explicitly for book-influenced evaluations.
No battle-turn decisions or training paths consult the book.

Sheets come from the pool setups through the core's data-name API. Each query supplies both six-species teams and
both sides' open-sheet items. Schema 2 conditions on own items and opposing species (not opposing items).
The book's existing backoff selects an evidence level; **each full lead/back suggestion** must then
have at least `book-min-count` actual observed games. A level total, a marginal species support count, or a partial
lead-only observation does not meet that requirement. Unsupported choices fall back to the original network.
The wrapper does not skip to another evidence level if that level answered but its full choices fail this gate.

`override` ranks eligible choices by the lower Wilson endpoint using observed wins/decisive games and `z=1.96`,
reducing selection of noisy small-sample maxima. Ties use the serialized species key and then lowest legal joint
rank. The criterion is recorded as `wilson_lower_endpoint_z1.96`; it is a conservative ranking, not a calibrated
confidence guarantee for replay sampling. A missing decisive win rate cannot override. `prior` renormalizes the eligible book
probabilities and replaces the search's preview choice with the greedy argmax of `(1-weight)*net + weight*book`.
Search has no preview lookahead: the mixture uses its underlying network's preview distribution. The book stored unordered pairs:
its mass is divided equally across every ordering listed by the existing domain helpers for those exact leads
and backs. Override uses the lowest of those ranks. No backs, names, slot order evidence or legality are guessed.
Weight zero preserves the original choice without a second model application. Native domain/profile refusals,
missing backs, insufficient counts, query refusals and absent species are explicit causes.

Book diagnostics distinguish answered queries from applied choices, report backoff levels, count fallback games
per cause (causes may overlap), and separately count rejected suggestions. Arena summaries include these counts
per configuration; ladder summaries include them per player over its evaluated preview opportunities. A/B shares
use all budgeted games as denominator, including games that never reached a preview request. File checksums and
mode/minimum/weight are recorded only when enabled. Preview-only caches avoid recounting repeated sheet matchups;
these allocations are evaluation metadata, with no change to the C battle hot paths.

The separate CLI measures the same checkpoint with/without the book against the unchanged checkpoint and each
stage-1 opponent (BC = `params-0`, `params-3600`, `params-11000`):

```sh
PYTHONPATH=python python -m duoforge_search.book_ab --run-dir /private/run --checkpoint params-18129 \
    --panel-run-dir /private/stage1-run \
    --book /private/openings.json --out /private/book-ab --book-mode prior --book-weight 0.5 \
    --games 2000 --workers 8
```

`--panel-run-dir` explicitly identifies the stage-1 run for the default panel names. Alternatively,
`--panel BC_PATH,3600_PATH,11000_PATH` supplies three absolute checkpoint paths. The candidate's run is never a
default panel source, even when it contains checkpoints with the same names. Resolved panel paths and hashes
(and the candidate path/hash) are recorded in `summary.json`. Defaults are 2000 games **per arm
per opponent**, four opponents, and eight workers. The game budget must be even. Each sampled pairing has both
learner seat orders adjacent; the two arms use identical rows, batch seed, workers and cutoff. Bootstrap CIs
resample those seat pairs together, including the paired treatment-minus-baseline score interval. Reports include
score/CIs, answered/applied book shares and levels, per-cause fallbacks, and a breakdown by the learner's pool group
(`PP_/A/B/C`, `LL_`, or explicit `other`). `--seed`, `--max-steps` and `--resamples` are configurable.

The output directory must be empty and outside every repo worktree. It holds raw game CSVs, private preview event
JSON and `summary.json` with provenance and reports. These are book-derived data: never commit or upload them,
including derived aggregate numbers in this code PR. A later, separately authorized docs PR may publish aggregate
results only. The tests use hand-written books and temporary synthetic checkpoints, with a tiny native-engine
smoke and a NumPy backend stand-in; no private checkpoints or book files are needed. Do not launch the default
full measurement while the M12 arena is using the CPU.

`build` needs:
- NumPy;
- pyarrow, for parquet sources;
- the DuoForge library (`DUOFORGE_LIBRARY` or a build);
- Node and the pinned Showdown checkout (`ps_stats.js` computes the own side's stats).

**Parts and resume (for a long run on a VM).**
- The output is split into parts, one per source unit: a parquet row group, or `--unit-lines` lines of a JSON lines file. Which games a part holds depends on the source files only, never on the worker count.
- Each part is written to `part-<unit>.tmp/` and renamed to `part-<unit>/` when complete.
- Start the same command again after an interruption. It skips the finished parts, removes the half-written ones and writes the rest. It refuses an output that was started with other inputs (`replay-dataset.json`: sources, prior, filters, unit size, code commit).
- Each part holds its own shards, `games.npz`, `counters.json` and `manifest.json`.
- stdout gets one line per finished part (games, rows, seconds, games per second so far), for a first throughput reading.
- At the end, the output's `counters.json` sums all parts, and `manifest.json` records the provenance, the parts and the run.
- `dataset.read(out)` iterates all parts in name order. Each shard names its part, whose `games.npz` its rows index.

Between parts the build waits while the fuzz pause file exists. A full run is announced to the HauptSession first. Nothing assumes Windows: paths and the command line only (Linux VM: Python 3.12, NumPy, pyarrow, Node and the pinned Showdown checkout).

## What a row holds

| Array | Content |
|---|---|
| `observation` | `_layout.OBSERVATION`, from the player's side. The own side shows HP as the public percentage, PP from the uses seen, and stat points and stats from the prior (`prior_level` per member) |
| `domain` | `_layout.FACTORED_DOMAIN`: the superset slot lists and the full pair mask, or the team domain |
| `label_slots`, `label_team`, `label_reason` | the options that agree with the log, per slot (a 32-bit mask) or over the 360 team tuples (45 bytes); the reason per slot: `labels.EXACT`, `TARGET_UNKNOWN`, `MOVE_HIDDEN`, `FORCED`, `UNKNOWN`, `NOT_REQUESTED` |
| `game`, `side`, `point` | the game's index into `games.npz`, the player, the decision point |

`games.npz` holds, per game:
- the replay id;
- the format;
- the Bo3 game number;
- both ratings from the `|player|` lines;
- the winner;
- the turns;
- hashed player names and sheets.

`counters.json` counts every game, perspective and point that was skipped or stopped, by reason.

It also counts the **funnel** per format id, as `funnel.<format id>.<stage>`. `python -m duoforge_replay funnel <dir>`
prints it, aggregates only:

read -> not in the build's formats / without two sheets -> with sheets -> refused (names, legality, Illusion, Reg M-B PP,
...) or internal error -> set up -> perspectives to the end / stopped by reason -> rows.

Reg M-A shows as one line: its game count and "excluded".

## Stops

A perspective stops at the first line the view cannot represent (`duoforge_live.lines`):
- a feature of decision 0018 whose `supported` bit is not set;
- an unknown line.

The decisions after the stop are counted and not written. When the library supports a feature, its lines are folded instead.
