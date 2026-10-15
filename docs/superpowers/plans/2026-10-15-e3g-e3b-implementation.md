# E3g/E3b: synthetic value graphs, then tile-16 scheduling

Owner/HS authorized E3g and E3b after E3n, with synthetic parameters only.
This is an implementation preparation, not a registered graph, training/export
approval, performance result or adoption record. E4 remains off. E3n #566 must
merge before its dependent implementation PR opens. During the exclusive
restructure-step-9 window, push branches only; open no new PR. HS merges.

## Source inspection and the graph declaration prerequisite

Inspected E3n `e3062f7ed875f8e9b54b723173fba72b7a79f96e`, dirty=false,
including main `ac555c167dce3e7bea91aed117eff5d869687eb8`, on Linux x86-64
machine `8c91664c82d0`. The following are source facts, not private-model or
timing measurements. No private checkpoint was opened.

The approved [evaluation specification](../specs/2026-10-14-in-engine-evaluation-design.md),
sections 5, 7 and 11, requires reviewed concrete full/small/medium declarations.
Its small/medium dimensions remain open. E2's production registry is still empty.
An HS question asks where the reviewed declarations are located; none was found
in the inspected source. Do not describe an invented candidate as pre-approved.
Before implementing a candidate, reconcile its dimensions, topology, tensor
inventory, scales/arithmetic and resource limits with the reviewed declaration.
Do not infer the actual teacher configuration from the BC6 nickname.

For the public `model_v2.config("M")` defaults, source inspection gives:

| Source property | Value |
| --- | --- |
| Embedding/member/position/hidden widths | 64 / 128 / 128 / 640 |
| Torso layers | 3, with LayerNorm; layers 1 and 2 add residuals |
| Species/move/item/ability/nature capacities | 1024 / 1024 / 256 / 256 / 25 |
| Nature embedding width | 8 |
| Encoder groups | global 36; side 2×29; position 2×2×105; member 2×6×32 |
| Member/position/first-torso input widths | 362 / 234 / 1118 |
| Value-path source tensors | 27 |
| Value-path source elements | 1,802,441 |

This is the public M topology, **not verification of a private BC6 artifact**.
The source inventory is five embeddings; weights/biases for move_token, member1,
member2, position, three torso layers and value; and gamma/beta for each of the
three torso normalizations. Struggle and policy/team heads are not read by the
value path and are excluded. The C dense layout transposes source `[input,output]`
weights into `[output,input]`; independent tests must verify that mapping.
The eventual wire inventory also accounts for every scale, input conversion and
normalization descriptor; 27 is not a claimed final wire-tensor count.

## E3g: bounded graph PRs

Start with the reviewed full graph. Split the small/medium graph additions into
separate PRs when that keeps inventory and resource review tractable. Keep each
PR independently testable; merge current main normally before opening it.

1. **Freeze each concrete declaration before its results.** Record all dimensions,
   categorical capacities, exact source and wire inventories, rounding/saturation
   nodes, arithmetic identity, per-graph file/scratch maxima, alignment and
   leaf/worker limits. Medium must have a strictly intermediate value-parameter
   count. Register an explicit compiled descriptor; unknown graphs/tensors refuse
   by name. No executable graph is read from an artifact. Use synthetic runtime
   parameters only; no checkpoint inspection, calibration or export.
2. **Close the int32 path explicitly.** E3a `dense32` still takes int16 input;
   E3n's normalized and residual torso states are int32. Preserve those declared
   states through later torso layers and the linear head. Add the necessary
   checked private operator with independent int32 boundary/rounding vectors;
   never insert an unrecorded int16 saturation. Extend the cold descriptor proof
   beyond E2's current int16-only input bound where the graph requires it.
   Keep every existing scalar test and oracle unchanged.
3. **Resolve parameters cold.** Integrate the compiled descriptor with the
   existing opened-file SHA/schema checks. Decode canonical little-endian values
   without unaligned typed-pointer casts, pointer-size assumptions or host-endian
   interpretation. Validate every graph-specific scale/normalization/bound before
   publishing a model. Unknown/missing/reordered tensors, zero epsilon,
   unprovable bounds and one-past resource limits refuse explicitly. Any decoded
   parameter storage is immutable and allocated only during cold construction.
4. **Wire one scalar world.** Use E3a's canonical input grouping/ID conversion.
   Preserve move masks, sum/max pools, registered-member masks, occupant gathers,
   position inputs, roster order, each dense→LayerNorm→ReLU sequence, the first
   torso replacement, later residuals and unclamped Q12.20 linear value output.
   All branch rescalings are declared. No cross-world statistics, delta cache,
   learned-feature shortcut or second visibility/feature recipe.
5. **Prove complete fresh computation.** An independent Python integer graph
   oracle compares every named intermediate and final value with C. Freeze the
   expected stage/tensor inventories independently; missing stages cannot turn
   into fewer passing comparisons. Include empty/partial pools, ID zero,
   absent/registered members, boundary IDs, mask/gather ordering, negative ties,
   positive epsilon, residuals, late failure and linear values outside [-1,1].
   Poison scratch between A/B/A calls and change/reorder worlds: no previous
   activation or world can affect a recomputed result.
6. **Report the graph's resource gate.** Reserve checked aligned scratch from E2's
   worker regions, with no vector-sized automatic arrays or warm heap operations.
   Account for one existing encoder row, its raw-bit bridge, canonical inputs,
   live activations, operator scratch and alignment. Record actual maxima and
   worst nested stack, rather than treating a guessed cap as a measurement.
   Distinguish private graph measurements from later expand/digest peak memory.

Per-PR gates: synthetic graph/intermediate parity, complete registered inventories,
malformed/incompatible artifact refusals, maximum/one-past capacities, warmed
allocation hooks, stack reports, sanitizers, source lint and unchanged old
API/layout/export surface. Run targeted CTests with IPO on and off. Compare the
same canonical integer streams under GCC, Clang and hosted Windows/MSVC builds.
Every report identifies commit, dirty status and machine. These gates establish
synthetic graph correctness; they do not establish fidelity to trained BC6.

## E3b: tile-16 worker dispatch after the scalar graph

Use the existing cold-created batch worker pool. Its callback already supplies
the worker index; the current `dfi_batch_leaves` bridge discards it. Add a private
worker-aware tile bridge as needed without changing the legacy leaf callback,
public expansion ABI or public numbering. Do not create another hot thread pool.

- Split logical rows into complete or partial tiles of at most 16. Compute tile
  counts and row offsets with checked arithmetic, including near-maximum counts.
  Assign tiles through the existing pool; bind each callback's actual worker
  index to that worker's preallocated scratch. Never derive scratch ownership
  from leaf indices or assume every worker receives a nonempty slice.
- Preserve logical row indices, fixed seed/key/sample inputs, output positions
  and deterministic diagnostic selection. Partial tiles evaluate exactly their
  real rows, with no padded leaves or cross-row reduction. Each graph still
  recomputes every world in full.
- Validate model/context/capacity/worker identity and acquire workspace ownership
  before dispatch. Refusal must not touch another owner's scratch. Preserve the
  existing public lifecycle/refusal contracts. Do not add the evaluated-expansion
  public sibling or Python evaluator switch here; those belong to E5.
- Compare scalar values and every intermediate across 0/1/15/16/17/31/32/33-row
  cases, all supported worker counts, empty slices, varied chunk boundaries,
  reordered worlds and repeated calls. Exercise actual concurrent dispatch,
  busy/identity/capacity refusals and scratch/output canaries under ASan/UBSan
  and TSan. Prove zero allocation/free in the warmed scheduler and operators.
- Optional integer SIMD must preserve every rounding point and pass exact
  scalar parity before enabling that kernel. It is not required to ship the
  first tile dispatcher. Unsupported acceleration uses the certified scalar
  implementation, without choosing a different graph.

Freeze and measure each graph's tile/worker scratch formula and additional
stack against its reviewed cap. Keep caller output arrays, model storage,
one encoder-row temporary, digest sidecars and committed battles separately
accounted for. A bound miss is a named refusal, not hidden resizing.

Synthetic microbenchmarks, if useful for this step, report only their own
workload/provenance and uncertainty. They establish neither real-network
throughput nor strength, candidate selection or adoption. The three-way
strength-at-equal-time comparison and equal-budget control remain later gates.

## Deferred by the authorization boundary

E4 conversion, all distillation/training (including retries), calibration,
private checkpoint/data access and live adoption remain off until their separate
Owner approvals. No private weights, runs, recordings or live logs enter the
repository or CI artifacts. New public identifiers require HS assignment.
