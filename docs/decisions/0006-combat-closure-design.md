# 0006 — Combat closure: data, state v3, execution, RNG draw sites, events, reference fixtures

Status: **proposed**; being implemented step by step (`tasks/M3_M4_COMBAT_CLOSURE.md`). **Implemented so far:** step 1a, the generated closure tables and the Champions stat and PP formulas (section 2, data only); step 1b-1, the state v3 layout with its invariants, codec and oracle (section 3.1, synthetic data only); step 1b-2, the CLOSURE contexts, real setup validation and the support gate (section 2.1); step 2a, the damage and stat arithmetic (`src/core/modifier.c`, checked against values the pinned reference computes) and the draw sites with the test-only tape (`src/rng/draw.c`, section 5); step 2b, the reference harness and the first recorded battles (section 5.1); step 2c, the turn core (section 4.1), which replays seven recorded battles draw for draw. The two real teams are still rejected with `E_UNSUPPORTED`, because their abilities and items are not implemented.

Showdown citations are `path:line` at the pin `b2cb775b0616115b775534eaeff50300e1fc81fc`.

## 1. Owner inputs this note builds on

| Date | Input |
|---|---|
| 2026-09-30 | **No backlog:** one continuous build in the order of `docs/research/mechanics-inventory.md` section 5; nothing parked; state v3 designed once; the real teams stay rejected until the closure gate. |
| 2026-10-01 | **Gender is always specified** in team specifications and fixtures. No construction-time gender draw exists in DuoForge. |
| 2026-10-01 | **Reference checkout approved.** It lives outside this repository at `C:\Dev\src\pokemon-showdown` (detached at the pin), installed with `npm ci --ignore-scripts --omit=dev` and built with `node build`. Nothing is vendored. |
| 2026-10-01 | **Lookup source:** https://www.pokewiki.de/ for questions about intended game behaviour. It explains; it never supplies test expectations. |
| 2026-10-01 | **Local verification runs natively on Windows, not in WSL** (section 9). |

## 2. Data: context v3

- `data_kind` keeps `SYNTHETIC` (1) for the structural and exhaustive domain tests of M1/M2 and gains `CLOSURE` (2): the generated tables of the two-team closure. A `SYNTHETIC` battle can never execute combat (`E_UNSUPPORTED`), because it has no types, stats or effects.
- **Generated, committed tables.** `tools/datagen/gen_closure.py` reads the pinned checkout and writes `src/data/closure_tables.{h,c}`. Every record carries its source `path:line`; the file header lists the sha256 of every input file. CTest checks the generated file's hash; an optional reference test (`DUOFORGE_PS_REFERENCE_DIR`) regenerates and compares byte-exactly, as the PCG known-answer test does. The core contains no parser and reads no file.
- **Contents:** 16 formes (types, base stats, weight, ability, Mega link and stone), 36 moves plus Struggle (type, category, power, accuracy, base PP, priority, target class, crit ratio, flags, effect id), 16 abilities and 11 items (effect ids), the 18-type chart, the 25 natures, and per species the move list of its set in decision `0004`.
- **Metadata is not mechanics** (ARCHITECTURE §2, §8). An effect id only names a typed handler written and tested in C.
- **Support manifest in code.** A compiled table marks each mechanic id (move effect, ability, item, status, field effect) as implemented. Setup computes the mechanic set of both teams; if any member of it is not implemented, creation fails with `E_UNSUPPORTED`. This is the no-fake-success gate: development fixtures are closure-legal sets whose mechanics are all implemented, and the two real teams pass only when the last flag is set (step 13).
- **Setup v3 (CLOSURE):** per member species, gender (required, must be legal for the species), nature, Stat Points (at most 32 each and 66 in total), ability, item and 1 to 4 moves from the species' list. Level is 50. Species Clause and Item Clause are enforced. The engine derives stats and PP; the synthetic `hp_max`/`pp_max` inputs exist only for `SYNTHETIC`.
- **Fingerprint v3** covers the configuration and the hash of the generated tables.

### 2.1 As built (step 1b-2)

- **Data kinds.** `SYNTHETIC` (1) is unchanged. `CLOSURE` (2) accepts format-legal sets only. `CLOSURE_DEV` (3) is `CLOSURE` except that a member may have No Ability. A CLOSURE config gives no species or move count and no table; the context uses the generated tables (16 formes, 37 moves; the target classes of the 36 team moves equal the M2 table T1) and puts the closure table hash where SYNTHETIC puts the hash of its target-class table. The canonical context bytes keep their 63-byte layout.
- **Why `CLOSURE_DEV`.** Every forme of the two teams has exactly one closure ability, and each of them is a mechanic of step 5, 7 or 12. With format legality alone, no battle could pass the gate before step 7. No Ability lets development fixtures isolate the mechanics of a step. The reference can replay such fixtures: the pin has the ability "No Ability" (`data/abilities.ts:36-42`), and a simulated battle does not run the team validator. A `CLOSURE_DEV` fingerprint differs from a `CLOSURE` one, so development states never pass as format states. **Owner review requested.**
- **Setup.** The member setup gains gender, nature, six Stat Points, ability and item; under CLOSURE, `hp_max`, `pp_max` and the stone flag must be 0 because the engine derives them. Rules, in check order: a base forme, 1 to 4 distinct moves of the forme's set, a gender legal for the species, nature < 25, Stat Points at most 32 each and 66 in total, the forme's ability (or No Ability under `CLOSURE_DEV`), an item or none; then Species Clause and Item Clause per side. Any closure item may be held; a Mega Stone makes the member Mega-capable only on its own species. A SYNTHETIC setup must leave every new field 0. Every violation is `E_INVALID_ARGUMENT`.
- **The gate.** `src/data/support_manifest.c` marks the core (turns, damage, switching, fainting, win rule and Struggle), Mega Evolution, and each move, ability and item. A legal setup needs the core, every move, ability and item of its registered members, and for a member holding its own stone, Mega Evolution and the Mega forme's ability. Anything unmarked gives `E_UNSUPPORTED` after all validation. In this build every flag is 0.
- **Member invariant of CLOSURE data** (reported as `MEMBER_EXTRA`): base forme, legal gender, nature and Stat Points in range, stone flag equal to "holds its own stone", Mega forme only with the stone, the current ability (the Mega forme's after Mega Evolution), `hp_max` and stats equal to the formulas for the current forme, moves of the set without repeats and PP maxima equal to the rule, sleep and freeze with a counter 1..3 and no counter otherwise. Current HP, PP, the consumed flag and the status itself stay free.
- **White-box path.** `dfi_battle_create_ungated` builds a legal CLOSURE team without the gate, so tests can check what the reference teams would be (every stat line of decision 0004). The public create never skips the gate.

## 3. Owned state v3 (one design for the whole closure)

Schema 3 / semantics 3 ("duoforge-m3-closure"). Fixed size, no padding, same envelope. The exact layout table and its static asserts are written in step 1; the v2 goldens become "rejected: schema 2" inputs.

| Group | Fields (new in v3 unless marked v2) |
|---|---|
| Header | fingerprint, RNG, next activation, boundary kind, request mask, epoch (v2); turn counter; execution phase; terminal result (none, side 0, side 1, tie). Boundary kind gains TERMINAL, the only kind with an empty request mask. |
| Field | weather and turns left; terrain and turns left; Trick Room turns left. |
| Side | roster count, brought mask and order, requested slots, Mega used, seen mask, sealed re-prompt record (v2); Reflect, Light Screen and Tailwind turns left. |
| Member (persistent) | base species, Mega flag, gender, nature, Stat Points, current stats, HP, status and its counter, item and consumed flag, current ability, four moves with PP and max PP. |
| Active slot (cleared on entry) | occupant and activation id (v2); seven stat stages; volatile flags (flinch, protect, Flash Fire, charging); stall counter; confusion turns; locked move and its target; move actions since entry (Fake Out); switch flag (pivot, Emergency Exit). |
| Action queue (continuation) | up to 12 records: kind, side, slot, activation binding, move slot, target, order class, priority, speed key, consumed flag; queue length and cursor; the sub-position inside a paused action. |
| Knowledge (per player) | seen mask (v2); per opposing member last seen HP percent and flag, observed uses per move, item-consumed and Mega-seen flags. |

- **Bounds.** The queue holds at most 2 Mega actions, 4 move or switch actions, 4 forced switch-ins and the residual action; 12 leaves one spare, and overflow is `E_INVARIANT`, never a dropped action.
- **Continuation** (DECISION_CONTRACT §5). A pause stores the queue, the cursor and the sub-position; nothing needed after the call returns lives on the C stack.
- **Last-seen HP** replaces the M2 prototype rule for benched opponents (decision `0005` section 6 limit).
- **Rule-authorized re-prompt** keeps its v2 record. No mechanic in this closure triggers it (no trapping); it stays structural.
- **Invariants** extend to every new field's range and to queue consistency. Decodability is still not reachability.

### 3.1 The layout as built (step 1b-1)

Schema 3, semantics 3, **1009 bytes**. `src/codec/state_codec.h` holds the offset table and its static asserts; `tools/state_model/state_v3_model.py` is the independent oracle.

| Offset | Size | Content |
|---|---|---|
| 0 | 86 | envelope, fingerprint, RNG, next activation, boundary kind, request mask, epoch (as v2) |
| 86 | 3 | turn (u16), result |
| 89 | 5 | weather and its turns, terrain and its turns, Trick Room turns |
| 94 | 121 | queue length, then 12 records of 10 bytes: kind, side, slot, move slot, target, reserve, activation id (u32) |
| 215 | 397 | side 0, then side 1 at 612 |

Per side: the v2 header (member count, brought mask, requested slots, Mega used, sealed, seen mask, bench order), Reflect, Light Screen and Tailwind turns; two positions of 21 bytes (occupant, activation id, 7 stages biased by 6, volatile flags, stall level and turns, confusion turns, charge turns, locked move and target, move actions since entry, switch flag); the sealed record; per opposing member a 7-byte knowledge record (HP percent and flag as last seen, revealed facts, observed uses per move slot); six members of 48 bytes (species, HP, max HP, five stats, move count, Mega stone flag, Mega forme flag, gender, nature, six Stat Points, status and its counter, item and its consumed flag, ability, four moves with PP and max PP).

Three entries of the table above are **not stored**, because the reference makes them derivable. This is a finding of step 1b-1:

- **Execution phase and the sub-position inside a paused action.** The reference pauses a turn only between two actions: after each action it collects the switch flags and makes the switch request (`sim/battle.ts:2876-2915`). Fainted Pokémon are replaced only when the queue is empty (`sim/battle.ts:2840-2843`, `checkFainted` at `:2524-2530`). So a pause mid-turn is always a PIVOT with the rest of the turn in the queue, and a pause after the residual is a REPLACEMENT with an empty queue. The boundary kind is the phase.
- **Queue cursor and consumed flag.** Executed actions leave the queue, as in the reference (`queue.shift`). The residual action is queued with the turn's choices (`sim/battle.ts:2945`), so a mid-turn pause always has a non-empty queue.
- **Order class, priority and speed key per record.** The order class follows from the record kind. Priority and speed are recomputed from the current state before every sort (`sim/battle.ts:2919-2926`, `:2998-3018`), and after a pivot only the new switch actions are sorted in front of the stored rest of the turn. The stored order is what a later sort shuffles ties from.

Two fields make explicit what the table implied:

- **Switch flag** per position: the cause of a PIVOT slot (a self-switch move, `sim/battle-actions.ts:1312`, or Emergency Exit, `data/abilities.ts:1250`). It marks exactly the requested slots of a PIVOT and is zero everywhere else.
- **Revealed facts** per knowledge record: the consumed item and the Mega forme of an opposing member, as the viewer saw them. A revealed fact must be true of the member.

New invariant ids, in check order: TURN_COUNTER (0 exactly at TEAM_SELECTION), RESULT (nonzero exactly at TERMINAL), FIELD, MEMBER_EXTRA (SYNTHETIC members have none of the new member fields), SIDE_CONDITION, VOLATILE (value ranges; an empty position is the cleared position), SWITCH_FLAG, KNOWLEDGE (nothing about an unseen member; the display of an active member is current; revealed facts are facts) and QUEUE (non-empty exactly at PIVOT; per-kind operands; zero tail). REQUEST_MASK allows 0 only at TERMINAL, and SEALED_RULE now allows a sealed choice only at a re-prompted TURN, because a PIVOT keeps the rest of the turn in the queue. There are 43 ids.

Behaviour that already uses the new fields: team selection starts turn 1; entering a position clears its volatile block and shows the member's HP display to the opponent; leaving clears the position and the opponent keeps the display it saw last; the observation takes an opposing member's HP only from this knowledge record; a TERMINAL battle requests nobody and rejects every bundle as invalid input.

## 4. Execution model

- **Step on a working copy** (DETERMINISM §6): validate the bundle, turn it into queued actions, run to the next boundary (TURN, REPLACEMENT, PIVOT or TERMINAL) on a stack copy with staged outputs, commit on success. Any failure leaves the committed battle unchanged.
- **Explicit scheduler** mirroring the reference: order classes 3 (forced switch-in), 103 (switch), 104 (Mega), 200 (moves), 300 (residual); then priority, then speed, then a tie shuffle; re-sort after every action (`sim/battle-queue.ts:174-192`, `sim/battle.ts:404-411`, `:2649`).
- **Typed hooks in fixed precedence**, not a generic effect language: priority modification, move blocking, redirection, try-hit (Protect, absorption), type and ability immunity, accuracy, base power, attack and defence modifiers, final damage modifiers, damaging-hit reactions, secondary effects, after-move (Emergency Exit, self-switch), switch-in, residual. Handler order follows the reference's order, priority, speed and sub-order; registration order never decides an outcome.
- **Arithmetic.** Truncating integer math with the reference's 4096-based modifiers: `modify(v, m) = tr((tr(v * tr(m * 4096)) + 2047) / 4096)` and the chained modifier `((prev * next + 2048) >> 12)` (`sim/battle.ts:2321-2343`); base damage `tr(tr(tr(tr(2L/5 + 2) * BP * A) / D) / 50)` (`sim/battle-actions.ts:1718`). These helpers enter `core/arith` with reference fixtures, as decision `0002` section 8 foresaw.
- **Struggle, locked move, Fake Out** become domain rules of the request module, replacing M2's `E_UNSUPPORTED` for Struggle.
- **Terminal.** A finished battle sits at TERMINAL with a result and an empty request mask; any further bundle is malformed input.

### 4.1 The turn core as built (step 2c)

`src/combat/turn.c` runs a TURN boundary of a CLOSURE battle on the working copy of the step:

- **Queue.** One move action per acting slot, in the reference's order of addition (side 0 slot a, b, then side 1), plus the residual action. It is sorted like `Battle.speedSort`: order, priority, speed (the staged Speed, capped at 10000, negated under Trick Room), then a SPEED_TIE shuffle of each tied group. It is sorted twice before the first move, once when the choices are committed and once in the epilogue of the reference's `beforeTurn` action. Afterwards it is sorted again before every move action (`sim/battle.ts:2917-2926`, `:2940-2947`, `:2998-3022`).
- **A move.** The target (a chosen foe; the partner, which is legal in doubles; a random foe when the chosen one is gone; every adjacent foe for spread moves; a random foe for Struggle), PP, what the opponent sees (move use, HP display), then the hit steps in the reference's order: Protect, type immunity, accuracy with the combined stage per target, then per target the critical hit and the damage roll, the damage, and one secondary roll per target, drawn even at 100.
- **Protect.** It fails without a draw when nobody acts after the user (`queue.willAct`). With a stall counter it succeeds on `random(3^level) == 0`, and a failure loses the counter. A success sets the protection and raises the counter. The residual phase ends the protection and counts the counter down.
- **Struggle.** Since 2c the request offers it as `DUOFORGE_MOVE_SLOT_STRUGGLE` with no target when an occupant has no move with PP left. It replaces M2's `E_UNSUPPORTED`; the oracle and decision `0005` section 3 follow. It is typeless and recoils by round(maxHP / 4).
- **Manifest.** It splits into `turn_core` (step 2, required at setup) and `switching` (step 3). A turn that would make a Pokémon faint, a switch, a pass, a Mega declaration, and a member with an unmarked move, ability or item all return `E_UNSUPPORTED`, and the working copy is discarded.
- **Ahead of the step order.** The secondary stat changes of Snarl, Muddy Water, Shadow Ball, Psychic, Focus Blast and Spirit Break belong to step 4 by the task file. Every spread move of the closure has a secondary or a self-drop, and these secondaries are plain stat stages, so step 2 takes them to test spread damage. Status and flinch secondaries stay in step 4.

Conformance: `tools/reference/trace_to_c.py` turns the traces into `tests/reference/conformance.h`. `duoforge.reference.conformance` replays the seven battles with their kept draws as a tape that must be consumed exactly, and compares HP, PP, stages, the stall counter and the turn after every step.

## 5. RNG draw sites

Every draw goes through one internal function that takes a **site id** and a bound and uses the bounded PCG32 of decision `0001`. The registry (stable ids, recorded in the fixtures):

| Site | Bound and meaning | Reference |
|---|---|---|
| SPEED_TIE | shuffle of a tied group of `n`: `n - 1` draws `random(i, n)` | `sim/prng.ts:150-155`, `sim/battle.ts:429-463` |
| ACCURACY | `random(100) < accuracy`, once per target with numeric accuracy | `sim/battle-actions.ts:690-760` |
| CRIT | `random(24)` or `random(8)` equal to 0 | `sim/battle-actions.ts:1623-1646` |
| DAMAGE_ROLL | `random(16)`, factor `100 - r` | `sim/battle.ts:2391-2394` |
| SECONDARY | `random(100) < chance`, drawn even at 100 | `sim/battle-actions.ts:1336-1352` |
| STALL | `random(counter) == 0` from the second consecutive Protect | `data/conditions.ts:439-462` |
| SLEEP_TURNS | `random(3)` over `[2, 3, 3]` | `data/mods/champions/conditions.ts:11-30` |
| FREEZE_THAW | `random(4) == 0` while the counter is positive | `data/mods/champions/conditions.ts:31-56` |
| FULL_PARALYSIS | `random(8) == 0` | `data/mods/champions/conditions.ts:2-10` |
| CONFUSION_TURNS | `random(2, 6)` at start | `data/conditions.ts:162-197` |
| CONFUSION_HIT | `random(100) < 33` per attempt, then a DAMAGE_ROLL | same |
| RANDOM_TARGET | `random(n)` over the valid foes when the chosen target is gone | `sim/battle.ts:2440-2521` |

- **No Showdown PRNG parity** (decision `0001`, DETERMINISM §3). What must agree with the reference is the **sequence of sites, bounds and outcomes**, not raw seeds.
- **Test-only tape.** Conformance tests run the same step through an internal, white-box entry point that takes the outcomes from a tape instead of the PCG. The tape states site and bound for every draw; a mismatch or an exhausted tape is an explicit error, never a silent fallback. The tape is not in the public header and not in any production path; replay and normal play use the PCG.
- The gender draw at construction (`sim/pokemon.ts:421-430`) does not exist here because gender is always specified.

### 5.1 What the recorded battles show (step 2b)

`tools/reference/ps_trace.js` recorded three development battles (No Ability, no items; `tests/reference/specs/`). Every draw carries a site and a context: the sort or event it belongs to. Counted over the three traces:

| Family | Context | Draws | Effect on the outcome |
|---|---|---|---|
| ACCURACY, CRIT, DAMAGE_ROLL, SECONDARY, STALL | move execution | 55 | decides it |
| SPEED_TIE | `queue`: tied actions in the turn order (`sim/battle.ts:429-463`) | 47 | decides the order |
| INSERT_TIE | a random position among tied actions when one is inserted (`sim/battle-queue.ts`, `insertChoice`) | 2 | decides the order |
| SPEED_TIE | `switch-order`: the actives sorted at a switch-in (`sim/battle-actions.ts:181-183`) | 2 | orders entry effects |
| SPEED_TIE | `field:Residual`: residual handlers, including handlers that only count down a duration (Protect and its stall counter tie on one holder) | 16 | none between counters of one holder; ties between holders can order damage, healing and fainting |
| SPEED_TIE | `each:Update`, `each:BeforeTurn`: all actives by speed before an event (`sim/battle.ts:466-475`), after every action | 167 | none unless tied actives both handle the event |
| RANDOM_TARGET | `action-speed`, `resolve`: the target computed for ModifyPriority or when a choice is queued | 24 | none: no closure handler reads that target |
| RANDOM_TARGET | `execute`: Struggle's real target, or the displayed main target of a spread move | 6 | decides Struggle's target |
| TEAM_ORDER | the team-preview actions, each side ordering only its own list | 6 | none |

The first battle, without speed ties, has 17 draws. The Struggle battle has two Milotic of equal speed on the field and 218 draws, 115 of them `each:Update`. Aligning DuoForge with the reference therefore means choosing how to treat the families without effect. **Owner decision requested:**

- **B, proposed, and how step 2c starts.** The engine draws only where a value can change the outcome. The trace converter keeps every draw of the first block and drops each family without effect by a named rule with a precondition it checks: `each:` ties only when no tied Pokémon has a handler for that event in the fixture; residual ties only between duration counters of one holder; `action-speed` and `resolve` targets always; TEAM_ORDER always. A dropped draw is listed in the generated fixture, so nothing disappears silently. If the engine and the reference disagree on a draw the converter kept, the tape fails.
- **A, the alternative.** The engine mirrors every sort and target call of the reference, draws included, so the converter drops nothing. That is B plus engine code that exists only for alignment; it can be added later without undoing B. Events, knowledge and observation

- A step produces **semantic events** (move used, damage as seen by each side, status, stage change, item consumed, ability shown, field and side condition start and end, switch, faint, Mega, result). Each event has a visibility: public, one side, or privileged.
- **One source for knowledge.** The per-player knowledge state is updated only by folding the events that player may see. Observations read own state plus knowledge, never the opponent's state.
- **Events are outputs, not state** (DETERMINISM §5). They are staged during the step; a too-small caller buffer returns `E_CAPACITY` with the required count and commits nothing, as in decision `0005` section 7.
- **Observation v2** adds what is public: statuses, stat stages, field and side conditions with turns, Mega formes, consumed items, last seen HP and observed move uses of the opponent. Exact PP and exact HP of the opponent stay hidden.
- Paired-information tests are extended with every mechanic that hides or reveals something.

## 7. Reference fixtures

- **Harness** `tools/reference/ps_trace.js` (our code, run with Node against the checkout). It passes a recording PRNG through the battle option `prng` (`sim/battle.ts:66`, `:224`), so every `random`, `randomChance`, `sample` and `shuffle` call is logged with its bounds and result, together with requests, choices and the battle log.
- **Input:** a fixture specification (format id, both teams with gender, the choices per request). **Output:** a normalized trace (requests, draws, HP and status at each boundary, events).
- **Formats.** `gen9championsvgc2026regmc` for the real teams. Development fixtures record the exact format id they used and whether it runs in debug mode (exact HP), so no fixture silently mixes display rules.
- **Into the tests.** Traces are committed under `tests/reference/` with pin, harness version and specification. A generator turns them into C fixture tables; CTest consumes only the generated tables and never runs Node. An optional test with label `reference` reruns the harness when the checkout and Node are present.
- **Draw alignment.** Each reference draw maps to a DuoForge site by position and bound. A count or bound mismatch fails the fixture; it is fixed in the engine or recorded as a known divergence in `docs/OPEN_DECISIONS.md`, never patched in the trace.
- Showdown is a reference implementation, not proof of cartridge behaviour (TESTING §2). Where https://www.pokewiki.de/ and the pin disagree, the disagreement is recorded and the owner decides.

## 8. Evidence per step

Every step of the task file delivers: unit tests with reference-derived expectations, interaction tests for the cross-team interactions it makes reachable, snapshot and resume tests at every boundary it can produce, draw-count tests against the registry, paired-information tests, malformed-input atomicity, negative controls, and executed reference fixtures. The oracle in `tools/state_model/` is extended to state v3 and the new domain rules.

## 9. Local verification (owner, 2026-10-01)

- Local builds run **natively on Windows**; WSL is no longer used.
- Toolchains (all native): MSVC (Visual Studio Build Tools 2022, Visual Studio generator), GCC 16.2 (WinLibs MinGW-w64 UCRT) and Clang 23.1 (LLVM, MSVC target), the latter two through Ninja, each in Debug and Release with `-DDUOFORGE_WARNINGS_AS_ERRORS=ON`.
- GCC and Clang were installed on 2026-10-01 (`winget install BrechtSanders.WinLibs.POSIX.UCRT`, `winget install LLVM.LLVM`). They are newer than the hosted CI compilers (GCC 13.3, Clang 18.1), so both sets of warnings have to stay clean.
- **Sanitizers stay in hosted CI.** MinGW GCC ships no AddressSanitizer and leak detection does not exist on Windows, so the GCC ASan/UBSan job on Linux is observed on every push before a step counts as done.

## 10. Alternatives considered

- Loading data from JSON at run time: rejected; generated C tables keep parsing and file access out of the core.
- A generic effect language: rejected (ARCHITECTURE §6); typed hooks with reference-derived order.
- Storing the event history in the battle: rejected (DETERMINISM §5); compact knowledge in state, events as output.
- Showdown PRNG parity: rejected (decision `0001`); semantic draw alignment through a test-only tape.
- Dropping `SYNTHETIC`: rejected; the exhaustive domain tests need all nine target classes, which the closure does not contain.
- Two schema bumps (one per former milestone): rejected by the owner's no-backlog decision.

## 11. Points the owner should look at

1. The support manifest as the setup gate (section 2).
2. The state v3 groups (section 3): anything missing here means a later schema bump.
3. The test-only tape (section 5) as the way to align with the reference.
4. Events as step output with the `E_CAPACITY` convention (section 6).
