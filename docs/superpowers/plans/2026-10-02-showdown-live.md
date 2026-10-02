# Showdown Live Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The night run's bot (update 25000) plays challenges on the official Pokémon Showdown server, in Bo1 (`gen9championsvgc2026regmc`) and Bo3 (`gen9championsvgc2026regmcbo3`), against players who use Team A or B with open team sheets.

**Architecture:** A small Python package, `python/duoforge_live`, with one unit per concern:
- `policy`: the network in NumPy.
- `data` and `teams`: sheets and ids through the converter's tables.
- `options`: a request's slot options, as DuoForge commands and as Showdown text.
- `tracker`: the protocol folded into DuoForge's `OBSERVATION`.
- `game`: the decisions of one battle, without IO.
- `client`: the websocket, the login, challenges and etiquette.

One oracle proves it. A Node helper replays every committed closure battle in the pinned Showdown and writes each player's client stream. The C runner dumps what DuoForge shows at every step. The tracker and the options must equal that dump byte for byte.

**Tech Stack:**
- Python 3.12 (`.venv`), NumPy 2, and the stdlib (asyncio, urllib, json). `websockets` is used only for the live connection.
- Node 18+ with the pinned Showdown, for the reference tests.
- C (`tools/difftest`) for the view dump.
- CMake/CTest.
- JAX only in the existing JAX test job.

**Spec:** `docs/superpowers/specs/2026-10-02-showdown-live-design.md` (8d70439, owner-approved 2026-10-02).

## Global Constraints

- **AGENTS.md applies.**
  - Correctness first.
  - No hidden rule implementation in Python: the tracker only records what Showdown reports and is checked against DuoForge.
  - Unsupported input fails explicitly.
  - Determinism.
  - Tests are never weakened.
- **Formats:** exactly `gen9championsvgc2026regmc` (Bo1, Open Team Sheets on request) and `gen9championsvgc2026regmcbo3` (Bo3, Force Open Team Sheets). Every other format is rejected.
- **Chat texts:** exactly those of spec section 7, as constants in `client.py`.
- **Password:**
  - Read only from the env var `DUOFORGE_PS_PASSWORD`, at run time.
  - Never logged, printed, stored or put on argv.
  - Without it, the bot logs in as a guest.
- **Official server:**
  - The bot only accepts challenges and plays one battle or Bo3 series at a time. It never ladders.
  - `--challenge` is refused for any host ending in `psim.us` or `pokemonshowdown.com`.
- **Logs:** one JSONL file per battle in `--log-dir`. The default is `%LOCALAPPDATA%\duoforge-live`, outside the repository.
- **Dependencies:** `websockets` is the only new one (owner OK 2026-10-02). It is imported inside the connect function, so every test runs without it.
- **Ids:** only through `tools/reference/trace_to_c.py` (`load_tables`, `parse_team`, `key`). Its `ConversionError` subclasses `SystemExit`, so it is caught by name.
- **C code:**
  - The C library does not change, so there is no version bump.
  - `diff_runner.c` gets only `--dump-views`, on the expansion lead's conditions (Task 1).
- **`duoforge_learn/checkpoint.py`:** gets only `widen_594` and the `widen IN OUT` command (agreed with the Learner v2 session).
- **Encoding of the v1 checkpoint.**
  - The night checkpoint was trained while `features.py` had `present = species_id != 0`. Rillaboom has forme id 0, and Team A holds it. A fix session corrects the encoder.
  - Decision: the bot plays a v1 checkpoint with the encoding it was trained on, through the fix PR #88: `features.as_encoder(obs_part, observations, checkpoint.encoder_of(config))` (version 1 rebuilds the old `present` column; 2 is the fixed encoding; others raise). New checkpoints use the fixed encoding.
  - The switch and its test come with the fix PR (HauptSession). Do not build it here. Task 6 needs that PR merged.
  - The checkpoint config key is the integer `"encoder"` (agreed with the HauptSession and Learner v2): 1 before the fix, 2 after; a missing key means 1.
- **The bot's name** must contain "bot" (any case), so the name says it is a bot (spec section 7).
- **Greedy and deterministic:** a tie between pairs or tuples goes to the lower flat index.
- **Process:**
  - One PR per task, on branch `chris/live-<n>-<topic>`. Branch from main once the task's dependencies are merged; otherwise stack on the open dependency's branch.
  - `tools/ci/local_ci.sh --quick` between iterations. The full run (11 jobs, machine lock) goes before the PR is handed to the main session "HauptSession" (formerly "M2 Requests and Commands"): send it the PR number and the green head; it merges with a merge commit.
  - A review agent (`fullstack-dev-kit:pr-reviewer`, model opus) on every code PR.
  - Stage files by name, never with `git add -A`. Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

The inputs most likely to hurt a live game that no spec test names. Each has a test in its owning task.

1. **A foe whose Pokémon have nicknames.** The protocol says `p2a: Nick`, and the sheet has no names. The tracker must map a Pokémon by the species of its first `|switch|`, and the observation must stay the same. Test: Task 5, `test_foe_nicknames_change_nothing`.
2. **Room lines in the battle room** (chat, the timer, joins) between a step's update and its request. They change no observation and never make a decision point. Tests: Task 5, `test_room_lines_do_not_complete_a_decision`; Task 6, `test_chat_between_request_and_update`.
3. **The same request twice** (a reconnect, the same `rqid`). There is no new decision point, the epoch does not move, and the bot sends one `/choose`. Tests: Task 5 `test_repeated_request_is_one_decision`; Task 6 `test_repeated_request_one_choice`.
4. **The tracker raises `ConversionError`** (a `SystemExit`) on an unknown line. The bot catches it, forfeits with the internal-error message and keeps running. Test: Task 6, `test_unknown_line_forfeits_and_keeps_running`.
5. **The battle ends while the bot waits** (the foe forfeits during the sheet wait or between Bo3 games). The bot sends no `/forfeit`, sends "gg", closes the log and is free for the next challenge. Test: Task 6, `test_foe_forfeits_during_sheet_wait`.

## Setup (once, in this worktree)

- [ ] `cmd //c mklink //J .venv C:\\Dev\\src\\duoforge\\.venv`
  - This lets `local_ci.sh` run the Python tests.
  - Remove it only with `cmd //c rmdir .venv`.
- [ ] Development build (Git Bash, GCC Debug, reference and Python tests):

```bash
export PATH="$LOCALAPPDATA/Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin:$PATH"
cmake -S . -B build/dev -G Ninja -DCMAKE_BUILD_TYPE=Debug -DCMAKE_C_COMPILER=gcc -DBUILD_TESTING=ON -DDUOFORGE_WARNINGS_AS_ERRORS=ON -DDUOFORGE_PS_REFERENCE_DIR=C:/Dev/src/pokemon-showdown -DDUOFORGE_PYTHON=C:/Dev/src/duoforge/.venv/Scripts/python.exe
cmake --build build/dev --parallel
```

- [ ] The test commands below use `ctest --test-dir build/dev -R <name> --output-on-failure`.

## File Structure

| File | Task | Responsibility |
|---|---|---|
| `docs/decisions/0016-showdown-live-adapter.md` | 1 | Decision note: owner decisions, scope, evidence; points to the spec |
| `tools/reference/ps_client.js` | 1 | Replays committed battles; writes each player's client stream; `--pack` |
| `tools/difftest/diff_runner.c` | 1 | `--dump-views FILE` |
| `tools/reference/test_dump_views.py` | 1 | The lead's test of the dump |
| `python/duoforge_live/__init__.py` | 2 | Package docstring |
| `python/duoforge_live/policy.py` | 2 | NumPy forward pass, ranked pairs and tuples, checkpoint loading |
| `python/duoforge_learn/checkpoint.py` | 2 | `widen_594`, `widen IN OUT` |
| `python/duoforge_live/data.py` | 3 | Tables (via `trace_to_c`), max PP, Mega stones, formes |
| `python/duoforge_live/teams.py` | 3 | Team A/B text, `pack`, `unpack`, `match` |
| `python/duoforge_live/options.py` | 4 | Request to slot options, `FACTORED_DOMAIN`, choice text |
| `python/duoforge_live/tracker.py` | 5 | Protocol to `OBSERVATION`; decision points |
| `python/duoforge_live/game.py` | 6 | One battle: tracker, options and policy, ranked candidates |
| `python/duoforge_live/client.py` | 6 | Websocket, login, challenges, rooms, Bo3, etiquette, logs |
| `python/duoforge_live/__main__.py` | 6 | CLI |
| `python/tests/test_live_unit.py` | 3–6 | Tests without Node (CTest `duoforge.python.live_unit`) |
| `python/tests/test_live.py` | 3–5 | Reference tests with Node (CTest `duoforge.python.live`) |

---

### Task 1: Client streams and engine views (PR 1, `chris/live-1-streams`, from main)

The PR also carries the spec, this plan and decision 0016.

**Files:**
- Create: `docs/decisions/0016-showdown-live-adapter.md`, `tools/reference/ps_client.js`, `tools/reference/test_dump_views.py`
- Modify: `tools/difftest/diff_runner.c` (usage, argument parsing, `run_battle` gets `FILE *views`), `tests/CMakeLists.txt`, `tools/reference/README.md` (one entry each)

**Interfaces (produces):**
- `node tools/reference/ps_client.js <checkout> <repo root> (--all | NAME...) [--check]`
  - Replays each committed closure battle. `--all` means every spec without `"data": "team_c"`.
  - Every step uses the inputs recorded in `tests/reference/traces/NAME.json`.
  - It uses `new Battle({formatid, prng: new PRNG(spec.seed), send})`, with `setPlayer` as `ps_trace.js` does, and calls `battle.sendUpdates()` after every command, as `BattleStream._write` does.
  - After both `setPlayer` calls it runs `battle.showOpenTeamSheets()` (then `sendUpdates`), as the server does when both players accept.
  - **Output:** one JSON object per message, in the order a websocket client gets them: `{"battle": NAME, "to": "p1"|"p2", "lines": [...]}`.
    - A `sideupdate` message goes to its side.
    - An `update` message goes to each player through `extractChannelMessages(data, [1, 2])`.
    - `|t:|` lines and empty messages are dropped.
  - **Self-check, always:**
    - Each step's omniscient lines, filtered as `ps_trace.js` `takeLog` does, must equal `trace.steps[k].log`.
    - The start lines without the two `|showteam|` lines must equal `trace.start.log`.
    - Otherwise it exits 1 with `ps_client: NAME step K differs from the trace`.
  - `--check` writes no stream and prints `ps_client: N battles match their traces`.
- `node tools/reference/ps_client.js <checkout> --pack <team file>` prints `Teams.pack(Teams.import(text))` and a newline.
- `duoforge_diff_runner [--dump-views FILE] [records file]`
  - With the flag, it writes `V <battle> <k> <viewer> <observation hex> <domain hex>`: lowercase hex, 1472 and 1304 characters. These come from `duoforge_battle_observe` and `duoforge_battle_factored`.
  - It writes after the create (k = 0) and after every applied step that passed its comparisons (k = si + 1), viewer 0 then 1.
  - A failing observe or factored call is a DIVERGENCE: `views: <status> (view K)`.
  - A write, flush or close error of FILE exits 1, with a message on stderr.
  - Without the flag, everything is byte-identical (the lead's conditions).

- [ ] **Step 1: Write the failing tests.**
  - `tools/reference/test_dump_views.py <runner> <records dir>` runs with `DUOFORGE_PYTHON` and needs `DUOFORGE_LIBRARY`.
  - It is registered as `duoforge.reference.dump_views` with `FIXTURES_REQUIRED duoforge_conformance_records`, and as a skip test without `DUOFORGE_PYTHON`.

```python
def test_views_of_every_battle(self):      # all R lines PASS; per battle 2 * (steps + 1) V lines,
    ...                                    # k ascending, viewer 0 then 1, epoch == k + 1, player == viewer,
                                           # boundary of the last observation TERMINAL when the battle ended
def test_first_view_is_the_public_api(self):
    # m5_real_ab_1 is Team A vs Team B: reference_setups([0]) (0 = A-B). Assert the setup's species equal
    # the record's M lines, then compare its k = 0 lines with a Batch's query_factored() of that setup.
    batch = duoforge.Batch(duoforge.Context(), duoforge.reference_setups([0]), 1, 1)
    batch.query_factored()
    for viewer in (0, 1):
        self.assertEqual(views[("m5_real_ab_1", 0, viewer)], (batch.observations[0, viewer].tobytes(),
                                                              batch.domains[0, viewer].tobytes()))
def test_flag_changes_nothing_else(self):  # stdout with and without --dump-views byte-identical
def test_unwritable_file_fails(self):      # FILE = an existing directory: exit 1, stderr names FILE, no R line claims PASS for a short file
```

  - Also register `duoforge.reference.client_streams`: `node ps_client.js <checkout> <root> --all --check`, in the Node block, timeout 300.
- [ ] **Step 2: Run them and check that they fail.**
  - `ctest --test-dir build/dev -R "dump_views|client_streams" --output-on-failure`
  - Expected: FAIL (unknown flag; missing script).
- [ ] **Step 3: Implement `ps_client.js` and the flag.** In the runner, add `static int write_views(FILE *f, const char *name, uint32_t k, const duoforge_context *ctx, const duoforge_battle *b, outcome *o)`. Call it after the create and after each step's checks pass. Test the `ferror`/`fflush`/`fclose` results.
- [ ] **Step 4: Run them and check that they pass,** together with the runner's existing tests:
  - `ctest --test-dir build/dev -R "dump_views|client_streams|diff_replay|diff_driver|diff_random|runner_records|runner_domain" --output-on-failure`
  - Expected: all PASS.
- [ ] **Step 5: Write decision 0016.**
  - About 40 lines: status, the owner decisions (spec section 2), scope and refusals, the information argument (spec section 4), the v1 encoding (`as_encoder`), the evidence (spec section 8), the coordination.
- [ ] **Step 6: Commit, run CI, hand off.**
  - Commit; `local_ci.sh --quick`; review agent; full `local_ci.sh`.
  - Open the PR; send the PR number to the lead (runner review) and to the main session.

### Task 2: NumPy policy and checkpoint widening (PR 2, `chris/live-2-policy`)

**Files:**
- Create: `python/duoforge_live/__init__.py`, `python/duoforge_live/policy.py`
- Modify: `python/duoforge_learn/checkpoint.py`, `python/tests/test_learn_numpy.py`, `python/tests/test_learn.py`

**Interfaces (produces):**
- `policy.forward(params, obs, slots, mask) -> (logp_pairs (B, 1024), logp_team (B, T), value (B,))`
  - The same computation as `duoforge_learn.model.apply`, in float32 NumPy. `MASKED = -1e9`; the log-softmax is computed stably.
- `policy.Policy(params)`
  - `.rank_pairs(obs_part, slot_part, pair_mask) -> list[tuple[int, int, float]]` lists the allowed pairs, best first, with their probabilities.
  - `.rank_teams(obs_part) -> list[tuple[int, float]]` lists tuple indices into `duoforge_learn.selfplay.TEAM_TABLE`, best first.
  - Ties go to the lower flat index.
- `policy.load(path) -> Policy` uses `checkpoint.load(path, obs_size=features.OBS_SIZE)`, so a 594-feature file raises.
- `Policy.encoder -> int` is `checkpoint.encoder_of(config)` (#88). `Policy.rank_pairs` and `rank_teams` take the raw `obs_part` and apply `features.as_encoder(obs_part, observations, self.encoder)` themselves, so they also take the observations. The widen command writes `"encoder": 1` into OUT's config.
- `checkpoint.WIDEN_594_COLUMNS = (12, 37, 38, 39, 61, 62, 63, 333, 334, 335, 357, 358, 359)` gives the indices in the 607 layout.
- `checkpoint.widen_594(params) -> params`
  - Returns a new dict whose `t1.w` has zero rows inserted at those indices.
  - Any `t1.w.shape[0] != 594` raises `ValueError`.
- `python -m duoforge_learn.checkpoint widen IN OUT`
  - Loads IN with `obs_size=594` and writes OUT in `train.save`'s npz format, with IN's config.
  - OUT that exists is refused.

- [ ] **Step 1: Write the failing tests** in `test_learn_numpy.py`:

```python
def test_widened_columns_are_the_new_features(self):
    # a minimal valid OBSERVATION (boundary TURN, occupants NONE) and a TURN-less domain:
    # terrain PSYCHIC sets column 12, NONE and GRASSY leave it 0; each POSITION_FLAGS bit of each of the
    # four positions changes exactly one column, and the 12 columns are WIDEN_594_COLUMNS[1:]
def test_widened_columns_are_zero_under_closure(self):
    # SelfPlay(16, 2, seed) with RandomPolicy-like uniform choices over 200 steps:
    # encoded obs[:, WIDEN_594_COLUMNS] == 0 everywhere
def test_widened_network_matches_the_original(self):
    # random 594 params (shapes of model.init: hidden 256, option 128, TEAM_ACTIONS 360);
    # forward(widen_594(p), x607) vs forward(p, np.delete(x607, WIDEN_594_COLUMNS, axis=1)):
    # allclose(rtol=1e-5, atol=1e-5) on real observations; greedy pair and team argmax equal
def test_widen_refuses_other_sizes(self):    # a 607 network -> ValueError
def test_widen_command(self):                # main(["widen", IN, OUT]): OUT loads with obs_size 607, rows zero,
                                             # config "encoder" == 1; IN with obs_size 607 raises; an existing OUT is refused
def test_v1_checkpoint_uses_the_legacy_encoding(self):  # policy.load of the widened file: encoder 1;
                                                        # no "encoder" key -> 1; "encoder": 2 -> 2;
                                                        # "encoder": 3 -> ValueError (encoder_of/as_encoder)
```

  Then in `test_learn.py` (the JAX job):

```python
def test_numpy_policy_equals_model_apply(self):
    # model.init(PRNGKey(3), OBS_SIZE, SLOT_FEATURES, TEAM_ACTIONS); random obs/slots, masks with 1..1024 pairs;
    # policy.forward vs model.apply: allclose(rtol=1e-5, atol=1e-4) for both log-probabilities and the value;
    # rank_pairs()[0] equals the argmax of model.apply's pair log-probabilities, and rank_teams()[0] its team argmax
```

- [ ] **Step 2: Run them and check that they fail.** `ctest --test-dir build/dev -R "python.learn_numpy" --output-on-failure` fails with an ImportError.
- [ ] **Step 3: Implement** `policy.py` and the two checkpoint additions. Nothing else changes in `checkpoint.py`.
- [ ] **Step 4: Run them and check that they pass.** Run `duoforge.python.learn_numpy` (PASS). The JAX test runs in WSL `gcc-release-ipo` when `~/df-learn` exists; read its result in the full CI.
- [ ] **Step 5: Commit, CI, review, PR, hand off.**

### Task 3: Sheets and teams (PR 3, `chris/live-3-teams`)

**Files:**
- Create: `python/duoforge_live/data.py`, `python/duoforge_live/teams.py`, `python/tests/test_live_unit.py`, `python/tests/test_live.py`
- Modify: `tests/CMakeLists.txt`
  - Add `live_unit` to the Python `foreach`.
  - Register `duoforge.python.live` in the Node block. It runs with `DUOFORGE_PYTHON` and gets `DUOFORGE_NODE`, `DUOFORGE_PS_REFERENCE_DIR`, `DUOFORGE_DIFF_RUNNER` and `DUOFORGE_LIBRARY` in its environment.
  - Without Node, the PS reference dir or Python, it is the `DUOFORGE_SKIP:` test.

**Interfaces (produces):**
- `data.ROOT` is the repository root, `Path(__file__).resolve().parents[2]`. `tools/reference` is added to `sys.path` with `sys.dont_write_bytecode = True`, as `conformance_records.py` does.
- `data.load(root=ROOT) -> Data`
  - `Data.tables` comes from `trace_to_c.load_tables(root, False)`.
  - `Data.team(text) -> list[dict]` is `trace_to_c.parse_team`: member dicts with `species`, `gender`, `nature`, `sp`, `ability` (+1), `item` (+1) and `moves`.
  - `Data.pp_max(move_id) -> int` reads field 6 of the `dfi_closure_moves` rows in `src/data/closure_tables.c`.
  - Also from the `dfi_closure_formes` rows: `Data.mega_forme(forme_id) -> int | None`, `Data.base_forme(forme_id) -> int` and `Data.ability_of(forme_id) -> int` (+1, as `parse_team`).
  - `Data.mega_capable(species, item) -> bool` is true when the item is the stone of the species' Mega (`mega_item`).
  - `Data.forme(name) -> int` is `tables['FORME'][trace_to_c.key(name)]`.
- `teams.text(name)` returns `tests/reference/teams/team_a.txt` or `team_b.txt` for `'A'` or `'B'`.
- `teams.pack(text) -> str` equals the pin's `Teams.pack(Teams.import(text))`. Names are `packName`, which keeps case.
- `teams.unpack(packed) -> list[dict]` gives keys `name`, `species`, `item`, `ability`, `moves` (list), `nature`, `evs` (6 ints), `gender` (`'M'`/`'F'`/`''`) and `level`.
- `teams.to_text(sets) -> str` is paste text that `parse_team` reads.
- `teams.match(sets, text) -> bool` is true for the same six sets in any order. Moves are compared as a set. Species, item, ability, nature, gender and level must be equal by `key()`.

- [ ] **Step 1: Write the failing tests.**

```python
# test_live_unit.py
def test_pack_unpack_round_trip(self):       # for A and B: pack(to_text(unpack(pack(t)))) == pack(t)
def test_showteam_line_unpacks(self):        # a literal |showteam| payload of Team A (no names, no EVs) -> the six sets
def test_match(self):                        # A and B match themselves; A with members and moves shuffled matches;
                                             # one changed species, move, item, ability, nature or gender does not;
                                             # B does not match A; five sets do not match
def test_data_equals_the_library(self):      # reference_setups([0]): the team-selection observation of a Batch;
                                             # per member: species_id, move_ids, pp_max, mega_capable, ability, item,
                                             # gender, nature equal Data.team(teams.text(X)) + pp_max/mega_capable
# test_live.py (Node)
def test_pack_equals_showdown(self):         # node ps_client.js <checkout> --pack team_X.txt == teams.pack(text) for A, B
```

- [ ] **Step 2: Run them and check that they fail.** `ctest --test-dir build/dev -R "python.live" --output-on-failure` fails with an ImportError.
- [ ] **Step 3: Implement** `data.py` and `teams.py`.
- [ ] **Step 4: Run them and check that they pass.** `ctest --test-dir build/dev -R "python.live" --output-on-failure`: PASS.
- [ ] **Step 5: Commit, CI, review, PR, hand off.**

### Task 4: Options (PR 4, `chris/live-4-options`, needs Tasks 1 and 3)

**Files:**
- Create: `python/duoforge_live/options.py`
- Modify: `python/tests/test_live.py` (the reference harness and the options checks), `python/tests/test_live_unit.py`

**Interfaces:**
- **Consumes:** `Data` (Task 3); `ps_client.js` and `--dump-views` (Task 1).
- **Produces:**
  - `Option(kind, move_slot, target, mega, reserve, text)` is a frozen dataclass. The first five are the `SLOT_COMMAND` fields.
  - `slot_options(request, side, roster_of, locked) -> list[list[Option]]` gives two lists in DuoForge's documented order (`src/state/request.c`, `dfi_slot_candidates`):

| Request | Options of slot list k |
|---|---|
| `wait` | not requested: `domain()` gives kind 0 |
| `active` (TURN) | slot k without a living occupant (`side.pokemon[k]` fainted or missing): PASS (`"pass"`). Struggle (`moves` is the single entry with `id` `struggle`): slot 4, target NONE, mega 0, `"move 1"`. Locked (a single entry without `pp` that is not Struggle): MOVE at the locked slot and `locked[k]`, mega 0, `"move 1"`. Otherwise, for each move entry i that is not `disabled` and has `pp > 0`, ascending: one option per target of its `target` type (normal and any: the three other positions; adjacentAlly: the ally; adjacentAllyOrSelf: self and ally; adjacentFoe: both foes; otherwise NONE), each with mega 0, then mega 1 when `canMegaEvo`. Text: `move i+1`, plus `" <loc>"` with a target (foe slot s is s+1, own slot s is -(s+1)), plus `" mega"`. Then a SWITCH for each reserve, in ascending roster order (`"switch <pos>"`, the 1-based index in `side.pokemon`), unless `trapped`. |
| `forceSwitch` | `forceSwitch[k]` true: a SWITCH per reserve, ascending, then PASS. False: NONE (`"pass"`). |

  - A reserve is a `side.pokemon` entry that is not active and whose condition does not end in `fnt`.
  - `roster_of` maps a request ident (`"p1: Rillaboom"`) to the roster index.
  - `locked` maps a locked slot k to its DuoForge target position. A locked slot without an entry raises `ValueError`.
  - `domain(lists, epoch) -> FACTORED_DOMAIN record`: kind SLOTS, the slot counts and commands, and the provisional `allowed` (every i < n0, j < n1).
  - `team_domain(epoch, member_count, pick_count) -> FACTORED_DOMAIN record`.
  - `none_domain(epoch) -> FACTORED_DOMAIN record` is kind 0, for wait.
  - `pair_text(a, b) -> "<a.text>, <b.text>"`.
  - `team_text(picks) -> "team " + "".join(str(p + 1) for p in picks)`.
  - `own_roster(request, own_members, data) -> dict[str, int]` maps each `side.pokemon` ident to its roster index, through the species of its `details` (a Mega forme goes through `Data.base_forme`).

- **The reference harness** (in `test_live.py`, used by Tasks 4 and 5):
  - It writes the records (`conformance_records.py --all`) and runs the runner with `--dump-views` and `ps_client.js --all` into a temp dir.
  - It loads the traces.
  - It yields, per battle and player, the messages in order, the decision points (k, the request) and the views of point k.
- [ ] **Step 1: Write the failing tests.**

```python
# test_live.py
def test_options_equal_duoforge(self):
    # every decision point k of every closure battle and player, with locked targets from the trace state
    # before step k (abs_target(side, state['sides'][side]['pokemon'][i]['locked'][1])):
    # per slot list, the set of (kind, move_slot, target, mega, reserve) equals the dump's; a waiting player's
    # dump domain has kind 0; every pair the dump allows is in the provisional mask (by command)
def test_choice_text_round_trip(self):
    # every allowed pair of the dump: trace_to_c.convert_choice(pair_text(a, b), side, state, roster_of)
    # == ('slots', [cmd_a, cmd_b]); every TEAM_TABLE tuple: convert_choice(team_text(t)) == ('team', list(t))
# test_live_unit.py
def test_locked_slot_without_target_raises(self):
def test_unknown_target_type_raises(self):   # a target type outside the table raises ValueError
```

- [ ] **Step 2: Run them and check that they fail.** `ctest --test-dir build/dev -R "python.live" --output-on-failure`: FAIL.
- [ ] **Step 3: Implement** `options.py` and the harness.
- [ ] **Step 4: Run them and check that they pass.** PASS on every closure battle.
- [ ] **Step 5: Commit, CI, review, PR, hand off.**

### Task 5: Tracker (PR 5, `chris/live-5-tracker`)

**Files:**
- Create: `python/duoforge_live/tracker.py`
- Modify: `python/tests/test_live.py`

**Interfaces:**
- **Consumes:** `Data`, `teams.unpack`, `options` (Task 4), and `trace_to_c.step_events(lines, viewer, roster_of, maxhp, tables)`. Every battle line goes through `step_events`: one parser, and it raises on unknown lines.
- **Produces:** `Tracker(data, own_text)`:
  - `.feed(lines)` takes one message of the battle room.
  - `.accepted(text)` takes the own choice that Showdown accepted.
  - `.ready -> bool`
  - `.request -> dict`
  - `.side -> int`
  - `.epoch -> int`
  - `.foe_sets -> list[dict] | None`
  - `.ended -> bool`
  - `.observation() -> OBSERVATION record`
  - `.domain() -> FACTORED_DOMAIN record` and `.options() -> list[list[Option]]` both come from `options` with the tracker's roster and locks.

- **Decision points.**
  - At the pin, `Battle.sendUpdates` sends a step's update before its requests (Task 1 ruling). So a `|request|` with a new `rqid` is a decision point, over the battle lines received since the previous one. A repeated `rqid` is ignored.
  - At team preview the point also needs the `|showteam|` lines of both sides; live they come after the request.
  - The epoch is 1 plus the number of earlier decision points.
  - Room lines are folded by nobody: text lines without `|`, `||…`, `c`, `c:`, `chat`, `j`, `J`, `l`, `L`, `n`, `N`, `raw`, `html`, `uhtml`, `uhtmlchange`, `inactive`, `inactiveoff`, `tempnotify`, `tempnotifyoff`, `controlshtml`, `fieldhtml`, `cantleave`, `allowleave`, `title`, `init`, `deinit`, `noinit`, `expire`, `badge`, `rated`, `message`, `notify`, `bigerror`, `error`, `timer`, `request`, `showteam`.
  - Every other line goes to `step_events`.
- **Field sources.** "Event" means a `step_events` tuple of the own view.

| Field | Source |
|---|---|
| `boundary_kind` | `teamPreview` TEAM_SELECTION. `active` TURN. `forceSwitch` or `wait`: REPLACEMENT if the lines since the previous request have `\|upkeep`, else PIVOT (`trace_to_c.boundary_of`). |
| `turn` | the last TURN event |
| `player`, own `requested`/`requested_slots`, `slot_mask` | the request: TEAM_SELECTION 0 slots; TURN the occupied positions; switch `forceSwitch`. `wait` is not requested. |
| foe `requested`/`requested_slots` | TEAM_SELECTION and TURN as the own. REPLACEMENT: foe positions fainted in this step while a foe reserve is left (4 brought minus the foe members seen fainted or standing). PIVOT: the foe position of this step's Parting Shot or Emergency Exit. |
| weather, terrain and Trick Room and their turns | WEATHER, FIELD_START and FIELD_END set them (5 turns). UPKEEP lowers every running count by 1. |
| side conditions | SIDE_START: Tailwind 4; Reflect and Light Screen 5, or 8 when the user of the last MOVE holds Light Clay. SIDE_END sets 0. UPKEEP lowers by 1. |
| own members | the sheet (`Data.team(own_text)`, the stat points). The request gives `hp`/`hp_max`/status (`condition`), `stats`, `details` (forme, is_mega), `ability`, and `item` (`''` means used up). PP is `pp_max` minus the MOVE events of the member (not LOCKED; on its sheet), and must equal the request's PP for an active member. Location: TEAM_SELECTION UNDETERMINED, else ACTIVE, BENCH or NOT_BROUGHT from the accepted `team` choice. `brought_order` is the picks, then NONE. |
| foe members | the sheet from `|showteam|` (`Data.team(teams.to_text(...))`), stat points and stats 0. Seen at its first SWITCH. Unseen: `hp_kind` UNKNOWN, location UNDETERMINED. Seen: the last HP display (`hp` percent, `hp_flag`, `hp_max` 100), location ACTIVE or BENCH, status from the events (NONE at 0 percent). PP is `pp_max` minus the uses seen (DERIVED). MEGA and FORME set `is_mega`, the forme and `Data.ability_of(mega)`. ITEM_END sets `item_used`. `brought_order` is all NONE. |
| occupants | SWITCH events (roster by name; a new name maps through the species of its details) |
| positions | SWITCH resets the position (stages 6, flags 0, lock NONE). BOOST and UNBOOST add or subtract the amount (clamped). CONFUSION_START and END. FLASH_FIRE. PROTECT sets `protecting`, chain +1 (max 6) and a stall count of 2; a FAIL right after the user's Protect MOVE sets chain 0. PREPARE starts the charge (count 2, `locked_slot` = the move's sheet slot, own `locked_target` from the accepted choice). MOVE, CANT and CONFUSED set `acted`. UPKEEP clears `protecting`, lowers the stall and charge counts and clears at 0. |
| `mega_used` | a MEGA event of that side |

  The bias of 6, the durations and the stall count are the values of `src/state/battle_internal.h` and `src/combat/turn.c`, as named constants. Test 1 proves every row; where a row is wrong, the dump decides, and the row is corrected in this table in the same PR.

- [ ] **Step 1: Write the failing tests** in `test_live.py`, on the Task 4 harness:

```python
def test_tracker_equals_duoforge(self):
    # every decision point of every closure battle and both players: tracker.observation().tobytes() equals the
    # dump; on a difference the message names the battle, k, viewer and every differing field path
    # (e.g. "sides[1].members[3].pp[2]: 7 != 8"); tracker.domain() equals options.domain() of Task 4's check
def test_foe_nicknames_change_nothing(self):      # foe idents renamed to "Nick<i>" in the stream: same observations
def test_room_lines_do_not_complete_a_decision(self):  # a chat chunk inserted after every request: ready only
                                                       # after the battle chunk, same observations
def test_repeated_request_is_one_decision(self):  # every request message sent twice: same epochs and observations
def test_unknown_line_raises(self):               # an inserted "|-futureline|p1a: X" raises trace_to_c.ConversionError
```

- [ ] **Step 2: Run them and check that they fail.** `ctest --test-dir build/dev -R "python.live$" --output-on-failure`: FAIL.
- [ ] **Step 3: Implement `tracker.py`.** Run the test, fix the first differing field, and repeat until every battle passes. Keep the table above true.
- [ ] **Step 4: Run them and check that they pass.** PASS on every closure battle and both players.
- [ ] **Step 5: Commit, CI, review, PR, hand off.**

### Task 6: Game, client and CLI (PR 6, `chris/live-6-client`, needs the encoder fix PR #88)

**Files:**
- Create: `python/duoforge_live/game.py`, `client.py`, `__main__.py`
- Modify: `python/tests/test_live_unit.py`
- Install (owner OK): `C:/Dev/src/duoforge/.venv/Scripts/python.exe -m pip install websockets`

**Interfaces:**
- **Consumes:** `Tracker`, `options`, `Policy`, `teams`.
- **Produces:**
  - `game.Game(data, policy, own_text)`, with no IO:
    - `.feed(lines)`
    - `.phase -> 'wait' | 'sheets' | 'decide' | 'ended'`
    - `.foe_sets`
    - `.candidates() -> list[Candidate(text, probability)]`: ranked. The input is `features.encode(observation, domain)`; the policy applies `as_encoder`. Team tuples come from `rank_teams`. Pairs come from `rank_pairs`, with `pair_text` built from the options.
    - `.accepted(text)`
    - `.rqid`
  - `client.Bot(config, connect, login, clock)`, with `async run()`. The connection is `send(str)`/`recv() -> str` (async). `login(name, challstr, password) -> assertion` uses urllib against `https://play.pokemonshowdown.com/action.php`. Tests inject fakes for all three.
  - `client.FORMATS = {'gen9championsvgc2026regmc': 1, 'gen9championsvgc2026regmcbo3': 3}`, and the chat texts as constants.
  - `python -m duoforge_live --checkpoint PATH --name NAME [--team A|B|random] [--server URL] [--log-dir DIR] [--team-link URL] [--challenge USER [--challenge-format bo1|bo3]]`
    - The default server is `wss://sim3.psim.us/showdown/websocket`.
    - `--challenge` with an official host exits 2 with a message.
    - A `--name` without "bot" (any case) exits 2 with a message.
- **Flow** (spec sections 6 and 7):
  1. `|challstr|` leads to the login, then `|/trn NAME,0,ASSERTION`.
  2. On `|updatechallenges|`: a free bot sends `/utm <packed>` and then `/accept USER` for a format in `FORMATS`. Otherwise it sends `/reject` and the PM.
  3. In a battle room: greet once. On `|uhtml|otsrequest|` send `/acceptopenteamsheets`.
     - While waiting for the sheets, the bot gives up after 60 s (`clock`), or on the line "`<foe> rejected open team sheets.`", or when the foe's sheets do not match A or B. Then: the sheet message (+ team link), and `/forfeit`.
  4. On `decide`: send `/choose <text>|<rqid>`. On `|error|[Invalid choice]`, send the next candidate.
     - After 64 rejections, `[Unavailable choice]`, or any exception of tracker, options or policy (`ConversionError` caught by name): the internal-error message and `/forfeit`; the cause goes to the log.
  5. On `|win|` or `|tie`: "gg", close the log, `/leave`.
  6. **Bo3:** in the series room, answer the ready prompt with `/confirmready`. The series room's `|win|` or `|tie|` frees the bot.
  - **Logs:** one JSONL file per battle room. Records: `{"in": line}`, `{"decision": rqid, "top": [[text, p] x3], "sent": text}`, `{"rejected": text, "error": line}`. Never the password.
- [ ] **Step 1: Write the failing tests** in `test_live_unit.py`. A `FakeServer` replays server lines and records what the bot sends; a fake `Game` gives canned candidates where the tracker is not under test.

```python
def test_login_guest_and_registered(self):     # guest without the env var; with it, login() gets the password,
                                               # and neither stdout nor the log files contain it
def test_challenge_formats(self):              # bo1 and bo3: /utm then /accept; another format: /reject + exact PM
def test_busy_rejects(self):                   # during a battle and between Bo3 games: /reject + busy PM
def test_sheets_flow(self):                    # prompt -> /acceptopenteamsheets; team chosen only after both
                                               # |showteam|; rejection line / 60 s / foe team C: message + /forfeit
def test_invalid_choice_next_best(self):       # the next candidate with the same rqid; 64 rejections -> forfeit
def test_chat_between_request_and_update(self):  # no /choose before the battle update
def test_repeated_request_one_choice(self):
def test_unknown_line_forfeits_and_keeps_running(self):  # ConversionError -> internal error + /forfeit; the next
                                                          # challenge is accepted
def test_foe_forfeits_during_sheet_wait(self):  # |win| while waiting: no /forfeit, "gg", log closed, bot free
def test_bo3_series(self):                     # ready prompt -> /confirmready in the series room; game 2 played;
                                               # the series |win| frees the bot
def test_challenge_flag_refused_on_official_hosts(self):
def test_name_must_say_bot(self):              # "--name Chris" exits 2; "--name DuoForgeBot" is accepted
def test_game_uses_the_policy_encoding(self):  # an encoder-1 Policy ranks with the old present column
```

- [ ] **Step 2: Run them and check that they fail.** `ctest --test-dir build/dev -R "python.live_unit" --output-on-failure`: FAIL.
- [ ] **Step 3: Implement** `game.py`, `client.py` and `__main__.py`.
- [ ] **Step 4: Run them and check that they pass.** `ctest --test-dir build/dev -R "python.live" --output-on-failure`: PASS.
- [ ] **Step 5: Commit, CI, review, PR, hand off.**

### Task 7: By hand: local server, then the official server (results into 0016, a small docs PR)

- [ ] **Checkpoint.**
  - Copy `\\wsl.localhost\Ubuntu-24.04\home\chris\df-runs\night-2026-10-02\params-25000.npz` to `%LOCALAPPDATA%\duoforge-live\`.
  - Run `python -m duoforge_learn.checkpoint widen params-25000.npz params-25000-w607.npz`.
  - `policy.load` must accept the result and refuse the original.
- [ ] **Local server.**
  - Start the pinned server (`node pokemon-showdown start 8000`; check the pin's options for guest names without a login server).
  - Run two bots (`--server ws://localhost:8000/showdown/websocket`). One uses `--challenge OTHER`, in Bo1 and in Bo3.
  - Expected: both games end with "gg". The logs hold every decision, and no internal error occurs.
- [ ] **Official server.**
  - The owner sets `DUOFORGE_PS_PASSWORD` if he wants a registered name, starts the bot and challenges it.
  - Afterwards, report the result and the log path to the owner in German.
- [ ] Write the results into decision 0016 (status implemented, evidence). Small docs PR; hand off.

---

## Self-review (done when writing)

- **Spec coverage.** Each spec item has a task:
  - Section 5 (components): Tasks 2–6.
  - The checkpoint widening: Task 2.
  - Section 6 (flow) and section 7 (refusals): Task 6.
  - Section 8: test 1 is Tasks 4 and 5; test 2 is Task 4; test 3 is Task 2; test 4 is Task 2; test 5 is Task 3; test 6 is Task 6; test 7 is Task 7.
  - Section 9: Task 1 (runner, `ps_client.js`, 0016) and Task 6 (`websockets`).
- **Types.** `Option`, `Data`, `Tracker`, `Game` and `Policy` names match across tasks. The tracker reuses `options.slot_options` and `options.domain`.
- **Open by design.**
  - The tracker's field rules are decided by test 1 against DuoForge; Task 5 keeps its table true.
  - The login endpoint is checked live in Task 7.
