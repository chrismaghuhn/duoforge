# 0001 — Gameplay RNG: PCG32 contract

Status: **proposed**. The decision is implemented and tested in M1. It becomes binding when the owner accepts the reviewed M1 change.

## Choice

The gameplay RNG is **PCG32 XSH-RR 64/32**, computed exactly as in `imneme/pcg-c-basic@bc39cd76ac3d541e618606bcc6e1e5ba5e5e6aa3` (`pcg32_srandom_r`, `pcg32_random_r`, `pcg32_boundedrand_r`). Each battle owns its own instance; there is no global generator. Provenance is recorded in `third_party/pcg-c-basic/PROVENANCE.md`.

Internal API (`src/rng/pcg32.h`). There is no public RNG API.

| Aspect | Contract |
|---|---|
| State | `state` (u64), `inc` (u64, always odd), `draws` (u64 counter of raw words consumed). |
| Seeding | `state = 0; inc = (initseq << 1) \| 1; step; state += initstate; step; draws = 0`. The two seeding steps are **not** counted. |
| Seed domain | Internally the full u64 domain is accepted. Bit 63 of `initseq` is discarded by the shift, so `initseq` and `initseq ^ 2^63` alias. Public setup therefore **rejects `initseq >= 2^63`** with `E_INVALID_ARGUMENT`, which makes `(initstate, initseq) -> (state, inc)` injective. |
| Raw draw | If `draws == UINT64_MAX`, returns `E_EXHAUSTED` and mutates nothing. Otherwise `old = state; state = old * 6364136223846793005 + inc; draws += 1; out = XSH-RR(old)`. |
| Bounded draw | `bound == 0` returns **`E_INVARIANT`** and mutates nothing. The RNG is internal, so a zero bound can only come from engine code; upstream would divide by zero here. Otherwise `threshold = (2^32 - bound) % bound` (the same value as upstream `-bound % bound`). Raw words are drawn until one is `>= threshold`, and the result is `word % bound`. |
| Accounting | Every raw word counts, including rejected ones. Bound 1 consumes exactly one draw and yields 0 (reference parity). |
| Atomicity | A bounded draw runs on a working copy and commits only on success. If exhaustion strikes between a rejected and an accepted word, the generator and the output are untouched. |
| Termination | There is no iteration cap. Every attempt consumes a counted draw, so the u64 counter bounds the loop; the expected number of attempts is below 2. |
| Serialization | Only inside the canonical state encoding (decision 0002): `state`, `inc` and `draws` as u64 LE, with `inc` required to be odd. `draws` is audit accounting and is not cross-checked against `state`. |
| Changes | Any change to seeding, output, the bounded method, accounting or exhaustion requires a new semantics id (decision 0002). |

No Showdown seed or trace parity is claimed. There is no test tape and no draw-site wrapper; those belong to M3.

## Alternatives considered

- **xoshiro256\*\* / SplitMix64.** Rejected: the architecture pack already proposed PCG32, it has a small pinned reference with published outputs, and it has explicit stream selection.
- **The Showdown PRNG.** Rejected: DETERMINISM_AND_REPLAY §3 rules out implicit seed parity, and a compatibility layer would be a separate, validated deliverable.
- **Bound 1 without a draw.** Deferred. Reference parity is kept for now; M3 decides per draw site whether a single-option event draws at all.
- **Lemire's multiply-shift method.** Rejected: it would diverge from the pinned reference's draw consumption.
- **An iteration cap.** Rejected: a cap would silently change semantics. The draw counter already bounds the loop.

## Consequences (proposed contracts, binding on acceptance)

- **M3 draw sites** forward `E_EXHAUSTED` as a capacity failure and `E_INVARIANT` as an internal failure. They never translate an RNG status into a caller-input error.
- **M3 decides per call site** whether a bound-1 event draws.
- **The M6 batch seed mapping** must emit `initseq < 2^63`.

## Evidence

| Test | What it proves |
|---|---|
| `duoforge.rng.kat` (T4) | Against KAT vectors generated from the pinned reference: 6 seeds; state after seeding; 16 raw words; 9 bounds × 12 draws with per-call draw counts, including rejections; a 52..2 shuffle sequence. |
| `duoforge.rng.contract` (T5) | Zero bound, bound 1, raw exhaustion, mid-rejection atomicity (with a positive control), seed aliasing and injectivity samples, instance independence. |
| `duoforge.rng.kat_regen` (T20, optional) | Byte-identical KAT regeneration from the pinned reference. |
| `duoforge.rng.reference_differential` (T21, optional) | 1,024,000 mixed operations in lockstep with the reference. |
| `duoforge.provenance.pcg_license` (T17) | The vendored `LICENSE.txt` is byte-exact. |

Negative controls were run locally on 2026-09-30:

- forcing the threshold to 0 fails T4 and T5;
- not counting rejected words fails T4 and T5.
