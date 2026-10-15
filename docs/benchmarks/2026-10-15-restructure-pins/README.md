# Restructure 2a: derived reference-set sums — proof

First full proof: clean main **`779e7693`** against the clean branch **`23eaf3b`**, both dirty=false, same source and
build paths, three profiles (Release with IPO, Release without IPO, Debug); machine as in [machine.json](machine.json).
Second full proof on the head merged with main (E3g #575, D1/S1 #576): clean main **`00931d3a`** against the
clean branch **`6baf9f3`** (merge `f79b38c`; its message misspells the main commit as `00931d38`), same three
profiles: P1 1501 names identical in all three profiles, every test's properties unchanged; selected runs 261/261
IPO, 255/255 no-IPO before and after; P2 1164 battles result bytes equal (`2046d213…cb46`); the ten native reference
runners' reports byte-equal in all three profiles; library byte-equal (IPO `6ca8f2d9…7213`, no-IPO `5b3f7dae…c7390`,
Debug `baa74491…7772`), no engine object differs (only test objects including the changed headers and
`bench/main.c.o`); exports, layouts and the CLOSURE / TEAM_C / POOL fingerprints equal.

- [equality.md](equality.md): every field of every set checked in on main equals the derived value (27 rows), and
  every count macro of the four committed headers equals the macro the configure writes (19 rows); `reference_pins.h`
  defines the same macros with the same values.
- [proof-summary.json](proof-summary.json): P1 inventory 1494 names, identical in all three profiles, every test's
  properties unchanged; selected runs 257/257 IPO, 251/251 no-IPO before and after; P2 1164 battles, 2654
  executions, result bytes equal (`2046d213…cb46`); the ten native reference runners' reports byte-equal in all three
  profiles; library byte-equal in all three profiles, no engine object differs; exports, layouts, fingerprints equal.
- [proofs.py](proofs.py): the script (`REPO`, `OUT`, `PHASE`). Only counts and hashes are retained.
