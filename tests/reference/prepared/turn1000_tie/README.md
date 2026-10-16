# Prepared reference battle: the turn-1000 tie

Not discovered by any test or tool (outside `tests/reference/specs`, `traces` and `battles`). The fix and its plan:
`docs/research/expansion/turn1000-tie.md`.

- `turn1000_tie.json`: the spec (plan mode; both sides switch both slots for 1000 turns).
- `turn1000_tie.summary.json`: what its trace shows at the pin (warning lines, the last two steps, the final state) and
  the trace's sha256. The trace itself (5.3 MB) is not committed; rebuild it:

```sh
node tools/reference/ps_trace.js <pinned checkout> tests/reference/prepared/turn1000_tie/turn1000_tie.json > <outside>/turn1000_tie.trace.json
```

Its sha256 must be the summary's `trace_sha256`. The replay (decision 0015 entry 5dt) converts it with
`trace_to_c.convert_battle` (the pool tables), writes its records with `conformance_records.write_battle` under the data
kind POOL and again under POOL_DEV, and runs them through `duoforge_diff_runner` (tools/difftest): both PASS, 1001 steps.
