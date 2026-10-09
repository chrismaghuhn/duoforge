# 0025 - Public values for Double Shock and Revival Blessing

Status: **accepted** (owner, 2026-10-09: "alles freigegeben" for the API items of the coverage push). The values below are the lead's proposal for those two moves, written before any code and revised after HauptSession's review of the Python side. Drafted by the expansion lead (build session A). Builds on:
- 0005 (requests and choices);
- 0006 (boundaries);
- 0007 (information boundary);
- 0015 (POOL tables, tail rev 4 in section 7);
- 0018 (view extension);
- 0021 (encoder in C);
- 0023 (determinization).

## Problem

The replay coverage of 2026-10-09 (Reg M-C, both sides playable) puts two moves of Pawmot near the top of the blockers: Double Shock is in 1,707 games and Revival Blessing in 1,245. Neither can be expressed with today's public values.

- Double Shock leaves its user with a typeless type slot (`???`). `DUOFORGE_EVENT_TYPE_CHANGE` carries exactly one type, and 0 is Bug.
- Revival Blessing asks its player to pick a fainted party member, which then comes back at half HP. No slot command picks a fainted member, and no event names a benched Pokemon.

## Decisions: Double Shock

1. **The pin** (data/moves.ts doubleshock; the Champions override adds the punch flag):
   - `onTryMove` fails unless the user has the Electric type now. That prints `-fail|USER|move: Double Shock` with `[still]`, and PP is spent.
   - After a hit, `self.onHit` runs `setType` with Electric replaced by `???`. It then prints `-start|USER|typechange|???/Fighting|[from] move: Double Shock`.
   - `???` counts as no type for effectiveness and STAB. An empty type list becomes Normal in sim/pokemon.ts getTypes (2143), but `???/Fighting` is not empty.
   - Switching out, fainting and Mega Evolution reset the types, and Soak overwrites them.
2. **The state is internal and needs no new field.**
   - The tail's `soak_type` (the first type slot override) may now hold `DFI_TAIL_TYPE2_TYPELESS` (255): "slot 1 is `???`".
   - The species' second type is held in `type2`.
   - battle_internal.h (lines 251 and 317) documents 255 as a `type2` value. That stays, and the comment on `soak_type` is extended the same way.
   - The invariant allows 255 in `soak_type` only together with a nonzero `type2`.
   - Every `dfi_types_of` caller is audited for a typeless first slot.
   - The only legal user in the pool, Pawmot, is Electric/Fighting. Any other result shape (Electric as the second type, a pure Electric user, Electric after Soak) returns `DUOFORGE_E_UNSUPPORTED` until a recorded battle covers it.
   - A test round-trips a state with `soak_type` = 255 through the codec, byte for byte.
3. **New public constant `DUOFORGE_TYPE_NONE` = 255u.** It is used only in the `detail` of `DUOFORGE_EVENT_TYPE_CHANGE`, for the `???` slot.
4. **`DUOFORGE_EVENT_TYPE_CHANGE.amount` gets a documented meaning:** the second type id + 1, with 0 meaning one type. It is additive:
   - Soak keeps `detail` Water and `amount` 0.
   - Double Shock gives `detail` `DUOFORGE_TYPE_NONE` and `amount` Fighting + 1, with cause MOVE and id2 Double Shock.
5. **The view.**
   - src/state/observation.c (373-376) copies `soak_type` into `type_now[0]` as it is. It must map 255 to `type_now` = {0, `type2` + 1}.
   - While `TYPE_CHANGED` is set, `type_now` is authoritative and 0 in a slot means "no type there". This overrides 0018 §14.5 for that case.
   - Without the mapping, both encoders refuse the value and every Pawmot game would fail.

## Decisions: Revival Blessing

6. **The pin** (data/moves.ts revivalblessing; sim/battle.ts 2781-2797 and 2878-2900; sim/side.ts 925-985; sim/pokemon.ts 1183):
   - **Failure:** `onTryHit` fails when the user's side has no fainted Pokemon.
   - **Request:** the move sets the slot condition `revivalblessing` and `selfSwitch`. The user's side then gets a switch request in which that slot (`reviving: true`) must name a fainted party member. The request is made even when the side has no living reserve (battle.ts 2882-2891).
   - **The `revivalblessing` action:**
     - adds 1 to pokemonLeft;
     - clears fainted and status;
     - sets the HP to maxhp / 2 through sethp;
     - prints `-heal|pN: NAME|HP|[from] move: Revival Blessing`, with no position letter for a benched Pokemon. The HP is split, as every heal line is: exact for the owner, a percentage for the foe.
   - **Instaswitch:** if the chosen member's position is below `active.length` (it fainted in an active slot, this turn or an earlier one, and was never replaced), it is switched straight back in. The `|switch|` line has no `[from]` (battle.ts 2783-2789).
   - PP 1, no PP boosts.
7. **The boundary is the existing `DUOFORGE_BOUNDARY_PIVOT`, with no new boundary kind.**
   - The user's side is requested, with `slot_mask` set to the user's position.
   - The foe's side is not requested at that boundary. Its observation shows `requested` 0 and `slot_mask` 0, as for any pivot of the other side.
8. **New public slot kind `DUOFORGE_SLOT_REVIVE` = 4u**, with `reserve` = the roster index of the fainted member.
   - The slot's candidates are exactly the brought, fainted members other than the user, one each, in roster order.
   - No MOVE, SWITCH or PASS is offered in that slot.
   - The factored domain lists them in the same way.
   - A REVIVE command outside such a request is not in the domain (`DUOFORGE_E_INVALID_ARGUMENT`).
9. **New public event `DUOFORGE_EVENT_REVIVE` = 43u**, for the `-heal` of a revived member.
   - **Fields:**
     - `position` = the user's flat position;
     - `id` = the revived member's roster index;
     - cause MOVE with `id2` = Revival Blessing.
   - **The HP goes in `hp`, `hp_max`, `hp_kind` and `hp_flag`, as for HEAL and SWITCH:** `DUOFORGE_HP_EXACT` for the owner's events and `DUOFORGE_HP_PERCENT` for the foe's, matching the split line. The exact HP would reveal the foe's hidden max HP (0007), so `amount` stays 0.
   - **The position:** the user's position is not in the `-heal` line. The converter takes it from the preceding `move|USER|Revival Blessing` line, and tools/reference/trace_to_c.py documents that.
   - `DUOFORGE_EVENT_HEAL` stays unchanged, because it needs a position, and a benched member has none.
10. **The instaswitch reuses `DUOFORGE_EVENT_SWITCH`**, with cause MOVE and `id2` Revival Blessing, together with the switch-in effects of the existing path.
    - The engine sets the cause; the line has no `[from]`, so consumers infer it from the REVIVE event just before.
    - A recorded battle covers an ally that fainted in an earlier turn and was never replaced.
11. **Determinization (0023).**
    - In a hypothesis world, a revived foe member's HP is half of that world's max HP for it.
    - The public record keeps the percentage from the line.
    - If 0023's public-record path cannot represent the REVIVE boundary, it refuses with `DUOFORGE_E_UNSUPPORTED`; the PR either implements it or adds that refusal with a test.
12. **Encoder 5, before Revival Blessing is supported.** Both encoders refuse slot kind 4 explicitly today (features.py:529, encode.c:406). Once Revival Blessing is marked, a batch that reaches a revive PIVOT would stop. So:
    - Encoder 5 follows 0018's "added value" pattern:
      - a REVIVE row is valid 1, all four kind bits 0, and `reserve / 5` set;
      - `SLOT_FEATURES` stays 12, with no change in public width;
      - encoders 1-4 refuse REVIVE explicitly, as they do Recharge;
      - encoder-4 checkpoints widen without new weights.
    - **Order:** the Revival Blessing PR marks the move supported only together with encoder 5, or encoder 4 and earlier exclude Revival Blessing teams explicitly.
    - `python/duoforge/features.py`, `encode.c` and `python/tests/_reference_features.py` change in the same PR, as a byte-equal pair.

## Who changes what

- **Lane A builder:** the engine, the header with `tools/layout/layout_dump.c` and `python/duoforge/_layout.py`, and the C side of encoder 5 (`encode.c`).
- **HauptSession, the Python side:**
  - `python/duoforge/features.py` and `python/tests/_reference_features.py` (encoder 5);
  - `python/duoforge/_lib.py` `EXPECTED_VERSION` with each version bump;
  - python/duoforge_live (the reviving request in options.py, the tracker's REVIVE handling, lines.py, `_foe_switch_slots`);
  - the replay points and labels.
- **Shared:** tools/reference/trace_to_c.py (`ev_pos` for `pN: NAME`, the REVIVE event, `convert_choice` kind 4). The lane A builder writes it, and HauptSession reviews it.
- **No new view bits:** "fainted and revivable" is derivable from the member view.

## Evidence and order

- **Two PRs, Double Shock first** (smaller). Each one bumps the MINOR version at merge. Each PR has:
  - the header values plus `tools/layout/layout_dump.c` and `python/duoforge/_layout.py` in one commit;
  - recorded battles against the pin, with genders stated;
  - mutation checks and a campaign;
  - a 0015 entry.
- **Revival Blessing battles:**
  - a revived benched member;
  - a revived fainted active ally, fainted this turn (instaswitch);
  - the same for an ally that fainted in an earlier turn and was never replaced;
  - failure with no fainted member;
  - a revived member later switched in by the player;
  - a side's win count after a revive;
  - a revive PIVOT with no living reserve.
- **The lead tells HauptSession** before each PR merges, so the Python side lands with it.

## Not in scope

Baton Pass, Ally Switch, Transform (0028), Imposter (0027) and Illusion (0026) are also approved (owner, 2026-10-09). Each has its own note.
