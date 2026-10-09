# 0029 - Small additive public values of lane A (overnight, 2026-10-09)

Status: **accepted** under the owner's overnight authorization (owner, 2026-10-09, directly in the lead chat: the schemas may be extended where a mechanic needs it, so the builders keep going; the owner reviews the list the next day). A living note: each small value that lane A's builders need tonight is appended here, with its reason, before the code that uses it. Larger designs get their own note (0025, 0028).

## Values

1. **`DUOFORGE_BLOCK_QUICK_GUARD` = 6u**, a `DUOFORGE_EVENT_BLOCKED` detail for `-activate|X|move: Quick Guard`.
   - Why: a priority move stopped at a target of the guarded side, the same shape as Wide Guard's detail 4 (step G7).
   - Why the number 6: the BLOCKED details share their numbers with `DUOFORGE_FIELD_*`, because Psychic Terrain's block uses 3, its field id. 5 is Misty Terrain's field id, and is kept free should its block ever use BLOCKED.
   - The view already has `guard_flags` bit `QUICK_GUARD` and the supported bit `FEATURE_QUICK_GUARD` (38).
   - The tail already has `quick_guard` per side (rev 4).
   - Encoders: no change, since the event is not encoded.
   - Info safety: the line is public.
   - Version: a MINOR bump at merge, with the step that marks Quick Guard.
