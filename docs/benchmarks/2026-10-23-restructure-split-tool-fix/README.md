# Restructure 6e: the fix of the split tool after the review of #662 — proof

**Commits compared.** Clean main **`095064af`** (#662) against the clean branch head **`56e2641c`**, both **dirty=false**. Same source and build paths in both phases, three profiles: Release with IPO, Release without IPO, and Debug. Machine: [machine.json](machine.json). Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py) (those of 6e-2; `NO_RENAMES=1`: this step renames nothing), [regen.sh](regen.sh).

**Why a separate PR.** #662 was merged at `99a4bce3`, before its review fixes. Its committed output is correct: the reviewer rebuilt it and found every check exactly once and every table in its section. The fixes of the tool land here on their own, as the HS decided.

## What changes

`tools/restructure/split_test.py`:
- **Macros in `merge()`.** The macros a section needs now take part in the comparison and the renames, like the items.
  - The review's case: two identical functions that name a macro of two values were kept as one, so the second section ran the first section's check with the first section's value. They now stay two.
  - A macro that only another macro names is kept.
  - The docstring states the order: the merge first, then the splits with `--except`. A rerun needs the sources back from git.
- **`split()`.** A part keeps only the `#define`s it needs. A block of comments and defines that loses every define loses its comments too. A part also keeps the blank line, or none, that its source had between two items.
- **`keep_header`** takes `header_replace`.

`tools/restructure/test_audit.py`: two part rows of one source may not name the same file. That allows one part row per merge target.

Unit tests in `duoforge.tools.restructure`, 26 in all:
- the review's macro case, and a macro of a macro;
- unused macros dropped;
- the names of anonymous enums and tagged structs;
- `--except` and `keep_header`;
- the part-row pair rule.

**The files made again with the fixed tool:**

| What | Change |
|---|---|
| Twelve 6e-1 parts and three 6e-2 parts | lose their unused macros |
| `test_aura_guard.c`, `test_magic_bounce.c` | get their source's spacing back |
| `test_magic_bounce.c` | its comment points at the stones' file |

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
