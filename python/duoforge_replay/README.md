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
