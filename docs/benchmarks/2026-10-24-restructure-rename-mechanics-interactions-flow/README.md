# Restructure 6d: the mechanics, interactions and flow tests named by behaviour — proof

Clean main **`38508650`** (#668) against the clean branch head **`ddd9cf72`**, both **dirty=false**. Same source and build
paths in both phases, three profiles: Release with IPO, Release without IPO, and Debug, configured with `DUOFORGE_PYTHON`,
`DUOFORGE_LEARN_PYTHON`, `DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE`. Machine: [machine.json](machine.json).
Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py) (those of 6e-3, the docstring of `proofs.py` updated).

## The renames

The 14 planned rename rows of `tests/renames.tsv` in `tests/mechanics`, `tests/interactions` and `tests/flow`, carried out
by `tools/restructure/rename_tests.py`: `mv` (`git mv` alone, a 100 % rename, in `3f590f20`), then `names`. Each test
executes the same checks under its new name, in both release profiles (the run passed each rename as a group of one, `SPLIT_GROUPS` with delta 0, so `proofs.py` asserted it test by
test):

| Old CTest | New CTest | Executed checks |
|---|---|---:|
| `duoforge.state.pool_g46_party` | `duoforge.flow.party_order` | 196 |
| `duoforge.state.pool_g27` | `duoforge.interactions.cursed_body_disable` | 1441 |
| `duoforge.state.pool_k4_draws` | `duoforge.interactions.gravity_accuracy_draws` | 59 |
| `duoforge.state.pool_i2` | `duoforge.interactions.illusion` | 280 |
| `duoforge.state.pool_g52` | `duoforge.interactions.revival_blessing_view` | 16 |
| `duoforge.state.pool_g47` | `duoforge.interactions.status_cures` | 236 |
| `duoforge.state.pool_g20` | `duoforge.mechanics.aurora_veil` | 442 |
| `duoforge.state.pool_terrain` | `duoforge.mechanics.electric_misty_terrain` | 406 |
| `duoforge.state.pool_g37` | `duoforge.mechanics.entry_hazards` | 1871 |
| `duoforge.state.pool_weather` | `duoforge.mechanics.sand_snow_weather` | 747 |
| `duoforge.state.pool_g20_protect` | `duoforge.mechanics.spiky_shield` | 253 |
| `duoforge.state.pool_g36` | `duoforge.mechanics.toxic` | 1026 |
| `duoforge.state.pool_g7` | `duoforge.mechanics.wide_guard` | 274 |
| `duoforge.state.pool_g72` | `duoforge.mechanics.yawn_exemptions` | 24 |

The rows' names were planned with the table (step 6a); each fits its test's header. `names` rewrote every living
reference: the registrations (all flags kept), the tests' own first lines and `df_test_begin`, `docs/mechanics` and
`docs/support/README.md` with its template, comment lines in `src/combat/turn.c` and `src/data/support_manifest.c` (one
line for one line, so no `__LINE__` moves), one comment line of `tools/datagen/pool_families.js`, and the paths that
`tools/reference/tests/test_trace_to_c.py` and `tools/reference/party_expect.py` read. Old flat paths such as
`tests/test_pool_weather.c` now name the real file.

**The review** (no blocking finding): the short names of five evidence lines in `docs/mechanics` (5ai, 5ab, 5aj, 5dw,
5t) name the new tests now, as 6e-3 did for 5ai; `docs/mechanics/flow/5cj` keeps its list of short names, a record of the
mutants' run. The copied `proofs.py` says which steps it serves. These changes after the proof's head are docs only.

## The lint's speed (CI)

With the 14 rows done, `duoforge.lint.test_renames` ran into its 60 s timeout on the CI runner (shard rest): the search for
old names in the living files was one Python alternation over the tree, 17 s here. `test_audit.py` now runs one
`git grep -I -o -w -F -f <the old names>` over the tracked files, with the same excludes (the table and the frozen
records). Measured here: 17.3 s before, 0.3 s after; with every row of the table counted as done (164 old names, the state
after 6e-4) 0.34 s. The same strictness: on the tree of main before 6d with this step's table (every 6d name still in the
files), the old and the new search find the same 104 (file, old name) pairs in 45 files. A word is what it was (no word
character before or after); a binary file is not read, as before; a text file that is not UTF-8 is now read too (stricter).
A unit test pins the word rule, the binary file and the old file's path. The 60 s timeouts stay. `duoforge.tools.restructure`
(its 31 unit tests, the committed table among them) takes 0.4 s instead of 18 s.

## Gate and P1–P6

- **Library:** byte-equal in all three profiles: IPO `6174a9f9…`, without IPO `96a5b7ea…`, Debug `384a60b4…`.
- **Objects that differ:** the bench's `main.c.o` (it embeds the commit) in all three profiles; with IPO also `turn.c.o`,
  `support_manifest.c.o` and `test_skill_swap.c.o` (their comment lines, compiled again with new random `.gnu.lto_*`
  suffixes; `libduoforge.a` holds the two library objects, the shared library is equal) and CMake's LTO probe objects.
- **P1:** 1647 names in all three profiles; every test's properties equal under the renames. Selected runs: 313 and 308,
  before and after, all passed.
- **P2:** 10 variants, 2818 executions, 1246 unique battles; result bytes equal before and after, with and without IPO:
  canonical SHA `6877987c6147b729202a89ca98eea60c1d8e2cfb7990217ebf1eed2aed824b5c`
  ([per-battle-digests.tsv](per-battle-digests.tsv)); the ten native reference reports byte-equal in all three profiles.
- **P3, P4:** perft and the search bench pass in both profiles; the pins and `BENCH_SHA256` are unchanged.
- **P5:** context fingerprints equal in all profiles. `P5_generated_unchanged` is false only because of the comment lines
  in `src/data/support_manifest.c` (written by hand) and `tools/datagen/pool_families.js`; no generated byte changes.
- **P6:** `include/` diff empty; 249 exports and the layouts byte-equal in all three profiles.
- **Full suite** (`ddd9cf72`, without IPO, Python, JAX on the CPU, pinned checkout): 1647 tests, 1645 passed; one skipped
  (`lint.no_mutable_globals`, not ELF here), one failed: `python.expert_teacher`, known red on this machine (#585). 91
  Python tests ran, none skipped.
- **Shard partition (#646):** each of the 1647 tests is in exactly one shard.
