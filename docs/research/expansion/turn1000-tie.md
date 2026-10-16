# The turn-1000 tie in doubles: prepared fix (design, test, reference battle)

Status: **prepared, no engine code.** Found by the C0 inventory (`champions-100.md` section 11 on `chris/c0-weights`).
HS decision 2026-10-16: a real bug (silent divergence), fixed in its own small PR right after the flow PR
(`restructure/4-flow`) is merged; behaviour exactly as Showdown (a tie, no refusal). This branch holds the reference
battle, the boundary test and this design; the code waits for the HS's signal.

## 1. The rule at the pin (`b2cb775b`)

- `endTurn` raises the counter first (`sim/battle.ts:1624`, `this.turn++`), runs the per-active end-of-turn updates
  (`:1665-1771`: moveThisTurn, newlySwitched, the move results, DisableMove, trapping), then calls
  `maybeTriggerEndlessBattleClause` (`:1773`).
- There: `if (this.turn <= 100) return;` (`:1836`), then **`if (this.turn > 1000)`** the line
  `|message|It is turn 1000. You have hit the turn limit!` and `this.tie()` (`:1839-1843`); "the turn limit is not a
  part of Endless Battle Clause" (`:1838`). The clause's own rule test comes later (`:1854`), so the limit applies to
  every format: Reg M-C (Flat Rules, no clause, `config/formats.ts:288-299`) as well as Champions OU.
- `endTurn` returns at once: no `|turn|1001` line, no request. The state's turn is 1001, `ended` true, `winner` ''.
- Before that, `|bigerror|You will auto-tie if the battle doesn't end in N turns (on turn 1000).` is printed at turns
  500, 600, 700, 800, 900, every 10 turns from 900 and every turn from 990 (`:1844-1852`): 24 lines, protocol only,
  no state.

## 2. The engine today (main `c02189e7`)

`dfi_end_turn` (`src/combat/turn.c`, about line 11850) refuses only a singles battle at turn 101 (decision 0083
section 6). A doubles battle goes on past turn 1000 (to `UINT16_MAX`, then `E_EXHAUSTED`): from turn 1001 on it plays
turns that the reference never plays. No real VGC game gets there (the server's timer ends it), but self-play can:
switching costs no PP, so two policies that keep switching never run out of moves.

## 3. The fix (to write after the flow PR)

In `dfi_end_turn` (after the flow PR: its home in `src/combat/flow/`, the end-of-turn phase function), in the pin's
order:

1. compute `turn = b->turn + 1` and the overflow checks, as today;
2. the singles refusal at turn 101 stays where it is (before any change). It is the clause's refusal, which the pin
   checks after the limit; a singles battle never passes turn 100, so the two never meet, and the existing test
   (`duoforge.state.singles`) keeps passing unchanged;
3. `b->turn = turn`, the per-position end-of-turn updates (choice lock end, newly switched, the raised/lowered/hurt
   bits, the move-result shift) exactly as today, because the pin runs them before the check;
4. **new:** `if (turn > 1000u) { b->result = DFI_RESULT_TIE; return dfi_terminal(r); }` — before the TURN event and
   before the request epoch moves: `dfi_terminal` emits the RESULT event (detail `DUOFORGE_RESULT_TIE`, the `|tie|`
   line), advances the epoch once, clears the requests, sets TERMINAL with request mask 0;
5. otherwise the TURN event and the requests as today (the epoch assignment moves after the check, so a tie advances
   the epoch once, as every other end of a battle does).

A named constant (`DFI_TURN_LIMIT 1000u`, pin `sim/battle.ts:1839`) and a comment citing the lines. No new public
value: RESULT and RESULT_TIE exist; the `|message|` and `|bigerror|` lines are not events. The state invariants
already accept a TERMINAL tie with Pokemon standing on both sides (the prototype below passes `duoforge_battle_check`).

**Prototype (not committed).** The change of step 4 (and the epoch move of step 5) was applied to a scratch copy of
main and built under the machine lock: the prepared test passes there (73 checks, 0 failures) and fails on main
(16 failures, all in the tie checks; the 999 -> 1000 step and the singles checks pass on main).

**Python side, with the fix.** `tools/reference/trace_to_c.py` stops today at the first warning line
(`ConversionError protocol-line bigerror`). It must treat `|bigerror|` (the turn-limit warnings) and the exact
`|message|It is turn 1000. You have hit the turn limit!` line as lines without an event, and map `|tie` to RESULT TIE
(it already does, `trace_to_c.py:1828`). The live tracker already ignores both kinds (`duoforge_live/tracker.py:179`,
`lines.py:62`).

## 4. Prepared files (on `chris/turn1000-tie`)

- `tests/reference/prepared/turn1000_tie/turn1000_tie.json`: the spec. Both sides bring four of six (marked content
  only, no items, no entry effects: both teams pass `duoforge_battle_create` under POOL with no unsupported entry) and
  switch both slots every turn (`switch 3, switch 4`): no PP, no damage, no draw (eight distinct Speeds).
- `tests/reference/prepared/turn1000_tie/turn1000_tie.summary.json`: what the recorded trace shows (1001 choice
  entries, 0 draws, the 24 warning lines, the logs of the last two steps, the final state: turn 1001, ended, no
  winner) and the trace's sha256. The full trace is **not committed**: 5.3 MB, ten times the largest committed trace.
  It is deterministic: `node tools/reference/ps_trace.js <pin> tests/reference/prepared/turn1000_tie/turn1000_tie.json`
  rebuilds it in about a second (its `--check` against the recorded copy matches).
- `tests/flow/test_turn_limit.c`: the boundary test (`duoforge.flow.turn_limit`), **not registered** in
  `tests/flow/tests.cmake`, because its doubles checks fail on main by design. It checks, for POOL and POOL_DEV: from
  turn 999 an ordinary TURN boundary at 1000; from turn 1000 TERMINAL, RESULT_TIE, turn 1001, request mask 0, no TURN
  event, the last event of both players RESULT TIE, `duoforge_battle_check` OK, and a further bundle refused
  (INVALID_ARGUMENT, battle unchanged); for singles the unchanged refusal (99 -> 100 runs, 100 -> 101 is
  E_UNSUPPORTED with the battle unchanged).

## 5. With the fix PR

1. the code of section 3;
2. register the test: `duoforge_add_test(NAME duoforge.flow.turn_limit SOURCES flow/test_turn_limit.c WHITEBOX
   TIER quick AREA flow)` in `tests/flow/tests.cmake`;
3. the converter rule for the two lines (section 3);
4. the reference battle: move the spec to `tests/reference/specs/`, record the trace, convert and capture its pins as
   any new battle. Its trace (5.3 MB) and payload are large: the HS decides whether it joins the committed pool set or
   stays a prepared, regenerated battle checked by its summary;
5. one mutant: the limit at 999 or 1001 must fail the test.
