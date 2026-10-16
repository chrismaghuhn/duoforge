# Prepared reference battles: a lock holder put to sleep before its locked turn (issue 606)

Not discovered by any test or tool (outside `tests/reference/specs`, `traces`, `battles` and `corpus`). The bug, the
planned fix and its plan: `docs/research/expansion/lockfam-sleep.md`.

Both battles use synthetic test teams (no player or match ids) and only content marked on main: fz_6_175 (lane A
campaign, seed 6, battle 175) with Raging Fury -> Outrage, Petal Dance -> Energy Ball, Double Hit -> Bug Bite,
Thrash -> Wild Charge. None of the replaced moves is used in either battle. Turn 1: Arcanine (p2a) uses Outrage
(LOCK_TURNS draws 2). Turn 2: its ally Milotic puts it to sleep with Hypnosis before it moves (`|cant|p2a: Arcanine|slp`);
the residual ends the lock through its duration and adds `|-start|p2a: Arcanine|confusion|[fatigue]` (one
CONFUSION_TURNS draw).

- `fz_6_175_outrage_main_prefix.json` + `.trace.json`: the 3-step prefix of issue 606 (team preview and two turns).
- `fz_6_175_outrage_main.json` + `.trace.json`: the whole battle (14 steps, `|win|p1`). Turn 3 adds the fatigue
  confusion's first activation (Arcanine wakes, is confused, does not hit itself, and uses Extreme Speed).

Both traces were recorded at the pin (`b2cb775b`, harness 14) and match it:

```sh
node tools/reference/ps_trace.js <pinned checkout> tests/reference/prepared/lockfam_sleep/<name>.json \
    --check tests/reference/prepared/lockfam_sleep/<name>.trace.json
```

## Promotion (with the fix PR, not before: both DIVERGE at step 2 on main)

1. Move each spec to `tests/reference/specs/<name>.json` and its trace to `tests/reference/traces/<name>.json`
   (the trace stores only the spec's file name, so a moved pair still passes `--check`). The HS may rename them to the
   repository's defect naming; a renamed spec must be recorded again (`ps_trace.js`), since the trace holds the name.
2. Convert: `python tools/reference/trace_to_c.py .` (the payloads under `tests/reference/battles/` and the pool
   conformance header), then `--check`.
3. Pins of the new battles only: `tools/reference/capture_battle_pins.py` (with `DUOFORGE_LIBRARY` and
   `DUOFORGE_DIFF_RUNNER` of the fix build, never `--update-existing`), and the format pins and counts that the new pool
   battles move (`tests/reference/pins/reg-mc.json` by hand, each change with its cause).
4. Delete this directory.
