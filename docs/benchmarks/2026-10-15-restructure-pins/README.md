# Restructure 2a: derived reference-set sums — proof

First full proof: clean main **`779e7693`** against the clean branch **`23eaf3b`**, both dirty=false, same source and
build paths, three profiles (Release with IPO, Release without IPO, Debug); machine as in [machine.json](machine.json).
The proof on the head merged with main `00931d38` follows in the PR text.

- [equality.md](equality.md): every field of every set checked in on main equals the derived value (27 rows), and
  every count macro of the four committed headers equals the macro the configure writes (19 rows); `reference_pins.h`
  defines the same macros with the same values.
- [proof-summary.json](proof-summary.json): P1 inventory 1494 names, identical in all three profiles, every test's
  properties unchanged; selected runs 257/257 IPO, 251/251 no-IPO before and after; P2 1164 battles, 2654
  executions, result bytes equal (`2046d213…cb46`); the ten native reference runners' reports byte-equal in all three
  profiles; library byte-equal in all three profiles, no engine object differs; exports, layouts, fingerprints equal.
- [proofs.py](proofs.py): the script (`REPO`, `OUT`, `PHASE`). Only counts and hashes are retained.
