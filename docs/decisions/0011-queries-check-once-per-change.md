# 0011 — Model-facing queries check once per change

Status: owner decision 2026-10-01 ("ja bau sie so"); library 0.8.0.

## 1. Problem

A sampling profile of battles with the uniform random policy (GCC, `-O2 -g`, the benchmark workload) put about 41 percent of the time into state checks, 36 percent into the candidate enumeration and 20 percent into the battle itself. At every decision point the full check ran about seven times (request, candidates and observe for each player, then the step's input) on a state that changes only in the step. Most of a full check is the re-derivation of every CLOSURE member: stats and HP maximum from the formulas, PP maxima, moves of the set.

## 2. Options put to the owner

- **Checks only in Debug builds.** Rejected. Release builds produce the training data: a corrupted battle would pass silently and a query could read out of bounds; Debug and Release would behave differently (AGENTS.md: fail explicitly, never silently).
- **A hash of the validated state, compared by every query.** As safe as today, but every query still reads the whole state; the gain is smaller than it looks.
- **Check once per change.** Chosen.

## 3. Decision

- The full check runs where a battle changes or leaves the engine: create, step (its input in full, its result relative to the input, decision 0008 section 7), decode, encode, digest and check.
- The model-facing queries (request, candidates, observe) run the query check (`dfi_state_check_query`): every rule except a CLOSURE member's derived values and move legality (`dfi_closure_member_ranges` runs instead of `dfi_closure_member_valid`). Every index, count and divisor stays checked, so a query never reads out of bounds.
- A battle whose member values were corrupted between calls passes the queries (their answers may reflect the corruption) and is reported with `E_INVARIANT` by the next step, encode, digest or check. Debug and Release behave the same.
- Battle semantics, outcomes, digests and state artifacts do not change. The library version moves to 0.8.0 because the queries' contract for corrupted battles changed.

## 4. Evidence

- `duoforge.request.query_checks`: corrupted derived values (a stat, a PP maximum, a repeated move) pass the three queries and fail check, step, encode and digest; corrupted indices, counts and divisors (nature, species, move id, HP maximum zero) fail the queries. With the full check in the queries, the test fails.
- The earlier query corruption cases (request mask, PP above the maximum) still fail in the queries.
- The full check's result is unchanged: `dfi_closure_member_valid` is the conjunction of the same conditions, split into the range part and the derived part.

## 5. Measured (2026-10-01)

A = d5be9e4 (main), B = this change (6bba955; the GCC binary at c8acc36, which adds only this note and the version string). Release builds, `duoforge_bench --battles 1000 --repetitions 5 --warmup 1`, three rounds per compiler with A and B alternating, CPU load 9 to 19 percent; only runs without disturbed repetitions count (GCC A 3, B 2; Clang A 3, B 3; MSVC A 1, B 2). Median time of the whole workload in ms:

| Family | GCC A | GCC B | A/B | Clang A | Clang B | A/B | MSVC A | MSVC B | A/B |
|---|---|---|---|---|---|---|---|---|---|
| STEP_CORE `plain` | 216.2 | 206.2 | 1.05 | 200.4 | 200.3 | 1.00 | 248.5 | 250.0 | 0.99 |
| REQUEST `request+candidates+observe` | 476.0 | 339.1 | 1.40 | 487.9 | 352.9 | 1.38 | 607.6 | 421.5 | 1.44 |
| EPISODE_NATIVE `uniform-random` | 651.4 | 540.0 | 1.21 | 655.4 | 558.3 | 1.17 | 799.1 | 661.2 | 1.21 |
| &nbsp;&nbsp;part `policy` | 359.0 | 272.0 | 1.32 | 370.2 | 289.1 | 1.28 | 453.6 | 337.5 | 1.34 |
| &nbsp;&nbsp;part `step` | 208.2 | 207.2 | 1.00 | 198.1 | 204.4 | 0.97 | 241.9 | 248.7 | 0.97 |

The queries are 1.38 to 1.44 times as fast, a battle with the random policy 1.17 to 1.21 times (GCC 6,140 to 7,407 battles per second, Clang 6,103 to 7,165, MSVC 5,005 to 6,049, one core); the step is unchanged, as intended. The query check still runs every structural rule; after this change the largest costs of a battle are the candidate enumeration (about 43 percent in the profile) and the structural check.
