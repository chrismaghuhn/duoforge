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

**The review (#662).**
- **Macros.** `merge()` now compares and renames macros like the other items, so two identical functions that name a macro of two values stay two. A macro that only another macro names is kept.
- **Unused macros.** `split()` and `merge()` keep only the macros a part needs. This removes some unused `#define`s and their comments from twelve 6e-1 parts and three 6e-2 parts; the generated code is otherwise unchanged.
- **Blank lines.** A part keeps the blank line, or none, that its source had between two items.
- **Headers.** `keep_header` takes `header_replace`, so `test_magic_bounce.c`'s comment points at the stones' new file.
- **Audit.** `test_audit` allows one part row per pair of source and merge target.
- **Tests.** Each of these has a unit test.

## What changes

**`forms/test_mega_stones.c`, one section per batch** (`split_test.py --merge`, [specs/mega_stones.merge.json](specs/mega_stones.merge.json)):

- Mega batch 2: Swampertite, Metagrossite, Froslassite and Lucarionite Z.
- G43: ten stones with no new rule; merged whole.
- G51: ten stones with no new rule, and Keen Eye and Big Pecks marked for Pidgeot.
- G57: the Magic Bounce stones (Absolite, Sablenite and Clefablite; Starminite unmarked), moved out of `test_magic_bounce.c`.
- G59: the six new Mega abilities and their stones.
- G63: the simple Mega abilities' stones, already this file's since 6e-1.

**How the sections are built:**
- Each section is one check over its batch's stones (marks, pairs, setups, API), as in its source.
- An item that two sections share stays one item when its text is the same after each section's renames (`base_ability_legal` of G43 and G51). Otherwise it is renamed in each section by the section's prefix, in code only: `stones_batch2_`, `stones_batch3_`, `stones_batch4_` (the batches have no other name), `magic_bounce_stones_`, `new_mega_abilities_`, `simple_mega_abilities_`.
- Each section's statements run in a block of their own in the one main.
- No check is rewritten.

**The splits:**

| Source | Parts |
|---|---|
| G51 (5bc) | the stones' section; `abilities/keen_eye` (no Grass holder of Keen Eye or Big Pecks next to Flower Veil, and Keen Eye's ignoreEvasion); `abilities/regenerator_pivot` |
| G59 (5bh) | the stones' section (one check over the six abilities, their stones and pairs); `abilities/mega_launcher` (the PULSE flag); `abilities/mega_sol` (its refusal in rain) |
| Mega batch 2 (5ag) | the stones' section (the marks, the Megas, Aura Guard as an engine row); `abilities/aura_guard` (the chain and its refusal) |
| G49 (5ao) | `items/power_and_accuracy_items` (**batch**: the three rows' marks and handlers, and every g49_* battle present); `items/bright_powder` (the orders of its priority -2 group and the two refusals) |

G61's stone checks are not moved: they are statements of its `check_marks`, which also checks Sheer Force's own rows, so moving
them would rewrite a check.

## Executed checks (one group: the sources and the tests they become)

| Before | Checks | After | Checks |
|---|---:|---|---:|
| `state.pool_g43` | 248 | `forms.mega_stones` | 603 |
| `state.pool_g51` | 275 | `abilities.keen_eye` | 23 |
| `state.pool_g59` | 76 | `abilities.regenerator_pivot` | 22 |
| `state.pool_mega2` | 238 | `abilities.mega_launcher` | 5 |
| `state.pool_g49` | 59 | `abilities.mega_sol` | 7 |
| `abilities.magic_bounce` | 654 | `abilities.aura_guard` | 203 |
| `forms.mega_stones` (6e-1, G63) | 15 | `abilities.magic_bounce` | 644 |
| | | `items.power_and_accuracy_items` | 21 |
| | | `items.bright_powder` | 38 |
| **sum** | **1565** | **sum** | **1566** |

- **The +1:** the new Regenerator main checks its own context (`DF_CHECK(&t, ctx != NULL)`, as G51's main did once). The proof script asserts the group sum with this delta.
- **Per source, where a source's parts have no shared file:** G49 59 → 21 + 38. `magic_bounce` loses exactly its 10 stone checks (654 → 644).

## Gate and P1–P6

- **Library byte-equal** in all three profiles: IPO `0a1d3855…`, without IPO `57d79859…`, Debug `8f4f3bef…`. `src/` changes in one comment.
- **P1:**
  - Under the map the inventory is identical: 1622 names before, 1624 after. Five sources go; seven new tests come; G43 merges into an existing name.
  - Every new test has its source's properties; its labels follow its folder (the abilities parts of the forms sources are labelled `abilities`). Every other test is equal.
  - Selected runs: 293/293 and 288/288 before, 295/295 and 290/290 after.
- **Full suite** (without IPO, Python, JAX on the CPU, pinned checkout):
  - 1624 tests, **1622 passed**.
  - One skipped: `lint.no_mutable_globals` (not ELF here).
  - One failed: `python.expert_teacher` (#585, known red on this machine).
  - 91 Python tests ran, none skipped.
- **Shard partition (#646):** every one of the 1624 tests is in exactly one shard.
- **P2:**
  - 2808 executions, byte-equal before and after with and without IPO (`77dc5c4a…`).
  - The native reports are equal in all three profiles.
- **P3–P6:** unchanged.

One comment in `tests/interactions/test_pool_g30.c` changes. It named G59's file for Mega Sol's refusal and now names
`tests/abilities/test_mega_sol.c`. Nothing else in `interactions/` changes.
