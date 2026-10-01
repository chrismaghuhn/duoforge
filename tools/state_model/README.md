# Structural state model (offline test oracle)

`state_v3_model.py` is a stdlib-only Python model of the structures and decision domains of state schema 3:

- canonical context bytes (with the target-class table hash) and fingerprint;
- synthetic setup validation and init (a TEAM_SELECTION state);
- the invariant checker v3 in its fixed order (43 ids);
- canonical encoding v3 (1009 bytes) and strict decoding;
- the mechanics-free team-selection transition (it starts turn 1);
- the knowledge record: what each player saw last of the opposing members;
- the complete side-choice domains in documented order (team picks; TURN, REPLACEMENT and PIVOT joint slot choices with the reserve, Mega and forced-switch constraints; nothing at TERMINAL);
- the perspective-safe observation (320 bytes).

It was written from the decision notes (`docs/decisions/0002`, `0005`, `0006` section 3), **not** from the C sources. It is **not** a model of Pokémon combat rules, and CTest **never** runs it. Python and bindings must not contain hidden rule implementation (AGENTS.md); this file is test evidence only.

It prints every golden value the C tests assert:

- context bytes and fingerprints (C1..C4, and the CLOSURE contexts K1 and K2, whose data hash is the closure table hash);
- fixture encodings and digests (G1, F1, F2, G3, F3, F4..F6, G7, F8..F13);
- per fixture and player the request, the candidate count and the SHA-256 of the concatenated canonical candidates (small domains are listed in full);
- per fixture and player the SHA-256 of the observation;
- the mutation region table and the per-region outcome counts of the exhaustive single-byte mutation sweeps (F1, F2, F5);
- the 139 targeted invariant edits and 8 accepted edits;
- setup-sweep counts.

With `--goldens` it prints `tests/support/goldens.c` (the C1 context bytes and the F1, F2, F3 and F5 encodings).

`state_v1_model.py` and `state_v2_model.py` are the M1 and M2 models. They stay as the derivation record of the schema-1 and schema-2 goldens (`tests/support/goldens_legacy.c`) that the v3 tests use as "rejected: old schema" inputs.

## Run

```sh
python3 tools/state_model/state_v3_model.py > model_out.txt
python3 tools/state_model/state_v3_model.py --goldens > tests/support/goldens.c
```

The run takes about three minutes (the mutation sweeps decode about 770,000 inputs). The output is identical on every platform (LF line ends).

## Rules

- Never copy C encoder output into test expectations.
- If this model and the C code disagree, stop and reconcile by review against the decision notes.
- A schema or semantics bump needs a new model version. The previous goldens then become "rejected: schema N" tests.
