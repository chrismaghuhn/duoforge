# 0033 - The event -item of the holder's own announcement (ITEM_SHOWN, step G67, lane B batch 3)

Status: accepted by HauptSession and the lead (2026-10-10). Part of decision 0015 (the content expansion, lane B), entry 5bl.

## The event

`DUOFORGE_EVENT_ITEM_SHOWN` = 48u, a new public event kind. It is the protocol line `-item|X|Item` with no attribute: the holder announces its own item at its switch-in. The first user is Air Balloon's `onStart` (`data/items.ts:191-195`, printed unless the item is ignored or gravity is up).

Fields: `kind` 48; `position` = the holder; `other` NO_POSITION; `cause` NONE; `id` 0; `id2` = the item + 1; every other field 0. This follows ITEM_START (42) for the position and id2 convention.

## The Frisk form (mapped by step G81)

The line with `[from] ability: X|[of] Y` is Frisk's announcement of a foe's item: `-item|X|Item|[from] ability: Frisk|[of] Y`. The pin prints NO `[identify]` (data/abilities.ts:1549: `this.add('-item', target, target.getItem().name, '[from] ability: Frisk', `[of] ${pokemon}`)`); an earlier draft of this note had it, and it is wrong for the pin b2cb775.

Fields (lead decision, HauptSession approved, step G81): `kind` 48; `position` = the frisked foe X; `other` = the Frisk user Y; `cause` ABILITY; `id` = Frisk + 1 (the ability+1 convention of the ABILITY id field, as in decision 0041; 0 stays "none"); `id2` = the item + 1; every other field 0. A foe whose Illusion disguise is up and that holds an item is refused (E_UNSUPPORTED) at the point the line would be printed.

The converter (`tools/reference/trace_to_c.py`) accepts exactly this form. Every other `-item` line that is not ITEM_START's move form or the plain form (including any other `[from] ability:` form and any line with `[identify]`) is refused: a refusal is never a silent mapping.

## Why no view change

This format has open team sheets, so the foe already knows the held item. The knowledge fold (`src/combat/events.c`) ignores ITEM_SHOWN: no revealed bit is set and no knowledge changes. A test asserts this (the knowledge of an observation is unchanged by the event).

## Version

The library version is not bumped by this step: HauptSession assigns versions in a version PR at merge time, in merge order (builders never bump). The event and its pins are in place; the version follows at merge.

## Pins that carry the event number

`include/duoforge/duoforge.h` (the define), `tools/layout/layout_dump.c` and `python/duoforge/_layout.py` (the constant, checked by the layout test), `tools/reference/trace_to_c.py` (`EV['ITEM_SHOWN']`, by value, as DRAG and CLEAR_ALL_BOOSTS).
