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
| Initial teams | **SELECTED by the owner 2026-09-30:** pokepast.es 470a6ec2468af8a4 and 7c9c0663ef60180e (decision 0004). The closure is inventoried in `docs/research/` (12 rows, draft, source-read only); the owner decided on 2026-09-30 to build it continuously in the order of `docs/research/mechanics-inventory.md` section 5 (see "Build plan for combat") | M3 |
| Roster selection | **M2:** ordered pick of `brought_count` from the registered roster, first two lead, all 360 ordered 4-tuples enumerated (decision 0005 section 2). **Owner 2026-10-01:** register 6, bring 4; the certified profile requires exactly 6 (decision 0010; enforced since library 0.7.0) | done |
| Information policy | **M2 prototype:** open sheets (species, moves, stone flag), own exact HP/PP, foe HP floor-percent with 20/50 flags for seen members, tagged unknowns, private bench order (decision 0005 section 6). Open: gender default (currently open), and knowledge must snapshot last-seen bench HP once bench HP can change (M3) | M3 real inputs |
| Tera and special cases | Champions: Mega Evolution is the only special mechanic (no Tera/Z/Dynamax). **M2:** declaration in the domain (once per side per battle, only for a synthetic stone holder, never on a switch); effects are M4 | M4 (effects) |
| RNG | PCG32 XSH-RR, pcg-c-basic@bc39cd7; decision 0001 (implemented M1; **owner confirmed 2026-10-01**, decision 0010) | done |
| Batch seed derivation | **Resolved (decision 0012):** splitmix64 over the batch seed, the environment and the episode with fixed tags; never from a worker; `initseq < 2^63` | done |
| Project license | Not chosen. An Apache-2.0-derived file is present (`src/rng/pcg32_derived.{h,c}`, `third_party/pcg-c-basic/`); a future project license must be compatible | Publishing licensed project material |
| Dependencies | Minimal, pinned, notice/provenance review required | Adding dependency |
| ABI stability | Opaque handles proposed; no frozen full ABI yet | External consumers |
| Numerical performance target | None until baseline measurement | Performance claims |
| First ML algorithm | Deferred; candidate-scoring interface does not require a chosen algorithm | Learner task |
| State artifacts | BATTLE_STATE v3 / CONTEXT v3 / semantics 3 / SHA-256 digest; reject on mismatch, no migration before certification (decisions 0002, 0005, 0006); the v1 and v2 goldens are rejected inputs | — |
| Caller-provided battle storage / placement API | Only if a measured need arises | M6 |
| Synthetic `hp_max`/`pp_max` inputs | **Done for CLOSURE (step 1b-2):** stats and PP are derived from the generated tables; the inputs stay for SYNTHETIC only | done |
| Observation v2 (public stages, statuses, conditions) and the event log | **RESOLVED (decision 0007, owner 2026-10-01):** exactly what a human player can see, abilities are very important, one design for state and history; foe PP shown as derived, the opponent's request shown, own sleep and confusion turns hidden | done |
| Draw alignment with the reference | **Owner confirmed 2026-10-01** (decision 0010; proposed in step 2b, used since step 2c; decision 0006 section 5.1): B, the engine draws only where a value can change the outcome and the trace converter drops the reference's draws without effect by named, checked rules (team-preview order, `each:` event ties, duration-counter ties of one holder, targets computed for priority). Alternative A mirrors every reference draw. Step 2c starts with B | done |
| Development data kind `CLOSURE_DEV` | **Proposed in step 1b-2** (decision 0006 section 2.1): closure data with No Ability allowed, so development fixtures can run before the abilities exist; separate fingerprint. **Owner accepted decision 0010 (2026-10-01):** kept as the development profile, outside the certification; a side registers `brought_count` to `max_roster` members | done |
| Team C expansion track | **Accepted 2026-10-01** (decision 0009; owner: build it so, with the closure setup rule): data kinds `TEAM_C` and `TEAM_C_DEV` over extended tables whose exact prefix is the closure, so the CLOSURE fingerprint, files, tests and traces stay; state v3 and observation v2 without a layout change; additive public values per step; points in decision 0009 section 9 | done (steps follow decision 0009) |
| Variable-size output convention | **RESOLVED (decision 0005 section 7):** exact count in the request plus required-size out-param on `E_CAPACITY` plus the profile bound `DUOFORGE_MAX_CANDIDATES`. Superseded text: decide with enumeration-cost evidence and the information-safety rules of decision 0002 §9 | M2 |
| Battle creation at a TEAM_SELECTION boundary | **RESOLVED (decision 0005):** the brought/leads setup path is removed; every battle starts at TEAM_SELECTION; mid-turn fixtures are white-box test builders | done |
| Request-mask visibility | **RESOLVED (decision 0007 point B, owner 2026-10-01):** the observation shows that the opponent must answer a pause, because a human sees the switch at once | done |
| Build plan for combat | **Owner decision 2026-09-30: no backlog.** M3 and M4 are built as one continuous closure for both reference teams, in the dependency order of `docs/research/mechanics-inventory.md` section 5. Each step is finished with tests before the next starts; nothing is parked. State v3 is designed once for the whole closure. The real teams stay rejected at setup until the closure gate passes (`tasks/M3_M4_COMBAT_CLOSURE.md`) | done |
| Secondary lookup source | **Owner 2026-10-01:** https://www.pokewiki.de/ (`docs/SOURCES.md` S10) may be consulted for questions about intended game behaviour. The pinned Showdown revision stays the executable reference; disagreements are recorded as known divergences, not resolved silently | done |
| Reference-fixture execution | **Owner approved 2026-10-01.** The checkout is at `C:\Dev\src\pokemon-showdown` (outside this repository, detached at the pin), installed with `npm ci --ignore-scripts --omit=dev`, built with `node build`; the format `gen9championsvgc2026regmc` loads. Method: decision 0006 section 7 | done |
| Gender in team specifications | **Owner 2026-10-01:** always specified. DuoForge has no construction-time gender draw (decision 0006) | done |
| Local verification toolchain | **Owner 2026-10-01:** native Windows, no WSL. MSVC, GCC 16.2 (MinGW-w64) and Clang 23.1 are installed and in the local loop, Debug and Release. GCC ASan/UBSan stays in hosted CI and is observed on every push (decision 0006 section 9) | done |
| Apache-derived file approval | Owner approves `src/rng/pcg32_derived.{h,c}` and decides whether `LICENSE` gets a factual third-party pointer | Publishing |

## Reference lock discipline

A source-lock manifest must contain the concrete repository/revision/path/content hash that was actually used. The source links in `SOURCES.md` were inspected on the stated date but are mutable upstream URLs, not a completed lockfile.

A scaffold may state `UNPINNED`; certification must reject that state. Do not use a placeholder 40-character hash or 'latest' as if it were verified provenance.

## Keep decisions small

An accepted decision note should explain the choice, alternatives considered, compatibility consequences and tests. Do not build a new architecture-governance framework before the first correct battle. Most implementation details can remain ordinary documented code until they affect a persisted artifact or external consumer.
