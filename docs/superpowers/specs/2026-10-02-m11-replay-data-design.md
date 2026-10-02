# M11 replay data: design

Date: 2026-10-02. Status: design approved by the owner in chat; this spec is for his review.

Roadmap: M11 in `docs/ROADMAP.md` (PR #110). Builds on:
- decisions 0007 (the player view), 0013 (the Python adapter), 0015 (POOL), 0016 (the live adapter and its tracker), 0017 (Learner v2, reserved) and 0018 (the POOL view extension);
- the replay spike of 2026-10-02.

## 1. Goal

Public Showdown replays of Reg M-C with open team sheets become training rows for Learner v2. Each row is one player at one decision:
- DuoForge's observation of that player;
- the options;
- the set of options that the log shows the player chose.

Behavior cloning on these rows gives the policy and the value a human prior. PPO self-play with a KL term toward it follows.

This spec covers the data side. It is built today, before the name rows and Learner v2 are on main:
- the spectator mode of the live tracker;
- decision points and labels;
- superset options;
- the stat point prior and the stats;
- the dataset writer with its counters;
- tests on our own reference battles.

**Success**
- On every committed reference battle (182 today, closure, Team C and pool), for both sides:
  - the spectator's decision points are DuoForge's;
  - its observation is DuoForge's, except the fields of section 6, which equal their documented source;
  - its options contain DuoForge's;
  - the true choice is always inside the label set.
- On the replay corpus, every game, perspective and decision is either written or counted under a named reason. Nothing is approximated silently.

Spike numbers for scale: Reg M-C has 74,081 games, of which 34,405 have open sheets. With every name in the tables, about 376,000 decisions were readable and representable.

## 2. Decisions

**Owner (2026-10-02)**
- **Approach:** the live tracker in a spectator mode, following the spike's recommendation:
  1. behavior cloning on open-sheet games, weighted by outcome or Elo;
  2. then PPO with a KL term toward the BC policy;
  3. offline RL later.
- **A perspective stops at the first line the view cannot represent**, until the view extension folds that line.
  - The decisions after the stop are dropped and counted by reason.
  - The rejected alternative skipped only the decisions while an effect is active. It would need effect lifetimes in Python.
- **The own side:**
  - HP is the public percentage;
  - stat points come from a per-set prior (VGCPastes);
  - stats are computed by Showdown, never by Python;
  - picks come from hindsight.
- **Data:** the replays, anything derived from them, and checkpoints trained on them never go into the repository. The dataset states no license.
- **PRs:** one PR for this pipeline, with a review agent. The BC trainer is a second PR, after Learner v2.

**Agreed with Learner v2 (2026-10-02)**
- Rows hold raw `OBSERVATION` and `FACTORED_DOMAIN` records. Labels are option sets (section 9).
- The BC PR does the following:
  - It calls `duoforge_learn.policy.make(config["model"], config["features"], config["slot_features"]).apply(params, obs, slots, mask)`.
  - It intersects the label set with the mask it passes to the model.
  - It adds `--init CKPT` to `train.py`.
  - It loads checkpoints through `checkpoint.load` and `checkpoint.widen`.
- `python/duoforge/data.py`, the Python binding of the data query API, comes with Learner v2's PR. This PR does not touch `_lib.py`, `_layout.py` or `layout_dump.c`.
- Merge order: Learner v2 first.

**Agreed with the HauptSession, after decision 0018**
- The tracker fills the view extension later, field by field.
  - It fills a field exactly when the library's `supported` mask has its bit.
  - It reads the field from the protocol signals of 0018 section 6.
  - Until the bit is set, a line of that feature stops the perspective (section 5).
- Quiet machine windows are respected, and long runs are announced.

## 3. Inputs

**Replays**
- Location: `C:\Dev\datasets\pokemon-showdown-replays\*.parquet`, from HolidayOugi.
- Columns: `id`, `format`, `players`, `log`, `uploadtime`, `views`, `formatid`, `rating`.
- A game is kept when its `formatid` starts with `gen9championsvgc2026regmc` (Bo1 and Bo3) and its log has exactly two `|showteam|` lines.
- The `log` is the room's spectator channel, in this order:
  - room lines (`|j|`, `|c|`, `|t:|`, `|inactive|`, `|html|`, `|uhtml|`, …);
  - `|player|p1|NAME|AVATAR|RATING`, `|gametype|`, `|gen|`, `|tier|`, `|rule|`, `|poke|`;
  - `|teampreview|`, the two `|showteam|` lines, `|teamsize|`;
  - `|start|` and the battle.

**Elo** comes from the rating field of the `|player|` lines, not from the dataset's `rating` column (spike). A missing rating is -1.

**Fixtures**, for tests only:
- They are the committed reference battles.
- `tools/reference/ps_client.js` replays each one in the pinned Showdown from its spec and trace. It emits the spectator channel (`extractChannelMessages`, channel 0), which is exactly what a replay log holds.
- No replay of the dataset is ever a test input, and none is committed.

**Prior source:** the VGCPastes pastes with Stat Points, outside the repo, in `C:\Dev\src\duoforge-data\vgcpastes-mc-2026-10-02\pastes\` (227 teams).

## 4. Architecture

New package `python/duoforge_replay/`: Python and NumPy. pyarrow is needed only to read parquet and is imported lazily.

| Module | Responsibility |
|---|---|
| `source.py` | Games from parquet files, in file and row order; the format and sheet filters. |
| `game.py` | One game: the pre-pass (sheets, players, Elo, winner, picks, Illusion), the decision points, both perspectives, the rows or the counted reasons. |
| `points.py` | The decision points of both sides, from the line structure (section 7). |
| `spectator.py` | `SpectatorTracker`: the live `Tracker` for a given side, with the own side folded like the foe (section 6). |
| `superset.py` | The superset slot lists, through `duoforge_live.options.slot_options` on a synthetic request (section 8). |
| `labels.py` | The label sets (section 9). |
| `prior.py` | The stat point prior: built from pastes, then looked up (section 10). |
| `stats.py` | Stats from the pinned Showdown through `tools/reference/ps_stats.js`: one persistent Node process per worker, with a cache. |
| `dataset.py` | Shards, the games table, the manifest and the counters, plus a reader for the trainer (section 11). |
| `__main__.py` | `python -m duoforge_replay prior …` and `build …` (section 12). |

**Changes to existing code**
- `python/duoforge_live/lines.py` (new) and `tracker.py`:
  - the line classes of section 5, shared by live and spectator play;
  - the fold of the fields that the TEAM_C and POOL kinds show: the choice lock, Follow Me, Helping Hand and Unburden;
  - view changes of supported mechanics whose line is `[silent]`;
  - hooks for the spectator subclass.

  The live adapter then refuses, and forfeits, on the newly classified lines, where today it folds them wrongly.
- `python/duoforge_live/data.py`: the POOL tables (forme rows, PP, target class) besides the closure ones.
- `tools/reference/ps_client.js`: `--spectator` (channel 0) and `--every` (closure, Team C and pool battles). `--all` stays the closure.
- `tools/reference/ps_stats.js` (new): the stats of (species, nature, stat points), from the format's `Battle.spreadModify`.
- `tests/CMakeLists.txt`: two Python tests (section 14).

**Data flow per game**
1. Filter the game.
2. Run the pre-pass.
3. Find the decision points.
4. For each side, fold the lines up to each own point and take the observation and the superset domain there.
5. Read the labels from the lines after each point.
6. Write the rows, or count the stop.

## 5. Line classes

Every protocol line passes one classification before the converter (`trace_to_c.step_events`) sees it.

| Class | Meaning | Action |
|---|---|---|
| room | a line of the room, not of the battle: `\|j\|`, `\|c\|`, `\|t:\|`, `\|inactive\|`, `\|raw\|`, `\|html\|`, `\|uhtml\|`, `\|-message\|`, `\|-hint\|`, empty | ignored |
| fold | a battle line whose effect on the view the tracker applies. Either its form occurs in the reference battles, where the equivalence test checks it, or it is generic, so the whole effect is in the line: `-damage`, `-heal`, `-boost`, `-unboost`, `-status`, `-curestatus`, `faint`, `-miss`, `-crit`, … | folded |
| feature | an effect of decision 0018 section 6.1, with its `DUOFORGE_VIEWEXT_FEATURE_*` bit | folded only when the library's `supported` mask has the bit, which none has today; otherwise stop `feature:<NAME>` |
| unknown | anything else: an unknown kind (`-sethp`, `-clearallboost`, `swap`, `drag`, `-transform`, …), or a known kind with an effect, attribute or cause that no entry of the table names | stop `line:<kind> <effect>` |

**The table** names each (kind, effect) pair for the kinds whose meaning depends on the effect:
- `-activate`, `-start`, `-end`, `-singleturn`, `-singlemove`;
- `-sidestart`, `-sideend`, `-fieldstart`, `-fieldend`, `-weather`;
- `-item`, `-enditem`, `-ability`, `detailschange`, `-formechange`, `replace`, `-mustrecharge`;
- the attributes of `move` and the `[from]` causes.

Examples:
- `-ability|POKEMON|ABILITY`:
  - with no `[from]`, and ABILITY the holder's current ability: fold (an announcement);
  - with `[from] ability: Trace` or `[from] move: X`: feature `ABILITY_CHANGE`;
  - any other form: unknown.
- `-enditem|POKEMON|ITEM`:
  - with no `[from]` (or with `[eat]` or `[weaken]`), and ITEM the holder's sheet item: fold, which sets `item_used`;
  - with `[from] move: Knock Off` (or Thief, Covet, Incinerate, Bug Bite, …) or with `[from] stealeat`: feature `ITEM_CHANGE`.
- `detailschange`:
  - to the member's Mega forme, followed by `-mega`: fold;
  - any other: feature `FORME_CHANGE`.
- `-weather|Sandstorm` gives feature `WEATHER_SAND`, `-sidestart|…|move: Aurora Veil` gives `AURORA_VEIL`, and `-start|POKEMON|perish3` gives `PERISH`.
- `-activate` is folded only for the effects that the reference battles show and the tracker handles, for example `move: Protect`, `confusion` and `ability: Emergency Exit`. Every other effect is unknown. The counters show which ones the replays need.
- `move` of Baton Pass is unknown: it passes stages and volatiles on without a line.

**The choice lock** comes from Showdown's choice items at the pin (Choice Band, Choice Scarf, Choice Specs). A reference test checks this list against `isChoice`.
- The lock starts at the holder's `|move|` line. That line appears exactly when Showdown sets the lock: a move stopped before it runs prints no line, and a move that Protect blocks still prints one.
- The lock ends when the holder leaves.
- Only Choice Scarf has recorded battles (Team C). Band and Specs follow the same lines.

**Turn-scoped features**
- `RAGE_POWDER`, `WIDE_GUARD` and `QUICK_GUARD` are visible only at a PIVOT boundary, and the next `|upkeep|` or `|turn|` clears them (0018 sections 3.3, 3.4.1 and 6.1).
- Such a line stops the perspective only when one of its decision points lies between the line and that clear.
- Otherwise it changes no observation. It is counted as `turn-scoped:<NAME>`.

**Whole-game skips:** a sheet with an Illusion holder skips the game (`skip:illusion`). The disguise binds a protocol name to the wrong member before any line could tell.

**A stop ends the perspective.** Its points from the stop line on are dropped and counted under the reason. The points before it are kept, with labels read from their own lines (section 9).

## 6. The spectator view

The spectator's observation for side s at a point is DuoForge's observation for player s, with these changes:
- The own side is shown the way the public sees it.
- What the spectator knows about the own side in hindsight is added.

| Field | Spectator value | DuoForge's player view | The test compares with |
|---|---|---|---|
| the global fields, both sides' positions, the foe's members, the side fields not listed below | the live tracker's fold | the same | DuoForge, exactly |
| own `hp`, `hp_max`, `hp_kind`, `hp_flag` | the public display: percent, `HP_PERCENT`, last seen; a member that never entered shows 100/100 | exact | the foe player's view of the same member; for a member that never entered, DuoForge's `hp == hp_max` |
| own `pp`, `pp_kind` | the maximum PP minus the uses seen, `PP_DERIVED` | exact, `PP_EXACT` | the foe player's view of the same member |
| own `status`, `item_used`, `is_mega`, `ability` | the fold, as for the foe | the same | DuoForge, exactly |
| own `stat_points` | the prior (section 10) | the set's | DuoForge, with the true team as the prior |
| own `stats` | Showdown's stats of the prior spread, for the current forme (the Mega forme after Mega Evolution) | exact | DuoForge, with the true team as the prior |
| own `location` | ACTIVE, BENCH or NOT_BROUGHT, from the hindsight picks; UNDETERMINED at team selection | the same | DuoForge, exactly |
| own `brought_order` | the leads in slot order, then the back members in ascending roster order | the chosen order | the leads exactly, the back members as a set |
| own positions' `locked_target` | the target on the release turn's `\|move\|` line (`[from] lockedmove`), since the charge turn's line shows none; when the move was drawn (Lightning Rod, Storm Drain, Follow Me, Rage Powder, Spotlight), retargeted (a faint or an empty position on the target's side) or never released, the perspective stops (`charge-target-hidden`) at its next own point | the stored target | DuoForge, exactly |
| `requested`, `requested_slots` (both sides), `slot_mask` | as in section 7 | the same | DuoForge, exactly |
| `epoch` | the number of decision points so far, both sides together | the same | DuoForge, exactly |

**Converter and encoder**
- The converter is called with viewer 2, which is no side, so both sides' HP lines read as percent.
- The encoder does not read `hp_kind`, `pp_kind`, `hp_flag` or `brought_order`.
- Its own-HP input becomes percent / 100 instead of hp / hp_max, at most one percent off.

**Incomplete picks**
- A won or forfeited game can leave fewer than four own members seen. The view then cannot show which unseen member was brought.
- The perspective keeps its team selection row, whose label is a set, and drops the rest: `stop:picks-incomplete`.

## 7. Decision points

The decision points of both sides come in log order, from the line structure. The fold state at a point gives the requested slots.

| Point | Where | Requested |
|---|---|---|
| TEAM_SELECTION | after both `\|showteam\|` lines, which must come before `\|start\|` (otherwise `skip:sheets-late`) | both sides |
| TURN | after each `\|turn\|N` | both sides, at the occupied positions |
| REPLACEMENT | before the first non-action `\|switch\|` after the turn's `\|upkeep\|` | the switch flag rule, with every position that switches in the point's run flagged first |
| PIVOT | before a non-action `\|switch\|` in the turn, before its `\|upkeep\|` | as for REPLACEMENT |

**Switches**
- A `|switch|` is a TURN action when no `|move|`, `|cant|`, `|-mega|` or confusion `|-activate|` line of the current turn comes before it. At the pin, Showdown runs switch actions (order 103) before Mega Evolution (104) and before moves (200).
- Any other `|switch|` belongs to a switch point.
- A switch point covers the run of `|switch|` lines that follows it. A position that switches a second time starts a new point.

**The switch flag rule**
- It is the rule the live tracker uses for the foe (`_foe_switch_slots`): DuoForge's own rule, which asks the flagged positions while their side has a reserve.
- Flagging the switching positions first covers pivot causes that the fold does not know, such as Volt Switch or Eject Button.
- The rule still decides the reserve condition and the positions that pass, for example a second fainted position without a reserve.
- If a switching position is still not asked (no reserve by the tracker's count), the perspective stops: `structure:<detail>`.

`|drag|` and `|replace|` are unknown or feature lines (section 5).

**Epoch and boundary**
- The epoch counts every point.
- A switch point's boundary is REPLACEMENT when an `|upkeep|` lies between it and the previous point, and PIVOT otherwise, as in `trace_to_c.boundary_of`.

The tests check the points, epochs, boundaries and requested slots against DuoForge on every reference battle.

## 8. Superset options

At an own point, `options.slot_options` runs on a synthetic request of the own side:
- every sheet move whose derived PP is above 0, with the target type of the move's target class in the tables;
- `canMegaEvo` when the member holds its stone and the side has not used Mega Evolution;
- not trapped;
- as reserves, the alive brought members on the bench, from the hindsight picks;
- a charging position offers only its locked move, with the locked target;
- a choice-locked position offers only its locked move;
- with every PP at 0, the only move is Struggle;
- at REPLACEMENT and PIVOT, `forceSwitch` comes from the requested slots.

**Pair mask and team selection.** The pair mask is the provisional full mask, every pair of valid options, as in live play. Team selection uses `options.team_domain` with 360 tuples.

**What the superset can hold beyond the request**
- It contains every option of the real request; the tests check this.
- It can also contain more:
  - moves that an effect outside the view disables: Fake Out after the first turn, Taunt, Imprison, Assault Vest, …;
  - switches of a trapped position.
- Exact sets would need an engine entry point "state from observation". That is a C API and needs the owner's OK; it is not part of this work.

## 9. Labels

A label is the set of options that agree with the log:
- per slot list, a 32-bit mask over its options: `label_slots`, where bit i is option i;
- at team selection, a 360-bit mask over `TEAM_TABLE`: `label_team`, 45 bytes.

A reason code per slot says why the set has its size.

| Reason | Set | When |
|---|---|---|
| EXACT | one option | a switch at the start of the turn; a move whose user and target are shown and could not be redirected or retargeted; a switch at a replacement or pivot; a pass at a requested slot that did not switch |
| TARGET_UNKNOWN | the move (slot and Mega choice) with every target | redirection was possible: a Follow Me, Rage Powder or Spotlight line of the other side earlier in the turn, or an `-activate` of Lightning Rod or Storm Drain right before the move. Retargeting was possible: a position of the target side fainted earlier in the turn, or was empty. Also `[notarget]`, and a `cant` line that names the move |
| MOVE_HIDDEN | every move option with the shown Mega choice | the slot did not switch and its move never showed: it fainted or left first, or a `cant` line names no move (paralysis, sleep, freeze, flinch, confusion) |
| FORCED | every option, so no information | `[from]lockedmove`, recharge, a lone pass |
| UNKNOWN | every option, so no information | anything else; counted with its cause |

**Team selection**
- The leads are the own switches at `|start|`, in slot order.
- The back pair is any pair of the remaining members that contains every back member seen later, in both orders.

**Where labels come from**
- A label comes from the lines between its point and the end of the point's turn. A TURN label spans the PIVOT points inside its turn.
- It is read in hindsight. That is allowed, because the label is the player's own choice.
- **A stop cuts the label too.** Labels read only the lines before the perspective's stop line. A slot whose action line comes after the stop gets UNKNOWN. The stop line may change what later lines mean, as Ally Switch's `|swap|` moves a slot's occupant.
- The team selection label and the picks are the exception: they use every switch line of the game. A switch line names the member that came in, and games with Illusion are skipped.

**Tests and loss**
- The tests check soundness on every decision of the reference battles: the true choice is in the set.
- The BC loss is −log P(label set): the log of the summed probability of the set's options under the model, with the set intersected with the model's mask.

## 10. Stat point prior and stats

`prior.py` reads Showdown pastes, with Stat Points written as EVs. For each key it keeps the most frequent spread; a tie goes to the smallest spread tuple. The levels:

| Level | Key |
|---|---|
| 0 | species, item, ability, nature and the move set |
| 1 | species, nature and item |
| 2 | species and nature |
| 3 | species |
| 4 | no paste matches: every stat point is 0 |

- An own member takes the first level that matches its open sheet.
- The row stores the level of each own member in `prior_level`.
- The prior file is JSON and lives outside the repo. Its SHA-256 goes into the manifest.

**Stats.** `tools/reference/ps_stats.js` returns the stats of the pinned Showdown for the format (`Battle.spreadModify`, level 50). Its input is (species, nature, stat points); it answers for the base forme and its Mega forme. Python never computes a stat.

## 11. Dataset

The writer refuses an output directory inside the repository.

**`rows-00000.npz`, …** 65,536 rows per shard. Each row holds:
- `observation`: an `_layout.OBSERVATION` record;
- `domain`: an `_layout.FACTORED_DOMAIN` record;
- `game` (u32): the index into the games table;
- `side` (u8) and `point` (u16);
- `label_slots` (2 × u32), `label_team` (45 × u8), `label_reason` (2 × u8);
- `prior_level` (6 × u8).

**`games.npz`**, per game:
- the replay id and the format id;
- the Bo3 game number (0 when unknown);
- the two ratings (-1 when unknown);
- the winner side (-1 for a tie or no winner);
- the turn count;
- two hashed player names: the first 8 bytes of the SHA-256 of the name's to_id. Names are never stored.
- two sheet hashes.

**`manifest.json`**
- format version 1;
- the code's git commit and dirty flag;
- the library version;
- data kind POOL and the context fingerprint;
- the names of every id in the converter's tables (species, move, item, ability, nature);
- the source files, with size and SHA-256;
- the filters;
- the prior file's SHA-256;
- the Showdown pin;
- the shards, with row counts and SHA-256;
- the counters.

**`counters.json`**
- games: read, skipped by reason, processed;
- perspectives: kept, stopped by reason;
- points: written, dropped by reason;
- label reasons.

**Determinism**
- Games are written in source order and rows in (game, side, point) order.
- The `.npz` files are written with fixed zip timestamps.
- The same input and the same code give byte-identical files. A test checks this.

## 12. Commands

```
python -m duoforge_replay prior --pastes DIR --out PRIOR.json
python -m duoforge_replay build --source DIR --prior PRIOR.json --out DIR [--workers N] [--limit-games N]
```

**What `build` needs:** NumPy, pyarrow, the library, Node and the pinned checkout (`--ps-dir`, default `$DUOFORGE_PS_REFERENCE_DIR`).

**How it runs**
- Workers process chunks of games, and the writer merges the results in order.
- Between chunks it waits while the fuzz pause file (`$DUOFORGE_FUZZ_PAUSE`) exists.
- A full run starts only after the name rows are on main. It is announced to the HauptSession and stays out of the quiet windows.
- Short development runs (`--limit-games`) may run before that. They too stay out of the quiet windows.

## 13. Errors

Every refusal is explicit and counted under a named reason. Nothing is clipped or replaced by a default, except the documented prior level 4.
- **Game skips:**
  - the wrong format;
  - not exactly two sheets, or sheets after `|start|`;
  - a name the tables do not have (`name:<table> <name>`);
  - a sheet the converter refuses;
  - Illusion;
  - a session line.
- **Perspective stops:**
  - `feature:` and `line:` from section 5;
  - `structure:`;
  - `converter:<rule>`, which is a `ConversionError`;
  - `picks-incomplete`.
- **Any other exception** is `internal:<type>`, kept with up to ten replay ids. The run finishes, prints them and exits with status 1.

## 14. Tests

**`duoforge.python.replay`** (labels `python;reference`) needs Node, the pin and the runner, like `duoforge.python.live`. It runs over every committed reference battle and both sides:
1. The points, epochs, boundaries and requested slots equal DuoForge's. DuoForge's side comes from `duoforge_diff_runner --dump-views` on the closure, Team C and pool records.
2. The observation equals DuoForge's, with the fields of section 6 compared to their documented sources.
3. The superset contains DuoForge's options.
4. The true choice is in the label set. The true choice is the trace's input, passed through `trace_to_c.convert_choice`. The share of EXACT slots is printed.
5. Every line of the reference spectator logs is room or fold, so nothing stops.
6. `ps_stats.js` gives DuoForge's own stats for every reference team member, base forme and Mega forme.
7. The choice items equal the pinned Showdown's `isChoice` items.
8. The committed spectator fixture of the unit tests equals the output of `ps_client.js`.

**`duoforge.python.replay_unit`** (label `python`) needs no Node. It runs on a committed spectator log of one reference battle, with lines injected:
- each stop reason: Sandstorm, Trace, Knock Off, an Illusion sheet, `-sethp`, Baton Pass, and a turn-scoped Rage Powder with and without a PIVOT inside its turn;
- the rows before a stop are kept, and the rows after it are dropped;
- each label reason;
- the prior's levels and its tie rule, on pastes of our reference teams;
- `|player|` ratings, the winner, the Bo3 game number;
- the writer: a round trip, a byte-identical repeat, the refusal inside the repo, counters that add up.

## 15. Later (not in this PR)

- **The BC trainer**, a second PR after Learner v2:
  - rows go through `features.encode_batch` and `policy.make(…).apply`;
  - the loss is −log P(label set), and the value is trained on the outcome;
  - row weights come from Elo or the outcome;
  - games are held out for evaluation;
  - `--init CKPT` is added to `train.py`.
- **The view extension**, per feature, as the expansion sets its bits (0018 section 13).
- **PPO with a KL term** toward the BC policy (`--kl-ref`, `--kl-coef`).
- **Closed-sheet games** with a set prediction, as an experiment.
- **Exact option sets** through an engine entry point "state from observation". It needs the owner's OK.
