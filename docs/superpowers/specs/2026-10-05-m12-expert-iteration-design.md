# M12 stage 3: expert iteration — specification

Status: **draft for owner approval, 2026-10-05; specification only**.
Decision: [0024](../../decisions/0024-expert-iteration.md). Builds on
[Learner v2](2026-10-02-learner-v2-design.md) and
[honest search](2026-10-04-m12-visible-search-design.md), especially its section 10.
No implementation, training or measurement is started by this PR.

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

TEAM_SELECTION remains the raw 360-action head, with no search policy target. Forced, unrequested,
unreconstructible and timed-out requests have `teacher_valid=0`; they are counted, not mislabeled as successful
search. Bayesian root value and expected row values are recorded diagnostics, not ground-truth value targets.

## 3. Loss and Learner v2 interface

The first arm is offline distillation, initialized from 49333. Student/control start with the same explicit
fresh optimizer; within-round resume restores optimizer and RNG state exactly:

    L = beta_D * mean_valid KL(tau || pi_theta) + c_V * mean_terminal (v_theta - z_game)^2
    beta_D = 1; c_V = 0.5 initially

Cross-entropy `-sum_i tau_i*log pi_theta(a_i)` has the same gradient as that KL. Gather the sparse target
against the full legal log-softmax. Normalize by valid, unpadded teacher rows, not every rollout row.
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

This is a proposed private target schema v1, not a new public C API. The learner session must confirm its exact
names/shapes, whether the auxiliary PPO arm fits its planned A/B, and exclusive GPU/CPU windows. The owner
relays questions/answers; this session does not implement or message that loop independently.

## 4. Collection and information safety

One expert-iteration round freezes teacher, opponents and belief. Use the existing self-play/league mixture,
logged in the manifest; in self-play the other seat is the same frozen raw network. Alternate the designated
learner seat. Search a deterministic **1/8** of its requested TURN/REPLACEMENT/PIVOT decisions with at least
two legal own actions, selected by a separate seeded decision-key stream before seeing search outcomes.
On selected successful roots, play a seeded draw from tau and save the distribution; elsewhere play raw.
Report eligible/selected/successful counts separately. Neither both-seat search nor a moving teacher is implicit.

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
hide this tail by changing tolerances. Proposed limits: **100 ms wall time per teacher decision, at most
10 ms within rational rescue**, including communication in the total deadline.

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

The **owner-provided ~30 ms/search** is a planning input, not a new benchmark. For one search controller,
ceiling successful-label throughput is about 33/s before collection/I/O/refusals; at f=1/8 this supports at most
about 267 eligible learner decisions/s. Native batch workers do not multiply independent solver throughput.
16,384 labels cost roughly 8.2 min of search service, 125,000 roughly 62.5 min, before overhead. For the gate,
service time is `0.030*(512*D_X + 512*D_E)` seconds, with searched decisions/game D measured in a short pilot.
Measure the CPU/GPU split and 2/4/8 native-worker settings before committing a larger budget.

Proposed local caps: one daytime CPU hour for the gate, up to two further CPU hours for collection, and two
exclusive nighttime GPU hours for student/control training and evaluation. Start one CPU teacher actor with
two native workers while sharing the machine; use four, then at most eight, only in an owner-assigned idle
window. Retiming is required: 30 ms is not promised at every worker count. Bound queues; measure shard bytes
per row and memory before scaling. Do not invent many actors or rent compute to outrun the synchronous learner.

Alongside Learner v2 A/B, documentation/interface review and small tests can proceed. CPU generation needs an
explicit spare-core window and must pause during its timing/throughput measurements. GPU distillation never
shares the GPU with that A/B; queue it at night after the learner releases the device. These are proposed budgets,
not permission to start jobs or a promise of completion time.

Targets, public histories/reproduction tables, checkpoints, manifests and run logs are private. Writers must
use `refuse_repository` across all worktrees and never upload CI artifacts. Later docs PRs carry aggregates
only, not rows, tables, game identifiers or weights. Approval order: owner reviews D0024/spec, relays/confirms
the Learner v2 contract and budgets, then approves an implementation plan. This PR ends at the specification.
