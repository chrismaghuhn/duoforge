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

A second reference point (owner, 2026-10-03): nessie123 (Smogon, 2026-09-28) was briefly #1 on the Reg M-C Bo3 ladder with open team sheets and a game-theoretic search. Its parts are a template for the stages above:
- **At every node, a matrix game:** a double-oracle solver finds the equilibrium of the simultaneous joint actions instead of one maximin choice.
- **Chance branched and pruned:** damage rolls, critical hits and secondary effects are expanded and pruned, not sampled blindly. Leaves are expanded first where they could move the result most.
- **Endgames close to exact:** 2v2 endgames within about 0.5 percent of an exhaustive solver.
- **Search-guided training (stage 3):** about 375,000 self-play games guided by the search and a network of about 1.5M parameters were enough. That took about 20 hours on an M4 Mac mini plus about $120 of cloud time. On the ladder it plays on one CPU core.
- **Its limits, as its author states them:** it plays only the equilibrium (no exploitation of human habits, which is our lever 2), and it handles the hidden stat points crudely.

The search must stay deterministic given its seeds.

Memory layout for the stage 2 tree (owner, 2026-10-03): allocate the nodes from a preallocated arena and link them by 32-bit indices, not by pointers. This also keeps heap allocation out of the hot path, as AGENTS.md requires. Parallelism comes from many trees at once, one per game, not from threads sharing one tree.
- **Reference:** the poke-engine fork larry-the-table-guy/poke-engine, PR #10 ("perf: Arena!") and PR #11 (4-byte handles).
- **What PR #10 measured:** a 5-second-search benchmark went from 2:50 to 2:24 on one thread and from 3:54 to 2:30 on eight. Most of the gain comes from dropping a whole tree at once.
- These are their numbers on their engine, not ours.

Status of stage 1 (spec `docs/superpowers/specs/2026-10-03-m12-search-stage1-design.md`, decision 0022, plan `docs/superpowers/plans/2026-10-03-m12-search-stage1.md`):
- **Built and merged on 2026-10-03:**
  - the matrix game and the decision keys (plan PR C, #204);
  - the library's leaf expansion and search seeds (plan PR A, #203, 0.42.0);
  - the Python bindings (plan PR B, #205);
  - `Model.value`, the lookahead and `SearchPlayer` (plan PR D, #206).
- **Measured (2026-10-04/05):** the oracle arena (#218/#219), then the honest public-information search (decision 0023, #222-#233). Its report (#236): E +0.39 / X +0.31 against the raw network and +0.12 to +0.20 against the panel, about 95 percent of the oracle's gain, with 2 percent raw fallbacks; about 33 ms per decision, 23 ms of it in the network on the CPU. On params-49333 the gain is X +0.27 (stage 3 P0, #242).
- **Team preview searched (#240, report #241):** no consistent panel gain, so the preview stays with the raw network.
- **Stage 3 (expert iteration):** spec `docs/superpowers/specs/2026-10-05-m12-expert-iteration-design.md`, decision 0024, phases P0 to P5. P0 passed; P1 (a pilot labelling one decision in eight) is being built from plans `docs/superpowers/plans/2026-10-08-stage3-p1-pilot.md` and `...-p1-learner.md`.

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

More levers recorded by the owner on 2026-10-03. Search mainly solves the endgame; these aim at the early game and at the tournament format. The owner's favourites are 7 and 11.

**The early game:**

7. **Exact engine aids as network inputs:** the engine (in C, no rule in Python) answers questions about the current state. Jaxcalibur and mikumiku37 both feed their networks no damage calculator, so this is our own edge. This needs a new public query and an owner OK. The questions:
   - the damage range of each move against each target, and whether it reaches a KO;
   - the speed order under Tailwind, Trick Room, stat stages, abilities and items.
8. **Team preview and leads by simulation:** with open sheets the opponent's team is known before the game. Evaluate our best bring-four and lead choices against the opponent's most likely ones over many fast played-out games. The team preview's time allows it.
9. **An opening book against the meta:** the replays give the frequent ladder teams. Offline search with heavy compute (AWS CPUs) fixes bring, leads and the first one or two turns against them; at game time it is a lookup.
10. **Human openings predicted:** turns 1 and 2 repeat common human patterns: who protects against Fake Out, who sets Tailwind or Trick Room at once, where the double target goes. The human-play model (lever 2) predicts them.

**The tournament format:**

11. **Adapting within a Bo3:** games 2 and 3 use what the opponent brought, led with and did in game 1. The opponent model is updated after every game.

**Training and decisions:**

12. **Training against the real meta:** self-play opponent teams are drawn by their ladder frequency, as the replays show it.
13. **Mixed strategies on purpose:** the move choice is solved as a mixed strategy, as in mikumiku37's payoff table, so humans find no fixed pattern to read.
14. **Ensembles and checkpoint tournaments:** several networks decide together, and large AWS tournaments pick the strongest checkpoint.
15. **Risk by game state:** a value head that also estimates the uncertainty. The agent plays safe when ahead and takes chances when behind.
16. **Exact chance nodes in the search:** damage rolls, critical hits and accuracy are weighted exactly by the engine instead of only sampled.

**Training data:**

17. **Plausible random teams** (owner, 2026-10-03):
   - **Why:** random teams make the network learn Pokémon in general rather than a fixed meta, together with the static dex features of decision 0020. They give data without limit and also widen the engine's random testing. Jaxcalibur trained entirely on random teams.
   - **Where the sets come from:** the pinned Showdown's own Champions random doubles sets (the "[Gen 9 Champions] Random Doubles Battle" format), taken as data. DuoForge's setup validates every team, and the generator draws only from what the engine supports, so it grows with the coverage.
   - **Mix, not replace:** for example about half real meta teams, a third plausible random teams and a small rest fully random. The ratio is measured.
   - **A second ladder:** Showdown's Champions Random Doubles ladder needs no team building. Its foe sets are hidden, so it needs M14 first.
   - **Mutated Pokémon** (from nessie123, owner 2026-10-03): in about half of its training games the Pokémon had changed stats, abilities, types, moves and items, so the network learns the rules rather than one meta. For us this works inside the engine's coverage: only changes the engine supports, each team validated by setup as above.

18. **Auxiliary prediction heads** (from nessie123, owner 2026-10-03): extra outputs trained beside the policy and value make the network learn the game's structure. nessie123 predicts weather, terrain, damage, the opponent's moves, how long a Pokémon survives and how long the game lasts. For us:
   - the targets come exactly from the engine during self-play: damage dealt, the opponent's next action, turns survived, game length;
   - the opponent-action head is already Learner v2's next lever;
   - each head is measured on its own, as for every lever above (Elo at a fixed time per move).

Related public work, as reference points:
- **Metamon** (UT Austin): offline RL on human Showdown replays, with spectator logs rebuilt into first-person trajectories (as M11 does). Gens 1 to 4 singles, about 79 percent GXE; code and data are open.
- **PokéChamp:** a minimax language-model agent.
- **nessie123** (Smogon, 2026-09-28): Reg M-C Bo3 with open sheets, briefly #1 on the ladder. A double-oracle matrix-game search with chance pruning, search-guided self-play, a network of about 1.5M parameters with auxiliary heads, and mutated Pokémon in half of the training games (see M12, levers 17 and 18). An analysis tool is planned for release after Reg M-C; no code yet.


Measured levers (2026-10-05 to 10-08):
- **Lever 9, the opening book:** built from about 100,000 Champions replays (#228) and A/B-tested (#234, #238). No gain (-0.011 to +0.001); the book changed the choice in only 13 percent of games. It stays in the code, default off.
- **Lever 8, team preview by search:** see M12 (#240, #241). No consistent gain.
- **Luck-adjusted evaluation (#239):** the value head as a control variate over chance. Unbiased, but only about 1.2x fewer games, because the GAE-trained value head explains luck poorly (correlation 0.39). An undiscounted win-probability head would help; stage 3 records it as a proposal.

Ideas recorded by the owner on 2026-10-09 (from the Chess Programming Wiki, an endgame-tablebase note and a paper list), with where they fit:
- **A cache of network inputs in the search:** the 16 worlds differ only in hidden values, and the network sees only the public view, so many of the 1,024 leaves of a decision may give byte-equal rows. Measure the duplicate rate first; if it is high, the cache belongs to stage 3 P2 (performance).
- **Perft/divide counts as an engine regression test:** frozen counts of the legal joint actions (and their sequences under fixed seeds) for reference positions. They catch a lost or added legal option during the content expansion. Enumerating chance outcomes would need an engine change.
- **Lever 7, the damage calculator as a network input,** planned after the engine coverage work: a new encoder version (7; 5 went to Transform and Revival Blessing, 6 to the reserve columns of the content expansion, decision 0050) with, per move option and target, the damage range and KO chance. It is computed by the engine's own formulas and assumes only public facts about the foe (species, item, ability, nature, and a common-spread assumption for the hidden stat points), never the hidden values. It needs a decision and an owner OK; existing networks are widened, not retrained from zero.
- **Gumbel top-k with sequential halving** (Gumbel MuZero, ReSCALE arXiv 2603.21162) for stage 3's compute routing (P3), next to double oracle (P4).
- **A KL-regularised matrix game with the network's policy as a fixed magnet** (test-time RL, arXiv 2608.30635) as a candidate teacher next to N/E/X. It bounds the loss against the network; measure it against X before use.
- **A learned belief network for the hidden stat points** (Sokota et al., Nature 2026, Stratego), extending lever 3. Public inputs only at inference time. Trained only on our self-play, it learns our pool's spreads, not human ones, so it needs public replay or paste data for ladder play.
- **Endgame solving:** exact tablebases do not fit (the engine does not enumerate chance outcomes, and even 1v1 states with HP, PP and status are vast). A depth-limited endgame search at game time, as in M12, is the practical form; its results can also serve as a teacher.
- Transposition tables, iterative deepening and tactical extensions matter only for multi-turn search. Alpha-beta, null-move and forward pruning do not fit simultaneous moves.
- Further references: Student of Games (arXiv 2112.03178) for multi-turn search and endgames; look-ahead on policy networks (arXiv 2312.15220); PokéChamp (arXiv 2503.04094).

A second pass over the Chess Programming Wiki (owner, 2026-10-09), for what we do not have yet:
- **SPRT for comparisons** (the wiki's "modern, preferred method", as in Fishtest and OpenBench): a sequential probability ratio test stops a version-against-version match as soon as the result is clear, instead of a fixed number of games. It fits checkpoint and search-variant comparisons after P1; the P1 evaluation itself keeps its predeclared 12,288 games.
- **A bench signature:** Stockfish writes a fixed search's node count on fixed positions into every commit. Ours would be a pinned digest of the honest search's decisions and work on fixed positions, run in CI: perft guards the legal actions, the bench guards the search. The P1 plan has such digests once; this makes them a standing test.
- **A test-position suite:** curated positions with a known best answer (Fake Out into a KO, reading Protect, setting or reversing Trick Room, an exactly solvable 2v2 endgame), solved per checkpoint. Cheap and deterministic, it shows missing knowledge; per the wiki, do not tune on it.
- **A fast cache key (Zobrist-style):** a 64-bit key, updated with the state, instead of SHA-256 for caching network evaluations across search calls and decisions, not only within one call (the P2 tick table). Measure the hit rate across calls first.
- **An incrementally updated first layer (the NNUE idea):** few of the encoder's columns change per step, so the first layer's accumulator could be updated instead of recomputed. Stage 3 P3, after measuring that layer's share of the time.
- **Live play:** pondering (searching likely next states while the opponent chooses, and during team preview) and time management (the search budget per decision by complexity and the remaining timer).
- **SPSA tuning** of search parameters (k, m, s of the N/E/X configurations) instead of a grid.

Ideas recorded by the owner on 2026-10-10 ("use Pokémon's structure instead of adding another famous game-AI algorithm"), with where they fit. Already covered elsewhere: the opponent's next action as a prediction target (lever 18, lever 2), an exploiter league (lever 5), adaptive search time (Gumbel top-k / P3, time management above), the counterfactual matrix under paired seeds (the honest search of M12 is that matrix), and tablebases (assessed above: a depth-limited endgame search instead). New:
- **Regret mining for distillation:** weight or select the states by how much worse the network's choice is than the search's, and train on the search's value per joint action, not only on its best action. A hard-state buffer keeps the high-regret states. P1 supports it: the teacher's argmax equalled the raw move in only 27 % of targets. It goes into a P2 plan as an option once the C2 repeat shows that the student learns the teacher at all. Reference: regret-guided search control (arXiv 2602.20809).
- **A belief-robust solver:** the honest search averages its values over the belief worlds, so an action that fails badly in a plausible minority of worlds can look as good as a safe one. A mix of the expected value and a lower tail (for example CVaR over the worst 10–20 % of belief mass), with the weight possibly depending on whether the side is ahead, is measured against the plain average before any use.
- **Value of information:** an action such as Protect or a harmless attack reveals sets, speed or the foe's plan. It should earn that through the value of the better later decisions, never through a scouting bonus. That needs a search over more than one turn, so it comes after the multi-turn search work. Reference: decision-relevant observation in POMDPs (arXiv 2604.01434).
- **Latent strategy concepts:** a small discrete latent (speed control, stalling Trick Room, sacrificing a slot for position, …) that the policy conditions on, to generalise strategy across teams. High risk; recorded, not planned.


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
