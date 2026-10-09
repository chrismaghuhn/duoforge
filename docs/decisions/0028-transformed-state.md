# 0028 - The transformed state: Transform and Imposter

Status: **accepted** (owner, 2026-10-09: all API items of the coverage push approved; the values below are the lead's proposal, written before any code). Drafted by the expansion lead (build session A). Lane B's 0027 (Imposter) gives only the trigger and uses this note's state and values. Builds on 0015 (tail rev 4, section 7) and 0018 (the view extension).

## Problem

The replay coverage of 2026-10-09 has Transform in 114 games and Imposter in 101. Both run `transformInto` (sim/pokemon.ts 1270-1360; no Champions override; Imposter is `onSwitchIn` with the foe opposite, data/abilities.ts 2115-2130). The engine can hold neither the copied Pokemon nor a view of it.

## The pin

`transformInto(source)`:
- **Fails if** the source fainted, either side has an Illusion, the source has a Substitute, or the source or the user is already transformed. The Ogerpon, Terapagos and Stellar cases cannot occur in Champions.
- **Copies:**
  - the source's species (setSpecies, no forme-change event) and weight;
  - its current types (`getTypes(true, true)`, or Roost's `typeWas`);
  - its stored stats except HP;
  - its move slots, each at PP min(5, base PP) and max PP the same;
  - its boosts;
  - the crit volatiles Focus Energy and Dragon Cheer (removed first, then copied);
  - timesAttacked;
  - its ability (setAbility, `isTransform`).
- **Prints** `-transform|USER|SOURCE[|[from] ability: Imposter]`.
- **Stays until** the user switches out or faints (`transformed = false` in the switch-in reset, champions scripts.ts:136). The user's HP, status, item and level stay its own.

## Decisions

1. **The state is derived, not copied wholesale.** Per position, the tail gets three fields, all cleared on switch-out and faint:
   - `transform_source` (u8): 0 = not transformed, else 1 + side * 6 + roster index of the source;
   - `transform_forme` (u16): the source's forme at the moment of the copy;
   - `transform_pp` (u16): four 4-bit PP counters for the copied moves, 0 to 5.

   The other copied things are recomputed from these fields:
   - stats are those of the source member computed for `transform_forme`, i.e. its nature and Stat Points with that forme's base stats, as setup computes them;
   - moves are the source member's four move ids, which are static per member in the pool, since no move-changing move is marked;
   - weight comes from the forme.

   What does not follow the source after the copy goes into existing state:
   - types go into the member's `soak_type`/`type2`;
   - the ability goes into the existing ability-change state of Trace (AC1);
   - boosts, the crit flags and `hits_taken` are already per position.

   The invariant checks that a transformed position's source is a brought member of the other side or the own side (Transform can target an ally), and that the PP counters are ≤ 5.
2. **Fit in the tail.** The three fields take 5 bytes per position, 20 in all. Tail rev 4 has 35 reserved bytes after hazard_order, and Illusion's roster index already lives in `ability_state`. The fields go into the reserve with no size change. If the builder finds the reserve smaller than counted, it stops and the lead asks the owner about a tail rev 5.
3. **New public view values:**
   - `DUOFORGE_POSITION_EXT_TRANSFORMED`: volatiles bit 21 (the next free bit after ROOST, 20).
   - `duoforge_position_ext.transform_source` (u8, from `reserved`): 1 + side * 6 + roster index of the source, 0 when not transformed. This is public: the line names the source.
   - `DUOFORGE_VIEWEXT_FEATURE_TRANSFORM` = 42 (FEATURE_COUNT becomes 43).
   - The transformed forme is shown through the existing `member_ext.forme`, and the types through `type_now`/`TYPE_CHANGED` and `ability_now`, as for Soak and Trace.
   - The player's own request offers the copied moves as move slots 0-3. PP stays inside the engine, as for every move.
4. **New public event `DUOFORGE_EVENT_TRANSFORM`** = 44, the next free number after 43 (REVIVE, decision 0025). Fields:
   - `position` = the user;
   - `id` = 1 + side * 6 + roster index of the source;
   - cause MOVE with id2 Transform, or cause ABILITY with id2 Imposter.

   Lane B's Illusion takes 45 or later.
5. **Refusals (E_UNSUPPORTED)** until a recorded battle covers them:
   - Mega Evolution of a transformed Pokemon (the pin forbids it; the request must not offer it);
   - a transformed Pokemon's copied Choice lock or Encore slot;
   - copying a source whose moves changed after setup (impossible in the pool today, guarded by a test listing the move-changing moves as unmarked).

## Evidence and order

- **One PR for the state and Transform; Imposter (lane B) follows on it.** The PR has:
  - the header values together with `tools/layout/layout_dump.c` and `python/duoforge/_layout.py`;
  - the tail fields with codec, invariants, the Python state model and the byte sweep.
- **Recorded battles:**
  - Transform into a foe;
  - Transform into an ally;
  - each failure case that is reachable;
  - copied boosts and Focus Energy;
  - 5 PP running out;
  - switch-out ending the transformation;
  - a transformed Pokemon hit by a super-effective move of its copied types.
- Mutation checks, a campaign, a 0015 entry, and the version bump at merge.
- **Python** (python/duoforge_live, the M11 tracker, features.py) is HauptSession's. It folds `-transform` and the new view fields. This PR changes only `_layout.py` on the Python side.
