# Structural state model (offline test oracle)

`state_v1_model.py` is a stdlib-only Python model of the M1 structures:

- canonical context bytes and fingerprint;
- synthetic setup validation and init;
- the invariant checker in its fixed order;
- canonical encoding v1 and strict decoding.

It was written from the tables in `docs/decisions/0002`, **not** from the C sources. It is **not** a model of Pokémon combat rules, and CTest **never** runs it.

It prints every golden value the C tests assert:

- context fingerprints;
- F1/F2/F3 bytes and digests;
- per-region outcome counts of the exhaustive single-byte mutation sweep;
- the 23 targeted invariant edits;
- setup-sweep counts.

## Run

```sh
python3 tools/state_model/state_v1_model.py > model_out.txt
sha256sum model_out.txt
```

The output recorded for M1 (Python 3.11.15, 2026-09-30) has sha256 `26accd30b43dc60d2ac5fac9e9e2b18fcce2b458b4dfe48e36823caa3893cb78`. The run takes about 5 s.

## Rules

- Never copy C encoder output into test expectations.
- If this model and the C code disagree, stop and reconcile by review against decision 0002.
- A schema or semantics bump needs a new model version. The v1 goldens then become "rejected: schema 1" tests.
