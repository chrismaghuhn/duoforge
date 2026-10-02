# Showdown live adapter: design

Date: 2026-10-02. Status: design approved by the owner in chat; this spec is for his review.

## 1. Goal

The bot of the night run (decision 0014, `docs/learning/2026-10-02-night`) plays live on the official Pokémon Showdown server against real players who challenge it. The owner's motive is curiosity, not a benchmark.

First version:

- **Challenges only**, in `[Gen 9 Champions] VGC 2026 Reg M-C` (`gen9championsvgc2026regmc`), as Bo1 and as Bo3.
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
| `client.py` | Websocket connection. Login: as a guest name through `getassertion`, or as a registered name whose password the program reads from `DUOFORGE_PS_PASSWORD` at run time. Challenges: `/utm`, `/accept`, `/reject`. Room routing; `/choose` with `rqid`. |
| `teams.py` | Packs Team A or B for `/utm`. Unpacks `\|showteam\|`. Matches a revealed sheet exactly against A and B: species, item, ability, moves, nature, gender and level. |
| `tracker.py` | One per battle and viewer. Reads the room's protocol lines and requests and builds the `OBSERVATION` record (`_layout.OBSERVATION`) that DuoForge would show this player. A battle line it does not know raises. |
| `options.py` | From a request: the slot options in the rows of `FACTORED_DOMAIN`, the team tuples at team preview, and the text of an option or pair for `/choose`. The provisional pair mask allows every pair of valid options; Showdown judges the pair (section 6). |
| `policy.py` | The network's forward pass in NumPy, the same function as `duoforge_learn.model.apply`. It plays greedily: the best pair or team tuple, then the next best after a rejection. |
| `__main__.py` | `python -m duoforge_live --checkpoint PATH --name NAME [--team A\|B\|random] [--server URL] [--log-dir DIR] [--team-link URL]` |

**IDs.** The adapter maps species, move, item, ability, nature and gender to DuoForge ids with the converter's own loader: `parse_team` and `load_tables` of `tools/reference/trace_to_c.py`. There is no second id table.

**Checkpoint.** `duoforge_learn.checkpoint` gets `widen_594(params)` and the command `python -m duoforge_learn.checkpoint widen IN OUT`. They insert zero rows into `t1.w` for the 13 features the encoder added in #84:

- the Psychic Terrain column (index 12);
- three flags in each of the four positions (37–39, 61–63, 333–335, 357–359).

Under CLOSURE these inputs are always 0, so the widened network gives the same outputs. The bot uses update 25000 of the night run, the best in its ladder (833 Elo). The live tool loads checkpoints only with `obs_size=features.OBS_SIZE`, so a 594-feature file is refused.

## 6. Data flow of one battle

1. Accept the challenge after `/utm` with the chosen team. A challenge in another format is rejected.
2. When asked, send `/acceptopenteamsheets`. Wait for `|showteam|` of both sides.
3. Match the foe's sheet against A and B exactly. If they do not match, forfeit (section 7).
4. **Team preview:** the team head's best tuple becomes `/choose team abcd|rqid`.
5. **Each request:**
   1. The tracker gives the observation and `options.py` the options.
   2. `features.encode` turns them into network input, and `policy.py` picks the best pair.
   3. Send `/choose` with that pair.
   4. On `|error|[Invalid choice]`, exclude that pair and send the next best. After 64 rejections the bot forfeits.
6. **End** (`|win|`, `|tie|`): send "gg" and write the log. In Bo3, every game is its own battle room and runs through steps 2–6 again. The bot carries nothing from one game to the next.

## 7. Errors and etiquette

Every refusal is explicit. The bot never lets the timer run out on a player.

| Case | Action and message |
|---|---|
| Challenge in another format | `/reject`; PM: "Sorry, I only play [Gen 9 Champions] VGC 2026 Reg M-C." |
| Already in a battle | `/reject`; PM: "Sorry, I'm in a battle right now. Please challenge me again in a few minutes." |
| Open team sheets denied, or the foe's team is not Team A or B | Chat: "I'm a research bot and only play DuoForge Team A or B with open team sheets, so I'm forfeiting this game." Then `/forfeit`. With `--team-link URL`, the link is added. |
| An unknown battle line, or an error in tracker, options or policy | Chat: "Internal error on my side, sorry. Forfeiting." Then `/forfeit`; the cause goes to the log. |
| Start / end | "Hi! DuoForge bot here, good luck!" / "gg" |

**Name and logs.**
- The name says that this is a bot.
- Each battle writes a JSONL file to `--log-dir`. The default is outside the repository, under `%LOCALAPPDATA%\duoforge-live`. The file holds every line received, every decision (the chosen pair and the three best with their probabilities) and every rejection.

## 8. Tests

1. **The tracker is exact.** This is the CMake test `duoforge.python.live`. It needs Node and `DUOFORGE_PS_REFERENCE_DIR` and is skipped without them. For every committed reference battle with Teams A and B:
   - **Client stream.** A new Node helper, `tools/reference/ps_client.js`, plays the spec's battle in the pinned Showdown. It writes each player's client stream: the protocol lines with `|split|` resolved for that player, and `|request|` with its JSON. This is what a websocket client receives.
   - **What DuoForge shows.** `duoforge_diff_runner --dump-views FILE` replays the same committed battle as it does today. Per step and viewer it writes DuoForge's observation (736 bytes) and factored domain (652 bytes).
   - **Comparison.** At every request, the tracker's observation must equal DuoForge's byte for byte. Its input is the client stream plus the foe's sheet, taken from the spec, because the recorded battles have no `|showteam|` lines. The options must equal DuoForge's slot options as a set, and every pair DuoForge allows must be in the provisional mask.
2. **Choice text.** Every option, turned into Showdown text and back through `trace_to_c.convert_choice`, gives the same DuoForge command. The same holds for team tuples.
3. **Checkpoint widening.**
   - On real CLOSURE observations, the 13 inserted columns are 0.
   - The widened network on 607 features matches the original on the 594-feature layout, within float tolerance.
   - The greedy actions are the same.
4. **NumPy against JAX.** `policy.py` equals `model.apply` on random parameters and inputs. This runs in `test_learn`, in the JAX job.
5. **Teams.**
   - Packing A and B equals the pinned Showdown's `Teams.pack`, through the Node helper.
   - Unpacking a `|showteam|` line and packing it again gives the same line.
   - The exact match accepts A and B and refuses a changed move, item or nature.
6. **Client protocol without network.** A fake websocket replays server lines: the login, a challenge in the right format, one in the wrong format, one while busy, the open-team-sheet prompt, and an invalid choice followed by the next best.
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
- **Bo3 room protocol:** verified against the pin's `server/room-battle-bestof.ts` when it is built.
- **Showdown's rules for bots:** the owner's statement applies. The bot only accepts challenges, plays one battle at a time and never ladders.
