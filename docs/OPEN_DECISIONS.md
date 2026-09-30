# Decisions to resolve at the correct milestone

Do not block M0 on all future choices. Conversely, do not silently turn unreviewed assumptions into authoritative rules.

| Decision | Proposal / current status | Must be resolved before |
|---|---|---|
| Language | C17 | M0 |
| Workspace | New dedicated local project, working name `pokemon-doubles-core` | Any writes |
| Platforms | Windows development and Linux validation; actual toolchains recorded | M0 build evidence |
| Game generation | Generation 9 | Content implementation |
| Combat format | Doubles, two sides, two active positions each. **Structurally implemented in M2** (positions, joint side choices, absolute target selectors; decision 0005) | M2 |
| Official regulation | **Owner decision 2026-09-30:** Pokémon Champions, `[Gen 9 Champions] VGC 2026 Reg M-C` (decision 0004). Still no VGC-compliance claim for engine output | VGC claims/certification |
| Operational mechanics reference | **PINNED:** Pokémon Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc` (owner: "take the newest", 2026-09-30; decision 0004) | M3 fixtures |
| Initial teams | **SELECTED by the owner 2026-09-30:** pokepast.es 470a6ec2468af8a4 and 7c9c0663ef60180e (decision 0004). The closure is inventoried in `docs/research/` (12 rows, draft, source-read only); the proposed M3/M4 split in `docs/research/mechanics-inventory.md` section 5 awaits owner review | M3 |
| Roster selection | **M2:** ordered pick of `brought_count` from the registered roster, first two lead, all 360 ordered 4-tuples enumerated (decision 0005 section 2). Registered size 4..6 vs exactly 6 remains an owner question for real teams | M3 |
| Information policy | **M2 prototype:** open sheets (species, moves, stone flag), own exact HP/PP, foe HP floor-percent with 20/50 flags for seen members, tagged unknowns, private bench order (decision 0005 section 6). Open: gender default (currently open), and knowledge must snapshot last-seen bench HP once bench HP can change (M3) | M3 real inputs |
| Tera and special cases | Champions: Mega Evolution is the only special mechanic (no Tera/Z/Dynamax). **M2:** declaration in the domain (once per side per battle, only for a synthetic stone holder, never on a switch); effects are M4 | M4 (effects) |
| RNG | PCG32 XSH-RR, pcg-c-basic@bc39cd7; decision 0001 (implemented M1; pending owner review) | M1 |
| Batch seed derivation | Tagged deterministic setup mapping; not worker-derived; must emit `initseq < 2^63` (decision 0001) | M6 |
| Project license | Not chosen. An Apache-2.0-derived file is present (`src/rng/pcg32_derived.{h,c}`, `third_party/pcg-c-basic/`); a future project license must be compatible | Publishing licensed project material |
| Dependencies | Minimal, pinned, notice/provenance review required | Adding dependency |
| ABI stability | Opaque handles proposed; no frozen full ABI yet | External consumers |
| Numerical performance target | None until baseline measurement | Performance claims |
| First ML algorithm | Deferred; candidate-scoring interface does not require a chosen algorithm | Learner task |
| State artifacts | BATTLE_STATE v2 / CONTEXT v2 / semantics 2 / SHA-256 digest; reject on mismatch, no migration before certification (decisions 0002, 0005); the v1 goldens are rejected inputs | — |
| Caller-provided battle storage / placement API | Only if a measured need arises | M6 |
| Synthetic `hp_max`/`pp_max` inputs | Replaced by real derivation from the pinned Champions data | M3 |
| Variable-size output convention | **RESOLVED (decision 0005 section 7):** exact count in the request plus required-size out-param on `E_CAPACITY` plus the profile bound `DUOFORGE_MAX_CANDIDATES`. Superseded text: decide with enumeration-cost evidence and the information-safety rules of decision 0002 §9 | M2 |
| Battle creation at a TEAM_SELECTION boundary | **RESOLVED (decision 0005):** the brought/leads setup path is removed; every battle starts at TEAM_SELECTION; mid-turn fixtures are white-box test builders | done |
| Request-mask visibility | The observation carries only the viewer's own `requested` flag; whether the opponent must also act at a pause is not exposed yet (decision 0005 section 6). Decide with the first real pivot mechanic | M4 |
| Apache-derived file approval | Owner approves `src/rng/pcg32_derived.{h,c}` and decides whether `LICENSE` gets a factual third-party pointer | Publishing |

## Reference lock discipline

A source-lock manifest must contain the concrete repository/revision/path/content hash that was actually used. The source links in `SOURCES.md` were inspected on the stated date but are mutable upstream URLs, not a completed lockfile.

A scaffold may state `UNPINNED`; certification must reject that state. Do not use a placeholder 40-character hash or 'latest' as if it were verified provenance.

## Keep decisions small

An accepted decision note should explain the choice, alternatives considered, compatibility consequences and tests. Do not build a new architecture-governance framework before the first correct battle. Most implementation details can remain ordinary documented code until they affect a persisted artifact or external consumer.
