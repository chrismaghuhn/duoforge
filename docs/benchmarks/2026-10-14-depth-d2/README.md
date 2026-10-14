# D2, the two-turn tree: its offline pass and its ladder arms (predeclared 2026-10-14)

D2 of the depth search (spec `docs/superpowers/specs/2026-10-13-depth-search-design.md`, sections 8 and 9.2; plan
`docs/superpowers/plans/2026-10-14-depth-search-d2.md`, steps 10 and 11) adds `depth = 2` to the honest search, off by
default: a full-width tree over two turns, solved by CFR+ (`tree.solve_tree`), the root played by the root rule of
spec section 5 unchanged.

**This file is a predeclaration, committed before any run of the offline pass.** Part 2 (the arms) stays a
predeclaration until its own go. Every run starts only on the HauptSession's go, under the machine lock.

## Part 1: the offline pass (plan step 10)

D1's `RM_MAX_ITERATIONS` (1,770, decided on D1's own pass) holds for D1's root only. The tree has other tables and
another cost per iteration, so `tree.TREE_MAX_ITERATIONS` (provisional 10,000) is fixed here by accuracy and by time,
before any D2 arm runs.

### Data and code

- **No recorded trees exist.** The pass therefore replays games and builds a tree beside each decision without
  playing it ("shadow"): the games are step 2e's (the adopted step whose root rule the D2 arms inherit, spec section
  5), seed `0x2026101200000440`, the ladder's pool, against `bot`; at every searched turn decision a second, depth-2
  search builds and solves the tree of the same root and records it; the move played is 2e's.
- **Provenance of the games:** the shadow never changes a move. The decisions digest of the played (2e) records is
  reported beside the digest of a plain 2e run on the same commit; they must agree, else the pass reports it and fixes
  nothing.
- **Tool:** `python -m duoforge_search.tree_offline` (to be built, the next commit on this branch, with tests): per
  shadow decision the widths, the node, information-set and leaf counts, the iterations CFR+ needs to reach ε, its gap,
  and the seconds of each phase (depth-1 policy call, leaf evaluation, tree solve). Rows are streamed to a JSONL file
  as they come (never held in memory), the report holds counts and quantiles; rows stay with the run, outside the
  repository.
- **Library:** `libduoforge_shared.so` of the commit the pass runs at (its sha256 in the results).
- **Solver:** ε = 1e-3 of the tree's range (Q1), the gap checked every 10 iterations, priors as the search gives them,
  `foe_below = "nash"`.
- **The observation key (HauptSession, 2026-10-14):** `info_key = "record"`, open team sheets only (the ladder's
  games are open). Its information sets may merge differently from the engine digest's (the record never splits by a
  hidden fact, but may merge nodes whose lines differ). Therefore:
  - decisions where the engine refuses a depth-1 node's public record end as `observation_key_refused`; they are
    counted by name, left out of the bound, and their share is reported here;
  - **gate before any arm:** the bound is checked again on trees keyed by the engine digest (plan step 9); if it
    differs, the new one holds;
  - the seconds are provisional until confirmed with the digest; until then they do not replace spec section 6.2.
- **Commit, library:** the pass runs at the commit that adds this section (its hash and `dirty: false` in the
  results), with `libduoforge_shared.so` built from c8ca7cee, sha256
  `76c9caeb2d8c59c3dff6a1e07b5e305a256b78a12c896efd2edf2312145e3efb` (the C sources are unchanged from c8ca7cee to
  the branch head, main a7dd956b merged).
- **The shadows' settings:** step 2e's (the ladder's STEP0 with rule ev) plus `depth = 2`, `root_solver = "rm"`,
  `rm_iterations` and `tree_iterations` = `--max-iterations`, the value call padded to 16,384 rows (spec section
  7.2), `info_key = "record"`, `foe_below = "nash"`.
- **Disclosed:** before this file's final commit, a smoke of the tool ran (1 pair against `bot`, width 2) to check
  that it works. Its numbers fix nothing here and are not reported as a result.

### The runs

1. **Accuracy (A):** 64 pairs against `bot`, widths (K2, M2) = (2, 2), (3, 3) and (4, 4), each a shadow of its own,
   `--max-iterations 50000`, `--plain-check` (the games once without shadows first: both decisions digests in the
   report), 8 workers, under the lock with the label `d2-offline-a`, not exclusive (its seconds are not used), and
   not beside another heavy job while memory is short.
2. **Time (B):** the same games, every 10th searched decision, widths (4, 4) and (2, 2), `--workers 1`, under the lock
   with `--exclusive` and the label `d2-offline-b`. Only B's seconds count.
3. One ticket per label; the owner files and the queue are checked before each start.

Each run reports its commit, its `dirty` flag and the library's sha256.

### Fixed now

- **T_acc:** twice the largest iteration count any decision of run A needed to reach ε, over all widths, rounded up to
  a multiple of 10. If any decision misses ε at 50,000 iterations, T_acc is undefined: reported, no default set.
- **T_time:** the iteration count at which the tree solve costs 0.4 s locally, from run B's p99 of solve seconds per
  iteration at (4, 4), rounded down to a multiple of 10 (the same solve budget as D1's root: the VPS is about 3x
  slower, and the rest of the 1.67 s local bound stays for the evaluation around the solve).
- **The default:** T_acc if T_acc ≤ T_time; otherwise none, and the HauptSession and the owner decide (as for D1).
- **`solver_unconverged`** stays a named class-(a) decision: counted, played without search, never a silent LP
  fallback. The arms count it apart; above 0.1 % of an arm's decisions the bound is re-assessed.
- **Reported, not gated:** the iterations to ε per width (median, p99, max) and the share solved by each T; the tree's
  gap; the information sets and the merge share; the leaf kinds; the seconds per phase and width (run B), against
  spec section 6.2's estimates; how often the shadow's root choice differs from 2e's.

### Results (2026-10-14)

#### Provenance

| run | label | settings | window | commit | dirty |
|---|---|---|---|---|---|
| A, width 2 | `d2-offline-a2` | 64 pairs vs `bot`, `--plain-check`, 8 workers | 05:21:41–05:42:23 | 060ef58d | false |
| A, width 3 | `d2-offline-a3` | 64 pairs vs `bot`, 8 workers | 05:43:26–05:59:43 | 060ef58d | false |
| A, width 4 | `d2-offline-a4` | 64 pairs vs `bot`, 8 workers | 06:00:06–06:16:42 | 060ef58d | false |
| B, widths 4 and 2 | `d2-offline-b` | every 10th decision, 1 worker, `--exclusive` | 06:17:07–06:22:15 | 060ef58d | false |

- **Library:** `~/df-build/d2-c8ca7cee/libduoforge_shared.so`, sha256
  `76c9caeb2d8c59c3dff6a1e07b5e305a256b78a12c896efd2edf2312145e3efb`, the one named above (checked again after the PC
  restart of 2026-10-14).
- **Deviations from the predeclaration, disclosed:**
  - **The commit:** the runs ran at 060ef58d, not at 11b7797e. Between them only the ladder's D2 STEPS entries, this
    file's part 2 and the digest's draft decision record changed; `tree_offline`, `honest` and `tree` did not, and
    step 2e's settings are the same (HauptSession, 2026-10-14).
  - **The labels:** A ran as three tickets, one per width (`d2-offline-a2`, `-a3`, `-a4`), not as `d2-offline-a`
    (HauptSession, for memory). The results do not depend on it.
  - **Two aborted starts, nothing of them used:** the first start of A (`accA-11b7797e`, 03:14:55) and the first start
    of a2 (`accA2-11b7797e`, 03:21:03) lost their lock wrappers (the first stopped by this lane, the second by Claude
    Code under memory pressure) and ran on outside the lock until the HauptSession had them stopped.
- **The games:** the played (2e) decisions digest is `5aea9b5a…` in all four runs; a2's plain run without shadows gives
  the same digest (`equal: true`). The shadows changed no move.
- **The memory guard:** every run started with at least 8 GB free on Windows (16,611–17,899 MB at the start); the
  watcher never saw less than 3 GB.

#### The bounds

| | measured | bound |
|---|---|---|
| T_acc: iterations to ε = 1e-3 of the range (A, all 956 keyed decisions per width) | max 340 (width 2), 450 (width 3), **490** (width 4); 0 unconverged at 50,000 | **2 × 490 = 980** |
| T_time: tree-solve seconds per iteration (B, exclusive, width 4) | median 0.851 ms, **p99 1.404 ms**, max 1.620 ms | **0.4 s / 1.404 ms → 280** |

**T_acc (980) > T_time (280).** By the rule fixed above, **no default is set**: the HauptSession and the owner decide
(the bound they set is below). At 280 iterations, 0.31 % (width 2), 0.84 % (width 3) and 0.84 % (width 4) of A's keyed decisions would end as
`solver_unconverged`, above the 0.1 % at which an arm's bound is re-assessed. At 490 none would.

- **Share solved by a bound T** (A, width 4): 40: 29.7 %; 80: 65.2 %; 160: 93.3 %; 320: 99.58 %; 640 and above: 100 %.
- **Iterations to ε** (A): median 60 / 60 / 70, p99 240 / 264.5 / 270 for widths 2 / 3 / 4.

#### The bound set (HauptSession and owner, 2026-10-14)

`tree.TREE_MAX_ITERATIONS = 490`: the largest count any of A's keyed decisions needed, so no recorded decision is cut
off. **This departs from the rule fixed above**: the default would have been T_acc = 2 × 490 = 980, and only if
T_acc ≤ T_time = 280. The bound drops the factor 2 and exceeds T_time. At 490 the tree solve costs up to about
490 × 1.404 ms ≈ 0.69 s (B's p99 per iteration), above the 0.4 s the rule assumed.

- **Gate before any arm:** the bound is checked again on trees keyed by the engine digest (decision 0082). If an arm's
  `solver_unconverged` share exceeds 0.1 %, the bound is assessed again before that arm counts.
- **Not live:** the live gate asks for an exclusive local p99 ≤ 0.67 s; the three tree phases alone take median
  0.83 s, p99 1.04 s (below), 0.55 s of it the depth-2 evaluation. D2 runs the ladder first; then the owner and the
  HauptSession decide whether live waits for D4's evaluation or the live budget is raised.

#### `observation_key_refused` (the record key's gap)

206 of 1,162 shadow decisions per width in A (17.7 %), 40 of 234 in B (17.1 %): a depth-1 node's public record was
refused by the engine, so the record key had no key; those decisions are counted by name and left out of the bounds.
The engine digest keys every node; the bound is checked again on digest-keyed trees before any arm (the gate above).

#### Reported, not gated (provisional until confirmed with the digest; they do not replace spec section 6.2)

- **Seconds per phase** (B, exclusive, 1 worker, 97 keyed decisions per width; the root's own work comes on top):

  | width | depth-1 policy | depth-2 evaluation | tree solve | the three together |
  |---|---|---|---|---|
  | 2 | median 0.212 s, p99 0.277 s | median 0.495 s, p99 0.565 s | median 0.038 s, p99 0.160 s | median 0.754 s, p99 0.919 s |
  | 4 | median 0.212 s, p99 0.246 s | median 0.545 s, p99 0.699 s | median 0.052 s, p99 0.208 s | median 0.825 s, p99 1.036 s |

  The evaluation is padded to 16,384 rows at every width (spec section 7.2), so width 2 pays width 4's value call.
- **Tree shape** (B): about 1,021 depth-1 nodes per decision, median 308 information sets, merge share median 0.709.
- **The root choice differs from 2e's** in 54 of 97 (width 2) and 56 of 97 (width 4) decisions of B's subsample.
- A's seconds are diagnostic only (non-exclusive) and not reported here.

## Part 1b: the bound re-checked on digest-keyed trees (predeclared 2026-10-14)

The bound `tree.TREE_MAX_ITERATIONS = 490` was set on record-keyed trees (above). Before any arm it is checked on
trees keyed by the engine's observation digest (decision 0082, `duoforge_batch_expand_digest`; the gate set above).
**This section is a predeclaration, committed and pushed before its runs**, which start on the HauptSession's go
(given 2026-10-14 for once the key reads the real call), under the machine lock and the WSL watchdog.

### Data and code

- **Games:** as part 1: step 2e, seed `0x2026101200000440`, the ladder's pool, 64 pairs against `bot`; at every
  searched turn decision a depth-2 shadow builds and solves its tree beside it; the move played is 2e's.
- **The shadows' settings:** as part 1, except `info_key = "digest"`: `depth = 2`, `root_solver = "rm"`,
  `rm_iterations` and `tree_iterations` = `--max-iterations 50000` (so the iterations to ε are seen beyond the bound),
  the value call padded to 16,384 rows, `foe_below = "nash"`, ε = 1e-3 of the range.
- **Tool:** `python -m duoforge_search.tree_offline --info-key digest`, rows streamed to a JSONL file outside the
  repository; the report's `over_bound` gives, per width, the share of keyed decisions (converged or not) that 490
  would cut off: more iterations than 490, or unconverged at 50,000.
- **The games are checked again:** the engine's C changed since part 1 (#489, E1a, E1b), so the width-2 run plays
  the games once without shadows first (`--plain-check`); both decisions digests are reported. Part 1's games digest
  is not compared.
- **Commit, library:** the commit that switches the key to the real call (E1b on main merged), its hash and
  `dirty: false`, and the sha256 of `libduoforge_shared.so` built from it, in the results.

### The runs

Widths (K2, M2) = (2, 2), (3, 3) and (4, 4), one run each, one at a time: labels `d2-digest-a2`, `d2-digest-a3`,
`d2-digest-a4`, 8 workers, not exclusive (no seconds are used), through `tools/ci/wsl_lock_watchdog.sh` inside
`tools/ci/machine_lock.sh`. A run starts only with at least 8 GB free on Windows (the job refuses otherwise). One
ticket per label; owner files and queue are read before each start.

### Fixed now

- **The gate:** if `over_bound` exceeds **0.1 %** at any width, the bound is re-assessed by the HauptSession and the
  owner before any arm; otherwise 490 holds for the arms.
- **Reported, not gated:** the iterations to ε per width (median, p99, max) and part 1's rule on them (twice the
  maximum), for comparison only; `observation_key_refused` and its share (counted by name; the digest refuses only a
  projection it cannot classify or a re-prompt root); the information sets and the merge share beside part 1's; the
  leaf kinds; how often the shadow's root choice differs from 2e's.
- **Disclosed:** before the first run, a smoke of the switched key (1 pair against `bot`, width 2) may run to check
  that the call works; its numbers fix nothing and are not reported as a result.

## Part 2: the ladder arms (plan step 11, spec section 9.2)

### Arms

All with step 2e's root rule (`rule = "ev"`, spec section 5), `root_solver = "rm"`, `info_key = "digest"` (unless the
HauptSession decides otherwise), `foe_below = "nash"`, the value call padded to 16,384 rows (spec section 7.2):

The arms are fixed entries of `ladder.STEPS` (names agreed with the AWS campaign #484, which starts an arm by its
name alone):

| arm | depth-2 widths | other |
|---|---|---|
| `d2-22` | K2 = M2 = 2 | |
| `d2-33` | K2 = M2 = 3 | |
| `d2-44` | K2 = M2 = 4 | |
| `d2-model-22`, `d2-model-33`, `d2-model-44` | as the arm of the same width | `foe_below = "model"` (Q4); only the one at the best width by its head-to-head point estimate runs |

The equal-time control of each arm: the one-turn arm (`root_solver = "rm"`, rule ev) from `d2c-k12m12`, `d2c-k16m16`,
`d2c-s32`, `d2c-s48`, `d2c-s64` whose exclusive latency p99 is closest to the D2 arm's, ties to the one with more
leaves. Both latencies are measured locally, exclusive, before the control's strength run; on AWS only the chosen
arms run.

### Gates (spec 9.2, as #440)

- **Strength:** head-to-head against step 2e, the lower bound > 0.50, 0 unresolved, 1024 pairs.
- **No harm:** against `bot` and `bc6`, the upper bound ≥ 0.50.
- **Reproduced:** the arm's games again from its seed (scores and decision digests).
- **Fallbacks:** at most 5 % (or 2e's share + 1 point); `solver_unconverged` and `observation_key_refused` reported
  apart.
- **Latency:** exclusive p99 ≤ 1.67 s local; for live adoption additionally ≤ 0.67 s local (Q2: the 2 s VPS cap).
- **Against the equal-time control:** the lower bound > 0.50, 512 pairs.
- **The mirror touchstone** (Team A against the private sun team, piloted by the live search): no harm, the upper
  bound ≥ 0.50, at least 512 pairs; the sim-pilot touchstone is reported only.

### Kill criterion (fixed now)

If no D2 width beats its equal-time control at its point estimate, depth with the BC6 value is parked, and the
evaluation (#451, #450 piece 2 / D4) comes before D3 and D5.

### Metrics and diagnostics (reported, not gated)

- The KO check per arm, with intervals, split into "not a candidate" and "among the candidates, not chosen". Fixed
  expectation: depth moves the answered-foe-threat row more than the own-KO row.
- The merge share, the tree gap, the depth-2 leaf kinds, how often the root choice differs from 2e's and from D1's.
- The plan's test positions A to D (private live positions, replayed with `ko_check --closed`), each arm's choice
  beside 2e's and step 0's; never a gate.

### Where and when

- **Strength runs on AWS** (#484, HauptSession and owner 2026-10-14): one instance type per series (c7a.16xlarge),
  8 workers per arm (16 CPUs fixed), 3 arms in parallel on one instance (whether 4 may run in parallel, the
  HauptSession decides after the first run), the ISA pinned as fixed locally (XLA `--xla_cpu_max_isa`,
  `OPENBLAS_CORETYPE`, one thread) and the versions pinned. Each arm writes its own digests; the equality proof checks
  an arm alone and beside the others. A D2 arm and its opponent arm (2e, or its control) run in the same AWS run on
  the same instance type. AWS and local results are never mixed or paired. Only the HauptSession starts AWS, from its
  own chat.
- **Locally:** the latency (exclusive p99) and the mirror touchstone (the private sun team stays off the bucket).
- Only after this file's final commit, the offline pass's default, the engine digest (if the arms use it) and the
  HauptSession's go. Latency always with `--exclusive`; strength runs alone, not beside the Book slot, while memory is
  short.
