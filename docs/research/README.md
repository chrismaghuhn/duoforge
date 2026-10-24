# Research drafts (unverified)

The files here are **agent-generated research drafts**. They are **not contracts, not evidence, and not a support claim**. Before any implementation relies on a statement, check it against the pinned Pokémon Showdown revision `b2cb775b0616115b775534eaeff50300e1fc81fc` (`docs/decisions/0004`).

| File | Content | State |
|---|---|---|
| `champions-reg-mc-report-draft.md` | Champions VGC 2026 Reg M-C: profile parameters, mechanics delta versus Gen 9, M2 decision-domain impact (Mega, team preview, mid-turn boundaries, open team sheets), open questions | Research workflow plus one critic pass (2026-09-30). The M2 points were verified against the pin in `docs/decisions/0005` |
| `matchup-inventory-draft.jsonl` | Per-Pokémon reachable-mechanics closure. One JSON line per team member; fields: id, category, behavior, Showdown refs, RNG draws, dependencies, complexity, uncertainty | **12 of 12 team members, 375 mechanics.** Rows 1–8 come from the first research pass; rows 9–12 (Archaludon, Farigiraf, Charizard, Grimmsnarl) were added on 2026-09-30 by source reading |
| `mechanics-inventory.md` | Synthesis: closure tables extracted from the pin, the three cross-cutting passes (implicit mechanics, cross-team interactions, decisions and information), the build order (owner decision 2026-09-30: continuous, no backlog), the verification pass and open points | Draft; build order decided by the owner |
| `2026-10-own-algorithm.md` | An own search and learning algorithm for Champions doubles: survey, mapping to the engine's strengths, five ranked proposals with falsifiable hypotheses and cheapest experiments, the owner's CARDS/MADS concepts transferred, what does not fit | Research session of 2026-10-23 (owner brief via the HauptSession). Docs only: nothing implemented, decided or measured; every number names its source |
| `expansion/` | Beyond the closure and Team C: the legal Reg M-C pool (validator at the pin), engine effort per move, ability and item (data, extension, family, bespoke), Smogon 2026-09 usage, a differential-testing design against Showdown, latent issues and a recommended order | Draft of four read-only research agents (2026-10-01), synthesised and spot-checked by the Team C session; the order is the owner's to decide |

## What was and was not verified

- **Source reading only.** No simulator was run. Statements in rows 1–8 that say "executed" were not re-run.
- `tools/research/verify_inventory.py` recomputes every quoted stat line, checks that every `path:line` reference lies inside the pinned file, extracts the move, ability and item tables from the pinned data, and compares the M2 target-class table with the pin.
- Executed reference fixtures (the differential oracle of `docs/TESTING_AND_BENCHMARKS.md` section 2) are still **NOT_RUN**; they need Node and the pinned repository.

## Before combat work

The owner decided on 2026-09-30 to build the closure continuously with no backlog, in the order of `mechanics-inventory.md` section 5 (`docs/history/tasks/M3_M4_COMBAT_CLOSURE.md`). The remaining open points are in section 7 and in `docs/OPEN_DECISIONS.md`. Combat work starts only when the owner asks for it.
