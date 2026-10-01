# 0010 — First certification: the closure matchups (M5)

Status: proposed 2026-10-01. Section 1 records the owner's answers; section 3 answers the owner's question about `CLOSURE_DEV`. (0009 is reserved for the Team C expansion track.)

Roadmap M5 asks to freeze the team specifications, the rules and information profiles, the source pins and an evidence manifest, then to certify a small reproducible matchup dataset with a test report. This note freezes the profile, lists the evidence that exists and the steps that are missing.

## 1. Owner decisions (2026-10-01)

- **RNG:** PCG32 XSH-RR as implemented (decision 0001) is confirmed.
- **Draw alignment B** (decision 0006 section 5.1) is confirmed: the engine draws only where a value can change the outcome; the trace converter drops the reference's other draws by named, checked rules. It also saves work in every battle.
- **Roster:** register 6, bring 4.
- **`CLOSURE_DEV`:** the owner asked whether removing it makes sense. Recommendation in section 3: keep it, outside the certification.

## 2. The certified profile

| Item | Frozen value |
|---|---|
| Format | `[Gen 9 Champions] VGC 2026 Reg M-C` (`gen9championsvgc2026regmc`) |
| Executable reference | Pokémon Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc` (Champions mod) |
| Teams | A and B, the owner's selections (decision 0004: pokepast.es `470a6ec2468af8a4`, `7c9c0663ef60180e`), with the sets, genders and stat points the test support builds (`df_setup_teams`) |
| Pairings | A-B, B-A, A-A, B-B |
| Data kind and context | `CLOSURE`, `max_roster` 6, `brought_count` 4; both sides register exactly 6 members (context fingerprint `09d8d247c926610b2c3957002644221c01cc07d268bfa98461575c3b1c6a8306`) |
| Information profile | decision 0007: observation v2 (736 bytes) and the per-player event log |
| State artifacts | BATTLE_STATE v3, CONTEXT v3, semantics 3, SHA-256 digests; library 0.7.0 (with the freeze of step 2) |
| Randomness | PCG32 XSH-RR (`pcg-c-basic@bc39cd7`), draw alignment B |

The reference accepts 4 to 6 registered members in this format (its minimum is the picked team size, 4). The certified profile is narrower by the owner's decision; under `CLOSURE` the engine is to reject the rest explicitly (section 4, step 2), never accept it silently.

## 3. `CLOSURE_DEV` stays, outside the certification

46 of the 71 recorded battles use No Ability, so that one mechanic is tested without ability interference (Intimidate, the weather and terrain setters), and 63 use four-member teams. Removing `CLOSURE_DEV` would mean re-recording them with full teams and losing that isolation, with no safety gain: its context has its own fingerprint, so its battles and states are never accepted by a `CLOSURE` context.

Proposed role: `CLOSURE_DEV` is the development profile. It has the same rule code and tables as `CLOSURE`, plus No Ability and rosters of 4 to 6. Its battles are evidence for the mechanics, not for the certified profile.

## 4. M5 steps

1. This note.
2. **Profile freeze in code.** `CLOSURE` accepts only the context (6, 4) and exactly 6 members per side; anything else fails explicitly (`E_INVALID_ARGUMENT` at setup, `E_INVARIANT` for a state). Four-member fixtures run under `CLOSURE_DEV`; the conformance test already falls back to it. Done in library 0.7.0: 8 of the 71 recorded battles now run under `CLOSURE`.
3. **More reference battles in the certified profile.** Today 8 recorded battles are full real-team battles. Add recorded battles of the real teams for all four pairings (random plans; seeds searched for coverage).
4. **Certified dataset.** A runner plays N battles per pairing with a documented seed derivation and the uniform random policy, stores per battle the seeds, the command tape and the final digest, and replays every battle. Output and manifest (versions, pins, fingerprints) go to `docs/certification/closure-v1/`.
5. **Failure minimization.** A tool that shrinks a failing battle (seeds, tape, failing check) to the shortest prefix and the simplest choices that still fail.
6. **Report.** Evidence per claim, results and known limitations.

## 5. Evidence that exists

| Claim | Evidence |
|---|---|
| The mechanics match the reference draw for draw, including requests and events | `duoforge.reference.conformance` (71 recorded battles), `duoforge.reference.conformance_tables` |
| The traces are what the pinned reference produces | the reference tests (with `DUOFORGE_PS_REFERENCE_DIR`) re-record and compare every trace |
| Damage arithmetic | `duoforge.reference.arith` |
| Random real-team play, replay, codec continuation, information equivalence | `duoforge.combat.closure_gate` (4000 battles) |
| The decision domain is exact | `duoforge.request.accepts`; the conformance test compares the candidates with the reference |
| Real sets are validated at setup | `duoforge.state.closure_setup`, `duoforge.state.setup_sweep` |
| Information boundary | `duoforge.request.information`, `duoforge.state.knowledge`, `duoforge.state.identity` |
| State codec | `duoforge.codec.golden`, `duoforge.codec.negative`, `duoforge.codec.mutation` |
| Platforms | CI runs the full suite on Linux with GCC and Clang (including ASan and UBSan) and on Windows with MSVC |

## 6. Known limitations (draft)

- Draw alignment B: the engine's random stream is not the reference's. Equality holds per outcome, through the converter's checked rules, not per seed.
- Coverage comes from recorded scenarios and random play; there is no adversarial search.
- No VGC compliance claim, nothing beyond Teams A and B.
- `CLOSURE_DEV` battles test the rule code outside the certified profile.
