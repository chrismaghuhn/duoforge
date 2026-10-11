# Repository restructure by mechanic, with conflict-free tests

Owner-approved plan, 2026-10-11. It merges the owner's target structure and test rules with the measured design draft
of the same day. It is written for an agent that has not seen this repository before.

**When it may run:** only while **no pull request is open** on the repository (owner, 2026-10-11). Every step below is
its own PR; the next step starts after the previous PR is merged.

## Rules for the executing agent

- Read `AGENTS.md` first. It applies in full: correctness before optimisation; no hidden rule implementation in Python;
  unsupported must fail explicitly; determinism is first-class; **tests must not be weakened**; performance claims
  need measurements; weights, checkpoints, run dirs, replay data and live logs are private and never committed.
- **No behaviour change** in any step. Moves, family splits and new features are never mixed: a file move is its own
  commit (`git mv`, 100 % rename) before any edit, so `git log --follow` and `git blame -M -C -C` keep working. When a
  function is split out of a file, the commit message says `split from <file>@<sha>` and the PR body lists the old-line
  to new-file map.
- Git: one branch per step (`restructure/<step>-<name>`), base `main`; never rebase or force-push a pushed branch; to
  update, `git fetch origin main && git merge FETCH_HEAD`. One PR per step, title `restructure <n>: ...`.
- Heavy local work (builds, long test runs, measurements) only through `bash tools/ci/machine_lock.sh <name> <cmd>`
  from Git Bash (two shared slots; `--exclusive` for measurements). The hosted GitHub CI is the merge gate; locally,
  build and run only what you need. Each worktree uses its own build directory.
- Do not merge your own PRs. Report the proof results (below) in the PR body; the maintainer merges after reading the
  check counts.
- If a step turns out to need a behaviour change, stop and report; do not include it.

## Measured starting point (main a2c73001, last 7 days: 133 PRs, 396 merge commits)

| File | PRs touching it | listed merge conflicts |
|---|---:|---:|
| `tests/CMakeLists.txt` (one long `foreach(_py ...)` line, ~850 lines total) | 57 | 28 |
| `tests/reference/conformance_pool.h` (generated) | 29 | 19 |
| `tests/test_pool_tables.c` | 27 | 18 |
| `tests/test_conformance.c` | 29 | 17 |
| `tests/reference/tiebreak_ref.h` (generated) | 29 | 17 |
| `src/data/pool_tables.c` (generated) | 26 | 17 |
| `tests/test_tiebreak.c` | 29 | 16 |
| `tests/test_pool_setup.c` | 26 | 16 |
| `tools/state_model/state_v3_model.py` | 28 | 15 |

`src/combat/turn.c` has about 12,000 lines and 292 functions (`dfi_run_move_body` alone about 1,950); it is touched by
many PRs but causes few conflicts: its problem is size and review. `tests/` holds about 135 `test_*.c` files side by
side, many with historical names (`test_pool_g49.c`). `python/duoforge_live/tracker.py` has one 475-line method.

## Target structure

| Area | Content | Tests |
|---|---|---|
| `src/combat/flow/` | turn flow, action order, switching, faint handling | `tests/flow/` |
| `src/combat/mechanics/` | damage, accuracy, status, weather, terrain, protection, hazards | `tests/mechanics/` |
| `src/combat/items/` | item effects, grouped by family | `tests/items/` |
| `src/combat/abilities/` | abilities and shared ability families | `tests/abilities/` |
| `src/combat/moves/` | moves with their own special logic | `tests/moves/` |
| `src/combat/forms/` | Mega Evolution and other forme changes | `tests/forms/` |
| `src/data/` | generated Pokémon, move, item and ability tables and the support mapping | `tests/data/` |
| — | interplay of several mechanics | `tests/interactions/` |
| — | shared test helpers and fixture builders | `tests/support/` |
| — | recorded reference battles and their checks | `tests/reference/` |

Pokémon themselves are mostly data (stats, types, legal moves and abilities); own C code exists only where real special
behaviour needs it. Shared effects (berries, type boosters) stay implemented as families. **The turn flow keeps deciding
explicitly when and in which order effects run;** items and abilities call shared functions for damage, healing, status
and item changes. The folder split must not change any order.

## Test rules

- **Names describe behaviour** (`test_focus_sash.c`, `test_item_transfer.c`, `test_weather_suppression.c`); the old
  G number goes into a comment.
- **Mixed tests are split by subject.** For example `test_pool_g77.c` checks several abilities, Leek and damage
  interplay; those cases go to their areas or to `tests/interactions/`.
- **Every test builds its own mutable state and sets its seed explicitly.** Shared fixtures are immutable templates.
- **Every writing test gets its own temporary output directory.** Reference data is only read during a test run, or
  checked with `--check`.
- **Every test folder registers its own tests** with the existing `duoforge_add_test()`; the central CMake file only
  includes the areas (`add_subdirectory` or `include`). No shared list line.
- **Area tests add to, never replace, the whole-battle checks** (conformance, tiebreak, perft, differential): an item
  test alone does not prove its interplay with abilities, weather and turn order.
- **Pins live with what they count.** Global sums (battle count, tiebreak stops, record-assembler outcomes) are derived
  from per-battle or per-area values, not hand-edited single numbers. The bench signature (`BENCH_SHA256`) and the perft
  pins stay global on purpose: a deliberate change must show in one line.
- **Number spaces** (`DFI_SITE_*`, `DFI_RES_*`, volatile and flag bits, special ids) are assigned by a generator or a
  definition file with compile-time guards; existing values stay frozen (draw-site ids are recorded in fixtures and
  must never be renumbered). Lanes never edit shared numbering by hand.

**Working rule against conflicts:** a PR changes one bounded area and its tests. Shared interfaces, ids and integration
points are changed one after another, never in parallel.

## Python tests, tool tests and test tiers (owner addition, 2026-10-11)

- **Python tests by area.** The 62 flat files in `python/tests/` move into folders that mirror the packages:
  `python/tests/{engine,learn,search,live,replay,eval,data}/` plus `python/tests/support/` for the shared helpers
  (`_pivot_fixture.py`, `_reference_features.py`, `_replay_reference.py`) and their `fixtures/` and `data/`. The PR body
  carries the old-to-new path table. The CTest names (`duoforge.python.<name>` and friends) stay unchanged in that step.
- **Tool tests live with their tool:** `tools/<tool>/tests/` (today about 25 `test_*` files sit between the scripts in
  `tools/reference/`, and the same pattern exists in `tools/datagen/`, `tools/state_model/`, `tools/cloud/p1_pilot/`).
- **Each test folder registers its own tests**, as for C: no shared `foreach(_py ...)` line.
- **Every test has exactly one tier label:** `quick` (seconds, no interpreter extras), `full` (the normal suite),
  `reference` (needs the pinned Showdown / Node), `slow` (minutes, long sweeps or JAX training checks); plus its area
  label (`items`, `live`, `search`, ...). `ctest -L quick`, `ctest -L live` and similar then run one tier or one area
  alone. CI selects by label instead of by regex lists (today the TSan job uses `-R "duoforge\.((batch|search)\.|view$|encode$)"`);
  the full matrix stays the merge gate and the "no Python or reference test skipped" checks stay.

## Runs: one place, one format (owner addition, 2026-10-11)

A *run* is anything that produces results instead of checking code: training, evaluations and arenas, benchmarks and
latency measurements, coverage measurements, fuzz campaigns, cloud runs. Today their entry points are scattered
(`duoforge_learn/{train,bc,bc_eval,p1_eval,ladder,distill,collect_expert}.py`, `duoforge_search/{arena,book_ab,
preview_ab,expert_eval,eval_manifest,live_latency,tickbench,rowprobe,positions}.py`, `duoforge_live/arena.py`,
`tools/perf/`, `tools/cloud/`), every tool picks its own output layout, and the replay coverage runner exists only
outside the repository.

- **Code by kind.** Training stays in `duoforge_learn` (`train`, `bc`, `distill`, `collect_expert`); evaluation, arena,
  A/B, benchmark and latency entry points move to a new package `python/duoforge_eval/` (the search and learn packages
  keep only search and learning code). The live arena keeps its client code in `duoforge_live` and gets its entry point
  in `duoforge_eval`. The coverage runner moves into the repository as `tools/coverage/` (data path as an argument; the
  replay data itself stays private and outside, AGENTS.md).
- **Run definitions** (the exact command and arguments of a named, repeatable run; the existing `campaign.conf` format
  is one) live in `runs/<kind>/<name>.*` (`runs/fuzz/` takes `tools/cloud/aws_fuzz/campaigns/`). `runs/` holds
  definitions only; launch scripts stay in `tools/cloud/`.
- **Outputs never land in the repository.** Every run takes `--out`; its default is `$DUOFORGE_RUNS/<kind>/<date>-<name>/`
  (for example `C:\Dev\runs\...`), and a run refuses an output directory inside the repository.
  `python/tests/test_repo_hygiene.py` gets a check for that. Weights, checkpoints, caches, logs with match or user ids:
  private, as before.
- **One manifest per run:** a shared helper (`python/duoforge/runs.py`, no imports from the learn/search packages)
  writes `manifest.json` with code commit and dirty flag (falling back to `git -C <repo>` when the worktree's gitdir is
  not resolvable, the cause of `"code": null` in the #411 arena record), the full arguments, seeds, machine, start and
  end. Existing tools adopt it as they move.
- **Reports** (aggregates only) go to `docs/benchmarks/<date>-<name>/README.md` from one template: question, answer,
  setup, predeclared gates and results, provenance (commit, manifest fields), what it does and does not show.
- **Old commands keep working** for a transition: every moved entry point leaves a thin module that forwards to the new
  one and prints the new name. Running sessions (M11, M12, Learner v2) use these commands. The forwarders are removed
  in a later, separate PR once no session uses them.

## Data and leftovers (owner addition, 2026-10-11)

- `data/` stays the home of checked-in data: `data/teams/`, `data/teams_pending/`, `data/positions/`. Generated files
  (pool tables, reference headers, layouts) are marked `linguist-generated` in `.gitattributes` and carry a "generated
  by ... do not edit" header, so reviews and diffs show them as such.
- `tasks/` (the M0-M4 milestone briefs) moves to `docs/history/tasks/`.
- `bench/` and `certify/` stay where they are (own CMake targets, referenced by CI); they are not moved.

## Proof suite (every step; results in the PR body)

- **P1 tests:** full CI green; the sorted `ctest -N` inventory before and after is identical (except where the step
  says so), including skipped tests.
- **P2 reference results:** all reference data sets: battle count and a SHA-256 over the per-battle results equal
  before and after (conformance, tiebreak); states, requests, event sequences and RNG use unchanged for equal inputs.
- **P3 perft:** `duoforge.python.perft` against `tests/perft/pins.json`.
- **P4 search bench:** `python/tests/test_bench.py` with the pinned `BENCH_SHA256` unchanged.
- **P5 generated data:** `tools/datagen/gen_closure.py --check` and the provenance hashes; IDs and table order identical.
- **P6 public surface:** `git diff` of `include/duoforge/` empty; the exported symbol list of `duoforge_shared` equal;
  `duoforge.python.layout` equal.

## Steps

| # | PR | Content | Extra proof |
|--:|---|---|---|
| 0 | baseline | record the test inventory incl. skipped tests, the per-battle reference digests, generated-data hashes, the exported symbol list and the existing benchmark baseline, into `docs/benchmarks/<date>-restructure-baseline/` (aggregates only) | n/a |
| 1 | tests and CMake | move test files into the area folders (rename only), each folder registers its tests with `duoforge_add_test()`, the central file includes the areas; **test names kept** | P1 inventory identical; `git diff -M100%` shows only renames plus the CMake changes |
| 1b | Python and tool tests | move `python/tests/` into the area folders and tool tests into `tools/<tool>/tests/` (rename only), per-folder registration, **CTest names kept**; then add the tier and area labels and switch the CI selection to labels | P1 inventory identical; `git diff -M100%` renames plus CMake/CI; the label run `ctest -L quick` and the CI jobs run the same tests as before (lists in the PR body) |
| 2 | reference data and pins | generated reference data per battle (one generated file per battle under `tests/reference/battles/<set>/`, registry built from the directory) instead of the monolithic `conformance_pool.h` / `tiebreak_ref.h`; per-battle pins with the global sums derived; `test_live` record-assembler pins per battle | P2 digest of all battle records old vs new byte-equal; build time before/after measured |
| 3 | items pilot | move the existing item families out of `turn.c` into `src/combat/items/`, then one bounded effect area | P1–P6; bench with IPO on and off |
| 4 | abilities, mechanics, moves, forms, flow | one PR per area, same pattern; very large functions (`dfi_run_move_body`, the residual runner, `dfi_get_damage`) are cut into named phase functions one phase per PR | P1–P6 per PR |
| 5 | data generator and number spaces | split `gen_closure.py` by formes/Pokémon, moves, items, abilities; definition files with compile-time guards for draw sites, residual kinds and bits | P5 identical output and IDs; P2; a static-assert table of every old value |
| 6 | names and labels | rename tests to behaviour names (old G number in a comment), split mixed tests into areas / `tests/interactions/`, add CTest labels per area so areas can be run alone | P1: every old test case still runs (map old to new names in the PR body); the full CI matrix stays the merge gate |
| 7 | tracker | split `python/duoforge_live/tracker.py` into a package by fold family, with a re-export module | `test_live`, `test_live_unit`, `test_replay` and the per-battle pins unchanged |
| 8 | runs | `python/duoforge_eval/`, `runs/`, `tools/coverage/`, `python/duoforge/runs.py` with the manifest, `$DUOFORGE_RUNS` defaults, the report template; one PR per kind (eval, bench, coverage, fuzz), forwarders for every old command | P1; every old command line still runs through its forwarder (one smoke run each, outputs outside the repo); a manifest is written and names the commit; `test_repo_hygiene` refuses an output inside the repo |
| 9 | data and leftovers | `.gitattributes` generated marks and headers, `tasks/` to `docs/history/tasks/` | P1, P5 (no generated byte changes) |

Order rationale: step 1 (and 1b for Python) removes the most frequent conflict for the least risk; step 2 removes the generated-header and
pin conflicts; steps 3–4 are the only risky block and go area by area; step 5 must not change a single generated byte;
step 6 is cosmetic but valuable once the structure exists; step 8 comes last because running sessions call those
commands, and the forwarders keep them working.

## Risks to watch

- Build time and IPO/inlining after splitting `turn.c` (measure with IPO on and off; report numbers).
- Promoting `static` functions to shared `dfi_*` functions must not export new symbols from `duoforge_shared` (P6).
- Generated files: after merging, regenerate and check (`--check`); never hand-edit generated output.
- Documentation references to `turn.c` line numbers (about 26 docs) go stale; fix them in the step that moves the code.
- `tools/state_model/state_v3_model.py` is a deliberately independent second model of the state; splitting it is
  allowed but it must not start importing engine-side Python helpers.
