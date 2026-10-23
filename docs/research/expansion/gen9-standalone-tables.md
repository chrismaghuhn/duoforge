# A standalone Gen 9 table set: how big the job is (O8 note, 2026-10-23)

O8 stops before any generated gen9ou table (HS decision 2026-10-23, option B). Two things are in its PR:

- the definition `data/formats/gen9ou.json`, whose `tables` section names the rule set `gen9`;
- the pool `data/formats/pools/gen9ou.json`.

`tools/datagen/tablegen/source.py` refuses the gen9 rule set by name. This note measures what option A would take: a
pool build of the base data alone, with no Reg M-C prefix. It is the starting point for the Gen 9 design and decides
nothing.

The probe is `probe_gen9_standalone.py` on the branch `design/o8-gen9-standalone-probe`. That branch has no PR, and the
script is not part of the build. It ran on the pinned checkout b2cb775b, against main 80bb7524 plus O8. It uses an empty
override file in place of each Champions file, with no PP cap.

## Why a rule set alone does not build gen9ou

`build_pool` (`tablegen/tables.py`, about 315 lines) and `render_pool` (`tablegen/output.py`, about 420 lines) build the
pool tables as an extension of Reg M-C:

- **Prefix.** The rows start with the closure, Team C and the P1 and G2 rows, and the legal pool follows. The closure's
  Megas (Staraptor-Mega, Charizard-Mega-Y, Raichu-Mega-Y, Golisopod-Mega, Salamence-Mega, Floette-Mega) and their stones
  are not legal in gen9ou. The pool has 0 Megas and 0 stones, so the build stops at the first prefix row.
- **Header.** The pool header includes `data/formats/reg-mc/extended_tables.h`. It takes the row types
  (`dfi_move_data`, ...) and the row defines (`DFI_FORME_*`, `DFI_MOVE_*`, `DFI_ITEM_*`, `DFI_ABILITY_*`) from there.
  `table_set_names` renames only `dfi_pool_*` and `DFI_POOL_*`. A translation unit that sees both sets therefore needs
  prefixed row defines as well (`DFI_GEN9OU_FORME_*`, ...).
- **Learnsets.** `learnset_moves` (`tablegen/species.py`) reads only the flat `"9M"` lines of the Champions learnsets.
  The base learnsets carry many more source codes, for example `"9L33"`, `"9E"`, `"7M"` and `"5D"`. They also carry
  events, prevolution inheritance and Sketch. A standalone build would take each forme's learnable moves from the
  pinned validator, through the pool's `moves` lists. `forme_legal` would then have nothing left to cross-check them
  against. `duoforge.data.format_pool_gen9ou` already checks the pool against the validator again.

## What holds on the base data alone (probe)

**Fact checks.** 29 of the 35 fact checks that `build_pool` calls before its rows hold unchanged. The probe left out
`check_a0p1_facts`, `check_k2_facts` and `check_failskillswap`, which need the legal pool or the Champions scripts. Six
fail, because each one checks a Champions override that gen9 does not have:

| check | first failure |
|---|---|
| C4 | psyshieldbash: the Champions override is missing |
| A0 | crabhammer: the Champions entry is not the override `{accuracy: 95}` |
| A2a | naturalcure: no champions entry |
| G61 | dragonize: the Champions mod has no entry |
| G32 entries | regenerator not found |
| C2 | nightdaze: not the base power override 90 |

A gen9 build would need these checks per rule set. Each would either be dropped with its reason or get a gen9 variant.
These checks guard engine code, and no engine kind reads the gen9ou tables before O9.

**Move rows.** 660 of the 666 pool moves parse with `parse_pool_move`, with no override and no PP cap. Six fail:

- Pledges: firepledge, grasspledge and waterpledge have the unknown flag `pledgecombo`.
- Fake Out and First Impression: the `onDisableMove` the generator expects is not in the base entry; Champions adds it.
- Splash: the gravity flag of a pool move is new.

**Family columns.** Every item and ability derives its family on the base entries except Misty Surge. It follows the
TERRAIN_SETTER pattern but is no member of decision 0015's list.

## Open questions for the Gen 9 design

1. **Sketch-only moves.** Without Smeargle, the remaining formes learn only 622 of the 666 pool moves. The other 44 are
   learnable through Sketch alone. `build_pool` requires the move rows to be the legal pool plus Struggle, which would
   give 667 rows and 84 learnset bytes (W1 as decided). If the excluded forme's moves left the pool with it, there
   would be 623 rows and 78 bytes. The definition keeps 84 and decides nothing here.
2. **Learnable moves from the validator.** Is the validator's per-species list the source of truth for a Gen 9 table
   set? What, if anything, does the generator then cross-check it against?
3. **Fact checks per rule set.** The six Champions-only checks above, plus K2 and the PP cap of the Champions scripts.
4. **A writer without a prefix.** It needs its own row types or shared ones, prefixed row defines, and no include of a
   Reg M-C header.
5. **W3.** 246 of the 254 u8 item ids are used. The item widening proposal comes before O11.

Size estimate. This is not a measurement, since no prototype code exists beyond the probe. A standalone build path is
roughly 300 to 500 new lines in `tablegen/tables.py`, `species.py` and `output.py`, plus its tests. Every one of those
files is owned by the Restructure lane.
