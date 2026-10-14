# E3a scalar kernels and canonical encoder-6 inputs

This is the private arithmetic contract for E3a of the approved
[in-engine evaluation design](2026-10-14-in-engine-evaluation-design.md).
It selects no graph, network size, real parameters, trained artifact or backend.
E3n supplies normalization and residual nodes; E3g connects the reviewed graphs.
JAX, the tree and all existing expansion entry points remain unchanged.

`dfi_eval_scale` has a positive uint32 multiplier and uint32 shift in 0..63.
Requantization multiplies the magnitude, then divides by `2^shift`, rounding
nearest with ties to an even quotient. The sign is restored only after bounds
are checked. INT64_MIN has magnitude `2^63`; its negation is never evaluated.
There is no right shift of a negative value. A multiplier product beyond uint64
or an int64 result beyond its range is `E_EXHAUSTED`. Models prove the stricter
bound below before use. `requant16` explicitly saturates only a valid rounded
int64 result to [-32768,32767]; saturation is a graph operation, never overflow.

`requant32` uses the same rounding and checked multiplication, with an explicit
int32 range refusal instead of saturation. `dense32` shares validation and
ascending accumulation with `dense`, preserving BC6 pre-normalization int32
tensors and an unclamped Q12.20 value head. Values above 32767 and outside [-1,1]
remain valid within int32; results beyond int32 refuse as `E_EXHAUSTED`.

Dense weights are row-major int8, inputs int16 and biases int64. A channel
accumulates its bias and products in ascending input index. For fan-in N,
actual maximum input magnitude A, actual maximum weight magnitude W and bias B,
prove `abs(B) + N*A*W <= INT64_MAX` and this bound times the positive multiplier
`<= INT64_MAX`, using division before multiplication. A is at most 32768 and W
at most 128. The model loader uses approved bounds, not a lucky cancelling
sample. The kernel repeats this conservative proof using the actual input.
Optional ReLU acts on the accumulator before its requantization; normalization
and the full BC6 dense -> LayerNorm -> ReLU order are separate future nodes.

Embedding id zero is valid; an id at or beyond the table capacity refuses.
Registered pooling masks contain only bytes 0 and 1. Sum and maximum reduce in
ascending roster/move order; sums are wide and only then requantized. Empty and
all-masked pools produce zeros, including all-negative maximum inputs. A pool
sum bound is `N*32768 <= INT64_MAX`, with its multiplier product checked at
requantization. An absent occupant gathers a zero vector without dereferencing
its index. Concatenation has explicit branch scales to the common destination
scale and refuses insufficient capacity before writing. Caller buffers must
be disjoint and have their declared extents. Any refusal invalidates the whole
output; partial results must never be consumed. Each typed input/output extent
is checked against SIZE_MAX by division before any loop, including bias/scale
vectors, dense32 outputs, empty-pool outputs and concatenation capacity. An
unaddressable byte extent returns `E_CAPACITY` before reading or writing cells.
The same pure predicate is tested with a smaller byte limit on every platform;
32-bit builds additionally execute one-cell-backed impossible-size preflights.

Canonical inputs begin with the existing encoder-6 row. The private inline
bridge in `encode_internal.h` copies its binary32 representation with `memcpy`,
without another feature recipe or any floating computation. The value code
consumes only bits, categorical ids and integer activations. It decodes
categorical ids *before* scalar quantization with the exact binary32 value,
the existing table factor (65535, 255 or 24), and nearest ties-even. The result
agrees with `columns.decode`/`check_ids`; capacities are checked for every id,
including unregistered members. Nonfinite or negative ids refuse; none is
clipped or remapped. Continuous finite features multiply the exact significand
by their scale and round once; large magnitudes saturate only to the declared
int16 range. Nonfinite scalar cells refuse even if a later pool masks them.

`tools/eval/input_layout.py` derives the private map from the existing teacher's
`features.FEATURE_NAMES` and `columns.columns`, with `--check` for stale output.
All 1,094 columns are classified exactly once: global 36, side 58, position 420,
member scalars 384, occupant 28, member present/move-count 24, categorical ids 96
and PP 48. Coordinates and group order are those of the teacher. Exact name/order
validation rejects missing, extra, unknown, duplicate or malformed columns by
name. Registration is move-count > 0, not species id > 0. Present masks must
agree with registration; move counts are exact quarters, and occupant masks
are exact one-hot vectors including the absent entry 6. Categorical and metadata
slots are zero in the quantized scalar array, with their separate typed outputs.

All buffers are caller-owned. No kernel allocates, frees, performs I/O, resizes
or calls a platform floating function. One prepared row occupies 2,600 bytes;
its source bits occupy 4,376 bytes and cold per-column scales 8,752 bytes.
The existing binary32 row is reused, not cloned per leaf. A future workspace
accounts for these explicitly; it supplies activations and tile storage too.
GCC14 Release without IPO reports at most 176 bytes for any kernel frame;
including the arithmetic callee the largest kernel-only chain is 216 bytes,
below the additional 16 KiB limit. This excludes caller-owned buffers and
platform library frames; it is not a measurement of future graph peak memory.
GNU allocation hooks test that the warm synthetic kernel/input calls allocate
and free zero times. The source lint separately forbids allocation calls.
Only the three named evaluation modules gain fixed-width signed-type permission;
the float/double and all other banned-token rules remain enforced and have
negative self-test controls.

Public CI uses synthetic parameters and independent Python arbitrary-precision
and IEEE bit oracles. No trained weight file, checkpoint, row dataset or private
log is part of the change. Scalar arithmetic, groups, masks, saturation, bounds,
malformed inputs and byte framing are covered independently. Actual full graph,
MSVC/Clang execution, worker/tile parity, real-network fidelity and adoption gates
remain their planned steps; a synthetic operator pass does not satisfy them.
