# Depth search D2: the two-turn tree, the plan

**Status:** plan approved by the owner and the HS (2026-10-14), with the decisions at the end; step 1 built. Step D2 of the depth-search design
(`docs/superpowers/specs/2026-10-13-depth-search-design.md`, sections 4, 7, 8 "D2 in detail", 9.2, Q1–Q6), on top of
D1 (#481, merged with #482). Branch `search/d2-tree` from main c8ca7cee.

**What D2 is:** an option `depth = 2`, off by default. It replaces the root's one-turn leaves by a full-width tree over
two turns. Our depth-1 nodes are merged into information sets by an observation key. The foe's nodes stay per world.
One CFR+ solve runs over the whole tree, and today's `reduce` path plays the root.

**What D2 is not:** no measurement (spec 9.2 runs after D1's offline pass and the HS's go), no engine change before
Astra's field step is merged, no change to the team preview, the P1 teacher or the default search.

## Ground rules for every step

- TDD: the test first, then see it fail, then the code.
- The default (`depth = 1`) runs today's code path unchanged. The record and the decision stay byte-identical to main.
- Python holds no rule. Legality, outcomes, results, tiebreaks and observation identity come from the engine. Values
  and priors come from the networks. Python sums, compares bytes and solves games.
- Every refusal is named and counted. Nothing falls back silently.
- Fixed-order arithmetic as in `matrix.py` (no BLAS, no `dot`/`einsum`/`@`). The tree's iteration buffers are allocated
  once per search object, sized by the settings' maximum widths.
- Local runs: builds and targeted tests only, under `tools/ci/machine_lock.sh` with `d2-` labels. Full suites run on the
  GitHub CI.

## New settings (all off by default)

| setting | values | default | meaning |
|---|---|---|---|
| `depth` | 1, 2 | 1 | 1 = today's search; 2 = the two-turn tree |
| `k2`, `m2` | ≥ 1 | 2, 2 | our candidates per depth-1 information set, the foe's per depth-1 node |
| `chance` (C) | 1 | 1 | samples per (world, edge); C > 1 is refused by name until a later step |
| `info_key` | `"digest"`, `"record"` (tests only) | `"digest"` | the observation key of our depth-1 nodes (decision 1) |
| `evaluator` | `"jax"`, `"engine"` | `"jax"` | the leaf evaluation (spec 6.3); `"engine"` is refused by name until #485 lands |
| `foe_below` | `"nash"`, `"model"` | `"nash"` | Q4: the foe below the root plays the solver's equilibrium, or its network's policy |

Checks at construction: `depth = 2` requires `root_solver = "rm"` (the LP has no tree); the depth-2 settings under
`depth = 1` are refused, not ignored; `k2`, `m2` are positive ints; `chance` other than 1 is refused.

## Steps

### Step 1. The tree solver (pure NumPy, new module `duoforge_search/tree.py`)

A `Tree` holds the root (K own pairs, per world M foe pairs, weights p_w) and the depth-1 nodes n = (w, i, j), C = 1:

- node kind: `leaf` (TERMINAL, cut-off, or a value from the depth-1 evaluation, used when the node has no subtree),
  `ours` (only we are requested: K2 × 1), `foes` (only the foe: 1 × M2), `both` (K2 × M2);
- our information set id per node (−1 where we are not requested), its candidates and prior;
- the foe's candidates and prior per node;
- leaf utilities z[n, a2, b2], padded with masks.

`solve_tree(tree, prior, foe_priors, *, iterations, epsilon, check_every)`:

- Normalizes every utility by the tree's range, as `solve_bayes_rm` does with the table's range.
- Runs CFR+ with alternating updates, as D1: our pass (the root and all our depth-1 information sets) against the foe's
  current strategies, then the foe's pass (the root's per-world foes and every depth-1 foe node) against our new ones.
  Counterfactual reach: at our depth-1 information set I, p_w · y_w(j) over I's nodes; at a foe node, x(i). Linear
  (t-weighted) averaging of each information set's strategy by its own reach.
- The root step is the same arithmetic as `solve_bayes_rm`, on the root tables of the current continuation.
- The gap is the exact exploitability of the averages: a best-response pass bottom-up over our information sets and the
  foe's nodes, then the root. At depth 1 it reduces to `matrix.bayes_exploitability`.
- Stops at gap ≤ ε or raises `matrix.RMUnconverged` at T_max (Q1, the named fallback `solver_unconverged`).
- Returns the root `BayesSolution`, the root tables A_w[i, j] under the averaged continuation (unnormalized), the gap,
  the iterations, the per-information-set strategies.

Tests (pure, no engine, `test_tree.py`, quick):

- **Degenerate tree = D1, bit-identical:** a tree whose depth-1 nodes are all leaves gives exactly
  `solve_bayes_rm`'s x, ys, value, gap and iterations, on random tables and on D1's test tables.
- **Exactness on tiny games:** for trees of 2 worlds, K = M = 2, K2 = M2 = 2, with and without merged information
  sets, the normal form is enumerated and solved by the exact `matrix.solve`; the tree's value lies within ε · range
  and its gap ≤ ε.
- **Information sets:** two worlds whose nodes share a key get one strategy; with different keys the strategies are
  separate (a case where the per-world optima differ, so merging forces a visible compromise).
- **Node kinds:** TERMINAL, cut-off, `ours` (K2 × 1), `foes` (1 × M2), `both`.
- **Determinism:** two solves give byte-equal outputs.
- **Unconverged:** T_max without ε raises `RMUnconverged` with gap and iterations.

### Step 2. The observation key interface

`ObservationKey.keys(node_batch, count, viewer) -> (count, 32) uint8`. The information set of a depth-1 node is
(i, key). Only the engine decides what we saw (spec 4.2).

- `"digest"`: the engine digest of D2 (step 9). Until the library exposes it, `Honest(depth=2)` is refused at
  construction with a named error (`observation digest unavailable: needs the D2 engine extension`).
- The tree code reads keys only through this interface.
- Tests that need keys before step 9 use a **stub key** (`StubObservationKey`), in test classes whose names and
  docstrings say so ("stands in for the engine digest of D2, Q3; replaced when the extension lands"). They test the
  tree's handling of keys, never the engine's observation.

### Step 3. The evaluator interface (new module `duoforge_search/evaluator.py`)

`LeafEvaluator.leaves(source, keys, viewers, root_envs, samples, choices, cut) -> Leaves(values, step, encode,
results, tiebreaks)`. The depth-2 leaf phase calls only this.

- `JaxEvaluator`: today's mechanics. `expand` in chunks into the leaf batch, the cut-off's tiebreaks per chunk, the
  value call padded to `capacity` rows. The expand chunk size is a separate parameter (default `capacity`), so the
  tests can vary the chunking under a fixed value-call shape (spec 7.2).
- `"engine"`: the name is reserved for #485 (Astra's D4 hook). Until it exists it is refused by name. Astra adds the
  class; the tree code does not change.
- Tests: the JAX evaluator gives the same values, statuses and tiebreaks as today's `_prepare` + `_values` on the same
  leaves; a fake evaluator injected into `Honest` changes the depth-2 leaf values and nothing else (the D4 swap needs
  no tree change); an unknown evaluator name is refused.

### Step 4. `Honest` wiring for depth 2 (honest.py, agreed with the search lane via the owner)

The flow of spec 8, behind `depth == 2` in `_decision`:

1. `_prepare` as today, but expanding the root edges into a **node batch** of S · K · M · C environments (created at
   construction only when `depth == 2`) instead of the leaf batch. The default path keeps expanding into the leaf
   batch.
2. Query the node batch (both seats, encoded; the foe encoder too when there is a foe network). One policy call per
   network at the fixed shape of the whole node batch (spec 7.2).
3. Keys per open node (step 2). Our information sets = groups by (i, key) among the nodes where we are requested.
   Within an information set the engine's own pair masks must agree, or the decision stops with a named SearchError
   (the key merged states that differ for us). Our K2 candidates per information set from the mean of the policy
   probabilities over its nodes, node (w, i, j) weighted by p_w × the foe model's prior of j × its chance weight
   (1 at C = 1), renormalized (decision 3). The foe's M2 candidates per node from the foe network on the foe row of
   that node.
4. The depth-2 leaves: node n's leaves are seeded with its node key
   `splitmix64(splitmix64(decision key + DEPTH_TAG) + flat index of n)` and sample 0, through the evaluator.
5. Build the `Tree`, solve it (step 1), derive the root tables.
6. The root rule of spec section 5, unchanged: today's `reduce` plays the root tables under the averaged
   continuation with `rule`, `lam` (λ = 0 of #486 included), the dominance filter and the root solver; the tree's own
   root average and gap are recorded beside it (decision 4).

Tests (`test_honest.py`, a new class `DepthTwo`):

- **Depth 1 = D1:** with the root at the arena's cut-off (every depth-1 node a leaf) `depth = 2` gives D1's tables,
  choice, x, ys, gap and iterations bit for bit.
- **Same key, same strategy:** two worlds whose nodes share a stub key share one strategy and one candidate list;
  different keys are separate.
- **Node kinds at depth 1:** TERMINAL, cut-off, our-only (REPLACEMENT), foe-only (a foe PIVOT/REPLACEMENT), both.
- **Twice computed:** every decision of an A/B/C game computed twice gives the same record (timeless).
- **λ = 0 at depth 2:** the ev row of the root tables is played (decision 4, #486).

### Step 5. Refusals at depth 2 (#436's meaning per information set)

- A refused depth-2 leaf drops its own candidate at that information set (from every node of the set).
- An information set left without a candidate refuses every root edge that leads to it, so root row i leaves the solve,
  named in `refused_pairs` as today.
- A refused leaf at a foe-only node has only our empty response to drop, so it refuses root row i as well.
- No root row left: `Unreconstructible("engine_refused_leaves")`, played raw and counted, as today.
- Any other step status, an encoder refusal, a missing or stray tiebreak: SearchError with the reproduction (node
  index, world, pairs, node key, sample).
- Test: a refused leaf at depth 2 propagates by name (forced via a patched `expand`, as `refuse_pairs` does today).

### Step 6. The cut-off below the root

A depth-2 leaf is at the arena's cut-off when the root's step is the second-to-last. `decide` only gets `last_step`
today. `decide(..., steps_left=None)`, passed by `arena.SearchPlayer` from play_suite's step and `MAX_STEPS`; live
play passes an explicit "no limit" value (`honest.NO_STEP_LIMIT`). `depth = 2` with `steps_left` None is refused by
name, never a silent default; `depth = 1` ignores it, so its records do not change (decision 2, agreed with the search
lane via the owner). Tests: at two steps left the depth-2 leaves take the tiebreak and are counted as cut off; None is
refused at depth 2; the no-limit value values every depth-2 leaf.

### Step 7. `foe_below = "model"` (Q4's arm)

The foe at the depth-1 nodes follows its network's probabilities over its M2 candidates (renormalized) and has no
regrets. The root foe stays per world as in the LP. Test: the model arm keeps the foe's depth-1 strategies equal to its
prior; nash and model coincide where the foe has one candidate.

### Step 8. Record and the default proof

- Only a `depth = 2` record gains fields: `depth`, `k2`, `m2`, `chance`, `info_key`, `evaluator`, `foe_below`, the
  information-set count and merge share, the tree's iterations and gap, and the depth-2 leaf counts by kind (refused,
  terminal, cut-off, unresolved, open).
- **Default proof:** a test that the default and `depth = 1` named decide the A/B/C turns as main (pinned choices and
  tables, no new field), as D1's `test_the_default_root_solver_decides_as_on_main`. In the PR body: the SHA-256 digest of
  the A/B/C records on main c8ca7cee and on the branch head, identical, with both libraries' SHA-256.
- **Determinism across chunkings:** the same decisions with expand chunks of 16 and 7 (value call fixed) give
  byte-equal records.

### Step 9. The engine's observation digest (after Astra's field step is merged)

- Only after `restructure/4-field` is on main, agreed with Astra via the owner, with its own decision record.
- 32 bytes per leaf, folded on the stack over the event lines the viewer sees in the step (the lines the knowledge fold
  already consumes). No rule logic, no allocation.
- Either an output array of `duoforge_batch_expand` or a sibling call, as agreed with Astra.
- New public numbers (event, cause, feature) only from the HS, asked first. None is expected.
- Tests in C (equal lines → equal digest; a different damage line, switch-in or move order → different digest; the
  digest independent of worker, chunk and leaf position) and in Python (`info_key = "digest"` replaces the stub; the
  stub tests stay as tests of the tree).

### Step 10. D2's own offline pass (before any measurement)

D1's `RM_MAX_ITERATIONS` (1,770, from the search lane's offline pass) holds for D1's root only. The tree has other
tables and another cost per iteration, so D2 sets its own `TREE_MAX_ITERATIONS` by accuracy and time: a README first,
then the pass under the lock, its timing part with `--exclusive`, on recorded depth-2 trees (streamed, never all loaded
at once; the search lane's `rm_offline.py` is the template). `solver_unconverged` stays a named class-a decision:
counted, played without search, never a silent LP fallback. Arms count it separately; above 0.1 % of decisions the bound
is re-assessed.

### Step 11. Measurement README (no run)

`docs/benchmarks/<date>-depth-d2/README.md` with spec 9.2's arms ((2, 2), (3, 3), (4, 4), one `foe_below = "model"`
arm at the best width), the equal-time control, the gates, the kill criterion and the diagnostics, fixed before any
run. The run starts only after D1's offline pass, the predeclaration, and the HS's go, under `--exclusive` for latency,
or on AWS (#484) with the equality proof.

### Step 12. Review and PR

A review agent checks the whole branch. Its findings and their outcomes go into the PR body. The PR opens only after
Astra's field-step PR is merged and no Astra PR is open, then a green CI. The HS merges.

## Decisions (owner and HS, 2026-10-14)

1. **`info_key = "record"`** (the node's public record bytes for the viewer) is for tests only, refused by name under
   closed sheets. A measurement with it only on the HS's explicit decision.
2. **`steps_left`:** yes, agreed with the search lane via the owner. Live play passes an explicit "no limit" value;
   None stays refused at depth 2. Tested.
3. **Candidate weight per node:** p_w × the foe model's prior of j × the chance weight, renormalized.
4. **The root rule of spec section 5 stays unchanged**, λ = 0 of #486 included, with a test of λ = 0 at depth 2.
5. **The digest** is a new sibling call, no ABI break of `duoforge_batch_expand`, shareable with the D4 call. Where the
   fold lies after the field step, Astra answers in the D4 spec.
6. **D2's iteration bound** comes from its own offline pass (step 10), not from D1's.
