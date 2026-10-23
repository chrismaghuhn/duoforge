# Restructure 11: docs per mechanic — proof

Base: clean `main` **`7ef33a66`**. Documentation, two tools and two test registrations only: no file under `src/`,
`include/`, `python/`, `tools/datagen/` or `tests/` other than one `include` line in `tests/CMakeLists.txt` changes, so
P2 to P6 (reference results, perft, bench, generated data, public surface) cannot change and were not rerun.

## What moved

- **Decision 0015** (695,226 bytes → 67 KB): its 117 entries (ids 5a to 5dy) are now one file each,
  `docs/mechanics/<area>/<id>-<slug>.md`: 57 moves, 23 abilities, 19 forms, 7 field, 6 flow, 3 items, 2 mechanics.
  Every entry's text is unchanged (its first line still starts with `<id>. **`). In front of it come the anchor, a
  heading and the lines `Area`, `Step` and `Tests` (the CTest names the entry cites, the only place that names them, for
  the renames of step 6). The entry's line(s) of the support README follow under `## Support`.
  [entry-map.tsv](entry-map.tsv) lists id, old line in 0015 and new file.
- 0015 keeps everything else in its order: sections 1 to 3, section 4 with its numbered steps 1 to 7, 4.1, 4.2, and
  sections 5 to 8. The new **section 4.3** holds the frozen redirect table (id, step, title, file#anchor) and the batch 8
  note, which introduced entries and now stands under the table.
- **The id 5dl was given twice** (the Illusion item use of issue 556 and K4 Gravity of issue 475). HS decision
  2026-10-23: Gravity keeps `5dl` (every code citation means it), the Illusion entry is `5dl-556`; its file says so, and
  the id check allows that one suffixed id by name.
- **Seven ids are cited but never had an entry**: 5ck, 5cl, 5cm, 5cn and 5cz (decisions 0045, 0046, 0047, 0048 and
  0065), 5cq (comments of the manifest and of `tests/data/test_pool_tables.c`) and 5cr (`champions-100.md`). Each has a
  "no entry" row in the table pointing at its record.
- **`docs/support/README.md` is generated** by `tools/docs/mechanics_docs.py --write` from
  `docs/support/README.template.md` (the rows that belong to no mechanic file), the `## Support` sections of the mechanic
  files (in id order: table rows into the table, the other lines as paragraphs) and `src/data/support_manifest.c` (a new
  generated section: the three flags, the marks per kind, the supported view extension features).

Left as they were (verbatim, listed here only): the entry 5cv holds an evidence line of G76 (`g76_*` battles) and the
merge notes of G67 (`chris/expansion-g67-guard-balloon`); in the README, the long G37 paragraph exists in two different
versions (old lines 54 and 84), both kept.

## Proofs

`tools/restructure/split_0015.py` made the files from main's 0015 and README; `tools/restructure/split_0015_check.py`
checks the result against them:

```
1. 117 entries = the bodies of the 117 mechanic files with their id as anchor, byte for byte
2. 0015 outside the entries: 167 non-blank lines equal in order; the batch 8 note moved to 4.3
3. support README: 73 of 74 non-blank lines kept (1 exact duplicate removed), 13 generated lines added
```

- The removed README line is the exact second copy of the G48 paragraph (Rage Fist, Stone Axe, Ceaseless Edge,
  Population Bomb; old lines 57 and 79). The 13 added lines are the generated-by comment and the manifest section.
  [support-readme.diff](support-readme.diff) is the full diff (most of it is lines that moved).
- `python3 tools/docs/mechanics_docs.py --check`: README up to date; 117 mechanic files, 117 table rows to files, 7
  no-entry rows, 3209 citations next to "0015" in tracked files resolve.
- Mutants of the checks (each reverted): a hand edit of the README, a changed support line without `--write`, an entry text under another id's anchor, an `Area` line naming another folder, an
  anchor changed to another file's id, a removed mechanic file, a suffixed id other than `5dl-556`, and
  a citation of an unknown id next to "0015" in a tracked header: each fails `--check`.
- **P1:** sorted `ctest -N` inventory (configured with the LANES.md options, both trees) 1599 before, 1601 after; the
  only difference is the two new tests `duoforge.docs.mechanics_ids` and `duoforge.docs.support_readme` (tier quick,
  area tools). [test-inventory.txt](test-inventory.txt) is the new inventory. Locally they pass together with
  `duoforge.data.test_main_last`, `duoforge.python.generated_marks` and `duoforge.tools.restructure`; the full suite runs
  on the hosted CI.

## Adding and converting entries

[docs/mechanics/README.md](../../mechanics/README.md) and [TEMPLATE.md](../../mechanics/TEMPLATE.md): a new entry is
one new file (no row in 0015); an entry written in the old format on a paused branch is converted in four steps.
