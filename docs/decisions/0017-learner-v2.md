# 0017 — Learner v2 for many teams

Status: owner decisions 2026-10-02. The owner approved the specification `docs/superpowers/specs/2026-10-02-learner-v2-design.md` ("sieht gut aus"); the plan `docs/superpowers/plans/2026-10-02-learner-v2.md` awaits his review. Follows decision 0014 (learner pipeline) and works with decision 0015 (content expansion, POOL).

## 1. Context

**Why.** The night run of 2026-10-02 (`docs/learning/2026-10-02-night/`) plateaued after about 70 minutes on two teams. The owner's goal for the next training run is at least 6 to 12 real Reg M-C tournament teams, and later more than 100.

**What stood in the way:**
- The engine could set up only the four reference pairings from Python.
- Model v1 does not see which species or moves are on the field. The ids arrive as scalars of about 10⁻⁴, and its option scores know only move slots.
- A run could not resume.

## 2. Decisions

1. **Model v2 with embeddings** is part of this work: species, moves, items, abilities and natures. It is built equivariant to roster order and move order, and its size is configurable (presets of about 0.35, 2 and 8 million parameters). It is measured against v1.
2. **The A/B/C stage** must show the pipeline and measurements. No learning threshold is a merge condition.
3. **Approach A.** The synchronous loop of decision 0014 is extended. Asynchronous actors come only when measurements show the need.
4. **Teams** come from the shared registry `data/teams/` (expansion A7). The library checks every team at setup. Names map to ids through one data query API for names and legality, built by the expansion track after P1.
5. **Self-play** covers all N² ordered pairings, with a weight per team. A league plays against past snapshots, and a slot changes its opponent only at an episode boundary. The entropy schedule runs over decisions. The run state is atomic, and a run resumes, also with more teams and with checkpoints widened by column name.
6. **Encoder fix.** Checkpoints carry `"encoder"`: 1 before the `present` fix, 2 after it. Every loader passes `legacy_present = config.get("encoder", 1) < 2` to the encoder, so v1 checkpoints stay exact.
7. **Hardware.** The first runs go local at night with 8 threads. A rented machine comes only for long or parallel runs; resume is required anyway.

The details, the parts and the order are in the specification. The tasks are in the plan.
