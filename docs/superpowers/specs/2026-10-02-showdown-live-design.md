# Showdown live adapter: design

Date: 2026-10-02. Status: design approved by the owner in chat. Self-review the same day: the formats, the open team sheets and the Bo3 flow were checked against the pin. This spec is for his review.

## 1. Goal

The bot of the night run (decision 0014, `docs/learning/2026-10-02-night`) plays live on the official Pokémon Showdown server against real players who challenge it. The owner's motive is curiosity, not a benchmark.

First version:

- **Challenges only**, in the two formats of `[Gen 9 Champions] VGC 2026 Reg M-C` at the pin (`config/formats.ts`):
  - Bo1, `gen9championsvgc2026regmc`. Open team sheets come only when both players accept (rule `Open Team Sheets`).
  - Bo3, `gen9championsvgc2026regmcbo3` ("(Bo3)"). Open team sheets always come (rule `Force Open Team Sheets`).
- **Both players use Team A or Team B** (`tests/reference/teams/`), the teams the bot was trained on, with open team sheets.

## 2. Owner decisions (2026-10-02)

- **Where:** the official server against real players. The owner states that Smogon allows bots.
- **Opponents:** challenges with Team A or B only. The ladder waits until the bot has trained on more teams.
- **Approach:** an own small Python client (approach 1 of 3). poke-env and a Node client were rejected.
- **Chat:** short messages in English (section 7).

## 3. Not in scope

- The ladder, arbitrary teams, Team C and pool teams.
- Changes to training.
- Search.
- Challenges sent by the bot on the official server.
- More than one battle at a time.

## 4. Information profile

DuoForge's observation (decision 0007) shows the foe's sheet as open: species, moves, item, ability, nature and gender. The foe's stat points and stats stay hidden.

In Champions formats, Showdown's Open Team Sheets show exactly that. `sim/battle.ts` of the pin keeps the nature for `champions` mods and drops EVs and IVs. When both players accept open team sheets, the observation can be filled exactly from what the bot receives, without assumptions.

## 5. Components: `python/duoforge_live/`

| File | Responsibility |
|---|---|
| `client.py` | Websocket connection. Login: as a guest name through `getassertion`, or as a registered name whose password the program reads from `DUOFORGE_PS_PASSWORD` at run time. Challenges: `/utm`, `/accept`, `/reject`. Room routing, including the Bo3 series room (`game-bestof3-…`) and `/confirmready` there; `/choose` with `rqid`. |
| `teams.py` | Packs Team A or B for `/utm`. Unpacks `\|showteam\|`. Matches a revealed sheet against A and B: the same six sets in any order, each with the same species, item, ability, moves (in any order), nature, gender and level. |
| `tracker.py` | One per battle and viewer. Reads the room's protocol lines and requests and builds the `OBSERVATION` record (`_layout.OBSERVATION`) that DuoForge would show this player. The foe's members and moves keep the order of its `\|showteam\|` line; the own team is the one the bot registered. A battle line it does not know raises. The tracker implements no battle rule: it only records what Showdown reports, and test 1 checks it against DuoForge's own observation. |
| `options.py` | From a request: the slot options in the rows of `FACTORED_DOMAIN`, the team tuples at team preview, and the text of an option or pair for `/choose`. The provisional pair mask allows every pair of valid options; Showdown judges the pair (section 6). |
| `policy.py` | The network's forward pass in NumPy, the same function as `duoforge_learn.model.apply`. It plays greedily: the best pair or team tuple, then the next best after a rejection. |
| `__main__.py` | `python -m duoforge_live --checkpoint PATH --name NAME [--team A\|B\|random] [--server URL] [--log-dir DIR] [--team-link URL] [--challenge USER]`. `--challenge` is for the local server only (section 8). |

**IDs.** The adapter maps species, move, item, ability, nature and gender to DuoForge ids with the converter's own loader: `parse_team` and `load_tables` of `tools/reference/trace_to_c.py`. There is no second id table.

**Checkpoint.** `duoforge_learn.checkpoint` gets `widen_594(params)` and the command `python -m duoforge_learn.checkpoint widen IN OUT`. They insert zero rows into `t1.w` for the 13 features the encoder added in #84:

- the Psychic Terrain column (index 12);
- three flags in each of the four positions (37–39, 61–63, 333–335, 357–359).

Under CLOSURE these inputs are always 0, so the widened network gives the same outputs. The bot uses update 25000 of the night run, the best in its ladder (833 Elo). The live tool loads checkpoints only with `obs_size=features.OBS_SIZE`, so a 594-feature file is refused.

**Encoding of the night checkpoint.**
- The night checkpoint was trained while the encoder set a member's `present` input from `species_id != 0`. Rillaboom of Team A has forme id 0, so its `present` was always 0.
- The bot plays this checkpoint with the encoding it was trained on, through the fix PR's `features.as_encoder(obs_part, observations, version)` (#88): version 1 rebuilds the old `present` column, version 2 is the fixed encoding.
- A checkpoint's config says its encoding with one integer key, `"encoder"`: 1 before the fix, 2 after (agreed with the main session and Learner v2). A missing key means 1, because no earlier checkpoint has it. The widened file records `"encoder": 1`.
- New checkpoints use the fixed encoding.

## 6. Data flow of one battle

1. Accept a challenge in one of the two formats after `/utm` with the chosen team. A challenge in any other format is rejected.
2. **Open team sheets.**
   - Bo1: the server asks both players (`|uhtml|otsrequest|`), and the bot sends `/acceptopenteamsheets`. Bo3: the sheets come without asking.
   - The bot chooses its team only after the `|showteam|` lines of both sides are in, because the team head sees the foe's sheet.
   - The sheets count as denied when the foe's line "… rejected open team sheets." arrives, or when they have not come 60 seconds after the team preview request. The VGC timer gives 90 seconds for team preview.
3. Match the foe's sheet against A and B (section 5, `teams.py`). If it does not match, forfeit (section 7).
4. **Team preview:** the team head's best tuple becomes `/choose team abcd|rqid`.
5. **Each request:**
   1. The tracker gives the observation and `options.py` the options.
   2. `features.encode` turns them into network input, and `policy.py` picks the best pair.
   3. Send `/choose` with that pair.
   4. On `|error|[Invalid choice]`, exclude that pair and send the next best. After 64 rejections at one decision point, across its original and updated requests, the bot forfeits as an internal error (section 7). The counter resets only on a new non-update request.
   5. `|error|[Unavailable choice]` comes with a changed request, because of information the player did not have: a switch of a hidden-trapped last active (Shadow Tag, Arena Trap, Magnet Pull; `sim/side.ts:527-534, 984-1000`) or a move disabled by the foe's Imprison (`data/moves.ts:9505-9509`, `sim/side.ts:742-761`). Showdown then sends the move request again under a new rqid (`update: true`) with what the refusal revealed. The tracker takes it as a new request epoch of the same decision point, and the bot chooses again from it. This is a preparatory client/tracker change: the currently registered Teams A/B cannot exercise these refusals, but the boundary handles them explicitly. A third unavailable choice at one decision point is an internal error (section 7). Changed 2026-10-03: until then every unavailable choice was an internal error, which forfeited the first switch attempt against a hidden Shadow Tag.
6. **End** of a game (`|win|`, `|tie|` in the battle room): send "gg" and write the log. The bot carries nothing from one game to the next.
7. **Bo3** (checked against the pin's `server/room-battle-bestof.ts`): the series has its own room, `game-bestof3-gen9championsvgc2026regmcbo3-N`, and every game is a battle room of its own that runs through steps 2–6. Between games the series room asks "Are you ready for game N", and the bot answers with `/confirmready` there. The series room's own `|win|` or `|tie|` ends the series. The team from the challenge stays the same in every game.

## 7. Errors and etiquette

Every refusal is explicit. The bot never lets the timer run out on a player.

| Case | Action and message |
|---|---|
| Challenge in another format | `/reject`; PM: "Sorry, I only play [Gen 9 Champions] VGC 2026 Reg M-C, Bo1 or Bo3." |
| Already in a battle | `/reject`; PM: "Sorry, I'm in a battle right now. Please challenge me again in a few minutes." |
| Open team sheets denied or not given within 60 seconds, or the foe's team is not Team A or B | Chat: "I'm a research bot and only play DuoForge Team A or B with open team sheets, so I'm forfeiting this game." Then `/forfeit`. With `--team-link URL`, the link is added. |
| An unknown battle line, or an error in tracker, options or policy | Chat: "Internal error on my side, sorry. Forfeiting." Then `/forfeit`; the cause goes to the log. |
| Start / end | "Hi! DuoForge bot here, good luck!" / "gg" |

**Name and logs.**
- The name says that this is a bot.
- Each battle writes a JSONL file to `--log-dir`. The default is outside the repository, under `%LOCALAPPDATA%\duoforge-live`. The file holds every line received, every decision (the chosen pair and the three best with their probabilities) and every rejection.

## 8. Tests

1. **The tracker is exact.** This is the CMake test `duoforge.python.live`. It needs Node and `DUOFORGE_PS_REFERENCE_DIR` and is skipped without them. For every committed closure battle (all of them, not only the real-team ones, because live games can reach every closure mechanic; the Team C battles are out of scope):
   - **Client stream.** A new Node helper, `tools/reference/ps_client.js`, plays the spec's battle in the pinned Showdown. It writes each player's client stream: the protocol lines with `|split|` resolved for that player, and `|request|` with its JSON. This is what a websocket client receives. At team preview it writes `>show-openteamsheets` to the battle, as the server does when both players accept, so the stream holds both `|showteam|` lines; this draws no random numbers.
   - **What DuoForge shows.** `duoforge_diff_runner --dump-views FILE` replays the same committed battle as it does today. Per step and viewer it writes DuoForge's observation (736 bytes) and factored domain (652 bytes).
   - **Comparison.** At every request, the tracker's observation must equal DuoForge's byte for byte. Its input is the client stream, with the foe's sheet from the `|showteam|` line, and the player's own team from the spec, as a live bot knows the team it registered. The options must equal DuoForge's slot options as a set, and every pair DuoForge allows must be in the provisional mask.
2. **Choice text.** Every option, turned into Showdown text and back through `trace_to_c.convert_choice`, gives the same DuoForge command. The same holds for team tuples.
3. **Checkpoint widening.**
   - On real CLOSURE observations, the 13 inserted columns are 0.
   - The widened network on 607 features matches the original on the 594-feature layout, within float tolerance.
   - The greedy actions are the same.
4. **NumPy against JAX.** `policy.py` equals `model.apply` on random parameters and inputs. This runs in `test_learn`, in the JAX job.
5. **Teams.**
   - Packing A and B equals the pinned Showdown's `Teams.pack`, through the Node helper.
   - Unpacking a `|showteam|` line and packing it again gives the same line.
   - The match accepts A and B, also with members or moves reordered, and refuses a changed species, move, item, ability, nature or gender.
6. **Client protocol without network.** A fake websocket replays server lines: the login, a challenge in each right format, one in a wrong format, one while busy, the open-team-sheet prompt, sheets denied and sheets that never come, an invalid choice followed by the next best, and a Bo3 series with the ready prompt between games.
7. **By hand, not in CI.**
   - The pinned server runs locally, and two bot instances play Bo1 and Bo3 against each other. The test-only flag `--challenge USER` is refused for the official server.
   - Then a first game on the official server: the owner challenges the bot.

## 9. Dependencies and coordination

- **New dependency:** `websockets` in `.venv`.
- **`tools/difftest/diff_runner.c`:** gets `--dump-views`, an additive flag. Its home is the expansion track; the lead will be told before the change.
- **`tools/reference/ps_client.js`:** new and additive.
- **Decision note:** 0016, because 0015 belongs to the expansion (POOL).
- **Library version:** none needed. Nothing in the C API changes.

## 10. Risks and open points

- **The live server may differ from the pin** in protocol lines or mechanics.
  - An unknown battle line ends the game with a forfeit (section 7).
  - Different mechanics only change how well the bot plays, never what it reports.
- **Showdown's rules for bots:** the owner's statement applies. The bot only accepts challenges, plays one battle at a time and never ladders.
