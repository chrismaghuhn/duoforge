# Task: M2 — Requests, joint commands and the information boundary

## Starting point

- **M1 is complete.** Deterministic primitives and owned state are in `docs/decisions/0001`–`0003` and `tasks/M1_DETERMINISTIC_PRIMITIVES.md`; the last commit on branch `chris/practical-thompson-xasnox` is green in CI (Linux GCC/Clang, ASan/UBSan, MSVC x64/Win32).
  - If M1 is not yet merged into `main`, base your work on that branch.
- **Owner decisions** (`docs/decisions/0004`):
  - rules basis **Pokémon Champions**, format `[Gen 9 Champions] VGC 2026 Reg M-C`;
  - **Mega Evolution is the only special mechanic** (no Tera, Z or Dynamax);
  - Showdown pinned at `b2cb775b0616115b775534eaeff50300e1fc81fc`;
  - two fixed teams.
- **Unverified research drafts** are in `docs/research/`. `champions-reg-mc-report-draft.md` §3 covers M2. Verify each point before use.

## Budget rule (owner, 2026-09-30)

- The owner's credit is limited. **Do not use subagents or workflows unless the owner explicitly asks.**
- Work efficiently:
  - read files selectively;
  - do not dump large files in full;
  - keep command output short;
  - write your own plan briefly rather than elaborately.

## Read first

- `AGENTS.md`
- `docs/ROADMAP.md` (M2 and the note before M3)
- `docs/DECISION_CONTRACT.md` (**entire document; it is the main contract for M2**)
- `docs/ARCHITECTURE.md` §4, §5, §7, §9
- `docs/decisions/0002` (especially §1 atomicity and privileged operations, and **§9 constraints for M2**)
- `docs/TESTING_AND_BENCHMARKS.md` (information-boundary tests)
- The existing code in `include/`, `src/` and `tests/` (style, fixtures, oracle model in `tools/state_model/`)

## Pinned reference (when you need Showdown facts)

```sh
git clone --filter=blob:none --no-checkout https://github.com/smogon/pokemon-showdown.git ps
git -C ps checkout b2cb775b0616115b775534eaeff50300e1fc81fc -- sim/side.ts sim/battle.ts data/rulesets.ts data/moves.ts data/mods/champions
```

Cite `path:line` at this commit for every rule you take from it. Vendor no Showdown code.

## Scope

Implement M2 only. There is **no combat**: damage, move effects, PP consumption, switch execution and Mega effects are M3/M4.

Use explicitly **SYNTHETIC** fixtures wherever combat is not yet available.

1. **Boundaries.**
   - A `boundary_kind`: at least TEAM_SELECTION and TURN.
   - Represent mid-turn REPLACEMENT/PIVOT boundaries only structurally (for synthetic fixtures). Keep in mind that the Champions research reports **pivots on both sides at once**, for example Emergency Exit together with an opposing Eject Button.
   - A request epoch: u32, strictly increasing, with `E_EXHAUSTED` instead of wrapping. A stale epoch is malformed input.
2. **Team selection (Reg M-C).**
   - From 6 registered, pick an **ordered 4**; the first two are the leads.
   - Duplicate or out-of-range picks are not in the domain.
   - Enumerating all ordered 4-tuples (360 for 6) is the safe superset: bench order matters only with Illusion. Document the decision.
   - M1's synthetic `brought_mask`/`leads` setup path becomes a test-fixture path or is removed (a semantics bump).
3. **Turn command per active slot.**
   - MOVE (move slot, target selector) with an optional **Mega declaration**; SWITCH (reserve); forced no-action for an empty or fainted slot only where the profile says so.
   - **Joint side choices, completely enumerated in a documented deterministic order.**
   - No two switches to the same reserve.
   - At most **one Mega declaration per side per choice**, and only once per battle per side (a side-wide flag in the state). Only for a holder of a matching stone, which in M2 is a **synthetic** flag in the setup/context. Never on a switch.
   - A move with pp 0 is not selectable. Struggle is M3; an all-pp-0 request is represented only structurally.
4. **Target selectors.**
   - The context schema v2 gets a synthetic move table with a **target class** per move.
   - Take the target classes of the moves in both teams from `data/moves.ts` at the pin; the synthetic table may mirror them.
   - A selectable target is **not** a resolved target: no redirection, no pre-resolution (DECISION_CONTRACT §3).
5. **Simultaneous choices.**
   - Both sides' responses arrive in one decision bundle, or through a host collector that never changes combat state.
   - Sealed commitments are stored in the state wherever re-prompts would need them.
   - **One player's choice must never be visible to the other player.**
6. **Honest execution.**
   - A valid TEAM_SELECTION bundle may perform the transition to TURN; it is mechanics-free.
   - A valid TURN bundle can **not** be executed in M2. Return an explicit, documented unsupported/not-implemented status **atomically**, with no mutation. **No fake success.**
7. **Observation prototype (perspective-safe).**
   - Knowledge state per player.
   - Open team sheets (verify against the pin): species/forme, item, ability, moves and nature of all 6 are open; **Stat Points and IVs never**.
   - Gender: owner decision, currently open. Pick a default and document it.
   - The brought four and their order stay private until sent into battle.
   - HP: own side exact; opponent according to the profile (floor percent, minimum 1; verify).
   - Tagged unknowns rather than zero values.
8. **Output convention.** Resolve the open decision on variable-size outputs (required-size out-param vs. size query vs. context maximum). The information-safety rules of 0002 §9 apply: sizes, counts, order and statuses must not reveal hidden information.
9. **State schema v2 / semantics 2.**
   - The v1 goldens become "rejected: schema 1" tests.
   - Extend the oracle model `tools/state_model/` to v2 **and** to domain enumeration (independent expectations).
   - Keep the M1 coding rules, lint and CI.

## Required tests (independent expectations, finite, with timeouts)

- **Exhaustive domain tests** on small synthetic fixtures, against the Python oracle: counts, order and completeness.
- **Stable enumeration:** enumerating twice gives the same bytes.
- **Queries are pure:** request and enumeration consume **zero** RNG (`rng.draws` unchanged) and mutate nothing.
- **Information equivalence:** paired states with the same authorized information and different hidden information give identical requests, candidates, observations, **statuses and sizes**.
- **Malformed-input atomicity**, tested **separately** from rule-authorized rejection (DECISION_CONTRACT §6). No mechanic triggers the latter yet, so model it structurally and test it as its own category.
- **Contract minimum tests:** stale and late responses, two-side replacement, one-side pivot continuation, and a snapshot at every exposed boundary kind.
- **Negative controls:** for each important guarantee, deliberately break the code once and confirm the test goes red.

## Verification

- GCC and Clang, Debug and Release, with `-DDUOFORGE_WARNINGS_AS_ERRORS=ON`.
- The GCC sanitizer build (`cmake --preset sanitize`).
- Hosted CI green, including MSVC. MSVC's C mode has **no `max_align_t`**; watch `/W4 /WX`.
- Report PASS/FAIL/NOT_RUN/BLOCKED/SKIPPED with commands and times. Hosted CI counts as PASS only once a run has been observed.

## Git

- Commit and push each slice to the session branch, based on the M1 branch.
- Commit messages end with the session attribution.
- Open a PR only if the owner asks.

## Deliverables

- Code and tests.
- A decision note `docs/decisions/0005-...` covering requests, commands, the information profile, the output convention and schema v2.
- Updated docs: README, `docs/support/README.md`, `docs/OPEN_DECISIONS.md`.

## Stop

**Stop after M2** and report: changed files, scope, tests run and not run, open points, and the proposed next step.

The next step is **not** to start M3 on your own. First the mechanics inventory must be completed (`docs/research/README.md`).
