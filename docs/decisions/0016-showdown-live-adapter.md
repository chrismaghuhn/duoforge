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
