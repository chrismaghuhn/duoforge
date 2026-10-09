# 0027 — Imposter (Ditto): the trigger of the transformed state

Status: **proposal** (lane B, 2026-10-09). The owner approved Imposter as an API item. **This note adds no public value, no event and no state of its own.** The transformed state, its view and `DUOFORGE_EVENT_TRANSFORM` (44) are decision 0028 (lane A, PR #252); Imposter is a second way into it. Builds on 0028 and 0026 (Illusion).

## 1. Why, and how much

- **Coverage:** Imposter is in 101 games of the coverage run of 2026-10-09; marking it alone unlocks 47 (greedy rank 313).
- **Holder:** its only holder in the pool is Ditto (abilities Limber, Imposter).
- **Dependency:** it can only be built after the 0028 PR (state plus Transform) has merged.

## 2. The pin

`data/abilities.ts` (imposter; the Champions mod has no entry):

- **onSwitchIn:** the target is `pokemon.side.foe.active[foe.active.length - 1 - pokemon.position]`, the **diagonal** foe in doubles.
  - Slot a copies the foe's slot b, and slot b copies the foe's slot a.
  - If that slot is empty (`null`; a fainted, unreplaced foe still counts as an object there), nothing happens. A fainted target makes `transformInto` fail silently.
- **Then `transformInto(target, Imposter)`**, with every failure case of 0028:
  - the target has a Substitute, is transformed, or has an Illusion up (0026);
  - the holder itself is transformed.
- **The line** is `-transform|HOLDER|TARGET|[from] ability: Imposter`. The event is 0028's TRANSFORM with cause ABILITY and `id2` = Imposter + 1.
- **The copied ability runs its Start**: `setAbility(..., isTransform)` (`sim/pokemon.ts:1352`, `:1908-1946`) calls `singleEvent('Start')` unless the old and new abilities are the same id.
  - So a Ditto that copies an Intimidate user **intimidates**.
  - That also holds for Transform (lane A), so it belongs in 0028 as well.
  - A `cantsuppress` ability is not copied (`setAbility` returns false before the change); the transformation itself stands.
- **Timing:** Imposter is a SwitchIn handler.
  - At battle start and after a mid-turn replacement, it runs in the sorted SwitchIn order with the other entry abilities (Intimidate, the weather setters, Unnerve, Pressure from G45).
  - The order is speed, with the tie draws the engine already models.
  - A Ditto that is faster than an Intimidate user copies before that user's Intimidate lowers anything.
- **Flags:** `failroleplay`, `noreceiver`, `noentrain`, `notrace`. Trace never copies Imposter.

## 3. Rules the engine adds

- **One SwitchIn handler**, read by id (an engine row). It sits in the existing switch-in ordering, the same path as Intimidate.
- **It calls 0028's transform routine** with cause ABILITY. No new code path for the copy itself.
- **After the copy, the copied ability's start handler runs** (as above), if the engine models it. If it is not marked, the battle can't have been created, because the target's ability is gated by the manifest.
- **Refused with `E_UNSUPPORTED`** until a recorded battle covers it:
  - Imposter's copy of a Mega-evolved target that then lets the holder's request offer Mega Evolution. The pin forbids that, and 0028 already refuses it.
  - A copied ability whose Start the engine cannot run.

## 4. View and search

- **Nothing of its own.** The foe sees `-transform` and the copied forme, as in 0028.
- **The holder's own stats** in the view stay its **own** (the review point sent to 0028: the pin's request shows `baseStoredStats`, `sim/pokemon.ts:1159-1164`). Otherwise the own row would show the foe's hidden stat points.
- **Decision 0023:** the transformed state is public apart from the copied stats. Those follow from the foe's hypothesised stat points, so `from_view` recomputes them from the world's values. No new refusal.

## 5. Evidence plan (after 0028 merges)

- **Recorded POOL battles:**
  - Ditto leading in slot a and in slot b (the diagonal copy);
  - Ditto switching in mid-battle;
  - Ditto copying an Intimidate user (its Intimidate fires);
  - a copy that fails into a Substitute (if marked) or into a transformed foe;
  - an empty diagonal slot;
  - a faster Ditto against a slower Intimidate lead.
- **A C test, mutation checks, a campaign of about 300 battles, a 0015 entry and a support line.**
