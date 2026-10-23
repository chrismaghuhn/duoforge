# Design: the equal-Speed tie of the no-order residual handlers (issues #630, #633, #554)

Status: **accepted by the HS on 2026-10-23** (restructure lane). Decisions: draw site 1 `SPEED_TIE`, no new number (section 4); option (b) of section 3.3; the restructure lane implements it after restructure step 12, as the last piece of its window, and changes the perft and bench pins deliberately with the count of the affected residuals (section 5). The converter part of #554 then goes to the content or fuzz lane. No code change comes with this document.
Engine references are to main `907458c4` (`src/combat/turn.c`, the six phases of `dfi_residual_events_run`, restructure
step 4, #621); reference references to the pin `b2cb775b`.

## 1. What the pin does

`fieldEvent('Residual')` (`sim/battle.ts:484-575`) collects every handler of the event once, sorts the list once with
`speedSort` (`sim/battle.ts:429-460`) and then runs it.

- **The sort.** `speedSort` is a selection sort with `comparePriority`: order ascending (a missing order counts as `4294967296`, so the no-order handlers sort last), then Speed descending, then sub-order ascending.
- **Ties.** Each group of equal handlers is shuffled as soon as it is placed (`prng.shuffle(list, sorted, sorted + n)`). That is `n - 1` draws `random(i, n)`, which the engine's tape records as site 1, `SPEED_TIE`.
- **When the draws happen.** All of them come before the first handler runs, in the order in which the sort places the groups: first the orders 1 to 29, then the no-order groups, the fastest Speed first.
- **The no-order group of one Speed.** It holds every no-order handler of every active Pokemon with that Speed and sub-order (for the volatiles, the condition sub-order 2). Today these handlers are:
  - the duration handlers of Protect, flinch, Helping Hand, Follow Me, the stall counter, a charge (`twoturnmove`), `mustrecharge` and Ally Switch's volatile;
  - `lockedmove`'s duration handler with its `onResidual` callback (`data/conditions.ts:253-285`).
- **The order inside the group.** Which handler of the group runs first depends on the draws and on the order in which the handlers stood in the list before the sort. A Pokemon's volatiles are listed in the order they were added.
- **When the order shows.** Only through what happens between two handlers:
  - a lock's end, which has its fatigue line and its confusion draw;
  - the faint points: `faintMessages` runs after every handler that does not end, and a battle that ends there leaves the rest of the list unrun (`sim/battle.ts:565-566`).

## 2. What the engine does today

- **Phase 2** (`dfi_residual_order`) sorts the list in two `dfi_residual_sort` passes. It draws the ties of the callbacks of orders 1-25, those of the side conditions (26) and those of White Herb (29).
  - It draws a group only when it holds two callbacks or more. This follows the conversion's rule: a tie of handlers without a callback does not show, so `trace_to_c.py` drops its draws.
  - The second pass stops once it has placed every callback up to White Herb (`want = early_calls + herbs`). **The no-order entries are never sorted.** These are `DFI_RES_LOCK` (a callback) and the `DFI_RES_DURATION` entries with `NO_ORDER`. `dfi_residual_collect` already lists those one per handler, through the `ends` count of a position, which includes Ally Switch's volatile; so the groups already have the pin's size.
- **Phase 6** (`dfi_residual_noorder`) runs the no-order handlers by position in Speed order, with no draw. It has three exceptions:
  - The lone Protect / stall pair of one standing holder at a battle end draws one `SPEED_TIE` `random(0, 2)` (`turn.c:10287`).
  - An equal-Speed neighbour at a battle-ending faint point is refused (`E_UNSUPPORTED`, #633 case 1). Since #632 this includes the lock holders.
  - A holder with a lock and a counter that keeps, at its own battle-ending faint point, is refused (#633 case 2).
- **#630** is the case that diverges today: two lock holders of equal Speed. Their two `lockedmove` callbacks are a group of two callbacks at no order, so the pin draws and the conversion keeps that draw. The engine never draws it, and its tape is one draw short (6 mirror battles of seed 606).
- **#554 `residual-tie-callbacks`** (129 battles in the #396 fuzz, 59 in the lock campaigns): the converter refuses a residual tie group that holds a lock callback together with flinch or stall. It cannot state that group's outcome as a tape entry the engine reads.

## 3. Proposal

### 3.1 Where the draws go: phase 2, as a third sort pass

At the end of `dfi_residual_order`, after the White Herb pass, a third pass `dfi_residual_sort(..., want = all callbacks, want_sorted = n)` sorts the no-order entries the way the pin does:
- fastest Speed first;
- each group shuffled with `SPEED_TIE` draws, at once, before any handler runs.

The draw order and the bounds are then the pin's. Every draw of the residual stays in phase 2, as it does today for orders 1-29. Phases 3 to 5 are unchanged.

The engine keeps its rule of drawing only a group that holds two callbacks or more. A group with fewer has no outcome that shows, and the conversion drops its draws. With one exception (3.3), that holds for the no-order groups as well.

### 3.2 The group is the pin's group, handler for handler

The bound of a draw is the size of the group. `dfi_residual_collect` already lists every no-order handler as its own entry: one `DFI_RES_DURATION` per handler (the `ends` count of a position), plus `DFI_RES_LOCK`, each with the holder's Speed and sub-order 2, and only the lock a callback. So the group sizes are the pin's without a change to the list. What changes is phase 6: it walks the sorted entries instead of the positions in Speed order.

A Pokemon's volatiles are added in an order the state does not hold, so the pre-sort order of a group is partly unknown. The existing machinery covers this:
- `dfi_residual_order_ambiguous`, extended to the no-order groups through `dfi_residual_is_volatile`;
- `dfi_residual_model`, the exact test over every arrangement;
- `dfi_residual_arrangement_possible`: a counter of this turn never comes before a lock that ends now, because that lock is older.

A group whose callbacks come out in the same order for every possible arrangement and every draw is played. Any other group stays refused (`E_UNSUPPORTED`), but with its real reason. "Equal Speed at a battle end" is no longer a reason.

### 3.3 Phase 6 runs the drawn order; the #633 refusals go

- **#633 case 1** (equal-Speed neighbours at a battle-ending faint point). The order is now drawn exactly as the pin draws it, so the faint point that ends the battle and the handlers left unrun follow from the sorted list. The refusal goes. Two points still need checking against recorded battles:
  - The pin draws such a group even when it holds no two callbacks: two Protects of equal Speed draw, and the draw shows when the battle ends between them.
  - The conversion keeps such a draw only when the outcome shows (today's `no_order_end_tie`).
  - So the engine draws a no-order group with fewer than two callbacks exactly when the conversion keeps the draw: in a residual where the battle ends at a faint point inside the group. This is the existing Protect / stall pair rule, generalised from one holder to the group. Drawing it in phase 2 (before anything runs) and knowing later whether the battle ended inside the group do not fit together. Two ways out:
    - (a) the engine always draws such a group, and the conversion stops dropping these draws (a converter change; the reference data of every battle with such a group changes);
    - (b) the draw stays where it is today: in phase 6, at the battle end, as in the existing pair rule. This rule and the converter's `no_order_end_tie` agree today.
  - **Recommendation: (b)** for the groups without two callbacks. It keeps every committed tape valid. Phase 2 draws only the groups with two callbacks or more (3.1).
- **#633 case 2** (one holder with a lock and a counter that keeps, at its own battle-ending faint point). Its two handlers are members of one group, and the arrangement test of 3.2 decides: played when the order cannot matter, else refused with the arrangement reason.

### 3.4 The converter (#554)

With the engine sorting the no-order groups, the converter's `residual-tie-callbacks` refusal for a group with a lock callback and flinch or stall can become an ordinary tape entry: `SPEED_TIE`, the draw with the pin's bounds. This is a tool change in `tools/reference/trace_to_c.py` and its tests, in its own PR after the engine change.

## 4. Which draw site

**Recommendation: site 1, `SPEED_TIE`, no new site.**
- The pin's draw is the same `speedSort` shuffle as every other residual tie. The engine records all of those as `SPEED_TIE` (`turn.c:2536, 2798, 8961, 9133, 9589, 10287`), and so do `ps_trace.js` and `trace_to_c.py`.
- A new site would split one reference mechanism into two labels. It would need a converter rule to tell a no-order group from an ordered one, and it would make the existing pair draw (`turn.c:10287`, site 1 in committed fixtures) inconsistent, or force that draw's renumbering, which fixtures forbid.

If the HS wants the no-order tie separable in draw-count tests anyway, the free id would be **27** (`DFI_DRAW_SITE(RESIDUAL_NOORDER_TIE, 27u, ...)`, a line in `src/rng/draw_sites.def`, restructure 5c). In that case only the new phase-2 pass uses it, and the existing pair draw keeps site 1.

## 5. Effect on reference digests, perft and the bench

- **Committed reference battles (P2): expected unchanged.** Every battle with such a group is today refused by the converter (#554), refused by the engine (#633), or divergent (#630), so none is in a committed set. This is a prediction: the implementing PR proves it with the P2 capture (2808 executions, 1241 battles, `77dc5c4a…`). New recorded battles are added for #630 (mirror Outrage at equal Speed) and #633 (a Perish end between equal-Speed lock holders).
- **Perft and `BENCH_SHA256`: may change.** Perft and the bench play with the PCG.
  - A residual that today runs a group of two equal-Speed lock callbacks without drawing would gain a draw. That changes the stream after it, and so the digests.
  - A residual that today is refused (#633) would be played. That changes the outcome of that step.
  - Whether either happens in the pinned workloads is a measurement for the implementing PR. Count the residuals with a no-order group of two callbacks or more, and the #633 refusals, in the perft and bench workloads. If they are non-zero, the pins change deliberately, in one line each, with the count in the PR body.
- **Draw count per residual:** at most `n - 1` extra draws per qualifying group, only in those residuals. No other residual changes.

## 6. Order of work (proposal)

1. **Engine PR (restructure lane, after step 12; decision 0015 block, residual runner).**
   - It adds the per-volatile no-order entries (3.2), the third sort pass (3.1) and phase 6 walking the sorted list (3.3, option b).
   - It removes the #633 refusals.
   - It brings the recorded battles of #630 and #633, the boundary tests from the issues and one mutant (for example, the third pass removed).
   - **Gate:** P1-P6 with the P2 digests equal, perft and bench either equal or changed with the measured count, and a differential fuzz run against the pin. This is a behaviour change, so the restructure gates do not apply.
2. **Converter PR (#554 `residual-tie-callbacks`).** Accept the lock-callback groups.
3. **Fuzz re-run of the seed-606 lock campaigns.** The 6 #630 divergences and the 59 refusals should become PASS.

## 7. Decisions (HS, 2026-10-23)

1. Draw site 1, `SPEED_TIE`: the same `speedSort` mechanism, no new number.
2. Option (b) of 3.3.
3. The restructure lane implements the engine part after restructure step 12. The converter part of #554 goes to the content or fuzz lane afterwards.
