# E3g: compiled integer value graphs

Implements the three shapes frozen by Owner/HS in
[#569](https://github.com/chrismaghuhn/duoforge/pull/569),
[experiment declaration](../../benchmarks/2026-10-15-evaluation-graphs/README.md).
Only synthetic runtime parameters are used for this implementation gate.
E4 conversion/calibration/training and E5 integration/adoption remain separate.

## Registry, inventory and storage

`tools/eval/graphs.json` fixes the three approved declarations. Its generator
`tools/eval/graph_registry.py` emits `src/eval/graph_registry.inc` and has `--check`.
Each declaration and field is positively classified; unknown/missing graphs,
changed dimensions, identities or resource limits refuse by name. Independent
tests freeze the source shapes and counts without importing that generator.

Private artifact graph identities are 1001=full, 1002=small, 1003=medium.
DFEVAL format/arithmetic remain 1; these are not public gameplay identifiers.
All descriptors pin encoder 6, mask bits 0..46, width 1094, the SHA-256 of the
compact JSON feature-name list, and E3a's compact feature-name/group/coordinate
mapping SHA-256. No serialized graph, instruction stream or arbitrary shape is
executed. Public loading selects only these compiled descriptors after hashing
the opened file; missing/unknown identities remain `eval_graph_unregistered`.

Wire inventories contain 28/24/28 entries for full/small/medium, respectively:

1. `input.unit`: one I16 scalar, no scale records.
2. `species`, `move`, `item`, `ability`, `nature`: I8 embedding matrices, each
   with one multiplier/shift record, using the frozen capacities and widths.
3. `move_token`, `member1`, `member2`, `position`: I8 `.w` matrices in
   `[output,input]` order with one scale per output; I64 `.b` vectors.
4. For each torso layer i, in order: `torso.i.w`, `torso.i.b`, `norm.i.g`,
   `norm.i.b`. Gamma/beta are I32; dense weights/biases follow the preceding rule.
5. `value.w` and `value.b`, with one output and the same dense storage rules.

All source learned elements are accounted for: 1,802,441 / 333,769 / 773,193.
The extra input-unit scalar is not a learned parameter. Scale records are
additional format data. Reordered, missing, duplicated or extra records refuse;
none can reduce graph coverage. No policy/team head or policy-only Struggle
array is present. E4 must separately prove complete original teacher provenance.

The E2 opened-file hash, schema, exact directory/extents, metadata, context and
second-snapshot checks remain. Registered files additionally respect their
1/2/4 MiB per-graph cap before a parameter slab is allocated. Cold binding
decodes all signed values and scales explicitly from little-endian bytes into
aligned native typed storage; it never casts unaligned wire bytes to typed
arrays. An additional cold allocation owns these bindings. A workspace retains
them through the existing model lifetime. Every cold allocation can fail without
publishing a model; all constructed storage is released on refusal.

## Exact quantized graph

`input.unit=U` is a common activation unit, an exact power of two from 256 through
16384. This is a declared graph-arithmetic capability, not a trained default.
The canonical input quantizer has multiplier U, shift 0. Categorical IDs are
recovered first, unchanged; side/registration/occupied flags use U or zero.
Each embedding/dense scale converts its parameter units to this common activation
unit. Concatenations and gathers copy common-unit values without an extra hidden
rounding. Pools reduce in source order; their declared output conversion is
identity followed by the explicit I16 activation saturation. The actual scale
and parameter provenance remain E4's separately approved private manifest.

Move/member/position stages use E3a I16 activations and checked I64 dense sums.
ReLU is at the source dense nodes, followed by their declared I16 conversion.
Registration masking occurs after member2. Absent occupants zero their gathered
member vector; their position scalar/bias computation is still performed, as
in the source. The first torso layer replaces its input; later layers add the
previous torso only after dense, learned LayerNorm and ReLU. Every torso state
and residual is I32, including input to later dense layers and the value head.
The new private int32-input dense operator never narrows to I16.

For every torso normalization, gamma/beta are in common units U. Derive epsilon
from the teacher's exact binary32 `1e-5` bits `0x3727c5ac` with integer
nearest/ties-to-even conversion at squared scale U²; require a positive result.
Use normalization-v1 with `sqrt_shift=31`, `numerator_shift=47`, gamma scale
`{1,16}` and output scale `{1,0}`. Thus normalized values retain 16 fractional
bits before gamma conversion; gamma/beta and epsilon are never omitted.
Residual32 adds the two common-unit branches with identity scales, range checked.
The final linear dense returns I32 Q12.20 with its explicit output scale and
no clamp to [-1,1]. Numeric range failure invalidates the evaluation and refuses.

## Cold bounds and publication

Each dense matrix's compiled fan-in/input bound and actual maximum weight
magnitude prove its absolute I64 accumulation and multiplier product before
model publication. Input bounds cover full I32 magnitudes for later torso/head
layers; no I16-only proof is reused there. Bias magnitude is at most 2^40.
The int32-input scalar also independently checks the bound before computing.
Its limb-product predicate avoids both overflow and variable division.

Gamma magnitude is at most 2^20; beta magnitude at most 2^24. The approved hidden
widths are <=640, hence <=1024. For deviation d and rounded variance v,
`d² <= H*(v+1) <= H*(v+epsilon)` since epsilon>=1. Denominator rounding at
31 fractional bits changes that ratio by less than `1/(1-2^-32)`. With 16
normalized fractional bits, normalized magnitude is at most `32*65536+1`.
Gamma requantization and beta therefore bound the normalization result by
`33554448 + 16777216 = 50331664`, safely I32. At most three nonnegative ReLU
outputs are added, also safely I32. E3n still checks every intermediate/result;
dense I32 outputs retain runtime range refusal, never implicit clipping.

`dfi_eval_graph_row` is private. Its caller holds E2 workspace ownership and
supplies one complete worker region and row slot 0..15. Raw input bits/output
are disjoint from writable activations/canonical inputs; raw bits may occupy
the reserved row temporary. It checks identity and capacity before writes.
Only a completely successful evaluation publishes its value; input, range or
even late trace refusal leaves that output unchanged. Scratch may change on
refusal. Optional private trace callbacks are for synthetic oracles and do not
form a public API. Their failure is propagated rather than silently losing
intermediate coverage.

## Resource layout and full recomputation

The existing worker cap is reserved cold: small 256 KiB, medium 384 KiB, full
512 KiB, at most 32 workers and 65,536 logical leaves. No per-leaf private slab
is reserved. Cold binding bytes plus the file snapshot and model/lifetime
records fit `2*file_max + 64 KiB`; tests check the actual sum.

Inside each worker region, align the base and each buffer to 128 bytes, charging
up to 127 initial bytes within that region. Two 4,376-byte row temporaries are
reserved; common input-scale records are derived once in the immutable cold
bindings, so neither reserved row is overwritten by the graph. E5 can stage the
existing encoder row/copy/conversion in this bounded storage by lifetime,
not add a whole count×1094 slab. Sixteen 2,688-byte canonical-input slots and
the experiment declaration's activation matrices follow. A static assertion
checks canonical inputs fit their slot. Rows use natural scalar alignment;
the whole buffers have 128-byte boundaries. The final offset query includes
worst initial alignment and is tested against each frozen worker cap.

Every call reconstructs canonical inputs and all move/member/position/pool/torso
stages from the supplied row. No activation, source row, mean world, previous
leaf or incremental accumulator is reused. Partial-tile scheduling is E3b;
this step only supplies independently addressable scalar slots. No public
evaluated-expansion call or Python backend switch is added.

Synthetic gates compare exact canonical bytes for every independently inventoried
stage, across multiple scratch slots, poisoned A/B/C/A calls, two U choices,
empty/partial masks, ID zero/boundaries and absent occupants. Explicit >I16
torso values catch accidental narrowing; linear values outside [-1,1] catch
hidden output clamping. Unit/capacity/schema/tensor/bound refusals, late output
publication, all four cold allocation sites and zero warm allocations are
tested. Original arithmetic/input/normalization/lifecycle tests remain intact.
The compiler/IPO/sanitizer, inventory, export and actual resource reports belong
to the implementation delivery evidence. No throughput, trained fidelity or
strength result follows from passing these synthetic gates.
