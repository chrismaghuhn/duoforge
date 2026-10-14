# D1 offline pass: the CFR+ root solver's iteration bound, by accuracy and by time (#481; predeclared 2026-10-14)

D1 (#482, merged as c8ca7cee) added `matrix.solve_bayes_rm`, a CFR+ solver for the turn decisions' Bayes game, as the
option `root_solver = "rm"`, switched off. Its iteration bound `RM_MAX_ITERATIONS = 10_000` is provisional. The review
of #482 measured about 0.4 ms per iteration at 16 × 8 × 8, so 10,000 iterations would break the 2 s live cap. This pass
fixes the default by accuracy **and** by time (HauptSession, 2026-10-14), on recorded tables, without playing a game
(spec `docs/superpowers/specs/2026-10-13-depth-search-design.md`, section 9.1).

**This section is a predeclaration. It is committed before any run of the pass.**

## Data and code

- **Tables:** every searched decision with tables in step 0's rebaselined ladder run at af168d56 (#440, `dirty:
  false`, 1024 pairs against `bot`, `bc6` and `ppo`). That is about 58k decisions in three private decision files:

  | file | sha256 prefix |
  |---|---|
  | `step-bot-decisions.jsonl` | `247e70ea` |
  | `step-bc6-decisions.jsonl` | `3a180e33` |
  | `step-ppo-decisions.jsonl` | `3039d56b` |

  Each decision is solved again as the search reduced it, from the record's own fields: `tables`, `weights`,
  `foe_probs`, `own_probs`, the play uniform `u` and `lam`.
- **Tool:** `python -m duoforge_search.rm_offline`, on this branch (`search/d1-offline`), at the commit that adds this
  section.
- **Library:** `libduoforge_shared.so` built from main 86e46a15 (sha256 `76c9caeb…3efb`). Main has had no C change
  since.
- **Solver settings:** ε = 1e-3 of the range (Q1), the gap checked every 10 iterations (`RM_CHECK_EVERY`), and the
  BC6 prior.

## The runs

1. **Accuracy (A):** every decision, `--max-iterations 100000`, `--workers 8`, under the machine lock with the label
   `search-d1-offline`. Not exclusive, so its seconds are not used.
2. **Time (B):** a fixed subsample (`--every 20`: every 20th searched decision, about 2.9k), `--max-iterations 100000`,
   `--workers 1`, under the lock with `--exclusive`. Only B's seconds count.

Each run reports its commit and its `dirty` flag.

## Fixed now

- **T_acc,** the bound by accuracy: twice the largest iteration count that any recorded decision of run A needed to
  reach ε, rounded up to a multiple of 10. The factor 2 is a margin for unseen tables. The recorded tables then never
  reach the bound (Q1). If any decision of run A misses ε at 100,000 iterations, T_acc is undefined: the pass reports it
  and sets no default.
- **T_time,** the bound by time: the iteration count at which a solve costs 0.4 s locally, from run B's p99 of RM
  seconds per iteration, rounded down to a multiple of 10.
  - **Why 0.4 s:** the VPS cores are about 3× slower, which puts the solve at about 1.2 s there. The rest of the
    VPS bound of 1.67 s stays for the search around the solve; step 0's exclusive p99 is 0.10–0.17 s locally.
- **The default:**
  - If T_acc ≤ T_time, `RM_MAX_ITERATIONS` becomes T_acc.
  - Otherwise no default is chosen. The pass reports both bounds, and the HauptSession and the owner decide: a time
    above 0.4 s, a larger ε, or a counted share of `solver_unconverged`.
- **Reported, not gated** (spec 9.1):
  - the iterations to reach ε (median, p99, max), and the share solved by each bound T;
  - the RM value against the LP value, as a share of the range;
  - choice agreement under nash (the same play uniform), ev and mix;
  - the mass RM's average puts on rows the LP gives 0;
  - the LP's exact rescues;
  - LP and RM seconds per decision (run B only).

  Agreement is no gate: where a game has several equilibria, the LP returns one vertex and RM's average another
  point of the same set, so nash and mix may legitimately differ. D1 solves the same game.
- **Disclosed:** before this predeclaration, a 20-decision smoke of the tool ran (every 97th decision) to check that
  it works. Its numbers fix nothing here and are not reported as a result.

## Results (2026-10-14)

### Provenance

| run | commit | dirty | settings | window |
|---|---|---|---|---|
| B, time | 0f1ad8e1 | false | every 20th decision (2,860), 1 worker, `--exclusive` | 01:18:09.5–01:19:47.1 |
| A, accuracy | 2e3c9f09 | false | all 57,191 decisions, 8 workers | 01:25:56–01:34:45 |

- **Library:** main 86e46a15's (Release, `duoforge_shared`), sha256 `76c9caeb…3efb`.
- **A's commit:** two commits after 0f1ad8e1:
  - fca352b1 hands the pool a bounded block at a time. The first try of A held every table in memory (2.7 GB) and was stopped at 10,000 decisions; nothing of it is used.
  - 2e3c9f09 adds a test that the pool reads at most one block ahead.

  Neither changes a row (a test compares 2 workers to 1). B ran with 1 worker and never used the pool. A ran after the tool's tests passed in the same lock ticket. It was queued at fca352b1 and ran at 2e3c9f09. The report did not record its commit then; it does now (commit, dirty, library, CPU).
- **B ran alone:**
  - It waited for the whole machine from 01:09:51 (`machine_lock --exclusive`, which takes every slot) and ran 01:18:09.5–01:19:47.1 (its log's birth and last write).
  - The next holder was the D2 lane's library build, through the lock from 01:20:00. Its file times: export 01:20:00.48, cmake configure 01:20:01–01:20:15, build 01:20:15–01:20:23. There was no overlap.
  - The lock keeps no log, so the evidence is the owner lines and the file times. The HauptSession accepted B, its times included.

### The bounds

| | measured | bound |
|---|---|---|
| T_acc: iterations to reach ε = 1e-3 of the range (A, all decisions) | median 50, p99 280, **max 1,710**; 0 unconverged at 100,000 | **2 × 1,710 = 3,420** |
| T_time: RM seconds per iteration (B, exclusive) | median 0.126 ms, **p99 0.2256 ms** (0.22565), max 0.394 ms | **0.4 s / 0.22565 ms = 1,772.7 → 1,770** (rounded down to a multiple of 10) |

**T_acc (3,420) > T_time (1,770).** By the rule fixed above, **no default is set**: the HauptSession and the owner decide.
- **How rare the slow tail is:** only 3 of 57,191 decisions needed more than 1,280 iterations, and 31 more than 640. None needed more than 1,770, so T_time itself would not have cut any recorded decision. It would only lack the predeclared factor 2.
- **The share solved by a bound T:**

  | T | 40 | 80 | 160 | 320 | 640 | 1,280 | 2,560 |
  |---|---|---|---|---|---|---|---|
  | solved | 37.3 % | 75.4 % | 94.9 % | 99.35 % | 99.95 % | 99.995 % | 100 % |

- **The slowest decisions** are full 16 × 8 × 8 tables (1,710; 1,670; 1,320; then ≤ 1,010 iterations). None needed the LP's exact rescue.

### Reported, not gated (spec 9.1, run A)

- **RM against the LP:** the LP value minus the RM value, as a share of the range: median 2.0e-4, p99 9.5e-4, max 1.0e-3. Always within ε, as the stopping rule guarantees.
- **Choice agreement** (the same play uniform): nash 86.8 %, mix 92.5 %, ev 100 % (ev does not depend on the solver).
- **The mass RM's average puts on rows the LP gives 0:** median 0.2 %, p90 49.9 %, p99 99.9 %.
  - Where a game has several equilibria, the LP returns one vertex and RM's average another point of the same set.
  - This is why nash and mix choices differ while the values agree.
- **The LP's exact rescue** ran in 4 of 57,191 decisions.
- **Seconds per decision (B, exclusive, 1 worker):**

  | | median | p99 | max |
  |---|---|---|---|
  | LP | 2.1 ms | 9.3 ms | 127 ms |
  | RM | 7.3 ms | 34 ms | 78 ms |

- **Shapes:** 47,162 of the 57,191 tables are 16 × 8 × 8. The rest are smaller after refused or masked pairs.

### Decision (the HauptSession and the owner, the owner afterwards on 2026-10-14, #481): `RM_MAX_ITERATIONS = 1,770`, the time bound

- **The predeclared rule gave no value:** T_acc, twice the maximum (3,420), exceeds T_time (1,770).
- **Why the time bound:** the HauptSession chose it, and the owner agreed afterwards (a comment on #481), because it cuts none of the 57,191 recorded decisions (max 1,710). What it gives up is the factor-2 margin for unseen tables.
- **`solver_unconverged` stays a named class-(a) decision:** counted, and played without search. There is no LP fallback; that would be a rule of its own, measured in an arm of its own.
- **The D1 ladder arm and any live run count `solver_unconverged` apart.** If its share in an arm exceeds 0.1 %, the bound is re-evaluated.
- **The bound holds for D1's root only.** D2's tree gets an offline pass of its own.
- Live stays `root_solver = "lp"`.
