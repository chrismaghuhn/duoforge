# Mechanics: one file per entry

Every mechanic step of the content expansion has one file here, `docs/mechanics/<area>/<id>-<slug>.md`. The areas follow
the code layout of `src/combat/`: `flow`, `mechanics`, `items`, `abilities`, `moves`, `forms`, `field`. A step that
touches several areas goes where most of it is.

The entries 5a to 5dy were split out of decision 0015 by restructure step 11, each with its text unchanged and its
frozen id as the anchor. The frozen redirect table in
[decision 0015 section 4.3](../decisions/0015-content-expansion-pool.md) maps every old id to its file; "decision 0015
entry `<id>`" in code comments and other docs keeps meaning that file. Cross-cutting rules stay in `docs/decisions/`.

## A file

```markdown
<a id="<id>"></a>

# <id>. <step code>, <title>

- Area: <area>
- Step: <step code, or ->
- Tests: <CTest names, comma separated, or ->

<id>. **<step code>, <title>** (<lane, builder, branch, issue>). <the entry: pin, state and rules, events, view,
evidence, mutants, campaigns, open gaps>

## Support

<the line(s) of docs/support/README.md for this step: a table row "| <area> | **IMPLEMENTED + TESTED** ... |" or a
paragraph "**<title> (step <code>, decision 0015 entry <id>)**: ...">
```

- The first line is the anchor and nothing else; the id is the file name's prefix.
- `Tests:` is the only place that names the step's CTest names (restructure step 6 renames tests by script from
  `tests/renames.tsv` and rewrites this line); the text may refer to it.
- `## Support` is optional (a step without a support line leaves it out, never empty). Each table row and each
  paragraph (lines up to a blank line) is copied into `docs/support/README.md` in id order: table rows into the table,
  paragraphs after it.
- `--check` enforces this header: the anchor alone on line 1, the heading on line 3, one `Area` line naming the folder,
  one `Step` and one `Tests` line, and the entry text starting once with `<id>. **`.

[TEMPLATE.md](TEMPLATE.md) is a copy to start from.

## Adding an entry

The scaffold does steps 1 and 2 together with the step's test (restructure step 12):

```bash
python3 tools/new_mechanic.py <test area> <behaviour> --id <id> --lane <Content | Fuzz | HS> --title "<title>" \
    [--step <code>] [--doc-area <area>] [--draw-site NAME=ID] [--residual-kind NAME=NUMBER] [--dry-run]
```

It writes `docs/mechanics/<area>/<id>-<slug>.md` from `TEMPLATE.md` (anchor, heading, Area, Step and the Tests line
filled in; the optional `## Support` section is left out, add it with step 3 when the step has a support line),
`tests/<area>/test_<behaviour>.c` with its line in `tests/<area>/tests.cmake` (CTest
`duoforge.<area>.<behaviour>`, the naming of `tests/renames.tsv`), and, when given, the definition-file lines and
`#define`s of a draw site or a residual kind (restructure step 5c) with the numbers the HS handed out. It refuses an id
outside the lane's block or one that has its file or anchor already, a taken test name, site or kind, and a name with a
step number, and then writes nothing. Its test fails ("scaffold of <id>: write the mechanic's checks") until the
mechanic's own checks replace the placeholder.

By hand:

1. Take the next id from your lane's block in `docs/process/NUMBERS.md`.
2. Copy `TEMPLATE.md` to `docs/mechanics/<area>/<id>-<slug>.md` (slug: a few lowercase words of the title, `-`
   between them) and fill it in. Do not add a row to the table in decision 0015: it is frozen, new ids resolve through
   their anchor.
3. If the file has a `## Support` section: `python3 tools/docs/mechanics_docs.py --write`, which regenerates
   `docs/support/README.md`. Never edit that README by hand; a merge conflict in it is resolved by running `--write`
   again on the merged tree.
4. `python3 tools/docs/mechanics_docs.py --check` (CTests `duoforge.docs.support_readme` and
   `duoforge.docs.mechanics_ids`): the README is up to date, every id is in one file, every table row resolves, and
   every id that a line naming 0015 cites anywhere in the repository exists (the id and "0015" on the same line).

## Converting an entry written in the old format

A branch that started before step 11 may still add its entry to `docs/decisions/0015-content-expansion-pool.md` (a
paragraph `<id>. **...**` plus its indented lines) and a line to `docs/support/README.md`. After merging `main`:

1. Take the merge's version of 0015 (`main`'s, with the table) and cut the entry out of it: the paragraph from
   `<id>. **` to the line before the next heading, numbered step or entry.
2. Create `docs/mechanics/<area>/<id>-<slug>.md` with the header of the template (anchor, heading, the Area, Step and
   Tests lines) and paste the entry below it unchanged. Put the CTest names the entry introduces on the `Tests:` line.
3. Move the branch's line of the old `docs/support/README.md` under `## Support` in that file, and take `main`'s README.
4. `python3 tools/docs/mechanics_docs.py --write`, then `--check`. 0015 must not differ from `main`'s.
