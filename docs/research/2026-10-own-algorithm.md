# An own search and learning algorithm for DuoForge (research, 2026-10-23)

Status: **research draft, docs only** (owner brief of 2026-10-23, relayed by the HauptSession). Nothing here is
implemented, decided or measured by this session. Every number from the repository names its source; every external
claim names its source and says whether it was verified (abstract or page read) or only reported second-hand. The
owner's private concept notes (CARDS V0.2.3, MADS V0.4) are referred to by name only, as agreed; nothing of them is
copied. Private data (weights, live logs, replay ids, player names) is absent by construction.

The question (owner, 2026-10-23): design DuoForge's own search and learning algorithm for Pokémon Champions VGC
doubles (Reg M-C; Champions singles later), one that exploits what others do not have instead of copying Jaxcalibur,
mikumiku37, nessie123 or PokaiTrainer (owner decision 2026-10-11: competitors are reference points, not a blueprint).

## 0. Summary

**What is actually ours.** Exact chance enumeration is *not* unique to DuoForge any more: PokaiTrainer (arXiv
2608.29197, verified) enumerates every weighted outcome of a joint action in a Rust engine, bundles damage rolls,
solves a Bayesian matrix game with CFR over 15 bring-worlds and reached 1350–1400 Elo on the open-sheet Bo3 ladder.
What no published Pokémon system has is the *combination* DuoForge already ships: an engine certified byte for byte
against the pinned Showdown with determinism as a first-class property, honest-information world construction with
round-trip proofs (`duoforge_battle_from_view`, decision 0023), an observation digest per leaf that defines sound
information sets (decision 0082), a C encoder and C integer inference kernels (E2–E3b merged, E4/E5 pending), and a
measurement culture (paired common-random-number ladders with predeclared gates). The edge is therefore
**verification-grade search**: exactness you can test against an exhaustive solver, labels you can pair seed for seed,
hypotheses the engine itself can refute, and certificates where the leaves are exact.

**The proposal** is one algorithm family, "counterfactual-certified search", delivered as five measurable pieces,
ranked by expected value per cost (section 7):

| # | piece | exploits | cheapest test | rank |
|---|---|---|---|---|
| P1 | exact chance by a tape-driven enumerator with outcome classes refined on counterexample (#358) | one draw function with named sites and bounds (`src/rng/draw.h`), cheap copies, common random numbers by design | teacher seed-flip rate on recorded roots; 2v2 positions against an exhaustive solver | 1 |
| P2 | engine-probed relation classes (speed tier, KO class per pair) as network input and as abstraction keys (#366, #604 stage 1) | counterfactual probing already built (KO check, role check), no rule in Python | value-only heads on the existing BC rows: AUC, monotonicity, KO-check "candidate not chosen" | 2 |
| P3 | certified endgames: the digest-keyed tree (D2) with exact chance, terminal leaves, interval matrix games and a root certificate (#367, #440 step 4) | D2 built and offline-passed, `expand_digest`, `battle_equal`/`digest`, 150k leaf expansions/s | harvested ≤2v2 positions, paired play-outs, agreement with the exhaustive solver | 3 |
| P4 | belief cells: hidden spreads and sets grouped by decision-relevant classes, split on counterexample, filtered exactly by replaying the turn in each world; rated human foe model and Bo3 memory (#368, #365, #379) | 16 worlds in 0.4 ms, hypotheses as numbers, the particle filter for closed sheets | posterior mass on the true spread in self-play games (privileged check offline), then the ladder | 4 |
| P5 | counterfactual distillation: search as teacher with exact chance, common-random-number per-action targets, privileged per-world value targets guarded by the digest, engine-built consistency edits, C inference for throughput (#360, #371, #380, #655) | per-action values are free from the matrix, exact tiebreak, byte-equal labels, the monotone edit path | a label learning curve (100k / 300k / 1M labels) locally before any AWS run | 5 |

P1 is the enabler and the cheapest; P5 is the destination and the most expensive. The owner's CARDS and MADS concepts
transfer not as a search over structured Magic actions (Pokémon actions are atomic) but as the **discipline of sound
cells, uncovered-action accounting and certificates** over worlds and chance classes; that is section 6, and it is
folded into P1, P3 and P4. Section 6.1 checks the owner's earlier plan to combine MADS and CARDS: the two collide
in Magic because abstract cells are nodes of the decision graph, and they compose in Pokémon because worlds and
chance classes hang below the edges of a digest-keyed tree.

**What probably does not fit** (section 8): chess-style NNUE, a full ReBeL public-belief recursion, a transformer PPO
run at one H100-week, decoupled UCT, more one-turn budget, team preview as a Nash game (measured flat), tablebases,
R-NaD as the main learner (owner closed #359), a "scouting bonus" for information.

## 1. Scope, method, what was verified

- Read: `AGENTS.md`, `docs/process/LANES.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, decisions 0017, 0020–0024,
  0081–0083, the depth-search spec (2026-10-13), the in-engine evaluation spec (2026-10-14), the expert-iteration spec
  (2026-10-05), the Bo1 belief and human-model designs, the benchmarks of 2026-10-11 to 2026-10-15 under
  `docs/benchmarks/`, the learning reports under `docs/learning/`, the roadmap issues #355–#385, #418, #433, #440,
  #450, #451, #481, #485, #494–#498, #509, #604, #655 with their comments (owner paper digests, the NNUE discussion and
  the community counter-arguments of 2026-10-23).
- Checked in the code: the public API list of `include/duoforge/*.h`; `src/rng/draw.h` and `draw.c` (every gameplay
  draw passes `dfi_draw(site, lo, hi)`, 34 site ids, 35 call sites in `src/combat/`; a **test-only tape** replaces the
  PCG in conformance tests and is unreachable from the public API); `src/search/search.c` (304 lines: clone, reseed,
  step, encode; `expand_digest` since E1b); `src/eval/` (E2 loader, E3a kernels, E3n LayerNorm, E3g three value
  graphs, E3b tiles merged; **no** `duoforge_batch_expand_evaluated` yet, so E5 wiring and the E4 conversion are
  pending and every E4 run needs the owner's go); `src/encode/encode.c` (encoder versions 1–6, 1094 columns at 6);
  `python/duoforge_search/` (honest, matrix with the LP and the CFR+ root solver, tree with the two-turn CFR+ solver,
  belief, ko_check, tree_offline, record_roots), `python/duoforge_learn/model_v2.py`.
- Verified claims of the brief: ~10k random games/s per core (10,458 battles/s at one GCC worker, 82k at 16;
  `docs/benchmarks/2026-10-01-batch-scaling`); flat state with `memcpy` copies (`duoforge_battle_copy`, ARCHITECTURE
  §4.2); exact chance enumeration is **possible in principle but not built** (#358 open; the draws are centralised and
  the tape exists, see P1); cheap counterfactuals exist as *stepping* (copy, reseed, step: 1024 leaves in 6.6–7.0 ms on
  8 workers) and as *world construction* (`from_view`, 16 worlds in 0.4 ms); **no public damage or speed query exists**
  (`duoforge_move_result` classifies a move's public result from events for the tracker; `duoforge_hp_display` is the
  percent display; `duoforge_data_type_effect` is the type chart); the KO check and the role check compute threats by
  probe-stepping, not by a formula.
- External survey: web search with the abstract or page read for every source in section 9, unless marked
  "second-hand" or "not fetched". Papers after this model's knowledge cutoff were only read through their abstracts.

## 2. The measured starting point (what any design must respect)

| fact | value | source |
|---|---|---|
| where a decision's time goes (honest search, K = M = 8, S = 16) | network 93 % at the padded capacity, 45 % at capacity 1024; engine parts under 6 %: `expand` 1024 leaves 6.6–7.0 ms, 16 worlds 0.4 ms | `2026-10-11-honest-search-breakdown` |
| one-turn search against raw BC6 (paired, held-out bot) | h 0.527 [0.518, 0.537]; against the PPO net 0.561; live path 0.658 [0.613, 0.702] against raw | `2026-10-12-search-ladder`, `2026-10-11-live-arena` |
| a human-like foe model instead of the own net | h 0.527 [0.519, 0.536], +5.4 points of score | `2026-10-11-foe-model-arena` |
| the best answer instead of the Nash mix (2e, live since 2026-10-14) | h2h 0.535 [0.517, 0.554] | search ladder, step 2 |
| more one-turn budget (×2 candidates or worlds) | 0.490 / 0.496 / 0.500: flat; the exact LP rescue breaks above 20,898 tableau cells | search ladder, budget step |
| team preview as Nash / turn-1 rollout / wider preview | 0.519, 0.517 (not adopted); 1bw passed the ladder and failed the mirror touchstone 0.415 | search ladder, steps 1, 1b, 1bw |
| two-turn tree (D2) | built, CFR+ bound 490 iterations, the root choice differs from 2e in ~53 % of decisions, the three tree phases take median 0.83 s locally; **ladder arms not run** (ML paused 2026-10-16) | `2026-10-14-depth-d2` |
| KO check on live logs (1,768 decisions) | own likely KO available 880, played 514 (58 %); missed because not a candidate 22, **among the candidates and not chosen 344**; foe likely threats 777, answered 174 (22 %), the threatening worst pair was a search column in 0.57 of the weight | #440, comment 2026-10-15 |
| role check | losing the last answer to a foe Pokémon in 132 of 352 own faints; 87 of those 132 games lost | #440, comment 2026-10-15 |
| network diagnosis (BC6, held-out players) | top-8 recall on turns 68.0 %, 32.0 % of human actions outside the top 8; value AUC 0.793 (0.63 at preview, 0.88–0.90 from turn 6); ECE 0.031 | `2026-10-13-network-diagnosis` |
| value monotonicity (BC6) | removing a move raises the own side's value in 21.3 % of edits, lowers the foe's in 22.2 % | `2026-10-15-bc6-monotone` |
| distillation (C2) | the student fits the train targets but held-out agreement stays at 0.32 from 13k labels; the teacher's argmax flips in 14 % of states under another search seed (self-agreement 0.859) | #357 |
| label throughput | 20–36 searched decisions/s (lockstep tick, dedup 2.45× fewer value rows) against 22–27k raw self-play decisions/s | `2026-10-09-stage3-p2`, `2026-10-02-night` |
| luck meter | weighting hidden foe actions by BC6 biases the luck by +0.046 per mixed turn; the unmixed number agrees with the oracle | `2026-10-14-cts-luck` |
| preview exploitability (one tournament team) | 34.6 points [29.1, 39.8] lost to the foe's best answer | `2026-10-13-preview-exploitability` |
| engine coverage | 82.4 % of the Reg M-C replay games playable on both sides (ceiling 99.95 %) | `docs/research/expansion/champions-100.md` |
| compute | Ryzen 7 5800X (16 threads) and an RTX 4060 Ti 8 GB locally; a 4-vCPU VPS about 3× slower per core; AWS spot on request (c7a.16xlarge used for the ladder campaign, #484); live cap min(2 s, 10 % of the remaining turn time) | LANES, depth spec §1.2, #484 |

Three readings follow. First, **the evaluation and the choice limit the bot, not the width or the budget**: the KO
misses are among the candidates, the budget curve is flat, the value head is non-monotone in a fifth of the edits.
Second, **the search's gain over the raw network is small (5.5 points)** because BC6 carries a strong human prior and
the search looks one turn ahead; any "search as teacher" plan must first make the search a clearly better player than
the net (PokaiTrainer reports the opposite regime: its raw policy loses even to a shallow heuristic search). Third,
**the network, not the engine, bounds everything**; the C pipeline (encoder, batch API, inference kernels) lowers that
cost by an estimated 5–8× (the spec's estimate, not a measurement), which makes evaluation-heavy proposals cheaper but
does not change what is ours: exact engine queries.

## 3. Survey: what the literature offers, and what it means here

Each entry: what the source says (verified unless marked), then the reading for DuoForge.

### 3.1 Poker line: search over beliefs

- **CFR and CFR+** (Zinkevich et al. 2007; Tammelin's CFR+) are the solvers DuoForge already uses at the root (D1) and
  in the tree (D2). Nothing to change.
- **DeepStack** (Moravčík et al. 2017): continual re-solving with a depth-limited lookahead and a counterfactual value
  network trained on solved subgames. Reading: the "value per world" idea (one value per hypothesis instead of one
  average) is what PokaiTrainer copied for VGC ("one value per bring subset"); DuoForge's value head reads the viewer's
  public row and so returns the *same* value in every world of a cell (the honest search's "own row" contract).
  A per-world value head is cheap to add in training (the privileged truth is known in self-play) and is P5's target
  (b).
- **Safe and nested subgame solving** (Brown and Sandholm 2017) and **depth-limited solving with multi-valued states**
  (Brown, Sandholm, Amos 2018): below the depth limit the opponent chooses among several continuation strategies, so
  the leaf is a vector, not a scalar. **Matrix-valued states / ABD** (Milec, Kovařík, Lisý 2025, arXiv 2501.10464):
  the same portfolio idea used to adapt to a known sub-rational opponent while staying robust. Reading: the depth
  spec's `foe_below = "nash" | "model"` is the two-element portfolio; a vector leaf {equilibrium, human model,
  exploiter} is the principled form of "exploit humans but stay safe" (P4, Bo3 memory).
- **ReBeL** (Brown et al. 2020): search and RL over public belief states, converges to Nash in two-player zero-sum
  games. **Student of Games** (Schmid et al. 2023): sound search (GT-CFR) plus learning, chess to poker to Scotland
  Yard. Reading: PokaiTrainer is the SoG recipe for VGC; its remaining defects (early-game optimism of the value net,
  opponent menu coverage 64 % per the Pith review, closed sheets unsolved) are the ones DuoForge's measurements also
  show. A full public-belief-state recursion over six 66-point spreads plus sets is too large (DeepNash's argument for
  Stratego); DuoForge's belief stays a sampled or clustered world set (P4).
- **Test-time RL in imperfect-information games** (Kubíček, Lisý, Sandholm 2026, arXiv 2608.30635): a KL-regularised
  matrix game with the network's policy as the magnet bounds the exploitability in the unregularised game. A review
  (Pith) argues the safety theorem does not cover the evaluated implementation. Reading: the roadmap's "magnet" idea
  stays an arm, not the default.

### 3.2 Stratego line: regularised self-play and learned belief search

- **DeepNash / R-NaD** (Perolat et al. 2022): model-free, no search, 84 % against human experts. Reading: the owner
  closed R-NaD as the main learner (#359); its regularisation stays an ingredient.
- **Ataraxos** (Sokota et al., Nature 2026, arXiv 2511.07312, abstract and methods read): Learned Belief Search samples
  hidden states from a supervised autoregressive belief network, runs 1,000 depth-40 rollouts with the move network,
  takes **one tabular magnetic mirror descent step at the root with a reverse-KL anchor to the move network**;
  "removing the reverse KL term devastates performance" (the search falls below the raw network). 16 H100 for a week
  plus 4 H100 for 4 days; 15–1–4 against the world champion. Reading: (i) the belief network is trained on the true
  hidden state of self-play, which DuoForge can do exactly (the privileged hypothesis is a documented boundary); (ii)
  the anchor warning applies to DuoForge's `ev` rule, which already plays the best answer to the foe model and showed
  no harm in the mirror touchstone; a KL-anchored root is cheap to run as an arm; (iii) the measurement that matters
  is "search minus raw at equal time", which the ladder already does.
- **Magnetic mirror descent** (Sokota et al., ICLR 2023): one algorithm for RL and equilibrium solving. Reading: the
  `--policy-objective mmd` flag exists in the learner (plan 2026-10-11) and stays an alternative arm.

### 3.3 Determinization and its pitfalls

- **PIMC** (Long, Sturtevant, Buro, Furtak 2010): strategy fusion and non-locality are the two failure modes;
  **ISMCTS** (Cowling, Powley, Whitehouse 2012) searches information sets instead of determinizations; **MAPLE**
  (arXiv 2605.24139, CoG 2026, abstract read): one search tree over several sampled world states with aggregated
  policy and value evaluation, +291 Elo over PIMC-AlphaZero in Phantom Go and +136 in Dark Hex. Reading: the depth
  spec's "one tree over all worlds, our nodes merged by the observation digest" is already the ISMCTS/MAPLE shape;
  the merge share is a diagnostic there. Nothing to copy, something to keep.
- **BETS** (Solinas, Haluška, Schmid, Buro, Sturtevant, Bowling 2026, arXiv 2610.15046, abstract read): a learned
  belief embedding updated along the tree, trained on the realized hidden state. Reading: a later step of P4 once the
  exact filter and the cells are measured.

### 3.4 Simultaneous moves

- **Bošanský, Lisý, Lanctot, Čermák, Winands (AIJ 2016)**: exact backward induction with pruning (double oracle,
  serialized alpha-beta bounds) and sampling algorithms for two-player simultaneous-move games; **Saffidine, Finnsson,
  Buro (AAAI 2012)**: simultaneous-move alpha-beta (SMAB) keeps upper and lower bounds on the payoffs of stacked
  matrix games and prunes dominated actions by LP feasibility (verified, abstract). **Lisý et al.
  (NeurIPS 2013)** and **Kovařík and Lisý (2018, arXiv 1804.09045)**: Hannan-consistent selection (regret matching,
  Exp3) with averaging converges in simultaneous-move MCTS; applying such algorithms naively to observed payoffs does
  not. Reading: for P3's bound-guided endgame solver the pruning literature is the right reference, not alpha-beta.
- **Decoupled UCT is exploitable, measured in VGC**: PokaiTrainer's informed local best response wins 83.6 % against a
  decoupled-UCT mix and 49.6 % against the CFR mix (verified). **Oak** ("Stockfish for RBY", GPL; tutorial read) offers
  `ucb`, `pucb`, `exp3`, `pexp3` and `rm` bandits and says plain UCB is currently its strongest variant "despite
  exp3's theoretical guarantees" and better suited to low-iteration searches; it does not claim UCB is unsound.
  Reading: the depth spec's choice (RM with the prior as exploration, Exp3 as an arm) is right; "UCB wins in practice
  at low budgets" is a reason to keep a UCB arm in D5, measured by exploitability as PokaiTrainer did.
- **Double oracle** (McMahan 2003; Bošanský 2013/2014): grow the restricted game by best responses. Reading: #433 is
  the DuoForge form; CARDS's "UNKNOWN = uncovered" accounting (section 6) is the honest bound while it grows.
- **Factored and combinatorial actions**: CFR-MIX (Li et al., IJCAI 2021) decomposes joint regrets as products for
  teams; regret circuits (Farina et al.) compose regret minimizers over structured action spaces. Reading: doubles'
  joint pairs (up to 1024) are small enough for explicit candidates at the root; factoring matters only for a full
  double-oracle over the legal domain and is not a first step.

### 3.5 AlphaZero line: search as teacher

- **Expert iteration** (Anthony, Tian, Barber 2017) and **Gumbel MuZero** (Danihelka et al. 2022): policy
  improvement with few simulations by Gumbel top-k and sequential halving; **ReSCALE** (arXiv 2603.21162): the same
  two devices restore monotone budget scaling in LLM tree search. **Regret-guided search control** (Tsai et al., ICLR
  2026, arXiv 2602.20809): a regret network picks high-regret states as self-play restart points, +77 Elo over
  AlphaZero on 9×9 Go, Othello, Hex. Reading: the roadmap's P3 "regret routing" and "regret mining" are these; at a
  root with 8 candidates, sequential halving buys little, at depth (D5) it is the budget router.
- **Self-Play Search Distillation** (arXiv 2609.30936, abstract read): despite the owner's digest, this paper distils
  board-game search records into **LLM reasoning chains**; only the general idea (keep alternatives, replies and
  values in the record, distil the distribution) transfers, and it is what decision 0024 already prescribes (the
  mixture, not the argmax; #357 confirmed the argmax is the worse target). **π-Play** (arXiv 2604.14054, abstract
  read): privileged self-distillation for LLM agents; the transferable idea is "a teacher that sees more than the
  student, with the student's inputs kept public", which is P5 (b) with the digest as the guard.

### 3.6 Evaluation and variance

- **AIVAT** (Burch et al., AAAI 2018): an unbiased low-variance estimator from a heuristic state value and known
  strategies, 85 % less standard deviation in a hold'em match. **AV-AIVAT** (arXiv 2608.06362, abstract read): AIVAT
  plus anytime-valid confidence sequences; a median 54× variance reduction and 74× fewer hands in the asymptotic
  version, only 1.37× with the exact finite-sample certificate. **VR-MCCFR** (Schmid et al., AAAI 2019): baselines for
  sampled CFR. **Common random numbers** (Glasserman and Yao 1992): provably beneficial under monotonicity, and the
  pairing must be synchronised. **SPRT** (chessprogramming.org; Fishtest): sequential stopping with pentanomial
  statistics over game pairs. Reading: DuoForge's ladder already pairs seeds and seats (the chess "game pair"); the
  luck meter (#494) is an AIVAT-style control variate with the engine's own chance seeds; #375 (SPRT) and #356
  (measuring the variance reduction) are cheap and should come before any expensive run, because they shrink every
  later experiment. The AV-AIVAT numbers warn that the certified version saves much less than the screening version.

### 3.7 Pokémon-specific systems (reference points)

| system | what it is | numbers | what to take |
|---|---|---|---|
| **PokaiTrainer** (arXiv 2608.29197, Max Yu, verified) | Rust engine enumerating the full weighted outcome distribution (median 9 branches per joint action, max 18,176; a 32-branch cap covers 99.5 % of mass in 1.0 ms against 9.9 ms exhaustive; 6 of 500 turns mismatched Showdown); CFR Bayesian matrix game over 15 bring-worlds, stat spreads as a mixture inside each world reweighted by the engine's transition probability; counterfactual value net 5.4M parameters with one value per bring subset; SoG-style training from BC on 122,804 replays; 250 L40S-hours self-play plus 15 A100-hours | 59 % of 150 Bo3 sets at ~1320 Elo opponents, band 1350–1400, peak 1492; 10–23 s per decision; belief tiers worth +8–12 pp (confounded with search changes); opponent menus ranked by the belief-weighted prior +16 pp; widening the opponent menu 16→32: 47.3 % (no gain); Brier of the solved root value 0.171 against 0.214 for the net | the closest reference; its defects (value optimism, menu coverage 64 %, closed sheets unsolved, no confidence intervals, single seed) mark where DuoForge's measurements can be better |
| **nessie123** (Smogon thread, read) | ~1.5M-parameter net with auxiliary heads; double-oracle search seeded by the net's guess; chance branched on important events (KO rolls, crits, secondaries); selective deepening by reach² × static-eval entropy; "in many 2v2 endgames the search value is ~entirely terminal nodes" and within ~0.5 % of a strict solver; ~375k search-guided self-play games, half with mutated Pokémon; one CPU core live; no exploitation; stat points public in training | briefly #1 on the Reg M-C Bo3 ladder (2026-09-28); no Elo in the thread | the 0.5 % endgame yardstick (P3); search-guided self-play at hobby budget (P5) |
| **mikumiku37** (Smogon thread, second-hand) | ~8.7M-parameter transformer, PPO against a league of its own versions, no human data; a wide one-turn solve | #1 on the Reg M-C ladder at 1857 Elo, 81.2 % GXE (2026-10-01); the roadmap's "16 worlds, 8×8, +110 Elo from search" is the owner's digest and was not found by this session | a network can carry most of the strength; the search adds a bounded amount |
| **Jaxcalibur** (project page, read) | randbats singles; 8.5M-parameter transformer with 24 learned matchup tokens; PPO, ~100M games on one H100 for a week; pUCT with regret mixing, 32 worlds, depth 4, 20,480 rollouts, seconds per move on a GPU | peak 2557 Elo / 95.3 GXE; the author estimates search at +100–150 Elo | "matchup tokens" are learned, not an exact calculator: P2 stays an own edge |
| **Foul Play** (blog, read) | MCTS with decoupled UCB, damage rolls grouped (fainting rolls apart, the rest averaged), set inference from damage, speed, weather length, items | Gen 9 OU GXE 80 %, random battles 88 % | the static bundling rule P1 generalises adaptively |
| **Metamon** (Grigsby et al., RLC 2025) | offline RL on reconstructed human replays, gens 1–4 singles | top 10 % of active players | the M11 replay path is the same idea; no search |
| **PokéChamp** (Karten et al., ICML 2025) | LLM-driven minimax | projected 1300–1500 Elo | not a direction for an exact engine |
| **VGC-Bench** (Angliss et al., AAMAS 2026, abstract) | benchmark, 700k logs, BC/RL/LLM/double-oracle baselines; single-team agents beat a professional in a mirror but generalise worse as teams grow | – | the random-teams experiment of #450 is the right generalisation control |
| **Oak** (lab-oak, GPL, tutorial read) | RBY singles, libpkmn, bandits ucb/exp3/rm with network priors, small MLP evaluator, Nash on the root empirical matrix | 1,048,576 iterations in 12.8 s on turn 1 (author's machine); the net about 3× slower than the plain rollout | a template for in-engine evaluation throughput, not for doubles |

### 3.8 Abstraction refinement (for section 6)

**CEGAR** (Clarke, Grumberg, Jha, Lu, Veith, CAV 2000; JACM 2003) and **counterexample-guided planning** for
stochastic games and MDPs (Chatterjee, Henzinger, Jhala, Majumdar, UAI 2005; arXiv 1207.1373) are the roots of the
owner's CARDS concept. **Interval matrix games** (Li, Omega 2011; Hladík, Kybernetika 2010; second-hand through search
summaries): the value of a zero-sum game with interval payoffs is itself an interval, obtained from two auxiliary
linear programs. That is the arithmetic P3 needs to certify a root in a matrix game.

## 4. DuoForge's strengths and limits, mapped

| property of the game | DuoForge today | consequence for the design |
|---|---|---|
| hidden information (open sheets: stat points, exact HP, bench order, drawn counters; closed sheets: whole sets) | worlds from a public record and a numeric hypothesis, round-trip proven; spread table from Smogon usage; particle filter for sets; **no update from observed damage or speed** | the exact filter (P4) is the missing piece; the information-set digest keeps multi-turn search sound |
| chance (damage 16 rolls, crit, accuracy, secondaries, speed ties, sleep/confusion turns, multi-hit, drag, Moody) | one sample per world and edge, common random numbers across cells; 34 draw sites behind one function | enumeration is an engine extension of bounded size (P1); outcome classes come from the engine, never Python |
| simultaneous moves | exact Bayes LP at the root (size-limited), CFR+ root and tree solvers, best-answer rule live | keep; bound-guided pruning for exact endgames (P3) |
| shallow effective depth | one turn live; two turns built, not measured; the KO check shows one-turn threats unanswered | depth matters for threats and endgames, not for the early game; measure D2 before investing in D5 |
| doubles branching | K = M = 8 of up to 1024 joint pairs; misses are not a width problem (22 of 366) | width stays as is; the foe's uncovered responses get an honest bound (section 6) |
| team preview | raw policy live; Nash/rollout/wider forms flat or harmful on the touchstone; exploitable by 34.6 points against one team | a structured decision where lazy construction with bounds could apply (MADS), but the value head is the limit; keep the book oracle's measurement |
| Bo1/Bo3 | Bo3 open sheets live; closed sheets via particles | Bo3 memory as a prior shift (P4) |
| compute | one 8 GB GPU, 16 threads, a slow VPS, AWS on request; ML paused until Champions 100 % | every experiment below is sized for the local machine first |

## 5. Proposals

Each proposal states the idea, why it fits DuoForge specifically, a falsifiable hypothesis, the cheapest controlled
experiment with metrics and cost, risks, and what has to exist first. "Equal time" means the ladder's equal-time
control (exclusive p99, `docs/benchmarks/2026-10-12-search-ladder`); "lower bound" means the 95 % team-pair bootstrap.

### P1. Exact chance by a tape-driven enumerator, with outcome classes refined on counterexample

**Idea.** Every gameplay draw already goes through `dfi_draw(site, lo, hi)`, and the conformance tests already drive a
step from a *tape* of prescribed outcomes. Make a search-only variant of that tape a public enumeration driver: a step
run with a prefix tape stops at the first draw the tape does not cover and *reports* `(site, lo, hi)` instead of
failing. A depth-first search over prefixes then enumerates every outcome path of a joint action in a world with its
exact probability (the product of `1/(hi − lo)` per draw), prunes by probability mass, and groups the leaves into
**outcome classes defined by the engine** (first class key: which members fainted this turn, i.e. the KO pattern;
later keys: the status and field facts the step produced). Each class is evaluated once by a representative leaf (or
by all its leaves where the budget allows) with the class's exact weight. The CARDS transfer (section 6): classes are
cells with an interval over their members; a class is split only when a counterexample shows the root decision
depends on the split (two members whose values straddle the decision), and in endgames the certificate is exact.

**Why DuoForge.** (i) The draws are centralised with named sites and bounds, so the enumerator inherits the certified
semantics without a second rule implementation (PokaiTrainer re-implemented the rules and reached 99 % parity;
DuoForge's parity is tested byte for byte). (ii) A re-run per prefix is cheap: a step costs microseconds (about
340k decisions/s on one worker in the native loop), the leaf batch runs on all workers. (iii) Common random numbers
across cells are already the design (the seeds never depend on the cell), so exact enumeration is the limit of a
discipline the search has, not a new one. (iv) The same enumerator answers P4's filter question ("which rolls produce
the shown HP") and P3's terminal leaves.

**Hypotheses.**
- H1.1 (teacher noise): on recorded roots the teacher's argmax flip rate under a changed search seed falls from 14 %
  (#357) to below 5 % at equal worlds (only the belief sampling remains).
- H1.2 (endgame exactness): on positions with at most two Pokémon left per side and terminal-only leaves, the
  enumerated value matches an exhaustive solver within 0.5 points of win probability in at least 95 % of positions
  (nessie's yardstick), and the choice agrees in at least 95 %.
- H1.3 (strength at equal time): exact chance at S = 16 against sampled chance with the budget matched (the b-s32
  shape) has a lower bound above 0.50 against 2e. Prior evidence is against a large one-turn gain (the ×2 S arms were
  flat), so the main value of P1 is H1.1, H1.2 and what it enables.

**Cheapest experiment.**
1. Engine: the enumeration call (`expand` with a prefix tape, the "next draw" report, mass pruning, a class key by
   faint pattern), with a conformance test that replays every recorded reference battle's tape through the new path
   and reproduces its events; a refusal by name when the branch cap is hit (multi-hit, drag, Moody). This needs a
   decision note (#358) because the tape is marked test-only and the public API gains a call; information safety is
   as for reseeding (search copies only, never the root's RNG).
2. Offline shadow on 64 team pairs (as `tree_offline` does): sampled against exact root tables on the same roots;
   report the flip rate (two seeds), choice agreement, |value difference| per cell, branches and classes per cell
   (median, p99), the pruned mass, and the seconds per decision exclusive.
3. Endgame oracle: harvest positions with ≤ 2 members left per side in every world from the recorded ladder games
   (public records are in the decision records), run the enumerator to the end where it terminates within the cap,
   compare with a plain exhaustive enumerator without classes (the oracle), count certified and unresolved positions.
Cost: engine 2–4 days plus review; machine time hours under the lock; no training, no AWS.

**Risks.** Branch explosion in the tail (PokaiTrainer: median 9, max 18,176 branches per joint action); a class key
that is too coarse (KO pattern only) hides the HP left for the next turn, which the counterexample loop must catch;
cost at depth 2 multiplies by the class count; a budget in work units, never wall time, as the depth spec requires.

**Needs.** The engine decision and call; class keys defined and tested in C; the DFS driver in Python (numbers only);
the offline tools above.

### P2. Engine-probed relation classes as network input and as abstraction keys

**Idea.** Per world and per pair (own member, foe member), the engine answers exact relational questions: outspeeds /
ties / is outsped under the current field (Tailwind, Trick Room, paralysis, boosts, items); the KO class of the best
own move into that foe (KO / 2HKO / 3+ turns, over the 16 rolls, crit as a separate flag); the same from the foe's
side; per own move option and target the KO chance class. These sparse on/off columns go into a new encoder version
(7) for the value and policy heads (owner lever 7, #366), and the same classes serve as keys for world cells (P4) and
chance classes (P1). Two ways to compute them: by probe-stepping, as the KO check and the role check already do
(four samples per world per probe), or by an exact damage and speed query in C (#604 stage 1, the "benchmark
optimiser" API), which is cheaper and exact. At the root and in training rows the foe's hidden stat points are
replaced by the common-spread assumption (#366); inside the search each world's values are used.

**Why DuoForge.** The evidence that the network misjudges exactly these relations: the KO misses are among the
candidates (344 of 366), a fifth of move removals move the value the wrong way, threats are answered in 22 % of the
likely cases. Jaxcalibur and mikumiku37 feed no calculator (Jaxcalibur's 24 matchup tokens are learned); PokaiTrainer
feeds spread quantiles and belief summaries (worth +8–12 pp, confounded). An exact engine can give the classes for
free and without a rule in Python.

**Hypotheses.**
- H2.1 (offline): a value-only head trained on the existing M11 rows with the relation columns beats the same head
  without them by at least 0.02 held-out AUC and halves the wrong-way rate of the monotone probe (21 % → ≤ 12 %),
  because a removed move changes the KO class.
- H2.2 (policy): held-out top-8 recall on turns rises from 68.0 % to at least 72 %.
- H2.3 (strength at equal time): the search with the new value beats the search with BC6's value, lower bound above
  0.50, no harm against the held-out bot, the monotone gate not worse than BC6's.

**Cheapest experiment.** Compute the columns for the existing BC rows through the engine (866k value rows; a few
microseconds each by query, more by probe); train value-only heads of the S preset on the same rows with and without
the columns (local GPU, hours; the BC6-M run fit on it); evaluate AUC, Brier, ECE by turn, the monotone probe (tool
exists), and the KO check with the new value in the search on the recorded logs. Only then a BC run of the full
network (owner go) and the ladder arm. Cost: the C query is an engine decision (days); training hours; evaluation
hours.

**Risks.** Probe cost at every leaf if no query exists (mitigate: query, or classes at the root only); leakage of
hidden values into the public row (the columns at the root must come from public facts plus the common spread, the
world's exact values only inside the search); the network may already infer the classes, then the measurement says
so; distribution shift between human rows and self-play.

**Needs.** An engine decision for the query (or the probe path), encoder 7 (a decision, HS numbers), a training go.

### P3. Certified endgames: the digest-keyed tree with exact chance, terminal leaves and interval certificates

**Idea.** When few Pokémon remain (first rule: at most two per side in every world, counted from the public record),
the search switches from "value head after one turn" to "solve": D2's tree over information sets keyed by the
observation digest, exact chance from P1, depth until terminal where the budget allows (the arena's cut-off tiebreak
stays exact), transpositions by `duoforge_battle_equal` or the digest, and the value head only at cut leaves with a
declared interval (or `[−1, +1]` when nothing is trusted). The root is certified when the lower bound of the chosen
action (or mix) is at least the upper bound of every alternative, computed as interval matrix games (two LPs per
node). Output: `CERTIFIED` with the certificate, or `UNRESOLVED` with the anytime choice (the solved mix). This is
#367's "exact small endgames" and #440 step 4; nessie reports 2v2 within 0.5 % of a strict solver; PokaiTrainer has no
endgame mode; nobody publishes certificates.

**Why DuoForge.** D2 is built and offline-passed (bound 490 iterations, root choice differs from 2e in half the
decisions); `expand_digest`, `battle_equal` and `battle_digest` exist; the engine expands 150k leaves/s on 8 workers;
the exactness is testable (an exhaustive solver on the same positions), which is the owner's "verify, don't assume".
The value head is good late in the game (AUC 0.88–0.90 from turn 7), so the gain must come from the KO race and the
threat answering, not from calibration; that is what the KO check's endgame rows measure.

**Hypotheses.**
- H3.1 (exactness): on harvested ≤ 2v2 positions where the tree reaches terminals, the solve agrees with the
  exhaustive solver within 0.5 points in at least 95 % of positions; the certified share is reported.
- H3.2 (strength): from the same positions, both seats, paired seeds, solve mode beats 2e with a lower bound above
  0.50 and answers more foe KO threats (KO check, endgame rows, "answered" up by at least 10 points).
- H3.3 (cost): exclusive p99 within the live cap on the VPS at the chosen budget level; the unresolved share and the
  transposition hit rate are reported, not gated.

**Cheapest experiment.** Harvest endgame roots from recorded ladder games (`record_roots` serves roots from public
records); build the strict enumerator as the oracle (no classes, no cut); run solve mode, 2e and D2-with-value on the
positions; paired play-outs from the positions for strength. Mostly Python on existing pieces plus P1; machine hours.

**Risks.** Endgames that do not terminate within the depth (Protect loops, recovery) leave intervals wide, so no
certificate (report the share); transposition canonicalisation is an engine matter with proofs (the HS note on #450:
PP above a threshold, the last-used move only where something reads it; MADS's audit method in section 6 is the
tool); depth 3 with exact chance explodes without selectivity (D3/D5); the arena-allocated tree in C for D5 is a
separate build.

**Needs.** P1; the D2 ladder arms first (the predeclared kill criterion for depth with the BC6 value does not apply
to solve mode, which uses terminal leaves, so run it as its own arm on endgame positions); interval LP in
`matrix.py`.

### P4. Belief cells: exact filtering, counterexample-refined world groups, and an adaptive foe model

**Idea.** Three parts, measured apart. (i) **Exact filtering.** A hypothesis (a spread, under closed sheets a set) is
refuted when no outcome path reproduces the turn's shown events in that world: the enumerator of P1 answers "which
rolls produce the shown HP percent", and an observed move order refutes spreads directly through the engine's speed
comparison. Keep a persistent posterior per foe member across turns and across the games of a Bo3 (the luck meter
already refutes worlds whose sets contradict the turn). (ii) **Cells.** Group hypotheses by the relation classes of
P2 (outspeeds X? survives Y's best move?); the root is solved per cell with a representative world and an interval
over its members; a cell is split only when a counterexample shows the root decision depends on it (section 6).
(iii) **The foe model.** BC6 today; the rated human model (#365, design exists) for human opponents; a vector leaf
{equilibrium, human model} in the depth tree (ABD's portfolio) so that exploiting stays robust; the opponent's game-1
choices as a prior shift in game 2 (#379).

**Why DuoForge.** Worlds are built in C from numbers in 25 µs each; the engine already refuses hypotheses that
contradict the public record (HP display bounds) and the particle tracker already rejects sets by facts; the 713k
replay games with ratings exist for the human model. PokaiTrainer reweights spreads by the engine's transition
probability and reports belief tiers worth +8–12 pp (confounded); Foul Play infers from damage and speed by hand
rules; DuoForge can do it exactly and without a rule in Python.

**Hypotheses.**
- H4.1 (belief quality): after turn 3 the posterior mass on the true spread (known privately in self-play games) is at
  least twice the prior's; the KO check's "known" share rises from 0.57 to at least 0.70; the value spread across
  worlds shrinks.
- H4.2 (strength): the filtered belief at 16 worlds beats today's at 16 worlds, lower bound above 0.50 against 2e.
- H4.3 (cells): cells with refinement reach the same decision as 16 i.i.d. worlds in at least 95 % of decisions at
  half the leaves (decision stability under world resampling as the metric, as #368's digest suggests).
- H4.4 (foe model): the rated model as the foe model beats BC6 as the foe model against the human-like panel (the
  held-out bot and the model's own samples per band), lower bound above 0.50, and shows no harm against the searching
  mirror.

**Cheapest experiment.** Offline on self-play ladder games with the true spreads available privately
(`duoforge_battle_hypothesis` is the oracle, never a model input): posterior mass per turn with and without the
filter; then the ladder arm; the foe-model arm needs the one BC run of the rated model (owner go). Cost: Python plus
the P1 enumerator; days.

**Risks.** Posterior collapse on priors that lack the true set (the redraw cap, already counted); the foe's own
choices as evidence need the foe model (an arm, not the default); the human-model measurement is circular without
human play, which is allowed only where bots are welcome; Bo3 memory can be exploited by an opponent who changes.

**Needs.** P1 (or an exact damage-range query), a persistent posterior store in the search (numbers only), the rated
model's training go.

### P5. Counterfactual distillation: the learning algorithm

**Idea.** Self-play where the search is the teacher (the owner's direction, Stockfish-style), with targets only
DuoForge can produce cheaply and exactly: (a) the solved root mix and the **per-action counterfactual values** under
exact chance (P1) and common random numbers across cells, so that the differences between actions, which is what a
regret target needs, carry no chance noise; (b) **privileged per-world value targets**: in self-play the engine knows
the true hidden state, so the value head can be trained per world (DeepStack's counterfactual values, Ataraxos's
belief training) while the student's inputs stay public, guarded by the observation digest; (c) a **consistency loss**
from engine-built edited positions (the monotone tool: a removed move must not raise the own value, mirror for the
foe); (d) label selection by regret (regret mining, #371; regret-guided search control); (e) the student is the same
network family, distilled into the small or medium C value graph (E3g) for throughput; (f) throughput from C inference
(E5), tick batching (1.43× measured) and fewer worlds per label where the cells (P4) allow. PPO stays the prior;
R-NaD stays closed; ReBeL waits.

**Why DuoForge.** Per-action values are free from the matrix the search already solves; the tiebreak and terminal
results are exact; labels reproduce byte for byte (the P2 identity gate); the privileged truth has a documented
boundary (decision 0002, 0023); the monotone edit path exists; the C pipeline makes the label cost fall.

**Hypotheses.**
- H5.1 (learning curve): held-out teacher argmax agreement rises from 0.32 at 13k labels (#357) to at least 0.6 at
  1M labels (the teacher's own self-agreement is 0.86; higher with exact chance).
- H5.2 (raw strength): the student's raw play beats BC6's raw play, lower bound above 0.50, at 2M labels.
- H5.3 (the exit rule): student plus search beats BC6 plus search at equal time.
- H5.4 (targets): per-world privileged value targets beat outcome-only targets in held-out Brier at equal labels;
  the consistency loss lowers the wrong-way rate below BC6's 21 % without hurting AUC.

**Cheapest experiment.** A learning curve, locally, no AWS: 100k, 300k and 1M labels with the lockstep tick path
(at 36 decisions/s about 8 hours for 1M; a few with C inference), the C2 recipe with early stopping, BC6 as the
start; metrics: held KL, agreement, Brier, the monotone rate, then raw head-to-head. The AWS run only after the curve
bends. Cost: 1–2 days of machine time, a training go per run, the P1 enumerator for the exact teacher.

**Risks.** The C2 generalisation failure persists (then data mix, not labels, is the issue: random teams, mutated
sets); the teacher is only 5.5 points better than the student today, so the signal is thin until P1–P3 make the
search stronger (PokaiTrainer's regime is the reverse); privileged targets could leak through proxies, so the digest
guard and the information-safety test of decision 0023 (two roots differing only in hidden values give the same
decision) must hold for every training row; label cost on the GPU-poor machine.

**Needs.** The owner's go per run, E4/E5, P1–P3 as the teacher, the label pipeline (`collect_expert`, `label_tick`),
an AWS budget later.

## 6. The owner's CARDS and MADS concepts, transferred

The owner's private notes (CARDS V0.2.3, counterexample-guided abstraction refinement for decision search; MADS V0.4,
bound-guided transposition-aware adversarial decision-graph search) target deterministic, perfect-information,
sequential Magic-like games over an authoritative engine; both exclude hidden information, chance and simultaneous
moves in their V0. The HauptSession's first assessment (2026-10-23) was: the V0 domain excludes exactly what Pokémon
has; Pokémon actions are atomic, so action abstraction gains little; the promising transfers are (a) the drawn worlds
of the opponent's sets, (b) chance as classes, (c) exact 2v2 endgames with intervals over matrix games. This session
agrees and adds three points.

**What carries over, and where it already sits.**

1. **Sound cells over hidden worlds and chance classes** (CARDS's primary invariant: every member's exact value lies
   inside the cell's interval). A cell of worlds or outcomes with an interval is sound only when the leaves are exact,
   that is in endgames with terminal leaves (P3) or wherever the value is a certified bound. With a neural value the
   interval is not sound, and the loop degrades to a *refinement heuristic*: split a cell when its members' values
   straddle the root decision. That heuristic is still useful (it is the principled form of "world clustering" in
   #368 and of adaptive chance bundling in P1), but it certifies nothing. The owner's own rule applies: a coarse
   abstraction may be imprecise, never falsely precise.
2. **"UNKNOWN means uncovered."** The honest search solves an 8 × 8 restricted game and silently treats the foe's
   other legal pairs as absent; the KO check shows the threatening pair is a column in only 0.57 of the weight. In
   CARDS's accounting the foe's uncovered responses keep the lower bound at −1 until covered; MADS's partial-expansion
   envelope says the same. A live bot cannot afford full coverage, but the *accounting* is cheap: report per decision
   the mass of foe responses outside the columns (the foe model's tail) and the value loss against the best probed
   response; refuse to call a decision "safe" (#495) while the uncovered mass is large. This is a diagnostic first and
   a double-oracle stop rule (#433) second.
3. **Interval matrix games as the certification arithmetic** (section 3.8): the lower bound of a mix is the LP over
   the lower matrix, the upper bound of the game value the LP over the upper matrix; a pure root action is certified
   when its lower bound reaches the upper bound of the rest. A formal check of the May/Must direction in the
   simultaneous case is required before any certified claim, as CARDS itself demands for its backup rules.
4. **May and Must actions** collapse for our own side under open sheets (we know our legality) and reappear under
   closed sheets: a hidden trapping ability makes our switch legal in some worlds and not in others. Today a leaf the
   engine refuses drops its own candidate (#436, "drop"), which is the Must-only lower bound. Keeping the candidate
   with its interval is the CARDS form; the engine's per-world domain already gives the facts.
5. **MADS's state-key audit** (INCLUDE / NORMALIZE / EXCLUDE / BENCHMARK_NAMESPACE with paired-state bounded
   bisimulation tests) is exactly the method D3 needs for canonical transposition keys (the HS note on #450: PP above
   a threshold, the last-used move only where something reads it, left/right symmetry without a symmetry breaker).
   The depth-bounded form is attractive: within a k-turn search, PP values above k are equivalent by construction.
   RNG state is EXCLUDE inside the search (every leaf is reseeded). The exact game graph is nearly acyclic because PP
   decreases with every move used, so MADS's acyclic V0 contract holds for exact keys and must be re-checked for
   normalised ones.
6. **MADS's certificate discipline for partial-order reduction** has one real home: the team preview's bench order.
   1bws merges the bench order by assumption ("an assumption no test checks", search ladder README); a certificate
   with positive fixtures and near-miss negatives (drag draws by bench order, a value-head difference) would make the
   merge a proven reduction or refuse it.
7. **Lazy construction with bounds** (MADS) has a structured decision to act on only at team preview (choose four of
   six and the leads: 360 tuples) and at replacement/pivot points; with a neural value the bounds are heuristic, and
   the anytime fallback (highest estimate, then lower bound, then stable order) is what the preview search does with
   a prior today. Modest.

**What does not carry over.** Prefix abstraction and symbolic coverage of structured actions (CARDS's primary
hypothesis H1): per-slot commands are complete and canonical in `duoforge_factored_choice`, and the joint space is at
most 1024 pairs, so there is nothing to keep symbolic. Construction replay sufficiency holds trivially. CARDS's
non-enumeration requirement is reversed here: Pokémon's exact space per node (worlds × classes × pairs) is small
enough that plain enumeration may beat refinement, which is CARDS's own "useful negative result" and must be
measured, not assumed.

**The cheapest CARDS-DF experiment** (folded into P1 and P3): on harvested ≤ 2v2 positions with terminal leaves,
compare the full enumeration over worlds and chance (the oracle) with the refinement loop that starts from one world
cell and KO-pattern chance classes. Catastrophic gate: certified root disagreements with the oracle = 0. Metrics:
engine steps and leaf evaluations saved (CARDS's refinement yield), counterexamples per certified root, the share of
positions where every cell splits (locality), certified share at a fixed budget. Falsifiable claim: at least 3× fewer
engine steps at zero certified errors on at least half of the positions. If chance in Pokémon is decision-relevant
almost everywhere (KO thresholds), the loop reconstructs the exact space and the result is a precise negative.

### 6.1 Combining MADS and CARDS: what collides in Magic, and why Pokémon is different

The owner once planned to combine the two concepts and dropped the plan because CARDS would have required leaving
out parts of MADS. The HauptSession's hypothesis (2026-10-23): exact transpositions are rare in Pokémon (simultaneous
moves, HP changes, chance), so the MADS parts that collide with CARDS are the cheap ones here, and a combination
(MADS bounds and scheduling plus CARDS abstraction over worlds and chance classes) may fit Pokémon better than Magic.
Checked against both notes:

| MADS part | why it collides with CARDS in Magic (as the notes state it) | in Pokémon doubles |
|---|---|---|
| exact transposition identity and the exact TT | CARDS forbids an abstract cell key as a TT key and forbids cell-local or epoch-derived bounds in the TT; a MADS node bound derived from cell children becomes epoch-dependent, so the TT may hold only exact-state facts (terminal values, exact successors) | exact transpositions are rare: HP after exact rolls, PP falling with every move, two sides moving at once; the measured merging in our search is by **information set** (digest merge share 0.61–0.71 at depth 2; 49 % byte-equal viewer rows across worlds in P2's tick), which is a CARDS cell, not a MADS transposition. Losing the exact TT costs little; a depth-bounded normalised key (PP above k) may recover some endgame merges and is a measurement (expected: under 5 % exact hits in ≤2v2 trees of depth 3) |
| reverse-parent fixpoint propagation over the DAG | a cell split re-targets edges and reverse-parent sets across the graph; CARDS's answer is a transactional epoch with a full recomputation, which kills MADS's incremental propagation and frontier | the abstraction axis is **orthogonal to the decision graph**: worlds and chance classes hang below an edge, our decision nodes are information sets fixed by the digest. Splitting a world cell or a chance class adds leaves under the same edge and never re-targets an edge between decision nodes, so bounds tighten monotonically by adding leaves, which is MADS's own partial-expansion semantics (unexpanded = envelope). No epoch invalidation of the decision graph is needed |
| acyclic contract | an abstraction can quotient an acyclic exact graph into cycles (two exact states in one cell with edges both ways), so CARDS needs least/greatest fixed points over abstract SCCs | the tree is depth-indexed by turn and the cells live under edges, so no abstract cycle appears; the SCC machinery is unnecessary |
| partial-order reduction on exact states | POR certificates need exact-state equality after an order swap, which means materialising the very states CARDS keeps symbolic | the engine orders actions within a turn (speed), so there is no player-chosen order to reduce; the one POR-like reduction (bench order at team preview) is an exact-state certificate independent of any cell, and it stays a MADS-style certificate (point 6 above) |
| two schedulers (root-critical `ExpansionTask` vs `RefinementObligation`) | two priority units with no principled exchange rate between "expand exact work" and "refine representation"; the owner's note expects bookkeeping overhead | both units become **unresolved leaves of one interval Bayes game**: an unexpanded joint action (MADS) and an unsplit cell (CARDS) are ranked by the same quantity, the root interval width they block, weighted by the reach probability and the cell's mass. The scheduling reference for simultaneous moves is SMAB (Saffidine et al. 2012: bounds on stacked matrix games, pruning by LP feasibility) plus double oracle, not MADS's incumbent/challenger pair, because the root proof is about a mixed solution's value, not one pure action |
| certified and anytime modes, the RNG firewall, the oracle suite caps, paired-state key audits | no collision | carry over unchanged; the firewall exists (search seeds, decision 0022), the oracle is the exhaustive endgame enumerator, the key audit is D3's method |

**Verdict.** The hypothesis holds, and for a structural reason stronger than "transpositions are rare": in Pokémon
the CARDS cells (hidden worlds, chance classes) are a dimension *below* the decision graph, while in Magic the cells
*are* nodes of the decision graph. That is why the two concepts fight in Magic (a split rewires the DAG) and compose
in Pokémon (a split adds leaves). What survives of MADS here is exactly what the HauptSession named, bounds and
scheduling: the partial-expansion envelope for uncovered foe responses, certified and anytime modes, the key audit;
what is dropped (exact TT, incremental reverse propagation, POR) has little to merge in this game. What survives of
CARDS is the sound-cell invariant and the counterexample-driven split; what is dropped (symbolic prefix coverage,
SCC closure) has no object here. The combined solver is a bound-guided, counterexample-refined interval Bayes LP over
a digest-keyed tree, which is P3 with P1's classes and P4's cells. Its proof obligations are smaller than either
original: no replay-sufficiency lemma (choices are complete and canonical), no producer-domain closure (worlds are
finite and sampled, classes are enumerated), but one new one, the interval LP's soundness under per-world foe best
responses. Two caveats: the composition is only *sound* where leaves are exact (endgames), and whether refinement
beats plain enumeration is the measurement of section 6's experiment, not a given.

## 7. Ranking by expected value per cost, and the order

| rank | piece | expected value | cost | why this rank |
|---|---|---|---|---|
| 1 | P1 exact chance with refined classes | medium alone (the one-turn gain is likely small), high as the enabler of P3, P4, P5 and of less noisy labels | engine days, no training | the cheapest decision with the widest reach; two of its three tests need no network |
| 2 | P2 relation classes | high: the evidence points at evaluation and choice | a C query (days), one training go, offline evaluation hours | testable offline on existing rows before any self-play |
| 3 | P3 certified endgames | medium–high: endgames and threats are where games are lost (role check); the certificate is a product feature (#604 analysis) | mostly Python on built pieces, needs P1 | isolates search from the value head: the clean "search alone" measurement the owner asked for in #440 |
| 4 | P4 belief cells and foe model | medium (PokaiTrainer's +8–12 pp is confounded); the foe-model gain of +5.4 points is already measured | Python plus P1, one training go for the rated model | the human-side gains need human play, which is restricted |
| 5 | P5 counterfactual distillation | highest if it works; C2's failure and the thin teacher signal say "not yet" | training runs, AWS later | the destination; it needs P1–P3 to make the teacher worth distilling |

Before any of them, two cheap methodology items shrink every later run: the paired variance measurement (#356) and
SPRT (#375); both are hours of work on the existing ladder and are prerequisites for runs on a slow VPS or paid AWS.
When ML resumes (after Champions 100 %), the order is: P1 engine piece and its offline tests; P2 offline on BC rows;
P3 on harvested endgames; then the D2 ladder arms with P1 inside; P4; P5's learning curve. Each step is measured on
its own before the next is stacked (the M13 exit rule).

## 8. What probably does not fit, and why

- **Chess-style NNUE with incremental accumulators** (#376): a doubles turn changes many inputs (HP of several
  Pokémon, status, boosts, field, switches), the accumulator would have to be copied along chance and simultaneous
  nodes, and the need here is breadth (worlds × joint actions), not depth; the community's counter-arguments of
  2026-10-23 and the in-engine evaluation spec (no incremental goal) agree. The part that survives is P2: engine-
  computed relation inputs for any architecture. The entity-level cache (#655: cache unchanged members' embeddings,
  update the sum pool incrementally, recompute the max) is a free implementation detail of C inference, not an
  algorithm, and must stay byte-identical.
- **A full ReBeL / public-belief-state recursion**: the hidden space (six 66-point spreads, under closed sheets whole
  sets) is far beyond poker's, which is DeepNash's reason for model-free play in Stratego; DuoForge's sampled or
  clustered worlds (P4) are the tractable form, Student of Games's structure the long-term shape.
- **A large transformer PPO run** (mikumiku37 8.7M, Jaxcalibur 8.5M on one H100-week): the machine has 8 GB and the
  owner's lever is exactness, not scale; the random-teams experiment (#450) covers generalisation at the current size.
- **LLM agents** (PokéChamp): 1300–1500 Elo projected, no exactness, no determinism.
- **Decoupled UCT**: exploitable in VGC by measurement (PokaiTrainer: 83.6 % for the informed best response); RM with
  the prior stays the default, UCB an arm with exploitability as the metric.
- **More one-turn budget, team preview as a Nash game, a wider preview**: measured flat or harmful (section 2).
- **Tablebases**: the state space (HP, PP, status, field) and hidden information rule them out; the depth-limited
  exact endgame (P3) is the practical form.
- **R-NaD or MMD as the main learner**: closed by the owner (#359); the regularisation lives on as a magnet arm in
  the search and as `--policy-objective mmd` for a comparison.
- **A "scouting bonus" for information**: information must pay through later decisions (the digest-keyed tree, #373);
  the VOI planner literature (Laouar et al. 2026) prunes observation branches, which is a budget trick, not a reward.
- **A learned belief network trained only on our self-play for ladder use**: it learns our pool's spreads, not human
  ones (roadmap note of 2026-10-09); the exact filter (P4) needs no training data and the Smogon prior stays the
  prior.
- **Exploiter league before a stable learner**: the owner's order (#369) stands; the no-training pre-stage (our bot
  as the foe model of the opponent's search, exploitability as a standing metric) is the cheap version.

## 9. Open points for the owner and the HauptSession

1. P1 is an engine decision (#358): the enumeration call, the class keys in C, the public tape variant, number
   assignments by the HS.
2. P2 needs the damage and speed query (#604 stage 1, #366) or a probe path, plus encoder 7.
3. P3 waits for the D2 ladder arms (not run since ML paused) and P1.
4. P5 and the rated model each need a training go; the AWS run only after the local learning curve.
5. The CARDS/MADS transfer is a design discipline, not a separate lane: it enters P1 (classes), P3 (certificates,
   state-key audit) and the search's diagnostics (uncovered-response mass). A separate "CARDS-DF" implementation is
   not recommended before the endgame experiment of section 6 has a result.
6. Champions singles (decision 0083): everything above transfers; the matrices shrink to one slot per side, and
   certified endgames become easier (one Pokémon per side with exact rolls).

## 10. Sources

Repository (paths as of main `de746106`): `AGENTS.md`; `docs/process/LANES.md`; `docs/ROADMAP.md`;
`docs/ARCHITECTURE.md`; decisions 0017, 0021, 0022, 0023, 0024, 0081, 0082, 0083;
`docs/superpowers/specs/2026-10-13-depth-search-design.md`, `2026-10-14-in-engine-evaluation-design.md`,
`2026-10-05-m12-expert-iteration-design.md`, `2026-10-10-m11-bo1-belief-design.md`,
`2026-10-11-m13-human-model-by-rating-design.md`; `docs/superpowers/plans/2026-10-11-mmd-objective.md`;
`docs/benchmarks/2026-10-01-batch-scaling`, `2026-10-02-python-loop`, `2026-10-11-honest-search-breakdown`,
`2026-10-11-live-arena`, `2026-10-11-foe-model-arena`, `2026-10-12-search-ladder`, `2026-10-13-network-diagnosis`,
`2026-10-13-preview-exploitability`, `2026-10-14-d1-offline`, `2026-10-14-depth-d2`, `2026-10-14-cts-luck`,
`2026-10-15-bc6-monotone`, `2026-10-15-evaluation-graphs`; `docs/learning/2026-10-02-night`,
`2026-10-09-stage3-p2`, `2026-10-10-stage3-p1-result`; `docs/research/expansion/champions-100.md`; issues #355–#385,
#418, #433, #440, #450, #451, #481, #485, #494, #495, #498, #509, #604, #655; `src/rng/draw.h`, `src/rng/draw.c`,
`src/search/search.c`, `src/eval/`, `src/encode/encode.c`, `include/duoforge/*.h`, `python/duoforge_search/`.

External (verified = abstract or page read by this session; second-hand = reported by a search summary only):
- Brown, Bakhtin, Lerer, Gong. Combining deep RL and search for imperfect-information games (ReBeL). NeurIPS 2020.
  arXiv 2007.13544. Verified.
- Schmid et al. Student of Games. Science Advances 2023; arXiv 2112.03178. Verified.
- Sokota et al. Scalable decision-making for games of imperfect information (Ataraxos). Nature 2026; arXiv
  2511.07312. Verified (methods read).
- Perolat et al. Mastering the game of Stratego with model-free multiagent RL (DeepNash). Science 2022; arXiv
  2206.15378. Verified.
- Sokota et al. A unified approach to RL, QRE and two-player zero-sum games (MMD). ICLR 2023; arXiv 2206.05825.
  Verified.
- Kubíček, Lisý, Sandholm. Test-time RL in imperfect information games. arXiv 2608.30635. Verified (abstract);
  critique: pith.science review (AI-generated, unverified).
- Moravčík et al. DeepStack. Science 2017; arXiv 1701.01724. Verified.
- Brown, Sandholm. Safe and nested subgame solving. NeurIPS 2017; arXiv 1705.02955. Verified.
- Brown, Sandholm, Amos. Depth-limited solving for imperfect-information games. NeurIPS 2018; arXiv 1805.08195.
  Verified.
- Milec, Kovařík, Lisý. Adapting beyond the depth limit (matrix-valued states). AAMAS 2025; arXiv 2501.10464.
  Verified (abstract).
- Long, Sturtevant, Buro, Furtak. Understanding the success of PIMC sampling. AAAI 2010. Second-hand (abstract via
  search).
- Cowling, Powley, Whitehouse. Information set MCTS. IEEE TCIAIG 2012. Second-hand.
- MAPLE: Multi-state aggregated policy evaluation for AlphaZero in imperfect-information games. arXiv 2605.24139,
  CoG 2026. Verified (abstract).
- Solinas et al. Belief Embedding Tree Search. arXiv 2610.15046. Verified (abstract).
- Bošanský, Lisý, Lanctot, Čermák, Winands. Algorithms for computing strategies in two-player simultaneous move
  games. AIJ 237, 2016. Second-hand. Bošanský et al. Double oracle and serialized alpha-beta for simultaneous moves,
  IJCAI 2013. Second-hand. Saffidine, Finnsson, Buro. Alpha-beta pruning for games with simultaneous moves (SMAB). AAAI
  2012, vol. 26, pp. 556–562. Verified (abstract).
- Lisý, Kovařík, Lanctot, Bošanský. Convergence of MCTS in simultaneous move games. NeurIPS 2013; arXiv 1310.8613.
  Second-hand. Kovařík, Lisý. Analysis of Hannan consistent selection for MCTS in simultaneous move games. arXiv
  1804.09045. Verified (abstract).
- Li et al. CFR-MIX. IJCAI 2021; arXiv 2105.08440. Second-hand. Farina et al. Regret circuits. arXiv 1811.02540.
  Second-hand.
- Anthony, Tian, Barber. Thinking fast and slow with deep learning and tree search. NeurIPS 2017. Second-hand.
- Danihelka et al. Policy improvement by planning with Gumbel. ICLR 2022. Verified (abstract).
- Ugadiarov et al. ReSCALE. arXiv 2603.21162. Verified (abstract).
- Tsai et al. Regret-guided search control for efficient learning in AlphaZero. ICLR 2026; arXiv 2602.20809.
  Verified (abstract via mirrors).
- Molfetta et al. Self-play search distillation for LLM reasoning. arXiv 2609.30936. Verified (abstract; an LLM
  paper, only the record format transfers).
- Zhang et al. π-Play: multi-agent self-play via privileged self-distillation. arXiv 2604.14054. Verified
  (abstract; an LLM-agent paper, only the privileged-teacher idea transfers).
- Burch et al. AIVAT. AAAI 2018; arXiv 1612.06915. Verified (abstract). AV-AIVAT. arXiv 2608.06362. Verified
  (abstract).
- Schmid et al. VR-MCCFR. AAAI 2019. Second-hand.
- Glasserman, Yao. Some guidelines and guarantees for common random numbers. Management Science 1992. Second-hand.
- chessprogramming.org, Sequential Probability Ratio Test; Fishtest wiki. Verified (pages via search summaries).
- Laouar, Ho, Sunberg. Leveraging the value of information in POMDP planning. arXiv 2604.01434. Verified (abstract).
- Max Yu. PokaiTrainer: scaling equilibrium search to competitive Pokémon VGC. arXiv 2608.29197 v2. Verified (full
  text read); critique: pith.science review (AI-generated).
- nessie_dev. Nessie123: an OTS VGC bot that topped the Reg M-C Bo3 ladder. Smogon thread 3789213. Verified (thread
  read).
- mikumiku37. Smogon programming thread and the author's announcement. Second-hand (ladder numbers via search
  summaries).
- Jaxcalibur project page (jaxcalibur.github.io). Verified (page read).
- pmariglia. Foul Play (blog post). Verified (page read).
- Grigsby et al. Human-level competitive Pokémon via scalable offline RL with transformers (Metamon). RLC 2025;
  arXiv 2504.04395. Verified (abstract).
- Karten, Nguyen, Jin. PokéChamp. ICML 2025; arXiv 2503.04094. Verified (abstract).
- Angliss et al. VGC-Bench. AAMAS 2026; arXiv 2506.10326. Verified (abstract).
- lab-oak/oak (GitHub README and TUTORIAL.md). Verified (pages read).
- Clarke, Grumberg, Jha, Lu, Veith. Counterexample-guided abstraction refinement. CAV 2000; JACM 2003. Verified
  (citation). Chatterjee, Henzinger, Jhala, Majumdar. Counterexample-guided planning. UAI 2005; arXiv 1207.1373.
  Verified (citation).
- Li, D.-F. Linear programming approach to solve interval-valued matrix games. Omega 2011; Hladík, M. Interval
  valued bimatrix games. Kybernetika 2010. Second-hand.
- The owner's private notes CARDS V0.2.3 and MADS V0.4 (2026-09-27, 2026-09-26). Read; referred to by name only.
