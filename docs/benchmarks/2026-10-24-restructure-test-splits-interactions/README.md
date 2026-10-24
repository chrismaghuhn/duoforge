# Restructure 6e-4: the mixed interactions tests split by subject — proof

Clean main **`32da809f`** (#669) against the clean branch head **`94d88feb`**, both **dirty=false**. Same source and build
paths in both phases, three profiles: Release with IPO, Release without IPO, and Debug, configured with `DUOFORGE_PYTHON`,
`DUOFORGE_LEARN_PYTHON`, `DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE`. Machine: [machine.json](machine.json).
Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py) (those of 6d).

## The splits

`tools/restructure/split_test.py` cuts each source by subject from the specs in [specs/](specs/), as in 6e-1 to 6e-3. The
specs make the committed parts byte for byte with the sources back from `32da809f`, apart from one comment of
`tests/abilities/test_damp_sturdy_rows.c` that names the test which now checks Sturdy's OHKO immunity
(`duoforge.moves.confusion_moves`). Parts about one mechanic go to that mechanic's area.

| Source | Parts (`tests/interactions/` unless named) | Executed checks |
|---|---|---:|
| G30 (5u) | `rage_powder_batch_rows` (**batch**), `moves/rage_powder_view` | 3090 → 1785+1305 = **3090** |
| G33 (5ad) | `multi_hit_mirror_armor_rows`, `multiaccuracy_later_hits` (the proven accuracy and the Wide Lens refusal) | 29 → 10+19 = **29** |
| G34 (5w) | `small_rules_rows` (**batch**), `modify_damage_chain_order` (the commutation test and the engine's refusal) | 1162 → 1078+84 = **1162** |
| G35 (5z) | `rain_dish_friend_guard_rows` (**batch**), `friend_guard_chain_order` | 191 → 36+155 = **191** |
| G39 (5ah) | `thirteen_abilities_rows` (**batch**), `abilities/damp_sturdy_rows`, `hyper_cutter_flower_veil` | 58 → 42+11+5 = **58** |
| G67 (5bl) | `magic_guard_air_balloon`, `mechanics/item_shown_fold` | 190 → 182+8 = **190** |
| G77 (5bq) | `crit_package_rows` (**batch**), `modify_damage_bound`, `sniper_chain_order`, `magma_armor_frozen_refusals` | 46 → 14+11+3+18 = **46** |
| G83 (5bt) | `bulletproof_rivalry_leaf_guard_iron_ball`, `leaf_guard_mega_sol_refusal` | 139 → 47+92 = **139** |

Each source's executed checks equal the sum of its parts', in both release profiles; the proof script asserts it source by
source (`SPLIT_GROUPS`, delta 0).

**Why the batches stay one test.** Each `_rows` part is the facts of its step's rows: the marks, the handler numbers and
the flags, checked over all rows of the batch. Every other check names one mechanic or one rule and has its own file.

**G75 is not in this step.** The review found no batch invariant in it (its marks mix three rows with three stones, its
pairs the Mega pairs with a base ability's legality), and its Mega pairs could join `forms/test_mega_stones.c` as 6e-2
did for the other stones. Whether to split it so or keep it whole is a question of the plan, left to the owner: its row
stays planned and `tests/interactions/test_pool_g75.c` unchanged.

## The `DF_CHECK` call sites

| Source | Sites before | Sites after |
|---|---:|---|
| G30, G33, G34, G35, G39, G77, G83 | 33, 18, 43, 28, 22, 31, 18 | the same, in the parts (G30's and G83's `build_setup`, `bundle_of` and `find` come from `tests/support/conformance_replay.h`, which has no new item) |
| G67 | 12 | 15: `replay_all` (3) is in both parts |

## Function map (old → part)

- **G30:** `check_facts` → rage_powder_batch_rows; `rows`, `names` and main blocks 1-3, 5-7 → moves/rage_powder_view; `build_setup`, `bundle_of`, `find` → the header.
- **G33:** `check_facts` → multi_hit_mirror_armor_rows; `check_proven_accuracy`, `check_refusal` and their setup → multiaccuracy_later_hits.
- **G34, G35:** `check_facts` → the rows part; `walk`, `brute`, `check_chain`, `check_refusal` and their setup → the chain-order part.
- **G39:** `check_marks` → thirteen_abilities_rows; `check_inert` and `move_named` → abilities/damp_sturdy_rows; `check_hyper_cutter_not_grass` → hyper_cutter_flower_veil.
- **G67:** `check_marks`, `check_battles` → magic_guard_air_balloon; `check_fold_ignores_item_shown` → mechanics/item_shown_fold; `replay_all` → both; `build_setup`, `bundle_of`, `find` → the header.
- **G77:** `check_facts` → crit_package_rows; `check_chain_bound` → modify_damage_bound; `check_commute` → sniper_chain_order; main block 4 (`check_skill_swap`, `check_trace_refusal` and their helpers) with the context block → magma_armor_frozen_refusals.
- **G83:** `check_marks`, `check_battles` → bulletproof_rivalry_leaf_guard_iron_ball; `run_poison_powder`, `check_mega_sol_refusal` → leaf_guard_mega_sol_refusal; `replay_all` → the first; `build_setup`, `bundle_of`, `find` → the header.

## The living references

- `docs/mechanics` (5ah, 5bl, 5bq, 5bt, 5ds, 5u, 5w, 5z) and `docs/support/README.template.md` name the part they mean, or
  all parts; `docs/support/README.md` is made again from the template. Short names in the records of mutation runs (5bo,
  5bp, 5z) stay: they name what ran then.
- Comments only, one line for one line: `src/combat/turn.c`, `src/combat/mechanics/damage/modify_damage.h`,
  `src/data/support_manifest.c`, `tests/support/conformance_compare.c`, `tools/datagen/tablegen/abilities.py` (a Python
  comment, not emitted), `tools/reference/trace_to_c.py`.
- `tests/interactions/tests.cmake`: the comments above the registrations say what stays and where the rest went.
- **The review** (two rounds, the second without a finding): four header sentences that the code did not back (a fold
  after every step, two unmarked rows that later steps marked, "every" battle where a list replays some) were corrected in
  the specs and the parts made again; G75 was taken back out (above).

## Gate and P1–P6

- **Library:** byte-equal in all three profiles: IPO `6174a9f9…`, without IPO `96a5b7ea…`, Debug `384a60b4…`.
- **Objects that differ:** the bench's `main.c.o` (it embeds the commit) in all three profiles; with IPO also `turn.c.o`,
  `support_manifest.c.o` and `conformance_compare.c.o` (their comment lines, compiled again with new random `.gnu.lto_*`
  suffixes; `libduoforge.a` holds the two library objects, the shared library is equal) and CMake's LTO probe objects.
- **P1:** 1658 names in all three profiles; every test's properties equal under the splits. Selected runs: 313 and 308
  before, 324 and 319 after (the parts), all passed.
- **P2:** 10 variants, 2818 executions, 1246 unique battles; result bytes equal before and after, with and without IPO:
  canonical SHA `6877987c6147b729202a89ca98eea60c1d8e2cfb7990217ebf1eed2aed824b5c`
  ([per-battle-digests.tsv](per-battle-digests.tsv)); the ten native reference reports byte-equal in all three profiles.
- **P3, P4:** perft and the search bench pass in both profiles; the pins and `BENCH_SHA256` are unchanged.
- **P5:** context fingerprints equal in all profiles. `P5_generated_unchanged` is false only because of the comment lines
  in `src/data/support_manifest.c` (written by hand) and `tools/datagen/tablegen/abilities.py`; no generated byte changes.
- **P6:** `include/` diff empty; 249 exports and the layouts byte-equal in all three profiles.
- **Full suite** (`94d88feb`, without IPO, Python, JAX on the CPU, pinned checkout): 1658 tests, 1656 passed; one skipped
  (`lint.no_mutable_globals`, not ELF here), one failed: `python.expert_teacher`, known red on this machine (#585). 91
  Python tests ran, none skipped.
- **Shard partition (#646):** each of the 1658 tests is in exactly one shard.
