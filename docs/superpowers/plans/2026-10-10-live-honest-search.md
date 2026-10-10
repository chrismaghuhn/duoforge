# Live honest search: implementation plan (option A, 2026-10-10)

The owner chose option A after P1 and approved this spec (via HauptSession, 2026-10-10): the live bot plays TURN, REPLACEMENT and PIVOT decisions with honest search X. Team preview stays raw.

**Owner decisions:**
- **(i) Failure classes:**
  - (a) Named public refusals fall back to raw for that decision. Each fallback is logged and counted per cause.
  - (b) Unexpected errors also play that decision raw, mark the game dirty and play the rest of it raw. The session then takes no new challenge until reviewed.
- **(ii) The live-path arena gate:** 400 games in 200 swapped-seat pairs from the 652-team pool. A PASS needs all of:
  - lower 95% bound > 0.50;
  - 0 crashes, 0 class (b) errors, 0 timer losses;
  - class (a) fallbacks ≤ 5% of decisions, deadline fallbacks ≤ 1%;
  - p99 latency within the budget.
- **(iii) A foe species without a spread prior:** raw, counted. The live spread table comes from the registry's playable PP_ pastes (838), pinned by its hash. The 79 SPREAD_SOURCES stay for P1 and the evaluation. Replay aggregates stay private and unused.

Ladder games run only after the owner's go.

## Global constraints

- **No rules in Python.** The record is built in C from public facts; the tracker supplies what a counting player knows (0023 §4).
- **No silent fallback.** Every raw decision has a named, counted cause.
- **No new public value** without HauptSession's assignment from M12's reserve.
- **Determinism:** the builder is a pure function of its inputs.
- **Privacy:** live logs and arena results stay private (AGENTS.md).

## Task 1: `duoforge_public_from_parts` (C) and its equivalence test

The core: a public record (`duoforge_public_state`) built from the player's knowledge instead of a true battle.
- **Approach:** build a `duoforge_battle` from the parts, then run the existing record path (`dfi_view_encode`). Its refusals and masks stay one code path.
- **Placeholders:** fields the player cannot know are filled with placeholders. Every one of them is masked in the record: RNG, sleep and confusion counters, the foe's charge target, bench order, exact HP, stats, stat points and PP.
- **Placeholder check:** a test varies each placeholder and asserts the same record bytes.

**Parts the builder takes**, on top of the observation and its extension (byte-exact from the tracker today):
- **Both team sheets:**
  - the own sheet: exact;
  - the foe's open sheet from `|showteam|`: species, moves, items, abilities, nature, gender, level. Its stat points are a placeholder.
- **Own exact state from the request:** HP, stats and PP per member.
- **Bookkeeping that the tracker counts from the public history.** By encoding block:
  - **Battle header:**
    - `next_activation_id`;
    - turn, `boundary_kind`, `request_mask`, `request_epoch`, result.
  - **Queue:**
    - TURN: empty.
    - PIVOT: only the residual record (a PIVOT with a move left is refused).
    - Any other queue is refused.
  - **Per side:**
    - `brought_mask`, `brought_order`;
    - `requested_slots`, `mega_used`, `sealed` and the sealed commands;
    - `seen_mask`;
    - reflect, light screen and tailwind turns.
  - **Per position:**
    - `activation`, `stages`;
    - flags without the silent flinch;
    - `stall_level`, `stall_turns`, `charge_turns`;
    - `locked_move`;
    - `move_actions`, `switch_flag`.
  - **Knowledge, both sides:** per opposing member `hp_percent`, `hp_flag`, `revealed`, `moves_used`.
  - **Per member:**
    - status, `item_consumed`, `is_mega`;
    - the foe's displayed HP percent from the observation.
  - **POOL tail, field:** `gravity_turns`.
  - **POOL tail, per side:** `wide_guard`, `aurora_veil_turns`, the hazards and `hazard_order`, `quick_guard`.
  - **POOL tail, per position:**
    - `last_move`, `encore_slot`, `encore_turns`, `throat_chop_turns`, `heal_block_turns`, `perish`;
    - `taunt_turns`, `disable_slot`, `disable_turns`, `imprison`, `must_recharge`;
    - the trap fields, `leech_seed_source`, `yawn_turns`, `focus_energy`, the stockpile fields, `charge`, `glaive_rush`;
    - the presence of a Substitute (refused anyway);
    - `protect_kind`, `move_result`, `single_turn`, `hits_taken`, `ability_state`, `lock_turns` (refused while the lockedmove proxy holds).
  - **POOL tail, per member:** `ability_now`, `forme_now`, `soak_type`, `item_now`, `toxic_stage`, `type2`, flags.
  - **POOL tail, rev 5 block:** as `DFI_ENC_TAIL5_*`.

**Equivalence test (the gate of this task), `duoforge.view.from_parts`:**
- for engine-played games of every POOL kind, at every state where `duoforge_battle_public` succeeds, and for both players;
- the parts are derived the way the tracker derives them (observation, extension, request, counted bookkeeping);
- the builder's record must be byte-identical to `duoforge_battle_public`;
- and where `public` refuses, the builder must refuse with the same status.

**Tracker side (HauptSession):** keep the bookkeeping above from the protocol lines, then extend `test_view_equals_duoforge` to the parts.

## Task 2: `Honest.decide_records`

Search over records instead of a batch: `decide_records(records, previews, observations, keys)`. It is a refactor with the same logic and an identity test against `decide` on engine batches.

## Task 3: the live spread table

The live belief's sources are the registry's playable PP_ pastes, pinned by the table hash. A foe species missing from it gets the refusal cause "no spread prior" (raw, counted). `data/teams/README.md` documents the live list beside the pinned 79.

## Task 4: latency

Single-game latency per boundary kind: p50, p95 and p99, plus the warm-up at startup.
- **Machine:** this one, exclusive under the machine lock (`--exclusive`).
- **Runtime:** JAX on the CPU against NumPy `forward` for the value and policy calls; the faster one is chosen.
- **Budget:** the deadline is min(2 s, 10% of the remaining turn time), with the timer read from `|inactive|`.

## Task 5: live wiring

A play mode `--search honest` in `python -m duoforge_live`:
- fallbacks (a) and (b) with their counters;
- the deadline;
- the dirty-game stop;
- a per-game summary in the private log.

## Task 6: the live-path arena

- **Setup:** a local pinned Showdown server, search mode against raw mode, with the predeclared numbers above.
- **Report:** aggregates only.
- **Ladder:** only after the owner's go.
