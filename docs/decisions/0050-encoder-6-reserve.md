# 0050 - Encoder 6: reserve columns for the content expansion

Status: **accepted** (owner request 2026-10-10, design approved by HauptSession). Builds on 0018 (the view extension and its feature mask), 0021 (the encoder in C) and 0028 (encoder 5). Lever 7 (the damage calculator) becomes encoder 7.

## Problem

The expansion keeps adding public presence effects: Healing Wish, Attract and others as `duoforge_position_ext.volatiles` bits, new side guards, side and field conditions. Encoder 5 refuses every bit it has no column for, as the explicit-failure rule says, so each new bit meant a new encoder. Lane B's `_AWAITING_ENCODER` was the stopgap. The owner wants one encoder for the whole expansion.

## Decision

Encoder 6 is encoder 5's 862 columns, byte for byte, followed by **232 reserve columns**, for a width of **1094**. Each reserve column is a 0/1 column for one bit of a bitfield the expansion fills, named by bit number (`ext6.` names, never effect names, so checkpoint layouts stay stable).

| Family | Field | Bits | Columns | Feature (gate) |
| --- | --- | --- | --- | --- |
| field flags | `duoforge_field_ext.flags` (u16, new) | 0-15 | 16 | `FIELD_FLAGS` (63) |
| guards | `duoforge_side_ext.guard_flags` | 2-7 per side | 12 | `RESERVE_GUARDS` (61) |
| side conditions | `duoforge_side_ext.conditions` (u8, new) | 0-7 per side | 16 | `SIDE_CONDITIONS` (62) |
| volatiles | `duoforge_position_ext.volatiles` | 22-31 per position | 40 | `RESERVE_VOLATILES` (59) |
| volatiles2 | `duoforge_observation_ext.volatiles2[side][position]` (u32, new) | 0-31 per position | 128 | `VOLATILES2` (60) |
| position flags | `duoforge_position_view.reserved` (the observation) | 3-7 per position | 20 | none |

Order: the field flags first; then per side, own first, the guard bits and the conditions; then per position, slot 0 first, the volatiles bits, volatiles2 and the position flag bits.

- **The new fields** use reserve bytes of the record. `field_ext.flags` sits at offset 2, `side_ext.conditions` at 62, and `volatiles2` takes 16 of `reserved1`'s 32 bytes (`position_ext` has no room for a u32). Size (192) and revision (1) are unchanged. No bit of the new fields is defined yet; `DUOFORGE_POSITION_EXT2_*`, `DUOFORGE_SIDE_CONDITION_*` and `DUOFORGE_FIELD_FLAG_*` are the prefixes for the bits the lanes add.
- **Gating per family.** The feature mask has 64 bits, and the free ones (43-58 for the lanes) are far fewer than the reserve's 82 record bits. So a family's columns are gated by one family feature, bits 59-63 (HauptSession's numbers). A bit with a feature of its own name (`POSITION_EXT_X`, `POSITION_EXT2_X`, `SIDE_GUARD_X`, `SIDE_CONDITION_X` or `FIELD_FLAG_X` with `VIEWEXT_FEATURE_X`, through the existing exception table) is shown only under that feature as well. A bit without such a feature, named or not, stands in its column under the family feature. The position flags are the observation's own field and have no gate. The library reports the five family features as supported: their fields are exact while no bit is defined, and a step that defines a bit makes it exact before it lands.
- **Why that is safe without a feature per bit.** The mask exists so that a column a network only ever saw at 0 never feeds it a signal through random weights. A fresh network starts every input row fed only by reserve columns at zero (`columns.reserve_rows`, `Model.init`). Widening gives zero rows too. While a column is 0 its gradient is 0, so Adam leaves those rows at 0. A bit that appears later changes nothing until training sees it set.
- **Older encoders.** Encoders 1 to 5 refuse a value in the reserve as one they cannot show: a volatiles bit above 21, a guard bit above 1, a nonzero volatiles2, conditions or field flags word, or a position flag bit beyond the three known ones. C returns `E_UNSUPPORTED`, after every check of a malformed record. Python raises `features.EncoderAwaitingBit`, a `ValueError`, in `encode_batch(..., encoder=v)` and, for the position flags, in `as_encoder`. A mask bit a version has no column for stays `E_INVALID_ARGUMENT`. Encoder 5 stays available unchanged: its feature bits are fixed at 0 to 42 (`TRANSFORM`), and the tier count `DUOFORGE_VIEWEXT_FEATURE_COUNT` may grow up to 59 (the expansion's `HEALING_WISH` 43 next) without touching the encoder.
- **C and Python.** `src/encode/encode.c` builds version 6 byte for byte as `features.py`. Python derives the own features from the constant names. C reads them from `DUOFORGE_VIEWEXT_RESERVE_OWN` in `duoforge.h`, an X-list that a step extends next to its bit's definition. A test checks that the list and the names agree, so no lane edits `encode.c` for a bit.

## Not reserved

Ailments, weather, terrain and slot kinds are closed in gen 9 (Tox is in; SV has no Frostbite and no primal weather). An unknown value there stays an error. Counters (turns) cannot be reserved: a new counter still needs a new encoder. The expansion's convention is presence bits.

## Tests

- `python/tests/test_encoder6.py`:
  - the layout;
  - encoder 5's columns byte-equal;
  - every reserve column;
  - gating per family and by an own feature;
  - refusals by older encoders (`EncoderAwaitingBit`);
  - the header list against the names;
  - a stand-in tier bit 43 that leaves encoder 5 alone;
  - a fresh network unaffected by the reserve before and after an optimizer step;
  - an encoder 5 network widened to 6 with equal outputs.
- `python/tests/test_encode_c.py`: C against Python for versions 1 to 6, with reserve records and fuzzed reserve fields.
