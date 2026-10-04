# M12: the visible-information search — specification

Status: owner decisions of 2026-10-04 (the brief, and the brainstorming answers to questions 1 to 7). The owner approved sections 1 to 3 of the design on 2026-10-04. This specification goes up with the draft of decision 0023 as a docs PR. Nothing is implemented before the owner approves it; the implementation plan follows that approval.

The owner approved this specification, with the three points below, on 2026-10-04 ("Implementierung starten"). The plan is `docs/superpowers/plans/2026-10-04-m12-visible-search.md`.

Three points were added while writing it, after the design approval:
- **The queue mask** (section 4.3): a fifth public call, so that the rules deciding which foe pairs agree with the turn so far (question 7) stay in C.
- **Facts, not derivations** (section 4.3): the record's new fields are things the client shows or counts of them, so the live tracker needs no rule.
- **Leave one team out** (section 5.1): the foe's own team's sets are left out of the spread table in the arena and in self-play.

It follows the stage 1 specification (`docs/superpowers/specs/2026-10-03-m12-search-stage1-design.md`, decision 0022), whose section 9 named this interface without building it.

## 1. Goal

Stage 1's search is an oracle: it expands the true state, so it knows the foe's stat points, its exact HP and the secret counters of both sides. Training on its choices would teach decisions that rest on hidden information.

The new search sees only what the viewer can see (decision 0007). It samples the hidden values into worlds and decides once for all of them. It serves two uses:
- **Stage 2, live play:** the search on Showdown, where no true state exists.
- **The stage 3 teacher:** the search's choices as training targets in self-play.

The measurement puts the honest search beside the oracle search and the raw network, against the same panel. The difference between the oracle and the honest search is the oracle bias.

Not in this work: a tree search deeper than one turn, closed team sheets (M14), belief updates from observed damage and turn order (M13 lever 3; this work leaves the hook), and the stage 3 training loop itself (its own specification; section 10 fixes what the search hands it).

## 2. Decisions (2026-10-04)

**From the owner's brief**
- Only what the viewer can see (decision 0007); the hidden values are sampled into worlds.
- Belief model: the hidden stat points are drawn from common spreads.
  - Pastes are the source: the curated `PP_` teams carry real spreads.
  - `LL_` spreads are importer guesses and are not used.
  - Replays show sets, never stat points.
  - A hook stays for later updates from observed damage and turn order (M13 lever 3).
- Reduction rules: Nash, expected value (EV) and a mix. The default teacher is a 50/50 mix of Nash and EV until a measurement says otherwise.
- Measured stage 1 context:
  - cost 5.74 ms per decision (1,024 leaves, GPU);
  - against the raw network Nash scored 0.71 to 0.73 and EV 0.90 to 0.91 (2,048 games each);
  - against opponents other than its own model, EV's edge halves (+0.41 to about +0.2) but stays at least Nash's;
  - 16 samples are enough.

**Brainstorming answers**

| Question | Answer |
|---|---|
| 1. The engine entry point | A public state record and `from_view`, proven by a round trip (section 4.3) |
| 2. The stat point belief | Empirical spreads with backoff (section 5.1) |
| 3. The unseen bench | The opponent model's team head, per world (section 5.3) |
| 4. Worlds and chance | W worlds with one chance sample each; W = 16 (section 5.6) |
| 5. The table across worlds | A Bayesian game: one strategy for all worlds, the foe best-responding per world (section 6.3) |
| 6. The teacher | The mix as a KL target on a fraction of decisions, at the full budget (section 10) |
| 7. PIVOT roots | The foe's queued commands are sampled (section 5.5) |

## 3. Findings that shape the design

**What the viewer sees** (decision 0007, rules 1 to 4)
- Its own team exactly: stat points, stats, exact HP and PP, pick order.
- Both open team sheets: species and forme, gender, item, ability, moves, nature. Stat points never.
- The battle as the game shows it: every public message, plus the exact values only the viewer's own screen shows.
- Anything that follows from these may be handed over. Anything rolled in secret and never shown stays hidden, for the viewer's own side as well (0007:20).

**What is hidden** (0007:29-31, 96, 101; 0005:75-81; 0018:134-147; 0006:212)

| Hidden value | How it arises |
|---|---|
| The foe's stat points, hence its stats and maximum HP | set at team building |
| The foe's exact HP | shown as a floor percent, 1..100 while alive, with a flag at exactly 20 and 50 |
| Which unseen foe members were brought, and the pick order | private until a member is sent in |
| Sleep turns, both sides | drawn: `sample([2, 3, 3])` |
| Confusion turns, both sides | drawn: `random(2, 6)` |
| Partial trap turns and multi-turn lock turns | drawn: 5 to 6, 2 to 3 |
| The foe's charging move's target | chosen in secret |
| The foe's queued commands at a PIVOT | sealed at the turn's start |
| The RNG | never exposed |

**Public, but not in today's observation.** These follow from public lines, so a world may hold them exactly:
- the order of the active members' switch-ins, which decides some ties (Lightning Rod);
- the toxic stage, the freeze counter, the remaining turns of Encore, Disable, Taunt, Yawn, Heal Block and Throat Chop (every counter set without a draw);
- what the foe knows of the viewer (its seen masks and displays, the moves it saw used).

**The format** (decision 0004: Pokémon Champions)
- Stat points: at most 32 per stat and 66 in all (`DUOFORGE_STAT_POINTS_MAX`, `_TOTAL_MAX`).
- Level 50 and IVs 31, neither a field. The nature is on the open sheet.
- HP = base + SP + 75; the other stats are (base + SP + 20), times 110/100 or 90/100 for the nature, truncated (`src/data/formulas.c`).
- So a foe member's maximum HP has 33 candidates, and one display bucket holds at most 3 exact values (maximum HP 267 in Reg M-C).

**No call builds a mid-game state.** Battles are created from setups at TEAM_SELECTION. Mid-turn fixtures are white-box only (decision 0005); decoding canonical bytes is the only other path, and it is privileged.

**The spread data**
- 71 `PP_` teams state their spreads. With Teams A, B and C that is 444 sets over 28 species. 443 sum to 66 and one to 65.
- The spreads are dispersed:
  - Rillaboom: 57 sets, 46 distinct spreads;
  - Salamence: 48 sets, 27 distinct;
  - Sneasler: 44 sets, 24 distinct.
- The 573 `LL_` lists and 5 `PP_` pastes have no spreads (every stat point 0).
- `duoforge_replay/prior.py` keeps only the most common spread per key, which leaves no uncertainty.
- About 227 further pastes live outside the repository (the M11 spec).

## 4. Architecture

### 4.1 Parts

- **Engine (decision 0023):**
  - two records, the public state and the hypothesis;
  - five public calls: `duoforge_battle_public` and `duoforge_battle_from_view`, their batch forms `duoforge_batch_public` and `duoforge_batch_from_view`, and `duoforge_public_queue_mask` for PIVOT roots;
  - one privileged call, `duoforge_battle_hypothesis`, for tests and the oracle;
  - stats, HP bounds, every distribution of a hidden counter and every consistency rule live here, never in Python.
- **Belief (Python, NumPy):** the spread table, its builder, and `Belief.sample`, which draws hypotheses from seeds. It draws numbers only.
- **Search (Python):** the worlds batch, the per-world tables, the rules N, E and X, the records, the arena's honest agent and the teacher's targets.
- **Live (stage 2):** the tracker fills the public record from the protocol, as it fills the observation today (section 11).

### 4.2 One honest search round

At each arena step, for every game where the searcher decides:
1. **The public record:** in the arena, `duoforge_batch_public` derives it from the true state. Live, the tracker fills it.
2. **The hypotheses:** `Belief.sample` draws W of them from the decision's seeds, including the bench tuple (section 5.3) and, at a PIVOT, the foe's queued commands (section 5.5).
3. **The worlds:** `duoforge_batch_from_view` builds W worlds per decision into a worlds batch, in the workers.
4. **The root policy:** one policy call over the rows of the worlds batch. The viewer's own row is the same in every world (tested); the foe's row differs per world, since it sees its own sampled values.
5. **The leaves:** K own pairs × M foe pairs × W worlds, world w with chance sample w. `duoforge_batch_expand` takes the worlds batch as its roots.
6. **The values:** one value call per chunk, padded to the capacity, as in stage 1.
7. **The decision:** per world a table A_w; then the rule (section 6) and the record.

### 4.3 The engine calls (decision 0023)

Working declarations. The plan fixes the layouts.

```c
/* The complete public knowledge of one player (decision 0007 rules 1 to 3 and what follows from them). */
typedef struct duoforge_public_state duoforge_public_state;
/* One sampled assignment of everything the public state leaves open (numbers only). */
typedef struct duoforge_hypothesis duoforge_hypothesis;

duoforge_status duoforge_battle_public(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                       duoforge_public_state *out);
duoforge_status duoforge_battle_from_view(const duoforge_context *ctx, const duoforge_public_state *view,
                                          const duoforge_hypothesis *hypothesis, duoforge_battle *out);
duoforge_status duoforge_batch_public(const duoforge_batch *batch, const uint32_t *players,
                                      duoforge_public_state *out, duoforge_status *statuses);
duoforge_status duoforge_batch_from_view(duoforge_batch *worlds, const duoforge_public_state *views,
                                         const duoforge_hypothesis *hypotheses, uint32_t count,
                                         duoforge_status *statuses);
/* PIVOT views: the foe's pairs at the turn's start that agree with what the turn has shown so far, in the
   pair layout of duoforge_batch_query_encoded. turn_start is the same player's view at the turn's start. */
duoforge_status duoforge_public_queue_mask(const duoforge_context *ctx, const duoforge_public_state *turn_start,
                                           const duoforge_public_state *view, uint8_t *mask);
/* PRIVILEGED: the true values of everything the player's public state leaves open (tests, the oracle). */
duoforge_status duoforge_battle_hypothesis(const duoforge_context *ctx, const duoforge_battle *battle,
                                           uint32_t player, duoforge_hypothesis *out);
```

**Facts, not derivations**
- The record holds the player's observation and its extension as they are.
- Every further field is something the player's client shows, or a count of shown events, such as the turns since a counter started.
- Whatever needs a rule to follow from these, the engine derives inside its calls: stats, the remaining turns of a counter, the posterior of a drawn counter, and which foe commands agree with the turn so far.
- So the live tracker fills the new fields by folding the protocol, as it fills the observation today (decision 0016 §2). Python holds no rule.

**The public state** (fixed size, versioned, little-endian like the canonical encoding)
- A header: revision, the player, the context fingerprint, the data kind, the boundary, the request state, the epoch and the turn.
- The player's observation and its extension (decisions 0007 and 0018), as the encoder reads them. They already hold the open sheets, both sides' members as the player sees them (own exact values, the foe's HP displays, the move uses seen, statuses, `is_mega`, `item_used`, locations), the positions, the field and the side conditions.
- What they leave out, though the player knows it:
  - the foe's leads;
  - per position, on both sides, the turns since each counter started, drawn or not;
  - the order of the actives' switch-ins;
  - what the foe knows of the player: its seen masks, HP displays and move uses seen.
- **At a PIVOT,** in addition: which positions have already acted in this turn, and the player's own queued commands.
- Not in it: the values of the drawn counters, on either side (hidden from the player too, 0007:20), and everything else the hypothesis holds.

**The hypothesis** (numbers only)
- Its uniforms are 64-bit words u, read as u / 2^64. The engine maps them in integer arithmetic, so no float enters it (decision 0022).
- The foe's six stat point spreads.
- One uniform per foe member for its exact HP inside the shown bucket.
- The foe's pick order: all six entries. At TEAM_SELECTION it is empty, since nobody has chosen yet.
- One uniform per instance of a drawn counter (sleep, confusion, partial trap, lock), on either side.
- One uniform per charging foe member for its target.
- At a PIVOT, the foe's queued commands for the slots that have not acted yet, as slot commands of the choice API.

**The engine's mapping** (rules in C only, integer arithmetic)
- **A uniform u picks** the ⌊u · n / 2^64⌋-th of n equally weighted values. With integer weights it picks the value whose cumulative range holds ⌊u · total / 2^64⌋.
- **Stats and maximum HP** follow from the stat points by the formulas.
- **Exact HP:** u picks among the exact values the shown percent and flag allow under that maximum HP. A never-seen member is at full HP.
- **A drawn counter:** u picks from the posterior of its draw, given the turns since it started, with the prior's integer weights. For example, a sleep of `sample([2, 3, 3])` still running after one attempt has 1 or 2 turns left, in the ratio 1 : 2.
- **A charging target:** u picks among the targets the move could have chosen.
- **At a PIVOT,** the queued commands become the foe's queue.
- **Substitute HP and every other value derived from a hidden one** are computed from the world's values.
- The world's RNG is left zero, and every leaf is reseeded (decision 0022).
- `duoforge_battle_hypothesis` returns for each uniform the middle of the range of words that picks the true value, and at a PIVOT the true queue.

**Records the caller keeps**
- A game's team-preview record, for the bench (section 5.3), and the record of its current turn's start, for PIVOT roots (section 5.5).
- The arena's searcher takes both when it is asked there, and the live tracker has both.

**The queue mask** (PIVOT views only)
- **The mask** marks the foe's pairs that were legal at the turn's start and agree with what the turn has shown since: the switches, the Mega Evolutions and the moves used, by the two records.
- **The engine's rules decide what agrees,** never Python: the order of switches, Mega Evolution and moves, and moves called by other moves.
- **Targets are not compared,** since the records show none. The mask is sound (the true pair is always marked) but can keep a pair whose target the turn has ruled out.
- **No hypothesis is needed:** under open sheets the foe's legal choices at the turn's start follow from public facts. Where they do not, the call refuses (`E_UNSUPPORTED`).

**Refusals** (explicit, never a guess)

| Status | When |
|---|---|
| `E_NULL_ARGUMENT` | a missing argument |
| `E_CONTEXT_MISMATCH` | the record's fingerprint is not the context's |
| `E_SCHEMA_MISMATCH` | a record of another revision |
| `E_MALFORMED` | a record's reserved bytes or ranges are wrong |
| `E_INVALID_ARGUMENT` | the hypothesis contradicts the record: a spread past 32 or 66; a pick order against a member seen or the leads, or one at TEAM_SELECTION; a queued command for a slot that has acted, or one its member could not have chosen. Also a queue mask asked for a view that is not at a PIVOT, or with a `turn_start` that is not the same player's TURN record of the same turn |
| `E_UNSUPPORTED` | a state the record cannot express, from a documented list: a POOL tail feature whose support bit is clear, any hidden value whose distribution the engine does not model |

- The built world passes the full check. If it does not, the call returns `E_INVARIANT`, an engine bug.
- On a refusal a call writes nothing, as every call of the library does (`duoforge.h`).

**Proofs by test**
- **Round trip:** for every state reached in random play under every data kind, at every boundary and for both players, `from_view(public(s, p), hypothesis(s, p))` equals `s` byte for byte, apart from the RNG. States the record cannot express are refused with `E_UNSUPPORTED` and counted by reason, and the test pins those counts.
- **Tightness:** for every such state and random valid hypotheses h, `public(from_view(public(s, p), h), p)` equals `public(s, p)`. A field that read a hidden value would differ.
- **Info-safety (decision 0002):** the record's sizes and statuses depend only on p's view.
- **The own row:** p's encoded row is the same in every world built from one public state.
- **The queue mask:** at every PIVOT of random play the pair the foe chose at the turn's start is marked.
- **The batch forms** allocate nothing, and equal the single calls for every worker count.

## 5. The belief and the worlds

### 5.1 The spread table

- **Source:** the `PP_` teams in `data/teams` and Teams A, B and C, read deterministically. A flag adds the external pastes; that table is then written outside the repository. Sets without a stated spread are skipped.
- **Keys and backoff:**
  1. (species, nature, item) with at least `min_sets` sets (default 5);
  2. else (species, nature);
  3. else species;
  4. else the spreads of every species whose nature raises the same stat, as stat shapes mapped onto the member.
- **A draw takes one whole spread,** weighted by how often it was seen. That keeps the 66 total and the shapes people play, such as 32/32 in two stats.
- **The record of a run** holds the table's SHA-256 and its counts.
- **Leave one team out.** In the arena and in self-play the foe's team can be one of the table's own sources. Its worlds are then drawn from the table without that team's sets. Otherwise the honest search would draw the true spread with the weight of one set, a leak that live play does not have. The pool's ids, already in the arena's conditions, say which sets are left out; the run records the rule beside the full table's SHA-256.

### 5.2 Drawing a world

Everything comes from the search seed, the decision key (decision 0022) and the world index w:

    g      = splitmix64(splitmix64(seed + 0x574F524C44000001) + key)     ("WORLD" tag)
    z_w    = splitmix64(g + w)
    x_w,k  = splitmix64(z_w + k),   k = 1, 2, ...                         (64-bit words)

- **The engine's uniforms** are these words (section 4.3).
- **A spread** is the ⌊x · N / 2^64⌋-th of the N sets under its key, in the table's order, so a spread seen c times has weight c. This is integer arithmetic too.
- **A draw from the network's probabilities** (the bench tuple, the queue pair) takes u = (x >> 11) · 2^-53 against the cumulative sum, as the play draw does (decision 0022).

The draws come in a fixed order, each kind in its own fixed range of k, so one draw never shifts another:
1. the spreads, foe member 1 to 6;
2. the HP uniforms;
3. the bench tuple (section 5.3);
4. the counter uniforms;
5. the charging-target uniforms;
6. at a PIVOT, the foe's pair at the turn's start (section 5.5).

No draw depends on a worker, a chunk, a cell or a position.

### 5.3 The unseen bench

The opponent model (stage 1: the searcher's own network) chose the foe's four at team preview. Per world:
1. The engine builds the world's team-preview state: `from_view` of the game's team-preview record (section 4.3), with the world's spreads.
2. The policy call takes the foe's row there.
3. Its team head gives the 360 ordered tuples a probability.
4. The tuples that disagree with the record's facts (the leads, the members seen) are dropped. That is a comparison of roster indices, no rule, and the engine refuses a pick order that disagrees anyway. The rest are renormalized and one is drawn by its u.

This costs one world build and one network row per world, batched with the root rows.

### 5.4 Secret counters

The engine maps each counter's uniform as section 4.3 says. Python neither knows the draws' distributions nor computes a posterior.

### 5.5 PIVOT roots

At a PIVOT the foe's commands for the rest of the turn were sealed at the turn's start. Per world:
1. The engine builds the turn-start world: `from_view` of the turn's start record (section 4.3), with the world's spreads, uniforms and pick order.
2. The opponent model's row of the foe there gives its pair probabilities.
3. `duoforge_public_queue_mask` marks the pairs that agree with the turn so far. It is called once per decision, since it needs no hypothesis. The other pairs are dropped, the rest renormalized, and one is drawn by its u.
4. The drawn pair's commands for the foe slots that have not acted yet (the record says which) are read from the turn-start world's domain and go into the hypothesis. That is a lookup, no rule.

### 5.6 Weights, worlds and chance

- **Weights:** version 1 gives every world 1/W. `Belief.sample(view, history, n, seed) → [(hypothesis, weight)]` keeps the hook: a later belief over the stat points (M13 lever 3) reweights or redraws the worlds, and the table already uses the weights.
- **W = 16 by default.** World w uses leaf sample w, so the cells of one world share the same chance (common random numbers). That gives 8 × 8 × 16 = 1,024 leaves, the cost of stage 1.

## 6. The table and the rules

### 6.1 Candidates
- **Own:** the top K pairs of the viewer's row, which is the same in every world. Ties go to the lower flat index, as in stage 1.
- **Foe:** the top M pairs by the world-weighted mean probability of the foe's rows. A foe without a request has M′ = 1.

### 6.2 Leaves and tables
- Leaf values as in stage 1: the value head on the viewer's row; TERMINAL by the result; the arena's cut-off by the tiebreak; a refused leaf counts −1.
- A_w[i, j] is the value of the leaf (i, j) of world w. The standard error of every cell across the worlds is recorded.
- The value head reads only the viewer's row, so the hidden values act on a leaf only through what is visible in it.

### 6.3 N: the Bayesian Nash rule
- **The game:** our one mixed strategy x holds for every world, because we cannot tell them apart. The foe knows its world and best-responds in each.

      maximize   Σ_w p_w v_w
      subject to v_w ≤ Σ_i x_i A_w[i, j]   for every w and j
                 Σ_i x_i = 1,  x ≥ 0

- **The solver:** a dense simplex with Bland's rule, as in `matrix.py`. The final basis is solved again in float64 without BLAS. An exact rescue in rational arithmetic runs if the float path fails or misses the certificate.
- **The certificate:** with the duals y_w, scaled to sum to 1 (the foe's strategy in world w), max_i Σ_w p_w (A_w y_w)_i − Σ_w p_w min_j (xᵀA_w)_j must be at most 1e-9, relative to the range as in stage 1. Otherwise the run stops and writes the tables.
- With W = 1 it is stage 1's matrix game. A test checks that it equals `matrix.solve`.
- **The move** is drawn from x by the decision's play uniform, as in stage 1.

### 6.4 E: the expected value
- The row with the highest Σ_w p_w Σ_j q_w,j A_w[i, j].
- q_w are the foe's probabilities on its row in world w, renormalized over the M pairs.
- Ties as in stage 1.

### 6.5 X: the mix
- π = λ · x + (1 − λ) · e_E, with λ = ½ by default and e_E the one-hot vector of E's row.
- The move is drawn from π by the play uniform.
- X is the default teacher (section 10). Every rule's record holds all three results.

### 6.6 Strategy fusion
- Determinized search goes wrong when the player chooses differently in each world, because it could not tell the worlds apart in play. Here the root has one strategy for the whole information set, so no fusion arises there.
- Averaging per-world equilibria would bring fusion back, so it is not done.
- A tree search (later) needs the same principle at every own decision, with one strategy per information set.

### 6.7 Decision kinds

| Root | Handling |
|---|---|
| TEAM_SELECTION | the raw network, counted |
| One own pair | forced, counted |
| TURN, REPLACEMENT, PIVOT with at least 2 own pairs | searched (PIVOT with the sampled queue) |
| An engine call of section 4.3 refuses with `E_UNSUPPORTED` | the raw network decides, counted as "unreconstructible" with its reason, never silently |
| Not requested | no decision |

## 7. Seeds and determinism

- **Separate streams:** the world stream (section 5.2), the leaf seeds (`duoforge_search_seeds(seed, key, w)`) and the play uniform (decision 0022) are separate.
- **The decision key:** in the arena, as in stage 1. Live: the game id, the request epoch and the seat.
- **Reproduction** (stage 1 spec, section 6): bit for bit on the same machine with the same capacity; across machines within float tolerance. The spreads, the engine's uniforms and the engine's part are bit-exact everywhere. The bench tuple and the queue pair come from the network's probabilities, so they share its reach.
- **A run's conditions** add the spread table's SHA-256, W and λ.

## 8. Failure modes

| Case | Handling |
|---|---|
| An engine call of section 4.3: any status but `OK` and `E_UNSUPPORTED` | a bug: the run stops and writes the public records' bytes and the hypothesis |
| An engine call of section 4.3: `E_UNSUPPORTED` | the decision is "unreconstructible": the raw network decides, counted with its reason |
| No bench tuple or no pair of the queue mask has a probability | the run stops (the record and the model disagree) |
| A leaf | as in stage 1 (stage 1 spec, section 7) |
| The Bayesian certificate is missed | the run stops and writes the tables |
| Live: the tracker cannot fill a field | the decision is "unreconstructible", counted, and the reason is logged |

## 9. The measurement

- **Agents:** the honest search (H), the oracle search (O, stage 1) and the raw network (R). H and O play the rules N, E and X.
- **Opponents:** the same panel: the BC network, updates 3600 and 11000, the scripted baseline, and R.
- **The suite:** the run's suite, with one arena seed and the same rows for everyone. The settings match stage 1's: 2,048 games, 8 × 8, W = S = 16.
- **The belief** leaves the foe's own team out of the spread table (section 5.1).
- **What is reported:**

  | Quantity | Definition |
  |---|---|
  | Oracle bias | score(O) − score(H) per rule and opponent, paired per row and bootstrapped |
  | Honest gain | H − R per opponent |
  | Cost per decision | split into the public records, the world builds, the team head, the leaves, the network and the solve |
  | Counts | unreconstructible decisions, PIVOT roots, and the bench tuples dropped as inconsistent |

- **Tooling:** `python -m duoforge_search.arena` (#214) gains `--search honest|oracle` and agent X.
- **The run** happens locally on the owner's machine in the daytime. Checkpoints never leave it. The report holds scores and hashes only (AGENTS.md).

## 10. The stage 3 teacher

What the search hands the training, per searched decision:
- **The policy target:** π_X over the K own pairs, 0 elsewhere. It is learned as an auxiliary loss on the searched rows: KL(π_X ‖ π_θ) over the whole target distribution, with its own coefficient beside the KL anchor of #216. That anchor takes k3 on the taken actions; this loss needs no sample.
- **The value target** stays the game's result. The search's root value (the Bayesian value, the best expected value) is recorded, not trained on. Using it is a separate, measured lever, because it comes from the value head itself.
- **Which decisions:** a fixed fraction of self-play decisions is searched, 1/8 to start, at the full budget of 8 × 8 × 16. The fraction, the budget and λ are parameters.
- **The belief** leaves the foe's own team out, as in the measurement (section 5.1), so the targets rest on no more than live play would know.
- **Cost:** at the measured 5.74 ms per decision, plus the world builds and the team head, the cost per searched decision and the self-play throughput are measured and reported before any training run.

## 11. Live play (stage 2)

- The tracker fills `duoforge_public_state` from the protocol, as it fills the observation today (decision 0016 §2): through the converter's parser, folding events, with no rule of its own. The new fields are facts and counts (section 4.3).
- A test proves the tracker's record equal to `duoforge_battle_public`, byte for byte, at every request of every committed closure battle, as `duoforge.python.live` does for the observation.
- A field the tracker cannot fill makes the decision "unreconstructible": counted, with the reason logged.
- `SearchPolicy.rank_pairs` ranks the drawn pair first, then by the rule's probability, then by the prior, as section 9 of the stage 1 spec says. A choice the server rejects is chosen again as today.
- The budget is a count of leaves, fitted to the time per move.

## 12. Tests

**C**
- The round trip over random play in every data kind, for both players, at every boundary, PIVOT included.
- Tightness, info-safety, the own row and the queue mask, as in section 4.3.
- Every refusal of the table in section 4.3, each with a constructed case.
- The batch forms against the single calls for 1, 2, 3, 4, 8 and 16 workers. No allocation per call.
- The mapping:
  - every HP uniform lands inside the shown bucket and flag;
  - every counter value is possible under its draw and the turns since it started;
  - every charging target is one the move could have chosen;
  - with u = 0 and u = 2^64 − 1, the extremes come out.

**Python**
- **The spread table:** deterministic from its inputs, the backoff levels, whole spreads with the 66 total, skipped sets without a stated spread.
- **The world draws:**
  - pure in (seed, key, w), independent of order;
  - the fixed draw order;
  - the bench draws agree with the leads and the members seen;
  - the queue draws stay inside the queue mask;
  - leave one team out: no set of the foe's team is in its table.
- **The Bayesian rule:**
  - the certificate on random tables up to 16 × 16 × 16, degenerate and duplicate rows included;
  - W = 1 equals `matrix.solve`;
  - a constructed game where the foe's knowledge of its world changes our best strategy.
- **E and X:** E with the per-world q; X's mixture and its draw.
- **End to end:** a pinned decision on Teams A, B and C. Its integer parts are exact on every machine and its table is within a tolerance, as in stage 1.
- **The arena:** the honest agent with K = 1 plays the raw network's choice.
- **Information safety, end to end:** two roots that differ only in values hidden from the searcher get the same worlds and the same decision, table and draw included. The second root is built with `from_view` from the first's public record and another hypothesis.

## 13. Not in this work

- a tree search deeper than one turn, and endgame solving;
- closed team sheets (M14), where the hypothesis would also hold the unrevealed sets;
- belief updates from observed damage and turn order (M13 lever 3): only the hook;
- the stage 3 training loop (its own specification);
- a model of human play as the opponent model (M13 lever 2): the interface takes it later.

## 14. Coordination

- Decision 0023 records the engine API. Its number is reserved, and the HauptSession may renumber it at merge.
- **API approval:** the five public calls and the two records are public additions, and the privileged call joins those of decision 0002. The owner approves them with this specification; decision 0023 records that approval.
- **Process:** the HauptSession merges. The implementation plan follows the owner's approval, and nothing is built before it.
- **Runs:** in the daytime only, on the owner's machine. Checkpoints and run directories stay private (AGENTS.md).
