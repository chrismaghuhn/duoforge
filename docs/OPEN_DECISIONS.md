# Decisions to resolve at the correct milestone

Do not block M0 on all future choices. Conversely, do not silently turn unreviewed assumptions into authoritative rules.

| Decision | Proposal / current status | Must be resolved before |
|---|---|---|
| Language | C17 | M0 |
| Workspace | New dedicated local project, working name `pokemon-doubles-core` | Any writes |
| Platforms | Windows development and Linux validation; actual toolchains recorded | M0 build evidence |
| Game generation | Generation 9 | Content implementation |
| Combat format | Doubles, two sides, two active positions each | M2 |
| Official regulation | NOT SELECTED; do not claim current VGC compliance | VGC claims/certification |
| Operational mechanics reference | Pinned Showdown revision proposed; commit NOT PINNED | M3 fixtures |
| Initial teams | Two exact teams selected for tractable rules closure; NOT SELECTED | M3 |
| Roster selection | Design supports six registered / four brought and lead assignment; exact first profile pending | M2/M3 |
| Information policy | Explicit profile; open team sheets do not automatically mean full state | M2 observations / M3 real inputs |
| Tera and special cases | Implement required reachable behavior or reject unsupported profile; no invisible approximation | M4/M5 |
| RNG | PCG32 XSH-RR proposed, exact implementation and contract pending | M1 |
| Batch seed derivation | Tagged deterministic setup mapping; not worker-derived | M6 |
| Project license | Not chosen in this pack | Publishing licensed project material |
| Dependencies | Minimal, pinned, notice/provenance review required | Adding dependency |
| ABI stability | Opaque handles proposed; no frozen full ABI yet | External consumers |
| Numerical performance target | None until baseline measurement | Performance claims |
| First ML algorithm | Deferred; candidate-scoring interface does not require a chosen algorithm | Learner task |

## Reference lock discipline

A source-lock manifest must contain the concrete repository/revision/path/content hash that was actually used. The source links in `SOURCES.md` were inspected on the stated date but are mutable upstream URLs, not a completed lockfile.

A scaffold may state `UNPINNED`; certification must reject that state. Do not use a placeholder 40-character hash or 'latest' as if it were verified provenance.

## Keep decisions small

An accepted decision note should explain the choice, alternatives considered, compatibility consequences and tests. Do not build a new architecture-governance framework before the first correct battle. Most implementation details can remain ordinary documented code until they affect a persisted artifact or external consumer.
