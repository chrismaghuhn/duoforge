# Value-graph proposal before synthetic E3g results

Status: **proposed for Owner/HS review**. HS authorized the full BC6-M value path
with synthetic parameters immediately; the small and medium declarations below
require approval before implementation or registration. This document starts no
training, checkpoint conversion, calibration, timing comparison or live adoption.
E4 remains off. Training budgets, seeds and private data identities belong to the
separately approved private E4 manifests, not this public proposal.

Source inspection: main `ac555c167dce3e7bea91aed117eff5d869687eb8`, clean
`dirty=false`, Linux x86-64 machine `8c91664c82d0`. Dimensions come from
`python/duoforge_learn/model_v2.py`, `columns.py` and encoder-6 column groups.
Parameter counts and memory expressions below are arithmetic over those declared
shapes, **not measured inference resources or trained-model results**. No private
checkpoint was read. Full means the source BC6-M value topology; E4 must still
verify actual teacher configuration/weights against checkpoint `bda5de8e…` and
record its complete SHA-256 privately.

## Three concrete value-only graphs

All candidates consume each world's encoder-6 row independently, using identical
categorical/registration/occupant semantics. They have the same value topology
with different widths/depth. Neither policy/team heads nor the policy-only
Struggle embedding are included. The full graph preserves all original value
operators, including learned gamma/beta and epsilon; small/medium are proposed
students, not approved substitutes for the teacher.

| Declaration | Small: public S value shape | Medium: proposed intermediate | Full: public M value shape |
| --- | ---: | ---: | ---: |
| Embedding width E | 32 | 48 | 64 |
| Member width M | 64 | 96 | 128 |
| Position width P | 64 | 96 | 128 |
| Torso width H | 256 | 368 | 640 |
| Torso layer count L | 2 | 3 | 3 |
| Nature embedding width | 8 | 8 | 8 |
| Member input width: 5E+42 | 202 | 282 | 362 |
| Position input width: 106+M | 170 | 202 | 234 |
| Torso input width: 94+4P+4M | 606 | 862 | 1118 |
| Source value tensors | 23 | 27 | 27 |
| Learned value parameters | **333,769** | **773,193** | **1,802,441** |

All capacities match the public teacher configuration: species 1024, move 1024,
item 256, ability 256, nature 25. An out-of-capacity ID refuses; no clipping or
substitution. Registration is move_count>0, including valid species ID zero.
Missing members and occupants use the existing masks. Empty pools produce zero.

Medium's 773,193 parameters are **0.314% below** the geometric target
`sqrt(333769 * 1802441) = 775628.0875…`, strictly between small and full. Hidden
width 368 and the other proposed medium widths are multiples of 16. This is a
predeclared shape choice, not evidence of speed or strength. It changes both
representation size and value-parameter count, not merely scheduling.

## Exact topology and source tensor inventory

For each of two sides, six roster members and up to four moves per member:

1. Embed species, item and ability into E channels; nature into eight channels.
   A move's E-channel embedding plus its PP scalar goes through
   `move_token: (E+1)→E`, then ReLU. Sum and max move pools use the move-count
   mask in move order.
2. Concatenate species embedding, move sum, move max, item embedding, ability
   embedding, nature embedding, 32 member scalars, side flag and registration.
   `member1: (5E+42)→M`, ReLU, `member2: M→M`, ReLU, then registration mask.
3. Each of four positions gathers its occupant's masked member vector, or zero
   if absent. Concatenate its 105 scalars, occupied flag and M-channel gather.
   `position: (106+M)→P`, ReLU. Do not additionally erase an absent position's
   scalar/bias contribution; follow the source position computation exactly.
4. Compute masked roster sum/max pools for both sides in roster order.
   Concatenate global 36, flattened side 58, four position vectors, both side
   sums and both side maxima into `94+4P+4M` channels, in source order.
5. Torso layer 0: dense `(94+4P+4M)→H`, learned LayerNorm, ReLU; **replace**
   the torso input. Each of layers 1..L-1: dense `H→H`, its own learned
   LayerNorm, ReLU, then add the previous torso as a residual. No residual on
   layer 0, no moved normalization, and no cross-world normalization.
6. Linear `value: H→1`, with bias and no clamp to [-1,1].

The source inventory is five embedding arrays; weights/biases for move_token,
member1, member2, position, every torso layer and value; gamma/beta for every
torso LayerNorm. E3g's compiled wire inventory also includes each required
input/branch/normalization descriptor and scale, and must map every source value
element exactly once. Parameter counts above exclude nonlearned descriptors and
scale records. C weights are `[output,input]`, a declared transpose of source
`[input,output]`, never a change in dense reduction order.

Reproduce learned parameter counts without loading or initializing a network:

```python
def parameters(e, m, p, h, layers):
    return (2560*e + 25*8                         # five embeddings
            + (e+1)*e + e                        # move_token
            + (5*e+42)*m + m + m*m + m            # member1/member2
            + (106+m)*p + p                       # position
            + (94+4*p+4*m)*h + h                  # first torso
            + (layers-1)*(h*h+h)                  # later torso
            + 2*layers*h                         # all gamma/beta
            + h + 1)                             # linear value

assert parameters(32, 64, 64, 256, 2) == 333769
assert parameters(48, 96, 96, 368, 3) == 773193
assert parameters(64, 128, 128, 640, 3) == 1802441
```

Every graph fully recomputes from each new world's observation. No NNUE-style
accumulator, activation reuse across leaves, mean-world input or hidden-state
feature row is part of these declarations.

## Arithmetic and registered identities

Use DFEVAL format **1**, compiled integer arithmetic **1**, E3a's checked scalar
rules and **normalization-v1/residual-v1**. The concrete full graph requires a
checked int32-input dense path: E3a `dense32` currently has int16 input, so it
cannot silently narrow the normalized/residual torso between layers. Its
implementation and independent vectors belong to E3g before graph registration.
Unknown graph/arithmetic versions and unclassified tensors refuse by name.
These are private artifact identities, not new public gameplay numbers.

- Dense/embedding weights are int8, biases int64. Member/move/position activation
  storage is int16 at explicit quantization nodes. Pre-normalization, normalized
  torso, residual and linear value storage is int32. Gamma/beta are int32.
- The value is int32 Q12.20. Int32 range errors refuse; no hidden final clamp.
  Every intentional int16 saturation is an explicit descriptor/oracle node.
- Accumulate in ascending source index. Scales are positive multiplier and
  power-of-two shift; divisions round nearest/ties-to-even symmetrically.
  Each tensor's common units and each branch conversion are immutable graph
  data, with no input-dependent precision or implicit per-world rescaling.
- Preserve the teacher's positive epsilon through its declared variance scale.
  If conversion would produce zero, refuse rather than replacing epsilon.
  Compute variance/square-root with E3n's portable checked limb arithmetic.
- Cold loading validates all input columns, tensor shapes, scales, layer-specific
  bounds and normalization precision before returning a model. A matching shape
  alone is insufficient. E4 privately freezes the actual scale/calibration data;
  this proposal supplies no trained scale or parameter defaults.

Synthetic parity freezes canonical intermediate and final integer streams and
complete expected inventories independently of C. It does not imply floating
BC6 fidelity. Compiler/platform/IPO gates require zero differing bits. Later
full-BC6 conversion has the full spec section-9 fidelity gates; students report
those deviations and retain their separate mandatory gates. No threshold changes.

## Predeclared resource caps

These are **proposal limits before implementation/results**, not measured peaks.
E3g/E3b must produce exact aligned workspace layouts, checked size formulas,
maximum/one-past refusal tests, allocation-hook results and nested stack reports
within these caps. A miss requires an explicit reviewed declaration change.

| Limit | Small | Medium | Full |
| --- | ---: | ---: | ---: |
| Complete DFEVAL file, including metadata/directory/scales | 1 MiB | 2 MiB | 4 MiB |
| Metadata, included in file cap | 64 KiB | 64 KiB | 64 KiB |
| Additional scratch per worker, tile capacity 16 | 256 KiB | 384 KiB | 512 KiB |
| Workers maximum | 32 | 32 | 32 |
| Total workspace scratch maximum | 8 MiB | 12 MiB | 16 MiB |
| Logical leaf capacity maximum | 65,536 | 65,536 | 65,536 |
| Additional nested hot-path stack over legacy leaf/step | **16 KiB** | **16 KiB** | **16 KiB** |

No per-leaf private slab is reserved: E2's formula is
`workers * scratch_per_worker + leaf_capacity * 0`, bounded by the graph's
scratch maximum. Caller-owned values/statuses/digests, committed batch battles
and immutable loaded-model storage are accounted separately. The cold model
storage cap is `2 * file_max + 64 KiB`, covering the immutable opened-file
snapshot, decoded parameter payload and binding/scale/alignment overhead.
There is no automatic growth. More workers/leaves/bytes refuse named capacity.

A conservative proposed tile layout justifying the scratch envelopes reserves
two 4,376-byte encoder/raw-bit row temporaries (only one float encoder row),
16 canonical-input slots of 2,688 bytes, and two 16-element 32-bit result/status
arrays. E3a's canonical row currently occupies 2,600 bytes; slot padding makes
the reservation explicit and testable. Additional activation reservations for
each of 16 worlds are:

| Buffer | Bytes per world |
| --- | ---: |
| All masked move tokens | 96E |
| Masked member vectors | 24M |
| Position vectors | 8P |
| Member dense input | 2(5E+42) |
| Move dense input | 2(E+1) |
| Position dense input | 2(106+M) |
| First torso input | 2(94+4P+4M) |
| Four H-channel int32 torso/dense/norm/operator buffers | 16H |
| Move sum/max working vectors | 4E |
| Side sum/max vectors | 8M |

This totals **241,936 / 328,976 / 456,976 bytes** per tile-worker for
small/medium/full before final buffer alignment. Reserve an additional 4 KiB
for 128-byte buffer-boundary alignment, bounded scalar graph bookkeeping and
canaries in the resource tests; the sums remain below the respective caps.
Align each whole buffer, not every logical row. Large activations and input
rows belong in this cold-allocated scratch, never in variable-length stack
arrays. E3g may reuse non-overlapping lifetimes to reduce actual sizes, but may
not exceed a cap or omit a source stage to fit. The final report includes
actual offsets and measured peaks; these calculations are not that report.

The evaluated-expansion/digest integration must additionally account for its
bounded observation sidecars and existing call chain in E5, within the same
16 KiB additional stack limit. A private scalar graph or tile test alone does
not pass the integrated expand/project/digest/inference memory gate.

## Approval and delivery boundaries

1. Owner/HS review this documentation proposal. Full BC6-M synthetic wiring may
   proceed under the existing HS Go; small/medium stay out of the registry and
   implementation until this declaration is approved.
2. E3g ships registered scalar graphs in bounded PRs with exact source/wire/stage
   inventories, independent synthetic intermediate parity, checked resources,
   full recomputation, unchanged legacy behavior and unchanged public exports.
3. E3b adds tile-16 scheduling through the existing worker pool, with exact scalar
   parity under worker/chunk/partial-tile combinations, stack/workspace reports
   and no warm scheduler allocation. Integer SIMD is optional and separately
   subject to the same bit-equality gate. No new public expansion call here.
4. E4 remains disabled until the Owner separately authorizes conversion and
   each individual training run. No private weights, checkpoints, data rows,
   recordings, live logs or run outputs enter the repository or CI artifacts.
5. Synthetic speed is only a property of that synthetic workload. Candidate
   choice and adoption depend on the later three-way strength-at-equal-time
   comparison, equal-budget controls and all applicable fidelity/resource/live
   gates. The default evaluator remains JAX.
