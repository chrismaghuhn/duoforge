# P1 honest teacher (C3)

`expert.py` labels admitted learner roots for the [P1 pilot](../../docs/superpowers/plans/2026-10-08-stage3-p1-pilot.md). It runs the existing honest search (`honest.py`): its foe model is its own frozen network, worlds come from public facts only (C builds and checks them), and no privileged call or true-root encoding is used. It contains no battle rules. The collection loop (lockstep games, the student's keyed raw draw, opponent moves, rewards, truncation, shards, collection resume) belongs to Learner v2. This module supplies the teacher side of it.

## Collector contract, per logical tick

1. Query the roots, then call `observe(search, roots, envs, seats)` for **every** learner request of the tick: raw, forced, preview or labeled. It records the public team-preview and turn-start records that later reconstructions need. `label_decision` refuses a request that was not observed. It also refuses a game whose team-preview request was never observed: that is a collector error, not a public refusal (a preview whose public record was refused is still observed and becomes a counted public refusal later).
2. The learner seat of a game is `learner_seat(game_id)` (game id mod 2). `label_decision` and `teacher_row` refuse keys of the other seat or of games outside the manifest.
3. Assemble the complete tick's eligible selected roots (`expert_data.is_selected`) as `AdmissionRequest`s and call `admit_tick` **before** any teacher work.
4. For each admitted root, call `label_decision(search, roots, env=, seat=, key=, raw_action=, raw_logp=, last_step=, config=, manifest=)`. `raw_action` and `raw_logp` are the student's pre-drawn raw action and its full-legal log-probability.
   - `TARGET`: the action is drawn from X over the candidates. These are the top K plus the raw action, which displaces the lowest-ranked candidate if it is absent. The draw uses the key's X word. `behavior_logp` is the exact log-probability of that play distribution (X without sub-floor mass, renormalized), and the target stores the same distribution.
   - `PUBLIC_REFUSAL` (no supported public reconstruction, e.g. `public:visible_sleep`) and `WORK_EXHAUSTED` (`work:<cap>`): the raw action executes with `raw_logp`, and the cause is named.
   - Any other failure raises.
5. For every other requested learner root, call `raw_decision(status, raw_action, raw_logp, legal_count=)`. Status is `UNSELECTED`, `CAP_RAW` (selected but without a ticket) or `FORCED` (one legal action, logp 0). It touches no world, network or solver.
   **Per tick (stage 3 P2):** `label_tick(search, roots, [TickRoot(env, seat, key, raw_action, raw_logp), ...], last_step=, config=, manifest=)` labels all admitted roots of the tick at once. It returns results in input order and reads the encoded rows and public records once. Each root's worlds are built, and its primary and K+1 audit are prepared, before the next root; all open leaves share one deduplicated table of 1024-row value calls. Per-root bytes equal `label_decision`'s, given value bits independent of row position, neighbours and padding at that capacity. `rowprobe` showed this for params-49333 on the owner's CPU and GPU; re-probe for another checkpoint or machine. Every root is checked before any worlds are built. A tick above `ticks.MAX_ROWS` unique rows (roughly 500 labeled roots) raises `ValueError`, and any other failure of one root stops the whole tick. `label_decision` stays the per-root reference path.
6. `commit_tick` with each root's status; build rows with `teacher_row(decision | None, StepData, manifest)`. Waiting steps pass `None` and become `UNREQUESTED`. Reward, done, collector value and bootstrap are kept exactly as the collector gives them, and the row is checked by `validate_row`.

Rows: one learner seat per game; a row on every lockstep step (`logical_tick` gapless from the team-preview row at 0); one episode per (game, seat), with `done` at most on the last row. A truncated episode ends with `done=False` and its bootstrap.

## Keys, work and audit

- Key words (`expert_data.selection_word`, manifest seed) are domain-separated:
  - world: belief sampling and leaf keys;
  - X: the label draw;
  - audit: the 1% K+1 audit selection.
- Each primary decision has its own `matrix.WorkLedger(config.budget)`. Exhaustion is never retried or rescued.
- The K+1 audit (`audit word < floor(2**64/100)`) re-solves the same worlds with the next candidate added and the raw action kept. It runs under its own ledger with identical caps and reports action/value/certificate changes. It never replaces the label. An exhausted audit is reported as `exhausted:<cap>`.
- Audit work belongs to generation but not to the primary fallback numerator.
- Build `TeacherConfig.from_manifest(manifest, ...)`. It must equal the manifest's key seed, K, M, W, lambda and capacity (P1 pins 8, 8, 16, 0.5 and 1024). It must also match the search: those sizes, rule X and the search's own belief/leaf seed (`search_seed`). Only the budget, audit rate and search seed may be overridden. `manifest.belief_hash` is the sha256 of the search's spread table (`search.table_info`); production uses the pinned `honest.SPREAD_SOURCES`.
- Each label re-queries the encoded rows and public records of all environments: measured at 512 environments, about 3 ms per label (about 6% of P0's ~50 ms). This is a P2 performance item, not a correctness one.

## Resume and determinism

`teacher_checkpoint(search, roots, cursor, config, manifest)` stores every recorded public history together with the label cursor. It is bound to the manifest, the teacher configuration (search seed included), the key version, and the search's identity: a SHA-256 over the network weights, the spread-table hash and the per-environment exclusions. `restore_teacher` fills a fresh search for the restored roots and returns the cursor, pending reservations included. It refuses other manifests, configurations, weights, spread tables, exclusions, key or checkpoint versions, environment counts, episodes and record sizes, as well as partial or altered checkpoints. `decision_bytes` gives canonical decision bytes. Tests run at the P1 sizes: 1024 primary leaves and 1152 audit leaves, the audit in two expand chunks of capacity 1024. They compare decision bytes per game id uninterrupted, with games permuted across environment slots and call order, regrouped within one tick, resumed and under clock jumps. There is no GPU or cross-capacity trajectory claim.

## Differences from the plan's signature sketch

- `label_decision` takes `raw_logp` (non-target likelihoods are the student's), `last_step` (the table's cut-off rule) and the `manifest` it labels for.
- The plan's `admitted` flag is replaced by the separate `raw_decision`, so rows without a search never touch the teacher.
- `observe` is new; it is needed because only the teacher's own history reconstructs worlds.
- `TeacherDecision` also carries `raw_action` and `cause`.

Tests use a deterministic foe-sensitive NumPy network and reference setups, with no trained weights or real data.
