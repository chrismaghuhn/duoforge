# 0028 - The transformed state: Transform and Imposter

Status: **accepted** (owner, 2026-10-09: all API items of the coverage push approved; the values below are the lead's proposal, written before any code). Drafted by the expansion lead (build session A). Lane B's 0027 (Imposter) gives only the trigger: `onSwitchIn`, aimed at the diagonal foe `foe.active[foe.active.length - 1 - position]`, with no transform when that slot is empty, for the leads at the start and for every later switch-in. It uses this note's state and values. Builds on 0015 (tail rev 4, section 7) and 0018 (the view extension).

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
- **Then copies the ability** with `setAbility(source.ability, this, null, true, true)` (sim/pokemon.ts:1352):
  - isFromFormeChange and isTransform are both true, so the cantsuppress check (:1919) and the SetAbility event are skipped, and a cantsuppress ability IS copied;
  - the old ability's End runs (:1926);
  - the new ability's Start runs unless the old and new ids are equal (:1945-1946). Transforming into an Intimidate user intimidates, and weather setters, Unnerve and Pressure announce again.
- **Stays until** the user switches out or faints (`transformed = false` in the switch-in reset, champions scripts.ts:136). The user's HP, status, item and level stay its own.

## Decisions

1. **The state is derived, not copied wholesale.** Three tail fields, all cleared on switch-out and faint (placement in item 2):
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
2. **Fit in the tail.** Tail rev 4 has 35 reserved bytes on main:
   - 7 in the field block;
   - 4 per position (16 in all);
   - 1 per member (12 in all).

   G46's `party_order` takes field bytes +1..+6. This note takes:
   - `transform_source` in the member reserve, one byte per member. It is the member that is transformed, and it is cleared when that member leaves the field;
   - `transform_forme` (u16) and `transform_pp` (u16) in the position reserve, 4 bytes per position.

   That uses 28 bytes and leaves one, at field byte +7, with no size change. Illusion's roster index already lives in `ability_state`. If the builder finds a different reserve, it stops, and the lead asks the owner about a tail rev 5.
3. **New public view values:**
   - `DUOFORGE_POSITION_EXT_TRANSFORMED`: volatiles bit 21 (the next free bit after ROOST, 20).
   - `duoforge_position_ext.transform_source` (u8, from `reserved`): 1 + side * 6 + roster index of the source, 0 when not transformed. This is public: the line names the source.
   - `DUOFORGE_VIEWEXT_FEATURE_TRANSFORM` = 42 (FEATURE_COUNT becomes 43).
   - The transformed forme is shown through the existing `member_ext.forme`, and the types through `type_now`/`TYPE_CHANGED` and `ability_now`, as for Soak and Trace.
   - **Moves and PP in the member view.**
     - While the member is transformed, `duoforge_member_view.move_ids`, `pp` and `pp_max` show the COPIED moves, as the pin's request does (sim/pokemon.ts:1166, `moves`): the owner sees them exactly, and the foe gets them per `pp_kind` (DERIVED).
     - So request move slot k is the move in column k.
     - `pp_max` is min(5, base PP).
     - They return to the member's own moves when the transformation ends.
     - Under Open Team Sheets the copied moves are public, because the source's sheet is.
   - **Stats in the member view stay the member's OWN.** The pin's request shows `baseStoredStats` (sim/pokemon.ts:1159-1164).
     - Showing the copied stats would leak the source's hidden Stat Points to the transformed side.
     - It would also break 0023: the own row must be the same in every world of one record.
     - The copied stats live only inside the engine, and the header comment on `stats` says so.
     - A test checks two things: Transform leaves the own `stats` unchanged, and two determinized worlds with different foe spreads give identical own rows.
   - **The other copied things are always shown while transformed:**
     - `TYPE_CHANGED` is always set, and `type_now` holds the copied types. They are the source's types before Roost (`typeWas`) when the source had Roosted, with 0 meaning no type.
     - `ability_now` holds the copied ability when it differs from the sheet's.
     - `member_ext.forme` holds `transform_forme` + 1.
     - The copied boosts and crit stages are the position's own, as always.
   - **Decision 0018 is superseded on two points.** Line 193 (Transform kept out of the view as hidden) and the table row at 228 (Transform "not exposed") no longer hold. Transform is public under Open Team Sheets and is exposed by this note.
4. **New public event `DUOFORGE_EVENT_TRANSFORM`** = 44, the next free number after 43 (REVIVE, decision 0025). Fields:
   - `position` = the user;
   - `id` = 1 + side * 6 + roster index of the source;
   - cause MOVE with `id2` = Transform, or cause ABILITY with `id2` = Imposter + 1 (ability + 1, as the cause convention says).

   45 is `DUOFORGE_EVENT_DRAG` (G46). Lane B's Illusion takes 46 (0026).
5. **Choice lock.** A Choice item locks into a COPIED move as into any move. This is the most common Ditto set: Scarf plus Imposter, about 41 of about 115 Ditto sheets in the coverage data. The lock is supported, not refused, and the lock state refers to the move slot, which now holds the copied move.
6. **Refusals (E_UNSUPPORTED)** until a recorded battle covers them:
   - Mega Evolution of a transformed Pokemon. The pin forbids it, and the request must not offer it.
   - An Encore that forces a copied move.
   - Copying a source whose moves or stats changed after setup. That is impossible in the pool today, and a guard test lists as unmarked the move-changing moves and the stat-swap moves Power Trick, Guard Split, Power Split and Speed Swap.
7. **Encoders, as in 0025 item 12.**
   - One shared encoder 5 carries the REVIVE rows (0025), the TRANSFORMED bit and `transform_source`, with the side relative to the viewer.
   - Encoders 1-4 refuse a record with volatiles bit 21 or the TRANSFORM feature explicitly.
   - The C `dfi_version_features(4)` must mask feature 42, so that C and Python stay a byte-equal pair.
   - The static asserts (encode.c:59 on the feature count, features.py:147 on the volatile bits) are updated in the same PR.
   - Transform (and lane B's Imposter) are marked supported only together with encoder 5, or are explicitly excluded for encoder 4 and earlier.
8. **Determinization (0023).** For a foe position, the public record carries `transform_pp` as 5 minus the copied move's observed uses. That is derivable: the source's moves are public and each starts at 5 PP. Hypotheses supply the source's hidden stats, as they do for the source itself. The tracker builds the byte-equal record. Until that path exists, determinizing a record with a transformed foe refuses with E_UNSUPPORTED, with a named cause and a test.
9. **Tail ledger.** The tail stays rev 4. Its reserve is shared in one ledger, documented in 0015 §7: G46's `party_order` takes field bytes +1..+6, this note takes the member and position reserves (28 bytes), and field byte +7 stays free.

## Evidence and order

- **One PR for the state and Transform; Imposter (lane B) follows on it.** The PR has:
  - the header values together with `tools/layout/layout_dump.c` and `python/duoforge/_layout.py`;
  - the tail fields with codec, invariants, the Python state model and the byte sweep.
- **Recorded battles:**
  - Transform into a foe;
  - Transform into an ally;
  - Transform through Protect (Transform has no protect flag);
  - Ditto with Scarf plus Imposter locking into a copied move;
  - Transform into an Intimidate user (Start runs);
  - Transform between two holders of the same ability (no Start);
  - each failure case that is reachable;
  - copied boosts and Focus Energy;
  - 5 PP running out;
  - switch-out ending the transformation;
  - a transformed Pokemon hit by a super-effective move of its copied types.
- Mutation checks, a campaign, a 0015 entry, and the version bump at merge.
- **Who changes what:**
  - The lane A builder: the engine, the header with `tools/layout/layout_dump.c` and `python/duoforge/_layout.py`, the C side of encoder 5 (`encode.c`, `dfi_version_features`), and `tools/reference/trace_to_c.py` (`-transform`; HauptSession reviews it).
  - HauptSession: `features.py` and `_reference_features.py` (encoder 5, byte-equal), `_lib.py` at merge, and the tracker's TYPE_CHANGE, ABILITY_CHANGE, FORME_CHANGE and TRANSFORM folds.
  - Until the tracker folds a lock on a copied move, a copied-move lock stops the tracker (tracker.py:427 locks only sheet moves).
