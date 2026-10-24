# Restructure 6e-1: the mixed abilities tests split by subject — proof

Clean main **`757a00ca`** against the clean branch head **`552b777d`**, both **dirty=false**. Same source and build paths in
both phases, three profiles: Release with IPO, Release without IPO, and Debug, configured with `DUOFORGE_PYTHON`,
`DUOFORGE_LEARN_PYTHON`, `DUOFORGE_PS_REFERENCE_DIR` and `DUOFORGE_NODE`. Machine: [machine.json](machine.json).
Scripts: [proofs.py](proofs.py), [summarize.py](summarize.py): those of 6c, with the parts of a split (each part has the
source's properties, its own name, executable and area label) and the executed checks of every source and part.

## The splits

`tools/restructure/split_test.py` cuts each source by subject from the specs in [specs/](specs/). Every item of the source
lands in at least one part or in the support header. Every check call lands in exactly one part, and so does every main block,
except the setup blocks a spec names as shared (`shared_blocks`). For a main written out (`main_body`, G22 and A2a: a loop
over contexts), the parts must make the source's check calls exactly, as a multiset of call texts with their arguments, and
every other line of the source main must be a line of some part's main. Otherwise the spec is refused. The parts keep the
source's registration flags.

The specs reproduce the committed parts byte for byte. To verify, put each source of `main` back and run
`python3 tools/restructure/split_test.py docs/benchmarks/2026-10-23-restructure-test-splits-abilities/specs/<id>.json --check`.

| Source | Parts | Executed checks |
|---|---|---:|
| G45 (5ba) | `simple_ability_rows` (**batch**: one loop over the six rows' marks and handlers, and the Mold Breaker family unmarked for the breakable three), `steadfast`, `moxie`, `weak_armor`, `telepathy`, `volt_absorb` | 56 → 13+6+7+6+6+18 = **56** |
| G65 (5bk) | `modifier_abilities` (**batch**: one loop over the five rows, Mold Breaker unmarked), `reckless`, `trace_water_bubble` | 37 → 17+9+11 = **37** |
| G63 (5bj) | `simple_mega_abilities` (**batch**: the four engine rows and the base abilities they leave unmodelled), `stalwart`, `forms/mega_stones` (the six stones; the other Mega batches join it in 6e-2) | 403 → 16+372+15 = **403** |
| G22 (5o) | `swift_swim_fainted_holder`, `inner_focus_intimidate_cap` (each over both POOL kinds, as the source's loop) | 90 → 38+52 = **90** |
| A2a (5dy) | `one_clause_abilities` (**batch**: the marks, and one check over all fourteen clauses: the clause decides at its step, a marked neighbour of the same hook does not), `flower_veil_drop_refusals`, `tangled_feet` (the later-hit refusal and the order of the priority -1 group), `life_dew_water_absorb`, `natural_cure` | 510 → 420+27+29+25+13 = **514** |

**Why the batches stay one test.** Each batch file is one check over every row of its batch: the same marks loop, or the same
clause-at-its-step check over a table of all fourteen clauses. Every other check of a source names one mechanic and has its own
file.

**A2a's +4.** A2a's four new mains each create their context and check it (`DF_CHECK(&t, kp != NULL)`, as the source's main
did once). These four checks are the only difference, and the proof script asserts it (`SPLIT_DELTA`).

**The `DF_CHECK` call sites.** These match source by source: G65 22 → 22, G63 22 → 22. The replay helpers that two or more
parts share moved to `tests/support/conformance_replay.h`, with 3 call sites per replay variant:

| Source | Sites before | Sites after |
|---|---:|---:|
| G45 | 17 | 14 in the parts + 3 in the header |
| G22 | 20 | 17 in the parts + 3 in the header |
| A2a | 63 | 64 in the parts + 3 in the header − the 4 context checks = 63 |

**Shared helpers.** `tests/support/conformance_replay.h` holds only the helpers two or more parts use, each one character for
character the source's copy. `split_test.py` refuses a header whose copy differs, comments and white space aside. This covers
`build_setup`, `bundle_of`, `find`, the two replay variants, `member_of`, and `run_step` with its result type.

Helpers that one part uses stay in that part, for example G65's trace helpers.

## Function map (old → part)

- **G45:** `check_marks` → simple_ability_rows; each `check_<ability>` → its file; `build_setup`, `bundle_of`, `find`, `replay` → the header.
- **G65:** `check_facts` → modifier_abilities; `check_recoil_rows` → reckless; `check_trace_refusal` with `find`, `build_setup`, `bundle_of` → trace_water_bubble.
- **G63:** the two row checks → simple_mega_abilities; `test_no_marked_scripted_move` → stalwart; `test_mega_stones_g63` → forms/mega_stones.
- **G22:** `check_fainted_holder` → swift_swim_fainted_holder; `check_cap` with `step_events` → inner_focus_intimidate_cap; the replay helpers → the header.
- **A2a:** `check_marks`, `check_case` and the `cases` table → one_clause_abilities; `check_flower_veil_refusals` and `check_illuminate_flower_veil` → flower_veil_drop_refusals; `check_tangled_feet_later_hit` and `check_dyadic_order` → tangled_feet; `check_life_dew` → life_dew_water_absorb; `check_natural_cure_event` → natural_cure; `member_of`, `run_step` and the replay helpers → the header.

## Gate and P1–P6

- **Library byte-equal** in all three profiles: IPO `0a1d3855…`, without IPO `57d79859…`, Debug `8f4f3bef…`. `src/` changes only in one comment, which names the part.
- **P1:**
  - The inventory under the map is identical: 1608 names before, 1622 after (5 sources became 19 parts).
  - Every part has its source's properties; its labels follow its folder (`forms/test_mega_stones.c` is labelled `forms`), and its command differs only in the executable.
  - Every other test is equal.
  - Selected runs: 279/279 and 274/274 before, 293/293 and 288/288 after.
- **Full suite** (without IPO, Python, JAX on the CPU, pinned checkout):
  - 1622 tests, **1620 passed**.
  - One skipped: `lint.no_mutable_globals` (not ELF here).
  - One failed: `python.expert_teacher` (#585, known red on this machine).
  - 91 Python tests ran, none skipped.
- **The shard partition of #646:** every one of the 1622 tests is in exactly one shard.
- **P2:**
  - 2808 executions, byte-equal before and after with and without IPO (`77dc5c4a…`).
  - The native reports are equal in all three profiles.
- **P3–P6:** unchanged.
