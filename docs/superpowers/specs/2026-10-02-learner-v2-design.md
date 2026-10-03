# Learner v2 for many teams — specification

Decision: `docs/decisions/0017-learner-v2.md` (written with the plan). Builds on decisions 0013 (Python adapter), 0014 (learner pipeline) and 0015 (content expansion, POOL). Status: draft for the owner's review, 2026-10-02.

## 1. Goal

The next training run uses at least 6 to 12 real Reg M-C tournament teams. In the long term the pool grows past 100 teams as the expansion completes them: the M-C sheet has 382 pastes with Stat Points. Later, random teams are mixed in.

Learner v2 makes the learner ready for that:
- **Teams.** They come from the shared registry. The library sets them up and refuses what it does not support.
- **Self-play** covers all N² ordered pairings, with a weight per team.
- **League.** An opponent pool of past checkpoints works against cycling.
- **Entropy schedule.**
- **Resume.** A run can stop and resume, also with more teams or a wider encoder.
- **Evaluation and a ladder per team.**
- **Model v2** sees what is on the field, at a configurable size.

**Success for the stage with Teams A, B and C** (owner, 2026-10-02: "pipeline plus measurement"):
- Everything above runs on the 9 pairings of A, B and C, including a run that is interrupted and resumed.
- Measured at equal decisions: v1 against v2, and three v2 sizes (about 0.35, 2 and 8 million parameters).
- A report in `docs/learning/`.

No learning threshold is a merge condition. The numbers decide the configuration of the first run on 6 to 12 teams.

## 2. Decisions and agreements (2026-10-02)

**Owner**
- Model v2 with embeddings is part of this work, measured against v1.
- The A/B/C stage must show the pipeline plus measurements.
- Approach A: extend the synchronous loop of decision 0014. Asynchronous actors come only when measurements show the need.
- Long-term goals, relayed by the HauptSession:
  - 100+ teams;
  - the network size is configurable, 1 to 10 million parameters are realistic, and the effect is measured;
  - teams are added on resume;
  - checkpoints are widened exactly when OBS_SIZE grows;
  - later, random teams are mixed with tournament teams, made by one generator shared with the fuzzing.
- Hardware, relayed by the HauptSession:
  - The first runs (A/B/C, then the first 6 teams) run locally at night with 8 threads.
  - A rented machine comes only for long or parallel runs. Resume is required anyway.

**Review.** The HauptSession agreed to all six design sections. Its changes are adopted here. The owner approves the written spec and the plan himself.

**Expansion lead**
- One team registry for fuzzing and training: `data/teams/`, built by Builder A in A7.
- POOL gets learnsets: P1 was amended.
- The lead's track defines the frozen pool profile once about 6 complete curve teams exist.
- One data query API for names and legality, built by the lead's track after P1 (section 5.2).
- This track owns the random-team sampler, after stage 1.

**Versions.** The HauptSession assigns them at merge, in merge order. P1 has 0.20.0.

## 3. Findings that shape the design

1. **One set per forme under CLOSURE and TEAM_C.**
   - A forme row has one ability and at most four set moves, and setup requires the forme's set.
   - 15 of the 17 teams in `curve.txt` use a table move outside their forme's set, for example Milotic's Protect or Golisopod's Sucker Punch. The gap count, which looked only at names, was optimistic.
   - P1 now gives POOL learnsets and legal abilities. CLOSURE and TEAM_C stay frozen.
   - Trainable today: Team A (= MC405), Team B (= MC408) and Team C.
2. **Model v1 cannot see identities.**
   - The encoder scales species and move ids by 65535, and items and abilities by 255, so that a network can recover them for an embedding. Model v1 feeds them to its MLP as scalars.
   - In the night run's last checkpoint (update 30415), the first-layer weights of the species inputs keep the scale of all the others: mean |w| 0.079 against 0.080. So a species input moves a unit by at most 3.2·10⁻⁴.
   - A move option says "move slot k", not which move it is.
   - With two fixed teams, the stats identify the members. With many teams, and the same species in other sets, they do not.
3. **The engine is not the night run's limit.**
   - Median per update in the night log: collection 0.26-0.29 s, update 0.30-0.31 s.
   - Throughput reference points:
     - The engine runs 2.5 to 3.1 million decisions per second natively on 16 workers (M6 report).
     - The Python loop with the random policy reaches 1.5 million (PRs #64 and #65).
     - The learner's loop reached 26,000 with 8 workers.
   - So the engine is a small part of the collection. The estimate for the rest is the Python thread: the encoder, ctypes and JAX calls. Part 9 measures the split.
   - The update copies about 16 MB from host to device per minibatch (slots and mask).
   - More CPU cores speed up only the engine part.
4. **Encoder defect.**
   - `features.py` derives a member's `present` from `species_id != 0`. Forme id 0 is Rillaboom, so a registered Rillaboom reads as absent (verified with Team A).
   - A separate fix PR repairs it. The v1 legacy path is in section 9.4.

## 4. Parts and order

| Part | Content | Depends on | Built by |
|---|---|---|---|
| 1 | C: batch reset with new setups | — | this track |
| 2 | C: data query API (names, legality, support) | P1 | the lead's track |
| 3 | Python: `duoforge.teams`, the registry loader | 2, A7 | this track |
| 4 | Python: `features.FEATURE_NAMES` | — | this track |
| 5 | Learner: model v2, checkpoint v2, widening | 4, encoder fix | this track |
| 6 | Learner: team pool, pairings, league | 1, 5 | this track |
| 7 | Learner: entropy schedule, run state, resume | 6 | this track |
| 8 | Learner: evaluation and ladder per team | 5, 6 | this track |
| 9 | Throughput (phase timings, transfer fix), measurements on A/B/C, report, runbook | 3, 7, 8 | this track |

- Parts 1 and 4 to 8 start at once. They are tested with Teams A and B through `duoforge.reference_setups`.
- Part 3 follows once part 2 and A7 are on main.
- Part 9 runs on A, B and C.
- Each part is one PR:
  - It passes the full local CI (`tools/ci/local_ci.sh`, 11 jobs).
  - A code PR also gets a review agent (`fullstack-dev-kit:pr-reviewer`, Opus).
  - The HauptSession merges.
- A C part is announced to the HauptSession before its PR, for the version number.

## 5. Library

### 5.1 Batch reset with new setups (part 1)

```c
/* Resets environment envs[i] to episode episodes[i] with setup setups[i], for
   i < count. Each setup passes the checks of duoforge_battle_create (its rng
   fields are replaced by the seed derivation, as at create and reset),
   becomes the environment's setup, and a fresh battle starts. Outcomes are
   atomic per environment: a failing environment keeps its setup and its
   battle, and its status goes to statuses[i] when statuses is given. The call
   returns the status of the lowest failing i, or OK.
   Checks before any change:
   - NULL batch, or NULL envs, episodes or setups with count > 0:
     E_NULL_ARGUMENT;
   - an environment out of range or listed twice: E_INVALID_ARGUMENT,
     and nothing changes.
   count 0 is a no-op. It runs on the batch's workers and allocates as
   duoforge_batch_reset does: one fresh battle per environment. */
duoforge_status duoforge_batch_reset_setups(duoforge_batch *batch, uint32_t count, const uint32_t *envs,
                                            const uint32_t *episodes, const duoforge_battle_setup *setups,
                                            duoforge_status *statuses);
```

- **Seeds.** The seeds stay a pure function of the batch seed, the environment and the episode (`duoforge_batch_seeds`). The setup does not enter them.
- **Python.** `Batch.reset_setups(envs, episodes, setups)` takes NumPy arrays (uint32, uint32, `SETUP` records) and raises like the other batch calls, naming the lowest failing environment.
- **Tests:**
  - A reset with a new setup plays exactly what a fresh batch created with that setup plays at that episode (digests equal).
  - A refused setup leaves its environment, setup and battle unchanged, while the other entries go through.
  - An environment that is out of range or duplicated changes nothing.
  - The NULL checks hold.
  - The worker counts 1 and 4 give equal results.

### 5.2 Data query API (part 2, the lead's track)

There is one header section for names and legality, one PR and one version bump, after P1. The lead specifies the legality queries:
- the allowed moves and abilities per forme under the context's kind;
- the legal genders;
- the Mega forme and its stone;
- the support status of each id;
- the Stat Point rules.

The setup validation stays the final judge. The names part is what this track needs:

| Function | Contract |
|---|---|
| `duoforge_data_find(ctx, table, name, length, &id)` | Finds an id by name. Tables are `SPECIES` (base and Mega formes), `MOVE`, `ITEM`, `ABILITY` and `NATURE`. Names are Showdown ids (toID: lowercase letters and digits), generated by `gen_closure.py` with the tables and kept outside the fingerprint. A name that is not in the context kind's tables, or one whose id is at or past the kind's count, gives E_INVALID_ARGUMENT: a POOL move is refused under TEAM_C. SYNTHETIC gives E_UNSUPPORTED. |
| `duoforge_data_name(ctx, table, id, &name)` | Gives the name of an id, as a pointer into constant data. It serves logs, ladder tables and the name check on resume. |
| `duoforge_data_count(ctx, table, &count)` | Gives the kind's count. |

Tests:
- every row round-trips;
- an unknown name and an id past the kind's count are refused;
- the NULL checks hold;
- the generated names match the tables.

## 6. Teams in Python (part 3)

`duoforge.teams` reads the registry. `data/teams/<id>.txt` is a Showdown paste with every gender stated, and `data/teams/index.json` holds the metadata (A7).

**Parsing.** The parser is strict and parses text only; legality stays in the library.
- Members are separated by blank lines; there are 1 to 6 blocks, and the library checks the count against the kind.
- The first line is `Species (M|F) @ Item`. The item and the gender tag are optional. A missing gender tag becomes `DUOFORGE_GENDER_NONE`, and the library refuses that for a gendered species. A nickname form `Name (Species)` is an error.
- The other lines:
  - `Ability: X`;
  - `Level: 50`, which may be absent; any other level is an error;
  - `EVs: n Stat / ...`, read as Stat Points;
  - `<Nature> Nature`;
  - `- Move`, 1 to 4 of them.
- Any other line is an error that names the file, the line and the reason. The registry carries no cosmetic lines; `import_paste.py` drops them.

**Mapping.** Each name is reduced to its Showdown id and looked up with `duoforge_data_find`. The item becomes id + 1, or 0 when there is none; the ability becomes id + 1. The result is a `SIDE_SETUP` record. An unknown name raises `TeamError(team, member, table, name)`.

**Validation.**
- `teams.load(context, ids, root="data/teams")` reads the teams from the registry (or another root). It checks every team in the given context: it creates a mirror battle with the team on both sides. A refusal raises `TeamError(team, status)`.
- It returns a `TeamPool`: ids, the sha256 of each file, weights (default 1) and side setups.
- `TeamPool.from_setups(ids, sides)` serves the tests and the stage before part 3 (Teams A and B from `reference_setups`).

**Tests:**
- every parse error class;
- Team A and Team B from their files equal `duoforge_reference_setup`;
- Team C is accepted under TEAM_C and refused under CLOSURE;
- an unknown name is refused;
- a missing gender is refused for a gendered species.

## 7. Feature names (part 4)

- `features.FEATURE_NAMES` is a tuple with one name per observation column, for example `global.terrain.PSYCHIC`, `own.pos0.flag.follow_me` and `foe.member3.species`.
- `features.SLOT_FEATURE_NAMES` does the same for the 12 option columns.
- Both are built from the same constants as `OBS_SIZE` and `SLOT_FEATURES`, so there is no second source of truth.
- **Tests:**
  - `len(FEATURE_NAMES) == OBS_SIZE`, and the names are unique.
  - Samples at known indices: the terrain one-hot at 10 to 12, and own slot 0's position flags at 37 to 39 (as `test_encode_position_flags`).
  - Encoding a crafted observation puts each value under its name.

Model v2 finds its columns by name, and widening maps by name.

## 8. Model v2 (part 5)

### 8.1 Inputs and ids

The inputs stay those of v1: the observation part (607 floats), the slot part (2 × 32 × 12) and the pair mask.

Model v2 recovers ids from the observation through `FEATURE_NAMES`:
- species and move ids: `round(x · 65535)`;
- item and ability: `round(x · 255)`, where 0 means none;
- the move count: `round(x · 4)`. Move slots below it are valid.
- A member counts as registered when its move count is above 0. This does not depend on the `present` column.
- The occupant of a position: the index of the hot entry of its occupant one-hot.
- An option's move slot: `round(x · 4)`, where 4 is Struggle.
- An option's reserve: `round(x · 5)`, a roster index.

### 8.2 Embeddings

| Table | Capacity | Notes |
|---|---|---|
| species | 1024 | base formes; Mega Evolution is the `is mega` flag, because the view keeps the base forme id |
| moves | 1024 | plus one learned Struggle vector |
| items | 256 | row 0 = none |
| abilities | 256 | row 0 = none |
| natures | 25 | |

- The capacities are part of the model configuration. They cover the legal Reg M-C pool (375 formes, 510 moves, 166 items, 215 abilities) without widening.
- Before a forward pass, the host checks every recovered id. An id at or past its capacity raises a ValueError naming the table, the id and the capacity. It is never clipped.

### 8.3 Order-invariant encoding

Roster order follows the team file, and move order follows the paste. Neither carries meaning, so the network is built to be equivariant to both (HauptSession review).

- **Move token**, one per valid move of a member: the move embedding plus the PP fraction, through a dense layer. A member's moves are pooled with sum and max.
- **Member vector** `h_m`, the same weights for own and foe members:
  - the species embedding, the pooled move tokens, the item, ability and nature embeddings;
  - the member's scalars: HP fraction, location, status, the Mega flags, item used, gender, Stat Points, stats, own or foe.
  - These go through two dense layers.
- **Position vector**, one for each of the 4 active positions: the position's scalars (stages, flags, position flags, occupied) plus the occupant's `h_m`, through a dense layer. The occupant one-hot itself is not an input.
- **Torso**:
  - Inputs: the global scalars, both sides' scalars, the 4 position vectors, and per side the sum and max of the registered members' `h_m`.
  - These go through L dense layers of width H, with LayerNorm. From the second layer on they are residual.
- **Options**, per slot list s and entry i:
  - the option's kind, target and Mega columns;
  - for a move, the move token of the actor's move at that move slot (the actor is the occupant of own position s), or the Struggle vector;
  - for a switch, the reserve's `h_m`;
  - a projection of the torso.
  - Two dense layers give one logit per slot list. As in v1, a pair's logit is the sum of its two options' logits, and pairs outside the engine's mask get no probability.
  - The move slot and the reserve index are used to gather, never as features.
- **Team selection**: the same 360 ordered tuples of 4 of 6 as v1, so the action space is unchanged.
  - Each member gets three scores from its `h_m` and the torso: lead 0, lead 1 and back.
  - Each ordered lead pair gets one pair score.
  - A tuple's logit is lead0(a) + lead1(b) + pair(a, b) + back(c) + back(d).
- **Value**: a dense layer from the torso.

**Equivariance test.**
- Permuting the own roster (member blocks, occupant indices, reserve indices, team tuples) permutes the action distribution accordingly. The same holds for permuting a member's moves (move columns, PP, option move slots).
- The value stays the same, within float tolerance.

### 8.4 Sizes

Every dimension is configurable. There are three presets:

| Preset | embedding | member | position | torso H × L | option | target parameters |
|---|---|---|---|---|---|---|
| S | 32 | 64 | 64 | 256 × 2 | 64 | about 0.35 M (v1: 345,707) |
| M | 64 | 128 | 128 | 640 × 3 | 128 | about 2 M |
| L | 64 | 256 | 256 | 1024 × 5 | 256 | about 8 M |

The exact parameter count of each preset is pinned by a test. The checkpoint stores the full configuration.

### 8.5 v1 stays

Model v1 stays loadable, trainable and playable. The ladder plays v1 and v2 checkpoints against each other.

## 9. Checkpoint v2 and widening (part 5)

### 9.1 Format

`params-<update>.npz` holds the parameter arrays (the flattened tree paths, as today) and a `config` JSON with:
- `format: 2` and the model configuration (version and dimensions);
- the key `"encoder"` (9.4), `FEATURE_NAMES` and `SLOT_FEATURE_NAMES`;
- the data kind and the context fingerprint, in hex, and under `"ids"` the names of every id of the embedded tables (`checkpoint.ids_of`; added 2026-10-03).
- the team pool: ids, sha256 and weights;
- the update and the decision count;
- the training configuration.

`checkpoint.load` reads format 1 (today's files) and format 2.

### 9.2 Widening the observation

- A checkpoint is loaded against the current layout.
- Its column names must be a subset of the current ones. A missing or renamed column is refused, naming the column.
- New columns get zero rows in the first layer that reads them: `t1.w` for v1, and the respective input layer for v2. Old columns keep their weights at their new positions. Slot features follow the same rule.
- **Test:** the widened network gives exactly the old outputs on inputs whose new columns are zero.
- The 594 → 607 widening of the Showdown adapter (`widen_594`) stays as it is. It covers the format-1 files that have no names.

### 9.3 Other growth

- Ids keep their rows.
- Raising a capacity appends freshly initialized rows.
- On resume, the Adam moments of new rows and columns are 0, and the step count stays.

### 9.4 v1 legacy path for the encoder fix (agreed with the HauptSession and the Showdown adapter)

- **The switch.** The fix PR gives the encoder a switch: `features.encode` and `encode_batch(..., legacy_present=False)`. With `True`, the old `present = species_id != 0` holds. The switch and its test come with the fix PR.
- **The key.** Checkpoints carry the key `"encoder"`, an integer:
  - 1 before the fix and 2 after it;
  - a missing key counts as 1;
  - new runs write 2.
- **Loaders.** Every loader of a checkpoint sets `legacy_present = config.get("encoder", 1) < 2`: the v1 path, the evaluation, the ladder and the adapter. The night run's checkpoints then stay exact.
- **Mixed games.** In a game between players of different revisions, each seat's observation is encoded with its own player's setting.
- **Runs.** A run keeps the encoder setting it started with, also across a resume.
- **Model v2** does not read the `present` column, but it records the key like every checkpoint.
- Part 5 waits for the fix PR.

## 10. Self-play over N teams (part 6)

### 10.1 Pairings

- The team pool has N teams with weights w (default 1).
- A pairing is an ordered pair (side-0 team, side-1 team); mirrors are included.
- The pairing of environment e in episode k is a pure function of the run seed, e, k and the weights:
  - two splitmix64 draws, tagged per side;
  - each draw picks its team by inverse cumulative weight.
- With equal weights, every one of the N² pairings is equally likely.
- With N' teams after a resume, the same rule covers N'² pairings.
- An environment that ends its episode is reset to its next episode with its new pairing, through part 1.

### 10.2 Seats and rewards

- These are unchanged from decision 0014:
  - +1, −1 or 0 at the end of an episode;
  - GAE over each seat's own decisions;
  - an episode cut off after `--max-steps` scores as a tie.
- `--data-kind` names the context kind: CLOSURE for A and B, TEAM_C for A, B and C, and later the frozen pool profile.

## 11. League (part 6)

- **Groups.** The first round(s · E) of the E environments play self-play, with the learner on both seats (`--self-play-share` s, default 0.5). The others are league environments. In league environment e the learner sits on seat e mod 2.
- **Training rows.** In a league environment the opponent seat is played by a frozen snapshot, sampled from its distribution. Its rows go neither into the policy loss nor into the value loss.
- **Snapshots.**
  - The learner's parameters are saved every `--snapshot-every` updates (default 200) as `params-<update>.npz`; the ladder uses the same files.
  - The pool is every snapshot of the run so far, plus the initial parameters.
- **Slots.** K slots (`--league-slots`, default 4) hold one snapshot each.
  - A league environment picks a slot at the start of each episode: by a splitmix64 draw over the open slots.
  - Every `--slot-refresh` updates (default 50), the next slot in round robin starts draining:
    - It takes no new episodes.
    - Once its last episode has ended, it loads a snapshot drawn uniformly from the pool and opens again.
    - One slot drains at a time.
  - An opponent therefore changes only at an episode boundary.
- **Forward.** One jitted call evaluates the K stacked snapshot parameter sets (vmap over the slots) on the league opponent rows and picks each row's slot. The cost is measured in part 9.
- **Statistics.** Games, wins and ties of the learner against each snapshot go into the log and the run state. They are the basis for weighted opponent sampling (PFSP), which is not built now.

## 12. Entropy schedule, run state, resume (part 7)

### 12.1 Entropy schedule

- `--entropy` takes a number (constant, as today) or a piecewise-linear schedule over decisions, for example `0:0.02,500M:0.01,2G:0.003`.
  - The suffixes K, M and G mean 10³, 10⁶ and 10⁹.
  - The decision points must rise strictly; anything else is an error.
- The value is held after the last point. The coefficient of an update comes from the decisions so far.
- Machine speed and resumes do not change it. It is logged with each update.

### 12.2 Run directory

- `config.json`.
- `log.jsonl`, with one line per update; a resume appends a `resume` line with the changes.
- `params-<update>.npz` snapshots.
- `state.npz` and `state.prev.npz`.

### 12.3 Run state

`state.npz` holds:
- the parameters and the optimizer state;
- the counters: update, decisions, episodes;
- each environment's episode number;
- the league: the snapshot pool, the slots, the draining slot and the statistics;
- the NumPy generator state and the JAX key;
- the team pool: ids, sha256 and weights;
- the data kind, the fingerprint and the names of every embedded id (`"ids"`, `checkpoint.ids_of`);
- the model configuration and the encoder layout.

It is written atomically: to a temporary file, then fsync, then a rename over `state.npz`, after moving the old one to `state.prev.npz`. Writes happen:
- every `--save-minutes` (default 10);
- at the end of the run;
- after SIGTERM, at the next update boundary. The run then exits cleanly.

### 12.4 Resume

`python -m duoforge_learn.train --resume RUN_DIR [options]`.
- **Episodes.** Episodes that were running are dropped. Every environment starts its next episode, so no battle seed repeats.
- **Allowed changes**, each logged:
  - more teams or new weights;
  - another environment or worker count;
  - the duration;
  - the league and schedule options.
- **Refused explicitly:**
  - a team file whose sha256 changed under the same id;
  - a model configuration that differs without a widening rule;
  - an observation layout that drops a column;
  - tables whose names do not keep the old ids (`checkpoint.check_ids`, when the fingerprint differs). A run state without names needs the same fingerprint.
- **Tests:**
  - the state round-trips;
  - the counters continue;
  - no (environment, episode) pair repeats;
  - a changed team file is refused;
  - a SIGTERM leaves a loadable state;
  - a resume with one more team samples it.

## 13. Evaluation and ladder per team (part 8)

**Suite.** A fixed list of games: pairing, learner seat and seed.
- With N ≤ 8: every pairing, both seats, `--eval-games` games each (default 2).
- With more teams: a sample stratified by team, with a budget of `--eval-budget` games (default 512). Each team is the learner's team equally often, and its opponents are spread evenly.
- The suite is deterministic for a team pool and a seed.

**During the run.** Every `--eval-every` updates the greedy learner plays the suite against the random baseline and against the previous evaluation's parameters. The log records the overall score and the score per learner team.
- Scripted joins only once the ScriptedPolicy scoring is repaired; that owner decision is pending.
- Unfinished episodes count as ties and are reported, as today.

**Ladder.** `python -m duoforge_learn.ladder RUN_DIR [RUN_DIR ...]`.
- Players are checkpoints from one or more runs, v1 and v2 mixed, each played by its own model.
- It plays a round robin over the suite and keeps every game's record: pairing, seats, result.
- It reports:
  - **Elo overall:** a Bradley-Terry fit, as today.
  - **Elo per team:** a fit over the games in which a player pilots that team.
  - **Confidence intervals** from 200 bootstrap resamples with a fixed seed.
  - **A team-against-team matrix** for the strongest player.
- The output is `ladder.json` plus a Markdown table. It runs as its own process, also beside a training run.

## 14. Throughput (part 9)

**Phase timings.** Each update logs:
- the collection split into engine, encoder, policy and the rest;
- the update split into transfer and compute.

This costs one device synchronization per update.

**Transfer fix.**
- The rollout's samples go to the device once per update, padded to a multiple of the minibatch.
- The minibatches are gathered on the device from a permutation per epoch.

Both are measured on a quiet machine (owner rule): the night configuration, before and after the fix, interleaved runs of 300 updates, three repetitions each. Reported are medians, ranges and the raw output.

## 15. Measurements on A, B and C (part 9)

- Four training runs on A, B and C (TEAM_C, 9 pairings), with the same pipeline: league and entropy schedule.
  - 200 million decisions each: v1, v2-S, v2-M and v2-L.
  - Local at night with 8 workers, each run announced to the HauptSession.
  - One run is stopped with SIGTERM and resumed.
- A cross ladder over checkpoints of all four runs plus the untrained network, on the A/B/C suite: Elo overall and per team.
- Throughput per model size: decisions per second and the phase split.
- Report: `docs/learning/<date>-learner-v2-abc/` with the README, the configurations, `ladder.json` and an excerpt of the evaluation log.
- Runbook `docs/learning/RUNBOOK.md` for a rented Linux machine:
  - building Release with LTO and a venv with `jax[cuda12]`;
  - a smoke test;
  - starting under tmux on the persistent volume;
  - syncing the run directory;
  - resuming after an interruption.

## 16. Errors

Every refusal is explicit and names its cause. Nothing is clipped, skipped or replaced by a default.

- **Teams:**
  - a parse error names the file, the line and the reason;
  - an unknown name names the table, the name and the kind;
  - a library refusal names the team and the status;
  - a changed file on resume is refused.
- **Model:** an id beyond capacity; a dropped column; a configuration mismatch.
- **Run:** a resume without a state; another data kind; tables whose names do not keep the old ids, or a state without names under another fingerprint (`checkpoint.check_ids`).
- **Batch:** a failing environment is reported with its index and status.

## 17. Not in this work

- Asynchronous actors.
- PFSP opponent weights.
- The random-team sampler (this track, after stage 1, over the lead's query API).
- A learning-rate schedule (the schedule syntax would allow it).
- Pairing curricula.
- An encoder on the GPU.
- Changes to the observation.

## 18. Coordination

- **HauptSession:** merges every PR, assigns versions at merge, and gets every long run announced beforehand.
- **Expansion lead:** the registry (A7), the data query API (part 2), the frozen pool profile and the order of curve teams. This track asked for variety when two teams cost about the same.
- **Showdown live adapter:** keeps `widen_594` and switches to the data query API later.
- **Encoder fix (the HauptSession or the fix session):** the `present` fix, the `legacy_present` switch and the checkpoint key `"encoder"` (9.4).
