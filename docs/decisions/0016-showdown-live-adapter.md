# 0016 — Showdown live adapter

Status: owner decisions 2026-10-02 (design in chat, the written spec and the plan: "ja"). Design: `docs/superpowers/specs/2026-10-02-showdown-live-design.md`. Plan: `docs/superpowers/plans/2026-10-02-showdown-live.md`. Builds on decisions 0007 (what a player sees), 0013 (Python adapter) and 0014 (learner). **Built** (#93, #97, #98, #99, #100, #103) and played on the official server on 2026-10-02 (section 6).

## 1. Decisions

- **What:** the bot of the night run (decision 0014, update 25000) plays live on the official Pokémon Showdown server. The motive is curiosity, not a benchmark.
- **Opponents:** challenges only, in `gen9championsvgc2026regmc` (Bo1, open team sheets on request) and `gen9championsvgc2026regmcbo3` (Bo3, forced open team sheets). Both players use Team A or B of decision 0004. The ladder waits for training on more teams.
- **How:** an own small Python client, `python/duoforge_live` (not poke-env, not a Node client). One battle or Bo3 series at a time; the bot never sends challenges on the official server and never ladders. The owner states that Smogon allows bots.
- **Etiquette:** short English chat messages; every refusal is explicit (a PM, or a message and a forfeit); the bot never lets the timer run out on a player. The name says that it is a bot. The password comes only from `DUOFORGE_PS_PASSWORD`.

## 2. Why the observation can be exact

DuoForge's observation shows the foe's open sheet (species, moves, item, ability, nature, gender) and hides its stat points and stats. In Champions formats, Showdown's open team sheets show exactly that: the pin's `showOpenTeamSheets` keeps the nature for `champions` mods and drops EVs and IVs. So the adapter can rebuild the observation from what the bot receives, without assumptions. The tracker implements no battle rule: it folds the protocol lines (through the converter's own parser, `trace_to_c.step_events`) into the `OBSERVATION` record, and a test proves it equal to DuoForge's observation, byte for byte, at every request of every committed closure battle.

## 3. The checkpoint

- The night checkpoint takes 594 features; the encoder makes 607 since #84. `duoforge_learn.checkpoint widen` inserts zero rows for the 13 new inputs (Psychic Terrain, three position flags per position), which are 0 under CLOSURE, so the network's outputs do not change.
- It was trained while the encoder read a member's `present` from `species_id != 0`, and Rillaboom (Team A) has forme id 0. The bot plays it with that encoding, through the encoder fix's `features.as_encoder(obs_part, observations, version)` (#88), which rebuilds the old `present` column for version 1. A checkpoint's config says its encoding with the integer key `"encoder"`: 1 before the fix (also when the key is missing), 2 after; the widened file records 1. Agreed with the main session and the Learner v2 session.

## 4. Evidence

- `duoforge.reference.client_streams`: `tools/reference/ps_client.js` replays every closure battle in the pinned Showdown from its trace's choices and writes each player's client stream; every step's lines equal the trace.
- `duoforge.reference.dump_views`: `duoforge_diff_runner --dump-views` writes DuoForge's observation and factored domain of both players at every state; checked against the public API.
- `duoforge.python.live`: the tracker's observations and the options against these views; the choice texts back through the converter; packing Teams A and B equal to Showdown's.
- `duoforge.python.live_unit` and `duoforge.python.live_client`: teams, and the client protocol with a fake server (challenges, refusals, open team sheets, invalid choices, Bo3, errors).
- `duoforge.python.learn_numpy` and `duoforge.python.learn`: the widening, and the NumPy forward pass against JAX.
- By hand: two bots on a local pinned server (Bo1, Bo3), then a first game on the official server against the owner.

## 5. Coordination

- `tools/difftest/diff_runner.c` belongs to the expansion track; `--dump-views` was agreed with its lead (additive; without the flag nothing changes).
- `duoforge_learn/checkpoint.py` gets only `widen_594` and the `widen` command (agreed with Learner v2).
- New dependency: `websockets` in `.venv` (owner OK), imported only for the live connection.
- No library change, no version bump.

## 6. Results (2026-10-02)

- **Local server.** Two bots on a copy of the pinned server, Team A against Team B with the widened night checkpoint and real guest logins, played a Bo1 and a Bo3 (three games) to the end. No forfeit, no internal error.
- **Official server.** The owner (christest1111, Team A) challenged DuoForgeBot (registered name, password from the environment) in a Bo1 with open team sheets. The bot accepted, matched the sheet as Team A, chose its team, and played all 9 turns: 12 decisions, no internal error. The owner won.
- **How the bot played (from the log).** Behind, it stalled with high confidence:
  - From turn 4 on, Gholdengo (31, 42, then 12 of 179 HP) chose Protect every turn: "Swords Dance / Protect" at 0.93, 0.88, 0.91 and 0.47.
  - Ceruledge chose Swords Dance in every one of those turns.
  - On turn 8, alone with 35 of 181 HP, Ceruledge chose Protect at 0.73.

  The likely cause is in the training, not in the adapter. Self-play cut off a battle after 500 steps and scored the cut as a tie. Delaying was therefore worth more than a likely loss (-1). Learner v2 plans to score cut-offs by Showdown's tiebreak (`Battle.tiebreak`, sim/battle.ts:1467).
- **Rejected pairs.** Showdown refused "pass, pass" twice at a replacement ("You need to switch in a Pokémon"). The bot then sent the next best pair. This is the provisional pair mask working as designed (spec section 5). Every rejected choice costs one round trip.
- **Found while playing, fixed in #103.**
  - At the pin, a challenge reaches the bot as a PM "/challenge FORMAT|...", not as |updatechallenges|.
  - The login server refuses Python's default User-Agent (403), so the bot names itself in the header.
  - Two bots on one machine need one log per room and bot.
- **Chat.** The official server did not let the account speak ("Due to spam from your internet provider, you can't speak except to staff"). The greeting, gg and the refusal texts did not appear. The server says an account with more history may chat. The game itself was not affected.
- **Open.**
  - The bot does not reconnect when its connection drops. A reconnect's replay fails explicitly (forfeit) instead of folding the log twice.
  - The pair mask could follow DuoForge's forced-switch rule to avoid the refused passes. The spec chose to let Showdown judge.

## 7. PKMN Arena mode (owner, 2026-10-12)

The owner approved playing on PKMN Arena (https://vgc.ellep.dev, spec https://vgc.ellep.dev/llms.txt), a public ladder for VGC bots that speaks the Showdown protocol. The owner registered the bot **Tian-Suan** for open team sheets, `gen9championsvgc2026regmcots`. The mode is `python/duoforge_live/pkmn_arena.py`, started with `--server arena`. The Showdown modes above stay as they are, including the refusal of `--challenge` on the official server.

**Run (WSL, by the owner).** The bot needs JAX (`~/df-learn`), a Linux build of the library from the same commit as the checkout, and `websockets`.

```
set -a; source ~/.duoforge-arena.env; set +a      # ARENA_BOT_NAME=Tian-Suan, ARENA_BOT_TOKEN=pka_... (mode 600)
cd /mnt/c/Dev/src/duoforge
export DUOFORGE_LIBRARY=<Linux build of this commit>/libduoforge_shared.so PYTHONPATH=python JAX_PLATFORMS=cpu
BC6=/mnt/c/Dev/datasets/m11-bc-runs/bc6-M/bc.npz

# recommended (owner, 2026-10-12): the honest search, BC6 as the network and as the foe model (M7: F 0.892, M 0.862)
~/df-learn/bin/python -m duoforge_live --server arena --format gen9championsvgc2026regmcots \
    --checkpoint $BC6 --search honest --foe-net $BC6 --team <team paste> --log-dir ~/duoforge-arena-logs

# raw play with BC6
~/df-learn/bin/python -m duoforge_live --server arena --format gen9championsvgc2026regmcots \
    --checkpoint $BC6 --team <team paste> --log-dir ~/duoforge-arena-logs
```

- `--foe-net P` gives the search's worlds the foe's policy from P (Honest's `foe_net`, M7). It needs `--search honest`. Without it, the search models the foe with its own network. The default of the Showdown mode is unchanged.
- `--team-pool FILE` holds the random ladder's published teams (see below).
- `--foe-net-sha256 HEX` pins the foe network's file: another digest is refused before loading.
- **Tables across data versions** (owner via HauptSession, 2026-10-12; both modes, the network and the foe network). The battle is always played on the current library's tables. A checkpoint with the same data fingerprint starts as before. A checkpoint with another fingerprint starts only when `checkpoint.check_ids` holds against those tables: every id its network embeds still names the same row, and the tables only grew at the end. Otherwise it is refused, as before. `checkpoint.check_data` is the one helper for this check. The run log names both fingerprints and the result (`same tables` or `carried over`) for the network and the foe network.
- On main, BC6 (fingerprint `064f44c4`) and params-49333 (`887c0e6c`) differ from the library's `e3f308c9`, and both carry over. Before this change, the fingerprint equality refused both in the live start, including the Showdown mode with params-49333.

**Name and token.**
- The name comes only from `ARENA_BOT_NAME` and the token only from `ARENA_BOT_TOKEN`. No option takes either.
- The mode refuses to start when the command line contains the token or anything starting with `pka_`. It checks this before argument parsing, so the token is never echoed.
- The token is read from the environment at each login and sent only in `|/trn NAME,0,TOKEN`. The bot never stores it, and every printed or logged text replaces it with `[token]`.
- The host is fixed in code (`pkmn_arena.URL`). The Showdown mode refuses that host.

**Play.**
- The team (`--team`, a paste with genders) goes with `/utm` after every login, so after every reconnect too. A `|popup|` that rejects the team stops the bot with the server's reasons.
- The server puts the bot in battles; it plays every one, one at a time, with the request's rqid on every `/choose`. A `wait` request gets no answer.
- After `[Invalid choice]`, the bot sends the next-best candidate, up to 16 times per decision point.
- The bot never forfeits and never chats.

**Open team sheets.** At team preview, `|showteam|` reveals both sides' species, items, abilities, moves and natures, but not their stat points. The tracker folds these lines as it does on Showdown (section 2): the foe's members in the observation carry the revealed sets, and their stat points and stats stay unknown, as in DuoForge's own view. The honest search gets the same public record.

**Closed team sheets** (decision 0081, #385 step 4). The CTS format is played over 16 particles, each a drawn foe team folded by the tracker above; the search builds world `w` from particle `w`'s record. Until then it fell back with the reason `closed_team_sheets`.

**Fallback.** When the engine cannot represent a battle, the rest of that battle is answered with `/choose default`. The server's simulator then picks; Python picks no move. Each such battle and each defaulted decision is counted by its reason in the run log. The reasons are:

| reason | cause |
|---|---|
| `no_open_sheets` | the sheets did not arrive within 20 s of the team preview request |
| `stop:<kind>`, `error:<type>` | a tracker Stop, or an exception of the tracker, the options or the policy; a particle tracker's stop by its name (`stop:cts:redraw-cap`, ...) |
| `rejections` | more than 16 refused choices at one decision point |
| `unavailable` | more than two unavailable choices at one decision point |
| `deadline`, `policy_busy` | the decision took more than 20 s; or a late decision still runs (never two at once) |
| `reconnect` | after a reconnect, the replayed log differs from the lines already folded |
| `random_team_unknown`, `random_team_ambiguous` | a random-team battle whose team is not exactly one `--team-pool` team |
| `format` | a battle of another format |
| `no_team` | a team-ladder battle without `--team` |
| `request` | a request that is no JSON object (answered with a default without an rqid) |
| `forfeit` | a case where the Showdown mode would forfeit: the arena bot never forfeits |

With one battle at a time, as the arena runs them, every request gets an answer well within the arena timer (45 s, 90 s at team preview). A dropped connection is no fallback: the bot reconnects, and the server sends the open request again.

**Reconnect.**
- A dropped connection reconnects after 1, 2, 5, 10, then every 30 s; a successful login resets the backoff.
- Close code 4001 (another login as the bot) stops the bot, so that two instances do not take turns. A refused login (`|nametaken|`) also stops it.
- The server replays an open battle's log, then sends the open request again. When the replay starts with every battle line already folded, the new lines are folded, and the open request is answered again with the same choice. A `|sentchoice|` line, beside the log or the request, means the server already holds the choice: the bot sends nothing, and the line is never folded.
- A connection must stay up for 60 s after its login before the backoff starts again, so a server that closes at once is not hit every second.

**Random-team ladder** (`…random`). The team comes from the first request, which lacks the natures and stat points that the tracker's own sheet needs. The policy plays such a battle only when exactly one `--team-pool` team matches the request's species, items, abilities and moves. Otherwise the battle falls back.

**Logs.**
- One JSONL file per battle (it holds match and user ids) and an aggregate run log, `arena-run-<UTC start>.json`, which holds counts only.
- Both stay private. The mode refuses a log directory inside the repository.
- Reports quote aggregate counts only.

**Evidence.**
- `duoforge.python.pkmn_arena`: a fake websocket only. It covers login, team and token handling, an OTS battle that folds the sheets, every fallback, retries, the deadline, reconnects and the random ladder.
- `duoforge.python.pkmn_arena_net` (JAX): a tiny synthetic checkpoint in the BC file format (model v2, encoder 6) loads as its own network. It plays the OTS fixture raw, with the honest search, and with the honest search and the same file as `foe_net`, with no fallback.
- Nothing connects to the arena in tests.
