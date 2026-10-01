# Reference harness (pinned Pokemon Showdown)

Scripts here run against the pinned Showdown checkout (`b2cb775b0616115b775534eaeff50300e1fc81fc`, decision 0004) and turn its behaviour into committed C test data (decision 0006 section 7). CTest never needs Node: the generated files are committed, and the checks below run only when `-DDUOFORGE_PS_REFERENCE_DIR=<checkout>` is set and Node is found.

## `arith_ref.js`

Reference values of the damage and stat arithmetic: `Battle.modify`, `chainModify`, `Battle.randomizer` with a fixed roll, `Dex.trunc` and `Pokemon.calculateStat` on a real Pokemon of the format are called directly. The expressions the reference computes inline (base damage, the critical hit, type and final steps of `modifyDamage`, the accuracy stages) are evaluated with the reference's own `trunc` and cited in the script.

```sh
node tools/reference/arith_ref.js <checkout> > tests/reference/arith_ref.h
node tools/reference/arith_ref.js <checkout> --check tests/reference/arith_ref.h
```

CTest runs the `--check` form as `duoforge.reference.arith` (label `reference`). `duoforge.unit.modifier` compares `src/core/modifier.c` with the committed header.

## `ps_trace.js`

Records a complete battle. A spec (`tests/reference/specs/*.json`) gives the format, a PRNG seed, both teams as Showdown paste text (gender always given) and the choices in request order. The harness runs the battle with a recording PRNG and writes a trace (`tests/reference/traces/*.json`): for every choice entry the draws it caused (site, context, bounds, value), the protocol lines and the state at the next boundary (exact HP, status, stages, PP, volatiles, active slots, requests).

```sh
node tools/reference/ps_trace.js <checkout> tests/reference/specs/s2_turn_core_1.json > tests/reference/traces/s2_turn_core_1.json
node tools/reference/ps_trace.js <checkout> tests/reference/specs/s2_turn_core_1.json --check tests/reference/traces/s2_turn_core_1.json
```

The site of a draw is read from its call stack, the context from the reference's event entry points, which the harness wraps (`queue`, `insert`, `switch-order`, `each:<event>`, `field:<event>`, `event:<event>`, and for random targets `action-speed`, `resolve` or `execute`). A draw it cannot classify is written as `UNKNOWN`; such a trace must not become a fixture. CTest reruns every spec as `duoforge.reference.trace.<name>` (label `reference`). Decision 0006 section 5.1 explains what the families mean for aligning DuoForge with the reference.

## `trace_to_c.py`

Turns every spec and trace into `tests/reference/conformance.h`: the teams in DuoForge ids, the slot commands per step, the expected members (HP, PP, stages, stall counter) and the tape. Draws without effect are dropped by named rules whose preconditions it checks (decision 0006 section 5.1); each step records how many were dropped. Shuffle draws become relative to their group. CTest checks that the committed header is what the script makes of the traces (`duoforge.reference.conformance_tables`).

```sh
python tools/reference/trace_to_c.py .           # write tests/reference/conformance.h
python tools/reference/trace_to_c.py . --check   # compare
```

To add a battle: write a spec (gender for every gendered species, No Ability and no items until those mechanics exist), record its trace with `ps_trace.js`, run `trace_to_c.py`, and raise the battle count in `tests/test_conformance.c`.

The checkout needs `npm ci --ignore-scripts --omit=dev` and `node build` once, so that `dist/sim` exists.
