# 0084 - Leppa Berry: the PP restore, its ACTIVATE event and the viewer's fold (entry 5ek)

Status: **draft for the HS** (Content lane, 2026-10-24, branch `chris/leppa-0084-note` on main `69b04cba`). This note is
documentation only. Nothing in `src/`, `include/`, `python/` or `tests/` changes with it. The code comes after the HS
decides the open points (section 11) and after the Restructure lane's exclusive window ends (`docs/process/LANES.md`).
The HS assigned the number 0084. Entry 5ek comes from the Content block (`docs/process/NUMBERS.md:11`).

**No new public value.** The step adds no event kind, no cause, no draw site, no residual kind, no volatile, no tail
byte and no view feature. The only new form is a cause that already exists (ITEM) on a kind that already exists
(ACTIVATE). The new public function of section 6 is an open point.

Every line reference without a path prefix such as `data/` or `sim/` is a DuoForge path. Pin paths are in the
Showdown checkout `b2cb775b`.

## 1. The pin

**The item** (`data/items.ts:3352-3376`; the Champions mod has no entry, so the base item is inherited:
`data/mods/champions/items.ts` has no `leppaberry`):

- `isBerry: true` (`:3355`).
- `onUpdate` (`:3360-3365`): `if (!pokemon.hp) return;`. If **any** move slot has `pp === 0`, it calls
  `pokemon.eatItem()`.
- `onEat` (`:3366-3373`) picks the slot as follows:
  - the **first** slot with `pp === 0` (slot order of `moveSlots`);
  - otherwise the first slot with `pp < maxpp`;
  - with no such slot it returns without a line (the berry is still gone).
- The amount is 20 with Ripen and 10 without. The new PP is `Math.min(moveSlot.pp + addedPP, moveSlot.maxpp)`
  (`:3371`).
- It prints `-activate|X|item: Leppa Berry|<Move>|[consumed]` (`:3372`). X is the eater; `<Move>` is the move
  whose slot got the PP.

**The eat** (`sim/pokemon.ts:1768-1809`, `eatItem`):

- It needs HP and `isActive` (`:1770`).
- It runs `UseItem` and `TryEatItem` (`:1779-1781`). Unnerve's `onFoeTryEatItem` (`data/abilities.ts:5268-5270`)
  makes TryEatItem fail, so nothing happens. `onUpdate` tries again at every later Update.
- It prints `-enditem|X|Leppa Berry|[eat]` (`:1783`) **before** the Eat handler runs (`:1785`). The two lines
  always come in the order `-enditem`, then `-activate`.
- Then come EatItem (`:1786`), the staleness bookkeeping (`:1788-1798`, section 9.7), `lastItem`,
  `usedItemThisTurn`, `ateBerry` (`:1800-1804`) and `AfterUseItem` (`:1805`: Unburden, Symbiosis).

**The timing.** `onUpdate` runs at every `eachEvent('Update')` (`sim/battle.ts:465-476`: speed order, ties
shuffled). The PP of a move are deducted in `runMove` before the move runs (`sim/battle-actions.ts:282`). The
Pressure extra is deducted in `useMove` (`:473-484`). `deductPP` stops at 0 and charges nothing more
(`sim/pokemon.ts:888-902`). So the slot reaches 0 before the move does anything, and the berry is eaten at the
**first Update after that**:

- **A damaging move that deals damage:** the Update inside the hit loop. Champions overrides `hitStepMoveHitLoop`
  (`data/mods/champions/scripts.ts:427`). Its Updates are at `:537`, after each hit, and at `:574`, after the hits.
  Both come before `afterMoveSecondaryEvent` (`:576`). The engine's matching call sites are
  `src/combat/turn.c:8607-8609` (the hit loop) and `:8710` (after the hits).
- **A status move, or a damaging move that hit nothing** (it missed, was protected against, or had no target): the
  `runAction` Update (`sim/battle.ts:2860-2861`; engine `src/combat/flow/turn.h:736`).
- **Other Updates:** BeforeSwitchOut (`sim/battle-actions.ts:80-84`; engine `src/combat/flow/switch.h:439`) and the
  Update that ends `eachEvent('Weather')` (`sim/battle.ts:472-475`; engine `src/combat/turn.c:9532`). They matter
  for a holder that received a Leppa Berry (Trick, Thief, Covet, Symbiosis) while a slot was already at 0, or whose
  Unnerve block has ended.

**Other ways to eat it:**

| Source | Pin | Who eats |
|---|---|---|
| Bug Bite | `data/moves.ts:1911-1934`; onHit `:1920-1930` | the move's user; no TryEatItem, so Unnerve does not block |
| Pluck | `:13439-13462` | the same as Bug Bite |
| Fling | `:5733-5786`; berry branch `:5747-5755` | the **target** |

Mystery Berry (`data/items.ts:8034-`) uses a volatile named `leppaberry`. It is a Gen 2 item and not in the pool.

**PP under Champions:**

- The base PP of every move is capped at 20 (`data/mods/champions/scripts.ts:4-8`).
- `calculatePP` (`:41-43`) is `(pp / 5 + 1) * 4` unless the move has `noPPBoosts`. It ignores `ppUps`, so the
  `ppUps = 3` of `sim/pokemon.ts:361-362` has no effect.
- So `pp_max` depends on the move id alone: 8, 12, 16 or 20 (or the base PP of a `noPPBoosts` move).
- A Leppa Berry fills the slot of a 5-PP move (`pp_max` 8) completely.

## 2. The event form

### 2.1 The record

`-activate|X|item: Leppa Berry|<Move>|[consumed]` is one ACTIVATE event:

| field | value |
|---|---|
| kind | `DUOFORGE_EVENT_ACTIVATE` (35) |
| position | X, the eater: the holder at an Update, or the user of Bug Bite (section 7) |
| other | `DUOFORGE_NO_POSITION`: the line has no `[of]` |
| cause | `DUOFORGE_CAUSE_ITEM` (2) |
| id2 | Leppa Berry + 1 = 115 (`DFI_ITEM_LEPPABERRY` = 114, `src/data/formats/reg-mc/pool_tables.h:1275`) |
| id | the move named in the line (its table id, as in a MOVE event) |

**Allowed only in this form** (HS direction): an ACTIVATE with cause ITEM always has id2 = Leppa + 1 and
`other == NO_POSITION`.

**Today the form does not exist:**

- The header says "Every other ACTIVATE has id 0" (`include/duoforge/duoforge.h:1164`).
- No ACTIVATE in `src/` has cause ITEM (a grep for `EVENT_ACTIVATE` with `CAUSE_ITEM` finds nothing).
- The digest classifier allows ACTIVATE only with the causes MOVE and ABILITY (`src/state/observation_digest.c:85`).
- The converter refuses the line: it has three arguments, so it reaches `elif len(args) != 2` and raises
  `activate-line` (`tools/reference/trace_to_c.py:2167-2168`).
- The `-enditem|X|Leppa Berry|[eat]` before it is the existing ITEM_END with the eaten flag.

### 2.2 The header (`include/duoforge/duoforge.h`)

At `:1158-1164` (ACTIVATE), insert before the last sentence:

> POOL kinds, Leppa Berry (decision 0084, entry 5ek): `-activate|X|item: Leppa Berry|Move|[consumed]` is cause ITEM,
> id2 Leppa Berry + 1, position the eater (the holder at an Update, or the user of Bug Bite that ate the target's
> berry), other DUOFORGE_NO_POSITION, and id the move whose slot got the PP back. It is the only ACTIVATE with cause
> ITEM.

The last sentence then reads "Every other ACTIVATE has id 0".

Two more header changes:

- `DUOFORGE_PP_DERIVED` (`:727-729`): append "; a Leppa Berry line gives back up to 10 of the named move's
  attributed uses, never below 0 (decision 0084)".
- `DUOFORGE_CAUSE_ITEM` (`:1225`) stays as it is (id2 is the item + 1). Optional: add "(ACTIVATE: Leppa Berry only)".

None of these changes a constant, a struct or a layout. They are comments only, so `python/tests/engine/test_layout.py`
(the constants and structs check) does not move.

### 2.3 The digest classifier (`src/state/observation_digest.c`)

- `:85`: add `DFI_CAUSE_BIT(ITEM)` to the ACTIVATE causes. The field set POCIJ stays the same. The bytes of an
  ACTIVATE line already carry `id` (decision 0082, table "ABILITY, ACTIVATE, ITEM_START, ITEM_SHOWN | POCIJ").
- `dfi_line_variant` (`:103-136`): add one case for ACTIVATE:

  ```c
  case DUOFORGE_EVENT_ACTIVATE:
      return e->cause != DUOFORGE_CAUSE_ITEM ||
             (e->id2 == 1u + DFI_ITEM_LEPPABERRY && e->other == DUOFORGE_NO_POSITION &&
              e->position < 2u * DUOFORGE_ACTIVE_PER_SIDE);
  ```

  Any other item ACTIVATE stays `E_UNSUPPORTED` / `observation_line_unclassified`. The causes MOVE and ABILITY
  keep their current rule.
- **No new domain version.** Decision 0082 (`docs/decisions/0082-observation-digest.md:124-128`) enters new
  variants into the classifier one by one, in the PR that introduces them, with a test. Speed Swap was the first;
  this is the second. The v1 bytes of every existing line stay the same. The PR also updates that paragraph of 0082
  to name the Leppa form.

### 2.4 The converter (`tools/reference/trace_to_c.py`)

**`step_events`.** A new branch in the `-activate` block, before `elif len(args) != 2` (`:2167`):

```python
elif what == 'item: Leppa Berry' and len(args) == 3 and attrs == ['[consumed]']:
    # decision 0084: the eater, the move whose slot got the PP; cause ITEM, id2 the berry + 1, no [of]
    if pos is None or key(args[2]) not in tables['MOVE']:
        raise ConversionError('activate-line', ..., detail='Leppa Berry')
    e = ev_tuple(EV['ACTIVATE'], pos, NOPOS, CAUSE['ITEM'], tables['MOVE'][key(args[2])],
                 tables['ITEM'][key('Leppa Berry')] + 1)
```

Every other `item: ...` activate keeps raising.

**The oracle's PP fold** (`ill_pp_fold`, `:1434-1617`; its counts give `pp_foe` at `:2838-2844`). This is the
reference side: it derives the foe's knowledge only from protocol lines (its PROVENANCE note, `:1454-1457`).

- It needs its own branch for the line: the shown name's row, and the slot of the named move.
- The new count is `max(0, min(count, start) - 10)`. `start` is the pin's own start PP of the slot. That is the
  `pp_start` of `:2709`, which `ill_pp_fold` must now receive as an argument.
- This is not a second engine rule. It is the independent oracle that the conformance test compares the engine with
  (`tests/support/conformance_compare.c:125-131`: the viewer's derived PP against `pp_foe`, at every step of every
  recorded battle). The oracle takes its bound from the pin's start state, not from the engine's formula.
- A Leppa line under a shown disguise (Illusion window open) raises `leppa-illusion` (section 9.8).

**The each-tie set.** `EACH_HANDLERS` (`:816-817`) gets `leppaberry`, the same as `sitrusberry`. A tie of a Leppa
holder with another Update bearer is then kept, and the engine draws it (section 3).

## 3. The engine state (where the berry is eaten)

This note fixes the rule, not the code. The places are:

- **The Update bearers** (`src/combat/turn.c:2896-2898`): a Leppa Berry holder is a bearer, the same as a Sitrus
  Berry holder at any HP. The converter keeps the same set (section 2.4).
- **The handler**, in the loop of `dfi_update` next to Sitrus (`:2927-2933`) and Lum (`:2938-2943`). One item per
  holder, so the order inside one holder does not matter. All of these must hold:
  - the holder has HP (`m->hp != 0`);
  - it holds the berry;
  - some slot has `pp == 0`;
  - `!dfi_unnerved(b, flat)` (`:1068-1078`).

  Then the handler runs, in this order:
  1. `dfi_use_item_core(r, flat, NO_POSITION)`, which prints `-enditem [eat]`;
  2. the slot pick: the first slot with `pp == 0`, else the first with `pp < pp_max`;
  3. `pp = min(pp + 10, pp_max)`;
  4. the ACTIVATE of section 2.1;
  5. `dfi_symbiosis(r, flat)` (the AfterUseItem, as for Sitrus).
- **The isBerry lists.** `dfi_use_item_core` (`:2081-2083`, the EATEN flag) and `dfi_bug_bite` (`:2113-2115`)
  each list the pool's berries by hand. Leppa must be added to **both** lists, or the two must be replaced by one
  generated isBerry column (`docs/research/expansion/champions-100.md:594` names that column as a gap). If only one
  list has it, the `[eat]` flag is wrong or Bug Bite misses the berry in silence.
- **The data.** The generator gets `leppaberry` in `ENGINE_ROWS` (`tools/datagen/tablegen/families.py:25-27`) and an
  item-facts entry with the pinned `onUpdate` and `onEat` texts, as `G47_ITEM_FACTS` does
  (`tools/datagen/tablegen/items.py:23-31`). Bug Bite's pinned text already contains the Leppa staleness line
  (`tools/datagen/tablegen/moves.py:1559-1563`). The row's handler then goes from UNMODELED
  (`src/data/formats/reg-mc/pool_tables.c:2768`; reasons at `:1958`) to NONE, and the support manifest marks the
  item (`src/data/support_manifest.c`, next to Lum at `:996`).
- **Ripen** doubles the amount. It is unmarked (UNMODELED, `pool_tables.c:2971`), so setup refuses a Ripen holder
  (section 8). The handler uses 10 only.
- **No new state.** The PP is in the member, the eaten item in `item_consumed`, the foe's knowledge in
  `moves_used`. No tail byte and no schema change.

## 4. The viewer's fold (question 2)

### 4.1 Where

One place: the knowledge fold `dfi_events_fold_knowledge` (`src/combat/events.c:353-511`). The new branch goes next
to the Symbiosis branch (`:492-504`):

```c
} else if (e.kind == DUOFORGE_EVENT_ACTIVATE && e.cause == DUOFORGE_CAUSE_ITEM &&
           e.id2 == 1u + DFI_ITEM_LEPPABERRY) {
    /* decision 0084: the named move's slot on the open sheet gets up to 10 attributed uses back */
    if (disg[slot]) return false;                 /* refused earlier by the engine (section 9.8): E_INVARIANT */
    find j with fs->members[m].moves[j].move_id == e.id, else return false;
    k->moves_used[j] = dfi_leppa_used(k->moves_used[j], fs->members[m].moves[j].pp_max);
}
```

A `false` from the fold makes the step `E_INVARIANT` (`src/state/request.c:971-974`; the step is atomic on `tmp`).

**Not in `observation.c`.** The observation only reads the state and the knowledge: `dfi_derived_pp`
(`src/state/observation.c:128-132`) and the foe's PP (`:228-232`). The public record (decision 0023) carries
`moves_used` itself, and `duoforge_battle_from_view` rebuilds the world's PP from it (`src/state/view.c:1555-1559`).
So the fold must change `moves_used`. A derivation in the observation alone would give a world with the wrong PP.
`observation.c` and `view.c` stay as they are.

### 4.2 One rule for the state and the view

The pin's line `data/items.ts:3371` is one helper, `dfi_leppa_pp(pp, pp_max) = min(pp + 10, pp_max)`. It lives in
the items area (`src/combat/items/`, `docs/process/CONTENT.md` step 3). Both paths use it:

- the turn code applies it to the true PP;
- the knowledge fold applies it to the derived PP:

  ```c
  uint8_t dfi_leppa_used(uint32_t used, uint32_t pp_max)
  {
      const uint32_t derived = pp_max - (used < pp_max ? used : pp_max);
      return (uint8_t)(pp_max - dfi_leppa_pp(derived, pp_max));
  }
  ```

  This is exactly `used' = max(0, min(used, pp_max) - 10)`, the HS's formula, and it is written once in C.

### 4.3 Does the viewer know the foe's `pp_max`? Yes

- The observation copies `pp_max` for every member of **both** sides, before it splits own from foe
  (`src/state/observation.c:183-186`). This is the open team sheet.
- Under the POOL kinds `pp_max` is not a free setup value. It is derived from the move id
  (`src/state/closure_member.c:416-419`, set at `:441-444`, checked at `:535-541`) by the Champions formula
  (`src/data/formulas.c:34-48`, cap `DFI_PP_CAP` = 20 at `src/data/formulas.h:16`). These are the same as the pin's
  `scripts.ts:4-8` and `:41-43`.
- So there is no hidden PP Up. The bound in the fold is the pin's own cap `Math.min(..., moveSlot.maxpp)`, with the
  value the viewer is shown.
- Under closed team sheets (decision 0081) `pp_max` is still a function of the move id, and the line names the move.
  The slot always holds a move the foe had already used (it was at 0 or below its maximum), so the move is already
  revealed.

### 4.4 Why `min(used, pp_max)`, and what the rule cannot see

- **Over-count (real, and needs the min).** A slot at 1 PP used into a Pressure target: `runMove` takes 1, and
  Pressure takes 0, because `deductPP` stops at 0 (`sim/pokemon.ts:893`; engine `src/combat/turn.c:7018-7023`). The
  viewer counts 1 + 1 (`src/combat/events.c:450`), so `used = pp_max + 1`.
  - Without the min: `pp_max + 1 - 10` gives a derived PP of 9.
  - With it: `max(0, pp_max - 10)` gives `min(10, pp_max)`, which is the truth.
- **Under-count (documented, kept).** Decision 0030 section 1 (its amendment) does not attribute the single-target
  Pressure extra of a `[still]` line. So `used` can be lower than the truth.
  - A Leppa line from the holder's own Update means the slot was at 0. A rule that set `used := pp_max` first would
    recover the hidden extra.
  - **Recommendation: no.** The HS formula keeps the attribution meaning of `DUOFORGE_PP_DERIVED` ("the PP the
    viewer can attribute"). It is one rule for both paths: after a Bug Bite the named slot is only "below its
    maximum", and the viewer cannot tell which branch of `onEat` it was without reading a second event.
  - The deficit that was there before stays the same size. It does not grow.
  - The two rules agree whenever the count was exact, which is every recorded battle without a `[still]` Pressure
    extra.
  - Open point 11.2.

## 5. The white-box values of the fold

These are the expected values for the C table test, over the Champions range:

| pp_max | used | used' | derived PP after |
|---|---|---|---|
| 8 | 8 | 0 | 8 |
| 8 | 9 | 0 | 8 |
| 12 | 12 | 2 | 10 |
| 12 | 13 | 2 | 10 |
| 16 | 16 | 6 | 10 |
| 20 | 20 | 10 | 10 |
| 20 | 21 | 10 | 10 |
| 20 | 15 | 5 | 15 |
| 20 | 3 | 0 | 20 |
| 16 | 255 | 6 | 10 |

The rows with `used < pp_max` cover the Bug Bite branch (section 7). Each value is the pin's `min(pp + 10, maxpp)`
applied to `pp = pp_max - min(used, pp_max)`.

## 6. Python (question 3)

**What reads the fold today.**

- The live tracker keeps `uses` per member, for its own members and the foe's alike. It adds `1 + pressure` per move
  line (`python/duoforge_live/tracker/fold_event.py:113-117`).
- `record.py` writes the foe's knowledge from it (`python/duoforge_live/record.py:295`) and the player's own PP
  (`:369-371`, with the refusal `pp-uses-past-maximum`).
- `tracker/views.py:144` and `:158` derive the view's PP the same way.
- The tracker gets the converter's event tuples (`fold_event.py:8`, `from ..data import trace_to_c`). So once the
  converter emits the ACTIVATE of section 2.4, the tracker has it without parsing the line itself.
- `lines.check` stops at the line today: `item: Leppa Berry` is in no fold set of `python/duoforge_live/lines.py:388-421`.

**It cannot simply take the engine's view.**

- In live play there is no engine battle: the tracker is the source of the record. `duoforge_public_record_check`
  builds a world from the record but does not recompute `moves_used`.
- For the player's own *active* members the request carries the exact PP. `tracker/requests.py:85-91` already
  compares it with the tracked value and raises `own PP of ...` on a mismatch.
- But the request has no PP for bench members (a holder that ate the berry and then left by a pivot), and it has
  none for the foe. So the request alone is not enough.

**Recommendation: no second rule. A pure library call holds the rule, as `duoforge_hp_display` does** (decision 0023
section 4; `include/duoforge/duoforge_view.h:191-197`, `src/state/view.c:779`, `python/duoforge/view.py:34-41`).

- A new export `duoforge_leppa_uses(uint32_t used, uint32_t pp_max, uint8_t *out_used)` calls `dfi_leppa_used` of
  section 4.2.
  - It is a pure call, with no heap.
  - It refuses `pp_max` 0 or above 255 with `E_INVALID_ARGUMENT`, and NULL with `E_NULL_ARGUMENT`.
  - It writes nothing on a refusal.
- `python/duoforge/view.py` gets `leppa_uses(used, pp_max)`, with the signature in `python/duoforge/_lib.py:34-35`.
- `fold_event.py` applies it, own and foe alike, on the ACTIVATE with cause ITEM and id2 Leppa + 1:
  `m.uses[k] = view.leppa_uses(m.uses[k], m.pp_max[k])`, with k the slot of `ident`. A move off the sheet raises a
  sheet contradiction.
- `lines.py` classifies exactly the form `-activate|X|item: Leppa Berry|Move|[consumed]` as `"fold"`; any other
  form stops. `record.py` itself does not change: it reads `uses`.
- `dfi_leppa_used` stays private. It joins the "not a shared library export" lists of `test_layout.py:51-77`.

**The shared test with exactly the C result.**

- `test_pool_records_equal_engine` (`python/tests/live/test_live.py:968-984`) runs each new reference battle through
  the tracker. At every decision point it compares the assembled record field by field with the engine's record of
  the same point. That includes `knowledge*.moves_used` for the foe and `member*.move*.pp` for the player's own
  members.
- Each battle's per-battle pins (`tests/reference/battles/reg-mc/pool/<name>.json`, read by
  `python/tests/support/_reference_pins.py:9-35`) set `own_pp_stops: []`. That proves the tracker's own PP equals
  the pin's request after every Leppa line (the `requests.py:89` guard).
- A unit test of `view.leppa_uses` takes the rows of section 5. It tests the binding, not a second rule.

**The cost of the export:**

- one ABI addition;
- the Restructure lane's exported-symbol baseline (`docs/benchmarks/*/exported-symbols.txt`) gains one name, so the
  Restructure lane must take the new list as the base of its next proof;
- the HS decides whether it bumps the library version (open point 11.1).

**Fallback if the HS refuses a new export:** the tracker holds `max(0, min(u, pp_max) - 10)` itself, pinned by the
same two tests. That is a second copy of the rule, which `AGENTS.md` ("Python and bindings must not contain hidden
rule implementation") argues against. Not recommended.

The replay pipeline needs nothing of its own. `python/duoforge_replay/spectator.py:24-26,43` uses the same tracker.
The Leppa games of the replay data (83, `docs/research/expansion/champions-100.md:219`) stop at the line today and
fold afterwards.

## 7. Bug Bite and Pluck (question 4): build Bug Bite in the same step

**What the pin does.** Bug Bite (`data/moves.ts:1920-1930`):

- it takes the target's berry and prints `-enditem|T|Leppa Berry|[from] stealeat|[move] Bug Bite|[of] U`;
- then it runs the berry's Eat for the **user**, with no TryEatItem;
- Leppa's `onEat` then picks the **user's** first slot at 0, else the user's first slot below its maximum, and
  prints `-activate|U|item: Leppa Berry|<Move>|[consumed]`;
- Bug Bite's own `deductPP` (`sim/battle-actions.ts:282`) has already put its slot below the maximum, so in the pool
  a slot is always found.

**Recommendation: build Bug Bite in the same step.** Reasons:

1. **A silent divergence otherwise.** Bug Bite is marked (`src/data/support_manifest.c:526`). Its berry test
   (`src/combat/turn.c:2113-2115`) lists Sitrus, Lum and the resist berries. Once Leppa is marked, a Bug Bite into a
   Leppa holder would take nothing and print nothing, while the pin steals and eats. So the step must touch
   `dfi_bug_bite` either way.
2. **The same event, the same rule.** The event form is section 2.1 with position = the user. The slot rule is the
   same `onEat` helper as the Update path (with the eater as a parameter). The viewer's fold is the same branch
   (section 4.1).
3. **Evidence for the second branch.** The second branch of `onEat` ("first slot below its maximum") is reachable
   only through Bug Bite among the marked mechanics. Building it gives that branch a reference battle. Refusing it
   leaves the branch dead until Fling or Pluck.
4. **A refusal would cost play.** It would be an `E_UNSUPPORTED` in the middle of the battle at the hit
   (`dfi_bug_bite`, `src/combat/turn.c:2104`). That refuses a reachable pairing (a Bug Bite user against a Leppa
   holder), and it refuses such battles for the search and the live bot. The build costs one more reference battle.

**What the Bug Bite path does exactly:**

- Unnerve does not block it (the pin skips TryEatItem; the comment at `src/combat/turn.c:2100` already says so).
- Sticky Hold still keeps the berry (`:2120-2125`).
- There is no AfterUseItem, so no Unburden or Symbiosis for the eater (`:2141-2142`).
- The case "no slot below its maximum" cannot be reached in the marked set, because Bug Bite always spends its own
  PP. It returns `E_INVARIANT`, named in a comment. Following the pin there (no line) would be an untested path.

**Pluck** (`data/moves.ts:13439-13462`) has the same `onHit`. It is unmarked (UNMODELED, `pool_tables.c:1381`) and
refused at setup (section 8). When it is marked, it shares `dfi_bug_bite`, and with it the Leppa path. This step does
not mark it.

## 8. Harvest, Recycle, Fling (question 5)

All of them are unmarked today and refused at setup. The support gate refuses a member whose ability, item or move is
unmarked (`src/state/closure_member.c:302-318`, from `src/state/battle.c:168-172`, `E_UNSUPPORTED`). This step marks
none of them.

| Mechanic | Pin | Pool row | What it would do with a Leppa Berry |
|---|---|---|---|
| Harvest | `data/abilities.ts:1800-1816` | UNMODELED, `pool_tables.c:2897` | gives back the last berry at the residual (sun, else `randomChance(1, 2)`: a draw site from the HS). A Leppa Berry given back to a holder with a slot at 0 is eaten again at the next Update: a loop of restores |
| Recycle | `data/moves.ts:14821-14841` | UNMODELED [callback onHit], `pool_tables.c:1445` | gives back `lastItem` (`-item ... [from] move: Recycle`), then the same Update eat |
| Fling | `data/moves.ts:5733-5786`, berry `:5747-5755` | UNMODELED [onPrepareHit; condition], `pool_tables.c:1137` | the **target** eats the berry: an ACTIVATE of section 2.1 with position = the target, and its slot rule |
| Pluck | `:13439-13462` | `pool_tables.c:1381` | as Bug Bite (section 7) |
| Ripen | - | `pool_tables.c:2971` | 20 instead of 10. The ability is public (sheet, `-activate` line), so the fold would read it |
| Cud Chew, Cheek Pouch, Pickup | - | `pool_tables.c:2868`, `:2862`, `:2952` | re-eat, a heal after eating, or a found item: each needs its own step |

- Each of them needs `lastItem` state, a draw, or another eater. None of these exists in the engine.
- Recommendation: add a guard to `tests/data/test_pool_tables.c` in the style of its G46 guards (`:1744-1760`). It
  asserts that Harvest, Recycle, Fling, Pluck and Ripen stay unmarked while Leppa is marked. Its comment says that
  marking one of them needs its Leppa path.

## 9. Interactions

**1. Pressure.** The viewer counts the extra (`src/combat/events.c:450`, decision 0030). The min of section 4.4
handles the over-count at 1 PP. After a Leppa Berry, Pressure keeps charging the restored slot as before. A
reference battle with a Pressure target speeds up the drain (2 PP per use) and reaches the over-count case
(section 10).

**2. Struggle.** Struggle has no slot:

- `deductPP` finds no `getMoveData` and returns 0 (`sim/pokemon.ts:890-891`; `sim/battle-actions.ts:282` exempts
  `struggle`);
- the engine deducts only for `q->move_slot < 4` (`src/combat/turn.c:6770-6776`).

So Struggle never empties a slot and never triggers the berry. A holder reaches Struggle (all slots at 0, the request
of `src/state/request.c:187-199`) only when the berry cannot be eaten: it is gone, or blocked by Unnerve. The fold
does nothing for Struggle. The derived PP matters here: after the fold, the search does not wrongly believe the foe
must Struggle.

**3. Disable and Encore.** Both read the true PP, so a Leppa Berry eaten in the same action changes them as in the
pin:

- Disable fails on a last move at 0 PP (`data/moves.ts:3680-3684`; engine `src/combat/turn.c:3960`). The holder's
  move empties its slot, the berry restores it at that action's Update, and a later Disable in the same turn succeeds.
- Encore fails to start on a move at 0 PP (`data/mods/champions/moves.ts:320`; engine `src/combat/turn.c:3921`).
- Encore ends at the residual when the encored move has no PP (`data/moves.ts:4757-4762`; engine
  `src/combat/turn.c:9627-9633`). The Update comes before the residual, so a restored encored move keeps its Encore.
- No new code. One reference battle (Encore on the drained move) proves the order (section 10).

**4. Mimic, Sketch, Transform.**

- Mimic and Sketch are not in the Reg M-C pool: `pool_tables.h` has no `DFI_MOVE_MIMIC` or `DFI_MOVE_SKETCH`, and
  `pool_tables.c` has no `"mimic"` or `"sketch"` row.
- Transform is in the pool but UNMODELED (`pool_tables.c:1667`), so setup refuses it. The digest refuses a transform
  source as well (`src/state/observation_digest.c:230`).
- So `moveSlots` is always the open sheet's slots. The move a line names is always on the eater's sheet. A move off
  the sheet is `E_INVARIANT` in the fold (section 4.1).

**5. PP Ups.** They do not exist under Champions: `calculatePP` ignores `ppUps`
(`data/mods/champions/scripts.ts:41-43`), and `pp_max` is a function of the move id (section 4.3).

**6. Unnerve.** It blocks the Update path (section 1; engine `dfi_unnerved`, `src/combat/turn.c:1068-1078`). The
holder keeps the berry and tries again at every Update until the Unnerve holder leaves or faints. Unnerve does not
block the Bug Bite path.

**7. Endless Battle Clause (staleness).**

- In the pin, Leppa feeds the staleness of the clause:
  - `RESTORATIVE_BERRIES` (`sim/pokemon.ts:41-45`), read at `eatItem` (`:1788-1798`);
  - `setItem` sets `pendingStaleness` (`:1873-1879`; the test `RESTORATIVE_BERRIES.has('leppaberry')` at `:1873` is
    always true, a quirk of the pin);
  - Bug Bite (`data/moves.ts:1926`), Pluck (`:13454`) and Fling (`:5756`) set `staleness = 'external'`.
- Staleness is read only by the clause: `maybeTriggerEndlessBattleClause` (`sim/battle.ts:1803-1903`) returns
  before turn 101 (`:1836`) and without the rule (`:1854`); the staleness test is at `:1859`.
- **The doubles kinds:** the Reg M-C formats (`config/formats.ts:288-299`: Flat Rules) do not have the clause. Flat
  Rules' list is at `data/mods/champions/rulesets.ts:28-33`.
- **The singles kind** (`[Gen 9 Champions] OU`): Standard AG has the clause (`data/mods/champions/rulesets.ts:5`).
  But the engine refuses a singles step that would start turn 101 (`src/combat/flow/turn.h:215-222`, decision 0083
  section 6), before the clause's first check.
- **So the staleness has no effect in any kind.** The engine keeps no staleness state and needs none. Without the
  clause the writes are dead state in the pin. The generator's facts record the reads as checked and inert.

**8. Illusion (a new refusal).**

- While a disguise is up, the foe attributes every shown line to the disguise's row (decision 0026 section 4). Moves
  that are not on the disguise's sheet go to `ill_pending` as additive counts (`src/combat/events.c:153-164`). The
  break adds the pending counts and the disguise row's uses above the snapshot (`:192-202`).
- A restore cannot be written into either count. A pending count cannot go negative, and a restore on the disguise
  row below its snapshot is lost (`:192`).
- **Recommendation:** the engine refuses an eat by an eater whose position shows a disguise (`dfi_illusion_disguise_up`,
  `src/state/battle_internal.h:494`) with `E_UNSUPPORTED`, before any change. This covers both the Update path and
  Bug Bite. It gets a test (`docs/process/CONTENT.md` step 6).
- The fold's `return false` (section 4.1) stays a defensive check. The converter raises `leppa-illusion`
  (section 2.4), and the live tracker stops at the line under a disguise.
- Illusion holders with a Leppa Berry are rare. An exact Illusion fold would need a signed pending count and is a
  later step.

**9. Item transfers.**

- Trick, Switcheroo, Thief and Covet are marked (`src/data/support_manifest.c:302-305`), and so is Symbiosis
  (`:817`). A Leppa Berry can reach a member that already has a slot at 0; it is then eaten at the next Update. This
  is the general Update path, with no special case.
- Knock Off (`:301`) removes the berry with no eat.
- Item Clause = 1 (Flat Rules) allows one Leppa Berry per side.

**10. Magic Bounce and Heal Block.**

- A bounced move costs no PP (`src/combat/events.c:445-447`), so it never empties a slot.
- The berry is not a heal, so Heal Block does not stop it (the pin's `onEat` has no heal test).

**11. The move-result classifier** (`duoforge_move_result`, its `mr_changed` at `src/state/view.c:933-1022`). Neither event counts as
a change:

- the berry's ITEM_END has cause NONE (only ITEM_TAKEN counts, `:996-1000`);
- ACTIVATE falls to `default`.

So a status move whose Update eats the berry keeps its move result. A reference battle with a status move drained to
0 checks the tail's `move_result` against the pin (the POOL conformance).

## 10. Evidence plan

### 10.1 Reference battles

Each is a spec under `tests/reference/specs/`, `"data": "pool"`, format `gen9championsvgc2026regmc`. Each goes
through `ps_trace.js`, `capture_battle_pins.py`, `trace_to_c.py` and `tiebreak_ref.js`, each with `--check`
(`docs/process/CONTENT.md` step 5). Each battle checks two things:

- **the conformance:** the true PP against the pin at every step, and the viewer's PP against `pp_foe`
  (`tests/support/conformance_compare.c:125-131`);
- **the live tracker:** the records against the engine and `own_pp_stops: []` (section 6).

The drain setup: a member with a 5-PP move (`pp_max` 8) uses it into a Pressure target (Kingambit or Aerodactyl, as in
`tests/reference/specs/g53_fainted_holder.json`), so the slot empties in 4 uses instead of 8.

| Battle | Proves | Kills mutant |
|---|---|---|
| L1 status move drained to 0 | eat at the `runAction` Update; `move_result` unchanged; `pp_max` 8 fully restored | M2, M6 |
| L2 damaging move drained to 0 on a hit | eat at the hit-loop Update: damage, then `-enditem`, `-activate`, then secondaries and recoil | M6 |
| L3 damaging move drained to 0 that misses or is Protected | eat at the action-end Update | M6 |
| L4 one use without Pressure (7 left), then into Pressure down to 1, then 1 to 0 into Pressure | the over-count: the viewer's `used = pp_max + 1`, derived PP after = `min(10, pp_max)` | M1 |
| L5 Unnerve foe while the slot is at 0, then the Unnerve holder leaves | no eat while it stands, eat at the next Update after; the Update order | M5 |
| L6 Bug Bite into a Leppa holder | the user eats; the first slot below its maximum, the second branch | M10 |
| L7 Encore on the drained move | Encore kept after the restore (section 9.3) | - |

L7 is optional. A tie of a Leppa holder with a Sitrus holder at equal Speed (an each-tie draw) goes in L1 if a seed
gives one. Otherwise it is open point 11.4.

### 10.2 White-box test

The test is `tests/items/test_leppa_berry.c`, scaffolded with
`tools/new_mechanic.py items leppa_berry --id 5ek --lane Content`. It checks:

- the table of section 5 for `dfi_leppa_used`, and the export of section 6 if the HS adopts it;
- two slots at 0 when Leppa arrives: only the first slot by order is restored, and the line names it;
- a fainted holder: no eat;
- Unnerve: no eat, no event;
- the disguised eater: `E_UNSUPPORTED` with the state unchanged (the new refusal);
- the digest: the Leppa form is accepted; cause ITEM with Sitrus + 1, with `other != NO_POSITION`, and with
  `position == NO_POSITION` are each refused (`E_UNSUPPORTED`). These go next to the Speed Swap cases of
  `tests/flow/test_observation_digest.c:95-101`;
- the guard of section 8.

### 10.3 Mutants

Each mutant is applied to the committed source, the affected tests are rebuilt and run, and the source is restored.

| Mutant | Change | Killed by |
|---|---|---|
| M1 | fold without `min(used, pp_max)` | L4 (conformance `pp_foe`), section 5 rows with `used > pp_max` |
| M2 | state restore without the `pp_max` cap | L1 (`pp_max` 8: PP above the maximum, state check / conformance) |
| M3 | fold on the slot of the last move instead of `e.id` | white-box two slots |
| M4 | engine picks the last slot at 0 | white-box two slots |
| M5 | no Unnerve test | L5 |
| M6 | eat only at the action-end Update | L2 (line order) |
| M7 | Leppa missing from one isBerry list | L1 (`[eat]` flag) or L6 (Bug Bite) |
| M8 | oracle without its Leppa branch | conformance red on L1 to L6 (the oracle is independent) |
| M9 | tracker without the Leppa fold | `own_pp_stops` and the record diff in `test_pool_records_equal_engine` |
| M10 | Bug Bite without Leppa | L6 |
| M11 | digest accepts any item ACTIVATE | white-box digest refusal |

### 10.4 What moves (pins and goldens)

These are measured at the merge, as the sum of all merged work (`docs/process/CONTENT.md` step 7).

| Pin | Moves? | Why |
|---|---|---|
| `POOL_HASH_HEX` (`tests/data/test_pool_tables.c:48`) | yes | Leppa's handler column goes from UNMODELED to NONE |
| `UNMODELED_ITEMS` (`:73`) | yes, 18 to 17 | as above |
| `POOL_TABLE_HASH` (`tools/state_model/state_v3_model.py:316`, checked by `tools/state_model/tests/test_model_pins.py`) | yes | the same hash, in the model |
| `FP_KP_HEX`, `FP_KPD_HEX` (`tests/data/test_pool_setup.c:44-45`) | yes | the POOL and POOL_DEV fingerprints carry the table hash |
| Item mark counts in `tests/data` (where pinned) | yes | the new mark |
| `context_fingerprint` in `tests/perft/pins.json` | not compared (its `about`, `:2`) | perft counts themselves: no Leppa in the perft positions, measure |
| Per-battle live pins `tests/reference/battles/reg-mc/pool/<name>.json` | new files | one per new battle (L1 to L7) |
| CLOSURE and TEAM_C fingerprints (`tests/support/fixtures.h:50-53`, `tests/data/test_closure_setup.c:48-49`, `tests/data/test_team_c_setup.c:31-32`) | no | those tables never change |
| Codec goldens (`tests/flow/test_codec_golden.c`, closure) | no | |
| POOL tail pins (`tests/data/test_pool_tail.c:43-45`) | no | no tail byte |
| Digest vectors (`tests/support/observation_digest_vectors.h:40`, ACTIVATE `2300ff0102010403`; `:57-59`, request and stream) and `tools/reference/observation_digest_vectors.py:26,41` | no | the v1 bytes are unchanged; the accepted variant is a white-box test, not a vector |
| Event layout (`src/combat/events.c:16`, 20 bytes) and `python/tests/engine/test_layout.py` | no | no struct and no constant |
| `BENCH_SHA256` (`python/tests/search/test_bench.py:34`) | expected no | its roots are the reference setups, which have no Leppa Berry; measured, not assumed |
| `python/duoforge/_lib.py` signatures and the exported-symbol baseline | only with the export of section 6 | |

## 11. Open points for the HS

1. **The export** `duoforge_leppa_uses` (section 6): adopt it, and decide whether it bumps the library version.
   If the HS refuses it, the fallback is a Python copy of the rule under the shared test (not recommended).
2. **Under-count after a `[still]` Pressure extra** (section 4.4): keep the HS formula (recommended), or let the
   Update path set `used := pp_max` first.
3. **Illusion:** refuse a disguised eater by name (recommended, section 9.8), or design a signed pending count now.
4. **The each-tie draw:** confirm that a Leppa holder is an Update bearer at every PP, as Sitrus is at every HP
   (sections 2.4 and 3). If no seed gives a tie of two bearers, the mutant "Leppa not a bearer" stays unproven by a
   reference battle. The white-box test can then check the bearer set directly.
5. **The isBerry lists:** add Leppa to the two hand lists (`src/combat/turn.c:2081-2083`, `:2113-2115`), or
   replace them in the same step with a generated isBerry column.
6. **Timing:** the code waits for the end of the Restructure lane's exclusive window. The helper goes in the items
   area folder as that window leaves it.
