# M11 Replay Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn open-sheet Reg M-C Showdown replays into per-player decision rows (DuoForge observation, superset options, option-set labels), proven on our own reference battles, written as shards outside the repository.

**Architecture:** A new package `python/duoforge_replay/` builds on the live adapter (`python/duoforge_live`). It adds:
- a spectator subclass of its `Tracker`;
- decision points from the log;
- labels;
- a stat point prior with stats from the pinned Showdown;
- a deterministic writer.

The shared fold gets a line classification (room, fold, feature, unknown) and the TEAM_C and POOL view fields. Every check of a fold against DuoForge goes through the reference harness: Showdown's spectator channel of all committed battles and the runner's `--dump-views`.

**Tech Stack:** Python 3.12, NumPy 2.5; pyarrow 25 (only `source.py`, imported lazily); Node and the pinned Showdown (`ps_client.js`, `ps_stats.js`); CTest.

**Spec:** `docs/superpowers/specs/2026-10-02-m11-replay-data-design.md`. Read it first; section numbers below refer to it.

## Global Constraints

- No battle rule is computed in Python that the reference test does not check. **Stats come only from `ps_stats.js`.**
- No replay, derived data, prior file or checkpoint is committed. The writer refuses any output path inside the repository.
- This PR does not touch `python/duoforge/_lib.py`, `_layout.py` or `tools/layout/layout_dump.c` (agreed with Learner v2). Constants missing from `_layout` are module constants with a comment naming the header, as in `tracker.py`: `DATA_KIND_POOL = 6  # DUOFORGE_DATA_KIND_POOL (include/duoforge/duoforge.h)`.
- Every refusal is explicit:
  - a perspective stop is a `duoforge_live.lines.Stop(reason)`, a `ValueError` subclass, so the live client still forfeits on it;
  - a game skip is `duoforge_replay.game.Skip(reason)`.
  - The reason strings are exactly the spec's: `feature:<NAME>`, `line:<kind> <effect>`, `structure:<detail>`, `converter:<rule>`, `picks-incomplete`, `skip:illusion`, `skip:sheets-late`, `skip:format`, `skip:sheets`, `name:<table> <name>`, `internal:<type>`.
- Quiet windows today (no builds, tests or data runs): 17:00–17:45 and 22:00–22:30. Full data runs need the name rows on main and a note to the HauptSession.
- Before each push, run `tools/ci/local_ci.sh --quick`. The merge gate is the hosted CI (13 checks).
- Commits: `git add` the named files only, never `-A`. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test commands: run from the worktree with the main checkout's venv.
  - `PY=/c/Dev/src/duoforge/.venv/Scripts/python.exe`
  - `PYTHONPATH=python`
  - `DUOFORGE_LIBRARY=<build>/…/duoforge_shared.dll`
  - The reference tests additionally need `DUOFORGE_NODE=node`, `DUOFORGE_PS_REFERENCE_DIR=C:/Dev/src/pokemon-showdown` and `DUOFORGE_DIFF_RUNNER=<build>/…/duoforge_diff_runner.exe`.
  - Build once: `cmake -S . -B build/gcc-debug -G Ninja -DCMAKE_C_COMPILER=<gcc> -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DDUOFORGE_PYTHON=$PY -DDUOFORGE_PS_REFERENCE_DIR=C:/Dev/src/pokemon-showdown` (see the memory note on the toolchain).

## Review Focus

1. **A Bo3 log with a second game's lines or a reconnect (`|init|`, `|sentchoice|`).** Expected: `Skip("skip:session")`, counted, never a crash. Test: `test_session_line_skips_game` (Task 8).
2. **A sheet name with a form suffix or odd spelling (`Indeedee-F`, `Floette-Eternal`, `Rotom-Wash`).** Expected: resolved through `trace_to_c.BASE_SPECIES_NAME` and `key()` like the live adapter; an unknown name gives `name:<table> <name>`. Test: `test_unknown_name_skips_with_reason` (Task 8).
3. **A game with no `|win|` (timer or a log cut off).** Expected: winner -1, rows kept, picks judged as incomplete when fewer than four members were seen. Test: `test_no_win_line` (Task 8).
4. **A rating field that is empty or not a number in `|player|`.** Expected: -1. Test: `test_player_ratings` (Task 8).
5. **Two workers versus one.** Expected: byte-identical shards. Test: `test_workers_same_bytes` (Task 9).

---

### Task 1: Showdown tools: spectator streams for every battle, stats, choice items

**Files:**
- Modify: `tools/reference/ps_client.js`
- Create: `tools/reference/ps_stats.js`
- Modify: `tests/CMakeLists.txt` (next to `duoforge.reference.client_streams`)
- Modify: `tools/reference/README.md` (one paragraph per tool)

**Interfaces:**
- Produces for `ps_client.js`:
  - `--every`: every committed battle (closure, Team C and pool). `--all` stays closure-only, because `test_live.py` depends on it.
  - `--spectator`: per battle, one JSON object `{"battle": NAME, "to": "spectator", "lines": [...]}`. It holds every line of `extractChannelMessages(data, [0])[0]` for each update, in order, without `|t:|` and empty lines. The `showOpenTeamSheets()` update is included.
  - `--spectator` replaces the per-player messages; with `--check` it prints the usual summary.
- Produces for `ps_stats.js`:
  - usage: `node ps_stats.js <pinned checkout> [--serve]`.
  - The input is a JSON list of `{"species": NAME, "nature": NAME, "sp": [6 ints]}`. The output is a JSON list of `[hp, atk, def, spa, spd, spe]`.
  - The stats are `battle.spreadModify(dex.species.get(species).baseStats, {evs: {hp,atk,def,spa,spd,spe}, ivs: 31s, nature, level: 50})` on a `new Battle({formatid: 'gen9championsvgc2026regmc'})`.
  - With `--serve` it reads and answers one JSON list per line until stdin closes.
  - An unknown species or nature exits 2 with a message.
- Produces the option `ps_stats.js <checkout> --choice-items`, which prints the sorted JSON list of the ids of `dex.items.all().filter(i => i.isChoice)`.

- [ ] **Step 1:** Add the CTest `duoforge.reference.spectator_streams`:
  - It runs `ps_client.js <ps> <root> --every --spectator --check` and expects `ps_client: 182 battles match their traces` (the count is the number of committed specs).
  - Run it and see it fail, because the options do not exist yet.
- [ ] **Step 2:** Implement `--every` and `--spectator` in `ps_client.js`. Run `ctest -R spectator_streams` and `-R client_streams`; both pass.
- [ ] **Step 3:** Implement `ps_stats.js`. Check it by hand: `echo '[{"species":"Rillaboom","nature":"Adamant","sp":[32,32,0,0,0,2]}]' | node tools/reference/ps_stats.js C:/Dev/src/pokemon-showdown` prints one list of six numbers.
- [ ] **Step 4:** Commit with the message `Reference tools: spectator streams of every battle, Showdown stats`.

### Task 2: POOL table data for the fold

**Files:**
- Modify: `python/duoforge_live/data.py`
- Test: `python/tests/test_replay_unit.py` (new; `class DataTest`)

**Interfaces:**
- Produces `data.load(root=ROOT, kind="closure")`, where `kind` is `"closure"` or `"pool"`.
  - `"pool"` reads `pool_tables.c`/`.h` through `trace_to_c.load_tables(root, True)` and the pool rows: `dfi_pool_formes[DFI_POOL_FORME_COUNT]` and `dfi_pool_moves[DFI_POOL_MOVE_COUNT]`.
  - Any other kind raises `ValueError`.
- Produces `Data.target_type(move_id) -> str`, the Showdown target type of the move's `target_class` (8th field of the move row):
  - 1 `normal`, 2 `any`, 3 `adjacentAlly`, 4 `adjacentAllyOrSelf`, 5 `adjacentFoe`, 6 `self`, 7 `allAdjacentFoes`, 8 `allySide`, 9 `all`;
  - any other class raises `ValueError(f"move {id}: target class {c} has no Showdown target type")`.
- The existing methods (`team`, `forme`, `pp_max`, `ability_of`, `base_forme`, `mega_forme`, `mega_capable`) work for both kinds.

- [ ] **Step 1:** Write `DataTest`:
  - `load(kind="pool")` has as many forme, move and pp rows as the `DFI_POOL_*_COUNT` defines in `pool_tables.h`.
  - `target_type` of Tailwind is `allySide` and of Protect is `self`.
  - `pp_max` of Protect is 8, its value in the closure tables.
  - Every closure id gives the same `forme`, `pp_max` and `mega_forme` under both kinds, because the pool tables keep the closure prefix.
  - `load(kind="x")` raises.

  Run it and see it FAIL.
- [ ] **Step 2:** Implement it, extending the move-row regex to capture `pp_max` and `target_class`. Run `$PY -m unittest python.tests.test_replay_unit -k Data -v`; it passes. `python.tests.test_live_unit` still passes.
- [ ] **Step 3:** Commit with the message `Live data: the POOL tables and move target types`.

### Task 3: Line classes in the shared fold

**Files:**
- Create: `python/duoforge_live/lines.py`
- Modify: `python/duoforge_live/tracker.py` (`feed` calls `lines.check` before `_fold`)
- Test: `python/tests/test_replay_unit.py` (`class LinesTest`)

**Interfaces:**
- Produces `class Stop(ValueError)` with the attribute `reason: str`.
- Produces `FEATURES: dict[str, int]`, the feature name to `DUOFORGE_VIEWEXT_FEATURE_*` bit, copied from decision 0018 section 7.1.
- Produces `SUPPORTED = 0`, the library's supported mask. It is 0 until step V1 of 0018 exists; then it is read from the library.
- Produces `TURN_SCOPED = {"RAGE_POWDER", "WIDE_GUARD", "QUICK_GUARD"}`.
- Produces `CHOICE_ITEMS = ("choiceband", "choicescarf", "choicespecs")`.
- Produces `check(line: str, view) -> str | None`:
  - It returns `None` for a room line, `"fold"` for a line the tracker folds, and `"turn:<NAME>"` for a turn-scoped feature line.
  - It raises `Stop("feature:<NAME>")` for a feature without its bit in `SUPPORTED`, and `Stop("line:<kind> <effect>")` for an unknown line.
  - `view` is the tracker. `check` reads `view.current_ability(pos)` (1-based ability id) and `view.sheet_item(pos)` (1-based item id, 0 for none) of the position a line names, and `view.data.tables`.
- **The table** follows spec section 5 exactly.
  - Generic fold kinds: `move` (attributes as the converter accepts), `switch`, `-damage`, `-heal`, `faint`, `cant`, `-miss`, `-crit`, `-supereffective`, `-resisted`, `-immune`, `-fail`, `-boost`, `-unboost`, `-status`, `-curestatus`, `-prepare`, `-anim`, `-mega`, `turn`, `upkeep`, `win`, `tie`, and the converter's `NOT_EVENTS`.
  - Per effect:
    - `-activate`: only the effects the reference spectator logs contain (Task 5 gathers and freezes them);
    - `-singleturn`: Protect, Helping Hand, `move: Follow Me`; Rage Powder, Wide Guard and Quick Guard are turn-scoped;
    - `-start`/`-end`: `confusion`, `ability: Flash Fire`, and the 0018 features (`perishN`, `move: Taunt`, …);
    - `-weather`: RainDance, SunnyDay, none; Sandstorm and Snowscape are features;
    - `-fieldstart`/`-fieldend`: Grassy, Psychic, Trick Room; Electric, Misty and Gravity are features;
    - `-sidestart`/`-sideend`: Tailwind, Reflect, Light Screen; Aurora Veil and the hazards are features;
    - `-ability`, `-enditem`, `-item`, `detailschange`, `-formechange`: as the spec's examples;
    - `replace` is ILLUSION;
    - `move` of Baton Pass or Revival Blessing is `line:move <name>`.
- The tracker reraises the converter's `ConversionError` as `Stop(f"converter:{e.rule}")`. Its other `ValueError`s stay as they are.

- [ ] **Step 1:** Write `LinesTest`. Each case below is one assertion:
  - `|-weather|Sandstorm|[from] ability: Sand Stream|[of] p1a: X` gives `Stop("feature:WEATHER_SAND")`.
  - `|-ability|p2a: X|Intimidate|[from] ability: Trace|[of] p1a: Y` gives `feature:ABILITY_CHANGE`.
  - `|-enditem|p1a: X|Sitrus Berry|[from] move: Knock Off|[of] p2a: Y` gives `feature:ITEM_CHANGE`.
  - `|-enditem|p1a: X|Sitrus Berry|[eat]`, where it is X's sheet item, gives `"fold"`.
  - `|-sethp|p1a: X|50/100` gives `line:-sethp`.
  - `|move|p1a: X|Baton Pass|p1a: X` gives `line:move Baton Pass`.
  - `|-singleturn|p1a: X|move: Rage Powder` gives `"turn:RAGE_POWDER"`.
  - `|j|☆x` gives `None`.
  - `|-ability|p1a: X|Pressure`, where Pressure is X's ability, gives `"fold"`.

  Run it and see it FAIL.
- [ ] **Step 2:** Implement `lines.py` and the `feed` hook. Run the unit tests, then `-m unittest python.tests.test_live -v` with the reference env: every live test still passes. This is outside 17:00–17:45.
- [ ] **Step 3:** Commit with the message `Live tracker: line classes (fold, feature, unknown), stops are explicit`.

### Task 4: Stat point prior and stats

**Files:**
- Create: `python/duoforge_replay/prior.py`, `stats.py`
- Test: `test_replay_unit.py` (`PriorTest`) and `test_replay.py` (`test_choice_items_equal_showdown`; this test needs only Node and the pin, not the harness)

**Interfaces:**
- Produces `prior.build(paste_dir: Path) -> dict`, as JSON: `{"version": 1, "pastes": n, "levels": [ {key: [sp*6, count]}, … ×4 ]}`.
  - The keys are the to_id joins of spec section 10's fields; the move set is sorted and joined with `,`.
  - Pastes are read with `duoforge_live.teams._paste`. A nickname head `Nick (Species)` is accepted here by taking the species in parentheses.
- Produces `prior.Prior(data: dict)` with `.lookup(sheet: dict) -> tuple[list[int], int]`, giving (stat points, level). `Prior.load(path)` reads the file.
- Produces `stats.StatSource(node: str, ps_dir: str)`, a persistent `ps_stats.js --serve` process, with:
  - `.stats(species_name: str, nature: str, sp: list[int]) -> list[int]` (6 stats, cached);
  - `.close()`.

- [ ] **Step 1:** Write the tests.
  - `PriorTest`, with a temporary paste dir built from `tests/reference/teams/team_a.txt`, `team_b.txt` and a copy of team A whose Rillaboom has another spread:
    - Team A's sheet gives level 0 with its own spread;
    - a changed move set gives level 1;
    - a changed item gives level 2;
    - a changed nature gives level 3;
    - an unknown species gives `([0]*6, 4)`;
    - the two-spread tie gives the smaller tuple.
  - `test_choice_items_equal_showdown`: `lines.CHOICE_ITEMS` equals `ps_stats.js --choice-items`.

  Run them and see them FAIL.
- [ ] **Step 2:** Implement it. Run the tests; they pass.
- [ ] **Step 3:** Commit with the message `Replay: stat point prior and Showdown stats`.

### Task 5: Decision points and the spectator tracker, equal to DuoForge

**Files:**
- Create: `python/duoforge_replay/__init__.py`, `points.py`, `spectator.py`
- Modify: `python/duoforge_live/tracker.py`:
  - the hooks `_public(side) -> bool` and `_view_own_member(...)`;
  - the fold of choice lock, Follow Me, Helping Hand and Unburden;
  - the view changes of supported `[silent]` lines, as the test demands.
- Modify: `python/duoforge_live/lines.py` (freeze the `-activate` effects seen in the reference logs)
- Create: `python/tests/_replay_reference.py`, the harness, built once per process:
  - the spectator streams of `ps_client.js --every --spectator`;
  - views from `conformance_records.py --all` plus `duoforge_diff_runner --dump-views` on `closure.records`, `team_c.records` and `pool.records`;
  - the traces through `trace_to_c.load_battle`.
- Create: `python/tests/test_replay.py`, tests 1, 2 and 5 of spec section 14.
- Create: `python/tests/data/replay/<battle>.log`, the spectator log of one reference battle with a Mega, a pivot and a replacement (pick it with the harness), for the unit tests.

**Interfaces:**
- Produces `points.Point`, a frozen dataclass:
  - `index: int` (0-based);
  - `line: int`, the index in the log's line list where the observation is taken (exclusive);
  - `boundary: int` (`DUOFORGE_BOUNDARY_*`);
  - `run: tuple[int, ...]`, the flat positions `side*2+slot` that switch in this point's run (empty for TS and TURN);
  - `turn_end: int`, the index of the `|upkeep|` (or the end) closing the turn whose actions label it.
- Produces `points.find(lines: list[str]) -> list[Point]`, following spec section 7. It raises `Stop("structure:…")` (from `duoforge_live.lines`) or `Skip("skip:sheets-late")`, and does not fold.
- Produces `spectator.SpectatorTracker(data, sheets: tuple[list[dict], list[dict]], side: int, picks: tuple[int, ...] | None, stats_of)`.
  - `sheets` are both sides' unpacked `|showteam|` sets (`teams.unpack`).
  - `picks` are the own roster indices: leads in slot order, then back members ascending; `None` before they are known.
  - `stats_of(species_forme_id, sheet) -> list[int] (6)` gives the own member's stats and stat points.
  - It feeds lines like `Tracker`, through the converter with viewer 2.
  - `at_point(point: Point) -> None` advances the epoch, sets the boundary and computes the requested slots of both sides by the switch flag rule, with `point.run` positions flagged first. A switching position that is not asked raises `Stop("structure:…")`.
  - `observation()` and `ready` keep the base class's meaning.
- Produces `spectator.own_requested(tracker) -> int`, the own requested slot mask.

- [ ] **Step 1:** Write `test_replay.py`. All tests run over every battle × side; a failure names the battle, k and side.
  - `test_points_equal_duoforge`: for each battle and side, the spectator's points where the side is requested have epochs `{k+1 : views[(k, side)].requested == 1}`, with the same `boundary_kind`, `slot_mask` and both sides' `requested`/`requested_slots`.
  - `test_view_equals_duoforge`: at each own point, `differences(spec_obs, views[(k, side)].obs)` (copy the helper from `test_live.py`) is empty after the documented fields are taken out. Those fields are then asserted against their sources:
    - own `hp`, `hp_max`, `hp_kind`, `hp_flag`, `pp`, `pp_kind` equal the foe player's view `views[(k, 1-side)]` of the same member;
    - for a member that never entered, `hp == 100 == hp_max` against DuoForge's `hp == hp_max`;
    - `stats` and `stat_points` equal DuoForge's own (the harness passes the true team as `stats_of`, with stats from `ps_stats.js` through `StatSource` of Task 4);
    - `brought_order[:2]` is equal and `set(brought_order[2:4])` is equal.
  - `test_stats_equal_duoforge`: for every member of every reference team, base forme and Mega forme, `StatSource.stats` (Task 4) equals DuoForge's own view stats (atk..spe, plus `hp_max` for HP) at a point where the member is on the field in that forme.
  - `test_reference_logs_never_stop`: no `Stop` in any reference spectator log.

  Run it with the reference env and see it FAIL (the modules do not exist).
- [ ] **Step 2:** Implement `points.py` and `spectator.py`, then the tracker hooks. Make the three tests pass by extending the fold, only where a test names a field and only from protocol lines (choice lock, position flags, silent lines). Record every new fold rule in a comment that names the reference battle that proves it.
- [ ] **Step 3:** Freeze the `-activate` effect list from what the harness saw. Run `test_live` (still green) and `test_replay` (green).
- [ ] **Step 4:** Commit with the message `Spectator tracker and decision points, equal to DuoForge on every reference battle`.

### Task 6: Superset options

**Files:**
- Create: `python/duoforge_replay/superset.py`
- Test: `python/tests/test_replay.py` (`test_superset_contains_duoforge`) and `test_replay_unit.py` (`SupersetTest`)

**Interfaces:**
- Produces `superset.domain(tracker: SpectatorTracker) -> tuple[np.ndarray, list[list[Option]] | None]`. It returns the `FACTORED_DOMAIN` record with epoch, slot lists and full pair mask, and the slot lists; at team selection it returns `options.team_domain(epoch, 6, 4)` and `None`.
  - It builds a synthetic request from the tracker's state, as in spec section 8, and calls `options.slot_options` and `options.domain`.
  - Target types come from `Data.target_type`.
  - The own locked target comes from the tracker.

- [ ] **Step 1:** Write the tests.
  - `test_superset_contains_duoforge`: at every own point, DuoForge's slot commands, as sets of `(kind, move_slot, target, mega, reserve)`, are a subset of the superset's.
  - `SupersetTest` on the fixture log: a move with derived PP 0 is absent; at a REPLACEMENT the list is the alive brought bench plus PASS.

  Run them and see them FAIL.
- [ ] **Step 2:** Implement it. Run the tests; they pass.
- [ ] **Step 3:** Commit with the message `Replay: superset options`.

### Task 7: Labels

**Files:**
- Create: `python/duoforge_replay/labels.py`
- Test: `test_replay.py` (`test_true_choice_in_label`) and `test_replay_unit.py` (`LabelsTest`)

**Interfaces:**
- Produces reason constants `NOT_REQUESTED, EXACT, TARGET_UNKNOWN, MOVE_HIDDEN, FORCED, UNKNOWN = range(6)`.
- Produces `Label`, a dataclass:
  - `slots: tuple[int, int]` (u32 masks);
  - `team: bytes` (45 bytes, bit i = `TEAM_TABLE[i]` of `duoforge_live.game`);
  - `reasons: tuple[int, int]`.
- Produces `labels.turn_label(lines, point, side, names, lists, stop_line) -> Label`. `names` maps protocol names to roster indices for both sides, as the tracker's `_names`.
- Produces `labels.switch_label(lines, point, side, names, lists, stop_line) -> Label`, for REPLACEMENT and PIVOT.
- Produces `labels.team_label(leads: tuple[int, int], seen_back: set[int], member_count=6) -> Label`.
- The rules are spec section 9, read from raw lines, including the cut at `stop_line`.

- [ ] **Step 1:** Write the tests.
  - `test_true_choice_in_label`: for every own decision of every reference battle, the trace's choice is in the label set. Pass `step.input[pid]` through `trace_to_c.convert_choice` to get the commands, then find their indices in the superset lists; for a team choice, find the tuple index. The test prints the share of EXACT slots.
  - `LabelsTest`, one fixture-log segment per reason:
    - a plain move gives EXACT;
    - a Follow Me line earlier in the turn gives TARGET_UNKNOWN, with every target of that move set;
    - `|cant|…|par` gives MOVE_HIDDEN, with every move option of the shown Mega choice;
    - `[from]lockedmove` gives FORCED, with all bits set;
    - a stop line before the slot's move gives UNKNOWN;
    - team selection with one back member seen gives 6 tuples, and with none seen 12.

  Run them and see them FAIL.
- [ ] **Step 2:** Implement it. Run the tests; they pass.
- [ ] **Step 3:** Commit with the message `Replay: option-set labels`.

### Task 8: One game end to end

**Files:**
- Create: `python/duoforge_replay/game.py`
- Test: `test_replay_unit.py` (`GameTest`)

**Interfaces:**
- Produces `class Skip(Exception)` with the attribute `reason`.
- Produces `GameRecord`, a dataclass:
  - `replay_id`, `format_id: str`;
  - `bo3_game: int`;
  - `ratings: tuple[int, int]`;
  - `winner: int`;
  - `turns: int`;
  - `players: tuple[int, int]` (u64 hashes);
  - `sheets: tuple[int, int]` (u64 hashes).
- Produces `Row`, a dataclass:
  - `observation`, `domain` (NumPy records);
  - `side: int`, `point: int`;
  - `label: Label`;
  - `prior_level: tuple[int, ...]` (6).
- Produces `GameResult(record: GameRecord, rows: list[Row], counters: collections.Counter)`.
- Produces `game.process(replay_id: str, format_id: str, log: str, data, prior: Prior, stats: StatSource) -> GameResult`. It raises `Skip`, and it never raises any other exception for a malformed game.
- Counter keys:
  - `games.skipped.<reason>`;
  - `perspectives.kept`;
  - `perspectives.stopped.<reason>`;
  - `points.written`;
  - `points.dropped.<reason>`;
  - `labels.<REASON>`;
  - `turn-scoped.<NAME>`.

- [ ] **Step 1:** Write `GameTest` on the fixture log:
  - the clean log gives rows for both sides, with `points.written` equal to the number of own points and every `perspectives.kept` at 2;
  - a `|-weather|Sandstorm` line injected after `|turn|2` keeps the points up to turn 2 and counts the rest under `points.dropped.feature:WEATHER_SAND`;
  - an Illusion ability in one sheet gives `Skip("skip:illusion")`;
  - `test_session_line_skips_game`, `test_unknown_name_skips_with_reason`, `test_no_win_line`, `test_player_ratings` (Review Focus 1–4);
  - a Rage Powder line in a turn without a pivot gives `turn-scoped.RAGE_POWDER` and no stop; with a PIVOT point after it in the same turn, `feature:RAGE_POWDER`;
  - a log where one back member never appears gives only the team selection row for that side and `perspectives.stopped.picks-incomplete`.

  Run it and see it FAIL.
- [ ] **Step 2:** Implement it. The pre-pass, then `points.find`, then for each side a `SpectatorTracker` fed to each point, with `superset.domain` and the labels; `Stop` is caught per side. Run the tests; they pass.
- [ ] **Step 3:** Commit with the message `Replay: one game end to end, with skips and stops counted`.

### Task 9: Source, writer and command line

**Files:**
- Create: `python/duoforge_replay/source.py`, `dataset.py`, `__main__.py`
- Test: `test_replay_unit.py` (`DatasetTest`, `SourceTest`)

**Interfaces:**
- Produces `source.games(paths: list[Path], format_prefix="gen9championsvgc2026regmc") -> Iterator[tuple[str, str, str]]`, yielding `(id, formatid, log)` in file and row order. pyarrow is imported inside it.
- Produces `source.select(rows: Iterable[tuple[str, str, str]], format_prefix) -> Iterator[...]`: the format and two-sheet filter, counting `games.skipped.skip:format` and `skip:sheets`.
- Produces `dataset.Writer(out_dir: Path, manifest: dict, shard_rows=65536)`:
  - `.add(result: GameResult)`;
  - `.close() -> dict` (the counters).
  - It raises `ValueError("the output … is inside the repository")` when `out_dir` resolves under `data.ROOT`.
  - Zip entries carry `date_time=(1980, 1, 1, 0, 0, 0)` and `ZIP_DEFLATED`.
- Produces `dataset.read(out_dir) -> Iterator[dict[str, np.ndarray]]`, one dict per shard, plus `dataset.read_games(out_dir) -> dict[str, np.ndarray]`.
- CLI as in spec section 12:
  - `build` runs `--workers N` processes, each with its own `StatSource`, over chunks of 64 games with `multiprocessing` (spawn).
  - Results are merged in chunk order.
  - Between chunks it waits while `$DUOFORGE_FUZZ_PAUSE` (or `%TEMP%/duoforge-fuzz.pause`) exists.
  - It exits 1 after printing `internal:` examples.

- [ ] **Step 1:** Write the tests.
  - `DatasetTest`:
    - a round trip of two `GameResult`s;
    - writing twice gives the same shard bytes;
    - `Writer(ROOT / "x")` raises;
    - the counters add up (`points.written` equals the row count);
    - `test_workers_same_bytes` (Review Focus 5) runs `build` on a temporary source of fixture games with `--workers 1` and `2` through a fake source.
  - `SourceTest`: `select` on synthetic tuples.

  Run them and see them FAIL.
- [ ] **Step 2:** Implement it. Run the tests; they pass.
- [ ] **Step 3:** Commit with the message `Replay: parquet source, deterministic shards, command line`.

### Task 10: Registration, docs, verification, PR

**Files:**
- Modify: `tests/CMakeLists.txt`:
  - add `replay_unit` to the `foreach(_py …)` list;
  - add `duoforge.python.replay` next to `duoforge.python.live`, with the same env, `TIMEOUT 900` and a skip fallback.
- Create: `docs/decisions/0019-m11-replay-data.md`, a one-page summary of the spec's decisions. Confirm the number with the HauptSession first.
- Create: `python/duoforge_replay/README.md` with the commands, the requirements and the data rule.

- [ ] **Step 1:** Register both tests, then configure and run `ctest -R "duoforge.python.(replay|live)" --output-on-failure`. Everything passes. Not in a quiet window.
- [ ] **Step 2:** Run a development smoke run: `build --limit-games 300`, with the spike venv for pyarrow, into `C:\Dev\src\duoforge-data\m11\smoke`. Note the counters and the games/s. Before the name rows land most games skip with `name:`; that is expected.
- [ ] **Step 3:** Run `tools/ci/local_ci.sh --quick`; it passes.
- [ ] **Step 4:** Commit, push, and open a PR against `main`.
  - Body: summary, the stops and skips, the test results, and the smoke counters.
  - It ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- [ ] **Step 5:** Run the review agent `fullstack-dev-kit:pr-reviewer` (opus) on the PR. Verify each finding, fix it, retest and push.
- [ ] **Step 6:** When the 13 hosted checks are green, send the HauptSession the PR number and the green head. The merge comes after Learner v2.
