# E3n: normalization-v1 and residual-v1 scalar contract

Implements E3n of the approved [in-engine evaluation spec](2026-10-14-in-engine-evaluation-design.md),
sections 5–9/11, on top of E3a. These are private scalar C17 operators and synthetic oracles.
No graph dimensions, candidate choice, checkpoint conversion, training, model loading,
evaluated expansion or JAX default changes are included. The entire full BC6 value graph,
its masks, original gamma/beta, normalization order and residual topology remain required
when a separately approved export/integration supplies it. Passing these operator tests
is neither a real BC6 fidelity result nor the integrated E2/E3 memory gate.

## Exact arithmetic and scales

`normalization-v1` accepts an int32 vector and int32 gamma/beta vectors of the same
positive channel count. The exporter declares the tensor units, not the kernel. The
private parameter descriptor has this canonical little-endian representation, independent
of C structure layout (the future artifact writer must serialize these fields explicitly):

| Byte offset | Type | Meaning |
|---|---|---|
| 0 | uint64 | positive epsilon in squared input-integer units |
| 8 | uint32 | sqrt fractional shift `r`, 0–31 |
| 12 | uint32 | normalization numerator shift `n`, 0–63 |
| 16, 20 | uint32, uint32 | positive gamma-product multiplier and shift, 0–63 |
| 24, 28 | uint32, uint32 | positive output multiplier and shift, 0–63 |

There are 32 canonical parameter bytes. These are a private arithmetic-version contract,
not public gameplay numbers or permission to hand-edit an artifact. E4 must quantize the
teacher's binary32 epsilon at the declared squared-input scale. If it becomes zero,
export/load must refuse; the kernel also refuses zero. No implicit epsilon replacement.
Gamma, beta and precision are retained; shifts/multipliers are explicit descriptor data,
not selected from the current vector. An unsupported shift refuses rather than narrowing.

In ascending channel order:

1. Sum input integers in checked int64. `mean = RNE(sum/count)` once.
2. Sum exact `(input[i]-mean)^2` with portable two-word uint128 limbs.
   `variance = RNE(sum_squares/count)` once, with no per-channel truncation.
3. Add declared epsilon, then shift the radicand by `2*r`. Compute the nearest
   integer square root by comparing distances to the two adjacent squares.
   This declares `denominator = RNE(sqrt(variance+epsilon)*2^r)`.
4. `normalized[i] = RNE((input[i]-mean)*2^n/denominator)` into checked int64.
   Its units are `2^(n-r)` per normalized unit. Do not collapse this division
   with a later gamma multiplication: the intermediate rounding point is fixed.
5. `affine = RNE(normalized[i]*gamma[i]*gamma_multiplier/2^gamma_shift)` into
   checked int64; add beta in those same declared units, checked.
6. `output = RNE((affine+beta)*output_multiplier/2^output_shift)`, checked int32.
   LayerNorm itself does not clamp; ReLU and any declared int16 activation
   conversion follow at their original graph positions.

Every RNE uses unsigned magnitudes and symmetric nearest/ties-to-even, including
negative means, normalized values and products. No negative signed right shift,
float, platform sqrt, FMA or compiler-specific integer type participates. Portable
64×64→128 limb multiplication, restoring division and checked limb addition/shifting
are the scalar oracle. Exact int128 storage would not be portable to the MSVC oracle.
The public binary32 encoder remains unchanged.

For a positive integer channel count at most UINT32_MAX, the mean sum fits int64;
an int32 deviation is at most `2^32-1`, and the square sum uses fewer than 96 bits.
The rounded variance plus uint64 epsilon needs at most 65 bits; its maximum allowed
shift is 62, so the radicand fits 127 bits. A normalized numerator needs at most 96
bits. Gamma and multiplier products are checked before any conversion, even where
the known int64×int32×uint32 operand limits prove at most 127 bits. The resulting
int64/int32 range is checked explicitly, not inferred from calibration samples.
A graph's cold bound proof must certify these intermediate/result ranges for its
approved tensor descriptor before adoption; runtime checks remain a final guard.

The standalone uint128 square-root oracle also covers full 128-bit radicands. A
rounded result of `2^64` refuses; it never wraps to zero. An exact adjacent-square
tie is impossible for an integer radicand: their difference `2*root+1` is odd.
Vectors check both integer neighbors of that midpoint, exact squares and endpoints.

`residual-v1` first independently requantizes both int32 branches with their
positive multiplier/power-of-two scales into checked int64, then adds them in that
order, then requantizes once to the declared output units. `residual32` checks the
int32 range without clipping. `residual16` alone declares final saturation to
[-32768,32767]; an earlier int64 overflow still refuses even if saturation would
hide it. This preserves distinct rescaling and saturation nodes for E4's oracle.

## Refusals, scratch and publication

The operators use existing statuses; future evaluator diagnostics map them to
`eval_normalization_arguments`, `eval_normalization_scale`,
`eval_normalization_capacity`, or `eval_normalization_range` (and the corresponding
`eval_residual_*`). No new public numeric error/event/cause/feature is allocated.
Pointers/counts/scales are checked before arithmetic. Zero channel count or epsilon,
zero multiplier, oversized shifts and exact scratch aliasing refuse. Capacity one
past the caller's scratch count returns E_CAPACITY. Unrepresentable intermediates
or int32 outputs return E_EXHAUSTED. The input-buffer extents are caller preconditions;
all scratch bytes must be disjoint from inputs and outputs, including partial overlaps.
LayerNorm32/residual32 final outputs may overlap same-type int32 inputs because
publication occurs last. Residual16's int16 output must be disjoint from every
int32 input object, including partial overlaps, to preserve portable effective-type
and strict-aliasing rules; delayed publication alone does not grant cross-type aliasing.

Additional caller scratch is exactly `4*channel_count` bytes, int32-aligned, plus
constant-size scalar/limb locals; no vector-sized stack arrays, heap allocation,
shared mutable state or graph-dependent automatic storage. The cold workspace later
checks `4*count <= SIZE_MAX` and reserves this scratch for each worker. The operators
also check that arithmetic before touching channels, including standalone
`layernorm_moments` without scratch. Conditional Win32 tests use a one-cell input
and a too-large declared count to require no input access and no result publication. Every result is computed into
scratch and published only after all channels pass; even a late channel refusal
leaves the entire output unchanged. Scratch can be modified on refusal.
`layernorm_moments` exposes the same private scalar core for the independent
intermediate mean/variance/denominator oracle; its result also publishes last.
Actual stack-usage measurements, allocation-hook counts and toolchain provenance
belong in the delivery report. No claim is made about expansion's future workspace
or the 16 KiB integrated peak before the evaluated sibling exists.

## Synthetic vectors and gate

`duoforge.eval.normalization` exercises constant inputs, smallest positive epsilon,
negative/tied mean and variance, original gamma/beta positions, int32 endpoints,
>64-bit square sums, nearest roots on both sides of adjacent-square midpoints,
uint128 extremes, scale/epsilon/capacity/null refusal, in-place publication,
late-channel failure and residual16 saturation versus earlier overflow. GNU/Clang
allocation hooks count malloc/calloc/realloc/free during 1,024 warmed iterations
of all five operators (5,120 calls); required count is zero. Windows uses the same
arithmetic tests without unavailable GNU linker wrapping.

`duoforge.eval.normalization_oracle` generates deterministic runtime synthetic
vectors (seed 20261014) using independent Python arbitrary-precision arithmetic
and `math.isqrt`. It compares every final result/status and the intermediate mean,
variance and denominator exactly. No checked-in weight/vector artifact is generated.
It freezes 20,684 vectors: 4,540 roots, 4,072 moments, 4,072 normalizations,
4,000 residual32 and 4,000 residual16 operations. Canonical comparison frames are
one ASCII operation byte plus uint32 LE status; success adds uint64 LE root,
`int64,uint64,uint64,uint64` LE moments, or int32 LE channels. Refusals add no
value bytes. The resulting frame-stream SHA-256 is:

`cdde454f97ad458aae34ab6c5bef3ab7dc08937a40cea52542da8e14a6463f67`

All scalar release toolchains and IPO profiles must produce that exact stream,
with zero differing bits, before optimized/full-graph code replaces an operator.
Existing API/export/layout/test names, battle/reference behavior and JAX stay
unchanged. MSVC release execution remains a hosted CI gate, not something a
MinGW compilation may stand in for. E4 still requires the Owner's explicit Go.
