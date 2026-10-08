# Stage 3 P1 implementation plan: random-1/8 distillation pilot

Status: **proposal for owner approval, 2026-10-08**. This PR is a reviewed-by-author implementation plan, not permission to implement, collect or train. The owner reviews it after the coordinating review; each later run needs the agreed resource window. P1 does not authorize P2–P5.

Sources: [decision 0024](../../decisions/0024-expert-iteration.md), [stage-3 spec](../specs/2026-10-05-m12-expert-iteration-design.md), [P0 report](../../learning/2026-10-08-stage3-p0/README.md) ([#242](https://github.com/chrismaghuhn/duoforge/pull/242)). P0 X gain is +0.2695 [0.2129, 0.3262]. Its CPU search median is about 50 ms, not the older 30 ms estimate. GPU inference improvements do not change the P1 CPU teacher or satisfy P2 identity requirements.

## Scope and ownership

M12 owns the honest teacher adapter, sparse-label/collection contract, deterministic solve-work budget and measurement orchestration. **Learner v2 owns the training loop, loss/optimizer/resume integration and continuation arm; the owner relays and confirms this interface.** Proposed new modules below are implementation locations to agree, not existing APIs. No messages to other sessions are authorized by this plan.

Keep preview raw, book off, frozen 49333 teacher and collector, 50/50 X, W=S=16, K=M=8, capacity 1024, CPU teacher, four assigned native workers and 512 lockstep games. Pin logical game ids/seat/epoch/order, runtime/compiler, masks, encoder/id/pool/belief hashes and all RNG streams. No regret router, GPU teacher batching, double oracle, hindsight, outcome head, exploiter population or PPO+distill arm. No new C battle rules, hot-path allocations or silent fallback.

## Task 1 — freeze the experiment and relay the Learner v2 contract

Files to inspect: `python/duoforge_learn/{train,selfplay,returns,ppo,policy,runstate,checkpoint}.py`, `python/duoforge_search/{honest,matrix,arena}.py`. Proposed manifest/schema: `python/duoforge_search/expert_data.py`; validation tests in `python/tests/test_expert_data.py`.

- [ ] Freeze params-49333 SHA-256 `ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb`; teacher/student start at identical params, same architecture/encoder, fresh optimizer in both arms. No moving league snapshot or teacher during collection.
- [ ] Owner relays schema v1 fields: own public observation/slots/legal mask; logical game/seat/request epoch; sparse joint ids/probabilities; requested/acting/learner/value/target masks; selected/status/cause and work counters; raw sampled action, executed action and true behavior log-probability; actual rewards/done/collector values/bootstrap; reference policy provenance; teacher/collector/model/encoder/id/pool/belief/config hashes; split/shard cursor and RNG/optimizer state.
- [ ] Learner v2 confirms unchanged GAE gamma/lambda/c_V, waiting-row and truncation semantics, full joint log-prob API, deterministic checkpoint/resume and the continuation configuration. Copy actual values into the private manifest; no guessed default. Confirmation is required before implementation crosses into its loop and before a run.
- [ ] Predeclare primary endpoints, fixed BC/3600/11000 checkpoint hashes, seeds, budgets and required evaluation buckets **PP_/A/B/C and LL_**. P0 had no LL_; prepare an approved registry/weight manifest with LL_ coverage before spending the training budget. If unavailable, report blocked promotion and re-plan, never drop the requirement.
- [ ] All target shards, captured states, checkpoints, diagnostics and run directories pass `refuse_repository` and stay outside Git/CI artifacts. Unsupported schema, illegal id, incompatible resume, invalid likelihood or nonfinite labels fail explicitly. Hashes and run aggregates may be reported later; individual rows/worlds/tables may not.

Acceptance: owner-relayed interface and resource/evaluation manifest are agreed; synthetic schema/resume/privacy checks pass. Missing agreement/coverage stops at planning, not an improvised arm.

## Task 2 — deterministic rescue before collection

Proposed changes: `matrix.py` budget accounting; `honest.py` typed work-exhaustion status. Tests: `python/tests/test_search_budget.py` and existing matrix tests.

- [ ] Add opt-in solve-work accounting, preserving the current default solver behavior. Per decision, count all float attempts/stable retries/certification together: 4096 float pivots; 32 exact pivots; 250000 exact arithmetic/comparison operations; 4096-bit numerator/denominator. Count tableau initialization, conversions and certificate work; budget counters never reset on retry. Define the counted primitive operations in the manifest/tests, including bit checks around intermediate results.
- [ ] Use a dedicated exhausted-work status with cause and consumed/allowed counters. Only this documented condition plays the already sampled raw action and emits **no teacher label**. Keep original payoffs, fixed tie-breaking and certificate tolerance; no quantization or uncertified float acceptance. Unexpected solver errors abort instead of becoming raw choices.
- [ ] Calibrate on retained private rescue-tail fixtures and public synthetic ill-conditioned tables before collection. Measure identity to the unbounded solution when within budget, work counts and exhaustion share. If caps need changing, stop for reviewed re-plan; do not loosen the certificate or automatically raise the budget.
- [ ] Outer wall watchdog aborts an incomplete shard/run and rejects late keys. PC load may stop a run, never select a different policy trajectory by timing out individual solves.

Acceptance: byte-identical result/counters for the same table/config, including under injected clock delays; exact/float cap and bit-limit tests; valid within-budget certificates; default-off regression checks. **Work fallbacks >1% of selected eligible roots stop P1.** Public reconstruction refusals are separately counted and excluded from that numerator; report denominators and overlapping causes.

## Task 3 — keyed random collection and teacher labels

Proposed module: `python/duoforge_search/expert.py`; adapter to Learner v2's approved collector. Tests: `python/tests/test_expert_teacher.py`.

- [ ] Draw raw action first from the frozen student's full legal policy with an independent keyed word. Select eligible learner TURN/REPLACEMENT/PIVOT requests with at least two legal actions using `word_SELECT < 2**61` (exact probability 1/8), not every eighth arrival or a floor quota. Keys encode immutable logical game id, seat and request epoch; raw/selection/world/X/audit streams are domain-separated and versioned. Preview/forced/unrequested states have no target.
- [ ] Collect one learner seat, alternated by logical game id; other seat executes the frozen self-play or predeclared league controller. Teacher foe model is always 49333, never the real opponent network. Keep existing explicit public sleep/confusion/queue refusals. No privileged truth, oracle or future reveals in inputs/targets/weights.
- [ ] Preserve fixed K=8: if sampled raw action is outside the top eight, displace the lowest-ranked candidate with deterministic ties. Record included/displaced ids. A keyed 1% selected-root K+1 audit uses the same worlds, is charged to generation and does not replace labels. Report differences honestly: restricted universes can disagree; missing Q must not be guessed. Audit setting is separate, including its 1152-leaf chunking/capacity effects.
- [ ] Use one Bayesian strategy across worlds: `tau = 0.5*x_N + 0.5*one_hot(E)`. Map candidate joint ids to sparse mass in the full 1024 action space; normalize the student over all legal actions. Validate unique/legal ids, finite nonnegative mass and sum 1±1e-6. Do not train slot marginals or final-outcome values as search labels.
- [ ] Valid selected roots execute a keyed tau draw and record `log tau(executed)`. Unselected/refused/exhausted roots execute the previously drawn raw action and record its raw likelihood. Store actual collector reward/value/termination data for GAE, not counterfactual teacher rewards.
- [ ] Stop at 16384 accepted targets including held-out targets. Finish active games privately so returns are valid; deterministic label cap/overflow accounting is by logical decision order, never completion speed. Whole-game keyed split assigns approximately 20% to validation before training; never split rows of one game across train/validation. Record realized target counts. Validation labels never receive optimizer updates.

Acceptance: synthetic tests for singleton/permuted/regrouped requests, keyed selection frequencies and inclusion/ties; mapping and likelihood checks; no-label fallbacks; slot masks; uninterrupted/resumed byte identity at pinned capacity/parallel-game count. Public-prefix mutation traps must compare world/leaf digests and labels with a foe-sensitive net; trap privileged calls and changing the real league-opponent network. No hindsight in collection, validation or evaluation.

## Task 4 — Learner v2 distillation and drift guards

Learner v2 implements the agreed loop extension (proposed `python/duoforge_learn/distill.py`), with `returns.py`/`ppo.py` value logic reused; M12 supplies schema/teacher tests, not a second training loop.

- [ ] Keep existing GAE value regression, coefficients, acting/waiting targets, reward aggregation, terminal zero bootstrap and existing truncation protocol. Value targets come from actual collector trajectories. No `z_game` MSE on the discounted head and no separate win head. Include waiting learner rows; exclude opponent private rows.
- [ ] Pilot loss is `mean_target KL(tau||pi_theta) + 0.1*mean_non_target KL(pi_49333||pi_theta) + c_V*existing_GAE_value_loss`. PPO policy surrogate and magnet are off **only for the distillation arm**; league is collection. Continuation retains its approved Learner v2 recipe.
- [ ] Use fixed minibatches of 4096: 512 teacher rows and 3584 non-target learner rows. Padding has zero weight; each mean uses its own valid weight sum. Reference policy KL uses requested/legal policy rows and the correct head (preview may be regularized, never teacher-labelled); waiting rows remain value-only. Freeze reference outputs by the pinned full legal policy. Preserve the existing value-loss formula/masks; log policy/value counts and gradient magnitudes so stratum sampling is visible.
- [ ] Uniform teacher weights. Shuffle whole training strata deterministically; each training label visited once per epoch, with padded final chunk rather than silent dropping. Non-target reuse and shuffle cycles are recorded, with sufficient non-target rows or explicit refusal. Max four epochs and 128 updates, whichever first; fresh Adam, LR 3e-5 constant, gradient norm 0.5. No mid-pilot tuning or extending the epoch cap.
- [ ] Validate each epoch on held-out whole games: teacher KL and non-target reference KL. Keep best epoch; stop after two epochs without >=1e-4-nat improvement, nonfinite loss or held-out non-target KL >0.02 nats. Restore identical optimizer/shuffle/keys/stratum/shard cursor on resume; mismatches refuse resume.

Acceptance: synthetic loss tests distinguish sparse full-space KL from candidate-only renormalization; unchanged GAE targets/value formula including waiting/end/truncation; no gradient from padding/held-out/opponent rows; stop/restore tests. Existing default PPO path and opt-out training remain unchanged.

## Task 5 — continuation control, evaluation and stop

Learner v2 coordinates the control; owner relays the recorded configuration and artifacts. Proposed evaluation CLI: `python/duoforge_search/expert_eval.py`, reusing arena/ladder pairing and private-output guards.

- [ ] Start both arms from frozen 49333 with fresh optimizer and unchanged model size. Continuation collects **its own Learner v2 data at matched compute**, never teacher-labelled data. Match predeclared CPU-core-hour/GPU-minute ceilings and resource windows; charge teacher generation, compilation, audits, failed attempts and restarts to the pilot. Learner v2 sizes the control against the pilot's measured resource expenditure with an owner-agreed tolerance; equal configured ceilings alone do not establish matched actual compute. Do not call equal optimizer steps or equal game count equal compute.
- [ ] Pin a fixed train/validation/evaluation split, registry weights and seeds, identical evaluation hardware, batch shapes and raw play for both arms. Preview and book remain off. Run separate-output ladder, primary student vs continuation H2H (2048 games, both seats), frozen-49333 H2H and paired panel suites (propose 2048 per H2H, 1024 per panel opponent per arm). Predeclare these budgets; inadequate resource budget means re-plan, not reduced evidence presented as a pass.
- [ ] Use 2000 paired-seat bootstrap resamples. Primary continuation H2H must have point score >=0.52 **and** lower 95% >0.50. Frozen-49333 H2H must have point>=0.53/lower 95% >0.50; panel student-minus-continuation pooled equal-opponent-weight gain must have lower 95% >0, with each opponent reported. No picking whichever endpoint happens to pass.
- [ ] Report group-specific student-minus-continuation panel gains with matched seat clusters; required PP_/A/B/C and LL_ lower 95% bounds must both exceed -0.03. Missing, failing or inconclusive required groups block promotion. Allocate equal evaluation mass to these two buckets in the reviewed manifest; this new evaluation pool is not an unlabelled comparison to P0's PP-only pool. Report all group/game budgets and the ladder separately.
- [ ] Stop on strength failure/inconclusive evidence, drift, leak/compatibility, >1% deterministic-work fallback or budget breach. No repeated statistical trials until success, no best-of-seeds checkpoint selection, no automatic scale-up. Publish only aggregates and fingerprints in a later result docs PR; retain rows privately.

Acceptance: adversarial synthetic pairing/seat/group/CI tests, explicit missing-group failure, private paths refused, panel hashes stable and continuation data provenance separate. A passing result authorizes an owner promotion decision, not P2 implementation.

## Resources and delivery sequence

**After plan approval only:** first schema + teacher/work-budget code and synthetic tests; then owner-relayed Learner v2 integration/control review; then bounded private collection, GPU training/evaluation windows and aggregate report. Review each component before a run; no heavy run implicit in this docs PR.

Generation cap: two CPU wall hours on four assigned cores; account separately in core-hours for the continuation comparison. At the measured ~50 ms/search, 16k labels alone cost about 14 min, before raw collection/public refusals/audits. At ~8.7 eligible decisions/game and random 1/8, order-of-magnitude ~15k games; P0 counted searched rather than all eligible decisions, so measure the actual eligible count and success rate before projecting. Formula `games=labels/(selection_share*eligible_per_game*success_rate)`. A short smoke, included in the cap, forecasts throughput/shard size; projected or actual cap breach stops for re-plan. No automatic extra workers.

Two exclusive GPU hours total for pilot/control/evaluation, split evenly between arm-attributable work; charge inference and compilation too, with shared evaluation overhead recorded. Actual work and unused ceilings must be visible: a trivial pilot update budget is not assumed to consume an hour. If matching the continuation or fixed evaluation budgets cannot fit, stop before runs and seek a revised plan. Use scheduled local night windows without contending with Learner v2 A/B or ongoing training; CPU generation in assigned daytime windows. Documentation/small tests can coexist. Do not change existing jobs/worker counts. AWS only after engine meta coverage and a new owner-approved budget.

## Approval checklist

- [ ] Owner approves this P1 plan; Learner v2 contract/continuation/evaluation manifest confirmed via owner.
- [ ] CPU teacher, work accounting/caps, schema/loss/GAE/default-path and privacy tests reviewed.
- [ ] Required LL_ coverage and group evaluation budgets available; resource windows and matched compute ledger agreed.
- [ ] Pilot run separately scheduled within caps; stop counters and reproducibility contract fixed before collection.

No approvals are presumed checked. No feature code, target generation or training is included in this PR.
