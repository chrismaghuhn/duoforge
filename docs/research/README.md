# Research drafts (unverified)

The files here are **agent-generated research drafts** from 2026-09-30. They are **not contracts, not evidence, and not a support claim**. Before any implementation relies on a statement, check it against the pinned Pokémon Showdown revision `b2cb775b0616115b775534eaeff50300e1fc81fc` (`docs/decisions/0004`).

| File | Content | State |
|---|---|---|
| `champions-reg-mc-report-draft.md` | Champions VGC 2026 Reg M-C: profile parameters, mechanics delta versus Gen 9, M2 decision-domain impact (Mega, team preview, mid-turn boundaries, open team sheets), open questions | Research workflow plus one critic pass |
| `matchup-inventory-partial-draft.jsonl` | Per-Pokémon reachable-mechanics closure. One JSON line per team member; fields: id, category, behavior, Showdown refs, RNG draws, dependencies, complexity, uncertainty | **Partial:** 8 of 12 team members. Missing: Archaludon, Farigiraf, Charizard, Grimmsnarl (Team B). The cross-cutting passes (implicit mechanics, cross-team interactions, decision/info), synthesis and critics were **not run** (stopped for budget) |

Before M3 the mechanics inventory must be completed: the remaining 4 Pokémon, the cross-cutting passes, and a verification pass against the pinned source.
