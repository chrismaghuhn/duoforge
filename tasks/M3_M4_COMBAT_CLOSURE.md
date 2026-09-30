# Task: M3+M4 — Combat closure for the two reference teams (continuous, no backlog)

## Starting point

- **M2 is complete** (decision `0005`, PR `chrismaghuhn/duoforge#3`). If it is not merged into `main`, base your work on branch `chris/m2-requests-and-commands`.
- **Owner decision (2026-09-30): no backlog.** M3 and M4 of `docs/ROADMAP.md` are built as **one continuous closure** for both reference teams of decision `0004`. There is no parked list of deferred mechanics.
- **Inventory:** `docs/research/mechanics-inventory.md` and `docs/research/matchup-inventory-draft.jsonl` (12 rows, 375 mechanics). It is a **draft from source reading; nothing was executed**. Verify each point against the pin before you rely on it.
- M2 has no combat: a valid TURN, REPLACEMENT or PIVOT bundle returns `E_UNSUPPORTED`. This task replaces that, step by step.

## Budget rule (owner)

- The owner's credit is limited. **Do not use subagents or workflows unless the owner explicitly asks.**
- Read files selectively, do not dump large files, keep command output short, plan briefly.

## Read first

- `AGENTS.md`
- `docs/ROADMAP.md` (M3, M4 and the owner note before M3)
- `docs/DECISION_CONTRACT.md` (entire document, especially §5 mid-turn pauses and §6 failure categories)
- `docs/ARCHITECTURE.md` §4–§8, `docs/DETERMINISM_AND_REPLAY.md`, `docs/TESTING_AND_BENCHMARKS.md` §1–§3
- `docs/decisions/0001`–`0005`
- `docs/research/mechanics-inventory.md` (all sections) and the JSONL rows of the mechanic you are about to build
- The existing code in `include/`, `src/`, `tests/` and the oracle in `tools/state_model/`

## References

- **Executable reference:** Pokémon Showdown at `b2cb775b0616115b775534eaeff50300e1fc81fc`. Keep a full checkout **outside** this repository; vendor nothing. Add the hashes of the `champions` mod files to decision `0004` when you first derive data from them (they are listed in `docs/research/mechanics-inventory.md` section 6).
- **Setting up the checkout runs third-party code** (clone, dependency install, build). Ask the owner before you do it. Node v24 is on the Windows host; WSL has no Node.
- **Lookup source:** the owner named a PokéWiki for questions about intended game behaviour. Record its URL and retrieval date in `docs/SOURCES.md` on first use. It explains; it is **not** a source of test expectations. Where it disagrees with the pin, record a known divergence in `docs/OPEN_DECISIONS.md` and ask the owner; do not pick a side silently.
- Cite `path:line` at the pin for every rule you implement.

## Rules of the no-backlog build

1. **One step at a time, in the order below.** A step is done when it is implemented, tested, documented, committed, pushed and green in hosted CI. Then the next step starts.
2. **Nothing is parked.** If a step needs a mechanic that is not built yet, build it now as part of that step. A deferral needs an owner decision recorded in `docs/OPEN_DECISIONS.md`.
3. **No fake success.** Whatever is not implemented yet still fails explicitly (`E_UNSUPPORTED`, atomic). The two real teams stay **rejected at setup** until the closure gate (step 13) passes; before that, battles run only on labelled development fixtures.
4. **State schema v3 / semantics 3 is designed once** for the whole closure (step 0) and then filled in. No second schema bump inside this task unless the owner agrees.
5. **Only the closure.** Data tables cover the 16 formes, 36 moves, 16 abilities and 11 items of the two teams, each record with provenance at the pin. Any other set is rejected at setup.
6. **Determinism.** Every random draw has a named site and a fixed position in the draw order. Queries stay pure.
7. **Information boundary.** Every new event updates the per-player knowledge state; observations never read hidden state directly. Extend the paired-information tests with each mechanic that hides or reveals something.

## Step order

0. **Decision note `0006`:** state v3 (stat stages, status, volatiles, field and side conditions, action queue and continuation data, Mega forme, per-activation move-action counter, locked move), the RNG draw-site registry, data tables and provenance, the event and knowledge model, and the reference-fixture method (controlled RNG injection; decision `0001` rejects PRNG parity).
1. **Real data and formulas:** context with real tables, Champions stat and PP formulas, real setup validation. Play is still rejected.
2. **Turn core:** action queue and ordering (priority, speed, tie shuffle, re-sort), plain damaging moves single and spread, accuracy with stages, critical hits, random factor, STAB, type chart, stat stages, self-boost moves, PP deduction, Struggle, Protect with the stall counter.
3. **Switching and fainting:** voluntary switch, faint queue, real REPLACEMENT boundaries, win rule.
4. **Secondary effects and statuses:** paralysis, sleep, freeze, burn, flinch, confusion (Champions variants).
5. **Entry abilities, weather, terrain, residual phase:** Drizzle, Drought, Grassy Surge, Intimidate; ordered residuals.
6. **Side and field conditions:** Tailwind, Reflect, Light Screen, Trick Room.
7. **Reactive abilities:** Stamina, Competitive, Contrary, Flash Fire, Lightning Rod, Good as Gold, Armor Tail, Prankster, Blaze, No Guard, Tough Claws.
8. **Items:** Leftovers, Sitrus Berry, Grassy Seed, Life Orb, Miracle Seed, Mystic Water, Light Clay.
9. **Recoil, drain, self-drops:** Wood Hammer, Brave Bird, Bitter Blade, Leech Life, Close Combat, Make It Rain.
10. **Special moves:** Weather Ball, Hurricane, Grass Knot, Grassy Glide, Fake Out (with its disable rule), Electro Shot (charge, rain skip, locked move).
11. **Mega Evolution:** the four formes, timing, the side-wide limit, persistence after fainting.
12. **Pivots:** Parting Shot and Emergency Exit with real PIVOT boundaries and continuation; sealed commitments become real.
13. **Closure gate:** both real teams are accepted at setup; battles run from team selection to a terminal result; no `E_UNSUPPORTED` is reachable inside the closure; bounded random play keeps every invariant and replays byte-identically; information equivalence holds on real states.

The order follows `docs/research/mechanics-inventory.md` section 5. Change it only when a dependency forces you to, and say so in the step's commit message.

## Required tests (every step)

- **Unit and arithmetic tests** with expectations derived from the pinned reference, never from running the implementation once.
- **Interaction tests** for the cross-team interactions of inventory section 3 that the step makes reachable.
- **Continuation tests:** snapshot and restore at every boundary the step can produce; resuming must not repeat PP use, entry effects, damage or draws.
- **Determinism:** same inputs, same bytes; draw counts per action match the draw-site registry.
- **Information boundary:** paired states for everything the step hides or reveals.
- **Malformed-input atomicity** stays separate from rule-authorized rejection.
- **Negative controls** for each important guarantee.
- **Executed reference fixtures** from the pinned simulator once the owner has approved the checkout. Until then mark them NOT_RUN and do not claim parity.

## Verification

- GCC and Clang, Debug and Release, with `-DDUOFORGE_WARNINGS_AS_ERRORS=ON`; the GCC sanitizer build.
- Hosted CI green, including MSVC (`/W4 /WX`, no `max_align_t`).
- Report PASS/FAIL/NOT_RUN/BLOCKED/SKIPPED with commands. Hosted CI counts as PASS only once a run has been observed.

## Git

- Work on one branch for this task. Commit and push every step; every commit must build on its own.
- Commit messages end with the session attribution.
- The owner wants a pull request for finished work: open one when the closure gate passes, or earlier if the owner asks.

## Deliverables

- Code, tests, the extended oracle (`tools/state_model/`), decision note `0006`.
- Updated `README.md`, `docs/support/README.md`, `docs/OPEN_DECISIONS.md`, and provenance for every data record.

## Stop

**Stop after the closure gate** and report: changed files, scope, tests run and not run, open points, and the proposed next step. M5 (certification), M6 (batch runtime) and M7 (Python adapter) are separate authorizations. Do not start them on your own.
