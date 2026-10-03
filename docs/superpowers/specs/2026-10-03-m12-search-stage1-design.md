# M12 stage 1: one-turn lookahead — specification

Decision: 0022 (search support), written with the plan. Builds on decisions 0002 (privileged operations, reseed), 0012 (batch runtime), 0013 (Python adapter; section 6 names search support), 0014 (value targets), 0017 (suite and ladder), 0018 (view extension, encoders 3 and 4) and 0021 (the C encoder, in progress). Status: **approved** by the owner on 2026-10-03.

## 1. Goal

Stage 1 of roadmap M12 is a one-turn lookahead on top of the learned policy and value. The engine is the exact model: the search copies the state and steps the copy. At a decision the searcher:
1. takes its policy's best own joint choices ("pairs": the two slot commands of one side);
2. takes the opponent's likely pairs from a policy;
3. steps a copy of the state for every own pair against every opponent pair, over sampled random outcomes;
4. scores each resulting state with the value head;
5. reduces the table of own by opponent pairs to one choice.

Stage 1 runs and is measured in the arena, on the true battle state where both seats are known. That is an oracle benchmark in the sense of ARCHITECTURE §10 and is labeled as one (section 3). It is measured against the same network without search, at a stated compute budget per decision.

Not in stage 1: live play on Showdown. There the foe's stat points are hidden, so the search needs states built from an observation and a sampled hypothesis. Section 9 names that interface so stage 1 does not block it.

Success is the report of section 8.6. No Elo threshold is a merge condition for the code; the gate in section 8.6 decides whether stage 2 starts.

Terms:
- **Pair:** one side's joint choice, an entry of the factored domain (decision 0013).
- **Leaf:** a copy of the root after one step with one own pair, one foe pair and one chance sample.
- **Table:** A[i, j], the mean leaf value of own pair i against foe pair j.
- **Budget:** the number of leaves per decision.

## 2. Decisions and agreements (2026-10-03)

**Owner**
- **Reduction:**
  - The Nash equilibrium of the table is the main rule: a mixed strategy, the move drawn from a seed.
  - The expected value under the opponent policy is measured beside it, on the same table.
  - Maximin is not built.
  - The number of chance samples per cell is fixed and equal for both rules. The Nash solution reacts more strongly to noise in the table than the expected value, so the comparison must be fair.
- **Opponents:**
  - The main comparison is the search against the same network without search.
  - A panel of older checkpoints is added. Against it the raw network and the search play the same games, paired, so the gain is also measured where the opponent model is wrong.
- **Architecture A:** Python orchestrates the search; the engine gets one new parallel batch call.
  - Not a C search core: the engine stays a pure simulator, and the network runs in JAX either way.
  - Not a Python loop over single-battle bindings: that is single-threaded and costs about 5 to 9 ms more per decision.
- **Decision number:** 0022. Number 0021 is reserved for the C encoder of learner v2.
- **Encoder:** the new call encodes the leaves with decision 0021's C encoder (`duoforge_batch_query_encoded`), in the worker threads, not in Python.
- **The design:** its three sections (architecture; the search; the measurement and the live interface) were approved as presented.

## 3. Findings that shape the design

- **The batch runtime cannot load a state.**
  - Environments are created from setups and reset from the seed derivation (decision 0012).
  - No call puts a given state into an environment, and the Python package binds no single-battle copy, reseed or step.
  - Decision 0013 section 6 names this as the first function search needs.
- **Search on the true state is an oracle.** ARCHITECTURE §10 sets the rules:
  - a fair planner builds hypothetical states from its own observation, with a separate search RNG;
  - planning on a privileged snapshot is an oracle benchmark and must be labeled so;
  - copy and reseed are privileged operations (decision 0002), and reseed exists to decorrelate a forked copy for search.
- **A copy of the true state carries the real future.**
  - The battle holds its gameplay RNG. A child stepped without a reseed would see this turn's real damage rolls, critical hits and accuracy.
  - Every leaf is therefore reseeded from the search seeds before it steps (section 6).
- **What the oracle still knows:** the foe's stat points and the stats they give, its exact HP, and the secret counters of both sides (sleep and confusion turns and the like). Section 9 replaces these by sampled hypotheses.
- **The engine is cheap, the network is not.**
  - Engine, on one Zen 3 core with the CLOSURE teams (`docs/benchmarks/2026-10-01-closure-pairings-v1`):

    | Call | Measured rate | Time per call |
    |---|---|---|
    | state copy | 8.9 to 10.5 million per second | about 0.1 µs |
    | step | 301,000 to 366,000 steps per second | about 2.7 to 3.3 µs |
    | request, candidates and observation | 246,000 to 304,000 per second | 3.3 to 4.1 µs |

  - The batch runtime reaches about 6 times one worker on 8 physical cores (`docs/benchmarks/2026-10-01-batch-scaling`).
  - Network (`docs/learning/2026-10-03-learner-v2-abc`): `act` on 512 rows takes 2.87 ms on the GPU and 60 ms on the CPU for v2-M, and 1.76 ms and 31.9 ms for v2-S.
  - NumPy encoder: about 4.5 µs per row (0.073 to 0.078 s per 32 steps of 256 environments and both seats).
- **The policy is factored.**
  - Model v2 scores the 32 × 32 pairs of the two slot lists (1024 entries, masked by the pair rule), plus 360 team tuples.
  - It gives one value per row, from the row's own view. The value is trained on +1, −1 and 0, discounted per own decision.
  - The value does not read the slot inputs.
- **Value targets cover waiting rows.** The value is trained on every row, also where the seat waits (decision 0014 section 5). The value at a REPLACEMENT or PIVOT boundary where only the foe is asked is therefore in distribution.
- **The arena exists.**
  - `evaluate.play_suite` plays greedy players over a suite. It scores a game still running after `max_steps` by the reference's tiebreak ("unfinished"). A game the engine refuses (E_UNSUPPORTED) is the learner's loss ("unresolved").
  - `suite.make_suite` stratifies the games by team.
  - `ladder` fits Bradley-Terry Elo with bootstrap intervals.

## 4. Architecture

### 4.1 Parts

- **Engine (C), decision 0022:**
  - one new batch call, `duoforge_batch_expand` (working name);
  - the search seed derivation as a pure public function, like `duoforge_batch_seeds`.

  The engine holds no search logic: it copies, reseeds, steps and encodes.
- **Bindings:** thin wrappers in `python/duoforge` (`Batch.expand`, the seed function). They contain no rules.
- **Search (Python), a new package `python/duoforge_search/`:**
  - the root policy and the candidate selection;
  - the decision keys;
  - the leaf rounds and the value calls;
  - the table, the reductions and the per-decision record;
  - the arena driver.

  Indicative modules are `seeds.py`, `lookahead.py`, `matrix.py` and `arena.py`; the plan fixes them. The search knows no rule:
  - legality comes from the engine's factored domain;
  - outcomes, results and the tiebreak come from the engine;
  - values come from the network.
- **Model:** a value-only call beside `act` in `duoforge_learn.policy.Model`, since the leaves need no policy.
- **Opponent model:** an interface `OpponentModel` that gives the foe's pairs and their probabilities for a root.
  - Stage 1: the searcher's own network on the foe's row.
  - Later: the human-play model (M13 lever 2).

### 4.2 One search round

The arena runs E games in one batch, as `play_suite` does. At each step:
1. The arena queries every game: requests, factored domains, and the encoded rows of both seats.
2. One policy call over the roots' rows gives each seat's 1024 pair log-probabilities.
3. For every game where the searcher must decide, section 5.1 picks K′ own and M′ foe pairs. With S samples that makes K′ · M′ · S leaves per decision.
4. `expand` steps all leaves of all these decisions, in chunks of at most L leaves.
   - L is a configuration value, chosen by measurement; the default is 16,384, that is 16 decisions at the main budget.
5. One value call per chunk, padded to L rows, so there is one compiled shape.
6. Per decision: the table, the choice, the record.
7. The arena steps every game with the chosen indices, the opponents' greedy indices included.

The search takes, per decision, a list of weighted root states. Stage 1 passes one root, the true state, with weight 1; stage 2 passes several worlds (section 9).

### 4.3 The engine call (decision 0022)

**Status of this section.** It is written against the C encoder's interface on the branch `chris/encoder-in-c` at 8515e21: `include/duoforge/duoforge_encode.h`, `docs/decisions/0021-encoder-in-c.md` and `docs/superpowers/specs/2026-10-03-encoder-in-c-design.md`. The layout is fixed: encoder 4, decision 0018 §10.2, obs width 850. Once 0021 is merged, this section is checked against `main` again. At most a detail should change, for example a parameter name or the refusal order.

**Declarations** (in `include/duoforge/duoforge_search.h`, which includes `duoforge_encode.h`):

```c
/* The leaf seeds of (seed, key, sample): rng_initstate and an rng_initseq
   below 2^63 (decision 0001), splitmix64 with the tags of decision 0022. */
void duoforge_search_seeds(uint64_t seed, uint64_t key, uint32_t sample,
                           uint64_t *out_initstate, uint64_t *out_initseq);

duoforge_status duoforge_batch_expand(
    duoforge_batch *leaves, const duoforge_batch *roots,
    uint32_t version, uint64_t ext_supported, uint64_t seed,
    const duoforge_request *root_requests,          /* 2 * root envs, as the roots' query wrote them */
    const duoforge_factored_domain *root_domains,   /* 2 * root envs, likewise */
    const uint64_t *keys,                           /* root envs: the decision key */
    const uint8_t *viewers,                         /* root envs: the searching seat, 0 or 1 */
    uint32_t count,                                 /* leaves, at most the leaf batch's env_count */
    const uint32_t *root_envs,                      /* count: the root environment of leaf i */
    const uint32_t *samples,                        /* count: the sample index */
    const duoforge_factored_choice *choices,        /* 2 * count: player p's choice at 2 * i + p */
    duoforge_status *step_statuses,                 /* count */
    duoforge_status *encode_statuses,               /* count */
    duoforge_step_result *results,                  /* count */
    uint32_t *leaf_results,                         /* count: DUOFORGE_RESULT_* at TERMINAL, else 0 */
    float *obs);                                    /* count * duoforge_encoder_size(version) */
```

**Inputs**
- **The leaf batch:** an ordinary batch of L environments, created once with the roots' context. Leaf i is environment i. Every leaf environment is overwritten at each call, so its setup does not matter.
- **The root batch:** in stage 1 this is the arena batch itself. `root_requests` and `root_domains` are the arrays its `duoforge_batch_query_encoded` (or `_query_factored`) wrote, indexed 2 · env + p as there. `keys` and `viewers` are read only for root environments that some leaf names.
- **Choices:** a player whose root request has `requested` 0 gets no response, and its choice entry is ignored, as in `duoforge_batch_step_factored`.

**Per leaf**, on the leaf batch's workers, in one pass:
1. The leaf environment becomes a copy of its root (`duoforge_battle_copy`, no allocation).
2. It is reseeded with `duoforge_search_seeds(seed, keys[root], samples[i])` (section 6).
3. It is stepped with the bundle of the two factored choices. The bundle is built and checked exactly as `duoforge_batch_step_factored` builds it. `step_statuses[i]` and `results[i]` receive the outcome.
4. If the step succeeded and the leaf is TERMINAL: `leaf_results[i]` is its result, the obs row is all zero and `encode_statuses[i]` is OK. A TERMINAL leaf is scored by its result and needs no row.
5. Otherwise the viewer's request, observation, factored domain and view extension are taken as `duoforge_batch_query_encoded` takes them for one player. `duoforge_encode(version, ext_supported, …)` then writes obs row i. The slots and pair mask the encoder also produces go to stack buffers of the leaf (3 KB and 1 KB), as `duoforge_batch_query_encoded` keeps its observation, domain and extension on the stack, and are not returned.

**Contract**
- **Atomic per leaf**, as in decision 0012. Two status arrays keep the engine's refusals apart from the encoder's: a failed step leaves `encode_statuses[i]` OK and the row all zero. The call returns the lowest failing leaf's step status, else its encode status, else OK.
- **The roots are only read** and must not change during the call. Only one caller uses either batch at a time.
- **No allocation per call:** the leaf batch and the output arrays exist before the call, and a leaf's temporaries live on the stack.
- **Equivalence:** leaf i equals `duoforge_battle_copy`, `duoforge_battle_reseed`, the factored step and then `duoforge_batch_query_encoded`'s row of the viewer for that environment, byte for byte, for every worker count.
- **Checks before any leaf is touched:**
  - an unknown version, or a mask past the version, is E_INVALID_ARGUMENT, exactly as `duoforge_encode` checks it;
  - a NULL pointer, a count past the leaf batch, a root environment past the root batch, a viewer other than 0 or 1, or batches of different contexts are E_NULL_ARGUMENT, E_INVALID_ARGUMENT or E_CONTEXT_MISMATCH;
  - the same batch as leaves and roots is E_INVALID_ARGUMENT: a leaf would overwrite a root that other leaves read.
  - Their order: NULL, then the contexts, then the version and mask, then the rest (`include/duoforge/duoforge_search.h`).

### 4.4 Cost per decision

The estimate is for the main budget: K = M = 8 and S = 16, so 1024 leaves. It is built from the measurements of section 3; the plan's first measurement replaces it.

| Part | Estimate |
|---|---|
| Value of v2-M on 1024 rows, GPU | at most 5.7 ms (2 × 2.87 ms for 512 rows) |
| Engine and C encoder, 1024 leaves on 8 workers | about 1 to 1.5 ms (copy, step, then the viewer's request, observation, domain, extension and encoding: about 6 to 9 µs per leaf on one core, from the rates of section 3; POOL states and the C encoder are not yet measured) |
| Nash solution of an 8 × 8 table | under 1 ms |
| Root policy of both seats | one call shared by all games of a round |
| **Total** | **about 8 ms per decision** |

- On the CPU alone the value call dominates: about 120 ms for v2-M and about 65 ms for v2-S.
- With the NumPy encoder in place of decision 0021, the leaves would cost about 5 ms more.

## 5. The search

### 5.1 Candidates

- **Own pairs:** the K = 8 pairs with the highest policy probability among the 1024 masked pairs.
- **Foe pairs:** the M = 8 pairs with the highest probability under the opponent model, from the foe's row of the root.
- **Small domains:** with fewer legal pairs, K′ or M′ is the domain size.
- **A foe without a request:** M′ = 1, its empty response.
- **Equal probabilities:** the lower flat pair index ranks first.
- **Recorded:** the coverage of the foe's pairs, that is the sum of their probabilities.

### 5.2 Chance

- **Samples:** S = 16 per cell, fixed, and the same for both rules.
- **Common random numbers:** sample s has the same seeds in every cell (section 6). The difference between two cells then measures the pairs, not a different luck.

### 5.3 Leaves

A leaf is the first decision boundary after the step: TURN, REPLACEMENT, PIVOT or TERMINAL. Its value:
- **Not terminal:** the value head on the viewer's row.
- **TERMINAL:** the exact result from the viewer's side: +1, −1, or 0 for a tie.
- **At the arena's cut-off** (this step reaches `max_steps`): the reference's tiebreak (`Batch.tiebreak` on the leaf environment), as the arena scores that game. A tiebreak the engine cannot resolve counts −1, as in `play_suite`.

The leaves are not stepped further. A PIVOT leaf is mid-turn; how often leaves are PIVOT is reported (section 8.5).

### 5.4 The table

- A[i, j] is the mean leaf value over the S samples.
- The standard error of every cell is recorded.
- Both rules read this same table.

### 5.5 The reductions

- **Nash (main rule, agent N):**
  - The table is solved as a zero-sum matrix game by an exact linear program, in NumPy with float64: a small dense simplex with Bland's rule. No new dependency.
  - **Certificate:** the exploitability max_i (A y)_i − min_j (xᵀA)_j of the solution (x, y) must be at most 1e-9. Otherwise the run stops and writes the table.
  - **The move:** drawn from x by the decision's play seed (section 6). Probabilities below 1e-9 count as 0; the rest is renormalized.
- **Expected value (agent E):**
  - The own pair with the highest Σ_j q_j A[i, j].
  - q are the foe pairs' probabilities, renormalized over the M′ pairs.
  - No draw.

### 5.6 Ties

- Comparisons are exact.
- The first tie-break is the higher own policy probability, the second the lower flat pair index.
- The Nash draw walks the own pairs in rank order: the first pair whose cumulative probability exceeds the draw is played.

### 5.7 Decision kinds

| Root | Handling | Counted as |
|---|---|---|
| TEAM_SELECTION | No search; the raw network chooses. Team preview by simulation is M13 lever 8 | team selection |
| TURN, REPLACEMENT, PIVOT with at least 2 own pairs | search | searched |
| exactly 1 own pair | no search, the pair is played | forced |
| the searcher is not requested, or TERMINAL | no decision | — |

## 6. Seeds and determinism

**Seeds**
- **The search seed:** a run parameter, written to the record.
- **The decision key:** 64 bits.
  - Arena: a splitmix64 chain over the arena seed, the environment, the episode, the root's request epoch and the seat.
  - Live (stage 2): the game id, the request epoch and the seat.
- **Leaf seeds:**
  - The engine's pure function of (search seed, key, sample) gives `rng_initstate` and an `rng_initseq` below 2^63 (decision 0001).
  - It is splitmix64 with tags documented in decision 0022, in the manner of `duoforge_batch_seeds`.
  - They depend on these three values only: never on a worker, a chunk, the leaf's position or the cell (i, j).
- **The play seed:** the same derivation with its own tag. It gives a uniform number in [0, 1) with 53 bits.
- **Separate streams:** search seeds are separate from the gameplay RNG, the arena seeds and the policy seeds (`docs/DETERMINISM_AND_REPLAY.md`).

**Determinism**
- **The engine part is bit-exact:** the same leaves and the same digests for every worker count.
- **The network:**
  - The batch shape is fixed by padding.
  - XLA's deterministic GPU ops are on.
  - Games are processed in a fixed order, so every round has the same composition on a rerun.
  - A rerun with the same seeds, checkpoint, library, JAX version and device reproduces every decision bit for bit. The report states the device and the versions.
- **The reductions:** float64 in NumPy, on the network's float32 values.
- **The budget is a count of leaves, never a time.** A time budget would make the choice depend on the machine; the time per decision is measured and reported beside it.

## 7. Failure modes

Every case is explicit and counted. There is no fallback to the raw network inside a search.

| Case | Handling |
|---|---|
| Leaf TERMINAL | exact result (section 5.3) |
| Leaf at the arena's cut-off | tiebreak; unresolvable counts −1 (section 5.3) |
| Leaf refused (E_UNSUPPORTED) | value −1, marked refused. The arena scores a game the engine refuses as the agent's loss, and the leaf is scored the same way |
| Leaf E_INVARIANT | the run stops; the root's bytes (privileged encode), the pair and the seeds are written for reproduction |
| Leaf E_INVALID_ARGUMENT, E_STALE_EPOCH, E_CAPACITY or E_EXHAUSTED | the run stops: a bug in the caller, or a counter overflow |
| The C encoder refuses the version or mask | the run stops before any leaf (checked once per call) |
| The C encoder refuses a leaf's row (`encode_statuses[i]`: a value the mask cannot show, such as Sand without its bit, or a malformed record) | the run stops and writes the leaf's reproduction data. The network cannot read that state, and scoring it −1 would bias the search against the moves that lead there |
| An id the model cannot embed (`Model.check`) | the run stops, as the arena does today |
| The Nash certificate is missed | the run stops and writes the table |
| Root TEAM_SELECTION, forced or not requested | section 5.7 |
| A game cut off or refused in the arena itself | as in `play_suite`: unfinished (tiebreak) or unresolved (loss), counted |

## 8. The arena measurement

### 8.1 Network and teams

- **The network:** the best checkpoint of the many-team run, by that run's own ladder (v2-M at the time of writing). The report names it and its update.
- **The teams:** the checkpoint's pool, as its run directory records it (`ladder._pool_of`). At the time of writing that is the 79 `PP_` teams plus A, B and C, N = 82.

### 8.2 Agents and opponents

**Agents**
- **R:** the raw network, greedy (`evaluate.Player`).
- **N:** R plus the search with the Nash rule.
- **E:** R plus the search with the expected-value rule.

**Opponents**
- **Main comparison:** N against R, and E against R.
- **Panel:** three older checkpoints of the same run, those nearest to 25, 50 and 75 percent of its updates, playing greedy.
  - R, N and E each play the same suite rows with the same arena seed against every panel member.
  - Per row the paired differences are N − R and E − R.
- In stage 1 the searcher's own network is also its opponent model. Against R the model is exactly the opponent; against the panel it is wrong.

### 8.3 Games and confidence intervals

- **Suite:** `make_suite(82, seed, budget=2048)`.
  - Each team is the agent's own team about 25 times, its opponents spread by the suite's permutation, the seats alternating.
  - Every agent and opponent plays the same rows and the same arena seed.
- **Cut-off and refusals:** `max_steps` is 1000, as in `play_suite`. Unfinished and unresolved games are counted and shown.
- **Score:** the mean over the games, a tie counting half.
  - **95 % interval:** bootstrap over the suite rows, 2,000 resamples, fixed seed.
  - **Elo:** 400 · log10(s / (1 − s)), the interval mapped the same way.
  - **Expected half-width at 2,048 games:** about 2.2 percentage points of score, about 15 Elo near 0.5.
- **Panel:** the paired difference per row, bootstrapped over the rows, given as score and as Elo.

### 8.4 Budget

- **Main point:** 1024 leaves per searched decision (K = M = 8, S = 16), plus the root rows. The raw network uses one row per decision.
- **Sweep:** against R only, for N and E:
  - S ∈ {4, 64} at 8 × 8;
  - K × M ∈ {4 × 4, 16 × 16} at S = 16.

  That is 256 to 4,096 leaves per decision. The S points show how much the noise of section 5.2 costs each rule.
- **Measured per configuration:**
  - the ms per searched decision (median and p95), split into network, engine and reduction;
  - the device and the library and JAX versions;
  - the searched decisions per game.
- **Estimated cost:** about 4 to 5 minutes of GPU for each main-point configuration (2,048 games, about 15 to 18 searched decisions each, 8 ms each).
  - The S = 64 and 16 × 16 points cost four times that.
  - The whole measurement is about 25 such units, about 2 hours. (The design discussion said 1 to 1.5 hours; that missed the four-fold sweep points.)
- **When:** only in the daytime. No GPU and no heavy job from 21:30 to 06:00, when the night training run owns the machine.

### 8.5 Diagnostics

Each searched decision gets a record; the report summarizes the records:
- the game row and step, the root's boundary, K′, M′ and S;
- both sides' pairs with their probabilities, the table and its standard errors;
- the Nash strategies, the game value and the support sizes;
- the chosen pair, the raw network's argmax, and whether they differ;
- the coverage of the foe's pairs;
- **split-half stability:**
  - the tables of samples 1 to 8 and of 9 to 16 are compared;
  - for the expected value: how often both halves give the same choice;
  - for Nash: the exploitability of one half's strategy in the other half's table;
- the leaf boundaries (TURN, REPLACEMENT, PIVOT, TERMINAL);
- refused leaves, cut-off leaves, forced decisions and team selections;
- the time split.

### 8.6 Report and gate

- **The report:** `docs/learning/<date>-m12-stage1/README.md` with `raw/` (the records and a per-game table), in the manner of the learning reports. It is titled and labeled as an oracle benchmark (section 3).
- **The gate to stage 2:** both conditions must hold.
  - N against R has a lower 95 % bound above 0.5.
  - The paired panel difference N − R, over all three panel members, is positive with an interval that excludes 0.

  Otherwise a cause analysis (noise, coverage, the value head) comes before stage 2.
- **The roadmap's M12 exit,** the Elo gain on the ladder at a fixed time per move, needs stage 2.

## 9. The live-play interface (stage 2, named, not built)

- **`Hypothesis`:** the hidden values of one world:
  - the foe's stat points per member;
  - the foe's exact HP within the shown percentage;
  - the secret counters.

  With closed team sheets (M14) it also holds the unrevealed sets.
- **`Belief.sample(view, history, n, seed)`:** gives a list of (hypothesis, weight) pairs. This is M13 lever 3, the belief over the hidden stat points. The first version draws from a prior.
- **The engine, a new public function with its own decision:** `duoforge_battle_from_view` (working name).
  - It takes a context, the player, the player's view and a hypothesis.
  - It builds a complete, fully checked battle: decision 0013 section 6.2, "determinization".
  - The view is what the live tracker holds: the observation and its extension, the own team's setup and the foe's open sheet.
  - The engine computes stats and HP from stat points, never Python.
  - The belief model needs an owner decision first (decision 0013 section 6.2).
- **The search:**
  - It takes these worlds as its weighted roots (section 4.2), all in one root batch.
  - Each world's foe row comes from the engine's view of that world for the foe.
  - The table is the weighted mean over worlds and samples, and one strategy is solved for all worlds, since the player cannot tell the worlds apart.
  - The foe's pairs are its top M by the world-weighted probability.
  - Sample s has the same seeds in every world.
- **`SearchPolicy.rank_pairs`:** gives a ranking like `duoforge_live.policy.Policy`: the drawn pair first, then by Nash probability, then by prior. A choice the server rejects is chosen again as today (#193).
- **The budget** stays a count of leaves, chosen to fit the time per move.

## 10. Tests

**C**
- **Equivalence:** `expand` equals copy, reseed, `step_factored` and encode one by one, for every leaf, with 1, 2, 3, 4, 8 and 16 workers, as decision 0012 tests the batch.
- **Seeds:** the search seed function is pinned by known values; the leaves do not depend on the worker or the chunk.
- **Isolation:**
  - a refused leaf leaves the others unchanged;
  - every leaf gets its own status;
  - the roots' digests are equal before and after the call.
- **No allocation per call:** checked with the method of the M6 evidence.
- **ThreadSanitizer** covers the new call, as it covers the batch tests.

**Python**
- **Nash:**
  - the certificate holds on random tables from 1 × 1 to 16 × 16, including degenerate tables and duplicated rows and columns;
  - the solution agrees with support enumeration up to 4 × 4;
  - pure saddle points are found exactly.
- **The expected value and the tie rules:** checked on constructed tables with equal entries.
- **Candidates:**
  - top K with ties to the lower index;
  - K′ and M′ for small domains;
  - M′ = 1 for a foe without a request.
- **Common random numbers:** sample s has the same seeds in every cell.
- **Purity:** the same decision twice gives the same table bit for bit; so does a decision alone and inside a full round, on the device used. A difference is reported, not hidden.
- **The raw network inside the search:** with K = 1 the search must play the raw network's argmax. N with K = 1 therefore reproduces R's games exactly, record for record.
- **End to end:** one decision on Teams A and B with a small fixed network gives a pinned table digest, on the CPU.

## 11. Not in this work

- live play, determinization and the belief (stage 2, section 9);
- tree search, two turns ahead and endgame solving (stage 2 and later);
- expert iteration (stage 3);
- team preview by simulation (M13 lever 8);
- exact chance nodes (M13 lever 16);
- a model of human play (M13 lever 2); the `OpponentModel` interface takes it later;
- a C search core.

## 12. Coordination

- **Order:** decision 0021's `duoforge_batch_query_encoded` lands on `main` first. Decision 0022 follows with the plan.
  - The plan may be written before that, against `chris/encoder-in-c` at 8515e21 (section 4.3).
  - After 0021 is merged, section 4.3 and the plan are checked against `main` once more.
- **API approval:** `duoforge_batch_expand` and the seed function are public API additions. The owner approved approach A in principle on 2026-10-03; decision 0022 records the final approval.
- **Process:** the implementation plan follows only after the owner approves this spec. The HauptSession merges.
- **Runs:** in the daytime only; no GPU from 21:30 to 06:00.
