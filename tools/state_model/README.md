# Structural state model (offline test oracle)

`state_v3_model.py` is a stdlib-only Python model of the structures and decision domains of state schema 3:

- canonical context bytes (with the target-class table hash) and fingerprint;
- synthetic setup validation and init (a TEAM_SELECTION state);
- the invariant checker v3 in its fixed order (50 ids, the seven TAIL ids of the POOL tail included);
- canonical encoding v3 (1009 bytes) and strict decoding; for the POOL kinds the schema 0x0503 encoding with the 348-byte state tail (1357 bytes, decision 0015 section 7: the rev 4 part and the rev 5 block; rev 1, 0x0103, rev 2, 0x0203, rev 3, 0x0303, and rev 4, 0x0403, are refused), its tail rules and the decode order with the two schemas. The tail fields of the expansion steps are in the model with their rules: the party order (G46, field block +1..+6), the elapsed count of a partial trap (G90, decision 0060: position byte +32, turns + elapsed is 5 or 6 while the trap is up), the position flags of the rev 5 block (G72b, G76, G82 Healing Wish bit 0, G84b Curse bit 7, G88: every bit defined, the Dragon Cheer stage at most 2), the Attract sources (G71, decision 0034: rev 5 reserve bytes 0..3), the Ally Switch volatile (G80, decision 0044: reserve bytes 4..7), Double Shock's typeless soak slot (G50, decision 0025) and the two halves of a lock (G56: the tail's `lock_turns` needs the body's locked move, a locked move needs its lock or `VOLATILE`); 33 bytes stay reserved;
- the mechanics-free team-selection transition (it starts turn 1);
- the knowledge record: what each player saw last of the opposing members;
- the complete side-choice domains in documented order (team picks; TURN, REPLACEMENT and PIVOT joint slot choices with the reserve, Mega and forced-switch constraints; Struggle when no move has PP left; for closure data Fake Out disabled after a move action and a locked move offered alone; nothing at TERMINAL);
- the observation v2 of decision 0007 (544 bytes): what a player sees.

It was written from the decision notes (`docs/decisions/0002`, `0005`, `0006` section 3), **not** from the C sources. It is **not** a model of Pokémon combat rules, and CTest does not run it, except its POOL tail part: `test_model_pins.py` (CTest `duoforge.state.model_pool_tail`) computes the envelope, the example and the byte sweep and compares them with `ENVELOPE_HEX`, `TAIL_HEX` and `sweep[]` of `tests/data/test_pool_tail.c`, so a step that adds a tail byte or rule without the model fails there (and `duoforge.data.model_pool_hash` compares its `POOL_TABLE_HASH`). Python and bindings must not contain hidden rule implementation (AGENTS.md); this file is test evidence only.

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
python3 tools/state_model/state_v3_model.py --pool-tail   # only the POOL tail: tests/data/test_pool_tail.c pins its envelope, example bytes and byte sweep
python3 tools/state_model/test_model_pins.py              # the model's pins against the C tests (CTest runs it; the tail sweep takes about 15 s)
```

The run takes about three minutes (the mutation sweeps decode about 770,000 inputs). The output is identical on every platform (LF line ends).

## Rules

- Never copy C encoder output into test expectations.
- If this model and the C code disagree, stop and reconcile by review against the decision notes.
- A step that adds a POOL tail byte or rule teaches this model the rule from its decision note first; `sweep[]` of `tests/data/test_pool_tail.c` is the model's output, no row is kept by hand (`duoforge.state.model_pool_tail` fails otherwise).
- A schema or semantics bump needs a new model version. The previous goldens then become "rejected: schema N" tests.
