# Depth search: from the one-turn Bayes LP to a simultaneous-move tree

Status: **design, for owner review** (2026-10-13). The questions Q1–Q6 are answered (section 10); the specification
as a whole awaits the owner's approval. #450 piece 3, #367, with #358 (exact chance) and #433 (candidate
breadth) as neighbours. Design only: no product code, no build and no run were made for this document. Every number
below is read from the repository at 05705b44 (the search code is unchanged since 04755795) or from the aggregates on
#440 and #450, and every number not measured here is marked as an estimate.

## 0. Summary

Today the honest search looks one turn ahead and solves one exact Bayes LP per decision. This design turns it into a
search over two turns (later three). Each node of that search uses a regret-matching solver instead of an exact LP.
The design takes five PR-sized steps, D1 to D5, and every step stays switched off until its predeclared gates pass.

| # | question | decision | main alternative, and why it is not the default |
|---|---|---|---|
| 1 | node solver | **Regret-matching+ (CFR+)**. Each node sees its whole table, so the solver gets full feedback. The BC6 prior is used only to break ties, so the target stays the Nash set. In the sampled tree of D5 the solver is **regret matching with the prior as its exploration distribution**, and Exp3 runs as a measured arm | Exp3: it is built for bandit feedback, so it wastes information on a table that is fully evaluated. A prior that regularizes the solution (KL toward BC6) changes what the solver converges to, so it is a later arm |
| 2 | tree shape | **One tree over all worlds.** Our decision nodes are information sets shared across the worlds whose observation agrees. The foe's nodes stay per world, as the Bayes LP treats them today. Chance is sampled with one sample per world and edge (today's common random numbers); exact chance comes later (#358) | One tree per world, averaged at the end: our second-turn choice would then depend on facts we cannot see (strategy fusion). It stays as a diagnostic control |
| 3 | final choice | **A parameter, not a decision.** The tree produces root tables, and today's `reduce` plays them with `rule`, `lam`, the dominance filter and the solver. Below the root the foe plays the solver's equilibrium (`foe_below = "nash"`); `"model"` is an arm. The depth arms inherit the root rule of the last adopted ladder step | Fixing Nash or the best answer now would anticipate stage 2 of #440 (2d, 2e, 2l), which is running |
| 4 | evaluation | **Full width over two turns, BC6 value through batched JAX** (D2): two network calls per decision. Selective sampling (D5) waits for the in-engine evaluation (#450 piece 2) | A sampled MCTS on JAX: each iteration would cost a small network call, and the fixed overhead of each call dominates |
| 5 | budget | **Work, never wall time:** candidate widths, samples and solver iterations. Live play maps the remaining time onto a fixed table of budget levels *before* the search starts. The deadline stays a counted outer guard | An anytime search stopped by the clock: its choice would depend on the machine's load, which breaks reproduction |
| 6 | migration | D1: CFR+ at the root beside the LP (option, off) → D2: two-turn tree → D3: selectivity and node dedup → D4: in-engine evaluation hook → D5: sampled tree, three turns | – |
| 7 | measurement | Ladder arms with gates fixed in the README before any run, the mirror touchstone, the KO check as a metric, exclusive latency. **Equal-time controls** against a wider one-turn search, which D1 makes runnable | – |

The one engine extension this needs (D2): an **observation digest per leaf** for the viewer. It is computed inside
a new sibling of `duoforge_batch_expand` from the lines the viewer sees. The legacy call keeps its ABI. It contains
no rule logic and allocates nothing. The owner approved it for after Astra's restructure, agreed with Astra
(section 10, Q3); the proposed [in-engine evaluation spec](2026-10-14-in-engine-evaluation-design.md) defines the
shared digest/value call and the digest-first delivery.

Status: the owner and HS answered Q1–Q6 on 2026-10-13 (section 10). Building starts only after the owner approves this
specification. D1 comes after stage 2 of #440, and the search lane builds it.

## 1. Starting point (what exists and what has been measured)

### 1.1 The search today

`honest.Honest.decide` → `_decision` → `_prepare` / `_values` / `_finish` → `reduce` (honest.py:282):

- **Worlds:** S = 16 determinizations of the foe's hidden stat points and team, drawn from the belief
  (`belief.Belief`, seeded words, decision 0023). Each world is rebuilt by the engine from the public record
  (`Batch.from_view`), and `_check_worlds` makes it give the record back byte for byte.
- **Candidates:** K = 8 own pairs ranked by BC6's policy on the root row (`lookahead.select`), masked by the engine's
  domain. M = 8 foe pairs per world, ranked by the foe network's (BC6) policy, weighted by the worlds and filtered by
  each world's mask (`_prepare`).
- **Leaves:** S·K·M = 1024. Each is a copy of its world, reseeded by `(search seed, decision key, sample = world)` and
  stepped once (`duoforge_batch_expand`). It is valued by BC6's value head, by the exact result at TERMINAL, or by the
  tiebreak at the arena's cut-off. A refused leaf drops its own candidate (#436, `refused="drop"`).
- **Solve:** `matrix.solve_bayes` solves the Bayes game max_x Σ_w p_w min_j (x A_w)_j with one own strategy x for all
  worlds and a foe best response y_w per world. It runs a float simplex, then a stable retry, then an exact Fraction
  rescue, and every path is certified at 1e-9 of the range. The LP is refused above **20,898 tableau cells**
  (`MAX_BAYES_CELLS`, b-k16's size, #440).
- **Rule:** `mix` with λ = 0.5: π = λ·x + (1−λ)·e_ev (`matrix.mix`), where ev is the best answer to the foe model q.
  The move is drawn from π by the decision's play uniform. λ = 0 is the pure best answer, λ = 1 pure Nash.

### 1.2 Measured facts this design builds on

| fact | value | source |
|---|---|---|
| `Batch.expand`, 1024 leaves (clone, reseed, step, encode), 8 workers, local Ryzen 7 5800X | 6.6–7.0 ms, i.e. ~150k leaves/s | honest-search breakdown, 2026-10-11 |
| value call, 1024 rows / 16384 rows | 31–35 ms / 0.677 s, i.e. ~24–33k rows/s (params-49333, encoder 4; BC6 not timed alone) | same |
| step 0 (BC6), exclusive | p50 0.055 s, p99 0.10–0.12 s | #440, ladder README |
| budget arms, exclusive p99 | b-k16 0.24 s, b-m16 0.27 s, b-km16 (4096 leaves) 0.36 s, b-s32 1.16 s | #440 |
| the solver's share | b-s32 (2048 leaves, 257-row LP) costs ~1 s more than b-k16 (2048 leaves, 129 rows) | derived from the line above |
| more width or worlds at one turn | ×2 arms flat: b-k16 0.490, b-m16 0.496, b-s32 0.500 (against step 0, `bot`) | #440 |
| exact rescue | stops at 10,000 iterations for b-km16 and b-s64, about 1 in 10,000 decisions | #440 |
| KO check, step 0, 1374 decisions | own KO available 716: played 392, **among the candidates but not chosen 293**, not a candidate 31. Foe KO threat 625: answered 141, **among the candidates but not answered 146**, not a candidate 44, unavoidable 294 | #440 |
| live deadline | min(2 s, 10 % of the remaining turn time) on the VPS, cores about 3× slower | `duoforge_live/search.py:30`, #440 |

**What this means for depth.** More width or more worlds at one turn has not helped so far. Most KO misses happen
*among* the candidates, which points at evaluation and choice rather than breadth. Depth is a different lever. A leaf
one turn later replaces "BC6's guess of what the next turn does" with that turn played out by the engine. Examples are
a foe Tailwind followed by a faster KO, or a Protect that only pays off a turn later. **Whether that beats a better
value head is unknown.** D2 is built to answer that question cheaply, including a kill criterion (section 9).

## 2. Terms

- **World** w: one determinization with weight p_w. The worlds are the only source of hidden information.
- **Node:** an engine state in a world at a decision boundary. Its **edges** are joint (own pair, foe pair) choices, or
  one side's choice where only that side is requested (REPLACEMENT, PIVOT).
- **Chance sample** c: the seeds under which an edge is stepped. Today's leaf uses `sample = w` (one sample per world
  and edge, common random numbers across a table's cells).
- **Information set** I: our nodes that we cannot tell apart. The root is one information set over all worlds. Below
  it, two of our nodes share an information set exactly when our own past action and everything we observed are equal
  (section 4.2).
- **Iteration** t: one pass of the solver over the tree, which is a fixed tree in D1–D3 and a sampled path in D5.

## 3. Decision 1: the node solver

### 3.1 D1–D3: CFR+ (regret-matching+) with full feedback

In D1–D3 every node's table is fully evaluated before the solve: the tree has a fixed width and is evaluated in two
batched network calls (section 6). The solver therefore sees every utility. It runs regret-matching+ at every
information set, as CFR+ over the tree:

- **Strategy at I:** σ_I(a) ∝ R⁺_I(a), the positive part of the regret. When every regret is 0, σ_I is the BC6 prior
  of I's candidates (renormalized), not uniform. This is the only use of the prior in D1–D3. It changes which strategy
  the solver starts from and how ties break, but not the set it converges to.
- **Update, alternating as in CFR+:** first we update with the foe's current strategies, then the foe with our new
  ones. R⁺_I ← max(0, R⁺_I + r_I), where r_I is the counterfactual regret: the action's value minus σ_I's value, weighted
  by the foe's and chance's reach. At the root in D1 our r is Σ_w p_w A_w y_w − x·(…), and world w's foe gets
  −(x A_w) minus its own value.
- **Average:** the played strategy is the average weighted by t (linear averaging, CFR+). The current strategy is not
  played.
- **Stop:** the exploitability of the average is computed exactly every N iterations. At the root that is
  `matrix.bayes_exploitability`, which already exists; on the tree it is a best-response pass. The solver stops at
  gap ≤ ε·range, or at T_max iterations (section 7). Both are counts, never time.

**Why it converges.** Regret-matching+ is a no-regret learner. In a two-player zero-sum game, the average strategies of
two no-regret learners form an ε-equilibrium with ε ≤ (Regret_ours(T) + Regret_foe(T)) / T. The foe's best response
splits per world, so its regret is Σ_w p_w Regret_w(T), and the bound holds unchanged for the Bayes game. In the tree,
CFR's regret decomposition gives the same bound over information sets. It needs perfect recall, which the information-set
key of section 4.2 provides. The worst-case rate is O(range · √(|A| / T)). In practice CFR+ converges much faster,
close to O(1/T). **That is a reason to measure (D1), not a promise.**

**How the result depends on the budget.** The budget is T and ε. The exploitability of the played average is computed,
recorded and gated, so the dependence is measured per decision, not assumed. For our 8 × 8 × 16 root, the D1
measurement on recorded tables (section 9.1) gives the curve of T against the gap. That curve sets the default T.

**Why not keep the exact LP everywhere.** The exact LP is the right tool at one node of 8 × 8 × 16. It does not scale:

- the tableau grows with worlds × foe pairs;
- the exact rescue stops above ~20k cells (#440);
- a tree has hundreds of nodes whose games are coupled through the shared information sets.

CFR+ needs O(S·(K + M)) memory per node and has no tableau. The size limit does not apply to it (section 8, D1).

### 3.2 D5: sampled tree

Once the tree is sampled rather than evaluated in full (D5), a node sees only the utility of the sampled joint action
(bandit feedback):

- **Default: regret matching with importance-weighted sampled regrets** and exploration γ. A node plays
  σ = (1 − γ)·RM(R) + γ·prior, so the BC6 prior replaces the uniform exploration term.
- **Arm: Exp3**, with the same prior as its exploration term.
- **Not sound: decoupled UCB.** In simultaneous-move games it does not converge to an equilibrium. This is published
  (Shafiei, Sturtevant and Schaeffer 2009), and the public Gen 1 singles engine cited on #450 makes the same point.

**Why this converges.** Lisý, Kovařík, Lanctot and Bošanský (NeurIPS 2013) show for simultaneous-move MCTS: if every
node's selection is Hannan-consistent and explores with a positive probability, the average strategies converge to an
approximate subgame-perfect equilibrium. The approximation shrinks with the exploration. Both RM with γ and Exp3 meet
that condition. The prior as the exploration distribution keeps the guarantee, as long as every candidate has positive
prior mass, which holds: candidates are policy-ranked pairs with exp(logp) > 0.

**Why RM is the default rather than Exp3:**

- Exp3's learning rate is tied to the horizon T, so it couples to time management. RM has only γ.
- Published comparisons of SM-MCTS variants (Tak, Lanctot and Winands 2014) found no variant dominant across games,
  with regret matching competitive and Exp3 often weaker.

This is no result for our game, which is why Exp3 is an arm. The engine cited on #450 uses Exp3 for its own game.

## 4. Decision 2: the tree's shape

### 4.1 One tree, our nodes merged by information set, the foe's per world

The tree mirrors the structure of today's Bayes LP and extends it by one turn:

```
root information set (ours, shared by all worlds)            x over K own pairs
 └ world w (weight p_w)                                        foe node: y_w over M_w foe pairs
    └ edge (i, j), sample c                                    engine: expand(world w, (i, j), seeds(key, c))
       └ node n = (w, i, j, c): TERMINAL / cut-off / decision
          ├ our part:   information set I(n) = (i, observation digest of n)   shared across worlds
          └ foe part:   per node (the foe knows its world)                    M2 foe pairs from the foe network
             └ edge (i2, j2), sample c2 → leaf: BC6 value / result / tiebreak
```

- **Ours:** one strategy per information set. At the root that is the existing rule ("one strategy for the whole
  information set", visible-search spec section 6.6). Below the root the same rule applies, as that spec requires for
  a tree. Averaging per-world solutions would bring strategy fusion back.
- **The foe's:** one strategy per node, so the foe acts as if it knew the world. Today's Bayes LP does the same (the
  foe best-responds per world). This is conservative for us, and the design keeps it. A foe information set over our
  own hidden facts is pointless while our side is exact in every world.
- **Combining the worlds:** this is not a separate step. The root information set's counterfactual values are already
  the p_w-weighted sum over the worlds, as in the LP's objective. With depth 1 (D1) the tree *is* today's Bayes game,
  and CFR+ on it solves the same problem as `solve_bayes`. That gives D1's exactness test against the LP.
- **Root tables for the rule:** after the solve, A_w[i, j] = the value of node (w, i, j) under the solved continuation,
  averaged over its samples. These are the K × M tables that `reduce` takes today. The rule of section 5 then plays
  them unchanged, so the root rule is independent of the depth.

### 4.2 The information-set key

Two of our depth-1 nodes are in the same information set exactly when our root action i is the same and **everything
our seat saw during the step is the same**. Python must not decide what we saw: that would be a hidden rule. So the key
comes from the engine:

- **Open sheets, first choice:** the viewer's public record of the node, byte for byte. The worlds already give it
  back by `_check_worlds`. But under closed team sheets (decision 0081), a world's record holds its particle's filled-in
  facts. Then the bytes differ across particles although we observed the same thing, and the key would split
  information sets that are really one. That is strategy fusion again.
- **Therefore the decision: an observation digest per leaf.** `duoforge_batch_expand` (or a sibling call) writes a
  32-byte digest of the event lines the viewer sees in this step and its authorized request at the new boundary.
  Those lines are already produced: the engine folds each player's knowledge from them (`duoforge_battle_step`).
  The proposed [in-engine evaluation spec](2026-10-14-in-engine-evaluation-design.md) section 4 answers D2's
  coordination questions and defines the request projection; the key is (i, digest).
  - It splits exactly where a human would see a difference: a different damage percentage, a different switch-in, a
    different move order.
  - It merges where nothing visible differs.
  - It works the same for open and closed sheets.
  - It is computed incrementally on the stack, with no allocation and no rule logic.
  - This is the engine change of D2. It needs its own decision record, and it comes only after Astra's restructure,
    agreed with Astra (Q3).
- **Perfect recall:** the root observation is shared by construction. Our only earlier action is i, which is in the
  key, so the key has perfect recall over two turns. For three turns (D5) the key chains: (parent key, i2, digest).

The share of merged information sets is a diagnostic in every D2 report. If the foe's damage percentages split nearly
every node by world, the tree is close to "per world below the root". That is still correct, because we would see the
difference in play.

### 4.3 Chance

- **D2:** C = 1 sample per (world, edge), as today. The worlds double as chance samples, and the samples are common
  random numbers across a node's cells: the seeds depend on (seed, key, sample), never on the choices
  (`duoforge_search.h`). Below the root, node n's leaves are seeded with a **node key**
  `splitmix64(splitmix64(decision key + DEPTH_TAG) + flat index of n)`. That is a pure function of the decision key and
  the node's position (w, i, j, c), so common random numbers hold within each node's table. C > 1 is a budget lever
  (section 7).
- **Later, #358:** exact chance replaces the samples by the engine's enumeration of outcomes with their weights. CFR
  takes chance weights natively, so the tree needs no change of form. The enumeration itself is an engine decision
  (#358) that this design does not make.

### 4.4 Node kinds below the root

- **TERMINAL:** the exact result.
- **The arena's cut-off** (`last_step`): the tiebreak, or −1 when it is unresolvable, as today.
- **One side requested** (REPLACEMENT, PIVOT): a K2 × 1 or 1 × M2 node.
- **Both requested:** K2 × M2.
- **Refused steps (#436):** keep today's meaning per information set. A refused leaf drops its own candidate at that
  information set. An information set left with no candidate refuses every root edge that leads to it, and those root
  rows are dropped as today. If no root row remains, the decision is `Unreconstructible("engine_refused_leaves")`, named
  and counted, as today.

## 5. Decision 3: the final choice (a parameter)

The search's settings name the choice. Nothing in the tree depends on it:

| setting | values | meaning |
|---|---|---|
| `rule`, `lam` | nash / ev / mix, λ ∈ [0, 1] | as today, on the tree's root tables |
| `dominated` | off / on | 2d: weakly dominated own rows over all worlds leave before the solve |
| `root_solver` | `lp` / `rm` | D1: the exact LP (as today, size-limited) or CFR+ |
| `foe_below` | `nash` / `model` | below the root the foe plays the solver's equilibrium, or follows the foe network's policy over its candidates (no regrets for the foe) |

- **ev in a tree:** ev_i = Σ_w p_w Σ_j q_w,j A_w[i, j], where A comes from the solved continuation. So λ = 0 means "the
  best answer to the foe model now, equilibrium play afterwards". That is the natural extension of today's ev, and it
  needs no new rule.
- **`foe_below = "model"`:** this arm extends the same belief into the next turn. If stage 2 shows that the best answer
  wins (2e), this arm is that result's natural follow-up. It runs as its own measured arm.
- **Decided before the result:** the depth arms inherit `rule`, `lam` and `dominated` from the last adopted step of
  #440. If none of 2d, 2e or 2l is adopted, they stay at step 0's mix with λ = 0.5. This mapping is fixed here, before
  stage 2's result arrives.

## 6. Decision 4: evaluation and throughput

### 6.1 Why full width first

The leaf value is BC6's value head through batched JAX. A decision then costs a few large calls, and the fixed
overhead of each call matters little. A sampled MCTS would need thousands of tiny calls, or batched lockstep
iterations, which weaken selectivity. A full-width two-turn tree costs exactly:

1. the root and world policy calls (as today);
2. **one policy call on the depth-1 nodes:** both seats, ≤ 2·S·K·M·C rows, for the K2 and M2 candidates;
3. **one value call on the depth-2 leaves:** L2 ≤ S·K·M·C·K2·M2 rows, padded to a fixed capacity (section 7.2).

### 6.2 Leaves per second, and what fits (estimates, not measurements)

These are derived from section 1.2, not measured here:

- **The network bounds the search.** Locally that is about 17–30k leaf values/s. The low end is the p99 slope from
  b-k16 to b-km16 (+2048 leaves for +0.12 s); the high end is the isolated value call. The engine alone does about
  150k leaves/s.
- **On the VPS:** about 6–10k/s (×3 slower per core; the VPS core count is not stated here).
- **Policy rows at depth 1:** assumed to cost about as much as a value row. D2 measures this.

| config | L2 leaves | rows in total | local estimate | VPS ×3 |
|---|---|---|---|---|
| step 0 (one turn) | 1,024 | ~1.1k | measured p99 0.10–0.12 s | ~0.3–0.4 s |
| D2, K2 = M2 = 2 | 4,096 | ~6.2k | 0.3–0.5 s | 0.9–1.5 s |
| D2, K2 = M2 = 3 | 9,216 | ~11.3k | 0.5–0.8 s | 1.5–2.4 s |
| D2, K2 = M2 = 4 | 16,384 | ~18.5k | 0.7–1.2 s | 2.1–3.6 s |
| D2, K2 = M2 = 8 | 65,536 | ~67.6k | 2.4–4.1 s | 7–12 s |

- **The CFR+ solve on top:** T × L2 multiply-adds (8M at T = 500 and L2 = 16k), vectorized per level. Its time is
  unknown until D1 and D2 measure it.
- **The live deadline of 2 s on the VPS** admits roughly the K2 = M2 = 2–3 rows. The ladder's VPS gate (local p99 ≤
  1.67 s, i.e. 5 s on the VPS) admits up to 4. Anything wider needs more live time (a separate owner decision, Q2),
  the in-engine evaluation, or
  selectivity.
- **The 45 s arena limit** is the turn timer, not a per-decision budget. Live play spends at most 10 % of the remaining
  time, by today's rule.

### 6.3 The in-engine evaluation (#450 piece 2) and what it changes

- **Interface:** an evaluator setting, `jax` or `engine`. The tree code does not change. The engine evaluator values
  each leaf inside `expand`. That removes the encode step and the JAX call, so leaves no longer travel to Python.
- **Realistic gain:** the engine step bounds it at ~150k leaves/s locally, **about 5–8× over JAX**, not 100×. The
  "hundreds of thousands of inferences per second" quoted for the Gen 1 singles engine on #450 is for a much simpler
  game and is not transferable. The number comes from #450 piece 2's measurement.
- **What it opens:** the sampled tree (D5), whose per-iteration cost is then one engine call without a network
  round-trip. The order on #450 already places piece 2 before selective depth.
- **Its gate:** the decisions agree with the full network within a pinned tolerance. That gate belongs to #450 piece 2.

## 7. Decision 5: budget, determinism, memory

### 7.1 Budget in work, not time

- **The budget is a tuple of counts:** (K, M, S, C, K2, M2, T_max, ε). An iteration count or a gap target ends the
  solve, never the clock. A decision is therefore a pure function of (public inputs, seeds, network, library, settings,
  budget).
- **Live time management (#450 piece 5)** picks a budget level from a fixed table, by the time available
  *before* the search starts. Example: level 0 = step 0, level 1 = D2 (2, 2), level 2 = D2 (3, 3). The level is part of
  the decision record, so a replay uses the same level.
- **The deadline stays as the outer guard:** it plays raw and counts as `deadline`, as today, never as an answer
  silently cut short.
- **T_max without ε (decided, Q1):** the named fallback `solver_unconverged`, counted like `deadline`, never silent.
  D1 sets T_max so that the recorded tables never hit it. The gap is recorded with every decision.

### 7.2 Determinism

- **Seeds:** the root uses today's (search seed, key, sample). Below the root it uses node keys (section 4.3). Neither
  depends on choices, worker, chunk or batch position. The engine already guarantees this for `expand`.
- **Solver arithmetic:** fixed-order accumulation as in `matrix.py` (`_matvec`, `_vecmat`), with no BLAS. CFR+
  iterates in a fixed order: levels bottom-up, information sets by index, actions by prior rank.
- **Network values:** reproducible per batch shape (the lookahead docstring). Every call therefore pads to a capacity
  that the settings fix, never to the data's size:
  - the depth-1 policy call to 2·S·K·M·C;
  - the value call to chunks of 16384.
  A reproduction needs the same capacity, as today.
- **Equal settings give equal moves:** this is tested by the ladder's reproduced gate (scores and decision digests)
  and by a unit test that runs every decision twice.

### 7.3 Memory and the hot path

- **No new allocation in the engine's hot path.** D1–D3 use the existing preallocated `Batch`es:
  - the worlds (S);
  - a node batch of S·K·M·C environments (1024 at today's widths, the size of today's leaf batch);
  - a leaf batch of the fixed capacity.
  All are created when `Honest` is built. `expand` already keeps a leaf's temporaries on the stack. The observation
  digest (D2) is folded on the stack as well.
- **The Python tree:** NumPy arrays sized by the settings' maximum widths, allocated once per search object. Nodes and
  information sets are addressed by int32 indices. This is the arena layout the roadmap fixes for the stage 2 tree:
  preallocated nodes, 32-bit indices, one tree per game, no threads sharing a tree.
- **D5 in C:** a node arena preallocated per search object. A full arena refuses by name (`E_CAPACITY`) and never
  truncates silently. Its size is a setting, justified in its PR with a measurement.

## 8. Decision 6: migration in PR-sized steps

Every step ships as an **option that is off**. A test shows that the default is bit-identical to main, as #462 and #467
did. Each step's predeclared gates come before any of its runs.

| step | content | engine change | default |
|---|---|---|---|
| **D1** | CFR+ root solver, `root_solver = "rm"`, same candidates as the LP | none | off |
| **D2** | two-turn full-width tree, CFR+ over information sets; `depth = 2`, K2, M2, C | observation digest in `expand`, after Astra's restructure (Q3) | off |
| **D3** | selectivity: widths per node from the prior mass; node dedup by engine state equality (`duoforge_battle_equal`, or a digest); the per-slot breadth of #433 at the root, which the size limit no longer blocks once `root_solver = "rm"` | none expected | off |
| **D4** | evaluator hook `jax` / `engine`, once #450 piece 2 exists | that piece's own | `jax` |
| **D5** | sampled tree (RM with prior exploration; Exp3 arm), three turns, node arena in C | node arena, evaluator | off |

### D1 in detail (the first PR)

- **`matrix.solve_bayes_rm(tables, weights, prior_rank, *, iterations, epsilon)`:** CFR+ on the Bayes game as in
  section 3.1. It returns a `BayesSolution` plus the exact gap (`bayes_exploitability`) and the iterations used.
- **`reduce(..., solver="lp")`:** `"rm"` takes the new path. The `ev` row, `mix`, `draw` and the play uniform stay as
  they are.
- **`check_bayes_size` applies only to `root_solver = "lp"`.** The RM path has its own named refusal: a gap above ε at
  T_max (`solver_unconverged`, Q1). This lifts the size limit for the RM path without touching the LP's.
- **The P1 teacher** (its `WorkLedger` path and pinned manifest) stays on the LP and does not change.
- **Tests:**
  - On the recorded step-0 tables and on random tables: the RM value lies within ε·range of the LP value, and RM's
    gap ≤ ε.
  - Determinism: two runs give byte-equal output.
  - A constant table plays the first row.
  - The b-km16 and b-s64 tables that stopped the exact rescue are solved within ε. They are taken from the
    reproduction data of the stopped runs, if those were kept.
- **D1 changes no live decision.** Its purpose: it unblocks 2w (#433), the equal-time one-turn controls (b-km16,
  b-s32 and up) and D2's root.

### D2 in detail

- **The flow:** `Honest._prepare` gains a depth-1 phase.
  1. Query the node batch (both seats, encoded).
  2. Run one policy call for K2 and M2.
  3. Run one `expand` from the node batch into the leaf batch, with node keys.
  4. Run one value call.
  5. Solve with CFR+ and derive the root tables.
  6. `_finish` runs as today.
- **The record:** today's fields plus:
  - the depth, K2, M2 and C;
  - the information-set count and merge share;
  - the tree solver's iterations and gap;
  - the leaf counts by kind at depth 2.
- **Tests:**
  - At depth = 1, the tree gives the same root tables and choice as D1 (bit-identical).
  - Two worlds with the same digest share one strategy; different digests do not.
  - TERMINAL, cut-off and single-side nodes at depth 1.
  - A refused-leaf case at depth 2 propagates by name.
  - Determinism across chunkings of the leaf batch.

## 9. Decision 7: the measurement plan

All runs follow the #440 harness (`duoforge_search.ladder`). The README of each step holds its gates **before** its
first run. The search lane runs the arms in its queue under the machine lock. This design session runs nothing.

### 9.1 D1: offline first, then one ladder arm

- **Offline,** on the recorded tables of step 0's rebaseline on main (the decision records hold `tables`, `weights` and
  `foe_probs`):
  - T against the gap: median, p99 and max;
  - the RM value against the LP value;
  - choice agreement under nash (by the same play uniform), ev and mix;
  - the mass the RM average puts on rows the LP gives 0;
  - solve time per decision.
- **Fixed before the offline run:** a default T such that p99 of the gap ≤ ε, with ε = 1e-3 of the range (decided,
  Q1).
- **Ladder arm D1** (`root_solver = "rm"`, otherwise step 0), 512 pairs paired with step 0's rebaseline, `bot` and
  `ppo`. **Gates:**
  - no harm (upper bound ≥ 0.50 against `bot` and `bc6`);
  - reproduced;
  - fallbacks;
  - exclusive latency p99 ≤ 1.67 s local.
  - **No strength gate:** D1 solves the same game and is expected to play the same as step 0 within the gap.

### 9.2 D2: strength at equal time

- **Arms:** D2 at (K2, M2) = (2, 2), (3, 3), (4, 4), each with the inherited root rule (section 5). One arm
  `foe_below = "model"` at the best width.
- **The control at equal time** (the roadmap's M13 exit rule: "at a fixed time per move"): a one-turn arm with about
  the same wall time. That is K and M widened, or S widened under `root_solver = "rm"`, chosen by the exclusive latency
  of the D2 arm it controls. Without this control a D2 gain could be a budget gain, and the flat b-* arms argue against
  that. This is why D1 comes first.
- **Gates,** as #440, unchanged:
  - strength: head-to-head against the last adopted step, lower bound > 0.50, 0 unresolved, 1024 pairs;
  - no harm against `bot` and `bc6`;
  - reproduced;
  - fallbacks;
  - exclusive latency p99 ≤ 1.67 s local, and additionally ≤ 0.67 s local for live adoption at today's 2 s VPS
    deadline (Q2: measured under the 2 s cap first; raising it is a separate owner decision);
  - against the equal-time control: lower bound > 0.50, 512 pairs.
- **The mirror touchstone decides adoption next to the ladder gates:**
  - the setup: Team A against the Nationals sun team, piloted by the live search; the team file is private and stays
    outside the repository;
  - the criterion: no harm, the upper bound of the paired interval not below 0.50, at least 512 pairs, as the HS fixed
    for 1bws;
  - the sim-pilot touchstone is reported, not gated.
- **KO check as a metric per arm:** the shares with intervals, split into "not a candidate" and "among the candidates,
  not chosen". The expectation fixed here: depth moves the *answered foe threat* row (146 among the candidates but
  unanswered today) more than the own-KO row. A two-turn threat (a speed change this turn, the KO next turn) is not one
  of today's one-turn probes. That probe comes later (Q5): the problem is the choice, not the detection.
- **Kill criterion, fixed before the runs:** if no D2 width beats its equal-time control at its point estimate, depth
  with the BC6 value is parked. The evaluation (#451, #450 piece 2) then comes before D3 and D5.
- **Diagnostics:**
  - the information-set merge share;
  - the tree gap;
  - leaf kinds at depth 2 (terminal, cut-off, refused);
  - how often the root choice differs from step 0 and from D1.

### 9.3 D3 and D5

Same gates. Each arm's control is the last adopted D step at equal time. For D5 the Exp3 arm runs against the RM arm,
paired.

## 10. Risks and open questions for the owner

### Risks

1. **The evaluation limits, not the search.** The flat budget curve (#440) suggests BC6's value head limits strength.
   Depth evaluates positions one turn later with the same head. It may help, by playing the next turn out exactly, or
   not. The kill criterion of 9.2 bounds the cost.
2. **Latency.** Even K2 = M2 = 3 likely exceeds today's 2 s VPS deadline (section 6.2, an estimate). Live depth
   probably needs a larger live budget (a separate owner decision after D2's measurement, Q2), or the in-engine
   evaluation.
3. **The CFR+ average puts small mass on poor rows.** The play draw ignores mass below 1e-9 only, so a rarely played
   bad row is possible. D1 measures that mass. A purification threshold would be its own arm, never a silent rule.
4. **Fragmented information sets.** If damage percentages split almost every node by world, the shared-strategy
   machinery buys little. That is still correct. The merge share shows it.
5. **The foe knows the world** (conservative, as today). Against a weaker foe this may cost value. `foe_below =
   "model"` measures the other end.
6. **Batch-shape reproducibility of JAX:** handled by fixed padding (7.2). A capacity change is a settings change.
7. **Hidden rules in Python:** none by construction:
   - legality, outcomes, results, tiebreaks and observation identity come from the engine;
   - values and priors come from the networks;
   - Python sums, compares bytes and solves games.
   Any refusal stays named (#436).

### Decisions on Q1–Q6 (owner and HS, 2026-10-13)

The six questions of the first version, answered by the owner and HS (relayed by the coordinator, confirmed on #450).
The text above follows these answers.

- **Q1, the solver's certificate: yes, ε = 1e-3 of the range.**
  - The RM path plays an ε-equilibrium where the LP certifies 1e-9.
  - The gap is recorded with every decision.
  - A solver that misses ε at T_max gives the named fallback `solver_unconverged`, counted, never silent.
  - T_max is set so that the recorded tables of D1's offline pass never reach it.
- **Q2, live time: measure under today's 2 s VPS cap first.**
  - The 2 s are our own limit; the arena allows 45 s per turn.
  - If D2 brings measurable strength, the live budget may be raised later on purpose, for example to 5 s. That is a
    separate owner decision and not part of this specification.
- **Q3, the engine extension: yes, under conditions.**
  - The viewer's observation digest comes from leaf expansion. HS clarified on 2026-10-14: use a new sibling call,
    with no ABI break to `duoforge_batch_expand`; the same call later returns D4 evaluation for D5. See the proposed
    [in-engine evaluation spec](2026-10-14-in-engine-evaluation-design.md).
  - It comes only after Astra's restructure and is agreed with Astra.
  - No rule logic, and no allocation in the hot path.
- **Q4, the foe below the root:** `foe_below = "nash"` is the default; `"model"` is an arm of its own.
- **Q5, the KO check:** the two-turn threat probe comes later. The problem is the choice, not the detection.
- **Q6, the order:**
  - D1 comes after stage 2 of the search lane and takes over its root rule.
  - The search lane builds it.

Still in force:
- this lane delivers docs only;
- #468 is merged by HS;
- nothing is built before the owner approves this specification.

## 11. Not in this design

- The exact chance enumeration (#358, an engine decision).
- The in-engine network itself (#450 piece 2, #376).
- Live time management beyond the budget-level interface (#450 piece 5).
- Depth at team preview (step 1b's rollout covers turn 1).
- Endgame solving to the end (#367's second half). With few Pokémon left, D5's tree with a terminal-only evaluator is
  its natural home.
