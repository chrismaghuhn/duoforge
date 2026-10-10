# 0033 - The event -item of the holder's own announcement (ITEM_SHOWN, step G67, lane B batch 3)

Status: accepted by HauptSession and the lead (2026-10-10). Part of decision 0015 (the content expansion, lane B), entry 5bl.

## The event

`DUOFORGE_EVENT_ITEM_SHOWN` = 48u, a new public event kind. It is the protocol line `-item|X|Item` with no attribute: the holder announces its own item at its switch-in. The first user is Air Balloon's `onStart` (`data/items.ts:191-195`, printed unless the item is ignored or gravity is up).

Fields: `kind` 48; `position` = the holder; `other` NO_POSITION; `cause` NONE; `id` 0; `id2` = the item + 1; every other field 0. This follows ITEM_START (42) for the position and id2 convention.

## Reserved form (not mapped in this step)

The same line with `[from] ability: X|[of] Y` (Frisk: `-item|X|Item|[from] ability: Frisk|[of] Y|[identify]`) is reserved for a later step. Its fields would be cause ABILITY with id = the ability and other = the Frisk user. The converter (`tools/reference/trace_to_c.py`) refuses this form and every other `-item` line that is not ITEM_START's move form or the plain form. A refusal is never a silent mapping.

## Why no view change

This format has open team sheets, so the foe already knows the held item. The knowledge fold (`src/combat/events.c`) ignores ITEM_SHOWN: no revealed bit is set and no knowledge changes. A test asserts this (the knowledge of an observation is unchanged by the event).

## Version

The library version is not bumped by this step: HauptSession assigns versions in a version PR at merge time, in merge order (builders never bump). The event and its pins are in place; the version follows at merge.

## Pins that carry the event number

`include/duoforge/duoforge.h` (the define), `tools/layout/layout_dump.c` and `python/duoforge/_layout.py` (the constant, checked by the layout test), `tools/reference/trace_to_c.py` (`EV['ITEM_SHOWN']`, by value, as DRAG and CLEAR_ALL_BOOSTS).
