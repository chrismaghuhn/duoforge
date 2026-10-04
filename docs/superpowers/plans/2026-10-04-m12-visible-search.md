# M12 Visible-Information Search Implementation Plan

> **For agentic workers:** steps use checkbox (`- [ ]`) syntax for tracking. Work task by task, one PR at a time, in the order below.

**Goal:** the search of the specification `docs/superpowers/specs/2026-10-04-m12-visible-search-design.md` (S below), on the engine API of decision 0023 (D0023). Section numbers such as S4.3 refer to the spec.
- **The engine** builds worlds from a player's public record and a hypothesis.
- **The search** samples W worlds, solves one strategy for all of them, and plays N, E or X.
- **The measurement** puts honest, oracle and raw side by side against the panel.

**Architecture:**
- **C:**
  - a new header `include/duoforge/duoforge_view.h` and source `src/state/view.c` for the records and the single calls;
  - the batch forms in `src/batch/batch.c`;
  - the queue mask in `src/state/view.c`.
- **Python:**
  - bindings in `python/duoforge`;
  - the belief in `python/duoforge_search/belief.py` (NumPy);
  - the Bayesian rule in `python/duoforge_search/matrix.py` (NumPy);
  - the honest search in `python/duoforge_search/honest.py` (JAX).

**Status:** the owner approved the spec with its three added points on 2026-10-04 ("Implementierung starten"). This plan waits for the owner's OK.

## Global Constraints

These are stage 1's (plan `2026-10-03-m12-search-stage1.md`, Global Constraints), and in addition:
- **No rule in Python.** Stats, HP buckets, counter posteriors, charging targets, legality and the queue mask come from C. The only checks in Python are comparisons of recorded indices (S5.3).
- **No float in the engine.** Uniforms are `uint64_t` words mapped with 64×64→128-bit products (`dfi_mul_hi64`, portable, with an MSVC path). `float` stays in `encode.c` (D0022).
- **No allocation** in any call of D0023. The records are fixed-size structs the caller owns.
- **Failure atomicity:** on any non-OK status nothing is written (`duoforge.h`).
- **Versions:** the HauptSession assigns a MINOR bump per C PR. A bump edits `duoforge.h`, `_lib.py` `EXPECTED_VERSION`, `test_lib.py` and `test_api_atomicity.c`.
- **Runs:** in the daytime only, on the owner's machine. Checkpoints and run directories stay private. No heavy job and no GPU from 21:30 to 06:00.
- **Usage:** no review fan-out. Each C PR gets at most one review agent, and only when the owner asks for it.

## What the state holds, and where it goes

From `src/state/battle_internal.h`; this is the core of Task 1.

| State field | Public record | Hypothesis | Note |
|---|---|---|---|
| header: fingerprint, `boundary_kind`, `request_mask`, `request_epoch`, `turn`, `result` | yes | | |
| `rng` | | | left zero; leaves reseed (D0022) |
| `next_activation_id`, positions' `activation_id` | yes | | every switch-in is public, so the exact ids are facts |
| field: weather, terrain, Trick Room and their turns; side screens and Tailwind | yes | | as in the observation |
| own members, all fields | yes | | own `status_counter` (sleep, freeze) excluded, see below |
| foe member: species, sheet, `is_mega`, `item_consumed`, `ability`, status | yes | | sheet and public facts |
| foe member: `stat_points` | | spreads | `stats` and `hp_max` recomputed (`formulas.c`) |
| foe member: `hp` | display + flag (knowledge) | HP word | never-seen member: full HP |
| foe member: move `pp` | uses seen (knowledge) | | PP = max − uses (closure); a POOL state with Pressure is `E_UNSUPPORTED` |
| `status_counter` (sleep, both sides) | turns asleep so far | counter word | posterior of `sample([2, 3, 3])` |
| `status_counter` (freeze) | turns frozen so far | | Champions freeze is fixed in length, so it is derived |
| `confusion_turns` (both sides) | turns confused so far | counter word | posterior of `random(2, 6)` |
| tail `trap_turns` (both sides) | turns trapped so far, `trap_band`, `trap_source`, `trap_move` | counter word | 5–6, or 8 with Grip Claw (public item) |
| tail `lock_turns` (both sides) | turns locked so far | counter word | 2–3 |
| `charge_turns`, `locked_move` | yes | | public: the charge message |
| `locked_target` while the foe charges | | target word | the own target is in the observation |
| tail Encore, Taunt, Heal Block, Disable, Throat Chop, Yawn, Perish | turns since start, plus the **duration variant** bit | | the initial length depends on the turn (Encore 3 or 4, Taunt 3 or 4, Heal Block 5 or 2). The variant is a public fact; the engine maps elapsed to remaining |
| tail `toxic_stage` | yes | | public: turns badly poisoned |
| other tail fields (Substitute HP aside) | yes | | public facts; Substitute HP is recomputed from the world's `hp_max` |
| `stall_level`, `stall_turns`, `move_actions`, flags, stages | yes | | |
| `brought_order` (foe), `brought_mask` (foe) | leads, seen mask | pick order | |
| `sides[foe].knowledge`, `sides[foe].seen_mask` | yes | | what the foe knows of the player |
| `sides[me].knowledge`, `seen_mask` | yes | | |
| `queue`, `queue_len` at a PIVOT | own records | foe MOVE records (move slot, target) | other kinds (RESIDUAL, SWITCH_IN) follow from the public state |
| `sealed_cmds`, `sealed` | own | foe | |

**The duration variant** refines S4.3's "turns since it started". The engine stores remaining turns, and the starting length varies, so the record needs one public bit per counter (for example, whether the target had moved in the turn Encore started). This keeps "facts, not derivations" and is the only deviation from the spec. D0023 and S4.3 are amended in Task 1's PR.

## PRs and order

| PR | Tasks | Branch | Needs |
|---|---|---|---|
| Docs | this plan; approval recorded in S and D0023 | `chris/m12-visible-plan` | — |
| A (C) | 1–4 | `chris/m12-view` | Docs |
| B (C) | 5–6 | `chris/m12-view-batch` | A |
| C (Python, NumPy) | 7 | `chris/m12-view-bindings` | B |
| D (NumPy) | 8–9 | `chris/m12-belief` | — (may start at once) |
| E (JAX) | 10–12 | `chris/m12-honest` | C, D |
| F (measurement) | 13 | — | E; owner's machine |

Not in this plan: the live tracker's record (stage 2) and the stage 3 training loop (their own plans).

---

### Task 1: The records

**Files:** create `include/duoforge/duoforge_view.h`, `src/state/view.c` and `tests/test_view_records.c`; modify `CMakeLists.txt` and `tests/CMakeLists.txt`.

- [ ] Define `duoforge_public_state` and `duoforge_hypothesis` as public, fixed-size, padding-free structs with `_Static_assert` sizes and a `revision` field. Fields follow the table above, with reserved bytes zero.
- [ ] Define the layout constants (`DUOFORGE_VIEW_REVISION`, the counter kinds, `DUOFORGE_VIEW_COUNTERS_MAX`) and the record validators `dfi_view_check` and `dfi_hypothesis_check` (`E_SCHEMA_MISMATCH`, `E_MALFORMED`, ranges).
- [ ] Test: sizes, zero-initialized records refused or accepted as specified, and every malformed field refused.
- [ ] Amend S4.3 and D0023 with the duration variant bit.
- [ ] Commit: "View: the public state and hypothesis records (D0023)".

### Task 2: `duoforge_battle_public` and `duoforge_battle_hypothesis`

- [ ] `public`: copy the public fields. Derive the elapsed counts and variant bits from the stored remaining turns and their starts. Refuse `E_UNSUPPORTED` from a documented list: Pressure PP under POOL, any tail feature without a support bit, and any hidden field the hypothesis does not model.
- [ ] `hypothesis` (privileged): the spreads; for each uniform, the middle word of the range that picks the true value; the pick order; the foe's queued MOVE records.
- [ ] `dfi_mul_hi64` and `dfi_pick(u, n)` and `dfi_pick_weighted(u, weights, n)` in `src/core`, with tests pinning the extremes u = 0 and u = 2^64 − 1.
- [ ] Info-safety test: sizes and statuses are equal for two states that differ only in hidden fields (built by editing a decoded state in the test).
- [ ] Commit.

### Task 3: `duoforge_battle_from_view`

- [ ] Build into a stack-local battle, then copy to `out` only on success.
  - Header, field and own side from the record.
  - Foe members from the sheet plus spreads: stats and `hp_max` by `formulas.c`, then HP from the word over the bucket (`knowledge.c`'s display function, inverted by enumeration over at most `hp_max` values), and PP from the uses.
  - Counters from their words over the posterior given elapsed and variant.
  - Substitute HP recomputed.
  - The queue: own records from the record, foe records from the hypothesis.
  - RNG zero.
- [ ] Refusals of S4.3. Finally `dfi_state_check`: a failure is `E_INVARIANT`.
- [ ] Commit.

### Task 4: The proofs, under every data kind

**Files:** `tests/test_view_roundtrip.c` (CTest `duoforge.view.roundtrip`, timeout 600).

- [ ] Random play with `duoforge_batch_play_random`-style stepping over every data kind (closure, Team C, both POOL kinds and the rest), both players, every boundary.
  - Round trip: `from_view(public(s, p), hypothesis(s, p))` equals `s` by `duoforge_battle_equal` with the RNG masked (compare the canonical bytes after zeroing the RNG field of both).
  - Tightness: 8 random valid hypotheses per state.
  - The own row: `duoforge_batch_query_encoded` rows equal across those worlds.
  - Refusal counts by reason are printed and pinned.
- [ ] TSan list, docs (ARCHITECTURE section on views), version bump from the HauptSession, PR A.

### Task 5: The batch forms

- [ ] `duoforge_batch_public` and `duoforge_batch_from_view` via `dfi_batch_each` and the leaf hook `dfi_batch_leaves`, with per-env statuses. Argument checks come before any env is touched.
- [ ] Test: equal to the single calls for 1, 2, 3, 4, 8 and 16 workers; no allocation (the allocation counter of `test_search_expand.c`).

### Task 6: `duoforge_public_queue_mask`

- [ ] Build the turn-start world from `turn_start` with a neutral hypothesis (legality is public; a state where it is not is `E_UNSUPPORTED`). Take the foe's factored domain and mark each legal pair whose public parts agree with the difference of the two records: switches and Mega Evolutions done, the moves used (knowledge `moves_used` deltas), and which positions have acted. Targets are not compared.
- [ ] Test: at every PIVOT of random play the foe's chosen pair is marked. Refusals: a view not at a PIVOT, or a mismatched `turn_start`.
- [ ] TSan, version, PR B.

### Task 7: Bindings

**Files:** `python/duoforge/_lib.py`, `python/duoforge/view.py`, `python/duoforge/batch.py`, `python/tests/test_view.py` (registered NumPy-only).

- [ ] NumPy structured dtypes mirroring both records, from `_layout` (generated constants, no hand-written offsets).
- [ ] `Batch.public(players)`, `Batch.from_view(views, hypotheses, count)`, `duoforge.queue_mask(ctx, turn_start, view)`, and the privileged `duoforge.hypothesis(...)` in a module named `privileged`.
- [ ] Test: Python round trip over a random-play batch; guards like `Batch.expand`'s.
- [ ] PR C.

### Task 8: The spread table and `Belief`

**Files:** `python/duoforge_search/belief.py`, `python/tests/test_belief.py` (NumPy).

- [ ] Parse spreads from the `PP_` teams and A, B and C through `duoforge.teams.parse`; skip sets without stat points. Build keys with backoff (S5.1); leave one team out by pool index. Write the SHA-256 of the table and its counts.
- [ ] World words `x_w,k` (S5.2) in `duoforge_search.seeds`, with fixed k ranges: spreads 1–6, HP 7–12, bench 13, counters 14–37, targets 38–41, PIVOT 42.
- [ ] `Belief.sample(view, history, n, seed, key, exclude_team)` returns hypotheses and weights of 1/W. The bench and the queue are filled later by the search (Task 10).
- [ ] Tests: determinism, backoff levels, whole spreads, exclusion, purity in (seed, key, w).

### Task 9: The Bayesian rule

**Files:** `python/duoforge_search/matrix.py`, `test_search_numpy.py`.

- [ ] `solve_bayes(tables, weights)` builds the LP of S6.3 for the existing simplex (Bland's rule, the float64 re-solve, the exact rescue) and returns x, the per-world duals and the certificate. `expected_values` gains per-world q. `mix(x, e, lam)`.
- [ ] Tests: W = 1 equals `matrix.solve`; certificates on random tables up to 16 × 16 × 16; the constructed game of S12.
- [ ] PR D.

### Task 10: Worlds in the lookahead

**Files:** `python/duoforge_search/honest.py`, `test_search.py`.

- [ ] Per decision:
  1. the public record (`Batch.public`), keeping the team-preview and turn-start records per env;
  2. hypotheses (`Belief.sample`);
  3. the bench: preview worlds, the foe's team-head row, drop disagreeing tuples, draw;
  4. at a PIVOT, the queue: turn-start worlds, the foe's row, the queue mask, draw, read the commands from the domain;
  5. `Batch.from_view` into the worlds batch;
  6. root rows;
  7. `Batch.expand` with world w using sample w;
  8. tables A_w.
- [ ] Records add W, the table SHA-256, the drops and the unreconstructible reasons.

### Task 11: The rules N, E and X, and decision kinds

- [ ] N by `solve_bayes`, E by the per-world q, X by the mix (λ = ½); draws by the play uniform. Decision kinds as in S6.7.
- [ ] Tests: K = 1 plays the raw network; the end-to-end information-safety test (two roots that differ only in hidden values, built with `from_view`, give the same decision); a pinned decision on Teams A, B and C (integers exact, table within tolerance).

### Task 12: Arena

- [ ] `arena.py` gains `--search honest|oracle`, agent `X`, `--lam`, leave-one-team-out by pool index, and the cost split of S9. Conditions add W, λ and the table SHA-256.
- [ ] PR E.

### Task 13: The measurement (owner's machine, daytime)

- [ ] H, O and R × N, E and X against BC, 3600, 11000, scripted and R, with 2,048 games, 8 × 8 and W = S = 16. Report the oracle bias (paired bootstrap), the honest gain, the cost per decision and the counts. The Learner session writes the report; scores and hashes only.
