# 0018 - The POOL player-view extension: `duoforge_observation_ext`

Status: **accepted** (owner, 2026-10-02: all points of section 14, with one change: Throat Chop is public, section 5). The first draft was design only; the build follows in steps (section 13). Builds on decision 0007 (what a player sees), 0015 (the POOL data kind and, in section 7, the POOL state tail), 0013 and 0014 (the Python encoder), 0016 (the live adapter and its tracker). The number 0017 is reserved for Learner v2.

## 1. Decided already (owner, in principle)

- The 736-byte `duoforge_observation` stays exactly as it is, for every kind.
- A new additive query `duoforge_battle_observe_ext(ctx, battle, viewer, duoforge_observation_ext *out)` returns a fixed-size struct. It is **all zero under every non-POOL kind** (CLOSURE, CLOSURE_DEV, TEAM_C, TEAM_C_DEV, SYNTHETIC); under POOL and POOL_DEV `revision` is nonzero.
- New enum values go into the existing fields of the old observation: weather Sand and Snow, terrain Electric and Misty, ailment Tox. They occur only under POOL, because only POOL data can start them.

This note fixes the exact layout, who sees what, where each field comes from in the Showdown protocol, how the layout grows, the build order, and what the Python encoder gains.

## 2. Design in one page

- **Everything is declared now, written later.** Revision 1 names a field for every effect of the replay spike's list and of the G7 to G11 steps (Wide Guard, Throat Chop, Heal Block, Encore, Soak). A field is zero until the step that implements its mechanic sets its bit in a `supported` mask in the struct. So the layout, the encoder shape and the Python layout pin change **once**, not once per mechanic.
- **Same style as the old observation:** fixed size, no pointers, no padding, every record zero-filled, reserved bytes zero, `*_ext` records mirroring the `*_view` ones (field-wide, per side, per position, per member). `sides[]` stays in absolute side order, like `duoforge_observation`.
- **Information rule (0007):** a field is **public** when the game shows it to both players, or when it follows from what both see (the open team sheets, the rules, the lines); it would be **own side only** when only the owner's screen shows it, and then zero in the opponent's section. No field of revision 1 is own side only. Durations that Showdown never shows are **not exposed**: only presence is, or what is publicly derivable (for example Perish counts).
- **Pure and checked like `duoforge_battle_observe`:** checks NULL -> `E_CONTEXT_MISMATCH` -> `E_INVALID_ARGUMENT` (player) -> `E_INVARIANT`; `*out` is written only on success. Under a non-POOL kind it checks the same things and then writes zeros.

## 3. Layout (revision 1): 192 bytes

Offsets are in bytes from the start of the record; every integer is native-endian, as the other public structs (the Python dtypes are explicit about that). The struct has alignment 8 (one `uint64_t`) and no padding; each nested record is a multiple of its own alignment.

### 3.1 `duoforge_observation_ext` (192 bytes)

| Field | Type | Offset | Range | Unit | Meaning |
|---|---|---|---|---|---|
| `revision` | u8 | 0 | 0 or 1 | - | 0: absent (a non-POOL kind), the whole struct is zero. 1: this layout. A consumer reads this first |
| `player` | u8 | 1 | 0, 1 | - | the viewer, as `duoforge_observation.player`; 0 when `revision` is 0 |
| `reserved0` | u8[2] | 2 | 0 | - | reserve (appendable) |
| `epoch` | u32 | 4 | any | request epoch | the epoch of the request that the paired `duoforge_observation` has; 0 when `revision` is 0 |
| `supported` | u64 | 8 | bit set | bit per `DUOFORGE_VIEWEXT_FEATURE_*` | features whose mechanic this build implements (section 8.2); a zero field of a clear bit means "not yet supported", of a set bit "absent" |
| `field` | `duoforge_field_ext` | 16 | - | - | field-wide section (3.2) |
| `sides[2]` | `duoforge_side_ext` | 32 | - | - | per side, absolute side order, 64 bytes each (3.3) |
| `reserved1` | u8[32] | 160 | 0 | - | section-level reserve: room for a whole new record (appendable) |

Size: 16 + 16 + 2 x 64 + 32 = **192** bytes. Used: 111 bytes. Reserve: 81 bytes (2 + 15 + 16 + 12 + 4 inside the records, 32 at the end; section 9).

### 3.2 `duoforge_field_ext` (16 bytes, public)

| Field | Type | Offset | Range | Unit | Meaning |
|---|---|---|---|---|---|
| `gravity_turns` | u8 | 0 | 0 to 5 | turns left | Gravity's remaining turns, 0 when absent. Start and duration (5) are public |
| `reserved` | u8[15] | 1 | 0 | - | reserve |

### 3.3 `duoforge_side_ext` (64 bytes)

| Field | Type | Offset | Range | Unit | Meaning |
|---|---|---|---|---|---|
| `positions[2]` | `duoforge_position_ext` | 0 | - | - | the two active positions, slot 0 then 1 (3.4) |
| `members[6]` | `duoforge_member_ext` | 32 | - | - | the roster, roster order (3.5) |
| `aurora_veil_turns` | u8 | 56 | 0 to 8 | turns left | Aurora Veil on this side; 5 turns, 8 with Light Clay (the sheet shows the item); public |
| `stealth_rock` | u8 | 57 | 0, 1 | flag | Stealth Rock on this side |
| `spikes` | u8 | 58 | 0 to 3 | layers | Spikes layers |
| `toxic_spikes` | u8 | 59 | 0 to 2 | layers | Toxic Spikes layers |
| `sticky_web` | u8 | 60 | 0, 1 | flag | Sticky Web |
| `guard_flags` | u8 | 61 | bits | `DUOFORGE_SIDE_GUARD_*` | single-turn guards of this side: `WIDE_GUARD` 1, `QUICK_GUARD` 2. This turn only: nonzero only at a PIVOT boundary (mid-turn); they end in the residual, so a TURN or REPLACEMENT boundary always has 0 |
| `reserved` | u8[2] | 62 | 0 | - | reserve |

Reflect, Light Screen and Tailwind stay in `duoforge_side_view`; the side conditions that this extension adds are in this record, never in the old one.

### 3.4 `duoforge_position_ext` (16 bytes)

An empty position (no occupant, or a fainted one) is all zero. Every field belongs to the occupant: it is cleared when the occupant leaves the position (section 6.1 gives the rule per field).

| Field | Type | Offset | Range | Unit | Meaning |
|---|---|---|---|---|---|
| `volatiles` | u32 | 0 | bits (3.4.1) | `DUOFORGE_POSITION_EXT_*` | presence flags of public conditions of the occupant. Bits 20 to 31 reserved (0) |
| `ability_now` | u16 | 4 | 0 to 65535 | ability id + 1 | the occupant's current ability when it differs from `duoforge_member_view.ability` (Trace, Skill Swap, Role Play, Worry Seed...); 0 = no change. The effective ability is `ability_now` if nonzero, else the member view's |
| `type_now[2]` | u8[2] | 6 | 0 to 18 | type id + 1 (alphabetical: Bug = 1 ... Water = 18) | the occupant's types after a type change (Soak); 0 in a slot = no type there. Zero unless `TYPE_CHANGED` is set |
| `encore_slot` | u8 | 8 | 0 to 4 | move slot + 1 | the one move slot the occupant is forced into by Encore; 0 = not encored. Public |
| `disable_slot` | u8 | 9 | 0 to 4 | move slot + 1 | the move slot that Disable bars; 0 = none. Public |
| `stockpile` | u8 | 10 | 0 to 3 | levels | Stockpile level |
| `perish` | u8 | 11 | 0 to 3 | count shown | the Perish count the game announced (3, 2, 1); 0 = no Perish. Public: the game announces every count |
| `reserved` | u8[4] | 12 | 0 | - | reserve |

#### 3.4.1 The `volatiles` bits

| Bit | Name | Visibility | Mechanic |
|---|---|---|---|
| 0 | `SUBSTITUTE` | public | Substitute is up (its HP is hidden: not exposed) |
| 1 | `TAUNT` | public | Taunt |
| 2 | `IMPRISON` | public | the occupant has used Imprison |
| 3 | `LEECH_SEED` | public | Leech Seed on the occupant |
| 4 | `YAWN` | public | Yawn: the occupant falls asleep at the end of the next turn |
| 5 | `FOCUS_ENERGY` | public | Focus Energy |
| 6 | `DRAGON_CHEER` | public | Dragon Cheer |
| 7 | `MUST_RECHARGE` | public | the occupant must recharge on its next action (Hyper Beam class) |
| 8 | `PARTIAL_TRAP` | public | partially trapped (Infestation, Wrap class); the source is not exposed |
| 9 | `GLAIVE_RUSH` | public | Glaive Rush: the occupant is hit as vulnerable until it moves again |
| 10 | `DESTINY_BOND` | public | Destiny Bond, until the occupant moves again |
| 11 | `CURSE` | public | the Ghost-type Curse is on the occupant |
| 12 | `NO_RETREAT` | public | No Retreat: the occupant cannot switch |
| 13 | `SALT_CURE` | public | Salt Cure |
| 14 | `CHARGE` | public | Charge: its next Electric move is doubled |
| 15 | `HEAL_BLOCK` | public | Heal Block (G7 to G11 table) |
| 16 | `THROAT_CHOP` | public (owner decision, 2026-10-02) | sound moves are barred (G7 to G11 table); set for both players |
| 17 | `RAGE_POWDER` | public | Rage Powder draws single-target moves this turn (PIVOT boundary only, like the guards) |
| 18 | `TYPE_CHANGED` | public | `type_now` holds the types |
| 19 | `ILLUSION_UP` | public | the occupant has Illusion and it is not broken yet (known from the open sheet and the lines) |

### 3.5 `duoforge_member_ext` (4 bytes)

Per roster member, bench included: a forme change or an item change outlives the switch. All zero for a member that never changed and for a foe member not yet seen.

| Field | Type | Offset | Range | Unit | Meaning |
|---|---|---|---|---|---|
| `forme` | u16 | 0 | 0 to 65535 | forme id + 1 | the member's current forme when it differs from the sheet's and from the Mega forme (Aegislash-Blade, Palafin-Hero, Mimikyu-Busted); 0 = as `duoforge_member_view.species_id`. A temporary forme (Aegislash) is reset when the member leaves the field; a permanent one (Palafin-Hero, Mimikyu-Busted) stays |
| `item_now` | u8 | 2 | 0 to 255 | item id + 1, or 255 | the member's held item when an effect other than its use changed it: 0 = as the member view (the sheet item, or used up); 1 to 254 = it now holds item (value - 1) (Trick, Switcheroo, Thief); 255 = it now holds nothing (Knock Off, Thief on the victim). The same 254-item bound as `duoforge_member_view.item` |
| `reserved` | u8 | 3 | 0 | - | reserve |

### 3.6 Ids

Forme, ability and item ids are the rows of the data tables that `duoforge_data_*` names (decision 0015, the data query API); a "+ 1" means 0 is "none". Type ids are the alphabetical order of the 18 types of the tables (Bug 0 ... Water 17); step V1 adds `DUOFORGE_TYPE_*` constants to the header for them.

## 4. New enum values of the old observation

| Field | Constant | Value | Notes |
|---|---|---|---|
| `weather` | `DUOFORGE_WEATHER_SAND` | 3 | `weather_turns` as for rain and sun: 5, or 8 with Smooth Rock (public item) |
| `weather` | `DUOFORGE_WEATHER_SNOW` | 4 | Snow (Snowscape); 5, or 8 with Icy Rock |
| `terrain` | `DUOFORGE_TERRAIN_ELECTRIC` | 3 | |
| `terrain` | `DUOFORGE_TERRAIN_MISTY` | 4 | |
| `status` (member view) | `DUOFORGE_AILMENT_TOX` | 6 | badly poisoned; the toxic counter is hidden by the game and not exposed |

These values never occur under the other kinds. Python's `features.encode` raises `ValueError` for a value outside its known sets (decision 0014's rule); for these it is the intended explicit refusal of a POOL observation by an encoder that predates this note (section 10).

## 5. Visibility per field (decision 0007)

Everything above is **public**, `THROAT_CHOP` included (owner decision, 2026-10-02): the move that causes it, Throat Chop, is a public move line, its secondary effect applies on every hit, and the `[silent]` start line is in both players' streams. The first draft had it own side only; the opponent's field is set exactly like the owner's. No field of revision 1 is own side only.

**Hidden by the game, hence not exposed** (decision 0007 section 9 point C, applied to the new effects). Only presence, or a publicly derivable count, is in the layout:

| Effect | What Showdown shows | What the layout has |
|---|---|---|
| Taunt, Encore, Disable, Heal Block, Throat Chop remaining turns | start and end line, never a counter | presence only (and the forced or barred slot for Encore and Disable; both slots are public: the move that Encore forces is the last one the foe was seen using, the Disable line names the move) |
| Substitute HP | nothing | presence only |
| Toxic counter | nothing | the ailment Tox only |
| Yawn | start line and the sleep one turn later | presence; the count (1 turn) follows from the rule |
| Imprison | start line | presence; the barred moves follow from the user's open sheet |
| Illusion's disguise (which Pokemon it shows) | the switch line | `ILLUSION_UP` only; the disguise is not exposed |
| Source of Leech Seed, a partial trap, Curse | `[of]` on the start line | not exposed in revision 1 (appendable into a position's reserve, section 9) |
| Perish Song | every count `|-start|POKEMON|perishN` | public: `perish` holds the count |
| Stockpile | the level in the line | public: `stockpile` |
| Aurora Veil, Gravity, weather, terrain | start and end; duration is a rule (and the Light Clay or rock item, both on the sheet) | remaining turns, as 0007 does for Tailwind |

## 6. Protocol signals (what sets a field, what clears it)

The live tracker (decision 0016) and the M11 spectator pipeline fill every field from the Showdown protocol alone, through the converter's parser (`trace_to_c.step_events`), which raises on a line it does not know. "OUT" means the occupant leaves the position: `|switch|`, `|drag|`, `|faint|` (a `|replace|` for Illusion). The lines below follow the replay spike's list and the pinned protocol; **owner rule (2026-10-02): every step that sets a `supported` bit verifies the protocol signals of its fields at the pin with recorded battles** (a spec, `ps_trace.js`, `trace_to_c.py`; one recorded battle per line that sets or clears the field, as decision 0007 does for abilities), and the bit is not set before they agree with the engine. A spectator sees the same public lines as a player and has no own side, so it fills every field of this section the same way.

### 6.1 Per field

| Field | Set by | Cleared by | Determined by the protocol? |
|---|---|---|---|
| `weather` Sand | `\|-weather\|Sandstorm\|...` (also `[from] ability: Sand Stream`) | `\|-weather\|none` or another weather | yes |
| `weather` Snow | `\|-weather\|Snowscape\|...` | `\|-weather\|none` or another | yes |
| `terrain` Electric, Misty | `\|-fieldstart\|move: Electric Terrain` (resp. Misty; also `[from] ability:`) | `\|-fieldend\|move: ...` or another terrain | yes |
| `status` Tox | `\|-status\|POKEMON\|tox`, and the own request's condition `hp/max tox` | `\|-curestatus\|POKEMON\|tox`, `\|faint\|` | yes |
| `ability_now` | Trace: `\|-ability\|POKEMON\|NEW\|OLD\|[from] ability: Trace\|[of] SRC` (NEW the copied ability, OLD the holder's own, which the open sheet already says; the line the pin prints is `battle.add('-ability', pokemon, ability.name, oldAbility.name, '[from] ' + effect.fullname, '[of] ' + source)`, sim/pokemon.ts:1937-1939); Skill Swap: `\|-activate\|POKEMON\|move: Skill Swap\|...\|[of] SRC` (swap the two occupants' effective abilities: both are on the open sheets); other changes: `\|-ability\|POKEMON\|ABILITY\|[from] move: X` | OUT (a changed ability reverts when the occupant leaves) | yes, with the sheet for the swap's other side |
| `type_now` + `TYPE_CHANGED` | `\|-start\|POKEMON\|typechange\|TYPE\|` (Soak; the pin's line has no `[from]`, so one type and no move) | OUT, and `\|-mega\|` of the occupant (setSpecies resets the types; step G11) | yes |
| `item_now` | `\|-item\|POKEMON\|ITEM\|[from] move: Trick` (and Switcheroo): both occupants; `\|-enditem\|POKEMON\|ITEM\|[from] move: Knock Off` (and Thief): 255 for the victim | never (the item stays gone or swapped); a consumed item is the old `item_used` | yes |
| `forme` | temporary: `\|-formechange\|POKEMON\|SPECIES\|...` (Aegislash); permanent: `\|detailschange\|POKEMON\|SPECIES, ...` (Palafin-Hero, Mimikyu-Busted) | temporary: the member's next `\|switch\|` shows the base forme; permanent: never | yes |
| `aurora_veil_turns` | `\|-sidestart\|pN: NAME\|move: Aurora Veil` (5, or 8 when the setter holds Light Clay: sheet) | `\|-sideend\|pN: NAME\|move: Aurora Veil` (also `[from] move: Brick Break` and the like); counts down in the residual | yes |
| `perish` | `\|-start\|POKEMON\|perishN` (N = 3, 2, 1): store N | `\|faint\|`, OUT | yes |
| `encore_slot` | `\|-start\|POKEMON\|Encore`; the slot is the one of the occupant's last `\|move\|` line on the open sheet | `\|-end\|POKEMON\|Encore`, OUT | presence yes; the slot derives from the move history (public). Set by step G9 (supported bit 7); the `-start`/`-end` lines are the `VOLATILE_START`/`VOLATILE_END` events with the detail `ENCORE` (2) |
| `THROAT_CHOP` | `\|-start\|POKEMON\|Throat Chop\|[silent]` (both players' streams carry it; the own request also disables the sound moves) | `\|-end\|POKEMON\|Throat Chop\|[silent]`, OUT | yes, for both sides |
| `HEAL_BLOCK` | `\|-start\|POKEMON\|move: Heal Block` | `\|-end\|POKEMON\|move: Heal Block`, OUT | yes |
| `toxic_spikes`, `spikes`, `stealth_rock`, `sticky_web` | `\|-sidestart\|pN: NAME\|move: Toxic Spikes` (Spikes, Stealth Rock, Sticky Web); each Toxic Spikes or Spikes line adds a layer | `\|-sideend\|pN: NAME\|move: ...` (absorbed: `[of] POKEMON`; Rapid Spin, Defog: `[from] move: ...`) | yes |
| `guard_flags` | `\|-singleturn\|POKEMON\|Wide Guard` (resp. Quick Guard): the user's side | the next `\|upkeep\|` / `\|turn\|` | yes |
| `RAGE_POWDER` | `\|-singleturn\|POKEMON\|move: Rage Powder` | the next `\|upkeep\|` / `\|turn\|` | yes |
| `TAUNT` | `\|-start\|POKEMON\|move: Taunt` | `\|-end\|POKEMON\|move: Taunt`, OUT | yes |
| `IMPRISON` | `\|-start\|POKEMON\|move: Imprison` | OUT | yes |
| `DISABLE` (`disable_slot`) | `\|-start\|POKEMON\|Disable\|MOVE`: the slot of MOVE on the open sheet | `\|-end\|POKEMON\|Disable`, OUT | yes |
| `MUST_RECHARGE` | `\|-mustrecharge\|POKEMON` | `\|cant\|POKEMON\|recharge`, OUT | yes. Set by step G17 (supported bit 15): `-mustrecharge` is the `VOLATILE_START` event with the detail `MUST_RECHARGE` (3), `cant\|X\|recharge` the `CANT` event with the cause `RECHARGE` (18); the volatile has no end line |
| `PARTIAL_TRAP` | `\|-activate\|POKEMON\|move: Infestation\|[of] SRC` (Wrap class alike) | `\|-end\|POKEMON\|Infestation\|[partiallytrapped]`, OUT, the source leaving | yes |
| `GLAIVE_RUSH`, `DESTINY_BOND` | `\|-singlemove\|POKEMON\|Glaive Rush` (resp. Destiny Bond) | the occupant's next `\|move\|` or `\|cant\|` line (the game ends it silently, at the start of its next action), OUT | yes. `GLAIVE_RUSH` is set by step G19 (supported bit 20); the line is `[silent]`, so the engine has no event for it and the view bit is the only trace (set by the Glaive Rush that hit) |
| `stockpile` | `\|-start\|POKEMON\|stockpileN` | `\|-end\|POKEMON\|Stockpile` (Spit Up, Swallow), OUT | yes |
| `SUBSTITUTE` | `\|-start\|POKEMON\|Substitute` | `\|-end\|POKEMON\|Substitute`, OUT | presence yes; its HP no |
| `DRAGON_CHEER`, `FOCUS_ENERGY` | `\|-start\|POKEMON\|move: Dragon Cheer` (resp. Focus Energy) | OUT | yes |
| `YAWN` | `\|-start\|POKEMON\|move: Yawn\|[of] SRC` | `\|-end\|POKEMON\|move: Yawn` (silent) and the `\|-status\|...\|slp` it brings, OUT | yes |
| `LEECH_SEED`, `SALT_CURE`, `CURSE`, `NO_RETREAT`, `CHARGE` | the `\|-start\|POKEMON\|...` line of the move | `\|-end\|...` where the game sends one; OUT; Charge also at the occupant's next Electric `\|move\|` | yes |
| `ILLUSION_UP` | the occupant's switch-in, when its sheet ability is Illusion | `\|replace\|POKEMON\|...` (the break), OUT | yes, through the open sheet |
| `gravity_turns` | `\|-fieldstart\|move: Gravity` | `\|-fieldend\|move: Gravity`; counts down in the residual | yes |

### 6.2 Left out because the protocol cannot determine it

| What | Why |
|---|---|
| Transform | the copied moves and PP are hidden from the foe; only the forme would show (`\|-transform\|`). Below 0.1 percent. Not in revision 1; a later revision may add a `TRANSFORMED` bit if the copy rule turns out public |
| Substitute's HP, the toxic counter, every hidden duration of section 5 | the game does not show them |
| The disguise of Illusion, the source of Leech Seed, partial traps and Curse | the line carries them but this revision gives them no field (appendable) |

## 7. The `supported` mask

`supported` (a u64) has one bit per feature. A bit is set only by the step that **implements the mechanic and records a reference battle with it under POOL**, in the same table that holds the support manifest (decision 0006's gate: only the step that tests a mechanic may mark it). Until then the field is zero and the bit is clear.

- **Bit clear: "not yet supported".** The zero in the field means *unknown*, not *absent*. A native battle cannot contain the mechanic (setup and step refuse it with `E_UNSUPPORTED`), but a live game on Showdown can. The tracker therefore fills a field **only if its bit is set** in the library it runs with, and never guesses.
- **Bit set: "absent" or "present" is exact.** A zero then means the effect is not there.
- Under a non-POOL kind `supported` is 0 and so is the whole struct, so a consumer tells "no extension" (`revision` 0) from "extension, nothing supported yet" (`revision` 1, mask 0).
- The mask also covers the new enum values of section 4, so an encoder can tell "Sand cannot occur yet" from "Sand did not occur".

### 7.1 The bits (`DUOFORGE_VIEWEXT_FEATURE_*`)

Numbered by tier (section 8), then by frequency. A bit stays assigned forever; bits 40 to 63 are free for appended features. The bits that stand for the new enum values of section 4 are 0 (Sand), 1 (Snow), 5 (Electric Terrain), 10 (Tox) and 32 (Misty Terrain).

| Tier | Bits |
|---|---|
| 1 | 0 `WEATHER_SAND`, 1 `WEATHER_SNOW`, 2 `ABILITY_CHANGE`, 3 `AURORA_VEIL`, 4 `PERISH`, 5 `TERRAIN_ELECTRIC` |
| 2 | 6 `THROAT_CHOP`, 7 `ENCORE`, 8 `TOXIC_SPIKES`, 9 `TYPE_CHANGE`, 10 `AILMENT_TOX`, 11 `ITEM_CHANGE`, 12 `IMPRISON`, 13 `STEALTH_ROCK`, 14 `TAUNT`, 15 `MUST_RECHARGE`, 16 `HEAL_BLOCK`, 17 `WIDE_GUARD` |
| 3 | 18 `PARTIAL_TRAP`, 19 `FORME_CHANGE`, 20 `GLAIVE_RUSH`, 21 `DISABLE`, 22 `STOCKPILE`, 23 `SUBSTITUTE`, 24 `DRAGON_CHEER`, 25 `YAWN`, 26 `ILLUSION`, 27 `GRAVITY`, 28 `LEECH_SEED`, 29 `FOCUS_ENERGY` |
| 4 | 30 `SPIKES`, 31 `CHARGE`, 32 `TERRAIN_MISTY`, 33 `STICKY_WEB`, 34 `SALT_CURE`, 35 `DESTINY_BOND`, 36 `CURSE`, 37 `NO_RETREAT`, 38 `QUICK_GUARD`, 39 `RAGE_POWDER` |

## 8. Priority tiers (replay spike frequencies)

The percentages are the replay spike's "share of decisions" with the effect on the field. Tier 1 is built first, together with the mechanics; a tier is not a commitment of dates, only of order.

| Tier | Features (percent of decisions) | State needed beyond tail rev 1 (decision 0015 section 7) |
|---|---|---|
| **1** (1 percent and more) | Sandstorm 6.45, Snow 4.83, ability changed 4.09, Aurora Veil 2.28, Perish Song 1.58, Electric Terrain 1.10 | new: weather and terrain values; per-position `ability_now`; Aurora Veil turns; Perish count |
| **2** (0.4 to 1 percent) | Throat Chop 0.93, Encore 0.90, Toxic Spikes 0.82, type change 0.74, Tox 0.67, item swapped 0.65, Imprison 0.51, Stealth Rock 0.49, Taunt 0.44, must recharge 0.44; and from the G7 to G11 table (not in the spike list): Wide Guard, Heal Block | Throat Chop, Encore, Heal Block, Wide Guard, Soak (the type change) are **already in tail rev 1**; the rest is new (tail rev 2) |
| **3** (0.15 to 0.4) | partial trap 0.38, Aegislash-Blade 0.37, Glaive Rush 0.35, Disable 0.29, Stockpile 0.27, Palafin-Hero 0.22, Substitute 0.22, Dragon Cheer 0.20, Yawn 0.19, Illusion 0.19, Gravity 0.18, Leech Seed 0.18, Focus Energy 0.17, Mimikyu-Busted 0.15 | new |
| **4** (below that) | Spikes, Charge, Misty Terrain, Sticky Web, Salt Cure, Destiny Bond, Curse, No Retreat; and the single-turn guards of a mid-turn pivot (Rage Powder, Wide Guard, Quick Guard: 0.05) | new |
| not exposed | Transform | - |

The state side is not designed here. Tail rev 2 (schema 0x0203, decision 0015 section 7) carries the state of the tier-1 and tier-2 fields of this note that rev 1 lacked: perish, Taunt, Disable with its slot, Imprison, Substitute with its HP, must-recharge, partial trap with source, move and turns, Leech Seed with its source, Yawn, Focus Energy, Stockpile, Charge, Glaive Rush, Aurora Veil, Toxic Spikes, Stealth Rock, Spikes, Sticky Web, Gravity, and per member the current ability, item and forme and the toxic stage; only item_now is written so far (Knock Off, step G16: 255, shown in the view with bit 11). A step that needs a byte it does not have revises the tail again (0x0303 and on) and says so. The view reads the state through `dfi_battle` like `duoforge_battle_observe`; it never reads the opponent's hidden state: an own-side-only field is read only for the viewer's side, and a public field only from state that follows from what the viewer saw (the check of 0007 section 7, extended in section 12).

How the tail rev 1 fills the view: `wide_guard` -> `guard_flags` bit `WIDE_GUARD`; `encore_slot` -> `encore_slot`; `throat_chop_turns` != 0 -> `THROAT_CHOP` (both sides); `heal_block_turns` != 0 -> `HEAL_BLOCK`; `soak_type` of the occupant -> `TYPE_CHANGED` and `type_now[0]`. The turn counters of the tail (`encore_turns`, `throat_chop_turns`, `heal_block_turns`) never leave the engine.

## 9. Revision and growth rule

1. **`revision`** is 0 (absent) or the number of the layout family. Revision 1 is this note. A struct of revision N never changes size or any offset.
2. **Reserved bytes** are always written as zero and a consumer ignores them. The reserve is spread by section: 2 bytes in the header, 15 in `duoforge_field_ext`, 4 in each position (16), 1 in each member (12), 2 in each side (4), and 32 at the end: **81 bytes**, 42 percent of 192.
3. **Fields are only appended into a reserve** within a revision. A new named field takes bytes from the reserve of its own record (a position field from the position's 4 bytes, a whole new record from the 32 at the end); no existing offset moves and no existing meaning changes. Such a field comes with a new `DUOFORGE_VIEWEXT_FEATURE_*` bit (bits 40 to 63 are free), so a consumer built before it sees a zero reserve and a clear bit it does not know. This is an additive public API change: **minor library version**; the layout pin (below) and the encoder (section 10) change in the same PR.
4. **What bumps the struct size:** only a new revision. If a field needs more than the reserve of its record, or an existing field needs a different width, the answer is a **new struct and a new function** (`duoforge_observation_ext2`, `duoforge_battle_observe_ext2`, `revision` 2), never a changed size of the old one: the query takes no size argument, so a caller that allocated `sizeof(duoforge_observation_ext)` must never be overrun. Revision 1 stays in the library, with its function, for as long as the library claims it. A new revision is a **minor library version** too. A ceiling of about 256 bytes per revision keeps one struct cache-friendly; beyond it the content should go into a second, separate record.
5. **Setting a `supported` bit** (a step marking its mechanic) changes no struct and no API: no minor bump. The rule of the project's versioning for behaviour is unchanged.
6. **Introduction (step V1)** is a minor bump: it adds one function, the structs, `DUOFORGE_OBSERVATION_EXT_SIZE` (192), `DUOFORGE_OBSERVATION_EXT_REVISION` (1), the feature bits, the volatile and guard bits, the new enum values and `DUOFORGE_TYPE_*`. The library version is assigned at merge by the main session, like the data query API's (the expected number then is the next free minor).
7. **Size checks.**
   - The header carries `#define DUOFORGE_OBSERVATION_EXT_SIZE 192u`; a typedef of a negative-size array when `sizeof` differs checks it in C and in C++ (the header is also compiled as C++: `tests/header_check`); `static_assert` is not available there. `_Static_assert` in `src/state/observation.c` checks `sizeof` and the `offsetof` of every section and field, and that no section overlaps.
   - **Python layout pin:** `tools/layout/layout_dump.c` gets `STRUCT` entries for the five records and `CONSTANT` entries for the size, the revision and the bits Python uses; `python/duoforge/_layout.py` gets the dtypes with explicit offsets (`OBSERVATION_EXT`, itemsize 192) and the constants; the existing test `duoforge.python.layout` requires the dump and the dtypes to agree (names, offsets, sizes). Appending a field means adding it to both in the same PR.
8. **No fingerprint, no state schema:** the extension is a view. The context fingerprint, the semantics id and the state schemas do not change (tail revisions are decision 0015's business).

## 10. Encoder impact (`python/duoforge/features.py`)

- **Encoder version 3** appends a fixed block of **235 columns** to `obs_part` (the old 607 stay, in place and bit-identical for every observation that has no extension): `OBS_SIZE` goes from 607 to 842. A network trained on encoder 1 or 2 keeps its inputs through `as_encoder`, which drops the block for those versions. The block is the same size for every kind; it is zero under non-POOL kinds.
- **The old one-hots are not re-laid out.** Weather, terrain and ailment keep their known sets (NONE, RAIN, SUN; NONE, GRASSY, PSYCHIC; the six ailments). Under encoder 3 a new value (Sand, Snow, Electric, Misty, Tox) gives an all-zero old group, and its own column in the appended block. Under encoders 1 and 2 it is the `ValueError` of the existing rule ("a value this encoder does not know"): a POOL observation with Sand is refused explicitly by an encoder that cannot show it.
- **Columns, in order** (own side first, then foe, as the existing sides; names are appended by name, the form Learner v2's `FEATURE_NAMES` takes):

| Group | Columns | Names (templates) |
|---|---|---|
| global | 5: `weather_sand`, `weather_snow`, `terrain_electric`, `terrain_misty` (one-hot over the new values), `gravity_turns / 5` | `ext.global.<name>` |
| per side (own, foe) | 7: `aurora_veil / 8`, `stealth_rock`, `spikes / 3`, `toxic_spikes / 2`, `sticky_web`, `wide_guard`, `quick_guard` | `ext.<side>.<name>` |
| per position (2 per side) | 36: the 20 `volatiles` bits (one column each), `encore_slot` one-hot (5: none, 1 to 4), `disable_slot` one-hot (5), `stockpile / 3`, `perish / 3`, `ability_changed` and `ability_now / 255` (2), `type_now[0..1] / 18` (2) | `ext.<side>.pos<k>.<name>` |
| per member (6 per side) | 6: `tox`, `forme_changed`, `forme / 65535`, `item_changed`, `item_removed`, `item_now / 255` | `ext.<side>.mem<r>.<name>` |

  Count: 5 + 2 x (7 + 2 x 36 + 6 x 6) = 5 + 2 x 115 = **235**.
- **One-hot sizes:** weather 3 -> 3 (+2 in the block), terrain 3 -> 3 (+2), ailment 6 -> 6 (+1 per member), `encore_slot` 5, `disable_slot` 5. No old one-hot grows.
- **The mask:** the 64-bit `supported` is not an input. A checkpoint's config records the mask it was trained with (`"ext_supported"`); the encoder zeros the columns of every feature whose bit is clear in it, so a network never sees a field that was unsupported when it learned. A later library with more bits therefore does not change what an old network reads.
- **Fields are declared now,** so later mechanics do **not** change the encoder shape: columns of an unsupported feature are zero. A reserve field added later (growth rule 3) is a new encoder version.
- **The tracker** (decision 0016) fills the extension for a Showdown game exactly where its feature bit is set, from the lines of section 6; the existing byte-for-byte test against DuoForge's observation extends to the ext at every request of every committed POOL battle, for the features supported at that commit.

### 10.1 Encoder 3 as built (2026-10-03)

`python/duoforge/features.py` is encoder 3 with the block above, names and order as in the table (`EXT_COLUMN_FEATURES` gives each column's bit). The points the table leaves open were decided so:

- **Two sources.** Sand, Snow, Electric, Misty and Tox (bits 0, 1, 5, 32, 10: `BASE_VALUE_FEATURES`) come from the old observation, so they need no record. Every other bit reads the records: `encode_batch(observations, domains, ext, ext_supported)`, with `ext` from `Batch.observe_ext()` (one `duoforge_battle_observe_ext` per player; no batch C API).
- **No old group lies.** A new base value whose bit is clear in the mask raises `ValueError`, as under encoders 1 and 2, instead of an all-zero old group the network never saw.
- **Explicit refusals.** These raise `ValueError`:
  - a record bit in the mask without records;
  - records of another player, epoch or revision;
  - a mask bit the records' `supported` lacks (a library older than the network);
  - a field above its documented range.
  Records of revision 0 (every kind but POOL) leave the record columns zero for any mask.
- **Recharge.** The move slot of a Recharge option (`DUOFORGE_MOVE_SLOT_RECHARGE`, 5) is 5 / 4 in the slot part, the one value above 1. `slots_as_encoder` refuses it for encoders 1 and 2, which never saw it; `as_encoder` gives them their 607 columns and refuses the new base values.
- **Checkpoints.**
  - A format-2 checkpoint of encoder 2 is widened by name to encoder 3, with zero rows for the block and no mask (0).
  - A format-1 file keeps the width of its own version.
  - A new training run reads by default every feature the library supports under its data kind (`--ext-supported` sets the mask) and records it as `"ext_supported"`. A resumed run keeps its mask.
- **Live play.** The live tracker fills no records yet, so the live policy refuses a mask with a record bit. It plays a network whose mask has only base-value bits.

## 11. Size, in one table

| Section | Bytes | Used | Reserve |
|---|---|---|---|
| header (`revision`, `player`, `epoch`, `supported`) | 16 | 14 | 2 |
| `duoforge_field_ext` | 16 | 1 | 15 |
| 2 x `duoforge_side_ext`: 2 x 2 positions x 16 | 64 | 48 | 16 |
| 2 x `duoforge_side_ext`: 2 x 6 members x 4 | 48 | 36 | 12 |
| 2 x `duoforge_side_ext`: 2 x 8 side bytes | 16 | 12 | 4 |
| tail reserve | 32 | 0 | 32 |
| **Total** | **192** | **111** | **81** |

## 12. Evidence (for every step that sets a bit)

- **Information equivalence** (0007 section 7): paired states that differ only in what the viewer must not see (the foe's `throat_chop_turns` counter, a hidden Taunt or Encore counter, a Substitute's HP, a toxic stage) give byte-identical extensions for that viewer; planted leaks are reported by their pair. Under every non-POOL kind the extension is all zero, tested on the existing closure gate states.
- **Against the reference:** a recorded POOL battle per feature (spec -> `ps_trace.js` -> `trace_to_c.py`), with the tracker's extension and the engine's equal at every request, and the protocol lines of section 6.1 read from the trace. Negative controls: a field read from the foe's `[silent]` line, a counter exposed, a bit set without its battle.
- **Layout:** `duoforge.python.layout` and the size and offset asserts; a test that `supported` is zero and the rest of the struct zero until the first mechanic marks a bit, and that every set bit has a recorded battle.
- **Zero-ness:** a write of any nonzero reserved byte or field of a clear bit is an `E_INVARIANT` of the engine's own test.

## 13. Steps

1. **This note** (owner review: one bundled OK).
2. **V1, the structure:** the header section, the five records, the constants and the new enum values (no mechanic: all-zero except `revision` under POOL), the query and its checks, the size asserts, the layout pin, encoder 3 with its 235 zero columns, the zero tests. No behaviour change under any other kind.
3. **Per mechanic, tier by tier** (each with its engine step, its recorded battle and its tracker line): a step writes the field and sets its bit; nothing else changes.

### 13.1 Step AC1 (Trace, bit 2)

The first source of a changed ability, with the bit: `position_ext.ability_now` is the POOL tail's `ability_now` of the occupant (ability id + 1) when it is not the sheet's ability, set by the `-ability|POKEMON|NEW|OLD|[from] ability: Trace|[of] SRC` line, cleared when the occupant leaves, faints or Mega Evolves (`|switch|`, `|drag|`, `|replace|`, `|faint|`, `|-mega|`), public (the line is in both streams). The event is the existing ABILITY kind with cause ABILITY: `other` is the foe that was copied, `id2` the copied ability + 1 (the old ability is not in the event). The bit is exact, as section 7 asks: every other source of a changed ability (Skill Swap, Mummy, Wandering Spirit and the others) is an unmarked move or ability and fails with `E_UNSUPPORTED` before it can happen. Evidence: `duoforge.state.pool_ac1` reads the extension of both viewers after every step of the five `ac1_trace_*` battles against rows that `tools/reference/test_trace_to_c.py` derives from the committed protocol lines.

## 14. Points for the owner's OK

1. **Size 192 bytes with 81 reserved** (about 256 at most per revision), rather than a smaller struct: the reserve is the cheap way to stay additive.
2. **Everything declared now**, zero until supported, with a `supported` mask in the struct.
3. **Throat Chop public**, set for both players (owner decision 2026-10-02, changing the draft's own-side-only: the hitting move line is public, the secondary applies on every hit, and the `[silent]` start line is in both streams).
4. **Hidden durations not exposed**: presence, slot, or a public count only (Perish, Stockpile, Aurora Veil, Gravity).
5. **Overlay fields** (`ability_now`, `forme`, `item_now`, `type_now`): 0 means "as the old observation says", so the old fields stay valid and complete for every non-POOL consumer.
6. **A size growth is a new struct and function, never a bigger old struct.**
7. **Encoder 3 appends 235 columns** and leaves the old one-hots alone; the mask is a checkpoint property.
8. **Number:** this note is 0018 (0016 is the live adapter, 0017 reserved for Learner v2).
