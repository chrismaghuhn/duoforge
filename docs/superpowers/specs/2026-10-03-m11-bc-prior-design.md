# M11 behavior-cloning prior: design

Date: 2026-10-03. Status: the owner approved approach A, the value head and Reg M-B as a second source (morning list items 8, 9 and 12, "alles ja", 10:52); this spec is for his review.

Builds on:
- the M11 replay data spec (`2026-10-02-m11-replay-data-design.md`) and decision 0019;
- Learner v2 (#174, decision 0017) and Encoder 3 (#178, decision 0018);
- the data API of decision 0020 (#164), which `duoforge_live.data` reads since #166.

## 1. Goal

Learner v2 first learns human play from the replay rows (behavior cloning, BC). PPO then starts from that network instead of random weights.

**Success** (performance claims need measurements, section 10):
- On held-out games, the BC network assigns the logged choices a clearly higher probability than a random network does (NLL, top-1 on EXACT labels).
- The BC network beats the random network and `ScriptedPolicy` in `evaluate.win_rate` on Learner v2's teams.
- PPO with `--init` from the BC network is stronger after the same wall-clock time than PPO from scratch, at the same seed and settings.

M-C comes first. Reg M-B joins afterwards in the same PR (section 11; owner OK to item 8).

## 2. Decisions

**Owner (2026-10-03)**
- **Approach A:**
  - A separate step, `python -m duoforge_learn.bc`, trains on the shards and writes an ordinary format-2 checkpoint.
  - `train.py --init CKPT` starts a new PPO run from it.
  - Rejected: B (BC as an extra loss inside PPO), which mixes two data sources into one run. C (a frozen BC reference with a KL term in PPO) builds on A later (section 12).
- **Earlier (2026-10-02, data spec section 2):**
  - BC on open-sheet games, weighted by outcome or Elo.
  - Then PPO with a KL term toward BC.
  - Data and anything trained on it never go into the repository.

**Owner (2026-10-03, 10:52, morning list)**
- **Item 12:** approach A, with a value head trained on the game outcome at a small weight (section 6). M-C first, then M-B.
- **Item 8:** Reg M-B is a second BC source. The data rule stays.
- **Item 9:** the newer M-C Bo3 replays may be downloaded (about 12k requests, at most 1 per second, with backoff).
  - The User-Agent names the repository URL and no e-mail address.
  - The download script, without data, may go into the repository.
  - It is its own small PR. This spec covers only how its JSONL output joins `--data`.

**Agreed with the HauptSession**
- **Mask transition on `--init`:** see section 8.

## 3. Inputs

- **Shards:** shards of `duoforge_replay` (`dataset.read(out)`). Per row:
  - `observation` (OBSERVATION) and `domain` (FACTORED_DOMAIN);
  - `label_slots` (2 × u32), `label_team` (45 bytes), `label_reason` (2 × u8);
  - `game`, `side`, `point`, `prior_level`.
- **Games:** `games.npz` per part gives:
  - the replay id and the format;
  - the ratings of both players;
  - the winner;
  - the hashed sheets.
- **No extension records.** The tracker stores none. So the encoder mask can hold only base-value bits (section 5).

## 4. Architecture

| Unit | Kind | Role |
|---|---|---|
| `python/duoforge_learn/bc.py` | new | The BC trainer and its CLI (`python -m duoforge_learn.bc`). |
| `python/duoforge_learn/bc_data.py` | new | Reads the shards, encodes them once (`features.encode_batch`), splits by game, gives the row weights and the value targets, and yields batches. |
| `python/duoforge_learn/train.py` | changed | Gets `--init CKPT` (section 8). |
| `python/duoforge_learn/checkpoint.py` | changed | Gets `zero_columns(params, config, names)`, which zeroes the input rows of named feature columns (the mechanism of `widen`). |
| `python/duoforge_live/lines.py`, `tracker.py` | changed | Fold the base-value features (section 5). |
| `python/duoforge_live/data.py` | changed | Resolves the cosmetic aliases (section 5). |

`duoforge_replay/game.py` also changes: it normalizes alias names on the sheets.

`policy.make`, `model_v2` and the checkpoint format stay as they are. A BC checkpoint is a format-2 checkpoint:
- **`model`:** the v2 config, taken from `--preset` and the dimensions as in `train.py`.
- **`encoder`, `features`, `slot_features`:** the current layout.
- **`ext_supported`:** the BC mask.
- **`data`:** `{kind: "pool", fingerprint}`.
- **`teams`:** `[]`. The league and `_check_teams` read the teams from the PPO run, not from the init checkpoint.
- **`update`:** 0.
- **`decisions`:** the number of training rows.
- **`train`:** `{"seed": seed, "bc": {...}}`. `bc` holds the dataset manifest's fingerprint, the format prefixes, the split, the weights and the epochs. `seed` sits on the train level because `ladder.main` reads `config.get("train", config)["seed"]` for a run's first player.
- **The ids of the embeddings:** the name lists (or a hash per prefix) that `checkpoint.check_ids` needs. Model v2 embeds species, moves, items, abilities and natures by table id; section 8 says why.

## 5. Data and encoding

**Encoder mask**
- `ext_supported = features.BASE_VALUE_FEATURES & library`.
  - `library` is the mask of the loaded library at run time: the `supported` of a POOL batch's `observe_ext`, read as `SelfPlay` does since #178. It is never `lines.LIBRARY_SUPPORTED`, the mask parsed from `support_manifest.c`. `--init` checks a checkpoint against this run-time value (`check_ext_supported`), so a BC checkpoint built against a stale build or another source would be refused there.
  - Today the mask is Sand, Snow and Tox; Electric and Misty come after #163.
- **A hard check:** `bc.py` requires `lines.LIBRARY_SUPPORTED` (the tracker's parse) to equal the run-time mask. Otherwise it raises a ValueError naming both values. The rows were folded under the tracker's view of support, and the network must learn under the same mask.
- `features.encode_batch(observations, domains, ext=None, ext_supported=mask)`.
- A record bit or a value outside the mask raises (Encoder 3's rules), so rows and mask must agree.

**Tracker folds for the base-value bits**
- The tracker folds these features:
  - Sand: `-weather Sandstorm` and its residual `-damage [from] Sandstorm`;
  - Snow: `-weather Snowscape`/`Snow`;
  - Tox: the `tox` status;
  - Electric and Misty terrain.
- Each fold follows the existing rule: it is folded exactly when the library's `supported` mask has the bit (`TRACKER_FOLDS` gets those bits). Otherwise the line stops as today.
- The view reads the weather, terrain and status values the engine has. The converter already parses these lines.
- Sand and Snow are the largest curable stops today (M-C on 2026-10-03: Sand 6,989 and Snow 4,316 perspectives).
- Extended weather (Smooth Rock, Icy Rock) keeps stopping (`_extended_field`).

**Aliases (#118)**
- `data.forme` resolves a name that is not in the converter's tables through `duoforge_data_find`. The cosmetic aliases (Sinistcha-Masterpiece, the Vivillon patterns) map to their base row.
- `game._prepass` writes the canonical name into the sheet before `parse_team`.
- A name the library does not find stays a `name:` skip.

**Split**
- By team pair, so Bo3 games of one match never straddle the split.
- The key is the sha256 of the two sorted sheet hashes in `games.npz`. Bucket 0 of 20 is the validation set (about 5 %).
- The split is deterministic and is recorded in the checkpoint.

**Encoding cache**
- The training rows are encoded once and kept in memory as float32 obs (N × 842), slots (N × 2 × 32 × 12) and a bool mask (N × 32 × 32). That is about 2.3 GB for M-C (32 GB RAM on the machine).
- `--cache DIR` (outside the repository) can keep them on disk as `.npy` files for repeated runs. They are keyed by the dataset fingerprint and the mask.

## 6. Loss and weights

**Moves**
- The label set of a decision row is `L = {(i, j) : bit i of label_slots[0], bit j of label_slots[1]} ∩ pair_mask`. The pair index is `i*32 + j`.
- `loss_pairs = −log Σ_{p∈L} P(p)` = `−logsumexp(logp_pairs[L])`.
- A slot with reason FORCED or NOT_REQUESTED has its whole list as its set (one option for FORCED), so it adds no information beyond the other slot.
- An empty `L` is an error (ValueError): the labeler guarantees the true choice is inside.

**Team selection**
- `loss_team = −logsumexp(logp_team[label_team bits])` over `TEAM_TABLE`. It is the same `permutations(range(6), 4)` order in `duoforge_live.game` and `selfplay`, and a test checks that.

**Value**
- `loss_value = (value − z)²` with `z = +1` if the row's side won and `−1` if it lost.
- Games without a winner (`winner = −1`) add no value term.

**Total and row weights**
- Total: `Σ w · (loss_policy + c_v · loss_value) / Σ w`, with `c_v = 0.25` (`--value-coef`).
- Row weights, `--weights rating` (default):
  - `w = 1` for a player rating of at least 1300;
  - rising linearly from 0.25 at 1000 to 1 at 1300;
  - 0.25 below 1000 or unrated.
- `--weights uniform` gives `w = 1`.
- The rating is the acting side's own, from the `|player|` line.

**Optimizer**
- `ppo.optimizer` (Adam with global-norm clipping, `--learning-rate`, default 3e-4).
- Batches of 1024 rows, shuffled by `--seed`.

**Stopping**
- An epoch ends with a validation pass: weighted NLL, top-1 on EXACT slots, and the value MSE.
- Early stop after 2 epochs without a better validation NLL (`--patience`), at most `--epochs` (default 20).
- The best epoch is the checkpoint `bc.npz`.

## 7. Commands

```sh
python -m duoforge_learn.bc --data <dataset dir> [<dataset dir> ...] --out <dir outside the repo> \
    [--preset M] [--embed ... like train.py] [--epochs 20] [--patience 2] [--batch 1024] \
    [--learning-rate 3e-4] [--value-coef 0.25] [--weights rating|uniform] [--seed N] [--cache DIR]
python -m duoforge_learn.train --out <dir> --init <dir>/bc.npz [usual train.py options]
```

`bc.py` writes `bc.npz`, `bc-log.jsonl` (one line per epoch with the train and validation metrics) and `bc-run.json` (the inputs).

## 8. `--init` in `train.py`

**Run setup**
- `--init` starts a new run (`--out`). It cannot be combined with `--resume`.
- A resume of an `--init` run does not apply `--init` again. `"init"` is in the run state, and `--init` is not in `_RESUMABLE`, so a resume that gives it is refused.
- The parameters come from `checkpoint.load_current(CKPT)`. A narrower feature layout is widened by name, as on resume.
- The optimizer, the league and the RNG start fresh. The league's first snapshot, `params-0`, is the initial network.
- The counters start at `update = 0` and `decisions = 0`, whatever the checkpoint holds: the entropy schedule runs over the learner's own decisions.

**Model and data checks** (only options given explicitly are compared, `args._given`, as `_merged` does; otherwise the defaults `--model` and `--data-kind closure` would refuse every `--init`)
- The model config and `data.kind` are inherited from the checkpoint when not given.
- A given `--model`, `--preset`, dimension or `--data-kind` that differs from the checkpoint is refused.
- **Ids across data versions** (Learner v2's open point, its spec 12.4):
  - `--init` compares `config.data.fingerprint` with the run's context.
  - If they differ, it checks the name lists per embedding kind: every old id must still name the same row, and rows appended at the end are fine. Otherwise it refuses explicitly. `load_current` widens by column name only, so a shifted id would point every embedding at the wrong row in silence.
  - The check is `checkpoint.check_ids(config, context)`, which Learner v2 builds for resume. Learner v2 sends its signature before `--init` is built; `bc.py` stores what it needs (section 4).

**Mask transition** (HauptSession and Learner v2, 2026-10-03)
- The run's `ext_supported` defaults to the library's run-time mask, as for a run without `--init`. An explicit `--ext-supported` overrides it, and `SelfPlay` checks it against the library (`check_ext_supported`).
- Every bit the run has beyond the checkpoint's mask is accepted only by zeroing the input rows of every feature column it switches on. This is `checkpoint.zero_columns`, the same row lookup as `widen`.
- The zeroing is exact. Those columns were always 0 in BC training, so the network starts with identical outputs on every row, and the new features are learned from zero. Without the zeroing, the rows would still hold their random init and act at once.
- If a column cannot be zeroed by name, `--init` refuses the larger mask explicitly.
- A smaller mask is refused: the network relied on those columns.
- The run logs the transition under `"changes"` (`ext_supported: old → new`). The snapshot config gets `"init": {"path", "fingerprint of the checkpoint file", "ext_supported"}`.

Learner v2 reviews this section, since `train.py` is its file.

## 9. Data rule

- The shards, `bc.npz`, the cache and every PPO checkpoint that descends from a BC network never go into the repository.
- `bc.py` refuses an output or cache directory inside any work tree of the repository (`dataset.refuse_repository`). `train.py --init` refuses an `--out` inside the repository.
- The checkpoint's `train.bc` names the dataset's fingerprint, so its provenance is traceable.
- Tests use our own fixtures only: shards built in the test from the committed reference battles and `c12_real_cb_4.log`, with the pipeline of #120.

## 10. Measurement

GPU runs (RTX 4060 Ti) only outside the measurement windows, announced to the HauptSession, and never during Learner v2 measurements.

1. **BC on M-C:**
   - the validation NLL, top-1 (EXACT slots), and value MSE per epoch;
   - for comparison, the same metrics of the random initial network.
2. **Play:** the BC network against the random network and against `ScriptedPolicy`, on Learner v2's POOL teams, with a fixed seed and enough games for a ±5 % interval.
   - It uses `suite.make_suite` with a `teams.load` pool, `evaluate.play_suite` and `evaluate.scores`. (`evaluate.win_rate` plays the CLOSURE reference pairings A/B, not POOL teams.)
   - The learner is an `evaluate.Player` with the checkpoint's `ext_supported`, as in the ladder.
3. **PPO:** two runs with the same seed, settings and minutes, one with `--init bc.npz` and one from scratch. Compared:
   - the ladder and the evaluation against `ScriptedPolicy` at equal wall clock;
   - the curves.

The report gives the numbers. A claim without a number is not made.

## 11. Reg M-B (owner OK, item 8; after M-C in this PR)

- `--data` takes several datasets.
- The build takes several format prefixes.
- M-B rows get the same treatment, plus explicit skips:
  - Strength Sap and Wish (their PP differ);
  - a sheet that POOL does not accept.
- `lines._kept_drop` accepts the full stat names that older servers write (`Attack`).
- The format id is in `games.npz`. `--format-weight regmb=0.5` (default 1) can weight M-B rows down.

## 12. Later (not in this PR)

- **C:** PPO with a KL term toward the frozen BC network (`--kl-ref`, `--kl-coef`).
- The extension records in the tracker, which allow a full encoder mask for BC (the HauptSession's follow-up, 0018 section 10).
- The download of the newer M-C Bo3 replays (item 9, approved): its own small PR; its JSONL output is one more `--data` source once built.

## 13. Errors

Every case fails explicitly; there is no silent fallback:
- an empty label set or a label outside the domain;
- a row whose observation or domain does not encode under the mask;
- a dataset whose rows were written under another library fingerprint than the run's (`replay-dataset.json` inputs);
- `--init` with a checkpoint of another model, kind or narrower mask;
- an output inside the repository;
- the tracker's parsed support mask differing from the loaded library's run-time mask (both named).

## 14. Tests

**Without JAX** (`duoforge.python.learn_v2_numpy` / a new `duoforge.python.bc_numpy`)
- The label-set loss against a brute-force sum over pairs and teams, including FORCED and NOT_REQUESTED slots and an empty set (error).
- The split: deterministic, by team pair, with Bo3 games of one match on the same side.
- The rating weights.
- `TEAM_TABLE` order equal in live and selfplay.
- `checkpoint.zero_columns`: the named rows are zero, and the other rows are unchanged.
- The mask check: a tracker mask that differs from the library's run-time mask raises, naming both.

**With JAX** (`duoforge.python.learn_v2`, needs `DUOFORGE_LEARN_PYTHON`)
- `bc.py` on a mini dataset from our fixtures for one epoch:
  - the loss falls;
  - the checkpoint loads with `checkpoint.load_current`;
  - its config has every format-2 key.
- `train.py --init` with the BC checkpoint:
  - the first snapshot equals the BC params;
  - the same mask gives identical outputs;
  - a larger mask gives zeroed rows, identical outputs on rows without the new features, and the change in `"changes"`;
  - the first log record has `decisions` from 0 (and `update` 0);
  - not giving `--model` or `--data-kind` inherits them from the checkpoint;
  - a smaller mask, a given model or kind that differs, `--resume` together with `--init`, or a resume of an `--init` run that gives `--init` are all refused;
  - ids that a data version shifted are refused (`checkpoint.check_ids`), while appended rows are accepted;
  - `ladder.main` accepts a BC checkpoint as a run's first player (`train.seed`).

**Tracker**
- Folds of Sand, Snow and Tox:
  - the replay equivalence test (`duoforge.python.replay`) covers the committed battles with them (g22_sand_rush, g22_speed_tie_snow, g30_solar_beam_sand_snow, g36_toxic_a, among others);
  - unit tests in `test_replay_unit` check the fold and that an unsupported bit still stops.
- Aliases: a sheet and a log with Vivillon-Pokeball and Sinistcha-Masterpiece run through the fixture without a stop.
