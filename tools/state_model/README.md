# Structural state model (offline test oracle)

`state_v2_model.py` is a stdlib-only Python model of the M2 structures and decision domains:

- canonical context bytes v2 (with the target-class table hash) and fingerprint;
- synthetic setup v2 validation and init (a TEAM_SELECTION state);
- the invariant checker v2 in its fixed order (34 ids);
- canonical encoding v2 (438 bytes) and strict decoding;
- the mechanics-free team-selection transition;
- the complete side-choice domains in documented order (team picks; TURN, REPLACEMENT and PIVOT joint slot choices with the reserve, Mega and forced-switch constraints);
- the perspective-safe observation (320 bytes).

It was written from the decision notes (`docs/decisions/0002`, `0005`), **not** from the C sources. It is **not** a model of Pokémon combat rules, and CTest **never** runs it. Python and bindings must not contain hidden rule implementation (AGENTS.md); this file is test evidence only.

It prints every golden value the C tests assert:

- context bytes and fingerprints (C1..C4);
- fixture encodings and digests (G1, F1, F2, G3, F3, F4..F6, G7, F8..F12);
- per fixture and player the request, the candidate count and the SHA-256 of the concatenated canonical candidates (small domains are listed in full);
- per fixture and player the SHA-256 of the observation;
- per-region outcome counts of the exhaustive single-byte mutation sweep;
- the 41 targeted invariant edits;
- setup-sweep counts.

`state_v1_model.py` is the M1 model. It stays as the derivation record of the schema-1 golden that the v2 tests use as a "rejected: schema 1" input.

## Run

```sh
python3 tools/state_model/state_v2_model.py > model_out.txt
sha256sum model_out.txt
```

The output recorded for M2 (Python 3.12.14, 2026-09-30) has sha256 `4c0eb0fbc7abfd7d8342b0f0c7a540b4bd592b940da2a9cb25cfc52c486340ae`. The run takes about 20 s.

## Rules

- Never copy C encoder output into test expectations.
- If this model and the C code disagree, stop and reconcile by review against the decision notes.
- A schema or semantics bump needs a new model version. The previous goldens then become "rejected: schema N" tests.
