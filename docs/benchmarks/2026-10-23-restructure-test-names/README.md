# Restructure 6b: the abilities, items and forms tests under behaviour names — proof

Clean main **`1bf6d5e4`** (#649) against the clean branch head **`199c8e68`**, both **dirty=false**. Same source and build
paths in both phases, three profiles: Release with IPO (`-flto=auto -ffat-lto-objects`), Release without IPO, and Debug,
configured with `DUOFORGE_PYTHON`, `DUOFORGE_LEARN_PYTHON`, `DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE`. Machine:
[machine.json](machine.json). Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py): those of 5c, comparing the
tests under the renames of `tests/renames.tsv`.

## Change

- **The renames.** `tools/restructure/rename_tests.py mv`, then `names --areas abilities,items,forms`, carry out the 14 planned renames of `tests/renames.tsv` (step 6a). Every row is now `done`.
  - `mv` is a commit of its own, with `git mv` only (100 % renames).
  - `names` rewrites the registration's `NAME` and `SOURCES`, and nothing else (tier, area labels, libraries and timeout stay).
  - It also rewrites the test's own name string, and the old CTest name and file name in every living file: CMake, tools, Python tests, the mechanic docs' `Tests:` lines and text, comments in `src/`.
- **What stays.** The step code stays in each test's header ("step AC1 of the ability-change work"). Frozen records (`docs/{history,benchmarks,research,decisions,superpowers}`) keep the old names; the table is their bridge.
- **The rename table:**

| Old | New |
|---|---|
| `abilities/test_pool_ac1.c`, `duoforge.state.pool_ac1` | `abilities/test_trace.c`, `duoforge.abilities.trace` |
| `abilities/test_pool_g41.c`, `duoforge.state.pool_g41` | `abilities/test_shadow_tag.c`, `duoforge.abilities.shadow_tag` |
| `abilities/test_pool_g53.c`, `duoforge.state.pool_g53` | `abilities/test_pressure.c`, `duoforge.abilities.pressure` |
| `abilities/test_pool_g57.c`, `duoforge.state.pool_g57` | `abilities/test_magic_bounce.c`, `duoforge.abilities.magic_bounce` |
| `abilities/test_pool_g61.c`, `duoforge.state.pool_g61` | `abilities/test_sheer_force.c`, `duoforge.abilities.sheer_force` |
| `abilities/test_pool_g69.c`, `duoforge.state.pool_g69` | `abilities/test_symbiosis.c`, `duoforge.abilities.symbiosis` |
| `abilities/test_pool_g73.c`, `duoforge.state.pool_g73` | `abilities/test_moody.c`, `duoforge.abilities.moody` |
| `abilities/test_pool_g79.c`, `duoforge.state.pool_g79` | `abilities/test_cloud_nine.c`, `duoforge.abilities.cloud_nine` |
| `abilities/test_pool_g81.c`, `duoforge.state.pool_g81` | `abilities/test_frisk.c`, `duoforge.abilities.frisk` |
| `abilities/test_pool_k2.c`, `duoforge.state.pool_k2` | `abilities/test_piercing_drill.c`, `duoforge.abilities.piercing_drill` |
| `forms/test_pool_g66.c`, `duoforge.state.pool_g66` | `forms/test_stance_change.c`, `duoforge.forms.stance_change` |
| `items/test_pool_g16.c`, `duoforge.state.pool_g16` | `items/test_knock_off.c`, `duoforge.items.knock_off` |
| `items/test_pool_g29.c`, `duoforge.state.pool_g29` | `items/test_item_transfer.c`, `duoforge.items.item_transfer` |
| `items/test_pool_g55.c`, `duoforge.state.pool_g55` | `items/test_duration_items.c`, `duoforge.items.duration_items` |

- **Speed-up found by this step.** `duoforge.lint.test_renames` checks that no living file names an old name. With rows done, it timed out at 60 s: a pattern per name and file over every tracked file. Both tools now match every old name in one pass per file, which takes 5 s over the tree. The rewrite redone from the `git mv` commit with the faster tool is byte-equal.

## Gate: the library is byte-equal

`src/` changes in comments only. `libduoforge_shared.so` is the same before and after in all three profiles:

| Profile | Library |
|---|---|
| IPO on | `0a1d3855…` |
| IPO off | `57d79859…` |
| Debug | `8f4f3bef…` (the comments keep their line count) |

## P1–P6

- **P1:**
  - The inventory under the renames is identical: 1604 names, and the before list with the 14 old names mapped to the new ones equals the after list.
  - Every renamed test keeps every property: labels, timeout, working directory. Its command differs only in the name of its executable.
  - Every other test is equal.
  - Selected runs: 277 with IPO and 272 without, before and after, all passed.
- **Full suite of `199c8e68`** (without IPO, with Python, JAX on the CPU and the pinned checkout):
  - 1604 tests, **1602 passed**.
  - One skipped: `duoforge.lint.no_mutable_globals` (not ELF in this configuration).
  - One failed: `duoforge.python.expert_teacher`, known red on this machine (#585).
  - 91 Python tests ran, none skipped.
- **The shard partition of #646.** On the merge with main `13f4b568` (1607 tests: three new ones of #651), `tools/ci/check_ctest_labels.py --partition` (the linux-full shards) reports every test in exactly one shard. The labels did not change.
- **P2:**
  - 2808 executions and 1241 battles, byte-equal before and after with and without IPO (`77dc5c4a…`, [per-battle-digests.tsv](per-battle-digests.tsv)).
  - The native reports are byte-equal in all three profiles.
- **P3–P6:** perft, bench, context fingerprints, `include/` and the 249 exports and layouts are all unchanged.

The merge of main `13f4b568` (#646, #651) after the proof changes no file under `src/`, `include/`, `tests/`, `bench/` or
`cmake/`.
