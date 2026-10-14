# The viewer's observation digest per leaf (draft decision record, D2)

**Status:** draft for the coordination with Astra (via the owner) and the HauptSession's decision, 2026-10-14. Not a
decision yet: its number comes from the HauptSession, its form from the agreement with Astra's D4 spec. No code.
Spec `docs/superpowers/specs/2026-10-13-depth-search-design.md` section 4.2 and Q3; plan
`docs/superpowers/plans/2026-10-14-depth-search-d2.md` step 9; read against main b4115367 (after the field step).

## Why

D2's tree merges our depth-1 nodes into information sets: two nodes share one when our root action is the same and
everything our seat saw during the step is the same. Python must not decide what we saw (AGENTS.md: no hidden rule),
so the key comes from the engine. The test key `info_key = "record"` (the public record's bytes) is refused under
closed team sheets and refused where the engine refuses a node's public record; the digest has neither gap.

## What the engine already has (main b4115367)

- Every step stages its events canonically on the stack (`dfi_events staged` in `dfi_battle_step_events_tape`,
  `src/state/request.c`), at most `DUOFORGE_MAX_EVENTS` (512) records of the 20-byte `duoforge_event`.
- `dfi_event_project(rec, player, out)` (`src/combat/events.h`) turns a record into one player's view: the opponent's
  HP as the percent display with its flag, the player's own HP exact. The knowledge fold
  (`dfi_events_fold_knowledge`) consumes these views; they are what the seat saw.
- `src/core/sha256.c` gives SHA-256.

## Proposal

- **A sibling call, no ABI break of `duoforge_batch_expand`** (HauptSession, 2026-10-14):
  `duoforge_batch_expand_digest(...)` with `duoforge_batch_expand`'s arguments plus `uint8_t *digests` (`count` × 32
  bytes). It expands exactly as `duoforge_batch_expand` does, and writes leaf i's digest for its viewer
  `viewers[root_envs[i]]`. A failed step writes 32 zero bytes (the step status already names it).
- **The digest:** SHA-256 of
  - a domain tag (`"duoforge.observation-digest.v1"`) and the viewer (one byte);
  - each of the step's records as `dfi_event_project` gives it to the viewer, in emission order, each serialized
    field by field with every `uint16_t` little-endian (20 bytes per record, independent of the platform's
    endianness and the struct's layout);
  - the record count (`uint32_t`, little-endian);
  - the leaf's public request header for the viewer after the step: boundary kind and request mask (both public).
- **On the stack, no allocation, no rule:** an incremental SHA-256 context and one 20-byte projected record at a time,
  inside the step where `staged` lives (an internal variant of the step that takes the viewer and an output pointer,
  or a fold hook beside the knowledge fold). The digest reads only bytes the engine already produces; it interprets
  nothing.
- **Determinism:** a pure function of the leaf's step (root, seeds of (seed, key, sample), choices) and the viewer:
  independent of worker, chunk and leaf position, like the leaf itself.
- **Shared with D4:** the in-engine evaluation's call (#485) takes the same optional `digests` output, so D5's sampled
  tree gets values and keys in one call.
- **Public numbers:** none expected (no event kind, cause or feature). Any number needed is asked from the
  HauptSession first.

## Tests (with the code, after the agreement)

- C: equal projected lines give equal digests; a different damage display, a different switch-in or a different
  move order gives different digests; the same leaf on 1 and 8 workers and in chunks of 1 and 16 gives the same
  digest; a viewer that sees less (the opponent's exact HP) does not split where its view is equal; zero bytes for a
  failed step.
- Python: `info_key = "digest"` keys the depth-1 nodes through `Batch.expand_digest`; the stub-key tests stay as tests
  of the tree; the HauptSession's gate before any arm: the offline pass's bound checked again on digest-keyed trees.

## Questions for Astra (via the owner)

1. After the field step, is `dfi_battle_step_events_tape` (with `staged`) still the place the leaf's step goes
   through in `duoforge_batch_expand` (`duoforge_battle_step` today), and is a viewer-and-digest variant of it there
   acceptable, or does the D4 spec put the fold elsewhere?
2. Does the record list above (the projected events plus the request header) cover everything a seat observes in a
   step, in the engine's own definition (decision 0007 section 6), or does the view carry an observation that is not
   an event line?
3. D4's call: one sibling call with optional `values` and `digests`, or two calls sharing the expand core?
