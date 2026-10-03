# Encoder in C: design draft

Date: 2026-10-03. Status: a draft for the owner's review, which goes through the HauptSession first. Building starts after the first many-team run (night 2026-10-03/04).

Builds on:
- the Python encoder `python/duoforge/features.py`, which is the reference: encoders 1 to 3 today, and encoder 4 (rev 4, cut B) on `chris/encoder-4`;
- decision 0018, the view extension, with `duoforge_battle_observe_ext`;
- the batch runtime of decisions 0012 and 0013;
- Learner v2 (decision 0017).

## 1. Goal

Encoding is the second-largest part of collection, after the policy. Moving it from the Python thread into the batch workers removes it from the critical path.

**Baseline**, from the many-team smoke run (main bed5005, v2-M, 79 teams, POOL, 256 envs, 8 workers; indicative, the machine was not quiet):
- `t_encode` is 0.30 s of the 0.79–0.89 s collection per update.
- In a separate measurement, `Observation` takes 7.29 ms per batch step with the full mask and 3.89 ms with base bits only.
- So the ext records cost 3.4 ms per step, 47 % of encoding:
  - `Batch.observe_ext` (512 ctypes calls): 1.92 ms;
  - encoding the records: about 1.5 ms.

**Success:** encoder output byte-equal to `features.py` for every version and mask, plus a measured drop of `t_encode` and a measured rise in decisions per second (section 8). A number goes into the report only when it was measured.

## 2. Decisions

- **The owner approved (morning list item 10):** the public function `duoforge_batch_observe_ext`.
- **The design follows from the rules in AGENTS.md:**
  - `features.py` stays the reference and keeps every rule. The C encoder implements the same rules and is held to byte equality. It is never "the more correct one": any difference is a C bug, or a reference change that both sides take together.
  - There is no hidden rule in Python or the bindings beyond calling the C encoder or the reference.
  - There is no silent fallback: a library without the encoder, or an encoder version it does not know, is an explicit error, never a quiet switch to Python.
  - The hot path does not allocate: the encoder writes into caller buffers and keeps its scratch on the stack.
- **Needs an OK: a second floating-point exception in the source lint.**
  - `cmake/checks/lint_sources.cmake` bans `float` and `double` in `src/` and `include/`. Its one exception is `src/state/tiebreak.c`, the reference's tiebreak arithmetic.
  - The encoder's outputs are float32 by contract, so the encoder needs a second exception:
    - its file `src/encode/encode.c`, which computes;
    - the header `include/duoforge/duoforge_encode.h`, whose signatures take `float *`.
  - The same rule as for tiebreak: only these two files, every other banned token still applies, and the battle state never sees a float. The encoder reads views and writes caller buffers.
  - **Why it stays deterministic:**
    - Only IEEE-754 binary32 and binary64 operations that are exactly rounded: division, conversion, and `fminf`.
    - No multiply-add pattern, so FMA contraction cannot change a result.
    - No fast-math, and SSE2 on every target (MSVC Win32 included).
    - The equality tests run on every compiler and build type of the hosted matrix.
  - Rejected: hiding `float` behind `void *` or a typedef, which would only dodge the lint.

## 3. C API (additive, one minor version at merge, assigned by the HauptSession)

```c
/* Encoder versions (features.ENCODERS): 1, 2 (BASE 607 columns), 3 (842, decision 0018), 4 (850, rev 4 cut B).
   The event-history encoder becomes 5. */
#define DUOFORGE_ENCODER_MAX 4u
#define DUOFORGE_ENCODER_SLOT_FEATURES 12u

/* obs_part width of an encoder version: E_INVALID_ARGUMENT for an unknown version. */
duoforge_status duoforge_encoder_size(uint32_t version, uint32_t *out_obs_size);

/* One player: a pure function of its observation, factored domain and view extension (ext may be NULL when
   ext_supported has no record bit). Writes obs (obs_size floats), slots (2*32*12 floats) and pair_mask (32*32
   bytes, 0 or 1). ext_supported: the network's mask (a checkpoint property); nonzero only for version >= 3. */
duoforge_status duoforge_encode(uint32_t version, uint64_t ext_supported, const duoforge_observation *observation,
                                const duoforge_factored_domain *domain, const duoforge_observation_ext *ext,
                                float *obs, float *slots, uint8_t *pair_mask);

/* In parallel: out[2 * env + p] = duoforge_battle_observe_ext of player p (item 10). */
duoforge_status duoforge_batch_observe_ext(duoforge_batch *batch, duoforge_observation_ext *out);

/* The RL loop's query in one pass, in the batch workers: per environment, query_factored (requests, observations
   and domains as duoforge_batch_query_factored), then, when ext_supported has a record bit, observe_ext into a
   stack record, then duoforge_encode into row 2 * env + p of obs, slots and pair_mask. Any of requests,
   observations, domains may be NULL (skipped); obs, slots and pair_mask may not. statuses[env] gets the
   environment's outcome; the call returns the status of the lowest failing environment. */
duoforge_status duoforge_batch_query_encoded(duoforge_batch *batch, uint32_t version, uint64_t ext_supported,
                                             duoforge_request *requests, duoforge_observation *observations,
                                             duoforge_factored_domain *domains, float *obs, float *slots,
                                             uint8_t *pair_mask, duoforge_status *statuses);
```

Notes:
- **Where it lives:** the encoder API goes into its own header, `include/duoforge/duoforge_encode.h`, and is implemented in `src/encode/encode.c`. That includes `duoforge_batch_query_encoded`, so that `float` stays in the two exempt files (section 2).
  - `batch.c` gets one internal, float-free hook, `dfi_batch_each(batch, fn, arg, statuses)`. It runs `fn(arg, env, battle)` over the worker slices, as every batch call does.
  - `encode.c` passes its float buffers through `arg`.
  - `duoforge_batch_observe_ext` has no float and goes into `duoforge_batch.h` and `batch.c`.
- **Why `duoforge_encode` per player:**
  - The single-player function makes the encoder testable without a battle.
  - The live tracker can use it later (its observations are not a batch's).
  - Byte-equality tests can feed it recorded and fuzzed rows.
- **Why a fused query:**
  - It encodes in the same worker pass that queries, so neither the observations nor the records cross into Python first.
  - The Python thread only waits for the pass.
  - `duoforge_batch_observe_ext` stays a separate, cheap batch call for callers that want the records themselves (evaluation, debugging).
- **Versions 1 and 2:**
  - They are the first 607 columns. Version 1 takes `present` from `species_id != 0`, as `as_encoder` does today.
  - They refuse what they cannot show (the new base values, a Recharge slot), as `as_encoder` and `slots_as_encoder` do.
  - The per-version wrappers then disappear from the hot path. They stay in `features.py` as the reference.
- **The mask:**
  - Versions 1 and 2 with a nonzero mask: `E_INVALID_ARGUMENT`.
  - A mask bit that the encoder version does not have (for example bit 40 under version 3): `E_INVALID_ARGUMENT`.
  - A record bit with `ext == NULL`: `E_NULL_ARGUMENT`.
- **Encoder 4:** I write the C encoder against the HauptSession's encoder 4 (`chris/encoder-4`):
  - 8 columns appended to encoder 3 at each position, `volatile.roost` and `move_failed`;
  - feature bits 40 and 41;
  - `DUOFORGE_VIEWEXT_FEATURE_COUNT` 42.
  Encoder 3 stays the first 842 columns.

## 4. Refusals: one status per reason class, the message from the reference

Every `ValueError` of `features.py` has a C status. There is no silent zero.

| Reference (ValueError) | C status |
|---|---|
| A value the version cannot show: Sand, Snow, Electric, Misty or Tox without its mask bit, Recharge under 1 or 2, a mask bit the records' library does not support | `E_UNSUPPORTED` |
| Malformed input: an unknown boundary, weather, terrain, location or ailment, a position flag bit or volatile bit outside the known sets, a field above its documented range, type_now without TYPE_CHANGED, records of another epoch, player or revision, a nonzero revision-0 record, a domain of another boundary | `E_INVALID_ARGUMENT` |

- **Statuses:** a refused row leaves its outputs zeroed, and the batch call reports the environment in `statuses`.
- **Encoder refusals are not engine refusals** (HauptSession review):
  - An `E_UNSUPPORTED` from `query_encoded` means the encoder cannot show the row. It is never the engine's step refusal, which `SelfPlay.step` ends as an unresolved episode.
  - In self-play and evaluation an encoder refusal stays fatal: `ValueError` from the reference, the run stops, and no episode ends and no game result is written.
  - `query_encoded` writes its own statuses array (`Batch.encode_statuses`). `Batch.statuses` stays the step's, so neither reads the other's leftovers.
  - Test: a refused encode stops the run with `ValueError`; `engine_unsupported`, `episodes` and the league counters are unchanged.
- **Python errors:** the Python side raises `ValueError` with the reference's own message. On a refusal it encodes the refused row once with `features.encode`, which must raise. If it does not raise, the binding raises an explicit error naming the disagreement. There is no message table in C.
- **Tests:** a C refusal where the reference accepts, or the reverse, fails a test. It is never papered over.

## 5. Where it runs and what it costs in memory

- **Workers:**
  - The encoder runs in the batch workers on their fixed contiguous slices; the caller's thread takes the first slice, as every batch call does.
  - Each player row is independent, so the output is identical for any worker count (decision 0012).
- **Memory:**
  - No heap allocation on the path. Per player there is one stack `duoforge_observation_ext` (192 bytes) and constant tables; the outputs go into the caller's buffers.
  - Per call: obs 2 × 256 × 850 × 4 B = 1.74 MB, slots 2 × 256 × 768 × 4 B = 1.57 MB, pair_mask 2 × 256 × 1024 B = 0.52 MB. Python keeps these arrays across steps (`Batch` owns them, like `observations`).
- **Python:**
  - `Batch.query_encoded(version, ext_supported)` fills `self.obs`, `self.slots` and `self.pair_mask` (bool view of the uint8 array).
  - `selfplay.Observation` takes them. `SelfPlay` and `evaluate` call it in place of `query_factored` and `features.encode_batch`.

## 6. Byte equality with the reference

**Arithmetic contract**
- Each column's float32 value is produced exactly as `features.py` produces it. The reference uses two recipes, column by column, and C copies each:
  - **a double division rounded once to float32**, `(float)((double)x / d)`. This covers:
    - the global ratios (turn with its clip at 1, weather, terrain and trick room turns);
    - the side head;
    - the position flags, including protect_chain / 3 clipped;
    - hp / hp_max (0 when hp_max is 0);
    - is_mega through species / 65535;
    - move_count / 4;
    - move_slot / 4 and reserve / 5;
    - every block column (for example aurora / 8, gravity / 5, ability_now / 255, forme / 65535, type_now / 18);
  - **a float32 division**, `(float)x / (float)d`. This covers:
    - stages / 12;
    - move ids / 65535;
    - pp / pp_max (0 when pp_max is 0);
    - stat points / 32;
    - stats / 1000, then `fminf(·, 1.0f)`.
- The design lists each column group's recipe next to the reference line it copies.
- The C file mirrors the reference's structure (global, sides, positions, members, the block), so a reviewer can read the two side by side.
- **Refusal order:** C checks in the reference's order (the domain against the observation, the mask, the records, the global one-hots, the sides, the block, the slots). So a row with two faults gets the same reason class on both sides.
- The design lists each column group's recipe next to the reference line it copies.
- The C file mirrors the reference's structure (global, sides, positions, members, the block), so a reviewer can read the two side by side.

**Equality tests**
1. **Random play** over every POOL team pairing of the registry, and over CLOSURE and TEAM_C:
   - for versions 1–4;
   - for masks 0, BASE_VALUE_FEATURES, the library mask, and 32 random subsets;
   - checked with `np.array_equal` on the obs, slot and pair_mask bytes, C against `features.encode_batch` plus `as_encoder` / `slots_as_encoder`.
2. **Recorded rows:** the replay rows of M11 (tracker observations) through `duoforge_encode` against `features.encode`. This runs without data in the repository: the test builds rows from the committed reference battles.
3. **Fuzzed rows:** observations, domains and records with random field values inside and just outside every known set and range. The accept/refuse decision must agree; refused rows must give the same reason class (section 4).
4. **Worker counts:** 1, 2 and 8 give byte-identical buffers. The fused query gives the same output as query_factored, then observe_ext, then encode.

**When the reference changes:** a later reference change (encoder 5, new values) changes both sides in one PR. The random-play test is what keeps them together.

## 7. Determinism

- The encoder is a pure function of its inputs. It reads no battle state beyond what the query returns, and it uses no RNG and no thread-dependent order.
- The fused query does not change any battle: no step, no seed.
- Same inputs give the same bytes for any worker count, build type or compiler. Tests cover all three:
  - the hosted matrix runs the equality tests on MSVC, GCC and Clang;
  - Debug and Release are both in the matrix.

## 8. Measurement plan

**Microbenchmark.** Per batch step, 256 environments, POOL, all teams of the pinned registry, the full library mask:
- `Observation` today (7.29 ms, of which `observe_ext` is 1.92 ms);
- `query_encoded` at 1 and 8 workers;
- `query_factored` alone, as the floor.

**Training A/B.** Interleaved, 3 repetitions per arm, 10 minutes each, a quiet window, same seed and options as the many-team run. The arms are Python encoder and C encoder. Reported:
- `t_encode` (the C arm makes it part of `t_engine`, so both columns are reported), collection, and update;
- decisions/s;
- matches/h.

**The expectation is not the claim.** Most of the 0.30 s per update should leave the Python thread. Collection is then policy-bound (0.34 s); bf16 opponents are the next lever.

## 9. Order of work (one PR)

1. `duoforge_batch_observe_ext`, with tests. It is useful on its own and replaces the ctypes loop in `Batch.observe_ext`.
2. `duoforge_encode` for versions 1–3, with the arithmetic contract and equality tests 1–3.
3. Version 4 (after `chris/encoder-4` is on main), with its tests.
4. `duoforge_batch_query_encoded` and the Python wiring (`Batch.query_encoded`, `Observation`, `selfplay`, `evaluate`), with equality test 4. The existing learner tests run on the C path.
5. The measurements of section 8, in the PR body.

**Review:** the review agent at the end (the C encoder is code-heavy), and the HauptSession as second reader for decision 0018's block.

## 10. Not in this work

- bf16 opponents and fewer league slots per step: the next throughput item.
- Double-buffering of collection and update: only if the measurement after this work shows it pays (the CPU-actor variant did not, decision 0017 report).
- The live tracker's switch to `duoforge_encode`: possible afterwards, with its own test.
