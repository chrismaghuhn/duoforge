# Differential fuzzing against Showdown: design sketch

Read-only study of `f756c8e`; timings are sequential runs on a busy machine (noisy).

## 1. Today

- **`gen_real_specs.py`.** Per real-team pairing it builds 40 candidates (shuffled team order, random plan, derived seed), one Node process each, `cpu_count` (16 here) in parallel. Traces with `UNKNOWN` draws or no result are **discarded, only counted**; greedy coverage keeps 16 (`m5_real_*`). `s13_real_*` (8) predate it.
- **Checking.** `trace_to_c.py` writes `conformance.h`, and `test_conformance.c` replays it with the tape. It compares state, observation and events, but of each request **only the per-slot move masks**.
- **Engine-only.** `closure_gate` and `duoforge_certify` play random battles without the reference.
- **Plan mode.** It repairs choices (target 1, first reserve), which biases play and breaks ally targets (decision 0009 §6.2).

## 2. The missing loop

There are three persistent processes, run in stages without lockstep:

1. **Node worker.** `ps_trace.js` becomes a module with a `--serve` mode. It draws random choices and Showdown judges each one (`side.choose`, `isChoiceDone`, `clearChoice`). Each battle is saved as a normal `choices` spec: reproducible, promotable to a fixture.
2. **Python.** `trace_to_c.py` becomes a library: the same drop rules, typed exceptions, and `--check` stays identical. Keep it as the one implementation:
   - a C port would duplicate 900 lines of parsing;
   - a Node port would split the converter or make CTest need Node.
3. **C runner.** White-box; creates TEAM_C(_DEV) battles, steps with the tape, and uses the comparators moved out of `test_conformance.c`.

**Legality.** Showdown chooses. The engine's candidate set is compared with Showdown's accepted set, translated by `convert_choice`. Factorized trial validation (slot 0, slot 1 behind a plain move, then the product) matched brute force on 210 requests and left the battles unchanged. It costs 0.8–6 ms per request, so sample it.

**Drop rules.** Under random play they still raise on anything unknown, e.g. `each:` ties between holders other than Sitrus Berry and Grassy Seed, or ModifyDamage ties beyond screens and Life Orb with Chople Berry. Keep them strict, but bucket each battle: PASS, DIVERGENCE, ORACLE_GAP (rule plus signature), UNSUPPORTED, REF_ERROR or CAP. Never discard a battle or relax a rule. Expect many gaps at first.

**First divergence.** The report gives:
- the spec, step, turn and boundary;
- the engine's requested site and bounds at the tape position (needs a test-only `dfi_draws` field, since a mismatch is an opaque `E_INVARIANT` today);
- the state and event diffs, the protocol lines and the draws with their drop reasons;
- the prefix spec as the reproducer.

**A latent translation gap.** `convert_choice` detects Struggle only when every PP is 0, but both sides also give Struggle when the only move with PP is a disabled Fake Out.

## 3. Reference throughput (measured)

|Spec|Steps|Draws|New process (median of 3)|Warm, recorded (median of 11)|Warm, plain|
|---|---|---|---|---|---|
|s2_turn_core_1|4|17|0.66 s|11 ms|9 ms|
|c05_helmet_order|28|283|0.63 s|55 ms|32 ms|
|m5_real_ab_4|33|259|0.94 s|86 ms|67 ms|
|m5_real_bb_1|27|597|0.75 s|116 ms|50 ms|
|s3_struggle_end|27|925|0.72 s|114 ms|34 ms|

- **One process per battle.** 0.4 s goes to startup and the format load, so about 1.1–1.6 battles/s per core.
- **Persistent worker.** 2.0–4.3 ms per step, so 9–12 battles/s per core. Recording costs 1.3–3.4× the plain simulation and grows with the draw count.
- **Converter.** All 108 traces convert in 0.64 s.
- The reference is about 1000× slower than the engine (owner's figure: ~10k/s). Traces are 30–330 KB; stream them.

## 4. Coverage and steering

- **From traces:**
  - line kind × effect (`[from]`, `[of]`, `-activate`, `cant`);
  - draw site × context × disposition (kept, or the dropping rule) × outcome;
  - request situations.
- **From the engine:** event kind × cause, boundaries, domain sizes.
- **Per manifest entry** (45 moves, 19 abilities, 14 items, 3 flags): brought versus fired. Silent modifiers (Mystic Water, Tough Claws, Prankster) need test-only probe counters in a caller-provided struct. Clang coverage of `turn.c` is the zero-code alternative.
- **Steering:**
  - weights of 1/(1+fired), with one focus mechanic per battle;
  - pairs of mechanics that never fired together;
  - a speed-tie mode that uses the engine's own stats;
  - weighted choices;
  - a greedy-coverage corpus;
  - an optional steered PRNG (in-bounds values, recorded in the spec).
- **Unsupported mechanics.** Reference-only campaigns over the full pool rank their gaps.

## 5. Mutation testing

`tools/mutate/` makes seeded mutants of the mechanic functions in `turn.c`, `request.c` and `modifier.c`: relational and boolean flips, modifier constants, deleted or swapped handler calls, early returns. Each mutant builds in its own worktree and build directory (never `build/`) and runs both conformance tests plus a frozen fuzz corpus. A survivor is either documented as equivalent or targeted until a battle kills it, and that battle is committed. Disabling any drop rule must also fail a committed battle. The score with versus without the corpus measures what fuzzing adds.

## 6. Components, order, blockers, risks

|#|Component|Effort|
|---|---|---|
|1|Worker (the 108 traces stay identical)|S|
|2|Converter library|M|
|3|Comparators, runner, domain check, draw diagnostics|M–L|
|4|Driver and buckets; must replay all 108 committed battles without divergence|M|
|5|Team generator (pool exported by the runner), choice policy|M|
|6|Coverage report (probes add M)|M|
|7|Minimizer, promotion to fixtures|M|
|8|Frozen corpus in CTest|S–M|
|9|Mutation runner|M|
|10|Steering|M–L|

**Order:** 1–4, then 5–7. Run 9 after 3 for a baseline; 8 and 10 come last.

**Blockers:**
- The machine is shared with the performance session.
- The Team C session edits the same files.
- `HARNESS_VERSION` stays 14.
- The owner decides where the corpus is stored.
- Eight mechanics are still unsupported.

**Risks:**
- A flood of oracle gaps.
- Translation bugs posing as divergences.
- Switch-heavy uniform choices, and rare Speed ties.
- Long battles.
- Worker determinism (record Node version and build).
