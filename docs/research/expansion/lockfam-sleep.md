# A lock holder put to sleep before its locked turn (issue 606): prepared fix

Status: **fixed on `chris/lockfam-sleep-fix` (decision 0015 entry 5dv).** The HS chose option (b) of section 3.4: a
persistent state bit, `DFI_SINGLE_TURN_LOCK_UNUSED` (bit 3 of the tail's `single_turn` byte; `position_flags` has no free
bit any more), internal and hidden, so a PIVOT pause keeps it and no pivot refusal is added. The fix sits on the
residual runner of restructure step 4 (#621): the lock's handler in the no-order phase of `dfi_residual_events_run`
has the pin's two phases. The text below is the preparation (`chris/lockfam-sleep-prep`, 935f909c) as it was; its
line numbers are those of main `dc9ce14b`; the decision entry is the record of what was done.

## 1. The rule at the pin (`b2cb775b`)

`lockedmove` (`data/conditions.ts:253-285`; Outrage, Thrash, Petal Dance and Raging Fury share it):

| line | handler | what it does |
|---|---|---|
| `:256` | `duration: 2` | the volatile's duration |
| `:257-263` | `onResidual` | holder asleep: `delete target.volatiles['lockedmove']` (no `onEnd`, `:258-261`); then `trueDuration--` (`:262`) |
| `:264-267` | `onStart` | `trueDuration = this.random(2, 4)` (`:265`, draw LOCK_TURNS) |
| `:268-272` | `onRestart` | `duration = 2` only when `trueDuration >= 2` |
| `:273-277` | `onAfterMove` | `duration === 1`: `removeVolatile` (so `onEnd`) |
| `:278-281` | `onEnd` | `trueDuration > 1`: nothing; else `addVolatile('confusion')` |

The Residual event (`fieldEvent`, `sim/battle.ts:484-560`):

- a volatile's handler is collected for Residual when it has a callback **or a duration** (`getKey = 'duration'`,
  `:487-489`; `findPokemonEventHandlers`, `:1107-1114`, with `end: pokemon.removeVolatile`);
- the handlers are sorted (`speedSort`, `:507`; `comparePriority`, `:404-411`: a handler without an order sorts last,
  `order || 4294967296`; lockedmove's `onResidual` has none);
- **for each handler with an end and a duration, the duration is counted down first** (`:515-522`): at 0 the end runs
  (`removeVolatile`, `sim/pokemon.ts:2035-2046`, which runs the `End` event: `onEnd`) and the loop `continue`s, so the
  handler's own `onResidual` does not run that turn.

The confusion's `onStart` (`data/conditions.ts:165-175`) prints `|-start|X|confusion|[fatigue]` for a lockedmove source
(`:166-167`) and draws its duration `random(2, 6)` (`:173-174`, CONFUSION_TURNS).

Consequences for a lock standing at a residual:

| this turn | duration at the residual | what happens |
|---|---|---|
| started or restarted (a hit) | 2 -> 1 | `onResidual`: asleep (put to sleep after its move) -> silent delete; `trueDuration--` |
| used, not restarted | - | already removed by `onAfterMove` at duration 1, with `onEnd` (fatigue when `trueDuration <= 1`) |
| not used (its move stopped before its use) | 1 -> **0** | **end with `onEnd`**: fatigue confusion when `trueDuration <= 1`; `onResidual` never runs |

The last row is issue 606: turn 1 Arcanine locks into Outrage (`trueDuration` 2, 1 after the residual); turn 2 its ally
Milotic puts it to sleep with Hypnosis before it moves (`|cant|p2a: Arcanine|slp`); the residual's countdown ends the
lock: `|-start|p2a: Arcanine|confusion|[fatigue]` and one CONFUSION_TURNS draw.

## 2. The engine today (main `dc9ce14b`, after the flow PR #610)

- `dfi_lock_remove` (`src/combat/turn.c:2667-2678`): the silent removal (clearVolatile, the sleep delete).
- `dfi_lock_end` (`turn.c:2680-2689`): `onEnd`, the removal and the confusion when `lock_turns <= 1`.
- The start and the restart (`turn.c:8318-8344`, `md->special == DFI_SPECIAL_LOCKED_MOVE`): LOCK_TURNS on a new lock,
  `r->lock_restarted` for a start or a restart.
- The epilogue of a used move (`src/combat/flow/turn.h:636-659`): a restarted use counts `lock_turns` down at once (the
  residual's `trueDuration--`, done at the use so that no residual of a later call needs `lock_restarted`); a use that
  did not restart it ends it there with `dfi_lock_end` (the `onAfterMove` path).
- The stopped use (`flow/turn.h:579-601`): a holder whose move is stopped before its use is refused (E_UNSUPPORTED),
  **except a sleeping one**, which goes on.
- The residual list (`turn.c:9936-9941`): `DFI_RES_LOCK`, no order, sub-order 2; its sorted place does nothing
  (`turn.c:10253-10255`), the lock runs in the order-less stage in Speed order (`turn.c:10554-10560`).
- **The site**: `dfi_residual_lock` (`turn.c:9739-9753`) assumes "every lock that stands here was used this turn" and
  removes a sleeping holder's lock with `dfi_lock_remove`: no end, no confusion, no draw. For the last row of the table
  above that is wrong when `lock_turns <= 1` (the tape is one draw short: `tape 4 of 5`). With `lock_turns == 2` the
  silent removal happens to give the same state and lines (`onEnd` returns), which is why only some battles show it.

## 3. The planned change

The engine needs, at the residual, the one fact the pin reads from the duration: **was this lock restarted this
turn?** A lock that stands at the residual and was not restarted reaches duration 0 there. With today's refusals only a
sleeping holder gets there unrestarted, and only through the stopped-use branch of `flow/turn.h:596-601`.

1. **Record the unused lock.** In the stopped-use branch (`flow/turn.h:596-601`), after the existing refusal for a
   holder that is not asleep: a holder that is alive and still has `lock_turns != 0` gets its bit in a new
   per-position mask ("its lock's duration ends at this residual"). Use `mover` after the Ally Switch remap
   (`flow/turn.h:589-595`), so the bit is the Pokemon's, at its slot.
2. **The residual's lock handler in the pin's two phases** (`dfi_residual_lock`):
   - *duration phase*: the bit is set -> clear it and `return dfi_lock_end(r, flat)` (`onEnd`: confusion when
     `lock_turns <= 1`; a Misty Terrain or an Own Tempo stops it inside `dfi_add_volatile` as at the normal end), and
     the callback phase is skipped;
   - *callback phase*: otherwise, as today: a sleeping holder's lock is deleted silently (`onResidual`); the count was
     already taken at the use.
   The test reads the bit, not the status: a holder cured after its `cant` line (the pin still ends the lock) is right
   too.
3. **The bit follows the Pokemon** on a swap: `dfi_run_swap_scratch` (`turn.c:4583-4598`) swaps it next to
   `lock_restarted`.
4. **Where the bit lives (an HS decision, not chosen here).** Two options:
   - *(a) run-scoped* (`dfi_run`, like `lock_restarted` and `drag_pending`; last in the struct, both positional
     initializers `flow/turn.h:410` and `:560` get one more `0u`). A PIVOT pause between the `cant` and the residual
     (a U-turn, Parting Shot or Emergency Exit later in the turn) starts a new `dfi_run` for the rest of the turn and
     would lose the bit: the turn must then be **refused** (E_UNSUPPORTED before `dfi_pivot`, `flow/turn.h:744`), never
     resumed with the silent removal. No new public value; the refusal is counted as UNSUPPORTED in campaigns.
   - *(b) persistent*: a bit in the battle state that survives the pause (a spare `position_flags` bit of the tail,
     bits 4-7 are zero today, `src/state/battle_internal.h:403-405`; or the unused fields of the queued RESIDUAL record).
     It is a **new public value** (codec, invariants, state model, the digest): its number comes from the lane's block,
     assigned by the HS. It removes the pivot refusal.
   The prototype (section 6) is (a).
5. Comments: `dfi_residual_lock`'s header, the stopped-use comment (`flow/turn.h:579-582`), `lock_restarted`'s comment in
   `src/combat/run_internal.h`, and the sleeping-holder case of `tests/moves/test_pool_g56.c` (its comment says the
   lock is "deleted silently"; with `lock_turns` 2 it ends with `onEnd` and no confusion: the checks stay, the comment
   changes).

## 4. In a phase-structured residual runner

Kept generic, so it fits whatever shape the restructure lane's runner has. The pin's loop is, per sorted handler:
*(skip a fainted holder's) -> duration phase -> (state still current?) -> callback*. A runner entry can describe this
with two optional parts:

- **duration part**: "does this handler's duration reach 0 now" and its **end** (a function of the entry); when it
  ends, the callback is skipped and the runner stops if the end decided the battle (`if (this.ended) return`,
  `:520`);
- **callback part**: the handler's `onResidual`.

Today the engine folds the duration into each handler where it is cheap (the yawn, Heal Block, Throat Chop, Roost's
`DFI_RES_DURATION`, Protect's sweep, all in `dfi_residual` from `turn.c:9649`). The lock is one more entry with both parts:
the duration part is "the unused-lock bit is set", its end is `dfi_lock_end`; the callback part is the sleep delete.
Its place in the order stays where it is (no order, sub-order 2, Speed order in the order-less stage), so the
confusion's `-start` line and its draw come exactly where the silent removal is today, after every ordered handler of
the residual and before the faint check of that holder. Nothing else in the runner changes, and the fix is one entry
whichever data shape the runner takes.

## 5. Paths that must stay unchanged

- **The fatigue on a normal end** (`flow/turn.h:636-659`): a used, not restarted lock ends at the use with
  `dfi_lock_end`, after the White Herb's AnyAfterMove, and the refusals for the White Herb order (`:624-632`, `:649-652`)
  stay. Boundary test scenario 3.
- **The countdown at a restarted use** (`flow/turn.h:644-648`): the count goes down at the use; such a lock is never
  ended by the residual. A holder put to sleep **after** its restarted use loses the lock silently (`onResidual`'s
  delete; the duration goes 2 -> 1, not 0) even with `lock_turns` 1 by then. Boundary test scenario 5 (the guard
  against a fix that ends every sleeping holder's lock with `onEnd`).
- **The Ally Switch epilogue of 5dn(h)** (`flow/turn.h:589-595`): the epilogue (AfterMove, the countdown, the fatigue)
  runs at the mover's new slot. The new bit is set with the remapped `mover`, and `dfi_run_swap_scratch` moves it with
  `lock_restarted`; the epilogue itself is not touched.
- **The refusals of a stopped use that is not a sleep** (a flinch, a full paralysis, a freeze, a confusion self-hit,
  `flow/turn.h:596-601`; `tests/moves/test_pool_g56.c`). The same end would apply to them, but lifting them is a
  separate change (it needs its own evidence), not part of this fix.
- **The silent removals** by a switch or a faint (`dfi_lock_remove` from clearVolatile), and the information safety
  of the lock length (`src/state/knowledge.h:24-28`, `dfi_maybe_lockedmove`): the fatigue line is public in the pin
  too, and `lock_turns` is 0 after the residual in both cases (`lock_turns` 1 or 2), as today.
- **The converter and the tracker**: `|-start|X|confusion|[fatigue]` is already converted (the normal end prints it);
  the prefix fails on the tape (`tape 4 of 5`), not in the converter.

## 6. Evidence prepared on this branch

**Reference battles** (`tests/reference/prepared/lockfam_sleep/`, README there; recorded at the pin, `ps_trace.js
--check` matches):

- `fz_6_175_outrage_main_prefix` (3 steps, the spec of issue 606);
- `fz_6_175_outrage_main` (the whole battle, 14 steps, `|win|p1`; the same teams and the campaign's choices; none of
  the replaced moves is used; turn 3 shows the fatigue confusion's first activation).

**Boundary test** `tests/moves/test_pool_lockfam_sleep.c` (`duoforge.state.pool_lockfam_sleep`, white-box, **not
registered**; to register with the fix:
`duoforge_add_test(NAME duoforge.state.pool_lockfam_sleep SOURCES moves/test_pool_lockfam_sleep.c WHITEBOX TIMEOUT 60
TIER quick AREA moves)` in `tests/moves/tests.cmake`). Five scenarios, each over seeds 1..16:

1. `countdown_sleep_fatigue`: `lock_turns` 1, put to sleep before its move: fatigue confusion in the residual;
2. `countdown_sleep_no_fatigue`: `lock_turns` 2, the same: no confusion;
3. `normal_last_use`: `lock_turns` 1, used: fatigue at the use, before the partner's move;
4. `normal_restarted_use`: `lock_turns` 2, used: restarted, counted to 1, the lock stays;
5. `sleep_after_restarted_use`: `lock_turns` 2, used, then put to sleep: silent delete, no confusion.

**Results** (scratch copies of main `dc9ce14b` built under the machine lock, the test registered only there):

| build | `pool_lockfam_sleep` | `pool_g56` | prefix | whole battle |
|---|---|---|---|---|
| main `dc9ce14b` | 1624 checks, **48 failures**, all in scenario 1 (32 missing CONFUSION_START, 16 `confusion_turns` 0: 16 seeds x 2 players + 16 seeds); scenarios 2-5 pass | 576 checks, 0 failures | **DIVERGENCE** step 2, tape 4 of 5 | **DIVERGENCE** step 2, tape 4 of 5 |
| main + prototype (option (a), not committed) | 1752 checks, 0 failures | 576 checks, 0 failures | PASS (3 steps) | PASS (14 steps) |

The prototype build also ran `ctest -R 'duoforge\.(state|data|reference)\.'` (with the test registered there): 143
tests, 142 passed, 1 skipped (`duoforge.reference.battle_pins`, no env), among them `conformance_pool_data` and
`corpus`. The prototype is the sketch of section 3 (a): the run-scoped mask, its swap, the two-phase
`dfi_residual_lock` and the pivot refusal (19 added and 2 changed lines in `run_internal.h`, `flow/turn.h`, `turn.c`).

**The mutant** of the fix PR: the silent removal back in the duration phase (`dfi_lock_remove` instead of
`dfi_lock_end` for a set bit). It must turn scenario 1 and both prepared battles red (DIVERGENCE at step 2), and
nothing else. A second, optional one: the bit never set; the same tests go red.

**Still to do with the fix** (issue 606's plan): `fz_6_175` (Raging Fury, needs the marks of A0 part 3) PASS; a
lock-family campaign with sleep inducers (Hypnosis, Spore, Sleep Powder, Yawn) for Outrage, and for Thrash, Petal
Dance and Raging Fury once they are marked again; count the pivot refusals of option (a).

## 7. With the fix PR

1. the code of section 3 (option (a) or (b) as the HS decides), after the residual-runner piece;
2. register the test (section 6);
3. promote the two battles (`tests/reference/prepared/lockfam_sleep/README.md`);
4. the mutant(s) of section 6 in one lock job, a clean rebuild, a sanity battle, the runner's sha256;
5. decision 0015 entry 5dv (draft below).

## 8. Draft: decision 0015 entry 5dv (not in the decision file yet)

> 5dv. **A lock holder put to sleep before its locked turn ends its lock through the duration (issue 606; found by
> lane A's lock-family check).** At the pin the Residual event counts a handler's duration down before its callback
> (`sim/battle.ts:515-522`): a lockedmove that was not restarted this turn (its holder's move was stopped before its
> use, which with the refusals of step G56 is only a sleep) reaches duration 0 there and ends with `onEnd`
> (`data/conditions.ts:278-281`): fatigue confusion when `trueDuration <= 1`, with its CONFUSION_TURNS draw; its
> `onResidual` (the silent delete of a sleeping holder, `:257-263`) does not run. The engine removed such a lock
> silently (`dfi_residual_lock`). Now the stopped use of a sleeping holder marks its lock, the mark follows the Pokemon
> on a swap, and the residual's lock handler ends a marked lock with `dfi_lock_end` before the sleep delete
> [option (a): a PIVOT pause with a marked lock is refused (E_UNSUPPORTED) / option (b): the mark is the state bit
> <number from the HS>]. Unchanged: the fatigue at a use that does not restart the lock, the countdown at a restarted
> use, the silent delete of a holder put to sleep after its restarted use, the Ally Switch epilogue of 5dn(h), and the
> refusals of a flinch, a full paralysis, a freeze and a confusion self-hit. **Evidence.** Two recordings
> (`fz_6_175_outrage_main_prefix`, `fz_6_175_outrage_main`, pool, synthetic teams), `duoforge.state.pool_lockfam_sleep`
> (five boundary scenarios), the mutant (the silent removal) caught by scenario 1 and both recordings; <campaign
> numbers>. Thrash, Petal Dance and Raging Fury may go back into a content batch.
