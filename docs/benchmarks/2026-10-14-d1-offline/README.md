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

## Results

None yet.
