# Research drafts (unverified)

The files here are **agent-generated research drafts**. They are **not contracts, not evidence, and not a support claim**. Before any implementation relies on a statement, check it against the pinned Pokémon Showdown revision `b2cb775b0616115b775534eaeff50300e1fc81fc` (`docs/decisions/0004`).

| File | Content | State |
|---|---|---|
| `champions-reg-mc-report-draft.md` | Champions VGC 2026 Reg M-C: profile parameters, mechanics delta versus Gen 9, M2 decision-domain impact (Mega, team preview, mid-turn boundaries, open team sheets), open questions | Research workflow plus one critic pass (2026-09-30). The M2 points were verified against the pin in `docs/decisions/0005` |
| `matchup-inventory-draft.jsonl` | Per-Pokémon reachable-mechanics closure. One JSON line per team member; fields: id, category, behavior, Showdown refs, RNG draws, dependencies, complexity, uncertainty | **12 of 12 team members, 375 mechanics.** Rows 1–8 come from the first research pass; rows 9–12 (Archaludon, Farigiraf, Charizard, Grimmsnarl) were added on 2026-09-30 by source reading |
| `mechanics-inventory.md` | Synthesis: closure tables extracted from the pin, the three cross-cutting passes (implicit mechanics, cross-team interactions, decisions and information), the build order (owner decision 2026-09-30: continuous, no backlog), the verification pass and open points | Draft; build order decided by the owner |

## What was and was not verified

- **Source reading only.** No simulator was run. Statements in rows 1–8 that say "executed" were not re-run.
- `tools/research/verify_inventory.py` recomputes every quoted stat line, checks that every `path:line` reference lies inside the pinned file, extracts the move, ability and item tables from the pinned data, and compares the M2 target-class table with the pin.
- Executed reference fixtures (the differential oracle of `docs/TESTING_AND_BENCHMARKS.md` section 2) are still **NOT_RUN**; they need Node and the pinned repository.

## Before combat work

The owner decided on 2026-09-30 to build the closure continuously with no backlog, in the order of `mechanics-inventory.md` section 5 (`tasks/M3_M4_COMBAT_CLOSURE.md`). The remaining open points are in section 7 and in `docs/OPEN_DECISIONS.md`. Combat work starts only when the owner asks for it.
