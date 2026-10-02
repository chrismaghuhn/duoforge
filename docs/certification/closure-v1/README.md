# Certification report: closure-v1

The first fixed-matchup certification (roadmap M5, decision 0010), 2026-10-01. It is scoped engineering evidence for the profile below, not a proof about every reachable state.

## 1. Certified profile

| Item | Value |
|---|---|
| Format | `[Gen 9 Champions] VGC 2026 Reg M-C` (`gen9championsvgc2026regmc`) |
| Executable reference | Pokémon Showdown `b2cb775b0616115b775534eaeff50300e1fc81fc` (Champions mod) |
| Teams | A and B of decision 0004 (`tests/reference/teams/team_a.txt`, `team_b.txt`), genders and stat points as given there |
| Pairings | A-B, B-A, A-A, B-B |
| Data kind and context | `CLOSURE`, `max_roster` 6, `brought_count` 4, exactly 6 registered members per side (context fingerprint `09d8d247c926610b2c3957002644221c01cc07d268bfa98461575c3b1c6a8306`) |
| Information profile | decision 0007: observation v2 and the per-player event log |
| State artifacts | BATTLE_STATE v3, CONTEXT v3, semantics 3, SHA-256 digests |
| Randomness | PCG32 XSH-RR (decision 0001), draw alignment B (decision 0006 section 5.1) |
| Library | 0.8.0 |

Anything outside the profile is rejected explicitly: another context, a roster of 4 or 5, a set that is not format-legal, or a mechanic outside the support manifest.

## 2. Evidence

| Claim | Evidence | Result |
|---|---|---|
| The engine plays like the reference, draw for draw: requests and candidates, protocol events, state at every boundary | `duoforge.reference.conformance`: 87 recorded battles, 24 of them in the certified profile | 3,014 checks, 0 failures |
| The recorded traces are what the pinned reference produces | `duoforge.reference.trace.*`: every trace re-recorded with the pin and compared (Windows with Node 24, Linux with Node 18) | all identical |
| Damage and stat arithmetic | `duoforge.reference.arith` | pass |
| Random real-team play is valid, replays identically, continues from a decoded state, and the views carry only authorized information | `duoforge.combat.closure_gate`: 4,000 battles, 63,622 steps, 12,217 replacements, 1,959 pivots | 1,339,571 checks, 0 failures |
| The certified dataset reproduces | `duoforge.certify.dataset`: 1,000 battles (250 per pairing), 17,936 steps, 32,216 decisions; each replayed from its choices with an encode/decode continuation and regenerated from its seeds; full state check after every step | 0 failures; bit-identical with GCC, Clang and MSVC (Debug, Release, LTO) on Windows and GCC 13 and Clang 18 on Linux |
| The dataset check is not vacuous | `duoforge.certify.negative.{digest,choice,seed}` | each changed dataset fails |
| The decision domain is exact | `duoforge.request.accepts` (step accepts exactly the enumerated domain), `duoforge.request.candidates_digest` (1,993 lists, 180,562 candidates pinned), candidates compared with the reference in the conformance test | 0 mismatches |
| Only the certified setups are accepted | `duoforge.state.closure_setup`, `duoforge.state.setup_sweep` | pass |
| The information boundary holds | `duoforge.request.information`, `duoforge.state.knowledge`, `duoforge.state.identity`, `duoforge.request.query_checks` | pass |
| The state codec is exact and rejects bad input | `duoforge.codec.golden`, `duoforge.codec.negative`, `duoforge.codec.mutation` | pass |
| Platforms | CI: Linux GCC and Clang (Debug, Release with LTO), GCC with ASan and UBSan, Windows MSVC x64 and Win32 | green |

## 3. The dataset

`dataset.txt` holds, per battle, the pairing, the seeds (one splitmix64 stream from the seed in the file: the battle's `rng_initstate`, then its policy seed; `rng_initseq` 1001), every choice as the index of the chosen candidate (uniform random policy), the step and turn counts, the result and the final digest. `duoforge_certify verify dataset.txt` checks it; `duoforge_certify generate 250 dataset.txt` writes it again, byte for byte.

| Pairing | Side 0 won | Side 1 won | Ties |
|---|---|---|---|
| A-B | 90 | 160 | 0 |
| B-A | 168 | 82 | 0 |
| A-A | 125 | 125 | 0 |
| B-B | 121 | 129 | 0 |

## 4. Findings during the certification

No engine mismatch was found. The new reference battles (step 3) found two tool gaps, both fixed: the harness rejected a planned switch of a trapped Pokémon, and the trace converter turned the "pass" of a fainted partner at a pivot during the turn into a requested pass. Failure minimization (`duoforge_certify minimize`, step 5) is ready for the next mismatch; today no dataset battle fails.

Correction after the certification (2026-10-02): the request offered Struggle together with a Mega declaration, which the reference never does (decision 0006 section 4.1). No dataset battle reaches such a state, so the dataset, the candidate digest and the closure gate are unchanged. The conformance test now checks it (`s16_struggle_mega`).

## 5. Known limitations

- Draw alignment B: the engine's random stream is not the reference's; equality holds per outcome, through the converter's named and checked rules, not per seed.
- Coverage comes from recorded scenarios and random play. There is no adversarial or exhaustive search, and random play reaches some interactions rarely.
- 63 of the 87 recorded battles run under `CLOSURE_DEV` (No Ability or four-member teams). They exercise the same rule code but lie outside the certified profile.
- No VGC compliance claim, and nothing beyond Teams A and B; the third team is a separate expansion track (decision 0009).
- Performance is measured (decision 0008) but is not part of the certification.

## 6. Reproduce

```
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DDUOFORGE_PS_REFERENCE_DIR=<pinned Showdown checkout>
cmake --build build
ctest --test-dir build
build/certify/duoforge_certify verify docs/certification/closure-v1/dataset.txt
python tools/reference/trace_to_c.py . --check
```

The reference battles of step 3 come from `python tools/reference/gen_real_specs.py --checkout <pin> --candidates 40 --keep 4`.
