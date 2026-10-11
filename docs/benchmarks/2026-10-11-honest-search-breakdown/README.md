# Where the honest search's time goes (issue #355, 2026-10-11)

**Question.** The 75% coverage gate asks where a decision's time goes before the next steps are chosen. This report covers the honest search X as the live mode plays it: K = M = 8, 16 worlds, mix 0.5.

**Answer.** Almost all of it goes to one padded network call.
- The value call evaluates the whole leaf buffer, 16384 rows, although a decision has only K · M · S = 1024 leaves. That call is **93%** of a decision.
- With a buffer of 1024 rows, the median decision drops from **0.52 s to 0.071 s (7.3×)**.
- The engine parts are small next to it:
  - expanding 1024 leaves (clone, reseed, step, encode) takes about 7 ms;
  - building the 16 worlds from the public record takes 0.4 ms.

## Setup

- **Machine:** this one, AMD Ryzen 7 5800X (16 threads), WSL Ubuntu 24.04. Run alone under `tools/ci/machine_lock.sh --exclusive`.
- **Code and runtime:** main 0bc8d8d9, Release build, JAX 0.11.2 on the CPU, NumPy 2.5.3.
- **Network:** params-49333 (model v2, encoder 4), the live mode's network. It stays private; this report quotes aggregates only.
- **Search:** `honest.Honest` with the live spread table and `species_prior`. Seat 0 searches and seat 1 plays the raw argmax.
- **Games:** 8 games on the reference setups 0-3. That gives 75 searched decisions per capacity.
- **Script:** `tools/perf/honest_breakdown.py` (the docstring lists every part):

  ```
  python tools/perf/honest_breakdown.py --checkpoint params-49333.npz --out DIR --games 8
  ```

## Per decision (searched decisions, the search's own cost fields)

| part | capacity 16384: mean s | share | capacity 1024: mean s | share |
|---|---|---|---|---|
| network (root and world policy calls, value calls) | 0.5075 | 92.9% | 0.0369 | 44.9% |
| world builds (`from_view`, the worlds' encoded queries and policy) | 0.0081 | 1.5% | 0.0104 | 12.7% |
| solve (Bayes matrix game, certificate, mix) | 0.0058 | 1.1% | 0.0080 | 9.7% |
| team head (the foes' team draws) | 0.0061 | 1.1% | 0.0068 | 8.3% |
| leaves (`Batch.expand`: clone, reseed, step, encode in C) | 0.0035 | 0.6% | 0.0043 | 5.2% |
| public records | 0.0008 | 0.1% | 0.0010 | 1.2% |
| **decision wall time, median (mean)** | **0.520 (0.547)** | | **0.071 (0.082)** | |

The fields do not add up to the wall time. The remainder is Python bookkeeping between the parts: the hypotheses, the table and the records.

## The parts in isolation (median of 20 warm runs)

| part | seconds |
|---|---|
| value call, 16384 rows | 0.677 |
| value call, 1024 rows | 0.031-0.035 |
| `Batch.expand`, 1024 leaves (clone + reseed + step + encode) | 0.0066-0.0070 |
| `step_factored`, 1024 environments (one step, no clone) | 0.003-0.007 (single run) |
| `query_encoded` − `query_factored`, 1024 environments (the encoder) | 0.0015-0.0031 |
| `from_view`, 16 worlds | 0.0004 |

## Paired check: the same decisions, faster (review of #401)

The tables above compare the two capacities on different positions, because each run's games follow its own choices. This check runs both capacities on the very same roots: `honest_breakdown.py --paired`, 8 games, 75 searched decisions. The order of the two calls alternates per decision. The game follows capacity 16384's choice.

| | value |
|---|---|
| same choice (16384 against 1024) | **75 of 75** |
| same candidates and table shape | 75 of 75 |
| largest leaf-value difference | 1.4 · 10⁻⁶ |
| largest table-entry difference | 1.4 · 10⁻⁶ |
| median decision time, 16384 → 1024 | 0.497 s → 0.079 s |
| median paired time ratio | **6.3×** |

The values differ only in the float32 last bits, which is the lookahead's documented batch-shape effect. No decision changed.

## The live path's latency at both capacities

`python -m duoforge_search.live_latency --capacity C`: 16 games, the live search's path (LiveSearch over the batch's parts), seconds per decision.

| boundary | n | capacity 1024: p50 / p95 / p99 | capacity 16384: p50 / p95 / p99 |
|---|---|---|---|
| turn | 150 | 0.056 / 0.066 / 0.071 | 0.533 / 0.639 / 0.696 |
| replacement | 15 | 0.049 / 0.060 / 0.060 | 0.506 / 0.617 / 0.617 |
| pivot | 6 | 0.004 / 0.004 / 0.004 | 0.004 / 0.005 / 0.005 |
| team selection | 16 | 0.004 / 0.452 / 0.452 | 0.005 / 0.657 / 0.657 |

- **Loading:** 4.1 s and 4.7 s.
- **Team selection:** its p95 is the first decision's compile.

## Provenance

- **Code:** the measurements of the two sections above ran on m12/bottleneck at ba7289b7 (main 0bc8d8d9 merged in), with that commit's Release library, under `tools/ci/machine_lock.sh --exclusive`, on 2026-10-11.
- **Scripts:** `tools/perf/honest_breakdown.py` and `python/duoforge_search/live_latency.py` at that commit.
- **Earlier tables:** the first tables came from b92f2464's script (before `--paired`), on main 0bc8d8d9.
- **Raw output:** `breakdown.json` and `latency.json` are private, outside the repository. This report quotes their aggregates only.
- **Paired run, other numbers:**
  - capacity 16384: 75 decisions, median 0.515 s, network 92.4%;
  - capacity 1024: median 0.052 s, network 46.4%;
  - isolated value call: 0.513 s for 16384 rows against 0.024 s for 1024 rows.

## What follows

1. **The live mode should size its leaf buffer to its leaves:** capacity = K · M · S = 1024 instead of `lookahead.CAPACITY` (16384). It is measured at 7.3× per decision across runs and 6.3× paired on the same roots, with the same decisions (75 of 75, values within 1.4 · 10⁻⁶). The lookahead's docstring says another batch shape changes the network's values in the last bits. A decision is therefore reproducible per capacity, and the capacity belongs to the search's settings. The live mode is no pinned artifact (P1's manifest pins its own capacity, untouched here).
   - This is applied in this PR as `HONEST_SETTINGS["capacity"] = 1024`.
   - The arena of #362 runs with it.
2. **The engine is not the bottleneck of the search** today: under 6% of a decision, even at capacity 1024. Faster stepping or encoding would not move the search's time.
3. **After the fix, a decision is about half network.** The rest splits into world building (13%), the solve (10%) and the team head (8%). The next levers are the network's batching across decisions (P2's dedup measurement, about 2.7× fewer rows) and the remaining Python bookkeeping.
4. **Strength is not measured here.** Where strength is lost is the arena's (#362) and the paired evaluation's (#356) question.
