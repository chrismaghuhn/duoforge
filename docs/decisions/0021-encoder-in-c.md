# 0021 — The observation encoder in C

Status: the owner approved the design (2026-10-03: "ja kannst" to the draft; "können wir nicht heute den C encode nehmen?"; one PR for the whole encoder with a review agent at the end). HauptSession agreed, as coordinator, to the second floating-point exception, with three conditions; the owner keeps his veto. The specification is `docs/superpowers/specs/2026-10-03-encoder-in-c-design.md`. Follows decisions 0013 (Python adapter), 0017 (Learner v2) and 0018 (view extension).

## 1. Context

**Why.** In the many-team smoke run (main bed5005, v2-M, 79 POOL teams, 256 environments, 8 workers), encoding was 0.30 s of the 0.79–0.89 s that collection takes per update, all of it in the Python thread. The view-extension records alone were 3.4 ms per batch step, 47 % of encoding (1.92 ms of `observe_ext` ctypes calls, about 1.5 ms of record encoding).

**What stays.** `python/duoforge/features.py` stays the reference. Its rules are the encoder's rules.

## 2. Decisions

1. **Four public functions** (additive; one minor version at merge, which the HauptSession assigns):
   - `duoforge_encoder_size`;
   - `duoforge_encode`, one player, a pure function of observation, factored domain and view extension;
   - `duoforge_batch_query_encoded`, the fused query and encoding in the batch workers;
   - `duoforge_batch_observe_ext`, owner-approved as morning-list item 10.

   `Batch.query_encoded` and `selfplay.Observation` use the fused query. The live tracker keeps the reference for now.
2. **Byte equality.**
   - For every version (1 to 4) and every view-extension mask, the C encoder gives the bytes of `features.encode_batch` with `as_encoder` and `slots_as_encoder`.
   - It refuses exactly the rows the reference refuses: `E_UNSUPPORTED` for a value the version or mask cannot show, `E_INVALID_ARGUMENT` for malformed input, `E_NULL_ARGUMENT` for a missing pointer or missing records. A refused row is all zero.
   - The checks run in the reference's order.
   - Any difference is a bug on one side, and the two sides change together.
3. **Encoder refusals are not engine refusals.**
   - `Batch.query_encoded` raises the reference's own `ValueError` for a refused row: the binding encodes that row once more with `features.py`.
   - If the reference accepts that row, the binding raises an explicit `RuntimeError` naming the disagreement.
   - An encoder refusal stops self-play and evaluation. It never ends an episode and never becomes a game result. The step's `E_UNSUPPORTED` path stays the engine's alone.
   - The encoder writes its own statuses array; `Batch.statuses` stays the step's.
4. **A second floating-point exception in the source lint.**
   - **Scope:** `cmake/checks/lint_sources.cmake` allows `float` and `double` in exactly two more files, `src/encode/encode.c` and `include/duoforge/duoforge_encode.h`. Every other banned token still applies to them.
   - **Lint self-test:** it pins the exception. Float in those two files is clean; `long` there fails; float in `src/batch/batch.c` or any other file fails.
   - **Battle state:** it never sees a float. The encoder reads views and writes caller buffers.
   - **Batch file:** `batch.c` stays float-free. The fused query runs through an internal hook, `dfi_batch_each`.
5. **Why the floats are deterministic.**
   - **Operations:** only exactly rounded IEEE-754 operations: integer-to-float conversion, division, comparison. No expression multiplies and adds.
   - **Recipe:** each column uses the reference's recipe, as listed in the specification:
     - a binary64 division rounded once to binary32, `(float)((double)x / d)`;
     - or a binary32 division, `(float)x / (float)d`, for stages, move ids, pp, stat points and stats.
   - **No contraction:** `#pragma STDC FP_CONTRACT OFF` (Clang), `#pragma fp_contract(off)` (MSVC), `-ffp-contract=off` for the file under GCC and Clang. No `-ffast-math` anywhere; MSVC keeps `/fp:precise`.
   - **No excess precision:** an `#error` refuses `FLT_EVAL_METHOD != 0` and 32-bit x86 without SSE2 (`_M_IX86_FP < 2`).
   - **Proof:** the byte-equality tests on the whole hosted matrix (MSVC x64 and Win32, GCC, Clang, Linux and Windows, Debug and Release). Any mismatch on any platform blocks the merge.
6. **One PR for the whole encoder**, with a review agent at the end (owner).
   - Measured afterwards on its own: steps per second, and an evaluation against the Python encoder on the same seeds.
   - bf16 opponents and fewer league opponents per step come later, each in its own PR with its own measurement (owner, 2026-10-03 11:51).

## 3. Consequences

- **Speed:** collection loses most of its Python encoding time. Indicative, not quiet: per batch step, 4.9–5.7 ms of Python encoding against 0.85–0.90 ms for the whole fused C query, of which `query_factored` alone is 0.57–0.60 ms. The measured A/B belongs in the PR body.
- **Reference fix:** the fuzz found that `features.encode_batch` raised `IndexError` for a viewer other than 0 or 1. It now raises `ValueError`, like every other malformed observation.
- **Encoder 4:** it comes with tail revision 4 (the HauptSession's `chris/encoder-4`). This work merges that branch, so its version 4 is the reference's. Whoever lands second re-syncs.
