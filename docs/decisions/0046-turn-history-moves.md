# 0046 - Turn-history moves: Lash Out, Assurance, Metal Burst (G88)

Status: **proposed** (phase 1, design only: no engine code, no lock use until the lead approves). Lane A batch 6, builder H20, decision 0015 letter **5cl**. Builds on 0015 (the POOL kinds, the tail rev 5 position byte), 0023 (determinisation and the public state: exact foe HP is hidden, the hypothesis carries it), 0007 (the player view), and the Alluring Voice design of step G72b (5ce part 2: `statsRaisedThisTurn` as bit 1 of `position_flags`).

Pin: Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`). No Champions override of `lashout`, `assurance` or `metalburst` in `data/mods/champions/` (checked: moves.ts, scripts.ts, conditions.ts, abilities.ts, items.ts). The Champions hit loop (`data/mods/champions/scripts.ts:561-568`) and clear-volatile (`scripts.ts:163-168`) repeat the main code exactly.

## 1. Pin semantics

### Shared flags (the three moves read them; nothing else reads them)

- **Reset.** `sim/battle.ts:1677-1683` (inside `endTurn`, `:1623`, after `turn++`): when `this.turn !== 1`, `statsRaisedThisTurn = false`, `statsLoweredThisTurn = false`, `hurtThisTurn = null`. `endTurn` runs once per turn, from `turnLoop` (`battle.ts:2955`) after the queue is empty: after the residual action (`battle.ts:2811-2817`, `Residual` then `|upkeep|`) and after any faint replacement (`makeRequest('switch')` at `:2912` returns before `endTurn`). So a replacement's switch-in hazard damage is cleared with the rest. The `|turn|` line follows at `:1785`.
- **Switch-out.** `sim/battle-actions.ts:123-124` clears the raised and lowered flags of `oldActive`; `sim/pokemon.ts:1548-1550` (inside `clearVolatile`, `:1508`) clears `attackedBy`, `hurtThisTurn`, `lastDamage` for the incoming Pokemon.
- **Faint** does not clear them (the fainted Pokemon keeps its record until replaced).

### Lash Out (`data/moves.ts:10048-10066`)

- Power: `onBasePower` (`:10055-10059`) returns `chainModify(2)` when `source.statsLoweredThisTurn` (base 75, so 150).
- **Set:** `sim/battle.ts:2086`, in `boost()` (`:2020`), `if (success) { if (some value < 0) target.statsLoweredThisTurn = true }`. The values are the *deltas after the cap*: `getCappedBoost` (`sim/pokemon.ts:1210-1219`) turns each request into the change actually made, and `boostBy` (`:1221-1230`) applies it. So the flag means "a real drop of at least one stage in this boost call". A stat at -6 that is asked to drop adds 0 and does not set the flag. Any source counts (own move self-drop, a foe's Intimidate, Parting Shot, Defiant-type reactions), because all of them go through `boost()`.
- **Not set** by `clearBoosts` and `setBoost` (`sim/pokemon.ts:1232-1244`: Haze, Clear Smog, switch-out resets). A Mirror Armor, Clear Body or Mist refusal returns no change, so no flag.
- **Cleared:** `:1679` (turn boundary) and `battle-actions.ts:124` (switch-out).

### Assurance (`data/moves.ts:643-660`)

- Power: `basePowerCallback` (`:648-653`): `target.hurtThisTurn` truthy gives 120 (base 60 doubled); else 60.
- **Set:** `sim/battle.ts:2137-2138`, in `spreadDamage` (`:2091`; the per-target loop at `:2100-2175`): after `target.damage()` returns `targetDamage`, `if (targetDamage !== 0) target.hurtThisTurn = target.hp`. So: any spread damage that removed HP, from any source (a move, a foe's or own ally's attack, Life Orb, Rocky Helmet, residual poison/burn/Sand, recoil, Leech Seed, Berry-like `damage` through `spreadDamage`). The stored value is the HP after the hit, so Assurance reads only truthiness: an HP of 0 reads as not hurt (a fainted target, which cannot be chosen anyway).
- **Not set** by `directDamage` (`battle.ts:2207-2259`): it calls `target.damage()` at `:2245` and never sets `hurtThisTurn`. Its callers in `data/moves.ts` are at `:1229, 2515, 3293, 5291, 16186, 18325` (among them the Substitute HP cost at `:18325`, and the strugglerecoil and confusion self-hits in `directDamage`'s own switch at `:2246-2256`). Their `-damage` line has the same text as a move's damage line (`:2254`).
- **Not set** by a Substitute-absorbed hit: the Substitute's `onTryPrimaryHit` (`data/moves.ts:18341-18370`) subtracts from the sub's HP and returns `HIT_SUBSTITUTE`; no `target.damage()` call.

### Metal Burst (`data/moves.ts:11655-11683`)

- **Power:** `damageCallback` (`:11657-11664`): `getLastDamagedBy(true)`; if found, `(lastDamagedBy.damage * 1.5) || 1`; else 0. Fixed damage: no crit, no random roll, no type multiplier (type Steel has no immunity).
- **Fail:** `onTry` (`:11670-11673`): `if (!lastDamagedBy?.thisTurn) return false`. So a turn with no non-ally numeric hit on this Pokemon fails (`-fail`); there is no fallback target.
- **Target:** `onModifyTarget` (`:11674-11681`): `targetRelayVar.target = this.getAtSlot(lastDamagedBy.slot)`, the occupant of the attacker's *slot* at use time (`battle.ts:1611-1617`), not the attacker itself. A switched-out attacker's slot may hold its replacement.
- **The record** (`sim/pokemon.ts:917-942`): `gotAttacked` (called from `battle-actions.ts:990-997`, and the Champions copy at `scripts.ts:561-568`) pushes `{source, damage: number or 0, damageValue: the hit result, thisTurn: true, slot: source.getSlot()}`. `getLastDamagedBy(true)` keeps entries whose `damageValue` is a **number** and whose source is **not an ally** (`!this.isAlly`, `:935-942`), and returns the last one.
- **The hit result**: a number when `target.damage()` removed HP (the capped HP lost, `pokemon.ts:1595-1605`, and any Focus Sash / Sturdy / Endure cap applied first); `true` for a Substitute-absorbed hit (`battle-actions.ts:1062-1065` maps `HIT_SUBSTITUTE` to `true`), which is not a number, so a Substitute hit never feeds Metal Burst.
- **Aging:** the entries of the side's active Pokemon get `thisTurn = false` at `endTurn` (`battle.ts:1703-1709`); entries of inactive sources are spliced there. Mid-turn the entry stays `thisTurn: true` even after its source switches out.
- **Edge (to check in phase 2):** a numeric 0 result (a hit that removes no HP) is a number, so it passes `getLastDamagedBy`, and then `(0 * 1.5) || 1` gives power 1. Whether a 0-HP-loss numeric hit can occur in the pool is open; the design stores the value so both cases are exact.

## 2. The minimal state

Engine state is the tail rev 5 per-position `position_flags` byte (`src/state/battle_internal.h:259-268`) plus the reserve for one value. Current bits (G72b): bit 0 Healing Wish (zero), bit 1 `DFI_POSFLAG_STATS_RAISED`, bits 2-3 Dragon Cheer stage; bits 4-7 are zero by invariant (`src/state/invariants.c:587-590`, `DFI_POSFLAG_VALID_MASK 0x0F`).

- **Lash Out:** `DFI_POSFLAG_LOWERED` = bit 4 (0x10). Set in `dfi_boost` (`src/combat/turn.c:1205-1213`, next to the raised bit) where `after < before`, POOL only. Cleared at the turn boundary (next to `turn.c:9641-9643`) and with the occupant (`dfi_tail_clear_occupant`). One bit. No new byte.
- **Assurance:** `DFI_POSFLAG_HURT` = bit 5 (0x20). Set where a spread damage removes HP (any source, after the cap, POOL only); **not** for the directDamage paths (see section 3). Cleared as above. One bit.
- **Metal Burst:** the last non-ally numeric hit on this position. Needs three things: the valid bit (implied by the amount being nonzero, see the edge above), the attacker's foe position (1 bit: the attacker is always on the other side, because an ally's hit is excluded; so the position is 0 or 1 within the foe's active pair), and the damage amount (up to the max HP, so 16 bits). The attacker's position fits bit 6 (0x40) of `position_flags`. The amount needs a 2-byte per-position record, i.e. 8 bytes for the four flat positions, which are **bytes 8-15 of the rev 5 reserve** (free via HauptSession, not yet assigned). Bit 7 stays zero.
- **Reset:** the Metal Burst record is cleared at the turn boundary (equivalent to the pin: a record from an earlier turn is never valid, since `thisTurn` is false) and with the occupant. Writing it: only where `gotAttacked` would push a numeric, non-ally entry (the spread path with `damage > 0`).
- **Codec:** the flags stay in the tail's `position_flags` byte (`src/codec/state_codec.c:84, 210`); the amount bytes go to the reserve, read and written at fixed offsets (new `DFI_ENC_*` constants, appended, not inserted). Invariants: bits 0 and 7 zero; bits 4-6 only with an occupant; the MB amount zero with bit 6 zero (or the amount nonzero with an occupant, and bit 6 only with a nonzero amount); the mirror in `tools/state_model/state_v3_model.py` (`TAIL_POS_REV5_FIELDS` at `:105`, `position_flags_valid` at `:975`, the flags-only occupant rule at `:1055-1056`).
- **Only POOL kinds** write these bits; other kinds keep the whole tail zero (`dfi_check_tail`, as for G72b).

Reuse: none of the three is an existing field. The raised bit (G72b) is the template for Lash Out's lowered bit and Assurance's hurt bit, and `dfi_boost`'s `after`/`before` test already gives "real change".

## 3. Information safety (decisions 0007, 0023)

### Lash Out and Assurance: derivable from the public log?

- **Lash Out (lowered):** derivable. Every real drop through `boost()` with a non-null effect prints `-unboost` (`battle.ts:2040-2083`, the `msg` line, `if (boostBy)`), and the Ability/Item/Move source is printed. **Check in phase 2:** a `boost()` with `effect` null prints nothing (`if (!effect) break;`, `:2062`), and such a drop would set the pin flag with no line. I found no such call in the moves of the pool yet (grep `boost(` with no effect); if one exists, the bit is not derivable and that row is refused. The record can carry the bit as a public fact, since it is a function of the public boost lines.
- **Assurance (hurt):** **not** derivable from the damage text alone. `-damage|P|hp` is printed by spreadDamage (move hit, residual, recoil) and by directDamage (the Substitute cost and the other callers in section 1, not all identified yet; the strugglerecoil and confusion self-hits are two of them); the directDamage ones do not set `hurtThisTurn`. The bit is derivable from the public log *only* with the move context (the line after `move|...|Substitute` or `|move|...|Belly Drum`, and the `[from] confusion` and `[from] recoil` tags). Proposal: the engine sets the hurt bit only in the spread path; the record carries that bit as public (it is a function of public events, the same events the view shows); the rebuild takes it from the record. No refusal needed if the engine's damage events carry the spread/direct distinction. **To verify in phase 2:** whether the C `DAMAGE` events distinguish the two paths (`src/combat/turn.c`, the Substitute cost at `:5249-5300` emits a DAMAGE event with cause MOVE, id2 Substitute). If they do not, the bit is refused by name (a cause), not guessed.
- Round trip: `from_view(public(s,p),h) == s` (0023 tests) requires the record to carry both bits exactly, for both players. They are public, so the foe's bits are carried as they are.

### Metal Burst: the foe's exact damage (HauptSession requirement)

- **Own Metal Burst user** (U is ours; the attacker A is the foe): the damage is our own HP lost, exact in our view (own HP is exact in the record, the `-damage` line shows our exact HP before and after). The record carries the amount for our own row, from the true state.
- **Foe Metal Burst user** (U is the foe, the attacker A is ours): the amount is the foe's HP lost, and the public record shows only the foe's floor percent (0023 §1, the 20 and 50 flags). The record must **not** carry it: the foe's row gets a withheld amount (the same masking as the foe's exact HP, 0023 section 2 "masked canonical encoding", `DUOFORGE_VIEW_HIDDEN`), and the valid bit and the attacker's position stay (both public: the attacker's identity and `thisTurn` are visible).
- **How the search recomputes it (the path):** `duoforge_battle_hypothesis` (the sampler, 0023 section 2: "u picks among the values that the shown percent and flag allow") draws the foe's exact HP per member (`duoforge_hypothesis.hp[]`, `include/duoforge/duoforge_view.h:88`). That is the **current** HP only. The amount needs the HP **before** the last hit as well, which the hypothesis does not carry. So the path is: (a) **option A**: a new hypothesis field (a new revision of `duoforge_hypothesis`, one value per foe member, drawn as "the HP lost by the last hit" from the range the two shown percents allow, the same way as `hp[]`), read by `duoforge_battle_from_view` (`src/state/view.c:642-...`, after the stat-point and pick checks, where it writes the foe's `hp[]` at `:705-710`) to write the record's amount; the rebuilt world then runs Metal Burst with that value. Or (b) **option B** (proposed for phase 2): refuse. `duoforge_battle_public` and `duoforge_battle_from_view` refuse with a named cause when a **foe** member that has Metal Burst among its open move ids (`ob->sides[s].members[occ].move_ids`, `view.c:229-249` pattern) holds a numeric, non-ally record from our side this turn (decided only from view fields: the open move list and the public hit lines). The determinisation then never has to invent the amount. Option B is smaller and needs one new cause value (lead assigns); option A needs a hypothesis revision (lead approval).
- **Recomputation path for the own U**: none, the amount is in the record.
- **The target** (`getAtSlot`, a public switch history): the target is the occupant of the attacker's slot. The slot is public (`-switch`/`drag` lines). If the attacker is no longer active, the target is whoever stands there now: derivable, but a case we do not want in phase 2. **Proposal: refuse** E_UNSUPPORTED when the attacker is not active at use (decided from the record's `thisTurn` and the public switch history), and model only the attacker-still-active case.

### Cause summary

| Case | Decided by | Value | Proposal |
|---|---|---|---|
| Lash Out lowered bit | public boost lines | public | carry; refuse only a null-effect drop if one exists |
| Assurance hurt bit | public damage lines + move context (spread vs direct) | public | carry; verify the DAMAGE event distinction in phase 2 |
| Metal Burst, own user | own HP (exact) | public | carry the amount in the own row |
| Metal Burst, foe user, amount | not public (floor percent only) | hidden | option A (hypothesis field) or option B (named refusal) |
| Metal Burst, attacker switched out | public switch history | public | refuse E_UNSUPPORTED |

## 4. New public values (requests; HauptSession assigns numbers, nothing picked here)

- **Position flag bits** 4 (lowered), 5 (hurt), 6 (Metal Burst attacker position): no new byte, but the invariant mask widens (`DFI_POSFLAG_VALID_MASK`, `invariants.c:589`) and the Python mirror follows. **Lead to approve.**
- **Reserve bytes 8-15** (four 2-byte amounts, one per flat position): **lead to approve** (HauptSession assigns the reserve; G82/G84/G86 may want bytes too).
- **Handler ids**: `DFI_SPECIAL_LASH_OUT`, `DFI_SPECIAL_ASSURANCE`, `DFI_SPECIAL_METAL_BURST` (the pool table generator, `gen_closure.py --pool`; the UNMODELED id moves). **Lead assigns.**
- **Cause** for Metal Burst option B (only if option B is chosen). **Lead assigns** (`DUOFORGE_PUBLIC_CAUSE_*`).
- **Hypothesis revision** (only for option A). **Lead decides.**
- **No new event kind, no volatile, no `flags3` bit, no VIEWEXT feature** is needed for Lash Out or Assurance unless the lead wants the flags observed (then one VIEWEXT bit per feature, with the mask pin). Lead to say.

## 5. Recordings and mutants (planned, not run)

POOL battles, six members a side, unique items, real genders, marked content only, learnsets from `data/mods/champions/learnsets.ts` (Assurance and Lash Out are listed for several species there, e.g. Umbreon, Machamp, Kangaskhan, Heracross, Tauros; Metal Burst is checked in phase 2). Sitrus speed tie on both sides in at least one battle per move.

- **Lash Out:** (1) own self-drop then Lash Out doubles (lowered on the user's turn); (2) a foe's drop (Intimidate or Parting Shot) on the user, then Lash Out next turn is not doubled (reset); (3) a drop blocked by a Mirror Armor or a stat at -6: no doubling; (4) a switch-out and return: no doubling; (5) a Haze turn: no doubling (clearBoosts sets nothing).
- **Assurance:** (1) hit by an ally's spread damage (Earthquake) earlier in the turn: doubled; (2) hit only by a Substitute: not doubled; (3) hit by its own Substitute cost at the Substitute user: not a case (the Substitute user is not the target); (4) residual damage (poison) at the end of the previous turn: reset, not doubled; (5) a Life Orb or Rocky Helmet hit on the target: doubled.
- **Metal Burst:** (1) hit by a foe, then Metal Burst on that foe (ours): amount 1.5x; (2) hit by a foe with a Substitute absorbing it: fail; (3) hit by an ally only: fail; (4) attacker switches out (U-turn), the slot holds its replacement: target is the replacement (only if option A or the refusal path is not chosen); (5) hit with Focus Sash: amount is the HP lost (1 HP lost, 1.5 power) (exact); (6) foe Metal Burst user under option B: refused.

Mutants (one edit each, `turn.c` or `view.c`): the lowered bit set on the requested keys (not the delta); the hurt bit set on directDamage too; the hurt bit read on the wrong side; the MB amount stored after the cap instead of before (the same here, check); the MB attacker's position off by one; the reset gate `turn !== 1` removed; the switch-out clear removed; the ally filter removed; the Substitute hit counted as a hit. Caught counts reported in phase 2.

Campaign: `diff_driver.py random`, about 300 battles, the three teams with the rows (POOL), per the lock budget (targeted subsets only locally; the full run on GitHub).

## 6. Refusals (E_UNSUPPORTED, named)

- Metal Burst with a foe Metal Burst user whose last hit came from our side this turn (option B; under option A, the amount comes from the hypothesis and the refusal is dropped).
- Metal Burst with its attacker not active at use (the slot now holds another Pokemon; the pin's target is that Pokemon, not modelled in phase 2).
- Lash Out or Assurance only if the verification in section 3 fails (a null-effect `boost()` drop, or a DAMAGE event that does not carry the spread/direct distinction).

## 7. Drop option (if the lead prefers less state)

Metal Burst is the one that needs the most: a 2-byte-per-position reserve, a withheld foe value and either a new hypothesis field or a new cause. If the lead does not approve bytes 8-15 or option A/B, drop Metal Burst with this reason ("the foe's exact damage is not public, 0023 section 1, and the hypothesis carries only the current HP") and keep Lash Out and Assurance (one bit each, already public, no new byte, no new value beyond the handler ids and the mask widening).

## 8. Open points for the lead

1. Bits 4-6 and the reserve bytes 8-15: approve, or give other places.
2. Metal Burst: option A (hypothesis revision) or option B (named refusal), or drop.
3. The handler ids and the cause numbers (HauptSession).
4. Whether the record should carry Lash Out and Assurance as bits (round trip) or whether they stay internal (then they need the derivation check in section 3 to pass in phase 2).
