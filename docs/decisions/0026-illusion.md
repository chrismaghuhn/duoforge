# 0026 — Illusion (Zoroark, Zoroark-Hisui): hidden identity in the player view

Status: **accepted, option B** (owner, 2026-10-09, relayed by HauptSession: hidden identity as in the game, `ILLUSION_END` = 46, the honest search refuses and plays raw, counted, while a foe Illusion could be active). This note lists every new public value and state field; it was reviewed **before any code**. Builds on decisions 0005 (bench order), 0007 (what a player sees), 0015 section 7 (POOL tail), 0018 (view extension, bit 19 `ILLUSION_UP`) and 0023 (public state and worlds).

## 1. Why, and how much

- **Coverage:** Illusion is in 286 of the 34,430 Reg M-C replay games (coverage run of 2026-10-09). Marking it alone unlocks 31 more games (greedy rank 123). Almost every holder is Zoroark-Hisui; the pool also has Zoroark.
- **What's at stake:** Illusion is the only ability whose main effect is on **information**. Its effect on the rules is small:
  - the disguise breaks on a damaging hit;
  - a fainted holder drops it;
  - Transform fails on it;
  - Shadow Tag's `maybeTrapped` reads the disguise's species.
- **What's hard:** the view. A wrong view leaks to the policy, or breaks the round trip of decision 0023.

## 2. The pin

`data/abilities.ts` (illusion; the Champions mod has no entry):

- **onBeforeSwitchIn:** the disguise is the **last non-fainted member to the right of the holder in `side.pokemon`**.
  - `side.pokemon` is the party order, not the roster order.
  - "To the right" can be the other active, but only when every bench member to its right has fainted.
- **onDamagingHit:** a damaging hit from **any** source, an ally included, ends it.
  - The end emits `replace|POKEMON|DETAILS` and then `-end|POKEMON|Illusion`.
  - It does not end while the holder is being called back.
- **onFaint:** dropped, after the faint line has shown the **disguise** fainting (`sim/battle.ts:2552`; the name comes from `sim/pokemon.ts:532`), so a KO that is not a hit is never followed by `replace`.
- **Flags:** `failroleplay`, `noreceiver`, `noentrain`, `notrace` (Trace, an engine row, must skip it), `failskillswap`.
- **Party order** (`sim/battle-actions.ts:115-133`, `sim/battle.ts:1590-1603` for swap, `sim/battle.ts:2750-2756` for team start):
  - At team start, `side.pokemon` is the picked order: leads first, then the bench in pick order.
  - Every switch **swaps** the incoming member into the position of the one it replaces, and the outgoing member (or the fainted one) into the incoming one's old position. Ally Switch swaps too.
  - So the bench order is **not** the pick order after the first switch.
- **Other readers:**
  - `sim/pokemon.ts:1273`: `transformInto` fails if either side has an illusion.
  - `sim/battle.ts:1714`: the gen 7+ `typechange [silent]` shows the **disguise's** types.
  - `sim/battle.ts:1735`: `maybeTrapped` reads the disguise's species.
  - `sim/battle-actions.ts:679`: the Prankster hint (no effect on the rules).
  - Mega Evolution of a disguised Pokemon: not reachable, since Zoroark has no stone.

## 3. State

- **The disguise.** It goes into `ability_state` (rev 4, per position), which already reserves "Illusion roster index + 1".
  - `DFI_TAIL_ABILITY_STATE_MAX` is 6, inclusive (`src/state/battle_internal.h`), and that is enough: roster index 5 + 1 = 6. Nothing changes.
- **The party order is lane A's G46 field.** `party_order` is the full `side.pokemon` permutation per side, taken from the rev 4 reserve. Illusion only reads it.
  - **0026 depends on G46, which is not on main yet.**
  - G46 must keep the field exactly as the pin does: set at team start, then swapped at every switch, replacement, pivot, drag and Ally Switch (`sim/battle-actions.ts:125-133`, `sim/battle.ts:1598-1603`).
  - This is a review point on G46.
- **The foe's shown state (new: tail rev 5 = 0x0503, 18 bytes per side, on the holder's side).** Species Clause allows one holder per side: Zoroark and Zoroark-Hisui share the dex number 571. The fields:
  - `ill_shown` (1 byte): the roster index + 1 of the member whose name carries values that the foe was shown for the holder, else 0. It outlives the disguise. After an unbroken switch-out or a faint while disguised, the game keeps showing those values on that name until a line about the real member replaces them.
  - `ill_override` (4 bytes): the values shown on that name while the holder carried it: HP percent, HP colour flag, status, and flags (active, fainted, item used).
  - `ill_snapshot` (9 bytes): the foe's knowledge of the disguise's row just before the disguise came in: `hp_percent`, `hp_flag`, `revealed`, `moves_used[4]`, shown status, shown location. The break restores it.
  - `ill_pending` (4 bytes): the uses of the holder's moves that are **not** on the disguise's open sheet, counted per holder slot while disguised and attributed at the break (section 4).
- **Why rev 5.** Lane A books the rev 4 reserve of 35 bytes (G46's `party_order` and 0028's 20 bytes).
  - So this is **tail revision 5** (0x0503), with only these fields.
  - It touches the POOL-only encoding, digest, invariants and registry entry, and it changes the POOL fingerprints.
  - Invariants: every `ill_*` field is zero when the side has no holder; `ill_shown` names a brought member that is not the holder; the counts saturate as `moves_used` does.
- **Rejected:** deriving the order or the shown values from the event history. They are state, and the round trip of 0023 needs them.

## 4. The view (option B, chosen by the owner on 2026-10-09)

Decision 0018 declared bit 19 `ILLUSION_UP` public, with "the disguise is not exposed". Read literally, the foe would see the **true** occupant plus a flag, which contradicts decision 0007 (exactly what a human sees). Option A, as 0018 wrote it, is rejected.

**The principle:** the foe's view of the holder's side is exactly what folding the lines the foe was shown gives, with perfect memory. The rules below are that fold.

**Switch-in of a disguised holder.**
- The foe's line names the disguise (`sim/pokemon.ts:545-552`). The foe's `occupant[pos]` is the disguise's roster index.
- The disguise's row is snapshotted into `ill_snapshot`. From then on the row shows `ill_override`: location ACTIVE, and the HP percent, flag and status of the holder as shown.
- The holder's own row keeps what the foe knew of it before.

**While disguised, every shown line is attributed to the disguise's row.** That covers HP from damage and heals, status, a consumed item (a Focus Sash the holder uses appears under the disguise's name), and moves:
- A move on the disguise's open sheet counts on that slot of the disguise's row, so the derived PP falls as the game shows it. A Protect is counted there, not nowhere.
- A move **not** on the disguise's sheet is still shown in the event log as used by that position. Its use goes into `ill_pending` on the holder's slot, and the view shows it nowhere else until the break. A human can deduce the holder from it; the model gets the event and may deduce it too, the view does not.

**The break** (`replace`, then `-end|Illusion`, in both streams).
- The foe's occupant becomes the true roster index.
- The holder's row gets:
  - the last shown HP percent, flag and status (`replace` carries no HP, so the last shown value stands);
  - the item consumption;
  - the move uses: the pending ones, plus the disguise row's counts above the snapshot, mapped by move id to the holder's slots.
- The disguise's row is restored from `ill_snapshot`, except that "seen and brought" stays: `side.pokemon` holds only brought members, so the disguise **is** one, and seeing its name is true knowledge.
- Every `ill_*` field is cleared.

**An unbroken switch-out.**
- The game keeps showing the disguise at the holder's last shown values. The disguise's row keeps `ill_override`, with location BENCH.
- `ill_snapshot` and `ill_pending` are dropped, because no break is ever shown.
- The override ends at the next line about the **real** disguise member (its switch-in or a drag), which shows its true values.

**A faint while disguised.**
- A KO that is not a hit is printed as the disguise fainting (`sim/battle.ts:2552`). Such KOs: residual damage, recoil, Life Orb, Destiny Bond, Perish Song, a self-KO. `onFaint` then clears the illusion, so no `replace` follows.
- The disguise's row shows fainted (HP 0) through `ill_override`, until a line about the real member contradicts it. The holder's row stays as the foe knew it.
- A hit always breaks the disguise first, so a KO by a hit shows the holder.
- No refusal is needed, and no rule keys on the holder's true state.

**The owner's own side.**
- The owner's own switch line shows the disguise too (`sim/pokemon.ts:545-552`). But the owner's view comes from the request, which holds the truth. So the owner's `occupant` is the holder's true roster index, and its SWITCH event carries the true index (its own command).
- Bit 19 `ILLUSION_UP` is set on the owner's own side only. **This changes 0018's visibility of bit 19 from public to own side only.** That needs no extension revision only because the feature bit was never supported, so no consumer ever saw it set. The change is recorded in 0018.

**The event log, per player.**
- In the foe's buffer, `DUOFORGE_EVENT_SWITCH.id` is the **shown** roster index. That changes its meaning, so it needs a **MINOR bump**.
- New `DUOFORGE_EVENT_ILLUSION_END` = **46**:
  - `position`, and `id` = the true roster index;
  - `hp`, `hp_kind` and `status` from the last shown values;
  - it goes to **both** players' buffers, because both streams show the break.
- One event for two lines (`replace` + `-end|Illusion`) is a documented **exception** to 0007's one line, one event. The two lines always come together and say one thing.

**The duplicate case.** If the holder is in slot a and both bench members to its right have fainted, the disguise is the active partner, and two positions would show one roster index. In revision 1 that switch-in is **refused with `E_UNSUPPORTED`**. It can only happen in the endgame, and the campaigns count it.

**Decision 0023 (the search).**
- `duoforge_battle_public` and `duoforge_batch_public` return `E_UNSUPPORTED` while **the viewer's facts** allow a disguise:
  - the foe's open sheet has an Illusion member;
  - the viewer has not seen it faint under its own name;
  - and it is not shown on the field under its own name.
  The search then plays raw.
- The cause cannot be derived from the observation alone: it needs history, and a Python derivation would be hidden rule logic. So **C returns it**:
  - a new pure call `duoforge_battle_public_causes(ctx, battle, player, uint32_t *out_mask)`, and its batch form `duoforge_batch_public_causes`;
  - the mask bits are `DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP` = 1, `_VISIBLE_CONFUSION` = 2 and `_ILLUSION_POSSIBLE` = 4, computed from the same viewer facts as the refusal.
  The honest search (`python/duoforge_search/honest.py`) moves from its own observation test to that mask. That is HauptSession's code; the C side ships first.
- Full support, i.e. a hypothesis field "which foe position is the holder", is a later 0023 revision.

**Encoders and the live adapter.**
- Encoders 1-4 get no new column, and the meaning of bit 19 moves to "own disguise up". A battle with Illusion is refused explicitly (`E_UNSUPPORTED`) by encoders 1-4. New columns, if any, come only with encoder 5.
- The live tracker (decision 0016) and the M11 pipeline fold `|replace|` and `-end|Illusion` (0018 section 6 already names `|replace|` as OUT). That is the owners' work, in `python/duoforge_live` and `python/duoforge_replay`; this lane does not touch them.

## 5. Rules

- **Disguise:** at every switch-in of a holder, from `party_order`.
- **End:** on the first damaging hit from any source, an ally included. If Substitute is marked by then, a hit into it does not end the disguise.
- **Faint:** the disguise is dropped after the faint line (section 4).
- **Transform and Imposter:** they fail against a disguised target, and a disguised Transform user fails too (`sim/pokemon.ts:1273`; decisions 0027 and 0028).
- **Trace** never copies Illusion (`notrace`).
- **Shadow Tag:** `maybeTrapped` reads the disguise's species (`sim/battle.ts:1735`). G41's predicate reads the holder, so the trap itself is unchanged.
- **Typechange:** the silent typechange of gen 7+ shows the disguise's types, and only to the foe.

## 6. New public values and state

The owner's OK, through the night authorization of 2026-10-09:

| Value | Kind | Note |
|---|---|---|
| `DUOFORGE_EVENT_ILLUSION_END` = 46 | event kind | `replace` + `-end Illusion`, both buffers |
| SWITCH `id` in the foe's buffer | meaning | the shown roster index; MINOR bump |
| bit 19 `ILLUSION_UP` | visibility | public -> own side only (never supported before) |
| `duoforge_battle_public_causes`, `duoforge_batch_public_causes`, `DUOFORGE_PUBLIC_CAUSE_*` (1, 2, 4) | functions, constants | the cause of a public-record refusal, from C |
| POOL tail rev 5 (0x0503): `ill_shown`, `ill_override[4]`, `ill_snapshot[9]`, `ill_pending[4]` per side | state schema | internal; a registry entry; the POOL fingerprints change |
| `duoforge_public_state` 1336 -> 1396 bytes, `DUOFORGE_VIEW_STATE_MAX` 1297 -> 1357 | layout | follows from tail rev 5 (step I1) |

No view struct grows: the observation (736 bytes) and the extension (192 bytes) stay as they are. The public record of decision 0023 does grow, because it carries the canonical state: `duoforge_public_state` 1336 -> 1396 bytes and `DUOFORGE_VIEW_STATE_MAX` 1297 -> 1357 (step I1, PR #279; the night authorization covers it as a consequence of tail rev 5). Its Illusion bytes are zero until the Illusion step, which must mask them in the foe's record (the pending counts and the snapshot are not the viewer's knowledge).

## 7. Open points

1. ~~Option A or B~~: **B** (owner, 2026-10-09).
2. ~~A move not on the disguise's sheet~~: decided in section 4 (pending counts, attributed at the break).
3. The duplicate case: refused in revision 1 (section 4).

## 8. Evidence plan

**Recorded POOL battles:**
- a disguise kept for several turns;
- a break by a foe hit, and one by an ally's spread move;
- a Focus Sash used while disguised;
- a Protect, and a move not on the disguise's sheet, while disguised;
- an unbroken switch-out, then the real member coming in;
- a residual faint while disguised;
- a disguise after a bench swap (party order not equal to pick order);
- Trace not copying;
- Transform failing (once 0028 lands).

**View tests:**
- the foe's fold against the protocol, line by line (occupant, rows, counts), before and after the break;
- the owner's view (truth, bit 19);
- info safety: the foe's record and the cause mask are equal for two battles that differ only in which brought member the holder disguises as, while it is undisclosed.

**Also:**
- round-trip tests of 0023 with the new refusal counted;
- mutation checks, a campaign of about 300 battles, a 0015 entry and a support line.

## 9. Amended by I2 (2026-10-09, owner and lead)

The sections below are corrected by the I2 builder's pin check. Where this section and an earlier one differ, this one holds. The rest of the note stands.

- **Section 2, the disguise.** Pin confirmed (`data/abilities.ts:2056-2069`): the scan runs from the highest index down to position+1 and takes the first non-fainted member, so the disguise is the last non-fainted member to the right. Unchanged.
- **Section 4 and 5, the break (P2).** The break is a damaging **move** hit, from any user, an ally included. It is the pin's `DamagingHit` (`sim/battle-actions.ts:1118-1130`), which fires for move hits that are neither secondary nor self. Recoil, Life Orb, Rocky Helmet, residual damage and hazards do **not** break. A hit with a numeric zero damage follows the pin's own condition (a number, not `false`). If the engine cannot tell such a case apart, it refuses the battle explicitly (`E_UNSUPPORTED`). Section 5's "damaging hit from any source" reads as this.
- **Section 4, the owner's protocol copy (P3).** The protocol names the disguise in both copies: `toString()` (`sim/pokemon.ts:532`) and `getFullDetails` (`:547-552`) feed the switch line for both players (`sim/battle-actions.ts:146-148`). The owner's true roster index is not in any protocol line before the break. It comes from the owner's recorded choice (`switch N`) for a voluntary replacement, and from the request data that the harness records (the active identity) for a drag or a random replacement. The harness records that as data, never as a rule. The owner's SWITCH event carries the truth; the foe's carries the shown index. The internal side channel is stripped by the projection, so no public value changes. The `replace` line names the true holder, because `onEnd` clears `illusion` before it adds the line (`abilities.ts:2076-2081`).
- **Section 2, the owner's max HP (Q1).** The owner's exact HP is that of the true member, so the converter takes its maximum HP from the true member.
- **Section 5, Shadow Tag (Q6).** The `maybeTrapped` hint of the pin (`sim/battle.ts:1734-1756`) reads the disguise's ability list. The engine has no `maybeTrapped` field and the switch stays allowed, so the hint is out of scope. The real trap (`onFoeTrapPokemon`, `data/abilities.ts:4157-4161`) reads the real holder, as the G41 row does.
- **Section 6 (Q7).** No version bump in the I2 PRs. The one version PR (0.44.0) is HauptSession's. The public values of section 6 are listed in the PR body.
- **Section 3, the snapshot (amended by I2, lead 2026-10-09).** `ill_snapshot` bytes 0..6 are the disguise row's knowledge before it came in (`hp_percent`, `hp_flag`, `revealed`, `moves_used[4]`). Bytes 7 and 8 are REDEFINED: byte 7 is the holder's status as the foe was shown it before the disguise, byte 8 the holder's location as the foe knew it (0 undetermined, 1 bench). Bytes 7..8 may be nonzero exactly while `ill_shown` != 0. Bytes 0..6 and `ill_pending` exist only while a disguise is up; an unbroken switch-out clears them and keeps 7..8.
- **Section 3, `ill_override` (amended by I2).** The fold writes it during the stay: HP percent and flag mirror the disguise row's knowledge; the status is the one the lines show on the name (the switch line, `-status`, `-curestatus`); the flags are active (bit 0), fainted (bit 1) and item used (bit 2). It keeps its values after an unbroken switch-out (active cleared) and after a faint without a hit (fainted set), until a SWITCH or DRAG of the real disguise member clears `ill_shown` and `ill_override`.
- **Section 3, one shown name per side (amended by I2).** The single state holds one name. A holder entry that would need a second name is refused `E_UNSUPPORTED` at switch-in, before any change: a disguise as another name while one is shown, or the holder's own entry (not disguised) while a name is shown. The disguise of a holder is the last non-fainted member to the right; a re-entry disguised as the shown name is allowed.
- **Section 4, the holder's row (amended by I2).** While `ill_shown` != 0 the foe's holder row shows the status and location of bytes 7..8, not the truth. The disguise's row shows the status of `ill_override` and fainted from it.
- **Section 4, the public record (amended by I2).** The foe's record hides the disguise flag (`ability_state`), snapshot bytes 0..6 and `ill_pending`. Bytes 7..8 and `ill_override` are the foe's own knowledge and stay.
- **Section 4, the refusal (amended by I2, point (a) and (d)).** `ILLUSION_POSSIBLE` (bit 4) is set from the viewer's observation: the foe's sheet has an Illusion member that the viewer has not seen fainted under its own name and that is not shown on the field under its own name; also while the foe side's `ill_*` is nonzero. `duoforge_battle_public` refuses while the bit is set.
- **Section 4, the encoders (amended by I2, point (b)).** Encoders 1 to 4 refuse (`E_UNSUPPORTED`) a battle in which a member of either side has the Illusion ability in its sheet. Encoder 5 gets the columns, if any, later.
- **Section 5, Trace (amended by I2, Q5).** The notrace expectation of the pool data is `{Trace, Illusion}`: Trace does not copy a disguised holder's name, and the turn code excludes Illusion there.
- **Section 4, the break of a never-seen disguise (amended by I2, lead decision 3).** A disguise is never fainted (P1: the first non-fainted member to the right), so a snapshot with hp_percent 0 means that the foe had never seen the disguise member. At the break such a row is set to full HP (100, flag none), status none, revealed 0, moves used 0, seen, and BENCH: it was brought and was never on the field. A snapshot with hp_percent != 0 is restored as written above. The converter's reference fold does the same, with no "last shown" value. The invariant accepts hp_percent 0 as unseen.
- **Section 4, `replace` in the reference (amended by I2).** The `replace` line marks the true holder as seen. Its HP is the last value shown under the disguise name, which the break carries.
- **Section 4, the clear of a faint-held name (amended by I2, lead decision B, option B).** A holder fainted under its shown name whose real disguise member then enters (its SWITCH or DRAG, while the holder stands fainted, on the field or on the bench) is refused `E_UNSUPPORTED` at the switch-in, before any change, until the holder's foe-known status and location are kept past the clear. Reason: the view must not read the holder's true state; no deduction is made from the faint. Pinned by the white-box check `check_faint_clear` of `tests/test_pool_i2.c`; the campaign's `fz_42` and `fz_130` are refused by it.
- **Section 4, the duplicate name (amended by I2, lead decision A).** The disguise and its real member both on the field (the holder's disguise is the other active) is refused at the switch-in that makes it (`dfi_switch_in`). The converter exempts the display of that real member only from the step at which both names are shown on the field, and reports that step; diff_driver counts an engine that does not refuse at or before it as an ORACLE_GAP (`illusion-duplicate-unrefused`).
