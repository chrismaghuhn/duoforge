# M12 stage 3: phased expert iteration — specification

Status: **revised draft for owner approval, 2026-10-08; no implementation**. Decision: [0024](../../decisions/0024-expert-iteration.md). Replaces the previous per-step floor quota, outcome-MSE pilot and wall-time policy fallback. Each phase needs its own plan/review and owner go/no-go.

## 1. Shared contract and targets

Freeze `many-c4e96e6/params-49333`, checkpoint/model/encoder/id hashes, library, pool/weights, belief and D0023 leave-foe-source-out setup. Elo 768 belongs to the original brief's ladder. Pin parallel-game count, logical game ids, actor assignment, device/runtime/compiler, capacities, shapes/chunk order, masks, seeds and cutoffs. No moving teacher. Book off; separately reviewed M12.x preview (#240) is not silently incorporated into P0/P1.

**Information safety:** only the learner's original public prefix and C-reconstructed sampled worlds. In league games the teacher's foe model is **always its own frozen teacher net**, never actual opponent parameters. Real opponent execution is a separate controller which exposes no model handle. No true foe row, privileged hypothesis, actual hidden HP/stats/bench or oracle labels. Trap privileged calls and actual-opponent-network access; changing that network under identical public inputs must not change teacher worlds/tables/targets. Keep explicit public sleep/confusion refusals. Champions OTS exposes stat alignment; closed sheets are outside this contract.

One information-set policy, not separately solved world policies:

    tau = 0.5*x_N + 0.5*one_hot(E)

Map the K own joint-action ids to the full legal 1024 slot-pair distribution, zero elsewhere. Normalize the student over all legal actions; do not substitute slot marginals. Store sparse labels and validate uniqueness, legality, finite/nonnegative mass and total 1±1e-6. Forced/unrequested/refused/work-exhausted rows have no policy label. Search values are diagnostics. Preview labels over the 360-action head require separate adoption approval.

Draw the student's raw action from its full legal policy by an independent **keyed uniform before selection/routing**. Streams for student action, budget, worlds and X draw are separate. Keys use immutable logical game id, epoch and seat, not worker arrival/batch position. In P1 and later full/cheap teacher passes, if the action is outside teacher top K, displace the lowest candidate, keeping K=4/8. Record the displaced/included ids and audit against K+1; never guess a missing Q.

## 2. P0 — gate and profiling, no feature code

Use merged [#236](https://github.com/chrismaghuhn/duoforge/pull/236): **honest X, lambda=0.5, K=M=8, W=S=16, capacity=1024**. Avoid the oracle CLI default. Raw/X each play 512 games against raw 49333, identical rows/seeds, both seat orders (256 blocks); 2000 paired-seat bootstrap resamples. E only if it fits the one-CPU-hour gate budget, never an automatic substitute teacher.

Pass: **X-minus-raw point >=+0.08 score points AND 95% lower bound >0**. Incomplete/inconclusive results stop/report, with no repeated testing until a pass.

Profile unchanged search first: CPU/GPU, policy/team/value/world/solve/transfer, fixed-size curve such as 64/256/1024/4096/16384. Warm compilation outside steady-state timings but charge total cost. #236 is the source for ~30–34 ms/search and 5/127435 rational rescues lasting 1.8–18 s. The owner's 23-of-33-ms CPU-net split is a profiling lead, not a new measurement here. Record cross-capacity float/action differences. No new head/router/batching/training in P0. Stop/re-plan on budget or reproducibility failure.

## 3. P1 — random-1/8 pilot, value decision and continuation control

Use the **current teacher path**, not regret routing. Select eligible learner-seat TURN/REPLACEMENT/PIVOT requests with >=2 legal actions by `u_SELECT(key)<1/8`. Singleton steps work; grouping cannot affect selection. Alternate learner seats. Other seats execute frozen self-play/league policies. Valid selected roots play a keyed X draw and store its actual behavior likelihood; others play the already drawn raw action. Freeze teacher/collector student per round. Record eligible/selected/valid and cause counters.

**Choose (a): retain the existing GAE value regression**, gamma/lambda, acting/waiting row semantics, terminal bootstrap and truncation protocol. Save actual collector rewards/values/bootstrap for `returns.gae`. Do not retarget the discounted head to final outcomes. No PPO policy surrogate with wrong raw likelihoods. PPO policy/magnet are off in the pilot; league remains a collection mechanism.

    L = mean_teacher KL(tau || pi_theta)
        + 0.1*mean_non_target KL(pi_49333 || pi_theta) + c_V*existing_GAE_value_loss

Each mean divides by its own valid unpadded weights. Minibatch 4096: 512 teacher rows plus 3584 non-target learner rows. Existing value-mask regression covers valid learner rows in both strata, including waiting rows; no opponent private rows. Pin inherited c_V/gamma/lambda and report policy:value counts/gradient magnitudes. Padding contributes zero.

**Drift:** 16384 valid targets, whole-game held-out seed split (20% validation), same-size model, fresh optimizer in both arms, Adam LR 3e-5 constant, gradient norm 0.5, max four epochs/128 optimizer steps. Check held-out teacher KL and non-target reference KL each epoch; keep best epoch. Stop after two epochs without >=1e-4-nat improvement, nonfinite losses, or held-out non-target KL >0.02 nats. Hindsight/regret weighting off. Resume restores optimizer/shuffle/keys/shard cursor exactly.

**(b) Deferred architecture:** [#239](https://github.com/chrismaghuhn/duoforge/pull/239) uses the GAE head as a control variate; its probe reports `corr(result,luck)=0.39` and proposes an undiscounted head, not an implemented one. A separate outcome head needs owner architecture/loader approval and its own arm. It could predict win/tie/loss with utility p_win-p_loss; labels are public final outcomes. Define `mean_terminal` for that optional arm as the mean over stored learner rows of complete games with valid final results, not only terminal positions; exclude unresolved/incomplete games, explicitly tag any allowed tiebreaks. P1 has **no mean_terminal MSE**. Later regret uses the teacher's discounted/bootstrapped Q units, not claimed win probabilities.

### Deterministic rescue prerequisite

Preserve payoffs/certificate. Initial proposed solve caps: 4096 float pivots; 32 exact pivots, 250000 counted rational arithmetic/comparison operations and 4096-bit numerator/denominator. Include conversions/certificate work; calibrate on retained tail fixtures before P1. Exhaustion is table/config-dependent: raw action, precise counted cause/work, no label, no uncertified float acceptance.

Stop if **work fallbacks >1% of selected eligible roots**. The ~2% public reconstruction refusals in #236 are separate and excluded from this rule. Report both denominators. Outer wall-clock watchdog kills a stuck worker and **aborts an incomplete shard/run**, never chooses raw and silently continues a hardware-load-dependent trajectory. Reject late keys. No timeout flushing/asynchronous batching.

### Success must beat continued training

Control: approved Learner v2 continuation from 49333, same initial params/optimizer, model size and GPU-minute/CPU-core-hour caps, using its own Learner v2 data at the matched budget, not teacher-labelled data. Charge teacher generation/JIT/restarts/audits. Equal steps alone is not equal compute.

Predeclare primary raw-student vs raw-continuation H2H, 2048 games, same hardware, both seats, paired-seat 95% bootstrap. Pass only with **point score >=0.52 AND lower bound >0.50**. Also require vs frozen 49333 point >=0.53/lower >0.50 and positive paired-panel lower-bound evidence. Pin BC/3600/11000 paths/hashes and separate ladder output. No post-hoc choice of a passing endpoint. PP_/A/B/C and LL_ noninferiority lower bounds must exceed -0.03; broad/inconclusive or failing groups **block promotion**. Both PP_/A/B/C and LL_ are required groups; a missing required group blocks promotion like an inconclusive one. Stop on failure/inconclusive strength, drift, leak/compatibility, work-fallback threshold or budget. KL reduction alone cannot promote/scale.

## 4. P2 — lockstep GPU batching only

Collect all leaves of a synchronized step in stable decision/cell/world order. Policy/team/value GPU calls have fixed capacities/shapes, padded/masked tail chunks and zero padding. Finish before actors advance; no async queues, timeout flush or active-count-sized calls. Pin parallel-game count, chunk order, runtime and shapes. Preallocate native buffers outside battle hot paths; Learner v2 owns the planner. No routing/pruning changes here.

Report decisions/s, valid targets/s, calls/transfers/memory/JIT/total compute against current CPU/GPU curve. Require repeat-run byte-identical decisions/targets at identical seeds/capacity/device/runtime and identity against reference audits. If reshaping changes float bits/targets, it is not pure performance: fix layouts or request a separately classified change. No CPU/GPU cross-device bit claim. Stop on identity failure or no throughput gain.

## 5. P3 — regret router after batching

Cheap honest 4x4/S=4; full 8x8/S=16 only on large regret/disagreement. Include the sampled student action by displacement. `Q_T(a)=sum_w p_w sum_j q_w,j A_w(a,j)`, `r=max Q_T-Q_T(a_student)`; disagreement `1-pi_X,cheap(a_student)`. Initial criteria r>=0.05 in Q units or disagreement>=0.5. Confidently wrong low-entropy states matter; entropy alone is forbidden.

Independent budget gate: criteria AND `u_BUDGET(key)<1/16` initially (configurable up to 1/8). This bounds expected share, not a per-step floor; report realized share and apply a separate total-work cap. Same keys route identically for singleton/permuted/regrouped requests; parallel-game count is still pinned. Reuse cheap first-four world identities and immutable cell/model hashes. Cheap targets are not trained. Include a keyed full-teacher audit sample and its cost; report false negatives. Compare random 1/8 and routing at matched **total wall/compute time**.

Full valid labels get weight `clip(r_full/0.1,0.1,2)`; weighted KL divides by valid total weight. Value loss unchanged. Compare uniform/regret weighting separately. Stop for grouping dependence, no quality-efficiency gain or loss versus continuation.

## 6. P4 — double oracle with full-table audit

Small subset of the fixed eight-own/eight-foe universe; add a best response only if it exploits the current solution beyond the unchanged certificate. One own strategy across worlds, Bayesian world-specific foe responses. Cache cells on identical worlds/chance; count response scans/retries. Cover needed excluded responses for certification, expand to full if necessary. A subgame certificate is not a full-candidate/full-legal-space certificate.

Audit full 8x8/S=16 values, exploitability, policies/actions within the original certificate, no new epsilon. E/X require full policy-weighted expectation checks; dense foe support can force all cells. Report zero/negative savings honestly. Stop on mismatch/no net leaves saved. K+1/expanded universe audits are separate settings.

## 7. P5 — hindsight, mixed loss and scale

Hindsight off in P1–P4. Mine later public reveals/outcomes only in **training-split games**, initially <=10% of selected targets, with mining share/cost reported. Never mine validation/evaluation. Re-evaluate saved original public prefixes/belief/seeds; future facts/privileged truth cannot condition worlds, targets or weights. Mutation tests require identical targets despite changed later reveals. Weight by honest regret, not hindsight truth. Separately measure PPO+distill with actual behavior/on-policy contract, then consider 125000 labels/new teacher rounds. Stop on leak/held-out or strength regression/budget. Exploiter populations are explicitly out of scope.

## 8. Cost, ownership and privacy

Reference ~30 ms implies <=33 unbatched searches/s before overhead; 16384 searches alone cost ~8.2 min, **not total generation time**. At random 1/8 and ~8.7 eligible decisions/game, ~16k valid targets require **~15k games**, more with refusals: `games=labels/(f*D*success_rate)`. Measure D, collection/policy/I/O/refusal costs and shard bytes. Native workers do not multiply controller throughput. Cheap passes have 1/16 the leaves, **not 1/16 unbatched time**; latency/padding dominate. After batching, cheap-all plus full-1/8 is 192 leaves/state vs 128 for random-full-1/8; full-1/16 matches 128 before audits, but leaves are not wall time.

Caps proposed: one CPU wall hour P0; **eight CPU core-hours P1 generation**; two exclusive GPU hours for pilot/control/evaluation, split evenly and charging inference as well as updates. Above projected/actual 28800 CPU-second generation cap: stop/checkpoint privately and return a re-plan, not automatic extra actors/budget. Owner amendment (2026-10-08): profile 4/8/14 native workers before freeze, pin the fastest count and use the same core count for continuation. CPU accounting is getrusage self+children user+sys; GPU seconds are synchronous device-section wall time including JIT. Match each actual axis within 5%; eight core-hours replaces 2 h ×4 cores without increasing budget. Pause during Learner v2 timing windows; never contend for GPU A/B windows. Docs/small tests can run alongside. **AWS only after the engine covers the meta** and a new owner-approved cost/run plan (2026-10-08).

Owner relays to Learner v2: full joint log-prob API; own public rows/slots/mask; sparse targets/status; keyed raw action/true behavior logp; GAE rewards/values/bootstrap/masks; teacher/student/id/context/belief hashes; logical ids/parallel count; immutable phase/work counters; routing/weight/mining provenance and optimizer/RNG/shard cursor. Refuse incompatible resume. Learner v2 owns all loop/loss/batching/resume code. Each phase needs its own approved plan/resource and promotion gate. Rows, worlds/tables, histories, checkpoints and runs stay private via `refuse_repository`; no CI uploads. Reports carry aggregates only. Nothing here starts implementation.
