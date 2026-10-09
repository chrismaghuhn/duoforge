# 0025 - Public values for Double Shock and Revival Blessing

Status: **accepted** (owner, 2026-10-09: "alles freigegeben" for the API items of the coverage push; the values below are the lead's proposal for those two moves, written before any code). Drafted by the expansion lead (build session A). Builds on 0005 (requests and choices), 0006 (boundaries), 0015 (POOL tables, tail rev 4 in section 7) and 0018 (the view extension).

## Problem

The replay coverage of 2026-10-09 (Reg M-C, both sides playable) puts two moves of Pawmot near the top of the blockers: Double Shock is in 1,707 games and Revival Blessing in 1,245. Neither can be expressed with today's public values.

- Double Shock leaves its user with a typeless type slot (`???`). `DUOFORGE_EVENT_TYPE_CHANGE` carries exactly one type, and 0 is Bug.
- Revival Blessing asks its player to pick a fainted party member, which then comes back at half HP. No boundary or slot command picks a fainted member, and no event names a benched Pokemon.

## Decisions: Double Shock

1. **The pin** (data/moves.ts doubleshock; the Champions override adds the punch flag):
   - `onTryMove` fails unless the user has the Electric type now. That prints `-fail|USER|move: Double Shock` with `[still]`, and PP is spent.
   - After a hit, `self.onHit` runs `setType` with Electric replaced by `???`. It then prints `-start|USER|typechange|???/Fighting|[from] move: Double Shock`.
   - `???` counts as no type for effectiveness and STAB. An empty type list becomes Normal in sim/pokemon.ts getTypes, but `???/Fighting` is not empty.
   - Switching out, fainting and Mega Evolution reset the types, and Soak overwrites them.
2. **The state is internal and needs no new field.**
   - The tail's `soak_type` (the first type slot override) may now hold `DFI_TAIL_TYPE2_TYPELESS` (255): "slot 1 is `???`".
   - The species' second type moves into `type2`.
   - The invariant allows 255 in `soak_type` only together with a nonzero `type2`.
   - Every `dfi_types_of` caller is audited for a typeless first slot.
   - The only legal user in the pool, Pawmot, is Electric/Fighting. Any other result shape (Electric as the second type, a pure Electric user, Electric after Soak) returns `DUOFORGE_E_UNSUPPORTED` until a recorded battle covers it.
3. **New public constant `DUOFORGE_TYPE_NONE` = 255u.** It is used only in the `detail` of `DUOFORGE_EVENT_TYPE_CHANGE`, for the `???` slot.
4. **`DUOFORGE_EVENT_TYPE_CHANGE.amount` gets a documented meaning:** the second type id + 1, with 0 meaning one type. It is additive:
   - Soak keeps `detail` Water and `amount` 0.
   - Double Shock gives `detail` `DUOFORGE_TYPE_NONE` and `amount` Fighting + 1, with cause MOVE and id2 Double Shock.
5. **The view needs no change.** 0018 already lets `type_now[k]` = 0 mean "no type there", so Pawmot after Double Shock shows `type_now` = {0, Fighting + 1} with `TYPE_CHANGED` set.

## Decisions: Revival Blessing

6. **The pin** (data/moves.ts revivalblessing; sim/battle.ts 2781-2797 and 2878-2900; sim/side.ts 925-985; sim/pokemon.ts 1183):
   - **Failure:** `onTryHit` fails when the user's side has no fainted Pokemon.
   - **Request:** the move sets the slot condition `revivalblessing` and `selfSwitch`. The user's side then gets a switch request in which that slot (`reviving: true`) must name a fainted party member.
   - **The `revivalblessing` action:**
     - adds 1 to pokemonLeft;
     - clears fainted and status;
     - sets the HP to floor(maxhp / 2);
     - prints `-heal|pN: NAME|HP|[from] move: Revival Blessing`, with no position letter for a benched Pokemon.
   - **A fainted active ally:** if the chosen member was in an active slot, it is switched straight back in (instaswitch).
   - PP 1, no PP boosts.
7. **The boundary is the existing `DUOFORGE_BOUNDARY_PIVOT`, with no new boundary kind.**
   - The request has the user's side requested and `slot_mask` set to the user's position.
   - A mid-turn pick of one slot is what PIVOT already is (0006).
8. **New public slot kind `DUOFORGE_SLOT_REVIVE` = 4u**, with `reserve` = the roster index of the fainted member.
   - The slot's candidates are exactly the brought, fainted members other than the user, one each, in roster order.
   - No MOVE, SWITCH or PASS is offered in that slot.
   - The factored domain lists them in the same way.
   - A REVIVE command outside such a request is not in the domain (`DUOFORGE_E_INVALID_ARGUMENT`, as any foreign command).
9. **New public event `DUOFORGE_EVENT_REVIVE`**, the next free event number (43 on main today), for `[-heal]` of a revived member. Fields:
   - `position` = the user's flat position;
   - `id` = the revived member's roster index;
   - `amount` = the HP after;
   - cause MOVE, `id2` = Revival Blessing.
   `DUOFORGE_EVENT_HEAL` stays unchanged, because it needs a position, and a benched member has none.
10. **The instaswitch reuses `DUOFORGE_EVENT_SWITCH`**, with cause MOVE and id2 Revival Blessing, together with the switch-in effects of the existing path.

## Evidence and order

- **Two PRs, Double Shock first** (smaller), each with:
  - the header values plus `tools/layout/layout_dump.c` and `python/duoforge/_layout.py` in one commit;
  - recorded battles against the pin, with genders stated;
  - mutation checks and a campaign;
  - a 0015 entry;
  - a version bump at merge.
- **Revival Blessing battles:** a revived benched member; a revived fainted active ally (instaswitch); failure with no fainted member; a revived member later switched in by the player; a side's win count after a revive.
- **Python** (python/duoforge_live, the M11 tracker, features.py) is HauptSession's. It must answer the reviving request and fold the `-heal` line of a benched member. The PRs change no Python file beyond `_layout.py`, and the lead tells HauptSession before the Revival Blessing PR merges.

## Not in scope

Baton Pass, Ally Switch, Transform, Imposter and Illusion are also approved (owner, 2026-10-09). Each gets its own note.
