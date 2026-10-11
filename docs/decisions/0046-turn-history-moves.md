# 0046 - Turn-history moves: Lash Out and Assurance (G88); Metal Burst deferred

Status: **proposed, revised after the lead's decisions** (phase 1 proposal of 2026-10-10, revised the same day). Lane A batch 6, builder H20, decision 0015 letter **5cl**. Builds on 0015 (POOL kinds, the tail rev 5 position byte), 0023 (determinisation and the public state), 0007 (the player view), and the Alluring Voice design of G72b (5ce part 2: `statsRaisedThisTurn` as bit 1 of `position_flags`, `DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN` = 32, a PIVOT refusal).

Pin: Showdown b2cb775 (`C:/Dev/src/pokemon-showdown`). No Champions override of `lashout`, `assurance` or `metalburst`. The Champions hit loop (`data/mods/champions/scripts.ts:561-568`) and clear-volatile (`scripts.ts:163-168`) repeat the main code.

## Decisions taken (lead, 2026-10-10)

1. Bits: `position_flags` bit 4 is taken by Destiny Bond (G76, batch 5, not yet on main). This step uses **bit 5 = LOWERED_THIS_TURN** and **bit 6 = HURT_THIS_TURN**. Bit 7 stays free. Reserve bytes 8-15 are **not** approved.
2. **Metal Burst is dropped from G88** and deferred to a later step. Its pin analysis (section 6) is kept as the basis.
3. Lash Out and Assurance follow the Alluring Voice precedent: the bits are cleared in `endTurn` before the `|turn|` line, so they are zero at every turn start. They matter only at a mid-turn decision point (PIVOT). The public record and `duoforge_battle_from_view` **refuse at a PIVOT** with a new named and counted cause, whenever an active Pokemon of either side knows Lash Out or Assurance. The check reads only view fields (`occupant[p]` and `members[occ].move_ids`, as in G72's `dfi_view_raised_risk`), never the engine queue. The bits are **not** carried in the record (internal, no round trip). The cause number is requested from HauptSession; until it is given, the code uses a named placeholder and no number is picked here.
4. Handler ids `DFI_SPECIAL_LASH_OUT` and `DFI_SPECIAL_ASSURANCE` are internal and renumbered in merge order (no HauptSession). `UNMODELED` stays last.
5. Assurance sets HURT only on the spread path (`spreadDamage`), not on `directDamage` and not on a Substitute-absorbed hit. The C DAMAGE events need not distinguish spread from direct, because the view refuses at a PIVOT.
6. Phase 2 is approved for Lash Out and Assurance, with the recordings and mutants in section 5.

## 1. Pin semantics

### Shared flags

- **Reset.** `sim/battle.ts:1677-1683` (inside `endTurn`, `:1623`, after `turn++`): when `this.turn !== 1`, `statsRaisedThisTurn` and `statsLoweredThisTurn` are cleared, and `hurtThisTurn = null`. `endTurn` runs once per turn from `turnLoop` (`battle.ts:2955`), after the queue is empty: after the residual action (`battle.ts:2811-2817`: `Residual`, then `|upkeep|`) and after any faint replacement (`makeRequest('switch')` at `:2912` returns before `endTurn`). The `|turn|` line follows at `:1785`.
- **Switch-out.** `sim/battle-actions.ts:123-124` clears the raised and lowered flags of `oldActive`. `sim/pokemon.ts:1548-1550` (in `clearVolatile`, `:1508`) clears `hurtThisTurn`, `attackedBy` and `lastDamage` for the incoming Pokemon.

### Lash Out (`data/moves.ts:10048-10066`)

- Power: `onBasePower` (`:10055-10059`) returns `chainModify(2)` when `source.statsLoweredThisTurn` (base 75, so 150).
- **Set:** `sim/battle.ts:2086`, in `boost()` (`:2020`, flag block `:2084-2087`): `if (success) { if (some value < 0) target.statsLoweredThisTurn = true }`. The values are the **post-cap deltas**: `getCappedBoost` (`sim/pokemon.ts:1210-1219`) turns each request into the change actually made, and `boostBy` (`:1221-1230`) applies it. So the flag means a real drop of at least one stage in one `boost()` call, from any source.
- **Not set** by `clearBoosts` and `setBoost` (`sim/pokemon.ts:1232-1244`: Haze, Clear Smog, switch resets).

### Assurance (`data/moves.ts:643-660`)

- Power: `basePowerCallback` (`:648-653`): 120 if `target.hurtThisTurn` is truthy, else 60.
- **Set:** `sim/battle.ts:2137-2138`, in `spreadDamage` (`:2091`; the per-target loop `:2100-2175`): after `target.damage()` returns `targetDamage`, `if (targetDamage !== 0) target.hurtThisTurn = target.hp`. So any spread damage that removed HP, from any source. The stored value is the HP after the hit, so Assurance reads truthiness (an HP of 0 reads as not hurt, a case that cannot be targeted anyway).
- **Not set** by `directDamage` (`battle.ts:2207-2259`, `target.damage()` at `:2245`, no flag). Callers include the Substitute cost (`data/moves.ts:18325`) and the strugglerecoil and confusion self-hits (`battle.ts:2246-2256`); others not all identified.
- **Not set** by a Substitute-absorbed hit (`data/moves.ts:18341-18370`, `onTryPrimaryHit`, returns `HIT_SUBSTITUTE`; no `target.damage()` call).

## 2. The minimal state (this step)

`position_flags` (`src/state/battle_internal.h:259-268`): bit 0 Healing Wish (zero), bit 1 `DFI_POSFLAG_STATS_RAISED`, bits 2-3 Dragon Cheer stage. This step adds:

- **`DFI_POSFLAG_LOWERED` = bit 5 (0x20).** Set in `dfi_boost` (`src/combat/turn.c:1205-1213`, next to the raised bit) where `after < before`, POOL only. Cleared at the turn boundary (next to `turn.c:9641-9643`) and with the occupant (`dfi_tail_clear_occupant`).
- **`DFI_POSFLAG_HURT` = bit 6 (0x40).** Set where a spread damage removes HP (after the cap, POOL only, the spread path only, decision 5). Cleared as above.
- No new byte, no reserve byte. Bits 0 and 4 stay as they are on main (bit 4 is Destiny Bond on batch 5's branch); bit 7 stays zero.
- **Invariant:** `DFI_POSFLAG_VALID_MASK` widens from `0x0F` to `0x6F` (bits 0-3, 5, 6); the new bits only with an occupant. Mirror in `tools/state_model/state_v3_model.py` (`position_flags_valid` at `:975`, the flags-only occupant rule at `:1055-1056`).
- **Codec:** the flags stay in the existing `position_flags` byte (`src/codec/state_codec.c:84, 210`). No layout change.
- **Only POOL kinds** write the bits; other kinds keep the tail zero (`dfi_check_tail`).

Template: the raised bit (G72b). `dfi_boost`'s `after`/`before` test already gives "real change".

## 3. Information safety (decisions 0007, 0023)

### Derivable from the public log?

- **Lash Out (lowered):** every real drop through `boost()` with a non-null effect prints `-unboost` (`battle.ts:2040-2083`). **Open check (phase 2):** a `boost()` with `effect` null prints nothing (`if (!effect) break;`, `:2062`). If such a call exists on a pool move, the drop is not visible and the row is refused by name.
- **Assurance (hurt):** `-damage|P|hp` text is shared by spread and direct damage. Not derivable from the line text alone. Decision 5: the rule is applied in the engine, and the view refuses at a PIVOT, so the bit never has to be derived publicly.

### The PIVOT refusal (decision 3)

- At a PIVOT boundary (`b->boundary_kind`, public), if an active Pokemon of either side has Lash Out or Assurance among its open move ids (`ob->sides[s].members[occ].move_ids`, the `dfi_view_raised_risk` pattern at `src/state/view.c:229-249`, `occ = ob->sides[s].occupant[p]`), then `dfi_view_visible_causes` (`view.c:251`) adds the new cause, and `duoforge_battle_public` and `duoforge_battle_from_view` refuse while it is set.
- Pool data only (the move ids are pool rows). Turn boundaries are not affected: the bits are zero there.
- **The cause value is pending HauptSession.** The code refers to it by a placeholder name (`DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY`, value not chosen). No number is picked in this document or in the code until the answer arrives.

### Cause summary

| Case | Decided by | Handling |
|---|---|---|
| Lash Out lowered bit (mid-turn) | the engine; visible through the boost lines | internal; PIVOT refusal |
| Assurance hurt bit (mid-turn) | the engine (spread path) | internal; PIVOT refusal |
| A null-effect `boost()` drop on a pool move | open check | refuse by name if it exists |

## 4. New public values (requests)

- **One PUBLIC_CAUSE value** for the PIVOT refusal (name above). **HauptSession assigns the number.**
- **Handler ids** `DFI_SPECIAL_LASH_OUT` and `DFI_SPECIAL_ASSURANCE`: internal, renumbered in merge order.
- **No** event kind, volatile, `flags3` bit, VIEWEXT feature, reserve byte or hypothesis field.

## 5. Recordings and mutants (planned)

POOL battles, six members a side, unique items, real genders, marked content only, learnsets from `data/mods/champions/learnsets.ts` (Assurance and Lash Out are listed for several species, e.g. Umbreon, Machamp, Kangaskhan, Heracross, Tauros). Each move has at least one battle with a Sitrus speed tie on both sides.

- **Lash Out:** (1) a self-drop (a marked move that lowers the user), then Lash Out is doubled on that turn; (2) a foe's drop (Intimidate, Parting Shot) on the user, then no doubling on the next turn (reset); (3) a drop blocked by Mirror Armor or Clear Body, or a stat at -6: no doubling; (4) a switch-out and return: no doubling; (5) Haze: no doubling.
- **Assurance:** (1) an ally's spread damage earlier in the turn: doubled; (2) a Substitute-only hit: not doubled; (3) residual damage at the end of the previous turn: reset, not doubled; (4) a Life Orb or Rocky Helmet hit: doubled.
- **PIVOT battle:** a U-turn (or similar pivot) on a turn where an active Pokemon knows Lash Out or Assurance. The public record refuses with the new cause, and a C test counts it.
- **Mutants** (one edit each in `turn.c` or `view.c`): the lowered bit set on the requested keys instead of the delta; the hurt bit set by `directDamage` too; the reset gate `turn !== 1` removed; the switch-out clear removed; the PIVOT refusal removed; the hurt bit read on the wrong side. Caught counts reported after the runs.
- **Campaign:** `diff_driver.py random`, about 300 battles, the teams with the rows (POOL), targeted subsets only locally, the full run on GitHub (builder_rules.md "Lock budget" and "Full suites on GitHub").

## 6. Metal Burst: deferred (pin analysis kept as the basis for a later step)

- **Power:** `damageCallback` (`data/moves.ts:11657-11664`): the last non-ally numeric attacker's damage times 1.5, `|| 1`; else 0. Fixed damage (no crit, no roll, no type multiplier).
- **Fail:** `onTry` (`:11670-11673`): fails unless that attacker has `thisTurn` set.
- **Target:** `onModifyTarget` (`:11674-11681`): `getAtSlot(attacker.slot)` (`battle.ts:1611-1617`), the occupant of the attacker's slot at use time.
- **Record:** `sim/pokemon.ts:917-942` (`gotAttacked`, from `battle-actions.ts:990-997`, Champions copy `scripts.ts:561-568`); `getLastDamagedBy(true)` excludes allies and non-numeric entries. A Substitute hit records `true` (`battle-actions.ts:1062-1065`).
- **Why deferred:** the foe's exact damage is not public (0023 section 1; only floor percents). The hypothesis carries the foe's current HP (`duoforge_view.h:88`), not the HP before the hit. Supporting it needs a hypothesis revision (option A) or a named refusal (option B), and it would use the whole remaining reserve (8 bytes). For +61 games that is too much for this step.
- A later step needs: a decision on A or B, the reserve bytes, and the handler id.

## 7. Refusals (E_UNSUPPORTED)

- Any pool move that is not Lash Out or Assurance in this step: unchanged.
- A PIVOT with an active Lash Out or Assurance user on either side (the new cause, decision 3).
- A null-effect `boost()` drop, if the phase-2 check finds one on a pool move (refused by name).

## 8. Status of phase 2

- Approved by the lead. Starts with the cause number (HauptSession). The PIVOT refusal cannot be merged correctly without it (without the refusal the view is wrong at a PIVOT), so engine work that depends on the refusal waits for the number.

## 9. Dependency on G74 (batch 5)

- `g88_av_sub` breaks the Substitute with Raichu's Quick Attack (no secondary), not with Thunderbolt. The reason: the pin draws the secondary roll for a Substitute-absorbed target too (`sim/battle-actions.ts:1336-1349` runs for a `null` target, since only `false` targets are skipped), and the engine's secondary loop draws only for hit targets (`src/combat/turn.c`, the SECONDARY loop). That gap is the secondary roll for an absorbed target: it comes with G74 (batch 5, H14's fix in the Alluring Voice and the generic secondary loops), not with G88. Until G74 is on the branch, a secondary move into a Substitute is not recorded in G88.
- The Substitute cost and the Substitute break keep their own direct and HURT rules (decision 5), unchanged by this dependency.

## 10. Information safety at the first decision (turn 1), approved by HauptSession

**The gap.** LOWERED is set by a stat drop at the battle start (Intimidate on entry, through `boost()`, `sim/battle.ts:2086`). `endTurn` clears it only when `this.turn !== 1` (`sim/battle.ts:1677-1683`), so a LOWERED from the start survives into the turn-1 decision (`g88_lo_intimidate`: Lash Out is doubled on turn 1). The view refused only at a PIVOT, so the view at the turn-1 decision did not carry LOWERED and a search from it would compute Lash Out without the doubling. An error of information safety, not a test pin.

**The rule** (cause `DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY` = 64, the same cause, no new value; `src/state/view.c`, `dfi_view_turn_history_risk`): the public record and `duoforge_battle_from_view` refuse while an active Pokemon of either side knows Lash Out at (a) a PIVOT boundary, or (b) the first decision, `b->turn == 1` (after team selection, and any boundary of turn 1 before its endTurn). Both decisions read only view fields: the boundary and the turn, `occupant[p]`, `members[occ].move_ids`. The rule refuses whenever Lash Out is known; it does not look at the stat stages (a negative boost is ambiguous: White Herb, Mirror Armor, Defiant). At a PIVOT, Assurance is refused too (section 3).

**Assurance (HURT) before turn 1: cannot be set, by the pin.** A HURT needs a spread damage that leaves the target alive (`sim/battle.ts:2137-2138`). Nothing deals damage before the first move of the battle:
- BeforeTurn only cancels actions: `data/conditions.ts:841-843` (`onBeforeTurn` = `queue.cancelAction`).
- Hazards are set by moves (Stealth Rock, Spikes), never at the start.
- Damage from abilities and items is one of: a hit (`onDamagingHit` / contact: `data/abilities.ts:82, 327, 1749, 2145, 2228, 3942`; `data/items.ts:3099, 5304, 5395`, Rocky Helmet, Rowap-type berries), an after-move effect (`data/items.ts:3415`, Life Orb), a residual (`data/items.ts:550` Black Sludge-type, `6121` Sticky Barb; `sim/battle.ts` residual), weather (`data/abilities.ts:1118`, `4406`: `onWeather`, which runs at the residual's `Weather` event, not at the start), or an `onUpdate` that needs a prior hit (Mimikyu's Busted, `data/abilities.ts:1006`).
- `data/abilities.ts:2407` (Liquid Ooze) is a heal reflection, not damage.
- The Substitute cost is a move effect (`data/moves.ts:18325`), after the move.

So at the first decision HURT is zero, and the rule does not include Assurance there. This is the reason, from the pin lines above; a later pool data change that adds a start-of-battle damage effect would have to extend the rule.

**Tests.** `duoforge.state.pool_g88`: `test_lo_turn1_refusal` (the first decision of `g88_lo_intimidate` has LOWERED and both players refuse with cause 64). `duoforge.state.pool_tail`: the team-selection tail carries LOWERED at tail bytes 328 and 330 (flats 2 and 3, the foe leads of Staraptor's Intimidate); the expectation states the reason. Mutant M9 (the turn-1 extension removed) is caught by `test_lo_turn1_refusal`.
