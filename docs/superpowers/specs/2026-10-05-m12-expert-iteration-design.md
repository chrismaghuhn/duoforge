# M12 stage 3: expert iteration — specification

Status: **draft for owner approval, 2026-10-05; specification only**.
Decision: [0024](../../decisions/0024-expert-iteration.md). Builds on
[Learner v2](2026-10-02-learner-v2-design.md) and
[honest search](2026-10-04-m12-visible-search-design.md), especially its section 10.
No implementation, training or measurement is started by this PR.
Owner additions of 2026-10-08 are incorporated below; this remains a proposal.

## 1. Starting checkpoint and entry gate

Freeze `many-c4e96e6/params-49333`, its hash, encoder/model/id tables, pool/weights, library and belief/exclusion
configuration. Elo 768 is the owner's reported rating in its existing ladder, not a cross-ladder calibration.
Opening-book overrides remain off throughout this experiment.

Re-measure **raw, honest X and honest E**, each for 512 games against the same frozen raw 49333. Use identical
pairings and seeds, 256 matchup blocks in both learner seat orders, and K=M=8, W=16, `lam=0.5`. Pin capacity,
network batch shapes and cutoff to the honest-search measurement. Bootstrap paired score differences by seat
block, not independent arms. E provides context; only X is the proposed teacher.

Proceed only if X-minus-raw mean score is **at least +0.08** and its 95% lower bound is positive. Otherwise
stop and report, including an inconclusive interval or incomplete resource-capped run. Do not tune lambda or
repeat gates until one passes. Record coverage, fallback causes and cost; a weaker gain against the stronger
net is a valid stop result. These are score points, not Elo points.

## 2. Teacher targets and action mapping

Current `Honest` records `own_pairs`, `pi_X`, `x`, `expected` and Bayesian `value`. The payoff tables are
8x8 **per world**; the policy target has at most eight entries over our joint actions, not 64 action labels:

    tau_i = 0.5 * x_N,i + 0.5 * 1[i = E]

For each root, map `own_pairs[i]` to the existing flat slot-pair index (`slot0*32 + slot1`) in the engine's
factored domain. Store sparse ids/probabilities; mathematically tau is zero on every other full-space action.
The student normalizes over **all legal actions**, not just the top eight. Its legal mask comes from C.
Reject duplicate/out-of-domain ids, negative/nonfinite mass or a sum outside 1±1e-6; never silently repair labels.
Do not replace the joint target with slot marginals: that discards strategic correlations. An existing additive
slot-head model may only approximate this distribution; monitor residual KL and off-candidate mass rather than
assuming perfect representability. A new policy architecture needs separate approval.

TEAM_SELECTION remains raw until the separate M12.x preview PR and its value-vs-turn-1-rollout measurement
are reviewed. If adopted, map its own tuple-candidate policy to the 360-action team head, with separate metrics
and a pinned preview evaluator; do not confuse it with slot-pair targets. Forced, unrequested,
unreconstructible and timed-out requests have `teacher_valid=0`; they are counted, not mislabeled as successful
search. Bayesian root value and expected row values are recorded diagnostics, not ground-truth value targets.

## 3. Loss and Learner v2 interface

The first arm is offline distillation, initialized from 49333. Student/control start with the same explicit
fresh optimizer; within-round resume restores optimizer and RNG state exactly:

    L = beta_D * sum_valid(w * KL(tau || pi_theta)) / sum_valid(w) + c_V * mean_terminal (v_theta - z_game)^2
    beta_D = 1; c_V = 0.5 initially

Cross-entropy `-sum_i tau_i*log pi_theta(a_i)` has the same gradient as that KL. Gather the sparse target
against the full legal log-softmax. Normalize by valid, unpadded teacher rows, not every rollout row.
Use full-teacher estimated regret from section 4.1: initial `w=clip(r_full/0.1, 0.1, 2)` on valid targets,
zero on invalid/padded rows. Pin the scale/caps per round and compare with uniform weighting at matched compute.
Do not weight labels by raw student entropy or hindsight truth. Regret weights do not change outcome-value labels.
`z_game` is the ordinary player-relative terminal result (-1/0/+1), shared across that player's game rows.
Incomplete/engine-refused games get no outcome-value label; explicitly tagged engine tiebreak outcomes may be
included only under the frozen collection cutoff protocol. Never train on the search's bootstrapped value
in this pilot. Value regression uses the stored learner rows with a valid outcome. Report policy and value
losses separately; shared-torso changes can affect the value head.

This pilot **replaces PPO and the magnet policy objective**; it does not feed teacher actions into PPO with
raw-policy likelihoods. League remains an opponent/data-distribution mechanism. This proposes a change to the
visible-search spec's auxiliary-first outline (section 10), requiring owner approval of D0024. If the pilot
succeeds, a separate arm may add `beta_D*L_D` beside the approved Learner v2 PPO/value/entropy/anchor losses. Teacher rows
then either stay supervised-only or carry the actual behavior likelihood required by that learner's on-policy
contract. The existing taken-action k3 anchor is not a substitute for full-distribution teacher KL.

**Owner-relayed contract to Learner v2, to confirm before implementation:**

| Producer supplies | Learner v2 owns/validates |
|---|---|
| Own encoded row, slots, legal mask, sparse joint ids/probabilities and validity/status | Full joint-policy log-probability API, masked KL, padding and sampling weights |
| Game/seat/epoch keys; terminal outcome and its validity | Game-level train/validation split, value-target use, optimizer and update cadence |
| Frozen teacher hash; schema/encoder/id/context/belief hashes; K/M/W/lambda, deadline and solver status | Compatibility checks and immutable round config; refuse incompatible resume |
| Deterministic data order and sampling/shuffle state | Atomic private shards/checkpoints, consumed-shard cursor, optimizer/RNG resume state |
| Frozen student choice/hash, cheap/full regret, routing reason, target weight, cached-world/cell keys | Routing/weight masks, synchronized step planner and fixed device-call shapes; preserve these on resume |

This is a proposed private target schema v1, not a new public C API. The learner session must confirm its exact
names/shapes, whether the auxiliary PPO arm fits its planned A/B, and exclusive GPU/CPU windows. The owner
relays questions/answers; this session does not implement or message that loop independently.

## 4. Collection and information safety

One expert-iteration round freezes teacher, collector student snapshot, opponents and belief. Use the existing self-play/league mixture,
logged in the manifest; in self-play the other seat is the same frozen raw network. Alternate the designated
learner seat. Eligible TURN/REPLACEMENT/PIVOT requests have at least two legal own actions. The random keyed 1/8
selector is the control; regret routing below is the proposed next arm. Only successful **full** teacher passes
play a seeded draw from tau and save a policy target; cheap passes are routing diagnostics, not targets.
Elsewhere play raw. Report eligible/cheap/promoted/successful counts separately. No moving teacher/both-seat search.

### 4.1 Student regret routes compute

Run a cheap honest 4x4, S=4 pass on many eligible states. Include the student's actual legal action within the
four own candidates (student plus top distinct teacher alternatives), so missing it cannot become guessed regret.
Use `Q_T(a)=sum_w p_w sum_j q_w,j A_w(a,j)` and `r=max_a Q_T(a)-Q_T(a_student)` in value units, not score points.
Disagreement is `1-pi_X,cheap(a_student)`. Initial promotion criteria are `r>=0.05` or disagreement `>=0.5`;
prioritize regret, with decision-key ties and a declared per-lockstep quota. A confidently wrong low-entropy
student must be routed. Entropy alone cannot be the selector.

Full promotion uses 8x8/S=16, includes the student action within that own budget, and reuses the cheap pass's
first four world ids/words. Freeze all hypotheses for the decision; never redraw between comparisons.
Start with at most `floor(eligible_in_step/16)` full promotions, bounded above by a configurable 1/8 quota;
if slots run out, record quota rejection, not a timeout. Monitor false negatives on a fixed keyed full-teacher
audit sample, charged to the same budget. Log cheap/full regret, disagreement, quotas and uncertainty: these are
teacher estimates, not actual hidden-state regret. Compare routing with random 1/8 selection on strength and
targets per total compute, not only on its selected-state average.

### 4.2 Restricted game / double oracle

After fixed-shape batching, start with a small subset of the fixed eight-own/eight-foe candidate universe and
add a best response only when it exploits the current solution beyond the unchanged certificate tolerance.
Own responses are one strategy across worlds; foe responses may be world-specific as in the Bayesian solver.
Cache evaluated `(decision, own_action, foe_action, world_id)` cells under model/context/hypothesis hashes.
Reuse the exact same worlds, chance streams and cell values; do not average separately solved per-world policies.

Best-response checks must cover every excluded candidate needed for a full-universe certificate. Count their
leaves, retries and expansions too. Stop only at that certificate or expand to the full table; a certificate
of the small subgame is not a certificate of all eight candidates, still less all legal actions. Keep the full
8x8/S=16 reference on an audit cohort. Require values to agree within the original certificate bound and report
exploitability, strategy/action disagreements and net leaves saved. Do not assert exact equivalence for E/X merely
because N's value agrees: their full policy-weighted expectations and mixed policies need separate checks.
Dense foe-policy support may require the full table for E/X; without valid omitted-cell bounds, report no
leaf saving for those rules rather than attributing an N-only saving to the 50/50 teacher.
Extending the response universe beyond the original top eight is another explicit, measured setting.

### 4.3 Hindsight mines states, never targets

Later public reveals or outcomes may rank saved decision keys for honest re-evaluation. The teacher receives
only that state's original public prefix, frozen belief and seeds, never future reveals, true spreads/HP,
future-conditioned worlds or privileged snapshots. Distillation weight comes from honest full-teacher regret,
not the hindsight signal. Save mining provenance separately. Tests append/change later reveals and require the
same re-evaluated target bytes for an identical saved prefix/config. Ordinary terminal value labels remain as
section 3; hindsight is not a replacement policy/value label. Exploiter populations are explicitly out of scope.

Use only `Honest` with public history and D0023's sampled worlds and leave-foe-source-out belief. Leaf expansion
uses reconstructed worlds, never the original true battle. Original true foe rows, privileged hypotheses,
canonical true-state snapshots and oracle-stage labels are forbidden model inputs/targets. Require an explicit
`teacher_kind=honest` manifest and enforce the actual implementation path; the arena's oracle default is unsafe
for generation. Trap privileged calls and test that hidden-only root changes, under identical public history,
keys and belief/exclusion config, leave worlds/targets unchanged. Unsupported visible sleep/confusion stays
explicitly counted raw play, as D0023 specifies. No Python battle rules are introduced.

First collect 16,384 **valid** policy targets. Split by whole games, with held-out seeds; reserve fixed matchup
blocks for validation and later strength evaluation. Log group/boundary coverage, label entropy, target KL,
off-candidate mass, leaf refusals, stale hashes and fallback rates. Consider 125,000 valid targets only after
the pilot passes. Freeze any next teacher only after evaluation and repeat the entry gate for the new teacher.

## 5. Bound the rational rescue

The owner reports five 1.8–18 s rescues among about 127k decisions. Preserve the normal certificate; do not
hide this tail by changing tolerances. Proposed rescue limit: **10 ms**, with an outer hard decision watchdog
initially 100 ms for the existing single-decision path. A lockstep batch gets an explicit bounded batch budget
chosen after profiling; it must not keep a single-decision 100 ms budget for an arbitrarily large batch.

A supervising collector already has the raw policy. A prewarmed isolated teacher worker receives only immutable
public inputs and owns its world/leaf buffers; no live battle handle is shared. Enforce the absolute monotonic
deadline outside that worker, not merely between rational pivots. Late or mismatched-key results are rejected; terminate/replace
the timed-out worker without blocking the collector, play raw, and emit no target. Count total-deadline and
rational-deadline expiry separately, with elapsed time and replay key. Unexpected engine/invariant errors stop
the run. Startup/JIT/restart cost counts toward the resource budget.

Record solver path, certificate/gap when available, and fallback status. Approximate float use is off by default;
a later explicit mode would require feasible strategies, a recorded actual exploitability, its own acceptance
threshold and separate evaluation. It must not claim the exact certificate or silently enter this dataset.
World/play/selection draws stay key-based. Wall-time expiry depends on load: replay the recorded fallback
decisions for reproducibility; seed alone cannot reproduce watchdog outcomes across machines.
The watchdog is safety containment, **not a batching policy**: it never flushes partial batches, changes
capacity or starts opportunistic work. Timing-triggered fallback runs fail the seed-only byte-identity acceptance
claim unless the identical recorded fallback map is replayed. Report them explicitly; deterministic bounded
solver work and no-watchdog-expiry repeated runs are the normal reproducibility gate.

## 6. Evaluation, success and stop

Students play **raw, without search or book**, with the same model size/encoder and one network decision as
49333. Freeze fresh evaluation rows/seeds, both seats, workers, cutoff and hardware. Use 2,048 games per
head-to-head/panel matchup, paired-seat bootstrap 95% intervals, and a separate ordinary ladder directory.
Pin the stage-1 BC/3600/11000 panel by explicit paths/hashes; never inherit it from the candidate run.
Report score/CIs, ladder Elo within the same anchors, and PP_/A/B/C versus LL_ results.

Success for the pilot requires score(student vs 49333) >=0.53 with lower bound >0.50, positive paired gain
against the fixed panel baseline, and no panel/group regression worse than -0.03 at its 95% lower bound.
If group intervals are too broad, report inconclusive rather than asserting no regression. Stop after a failed
pilot, nonfinite loss, information/compatibility failure, >1% deadline fallbacks, or resource exhaustion;
do not promote a checkpoint because training KL fell. No automatic unlimited rounds or hyperparameter sweeps.

Both sides have equal inference compute; teacher generation is an additional training cost and is reported.
Before claiming benefit over continued training, compare with a continuation from 49333 using the owner-approved
Learner v2 baseline under the same GPU-time and CPU-core-hour caps. Report actual usage, update/decision counts
and final strength; equal steps alone is not equal compute.

## 7. Cost, schedule and privacy

### 7.1 Inference optimization order and acceptance

First profile the unchanged honest teacher: CPU vs GPU, policy/value/world-build/solve/transfer timings and
the batch-size curve (e.g. fixed capacities 64/256/1024/4096/16384). The owner reports **23 of 33 ms** in
per-decision CPU network calls; this is the reference bottleneck, not a new measurement. Warm compilation outside
steady-state timings but charge it to total cost. Use identical pinned states/seeds and record cross-capacity
float/action differences; do not promise CPU/GPU or different capacities have identical bits.

Then collect leaves of **all decisions in one lockstep step** in stable decision/cell/world order. Policy,
team-head and value work use declared fixed-capacity GPU calls, padding the last chunk and masking padding.
Freeze and complete the step before actors advance; no asynchronous queues or timeout-based flushing.
Changing batch shapes with requested/active counts is forbidden. Capacity, chunk order, backend, deterministic
GPU flags, compiler/runtime and all masks are part of the reproducibility contract and resume metadata.
Preallocate/native buffers stay outside C battle hot paths; Learner v2 owns the synchronized planner interface.

Only then add routing/restricted-game pruning. Measure decisions/s, valid targets/s, total GPU calls, utilization,
transfer cost, leaves (including response scans), fallback counts and memory for (a) unchanged, (b) fixed lockstep
GPU batches, (c) batched cheap/full routing, (d) restricted games. Compare at equal total compute and include
quality checks against the full teacher. Accept each step only after repeated runs give **byte-identical chosen
actions and target distributions** at the same seeds/capacity/pinned runtime; a throughput win cannot relax this.

### 7.2 Planning budget

The **owner-provided ~30 ms/search** is a planning input for the old path, not a forecast after batching. For one search controller,
ceiling successful-label throughput is about 33/s before collection/I/O/refusals; at f=1/8 this supports at most
about 267 eligible learner decisions/s. Native batch workers do not multiply independent solver throughput.
16,384 labels cost roughly 8.2 min of search service, 125,000 roughly 62.5 min, before overhead. For the gate,
service time is `0.030*(512*D_X + 512*D_E)` seconds, with searched decisions/game D measured in a short pilot.
Measure the CPU/GPU split and 2/4/8 native-worker settings before committing a larger budget.
Cheap-all-state 4x4/S=4 costs 64 leaves/state; full 8x8/S=16 costs 1024. Adding full search on 1/8 costs
192 leaves per eligible state versus 128 for random-full 1/8. The initial routed 1/16 cap gives 128 before
audits/response scans, but equal leaves are not equal wall time. Recompute the cost plan from the profiling curve.

Proposed local caps: one daytime CPU hour for the gate, up to two further CPU hours for collection, and two
exclusive nighttime GPU hours for student/control training and evaluation. Start one CPU teacher actor with
two native workers while sharing the machine; use four, then at most eight, only in an owner-assigned idle
window. Retiming is required: 30 ms is not promised at every worker count. Bound queues; measure shard bytes
per row and memory before scaling. Do not invent many actors or rent compute to outrun the synchronous learner.

Alongside Learner v2 A/B, documentation/interface review and small tests can proceed. CPU generation needs an
explicit spare-core window and must pause during its timing/throughput measurements. GPU distillation never
shares the GPU with that A/B; queue it at night after the learner releases the device. These are proposed budgets,
not permission to start jobs or a promise of completion time. Both batched teacher inference and distillation
need exclusive GPU windows alongside the Learner v2 A/B, not merely the training update phase.

Targets, public histories/reproduction tables, checkpoints, manifests and run logs are private. Writers must
use `refuse_repository` across all worktrees and never upload CI artifacts. Later docs PRs carry aggregates
only, not rows, tables, game identifiers or weights. Approval order: owner reviews D0024/spec, relays/confirms
the Learner v2 contract and budgets, then approves an implementation plan. This PR ends at the specification.
