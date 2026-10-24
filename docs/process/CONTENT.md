# Content expansion: how a mechanic gets in

How the content lane adds a mechanic (move, ability, item, Mega, battle-only forme) or fixes a divergence since the
restructure (2026-10-24). Lane set-up, merge order and gates: [LANES.md](LANES.md); numbers: [NUMBERS.md](NUMBERS.md).

## Order of work

1. **Silent divergences first.** A divergence from the pinned Showdown found on `main` (a wrong result without a
   refusal) is fixed before new coverage. Correctness comes before coverage.
2. **Then the batch plan**: the gaps of the C0 inventory (`docs/research/expansion/champions-100.md`), ordered by use and
   effort. A batch is one PR of about 10-16 entries that share an area or a hook.

## One entry, step by step

1. **Pin check.** Read the behaviour in the pinned Showdown checkout (`b2cb775b`, read-only) and note `file:line`.
   Decide: modelled exactly, or refused by name. Never a silent approximation.
2. **Scaffold.**
   `python3 tools/new_mechanic.py <area> <behaviour> --id <id> --lane Content --title "<title>" [--step <code>]`
   writes the test `tests/<area>/test_<behaviour>.c` (red until real checks replace the placeholder), its CTest entry
   `duoforge.<area>.<behaviour>` and the doc file `docs/mechanics/<area>/<id>-<slug>.md`. The id comes from the lane's
   block in NUMBERS.md; draw sites and residual kinds only as handed out by the HS (`--draw-site`, `--residual-kind`).
3. **Code** in the area folder of `src/combat/` (`flow`, `mechanics`, `items`, `abilities`, `moves`, `forms`, `field`),
   as a clause at an existing hook where one exists. No new public value outside the block; no heap in the hot path.
4. **Data** in the generator, `tools/datagen/tablegen/<area>.py` (marks, facts checked against the pin); regenerate and
   run `tools/datagen/gen_closure.py --check` in every mode.
5. **Reference battle** against the pin: spec under `tests/reference/specs/`, then `tools/reference/ps_trace.js`,
   `capture_battle_pins.py`, `trace_to_c.py`, `tiebreak_ref.js`, each with its `--check`. A full trace that is too large
   for the repository stays out; the spec, a summary and its SHA-256 go in.
6. **Tests and mutant.** White-box checks in the scaffolded test; revert the fix and show the new test (or battle)
   turns red. Every new refusal gets a case that checks `E_UNSUPPORTED` and the unchanged state.
7. **Counting pins** (pool hash, fingerprints, `UNMODELED_*`, marked count, pool bound) are set as the sum of all merged
   work; after merging `main`, measure them again.
8. **Doc file.** Fill the entry (pin, rules, events, view, evidence, mutants, open gaps) and, if the step has a support
   line, the `## Support` section; then `python3 tools/docs/mechanics_docs.py --write`.

## Testing while building

- Run only what the change touches, by label:
  `ctest --test-dir build -L '^(abilities|data|reference)$'` (or the area of the mechanic, or `-L quick`).
  Seconds to minutes, not the full suite.
- Once before "Review durch": the full local suite, with `-DDUOFORGE_PYTHON=$HOME/df-learn/bin/python` and
  `JAX_PLATFORMS=cpu` (Python tests skip without it), heavy runs through `tools/ci/machine_lock.sh`. Shared pins can
  break tests in other areas; report how many Python tests really ran.
- Do not wait for the hosted CI (about 30 minutes): it is the HS's merge gate. Work on the next entry meanwhile.

## Builders and PRs

- Up to four builders, each in its own worktree on current `main`, with disjoint entries. Builders never push to `main`
  and open no PR; the lane lead integrates into one PR per batch.
- The lead runs a review agent, fixes its findings, and reports "Review durch" to the HS. The HS merges after that and
  green CI, never before.
- A conflict with `main`: merge `main` into the branch (never rebase), re-measure the pins, push.
- New divergences found on the way: an issue with a repro (synthetic teams, no player or match ids), fixed in its own
  small PR, not hidden in a batch.
- Per PR the lead notes entries, start, "Review durch", merge and conflicts (speed measurement since the restructure).
