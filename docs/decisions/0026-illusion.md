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
- **onFaint:** dropped silently.
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

## 3. State (no field of its own: G46's party order plus rev 4's ability_state)

- **`ability_state` (rev 4, per position) already reserves "Illusion roster index + 1"** (`src/state/battle_internal.h`, `DFI_TAIL_ABILITY_STATE_MAX`). It holds the disguise: 0 none, else the roster index + 1. The cap rises from 6 to 7, since there are six roster indices. The rest of rev 4 stays as it is.
- **The party order is lane A's G46 field.** G46 adds `party_order` (the full side.pokemon permutation per side, from the rev 4 reserve), because its random drag reads the `side.pokemon` order too. Illusion reads that field and adds nothing.
  - **Condition:** G46 must keep the field exactly as the pin does. It is set at team start and swapped at every switch, replacement, pivot, drag and Ally Switch (`sim/battle-actions.ts:125-133`, `sim/battle.ts:1598-1603`).
  - This is a review point on G46. If G46 stores something weaker, those swaps are added there, not as a second field.
- **Alternative rejected:** deriving the order from the event history. The order is state, and the round trip of 0023 needs it.

## 4. The view — the owner chose B

Decision 0018 declared bit 19 `ILLUSION_UP` as **public**, with "the disguise is not exposed". Read literally, the foe's observation shows the **true** occupant plus a flag. That contradicts decision 0007's principle (exactly what a human sees). Under open team sheets a human sees "Incineroar", not Zoroark.

**Option A — as 0018 wrote it**
- The true occupant is visible, and `ILLUSION_UP` is public.
- Cost: one view bit (exists) and the rules above.
- It leaks the hidden identity to the policy and to the search. The live tracker cannot fill it from the protocol until the break, because the protocol shows the disguise, so live and engine views would differ.
- **Not recommended.**

**Option B — hidden identity (chosen by the owner, 2026-10-09)**
- **The foe viewer, while the disguise holds:**
  - `occupant[pos]` is the **disguise's** roster index.
  - The disguise's member row shows location ACTIVE, and the holder's HP percent, flag and status (what the game shows on that name).
  - The holder's own row keeps what the viewer knew before (location BENCH or UNDETERMINED).
  - Foe move uses: a move that is not on the disguise's open sheet is still counted on the slot the game shows. See the open point in section 7.
- **The holder's own side:** the truth, plus bit 19 `ILLUSION_UP` set on its own side only. **This changes 0018's visibility of bit 19 from public to own side only.**
- **After the break:** `replace` moves the viewer's occupant to the true roster index.
  - The disguise's row goes back to what the viewer knew of it, except "seen": the disguise **is** a brought member (`side.pokemon` holds only brought members), so having seen its name is true knowledge.
- **The event log**, per player:
  - In the foe's buffer, `DUOFORGE_EVENT_SWITCH.id` is the disguise's roster index (the roster index the viewer was shown).
  - New `DUOFORGE_EVENT_ILLUSION_END` = **44** (the next free one after lane A's 43, decision 0025): `position`, `id` = the true roster index, `hp`/`hp_kind`/`status` as for SWITCH. It covers the `replace` line and the `-end|Illusion` line.
- **The duplicate case**
  - The holder in slot a, both bench members to its right fainted: the disguise is the active partner, so two occupants would show the same roster index.
  - That switch-in is **refused with `E_UNSUPPORTED`** in revision 1. It is an endgame-only case; the campaigns count it.
  - Supporting it later needs a view rule for one roster index in two positions.
- **Decision 0023 (the search)**
  - `duoforge_battle_public` and `duoforge_batch_public` return `E_UNSUPPORTED` for a viewer whose foe could have an Illusion holder up. The search then plays the raw policy, like visible sleep.
  - The refusal must depend on the **viewer's** facts only. So it holds whenever the foe's open sheet has an Illusion member that the viewer has not seen faint, and whose break the viewer has not seen in its current stay on the field.
  - The arena reports the share under a new cause, `illusion_possible`.
  - Full support (a hypothesis field "which foe position is the holder") is a later 0023 revision.
- **Encoder and live adapter**
  - Encoder 4: no new column. Bit 19 now means "own disguise up"; the columns stay.
  - The live tracker (decision 0016) and the M11 pipeline must fold `|replace|` and `-end|Illusion` (0018 section 6 already names `|replace|` as OUT). That is the owners of `python/duoforge_live` and `python/duoforge_replay`; this lane does not touch them.

## 5. Rules (both options)

- **Disguise** at every switch-in of a holder, from `party`.
- **End** on the first damaging hit from any source, Substitute aside (if Substitute is marked by then, a hit into it does not end it).
- **Faint:** dropped silently.
- **Transform and Imposter fail** against a disguised target, and a disguised Transform user fails too (`sim/pokemon.ts:1273`). That ties into decisions 0027 and 0028.
- **Trace never copies Illusion** (`notrace`).
- **Shadow Tag's `maybeTrapped`** reads the disguise's species. The request's trapped flag is unchanged (G41's predicate reads the holder).
- **The gen 7+ silent typechange** shows the disguise's types, in the foe's view only.

## 6. New public values (for the owner's OK)

| Value | Kind | Note |
|---|---|---|
| `DUOFORGE_EVENT_ILLUSION_END` = 46 | event kind | `replace` + `-end Illusion` |
| bit 19 `ILLUSION_UP` | visibility change | public -> own side only (option B) |
| SWITCH `id` in the foe's buffer | meaning | the shown roster index (option B) |
| `duoforge_battle_public` refusal `illusion_possible` | refusal cause | 0023 table, `E_UNSUPPORTED` |
| `ability_state` cap 6 -> 7; reads G46's `party_order` | state | internal; no tail bytes of its own |

No struct grows, and the observation layout (736 bytes) and the extension (192 bytes) stay the same.

## 7. Open points

1. ~~Option A or B~~: **B** (owner, 2026-10-09).
2. **A foe's move that is not on the disguise's sheet** (open sheets): a human then knows it is the holder. Recommended: keep the disguise in the view until `replace`, as the game shows it, and leave the deduction to the model. The move-use count goes to the slot of the move on the **holder's** sheet, revealed only at the break, so nothing is counted on the disguise.
3. **The duplicate case:** refuse it in revision 1, as in section 4.

## 8. Evidence plan (after the OK)

- **Recorded POOL battles:** a disguise kept for several turns; a break by a foe hit and by an ally's spread move; a faint while disguised; a disguise after a bench swap (party order not equal to pick order); Trace that does not copy; Transform failing (once 0028 lands).
- **View tests:** the foe's occupant and rows before and after the break; the own bit; info safety (the foe's record does not depend on whether the shown member is the holder).
- **Round-trip tests** of the public-state contract with the new refusal counted.
- **Mutation checks** and a campaign of about 300 battles, as on the expansion track.
