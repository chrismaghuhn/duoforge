# 0005 — Requests, joint commands, information boundary, state v2

Status: **proposed**, implemented and tested in M2 (branch `chris/m2-requests-and-commands`). It becomes binding when the owner accepts the reviewed M2 change. M2 has **no combat**: a valid TURN, REPLACEMENT or PIVOT bundle is rejected atomically with `E_UNSUPPORTED`. Nothing here claims that the engine plays Pokémon.

Showdown citations are `path:line` at the pin `b2cb775b0616115b775534eaeff50300e1fc81fc` (decision 0004). No Showdown code is vendored.

## 1. Boundaries and request lifetime

- `boundary_kind` (u8, stored): TEAM_SELECTION 1, TURN 2, REPLACEMENT 3, PIVOT 4. Value 0 and >4 are invariant violations. REPLACEMENT and PIVOT exist **structurally only** (test fixtures build them white-box); no mechanic produces them before M3/M4. A PIVOT may request **both** sides at once (Champions: Emergency Exit plus an opposing Eject Button; `sim/battle.ts:2877-2915` sends one switch request to every side with a set flag).
- `request_epoch` (u32, stored): 1 at creation, `+1` on every accepted transition and on every rule-authorized re-prompt. The increment is checked first; at `UINT32_MAX` the operation fails with `E_EXHAUSTED` before any mutation. A response whose epoch differs from the current one is `E_STALE_EPOCH` (malformed input; the epoch is public, so the code reveals nothing).
- `request_mask` (u8, stored): bit `s` means side `s` must respond. Per side `requested_slots` (u8): bit `k` means position `k` needs a slot command. TEAM_SELECTION: mask 3, slots 0. TURN: slots = occupied positions (a fainted occupant is requested and forced to PASS). REPLACEMENT/PIVOT: structural.
- A `duoforge_request` for player `p` is built only from `p`'s authorized view: epoch, boundary kind, `requested` flag, slot mask and the exact **candidate count**.
- Requests, candidate enumeration and observation are **pure**: `rng.draws`, the state and the epoch are unchanged. Enumerating twice yields identical bytes.

## 2. Team selection (Reg M-C)

- Picks are an **ordered** list of `brought_count` roster indices; the first `min(2, brought_count)` are the leads in slot order a, b (`sim/side.ts:1061-1071`: exactly `pickedTeamSize` picks, each in range, no duplicates; Flat Rules set `Picked Team Size = Auto` = 4 for doubles, `data/rulesets.ts:41`, `sim/dex-formats.ts:336-341`).
- Domain: **all ordered tuples of distinct indices**, in lexicographic order. For 6 registered and 4 brought that is 360. The bench order matters only through Illusion, so 360 is the safe superset (decision: keep it complete rather than collapse to 180 and reopen it for Zoroark later).
- The bench order is stored (`brought_order`) and stays **private**; the opponent learns a member only when it is sent in.
- M1's setup `brought_mask`/`leads` path is **removed**. Every battle starts at TEAM_SELECTION with an empty brought set and empty positions. Mid-turn fixtures are built white-box in tests (a test-fixture path), never through the public setup.

## 3. Slot commands, joint side choices, enumeration order

Records are caller-visible, padding-free (static asserts) and zero-filled by producers.

```text
duoforge_slot_command {kind, move_slot, target, mega, reserve, reserved[3]}      8 B
duoforge_side_choice  {epoch, side, kind, pick_count, picks[6], reserved[3],
                       slots[2]}                                                 32 B
duoforge_decision_bundle {epoch, response_mask, reserved[3], responses[2]}      72 B
```

Slot kinds: NONE 0 (unrequested slot), MOVE 1, SWITCH 2, PASS 3. Choice kinds: TEAM_SELECTION 1, SLOTS 2.

**Per-slot domain at TURN** (occupied position, occupant `hp > 0`):

1. MOVE for each move slot `k < move_count` with `pp > 0`, for each selectable target of its class (section 4), with `mega = 0` and, if the occupant is `mega_capable` and the side has not used Mega, also `mega = 1`. Order: move slot, then target, then mega.
2. SWITCH to each reserve: brought, not active in either position, `hp > 0`; ascending roster index.
3. A slot whose occupant is alive but has no selectable move would need Struggle (M3). The request fails with `E_UNSUPPORTED`; the state remains representable and checkable.

An empty position or a fainted occupant at TURN is forced to PASS (Showdown: a fainted active passes, `sim/side.ts:1343`).

**Per-slot domain at REPLACEMENT/PIVOT:** SWITCH candidates as above. Per side, exactly `min(requested slots, available reserves)` slots switch and the rest PASS (`sim/side.ts:1120-1126`, `1338-1341`). Which slots pass is the player's choice, so the joint domain lists every assignment.

**Joint side choice:** the domain of slot a is the outer loop and slot b the inner loop; a pair is dropped when both switch to the same reserve (`sim/side.ts:961`) or both declare Mega (`sim/side.ts:780-781`). Mega is only a MOVE modifier, never on a switch. `mega_used` is a side-wide flag in the state; it is a **public** fact.

The accepted set **is** the enumerated set: `step` validates a response by structural checks and then by byte-equality with an enumerated candidate of that side. Validation never reads the opponent's data.

## 4. Target classes and selectors

Context v2 carries a synthetic table `move_target_class[move_count]`:

| Class | Value | Selectable positions for actor at side `s`, slot `k` |
|---|---|---|
| NORMAL | 1 | ally and both foe positions |
| ANY | 2 | every position except self |
| ADJACENT_ALLY | 3 | ally |
| ADJACENT_ALLY_OR_SELF | 4 | self, ally |
| ADJACENT_FOE | 5 | both foe positions |
| SELF, ALL_ADJACENT_FOES, ALLY_SIDE, ALL | 6, 7, 8, 9 | none (`target = DUOFORGE_TARGET_NONE`) |

Classes 1 to 5 are Showdown's `CHOOSABLE_TARGETS` (`sim/battle-actions.ts:3`); the position rules are `validTargetLoc` (`sim/battle.ts:2399-2432`) with `activePerHalf = 2`, where every position is adjacent. Selectors are **absolute flat positions** `side*2+slot`, ascending. Occupancy does not shrink the set: a selectable target is not a resolved target (DECISION_CONTRACT section 3; Showdown accepts an empty location and retargets at execution).

The 36 distinct moves of both teams have classes normal 21, self 4, allAdjacentFoes 4, any 3, allySide 3, all 1 (`data/moves.ts` at the pin; `data/mods/champions/moves.ts` overrides fakeout, ironhead, makeitrain and protect without changing their targets). The fixture table T1 mirrors this list in the order of decision 0004.

## 5. Simultaneous choices, sealed commitments, honest execution

- `duoforge_battle_step` takes one bundle with responses for exactly the requested sides (`response_mask == request_mask`). A host collector may gather them separately; it never touches combat state.
- Sealed commitments live in the state: per side `sealed` (0/1) plus the two slot commands. TEAM_SELECTION and REPLACEMENT: none. TURN: `sealed[s] == 1` iff side `s` is not requested (a re-prompt of the other side). PIVOT: structural, any side.
- Rule-authorized re-prompt (DECISION_CONTRACT section 6) is a **successful result kind**, not a status. No M2 mechanic triggers it; the transition exists as the internal `dfi_reprompt_side` (epoch +1, `request_mask` = that side, the other side's accepted choice sealed) and is tested white-box as its own category, separately from malformed-input atomicity.
- A valid TEAM_SELECTION bundle performs the mechanics-free transition to TURN. A valid TURN/REPLACEMENT/PIVOT bundle returns `E_UNSUPPORTED` **after** full validation and mutates nothing. There is no fake success.

## 6. Information profile (prototype)

- **Open team sheets:** species/forme, item, ability, moves and nature of all registered members are open (`sim/battle.ts:3184-3224`: `showOpenTeamSheets` packs species, item, ability, moves, nature for `champions`, gender, level; `evs` and `ivs` are nulled). Stat Points and IVs are never revealed. In v2 the open fields that exist are `species_id`, `move_id[]` and the synthetic `mega_capable` (stone-holder stand-in: an item is open).
- **Gender:** default **open** (Showdown reveals it at team preview and in the sheet). No v2 field carries it; M3 adds it with real data. The owner may restrict it to battle-relevant formes later.
- **Brought set and order:** private until a member is sent in. Per player knowledge `seen_mask` of the opponent's roster: a member enters it when it occupies a position. Invariant: `seen_mask` is a subset of `brought_mask` and every foe occupant is seen.
- **HP:** own side exact. Opponent: `floor(100*hp/hp_max)`, minimum 1 while alive, 0 when fainted, with a colour flag at exactly 20 (`hp*5 > hp_max` gives YELLOW else RED) and 50 (`hp*2 > hp_max` gives GREEN else YELLOW) (`sim/pokemon.ts:2060-2073`). Unseen members: tagged UNKNOWN.
- **PP:** own exact; opponent UNKNOWN (tag). Values behind an UNKNOWN tag are zero and carry no information.
- `mega_used` of both sides and the occupants of all four positions are public.
- Never exposed: the opponent's sealed commitment, bench order, exact HP, PP, RNG, digests.
- **Known prototype limits (M3 work):** a seen but benched foe shows its *current* percent because no bench HP change exists yet; once one exists (Wish, Healing Wish), the knowledge state must snapshot the last-seen value instead. The observation carries only the viewer's own `requested` flag, not whether the opponent must also act at a pause. Gender, item, ability and nature fields arrive with real data in M3. A re-prompt does not change the re-prompted side's domain yet (the trapping mechanic that would is M3/M4).

## 7. Output convention (resolves the open decision)

Variable-size outputs use **exact count in the request plus required-size out-parameter on `E_CAPACITY`**:

1. `duoforge_request.candidate_count` is the exact domain size and depends only on the acting player's view.
2. `duoforge_battle_candidates(..., buffer, capacity, &count)` with `capacity < count` returns `E_CAPACITY`, writes **only** `*count = required` and no buffer byte. This is the single deviation from M1's "no out-parameter on error", limited to model-facing queries, because the count is itself authorized information.
3. `DUOFORGE_MAX_CANDIDATES` (784) is the profile bound: max(720 ordered 5- or 6-tuples of 6; 28 x 28 joint slot choices). A caller may allocate it once.

A bounded iterator was rejected: it would add cursor state without a measured need. A context-maximum-only convention was rejected: the exact count is cheap and the domain is small.

## 8. Status codes and information-safety rules

New codes: `E_UNSUPPORTED 11` (documented not-implemented path), `E_STALE_EPOCH 12`. Malformed bundles otherwise return `E_INVALID_ARGUMENT`. Engine-side failures in model-facing calls surface only as `E_INVARIANT`. Rules 1 to 4 of decision 0002 section 9 apply; paired-information tests compare statuses, counts and bytes.

## 9. Context v2, state v2, semantics 2

- **Context config v2:** M1 fields plus `move_target_classes` (pointer to `move_count` bytes, each 1..9). The context copies the table; the caller's memory is read once.
- **Canonical context bytes v2 (63 B):** v1 preimage with schema 2 / semantics 2, followed by `SHA-256(table)`.
- **State v2 (438 B):** v1 header, then `boundary_kind` u8, `request_mask` u8, `request_epoch` u32; per side (176 B): `member_count`, `brought_mask`, `requested_slots`, `mega_used`, `sealed`, `seen_mask`, `brought_order[6]`, positions 2x5, sealed slot commands 2x5, members 6x24 (`species`, `hp`, `hp_max`, `move_count`, `mega_capable`, moves 4x4). Layout table: `src/codec/state_codec.h`.
- **Invariants v2** extend the v1 order: boundary kind, epoch nonzero, request mask 1..3, per side (v1 checks; `mega_capable`/`mega_used`/`sealed` in {0,1}; `brought_order` consistent with the mask; TEAM_SELECTION implies empty mask, empty positions, no seal; requested slots per kind; sealed rules of section 5; sealed command ranges), then per player `seen_mask` rules.
- **Registry:** CONTEXT (1) schema 2, BATTLE_STATE (2) schema 2, semantics 2 = "duoforge-m2-requests". The v1 goldens become "rejected: schema 1" tests. The oracle `tools/state_model/state_v2_model.py` reproduces the goldens, the invariant order and every domain (counts, order, bytes) independently of the C code.

## 10. Evidence (local, 2026-09-30)

| Test | Covers |
|---|---|
| `duoforge.request.domain` | Every fixture and player against the oracle (counts, order, bytes), stable enumeration, purity, output convention, Struggle UNSUPPORTED, Mega constraints, bounds 720 and 636 (both below 784). |
| `duoforge.request.step` | Step reproduces the white-box fixtures, every enumerated pick pair accepted (72 on G7), malformed-input atomicity table, honest UNSUPPORTED for TURN/REPLACEMENT/PIVOT, exhaustion, re-prompt as its own category. |
| `duoforge.request.contract` | Snapshot at every boundary kind (and a re-prompted TURN), late and stale responses at every boundary, two-side replacement and pivot, one-side pivot continuation. |
| `duoforge.request.information` | Observation vs oracle, perspective rules, HP tables, nine paired-information cases with identical statuses, counts and bytes, legitimate differences visible. |
| `duoforge.state.*`, `duoforge.codec.*` | v2 invariants (34 ids), goldens, 41 targeted edits, 335,070 single-byte mutations with exact per-region counts, 8,596 setup creates. |

Negative controls (12, run locally on 2026-09-30, listed in the M2 completion report): each breaks one guarantee (reserve conflict, double Mega, enumeration order, foe PP leak, foe bench-order leak, mutation before validation, stale-epoch checks, query purity, E_CAPACITY buffer write, re-prompt sealing, seen-mask invariant, entry disclosure) and turns the named test red.

## 11. Alternatives considered

- Player-relative target selectors: rejected; absolute positions keep engine identity independent of rendering (decision 0002 section 4).
- Shrinking target sets by occupancy: rejected (section 4).
- Collapsing the bench order (180 picks): rejected (section 2).
- Struggle placeholder at all-pp-0: rejected as a fake command; `E_UNSUPPORTED` instead.
- A union in `duoforge_side_choice`: rejected; a flat record keeps the padding/zero-fill rule checkable.
