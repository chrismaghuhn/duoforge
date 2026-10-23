# Restructure 6e-3: the mixed moves tests split by subject — proof

Clean main **`b65decef`** (#667) against the clean branch head **`55a40e2c`** (`93dab4e2` with main merged), both **dirty=false**. Same source and build
paths in both phases, three profiles: Release with IPO, Release without IPO, and Debug, configured with `DUOFORGE_PYTHON`,
`DUOFORGE_LEARN_PYTHON`, `DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE`. Machine: [machine.json](machine.json).
Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py) (those of the tool fix #665).

## The splits

`tools/restructure/split_test.py` cuts each source by subject from the specs in [specs/](specs/), as in 6e-1 and 6e-2:
every item of a source lands in at least one part or in the support header, every check call and every main block in
exactly one part (the setup blocks a spec names as shared aside), and the parts keep their source's registration flags.
The specs make the committed parts byte for byte, apart from two comment lines that the review asked to name the parts
(below): `python3 tools/restructure/split_test.py docs/benchmarks/2026-10-23-restructure-test-splits-moves/specs/<id>.json
--check` with the source back from `8f69cc89` (the sources are the same on `b65decef`).

| Source | Parts (`tests/moves/` unless named) | Executed checks |
|---|---|---:|
| G8 (5a) | `throat_chop`, `heal_block` (with the equal-Speed order of two ends), `switch_clears_volatiles`, `throat_chop_heal_block_view` | 652 → 49+291+13+299 = **652** |
| G44 (5an) | `simple_move_rows` (**batch**), `power_trip`, `tri_attack` | 90 → 74+12+4 = **90** |
| G48 (5al) | `hits_taken_hazard_moves` (**batch**: the facts and the loop over the rows), `rage_fist` | 292 → 271+21 = **292** |
| G54 (5at) | `moves_batch_rows` (**batch**), `multi_hit_count`, `quick_guard_view` | 81 → 46+25+10 = **81** |
| G72b (5ce) | `alluring_voice_dragon_cheer_rows`, `alluring_voice` (with the PIVOT refusal), `dragon_cheer` | 99 → 10+41+48 = **99** |
| G76 (5cg) | `destiny_bond_final_gambit_rows`, `destiny_bond`, `final_gambit` | 56 → 13+29+14 = **56** |
| G80 (5dn) | `psych_up_howl_ally_switch_rows`, `ally_switch`, `abilities/stalwart_random_move` | 184 → 20+159+5 = **184** |
| G86 (5cn) | `power_move_rows` (**batch**), `heavy_slam`, `hard_press` | 43 → 20+11+12 = **43** |

Each source's executed checks equal the sum of its parts', in both release profiles: no context check is added (the
parts that make a context share the source's setup block, which checks nothing).

**Why the batches stay one test.** Each batch part is one check over every row of its batch: the marks loop, the handler
numbers and the pins of all rows (G44, G54, G86), or G48's loop over every step of every battle with the hits taken and
the hazard layers. G44's guard (Shield Dust, Serene Grace and Covert Cloak stay unmarked) is one more fact over the rows
that Ice Fang and Tri Attack bypass. Every other check names one mechanic and has its own file. A `_rows` part of G72b,
G76 and G80 holds the facts of both moves of its step (handler ids, marks, view bits): they are one table.

## The families (renamed, not split)

| Source | New name | Executed checks | Why one test |
|---|---|---:|---|
| G19 (5k) | `moves.glaive_rush_tail_view` | 867 | One loop over every step of every g19 battle (Coaching's included) reads the tail's glaive_rush and both viewers' extension; Coaching's mark and boost role are two facts of the same rows. |
| G31 (5ai) | `moves.taunt_yawn_tail_view` | 1870 | One loop over every step reads Taunt's and Yawn's tail turns and their view bits together, against one row table of both. |
| G42 (5as) | `moves.move_result_roost` | 830 | One loop over every boundary position reads the move result and the Roost bit; the Stomping Tantrum refusal is the same move result's unclassified bit. |
| G64 (5ca) | `moves.moves_batch_2_rows` | 24 | The handler numbers and the marks of the four rows, and the pins of Poltergeist (the row the turn code plays): one batch's facts. |
| G68 (5cc) | `moves.moves_batch_4_rows` | 23 | The same for the four rows of batch 4. |

`tests/renames.tsv`: their rows are renames (`git mv` alone in `a7d20580`, the names in the next commit); the table's
action changed from split to rename for these five.

## The `DF_CHECK` call sites

| Source | Sites before | Sites after |
|---|---:|---|
| G44, G48, G54, G86 | 75, 39, 57, 43 | the same, in the parts |
| G8 | 43 | 42 in the parts + 4 in the header: `replay` (4) is the header's new `df_conf_replay_checked`; `expect_tail` (1) is in three parts, `offered_for` (1) in two |
| G72b, G76, G80 | 66, 44, 85 | 69, 47, 88: `start()` (3) is in two parts of each |

The helpers that one part's checks need go with it; the copies are the source's own, unchanged. A shared header for the
scripted-battle helpers of G72b, G76 and G80 (`start`, `finish`, `setup_from` and `team_bundle` the same in all three, `turn_bundle` the
same but for its command type) would be a step of its own.

**Shared helpers.** `tests/support/conformance_replay.h` gains `df_conf_replay_checked`: G8's `replay`, character for
character with the header's renamed calls (the replay by name, then the state check), which three G8 parts use.
`split_test.py` refuses a header copy that differs. G8, G48 and G54 take `build_setup`, `bundle_of` and `find` from the
header as well.

## Function map (old → part)

- **G8:** main blocks 2 → throat_chop; 3, 4, 6 → heal_block; 5 → switch_clears_volatiles; `check_view_ext` and `view_ext_rows` → throat_chop_heal_block_view; `tail_at`, `expect_tail` → throat_chop, heal_block, switch_clears_volatiles; `offered`, `offered_for` → throat_chop, heal_block; `replay`, `build_setup`, `bundle_of`, `find` → the header.
- **G44:** `check_marks`, `check_pins`, `check_unmarked`, `check_guard_unmarked` → simple_move_rows; `check_power_trip_stages` → power_trip; `check_tri_attack_edges` → tri_attack.
- **G48:** `check_facts`, `rows`, `names` and main blocks 1-4, 8-10 → hits_taken_hazard_moves; `check_bound`, `rage_fist_dealt`, `check_power` → rage_fist; `build_setup`, `bundle_of`, `find` → the header.
- **G54:** `check_marks`, `check_pins`, `check_unmarked`, `check_constants` → moves_batch_rows; `check_multihit_weights` → multi_hit_count; `check_guard_flag` and main blocks 0, 7 → quick_guard_view; `build_setup`, `find` → the header.
- **G72b:** `test_row` → alluring_voice_dragon_cheer_rows; `test_av_*` and `test_pivot_refusal` → alluring_voice; `test_dc_*` → dragon_cheer; the scripted-battle helpers → alluring_voice and dragon_cheer.
- **G76:** `test_row` → destiny_bond_final_gambit_rows; `test_db_*` → destiny_bond; `test_fg_*` → final_gambit; the helpers → destiny_bond and final_gambit.
- **G80:** `test_rows` → psych_up_howl_ally_switch_rows; `test_codec_round_trip`, `test_invariant`, `test_illusion_refusal`, `test_swap_position_fields` → ally_switch; `test_stalwart_random_refusal` → abilities/stalwart_random_move; the helpers → ally_switch and stalwart_random_move.
- **G86:** `test_marks` → power_move_rows; `test_heavy_slam_power` → heavy_slam; `test_hard_press_power` → hard_press.

## The living references

- `docs/mechanics` (5a, 5ai, 5al, 5an, 5as, 5at, 5ca, 5cc, 5ce, 5dn, 5k) and `docs/support/README.template.md` name the
  part they mean, or all parts; `docs/support/README.md` is made again from the template (`tools/docs/mechanics_docs.py`).
  `docs/mechanics/flow/5cj` keeps the short names `pool_g42` and `pool_g54` in its record of the mutants' run: they name
  what ran then.
- `src`: five comment lines (`combat/turn.c`, `combat/moves/multihit.h`, `power_trip.h`, `tri_attack.h`,
  `data/support_manifest.c`), each one line for one line.
- `tools/reference/tests/test_trace_to_c.py` reads `view_ext_rows` from `tests/moves/test_throat_chop_heal_block_view.c`
  (the 32 rows of G8); `tools/reference/trace_to_c.py` names `duoforge.moves.destiny_bond`.
- **The review:** two comments that the parts copied from their sources named an old test
  (`test_moves_batch_rows.c:84`, `test_simple_move_rows.c:128`); they name the parts now (`93dab4e2`). The proof's first
  run on `fc77f6de` failed exactly there (`lint.test_renames` and `tools.restructure`). The proof was run again after the
  fix, and once more on the head with main (#667) merged; the numbers below are that last run.

## Gate and P1–P6

- **Library:** byte-equal in all three profiles: IPO `6174a9f9…`, without IPO `96a5b7ea…`, Debug `384a60b4…`.
- **Objects that differ** (all three profiles): the bench's `main.c.o` (it embeds the commit), and the nine earlier
  parts that include `tests/support/conformance_replay.h` and call a helper below the new function (its lines moved, so
  the `__LINE__` of their checks did). With IPO also `turn.c.o` and `support_manifest.c.o` (their comment lines; the
  shared library is still equal, `libduoforge.a` holds the objects) and test objects compiled again with new random
  `.gnu.lto_*` suffixes, CMake's own LTO probe objects (`_CMakeLTOTest-C`) among them. The before build tree also
  held objects of the parts from an earlier run (the comparison takes every object the before tree has), so some
  parts are listed too; the libraries are what the gate compares. [proof-summary.json](proof-summary.json) (`object_identity`) lists them.
- **Executed checks:** each source's equal to the sum of its parts' (or its family's), in both release profiles; the
  proof script asserts it group by group (the tables above).
- **P1:** 1647 names in all three profiles; every test's properties equal under the renames and splits (the parts keep
  their source's labels, timeout and libraries). Selected runs: 297 and 292 before, 313 and 308 after (the parts), all
  passed.
- **P2:** 10 variants, 2818 executions, 1246 unique battles; result bytes equal before and after, with and without IPO:
  canonical SHA `6877987c6147b729202a89ca98eea60c1d8e2cfb7990217ebf1eed2aed824b5c`
  ([per-battle-digests.tsv](per-battle-digests.tsv)); the ten native reference reports byte-equal in all three profiles.
- **P3, P4:** perft and the search bench pass in both profiles; the pins and `BENCH_SHA256` are unchanged.
- **P5:** context fingerprints equal in all profiles. The summary's `P5_generated_unchanged` is false only because
  `src/data/support_manifest.c` (written by hand, under `src/data`) changes two comment lines; no generated byte changes.
- **P6:** `include/` diff empty; 249 exports and the layouts byte-equal in all three profiles.
- **Full suite** (`55a40e2c`, without IPO, Python, JAX on the CPU, pinned checkout): 1647 tests, 1645 passed; one
  skipped (`lint.no_mutable_globals`, not ELF here), one failed: `python.expert_teacher`, known red on this machine
  (#585). 91 Python tests ran, none skipped.
- **Shard partition (#646):** each of the 1647 tests is in exactly one shard.
