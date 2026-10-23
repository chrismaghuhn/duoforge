# Restructure 6e: the fix of the split tool after the review of #662 — proof

**Commits compared.** Clean main **`095064af`** (#662) against the clean branch head **`56e2641c`**, both **dirty=false**. Same source and build paths in both phases, three profiles: Release with IPO, Release without IPO, and Debug. Machine: [machine.json](machine.json). Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py) (those of 6e-2; `NO_RENAMES=1`: this step renames nothing), [regen.sh](regen.sh).

**Why a separate PR.** #662 was merged at `99a4bce3`, before its review fixes. Its committed output is correct: the reviewer rebuilt it and found every check exactly once and every table in its section. The fixes of the tool land here on their own, as the HS decided.

## What changes

`tools/restructure/split_test.py`:
- **Macros in `merge()`.** The macros a section needs take part in the comparison and the renames, like the items.
  - The review's case: two identical functions that name a macro of two values were kept as one, and the second section ran the first section's check with the first section's value. They now stay two.
  - A macro that only another macro names is kept.
- **Spec paths of a merge.** They are read relative to the repository of the merge spec. A missing one is refused instead of looked up elsewhere, and so is a merge spec outside any repository.
- **The docstring** states the order: the merge first, then the splits with `--except`. A rerun needs the sources back from git.
- **`split()`** keeps only the `#define`s a part needs, line by line.
  - A comment directly above a dropped define goes only when it stands over that define alone. Only a whole comment goes: a run of `//` lines or one complete `/* ... */` block, never part of one (the fourth review's case) and never the continuation of a kept define above (the third review's: a kept macro of several lines lost its body). Anything else stays.
  - Blank lines stay; two that a removal makes adjacent become one, and a blank line that a removal leaves at the end of the preamble goes (the part puts one before its first item).
  - Nothing is dropped from a preamble that has a preprocessor conditional or a `#define` before an `#include` (in any spacing, `# include` too). A dropped define there could change another one's value without a trace, which the second review found. Such a preamble is kept whole, and so is one whose comments are not plain (a `/*` inside a comment, a `//` line ending with a backslash), or where a define to drop starts inside a comment or a comment runs on past it (the fifth review's cases). String and character literals are read as such, so a `/*`, `*/` or `//` in one is no comment (the sixth review's case), and one not closed on its line keeps the preamble whole.
- **Blank lines between items.** A part keeps the blank line, or none, that its source had between two items.
- **`keep_header`** takes `header_replace`, refused when its text is not in the comment.

`tools/restructure/test_audit.py`: two part rows of one source may not name the same file, so there is one per merge target.

Unit tests in `duoforge.tools.restructure` (30 in all) cover:
- the review's macro case, and a macro of a macro;
- defines dropped line by line, with the comments of a define and the source's double blank lines kept;
- the conditional and the config-define preambles kept whole;
- blank lines between items;
- `header_replace` and its refusal;
- the merge spec paths;
- the names of anonymous enums and tagged structs;
- `--except` and `keep_header`;
- the part-row pair rule.

**The files made again with the fixed tool.** Against main, every changed test file loses only `#define` lines, comment lines of those defines and blank lines that their removal made double. The one exception is `test_magic_bounce.c`, whose comment sentence now names the stones' file. `test_aura_guard.c` and `test_magic_bounce.c` also get their source's spacing back. No removed macro is named anywhere in its file.

`docs/mechanics` 5bc: its Tests and Mutation lines say again what was tested then and where those tests are now.

## Proof

- **`regen.sh` reproduces every 6e-1 and 6e-2 part from its sources byte for byte:** 27 files, 0 differ. The sources are main `757a00ca` for 6e-1 and `de746106` for 6e-2.
- **The removed macros were unused:**
  - The library is byte-equal in all three profiles: IPO `0a1d3855…`, without IPO `57d79859…`, Debug `8f4f3bef…`.
  - Every one of the 27 tests made again executes the same number of checks before and after (2651 in all, each test equal to itself).
- **P1:** 1624 names, every property equal. Selected runs: 295/295 and 290/290 in both phases.
- **Full suite** (without IPO, Python, JAX on the CPU, pinned checkout):
  - 1624 tests: 1621 passed, one skipped (`lint.no_mutable_globals`, not ELF here), two failed.
  - Neither failure is about this change. `python.expert_teacher` is known red on this machine (#585). `python.live` hit its 900 s timeout under the full suite's load.
  - `python.live` passes alone and in the selected runs, before and after: 497 s to 849 s against its 900 s limit, on main as well.
  - 91 Python tests ran, none skipped.
- **Shard partition (#646):** each of the 1624 tests is in exactly one shard.
- **P2:** 2808 executions, byte-equal (`77dc5c4a…`); the native reports are equal.
- **P3–P6:** unchanged.
