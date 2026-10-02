# 0019 - M11: training rows from human replays

Status: **accepted** (owner, 2026-10-02: design in chat, spec reviewed). Design: `docs/superpowers/specs/2026-10-02-m11-replay-data-design.md`; plan: `docs/superpowers/plans/2026-10-02-m11-replay-data.md`. Builds on 0007 (the player view), 0013 and 0014 (the Python adapter and the learner), 0015 (POOL), 0016 (the live adapter and its tracker), 0017 (Learner v2, reserved) and 0018 (the POOL view extension).

## Decisions

1. **The live tracker in a spectator mode** turns open-sheet Reg M-C replays into rows: per player and decision, DuoForge's observation, superset options and a label. Behavior cloning on them gives Learner v2 a human prior; PPO with a KL term toward it follows; offline RL later.
2. **A perspective stops at the first line the view cannot represent**, and the decisions after it are counted, never approximated. Every line is classified first (`duoforge_live.lines`): room, fold, a feature of 0018 (folded only when the library's `supported` bit is set), or unknown. Single-turn features (Rage Powder, Wide Guard, Quick Guard) stop only at a PIVOT of their perspective in their turn. The live adapter forfeits on the same lines instead of folding them wrongly.
3. **The own side as the public sees it, plus hindsight and a prior**: HP as the public percentage, PP from the uses seen, the picks from the members seen (a perspective with fewer than four keeps only its team selection row), stat points from a per-set prior of public pastes (levels 0 to 4, stored per row), stats from the pinned Showdown (`ps_stats.js`). Python computes no stat.
4. **Labels are option sets** (a 32-bit mask per slot list, 360 bits at team selection) with a reason per slot; the BC loss is -log P(label set). A stop also cuts the labels: an action after the stop line is UNKNOWN.
5. **Superset options** through the live adapter's `slot_options` on a synthetic request; exact sets would need an engine "state from observation" entry point (owner's OK, not now).
6. **Data stays local.** The dataset states no license: no replay, derived data, prior file or checkpoint trained on it goes into the repository; the writer refuses such an output path; fixtures are our own reference battles replayed by the pinned Showdown.
7. **Interfaces agreed with Learner v2**: rows hold raw `OBSERVATION` and `FACTORED_DOMAIN` records; the BC PR (after Learner v2) uses `policy.make(...).apply`, intersects the label set with the model's mask and adds `--init CKPT`.

## Evidence

`duoforge.python.replay` replays every committed battle (closure, Team C, pool) as the pinned Showdown's spectator log and checks, for both sides: the decision points equal DuoForge's; the observation equals DuoForge's except the documented fields, which equal their sources; the superset contains DuoForge's options; the true choice is in every label set. `duoforge.python.replay_unit` checks the line classes, the prior, the labels, a whole game with injected stop lines, and the writer's determinism and refusals.
