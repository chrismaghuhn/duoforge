# Restructure 6e-2: the Mega stones in one test, the forms and items tests split by subject — proof

Clean main **`de746106`** (#656) against the clean branch head **`e8ceee52`**, both **dirty=false**. Same source and build
paths in both phases, three profiles: Release with IPO, Release without IPO, and Debug, configured with `DUOFORGE_PYTHON`,
`DUOFORGE_LEARN_PYTHON`, `DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE`. Machine: [machine.json](machine.json).
Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py): those of 6e-1, with the merge rows and the executed checks
compared by group (several sources share the stones' file). Specs: [specs/](specs/).

**To make the files again:** export `tests/` of main `de746106` into a scratch tree. Run
`split_test.py specs/mega_stones.merge.json --merge --root <tree>` first: the merge reads its sources before their splits
change them. Then run each other spec with `--root <tree> --except forms/test_mega_stones.c`. This reproduces every file
byte for byte. The 6e-1 specs do the same from main `757a00ca`.

**The review (#662), fixed in #665:**
- **Macros in `merge()`.** `merge()` compares and renames the macros a section needs, like the items, so two identical functions that name a macro of two values stay two. A macro that only another macro names is kept.
- **Unused defines.** `split()` keeps only the `#define`s a part needs, line by line. A comment directly above a dropped define goes with it when it stands over that define alone. Nothing is dropped from a preamble with a preprocessor conditional or with a `#define` before an `#include`.
- **Spacing.** A part keeps its source's blank lines between items.
- **Headers.** `keep_header` takes `header_replace`.
- **What #665 changes in the files.** Twelve 6e-1 parts and three 6e-2 parts lose unused defines and the comments of those defines only. `test_aura_guard.c` and `test_magic_bounce.c` get their source's spacing back, and `test_magic_bounce.c`'s comment points at the stones' file. See [the fix's proof](../2026-10-23-restructure-split-tool-fix/README.md).
