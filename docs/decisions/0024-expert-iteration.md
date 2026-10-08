# 0024 — Phased expert iteration with the honest X teacher

Status: **revised proposal for owner approval, 2026-10-08**. Stage 3 is approved in principle, not as an implementation plan. This docs PR authorizes no feature code or run. The [specification](../superpowers/specs/2026-10-05-m12-expert-iteration-design.md) replaces the earlier outcome-MSE pilot, per-step quota and wall-time policy fallback. Follows [0017](0017-learner-v2.md), [0022](0022-search-support.md), [0023](0023-determinization-public-state.md), [honest arena #236](https://github.com/chrismaghuhn/duoforge/pull/236) and [luck probe #239](https://github.com/chrismaghuhn/duoforge/pull/239).

## Goal

Start from frozen `many-c4e96e6/params-49333` (reported Elo 768 in the original brief). Honest X, lambda=0.5, supplies joint-policy targets; Learner v2 distills them into a stronger raw network. No deployment search or opening book.

## Separate phases, plans and owner gates

| Phase | Scope | Stop rule |
|---|---|---|
| P0 | X/raw gate on 49333 and CPU/GPU profiling, no feature code | Point gain <+0.08, lower 95% bound <=0, incomplete gate/resource cap |
| P1 | Current path, random keyed 1/8, distillation, existing GAE value loss, continuation control, deterministic rescue | Drift, work fallbacks >1%, or failure to beat continuation |
| P2 | Fixed-shape lockstep GPU batching only | Byte-identity regression/no throughput benefit |
| P3 | Regret/disagreement routing vs random at matched total compute | Group-dependent routing/no quality-efficiency improvement |
| P4 | Restricted game/double oracle plus full-table audit | Certificate/policy mismatch/no net leaves saved |
| P5 | Capped training-split hindsight, separate PPO+distill arm, scale | Leak/held-out or strength regression/budget breach |

P1 retains the discounted head's GAE semantics; no final-outcome MSE on that head. A separate undiscounted head remains an architecture proposal requiring approval, not a feature implemented by #239. The teacher's foe model is always the frozen teacher net, including league games; the actual opponent model is isolated.

Regret routing uses independent decision-key streams for the raw action and budget, never a per-step floor. Pin parallel-game count. Include the sampled raw action by displacing the lowest candidate while keeping K=4/8, and audit displacement. P3 weights only full honest labels by full-teacher regret. Hindsight is off in the pilot and never enters teacher inputs/targets or validation. Exploiter populations are out of scope.

Bound rescue work by pivots, operations and bit size. Exhaustion plays raw, is counted, and emits no label. A wall-clock watchdog aborts an incomplete run; PC load must not choose trajectories. Public reconstruction refusals are a separate counter. No silent fallback, weakened certificate, timeout flushing or asynchronous batching.

Success must beat a matched-budget continuation from 49333, not just frozen 49333. Inconclusive groups block promotion. Local resources first: **AWS only after the engine covers the meta** (owner, 2026-10-08), under a new approved budget.

## Ownership

The owner relays the contract to Learner v2. Each phase needs its own reviewed plan and resource/promotion decision; passing one authorizes no next phase. M12.x (#240) is separately measured/gated, not silently added to P0/P1. No C rules or battle-hot-path allocations proposed. Generated rows, worlds/tables, weights and runs stay private; reports carry aggregates only.
