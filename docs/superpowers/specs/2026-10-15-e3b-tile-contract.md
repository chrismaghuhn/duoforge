# E3b: bounded tile-16 dispatch

Implements the E3b portion of the approved
[evaluation design](2026-10-14-in-engine-evaluation-design.md), with only
runtime synthetic parameters. The three value graphs and their arithmetic are
unchanged from E3g. Every row recomputes the complete scalar graph. No SIMD,
weight conversion, training, public evaluated-expansion API or backend switch
is introduced. E4 remains subject to its separate Owner approval.

## Ownership and scheduling

`dfi_eval_tiles` is private and synchronous. E5 can supply the existing batch
pool and a worker-aware encoder/leaf bridge; the scheduler does not create a
pool, expand battles, change the seed/key/sample mapping or interpret features.
The caller exclusively owns that existing pool during this call, just as for
its other batch operations. Its immutable row-source descriptor supplies raw
encoder-6 bits for a logical leaf and may optionally inspect that leaf's
intermediates. Callbacks run on different workers for distinct rows; their
shared inputs must be immutable and mutable outputs disjoint. Callbacks must
not retain scratch pointers or allocate in the hot path.

Required arguments and the registered graph are checked first. E2 validates
workspace/model/context identity, worker identity, capacity and exclusive
workspace ownership before dispatch. Scratch extents and output-size arithmetic
are then checked before any row/output/scratch is touched; a failed check
releases ownership. The supplied error record is the only preflight output.
Zero rows still perform global identity/ownership checks, accept NULL row/output
arrays, run no callback and touch no scratch. No refusal resizes or changes graph.

The tile count is `count/16 + (count%16 != 0)`, never `(count+15)/16`.
Approved graphs cap count at 65,536 and workers at 32. The existing pool divides
tile indices into contiguous slices using wide products. Within a slice each
tile visits precisely its real rows in order, and uses slot `leaf%16`. Logical
indices, output positions and source order within each slice are unchanged by
thread completion. Empty slices do not call the worker or read its old scratch.

Worker w exclusively owns `scratch + w*scratch_per_worker`; scratch is never
chosen from the leaf index. The first aligned raw-row reservation from E3g is
reused serially within this worker. The graph's activation/canonical-input slots
are disjoint from it. There is no private count-by-1094 slab or per-call pool.

All real rows continue even when a different row refuses. A successful graph
publishes its value; a refused source, input, graph or late trace leaves that
value untouched and writes a nonzero row status. The caller must check status.
Each worker saves its first failure in logical order. After joining, the caller
selects the minimum failing logical index across nonempty slices, then publishes
that status, phase and reason. Neither completion order nor stale empty slices
selects a diagnostic. An unnamed source failure receives
`input:eval_row_source_refused`; the callback's named refusal is otherwise kept.

## Resources and isolation

The final 256 bytes of each worker's existing cap hold one bounded diagnostic;
a static assertion proves its record fits. Byte copies avoid typed-alignment
requirements in that tail. The graph receives `worker_cap-256`, which is checked
against E3g's exact required region before any dispatch.

| Graph | E3g region including worst alignment | Diagnostic reservation | Existing worker cap |
| --- | ---: | ---: | ---: |
| Small | 242,431 B | 256 B | 262,144 B |
| Medium | 329,471 B | 256 B | 393,216 B |
| Full | 457,471 B | 256 B | 524,288 B |

Model storage and the existing 8/12/16 MiB maximum worker reservations are
unchanged. Caller-owned values/statuses/source state, the cold worker pool and
future battle/digest sidecars are accounted separately. The scheduler has only
fixed-size automatic control/diagnostic records, no heap calls or automatic
vector arrays. Stack compilation and watched allocation counts belong to the
delivery proof; they do not claim an integrated E5 expand/digest peak.

## Synthetic gates

The test's runtime-only in-memory fixture uses all three registered shapes and
the real graph binding/scalar forward. It does not validate an artifact by its
own declaration or replace E3g's independent Python arithmetic/graph oracle.
For 33 distinct raw observations, it independently runs the scalar path first.
Canonical SHA-256 includes every stage's name, index, type, count and integer
bytes; stage counts are independently fixed at 197/201/201. Both values and all
stage bytes must agree under scheduling. At least two scalar values must differ,
so constant-value fixtures cannot pass ordering accidentally.

The declared scheduling matrix is all eight boundary counts
`0/1/15/16/17/31/32/33` with every supported worker count 1..32 for small.
Full/medium cover every worker at 17 rows and all eight boundary counts at
1/4/32 workers. All three additionally test reordered worlds, poisoned scratch,
repeated calls and three complete chunk partitions at 1/4/32 workers. These
cross-product and boundary cases complement the row/scratch ownership argument;
they do not claim exhaustive testing of arbitrary count-sized partitions.

Every visited row is counted exactly once, assigned to the actual expected
worker, and compared with the scalar observation of that logical world. Every
absent row, output suffix, empty-worker region and unused diagnostic tail suffix
has a canary. Concurrent source/input/late-trace failures must retain successful
rows and select the smallest failing index. NULL/model/context/worker/busy/size
and one-past capacity refusals must leave scratch and caller outputs unchanged.
The maximum 65,536-row dispatch exercises all indices with named source refusals,
without running 65,536 redundant full synthetic graphs; every row is still
counted once and every value remains untouched. UINT32_MAX refuses preflight.

The separate `tiles_concurrent` case covers all graphs and actual 1/2/4/8/16/32
worker pools, including failure/chunk/order gates and maximum dispatch. It is
selected by `ci-tsan` without needing NumPy, JAX, Node or any private file.
Allocation hooks watch the scheduler and scalar operators, including parallel
callbacks. Compiler/IPO, sanitizer, inventory, exports and resource evidence
identify the clean code commit and machine in the delivery report. Test elapsed
time is not network throughput, strength evidence or an adoption result.
