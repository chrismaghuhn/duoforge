# Report template for runs (restructure step 8)

Copy this file to `docs/benchmarks/<date>-<name>/README.md` and replace every placeholder. A report holds aggregates
only: no weights, checkpoints, run directories, live logs, match ids or user ids (AGENTS.md). The run's own outputs,
with its `manifest.json` (`duoforge.runs`), stay in `$DUOFORGE_RUNS/<kind>/<date>-<name>/`, outside the repository.

```markdown
# <What was measured, in one line> (<issue or PR>, <date>)

**Question.** <The one question the run answers.>

**Answer.** <Yes / no / inconclusive, with the headline number and its interval.>

## Setup

- **Tool:** `python -m <module> <arguments>` (the full command line, with private paths shortened to DIR, RUN, ...).
- **Code:** commit `<manifest code.commit>`, dirty `<manifest code.dirty>`.
- **Inputs:** <checkpoints by name and SHA-256, team pool and seed, data kind; never the files themselves>.
- **Machine:** <manifest machine: system, processors, Python; GPU or CPU; alone (machine_lock.sh --exclusive) or shared>.
- **Run:** <manifest start and end, games or iterations planned and done>.

## Gates (predeclared) and results

<Every gate fixed before the run, with where it was declared (issue, PR, decision note) and when.>

| gate | rule | result |
|---|---|---|
| <name> | <the rule as declared> | <value and pass/fail> |

## Provenance

- Manifest fields: kind, tool, argv, seeds, code, machine, start, end (copy them; aggregates only).
- <Anything added or decided after the run started, marked as such with its time.>

## What this shows and what it does not

- Shows: <...>
- Does not show: <...>
```
