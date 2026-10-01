# 0012 — Batch runtime (M6)

Status: owner decision 2026-10-01 ("bau einmal Industriestandard", the four points below); first part implemented, library 0.9.0.

## 1. Model

EnvPool's design: the loop over the environments runs entirely in C on a fixed pool of worker threads, and a client calls it once per batch. At about 10,000 battles per second and core, a per-environment call from Python would cost more than the battles; the binding (M7) releases the GIL around one batch call and hands NumPy arrays as the output buffers, so nothing is copied. Gymnasium's vector environments are Python-side (synchronous, or asynchronous over subprocesses) and are not the model. This first part is EnvPool's synchronous mode (every environment one step); an asynchronous mode (send/receive with partial batches) follows only if a measurement shows idle workers.

## 2. Decisions

1. **A thin layer over the single-battle API** (`include/duoforge/duoforge_batch.h`, library `duoforge_batch`). The rule core is untouched; every environment is an ordinary `duoforge_battle` and every operation a single-battle call, so a batch plays exactly what the same calls one by one play.
2. **A fixed thread pool with static slices.** `worker_count` threads including the caller's; environment slice w is `[n * w / W, n * (w + 1) / W)`, the caller runs slice 0. No work stealing. The handoff runs under one mutex (Win32 SRW lock and condition variables, POSIX mutex and condition variables), so a worker's writes are visible to the caller. Each worker has its own scratch (a candidate list and the event buffers, about 41 KB).
3. **Seeds per environment and episode, never per worker** (resolves the open point of decision 0001). With `mix` one splitmix64 step (state + 0x9E3779B97F4A7C15, then the two multiply-xorshift rounds) and `key = seed ^ mix((env << 32) | episode)`: `rng_initstate = mix(key ^ "dfstate1")`, `rng_initseq = mix(key ^ "dfseque1") >> 1` (below 2^63), policy seed `mix(key ^ "dfpolic1")`, the tags read as big-endian ASCII. `duoforge_batch_seeds` exposes the mapping.
4. **Two modes, caller-owned outputs.** The step mode (`duoforge_batch_query`, `duoforge_batch_step`, `duoforge_batch_reset_terminal`) writes requests, observations and candidates into contiguous caller arrays in the layout `[env][player][...]`, steps every non-terminal environment with its bundle and resets finished environments to their next episode. The native mode (`duoforge_batch_play_random`) plays whole episodes with the uniform random policy (candidate `next() % count` of the environment's policy stream, requested players in player order) for benchmarks and baseline data. The batch allocates its environments and scratch at creation; caller-provided battle storage waits for a measured need.

Outcomes are atomic per environment: a failing environment keeps its state, the others go on, and a batch call returns the status of the lowest failing environment. A reset creates the next episode's battle before it releases the old one (one allocation per episode, not per step; a battle's creation costs about 1.4 µs, mostly setup validation).

## 3. Evidence

- `duoforge.batch.equivalence`: 37 environments over the four pairings. The native mode gives the same records (steps, decisions, turns, result, final digest) for 1, 2, 3, 4, 8 and 16 workers as a sequential reference with the single-battle API; the step mode with the same policy ends every environment in the reference's final state with 1 and 4 workers; a reset gives the next episode's fresh battle; a stale bundle fails only its environment, which keeps its state. It passes with GCC, Clang and MSVC (Debug and Release) on Windows and with GCC 13 on Linux.
- ThreadSanitizer: `DUOFORGE_ENABLE_TSAN`, a CI job (Linux, Clang) runs the batch tests under it; locally with Clang 18 and GCC 13 it reports no race.

## 4. Next

A benchmark family BATCH_NATIVE (games and decisions per second at 1, 2, 4, 8 and 16 workers, decision 0008) and the scaling report on an idle machine; then the roadmap's exit report (single/batch equivalence, scheduling independence, no races, bounded memory, reproducible Release benchmark).
