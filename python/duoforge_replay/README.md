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
    [--workers N] [--limit-parts N] [--unit-lines N] [--ps-dir <pinned Showdown>] [--node node]
```

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
Nothing is connected to training or M12 search; that requires a separate A/B measurement.

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

## Stops

A perspective stops at the first line the view cannot represent (`duoforge_live.lines`):
- a feature of decision 0018 whose `supported` bit is not set;
- an unknown line.

The decisions after the stop are counted and not written. When the library supports a feature, its lines are folded instead.
