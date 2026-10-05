# 0024 — Expert iteration with the honest X teacher (M12 stage 3)

Status: **proposed for owner approval, 2026-10-05**. Stage 3 is approved in principle; this decision and
the [specification](../superpowers/specs/2026-10-05-m12-expert-iteration-design.md) are not yet approved.
This PR contains documentation only. It authorizes no implementation or run. Follows decisions
[0017](0017-learner-v2.md), [0022](0022-search-support.md) and [0023](0023-determinization-public-state.md).

## Context

The owner names `many-c4e96e6/params-49333` as the starting checkpoint (current best, reported ladder Elo 768).
Honest search supplies policy targets which Learner v2 distills into a stronger raw network. Deployment needs
no search. The stronger starting network may have less remaining search benefit than earlier checkpoints.

## Proposed decision

1. **Gate first:** 512 games per configuration, honest X/E and raw against frozen 49333, identical team
   rows/seeds and both seats. X uses `lam=0.5`, K=M=8 and W=16. Stop/report if the paired X-minus-raw
   score gain is below +0.08 or its 95% lower bound is not positive. E is diagnostic; incomplete gates do not pass.
2. **Policy target:** `pi_X = 0.5*x_N + 0.5*one_hot(E)` over the own candidates. Map it to the complete
   legal joint-action distribution. Distill joint distributions, not sampled actions/slot marginals.
   Search values remain diagnostic.
3. **First pilot:** offline policy KL plus ordinary outcome-value regression, initialized from 49333.
   Replace PPO/magnet policy losses in this pilot; league supplies opponents, not another loss.
   Learner v2 owns training/resume; a later PPO-plus-distillation arm is separately measured.
4. **Collection:** frozen teacher per round, learner-seat-only search on a deterministic 1/8 of eligible
   requests. Alternate the learner seat; the other seat stays raw/frozen. Start with 16,384 valid targets,
   then consider 125,000 after pilot success. Re-gate before each new teacher round.
5. **Bound the rescue:** a supervised, isolated teacher worker has a proposed 100 ms decision deadline,
   with at most 10 ms for rational rescue. Expiry plays raw, records the cause, and emits no teacher target.
   No approximate float targets in the pilot, silent fallback or altered certificate.
6. **Information boundary:** public-information Honest only, including D0023's belief and leave-one-team-out
   rules. No oracle data, privileged true hypotheses or true foe rows can enter target generation.
7. **Success:** fresh raw-network evaluation against 49333 and the fixed panel, ladder and pool-group
   breakdowns; require at least +0.03 head-to-head advantage with positive bootstrap evidence and no material
   panel/group regression. Equal inference compute; account for teacher training cost separately.
8. **Resources/privacy:** use capped daytime CPU collection and exclusive nighttime GPU training.
   Do not contend with measured Learner v2 A/B windows. All targets, checkpoints and runs remain private;
   later docs PRs contain aggregates only. The 30 ms/search and rescue tail are planning inputs, not new measurements.

## Approval and consequences

The owner relays the spec's contract to Learner v2 for confirmation of the joint-policy API, schema/masks,
loss/resume contract and resource windows, then approves the implementation plan/budgets. No new C rules or
battle-hot-path allocation are proposed. Deeper trees, search-value targets, both-seat teachers and architecture
changes remain separate decisions. Oracle benchmarks stay labeled and separate.
