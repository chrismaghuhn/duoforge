# Extension system: design draft (after the restructure)

Status: **owner-approved**, 2026-10-11. Built after the repository restructure (#410); each step is its own PR with the full proof suite.
Basis: the retro measurement (kept outside the repository) (batches 1–8, 98 PRs, ~510 mechanics).
Scope: the **behaviour-changing** parts. The behaviour-neutral parts (per-battle pins, numbers from one definition,
docs per mechanic, scaffold, no central allow-list, format axis) are already in the restructure plan (#410, #412, #414, #426).

## Goal

The remaining Champions mechanics (287 blockers, >60 % in the expensive volatile/special/forme families) and later Smogon OU
(#413: ~316 moves, 131 abilities, 151 items missing, plus singles, level 100, EV/IV, Terastallization) must become cheap
to add, without giving up correctness, determinism or the byte-exact checks against Showdown.

**Success measure** (against the retro medians):
- a family-row mechanic touches **≤ 4 artifact kinds and ≤ 8 files** (today: 13 kinds, 41 files);
- a volatile/special mechanic needs **at most half** the commits and no separate Python PR;
- no global pin or shared number changes because of a parallel step.

## Non-goals

- No change to the turn flow's explicit ordering (the plan rule stays): hooks are called by the flow, never self-scheduled.
- No rule implementation in Python (AGENTS.md). This design reduces the Python rule code; it does not add any.
- No loosening of the evidence: every mechanic is still checked against the pinned Showdown.

## Components

### A. One rule source for hidden state (retro item 6)

**Problem.** The tracker re-implements hidden-state rules: Pressure ×4, the Ally Switch field partition ×4, durations ×2.
`FIELD_TURNS` blocked an item step. Every volatile step needed tracker work and often a separate Python PR.

**Design.** The tracker already turns log lines into the engine's event tuples (`ev_tuple`). It hands those tuples to **the
engine's own public-knowledge fold** through a new C API (for example `duoforge_track_fold(track, events, n)`), instead of
folding them in Python. Python keeps protocol parsing: line forms, names to ids, and stops for lines it cannot map. The rule
(counters, durations, slot- vs Pokémon-bound fields, source remaps) lives once, in C, and is the same code the engine uses
for its own knowledge record (`events.c`).

- **Interim step:** durations and constant tables (weather/terrain/screen turns, Taunt/Encore/Disable counts) are generated
  from one C-side table into Python, so `FIELD_TURNS`-style copies disappear before the fold API exists.
- **Proof:** `test_live` record-assembler equality stays the gate (11,590 equal, 0 mismatch today). The tracker's output
  must be byte-identical before and after each migrated fold.
- **Order:** Pressure, Ally Switch and partial trap first. They are the measured duplicates.

### B. Hook table and effect families (retro items 5 and 7)

**Problem.** 87 % of abilities are bespoke C. There are 121 move handler ids. Damage modifiers (about 16 lines each) and
field items (about 12 lines each) are near-identical code.

**Design.**
- Each mechanic **registers hooks** in a generated dispatch table. Hook kinds follow Showdown's events:
  - `onModifyDamage` / base-power / stat chains with their priority;
  - `onResidual` with order and sub-order;
  - on-hit and after-hit triggers;
  - stat-boost triggers;
  - immunities;
  - on-switch-in.
- The turn flow calls a hook point. The table lists who answers, sorted by Showdown's priority, with a fixed tie-break by id.
- **Families are parameterised rows:** a modifier row is (chain, priority, condition kind, numerator/denominator). A
  stat-trigger row is (event, stat, stages, condition). A status-immunity row is (status set, condition). A new
  family-member mechanic is one row in its definition file plus the evidence. Bespoke C stays for the true one-offs.
- **Candidates measured in the retro:** 22 Champions plus 38 OU damage-modifier abilities, the on-hit triggers (26 + 31),
  berries and pinch items.
- **Proof:** migrating existing mechanics into rows keeps `BENCH_SHA256`, the reference digests and perft identical. The hot
  path is measured: the dispatch must not slow the bench (bench with and without, IPO on).

### C. Evidence by scenario and campaign, not by hand (retro item 8)

**Problem.** Median 16 hand-picked recordings per step, 1,935 recording files, 108 MB of `tests/reference`. Tests are 34.7k
lines, twice the engine change. Most of that is C setup code and hand-calculated expectations.

**C1. Scenario language (owner, 2026-10-11).** A small text format for tests, run against **both** the engine and the
pinned Showdown:

```
teams
  p1: Charizard @ Life Orb | Blaze | Flamethrower, Protect
      Incineroar @ Sitrus Berry | Intimidate | Fake Out, Flare Blitz
  p2: Garchomp @ Choice Scarf | Rough Skin | Earthquake, Dragon Claw
      Amoonguss @ Rocky Helmet | Regenerator | Spore, Rage Powder
seed 7

turn 1
  p1a move flamethrower -> p2b
  p1b move fakeout -> p2a
  p2a move earthquake
  p2b move ragepowder

expect p2a flinched
expect p2b hp < 60%
expect same as showdown
```

- **Runner.** A Python runner (`tools/scenario/`) parses the file. It drives the engine through the existing bindings and
  Showdown through the existing `ps_trace`/`ps_play` tools, and compares the event streams the same way the conformance
  tests do. It only drives and compares; it contains no rules (AGENTS.md).
- **Expectations.**
  - `expect same as showdown` is the default oracle: no hand-calculated damage.
  - Targeted checks are possible as well: `hp`, `status`, `boost`, `event`, `item`, `ability`, `field`.
  - `expect refused <cause>` covers mechanics that are not supported yet.
- **Chance.** Use `seed N` first, with a helper that searches a seed giving the wanted outcome (crit, roll, secondary)
  in both engines. Add a test-only forced-chance mode only if seed search proves too slow. It is internal
  (`tests/support`), never in the public API, and Showdown gets the same forced values.
- **Files.** One scenario file per case under `tests/scenarios/<area>/<mechanic>/`, registered per folder with CTest labels
  (area + tier). A scenario that matches Showdown can be frozen into a per-battle reference record (plan step 2) with
  one command.
- **Effect.** A new mechanic's tests become a few scenario files instead of a C test plus hand recordings. Scenario files
  are also the natural seed for campaigns (C2) and for the scaffold (plan step 12).
- **Order.** It can be built right after the restructure, independently of A, B and D, and is the first candidate,
  because every following mechanic profits from it.

**C2. Campaigns.**
- Family rows are proven by **random-set differential campaigns** against the pinned Showdown: the #396 fuzz and the
  existing difftest. A per-mechanic evidence record (machine-readable: trigger counts, battles, seeds) replaces most
  hand recordings.
- Hand-calculated recordings stay for volatile and special mechanics, and as regression pins for found bugs.
- **Gate:** a mechanic counts as supported when its campaign shows at least N triggers of each of its hooks with 0
  deviations. N is set per family.

### D. State storage by declaration (retro item 2, the part that changes the schema)

**Problem.** Fixed tail bytes ran out: the position reserve is full. Each byte needed hand rules for Ally Switch, Baton
Pass and clear-on-switch, written again in the tracker and the state model.

**Design.**
- A **declared field table**. Per field it gives the name, width, scope (position / member / side / field), its range
  rule, and its behaviour on switch out, Ally Switch (moves with the Pokémon / slot-bound / relinked) and Baton Pass
  (copied or not).
- The codec, the invariant checker, the swap/copy/clear code and the tracker's partition are **generated** from it. This
  removes the ×4 swap duplication structurally.
- **Schema revision 6.** Old states are refused as "old schema", exactly like the earlier bumps; the goldens move.
- **Model independence.** The independent state model reads the declaration as its specification (data, not engine
  code) and keeps its own codec. A test compares both on sweeps, as #424 does for the tail today.

## Rollout (after the restructure, each step its own PR with the full proof suite)

0. **C1 scenario language:**
   - the runner, the format, the seed search;
   - 20 existing hand tests and recordings re-expressed as scenarios to prove equivalence (same events, same results).
1. **A interim:** generated duration tables into Python; delete the copies.
2. **B pilot:**
   - the damage-modifier family: migrate the existing modifier abilities and items into rows with identical results;
   - one new Champions mechanic added only as a row;
   - measure its cost against the retro median.
3. **A fold API:**
   - migrate Pressure, Ally Switch and partial trap;
   - `test_live` equality as the gate.
4. **C:** campaign evidence for the rows of step 2. Hand recordings are reduced only where a campaign covers them.
5. **D:** schema rev 6 with the declared field table. Done once, with the migration of all existing tail fields.
6. Then the remaining Champions mechanics through the new path, then OU format work (#413) on top of the format axis.

## Risks

- **Hot path:** a generic dispatch can cost speed. Measure every migration; keep direct calls where the bench shows it.
- **Big-bang temptation:** every step migrates a few mechanics with byte-identical proof, never "all at once".
- **The fold API moves the tracker's correctness onto the C fold:** `test_live` must keep comparing against the engine's
  full state, not against the same fold, or it proves nothing.
- **Schema rev 6** touches every saved state and golden. Do it once, late, after A–C have shown what the table needs.

## Owner decisions (2026-10-11)

1. **Order:** C1 (scenario language) first, then A (one rule source), then B (hooks and effect families), then the OU format
   work (#413) on top of the format axis.
2. **D (declared state storage, schema rev 6)** comes when a mechanic needs new per-member or per-position state that the
   fixed tail cannot hold. Terastallization for OU is the expected trigger.
