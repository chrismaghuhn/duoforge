# Implementation roadmap

Every milestone is a separate authorization boundary. A milestone may require multiple small tasks. Prefer one implemented contract with tests per task, not a single prompt asking for an entire engine.

**Status 2026-10-02:**
- **M0 to M7 are done.**
  - The closure matchups are certified (M5, `docs/certification/closure-v1/`).
  - The batch runtime is measured (M6, `docs/benchmarks/`).
  - Team C (decision 0009) is built and passes its gate, but is not certified.
- **CI:** the local CI (`tools/ci/local_ci.sh`, eleven jobs on Windows and WSL) is the merge gate. GitHub Actions runs nightly.
- **Next:** M8 to M12 below. M10 is built.

## M0 — Workspace, build and development foundation

Implement C17 CMake setup, a tiny core library, a smoke-test executable, CTest registration, documented local builds and initial CI configuration. Establish warnings, bounded execution and a minimal public version/status surface. Add source/coverage manifest scaffolding with explicit UNPINNED/UNSUPPORTED status.

Exit: actual available-platform Debug and Release builds and smoke tests pass; project structure and task boundaries are documented. Unavailable platforms are NOT_RUN. No combat, RNG, Python package or fake passing battle stubs.

Use `tasks/M0_BOOTSTRAP.md`.

## M1 — Deterministic primitives and owned state

Pin and implement the RNG choice and known-answer vectors; explicit arithmetic helpers; roster/position identities; state initialization and invariants; basic canonical codec/digest support and owned state cloning. Establish context compatibility and checked capacities. Add only fields justified by the initial requests/mechanics rather than an imagined complete Pokédex.

Exit: RNG, codec, invariant and clone tests; malformed-input atomicity; clear schema/semantics identifiers for artifacts that actually exist. State snapshots are foundation evidence, not proof that unimplemented future mechanics restore correctly.

## M2 — Requests, joint commands and information boundary

Implement team-selection/request types, complete joint-command validation/enumeration, request epochs, a perspective-safe observation prototype and simultaneous-choice collection semantics. Use explicitly synthetic request fixtures where combat is not yet available. Test constraints for reserve conflicts and side-wide resources.

Exit: exhaustive small-fixture domain tests, information-equivalence tests, stable enumeration and zero gameplay RNG consumption by queries. There must be no fake assertion that the engine already plays correct Pokémon.

Before M3, select the two concrete teams, operational reference commit, rules/information profile and conservative mechanics inventory. This is a small focused selection/review task, not a global census system.

**Owner decision (2026-09-30):** M3 and M4 are executed as one continuous build with no backlog, in the dependency order of `docs/research/mechanics-inventory.md` section 5. The descriptions of M3 and M4 below remain the content; `tasks/M3_M4_COMBAT_CLOSURE.md` is the task statement. M5 and later stay separate authorization boundaries.

## M3 — First combat vertical slice

Implement the selected foundational damage/stat/PP primitives, normal move execution, the necessary immediate effects, switching, faint processing and turn progression. Include implicit behaviors reachable in the slice such as PP exhaustion. Implement the scheduler/continuation structure even before every mid-turn effect exists.

Exit: pinned deterministic reference fixtures, reproducible native traces and replay across ordinary turns. Development fixtures may play out end-to-end, but the full selected matchup remains uncertified if dependencies are missing.

Do not represent an ignored ability, simplified rounding or absent item behavior as a valid competitive game.

## M4 — Doubles mechanics closure

Implement only the selected teams' required interactions: targeting/spread logic, protection, shared transformations when applicable, redirection, priority/dynamic speed ordering, pivot/replacement pauses, status/weather/terrain, items, abilities and ordered residuals as required by the actual inventory.

Split this milestone into dependency-ordered mechanic tasks. Every task includes negative cases, interaction tests and pause/replay tests where applicable. Record source uncertainty rather than inventing behavior.

Exit: every dependency of the declared slice has implementation and test evidence; continuation/restoration and model-visible information behavior pass; no silent unsupported paths. A simplified profile must stay explicitly labeled.

## M5 — First fixed-matchup certification

**Status 2026-10-01:** done for the closure matchups (decision 0010); report `docs/certification/closure-v1/README.md`.

Freeze exact team specifications, rules and information profiles, source pins and the evidence manifest. Run deterministic reference scenarios, controlled-RNG conformance tests, bounded randomized native play, replay verification and failure minimization.

Certification is scoped engineering evidence, not a mathematical proof of every reachable state. Record residual known limitations. Exclude an unsupported setup or change the named profile; do not weaken real rules invisibly.

Exit: a reproducible small certified matchup dataset and test report, with no unresolved known mismatch in the certified scope. Anything requiring unimplemented semantics remains rejected.

## M6 — Batch runtime and measurement

**Status 2026-10-01:** done for the synchronous runtime (decision 0012); report `docs/benchmarks/2026-10-01-batch-scaling/README.md`.

Add resident environment arrays and a worker pool outside the rule core. Reuse per-worker scratch; keep RNG per environment; support heterogeneous request kinds and completed environments. Define deterministic reset-seed derivation and atomic per-environment outcomes.

Start with configurable 1, 2, 4, 8 and larger environment counts as hardware allows, not a hard-coded promise of thousands. A thread is not an environment. Compare worker schedules using identical per-environment commands and seeds.

Exit: single/batch semantic equivalence, reproducibility independent of scheduling, no race findings on tested paths, bounded memory and a reproducible Release benchmark report. Optimization cannot reduce mechanics, candidate completeness or information guarantees.

## M7 — Python ML adapter and trusted trajectories

Add a thin C ABI binding, packed observation and candidate batches, random/scripted baseline drivers and a trajectory exporter. Store policy/opponent IDs, roles, RNG provenance, schema versions, request identifiers, selected canonical commands and outcome/truncation semantics. Keep provenance separated from features.

Exit: native-versus-binding equivalence, trajectory-to-replay checks, no hidden-information features and a small bounded generation example. A trained model is not needed to pass this milestone.

Status: done 2026-10-01 (decision 0013 section 8). The Python package `python/duoforge` drives the batch runtime over ctypes and NumPy; the Python loop equals the native mode byte for byte, recipes replay to features, and the encoder reads only the viewer's observation.

An initial candidate-scoring learner may follow in a separate task. Selecting PPO, recurrent architectures, search or leagues is not part of the engine gate.

That learner followed as decision 0014: PPO self-play over the factored domain. Its trial and night runs are in `docs/learning/`. The night run plateaued after about an hour on the two teams, which is what M8 and M9 address.

## M8 — Team pool expansion, complete teams first

Extend the tables and mechanics beyond the closure and Team C:
- **Data kind:** POOL (decision 0015).
- **How:** in families, each one C rule with parameters generated into the tables.
- **Order:** complete real teams. The owner decided on 2026-10-02 that the cheapest complete Reg M-C tournament team comes first, based on the pastes of the VGCPastes repository.

Every new mechanic is checked against the pinned reference, through recorded battles and the differential loop (A1 to A6). The engine refuses anything it does not support.

Exit:
- 6 to 12 complete real teams play under a frozen POOL profile.
- Each team has recorded reference battles and a clean differential run.
- Nothing is unsupported in silence.

## M9 — Learner v2 and a multi-team training run

Teach the learner many teams:
- team setups from Showdown pastes;
- self-play over all pairings of N teams;
- an opponent pool of past checkpoints against cycling;
- an entropy schedule;
- runs that resume from a checkpoint;
- evaluation and a ladder per team.

Then train on the M8 teams, if useful on a rented GPU machine.

Exit:
- A reproducible training report like `docs/learning/2026-10-02-night`: configuration, measured rates, the ladder across teams and the evaluation per team.
- Performance claims carry measurements.

## M10 — Live play on Pokémon Showdown

A client, `python/duoforge_live`, lets a trained bot accept challenges on the official server, in Reg M-C with open team sheets. The design is in `docs/superpowers/specs/2026-10-02-showdown-live-design.md`.
- It builds exactly the observation DuoForge would show the player.
- It refuses explicitly any team outside its training.
- First version: Teams A and B, challenges only. Ladder play waits for M9.

Exit:
- The tracker equals DuoForge's own observation byte for byte on recorded battles.
- The client protocol is tested without a network.
- A first logged game on the official server.

Status: built on 2026-10-02 (#93, #97 to #100, #103) and played on the official server.
- **The first game:** The bot lost, and at the end it chose Protect turn after turn. The night run had scored a battle cut off after 500 steps as a tie, so stalling was worth more to the policy than a likely loss.
- **The fix:** Learner v2 scores cut-offs with Showdown's tiebreak (`duoforge_battle_tiebreak`, #109).
- **Report:** decision 0016.

## M11 — Learning from human replays

Use public Showdown replays of the format as the starting point for the learner:
- **Source:** about 713,000 "Champions VGC 2026" games in the HolidayOugi dataset on Hugging Face.
- **Data:** each game becomes, per player, the observation and the action of every decision. The M10 tracker reads the protocol in a spectator mode, and DuoForge's data query API supplies the ids.
- **Training:** behavior cloning, and offline RL where it helps, give the policy and the value a human prior. M9's self-play then improves on it.

Constraints:
- **Teams:** Only teams the tables hold count.
- **Hidden information:** Open team sheets give a player's full sheet. Own exact HP and stat points are estimated, and the estimate is documented.
- **No rules in Python:** the option sets are judged by Showdown or the engine.
- **Data stays local:** the data set states no license, so it is not redistributed.
- **Gate:** the spike of 2026-10-02 measures how much of the data is usable before anything is built.

Exit:
- The measured share of usable decisions.
- A replay-trained policy that beats the self-play policy of M9 on the ladder, or improves it as its initialization, measured at an equal number of decisions.

## M12 — Search

Search on top of the learned policy and value, with the engine as the exact model (the engine clones and steps states). Built in stages:
1. A one-turn lookahead: the best own pairs against likely opponent pairs over sampled random outcomes, scored by the value head.
2. A simultaneous-move tree search. The policy gives the priors; chance and the opponent's hidden stat points are sampled.
3. Expert iteration: the search's choices become training targets.

Owner direction (2026-10-03): search deeper than one turn. A public reference point: mikumiku37 (Smogon, 2026-10-03) reached #1 on the Reg M-C ladder with a one-turn search. In each of 16 sampled worlds it solves an 8 x 8 payoff table of joint actions for a mixed strategy, and that added about 110 Elo over its raw policy. The engine's speed makes more affordable; the cost lies in the network evaluations, which are batched on the GPU. In order:
- **One turn first:** the same simultaneous-move payoff table.
- **Then two turns ahead.**
- **Endgame solving:** with few Pokémon left, search to the end instead of using the value estimate.

The search must stay deterministic given its seeds.

Exit:
- The Elo gain over the raw policy on the ladder, at a fixed time per move.
- A report like the learning reports in `docs/learning/`.

## M13 — Playing strength beyond self-play

Levers recorded by the owner on 2026-10-03, most promising first. The first two have the most weight: search with the exact engine (M12), and a model of human play.
1. **Deeper search and endgame solving:** see M12.
2. **A model of human play:** a policy trained on the human replays (M11) predicts how people play. The search uses it as the opponent model on the ladder, where the opponents are people, so it can exploit common habits (Protect, Fake Out, the usual switches). mikumiku37 never saw human games.
3. **A belief over the hidden stat points:** with open team sheets mostly the stat points are hidden. Observed damage and turn order narrow them down during a game. The search samples its worlds from that belief, not uniformly.
4. **Scale and breadth:**
   - more training games: the encoder in C, then a rented GPU after a measured trial;
   - a larger network with static dex features: decision 0020, model v2.1;
   - many teams, through the expansion's mechanic coverage.
5. **A robust league with exploiters:** agents trained only to beat the main agent, as in AlphaStar. They punish any weakness at once, so the self-play cycling of the first night run (a plateau of 750 to 830 Elo) does not come back.
6. **Team preview and team choice:**
   - the bring-four decision and the leads against the opponent's sheet, trained as a decision of their own;
   - the teams played on the ladder, chosen by how they fare against the current field.

Exit: each lever is measured on its own, as an Elo difference at a fixed time per move against the previous best agent, before the next one is stacked on it.

## M14 — Closed team sheets (the Bo1 ladder)

Today the bot plays only with open team sheets (decision 0016). In Bo3 they are forced. In Bo1 it asks for them and forfeits politely if the opponent refuses. In the replay spike only about 4 percent of Bo1 games had open sheets, so broad Bo1 laddering needs closed sheets. Owner, 2026-10-03: play Bo3 first; closed sheets come as their own step after M13. It needs:
1. **Reveal tracking:** the battle state records what each side has revealed (moves, item, ability; species at team preview). The observation marks the foe's unrevealed fields as unknown. That changes the state and the public view, so it needs an owner OK.
2. **The tracker:** it folds the reveals of a live game into that observation.
3. **Training with hidden foe sets:** the self-play viewer sees only what is revealed.
4. **Set prediction for the search:** the hidden sets are sampled from a predictor, for example a net head trained on the M11 replays, not from a uniform guess.
5. **The live adapter:** it accepts Bo1 games without open sheets.

Exit: the Elo on the Bo1 ladder without open sheets, against the bot's Bo3 Elo with open sheets.

## Later

Additional certified teams (a certification of the M8 teams in the manner of M5), broader regulation profiles, recurrent agents, belief-conditioned hypothetical search, best-of-three orchestration and further external clients. Add these based on measured needs, not speculative scaffolding.

## Review standard for every slice

A useful completion report includes scope, changed files, test commands/results, unresolved uncertainty, actual artifact paths and proposed next task. Distinguish implemented code, locally tested behavior, hosted CI and certified mechanics. Passing smoke tests never imply a completed rules engine.
